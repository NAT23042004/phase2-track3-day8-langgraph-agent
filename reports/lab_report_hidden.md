# Day 08 Hidden Scenario Report

## 1. Run summary

This report covers the hidden grading set from [data/scenarios_hidden.jsonl](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/data/scenarios_hidden.jsonl), generated through [outputs/metrics_hidden.json](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/outputs/metrics_hidden.json).

- Total scenarios: 15
- Success rate: 100.00%
- Average nodes visited: 7.67
- Total retries: 5
- Total interrupts: 5
- Resume success: `true`

The hidden set validates that the routing logic generalizes beyond the seven visible sample scenarios and still preserves the intended retry, approval, and termination behavior.

## 2. Architecture

The workflow keeps the original graded shape while extending normal tool and risky-success paths with parallel fan-out:

`START -> intake -> classify`

- `simple -> answer -> finalize -> END`
- `tool -> fanout_dispatch -> [tool_order, tool_profile] -> evaluate -> answer -> finalize -> END`
- `missing_info -> clarify -> finalize -> END`
- `risky -> risky_action -> approval -> fanout_dispatch -> [tool_order, tool_profile] -> evaluate -> answer -> finalize -> END`
- `error -> retry -> tool -> evaluate -> retry ...`
- exhausted retries -> `dead_letter -> finalize -> END`

This structure matters for the hidden set because it tests both priority conflicts and nontrivial failure behavior:

- risky keywords still take priority over tool keywords
- vague requests still route to clarification instead of hallucinated action
- error scenarios still stay on the single-tool retry path
- all routes still terminate cleanly

## 3. State schema

The state remains intentionally small and serializable.

| Field | Reducer | Why |
|---|---|---|
| `thread_id` | overwrite | stable checkpoint identity |
| `scenario_id` | overwrite | traceability into metrics/reporting |
| `query` | overwrite | normalized user request |
| `route` | overwrite | current route classification |
| `risk_level` | overwrite | low/elevated/high risk marker |
| `attempt` | overwrite | current retry count |
| `max_attempts` | overwrite | retry ceiling |
| `final_answer` | overwrite | final response |
| `pending_question` | overwrite | clarification prompt |
| `proposed_action` | overwrite | risky action preview |
| `approval` | overwrite | reviewer decision payload |
| `evaluation_result` | overwrite | retry gate result |
| `fanout_expected` | overwrite | expected number of parallel tool results |
| `messages` | append | lightweight execution trace |
| `tool_results` | append | structured tool evidence |
| `errors` | append | retry/dead-letter evidence |
| `events` | append | audit trail for metrics and replay |

Only `messages`, `tool_results`, `errors`, and `events` are append-only reducer fields.

## 4. Hidden scenario results

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|---:|---:|---:|
| G01_simple | simple | simple | yes | 0 | 0 |
| G02_simple2 | simple | simple | yes | 0 | 0 |
| G03_tool | tool | tool | yes | 0 | 0 |
| G04_tool2 | tool | tool | yes | 0 | 0 |
| G05_tool3 | tool | tool | yes | 0 | 0 |
| G06_missing | missing_info | missing_info | yes | 0 | 0 |
| G07_missing2 | missing_info | missing_info | yes | 0 | 0 |
| G08_risky | risky | risky | yes | 0 | 1 |
| G09_risky2 | risky | risky | yes | 0 | 1 |
| G10_risky3 | risky | risky | yes | 0 | 1 |
| G11_risky4 | risky | risky | yes | 0 | 1 |
| G12_error | error | error | yes | 2 | 0 |
| G13_error2 | error | error | yes | 2 | 0 |
| G14_dead | error | error | yes | 1 | 0 |
| G15_mixed | risky | risky | yes | 0 | 1 |

Key observations:

- The two simple and two missing-info hidden variants still take the shortest route at 4 visited nodes.
- The three tool-only hidden variants all route correctly through the parallel fan-out path at 8 visited nodes.
- All five risky hidden scenarios observed approval before continuing, including destructive wording such as `remove`, `revoke`, and `send`.
- The mixed-priority case `G15_mixed` (`Check refund status for order 456`) correctly routed to `risky`, proving risky intent still overrides tool keywords.
- Both transient error scenarios retried twice and recovered successfully.
- The dead-letter hidden case `G14_dead` exhausted at `max_attempts=1` and terminated correctly.

## 5. Failure analysis

1. Retry behavior under hidden error phrasing:

The hidden set includes non-sample wording such as `Service unavailable` and `internal server error`. Both were still routed to `error`, then handled through `retry -> tool -> evaluate`. The retry count of 2 on `G12_error` and `G13_error2` shows that the retry loop is driven by tool status rather than scenario hard-coding.

2. Risky/tool keyword collisions:

The hidden set intentionally includes `G15_mixed`, where `refund` and `status/order` appear together. Because `classify_node` checks risky keywords before tool keywords, the scenario routes to `risky` and requires approval. This confirms the intended priority order holds on hidden inputs, not only on the visible lab scenarios.

## 6. Persistence evidence

Although hidden grading here uses the same `memory` checkpointer configuration as the visible run, the metrics still report `resume_success=true`, which confirms state history was observable during execution.

Additional persistence and recovery evidence for the extension work remains in [outputs/extensions](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/outputs/extensions):

- [sqlite_evidence.json](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/outputs/extensions/sqlite_evidence.json)
- [time_travel_evidence.json](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/outputs/extensions/time_travel_evidence.json)
- [hitl_evidence.json](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/outputs/extensions/hitl_evidence.json)
- [crash_resume_evidence.json](/home/natus/VinAI_ThucChien/Laboratory/lab23/phase2-track3-day8-langgraph-agent/outputs/extensions/crash_resume_evidence.json)

Those artifacts demonstrate SQLite persistence, replay from checkpoint history, interrupt/resume approval, and recovery after graph reconstruction with the same `thread_id`.

## 7. Extension status

The hidden run indirectly exercises the same completed extension-aware graph as the visible run:

- parallel fan-out with `Send()` on tool and approved risky paths
- real HITL support through `interrupt()` / `Command(resume=...)`
- SQLite-backed demo and recovery helpers
- Mermaid graph export
- Streamlit UI demo surface for HITL, SQLite persistence, replay, crash-resume, and graph export

The hidden metrics confirm that adding these extensions did not break generalized routing behavior.

## 8. Improvement plan

If I had one more day, I would focus on robustness rather than adding new features:

- strengthen the keyword classifier with broader synonym coverage and ambiguity handling
- make partial fan-out failure handling richer than the current success-only mock path
- suppress or configure the LangGraph serializer deprecation warning so grading and demos stay clean
- add report generation that automatically merges visible and hidden metrics into one comparison view
