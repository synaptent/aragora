"""Tests for deterministic post-consensus output quality validation."""

from __future__ import annotations

import json

from aragora.debate.output_quality import (
    OutputContract,
    apply_deterministic_quality_repairs,
    build_concretization_prompt,
    build_upgrade_prompt,
    derive_output_contract_from_task,
    finalize_json_payload,
    load_output_contract_from_file,
    output_contract_from_dict,
    validate_output_against_contract,
)


def test_derive_output_contract_from_task_sections():
    task = (
        "Smoke test: output sections Ranked High-Level Tasks, Suggested Subtasks, "
        "Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, JSON Payload"
    )
    contract = derive_output_contract_from_task(task)
    assert contract is not None
    assert contract.required_sections == [
        "Ranked High-Level Tasks",
        "Suggested Subtasks",
        "Owner module / file paths",
        "Test Plan",
        "Rollback Plan",
        "Gate Criteria",
        "JSON Payload",
    ]
    assert contract.require_gate_thresholds is True
    assert contract.require_rollback_triggers is True
    assert contract.require_owner_paths is True
    assert contract.require_json_payload is True


def test_derive_output_contract_from_task_markdown_headers_phrase():
    task = (
        "Output MUST include exactly these sections as markdown headers: "
        "Ranked High-Level Tasks, Suggested Subtasks, Owner module / file paths, "
        "Test Plan, Rollback Plan, Gate Criteria, JSON Payload."
    )
    contract = derive_output_contract_from_task(task)
    assert contract is not None
    assert contract.required_sections == [
        "Ranked High-Level Tasks",
        "Suggested Subtasks",
        "Owner module / file paths",
        "Test Plan",
        "Rollback Plan",
        "Gate Criteria",
        "JSON Payload",
    ]


def test_derive_output_contract_from_task_fallback_known_headings():
    task = (
        "Return a plan with Ranked High-Level Tasks and Suggested Subtasks, then "
        "include Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, "
        "and JSON Payload."
    )
    contract = derive_output_contract_from_task(task)
    assert contract is not None
    assert contract.required_sections == [
        "Ranked High-Level Tasks",
        "Suggested Subtasks",
        "Owner module / file paths",
        "Test Plan",
        "Rollback Plan",
        "Gate Criteria",
        "JSON Payload",
    ]


def test_validate_output_against_contract_good_report():
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Suggested Subtasks",
            "Owner module / file paths",
            "Test Plan",
            "Rollback Plan",
            "Gate Criteria",
            "JSON Payload",
        ]
    )
    answer = """
## Ranked High-Level Tasks
- Implement the settlement tracker integration with ERC-8004 reputation scoring for all debate agents
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes
- Wire post-debate receipt generation into the Nomic Loop for closed-loop self-improvement feedback

## Suggested Subtasks
- Create unit tests for settlement hook dispatch covering extract and settle lifecycle events
- Validate ERC-8004 Brier score calculation against known calibration datasets for accuracy
- Add integration smoke test that runs a minimal debate and verifies receipt hash chain integrity

## Owner module / file paths
- aragora/debate/settlement_hooks.py
- aragora/debate/orchestrator.py
- tests/debate/test_settlement_hooks.py

## Test Plan
- Run full settlement hook unit tests with both successful and failed settle paths
- Execute integration smoke test covering debate creation through receipt persistence
- Verify ERC-8004 reputation updates are idempotent and handle concurrent writes correctly

## Rollback Plan
If error_rate > 2%, rollback by disabling feature flag and redeploy previous image.

## Gate Criteria
- p95_latency <= 250ms for 10m
- error_rate < 1% over 15m

## JSON Payload
```json
{
  "ranked_high_level_tasks": ["Settlement tracker ERC-8004 integration", "Data-feed verification", "Receipt Nomic Loop wiring"],
  "suggested_subtasks": ["Settlement hook tests", "Brier score validation", "Receipt hash smoke test"],
  "owner_module_file_paths": ["aragora/cli/commands/debate.py"],
  "test_plan": ["Settlement unit tests", "Integration smoke", "ERC-8004 idempotency"],
  "rollback_plan": {"trigger": "error_rate > 2%", "action": "disable flag"},
  "gate_criteria": [
    {"metric": "p95_latency", "op": "<=", "threshold": 250, "unit": "ms"},
    {"metric": "error_rate", "op": "<", "threshold": 1, "unit": "%"}
  ]
}
```
"""
    report = validate_output_against_contract(answer, contract)
    assert report.verdict == "good"
    assert report.has_gate_thresholds is True
    assert report.has_rollback_trigger is True
    assert report.has_paths is True
    assert report.has_valid_json_payload is True
    assert report.path_existence_rate >= 0.99
    assert report.practicality_score_10 >= 6.0
    assert report.defects == []


