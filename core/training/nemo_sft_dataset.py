"""
ZeroWall — NeMo SFT Dataset Builder (instruction → ranked-JSON pairs)
====================================================================
Turns the *real defense-cycle outcomes* (training_data/feedback.jsonl, the same
corpus the MLP policy trains on) into supervised fine-tuning examples for a
NeMo-fine-tuned Mutation Planner LLM.

WHY AN LLM PLANNER (vs the MLP in train.py):
    The MLP regresses a fixed-width one-hot context to per-transform scores. It
    works, but it cannot read free-form attack context (a novel payload string,
    a header anomaly, an attacker note) and it cannot explain itself. The
    fine-tuned LLM is trained to (a) read arbitrary attack context and (b) emit
    the SAME structured, ranked JSON contract the safe transform engine consumes
    — with a short rationale per transform. The MLP/Triton/deterministic tiers
    remain as the safety net (see MutationAgent cascade).

Each SFT example is grounded, not synthetic:
    input  = an instruction describing the attack + the legal transform menu
    output = the ranked JSON plan whose confidences ARE the observed mean
             effectiveness of each transform for that attack context.

NeMo's SFT/LoRA data format is JSONL with {"input": ..., "output": ...} records
(this is what `nemo.collections.llm` SFT recipes expect). We also write a
`prompt_template.txt` so serving uses the exact same prompt the model saw.

Usage:
    python -m core.training.nemo_sft_dataset \
        --feedback training_data/feedback.jsonl \
        --out training_data/nemo_sft
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List

from core.training.dataset_builder import build_dataset
from core.training.features import TRANSFORMS

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("zerowall.nemo_sft")

DEFAULT_OUT_DIR = Path(__file__).parent.parent.parent / "training_data" / "nemo_sft"

# The instruction the model is fine-tuned (and served) with. Kept in ONE place
# and written next to the data so train/serve prompts never drift.
SYSTEM_INSTRUCTION = (
    "You are ZeroWall's Mutation Planner. Given a detected attack on a FastAPI "
    "service, choose which behavior-preserving code transforms are most likely "
    "to neutralize the exploit while keeping all tests passing. You do NOT write "
    "code — you only rank transform TYPES. Respond with STRICT JSON and nothing "
    "else, in the form: "
    '{"plan": [{"transform": <name>, "confidence": <0..1>, "rationale": <short>}]}. '
    "Only use transforms from the provided menu. Rank most→least effective."
)

PROMPT_TEMPLATE = (
    "{system}\n\n"
    "Attack context:\n"
    "- endpoint: {endpoint}\n"
    "- payload_type: {payload_type}\n"
    "- detail: {detail}\n\n"
    "Transform menu (legal values): {menu}\n\n"
    "Return the ranked JSON plan now:"
)

# A little natural-language colour per payload type so the model learns to read
# free-form detail, not just the categorical label. These are descriptive only.
_DETAIL_BANK = {
    "path-traversal": [
        "request path contains ../ sequences trying to escape the data dir",
        "GET /data?file=../../etc/passwd style traversal attempt",
        "encoded ..%2f segments aimed at reading host files",
    ],
    "command-injection": [
        "query parameter smuggling ; rm -rf style shell metacharacters",
        "input with $(...) and backtick substitution reaching a subprocess",
        "pipe and semicolon chained commands in the run payload",
    ],
    "sql-injection": [
        "' OR '1'='1 style boolean bypass in the search term",
        "UNION SELECT probing the search query parameter",
        "stacked query attempt with a trailing comment --",
    ],
    "unknown": [
        "anomalous payload that does not match a known signature",
        "novel input pattern flagged by the behavioral detector",
    ],
}


def _detail_for(payload_type: str, rng: random.Random) -> str:
    bank = _DETAIL_BANK.get(payload_type, _DETAIL_BANK["unknown"])
    return rng.choice(bank)


def _build_completion(scores: Dict[str, float]) -> str:
    """Ranked JSON plan whose confidences are observed effectiveness."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    plan = [
        {
            "transform": t,
            "confidence": round(float(c), 3),
            "rationale": _rationale_for(t, c),
        }
        for t, c in ranked
    ]
    return json.dumps({"plan": plan}, separators=(",", ":"))


