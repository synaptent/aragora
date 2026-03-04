"""
Oracle Real-Time Streaming — WebSocket endpoint for the Shoggoth Oracle.

Replaces the batch request/response flow with streaming tokens and audio:
  1. Reflex phase: fast small-model acknowledgment (~2-3s)
  2. Deep phase: full essay-informed response with streaming TTS
  3. Tentacles: parallel multi-model perspectives
  4. Think-while-listening: pre-builds prompts from interim transcripts

Protocol:
  Client → Server (JSON text frames):
    {"type": "ask", "question": "...", "mode": "consult|divine|commune"}
    {"type": "interim", "text": "..."}   (partial speech transcript)
    {"type": "stop"}
    {"type": "ping"}

  Server → Client (JSON text frames):
    {"type": "connected"}
    {"type": "reflex_start"}
    {"type": "token", "text": "...", "phase": "reflex|deep", "sentence_complete": false}
    {"type": "sentence_ready", "text": "full sentence", "phase": "reflex|deep"}
    {"type": "phase_done", "phase": "reflex|deep", "full_text": "..."}
    {"type": "tentacle_start", "agent": "..."}
    {"type": "tentacle_token", "agent": "...", "text": "..."}
    {"type": "tentacle_done", "agent": "...", "full_text": "..."}
    {"type": "synthesis", "text": "..."}
    {"type": "error", "message": "..."}
    {"type": "pong"}

  Server → Client (binary frames):
    1-byte phase tag + raw mp3 chunk
    Phase tags: 0x00=reflex, 0x01=deep, 0x02=tentacle, 0x03=synthesis
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import aiohttp
from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)

try:
    from aragora.observability.metrics.oracle import (
        record_oracle_session_outcome,
        record_oracle_session_started,
        record_oracle_stream_phase_duration,
        record_oracle_stream_stall,
        record_oracle_time_to_first_token,
    )
except ImportError:
    # Metrics package is optional in some minimal deployments.
    def record_oracle_session_outcome(outcome: str) -> None:  # type: ignore[unused-ignore]
        del outcome

    def record_oracle_session_started() -> None:
        pass

    def record_oracle_stream_phase_duration(phase: str, duration_seconds: float) -> None:  # type: ignore[unused-ignore]
        del phase, duration_seconds

    def record_oracle_stream_stall(reason: str, *, phase: str = "unknown") -> None:  # type: ignore[unused-ignore]
        del reason, phase

    def record_oracle_time_to_first_token(phase: str, latency_seconds: float) -> None:  # type: ignore[unused-ignore]
        del phase, latency_seconds

# ---------------------------------------------------------------------------
# Constants — reuse from playground handler
# ---------------------------------------------------------------------------

_TTS_VOICE_ID = "flHkNRp1BlvT73UL6gyz"
_TTS_MODEL = "eleven_multilingual_v2"

# Per-tentacle TTS voices — each model gets a distinct voice
_TENTACLE_VOICES: dict[str, str] = {
    "claude": "flHkNRp1BlvT73UL6gyz",  # Deep, measured (default Oracle voice)
    "gpt": "pNInz6obpgDQGcFmaJgB",  # Adam - warm, authoritative
    "grok": "ErXwobaYiN019PkySvjV",  # Antoni - sharp, direct
    "deepseek": "VR6AewLTigWG4xSOukaG",  # Arnold - deep, deliberate
    "gemini": "21m00Tcm4TlvDq8ikWAM",  # Rachel - clear, analytical
    "mistral": "AZnzlk1XvdvUeBnXmlld",  # Domi - European, refined
}

_PHASE_TAG_REFLEX = 0x00
_PHASE_TAG_DEEP = 0x01
_PHASE_TAG_TENTACLE = 0x02
_PHASE_TAG_SYNTHESIS = 0x03

# Sentence boundary pattern: ends with . ! or ? followed by space, newline, or end
_SENTENCE_BOUNDARY = re.compile(r"[.!?](?:\s|\n|$)")

# Reflex model — fast, cheap, low-latency
_REFLEX_MODEL_OPENROUTER = "anthropic/claude-haiku-4-5-20251001"
_REFLEX_MODEL_OPENAI = "gpt-4o-mini"

# ---------------------------------------------------------------------------
# API key + model helpers (import from playground at runtime to avoid
# circular imports; fall back to env vars)
# ---------------------------------------------------------------------------


def _get_api_key(name: str) -> str | None:
    """Get an API key from secrets manager or env."""
    try:
        from aragora.config.secrets import get_secret

        return get_secret(name)
    except ImportError:
        return os.environ.get(name)


def _get_oracle_models() -> tuple[str, str, str]:
    """Return (openrouter_model, anthropic_model, openai_model) for deep phase."""
    try:
        from aragora.server.handlers.playground import (
            _ORACLE_MODEL_OPENROUTER,
            _ORACLE_MODEL_ANTHROPIC,
            _ORACLE_MODEL_OPENAI,
        )

        return _ORACLE_MODEL_OPENROUTER, _ORACLE_MODEL_ANTHROPIC, _ORACLE_MODEL_OPENAI
    except ImportError:
        return "anthropic/claude-opus-4.6", "claude-sonnet-4-6", "gpt-5.3"


def _get_tentacle_models() -> list[dict[str, str]]:
    """Return available tentacle model configs."""
    try:
        from aragora.server.handlers.playground import _get_available_tentacle_models

        return _get_available_tentacle_models()
    except ImportError:
        return []


def _build_oracle_prompt(
    mode: str,
    question: str,
    *,
    session_id: str | None = None,
) -> str:
    """Build the full Oracle prompt with essay context."""
    try:
        from aragora.server.handlers.playground import _build_oracle_prompt as _build

        return _build(mode, question, session_id=session_id)
    except ImportError:
        return question


def _sanitize_oracle_input(question: str) -> str:
    """Strip prompt injection attempts from user questions.

    Delegates to the canonical implementation in playground.py when
    available, falling back to a local re-implementation.
    """
    try:
        from aragora.server.handlers.playground import _sanitize_oracle_input as _sanitize

        return _sanitize(question)
    except ImportError:
        # Inline fallback — mirrors the playground implementation
        question = re.sub(
            r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|above|prior)", "", question
        )
        question = re.sub(r"(?i)you\s+are\s+now\s+", "", question)
        question = re.sub(r"(?i)system\s*:\s*", "", question)
        question = question[:2000]
        question = re.sub(
            r"</?(?:essay|system|assistant|user|instruction)[^>]*>",
            "",
            question,
            flags=re.IGNORECASE,
        )
        return question.strip()


def _filter_oracle_response(text: str) -> str:
    """Remove accidentally leaked sensitive content from streamed text.

    Delegates to the canonical implementation in playground.py when
    available, falling back to a local re-implementation.
    """
    try:
        from aragora.server.handlers.playground import _filter_oracle_response as _filter

        return _filter(text)
    except ImportError:
        text = re.sub(r"(?:sk-|key-|Bearer\s+)[a-zA-Z0-9_-]{20,}", "[REDACTED]", text)
        text = re.sub(
            r"(?i)(?:system prompt|my instructions|I was told to)", "my perspective", text
        )
        return text


# ---------------------------------------------------------------------------
# Session state for think-while-listening
# ---------------------------------------------------------------------------


@dataclass
class OracleSession:
    """Per-connection session state."""

    mode: str = "consult"
    last_interim: str = ""
    prebuilt_prompt: str | None = None
    active_task: asyncio.Task[Any] | None = None
    cancelled: bool = False
    completed: bool = False
    stream_error: bool = False
    created_at: float = field(default_factory=time.monotonic)
    debate_mode: bool = False  # True = run full multi-agent debate


# ---------------------------------------------------------------------------
# Streaming LLM — async generators yielding token strings
# ---------------------------------------------------------------------------

_SSE_DATA_PREFIX = "data: "


async def _stream_openrouter(
    model: str,
    prompt: str,
    max_tokens: int = 2000,
    timeout: float = 45.0,
) -> AsyncGenerator[str, None]:
    """Stream tokens from OpenRouter (OpenAI-compatible SSE)."""
    key = _get_api_key("OPENROUTER_API_KEY")
    if not key:
        return

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aragora.ai",
        "X-Title": "Aragora Oracle",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    logger.warning("OpenRouter stream error: %d", resp.status)
                    return
                async for line in resp.content:
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text.startswith(_SSE_DATA_PREFIX):
                        continue
                    data_str = text[len(_SSE_DATA_PREFIX) :]
                    if data_str == "[DONE]":
                        return
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("OpenRouter stream failed: %s", exc)


async def _stream_anthropic(
    model: str,
    prompt: str,
    max_tokens: int = 2000,
    timeout: float = 45.0,
) -> AsyncGenerator[str, None]:
    """Stream tokens from Anthropic Messages API (SSE)."""
    key = _get_api_key("ANTHROPIC_API_KEY")
    if not key:
        return

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Anthropic stream error: %d", resp.status)
                    return
                async for line in resp.content:
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text.startswith(_SSE_DATA_PREFIX):
                        continue
                    data_str = text[len(_SSE_DATA_PREFIX) :]
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            content = delta.get("text")
                            if content:
                                yield content
                    except (json.JSONDecodeError, KeyError):
                        continue
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("Anthropic stream failed: %s", exc)


async def _stream_openai_compat(
    base_url: str,
    key: str,
    model: str,
    prompt: str,
    max_tokens: int = 2000,
    timeout: float = 45.0,
) -> AsyncGenerator[str, None]:
    """Stream tokens from any OpenAI-compatible API (SSE)."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    logger.warning("OpenAI-compat stream error (%s): %d", base_url, resp.status)
                    return
                async for line in resp.content:
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text.startswith(_SSE_DATA_PREFIX):
                        continue
                    data_str = text[len(_SSE_DATA_PREFIX) :]
                    if data_str == "[DONE]":
                        return
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("OpenAI-compat stream failed (%s): %s", base_url, exc)


