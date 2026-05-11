"""CLI for the lab."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer
import yaml  # type: ignore[import-untyped]

from .extensions import (
    demo_crash_resume,
    demo_hitl,
    demo_sqlite_persistence,
    demo_time_travel,
    export_graph_mermaid,
)
from .graph import build_graph
from .metrics import MetricsReport, metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer
from .report import write_report
from .scenarios import load_scenarios
from .state import initial_state

app = typer.Typer(no_args_is_help=True)


@app.command("run-scenarios")
def run_scenarios(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run all grading scenarios and write metrics JSON."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios = load_scenarios(cfg["scenarios_path"])
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    metrics = []
    for scenario in scenarios:
        state = initial_state(scenario)
        run_config = {"configurable": {"thread_id": state["thread_id"]}}
        started_at = time.perf_counter()
        final_state = graph.invoke(state, config=run_config)
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        history_length = 0
        resume_success = False

        if checkpointer is not None:
            try:
                history = list(graph.get_state_history(run_config))
                history_length = len(history)
                resume_success = history_length > 0
            except Exception:
                history_length = 0
                resume_success = False

        metrics.append(
            metric_from_state(
                final_state,
                scenario.expected_route.value,
                scenario.requires_approval,
                latency_ms=latency_ms,
                resume_success=resume_success,
            )
        )
    report = summarize_metrics(metrics)
    write_metrics(report, output)
    if cfg.get("report_path"):
        write_report(report, cfg["report_path"])
    typer.echo(f"Wrote metrics to {output}")


@app.command("validate-metrics")
def validate_metrics(metrics: Annotated[Path, typer.Option("--metrics")]) -> None:
    """Validate metrics JSON schema for grading."""
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    report = MetricsReport.model_validate(payload)
    if report.total_scenarios < 6:
        raise typer.BadParameter("Expected at least 6 scenarios")
    typer.echo(f"Metrics valid. success_rate={report.success_rate:.2%}")


@app.command("export-graph")
def export_graph(output: Annotated[Path, typer.Option("--output")]) -> None:
    """Export the Mermaid graph for the extension report."""
    payload = export_graph_mermaid(output)
    typer.echo(f"Wrote Mermaid graph to {payload['output_path']}")


@app.command("demo-sqlite")
def demo_sqlite(
    database: Annotated[Path, typer.Option("--database")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run a SQLite-backed scenario and capture persistence evidence."""
    payload = demo_sqlite_persistence(database, output)
    typer.echo(
        f"Wrote SQLite demo to {output} "
        f"(thread_id={payload['thread_id']}, history_length={payload['history_length']})"
    )


@app.command("demo-time-travel")
def demo_time_travel_cmd(
    database: Annotated[Path, typer.Option("--database")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Capture checkpoint history and replay evidence."""
    payload = demo_time_travel(database, output)
    typer.echo(
        f"Wrote time-travel demo to {output} "
        f"(history_length={payload['history_length']})"
    )


@app.command("demo-hitl")
def demo_hitl_cmd(
    database: Annotated[Path, typer.Option("--database")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run the interrupt/resume HITL demo and capture approval evidence."""
    payload = demo_hitl(database, output)
    typer.echo(
        f"Wrote HITL demo to {output} "
        f"(thread_id={payload['thread_id']}, approved={payload['reviewer_decision']['approved']})"
    )


@app.command("demo-crash-resume")
def demo_crash_resume_cmd(
    database: Annotated[Path, typer.Option("--database")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Demonstrate persisted resume across graph reconstruction."""
    payload = demo_crash_resume(database, output)
    typer.echo(
        f"Wrote crash-resume demo to {output} "
        "(thread_id="
        f"{payload['thread_id']}, "
        f"history_length={payload['history_length_after_resume']})"
    )


if __name__ == "__main__":
    app()