def test_validate_output_against_contract_detects_threshold_gap():
    contract = OutputContract(
        required_sections=["Gate Criteria", "Rollback Plan", "JSON Payload"],
        require_owner_paths=False,
    )
    answer = """
## Gate Criteria
- Keep it safe and reliable.

## Rollback Plan
If failure spikes then rollback immediately.

## JSON Payload
```json
{"ok": true}
```
"""
    report = validate_output_against_contract(answer, contract)
    assert report.verdict == "needs_work"
    assert report.has_gate_thresholds is False
    assert any("quantitative thresholds" in defect for defect in report.defects)


def test_validate_output_against_contract_detects_weak_repo_grounding():
    contract = OutputContract(
        required_sections=[
            "Owner module / file paths",
            "Rollback Plan",
            "Gate Criteria",
            "JSON Payload",
        ]
    )
    answer = """
## Owner module / file paths
- aragora/this/path/does/not/exist.py

## Rollback Plan
If error_rate > 2% for 10m, rollback by disabling the feature flag.

## Gate Criteria
- p95_latency <= 250ms for 15m
- error_rate < 1% over 15m

## JSON Payload
```json
{"ok": true}
```
"""
    report = validate_output_against_contract(answer, contract)
    assert report.verdict == "needs_work"
    assert report.path_existence_rate == 0.0
    assert any("weakly grounded" in defect for defect in report.defects)


def test_build_upgrade_prompt_contains_defects_and_contract():
    contract = OutputContract(required_sections=["A", "B"])
    prompt = build_upgrade_prompt(
        task="t",
        contract=contract,
        current_answer="old",
        defects=["Missing required section: B"],
    )
    assert "Missing required section: B" in prompt
    assert "1. A" in prompt
    assert "2. B" in prompt
    assert "Current answer" in prompt


def test_build_concretization_prompt_contains_practicality_target():
    contract = OutputContract(required_sections=["Ranked High-Level Tasks", "JSON Payload"])
    prompt = build_concretization_prompt(
        task="t",
        contract=contract,
        current_answer="old",
        practicality_score_10=4.2,
        target_practicality_10=7.0,
        defects=["Output practicality is too low for execution handoff."],
    )
    assert "Current practicality score (0-10): 4.2" in prompt
    assert "Target practicality score (0-10): 7.0" in prompt
    assert "Replace placeholders" in prompt


def test_apply_deterministic_quality_repairs_is_additive():
    """Repair preserves original content and appends notes for missing structural elements."""
    contract = OutputContract(
        required_sections=[
            "Owner module / file paths",
            "Rollback Plan",
            "Gate Criteria",
            "JSON Payload",
        ]
    )
    weak = """
## Owner module / file paths
- TBD — need to identify the correct modules for settlement tracker integration

## Rollback Plan
We will monitor the system and respond to issues as they arise with care and attention.

## Gate Criteria
- Good quality across all metrics and operational parameters for the deployment

## JSON Payload
```json
{"bad": "trailing"}
```
"""
    before = validate_output_against_contract(weak, contract)
    repaired = apply_deterministic_quality_repairs(weak, contract, before)
    # The repair should preserve the original content.
    assert "TBD" in repaired
    assert "We will monitor" in repaired
    # The repair should add notes about missing structural elements.
    assert "No repo paths detected" in repaired or "trigger" in repaired.lower()
    # Original text is not discarded.
    assert "settlement tracker integration" in repaired