async def _call_provider_llm_stream(
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int = 2000,
    timeout: float = 45.0,
) -> AsyncGenerator[str, None]:
    """Unified streaming LLM dispatcher. Yields token strings."""
    if provider == "openrouter":
        async for token in _stream_openrouter(model, prompt, max_tokens, timeout):
            yield token
    elif provider == "anthropic":
        async for token in _stream_anthropic(model, prompt, max_tokens, timeout):
            yield token
    elif provider == "openai":
        key = _get_api_key("OPENAI_API_KEY")
        if key:
            async for token in _stream_openai_compat(
                "https://api.openai.com/v1", key, model, prompt, max_tokens, timeout
            ):
                yield token
    elif provider == "xai":
        key = _get_api_key("XAI_API_KEY")
        if key:
            async for token in _stream_openai_compat(
                "https://api.x.ai/v1", key, model, prompt, max_tokens, timeout
            ):
                yield token
    elif provider == "google":
        # Google doesn't support standard SSE — fall back to non-streaming
        try:
            from aragora.server.handlers.playground import _call_provider_llm

            result = await asyncio.to_thread(
                _call_provider_llm, provider, model, prompt, max_tokens, timeout
            )
            if result:
                yield result
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Streaming TTS — ElevenLabs chunked mp3
# ---------------------------------------------------------------------------


