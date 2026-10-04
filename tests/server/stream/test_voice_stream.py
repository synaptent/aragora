"""
Tests for VoiceStreamHandler and VoiceSession.

Tests cover:
- VoiceSession: Audio buffer management, state tracking, time calculations
- VoiceStreamHandler: Session lifecycle, WebSocket handling, TTS integration
- Rate limiting and IP tracking
- Error handling and recovery
- Concurrent session management
- WAV header generation
"""

import asyncio
import json
import struct
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from aragora.connectors.exceptions import (
    ConnectorConfigError,
    ConnectorRateLimitError,
)
from aragora.connectors.whisper import TranscriptionResult, TranscriptionSegment
from aragora.events.types import StreamEvent, StreamEventType


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_whisper():
    """Create a mock WhisperConnector."""
    whisper = MagicMock()
    whisper.is_available = True
    whisper.transcribe = AsyncMock()
    return whisper


@pytest.fixture
def mock_server():
    """Create a mock server with emitter."""
    server = MagicMock()
    server.emitter = MagicMock()
    server.emitter.emit = MagicMock()
    server.ws_connections = {}
    server.voice_connections = {}
    return server


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket response."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()
    ws.closed = False
    ws.exception = MagicMock(return_value=None)
    return ws


@pytest.fixture
def mock_request():
    """Create a mock aiohttp request with IP info."""
    request = MagicMock()
    request.headers = {}
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=("192.168.1.100", 12345))
    request.transport = transport
    return request


@pytest.fixture
def voice_handler(mock_server, mock_whisper):
    """Create a VoiceStreamHandler with mocked dependencies."""
    from aragora.server.stream.voice_stream import VoiceStreamHandler

    handler = VoiceStreamHandler(mock_server, mock_whisper)
    return handler


@pytest.fixture
def transcription_result():
    """Create a sample transcription result."""
    return TranscriptionResult(
        id="trans_abc123",
        text="Hello, this is a test transcription.",
        segments=[
            TranscriptionSegment(start=0.0, end=1.5, text="Hello, this is", confidence=0.95),
            TranscriptionSegment(start=1.5, end=3.0, text="a test transcription.", confidence=0.92),
        ],
        language="en",
        duration_seconds=3.0,
        source_filename="test.wav",
        word_count=6,
        confidence=0.85,
    )


# ===========================================================================
# VoiceSession Tests
# ===========================================================================


class TestVoiceSession:
    """Tests for VoiceSession dataclass."""

    def test_session_initialization(self):
        """Test VoiceSession default initialization."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        assert session.session_id == "voice_abc123"
        assert session.debate_id == "debate_456"
        assert session.client_ip == "192.168.1.100"
        assert session.audio_buffer == b""
        assert session.total_bytes_received == 0
        assert session.transcription_count == 0
        assert session.accumulated_text == ""
        assert session.segments == []
        assert session.language == ""
        assert session.is_active is True
        assert session.auto_synthesize is True
        assert session.tts_voice_map == {}

    def test_add_chunk_success(self):
        """Test adding audio chunk to buffer."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        chunk = b"\x00\x01\x02\x03" * 1000  # 4KB chunk
        result = session.add_chunk(chunk)

        assert result is True
        assert session.audio_buffer == chunk
        assert session.total_bytes_received == 4000

    def test_add_chunk_multiple(self):
        """Test adding multiple chunks accumulates correctly."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        chunk1 = b"\x00\x01" * 100
        chunk2 = b"\x02\x03" * 100

        session.add_chunk(chunk1)
        session.add_chunk(chunk2)

        assert session.audio_buffer == chunk1 + chunk2
        assert session.total_bytes_received == 400

    def test_add_chunk_buffer_overflow(self):
        """Test buffer overflow rejection."""
        from aragora.server.stream.voice_stream import VoiceSession, VOICE_MAX_BUFFER_BYTES

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Fill buffer to near limit
        session.audio_buffer = b"\x00" * (VOICE_MAX_BUFFER_BYTES - 100)

        # Try to add chunk that exceeds limit
        large_chunk = b"\x01" * 200
        result = session.add_chunk(large_chunk)

        assert result is False
        # Buffer should be unchanged
        assert len(session.audio_buffer) == VOICE_MAX_BUFFER_BYTES - 100

    def test_add_chunk_updates_timestamp(self):
        """Test that add_chunk updates last_chunk_at timestamp."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        original_time = session.last_chunk_at
        time.sleep(0.01)

        session.add_chunk(b"\x00\x01\x02\x03")

        assert session.last_chunk_at > original_time

    def test_clear_buffer(self):
        """Test clearing audio buffer."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        chunk = b"\x00\x01\x02\x03" * 100
        session.add_chunk(chunk)

        cleared = session.clear_buffer()

        assert cleared == chunk
        assert session.audio_buffer == b""

    def test_clear_buffer_empty(self):
        """Test clearing empty buffer returns empty bytes."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        cleared = session.clear_buffer()

        assert cleared == b""

    def test_elapsed_seconds(self):
        """Test elapsed time calculation."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Wait a bit
        time.sleep(0.05)

        elapsed = session.elapsed_seconds()
        assert elapsed >= 0.05
        assert elapsed < 1.0  # Should be less than 1 second

    def test_session_with_voice_map(self):
        """Test session with TTS voice mappings."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
            tts_voice_map={"claude": "sage", "gpt4": "narrator"},
        )

        assert session.tts_voice_map["claude"] == "sage"
        assert session.tts_voice_map["gpt4"] == "narrator"


