import importlib.util
import json
import runpy
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langgraph_agent_lab.cli import app
from langgraph_agent_lab.extensions import demo_crash_resume, demo_sqlite_persistence
from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.state import Route, Scenario, initial_state

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None,
    reason="langgraph not installed in local environment",
)


def _run_graph(query: str, route: Route) -> dict:
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(id="extension", query=query, expected_route=route)
    state = initial_state(scenario)
    return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})


def test_tool_route_fans_out_to_two_mock_tools():
    result = _run_graph("Please lookup order status for order 123", Route.TOOL)

    assert result["route"] == Route.TOOL.value
    assert len(result["tool_results"]) == 2
    assert {item["tool"] for item in result["tool_results"]} == {
        "mock_order_lookup",
        "mock_profile_lookup",
    }


def test_risky_route_uses_fanout_after_approval():
    result = _run_graph("Refund this customer and send confirmation email", Route.RISKY)

    assert result["route"] == Route.RISKY.value
    assert result["approval"]["approved"] is True
    assert len(result["tool_results"]) == 2


def test_rejected_approval_routes_to_clarify(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGGRAPH_INTERRUPT", "true")
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(
        id="reject",
        query="Delete customer account after support verification",
        expected_route=Route.RISKY,
    )
    state = initial_state(scenario)
    config = {"configurable": {"thread_id": state["thread_id"]}}

    for chunk in graph.stream(state, config):
        if "__interrupt__" in chunk:
            break

    from langgraph.types import Command

    result = graph.invoke(
        Command(
            resume={"approved": False, "reviewer": "qa-reviewer", "comment": "reject for test"}
        ),
        config=config,
    )

    assert result["approval"]["approved"] is False
    assert result["final_answer"].startswith("I need a bit more context")
    assert result["tool_results"] == []


def test_graph_mermaid_exposes_extension_branches():
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    mermaid = graph.get_graph().draw_mermaid()

    assert "classify -.-> fanout_dispatch;" in mermaid
    assert "fanout_dispatch -.-> tool_order;" in mermaid
    assert "fanout_dispatch -.-> tool_profile;" in mermaid
    assert "tool_order --> evaluate;" in mermaid
    assert "tool_profile --> evaluate;" in mermaid
    assert "approval -.-> fanout_dispatch;" in mermaid
    assert "retry -.-> tool;" in mermaid
    assert "retry -.-> dead_letter;" in mermaid


@pytest.mark.skipif(
    importlib.util.find_spec("langgraph.checkpoint.sqlite") is None,
    reason="sqlite checkpointer package not installed",
)
def test_demo_commands_generate_extension_artifacts(tmp_path: Path):
    runner = CliRunner()
    graph_path = tmp_path / "graph.mmd"
    sqlite_db = tmp_path / "sqlite.db"
    sqlite_out = tmp_path / "sqlite.json"
    time_db = tmp_path / "time.db"
    time_out = tmp_path / "time.json"
    hitl_db = tmp_path / "hitl.db"
    hitl_out = tmp_path / "hitl.json"
    crash_db = tmp_path / "crash.db"
    crash_out = tmp_path / "crash.json"

    result = runner.invoke(app, ["export-graph", "--output", str(graph_path)])
    assert result.exit_code == 0, result.output
    assert "fanout_dispatch" in graph_path.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        ["demo-sqlite", "--database", str(sqlite_db), "--output", str(sqlite_out)],
    )
    assert result.exit_code == 0, result.output
    sqlite_payload = json.loads(sqlite_out.read_text(encoding="utf-8"))
    assert sqlite_payload["database_path"] == str(sqlite_db)
    assert sqlite_payload["history_length"] > 0

    result = runner.invoke(
        app,
        ["demo-time-travel", "--database", str(time_db), "--output", str(time_out)],
    )
    assert result.exit_code == 0, result.output
    time_payload = json.loads(time_out.read_text(encoding="utf-8"))
    assert time_payload["history_length"] > 1
    assert time_payload["selected_checkpoint"]["next_nodes"]

    result = runner.invoke(
        app,
        ["demo-hitl", "--database", str(hitl_db), "--output", str(hitl_out)],
    )
    assert result.exit_code == 0, result.output
    hitl_payload = json.loads(hitl_out.read_text(encoding="utf-8"))
    assert hitl_payload["interrupt_payload"]["proposed_action"]
    assert hitl_payload["reviewer_decision"]["approved"] is True
    assert hitl_payload["final_state"]["approval"]["approved"] is True

    result = runner.invoke(
        app,
        ["demo-crash-resume", "--database", str(crash_db), "--output", str(crash_out)],
    )
    assert result.exit_code == 0, result.output
    crash_payload = json.loads(crash_out.read_text(encoding="utf-8"))
    assert crash_payload["thread_id"]
    assert crash_payload["persisted_before_resume"]["next_nodes"]
    assert crash_payload["resumed_final_state"]["final_answer"]


@pytest.mark.skipif(
    importlib.util.find_spec("langgraph.checkpoint.sqlite") is None,
    reason="sqlite checkpointer package not installed",
)
def test_demo_sqlite_rerun_on_same_db_stays_deterministic(tmp_path: Path):
    database = tmp_path / "sqlite.db"
    output = tmp_path / "sqlite.json"

    first = demo_sqlite_persistence(database, output)
    second = demo_sqlite_persistence(database, output)

    assert first["history_length"] == second["history_length"]
    assert first["journal_mode"] == second["journal_mode"] == "wal"
    assert first["thread_id"] != second["thread_id"]


@pytest.mark.skipif(
    importlib.util.find_spec("langgraph.checkpoint.sqlite") is None,
    reason="sqlite checkpointer package not installed",
)
def test_demo_crash_resume_rerun_on_same_db_stays_deterministic(tmp_path: Path):
    database = tmp_path / "crash_resume.db"
    output = tmp_path / "crash_resume.json"

    first = demo_crash_resume(database, output)
    second = demo_crash_resume(database, output)

    assert first["history_length_after_resume"] == second["history_length_after_resume"]
    assert first["persisted_before_resume"]["next_nodes"] == ["approval"]
    assert second["persisted_before_resume"]["next_nodes"] == ["approval"]
    assert first["thread_id"] != second["thread_id"]


def test_streamlit_ui_optional_dependency_declared():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'ui = ["streamlit>=1.38"]' in pyproject


def test_streamlit_ui_can_be_executed_as_a_script(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "streamlit", types.ModuleType("streamlit"))

    module_globals = runpy.run_path("src/langgraph_agent_lab/ui_streamlit.py")

    assert callable(module_globals["main"])
    assert module_globals["DATABASE_PATH"].name == "ui_hitl.db"


def test_streamlit_ui_exposes_all_extension_demo_specs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "streamlit", types.ModuleType("streamlit"))

    module_globals = runpy.run_path("src/langgraph_agent_lab/ui_streamlit.py")
    demo_specs = module_globals["extension_demo_specs"]()

    assert {spec["key"] for spec in demo_specs} == {
        "hitl",
        "sqlite",
        "time_travel",
        "crash_resume",
        "graph_export",
    }
    assert all(spec["title"] for spec in demo_specs)
    assert all(spec["button_label"] for spec in demo_specs)


def test_makefile_exposes_extension_commands():
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "export-graph:" in makefile
    assert "demo-extensions:" in makefile
    assert "streamlit-ui:" in makefile
    assert "8082" not in makefile