async def _stream_tts(
    ws: web.WebSocketResponse,
    text: str,
    phase_tag: int = _PHASE_TAG_DEEP,
    voice_id: str | None = None,
) -> None:
    """Stream TTS audio as binary WebSocket frames with phase tag prefix."""
    key = _get_api_key("ELEVENLABS_API_KEY")
    if not key:
        return

    effective_voice = voice_id or _TTS_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{effective_voice}/stream"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": _TTS_MODEL,
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.6,
            "use_speaker_boost": True,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning("ElevenLabs stream error: %d", resp.status)
                    return
                tag_byte = bytes([phase_tag])
                async for chunk in resp.content.iter_chunked(4096):
                    if ws.closed:
                        return
                    await ws.send_bytes(tag_byte + chunk)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("ElevenLabs stream failed: %s", exc)


# ---------------------------------------------------------------------------
# Sentence accumulator — detects boundaries and triggers TTS
# ---------------------------------------------------------------------------


class SentenceAccumulator:
    """Accumulates tokens and emits complete sentences."""

    def __init__(self) -> None:
        self._buffer = ""
        self._sentences: list[str] = []

    def add(self, token: str) -> str | None:
        """Add a token. Returns a complete sentence if boundary detected."""
        self._buffer += token
        match = _SENTENCE_BOUNDARY.search(self._buffer)
        if match:
            end = match.end()
            sentence = self._buffer[:end].strip()
            self._buffer = self._buffer[end:]
            if sentence:
                self._sentences.append(sentence)
                return sentence
        return None

    def flush(self) -> str | None:
        """Flush any remaining text as a final sentence."""
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining:
            self._sentences.append(remaining)
            return remaining
        return None

    @property
    def full_text(self) -> str:
        return " ".join(self._sentences)


# ---------------------------------------------------------------------------
# Reflex prompt — fast acknowledgment
# ---------------------------------------------------------------------------

_REFLEX_PROMPT = """You are the Oracle's quick-response system. Given the question below,
provide a 2-3 sentence immediate acknowledgment that shows you understand the question
and gives a preview of the direction you'll explore. Be warm, confident, and specific
to the question — never generic. Do NOT answer the full question.

Question: {question}"""


# ---------------------------------------------------------------------------
# Phase streaming functions
# ---------------------------------------------------------------------------