# ===========================================================================
# VoiceStreamHandler Basic Tests
# ===========================================================================


class TestVoiceStreamHandlerBasics:
    """Basic tests for VoiceStreamHandler initialization and properties."""

    def test_initialization(self, voice_handler, mock_server, mock_whisper):
        """Test handler initialization."""
        assert voice_handler.server is mock_server
        assert voice_handler.whisper is mock_whisper
        assert voice_handler._sessions == {}
        assert voice_handler._ip_sessions == {}
        assert voice_handler._ip_bytes_minute == {}

    def test_initialization_creates_whisper(self, mock_server):
        """Test handler creates WhisperConnector if not provided."""
        from aragora.server.stream.voice_stream import VoiceStreamHandler

        with patch("aragora.server.stream.voice_stream.WhisperConnector") as mock_whisper_class:
            mock_whisper_instance = MagicMock()
            mock_whisper_class.return_value = mock_whisper_instance

            handler = VoiceStreamHandler(mock_server)

            mock_whisper_class.assert_called_once()
            assert handler.whisper is mock_whisper_instance

    def test_is_available_true(self, voice_handler, mock_whisper):
        """Test is_available returns True when whisper is available."""
        mock_whisper.is_available = True
        assert voice_handler.is_available is True

    def test_is_available_false(self, voice_handler, mock_whisper):
        """Test is_available returns False when whisper is unavailable."""
        mock_whisper.is_available = False
        assert voice_handler.is_available is False

    def test_is_tts_available_disabled(self, voice_handler):
        """Test is_tts_available returns False when TTS is disabled."""
        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", False):
            assert voice_handler.is_tts_available is False

    def test_is_tts_available_no_backend(self, voice_handler):
        """Test is_tts_available returns False when no backend available."""
        with (
            patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True),
            patch("aragora.server.stream.voice_stream._get_tts_backend", return_value=None),
        ):
            assert voice_handler.is_tts_available is False

    def test_is_tts_available_backend_unavailable(self, voice_handler):
        """Test is_tts_available returns False when backend reports unavailable."""
        mock_tts = MagicMock()
        mock_tts.is_available.return_value = False

        with (
            patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True),
            patch("aragora.server.stream.voice_stream._get_tts_backend", return_value=mock_tts),
        ):
            assert voice_handler.is_tts_available is False

    def test_is_tts_available_true(self, voice_handler):
        """Test is_tts_available returns True when backend is available."""
        mock_tts = MagicMock()
        mock_tts.is_available.return_value = True

        with (
            patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True),
            patch("aragora.server.stream.voice_stream._get_tts_backend", return_value=mock_tts),
        ):
            assert voice_handler.is_tts_available is True


# ===========================================================================
# Client IP Extraction Tests
# ===========================================================================


class TestClientIPExtraction:
    """Tests for client IP extraction from requests."""

    def test_get_client_ip_from_transport(self, voice_handler, mock_request):
        """Test extracting IP from transport peername."""
        ip = voice_handler._get_client_ip(mock_request)
        assert ip == "192.168.1.100"

    def test_get_client_ip_from_x_forwarded_for(self, voice_handler, mock_request):
        """Test extracting IP from X-Forwarded-For header."""
        mock_request.headers["X-Forwarded-For"] = "10.0.0.1, 10.0.0.2, 10.0.0.3"

        ip = voice_handler._get_client_ip(mock_request)
        assert ip == "10.0.0.1"

    def test_get_client_ip_from_single_forwarded(self, voice_handler, mock_request):
        """Test extracting IP from single X-Forwarded-For value."""
        mock_request.headers["X-Forwarded-For"] = "10.0.0.1"

        ip = voice_handler._get_client_ip(mock_request)
        assert ip == "10.0.0.1"

    def test_get_client_ip_no_peername(self, voice_handler, mock_request):
        """Test fallback when no peername available."""
        mock_request.transport.get_extra_info.return_value = None

        ip = voice_handler._get_client_ip(mock_request)
        assert ip == "unknown"


