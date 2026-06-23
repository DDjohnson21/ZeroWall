"""
ZeroWall — Risk Scorer Training (logistic regression on real outcomes)
=====================================================================
Trains the deployment risk model the Risk Agent / Triton risk-scorer use to
decide whether a candidate is safe to hot-swap. Like the Mutation Planner, it
learns from the SAME real defense-cycle feedback log — so risk scoring is
data-driven, not a hand-tuned constant formula.

Model:
    features = [security_score, correctness_score]      (both in [0,1])
        security_score    = 1 - exploit_success_rate    (did it block the attack)
        correctness_score = tests passed?               (did it stay functional)
    target   = label (1 if the candidate was actually effective AND safe)
    head     = logistic regression  P(deploy-worthy) = sigmoid(w·x + b)

Exports `risk.npz` to BOTH the host artifacts dir and the Triton model repo, so
the Triton-served risk-scorer runs these trained weights (real served model).

Usage:
    python -m core.training.train_risk --epochs 3000
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

from core.training.feedback import DEFAULT_FEEDBACK_PATH

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("zerowall.train_risk")

ARTIFACT_DIR = Path(__file__).parent.parent.parent / "artifacts" / "models" / "risk"
TRITON_DIR = (
    Path(__file__).parent.parent.parent
    / "inference" / "triton-model-repo" / "risk-scorer" / "1"
)
WEIGHTS_FILE = "risk.npz"
META_FILE = "risk_meta.json"
FEATURES = ["security_score", "correctness_score"]


def _load_xy(feedback_path: Path) -> Tuple[np.ndarray, np.ndarray, int]:
    X: List[List[float]] = []
    y: List[float] = []
    if not feedback_path.exists():
        return np.zeros((0, 2), np.float32), np.zeros((0,), np.float32), 0
    with open(feedback_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            security = 1.0 - float(r.get("exploit_success_rate", 1.0))
            correctness = 1.0 if bool(r.get("verifier_pass", False)) else 0.0
            X.append([security, correctness])
            y.append(float(r.get("label", 0.0)))
    return np.asarray(X, np.float32), np.asarray(y, np.float32), len(y)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def train(feedback_path: Path | None, epochs: int = 3000, lr: float = 0.1, seed: int = 0) -> dict:
    path = feedback_path or DEFAULT_FEEDBACK_PATH
    X, y, n = _load_xy(path)
    if n == 0:
        raise SystemExit(
            "[train_risk] no feedback data — run self-play first "
            "(python -m core.training.selfplay)"
        )

    rng = np.random.default_rng(seed)
    w = rng.normal(0, 0.01, size=X.shape[1]).astype(np.float32)
    b = np.float32(0.0)

    t0 = time.time()
    loss = 0.0
    for epoch in range(epochs):
        z = X @ w + b
        p = _sigmoid(z)
        grad_z = (p - y) / n
        gw = X.T @ grad_z
        gb = float(np.sum(grad_z))
        w -= lr * gw
        b -= lr * gb
        eps = 1e-7
        loss = float(-np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
        if (epoch + 1) % max(1, epochs // 5) == 0:
            logger.info("[train_risk] epoch %d/%d loss=%.5f", epoch + 1, epochs, loss)
    train_s = time.time() - t0

    # Accuracy at 0.5 threshold (sanity).
    acc = float(np.mean((_sigmoid(X @ w + b) >= 0.5).astype(np.float32) == y))

    wrote_to = []
    for d in (ARTIFACT_DIR, TRITON_DIR):
        if d is TRITON_DIR and not d.exists():
            continue
        try:
            d.mkdir(parents=True, exist_ok=True)
            np.savez(d / WEIGHTS_FILE, w=w.astype(np.float32), b=np.float32(b))
            wrote_to.append(str(d))
        except OSError as e:
            logger.warning("[train_risk] could not write %s (%s) — skipping", d, e)

    meta = {
        "version": "v1",
        "kind": "logistic-regression",
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "features": FEATURES,
        "n_examples": n,
        "epochs": epochs,
        "final_loss": round(loss, 6),
        "train_accuracy": round(acc, 4),
        "train_seconds": round(train_s, 3),
        "weights": {"security_score": float(w[0]), "correctness_score": float(w[1]), "bias": float(b)},
    }
    for d in (ARTIFACT_DIR, TRITON_DIR):
        try:
            if d.exists():
                (d / META_FILE).write_text(json.dumps(meta, indent=2))
        except OSError:
            pass
    logger.info(
        "[train_risk] ✅ exported risk model (loss=%.5f, acc=%.2f, n=%d) -> %s",
        loss, acc, n, ARTIFACT_DIR,
    )
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Train ZeroWall risk-scorer")
    ap.add_argument("--feedback", type=Path, default=None)
    ap.add_argument("--epochs", type=int, default=3000)
    ap.add_argument("--lr", type=float, default=0.1)
    args = ap.parse_args()
    train(args.feedback, epochs=args.epochs, lr=args.lr)


if __name__ == "__main__":
    main()