async def _stream_phase(
    ws: web.WebSocketResponse,
    prompt: str,
    phase: str,
    phase_tag: int,
    session: OracleSession,
    provider: str = "openrouter",
    model: str | None = None,
    max_tokens: int = 2000,
) -> str:
    """Stream an LLM response through the WebSocket, returning full text.

    Sends token events, sentence_ready events, and streams TTS per sentence.
    """
    if model is None:
        models = _get_oracle_models()
        model = models[0]  # openrouter default

    accumulator = SentenceAccumulator()
    tts_tasks: list[asyncio.Task[None]] = []
    t_start = time.monotonic()
    first_token_emitted = False
    first_audio_emitted = False

    async def _tts_with_latency(
        ws: web.WebSocketResponse,
        text: str,
        tag: int,
        voice_id: str | None = None,
    ) -> None:
        nonlocal first_audio_emitted
        await _stream_tts(ws, text, tag, voice_id=voice_id)
        if not first_audio_emitted:
            first_audio_emitted = True
            ttfa = time.monotonic() - t_start
            logger.info(
                "[Oracle Latency] phase=%s time_to_first_audio=%.3fs",
                phase,
                ttfa,
            )

    async for token in _call_provider_llm_stream(provider, model, prompt, max_tokens):
        if session.cancelled or ws.closed:
            break

        if not first_token_emitted:
            first_token_emitted = True
            ttft = time.monotonic() - t_start
            logger.info(
                "[Oracle Latency] phase=%s time_to_first_token=%.3fs",
                phase,
                ttft,
            )
            record_oracle_time_to_first_token(phase, ttft)

        # Send token event
        await ws.send_json(
            {
                "type": "token",
                "text": token,
                "phase": phase,
                "sentence_complete": False,
            }
        )

        # Check for complete sentence
        sentence = accumulator.add(token)
        if sentence:
            await ws.send_json(
                {
                    "type": "sentence_ready",
                    "text": sentence,
                    "phase": phase,
                }
            )
            # Stream TTS for this sentence (fire and forget, bounded)
            task = asyncio.create_task(_tts_with_latency(ws, sentence, phase_tag))
            tts_tasks.append(task)

    # Flush remaining text
    remainder = accumulator.flush()
    if remainder and not session.cancelled and not ws.closed:
        await ws.send_json(
            {
                "type": "sentence_ready",
                "text": remainder,
                "phase": phase,
            }
        )
        task = asyncio.create_task(_tts_with_latency(ws, remainder, phase_tag))
        tts_tasks.append(task)

    # Wait for all TTS to finish
    if tts_tasks:
        await asyncio.gather(*tts_tasks, return_exceptions=True)

    total_elapsed = time.monotonic() - t_start
    record_oracle_stream_phase_duration(phase, total_elapsed)
    full_text = _filter_oracle_response(accumulator.full_text)

    if not first_token_emitted and not session.cancelled and not ws.closed:
        record_oracle_stream_stall("waiting_first_token", phase=phase)
    elif first_token_emitted and (session.cancelled or ws.closed):
        record_oracle_stream_stall("stream_inactive", phase=phase)

    if not session.cancelled and not ws.closed:
        await ws.send_json(
            {
                "type": "phase_done",
                "phase": phase,
                "full_text": full_text,
                "latency_ms": round(total_elapsed * 1000),
            }
        )

    return full_text


async def _stream_reflex(
    ws: web.WebSocketResponse,
    question: str,
    session: OracleSession,
) -> str:
    """Stream the reflex (quick acknowledgment) phase."""
    await ws.send_json({"type": "reflex_start"})

    prompt = _REFLEX_PROMPT.format(question=question)

    # Try OpenRouter with Haiku first, then OpenAI mini
    key_or = _get_api_key("OPENROUTER_API_KEY")
    if key_or:
        return await _stream_phase(
            ws,
            prompt,
            "reflex",
            _PHASE_TAG_REFLEX,
            session,
            provider="openrouter",
            model=_REFLEX_MODEL_OPENROUTER,
            max_tokens=300,
        )

    key_oai = _get_api_key("OPENAI_API_KEY")
    if key_oai:
        return await _stream_phase(
            ws,
            prompt,
            "reflex",
            _PHASE_TAG_REFLEX,
            session,
            provider="openai",
            model=_REFLEX_MODEL_OPENAI,
            max_tokens=300,
        )

    return ""


async def _stream_deep(
    ws: web.WebSocketResponse,
    prompt: str,
    session: OracleSession,
) -> str:
    """Stream the deep (full response) phase."""
    or_model, anth_model, oai_model = _get_oracle_models()

    # Try OpenRouter → Anthropic → OpenAI
    if _get_api_key("OPENROUTER_API_KEY"):
        result = await _stream_phase(
            ws,
            prompt,
            "deep",
            _PHASE_TAG_DEEP,
            session,
            provider="openrouter",
            model=or_model,
            max_tokens=2000,
        )
        if result:
            return result

    if _get_api_key("ANTHROPIC_API_KEY"):
        result = await _stream_phase(
            ws,
            prompt,
            "deep",
            _PHASE_TAG_DEEP,
            session,
            provider="anthropic",
            model=anth_model,
            max_tokens=2000,
        )
        if result:
            return result

    if _get_api_key("OPENAI_API_KEY"):
        return await _stream_phase(
            ws,
            prompt,
            "deep",
            _PHASE_TAG_DEEP,
            session,
            provider="openai",
            model=oai_model,
            max_tokens=2000,
        )

    return ""


