"""Regression tests for the OpenClaw command interface."""

from typer.testing import CliRunner

from core.orchestrator.openclaw_cli import app


runner = CliRunner()


def test_cli_help_loads_all_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    for command in ("defend", "replay", "status", "benchmark", "simulate-alert"):
        assert command in result.output


def test_benchmark_boolean_flags_are_valid():
    result = runner.invoke(app, ["benchmark", "--help"])

    assert result.exit_code == 0, result.output
    assert "--with-defense" in result.output
    assert "--no-with-defense" in result.output
