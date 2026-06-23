"""
ZeroWall — NeMo LoRA Fine-Tuning of the Mutation Planner LLM
===========================================================
Supervised fine-tuning (SFT) of a small base LLM with a LoRA adapter, using the
NeMo Framework, so the Mutation Planner learns to emit ZeroWall's ranked-JSON
plan from real defense-cycle outcomes. This is the tier-1 planner the cascade
calls first (NeMo → learned MLP → Triton → deterministic).

This file is import-safe WITHOUT NeMo installed (so the repo loads + `--help`
works on a CPU dev box), but ACTUAL TRAINING requires the NVIDIA NeMo container
and a DGX Spark GPU. Run it like:

    # 1) build the SFT data (CPU, fast)
    python -m core.training.nemo_sft_dataset --out training_data/nemo_sft

    # 2) fine-tune with LoRA inside the NeMo container (DGX Spark GPU)
    docker run --rm --gpus all --ipc=host \
        -v "$PWD":/work -w /work \
        nvcr.io/nvidia/nemo:24.12 \
        python -m core.training.nemo_finetune \
            --base-model meta-llama/Llama-3.2-1B-Instruct \
            --data-dir training_data/nemo_sft \
            --out artifacts/models/planner-llm \
            --max-steps 200

    # 3) serve the LoRA adapter (vLLM, OpenAI-compatible) — see
    #    inference/clients/nemo_planner_client.py for the serving contract.
    vllm serve <merged-or-base> --enable-lora \
        --lora-modules zerowall-planner=artifacts/models/planner-llm

Design choices that make this DGX-worthy (not a cloud-API call):
  * LoRA (PEFT) keeps the trainable footprint tiny so the GB10 can fine-tune AND
    serve in the same loop — the "gets smarter under sustained attack" thesis.
  * The data is generated on-device by RAPIDS from live telemetry, fine-tuned by
    NeMo, served by vLLM/TRT-LLM — all local, no cloud round-trip.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("zerowall.nemo_finetune")

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "training_data" / "nemo_sft"
DEFAULT_OUT_DIR = Path(__file__).parent.parent.parent / "artifacts" / "models" / "planner-llm"


def _require_nemo():
    """Import NeMo lazily with a clear, actionable error off-GPU."""
    try:
        import torch  # noqa: F401
        from nemo.collections import llm  # noqa: F401
        from nemo.collections.llm.peft import LoRA  # noqa: F401
        import nemo_run as run  # noqa: F401
    except Exception as e:  # pragma: no cover - exercised only in the container
        raise SystemExit(
            "[nemo_finetune] NeMo is not available in this environment.\n"
            "  This step runs inside the NVIDIA NeMo container on the DGX Spark "
            "GPU.\n  See the module docstring for the exact `docker run ... "
            "nvcr.io/nvidia/nemo` command.\n"
            f"  (import error: {e})"
        )


def finetune(
    base_model: str,
    data_dir: Path,
    out_dir: Path,
    max_steps: int = 200,
    lora_dim: int = 16,
    lr: float = 1e-4,
    micro_batch_size: int = 1,
    global_batch_size: int = 8,
    seq_length: int = 1024,
) -> dict:
    """Run NeMo SFT with a LoRA adapter. Requires the NeMo container + GPU."""
    _require_nemo()

    import torch
    import nemo_run as run
    from nemo.collections import llm
    from nemo.collections.llm.peft import LoRA

    train_file = data_dir / "training.jsonl"
    val_file = data_dir / "validation.jsonl"
    if not train_file.exists():
        raise SystemExit(
            f"[nemo_finetune] {train_file} missing — run "
            f"`python -m core.training.nemo_sft_dataset` first."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("[nemo_finetune] base=%s steps=%d lora_dim=%d", base_model, max_steps, lora_dim)

    # ── Data: NeMo fine-tuning data module over our input/output JSONL ───────
    data = llm.FineTuningDataModule(
        dataset_root=str(data_dir),
        seq_length=seq_length,
        micro_batch_size=micro_batch_size,
        global_batch_size=global_batch_size,
    )

    # ── Model: import the base checkpoint into NeMo, attach a LoRA adapter ───
    model = llm.HFAutoModelForCausalLM(model_name=base_model)
    lora = LoRA(
        target_modules=["linear_qkv", "linear_proj", "linear_fc1", "linear_fc2"],
        dim=lora_dim,
    )

    # ── Optim + trainer: short SFT run; bf16 on the GB10 ─────────────────────
    optim = llm.adam.pytorch_adam_with_cosine_annealing(max_lr=lr)
    trainer = run.Config(
        "nemo.lightning.Trainer",
        max_steps=max_steps,
        accelerator="gpu",
        devices=1,
        precision="bf16-mixed",
        log_every_n_steps=10,
        val_check_interval=max(10, max_steps // 4),
    )

    logger.info("[nemo_finetune] launching SFT+LoRA ...")
    llm.finetune(
        model=model,
        data=data,
        trainer=trainer,
        peft=lora,
        optim=optim,
        log=run.Config("nemo.lightning.NeMoLogger", log_dir=str(out_dir)),
    )

    meta = {
        "kind": "nemo-lora-sft",
        "base_model": base_model,
        "lora_dim": lora_dim,
        "max_steps": max_steps,
        "seq_length": seq_length,
        "data_dir": str(data_dir),
        "adapter_dir": str(out_dir),
        "serving": "vllm --enable-lora (OpenAI-compatible) or TRT-LLM",
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    }
    (out_dir / "planner_llm_meta.json").write_text(json.dumps(meta, indent=2))
    logger.info("[nemo_finetune] ✅ adapter + meta -> %s", out_dir)
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="NeMo LoRA fine-tune the Mutation Planner LLM")
    ap.add_argument("--base-model", default="meta-llama/Llama-3.2-1B-Instruct")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--max-steps", type=int, default=200)
    ap.add_argument("--lora-dim", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    args = ap.parse_args()
    finetune(
        base_model=args.base_model,
        data_dir=args.data_dir,
        out_dir=args.out,
        max_steps=args.max_steps,
        lora_dim=args.lora_dim,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