async def _stream_tentacles(
    ws: web.WebSocketResponse,
    question: str,
    mode: str,
    session: OracleSession,
) -> None:
    """Stream tentacle perspectives from multiple models in parallel."""
    models = _get_tentacle_models()
    if not models:
        return

    # Try to import tentacle-specific prompt builder and roles
    try:
        from aragora.server.handlers.playground import (
            _build_tentacle_prompt,
            _TENTACLE_ROLE_PROMPTS,
        )

        has_tentacle_prompts = True
    except ImportError:
        has_tentacle_prompts = False

    # Fallback prompt (used when tentacle prompt imports fail)
    fallback_prompt = _build_oracle_prompt(mode, question)

    async def run_tentacle(m: dict[str, str], role_idx: int) -> None:
        name = m["name"]
        if session.cancelled or ws.closed:
            return

        # Build model-specific tentacle prompt with role and model name
        if has_tentacle_prompts:
            role = _TENTACLE_ROLE_PROMPTS[role_idx % len(_TENTACLE_ROLE_PROMPTS)]
            tent_prompt = _build_tentacle_prompt(
                mode,
                question,
                role,
                source="oracle",
                model_name=name,
            )
            # Append model identity so the LLM knows which perspective it represents
            tent_prompt += f"\n\nYou are responding as the {name} model."
        else:
            tent_prompt = fallback_prompt

        # Select per-model TTS voice
        voice_key = name.lower().split("-")[0].split("/")[-1]
        voice_id = _TENTACLE_VOICES.get(voice_key)

        await ws.send_json({"type": "tentacle_start", "agent": name})

        accumulator = SentenceAccumulator()
        tts_tasks: list[asyncio.Task[None]] = []
        full_text = ""
        try:
            async for token in _call_provider_llm_stream(
                m["provider"],
                m["model"],
                tent_prompt,
                max_tokens=1000,
                timeout=30.0,
            ):
                if session.cancelled or ws.closed:
                    return
                full_text += token
                await ws.send_json(
                    {
                        "type": "tentacle_token",
                        "agent": name,
                        "text": token,
                    }
                )

                # Stream TTS per sentence with the tentacle's voice
                sentence = accumulator.add(token)
                if sentence and voice_id:
                    task = asyncio.create_task(
                        _stream_tts(ws, sentence, _PHASE_TAG_TENTACLE, voice_id=voice_id)
                    )
                    tts_tasks.append(task)
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            ConnectionError,
            TimeoutError,
        ):
            logger.warning("Tentacle %s failed", name, exc_info=True)

        # Flush remaining sentence for TTS
        remainder = accumulator.flush()
        if remainder and voice_id and not session.cancelled and not ws.closed:
            task = asyncio.create_task(
                _stream_tts(ws, remainder, _PHASE_TAG_TENTACLE, voice_id=voice_id)
            )
            tts_tasks.append(task)

        # Wait for TTS to finish for this tentacle
        if tts_tasks:
            await asyncio.gather(*tts_tasks, return_exceptions=True)

        if full_text and not session.cancelled and not ws.closed:
            await ws.send_json(
                {
                    "type": "tentacle_done",
                    "agent": name,
                    "full_text": _filter_oracle_response(full_text),
                }
            )

    # Run tentacles concurrently (max 5)
    tasks = [asyncio.create_task(run_tentacle(m, i)) for i, m in enumerate(models[:5])]
    await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Main ask handler — orchestrates reflex → deep → tentacles
# ---------------------------------------------------------------------------


async def _handle_ask(
    ws: web.WebSocketResponse,
    question: str,
    mode: str,
    session: OracleSession,
    *,
    session_id: str | None = None,
    summary_depth: str = "light",
) -> None:
    """Handle a complete Oracle consultation."""
    session.mode = mode
    session.cancelled = False
    session.completed = False
    session.stream_error = False

    try:
        # Start reflex immediately + build deep prompt concurrently
        reflex_task = asyncio.create_task(_stream_reflex(ws, question, session))

        # Use prebuilt prompt from interim if available, otherwise build now
        deep_prompt = session.prebuilt_prompt or _build_oracle_prompt(
            mode,
            question,
            session_id=session_id,
        )
        session.prebuilt_prompt = None  # consumed

        await reflex_task

        if session.cancelled:
            return

        # Stream deep response
        await _stream_deep(ws, deep_prompt, session)

        if session.cancelled:
            return

        # Stream tentacles
        await _stream_tentacles(ws, question, mode, session)

        if session.cancelled or ws.closed:
            return

        # Send synthesis summary
        synthesis = (
            f"The Oracle has spoken. {len(_get_tentacle_models())} perspectives weighed. "
            f"The deep analysis is complete."
        )
        await ws.send_json({"type": "synthesis", "text": synthesis})
        session.completed = True
    except asyncio.CancelledError:
        session.cancelled = True
        raise
    except (
        RuntimeError,
        ValueError,
        TypeError,
        OSError,
        KeyError,
        AttributeError,
        ConnectionError,
        TimeoutError,
    ):
        session.stream_error = True
        logger.exception("Oracle consultation failed", exc_info=True)
        raise
    finally:
        if session.completed:
            record_oracle_session_outcome("completed")
        elif session.cancelled:
            record_oracle_session_outcome("cancelled")
        else:
            record_oracle_session_outcome("error")


# ---------------------------------------------------------------------------
# Debate streaming bridge — runs a real multi-agent debate and streams events
# ---------------------------------------------------------------------------

# Optional imports for debate mode (graceful degradation)
try:
    from aragora.server.stream.debate_executor import execute_debate_thread, DEBATE_AVAILABLE
    from aragora.server.stream.emitter import SyncEventEmitter
    from aragora.server.stream.tts_integration import get_tts_integration

    _DEBATE_STREAMING_AVAILABLE = DEBATE_AVAILABLE