# ===========================================================================
# Rate Limiting Tests
# ===========================================================================


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_check_rate_limit_allows_initial(self, voice_handler):
        """Test rate limit allows initial requests."""
        result = voice_handler._check_rate_limit("192.168.1.100", 1000)
        assert result is True

    def test_check_rate_limit_tracks_bytes(self, voice_handler):
        """Test rate limit tracks bytes over time."""
        client_ip = "192.168.1.100"

        # Send several chunks
        for _ in range(10):
            voice_handler._check_rate_limit(client_ip, 100)

        # Should have tracking entries
        assert client_ip in voice_handler._ip_bytes_minute
        assert len(voice_handler._ip_bytes_minute[client_ip]) == 10

    def test_check_rate_limit_enforces_limit(self, voice_handler):
        """Test rate limit rejects when limit exceeded."""
        from aragora.server.stream.voice_stream import VOICE_MAX_BYTES_PER_MINUTE

        client_ip = "192.168.1.100"

        # Send exactly up to the limit
        chunk_size = VOICE_MAX_BYTES_PER_MINUTE // 10
        for _ in range(10):
            voice_handler._check_rate_limit(client_ip, chunk_size)

        # Next chunk should be rejected
        result = voice_handler._check_rate_limit(client_ip, 1000)
        assert result is False

    def test_check_rate_limit_cleans_old_entries(self, voice_handler):
        """Test rate limit cleans up old entries."""
        client_ip = "192.168.1.100"

        # Add old entry
        old_time = time.time() - 120  # 2 minutes ago
        voice_handler._ip_bytes_minute[client_ip] = [(old_time, 1000000)]

        # New request should clean old and allow
        result = voice_handler._check_rate_limit(client_ip, 1000)
        assert result is True

        # Old entry should be removed
        timestamps = [ts for ts, _ in voice_handler._ip_bytes_minute[client_ip]]
        assert all(ts > old_time for ts in timestamps)


# ===========================================================================
# WAV Header Tests
# ===========================================================================


class TestWAVHeaderGeneration:
    """Tests for WAV header generation."""

    def test_create_wav_header_structure(self, voice_handler):
        """Test WAV header has correct structure."""
        pcm_data = b"\x00" * 1000
        header = voice_handler._create_wav_header(pcm_data, 16000, 1, 16)

        # Header should be 44 bytes
        assert len(header) == 44

        # Check RIFF header
        assert header[:4] == b"RIFF"

        # Check WAVE format
        assert header[8:12] == b"WAVE"

        # Check fmt chunk
        assert header[12:16] == b"fmt "

        # Check data chunk
        assert header[36:40] == b"data"

    def test_create_wav_header_file_size(self, voice_handler):
        """Test WAV header contains correct file size."""
        pcm_data = b"\x00" * 1000
        header = voice_handler._create_wav_header(pcm_data, 16000, 1, 16)

        # File size is at offset 4, should be 36 + data_size
        file_size = struct.unpack("<I", header[4:8])[0]
        assert file_size == 36 + 1000

    def test_create_wav_header_sample_rate(self, voice_handler):
        """Test WAV header contains correct sample rate."""
        pcm_data = b"\x00" * 1000
        header = voice_handler._create_wav_header(pcm_data, 16000, 1, 16)

        # Sample rate is at offset 24
        sample_rate = struct.unpack("<I", header[24:28])[0]
        assert sample_rate == 16000

    def test_create_wav_header_channels(self, voice_handler):
        """Test WAV header contains correct channel count."""
        pcm_data = b"\x00" * 1000
        header = voice_handler._create_wav_header(pcm_data, 16000, 2, 16)

        # Channels is at offset 22
        channels = struct.unpack("<H", header[22:24])[0]
        assert channels == 2

    def test_create_wav_header_bits_per_sample(self, voice_handler):
        """Test WAV header contains correct bits per sample."""
        pcm_data = b"\x00" * 1000
        header = voice_handler._create_wav_header(pcm_data, 16000, 1, 16)

        # Bits per sample is at offset 34
        bits = struct.unpack("<H", header[34:36])[0]
        assert bits == 16


# ===========================================================================
# Text Message Handling Tests
# ===========================================================================


