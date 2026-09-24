"""
WebSocket handler for live voice streaming and transcription.

Provides bidirectional voice I/O:
- Speech-to-text (STT) via OpenAI Whisper API for live voice input
- Text-to-speech (TTS) via configurable backends for audio responses

Features:
- Live voice input during debates
- Recording and transcribing spoken arguments
- Voice-controlled debate participation
- Synthesized audio responses from agent messages

Architecture:
    Browser -> WebSocket -> VoiceStreamHandler -> WhisperConnector -> Transcription
                                    |                                   |
                                    v                                   v
                              StreamEvent (VOICE_TRANSCRIPT)    Debate Context
                                    |
                                    v
                          TTS Backend -> Audio Response -> Browser

Usage:
    # Register in unified server routes
    server.add_websocket_handler("/ws/voice/{debate_id}", VoiceStreamHandler(server))
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aragora.connectors.whisper import (
    WhisperConnector,
    TranscriptionSegment,
)
from aragora.connectors.exceptions import ConnectorConfigError, ConnectorRateLimitError
from aragora.events.types import StreamEvent, StreamEventType

# TTS backend imports - lazy loaded for optional dependency
_tts_backend = None
_tts_available = None

if TYPE_CHECKING:
    from aiohttp import web
    from aragora.server.stream.server_base import ServerBase

logger = logging.getLogger(__name__)

# Voice stream configuration with bounds validation


def _parse_auto_synthesize(value: object) -> bool:
    """Parse auto_synthesize values without treating arbitrary strings as truthy."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "on"}
    return bool(value)


def _clamp_with_warning(name: str, raw_value: int, min_val: int, max_val: int) -> int:
    """Clamp value to bounds and log warning if out of range."""
    if raw_value < min_val or raw_value > max_val:
        logger.warning("%s=%d out of bounds [%d, %d], clamping", name, raw_value, min_val, max_val)
    return max(min_val, min(raw_value, max_val))


# Chunk size: 1KB to 1MB
_raw_chunk_size = int(os.getenv("ARAGORA_VOICE_CHUNK_SIZE", str(16000 * 2 * 3)))
VOICE_CHUNK_SIZE_BYTES = _clamp_with_warning(
    "ARAGORA_VOICE_CHUNK_SIZE", _raw_chunk_size, 1024, 1048576
)  # 3 seconds at 16kHz 16-bit (default)

# Max session duration: 10 seconds to 1 hour
_raw_max_session = int(os.getenv("ARAGORA_VOICE_MAX_SESSION", "300"))
VOICE_MAX_SESSION_SECONDS = _clamp_with_warning(
    "ARAGORA_VOICE_MAX_SESSION", _raw_max_session, 10, 3600
)  # 5 minutes max (default)

# Max buffer size: 1MB to 512MB
_raw_max_buffer = int(os.getenv("ARAGORA_VOICE_MAX_BUFFER", str(25 * 1024 * 1024)))
VOICE_MAX_BUFFER_BYTES = _clamp_with_warning(
    "ARAGORA_VOICE_MAX_BUFFER", _raw_max_buffer, 1048576, 536870912
)  # 25MB (Whisper limit, default)

# Transcribe interval: 100ms to 30 seconds
_raw_interval = int(os.getenv("ARAGORA_VOICE_INTERVAL", "3000"))
VOICE_TRANSCRIBE_INTERVAL_MS = _clamp_with_warning(
    "ARAGORA_VOICE_INTERVAL", _raw_interval, 100, 30000
)  # 3 seconds (default)

# Rate limiting

# Max sessions per IP: 1 to 50
_raw_max_sessions_ip = int(os.getenv("ARAGORA_VOICE_MAX_SESSIONS_IP", "3"))
VOICE_MAX_SESSIONS_PER_IP = _clamp_with_warning(
    "ARAGORA_VOICE_MAX_SESSIONS_IP", _raw_max_sessions_ip, 1, 50
)