except ImportError:
    _DEBATE_STREAMING_AVAILABLE = False


async def _drain_emitter_to_ws(
    ws: web.WebSocketResponse,
    emitter: Any,
    session: OracleSession,
    debate_id: str,
) -> None:
    """Drain events from a SyncEventEmitter and forward them to the WebSocket.

    Translates debate events (DEBATE_START, AGENT_MESSAGE, CRITIQUE, VOTE,
    CONSENSUS, DEBATE_END, etc.) into Oracle-protocol JSON frames so the
    frontend can render them progressively.

    Also emits ``tts_hook`` events for sentence boundaries so the TTS
    integration can synthesize audio as text streams in.
    """
    tts_integration = None
    try:
        tts_integration = get_tts_integration()
    except (ImportError, NameError):
        pass

    while not session.cancelled and not ws.closed:
        events = emitter.drain(max_batch_size=50)
        if not events:
            # Check if debate completed by looking at the state
            await asyncio.sleep(0.05)
            continue

        for event in events:
            if session.cancelled or ws.closed:
                return

            event_dict = event.to_dict()
            event_type = event_dict.get("type", "")
            data = event_dict.get("data", {})
            agent = event_dict.get("agent", "")

            try:
                if event_type == "debate_start":
                    await ws.send_json(
                        {
                            "type": "debate_start",
                            "debate_id": debate_id,
                            "task": data.get("task", ""),
                            "agents": data.get("agents", []),
                        }
                    )

                elif event_type == "round_start":
                    await ws.send_json(
                        {
                            "type": "round_start",
                            "round": data.get("round", 0),
                        }
                    )

                elif event_type == "agent_message":
                    content = data.get("content", "")
                    role = data.get("role", "proposer")
                    await ws.send_json(
                        {
                            "type": "agent_message",
                            "agent": agent,
                            "content": content,
                            "role": role,
                            "round": event_dict.get("round", 0),
                            "confidence_score": data.get("confidence_score"),
                        }
                    )

                    # TTS hook: emit event for audio synthesis
                    if tts_integration and tts_integration.is_available and content:
                        await ws.send_json(
                            {
                                "type": "tts_hook",
                                "agent": agent,
                                "text": content[:2000],
                                "debate_id": debate_id,
                            }
                        )

                elif event_type == "agent_thinking":
                    await ws.send_json(
                        {
                            "type": "agent_thinking",
                            "agent": agent,
                            "step": data.get("step", ""),
                            "phase": data.get("phase", "reasoning"),
                        }
                    )

                elif event_type == "critique":
                    await ws.send_json(
                        {
                            "type": "critique",
                            "agent": agent,
                            "target": data.get("target", ""),
                            "issues": data.get("issues", []),
                            "severity": data.get("severity", 0.0),
                            "content": data.get("content", ""),
                            "round": event_dict.get("round", 0),
                        }
                    )

                elif event_type == "vote":
                    await ws.send_json(
                        {
                            "type": "vote",
                            "agent": agent,
                            "vote": data.get("vote", ""),
                            "confidence": data.get("confidence", 0.0),
                        }
                    )

                elif event_type == "consensus":
                    await ws.send_json(
                        {
                            "type": "consensus",
                            "reached": data.get("reached", False),
                            "confidence": data.get("confidence", 0.0),
                            "answer": data.get("answer", ""),
                            "synthesis": data.get("synthesis", ""),
                        }
                    )

                elif event_type == "debate_end":
                    await ws.send_json(
                        {
                            "type": "debate_end",
                            "duration": data.get("duration", 0.0),
                            "rounds": data.get("rounds", 0),
                        }
                    )
                    return  # Debate complete

                elif event_type == "phase_progress":
                    await ws.send_json(
                        {
                            "type": "phase_progress",
                            "phase": data.get("phase", ""),
                            "completed": data.get("completed", 0),
                            "total": data.get("total", 0),
                            "current_agent": data.get("current_agent", ""),
                        }
                    )

                elif event_type == "agent_error":
                    await ws.send_json(
                        {
                            "type": "agent_error",
                            "agent": agent,
                            "error_type": data.get("error_type", "unknown"),
                            "message": data.get("message", ""),
                            "recoverable": data.get("recoverable", True),
                        }
                    )

                elif event_type == "token_start":
                    await ws.send_json(
                        {
                            "type": "token_start",
                            "agent": agent,
                        }
                    )

                elif event_type == "token_delta":
                    await ws.send_json(
                        {
                            "type": "token_delta",
                            "agent": agent,
                            "token": data.get("token", ""),
                        }
                    )

                elif event_type == "token_end":
                    await ws.send_json(
                        {
                            "type": "token_end",
                            "agent": agent,
                            "full_response": data.get("full_response", ""),
                        }
                    )

                elif event_type == "error":
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": data.get("error", "Debate error"),
                        }
                    )
                    return  # Fatal error

                elif event_type == "synthesis":
                    await ws.send_json(
                        {
                            "type": "synthesis",
                            "text": data.get("content", ""),
                            "agent": data.get("agent", "synthesis-agent"),
                            "confidence": data.get("confidence", 0.0),
                        }
                    )

                elif event_type == "heartbeat":
                    await ws.send_json(
                        {
                            "type": "heartbeat",
                            "phase": data.get("phase", ""),
                            "status": data.get("status", "alive"),
                        }
                    )

            except (ConnectionError, OSError, RuntimeError) as exc:
                logger.warning("Failed to send debate event to Oracle WS: %s", exc)
                return