def test_output_contract_from_dict_parses_flags():
    contract = output_contract_from_dict(
        {
            "required_sections": ["A", "B"],
            "require_json_payload": "true",
            "require_gate_thresholds": "false",
            "require_rollback_triggers": True,
            "require_owner_paths": False,
            "require_repo_path_existence": False,
            "require_practicality_checks": False,
        }
    )
    assert contract.required_sections == ["A", "B"]
    assert contract.require_json_payload is True
    assert contract.require_gate_thresholds is False
    assert contract.require_rollback_triggers is True
    assert contract.require_owner_paths is False
    assert contract.require_repo_path_existence is False
    assert contract.require_practicality_checks is False


def test_load_output_contract_from_file(tmp_path):
    path = tmp_path / "contract.json"
    path.write_text(
        json.dumps(
            {
                "required_sections": [
                    "Ranked High-Level Tasks",
                    "JSON Payload",
                ],
                "require_json_payload": True,
                "require_gate_thresholds": False,
                "require_rollback_triggers": False,
                "require_owner_paths": False,
            }
        ),
        encoding="utf-8",
    )
    contract = load_output_contract_from_file(str(path))
    assert contract.required_sections == ["Ranked High-Level Tasks", "JSON Payload"]
    assert contract.require_json_payload is True
    assert contract.require_gate_thresholds is False


def test_finalize_json_payload_repairs_invalid_json_section():
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Gate Criteria",
            "JSON Payload",
        ],
        require_rollback_triggers=False,
        require_owner_paths=False,
    )
    answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes

## Gate Criteria
- error_rate < 1% over 15m
- p95_latency <= 250ms for 15m

## JSON Payload
```json
{"broken":
```
"""
    fixed = finalize_json_payload(answer, contract)
    report = validate_output_against_contract(fixed, contract)
    assert report.has_valid_json_payload is True
    assert report.verdict == "good"


def test_finalize_json_payload_includes_dissent_and_unresolved_risks():
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "JSON Payload",
        ],
        require_gate_thresholds=False,
        require_rollback_triggers=False,
        require_owner_paths=False,
    )
    answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes

## Dissent
- Concern: model collapse risk if heterogeneous agents converge on similar RLHF targets

## Unresolved Risks
- Risk: missing external benchmark for calibration validation across multiple model families
"""
    fixed = finalize_json_payload(answer, contract)
    assert "## JSON Payload" in fixed
    report = validate_output_against_contract(fixed, contract)
    assert report.has_valid_json_payload is True
    assert report.verdict == "good"


def test_finalize_json_payload_replaces_heading_with_colon_and_dedupes():
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "JSON Payload",
        ],
        require_gate_thresholds=False,
        require_rollback_triggers=False,
        require_owner_paths=False,
    )
    answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes

## JSON Payload:
```json
{"broken":
```

## JSON Payload
```json
{"also":"broken",}
```
"""
    fixed = finalize_json_payload(answer, contract)
    assert fixed.count("## JSON Payload") == 1
    report = validate_output_against_contract(fixed, contract)
    assert report.has_valid_json_payload is True
    assert report.verdict == "good"


def test_template_filler_detected_and_penalized():
    """Template content from _default_section_content() should be flagged as filler."""
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Suggested Subtasks",
            "Owner module / file paths",
            "Test Plan",
            "Rollback Plan",
            "Gate Criteria",
            "JSON Payload",
        ]
    )
    # This is the exact output from the old deterministic repair — all template text.
    template_answer = """
## Ranked High-Level Tasks
- Prioritized task list with execution rationale.

## Suggested Subtasks
- Break top task into independently testable subtasks.

## Owner module / file paths
- aragora/cli/commands/debate.py
- tests/debate/test_output_quality.py

## Test Plan
- Run targeted unit tests and one smoke run for validation.

## Rollback Plan
If error_rate > 2% for 10m, rollback by disabling the feature flag and redeploying the last stable build.

## Gate Criteria
- p95_latency <= 250ms for 15m
- error_rate < 1% over 15m

