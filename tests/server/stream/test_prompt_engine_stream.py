"""Tests for the prompt engine WebSocket stream handler."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.stream.prompt_engine_stream import (
    PromptEngineStreamClient,
    PromptEngineStreamEmitter,
    get_prompt_engine_emitter,
    set_prompt_engine_emitter,
)


# ---------------------------------------------------------------------------
# Emitter tests
# ---------------------------------------------------------------------------


class TestPromptEngineStreamEmitter:
    def test_add_and_remove_client(self) -> None:
        emitter = PromptEngineStreamEmitter()
        ws = MagicMock()
        client_id = emitter.add_client(ws, "session-1")

        assert emitter.client_count == 1
        emitter.remove_client(client_id)
        assert emitter.client_count == 0

    def test_remove_nonexistent_client(self) -> None:
        emitter = PromptEngineStreamEmitter()
        emitter.remove_client("does-not-exist")  # Should not raise
        assert emitter.client_count == 0

    @pytest.mark.asyncio
    async def test_emit_sends_to_matching_session(self) -> None:
        emitter = PromptEngineStreamEmitter()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        emitter.add_client(ws1, "session-a")
        emitter.add_client(ws2, "session-b")

        await emitter.emit("session-a", "prompt_engine_stage", {"stage": "decompose"})

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()

        # Verify message shape
        sent = ws1.send_json.call_args[0][0]
        assert sent["type"] == "prompt_engine_stage"
        assert sent["session_id"] == "session-a"
        assert sent["stage"] == "decompose"
        assert "timestamp" in sent

    @pytest.mark.asyncio
    async def test_emit_skips_different_session(self) -> None:
        emitter = PromptEngineStreamEmitter()
        ws = AsyncMock()
        emitter.add_client(ws, "session-x")

        await emitter.emit("session-y", "prompt_engine_start", {"prompt": "test"})
        ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnected_clients_are_cleaned_up(self) -> None:
        emitter = PromptEngineStreamEmitter()
        ws = AsyncMock()
        ws.send_json.side_effect = ConnectionError("disconnected")

        emitter.add_client(ws, "session-1")
        assert emitter.client_count == 1

        await emitter.emit("session-1", "prompt_engine_stage", {"stage": "decompose"})
        assert emitter.client_count == 0

    @pytest.mark.asyncio
    async def test_emit_multiple_clients_same_session(self) -> None:
        emitter = PromptEngineStreamEmitter()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        emitter.add_client(ws1, "shared")
        emitter.add_client(ws2, "shared")

        await emitter.emit("shared", "prompt_engine_complete", {"stages_completed": []})

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_creates_default_emitter(self) -> None:
        set_prompt_engine_emitter(None)  # type: ignore[arg-type]
        emitter = get_prompt_engine_emitter()
        assert isinstance(emitter, PromptEngineStreamEmitter)

    def test_set_replaces_emitter(self) -> None:
        custom = PromptEngineStreamEmitter()
        set_prompt_engine_emitter(custom)
        assert get_prompt_engine_emitter() is custom


# ---------------------------------------------------------------------------
# Pipeline execution (mocked)
# ---------------------------------------------------------------------------


class TestRunPipeline:
    @pytest.mark.asyncio
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    @patch("aragora.prompt_engine.SpecValidator")
    async def test_run_pipeline_emits_events(
        self,
        mock_validator_cls: MagicMock,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
    ) -> None:
        from aragora.server.stream.prompt_engine_stream import _run_pipeline

        # Set up mocks
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"intent_type": "feature"}
        mock_intent.needs_clarification = False

        mock_research = MagicMock()
        mock_research.to_dict.return_value = {"summary": "research"}

        mock_spec = MagicMock()
        mock_spec.to_dict.return_value = {"title": "Test"}

        conductor = mock_conductor_cls.return_value
        conductor.decompose_only = AsyncMock(return_value=mock_intent)
        conductor.research_only = AsyncMock(return_value=mock_research)
        conductor.specify_only = AsyncMock(return_value=mock_spec)

        config = MagicMock()
        config.skip_interrogation = False
        config.skip_research = False
        mock_config_cls.from_profile.return_value = config

        mock_validation = MagicMock()
        mock_validation.to_dict.return_value = {"passed": True}
        mock_validator_cls.return_value.validate_heuristic.return_value = mock_validation

        # Track emitted events
        emitter = PromptEngineStreamEmitter()
        events: list[tuple[str, str, dict[str, Any]]] = []
        original_emit = emitter.emit

        async def tracking_emit(session_id: str, event_type: str, data: dict[str, Any]) -> None:
            events.append((session_id, event_type, data))

        emitter.emit = tracking_emit  # type: ignore[assignment]

        await _run_pipeline(emitter, "test-session", "Build X", "founder", None)

        event_types = [e[1] for e in events]
        assert "prompt_engine_stage" in event_types
        assert "prompt_engine_intent" in event_types
        assert "prompt_engine_spec" in event_types
        assert "prompt_engine_validation" in event_types
        assert "prompt_engine_complete" in event_types

    @pytest.mark.asyncio
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    async def test_run_pipeline_emits_error_on_failure(
        self,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
    ) -> None:
        from aragora.server.stream.prompt_engine_stream import _run_pipeline

        conductor = mock_conductor_cls.return_value
        conductor.decompose_only = AsyncMock(side_effect=RuntimeError("boom"))
        mock_config_cls.from_profile.return_value = MagicMock()

        emitter = PromptEngineStreamEmitter()
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def tracking_emit(session_id: str, event_type: str, data: dict[str, Any]) -> None:
            events.append((session_id, event_type, data))

        emitter.emit = tracking_emit  # type: ignore[assignment]

        await _run_pipeline(emitter, "test-session", "fail", "founder", None)

        event_types = [e[1] for e in events]
        assert "prompt_engine_error" in event_types
        assert events[-1][2]["error"] == "Pipeline failed"


# ---------------------------------------------------------------------------
# Client dataclass
# ---------------------------------------------------------------------------


class TestPromptEngineStreamClient:
    def test_client_fields(self) -> None:
        ws = MagicMock()
        client = PromptEngineStreamClient(ws=ws, client_id="c1", session_id="s1")
        assert client.client_id == "c1"
        assert client.session_id == "s1"
        assert client.connected_at > 0
