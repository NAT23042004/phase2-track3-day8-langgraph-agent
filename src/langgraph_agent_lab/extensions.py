"""Extension helpers for demos, replay, and graph export."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langgraph.types import Command, StateSnapshot

from .graph import build_graph
from .persistence import build_checkpointer
from .scenarios import load_scenarios
from .state import Scenario, initial_state

EXTENSIONS_DIR = Path("outputs/extensions")
SAMPLE_SCENARIOS_PATH = "data/sample/scenarios.jsonl"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _serialize_snapshot(snapshot: StateSnapshot) -> dict[str, Any]:
    return {
        "config": _serialize(snapshot.config),
        "metadata": _serialize(snapshot.metadata),
        "created_at": snapshot.created_at,
        "next_nodes": list(snapshot.next),
        "tasks": _serialize(snapshot.tasks),
        "interrupts": _serialize(snapshot.interrupts),
        "values": _serialize(snapshot.values),
    }


def _close_checkpointer(checkpointer: Any | None) -> None:
    conn = getattr(checkpointer, "conn", None)
    if conn is not None:
        conn.close()


def _reset_sqlite_artifacts(database: Path) -> None:
    for candidate in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if candidate.exists():
            candidate.unlink()


@contextmanager
def sqlite_graph(database: Path) -> Iterator[Any]:
    checkpointer = build_checkpointer("sqlite", str(database))
    try:
        yield build_graph(checkpointer=checkpointer)
    finally:
        _close_checkpointer(checkpointer)


def load_sample_scenario(scenario_id: str) -> Scenario:
    for scenario in load_scenarios(SAMPLE_SCENARIOS_PATH):
        if scenario.id == scenario_id:
            return scenario
    raise ValueError(f"Unknown sample scenario: {scenario_id}")


@contextmanager
def interrupt_mode(enabled: bool) -> Iterator[None]:
    previous = os.environ.get("LANGGRAPH_INTERRUPT")
    if enabled:
        os.environ["LANGGRAPH_INTERRUPT"] = "true"
    else:
        os.environ.pop("LANGGRAPH_INTERRUPT", None)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LANGGRAPH_INTERRUPT", None)
        else:
            os.environ["LANGGRAPH_INTERRUPT"] = previous


def export_graph_mermaid(output: Path) -> dict[str, Any]:
    graph = build_graph()
    mermaid = graph.get_graph().draw_mermaid()
    _ensure_parent(output)
    output.write_text(mermaid, encoding="utf-8")
    return {"output_path": str(output), "line_count": len(mermaid.splitlines())}


def demo_sqlite_persistence(database: Path, output: Path) -> dict[str, Any]:
    scenario = load_sample_scenario("S02_tool")
    _reset_sqlite_artifacts(database)
    with sqlite_graph(database) as graph:
        state = initial_state(scenario)
        state["thread_id"] = new_thread_id()
        config = {"configurable": {"thread_id": state["thread_id"]}}
        final_state = graph.invoke(state, config=config)
        history = list(graph.get_state_history(config))

    with sqlite3.connect(database) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()

    payload = {
        "database_path": str(database),
        "thread_id": state["thread_id"],
        "history_length": len(history),
        "journal_mode": str(journal_mode[0]).lower() if journal_mode else "unknown",
        "final_route": final_state.get("route"),
        "final_answer": final_state.get("final_answer"),
    }
    _write_json(output, payload)
    return payload


def demo_time_travel(database: Path, output: Path) -> dict[str, Any]:
    scenario = load_sample_scenario("S02_tool")
    _reset_sqlite_artifacts(database)
    with sqlite_graph(database) as graph:
        state = initial_state(scenario)
        state["thread_id"] = new_thread_id()
        config = {"configurable": {"thread_id": state["thread_id"]}}
        final_state = graph.invoke(state, config=config)
        history = list(graph.get_state_history(config))

    selected = next((snapshot for snapshot in history if snapshot.next), history[-1])
    selected_values = selected.values if isinstance(selected.values, dict) else {}
    selected_events = selected_values.get("events", [])
    payload = {
        "database_path": str(database),
        "thread_id": state["thread_id"],
        "history_length": len(history),
        "selected_checkpoint": {
            "metadata": _serialize(selected.metadata),
            "created_at": selected.created_at,
            "next_nodes": list(selected.next),
            "event_nodes": [event.get("node") for event in selected_events],
            "state_values": {
                "route": selected_values.get("route"),
                "attempt": selected_values.get("attempt"),
                "tool_results_count": len(selected_values.get("tool_results", [])),
                "fanout_expected": selected_values.get("fanout_expected"),
            },
        },
        "final_route": final_state.get("route"),
    }
    _write_json(output, payload)
    return payload


def _extract_interrupt_payload(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    for chunk in chunks:
        interrupt_events = chunk.get("__interrupt__")
        if interrupt_events:
            interrupt_obj = interrupt_events[0]
            return _serialize(getattr(interrupt_obj, "value", interrupt_obj))
    raise RuntimeError("Expected interrupt payload but none was surfaced")


def demo_hitl(database: Path, output: Path) -> dict[str, Any]:
    scenario = load_sample_scenario("S04_risky")
    decision = {"approved": True, "reviewer": "streamlit-reviewer", "comment": "approved"}
    _reset_sqlite_artifacts(database)
    with sqlite_graph(database) as graph:
        state = initial_state(scenario)
        state["thread_id"] = new_thread_id()
        config = {"configurable": {"thread_id": state["thread_id"]}}
        with interrupt_mode(True):
            chunks = list(graph.stream(state, config))
            final_state = graph.invoke(Command(resume=decision), config=config)

    payload = {
        "database_path": str(database),
        "thread_id": state["thread_id"],
        "interrupt_payload": _extract_interrupt_payload(chunks),
        "reviewer_decision": decision,
        "final_state": _serialize(final_state),
    }
    _write_json(output, payload)
    return payload


def demo_crash_resume(database: Path, output: Path) -> dict[str, Any]:
    scenario = load_sample_scenario("S06_delete")
    decision = {
        "approved": True,
        "reviewer": "recovery-reviewer",
        "comment": "resume after graph reconstruction",
    }
    state = initial_state(scenario)
    state["thread_id"] = new_thread_id()
    config = {"configurable": {"thread_id": state["thread_id"]}}

    _reset_sqlite_artifacts(database)
    with sqlite_graph(database) as first_graph:
        with interrupt_mode(True):
            first_chunks = list(first_graph.stream(state, config))
            persisted = first_graph.get_state(config)

    with sqlite_graph(database) as second_graph:
        with interrupt_mode(True):
            resumed_final_state = second_graph.invoke(Command(resume=decision), config=config)
            resumed_history = list(second_graph.get_state_history(config))

    payload = {
        "database_path": str(database),
        "thread_id": state["thread_id"],
        "interrupt_payload": _extract_interrupt_payload(first_chunks),
        "persisted_before_resume": _serialize_snapshot(persisted),
        "reviewer_decision": decision,
        "resumed_final_state": _serialize(resumed_final_state),
        "history_length_after_resume": len(resumed_history),
    }
    _write_json(output, payload)
    return payload


def new_thread_id() -> str:
    return f"thread-{uuid.uuid4()}"