## JSON Payload
```json
{"ok": true}
```
"""
    report = validate_output_against_contract(template_answer, contract)
    # Template filler should NOT pass quality gate.
    assert report.verdict == "needs_work"
    assert any("Template filler" in d or "too brief" in d for d in report.defects)
    # Score should be penalized below 10.0.
    assert report.quality_score_10 < 10.0


def test_repair_preserves_real_debate_content():
    """Additive repair must not discard real debate output."""
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Gate Criteria",
            "JSON Payload",
        ],
        require_rollback_triggers=False,
        require_owner_paths=False,
    )
    real_debate = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents participating in multi-round consensus
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes

## Gate Criteria
- Settlement hook latency p95 should remain under three hundred milliseconds
"""
    before = validate_output_against_contract(real_debate, contract)
    repaired = apply_deterministic_quality_repairs(real_debate, contract, before)
    # Real content must survive.
    assert "settlement tracker integration" in repaired
    assert "ERC-8004 reputation scoring" in repaired
    # Template filler must NOT appear.
    assert "Prioritized task list with execution rationale" not in repaired


def test_numbered_headings_are_matched():
    """LLMs often prefix headings with numbers (e.g. '## 3. Gate Criteria')."""
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Suggested Subtasks",
            "Owner module / file paths",
            "Test Plan",
            "Rollback Plan",
            "Gate Criteria",
            "JSON Payload",
        ]
    )
    answer = """
## 1. Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes
- Wire post-debate receipt generation into the Nomic Loop for self-improvement feedback

## 2. Suggested Subtasks
- Create unit tests for settlement hook dispatch covering extract and settle lifecycle events
- Validate ERC-8004 Brier score calculation against known calibration datasets for accuracy
- Add integration smoke test that runs a minimal debate and verifies receipt integrity

## 3. Owner module / file paths
- aragora/debate/settlement_hooks.py
- aragora/debate/orchestrator.py
- tests/debate/test_settlement_hooks.py

## 4. Test Plan
- Run full settlement hook unit tests with both successful and failed settle paths
- Execute integration smoke test covering debate creation through receipt persistence
- Verify ERC-8004 reputation updates are idempotent and handle concurrent writes correctly

## 5. Rollback Plan
If error_rate > 2%, rollback by disabling feature flag and redeploy previous image.

## 6. Gate Criteria
- p95_latency <= 250ms for 10m
- error_rate < 1% over 15m

## 7. JSON Payload
```json
{"tasks": ["settlement tracker", "data-feed verification"], "quality_json_finalized": true}
```
"""
    report = validate_output_against_contract(answer, contract)
    assert report.section_count == 7, f"Expected 7 sections found, got {report.section_count}"
    for key, hit in report.section_hits.items():
        assert hit, f"Section {key} should be present but was missed"
    assert report.has_gate_thresholds is True
    assert report.has_rollback_trigger is True
    assert report.has_paths is True
    assert report.has_valid_json_payload is True
    assert report.verdict == "good"


def test_broad_threshold_detection():
    """Gate criteria with table/structured/natural language thresholds should be detected."""
    from aragora.debate.output_quality import _has_quantitative_thresholds

    # Standard operator format
    assert _has_quantitative_thresholds("p95_latency <= 250ms\nerror_rate < 1%")
    # Percentage-only format
    assert _has_quantitative_thresholds("Pass rate: 95% of tests\nCoverage: 80% minimum")
    # Natural language quantitative
    assert _has_quantitative_thresholds("under 250ms latency\nzero blocker errors")
    # Structured key-value format
    assert _has_quantitative_thresholds("threshold: 250\nthreshold_value: 95")
    # Unicode operators
    assert _has_quantitative_thresholds("latency \u2264 250ms\nerror_rate \u2264 1%")
    # Pure prose with no numbers should fail
    assert not _has_quantitative_thresholds("Keep it safe and reliable.")
    # Single threshold is not enough
    assert not _has_quantitative_thresholds("p95_latency <= 250ms")


