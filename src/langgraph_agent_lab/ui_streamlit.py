"""Streamlit UI for the extension demos."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st  # type: ignore[import-not-found]
from langgraph.types import Command

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from langgraph_agent_lab.extensions import (
        demo_crash_resume,
        demo_sqlite_persistence,
        demo_time_travel,
        export_graph_mermaid,
        interrupt_mode,
        new_thread_id,
        sqlite_graph,
    )
    from langgraph_agent_lab.state import Route, Scenario, initial_state
else:
    from .extensions import (
        demo_crash_resume,
        demo_sqlite_persistence,
        demo_time_travel,
        export_graph_mermaid,
        interrupt_mode,
        new_thread_id,
        sqlite_graph,
    )
    from .state import Route, Scenario, initial_state

DATABASE_PATH = Path("outputs/extensions/ui_hitl.db")
EXTENSIONS_DIR = Path("outputs/extensions")


def extension_demo_specs() -> list[dict[str, str]]:
    return [
        {
            "key": "hitl",
            "title": "HITL Approval",
            "button_label": "Start risky workflow",
        },
        {
            "key": "sqlite",
            "title": "SQLite Persistence",
            "button_label": "Run SQLite demo",
        },
        {
            "key": "time_travel",
            "title": "Time Travel Replay",
            "button_label": "Run replay demo",
        },
        {
            "key": "crash_resume",
            "title": "Crash Resume",
            "button_label": "Run crash-resume demo",
        },
        {
            "key": "graph_export",
            "title": "Graph Export",
            "button_label": "Export Mermaid graph",
        },
    ]


def _artifact_paths() -> dict[str, dict[str, Path]]:
    return {
        "sqlite": {
            "database": EXTENSIONS_DIR / "ui_sqlite.db",
            "output": EXTENSIONS_DIR / "ui_sqlite_evidence.json",
        },
        "time_travel": {
            "database": EXTENSIONS_DIR / "ui_time_travel.db",
            "output": EXTENSIONS_DIR / "ui_time_travel_evidence.json",
        },
        "crash_resume": {
            "database": EXTENSIONS_DIR / "ui_crash_resume.db",
            "output": EXTENSIONS_DIR / "ui_crash_resume_evidence.json",
        },
        "graph_export": {
            "output": EXTENSIONS_DIR / "ui_graph.mmd",
        },
    }


def _run_until_interrupt(query: str, thread_id: str) -> dict:
    scenario = Scenario(id="streamlit-hitl", query=query, expected_route=Route.RISKY)
    state = initial_state(scenario)
    state["thread_id"] = thread_id
    config = {"configurable": {"thread_id": thread_id}}

    with sqlite_graph(DATABASE_PATH) as graph:
        with interrupt_mode(True):
            chunks = list(graph.stream(state, config))

    for chunk in chunks:
        interrupt_events = chunk.get("__interrupt__")
        if interrupt_events:
            interrupt_obj = interrupt_events[0]
            return getattr(interrupt_obj, "value", interrupt_obj)
    return {}


def _resume(thread_id: str, approved: bool) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    decision = {
        "approved": approved,
        "reviewer": "streamlit-reviewer",
        "comment": "approved in UI" if approved else "rejected in UI",
    }
    with sqlite_graph(DATABASE_PATH) as graph:
        with interrupt_mode(True):
            return graph.invoke(Command(resume=decision), config=config)


def _run_demo(key: str) -> dict[str, Any]:
    artifact_paths = _artifact_paths()
    if key == "sqlite":
        return demo_sqlite_persistence(
            artifact_paths["sqlite"]["database"],
            artifact_paths["sqlite"]["output"],
        )
    if key == "time_travel":
        return demo_time_travel(
            artifact_paths["time_travel"]["database"],
            artifact_paths["time_travel"]["output"],
        )
    if key == "crash_resume":
        return demo_crash_resume(
            artifact_paths["crash_resume"]["database"],
            artifact_paths["crash_resume"]["output"],
        )
    if key == "graph_export":
        return export_graph_mermaid(artifact_paths["graph_export"]["output"])
    raise ValueError(f"Unknown UI demo key: {key}")


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "thread_id": "",
        "interrupt_payload": None,
        "final_state": None,
        "ui_demo_payloads": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_hitl_tab() -> None:
    st.subheader("Interactive approval flow")
    st.caption("Real interrupt/resume workflow backed by SQLite checkpoints.")

    query = st.text_input(
        "Risky request",
        value="Refund this customer and send confirmation email",
    )

    if st.button("Start risky workflow", type="primary"):
        st.session_state.thread_id = new_thread_id()
        st.session_state.final_state = None
        st.session_state.interrupt_payload = _run_until_interrupt(query, st.session_state.thread_id)

    if st.session_state.thread_id:
        st.write(f"Thread ID: `{st.session_state.thread_id}`")
        st.caption(f"SQLite DB: `{DATABASE_PATH}`")

    if st.session_state.interrupt_payload:
        st.markdown("**Approval required**")
        st.json(st.session_state.interrupt_payload)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve", use_container_width=True):
                st.session_state.final_state = _resume(st.session_state.thread_id, approved=True)
                st.session_state.interrupt_payload = None
        with col2:
            if st.button("Reject", use_container_width=True):
                st.session_state.final_state = _resume(st.session_state.thread_id, approved=False)
                st.session_state.interrupt_payload = None

    if st.session_state.final_state:
        final_state = st.session_state.final_state
        st.markdown("**Final result**")
        st.json(
            {
                "final_answer": final_state.get("final_answer"),
                "approval": final_state.get("approval"),
                "route": final_state.get("route"),
            }
        )
        st.markdown("**Event trail**")
        st.json(final_state.get("events", []))


def _render_demo_payload(key: str) -> None:
    payloads = st.session_state.ui_demo_payloads
    payload = payloads.get(key)
    if not payload:
        return

    st.markdown("**Latest artifact**")
    st.json(payload)

    if key == "graph_export":
        graph_path = Path(str(payload["output_path"]))
        if graph_path.exists():
            st.markdown("**Mermaid output**")
            st.code(graph_path.read_text(encoding="utf-8"), language="mermaid")


def _render_artifact_tab(key: str, title: str, button_label: str, description: str) -> None:
    st.subheader(title)
    st.caption(description)
    if st.button(button_label, key=f"run-{key}"):
        st.session_state.ui_demo_payloads[key] = _run_demo(key)
    _render_demo_payload(key)


def main() -> None:
    st.set_page_config(page_title="LangGraph Extension Demos", layout="wide")
    st.title("LangGraph Extension Demo Dashboard")
    st.caption(
        "Streamlit UI for HITL approval, SQLite persistence, time-travel replay, "
        "crash recovery, and Mermaid graph export."
    )

    _init_state()
    tabs = st.tabs([spec["title"] for spec in extension_demo_specs()])

    with tabs[0]:
        _render_hitl_tab()
    with tabs[1]:
        _render_artifact_tab(
            "sqlite",
            "SQLite persistence evidence",
            "Run SQLite demo",
            "Runs the fan-out tool scenario with a SQLite checkpointer "
            "and shows the saved artifact.",
        )
    with tabs[2]:
        _render_artifact_tab(
            "time_travel",
            "Checkpoint history replay",
            "Run replay demo",
            "Captures a prior checkpoint from SQLite state history "
            "and exposes the historical state values.",
        )
    with tabs[3]:
        _render_artifact_tab(
            "crash_resume",
            "Crash and resume recovery",
            "Run crash-resume demo",
            "Builds one graph up to the interrupt boundary, rebuilds a second "
            "graph from the same DB, and resumes with the same thread id.",
        )
    with tabs[4]:
        _render_artifact_tab(
            "graph_export",
            "Mermaid graph export",
            "Export Mermaid graph",
            "Exports the current graph with fan-out and retry branches "
            "and shows the Mermaid source inline.",
        )


if __name__ == "__main__":
    main()
