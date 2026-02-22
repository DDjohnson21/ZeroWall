"""
ZeroWall — OpenClaw Command Interface
=======================================
Terminal command interface mimicking OpenClaw-style orchestration.
Provides human operators and judges direct control over ZeroWall.

Commands:
  /defend         — Trigger a defense cycle
  /replay         — Replay exploit against active version
  /status         — Show current system status
  /benchmark      — Run burst benchmark mode
  /simulate-alert — Inject a mock IDS/webhook alert

Usage:
  python -m core.orchestrator.openclaw_cli [--interactive]

Or import and call programmatically.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

console = Console()
app = typer.Typer(name="openclaw", help="ZeroWall OpenClaw Command Interface")

# Lazy-init global defense loop
_defense_loop = None


def get_defense_loop():
    global _defense_loop
    if _defense_loop is None:
        from core.orchestrator.defense_loop import DefenseLoop
        from core.telemetry.collector import TelemetryCollector

        telemetry = TelemetryCollector()
        _defense_loop = DefenseLoop(
            target_url=os.environ.get("TARGET_URL", "http://localhost:8000"),
            triton_host=os.environ.get("TRITON_HOST", "localhost"),
            triton_port=int(os.environ.get("TRITON_HTTP_PORT", "8080")),
            vllm_host=os.environ.get("VLLM_HOST", "localhost"),
            vllm_port=int(os.environ.get("VLLM_PORT", "8088")),
            candidate_count=int(os.environ.get("MUTATION_CANDIDATE_COUNT", "10")),
            telemetry=telemetry,
        )
    return _defense_loop


def _print_banner():
    banner = Text()
    banner.append("╔══════════════════════════════════════════════╗\n", style="bold cyan")
    banner.append("║   ", style="bold cyan")
    banner.append("ZeroWall", style="bold white")
    banner.append(" — AI Moving Target Defense         ║\n", style="bold cyan")
    banner.append("║   Powered by NVIDIA DGX Spark                ║\n", style="bold cyan")
    banner.append("║   OpenClaw Orchestration Interface           ║\n", style="bold cyan")
    banner.append("╚══════════════════════════════════════════════╝", style="bold cyan")
    console.print(banner)
    console.print()


# ── Commands ─────────────────────────────────────────────────────────────────

@app.command(name="defend")
def cmd_defend(
    endpoint: str = typer.Option("/data", help="Attacked endpoint"),
    payload_type: str = typer.Option("path-traversal", help="Attack type"),
):
    """🛡️  Trigger a ZeroWall defense cycle."""
    console.print(Panel(
        f"[bold yellow]🛡️  Starting Defense Cycle[/bold yellow]\n"
        f"Attacked endpoint: [cyan]{endpoint}[/cyan]\n"
        f"Payload type: [cyan]{payload_type}[/cyan]",
        title="DEFEND",
        border_style="yellow",
    ))

    loop = get_defense_loop()
    attack_context = {
        "trigger": "openclaw-defend",
        "endpoint": endpoint,
        "payload_type": payload_type,
        "timestamp": time.time(),
    }

    try:
        cycle = loop.run_defense_cycle(attack_context=attack_context)
        _print_cycle_result(cycle)
    except Exception as e:
        console.print(f"[bold red]Defense cycle failed: {e}[/bold red]")
        raise typer.Exit(1)


@app.command(name="replay")
def cmd_replay(
    target_url: str = typer.Option("http://localhost:8000", help="Target URL"),
):
    """🎯 Replay exploit payloads against active version."""
    console.print(Panel(
        f"[bold red]🎯 Replaying known exploits against {target_url}[/bold red]",
        title="REPLAY",
        border_style="red",
    ))

    from core.agents.exploit_agent import ExploitAgent, KNOWN_PAYLOADS
    from core.models import CandidateResult, MutationPlan, TransformType

    agent = ExploitAgent(base_url=target_url)
    dummy_candidate = CandidateResult(
        candidate_id="active-version",
        plan=MutationPlan(
            candidate_id="active-version",
            transform_type=TransformType.RENAME_IDENTIFIERS,
            transform_params={},
            source_path="",
        ),
    )

    result = asyncio.run(agent.replay_against_candidate(dummy_candidate, target_url))
    _print_exploit_results(result)


@app.command(name="status")
def cmd_status():
    """📊 Show current ZeroWall system status."""
    loop = get_defense_loop()
    status = loop.get_status()

    table = Table(title="ZeroWall System Status", show_header=True)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    for key, value in status.items():
        table.add_row(str(key).replace("_", " ").title(), str(value))

    console.print(table)

    # Show inference health
    triton_status = "✅ Healthy" if status.get("triton_healthy") else "❌ Offline"
    vllm_status = "✅ Healthy" if status.get("vllm_healthy") else "❌ Offline"
    console.print(f"\n[bold]Inference:[/bold]  Triton: {triton_status}  |  vLLM: {vllm_status}")


@app.command(name="benchmark")
def cmd_benchmark(
    burst_size: int = typer.Option(50, help="Number of burst requests"),
    concurrency: int = typer.Option(8, help="Concurrent workers"),
    target_url: str = typer.Option("http://localhost:8000", help="Target URL"),
    with_defense: bool = typer.Option(False, help="Include defense cycle timing"),
):
    """🔥 Run burst benchmark mode and output metrics."""
    console.print(Panel(
        f"[bold magenta]🔥 Benchmark Mode[/bold magenta]\n"
        f"Burst: {burst_size} requests | Concurrency: {concurrency}",
        title="BENCHMARK",
        border_style="magenta",
    ))

    from core.benchmark.burst_sim import run_full_benchmark

    defense_loop = get_defense_loop() if with_defense else None
    results = asyncio.run(run_full_benchmark(
        target_url=target_url,
        burst_size=burst_size,
        concurrency=concurrency,
        defense_loop=defense_loop,
    ))
    console.print(f"\n[green]Results saved to: artifacts/benchmark/[/green]")


@app.command(name="simulate-alert")
def cmd_simulate_alert(
    endpoint: str = typer.Option("/data", help="Attacked endpoint"),
    severity: str = typer.Option("HIGH", help="Alert severity"),
):
    """🚨 Inject a mock IDS/webhook alert and trigger defense."""
    console.print(Panel(
        f"[bold red]🚨 SIMULATED IDS ALERT[/bold red]\n"
        f"Severity: [bold]{severity}[/bold]\n"
        f"Endpoint: [cyan]{endpoint}[/cyan]\n"
        f"Source: Mock IDS webhook → ZeroWall/OpenClaw",
        title="SIMULATE ALERT",
        border_style="red",
    ))
    console.print("\n[yellow]→ Triggering automatic defense cycle...[/yellow]\n")
    # Delegate to defend command
    cmd_defend(endpoint=endpoint, payload_type="simulated-ids-alert")


# ── Interactive Mode ──────────────────────────────────────────────────────────

@app.command(name="interactive")
def cmd_interactive():
    """💻 Start interactive OpenClaw session."""
    _print_banner()
    console.print("[bold]Commands:[/bold] /defend  /replay  /status  /benchmark  /simulate-alert  /quit\n")

    COMMAND_MAP = {
        "/defend": lambda: cmd_defend(endpoint="/data", payload_type="path-traversal"),
        "/replay": lambda: cmd_replay(target_url="http://localhost:8000"),
        "/status": cmd_status,
        "/benchmark": lambda: cmd_benchmark(burst_size=20, concurrency=4, target_url="http://localhost:8000", with_defense=False),
        "/simulate-alert": lambda: cmd_simulate_alert(endpoint="/data", severity="HIGH"),
    }

    while True:
        try:
            raw = console.input("[bold cyan]openclaw>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Goodbye.[/yellow]")
            break

        if raw in ("/quit", "/exit", "exit", "quit"):
            console.print("[yellow]Goodbye.[/yellow]")
            break

        if raw in COMMAND_MAP:
            try:
                COMMAND_MAP[raw]()
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
        elif raw:
            console.print(f"[red]Unknown command: {raw}[/red]")
            console.print("[dim]Available: /defend /replay /status /benchmark /simulate-alert /quit[/dim]")


# ── Result Printers ───────────────────────────────────────────────────────────

def _print_cycle_result(cycle):
    from core.models import DefenseCycle
    action_style = {"deploy": "green", "reject": "yellow", "rollback": "red"}.get(cycle.action, "white")

    table = Table(title="Defense Cycle Result")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Cycle ID", cycle.cycle_id[:12])
    table.add_row("Action", f"[{action_style}]{cycle.action.upper()}[/{action_style}]")
    table.add_row("Winner", str(cycle.winner_id or "None"))
    table.add_row("Candidates", str(len(cycle.candidates)))
    table.add_row("Cycle Latency", f"{cycle.cycle_latency_s:.2f}s")
    table.add_row("Mutation Latency", f"{cycle.mutation_inference_latency_ms:.0f}ms")
    table.add_row("Risk Latency", f"{cycle.risk_inference_latency_ms:.0f}ms")
    console.print(table)


def _print_exploit_results(result):
    from core.models import CandidateResult
    rate = result.exploit_success_rate
    style = "red" if rate > 0.5 else "green"
    console.print(Panel(
        f"Exploit Success Rate: [{style}]{rate:.0%}[/{style}]\n"
        f"Attempts: {result.exploit_attempts} | "
        f"Succeeded: {result.exploit_successes} | "
        f"Blocked: {result.exploit_failures}\n"
        f"Latency: {result.exploit_latency_ms:.0f}ms",
        title="Exploit Replay Result",
        border_style=style,
    ))


if __name__ == "__main__":
    app()