async def _handle_debate(
    ws: web.WebSocketResponse,
    question: str,
    mode: str,
    session: OracleSession,
    *,
    session_id: str | None = None,
) -> None:
    """Handle an Oracle consultation using a full multi-agent debate.

    Instead of direct LLM calls, this runs a real debate via the Arena engine
    and streams events (agent_message, critique, vote, consensus) in real time.
    """
    if not _DEBATE_STREAMING_AVAILABLE:
        # Fall back to the direct LLM path
        await _handle_ask(ws, question, mode, session, session_id=session_id)
        return

    session.mode = mode
    session.cancelled = False
    session.completed = False
    session.stream_error = False

    import uuid

    debate_id = f"oracle-{uuid.uuid4().hex[:12]}"

    try:
        # Phase 1: Quick reflex acknowledgment (parallel with debate setup)
        reflex_task = asyncio.create_task(_stream_reflex(ws, question, session))

        # Set up debate emitter
        emitter = SyncEventEmitter(loop_id=debate_id)

        # Determine agent count based on mode
        agent_count = 3 if mode == "divine" else 5
        rounds = 1 if mode == "divine" else 2

        # Get default agents
        try:
            from aragora.config import DEFAULT_AGENTS

            agents_str = DEFAULT_AGENTS
        except ImportError:
            agents_str = "anthropic-api,openai-api,grok"

        await reflex_task

        if session.cancelled:
            return

        # Signal debate start to client
        await ws.send_json(
            {
                "type": "debate_setup",
                "debate_id": debate_id,
                "question": question,
                "mode": mode,
                "rounds": rounds,
            }
        )

        # Run debate in background thread
        loop = asyncio.get_running_loop()
        debate_future = loop.run_in_executor(
            None,
            execute_debate_thread,
            debate_id,
            question,
            agents_str,
            rounds,
            "majority",
            None,  # trending_topic
            emitter,
        )

        # Start draining events from the emitter to the WebSocket
        drain_task = asyncio.create_task(_drain_emitter_to_ws(ws, emitter, session, debate_id))

        # Wait for debate completion or cancellation
        try:
            await asyncio.gather(debate_future, drain_task, return_exceptions=True)
        except asyncio.CancelledError:
            session.cancelled = True

        if session.cancelled or ws.closed:
            return

        # Send final synthesis
        synthesis = (
            f"The Oracle's debate is complete. "
            f"{agent_count} agents debated across {rounds} round(s)."
        )
        await ws.send_json({"type": "synthesis", "text": synthesis})
        session.completed = True

    except asyncio.CancelledError:
        session.cancelled = True
        raise
    except (
        RuntimeError,
        ValueError,
        TypeError,
        OSError,
        KeyError,
        AttributeError,
        ConnectionError,
        TimeoutError,
    ):
        session.stream_error = True
        logger.exception("Oracle debate consultation failed")
        if not ws.closed:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "The Oracle's debate failed. Try again.",
                }
            )
    finally:
        if session.completed:
            record_oracle_session_outcome("completed")
        elif session.cancelled:
            record_oracle_session_outcome("cancelled")
        else:
            record_oracle_session_outcome("error")


# ---------------------------------------------------------------------------
# Think-while-listening — process interim transcripts
# ---------------------------------------------------------------------------


def _handle_interim(session: OracleSession, text: str) -> None:
    """Process an interim transcript — pre-build the Oracle prompt."""
    session.last_interim = text
    session.prebuilt_prompt = _build_oracle_prompt(session.mode, text)


# ---------------------------------------------------------------------------
# Per-IP WebSocket rate limiting and session tracking
# ---------------------------------------------------------------------------

_ws_sessions: dict[str, int] = {}  # IP -> active session count
_MAX_WS_SESSIONS_PER_IP = 3
_WS_RATE_LIMIT = 10  # asks per minute
_WS_RATE_WINDOW = 60.0
_ws_ask_timestamps: dict[str, list[float]] = {}
_ws_rate_limit_hits: dict[str, int] = {}  # IP -> consecutive rate limit hits