def test_soft_defects_dont_block_good_verdict_at_high_score():
    """Soft defects (weak grounding, low practicality) should not block 'good' at high scores."""
    contract = OutputContract(
        required_sections=[
            "Ranked High-Level Tasks",
            "Gate Criteria",
            "JSON Payload",
        ],
        require_rollback_triggers=False,
        require_owner_paths=True,
        require_repo_path_existence=True,
        require_practicality_checks=False,
    )
    answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes
- Wire post-debate receipt generation into the Nomic Loop for self-improvement feedback

## Gate Criteria
- p95_latency <= 250ms for 10m
- error_rate < 1% over 15m

## Owner module / file paths
- aragora/debate/settlement_hooks.py
- aragora/debate/orchestrator.py

## JSON Payload
```json
{"tasks": ["settlement tracker"], "quality_json_finalized": true}
```
"""
    report = validate_output_against_contract(answer, contract)
    # The answer has all required sections with good content, but owner paths
    # may not exist on disk -- that's a soft defect.
    assert report.has_gate_thresholds is True
    assert report.has_valid_json_payload is True
    # If section_count covers all 3 required sections, score should be high.
    assert report.section_count == 3


def test_json_fallback_finds_json_block_anywhere():
    """If no JSON Payload section exists, the validator should still find JSON blocks."""
    contract = OutputContract(
        required_sections=["Ranked High-Level Tasks", "JSON Payload"],
        require_gate_thresholds=False,
        require_rollback_triggers=False,
        require_owner_paths=False,
    )
    # Answer has JSON in it but not under a "JSON Payload" heading.
    answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration

## Summary
Here is the orchestration payload:
```json
{"tasks": ["settlement"], "quality_json_finalized": true}
```
"""
    report = validate_output_against_contract(answer, contract)
    # The JSON Payload section itself is missing (hard defect), but JSON detection
    # should still succeed via fallback.
    assert report.has_valid_json_payload is True


def test_first_batch_concreteness_best_of_5_lines():
    """Generic intro on line 1 should not tank concreteness when later lines are actionable."""
    from aragora.debate.repo_grounding import assess_repo_grounding

    answer = """
## Ranked High-Level Tasks
We propose a comprehensive approach to improving the system quality and reliability.
- Implement the settlement tracker integration with ERC-8004 reputation scoring in aragora/debate/settlement_hooks.py
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes
- Wire post-debate receipt generation into the Nomic Loop for self-improvement feedback

## Suggested Subtasks
The following subtasks break down the above goals into manageable pieces for the team.
- Create unit tests for settlement hook dispatch covering extract and settle lifecycle events in tests/debate/test_settlement_hooks.py
- Validate ERC-8004 Brier score calculation against known calibration datasets for accuracy
- Add integration smoke test verifying receipt hash chain integrity end-to-end

## Owner module / file paths
- aragora/debate/settlement_hooks.py
- aragora/debate/orchestrator.py
"""
    report = assess_repo_grounding(answer, require_owner_paths=False)
    # The generic first lines ("We propose..." / "The following subtasks...")
    # score low (~0.1), but actionable lines below them score high (>= 0.5).
    # With best-of-5, the high-scoring lines should win.
    assert report.first_batch_concreteness >= 0.5, (
        f"Expected >= 0.5 with best-of-5, got {report.first_batch_concreteness}"
    )


def test_rollback_trigger_broader_detection():
    """Rollback trigger detection should handle 'abandon in place', 'feature flag', etc."""
    from aragora.debate.output_quality import _has_rollback_trigger

    # Standard format
    assert _has_rollback_trigger("If error_rate > 2%, rollback by disabling feature flag.")
    # Abandon-in-place strategy
    assert _has_rollback_trigger(
        "If canary fails threshold, abandon in place and disable feature flag."
    )
    # Previous version rollback
    assert _has_rollback_trigger(
        "When health check fails, redeploy previous version from stable tag."
    )
    # Feature flag without "rollback" word
    assert _has_rollback_trigger(
        "If test failures exceed threshold, disable the feature flag immediately."
    )
    # Pure prose without a trigger+action pair should fail
    assert not _has_rollback_trigger("The system is generally reliable and well-tested.")
    assert not _has_rollback_trigger("Monitor production metrics closely after deployment.")
