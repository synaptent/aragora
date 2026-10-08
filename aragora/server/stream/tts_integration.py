"""
TTS Integration for Live Voice Responses.

Subscribes to agent message events and triggers TTS synthesis for active
voice sessions. This bridges the debate event system with the voice streaming
infrastructure.

Usage:
    from aragora.server.stream.tts_integration import TTSIntegration

    # Initialize during server startup
    tts_integration = TTSIntegration(voice_handler)
    tts_integration.register(event_bus)

    # Now agent messages will automatically trigger TTS for voice sessions
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aragora.observability.metrics import record_tts_synthesis, record_tts_latency

if TYPE_CHECKING:
    from aragora.debate.event_bus import DebateEvent, EventBus
    from aragora.server.stream.voice_stream import VoiceStreamHandler

logger = logging.getLogger(__name__)

# Module-level singleton
_tts_integration: TTSIntegration | None = None


class TTSIntegration:
    """
    Integrates TTS synthesis with the debate event system.

    Listens for agent_message events and synthesizes speech for any
    active voice sessions connected to the debate.

    Features:
    - Automatic TTS for agent messages during debates
    - Configurable voice per agent
    - Rate limiting to prevent audio overlap
    - Graceful degradation when TTS unavailable
    """

    def __init__(
        self,
        voice_handler: VoiceStreamHandler | None = None,
        max_concurrent_synthesis: int = 3,
        min_interval_seconds: float = 0.5,
    ):
        """
        Initialize TTS integration.

        Args:
            voice_handler: VoiceStreamHandler for synthesizing audio
            max_concurrent_synthesis: Max concurrent TTS operations
            min_interval_seconds: Minimum time between TTS for same debate
        """
        self._voice_handler = voice_handler
        self._max_concurrent = max_concurrent_synthesis
        self._min_interval = min_interval_seconds
        self._active_synthesis: set[str] = set()  # debate_ids being synthesized
        self._last_synthesis: dict[str, float] = {}  # debate_id -> timestamp
        self._lock = asyncio.Lock()
        self._enabled = True

    def set_voice_handler(self, handler: VoiceStreamHandler) -> None:
        """Set or update the voice handler."""
        self._voice_handler = handler
        logger.info("[TTS Integration] Voice handler configured")

    def enable(self) -> None:
        """Enable TTS integration."""
        self._enabled = True
        logger.info("[TTS Integration] Enabled")

    def disable(self) -> None:
        """Disable TTS integration."""
        self._enabled = False
        logger.info("[TTS Integration] Disabled")

    @property
    def is_available(self) -> bool:
        """Check if TTS integration is available and enabled."""
        if not self._enabled:
            return False
        if self._voice_handler is None:
            return False
        return self._voice_handler.is_tts_available

    def register(self, event_bus: EventBus) -> None:
        """
        Register the TTS handler with the event bus.

        Args:
            event_bus: EventBus to subscribe to
        """
        event_bus.subscribe("agent_message", self._handle_agent_message)
        logger.info("[TTS Integration] Registered with EventBus for agent_message events")

    async def _handle_agent_message(self, event: DebateEvent) -> None:
        """
        Handle agent_message events by synthesizing TTS.

        Args:
            event: The debate event
        """
        if not self._enabled:
            return

        if self._voice_handler is None:
            return

        # Check if TTS is requested for this message
        enable_tts = event.data.get("enable_tts", True)
        if not enable_tts:
            return

        debate_id = event.debate_id
        agent_name = event.data.get("agent", "")
        content = event.data.get("content", "")

        if not content or not debate_id:
            return

        # Check if debate has active voice sessions
        if not self._voice_handler.has_voice_session(debate_id):
            return

        # Rate limiting - avoid overlapping audio
        now = time.time()
        last = self._last_synthesis.get(debate_id, 0)
        if now - last < self._min_interval:
            logger.debug("[TTS Integration] Rate limited for debate %s", debate_id)
            return

        # Concurrency check
        async with self._lock:
            if len(self._active_synthesis) >= self._max_concurrent:
                logger.debug("[TTS Integration] Max concurrent synthesis reached")
                return
            if debate_id in self._active_synthesis:
                logger.debug("[TTS Integration] Already synthesizing for %s", debate_id)
                return
            self._active_synthesis.add(debate_id)
            self._last_synthesis[debate_id] = now

        try:
            # Truncate very long content for TTS
            tts_content = content[:2000] if len(content) > 2000 else content

            # Track synthesis time
            synthesis_start = time.perf_counter()

            # Synthesize and send to voice sessions
            sessions_sent = await self._voice_handler.synthesize_agent_message(
                debate_id=debate_id,
                agent_name=agent_name,
                message=tts_content,
            )

            # Record metrics
            synthesis_duration = time.perf_counter() - synthesis_start
            if sessions_sent > 0:
                record_tts_synthesis(voice=agent_name, platform="debate_stream")
                record_tts_latency(synthesis_duration)
                logger.debug(
                    "[TTS Integration] Synthesized for %s -> %s voice session(s) in %.2fs",
                    agent_name,
                    sessions_sent,
                    synthesis_duration,
                )

        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.warning("[TTS Integration] Synthesis failed: %s", e)

        finally:
            async with self._lock:
                self._active_synthesis.discard(debate_id)

    async def synthesize_for_chat(
        self,
        text: str,
        channel_type: str = "telegram",
        channel_id: str = "",
        agent_name: str = "assistant",
        voice: str | None = None,
    ) -> bytes | None:
        """
        Synthesize audio for chat channels (Telegram, Discord, etc.).

        Returns audio bytes that can be sent as a voice note/message.

        Args:
            text: Text to synthesize
            channel_type: Type of channel (telegram, discord, whatsapp)
            channel_id: Channel/chat ID
            agent_name: Name of the agent
            voice: Optional voice override

        Returns:
            Audio bytes (mp3 format) or None if synthesis failed
        """
        if not self._enabled:
            return None

        try:
            from aragora.broadcast.tts_backends import get_fallback_backend

            backend = get_fallback_backend()
            if backend is None or not backend.is_available():
                logger.debug("[TTS Integration] No TTS backend available for chat")
                return None

            # Truncate for TTS
            tts_text = text[:2000] if len(text) > 2000 else text

            # Track synthesis time
            synthesis_start = time.perf_counter()

            # Synthesize to temp file
            audio_path = await backend.synthesize(
                text=tts_text,
                voice=voice or "narrator",
                output_path=None,  # Auto temp file
            )

            if audio_path is None or not audio_path.exists():
                return None

            # Read and return audio bytes
            audio_bytes = audio_path.read_bytes()

            # Cleanup temp file
            try:
                audio_path.unlink()
            except OSError as e:
                logger.debug("[TTS Integration] Failed to cleanup temp file: %s", e)

            # Record metrics
            synthesis_duration = time.perf_counter() - synthesis_start
            record_tts_synthesis(voice=voice or "narrator", platform=channel_type)
            record_tts_latency(synthesis_duration)

            logger.debug(
                "[TTS Integration] Synthesized %s chars -> %s bytes for %s in %.2fs",
                len(tts_text),
                len(audio_bytes),
                channel_type,
                synthesis_duration,
            )
            return audio_bytes

        except ImportError:
            logger.debug("[TTS Integration] TTS backends not available")
            return None
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.warning("[TTS Integration] Chat synthesis failed: %s", e)
            return None


def get_tts_integration() -> TTSIntegration | None:
    """Get the singleton TTS integration instance."""
    return _tts_integration


def set_tts_integration(integration: TTSIntegration) -> None:
    """Set the singleton TTS integration instance."""
    global _tts_integration
    _tts_integration = integration


def init_tts_integration(
    voice_handler: VoiceStreamHandler | None = None,
    event_bus: EventBus | None = None,
) -> TTSIntegration:
    """
    Initialize and configure TTS integration.

    Args:
        voice_handler: Optional voice handler (can be set later)
        event_bus: Optional event bus to register with

    Returns:
        Configured TTSIntegration instance
    """
    global _tts_integration

    if _tts_integration is None:
        _tts_integration = TTSIntegration(voice_handler)

    if voice_handler is not None:
        _tts_integration.set_voice_handler(voice_handler)

    if event_bus is not None:
        _tts_integration.register(event_bus)

    logger.info("[TTS Integration] Initialized")
    return _tts_integration


__all__ = [
    "TTSIntegration",
    "get_tts_integration",
    "set_tts_integration",
    "init_tts_integration",
]
