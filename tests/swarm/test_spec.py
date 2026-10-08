"""Tests for SwarmSpec serialization and creation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from aragora.swarm.spec import SwarmSpec
from aragora.agents.semantic_extraction import ExtractionResult


class TestSwarmSpecCreation:
    """Test SwarmSpec construction and defaults."""

    def test_default_creation(self):
        spec = SwarmSpec()
        assert spec.id
        assert spec.created_at
        assert spec.estimated_complexity == "medium"
        assert spec.user_expertise == "non-developer"
        assert spec.budget_limit_usd == 5.0
        assert spec.requires_approval is False
        assert spec.acceptance_criteria == []
        assert spec.constraints == []
        assert spec.track_hints == []
        assert spec.file_scope_hints == []
        assert spec.work_orders == []
        assert spec.mission_id == ""
        assert spec.stage_id == ""
        assert spec.assertion_ids == []
        assert spec.roadmap_refs == []
        assert spec.evidence_expectations == []
        assert set(spec.mission_context_policies) == {"worker", "validator"}

    def test_creation_with_values(self):
        spec = SwarmSpec(
            raw_goal="Make it faster",
            refined_goal="Improve dashboard load time by 50%",
            acceptance_criteria=["Page loads in under 2 seconds"],
            constraints=["Don't modify the API"],
            budget_limit_usd=10.0,
            track_hints=["sme", "core"],
            work_orders=[{"work_order_id": "wo-1", "title": "lane"}],
            mission_id="mission-rs-01",
            stage_id="stage-rs-01",
            assertion_ids=["RS-01-ASSERT-1"],
            roadmap_refs=["RS-01"],
            evidence_expectations=["validation_command", "receipt"],
            estimated_complexity="high",
            requires_approval=True,
            user_expertise="developer",
        )
        assert spec.raw_goal == "Make it faster"
        assert spec.refined_goal == "Improve dashboard load time by 50%"
        assert len(spec.acceptance_criteria) == 1
        assert spec.budget_limit_usd == 10.0
        assert spec.track_hints == ["sme", "core"]
        assert spec.work_orders == [{"work_order_id": "wo-1", "title": "lane"}]
        assert spec.mission_id == "mission-rs-01"
        assert spec.stage_id == "stage-rs-01"
        assert spec.estimated_complexity == "high"
        assert spec.requires_approval is True


class TestSwarmSpecSerialization:
    """Test SwarmSpec serialization round-trips."""

    def test_to_dict_and_back(self):
        spec = SwarmSpec(
            raw_goal="Test goal",
            refined_goal="Refined test goal",
            acceptance_criteria=["Criterion 1", "Criterion 2"],
            constraints=["No breaking changes"],
            budget_limit_usd=7.50,
            track_hints=["qa"],
            mission_id="mission-rs-credential-envelope",
            stage_id="stage-contract-aware-preflight",
            assertion_ids=["RS-04-ASSERT-1"],
            roadmap_refs=["RS-04", "RS-05"],
            evidence_expectations=["validation_command", "worker_contract", "receipt"],
            work_orders=[
                {
                    "work_order_id": "docs-lane",
                    "title": "Write operator guide",
                    "file_scope": ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"],
                    "expected_tests": [],
                }
            ],
        )
        data = spec.to_dict()
        restored = SwarmSpec.from_dict(data)

        assert restored.raw_goal == spec.raw_goal
        assert restored.refined_goal == spec.refined_goal
        assert restored.acceptance_criteria == spec.acceptance_criteria
        assert restored.constraints == spec.constraints
        assert restored.budget_limit_usd == spec.budget_limit_usd
        assert restored.track_hints == spec.track_hints
        assert restored.work_orders == spec.work_orders
        assert restored.id == spec.id
        assert restored.mission_id == spec.mission_id
        assert restored.stage_id == spec.stage_id
        assert restored.assertion_ids == spec.assertion_ids
        assert restored.roadmap_refs == spec.roadmap_refs
        assert restored.evidence_expectations == spec.evidence_expectations
        assert set(restored.mission_context_policies) == {"worker", "validator"}

    def test_to_json_and_back(self):
        spec = SwarmSpec(
            raw_goal="JSON test",
            acceptance_criteria=["Works"],
        )
        json_str = spec.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["raw_goal"] == "JSON test"

        restored = SwarmSpec.from_json(json_str)
        assert restored.raw_goal == spec.raw_goal
        assert restored.acceptance_criteria == spec.acceptance_criteria

    def test_created_at_serializes_as_iso(self):
        spec = SwarmSpec(
            created_at=datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc),
        )
        data = spec.to_dict()
        assert "2026-02-26" in data["created_at"]

    def test_from_dict_ignores_unknown_fields(self):
        data = {"raw_goal": "test", "unknown_field": "ignored"}
        spec = SwarmSpec.from_dict(data)
        assert spec.raw_goal == "test"

    def test_to_yaml_fallback_to_json(self):
        """to_yaml falls back to JSON when pyyaml is unavailable."""
        spec = SwarmSpec(raw_goal="YAML test")
        result = spec.to_yaml()
        assert "YAML test" in result

    def test_from_yaml_fallback_to_json(self):
        """from_yaml can parse JSON as fallback."""
        spec = SwarmSpec(raw_goal="Parse test")
        json_str = spec.to_json()
        # from_yaml should handle JSON if yaml module gives a dict
        restored = SwarmSpec.from_yaml(json_str)
        assert restored.raw_goal == "Parse test"


class TestSwarmSpecSummary:
    """Test human-readable summary generation."""

    def test_summary_includes_goal(self):
        spec = SwarmSpec(refined_goal="Improve tests")
        summary = spec.summary()
        assert "Improve tests" in summary

    def test_summary_falls_back_to_raw_goal(self):
        spec = SwarmSpec(raw_goal="Raw goal text")
        summary = spec.summary()
        assert "Raw goal text" in summary

    def test_summary_includes_budget(self):
        spec = SwarmSpec(budget_limit_usd=15.0)
        summary = spec.summary()
        assert "$15.00" in summary

    def test_summary_includes_tracks(self):
        spec = SwarmSpec(track_hints=["qa", "core"])
        summary = spec.summary()
        assert "qa" in summary
        assert "core" in summary

    def test_summary_includes_explicit_work_order_count(self):
        spec = SwarmSpec(work_orders=[{"work_order_id": "docs-lane"}])
        summary = spec.summary()
        assert "Explicit work orders: 1" in summary

    def test_summary_includes_mission_and_stage(self):
        spec = SwarmSpec(
            mission_id="mission-rs-credential-envelope",
            stage_id="stage-contract-aware-preflight",
        )
        summary = spec.summary()
        assert "mission-rs-credential-envelope" in summary
        assert "stage-contract-aware-preflight" in summary


class TestSwarmSpecDispatchBounds:
    def test_empty_spec_is_not_dispatch_bounded(self):
        spec = SwarmSpec(raw_goal="Make it better")
        assert spec.is_dispatch_bounded() is False
        assert "under-specified" in spec.dispatch_gate_reason()

    def test_acceptance_criterion_makes_spec_dispatch_bounded(self):
        spec = SwarmSpec(raw_goal="Goal", acceptance_criteria=["Tests pass"])
        assert spec.is_dispatch_bounded() is True

    def test_file_scope_hint_makes_spec_dispatch_bounded(self):
        spec = SwarmSpec(raw_goal="Goal", file_scope_hints=["aragora/swarm/spec.py"])
        assert spec.is_dispatch_bounded() is True

    def test_direct_goal_builder_extracts_path_scope(self):
        spec = SwarmSpec.from_direct_goal(
            "Only touch aragora/swarm/spec.py and tests/swarm/test_spec.py",
            budget_limit_usd=5.0,
            requires_approval=False,
            user_expertise="developer",
            use_llm=False,
        )
        assert spec.is_dispatch_bounded() is True
        assert "aragora/swarm/spec.py" in spec.file_scope_hints


class TestSwarmSpecDirectGoalEnrichment:
    @pytest.mark.asyncio
    async def test_from_direct_goal_async_enriches_fields_from_llm(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")

        async def fake_extract(prompt, **kwargs):
            assert "dispatch-bounded swarm spec" in prompt
            normalized = kwargs["normalizer"](
                {
                    "refined_goal": "Tighten direct goal spec enrichment for skipped interrogation.",
                    "acceptance_criteria": ["Focused swarm spec tests pass."],
                    "constraints": ["Keep the heuristic fallback path intact."],
                    "track_hints": ["qa", "core", "invalid"],
                    "file_scope_hints": [
                        "ast.parse(open('aragora/swarm/spec.py').read())",
                        "tests/swarm/test_spec.py::test_from_direct_goal_async_enriches_fields_from_llm",
                    ],
                    "estimated_complexity": "high",
                }
            )
            return ExtractionResult(
                value=normalized,
                source="anthropic-api",
            )

        monkeypatch.setattr("aragora.swarm.spec.extract_json_object_llm_first", fake_extract)

        spec = await SwarmSpec.from_direct_goal_async(
            "Improve direct goal spec enrichment",
            budget_limit_usd=5.0,
            requires_approval=False,
            user_expertise="developer",
        )

        assert spec.refined_goal == "Tighten direct goal spec enrichment for skipped interrogation."
        assert spec.acceptance_criteria == ["Focused swarm spec tests pass."]
        assert spec.constraints == ["Keep the heuristic fallback path intact."]
        assert spec.track_hints == ["qa", "core"]
        assert spec.file_scope_hints == ["aragora/swarm/spec.py", "tests/swarm/test_spec.py"]
        assert spec.estimated_complexity == "high"

    @pytest.mark.asyncio
    async def test_from_direct_goal_async_falls_back_to_heuristics(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")

        async def fake_extract(_prompt, **kwargs):
            return ExtractionResult(
                value=None,
                source="anthropic-api",
                error="anthropic-api:invalid_json",
            )

        monkeypatch.setattr("aragora.swarm.spec.extract_json_object_llm_first", fake_extract)

        spec = await SwarmSpec.from_direct_goal_async(
            "Only touch aragora/swarm/spec.py. Done means validators pass.",
            budget_limit_usd=5.0,
            requires_approval=False,
            user_expertise="developer",
        )

        assert spec.refined_goal == "Only touch aragora/swarm/spec.py. Done means validators pass."
        assert "aragora/swarm/spec.py" in spec.file_scope_hints
        assert spec.acceptance_criteria == [
            "Only touch aragora/swarm/spec.py. Done means validators pass."
        ]

    @pytest.mark.asyncio
    async def test_from_direct_goal_sync_wrapper_skips_llm_inside_running_loop(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")

        async def fail_if_called(_prompt, **kwargs):
            raise AssertionError("LLM helper should not run inside an active event loop")

        monkeypatch.setattr("aragora.swarm.spec.extract_json_object_llm_first", fail_if_called)

        spec = SwarmSpec.from_direct_goal(
            "Only touch aragora/swarm/spec.py",
            budget_limit_usd=5.0,
            requires_approval=False,
            user_expertise="developer",
        )

        assert spec.refined_goal == "Only touch aragora/swarm/spec.py"
        assert spec.file_scope_hints == ["aragora/swarm/spec.py"]


class TestSwarmSpecFileScopeExtraction:
    def test_infer_file_scope_hints_extracts_embedded_repo_paths(self):
        text = (
            'Acceptance: run `python3 -c "import ast; '
            "ast.parse(open('aragora/connectors/chat/signal.py').read())\"` "
            "and validate against tests/connectors/chat/test_signal.py::test_parse."
        )
        hints = SwarmSpec.infer_file_scope_hints(text)

        assert "aragora/connectors/chat/signal.py" in hints
        assert "tests/connectors/chat/test_signal.py" in hints
        assert not any("ast.parse(open" in hint for hint in hints)

    def test_sanitize_file_scope_entry_strips_command_wrapper(self):
        raw = "ast.parse(open('aragora/connectors/ecommerce/shopify.py').read())"
        assert SwarmSpec.sanitize_file_scope_entry(raw) == "aragora/connectors/ecommerce/shopify.py"
