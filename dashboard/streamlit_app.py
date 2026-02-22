"""
ZeroWall — Streamlit Dashboard
================================
Judge-friendly dashboard for the ZeroWall live demo.

Shows:
- Active deployment version and attack detection
- Mutation candidates table with test/exploit matrix
- Risk scores and confidence
- RAPIDS telemetry analytics
- Defense cycle latency and benchmark evidence
- Inference latency and throughput
- GPU utilization placeholder

Usage:
    streamlit run dashboard/streamlit_app.py
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

import streamlit as st

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ZeroWall — AI Moving Target Defense",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).parent.parent
TELEMETRY_DIR = BASE_DIR / "telemetry_data"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
BENCHMARK_DIR = ARTIFACTS_DIR / "benchmark"
DEPLOY_DIR = ARTIFACTS_DIR / "deploy"

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
.metric-card {
    background: linear-gradient(135deg, #1e3a5f, #0d2137);
    border-radius: 12px;
    padding: 1rem;
    border: 1px solid #2d5a8e;
}
.exploit-blocked { color: #00d26a; font-weight: bold; }
.exploit-failed { color: #ff6b6b; font-weight: bold; }
.status-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/2/21/Simple_English_Wikipedia_globe.svg/200px-Simple_English_Wikipedia_globe.svg.png", width=60)
    st.title("⚡ ZeroWall")
    st.caption("AI Moving Target Defense\nNVIDIA DGX Spark")
    st.divider()
    st.markdown("**NVIDIA Stack:**")
    st.markdown("✅ Triton Inference Server")
    st.markdown("✅ vLLM (TRT-LLM path)")
    st.markdown("✅ RAPIDS cuDF")
    st.divider()
    refresh_interval = st.slider("Auto-refresh (s)", 2, 30, 5)
    auto_refresh = st.toggle("Auto Refresh", value=True)
    if auto_refresh:
        time.sleep(0.1)


# ─── Header ──────────────────────────────────────────────────────────────────
st.title("🛡️ ZeroWall — AI Moving Target Defense")
st.caption("NVIDIA DGX Spark Hackathon | Multi-Agent Security Pipeline")
st.divider()


# ─── Helper: Load Data ───────────────────────────────────────────────────────

def load_telemetry() -> list:
    """Load all telemetry events."""
    path = TELEMETRY_DIR / "telemetry.jsonl"
    events = []
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        pass
    return events


def load_manifest() -> Dict[str, Any]:
    """Load deploy manifest."""
    path = DEPLOY_DIR / "manifest.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"active_version_id": "v1.0.0-ORIGINAL", "active_hash": "aabbcc001122", "history": []}


def load_benchmark() -> Dict[str, Any]:
    """Load latest benchmark summary."""
    path = BENCHMARK_DIR / "benchmark_summary.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def compute_analytics(events: list) -> Dict[str, Any]:
    """Compute analytics from telemetry events (pandas fallback)."""
    try:
        rapids_enabled = os.environ.get("RAPIDS_ENABLED", "true").lower() == "true"
        if rapids_enabled:
            try:
                import cudf as pd
                backend = "cuDF-GPU"
            except ImportError:
                import pandas as pd
                backend = "pandas-CPU"
        else:
            import pandas as pd
            backend = "pandas-CPU"

        if not events:
            return {"backend": backend}

        df = pd.DataFrame(events)

        def metric_vals(metric_name):
            try:
                mask = df["metric"] == metric_name
                vals = df[mask]["value"].astype(float)
                return list(vals)
            except Exception:
                return []

        baseline_rates = metric_vals("baseline_exploit_rate")
        candidate_rates = metric_vals("candidate_exploit_rate")
        cycle_latencies = metric_vals("cycle_latency_s")
        candidate_counts = metric_vals("candidate_count")

        def safe_avg(lst):
            return round(sum(lst) / len(lst), 4) if lst else 0.0

        return {
            "backend": backend,
            "exploit_before": safe_avg(baseline_rates) if baseline_rates else 1.0,
            "exploit_after": safe_avg(candidate_rates),
            "avg_cycle_s": safe_avg(cycle_latencies),
            "total_cycles": len(cycle_latencies),
            "total_candidates": int(sum(candidate_counts)) if candidate_counts else 0,
            "rolling_exploit": [round(r, 4) for r in baseline_rates[-20:]],
            "cycle_latencies": cycle_latencies,
        }
    except Exception as e:
        return {"backend": "error", "error": str(e)}


# ─── Load All Data ────────────────────────────────────────────────────────────
events = load_telemetry()
manifest = load_manifest()
benchmark = load_benchmark()
analytics = compute_analytics(events)

# ─── Row 1: Status Banners ────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="🔖 Active Version",
        value=manifest.get("active_version_id", "original")[:16],
        delta=manifest.get("active_hash", "aabbcc001122")[:8],
    )

with col2:
    total_cycles = analytics.get("total_cycles", 0)
    st.metric(
        label="🔄 Defense Cycles",
        value=total_cycles,
        delta="cycles completed",
    )

with col3:
    exploit_before = analytics.get("exploit_before", 1.0)
    exploit_after = analytics.get("exploit_after", 0.0)
    st.metric(
        label="💀 Exploit Rate Before",
        value=f"{exploit_before:.0%}",
        delta=f"→ {exploit_after:.0%} after",
        delta_color="inverse",
    )

with col4:
    avg_cycle = analytics.get("avg_cycle_s", 0)
    st.metric(
        label="⏱️ Avg Cycle Latency",
        value=f"{avg_cycle:.2f}s",
        delta="per defense cycle",
    )

st.divider()

# ─── Row 2: Deployment History & RAPIDS ──────────────────────────────────────
col_a, col_b = st.columns([1.5, 1])

with col_a:
    st.subheader("📋 Deployment History")
    history = manifest.get("history", [])
    if history:
        import pandas as pd_std
        df_display = pd_std.DataFrame(history)[
            ["version_id", "transform_type", "tests_passed", "exploit_success_rate", "confidence_score", "cycle_id"]
        ] if history else pd_std.DataFrame()
        if not df_display.empty:
            df_display["exploit_success_rate"] = df_display["exploit_success_rate"].apply(lambda x: f"{x:.0%}")
            df_display["confidence_score"] = df_display["confidence_score"].apply(lambda x: f"{x:.1%}")
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.info("No deployments yet. Run `/defend` in OpenClaw CLI.")
    else:
        st.info("No deployments yet. Run `/defend` in OpenClaw CLI.")

with col_b:
    st.subheader("⚡ RAPIDS Analytics")
    backend = analytics.get("backend", "unknown")
    backend_color = "🟢" if "GPU" in backend else "🟡"
    st.markdown(f"**Backend:** {backend_color} `{backend}`")
    st.markdown(f"**Total Candidates Evaluated:** `{analytics.get('total_candidates', 0)}`")
    st.markdown(f"**Exploit Reduction:** `{(exploit_before - exploit_after):.0%}`")

    # Rolling exploit rate chart
    rolling = analytics.get("rolling_exploit", [])
    if rolling:
        import pandas as pd_std
        chart_data = pd_std.DataFrame({"Exploit Rate": rolling})
        st.line_chart(chart_data, height=120)
    else:
        st.caption("No data yet — run a defense cycle to see trends")

st.divider()

# ─── Row 3: Inference Latency ─────────────────────────────────────────────────
st.subheader("🧠 Inference Latency (NVIDIA Stack)")
inf_col1, inf_col2, inf_col3 = st.columns(3)

def get_metric_vals(events, metric_name):
    return [e["value"] for e in events if e.get("metric") == metric_name and isinstance(e.get("value"), (int, float))]

mutation_lats = get_metric_vals(events, "mutation_latency_ms")
risk_lats = get_metric_vals(events, "risk_latency_ms")

with inf_col1:
    avg_mut = sum(mutation_lats) / len(mutation_lats) if mutation_lats else 0
    st.metric("Triton: Mutation Planner", f"{avg_mut:.0f}ms", delta="avg latency")

with inf_col2:
    avg_risk = sum(risk_lats) / len(risk_lats) if risk_lats else 0
    st.metric("Triton: Risk Scorer", f"{avg_risk:.0f}ms", delta="avg latency")

with inf_col3:
    bm_rps = benchmark.get("throughput_rps", 0)
    st.metric("Throughput (Benchmark)", f"{bm_rps:.0f} rps", delta="exploit requests/s")

st.divider()

# ─── Row 4: Benchmark Results ─────────────────────────────────────────────────
st.subheader("🔥 Benchmark Evidence")
if benchmark:
    bm_col1, bm_col2, bm_col3, bm_col4 = st.columns(4)
    with bm_col1:
        st.metric("Burst Size", benchmark.get("burst_size", "-"))
    with bm_col2:
        st.metric("Pre-Defense Exploit Rate", f"{benchmark.get('exploit_success_rate', 0):.0%}")
    with bm_col3:
        st.metric("Post-Defense Exploit Rate", f"{benchmark.get('post_defense_exploit_rate', 0):.0%}")
    with bm_col4:
        st.metric("Improvement", f"{benchmark.get('exploit_rate_improvement', 0):.0%}")

    with st.expander("Full Benchmark Summary"):
        st.json(benchmark)
else:
    st.info("Run `/benchmark` in OpenClaw CLI to generate benchmark evidence.")

st.divider()

# ─── Row 5: GPU Utilization Panel ────────────────────────────────────────────
st.subheader("🖥️ GPU Utilization (DGX Spark)")

gpu_col1, gpu_col2 = st.columns([2, 1])
with gpu_col1:
    st.info(
        "📸 **GPU Dashboard Panel** — On DGX Spark, embed screenshot here:\n\n"
        "Capture from: `nvidia-smi dmon` or DGX System Manager dashboard\n\n"
        "Export path: [Screenshot placeholder — attach actual DGX screenshot during live demo]"
    )
    gpu_stats_path = Path("artifacts/gpu_screenshot.png")
    if gpu_stats_path.exists():
        st.image(str(gpu_stats_path), caption="DGX GPU Utilization")

with gpu_col2:
    # Try to get live nvidia-smi stats if available
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            for i, line in enumerate(lines[:4]):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    st.metric(f"GPU {i}", parts[1], delta=f"{parts[2]} used")
        else:
            st.caption("nvidia-smi not available in this environment")
    except Exception:
        st.caption("nvidia-smi metrics not available — run on DGX Spark")

st.divider()

# ─── Footer ───────────────────────────────────────────────────────────────────
st.caption(
    f"ZeroWall — NVIDIA DGX Spark Hackathon | "
    f"RAPIDS: {analytics.get('backend', 'N/A')} | "
    f"Last refresh: {time.strftime('%H:%M:%S')}"
)

# Auto-refresh mechanism
if auto_refresh:
    st.markdown(
        f'<meta http-equiv="refresh" content="{refresh_interval}">',
        unsafe_allow_html=True,
    )