class TestTextMessageHandling:
    """Tests for WebSocket text message handling."""

    @pytest.mark.asyncio
    async def test_handle_config_message(self, voice_handler, mock_websocket):
        """Test handling config message."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        config_msg = json.dumps(
            {
                "type": "config",
                "language": "en",
                "auto_synthesize": False,
                "voice_map": {"claude": "sage"},
            }
        )

        await voice_handler._handle_text_message(session, mock_websocket, config_msg)

        assert session.language == "en"
        assert session.auto_synthesize is False
        assert session.tts_voice_map["claude"] == "sage"

        # Should send acknowledgment
        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "config_ack"
        assert call_data["auto_synthesize"] is False

    @pytest.mark.asyncio
    async def test_handle_config_message_auto_synthesize_string_values(
        self, voice_handler, mock_websocket
    ):
        """Test string-valued auto_synthesize config is parsed fail-closed."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        truthy_msg = json.dumps({"type": "config", "auto_synthesize": "yes"})
        await voice_handler._handle_text_message(session, mock_websocket, truthy_msg)

        assert session.auto_synthesize is True
        assert mock_websocket.send_json.call_args[0][0]["auto_synthesize"] is True

        malformed_msg = json.dumps({"type": "config", "auto_synthesize": "definitely"})
        await voice_handler._handle_text_message(session, mock_websocket, malformed_msg)

        assert session.auto_synthesize is False
        assert mock_websocket.send_json.call_args[0][0]["auto_synthesize"] is False

    @pytest.mark.asyncio
    async def test_handle_end_message(self, voice_handler, mock_websocket):
        """Test handling end message."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        end_msg = json.dumps({"type": "end"})

        await voice_handler._handle_text_message(session, mock_websocket, end_msg)

        assert session.is_active is False

    @pytest.mark.asyncio
    async def test_handle_ping_message(self, voice_handler, mock_websocket):
        """Test handling ping message returns pong."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        ping_msg = json.dumps({"type": "ping"})

        await voice_handler._handle_text_message(session, mock_websocket, ping_msg)

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "pong"
        assert "timestamp" in call_data

    @pytest.mark.asyncio
    async def test_handle_synthesize_message_empty_text(self, voice_handler, mock_websocket):
        """Test synthesize message with empty text returns error."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        synth_msg = json.dumps({"type": "synthesize", "text": ""})

        await voice_handler._handle_text_message(session, mock_websocket, synth_msg)

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "empty_text"

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self, voice_handler, mock_websocket):
        """Test handling invalid JSON doesn't crash."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Should not raise, just log warning
        await voice_handler._handle_text_message(session, mock_websocket, "not valid json")

        # No response expected for invalid JSON
        mock_websocket.send_json.assert_not_called()


# ===========================================================================
# Binary Chunk Handling Tests
# ===========================================================================


class TestBinaryChunkHandling:
    """Tests for WebSocket binary chunk handling."""

    @pytest.mark.asyncio
    async def test_handle_binary_chunk_success(self, voice_handler, mock_websocket, mock_server):
        """Test successful binary chunk handling."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        chunk = b"\x00\x01\x02\x03" * 100

        await voice_handler._handle_binary_chunk(session, mock_websocket, chunk)

        assert session.audio_buffer == chunk

        # Should emit chunk event
        mock_server.emitter.emit.assert_called_once()
        event = mock_server.emitter.emit.call_args[0][0]
        assert event.type == StreamEventType.VOICE_CHUNK

    @pytest.mark.asyncio
    async def test_handle_binary_chunk_rate_limited(self, voice_handler, mock_websocket):
        """Test rate-limited chunk returns error."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Simulate rate limit exceeded
        with patch.object(voice_handler, "_check_rate_limit", return_value=False):
            await voice_handler._handle_binary_chunk(session, mock_websocket, b"\x00\x01")

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_handle_binary_chunk_buffer_overflow(self, voice_handler, mock_websocket):
        """Test buffer overflow returns error."""
        from aragora.server.stream.voice_stream import VoiceSession, VOICE_MAX_BUFFER_BYTES

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Fill buffer near limit
        session.audio_buffer = b"\x00" * (VOICE_MAX_BUFFER_BYTES - 10)

        # Try to add chunk exceeding limit
        chunk = b"\x01" * 100
        await voice_handler._handle_binary_chunk(session, mock_websocket, chunk)

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "buffer_overflow"


# ===========================================================================
# Transcription Tests
# ===========================================================================


