from typing import Annotated, get_origin, get_type_hints

from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import AgentState, Route, Scenario, initial_state


def test_scenario_validation():
    scenario = Scenario(id="x", query="hello", expected_route=Route.SIMPLE)
    state = initial_state(scenario)
    assert state["thread_id"] == "thread-x"
    assert state["attempt"] == 0
    assert state["events"] == []


def test_load_scenarios():
    scenarios = load_scenarios("data/sample/scenarios.jsonl")
    assert len(scenarios) >= 6
    assert {item.expected_route for item in scenarios} >= {Route.SIMPLE, Route.TOOL, Route.RISKY}


def test_agent_state_reducers_only_apply_to_append_only_fields():
    append_only_fields = {"messages", "tool_results", "errors", "events"}
    reducer_fields = set()

    for field_name, annotation in get_type_hints(AgentState, include_extras=True).items():
        if get_origin(annotation) is Annotated:
            reducer_fields.add(field_name)

    assert reducer_fields == append_only_fields


def test_agent_state_excludes_cli_only_fields():
    fields = set(get_type_hints(AgentState, include_extras=True))
    assert "history_length" not in fields
    assert "resume_success" not in fields
    assert "fanout_expected" in fields
    state = initial_state(Scenario(id="y", query="hello", expected_route=Route.SIMPLE))
    assert "history_length" not in state
    assert "resume_success" not in state
    assert state["fanout_expected"] == 0
