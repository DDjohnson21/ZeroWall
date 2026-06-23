"""
ZeroWall — Training Dataset Builder (RAPIDS cuDF, pandas fallback)
=================================================================
Aggregates the raw feedback log into a clean supervised dataset for the
Mutation Planner. The heavy groupby/aggregation runs on GPU via cuDF on DGX
Spark (same code path falls back to pandas off-GPU), which is exactly the kind
of telemetry-at-scale work RAPIDS is built for.

Output (one row per distinct attack context):
    X : (n_contexts, FEATURE_DIM)  one-hot attack features
    Y : (n_contexts, LABEL_DIM)    mean effectiveness per transform in [0,1]
    W : (n_contexts,)              support (number of observations) per context

The planner is then trained to regress Y from X — i.e. "given this attack,
how effective is each transform" — and serves a ranking from that.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.training.features import (
    FEATURE_DIM,
    LABEL_DIM,
    PAYLOAD_TYPES,
    ENDPOINTS,
    TRANSFORMS,
    encode_context,
)
from core.training.feedback import DEFAULT_FEEDBACK_PATH

logger = logging.getLogger(__name__)

# ── RAPIDS cuDF import with graceful pandas fallback (same pattern as analytics)
RAPIDS_ENABLED = os.environ.get("RAPIDS_ENABLED", "true").lower() == "true"
if RAPIDS_ENABLED:
    try:
        import cudf as df_lib
        USING_RAPIDS = True
    except ImportError:
        import pandas as df_lib
        USING_RAPIDS = False
else:
    import pandas as df_lib
    USING_RAPIDS = False


@dataclass
class PlannerDataset:
    X: np.ndarray            # (n, FEATURE_DIM)
    Y: np.ndarray            # (n, LABEL_DIM)
    W: np.ndarray            # (n,) support weights
    contexts: List[Dict[str, str]]
    backend: str
    n_examples: int

    def __len__(self) -> int:
        return int(self.X.shape[0])


def _read_feedback(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def build_dataset(feedback_path: Optional[Path] = None) -> PlannerDataset:
    """Aggregate the feedback log into a training-ready PlannerDataset."""
    path = Path(feedback_path) if feedback_path else DEFAULT_FEEDBACK_PATH
    rows = _read_feedback(path)
    backend = "cuDF-GPU" if USING_RAPIDS else "pandas-CPU"

    if not rows:
        logger.warning("[dataset_builder] no feedback rows at %s", path)
        return PlannerDataset(
            X=np.zeros((0, FEATURE_DIM), dtype=np.float32),
            Y=np.zeros((0, LABEL_DIM), dtype=np.float32),
            W=np.zeros((0,), dtype=np.float32),
            contexts=[],
            backend=backend,
            n_examples=0,
        )

    df = df_lib.DataFrame(rows)
    # GPU/CPU groupby: mean effectiveness per (context, transform) + counts.
    grouped = (
        df.groupby(["payload_type", "endpoint", "transform"])
        .agg({"label": "mean", "cycle_id": "count"})
        .reset_index()
    )
    # Bring the small aggregated frame back to host for matrix assembly.
    if USING_RAPIDS:
        grouped = grouped.to_pandas()

    transform_index = {t: i for i, t in enumerate(TRANSFORMS)}

    # Assemble per-context rows.
    contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for _, r in grouped.iterrows():
        key = (str(r["payload_type"]), str(r["endpoint"]))
        if key not in contexts:
            contexts[key] = {
                "y": np.zeros(LABEL_DIM, dtype=np.float32),
                "support": 0.0,
            }
        t = str(r["transform"])
        if t in transform_index:
            contexts[key]["y"][transform_index[t]] = float(r["label"])
        contexts[key]["support"] += float(r["cycle_id"])

    X, Y, W, ctx_list = [], [], [], []
    for (payload_type, endpoint), v in contexts.items():
        X.append(encode_context({"payload_type": payload_type, "endpoint": endpoint}))
        Y.append(v["y"])
        W.append(v["support"])
        ctx_list.append({"payload_type": payload_type, "endpoint": endpoint})

    ds = PlannerDataset(
        X=np.asarray(X, dtype=np.float32),
        Y=np.asarray(Y, dtype=np.float32),
        W=np.asarray(W, dtype=np.float32),
        contexts=ctx_list,
        backend=backend,
        n_examples=len(rows),
    )
    logger.info(
        "[dataset_builder] %s: %d examples -> %d contexts (%s)",
        backend, len(rows), len(ds), path.name,
    )
    return ds