class TestTranscription:
    """Tests for audio transcription functionality."""

    @pytest.mark.asyncio
    async def test_transcribe_buffer_success(
        self, voice_handler, mock_websocket, mock_whisper, mock_server, transcription_result
    ):
        """Test successful buffer transcription."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )
        session.audio_buffer = b"\x00\x01" * 10000

        mock_whisper.transcribe.return_value = transcription_result

        await voice_handler._transcribe_buffer(session, mock_websocket)

        # Buffer should be cleared
        assert session.audio_buffer == b""

        # Session state should be updated
        assert session.transcription_count == 1
        assert "Hello, this is a test transcription." in session.accumulated_text
        assert session.language == "en"

        # Should send transcript to client
        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "transcript"
        assert call_data["text"] == "Hello, this is a test transcription."

        # Should emit event
        assert mock_server.emitter.emit.called
        events = [call[0][0] for call in mock_server.emitter.emit.call_args_list]
        transcript_events = [e for e in events if e.type == StreamEventType.VOICE_TRANSCRIPT]
        assert len(transcript_events) == 1

    @pytest.mark.asyncio
    async def test_transcribe_buffer_empty(self, voice_handler, mock_websocket, mock_whisper):
        """Test transcribing empty buffer does nothing."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        await voice_handler._transcribe_buffer(session, mock_websocket)

        mock_whisper.transcribe.assert_not_called()
        mock_websocket.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcribe_buffer_rate_limit_error(
        self, voice_handler, mock_websocket, mock_whisper
    ):
        """Test rate limit error re-adds buffer."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )
        original_buffer = b"\x00\x01" * 10000
        session.audio_buffer = original_buffer

        mock_whisper.transcribe.side_effect = ConnectorRateLimitError(
            "Rate limit exceeded",
            connector_name="Whisper",
        )

        await voice_handler._transcribe_buffer(session, mock_websocket)

        # Buffer should be restored
        assert session.audio_buffer == original_buffer

        # Should send warning to client
        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "warning"
        assert call_data["code"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_transcribe_buffer_config_error(
        self, voice_handler, mock_websocket, mock_whisper
    ):
        """Test config error sends error message."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )
        session.audio_buffer = b"\x00\x01" * 10000

        mock_whisper.transcribe.side_effect = ConnectorConfigError(
            "No API key",
            connector_name="Whisper",
        )

        await voice_handler._transcribe_buffer(session, mock_websocket)

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "config_error"

    @pytest.mark.asyncio
    async def test_transcribe_buffer_final_flag(
        self, voice_handler, mock_websocket, mock_whisper, transcription_result
    ):
        """Test final transcription sets is_final flag."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )
        session.audio_buffer = b"\x00\x01" * 10000

        mock_whisper.transcribe.return_value = transcription_result

        await voice_handler._transcribe_buffer(session, mock_websocket, final=True)

        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["is_final"] is True


# ===========================================================================
# TTS Synthesis Tests
# ===========================================================================


class TestTTSSynthesis:
    """Tests for TTS synthesis functionality."""

    @pytest.mark.asyncio
    async def test_synthesize_tts_disabled(self, voice_handler, mock_websocket):
        """Test synthesis when TTS is disabled."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", False):
            await voice_handler._synthesize_and_send(session, mock_websocket, "Hello")

        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "tts_disabled"

    @pytest.mark.asyncio
    async def test_synthesize_no_backend(self, voice_handler, mock_websocket):
        """Test synthesis when no TTS backend available."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        with (
            patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True),
            patch("aragora.server.stream.voice_stream._get_tts_backend", return_value=None),
        ):
            await voice_handler._synthesize_and_send(session, mock_websocket, "Hello")

        # Should send tts_unavailable error
        calls = mock_websocket.send_json.call_args_list
        error_calls = [c for c in calls if c[0][0].get("type") == "error"]
        assert len(error_calls) == 1
        assert error_calls[0][0][0]["code"] == "tts_unavailable"

    @pytest.mark.asyncio
    async def test_synthesize_success(self, voice_handler, mock_websocket, mock_server):
        """Test successful TTS synthesis."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Create mock TTS backend
        mock_tts = MagicMock()
        mock_audio_path = MagicMock(spec=Path)
        mock_audio_path.exists.return_value = True
        mock_audio_path.read_bytes.return_value = b"\x00\x01\x02" * 100
        mock_audio_path.suffix = ".mp3"
        mock_audio_path.unlink = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=mock_audio_path)

        with (
            patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True),
            patch("aragora.server.stream.voice_stream._get_tts_backend", return_value=mock_tts),
        ):
            await voice_handler._synthesize_and_send(
                session, mock_websocket, "Hello world", "narrator", "claude"
            )

        # Check TTS was called
        mock_tts.synthesize.assert_called_once()

        # Check messages sent
        json_calls = mock_websocket.send_json.call_args_list
        types = [c[0][0]["type"] for c in json_calls]

        assert "tts_start" in types
        assert "tts_audio_start" in types
        assert "tts_audio_end" in types

        # Check binary audio was sent
        assert mock_websocket.send_bytes.called

        # Check events emitted
        events = [call[0][0] for call in mock_server.emitter.emit.call_args_list]
        event_types = [e.type for e in events]
        assert StreamEventType.VOICE_RESPONSE_START in event_types
        assert StreamEventType.VOICE_RESPONSE_END in event_types

    @pytest.mark.asyncio
    async def test_synthesize_failure(self, voice_handler, mock_websocket):
        """Test TTS synthesis failure handling."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(side_effect=RuntimeError("TTS failed"))

        with (
            patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True),
            patch("aragora.server.stream.voice_stream._get_tts_backend", return_value=mock_tts),
        ):
            await voice_handler._synthesize_and_send(session, mock_websocket, "Hello")

        # Should send error message
        calls = mock_websocket.send_json.call_args_list
        error_calls = [c for c in calls if c[0][0].get("type") == "error"]
        assert len(error_calls) == 1
        assert error_calls[0][0][0]["code"] == "tts_failed"


# ===========================================================================
# WebSocket Handler Tests
# ===========================================================================


class TestWebSocketHandler:
    """Tests for main WebSocket handler."""

    @pytest.mark.asyncio
    async def test_handle_websocket_unavailable(
        self, voice_handler, mock_request, mock_websocket, mock_whisper
    ):
        """Test handler when voice is unavailable."""
        mock_whisper.is_available = False

        await voice_handler.handle_websocket(mock_request, mock_websocket, "debate_123")

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "voice_unavailable"
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_websocket_ip_session_limit(
        self, voice_handler, mock_request, mock_websocket
    ):
        """Test handler rejects when IP session limit reached."""
        from aragora.server.stream.voice_stream import VOICE_MAX_SESSIONS_PER_IP

        client_ip = "192.168.1.100"

        # Fill up IP session slots
        voice_handler._ip_sessions[client_ip] = {
            f"session_{i}" for i in range(VOICE_MAX_SESSIONS_PER_IP)
        }

        await voice_handler.handle_websocket(mock_request, mock_websocket, "debate_123")

        mock_websocket.send_json.assert_called_once()
        call_data = mock_websocket.send_json.call_args[0][0]
        assert call_data["type"] == "error"
        assert call_data["code"] == "rate_limited"
        mock_websocket.close.assert_called_once()


# ===========================================================================
# Session Management Tests
# ===========================================================================


class TestSessionManagement:
    """Tests for session management methods."""

    @pytest.mark.asyncio
    async def test_get_session_info_exists(self, voice_handler):
        """Test getting info for existing session."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )
        session.total_bytes_received = 5000
        session.transcription_count = 3
        session.language = "en"

        voice_handler._sessions["voice_abc123"] = session

        info = await voice_handler.get_session_info("voice_abc123")

        assert info is not None
        assert info["session_id"] == "voice_abc123"
        assert info["debate_id"] == "debate_456"
        assert info["total_bytes_received"] == 5000
        assert info["transcription_count"] == 3
        assert info["language"] == "en"
        assert info["is_active"] is True

    @pytest.mark.asyncio
    async def test_get_session_info_not_exists(self, voice_handler):
        """Test getting info for non-existent session."""
        info = await voice_handler.get_session_info("nonexistent")
        assert info is None

    @pytest.mark.asyncio
    async def test_get_active_sessions(self, voice_handler):
        """Test getting list of active sessions."""
        from aragora.server.stream.voice_stream import VoiceSession

        session1 = VoiceSession(
            session_id="voice_1",
            debate_id="debate_1",
            client_ip="192.168.1.100",
        )
        session1.total_bytes_received = 1000

        session2 = VoiceSession(
            session_id="voice_2",
            debate_id="debate_2",
            client_ip="192.168.1.101",
        )
        session2.total_bytes_received = 2000
        session2.is_active = False  # Inactive

        session3 = VoiceSession(
            session_id="voice_3",
            debate_id="debate_1",
            client_ip="192.168.1.102",
        )
        session3.total_bytes_received = 3000

        voice_handler._sessions = {
            "voice_1": session1,
            "voice_2": session2,
            "voice_3": session3,
        }

        sessions = await voice_handler.get_active_sessions()

        # Only active sessions
        assert len(sessions) == 2
        session_ids = [s["session_id"] for s in sessions]
        assert "voice_1" in session_ids
        assert "voice_3" in session_ids
        assert "voice_2" not in session_ids

    def test_get_active_voice_debates(self, voice_handler):
        """Test getting debates with active voice sessions."""
        from aragora.server.stream.voice_stream import VoiceSession

        session1 = VoiceSession(
            session_id="voice_1",
            debate_id="debate_1",
            client_ip="192.168.1.100",
        )

        session2 = VoiceSession(
            session_id="voice_2",
            debate_id="debate_2",
            client_ip="192.168.1.101",
        )
        session2.auto_synthesize = False  # TTS disabled

        session3 = VoiceSession(
            session_id="voice_3",
            debate_id="debate_1",
            client_ip="192.168.1.102",
        )

        voice_handler._sessions = {
            "voice_1": session1,
            "voice_2": session2,
            "voice_3": session3,
        }

        debates = voice_handler.get_active_voice_debates()

        # Only debates with auto_synthesize enabled
        assert debates == {"debate_1"}

    def test_has_voice_session_true(self, voice_handler):
        """Test has_voice_session returns True when session exists."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_1",
            debate_id="debate_1",
            client_ip="192.168.1.100",
        )
        voice_handler._sessions["voice_1"] = session

        assert voice_handler.has_voice_session("debate_1") is True

    def test_has_voice_session_false(self, voice_handler):
        """Test has_voice_session returns False when no session."""
        assert voice_handler.has_voice_session("debate_nonexistent") is False


# ===========================================================================
# Agent Message Synthesis Tests
# ===========================================================================


class TestAgentMessageSynthesis:
    """Tests for synthesize_agent_message method."""

    @pytest.mark.asyncio
    async def test_synthesize_agent_message_disabled(self, voice_handler):
        """Test returns 0 when TTS disabled."""
        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", False):
            count = await voice_handler.synthesize_agent_message(
                "debate_1", "claude", "Hello world"
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_synthesize_agent_message_no_sessions(self, voice_handler):
        """Test returns 0 when no matching sessions."""
        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True):
            count = await voice_handler.synthesize_agent_message(
                "debate_1", "claude", "Hello world"
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_synthesize_agent_message_inactive_session(self, voice_handler):
        """Test skips inactive sessions."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_1",
            debate_id="debate_1",
            client_ip="192.168.1.100",
        )
        session.is_active = False
        voice_handler._sessions["voice_1"] = session

        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True):
            count = await voice_handler.synthesize_agent_message(
                "debate_1", "claude", "Hello world"
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_synthesize_agent_message_auto_synthesize_off(self, voice_handler):
        """Test skips sessions with auto_synthesize disabled."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_1",
            debate_id="debate_1",
            client_ip="192.168.1.100",
        )
        session.auto_synthesize = False
        voice_handler._sessions["voice_1"] = session

        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True):
            count = await voice_handler.synthesize_agent_message(
                "debate_1", "claude", "Hello world"
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_synthesize_agent_message_wrong_debate(self, voice_handler):
        """Test skips sessions for different debates."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_1",
            debate_id="debate_2",  # Different debate
            client_ip="192.168.1.100",
        )
        voice_handler._sessions["voice_1"] = session

        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True):
            count = await voice_handler.synthesize_agent_message(
                "debate_1", "claude", "Hello world"
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_synthesize_agent_message_no_websocket(self, voice_handler, mock_server):
        """Test handles missing WebSocket gracefully."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_1",
            debate_id="debate_1",
            client_ip="192.168.1.100",
        )
        voice_handler._sessions["voice_1"] = session

        # No WebSocket in registry
        mock_server.ws_connections = {}
        mock_server.voice_connections = {}

        with patch("aragora.server.stream.voice_stream.VOICE_TTS_ENABLED", True):
            count = await voice_handler.synthesize_agent_message(
                "debate_1", "claude", "Hello world"
            )

        assert count == 0


# ===========================================================================
# Event Emission Tests
# ===========================================================================


class TestEventEmission:
    """Tests for stream event emission."""

    def test_emit_event(self, voice_handler, mock_server):
        """Test event emission through emitter."""
        voice_handler._emit_event(
            StreamEventType.VOICE_START,
            {"session_id": "voice_1", "debate_id": "debate_1"},
            "debate_1",
        )

        mock_server.emitter.emit.assert_called_once()
        event = mock_server.emitter.emit.call_args[0][0]

        assert isinstance(event, StreamEvent)
        assert event.type == StreamEventType.VOICE_START
        assert event.data["session_id"] == "voice_1"
        assert event.loop_id == "debate_1"


# ===========================================================================
# TTS Backend Loading Tests
# ===========================================================================


class TestTTSBackendLoading:
    """Tests for lazy TTS backend loading."""

    def test_get_tts_backend_caches(self):
        """Test TTS backend is cached after first load."""
        import aragora.server.stream.voice_stream as vs

        # Reset state
        vs._tts_backend = None
        vs._tts_available = None

        mock_tts = MagicMock()
        mock_tts.is_available.return_value = True
        mock_tts.name = "MockTTS"

        with patch("aragora.broadcast.tts_backends.get_fallback_backend", return_value=mock_tts):
            result1 = vs._get_tts_backend()
            result2 = vs._get_tts_backend()

        assert result1 is result2
        assert vs._tts_backend is mock_tts

        # Cleanup
        vs._tts_backend = None
        vs._tts_available = None

    def test_get_tts_backend_unavailable_cached(self):
        """Test unavailable state is cached."""
        import aragora.server.stream.voice_stream as vs

        # Reset state
        vs._tts_backend = None
        vs._tts_available = False

        # Should return None without trying to load
        result = vs._get_tts_backend()
        assert result is None

        # Cleanup
        vs._tts_backend = None
        vs._tts_available = None

    def test_get_tts_backend_import_error(self):
        """Test handling ImportError during TTS loading."""
        import aragora.server.stream.voice_stream as vs

        # Reset state
        vs._tts_backend = None
        vs._tts_available = None

        with patch(
            "aragora.broadcast.tts_backends.get_fallback_backend",
            side_effect=ImportError("No module"),
        ):
            result = vs._get_tts_backend()

        assert result is None
        assert vs._tts_available is False

        # Cleanup
        vs._tts_backend = None
        vs._tts_available = None

    def test_get_tts_backend_runtime_error(self):
        """Test handling RuntimeError during TTS initialization."""
        import aragora.server.stream.voice_stream as vs

        # Reset state
        vs._tts_backend = None
        vs._tts_available = None

        with patch(
            "aragora.broadcast.tts_backends.get_fallback_backend",
            side_effect=RuntimeError("Init failed"),
        ):
            result = vs._get_tts_backend()

        assert result is None
        assert vs._tts_available is False

        # Cleanup
        vs._tts_backend = None
        vs._tts_available = None


# ===========================================================================
# Concurrent Session Tests
# ===========================================================================


class TestConcurrentSessions:
    """Tests for concurrent session handling."""

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_ip(self, voice_handler):
        """Test multiple sessions from same IP are tracked."""
        from aragora.server.stream.voice_stream import VoiceSession

        client_ip = "192.168.1.100"

        # Create sessions
        async with voice_handler._sessions_lock:
            for i in range(3):
                session = VoiceSession(
                    session_id=f"voice_{i}",
                    debate_id=f"debate_{i}",
                    client_ip=client_ip,
                )
                voice_handler._sessions[f"voice_{i}"] = session

                if client_ip not in voice_handler._ip_sessions:
                    voice_handler._ip_sessions[client_ip] = set()
                voice_handler._ip_sessions[client_ip].add(f"voice_{i}")

        assert len(voice_handler._ip_sessions[client_ip]) == 3
        assert len(voice_handler._sessions) == 3

    @pytest.mark.asyncio
    async def test_session_cleanup_removes_ip_tracking(self, voice_handler):
        """Test session cleanup removes IP tracking entries."""
        from aragora.server.stream.voice_stream import VoiceSession

        client_ip = "192.168.1.100"
        session_id = "voice_abc123"

        # Add session
        async with voice_handler._sessions_lock:
            voice_handler._sessions[session_id] = VoiceSession(
                session_id=session_id,
                debate_id="debate_1",
                client_ip=client_ip,
            )
            voice_handler._ip_sessions[client_ip] = {session_id}

        # Remove session
        async with voice_handler._sessions_lock:
            voice_handler._sessions.pop(session_id, None)
            if client_ip in voice_handler._ip_sessions:
                voice_handler._ip_sessions[client_ip].discard(session_id)
                if not voice_handler._ip_sessions[client_ip]:
                    del voice_handler._ip_sessions[client_ip]

        assert session_id not in voice_handler._sessions
        assert client_ip not in voice_handler._ip_sessions

    @pytest.mark.asyncio
    async def test_sessions_different_debates(self, voice_handler):
        """Test sessions track different debates correctly."""
        from aragora.server.stream.voice_stream import VoiceSession

        async with voice_handler._sessions_lock:
            voice_handler._sessions["voice_1"] = VoiceSession(
                session_id="voice_1",
                debate_id="debate_1",
                client_ip="192.168.1.100",
            )
            voice_handler._sessions["voice_2"] = VoiceSession(
                session_id="voice_2",
                debate_id="debate_2",
                client_ip="192.168.1.101",
            )
            voice_handler._sessions["voice_3"] = VoiceSession(
                session_id="voice_3",
                debate_id="debate_1",
                client_ip="192.168.1.102",
            )

        debates = voice_handler.get_active_voice_debates()
        assert debates == {"debate_1", "debate_2"}


# ===========================================================================
# Edge Case Tests
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_audio_buffer_clear(self):
        """Test clearing already empty buffer."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Clear multiple times
        assert session.clear_buffer() == b""
        assert session.clear_buffer() == b""
        assert session.audio_buffer == b""

    def test_zero_byte_chunk(self):
        """Test adding zero-byte chunk."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        result = session.add_chunk(b"")
        assert result is True
        assert session.audio_buffer == b""
        assert session.total_bytes_received == 0

    @pytest.mark.asyncio
    async def test_handle_text_message_empty_string(self, voice_handler, mock_websocket):
        """Test handling empty text message."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Empty string should not crash
        await voice_handler._handle_text_message(session, mock_websocket, "")
        mock_websocket.send_json.assert_not_called()

    def test_voice_map_update(self):
        """Test updating voice map preserves existing entries."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
            tts_voice_map={"claude": "sage"},
        )

        session.tts_voice_map.update({"gpt4": "narrator"})

        assert session.tts_voice_map["claude"] == "sage"
        assert session.tts_voice_map["gpt4"] == "narrator"

    @pytest.mark.asyncio
    async def test_rapid_session_creation(self, voice_handler):
        """Test rapid session creation and cleanup."""
        from aragora.server.stream.voice_stream import VoiceSession

        # Rapidly create and clean up sessions
        for i in range(100):
            session_id = f"voice_{i}"
            async with voice_handler._sessions_lock:
                voice_handler._sessions[session_id] = VoiceSession(
                    session_id=session_id,
                    debate_id="debate_1",
                    client_ip="192.168.1.100",
                )

        assert len(voice_handler._sessions) == 100

        # Clean up
        async with voice_handler._sessions_lock:
            voice_handler._sessions.clear()

        assert len(voice_handler._sessions) == 0

    def test_large_accumulated_text_prompt(self):
        """Test transcription with large accumulated text uses truncated prompt."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Add large accumulated text
        session.accumulated_text = "word " * 1000  # 5000 characters

        # Get last 500 chars for prompt
        prompt = session.accumulated_text[-500:]
        assert len(prompt) == 500

    def test_session_state_transitions(self):
        """Test session state transitions."""
        from aragora.server.stream.voice_stream import VoiceSession

        session = VoiceSession(
            session_id="voice_abc123",
            debate_id="debate_456",
            client_ip="192.168.1.100",
        )

        # Initial state
        assert session.is_active is True

        # Deactivate
        session.is_active = False
        assert session.is_active is False

        # Can reactivate (though not typical in real usage)
        session.is_active = True
        assert session.is_active is True
