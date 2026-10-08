"""Tests for Oracle real-time streaming WebSocket endpoint.

Covers:
- SentenceAccumulator: boundary detection, flush, full_text
- OracleSession: default state, cancellation
- _handle_interim: think-while-listening prompt pre-building
- _stream_phase: streaming orchestration with sentence detection + TTS
- _stream_reflex / _stream_deep: provider fallback chains
- _stream_tentacles: parallel tentacle execution
- _handle_ask: full ask orchestration (reflex → deep → tentacles → synthesis)
- oracle_websocket_handler: WebSocket protocol (ask, interim, stop, ping, errors)
- _call_provider_llm_stream: provider dispatch routing
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.stream.oracle_stream import (
    OracleSession,
    SentenceAccumulator,
    _PHASE_TAG_DEEP,
    _PHASE_TAG_REFLEX,
    _REFLEX_PROMPT,
    _handle_interim,
)


# =========================================================================
# SentenceAccumulator
# =========================================================================


class TestSentenceAccumulator:
    """Test sentence boundary detection and accumulation."""

    def test_single_sentence(self):
        acc = SentenceAccumulator()
        result = acc.add("Hello world. ")
        assert result == "Hello world."

    def test_no_boundary_yet(self):
        acc = SentenceAccumulator()
        assert acc.add("Hello ") is None
        assert acc.add("world") is None

    def test_exclamation_boundary(self):
        acc = SentenceAccumulator()
        acc.add("Wow")
        result = acc.add("! ")
        assert result == "Wow!"

    def test_question_boundary(self):
        acc = SentenceAccumulator()
        acc.add("Really")
        result = acc.add("? ")
        assert result == "Really?"

    def test_multiple_sentences(self):
        acc = SentenceAccumulator()
        s1 = acc.add("First sentence. ")
        assert s1 == "First sentence."
        s2 = acc.add("Second sentence. ")
        assert s2 == "Second sentence."
        assert acc.full_text == "First sentence. Second sentence."

    def test_flush_remaining(self):
        acc = SentenceAccumulator()
        acc.add("Unfinished thought")
        assert acc.flush() == "Unfinished thought"

    def test_flush_empty(self):
        acc = SentenceAccumulator()
        assert acc.flush() is None

    def test_flush_after_complete_sentence(self):
        acc = SentenceAccumulator()
        acc.add("Done. ")
        assert acc.flush() is None

    def test_full_text_accumulates(self):
        acc = SentenceAccumulator()
        acc.add("A. ")
        acc.add("B. ")
        acc.add("C")
        acc.flush()
        assert acc.full_text == "A. B. C"

    def test_newline_as_boundary(self):
        acc = SentenceAccumulator()
        result = acc.add("End of line.\n")
        assert result == "End of line."

    def test_end_of_string_boundary(self):
        acc = SentenceAccumulator()
        # Period at end of string (no trailing space/newline) still matches
        result = acc.add("Final.")
        assert result == "Final."


# =========================================================================
# OracleSession
# =========================================================================


class TestOracleSession:
    """Test session state management."""

    def test_defaults(self):
        session = OracleSession()
        assert session.mode == "consult"
        assert session.last_interim == ""
        assert session.prebuilt_prompt is None
        assert session.active_task is None
        assert session.cancelled is False
        assert session.created_at > 0

    def test_cancellation(self):
        session = OracleSession()
        session.cancelled = True
        assert session.cancelled is True


# =========================================================================
# _handle_interim (think-while-listening)
# =========================================================================


class TestHandleInterim:
    """Test interim transcript processing."""

    def test_stores_interim_text(self):
        session = OracleSession()
        with patch(
            "aragora.server.stream.oracle_stream._build_oracle_prompt",
            return_value="built prompt",
        ):
            _handle_interim(session, "partial question")
        assert session.last_interim == "partial question"

    def test_prebuilds_prompt(self):
        session = OracleSession()
        with patch(
            "aragora.server.stream.oracle_stream._build_oracle_prompt",
            return_value="prebuilt",
        ):
            _handle_interim(session, "what is life")
        assert session.prebuilt_prompt == "prebuilt"


# =========================================================================
# _call_provider_llm_stream — provider dispatch
# =========================================================================


class TestProviderDispatch:
    """Test unified streaming LLM provider dispatch."""

    @pytest.mark.asyncio
    async def test_openrouter_dispatch(self):
        from aragora.server.stream.oracle_stream import _call_provider_llm_stream

        with patch(
            "aragora.server.stream.oracle_stream._stream_openrouter",
        ) as mock_or:

            async def fake_gen(*a, **kw):
                yield "token1"
                yield "token2"

            mock_or.return_value = fake_gen()

            tokens = []
            async for t in _call_provider_llm_stream("openrouter", "model", "prompt"):
                tokens.append(t)
            assert tokens == ["token1", "token2"]

    @pytest.mark.asyncio
    async def test_anthropic_dispatch(self):
        from aragora.server.stream.oracle_stream import _call_provider_llm_stream

        with patch(
            "aragora.server.stream.oracle_stream._stream_anthropic",
        ) as mock_anth:

            async def fake_gen(*a, **kw):
                yield "hello"

            mock_anth.return_value = fake_gen()

            tokens = []
            async for t in _call_provider_llm_stream("anthropic", "model", "prompt"):
                tokens.append(t)
            assert tokens == ["hello"]

    @pytest.mark.asyncio
    async def test_openai_dispatch_no_key(self):
        from aragora.server.stream.oracle_stream import _call_provider_llm_stream

        with patch("aragora.server.stream.oracle_stream._get_api_key", return_value=None):
            tokens = []
            async for t in _call_provider_llm_stream("openai", "model", "prompt"):
                tokens.append(t)
            assert tokens == []

    @pytest.mark.asyncio
    async def test_openai_dispatch_with_key(self):
        from aragora.server.stream.oracle_stream import _call_provider_llm_stream

        with (
            patch("aragora.server.stream.oracle_stream._get_api_key", return_value="sk-test"),
            patch(
                "aragora.server.stream.oracle_stream._stream_openai_compat",
            ) as mock_oai,
        ):

            async def fake_gen(*a, **kw):
                yield "oai-token"

            mock_oai.return_value = fake_gen()

            tokens = []
            async for t in _call_provider_llm_stream("openai", "gpt-4", "prompt"):
                tokens.append(t)
            assert tokens == ["oai-token"]

    @pytest.mark.asyncio
    async def test_xai_dispatch_with_key(self):
        from aragora.server.stream.oracle_stream import _call_provider_llm_stream

        with (
            patch("aragora.server.stream.oracle_stream._get_api_key", return_value="xai-key"),
            patch(
                "aragora.server.stream.oracle_stream._stream_openai_compat",
            ) as mock_xai,
        ):

            async def fake_gen(*a, **kw):
                yield "grok-token"

            mock_xai.return_value = fake_gen()

            tokens = []
            async for t in _call_provider_llm_stream("xai", "grok-2", "prompt"):
                tokens.append(t)
            assert tokens == ["grok-token"]


# =========================================================================
# _stream_phase — streaming orchestration
# =========================================================================


class TestStreamPhase:
    """Test the core phase streaming orchestration."""

    @pytest.mark.asyncio
    async def test_streams_tokens_and_sentences(self):
        from aragora.server.stream.oracle_stream import _stream_phase

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        async def fake_stream(*a, **kw):
            yield "Hello world. "
            yield "Done."

        with (
            patch(
                "aragora.server.stream.oracle_stream._call_provider_llm_stream",
                side_effect=fake_stream,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_tts",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_time_to_first_token",
            ) as mock_ttft,
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_stream_phase_duration",
            ) as mock_phase_duration,
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_stream_stall",
            ) as mock_stall,
        ):
            result = await _stream_phase(
                ws,
                "prompt",
                "deep",
                _PHASE_TAG_DEEP,
                session,
                provider="openrouter",
                model="test-model",
            )

        # Should have sent token events
        token_calls = [c for c in ws.send_json.call_args_list if c.args[0].get("type") == "token"]
        assert len(token_calls) >= 1

        # Should have sent phase_done
        phase_done_calls = [
            c for c in ws.send_json.call_args_list if c.args[0].get("type") == "phase_done"
        ]
        assert len(phase_done_calls) == 1
        assert phase_done_calls[0].args[0]["phase"] == "deep"
        mock_ttft.assert_called_once()
        mock_phase_duration.assert_called_once()
        mock_stall.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_waiting_first_token_stall_when_no_tokens(self):
        from aragora.server.stream.oracle_stream import _stream_phase

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        async def fake_stream(*a, **kw):
            if False:  # pragma: no cover
                yield "never"

        with (
            patch(
                "aragora.server.stream.oracle_stream._call_provider_llm_stream",
                side_effect=fake_stream,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_tts",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_stream_stall",
            ) as mock_stall,
        ):
            result = await _stream_phase(
                ws,
                "prompt",
                "deep",
                _PHASE_TAG_DEEP,
                session,
                provider="openrouter",
                model="test-model",
            )

        assert result == ""
        mock_stall.assert_called_with("waiting_first_token", phase="deep")

    @pytest.mark.asyncio
    async def test_respects_cancellation(self):
        from aragora.server.stream.oracle_stream import _stream_phase

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()
        session.cancelled = True

        async def fake_stream(*a, **kw):
            yield "token1"
            yield "token2"

        with (
            patch(
                "aragora.server.stream.oracle_stream._call_provider_llm_stream",
                side_effect=fake_stream,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_tts",
                new_callable=AsyncMock,
            ),
        ):
            result = await _stream_phase(
                ws,
                "prompt",
                "deep",
                _PHASE_TAG_DEEP,
                session,
                provider="openrouter",
                model="test-model",
            )

        # Should NOT have sent phase_done since cancelled
        phase_done_calls = [
            c
            for c in ws.send_json.call_args_list
            if c.args and c.args[0].get("type") == "phase_done"
        ]
        assert len(phase_done_calls) == 0

    @pytest.mark.asyncio
    async def test_respects_ws_closed(self):
        from aragora.server.stream.oracle_stream import _stream_phase

        ws = AsyncMock()
        ws.closed = True
        session = OracleSession()

        async def fake_stream(*a, **kw):
            yield "token"

        with (
            patch(
                "aragora.server.stream.oracle_stream._call_provider_llm_stream",
                side_effect=fake_stream,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_tts",
                new_callable=AsyncMock,
            ),
        ):
            result = await _stream_phase(
                ws,
                "prompt",
                "deep",
                _PHASE_TAG_DEEP,
                session,
                provider="openrouter",
                model="test-model",
            )

        # Should not send phase_done when ws is closed
        phase_done_calls = [
            c
            for c in ws.send_json.call_args_list
            if c.args and c.args[0].get("type") == "phase_done"
        ]
        assert len(phase_done_calls) == 0


# =========================================================================
# _stream_reflex — reflex phase with provider fallback
# =========================================================================


class TestStreamReflex:
    """Test the reflex (quick acknowledgment) phase."""

    @pytest.mark.asyncio
    async def test_uses_openrouter_when_available(self):
        from aragora.server.stream.oracle_stream import _stream_reflex

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                side_effect=lambda k: "key" if k == "OPENROUTER_API_KEY" else None,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_phase",
                new_callable=AsyncMock,
                return_value="Quick ack",
            ) as mock_phase,
        ):
            result = await _stream_reflex(ws, "test question", session)

        assert result == "Quick ack"
        # reflex_start should be sent
        ws.send_json.assert_any_call({"type": "reflex_start"})
        # Should use openrouter provider
        assert mock_phase.call_args.kwargs.get("provider") == "openrouter"

    @pytest.mark.asyncio
    async def test_falls_back_to_openai(self):
        from aragora.server.stream.oracle_stream import _stream_reflex

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                side_effect=lambda k: "key" if k == "OPENAI_API_KEY" else None,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_phase",
                new_callable=AsyncMock,
                return_value="OpenAI ack",
            ) as mock_phase,
        ):
            result = await _stream_reflex(ws, "test question", session)

        assert result == "OpenAI ack"
        assert mock_phase.call_args.kwargs.get("provider") == "openai"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_keys(self):
        from aragora.server.stream.oracle_stream import _stream_reflex

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with patch(
            "aragora.server.stream.oracle_stream._get_api_key",
            return_value=None,
        ):
            result = await _stream_reflex(ws, "test question", session)

        assert result == ""


# =========================================================================
# _stream_deep — deep phase with provider cascade
# =========================================================================


class TestStreamDeep:
    """Test the deep (full response) phase provider cascade."""

    @pytest.mark.asyncio
    async def test_tries_openrouter_first(self):
        from aragora.server.stream.oracle_stream import _stream_deep

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                return_value="key",
            ),
            patch(
                "aragora.server.stream.oracle_stream._get_oracle_models",
                return_value=("or-model", "anth-model", "oai-model"),
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_phase",
                new_callable=AsyncMock,
                return_value="Deep response",
            ) as mock_phase,
        ):
            result = await _stream_deep(ws, "prompt", session)

        assert result == "Deep response"
        assert mock_phase.call_args.kwargs.get("provider") == "openrouter"

    @pytest.mark.asyncio
    async def test_falls_back_to_anthropic(self):
        from aragora.server.stream.oracle_stream import _stream_deep

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        call_count = 0

        async def mock_stream_phase(ws, prompt, phase, tag, session, **kw):
            nonlocal call_count
            call_count += 1
            if kw.get("provider") == "openrouter":
                return ""  # OpenRouter returns empty
            return "Anthropic response"

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                return_value="key",
            ),
            patch(
                "aragora.server.stream.oracle_stream._get_oracle_models",
                return_value=("or-model", "anth-model", "oai-model"),
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_phase",
                side_effect=mock_stream_phase,
            ),
        ):
            result = await _stream_deep(ws, "prompt", session)

        assert result == "Anthropic response"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_keys(self):
        from aragora.server.stream.oracle_stream import _stream_deep

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                return_value=None,
            ),
            patch(
                "aragora.server.stream.oracle_stream._get_oracle_models",
                return_value=("or", "anth", "oai"),
            ),
        ):
            result = await _stream_deep(ws, "prompt", session)

        assert result == ""


# =========================================================================
# _stream_tentacles — parallel multi-model perspectives
# =========================================================================


class TestStreamTentacles:
    """Test parallel tentacle execution."""

    @pytest.mark.asyncio
    async def test_no_tentacles_when_no_models(self):
        from aragora.server.stream.oracle_stream import _stream_tentacles

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with patch(
            "aragora.server.stream.oracle_stream._get_tentacle_models",
            return_value=[],
        ):
            await _stream_tentacles(ws, "question", "consult", session)

        # No tentacle_start messages should be sent
        for call in ws.send_json.call_args_list:
            assert call.args[0].get("type") != "tentacle_start"

    @pytest.mark.asyncio
    async def test_streams_tentacle_tokens(self):
        from aragora.server.stream.oracle_stream import _stream_tentacles

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        models = [{"name": "Claude", "provider": "anthropic", "model": "claude-3"}]

        async def fake_stream(*a, **kw):
            yield "perspective "
            yield "text"

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_tentacle_models",
                return_value=models,
            ),
            patch(
                "aragora.server.stream.oracle_stream._build_oracle_prompt",
                return_value="prompt",
            ),
            patch(
                "aragora.server.stream.oracle_stream._call_provider_llm_stream",
                side_effect=fake_stream,
            ),
        ):
            await _stream_tentacles(ws, "question", "consult", session)

        # Should have sent tentacle_start
        start_calls = [
            c for c in ws.send_json.call_args_list if c.args[0].get("type") == "tentacle_start"
        ]
        assert len(start_calls) == 1
        assert start_calls[0].args[0]["agent"] == "Claude"

        # Should have sent tentacle_done
        done_calls = [
            c for c in ws.send_json.call_args_list if c.args[0].get("type") == "tentacle_done"
        ]
        assert len(done_calls) == 1
        assert "perspective" in done_calls[0].args[0]["full_text"]

    @pytest.mark.asyncio
    async def test_limits_to_5_tentacles(self):
        from aragora.server.stream.oracle_stream import _stream_tentacles

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        models = [
            {"name": f"Agent{i}", "provider": "openrouter", "model": f"model{i}"} for i in range(8)
        ]

        async def fake_stream(*a, **kw):
            yield "ok"

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_tentacle_models",
                return_value=models,
            ),
            patch(
                "aragora.server.stream.oracle_stream._build_oracle_prompt",
                return_value="prompt",
            ),
            patch(
                "aragora.server.stream.oracle_stream._call_provider_llm_stream",
                side_effect=fake_stream,
            ),
        ):
            await _stream_tentacles(ws, "question", "consult", session)

        # Should only start 5 tentacles (max)
        start_calls = [
            c for c in ws.send_json.call_args_list if c.args[0].get("type") == "tentacle_start"
        ]
        assert len(start_calls) == 5

    @pytest.mark.asyncio
    async def test_skips_when_cancelled(self):
        from aragora.server.stream.oracle_stream import _stream_tentacles

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()
        session.cancelled = True

        models = [{"name": "Agent", "provider": "openrouter", "model": "m"}]

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_tentacle_models",
                return_value=models,
            ),
            patch(
                "aragora.server.stream.oracle_stream._build_oracle_prompt",
                return_value="prompt",
            ),
        ):
            await _stream_tentacles(ws, "question", "consult", session)

        # No tentacle_done since cancelled before start
        done_calls = [
            c for c in ws.send_json.call_args_list if c.args[0].get("type") == "tentacle_done"
        ]
        assert len(done_calls) == 0


# =========================================================================
# _handle_ask — full orchestration
# =========================================================================


class TestHandleAsk:
    """Test the complete ask orchestration flow."""

    @pytest.mark.asyncio
    async def test_full_flow(self):
        from aragora.server.stream.oracle_stream import _handle_ask

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        with (
            patch(
                "aragora.server.stream.oracle_stream._stream_reflex",
                new_callable=AsyncMock,
                return_value="Quick response",
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_deep",
                new_callable=AsyncMock,
                return_value="Deep response",
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_tentacles",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.server.stream.oracle_stream._build_oracle_prompt",
                return_value="full prompt",
            ),
            patch(
                "aragora.server.stream.oracle_stream._get_tentacle_models",
                return_value=[],
            ),
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_session_outcome",
            ) as mock_outcome,
        ):
            await _handle_ask(ws, "What is life?", "consult", session)

        assert session.mode == "consult"

        # Should send synthesis at the end
        synthesis_calls = [
            c for c in ws.send_json.call_args_list if c.args[0].get("type") == "synthesis"
        ]
        assert len(synthesis_calls) == 1
        mock_outcome.assert_called_once_with("completed")

    @pytest.mark.asyncio
    async def test_uses_prebuilt_prompt(self):
        from aragora.server.stream.oracle_stream import _handle_ask

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()
        session.prebuilt_prompt = "prebuilt from interim"

        with (
            patch(
                "aragora.server.stream.oracle_stream._stream_reflex",
                new_callable=AsyncMock,
                return_value="",
            ) as mock_reflex,
            patch(
                "aragora.server.stream.oracle_stream._stream_deep",
                new_callable=AsyncMock,
                return_value="deep",
            ) as mock_deep,
            patch(
                "aragora.server.stream.oracle_stream._stream_tentacles",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.server.stream.oracle_stream._get_tentacle_models",
                return_value=[],
            ),
        ):
            await _handle_ask(ws, "What is life?", "consult", session)

        # Prebuilt prompt should be used for deep phase
        assert mock_deep.call_args.args[1] == "prebuilt from interim"
        # And consumed
        assert session.prebuilt_prompt is None

    @pytest.mark.asyncio
    async def test_stops_on_cancellation_after_reflex(self):
        from aragora.server.stream.oracle_stream import _handle_ask

        ws = AsyncMock()
        ws.closed = False
        session = OracleSession()

        async def cancel_after_reflex(*a, **kw):
            session.cancelled = True
            return "reflex"

        with (
            patch(
                "aragora.server.stream.oracle_stream._stream_reflex",
                side_effect=cancel_after_reflex,
            ),
            patch(
                "aragora.server.stream.oracle_stream._stream_deep",
                new_callable=AsyncMock,
            ) as mock_deep,
            patch(
                "aragora.server.stream.oracle_stream._build_oracle_prompt",
                return_value="prompt",
            ),
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_session_outcome",
            ) as mock_outcome,
        ):
            await _handle_ask(ws, "question", "consult", session)

        # Deep phase should NOT be called since cancelled
        mock_deep.assert_not_called()
        mock_outcome.assert_called_once_with("cancelled")


# =========================================================================
# oracle_websocket_handler — WebSocket protocol
# =========================================================================


def _make_ws_mock(messages):
    """Create a WebSocket mock that supports ``async for msg in ws``."""
    from aiohttp import WSMsgType

    ws = AsyncMock()
    ws.closed = False
    ws.prepare = AsyncMock()

    msg_objects = []
    for m in messages:
        msg = MagicMock()
        msg.type = WSMsgType.TEXT
        if isinstance(m, str):
            msg.data = m
        else:
            msg.data = json.dumps(m)
        msg_objects.append(msg)

    # Build a proper async iterator
    class _WSIter:
        def __init__(self):
            self._idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._idx >= len(msg_objects):
                raise StopAsyncIteration
            obj = msg_objects[self._idx]
            self._idx += 1
            return obj

    ws.__aiter__ = lambda self_: _WSIter()
    return ws


class TestOracleWebSocketHandler:
    """Test the WebSocket handler protocol."""

    @pytest.mark.asyncio
    async def test_ping_pong(self):
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = _make_ws_mock([{"type": "ping"}])

        request = MagicMock()
        with patch(
            "aragora.server.stream.oracle_stream.web.WebSocketResponse",
            return_value=ws,
        ):
            await oracle_websocket_handler(request)

        # Should have sent connected + pong
        sent_types = [c.args[0].get("type") for c in ws.send_json.call_args_list]
        assert "connected" in sent_types
        assert "pong" in sent_types

    @pytest.mark.asyncio
    async def test_invalid_json_error(self):
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = _make_ws_mock(["not json{{"])

        request = MagicMock()
        with patch(
            "aragora.server.stream.oracle_stream.web.WebSocketResponse",
            return_value=ws,
        ):
            await oracle_websocket_handler(request)

        error_calls = [c for c in ws.send_json.call_args_list if c.args[0].get("type") == "error"]
        assert len(error_calls) == 1
        assert "Invalid JSON" in error_calls[0].args[0]["message"]

    @pytest.mark.asyncio
    async def test_ask_missing_question(self):
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = _make_ws_mock([{"type": "ask", "question": "", "mode": "consult"}])

        request = MagicMock()
        with patch(
            "aragora.server.stream.oracle_stream.web.WebSocketResponse",
            return_value=ws,
        ):
            await oracle_websocket_handler(request)

        error_calls = [c for c in ws.send_json.call_args_list if c.args[0].get("type") == "error"]
        assert len(error_calls) == 1
        assert "Missing question" in error_calls[0].args[0]["message"]

    @pytest.mark.asyncio
    async def test_interim_updates_session(self):
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = _make_ws_mock([{"type": "interim", "text": "partial speech"}])

        request = MagicMock()
        with (
            patch(
                "aragora.server.stream.oracle_stream.web.WebSocketResponse",
                return_value=ws,
            ),
            patch(
                "aragora.server.stream.oracle_stream._handle_interim",
            ) as mock_interim,
        ):
            await oracle_websocket_handler(request)

        mock_interim.assert_called_once()
        assert mock_interim.call_args.args[1] == "partial speech"

    @pytest.mark.asyncio
    async def test_ask_records_session_started_metric(self):
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = _make_ws_mock([{"type": "ask", "question": "Where are we headed?", "mode": "consult"}])

        request = MagicMock()
        with (
            patch(
                "aragora.server.stream.oracle_stream.web.WebSocketResponse",
                return_value=ws,
            ),
            patch(
                "aragora.server.stream.oracle_stream._check_ws_rate_limit",
                return_value=(True, 0),
            ),
            patch(
                "aragora.server.stream.oracle_stream.record_oracle_session_started",
            ) as mock_started,
            patch(
                "aragora.server.stream.oracle_stream._handle_ask",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await oracle_websocket_handler(request)

        mock_started.assert_called_once()


# =========================================================================
# Helper functions
# =========================================================================


class TestHelpers:
    """Test helper functions."""

    def test_get_api_key_from_env(self):
        from aragora.server.stream.oracle_stream import _get_api_key

        with (
            patch.dict("os.environ", {"TEST_KEY": "test-value"}),
            patch(
                "aragora.server.stream.oracle_stream.get_secret",
                create=True,
                side_effect=ImportError,
            ),
        ):
            # Falls back to env when import fails
            with patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                wraps=_get_api_key,
            ):
                result = _get_api_key("TEST_KEY")
                assert result == "test-value"

    def test_reflex_prompt_template(self):
        prompt = _REFLEX_PROMPT.format(question="What is truth?")
        assert "What is truth?" in prompt
        assert "2-3 sentence" in prompt

    def test_get_oracle_models_fallback(self):
        from aragora.server.stream.oracle_stream import _get_oracle_models

        # When playground import fails, should return defaults
        with patch.dict("sys.modules", {"aragora.server.handlers.demo.playground": None}):
            # Force reimport path through ImportError
            models = _get_oracle_models()
            assert len(models) == 3

    def test_get_tentacle_models_fallback(self):
        from aragora.server.stream.oracle_stream import _get_tentacle_models

        with patch.dict("sys.modules", {"aragora.server.handlers.demo.playground": None}):
            models = _get_tentacle_models()
            assert isinstance(models, list)

    def test_build_oracle_prompt_fallback(self):
        from aragora.server.stream.oracle_stream import _build_oracle_prompt

        with patch.dict("sys.modules", {"aragora.server.handlers.demo.playground": None}):
            result = _build_oracle_prompt("consult", "test question")
            # Fallback returns just the question
            assert "test question" in result


# =========================================================================
# Route registration
# =========================================================================


class TestRouteRegistration:
    """Test route setup."""

    def test_register_routes(self):
        from aragora.server.stream.oracle_stream import (
            oracle_websocket_handler,
            register_oracle_stream_routes,
        )

        app = MagicMock()
        register_oracle_stream_routes(app)

        app.router.add_get.assert_called_once_with(
            "/ws/oracle",
            oracle_websocket_handler,
        )


# =========================================================================
# TTS streaming
# =========================================================================


class TestStreamTTS:
    """Test TTS audio streaming."""

    @pytest.mark.asyncio
    async def test_no_tts_without_key(self):
        from aragora.server.stream.oracle_stream import _stream_tts

        ws = AsyncMock()
        ws.closed = False

        with patch("aragora.server.stream.oracle_stream._get_api_key", return_value=None):
            await _stream_tts(ws, "Hello world", _PHASE_TAG_DEEP)

        # No bytes should be sent
        ws.send_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_stops_on_ws_closed(self):
        """TTS should not send bytes when WS is already closed."""
        from contextlib import asynccontextmanager

        from aragora.server.stream.oracle_stream import _stream_tts

        ws = AsyncMock()
        ws.closed = True

        mock_resp = MagicMock()
        mock_resp.status = 200

        async def _iter_chunked(size):
            yield b"audio-data"

        mock_resp.content.iter_chunked = _iter_chunked

        @asynccontextmanager
        async def _fake_post(*a, **kw):
            yield mock_resp

        @asynccontextmanager
        async def _fake_session():
            sess = MagicMock()
            sess.post = _fake_post
            yield sess

        with (
            patch(
                "aragora.server.stream.oracle_stream._get_api_key",
                return_value="el-key",
            ),
            patch(
                "aragora.server.stream.oracle_stream.aiohttp.ClientSession",
                side_effect=lambda: _fake_session(),
            ),
        ):
            await _stream_tts(ws, "Hello", _PHASE_TAG_DEEP)

        # ws.closed is True, so no bytes should be sent
        ws.send_bytes.assert_not_called()


# =========================================================================
# Feature flag — enable_oracle_streaming
# =========================================================================


class TestFeatureFlag:
    """Test enable_oracle_streaming feature flag toggling."""

    @pytest.mark.asyncio
    async def test_disabled_flag_rejects_connection(self):
        """When enable_oracle_streaming is False, connections get an error and close."""
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = AsyncMock()
        ws.closed = False
        ws.prepare = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()

        request = MagicMock()

        with (
            patch(
                "aragora.server.stream.oracle_stream.web.WebSocketResponse",
                return_value=ws,
            ),
            patch(
                "aragora.server.stream.oracle_stream._is_oracle_streaming_enabled",
                return_value=False,
            ),
        ):
            await oracle_websocket_handler(request)

        # Should have sent error and closed
        error_calls = [c for c in ws.send_json.call_args_list if c.args[0].get("type") == "error"]
        assert len(error_calls) == 1
        assert "disabled" in error_calls[0].args[0]["message"].lower()
        ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_enabled_flag_allows_connection(self):
        """When enable_oracle_streaming is True, connections proceed normally."""
        from aragora.server.stream.oracle_stream import oracle_websocket_handler

        ws = _make_ws_mock([{"type": "ping"}])

        request = MagicMock()

        with (
            patch(
                "aragora.server.stream.oracle_stream.web.WebSocketResponse",
                return_value=ws,
            ),
            patch(
                "aragora.server.stream.oracle_stream._is_oracle_streaming_enabled",
                return_value=True,
            ),
        ):
            await oracle_websocket_handler(request)

        # Should have sent connected (not error)
        sent_types = [c.args[0].get("type") for c in ws.send_json.call_args_list]
        assert "connected" in sent_types

    def test_flag_defaults_to_enabled_on_import_error(self):
        """When feature flag registry is unavailable, streaming defaults to enabled."""
        from aragora.server.stream.oracle_stream import _is_oracle_streaming_enabled

        with patch.dict("sys.modules", {"aragora.config.feature_flags": None}):
            # Force re-import to hit the ImportError path
            assert _is_oracle_streaming_enabled() is True

    def test_flag_reads_from_registry(self):
        """Feature flag reads from the registry when available."""
        from aragora.server.stream.oracle_stream import _is_oracle_streaming_enabled

        with patch(
            "aragora.config.feature_flags.is_enabled",
            return_value=False,
        ):
            assert _is_oracle_streaming_enabled() is False

        with patch(
            "aragora.config.feature_flags.is_enabled",
            return_value=True,
        ):
            assert _is_oracle_streaming_enabled() is True

    def test_flag_registered_in_registry(self):
        """The enable_oracle_streaming flag is registered in the feature flag registry."""
        from aragora.config.feature_flags import FeatureFlagRegistry

        registry = FeatureFlagRegistry()
        assert registry.is_registered("enable_oracle_streaming")
        flag = registry.get_definition("enable_oracle_streaming")
        assert flag is not None
        assert flag.default is True
        assert flag.flag_type is bool


# =========================================================================
# _get_oracle_models — ImportError fallback must mirror the primary path
# =========================================================================


class TestGetOracleModelsFallback:
    """Regression: a missing playground import must NOT silently swap the
    configured Anthropic model (Sonnet) for Opus in the deep-phase slot."""

    def test_primary_path_uses_configured_constants(self):
        """When playground imports succeed, the configured constants are returned."""
        from aragora.server.stream.oracle_stream import _get_oracle_models
        from aragora.server.handlers.playground import (
            _ORACLE_MODEL_OPENROUTER,
            _ORACLE_MODEL_ANTHROPIC,
            _ORACLE_MODEL_OPENAI,
        )

        assert _get_oracle_models() == (
            _ORACLE_MODEL_OPENROUTER,
            _ORACLE_MODEL_ANTHROPIC,
            _ORACLE_MODEL_OPENAI,
        )

    def test_importerror_fallback_matches_primary_anthropic_model(self):
        """ImportError fallback must return the SAME Anthropic model as the
        primary path — not swap Sonnet for Opus."""
        from aragora.server.handlers.playground import _ORACLE_MODEL_ANTHROPIC

        with patch.dict("sys.modules", {"aragora.server.handlers.demo.playground": None}):
            from aragora.server.stream.oracle_stream import _get_oracle_models

            _, anthropic_model, _ = _get_oracle_models()

        assert anthropic_model == _ORACLE_MODEL_ANTHROPIC
        # Defensive: the fallback must not silently select an Opus model in the
        # Anthropic deep-phase slot.
        assert "opus" not in anthropic_model.lower()

    def test_importerror_fallback_matches_all_primary_models(self):
        """The full fallback tuple mirrors the configured primary-path tuple."""
        from aragora.server.handlers.playground import (
            _ORACLE_MODEL_OPENROUTER,
            _ORACLE_MODEL_ANTHROPIC,
            _ORACLE_MODEL_OPENAI,
        )

        with patch.dict("sys.modules", {"aragora.server.handlers.demo.playground": None}):
            from aragora.server.stream.oracle_stream import _get_oracle_models

            fallback = _get_oracle_models()

        assert fallback == (
            _ORACLE_MODEL_OPENROUTER,
            _ORACLE_MODEL_ANTHROPIC,
            _ORACLE_MODEL_OPENAI,
        )
