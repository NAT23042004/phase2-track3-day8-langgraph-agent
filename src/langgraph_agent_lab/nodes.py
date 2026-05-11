"""Workflow nodes for the LangGraph support agent lab."""

from __future__ import annotations

import re
from typing import Any

from .state import AgentState, ApprovalDecision, Route, make_event

RISKY_KEYWORDS = ("refund", "delete", "send", "cancel", "remove", "revoke")
TOOL_KEYWORDS = ("status", "order", "lookup", "check", "track", "find", "search")
ERROR_KEYWORDS = ("timeout", "fail", "failure", "error", "crash", "unavailable")
VAGUE_PRONOUNS = {"it", "this", "that", "them"}


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return True
    return False


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[\w']+\b", text.lower())


def intake_node(state: AgentState) -> dict:
    """Normalize raw query into state fields."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [
            make_event(
                "intake",
                "completed",
                "query normalized",
                query_length=len(query),
                scenario_id=state.get("scenario_id", "unknown"),
            )
        ],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using deterministic keyword rules."""
    query = state.get("query", "").strip().lower()
    tokens = _tokenize(query)
    route = Route.SIMPLE
    risk_level = "low"

    if _contains_keyword(query, RISKY_KEYWORDS):
        route = Route.RISKY
        risk_level = "high"
    elif _contains_keyword(query, TOOL_KEYWORDS):
        route = Route.TOOL
    elif len(tokens) <= 5 and any(token in VAGUE_PRONOUNS for token in tokens):
        route = Route.MISSING_INFO
        risk_level = "unknown"
    elif _contains_keyword(query, ERROR_KEYWORDS) or re.search(r"\bcannot recover\b", query):
        route = Route.ERROR
        risk_level = "elevated"

    return {
        "route": route.value,
        "risk_level": risk_level,
        "events": [
            make_event(
                "classify",
                "completed",
                f"route={route.value}",
                route=route.value,
                token_count=len(tokens),
                risk_level=risk_level,
            )
        ],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating."""
    query = state.get("query", "").strip()
    question = (
        f"I need a bit more context to help with: '{query}'. "
        "What system, account, or order should I inspect?"
    )
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [
            make_event(
                "clarify",
                "completed",
                "missing information requested",
                pending_question=question,
            )
        ],
    }


def fanout_dispatch_node(state: AgentState) -> dict:
    """Prepare the normal tool path for parallel fan-out."""
    return {
        "fanout_expected": 2,
        "events": [
            make_event(
                "fanout_dispatch",
                "completed",
                "parallel tool fan-out prepared",
                expected_tools=2,
                route=state.get("route"),
            )
        ],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool with structured success or transient failure output."""
    attempt = int(state.get("attempt", 0))
    route = str(state.get("route", ""))
    query = str(state.get("query", ""))

    if route == Route.ERROR.value and attempt < 2:
        result: dict[str, Any] = {
            "status": "error",
            "tool": "mock_support_lookup",
            "attempt": attempt,
            "payload": {"reason": "transient_upstream_failure", "query": query},
        }
    else:
        result = {
            "status": "success",
            "tool": "mock_support_lookup",
            "attempt": attempt,
            "payload": {
                "summary": f"Resolved support workflow for '{query}'",
                "route": route,
                "approved": bool((state.get("approval") or {}).get("approved")),
            },
        }

    return {
        "tool_results": [result],
        "events": [
            make_event(
                "tool",
                "completed",
                f"tool executed attempt={attempt}",
                tool=result["tool"],
                status=result["status"],
                attempt=attempt,
            )
        ],
    }


def _parallel_tool_result(tool_name: str, state: AgentState) -> dict[str, Any]:
    query = str(state.get("query", ""))
    approval = state.get("approval") or {}
    result_summaries = {
        "mock_order_lookup": f"order workflow checked for '{query}'",
        "mock_profile_lookup": f"customer profile reviewed for '{query}'",
    }
    return {
        "status": "success",
        "tool": tool_name,
        "attempt": int(state.get("attempt", 0)),
        "payload": {
            "summary": result_summaries[tool_name],
            "route": state.get("route"),
            "approved": bool(approval.get("approved")),
        },
    }


def tool_order_node(state: AgentState) -> dict:
    """Mock order lookup used by the fan-out extension path."""
    result = _parallel_tool_result("mock_order_lookup", state)
    return {
        "tool_results": [result],
        "events": [
            make_event(
                "tool_order",
                "completed",
                "order evidence gathered",
                tool=result["tool"],
                status=result["status"],
            )
        ],
    }


def tool_profile_node(state: AgentState) -> dict:
    """Mock profile lookup used by the fan-out extension path."""
    result = _parallel_tool_result("mock_profile_lookup", state)
    return {
        "tool_results": [result],
        "events": [
            make_event(
                "tool_profile",
                "completed",
                "profile evidence gathered",
                tool=result["tool"],
                status=result["status"],
            )
        ],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for approval."""
    query = state.get("query", "").strip()
    proposed_action = f"Execute risky support action for request: {query}"
    return {
        "proposed_action": proposed_action,
        "events": [
            make_event(
                "risky_action",
                "pending_approval",
                "approval required",
                risk_level=state.get("risk_level", "high"),
                proposed_action=proposed_action,
            )
        ],
    }


def approval_node(state: AgentState) -> dict:
    """Human approval step with optional LangGraph interrupt()."""
    import os

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt(
            {
                "proposed_action": state.get("proposed_action"),
                "risk_level": state.get("risk_level"),
            }
        )
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
        event_type = "interrupt_decision"
    else:
        decision = ApprovalDecision(approved=True, comment="mock approval for lab")
        event_type = "mock_decision"

    return {
        "approval": decision.model_dump(),
        "events": [
            make_event(
                "approval",
                event_type,
                f"approved={decision.approved}",
                approved=decision.approved,
                reviewer=decision.reviewer,
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record the next retry attempt and attach bounded-retry metadata."""
    attempt = int(state.get("attempt", 0)) + 1
    max_attempts = int(state.get("max_attempts", 3))
    error_message = f"retry attempt {attempt} of {max_attempts}"
    return {
        "attempt": attempt,
        "errors": [error_message],
        "events": [
            make_event(
                "retry",
                "completed",
                "retry attempt recorded",
                attempt=attempt,
                max_attempts=max_attempts,
                backoff_ms=attempt * 100,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response grounded in tool output and approval state."""
    tool_results = state.get("tool_results") or []
    approval = state.get("approval") or {}

    if tool_results:
        ordered_results = sorted(tool_results, key=lambda item: str(item.get("tool", "")))
        summaries = [
            str(item.get("payload", {}).get("summary", item.get("status", "missing")))
            for item in ordered_results
        ]
        answer = f"I found: {'; '.join(summaries)}"
        if approval.get("approved"):
            answer = f"{answer} Approval recorded by {approval.get('reviewer', 'reviewer')}."
    else:
        answer = "This is a safe mock answer for a non-tool scenario."

    return {
        "final_answer": answer,
        "events": [
            make_event(
                "answer",
                "completed",
                "answer generated",
                used_tool=bool(tool_results),
                approval_observed=bool(approval),
            )
        ],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results and drive the bounded retry loop."""
    tool_results = state.get("tool_results", [])
    fanout_expected = int(state.get("fanout_expected", 0))

    if fanout_expected:
        statuses = {str(item.get("status", "missing")) for item in tool_results}
        result_count = len(tool_results)
        if "error" in statuses:
            return {
                "evaluation_result": "needs_retry",
                "events": [
                    make_event(
                        "evaluate",
                        "completed",
                        "parallel tool result indicates failure, retry needed",
                        latest_status="error",
                        tool_result_count=result_count,
                    )
                ],
            }
        return {
            "evaluation_result": "success",
            "events": [
                make_event(
                    "evaluate",
                    "completed",
                    "parallel tool results satisfactory",
                    latest_status="success",
                    tool_result_count=result_count,
                    expected_count=fanout_expected,
                )
            ],
        }

    latest = tool_results[-1] if tool_results else {}
    latest_status = latest.get("status")

    if latest_status == "error":
        return {
            "evaluation_result": "needs_retry",
            "events": [
                make_event(
                    "evaluate",
                    "completed",
                    "tool result indicates failure, retry needed",
                    latest_status=latest_status,
                )
            ],
        }
    return {
        "evaluation_result": "success",
        "events": [
            make_event(
                "evaluate",
                "completed",
                "tool result satisfactory",
                latest_status=latest_status or "missing",
            )
        ],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures for manual review."""
    attempt = int(state.get("attempt", 0))
    max_attempts = int(state.get("max_attempts", 3))
    message = (
        "Request could not be completed after maximum retry attempts. "
        "Logged for manual review."
    )
    return {
        "final_answer": message,
        "errors": [f"dead letter after attempt {attempt} of {max_attempts}"],
        "events": [
            make_event(
                "dead_letter",
                "completed",
                f"max retries exceeded, attempt={attempt}",
                attempt=attempt,
                max_attempts=max_attempts,
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    return {
        "events": [
            make_event(
                "finalize",
                "completed",
                "workflow finished",
                route=state.get("route"),
                attempt=state.get("attempt", 0),
            )
        ]
    }
