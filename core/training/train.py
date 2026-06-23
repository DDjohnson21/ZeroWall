"""
ZeroWall — Mutation Planner Training (PyTorch, DGX Spark GPU)
============================================================
Trains the Mutation Planner policy on real defense-cycle outcomes and exports
lightweight NumPy weights for host-side serving (see planner_policy.py).

Design:
  * Input  : one-hot attack context (payload_type, endpoint)   [FEATURE_DIM]
  * Output : effectiveness score per transform in [0,1]         [LABEL_DIM]
  * Loss   : support-weighted BCE — contexts seen more often count more.

Run on the DGX Spark GPU inside the NVIDIA PyTorch container:
    docker run --rm --gpus all -v "$PWD":/work -w /work \
        nvcr.io/nvidia/pytorch:24.12-py3 \
        python -m core.training.train --epochs 4000

It auto-selects CUDA when available and falls back to CPU otherwise, so the
loop is demonstrable off-GPU while the real training uses the GB10.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np

from core.training.dataset_builder import build_dataset
from core.training.features import FEATURE_DIM, LABEL_DIM, TRANSFORMS
from core.training.planner_policy import DEFAULT_MODEL_DIR, WEIGHTS_FILE, META_FILE

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("zerowall.train")


def train(
    feedback_path: Path | None,
    out_dir: Path,
    epochs: int = 4000,
    hidden: int = 16,
    lr: float = 0.02,
    seed: int = 0,
) -> dict:
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dev_name = torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu"
    logger.info(f"[train] device={device} ({dev_name})")

    ds = build_dataset(feedback_path)
    if len(ds) == 0:
        raise SystemExit(
            "[train] no training data — run self-play first "
            "(python -m core.training.selfplay)"
        )
    logger.info(
        f"[train] dataset: {ds.n_examples} examples -> {len(ds)} contexts "
        f"({ds.backend}) feature_dim={FEATURE_DIM} label_dim={LABEL_DIM}"
    )

    X = torch.tensor(ds.X, dtype=torch.float32, device=device)
    Y = torch.tensor(ds.Y, dtype=torch.float32, device=device)
    # Normalise support into per-row weights (>=1 so every context counts).
    w = ds.W.copy()
    w = np.where(w <= 0, 1.0, w)
    W = torch.tensor((w / w.mean()).reshape(-1, 1), dtype=torch.float32, device=device)

    model = nn.Sequential(
        nn.Linear(FEATURE_DIM, hidden),
        nn.ReLU(),
        nn.Linear(hidden, LABEL_DIM),
        nn.Sigmoid(),
    ).to(device)

    opt = torch.optim.Adam(model.parameters(), lr=lr)
    bce = nn.BCELoss(reduction="none")

    model.train()
    t0 = time.time()
    final_loss = 0.0
    for epoch in range(epochs):
        opt.zero_grad()
        pred = model(X)
        loss = (bce(pred, Y) * W).mean()
        loss.backward()
        opt.step()
        final_loss = float(loss.item())
        if (epoch + 1) % max(1, epochs // 5) == 0:
            logger.info(f"[train] epoch {epoch+1}/{epochs}  loss={final_loss:.5f}")
    train_s = time.time() - t0

    # Export weights as NumPy for the host-side (torch-free) serving path.
    lin1, lin2 = model[0], model[2]
    W1 = lin1.weight.detach().cpu().numpy().T.astype(np.float32)  # (FEATURE_DIM, hidden)
    b1 = lin1.bias.detach().cpu().numpy().astype(np.float32)
    W2 = lin2.weight.detach().cpu().numpy().T.astype(np.float32)  # (hidden, LABEL_DIM)
    b2 = lin2.bias.detach().cpu().numpy().astype(np.float32)

    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(out_dir / WEIGHTS_FILE, W1=W1, b1=b1, W2=W2, b2=b2)

    # Also publish the trained weights into the Triton model repo so the
    # Triton-served mutation-planner (cascade tier-3) runs THIS policy, not a
    # hardcoded prior. This is the on-device "train → serve" handoff.
    triton_dir = (
        Path(__file__).parent.parent.parent
        / "inference" / "triton-model-repo" / "mutation-planner" / "1"
    )
    if triton_dir.exists():
        np.savez(triton_dir / WEIGHTS_FILE, W1=W1, b1=b1, W2=W2, b2=b2)
        logger.info("[train] published Triton weights -> %s/%s", triton_dir, WEIGHTS_FILE)

    # A human-readable view of what the model learned, per context.
    model.eval()
    with torch.no_grad():
        learned = model(X).cpu().numpy()
    learned_view = {
        f"{c['payload_type']}|{c['endpoint']}": {
            TRANSFORMS[i]: round(float(learned[r, i]), 3) for i in range(LABEL_DIM)
        }
        for r, c in enumerate(ds.contexts)
    }

    meta = {
        "version": "v1",
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "train_backend": dev_name,
        "device": device.type,
        "n_examples": ds.n_examples,
        "n_contexts": len(ds),
        "dataset_backend": ds.backend,
        "transforms": TRANSFORMS,
        "feature_dim": FEATURE_DIM,
        "label_dim": LABEL_DIM,
        "hidden": hidden,
        "epochs": epochs,
        "final_loss": round(final_loss, 6),
        "train_seconds": round(train_s, 3),
        "learned_effectiveness": learned_view,
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, indent=2))
    logger.info(
        f"[train] ✅ exported weights -> {out_dir}/{WEIGHTS_FILE} "
        f"(loss={final_loss:.5f}, {train_s:.2f}s on {dev_name})"
    )
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Train ZeroWall Mutation Planner")
    ap.add_argument("--feedback", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_MODEL_DIR)
    ap.add_argument("--epochs", type=int, default=4000)
    ap.add_argument("--hidden", type=int, default=16)
    ap.add_argument("--lr", type=float, default=0.02)
    args = ap.parse_args()
    train(args.feedback, args.out, epochs=args.epochs, hidden=args.hidden, lr=args.lr)


if __name__ == "__main__":
    main()