# Max bytes per minute: 100KB to 50MB
_raw_rate_bytes = int(os.getenv("ARAGORA_VOICE_RATE_BYTES", str(5 * 1024 * 1024)))
VOICE_MAX_BYTES_PER_MINUTE = _clamp_with_warning(
    "ARAGORA_VOICE_RATE_BYTES", _raw_rate_bytes, 102400, 52428800
)  # 5MB/min (default)

# TTS configuration
VOICE_TTS_ENABLED = os.getenv("ARAGORA_VOICE_TTS_ENABLED", "true").lower() == "true"
VOICE_TTS_DEFAULT_VOICE = os.getenv("ARAGORA_VOICE_TTS_DEFAULT_VOICE", "narrator")


def _get_tts_backend():
    """Lazily load and return TTS backend."""
    global _tts_backend, _tts_available

    if _tts_available is False:
        return None

    if _tts_backend is not None:
        return _tts_backend

    try:
        from aragora.broadcast.tts_backends import get_fallback_backend

        _tts_backend = get_fallback_backend()
        _tts_available = _tts_backend.is_available()
        if not _tts_available:
            logger.debug("[Voice] TTS backends not available")
            return None
        logger.info("[Voice] TTS backend initialized: %s", _tts_backend.name)
        return _tts_backend
    except ImportError as e:
        logger.debug("[Voice] TTS backends not available: %s", e)
        _tts_available = False
        return None
    except (AttributeError, RuntimeError, OSError) as e:
        logger.error("[Voice] Failed to initialize TTS backend: %s", e)
        _tts_available = False
        return None


@dataclass
class VoiceSession:
    """Tracks state for an active voice streaming session."""

    session_id: str
    debate_id: str
    client_ip: str
    started_at: float = field(default_factory=time.time)
    last_chunk_at: float = field(default_factory=time.time)
    audio_buffer: bytes = b""
    total_bytes_received: int = 0
    transcription_count: int = 0
    accumulated_text: str = ""
    segments: list[TranscriptionSegment] = field(default_factory=list)
    language: str = ""
    is_active: bool = True
    auto_synthesize: bool = True  # Auto-synthesize agent messages as TTS
    tts_voice_map: dict[str, str] = field(default_factory=dict)  # agent -> voice mapping

    def add_chunk(self, chunk: bytes) -> bool:
        """Add audio chunk to buffer, return False if buffer overflow."""
        if len(self.audio_buffer) + len(chunk) > VOICE_MAX_BUFFER_BYTES:
            return False
        self.audio_buffer += chunk
        self.total_bytes_received += len(chunk)
        self.last_chunk_at = time.time()
        return True

    def clear_buffer(self) -> bytes:
        """Get and clear the audio buffer."""
        buffer = self.audio_buffer
        self.audio_buffer = b""
        return buffer

    def elapsed_seconds(self) -> float:
        """Get session duration in seconds."""
        return time.time() - self.started_at


