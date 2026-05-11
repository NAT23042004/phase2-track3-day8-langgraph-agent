from langgraph_agent_lab.nodes import classify_node
from langgraph_agent_lab.routing import (
    route_after_approval,
    route_after_classify,
    route_after_evaluate,
    route_after_retry,
)
from langgraph_agent_lab.state import Route


def test_route_after_classify():
    assert route_after_classify({"route": Route.SIMPLE.value}) == "answer"
    assert route_after_classify({"route": Route.TOOL.value}) == "fanout_dispatch"
    assert route_after_classify({"route": Route.MISSING_INFO.value}) == "clarify"
    assert route_after_classify({"route": Route.RISKY.value}) == "risky_action"
    assert route_after_classify({"route": Route.ERROR.value}) == "retry"


def test_route_after_approval():
    assert route_after_approval({"approval": {"approved": True}}) == "fanout_dispatch"
    assert route_after_approval({"approval": {"approved": False}}) == "clarify"


def test_route_after_retry_bound():
    assert route_after_retry({"attempt": 0, "max_attempts": 3}) == "tool"
    assert route_after_retry({"attempt": 3, "max_attempts": 3}) == "dead_letter"


def test_route_after_evaluate():
    assert route_after_evaluate({"evaluation_result": "success"}) == "answer"
    assert route_after_evaluate({"evaluation_result": "needs_retry"}) == "retry"


def test_classify_prioritizes_risky_over_tool():
    result = classify_node({"query": "Please check order status and cancel it"})
    assert result["route"] == Route.RISKY.value
    assert result["risk_level"] == "high"


def test_classify_matches_missing_info_using_word_boundaries():
    assert classify_node({"query": "Can you fix it?"})["route"] == Route.MISSING_INFO.value
    assert classify_node({"query": "Please inspect item 42"})["route"] != Route.MISSING_INFO.value


def test_classify_supports_additional_keywords():
    assert classify_node({"query": "Revoke access immediately"})["route"] == Route.RISKY.value
    assert classify_node({"query": "Track package 1001"})["route"] == Route.TOOL.value
    assert classify_node({"query": "Service unavailable after crash"})["route"] == Route.ERROR.value


def test_classify_defaults_to_simple():
    result = classify_node({"query": "How does two-factor authentication work?"})
    assert result["route"] == Route.SIMPLE.value
