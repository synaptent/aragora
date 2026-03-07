"""Tests for SwarmInterrogator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aragora.swarm.interrogator import (
    FALLBACK_QUESTIONS,
    SwarmInterrogator,
)
from aragora.swarm.config import InterrogatorConfig


class TestInterrogatorFallback:
    """Test fixed-question fallback mode."""

    @pytest.mark.asyncio
    async def test_fallback_questions_are_asked(self):
        """When no harness is available, fixed questions are asked."""
        answers = iter(["answer 1", "answer 2", "answer 3", "answer 4", "answer 5", "answer 6"])
        output: list[str] = []

        config = InterrogatorConfig(fallback_to_fixed_questions=True)
        interrogator = SwarmInterrogator(config=config)

        # Patch harness to return None (unavailable)
        with patch.object(interrogator, "_get_harness", return_value=None):
            spec = await interrogator.interrogate(
                "Make it better",
                input_fn=lambda _: next(answers),
                print_fn=lambda x: output.append(str(x)),
            )

        assert spec.raw_goal == "Make it better"
        assert spec.interrogation_turns > 0
        # Should have asked fallback questions
        assert any("figure out" in line.lower() for line in output)

    @pytest.mark.asyncio
    async def test_spec_has_correct_raw_goal(self):
        """The raw_goal should be preserved from the initial input."""
        config = InterrogatorConfig(fallback_to_fixed_questions=True)
        interrogator = SwarmInterrogator(config=config)

        with patch.object(interrogator, "_get_harness", return_value=None):
            spec = await interrogator.interrogate(
                "Fix the login page",
                input_fn=lambda _: "yes",
                print_fn=lambda _: None,
            )

        assert spec.raw_goal == "Fix the login page"

    @pytest.mark.asyncio
    async def test_heuristic_track_detection(self):
        """Heuristic extraction should detect track keywords."""
        config = InterrogatorConfig(fallback_to_fixed_questions=True)
        interrogator = SwarmInterrogator(config=config)

        with patch.object(interrogator, "_get_harness", return_value=None):
            spec = await interrogator.interrogate(
                "Improve test coverage and fix security issues",
                input_fn=lambda _: "testing and security",
                print_fn=lambda _: None,
            )

        assert "qa" in spec.track_hints or "security" in spec.track_hints

    @pytest.mark.asyncio
    async def test_empty_answers_are_skipped(self):
        """Empty answers should not contribute to conversation."""
        answers = iter(["", "", "", "", "", ""])
        config = InterrogatorConfig(fallback_to_fixed_questions=True)
        interrogator = SwarmInterrogator(config=config)

        with patch.object(interrogator, "_get_harness", return_value=None):
            spec = await interrogator.interrogate(
                "Test goal",
                input_fn=lambda _: next(answers),
                print_fn=lambda _: None,
            )

        # Spec should still be produced
        assert spec.raw_goal == "Test goal"


class TestInterrogatorJsonParsing:
    """Test JSON extraction from LLM responses."""

    def test_parse_clean_json(self):
        interrogator = SwarmInterrogator()
        result = interrogator._parse_json_from_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_in_markdown_block(self):
        interrogator = SwarmInterrogator()
        text = '```json\n{"key": "value"}\n```'
        result = interrogator._parse_json_from_response(text)
        assert result == {"key": "value"}

    def test_parse_json_with_surrounding_text(self):
        interrogator = SwarmInterrogator()
        text = 'Here is the spec:\n{"key": "value"}\nDone.'
        result = interrogator._parse_json_from_response(text)
        assert result == {"key": "value"}

    def test_parse_invalid_json_returns_none(self):
        interrogator = SwarmInterrogator()
        result = interrogator._parse_json_from_response("not json at all")
        assert result is None

    def test_parse_nested_json(self):
        interrogator = SwarmInterrogator()
        text = '{"outer": {"inner": "value"}, "list": [1, 2]}'
        result = interrogator._parse_json_from_response(text)
        assert result["outer"]["inner"] == "value"
        assert result["list"] == [1, 2]


class TestFallbackQuestions:
    """Test that fallback questions are well-formed."""

    def test_fallback_questions_exist(self):
        assert len(FALLBACK_QUESTIONS) >= 3

    def test_all_questions_end_with_punctuation(self):
        for q in FALLBACK_QUESTIONS:
            assert q.endswith(".") or q.endswith("?"), f"Question missing punctuation: {q}"


class TestInterrogatorInputSafety:
    """Test non-interactive / EOF-safe interrogation behavior."""

    @pytest.mark.asyncio
    async def test_eof_input_is_handled_gracefully(self):
        """EOF during questioning should still produce a usable spec."""
        interrogator = SwarmInterrogator(
            config=InterrogatorConfig(fallback_to_fixed_questions=True)
        )

        with patch.object(interrogator, "_get_harness", new=AsyncMock(return_value=None)):
            spec = await interrogator.interrogate(
                "Check dry-run plumbing",
                input_fn=lambda _prompt: (_ for _ in ()).throw(EOFError()),
                print_fn=lambda _msg: None,
            )

        assert spec.raw_goal == "Check dry-run plumbing"
        assert spec.refined_goal == "Check dry-run plumbing"
