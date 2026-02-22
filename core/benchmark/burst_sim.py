"""
ZeroWall — Benchmark Suite
============================
Runs burst attack simulations and produces hard performance numbers.
Evidence output for NVIDIA DGX Spark eligibility.

Produces:
  - benchmark_summary.json
  - benchmark_summary.csv
  - human-readable terminal table (via rich)
"""

import asyncio
import csv
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

OUTPUT_DIR = Path(__file__).parent.parent.parent / "artifacts" / "benchmark"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class BurstSimulator:
    """
    Sends burst waves of exploit requests to measure:
    - Throughput (requests/second)
    - Latency distribution
    - Exploit success rate under load
    """

    def __init__(
        self,
        target_url: str = "http://localhost:8000",
        burst_size: int = 50,
        concurrency: int = 8,
        timeout_s: float = 5.0,
    ):
        self.target_url = target_url
        self.burst_size = burst_size
        self.concurrency = concurrency
        self.timeout_s = timeout_s

    async def run_burst(self) -> Dict[str, Any]:
        """Run a burst of exploit requests and collect metrics."""
        logger.info(
            f"[Benchmark] Starting burst: {self.burst_size} requests, "
            f"{self.concurrency} concurrent"
        )
        t_start = time.time()
        semaphore = asyncio.Semaphore(self.concurrency)
        results = []

        payloads = [
            ("GET", "/data", {"file": "../../etc/passwd"}, None),
            ("POST", "/run", None, {"cmd": "rm -rf /"}),
            ("GET", "/search", {"q": "' OR 1=1 --"}, None),
            ("GET", "/data", {"file": "../../config/secrets.yaml"}, None),
            ("POST", "/run", None, {"cmd": "; ls -la"}),
        ]

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            tasks = []
            for i in range(self.burst_size):
                payload = payloads[i % len(payloads)]
                tasks.append(self._fire(client, semaphore, payload, i))
            results = await asyncio.gather(*tasks, return_exceptions=True)

        t_elapsed = time.time() - t_start
        valid_results = [r for r in results if isinstance(r, dict)]

        successes = sum(1 for r in valid_results if r.get("exploited"))
        failures = len(valid_results) - successes
        errors = sum(1 for r in results if isinstance(r, Exception))

        latencies = [r["latency_ms"] for r in valid_results if "latency_ms" in r]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

        throughput = len(valid_results) / t_elapsed

        return {
            "burst_size": self.burst_size,
            "concurrency": self.concurrency,
            "total_requests": len(results),
            "successful_exploits": successes,
            "blocked_exploits": failures,
            "errors": errors,
            "exploit_success_rate": successes / max(len(valid_results), 1),
            "total_time_s": round(t_elapsed, 3),
            "throughput_rps": round(throughput, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
        }

    async def _fire(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        payload: tuple,
        index: int,
    ) -> Dict[str, Any]:
        method, endpoint, params, body = payload
        url = f"{self.target_url}{endpoint}"
        async with semaphore:
            t = time.time()
            try:
                if method == "GET":
                    resp = await client.get(url, params=params)
                else:
                    resp = await client.post(url, json=body)
                latency_ms = (time.time() - t) * 1000
                text = resp.text
                indicators = ["SIMULATED", "unknown", "' OR 1=1"]
                exploited = any(ind in text for ind in indicators) and resp.status_code not in (400, 403, 422)
                return {
                    "index": index,
                    "endpoint": endpoint,
                    "status_code": resp.status_code,
                    "exploited": exploited,
                    "latency_ms": latency_ms,
                }
            except Exception as e:
                return {
                    "index": index,
                    "endpoint": endpoint,
                    "exploited": False,
                    "latency_ms": (time.time() - t) * 1000,
                    "error": str(e),
                }


class BenchmarkReport:
    """Generates benchmark output files and terminal display."""

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir

    def save_json(self, data: Dict[str, Any], filename: str = "benchmark_summary.json") -> Path:
        path = self.output_dir / filename
        path.write_text(json.dumps(data, indent=2))
        logger.info(f"[Benchmark] Saved JSON: {path}")
        return path

    def save_csv(self, data: Dict[str, Any], filename: str = "benchmark_summary.csv") -> Path:
        path = self.output_dir / filename
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=data.keys())
            writer.writeheader()
            writer.writerow(data)
        logger.info(f"[Benchmark] Saved CSV: {path}")
        return path

    def print_table(self, data: Dict[str, Any]) -> None:
        """Print rich terminal benchmark table."""
        table = Table(title="🔥 ZeroWall Benchmark Results", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", ratio=2)
        table.add_column("Value", style="green", ratio=1)

        mappings = [
            ("Burst Size", str(data.get("burst_size", "-"))),
            ("Concurrency", str(data.get("concurrency", "-"))),
            ("Total Requests", str(data.get("total_requests", "-"))),
            ("Exploit Successes", str(data.get("successful_exploits", "-"))),
            ("Blocked Exploits", str(data.get("blocked_exploits", "-"))),
            ("Exploit Success Rate", f"{data.get('exploit_success_rate', 0):.1%}"),
            ("Throughput (rps)", str(data.get("throughput_rps", "-"))),
            ("Avg Latency (ms)", str(data.get("avg_latency_ms", "-"))),
            ("P95 Latency (ms)", str(data.get("p95_latency_ms", "-"))),
            ("Total Time (s)", str(data.get("total_time_s", "-"))),
            ("Defense Cycle Avg (s)", str(data.get("defense_cycle_avg_s", "-"))),
            ("Mutation Count", str(data.get("mutation_candidate_count", "-"))),
            ("RAPIDS Backend", str(data.get("rapids_backend", "-"))),
        ]
        for label, value in mappings:
            table.add_row(label, value)

        console.print(table)


async def run_full_benchmark(
    target_url: str = "http://localhost:8000",
    burst_size: int = 50,
    concurrency: int = 8,
    defense_loop=None,
) -> Dict[str, Any]:
    """
    Run full benchmark: burst attack + defense cycle timing.
    Returns combined metrics dict.
    """
    console.print("[bold cyan]🚀 ZeroWall Benchmark Mode Starting...[/bold cyan]")

    # Phase 1: Pre-defense burst
    console.print("[yellow]Phase 1: Pre-defense burst attack...[/yellow]")
    sim = BurstSimulator(target_url=target_url, burst_size=burst_size, concurrency=concurrency)
    pre_results = await sim.run_burst()

    # Phase 2: Defense cycle timing (if loop provided)
    defense_cycle_timing = {}
    mutation_count = 0
    if defense_loop:
        console.print("[yellow]Phase 2: Timing defense cycle...[/yellow]")
        t_cycle = time.time()
        cycle = defense_loop.run_defense_cycle(
            attack_context={"trigger": "benchmark", "endpoint": "/data"}
        )
        cycle_time = time.time() - t_cycle
        mutation_count = len(cycle.candidates)
        defense_cycle_timing = {
            "defense_cycle_avg_s": round(cycle_time, 3),
            "mutation_candidate_count": mutation_count,
            "mutation_latency_ms": round(cycle.mutation_inference_latency_ms, 2),
            "risk_latency_ms": round(cycle.risk_inference_latency_ms, 2),
        }

    # Phase 3: Post-defense burst
    console.print("[yellow]Phase 3: Post-defense burst attack...[/yellow]")
    post_results = await sim.run_burst()

    # Combine
    from core.telemetry.rapids_analytics import RapidsAnalytics
    ra = RapidsAnalytics()
    rapids_meta = ra.rapids_mode if hasattr(ra, 'rapids_mode') else False

    summary = {
        **pre_results,
        **defense_cycle_timing,
        "post_defense_exploit_rate": post_results["exploit_success_rate"],
        "post_defense_throughput_rps": post_results["throughput_rps"],
        "exploit_rate_improvement": round(
            pre_results["exploit_success_rate"] - post_results["exploit_success_rate"], 4
        ),
        "rapids_backend": "cuDF-GPU" if rapids_meta else "pandas-CPU",
        "timestamp": time.time(),
    }

    report = BenchmarkReport()
    report.save_json(summary)
    report.save_csv(summary)
    report.print_table(summary)

    return summary