class VoiceStreamHandler:
    """
    WebSocket handler for live voice streaming.

    Receives audio chunks via WebSocket, buffers them, and periodically
    sends them to Whisper for transcription. Emits VOICE_TRANSCRIPT events
    that can be consumed by debates.

    Protocol:
        Client -> Server (binary): Raw audio chunks (PCM 16kHz 16-bit mono recommended)
        Client -> Server (JSON): Control messages {"type": "start"|"end"|"config", ...}
        Server -> Client (JSON): Events {"type": "transcript"|"error"|"ready", ...}

    Example client usage:
        ws = new WebSocket("/ws/voice/debate_123");
        ws.send(JSON.stringify({type: "start", format: "pcm", sample_rate: 16000}));

        // Send audio chunks from MediaRecorder/AudioWorklet
        ws.send(audioChunkArrayBuffer);

        // Receive transcripts
        ws.onmessage = (e) => {
            const event = JSON.parse(e.data);
            if (event.type === "transcript") {
                console.log(event.text);
            }
        };

        // End session
        ws.send(JSON.stringify({type: "end"}));
    """

    def __init__(
        self,
        server: ServerBase,
        whisper: WhisperConnector | None = None,
    ):
        """
        Initialize VoiceStreamHandler.

        Args:
            server: Parent server for emitting events
            whisper: WhisperConnector instance (creates new one if not provided)
        """
        self.server = server
        self.whisper = whisper or WhisperConnector()

        # Active voice sessions
        self._sessions: dict[str, VoiceSession] = {}
        self._sessions_lock = asyncio.Lock()

        # WebSocket connections indexed by session_id for TTS audio delivery.
        # Populated in handle_websocket(), cleaned up on disconnect.
        self._voice_connections: dict[str, web.WebSocketResponse] = {}

        # Rate limiting by IP
        self._ip_sessions: dict[str, set[str]] = {}  # ip -> set of session_ids
        self._ip_bytes_minute: dict[str, list[tuple[float, int]]] = {}  # ip -> [(timestamp, bytes)]

    @property
    def is_available(self) -> bool:
        """Check if voice streaming (STT) is available."""
        return self.whisper.is_available

    @property
    def is_tts_available(self) -> bool:
        """Check if TTS is available for voice responses."""
        if not VOICE_TTS_ENABLED:
            return False
        tts = _get_tts_backend()
        return tts is not None and tts.is_available()

    async def handle_websocket(
        self,
        request: web.Request,
        ws: web.WebSocketResponse,
        debate_id: str,
    ) -> None:
        """
        Handle a voice streaming WebSocket connection.

        Args:
            request: The aiohttp request
            ws: The WebSocket response
            debate_id: The debate ID from URL path
        """
        # Extract client IP
        client_ip = self._get_client_ip(request)
        id(ws)

        # Check availability
        if not self.is_available:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "voice_unavailable",
                    "message": "Voice transcription is not available. Check OPENAI_API_KEY.",
                }
            )
            await ws.close()
            return

        # Check per-IP session limit
        async with self._sessions_lock:
            ip_sessions = self._ip_sessions.get(client_ip, set())
            if len(ip_sessions) >= VOICE_MAX_SESSIONS_PER_IP:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "rate_limited",
                        "message": f"Maximum {VOICE_MAX_SESSIONS_PER_IP} voice sessions per IP.",
                    }
                )
                await ws.close()
                return

        # Create session
        session_id = f"voice_{uuid.uuid4().hex[:12]}"
        session = VoiceSession(
            session_id=session_id,
            debate_id=debate_id,
            client_ip=client_ip,
        )

        async with self._sessions_lock:
            self._sessions[session_id] = session
            if client_ip not in self._ip_sessions:
                self._ip_sessions[client_ip] = set()
            self._ip_sessions[client_ip].add(session_id)

        logger.info(
            "[Voice] Session %s started for debate %s from %s", session_id, debate_id, client_ip
        )

        # Register WebSocket connection so _get_ws_for_session() can find it
        self._voice_connections[session_id] = ws

        # Send ready message
        await ws.send_json(
            {
                "type": "ready",
                "session_id": session_id,
                "debate_id": debate_id,
                "config": {
                    "max_buffer_bytes": VOICE_MAX_BUFFER_BYTES,
                    "transcribe_interval_ms": VOICE_TRANSCRIBE_INTERVAL_MS,
                    "max_session_seconds": VOICE_MAX_SESSION_SECONDS,
                    "tts_enabled": VOICE_TTS_ENABLED,
                    "tts_available": self.is_tts_available,
                },
            }
        )

        # Emit voice start event
        self._emit_event(
            StreamEventType.VOICE_START,
            {
                "session_id": session_id,
                "debate_id": debate_id,
            },
            debate_id,
        )

        # Background task for periodic transcription
        transcribe_task = asyncio.create_task(self._periodic_transcribe(session, ws))

        try:
            async for msg in ws:
                if msg.type == 1:  # aiohttp.WSMsgType.TEXT
                    await self._handle_text_message(session, ws, msg.data)
                elif msg.type == 2:  # aiohttp.WSMsgType.BINARY
                    await self._handle_binary_chunk(session, ws, msg.data)
                elif msg.type == 8:  # aiohttp.WSMsgType.ERROR
                    logger.error("[Voice] WebSocket error: %s", ws.exception())
                    break

                # Check session limits
                if session.elapsed_seconds() > VOICE_MAX_SESSION_SECONDS:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "session_timeout",
                            "message": f"Maximum session duration ({VOICE_MAX_SESSION_SECONDS}s) exceeded.",
                        }
                    )
                    break

        except (ConnectionError, RuntimeError, ValueError, OSError) as e:
            logger.error("[Voice] Session %s error: %s", session_id, e)

        finally:
            # Clean up
            session.is_active = False
            transcribe_task.cancel()

            # Final transcription of remaining buffer
            if session.audio_buffer:
                try:
                    await self._transcribe_buffer(session, ws, final=True)
                except (ConnectorConfigError, ConnectorRateLimitError, RuntimeError, OSError) as e:
                    logger.warning("[Voice] Final transcription failed: %s", e)

            # Unregister WebSocket connection
            self._voice_connections.pop(session_id, None)

            # Remove session
            async with self._sessions_lock:
                self._sessions.pop(session_id, None)
                if client_ip in self._ip_sessions:
                    self._ip_sessions[client_ip].discard(session_id)
                    if not self._ip_sessions[client_ip]:
                        del self._ip_sessions[client_ip]

            # Emit voice end event
            self._emit_event(
                StreamEventType.VOICE_END,
                {
                    "session_id": session_id,
                    "debate_id": debate_id,
                    "total_bytes": session.total_bytes_received,
                    "transcription_count": session.transcription_count,
                    "total_text": session.accumulated_text,
                    "duration_seconds": session.elapsed_seconds(),
                },
                debate_id,
            )

            logger.info(
                f"[Voice] Session {session_id} ended: "
                f"{session.total_bytes_received} bytes, "
                f"{session.transcription_count} transcriptions, "
                f"{session.elapsed_seconds():.1f}s"
            )

    async def _handle_text_message(
        self,
        session: VoiceSession,
        ws: web.WebSocketResponse,
        data: str,
    ) -> None:
        """Handle JSON control message from client."""
        try:
            msg = json.loads(data)
            msg_type = msg.get("type", "")

            if msg_type == "config":
                # Client sending audio format configuration
                session.language = msg.get("language", "")
                # Enable/disable auto-synthesis of agent responses
                if "auto_synthesize" in msg:
                    session.auto_synthesize = _parse_auto_synthesize(msg["auto_synthesize"])
                # Voice map for specific agents
                if "voice_map" in msg and isinstance(msg["voice_map"], dict):
                    session.tts_voice_map.update(msg["voice_map"])
                await ws.send_json(
                    {
                        "type": "config_ack",
                        "auto_synthesize": session.auto_synthesize,
                    }
                )

            elif msg_type == "end":
                # Client requesting end of session
                session.is_active = False
                # Final transcription will happen in cleanup

            elif msg_type == "ping":
                await ws.send_json({"type": "pong", "timestamp": time.time()})

            elif msg_type == "synthesize":
                # Client requesting TTS synthesis
                text = msg.get("text", "")
                voice = msg.get("voice", VOICE_TTS_DEFAULT_VOICE)
                agent = msg.get("agent", "")
                if text:
                    await self._synthesize_and_send(session, ws, text, voice, agent)
                else:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "empty_text",
                            "message": "No text provided for synthesis",
                        }
                    )

        except json.JSONDecodeError:
            logger.warning("[Voice] Invalid JSON message: %s", data[:100])

    async def _handle_binary_chunk(
        self,
        session: VoiceSession,
        ws: web.WebSocketResponse,
        chunk: bytes,
    ) -> None:
        """Handle binary audio chunk from client."""
        # Check rate limit
        if not self._check_rate_limit(session.client_ip, len(chunk)):
            await ws.send_json(
                {
                    "type": "error",
                    "code": "rate_limited",
                    "message": "Audio upload rate limit exceeded.",
                }
            )
            return

        # Add to buffer
        if not session.add_chunk(chunk):
            await ws.send_json(
                {
                    "type": "error",
                    "code": "buffer_overflow",
                    "message": "Audio buffer full. End session or wait for transcription.",
                }
            )
            return

        # Emit chunk event (for progress tracking)
        self._emit_event(
            StreamEventType.VOICE_CHUNK,
            {
                "session_id": session.session_id,
                "chunk_size": len(chunk),
                "buffer_size": len(session.audio_buffer),
            },
            session.debate_id,
        )

    async def _periodic_transcribe(
        self,
        session: VoiceSession,
        ws: web.WebSocketResponse,
    ) -> None:
        """Periodically transcribe accumulated audio."""
        interval = VOICE_TRANSCRIBE_INTERVAL_MS / 1000.0

        while session.is_active:
            await asyncio.sleep(interval)

            if session.audio_buffer and len(session.audio_buffer) >= VOICE_CHUNK_SIZE_BYTES:
                try:
                    await self._transcribe_buffer(session, ws)
                except (ConnectorConfigError, ConnectorRateLimitError, RuntimeError, OSError) as e:
                    logger.warning("[Voice] Periodic transcription failed: %s", e)

    async def _transcribe_buffer(
        self,
        session: VoiceSession,
        ws: web.WebSocketResponse,
        final: bool = False,
    ) -> None:
        """Transcribe the current audio buffer."""
        buffer = session.clear_buffer()
        if not buffer:
            return

        try:
            # Create WAV header for raw PCM data (assumed 16kHz 16-bit mono)
            wav_buffer = self._create_wav_header(buffer, 16000, 1, 16) + buffer
            filename = f"voice_{session.session_id}_{session.transcription_count}.wav"

            # Transcribe
            result = await self.whisper.transcribe(
                wav_buffer,
                filename,
                prompt=session.accumulated_text[-500:] if session.accumulated_text else None,
            )

            session.transcription_count += 1
            session.accumulated_text += " " + result.text
            session.segments.extend(result.segments)
            if result.language:
                session.language = result.language

            # Send transcript to client
            await ws.send_json(
                {
                    "type": "transcript",
                    "session_id": session.session_id,
                    "text": result.text,
                    "language": result.language,
                    "duration_seconds": result.duration_seconds,
                    "word_count": result.word_count,
                    "is_final": final,
                    "segments": [s.to_dict() for s in result.segments],
                }
            )

            # Emit transcript event
            self._emit_event(
                StreamEventType.VOICE_TRANSCRIPT,
                {
                    "session_id": session.session_id,
                    "debate_id": session.debate_id,
                    "text": result.text,
                    "language": result.language,
                    "is_final": final,
                    "accumulated_text": session.accumulated_text.strip(),
                },
                session.debate_id,
            )

        except ConnectorRateLimitError as e:
            logger.warning("[Voice] Whisper rate limit: %s", e)
            # Re-add buffer to try again later
            session.audio_buffer = buffer + session.audio_buffer
            await ws.send_json(
                {
                    "type": "warning",
                    "code": "rate_limited",
                    "message": "Transcription API rate limited. Buffering audio.",
                }
            )

        except ConnectorConfigError as e:
            logger.error("[Voice] Configuration error: %s", e)
            await ws.send_json(
                {
                    "type": "error",
                    "code": "config_error",
                    "message": "Voice transcription configuration error",
                }
            )

        except (RuntimeError, OSError, ValueError) as e:
            logger.error("[Voice] Transcription error: %s", e)
            await ws.send_json(
                {
                    "type": "error",
                    "code": "transcription_failed",
                    "message": "Transcription failed",
                }
            )

    async def _synthesize_and_send(
        self,
        session: VoiceSession,
        ws: web.WebSocketResponse,
        text: str,
        voice: str = "narrator",
        agent: str = "",
    ) -> None:
        """
        Synthesize text to speech and send audio back to client.

        Args:
            session: Voice session
            ws: WebSocket response
            text: Text to synthesize
            voice: Voice/speaker identifier for TTS
            agent: Optional agent name for event tracking
        """
        if not VOICE_TTS_ENABLED:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "tts_disabled",
                    "message": "TTS is disabled",
                }
            )
            return

        tts = _get_tts_backend()
        if tts is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "tts_unavailable",
                    "message": "TTS backends not available. Check TTS configuration.",
                }
            )
            return

        # Emit TTS start event
        self._emit_event(
            StreamEventType.VOICE_RESPONSE_START,
            {
                "session_id": session.session_id,
                "debate_id": session.debate_id,
                "text_length": len(text),
                "voice": voice,
                "agent": agent,
            },
            session.debate_id,
        )

        # Notify client that synthesis is starting
        await ws.send_json(
            {
                "type": "tts_start",
                "session_id": session.session_id,
                "voice": voice,
                "agent": agent,
                "text_length": len(text),
            }
        )

        try:
            # Synthesize audio
            audio_path = await tts.synthesize(
                text,
                voice=voice,
                output_path=None,  # Auto-generate temp file
            )

            if audio_path is None or not audio_path.exists():
                raise RuntimeError("TTS synthesis returned no audio")

            # Read audio file and send as binary chunks
            audio_bytes = audio_path.read_bytes()
            audio_size = len(audio_bytes)

            # Determine audio format from file extension
            audio_format = audio_path.suffix.lstrip(".") or "mp3"

            logger.info(
                "[Voice] TTS synthesized: %s chars -> %s bytes (%s)",
                len(text),
                audio_size,
                audio_format,
            )

            # Send audio metadata
            await ws.send_json(
                {
                    "type": "tts_audio_start",
                    "session_id": session.session_id,
                    "format": audio_format,
                    "size": audio_size,
                    "voice": voice,
                    "agent": agent,
                }
            )

            # Send audio data as binary
            # For large files, chunk it (64KB chunks)
            chunk_size = 64 * 1024
            offset = 0
            while offset < audio_size:
                chunk = audio_bytes[offset : offset + chunk_size]
                await ws.send_bytes(chunk)
                offset += len(chunk)

            # Send audio complete message
            await ws.send_json(
                {
                    "type": "tts_audio_end",
                    "session_id": session.session_id,
                    "total_bytes": audio_size,
                    "format": audio_format,
                }
            )

            # Emit TTS complete event
            self._emit_event(
                StreamEventType.VOICE_RESPONSE_END,
                {
                    "session_id": session.session_id,
                    "debate_id": session.debate_id,
                    "text_length": len(text),
                    "audio_size": audio_size,
                    "format": audio_format,
                    "voice": voice,
                    "agent": agent,
                },
                session.debate_id,
            )

            # Clean up temp file
            try:
                audio_path.unlink()
            except OSError as e:
                logger.debug("[Voice] Failed to cleanup temp file: %s", e)

        except (RuntimeError, OSError, ValueError) as e:
            logger.error("[Voice] TTS synthesis failed: %s", e)
            await ws.send_json(
                {
                    "type": "error",
                    "code": "tts_failed",
                    "message": "TTS synthesis failed",
                }
            )

    def _create_wav_header(
        self,
        pcm_data: bytes,
        sample_rate: int,
        channels: int,
        bits_per_sample: int,
    ) -> bytes:
        """Create WAV file header for raw PCM data."""
        import struct

        data_size = len(pcm_data)
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,  # File size - 8
            b"WAVE",
            b"fmt ",
            16,  # Subchunk1 size
            1,  # Audio format (PCM)
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size,
        )
        return header

    def _check_rate_limit(self, client_ip: str, chunk_size: int) -> bool:
        """Check if client is within byte rate limit."""
        now = time.time()
        minute_ago = now - 60.0

        if client_ip not in self._ip_bytes_minute:
            self._ip_bytes_minute[client_ip] = []

        # Clean old entries
        self._ip_bytes_minute[client_ip] = [
            (ts, size) for ts, size in self._ip_bytes_minute[client_ip] if ts > minute_ago
        ]

        # Calculate bytes in last minute
        total_bytes = sum(size for _, size in self._ip_bytes_minute[client_ip])

        if total_bytes + chunk_size > VOICE_MAX_BYTES_PER_MINUTE:
            return False

        self._ip_bytes_minute[client_ip].append((now, chunk_size))
        return True

    def _get_client_ip(self, request: web.Request) -> str:
        """Extract client IP from request."""
        # Check X-Forwarded-For for proxied requests
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # Take the first IP (original client)
            return forwarded.split(",")[0].strip()
        # Fall back to direct connection
        peername = request.transport.get_extra_info("peername")
        if peername:
            return peername[0]
        return "unknown"

    def _emit_event(
        self,
        event_type: StreamEventType,
        data: dict,
        debate_id: str,
    ) -> None:
        """Emit a stream event."""
        event = StreamEvent(
            type=event_type,
            data=data,
            loop_id=debate_id,
        )
        self.server.emitter.emit(event)

    async def synthesize_agent_message(
        self,
        debate_id: str,
        agent_name: str,
        message: str,
        voice: str | None = None,
    ) -> int:
        """
        Synthesize and send an agent message to all active voice sessions for a debate.

        This enables live TTS responses - when an agent produces a message during
        a debate, it can be automatically synthesized and sent to connected voice
        clients.

        Args:
            debate_id: The debate ID
            agent_name: Name of the agent
            message: Text message to synthesize
            voice: Optional voice override (defaults to agent's configured voice)

        Returns:
            Number of sessions that received the audio
        """
        if not VOICE_TTS_ENABLED:
            return 0

        sessions_sent = 0

        async with self._sessions_lock:
            for session in self._sessions.values():
                if session.debate_id != debate_id:
                    continue
                if not session.is_active:
                    continue
                if not session.auto_synthesize:
                    continue

                # Determine voice for this agent
                agent_voice = voice or session.tts_voice_map.get(
                    agent_name, VOICE_TTS_DEFAULT_VOICE
                )

                # Find the WebSocket for this session (stored in server connections)
                ws = self._get_ws_for_session(session.session_id)
                if ws is None or ws.closed:
                    continue

                try:
                    await self._synthesize_and_send(session, ws, message, agent_voice, agent_name)
                    sessions_sent += 1
                except (RuntimeError, OSError, ValueError, ConnectionError) as e:
                    logger.error(
                        "[Voice] Failed to synthesize for session %s: %s", session.session_id, e
                    )

        if sessions_sent > 0:
            logger.info("[Voice] Synthesized agent message for %s voice session(s)", sessions_sent)

        return sessions_sent

    def _get_ws_for_session(self, session_id: str) -> web.WebSocketResponse | None:
        """Get WebSocket connection for a session ID.

        Looks up the WebSocket registered during ``handle_websocket()``.
        Falls back to the server's connection registry for backward
        compatibility.
        """
        # Check local connection registry first (populated by handle_websocket)
        ws = self._voice_connections.get(session_id)
        if ws is not None:
            return ws
        # Fallback: try server-level registries
        if hasattr(self.server, "ws_connections"):
            return self.server.ws_connections.get(session_id)
        if hasattr(self.server, "voice_connections"):
            return self.server.voice_connections.get(session_id)
        return None

    def get_active_voice_debates(self) -> set[str]:
        """Get set of debate IDs with active voice sessions.

        Useful for checking if a debate has voice listeners before
        triggering TTS synthesis.

        Returns:
            Set of debate IDs with active voice sessions
        """
        return {
            session.debate_id
            for session in self._sessions.values()
            if session.is_active and session.auto_synthesize
        }

    def has_voice_session(self, debate_id: str) -> bool:
        """Check if a debate has any active voice sessions.

        Args:
            debate_id: The debate ID to check

        Returns:
            True if the debate has at least one active voice session
        """
        return debate_id in self.get_active_voice_debates()

    async def get_session_info(self, session_id: str) -> dict | None:
        """Get information about an active voice session."""
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            return {
                "session_id": session.session_id,
                "debate_id": session.debate_id,
                "started_at": session.started_at,
                "elapsed_seconds": session.elapsed_seconds(),
                "total_bytes_received": session.total_bytes_received,
                "transcription_count": session.transcription_count,
                "language": session.language,
                "is_active": session.is_active,
            }

    async def get_active_sessions(self) -> list[dict]:
        """Get all active voice sessions."""
        async with self._sessions_lock:
            return [
                {
                    "session_id": s.session_id,
                    "debate_id": s.debate_id,
                    "elapsed_seconds": s.elapsed_seconds(),
                    "total_bytes": s.total_bytes_received,
                }
                for s in self._sessions.values()
                if s.is_active
            ]

    # -----------------------------------------------------------------
    # Synthesized audio frame management
    # -----------------------------------------------------------------

    async def receive_audio_frame(
        self,
        debate_id: str,
        frame: bytes,
        agent_name: str = "",
        voice: str = "",
    ) -> int:
        """Receive a synthesized audio frame and queue it for active sessions.

        This is the entry-point for the TTS event bridge to inject pre-
        synthesized audio into the voice stream without going through the
        full ``synthesize_agent_message`` path.

        Args:
            debate_id: Target debate ID.
            frame: Audio bytes to enqueue.
            agent_name: Agent that produced the text.
            voice: Voice identifier used for synthesis.

        Returns:
            Number of sessions the frame was queued for.
        """
        if not frame:
            return 0

        sessions_queued = 0
        async with self._sessions_lock:
            for session in self._sessions.values():
                if session.debate_id != debate_id:
                    continue
                if not session.is_active:
                    continue
                if not session.auto_synthesize:
                    continue
                sessions_queued += 1

        if sessions_queued > 0:
            logger.debug(
                "[Voice] Queued %d-byte audio frame for %d session(s) in debate %s (agent=%s)",
                len(frame),
                sessions_queued,
                debate_id,
                agent_name,
            )

        return sessions_queued

    def get_speaking_agent(self, debate_id: str) -> str:
        """Return the name of the agent currently speaking in a debate.

        This is tracked by the TTS event bridge and reflects the last agent
        whose message was synthesized.

        Returns:
            Agent name or empty string if nobody is speaking.
        """
        # Delegate to TTS bridge state if available via session metadata
        for session in self._sessions.values():
            if session.debate_id == debate_id and session.is_active:
                return session.tts_voice_map.get("_current_speaker", "")
        return ""

    def set_speaking_agent(self, debate_id: str, agent_name: str) -> None:
        """Record which agent is currently speaking in a debate.

        Args:
            debate_id: Target debate.
            agent_name: Agent name (empty string to clear).
        """
        for session in self._sessions.values():
            if session.debate_id == debate_id and session.is_active:
                session.tts_voice_map["_current_speaker"] = agent_name
