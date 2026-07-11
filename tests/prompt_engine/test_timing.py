from __future__ import annotations

from aragora.prompt_engine.timing import OperationTiming, PipelineTiming


def test_pipeline_timing_surfaces_stage_breakdown_and_targets() -> None:
    timing = PipelineTiming(
        total_duration_ms=100.0,
        stage_durations_ms={
            "decompose": 15.0,
            "research": 60.0,
            "specify": 20.0,
        },
        operation_timings=[
            OperationTiming("decompose.agent_generate", 10.0, category="llm"),
            OperationTiming("research.km_query", 20.0, category="io"),
            OperationTiming("research.agent_generate", 35.0, category="llm"),
            OperationTiming("specify.parse_spec", 15.0, category="compute"),
        ],
    )

    payload = timing.to_dict()

    assert payload["tracked_duration_ms"] == 80.0
    assert payload["untracked_duration_ms"] == 20.0
    assert payload["tracking_coverage_pct"] == 80.0
    assert payload["stage_breakdown"][0]["stage"] == "research"
    assert payload["stage_breakdown"][0]["top_operation"]["operation"] == "research.agent_generate"
    assert payload["optimization_targets"][0]["operation"] == "research.agent_generate"
    assert payload["optimization_targets"][0]["share_of_total_pct"] == 35.0
    assert payload["operation_timings"][0]["stage"] == "decompose"
    assert payload["bottlenecks"] == []


def test_top_operations_orders_sub_millisecond_operations_by_duration() -> None:
    timing = PipelineTiming(
        operation_timings=[
            OperationTiming("research.agent_generate", 0.1, category="llm"),
            OperationTiming("research.parse_results", 0.9, category="compute"),
        ]
    )

    assert [item.operation for item in timing.top_operations()] == [
        "research.parse_results",
        "research.agent_generate",
    ]