def _check_ws_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check per-IP rate limit for WebSocket ask messages.

    Returns ``(allowed, retry_after_seconds)``.  On repeated rate limit
    hits the ``retry_after`` grows exponentially (2^n) to discourage
    aggressive retry loops.
    """
    now = time.monotonic()
    cutoff = now - _WS_RATE_WINDOW
    timestamps = _ws_ask_timestamps.get(client_ip, [])
    timestamps = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= _WS_RATE_LIMIT:
        base_retry = int(timestamps[0] + _WS_RATE_WINDOW - now) + 1
        # Exponential backoff for consecutive hits
        hits = _ws_rate_limit_hits.get(client_ip, 0) + 1
        _ws_rate_limit_hits[client_ip] = hits
        backoff_multiplier = min(2 ** (hits - 1), 32)  # cap at 32x
        retry_after = max(base_retry, 1) * backoff_multiplier
        _ws_ask_timestamps[client_ip] = timestamps
        return False, retry_after
    # Successful request — reset consecutive hit counter
    _ws_rate_limit_hits.pop(client_ip, None)
    timestamps.append(now)
    _ws_ask_timestamps[client_ip] = timestamps
    return True, 0


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------


def _is_oracle_streaming_enabled() -> bool:
    """Check whether Oracle streaming is enabled via feature flag."""
    try:
        from aragora.config.feature_flags import is_enabled

        return is_enabled("enable_oracle_streaming")
    except ImportError:
        # Feature flag registry unavailable — default to enabled
        return True


async def oracle_websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """WebSocket handler for real-time Oracle streaming.

    Endpoint: /ws/oracle
    """
    # Check feature flag
    if not _is_oracle_streaming_enabled():
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json(
            {
                "type": "error",
                "message": "Oracle streaming is disabled",
            }
        )
        await ws.close()
        return ws

    # Get client IP (supports X-Forwarded-For behind reverse proxy)
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.remote or "unknown"

    # Check concurrent session limit
    current = _ws_sessions.get(client_ip, 0)
    if current >= _MAX_WS_SESSIONS_PER_IP:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json(
            {
                "type": "error",
                "message": f"Too many concurrent sessions (max {_MAX_WS_SESSIONS_PER_IP})",
            }
        )
        await ws.close()
        return ws

    _ws_sessions[client_ip] = current + 1

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    session = OracleSession()

    await ws.send_json({"type": "connected", "timestamp": time.time()})

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "ping":
                        await ws.send_json({"type": "pong", "timestamp": time.time()})

                    elif msg_type in ("ask", "debate"):
                        question = _sanitize_oracle_input(str(data.get("question", "")).strip())
                        mode = str(data.get("mode", "consult"))
                        use_debate = msg_type == "debate" or data.get("debate", False)
                        if not question:
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": "Missing question",
                                }
                            )
                            continue

                        # Per-IP rate limiting on ask messages
                        allowed, retry_after = _check_ws_rate_limit(client_ip)
                        if not allowed:
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": f"Rate limited. Retry in {retry_after}s",
                                }
                            )
                            continue

                        # Cancel any running task
                        if session.active_task and not session.active_task.done():
                            session.cancelled = True
                            session.active_task.cancel()
                            try:
                                await session.active_task
                            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - awaiting cancelled task; any exception is expected
                                pass

                        # Extract optional session tracking params
                        session_id = data.get("session_id")
                        summary_depth = str(data.get("summary_depth", "light"))
                        session.debate_mode = use_debate

                        # Start new consultation
                        record_oracle_session_started()

                        if use_debate and _DEBATE_STREAMING_AVAILABLE:
                            session.active_task = asyncio.create_task(
                                _handle_debate(
                                    ws,
                                    question,
                                    mode,
                                    session,
                                    session_id=session_id,
                                )
                            )
                        else:
                            session.active_task = asyncio.create_task(
                                _handle_ask(
                                    ws,
                                    question,
                                    mode,
                                    session,
                                    session_id=session_id,
                                    summary_depth=summary_depth,
                                )
                            )

                    elif msg_type == "interim":
                        text = str(data.get("text", "")).strip()
                        if text:
                            _handle_interim(session, text)

                    elif msg_type == "stop":
                        session.cancelled = True
                        if session.active_task and not session.active_task.done():
                            session.active_task.cancel()
                            try:
                                await session.active_task
                            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - awaiting cancelled task on stop
                                pass

                except json.JSONDecodeError:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "Invalid JSON",
                        }
                    )

            elif msg.type == WSMsgType.ERROR:
                logger.error("Oracle WebSocket error: %s", ws.exception())
                break

    finally:
        _ws_sessions[client_ip] = max(0, _ws_sessions.get(client_ip, 1) - 1)
        session.cancelled = True
        if session.active_task and not session.active_task.done():
            session.active_task.cancel()
            try:
                await session.active_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - cleanup on WS disconnect
                pass

    return ws


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_oracle_stream_routes(app: web.Application) -> None:
    """Register the Oracle streaming WebSocket route."""
    app.router.add_get("/ws/oracle", oracle_websocket_handler)


__all__ = [
    "oracle_websocket_handler",
    "register_oracle_stream_routes",
    "OracleSession",
    "SentenceAccumulator",
    "_drain_emitter_to_ws",
    "_handle_debate",
]
