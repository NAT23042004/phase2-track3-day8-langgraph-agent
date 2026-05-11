import importlib.util

import pytest

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import Route, Scenario, initial_state

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None,
    reason="langgraph not installed in local environment",
)


@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        ("How do I reset my password?", Route.SIMPLE.value),
        ("Please lookup order status for order 123", Route.TOOL.value),
        ("Refund this customer", Route.RISKY.value),
    ],
)
def test_graph_runs_basic_routes(query, expected_route):
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(id="smoke", query=query, expected_route=Route(expected_route))
    state = initial_state(scenario)
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    assert result["route"] == expected_route
    assert result.get("final_answer") or result.get("pending_question")


@pytest.mark.parametrize("scenario", load_scenarios("data/sample/scenarios.jsonl"))
def test_graph_runs_all_sample_scenarios(scenario):
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    state = initial_state(scenario)
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    event_nodes = [event["node"] for event in result["events"]]

    assert result["route"] == scenario.expected_route.value
    assert event_nodes[-1] == "finalize"
    assert result.get("final_answer") or result.get("pending_question")

    if scenario.requires_approval:
        assert any(node == "approval" for node in event_nodes)
        assert result.get("approval", {}).get("approved") is True

    if scenario.id == "S07_dead_letter":
        assert event_nodes[-3:] == ["retry", "dead_letter", "finalize"]
        assert result["final_answer"].startswith("Request could not be completed")


def test_graph_mermaid_exposes_documented_conditional_branches():
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    mermaid = graph.get_graph().draw_mermaid()

    assert "classify -.-> answer;" in mermaid
    assert "classify -.-> fanout_dispatch;" in mermaid
    assert "classify -.-> clarify;" in mermaid
    assert "classify -.-> risky_action;" in mermaid
    assert "classify -.-> retry;" in mermaid
    assert "fanout_dispatch -.-> tool_order;" in mermaid
    assert "fanout_dispatch -.-> tool_profile;" in mermaid
    assert "tool_order --> evaluate;" in mermaid
    assert "tool_profile --> evaluate;" in mermaid
    assert "evaluate -.-> answer;" in mermaid
    assert "evaluate -.-> retry;" in mermaid
    assert "approval -.-> fanout_dispatch;" in mermaid
    assert "approval -.-> clarify;" in mermaid
    assert "retry -.-> tool;" in mermaid
    assert "retry -.-> dead_letter;" in mermaid
