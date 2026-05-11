from langgraph_agent_lab.metrics import MetricsReport, metric_from_state, summarize_metrics
from langgraph_agent_lab.report import render_report_stub
from langgraph_agent_lab.state import make_event


def test_metric_from_state_success():
    state = {
        "scenario_id": "S",
        "route": "simple",
        "final_answer": "ok",
        "events": [
            make_event("intake", "completed", "ok"),
            make_event("answer", "completed", "ok"),
        ],
        "errors": [],
    }
    metric = metric_from_state(
        state,
        expected_route="simple",
        approval_required=False,
        latency_ms=17,
        resume_success=True,
    )
    assert metric.success is True
    assert metric.nodes_visited == 2
    assert metric.latency_ms == 17
    assert metric.resume_success is True


def test_metric_from_state_uses_resume_success_argument_not_state_field():
    state = {
        "scenario_id": "S",
        "route": "simple",
        "final_answer": "ok",
        "resume_success": False,
        "events": [make_event("finalize", "completed", "workflow finished")],
        "errors": [],
    }
    metric = metric_from_state(
        state,
        expected_route="simple",
        approval_required=False,
        latency_ms=3,
        resume_success=True,
    )
    assert metric.resume_success is True


def test_metric_from_state_tracks_approval_and_retry():
    state = {
        "scenario_id": "S04_risky",
        "route": "risky",
        "final_answer": "approved",
        "approval": {"approved": True},
        "events": [
            make_event("intake", "completed", "ok"),
            make_event("approval", "completed", "ok"),
            make_event("retry", "completed", "ok"),
            make_event("answer", "completed", "ok"),
        ],
        "errors": ["retry-1"],
    }
    metric = metric_from_state(
        state,
        expected_route="risky",
        approval_required=True,
        latency_ms=9,
        resume_success=False,
    )
    assert metric.approval_observed is True
    assert metric.retry_count == 1
    assert metric.interrupt_count == 1
    assert metric.errors == ["retry-1"]


def test_summarize_metrics():
    m1 = metric_from_state(
        {"scenario_id": "1", "route": "simple", "final_answer": "ok", "events": [], "errors": []},
        "simple",
        False,
        latency_ms=11,
        resume_success=True,
    )
    m2 = metric_from_state(
        {"scenario_id": "2", "route": "tool", "final_answer": None, "events": [], "errors": []},
        "tool",
        False,
        latency_ms=13,
        resume_success=True,
    )
    report = summarize_metrics([m1, m2])
    assert report.total_scenarios == 2
    assert 0 <= report.success_rate <= 1
    assert report.resume_success is True


def test_render_report_stub_matches_starter_behavior():
    report = MetricsReport(
        total_scenarios=1,
        success_rate=1.0,
        avg_nodes_visited=6.0,
        total_retries=1,
        total_interrupts=1,
        resume_success=True,
        scenario_metrics=[
            metric_from_state(
                {
                    "scenario_id": "S01",
                    "route": "simple",
                    "final_answer": "ok",
                    "events": [make_event("finalize", "completed", "workflow finished")],
                    "errors": [],
                },
                "simple",
                False,
                latency_ms=5,
                resume_success=True,
            )
        ],
    )

    rendered = render_report_stub(report)

    assert "## Metrics summary" in rendered
    assert "TODO(student)" in rendered