def _rationale_for(transform: str, conf: float) -> str:
    base = {
        "swap_validators": "hardens the vulnerable input path directly",
        "route_rotation": "breaks hardcoded exploit paths",
        "rename_identifiers": "defeats templated/signature exploits",
        "reorder_blocks": "structural shuffle, low direct impact",
        "split_helpers": "minor structural variation",
    }.get(transform, "behavior-preserving transform")
    strength = "high" if conf >= 0.66 else "moderate" if conf >= 0.33 else "low"
    return f"{base} ({strength} observed effectiveness)"


def build_sft_examples(
    feedback_path: Path | None,
    augment: int = 3,
    seed: int = 0,
) -> List[Dict[str, str]]:
    """One SFT pair per (context, paraphrase). `augment` paraphrases per context
    teach the model to read varied free-form `detail` strings for the same
    underlying attack class."""
    ds = build_dataset(feedback_path)
    if len(ds) == 0:
        raise SystemExit(
            "[nemo_sft] no feedback data — run self-play first "
            "(python -m core.training.selfplay)"
        )

    menu = ", ".join(TRANSFORMS)
    rng = random.Random(seed)
    examples: List[Dict[str, str]] = []

    for row, ctx in enumerate(ds.contexts):
        scores = {TRANSFORMS[i]: float(ds.Y[row, i]) for i in range(len(TRANSFORMS))}
        completion = _build_completion(scores)
        for _ in range(max(1, augment)):
            prompt = PROMPT_TEMPLATE.format(
                system=SYSTEM_INSTRUCTION,
                endpoint=ctx["endpoint"],
                payload_type=ctx["payload_type"],
                detail=_detail_for(ctx["payload_type"], rng),
                menu=menu,
            )
            examples.append({"input": prompt, "output": completion})

    rng.shuffle(examples)
    logger.info(
        "[nemo_sft] %d contexts × %d paraphrases -> %d SFT examples (%s)",
        len(ds), augment, len(examples), ds.backend,
    )
    return examples


def write_dataset(
    examples: List[Dict[str, str]],
    out_dir: Path,
    val_frac: float = 0.15,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n_val = max(1, int(len(examples) * val_frac)) if len(examples) > 4 else 0
    val, train = examples[:n_val], examples[n_val:]

    train_path = out_dir / "training.jsonl"
    val_path = out_dir / "validation.jsonl"
    with open(train_path, "w") as f:
        for ex in train:
            f.write(json.dumps(ex) + "\n")
    with open(val_path, "w") as f:
        for ex in val:
            f.write(json.dumps(ex) + "\n")

    (out_dir / "prompt_template.txt").write_text(PROMPT_TEMPLATE)
    (out_dir / "system_instruction.txt").write_text(SYSTEM_INSTRUCTION)

    manifest = {
        "n_train": len(train),
        "n_val": len(val),
        "transforms": TRANSFORMS,
        "format": "nemo-sft-jsonl (input/output)",
        "train_file": str(train_path),
        "val_file": str(val_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    logger.info(
        "[nemo_sft] wrote %d train / %d val -> %s", len(train), len(val), out_dir
    )
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Build ZeroWall NeMo SFT dataset")
    ap.add_argument("--feedback", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--augment", type=int, default=4, help="paraphrases per context")
    ap.add_argument("--val-frac", type=float, default=0.15)
    args = ap.parse_args()

    examples = build_sft_examples(args.feedback, augment=args.augment)
    write_dataset(examples, args.out, val_frac=args.val_frac)


if __name__ == "__main__":
    main()
