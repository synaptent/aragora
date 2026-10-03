"""Regression tests for the Opus 4.7+ provider-behaviour compat helpers.

These pin the two behaviours that broke call sites during the Opus 4.8 -> Opus 5
migration (PR #9588): sampling parameters are rejected with a 400, and the first
content block is a thinking block rather than a text block.
"""

from __future__ import annotations

import pytest

from aragora.models.compat import (
    first_text_block,
    rejects_sampling_params,
    strip_sampling_params,
)


class TestRejectsSamplingParams:
    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-opus-5",
            "anthropic/claude-opus-5",
            "claude-opus-5-fast",
            "claude-opus-4-8",
            "claude-opus-4.8",
            "anthropic/claude-opus-4.8",
            "claude-opus-4-7",
            "claude-sonnet-5",
            "claude-fable-5",
            "claude-mythos-5",
        ],
    )
    def test_modern_claude_models_reject(self, model_id: str) -> None:
        assert rejects_sampling_params(model_id) is True

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gpt-5.5",
            "gemini-3.1-pro",
            "mistral-large-2512",
        ],
    )
    def test_older_and_other_providers_still_accept(self, model_id: str) -> None:
        """Must not silently strip params from providers that accept them."""
        assert rejects_sampling_params(model_id) is False

    @pytest.mark.parametrize("model_id", [None, ""])
    def test_unknown_ids_fail_open(self, model_id: str | None) -> None:
        assert rejects_sampling_params(model_id) is False


class TestStripSamplingParams:
    def test_strips_all_three_on_modern_model(self) -> None:
        payload = {
            "model": "claude-opus-5",
            "max_tokens": 100,
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 5,
        }
        strip_sampling_params(payload, "claude-opus-5")
        assert "temperature" not in payload
        assert "top_p" not in payload
        assert "top_k" not in payload
        assert payload["max_tokens"] == 100, "must not disturb unrelated keys"

    def test_preserves_params_on_older_model(self) -> None:
        payload = {"model": "claude-opus-4-6", "temperature": 0.1, "top_p": 0.9}
        strip_sampling_params(payload, "claude-opus-4-6")
        assert payload["temperature"] == 0.1
        assert payload["top_p"] == 0.9

    def test_is_a_noop_when_params_absent(self) -> None:
        payload = {"model": "claude-opus-5", "max_tokens": 10}
        assert strip_sampling_params(payload, "claude-opus-5") == {
            "model": "claude-opus-5",
            "max_tokens": 10,
        }


class _Block:
    """Stand-in for an SDK content block."""

    def __init__(self, type_: str, text: str | None = None) -> None:
        self.type = type_
        if text is not None:
            self.text = text


class TestFirstTextBlock:
    def test_skips_leading_thinking_block_raw_json(self) -> None:
        """The exact shape that broke: thinking first, text second."""
        content = [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "the answer"},
        ]
        assert first_text_block(content) == "the answer"

    def test_skips_leading_thinking_block_sdk_objects(self) -> None:
        content = [_Block("thinking"), _Block("text", "the answer")]
        assert first_text_block(content) == "the answer"

    def test_plain_text_first_still_works(self) -> None:
        assert first_text_block([{"type": "text", "text": "hi"}]) == "hi"
        assert first_text_block([_Block("text", "hi")]) == "hi"

    def test_returns_first_text_block_when_several(self) -> None:
        content = [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]
        assert first_text_block(content) == "first"

    @pytest.mark.parametrize("content", [None, [], [{"type": "thinking", "thinking": ""}]])
    def test_returns_empty_string_rather_than_raising(self, content: object) -> None:
        """Callers rely on falsy-means-unusable; it must never raise."""
        assert first_text_block(content) == ""

    def test_accepts_untyped_block_carrying_text(self) -> None:
        """Hand-built/legacy payloads omit "type"; a block with a str "text" is
        unambiguously text (thinking blocks carry "thinking" instead)."""
        assert first_text_block([{"text": "legacy shape"}]) == "legacy shape"

    def test_untyped_text_still_loses_to_a_preceding_thinking_block(self) -> None:
        content = [{"type": "thinking", "thinking": "reasoning"}, {"text": "answer"}]
        assert first_text_block(content) == "answer"

    def test_thinking_block_is_never_mistaken_for_text(self) -> None:
        """A thinking block must not be returned even though it has content."""
        assert first_text_block([{"type": "thinking", "thinking": "secret reasoning"}]) == ""

    def test_accepts_test_double_whose_type_is_not_a_string(self) -> None:
        """MagicMock(text="yes") auto-creates a non-str .type; a block with no
        usable declared type but a str .text is the text block."""
        from unittest.mock import MagicMock

        assert first_text_block([MagicMock(text="yes")]) == "yes"

    def test_rejects_test_double_without_a_string_text(self) -> None:
        """A bare MagicMock has a MagicMock .text, which is not usable text."""
        from unittest.mock import MagicMock

        assert first_text_block([MagicMock()]) == ""

    def test_declared_non_text_type_wins_over_a_text_attribute(self) -> None:
        """A block that declares type="thinking" is skipped even if something
        put a str in .text — an explicit type is authoritative."""
        assert first_text_block([{"type": "thinking", "text": "leaked"}]) == ""

    def test_tolerates_tool_use_and_malformed_blocks(self) -> None:
        content = [
            {"type": "tool_use", "id": "x", "input": {}},
            {"type": "text"},  # no text key
            {"type": "text", "text": None},  # wrong type
            {"type": "text", "text": "good"},
        ]
        assert first_text_block(content) == "good"
