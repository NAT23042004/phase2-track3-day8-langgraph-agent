"""Routing functions for conditional edges."""

from __future__ import annotations

from langgraph.types import Send

from .state import AgentState, Route


def route_after_classify(state: AgentState) -> str:
    """Map the classified route to the next graph node."""
    route = state.get("route", Route.SIMPLE.value)
    mapping = {
        Route.SIMPLE.value: "answer",
        Route.TOOL.value: "fanout_dispatch",
        Route.MISSING_INFO.value: "clarify",
        Route.RISKY.value: "risky_action",
        Route.ERROR.value: "retry",
    }
    return mapping.get(route, "answer")


def route_after_retry(state: AgentState) -> str:
    """Route retries back to the tool or to dead-letter when exhausted."""
    if int(state.get("attempt", 0)) >= int(state.get("max_attempts", 3)):
        return "dead_letter"
    return "tool"


def route_after_evaluate(state: AgentState) -> str:
    """Route successful tool evaluations to answer and failures to retry."""
    if state.get("evaluation_result") == "needs_retry":
        return "retry"
    return "answer"


def route_after_approval(state: AgentState) -> str:
    """Continue only when approval is granted."""
    approval = state.get("approval") or {}
    return "fanout_dispatch" if approval.get("approved") else "clarify"


def route_after_fanout_dispatch(state: AgentState) -> list[Send]:
    """Send normal tool requests to both extension tool nodes."""
    branch_state = {
        "query": state.get("query", ""),
        "route": state.get("route", ""),
        "approval": state.get("approval"),
        "attempt": state.get("attempt", 0),
    }
    return [
        Send("tool_order", branch_state),
        Send("tool_profile", branch_state),
    ]
