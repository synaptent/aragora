"""
Whisper Backend Abstraction Layer for Speech-to-Text.

Provides multiple transcription backends with fallback support:
1. OpenAI Whisper API - Cloud-based, fast, paid (requires OPENAI_API_KEY)
2. faster-whisper - Local CTranslate2-optimized (GPU recommended)
3. whisper.cpp - Local C++ implementation (CPU fallback)

Usage:
    from aragora.transcription.whisper_backend import (
        get_transcription_backend,
        TranscriptionConfig,
    )

    # Auto-select best available backend
    backend = get_transcription_backend()
    result = await backend.transcribe("audio.mp3")

    # Or specify backend explicitly
    backend = get_transcription_backend("openai")
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aragora.config import get_provider_key

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

AUDIO_FORMATS = {".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac", ".aac", ".wma"}
VIDEO_FORMATS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".flv"}
ALL_MEDIA_FORMATS = AUDIO_FORMATS | VIDEO_FORMATS

# Model sizes and their approximate VRAM requirements
WHISPER_MODELS = {
    "tiny": {"params": "39M", "vram": "~1GB", "speed": "~32x"},
    "base": {"params": "74M", "vram": "~1GB", "speed": "~16x"},
    "small": {"params": "244M", "vram": "~2GB", "speed": "~6x"},
    "medium": {"params": "769M", "vram": "~5GB", "speed": "~2x"},
    "large": {"params": "1550M", "vram": "~10GB", "speed": "~1x"},
    "large-v2": {"params": "1550M", "vram": "~10GB", "speed": "~1x"},
    "large-v3": {"params": "1550M", "vram": "~10GB", "speed": "~1x"},
}

DEFAULT_MODEL = "base"
MAX_AUDIO_DURATION_SECONDS = 7200  # 2 hours
MAX_FILE_SIZE_MB = 500

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TranscriptionSegment:
    """A segment of transcribed audio with timestamps."""

    id: int
    start: float  # seconds
    end: float  # seconds
    text: str
    tokens: list[int] | None = None
    temperature: float | None = None
    avg_logprob: float | None = None
    compression_ratio: float | None = None
    no_speech_prob: float | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    text: str
    segments: list[TranscriptionSegment]
    language: str
    duration: float  # total audio duration in seconds
    backend: str  # which backend was used

    # Optional metadata
    model: str | None = None
    word_timestamps: list[dict[str, Any]] | None = None
    processing_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "segments": [
                {
                    "id": s.id,
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                }
                for s in self.segments
            ],
            "language": self.language,
            "duration": self.duration,
            "backend": self.backend,
            "model": self.model,
            "processing_time": self.processing_time,
        }


@dataclass
class TranscriptionConfig:
    """Configuration for transcription backends."""

    # Backend priority (first available is used)
    backend_priority: list[str] = field(
        default_factory=lambda: ["openai", "faster-whisper", "whisper-cpp"]
    )

    # OpenAI Whisper API settings
    openai_api_key: str | None = None
    openai_model: str = "whisper-1"

    # Local whisper settings
    whisper_model: str = DEFAULT_MODEL
    whisper_device: str = "auto"  # auto, cuda, cpu
    whisper_compute_type: str = "auto"  # float16, int8, int8_float16

    # General settings
    language: str | None = None  # Auto-detect if None
    enable_timestamps: bool = True
    enable_word_timestamps: bool = False
    max_duration_seconds: int = MAX_AUDIO_DURATION_SECONDS
    max_file_size_mb: int = MAX_FILE_SIZE_MB

    # Output settings
    output_format: str = "verbose_json"  # text, json, verbose_json, srt, vtt

    @classmethod
    def from_env(cls) -> TranscriptionConfig:
        """Create config from environment variables."""
        backend_order = os.getenv("ARAGORA_WHISPER_BACKEND_ORDER")
        if backend_order:
            priority = [b.strip() for b in backend_order.split(",")]
        else:
            priority = ["openai", "faster-whisper", "whisper-cpp"]

        # The OpenAI key is read by the OpenAI backend when it is tried, so a
        # local-only backend order never touches that secret.
        return cls(
            backend_priority=priority,
            whisper_model=os.getenv("ARAGORA_WHISPER_MODEL", DEFAULT_MODEL),
            whisper_device=os.getenv("ARAGORA_WHISPER_DEVICE", "auto"),
            language=os.getenv("ARAGORA_WHISPER_LANGUAGE"),
            enable_timestamps=os.getenv("ARAGORA_WHISPER_TIMESTAMPS", "true").lower() == "true",
            enable_word_timestamps=os.getenv("ARAGORA_WHISPER_WORD_TIMESTAMPS", "false").lower()
            == "true",
        )


# =============================================================================
# Abstract Backend
# =============================================================================


class TranscriptionBackend(ABC):
    """Abstract base class for transcription backends."""

    name: str = "base"

    def __init__(self, config: TranscriptionConfig | None = None):
        self.config = config or TranscriptionConfig.from_env()

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available (dependencies installed, keys configured)."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (e.g., 'en', 'es'). Auto-detect if None.

        Returns:
            TranscriptionResult with text and segments
        """
        pass

    def _validate_file(self, path: Path) -> None:
        """Validate audio file before processing."""
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        suffix = path.suffix.lower()
        if suffix not in ALL_MEDIA_FORMATS:
            raise ValueError(f"Unsupported format: {suffix}. Supported: {ALL_MEDIA_FORMATS}")

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > self.config.max_file_size_mb:
            raise ValueError(
                f"File too large: {size_mb:.1f}MB (max: {self.config.max_file_size_mb}MB)"
            )


# =============================================================================
# OpenAI Whisper API Backend
# =============================================================================


class OpenAIWhisperBackend(TranscriptionBackend):
    """OpenAI Whisper API backend (cloud-based)."""

    name = "openai"

    def __init__(self, config: TranscriptionConfig | None = None, model: str | None = None):
        super().__init__(config)
        self._client: Any | None = None
        # Allow model override via constructor
        if model:
            self.config.openai_model = model
        # Validate API key is available
        api_key = self._api_key()
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable or config.openai_api_key required"
            )

    @property
    def model(self) -> str:
        """Return the OpenAI model name."""
        return self.config.openai_model

    def _api_key(self) -> str | None:
        return self.config.openai_api_key or get_provider_key(
            "OPENAI_API_KEY", consumer="OpenAI Whisper transcription"
        )

    def is_available(self) -> bool:
        """Check if OpenAI API is available."""
        api_key = self._api_key()
        if not api_key:
            return False

        try:
            import openai  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_client(self) -> Any:
        """Get or create OpenAI client."""
        if self._client is None:
            import openai

            api_key = self._api_key()
            self._client = openai.AsyncOpenAI(api_key=api_key)
        if self._client is None:
            raise RuntimeError("OpenAI client not initialized - client creation failed")
        return self._client

    async def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe using OpenAI Whisper API."""
        import time

        path = Path(audio_path)
        self._validate_file(path)

        client = self._get_client()
        lang = language or self.config.language

        start_time = time.time()

        with open(path, "rb") as f:
            # Use verbose_json for segment timestamps
            response = await client.audio.transcriptions.create(
                model=self.config.openai_model,
                file=f,
                language=lang,
                response_format="verbose_json",
                timestamp_granularities=(
                    ["segment", "word"] if self.config.enable_word_timestamps else ["segment"]
                ),
            )

        processing_time = time.time() - start_time

        # Parse segments
        segments = []
        for i, seg in enumerate(response.segments or []):
            segments.append(
                TranscriptionSegment(
                    id=i,
                    start=seg.get("start", 0),
                    end=seg.get("end", 0),
                    text=seg.get("text", ""),
                    tokens=seg.get("tokens"),
                    temperature=seg.get("temperature"),
                    avg_logprob=seg.get("avg_logprob"),
                    compression_ratio=seg.get("compression_ratio"),
                    no_speech_prob=seg.get("no_speech_prob"),
                )
            )

        # Get word timestamps if available
        word_timestamps = None
        if self.config.enable_word_timestamps and hasattr(response, "words"):
            word_timestamps = response.words

        return TranscriptionResult(
            text=response.text,
            segments=segments,
            language=response.language or lang or "en",
            duration=response.duration or 0,
            backend=self.name,
            model=self.config.openai_model,
            word_timestamps=word_timestamps,
            processing_time=processing_time,
        )


# =============================================================================
# Faster-Whisper Backend (Local)
# =============================================================================


class FasterWhisperBackend(TranscriptionBackend):
    """Local transcription using faster-whisper (CTranslate2 optimized)."""

    name = "faster-whisper"

    def __init__(self, config: TranscriptionConfig | None = None):
        super().__init__(config)
        self._model = None

    def is_available(self) -> bool:
        """Check if faster-whisper is installed."""
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_model(self) -> Any:
        """Load or get cached model."""
        if self._model is None:
            from faster_whisper import WhisperModel

            device = self.config.whisper_device
            if device == "auto":
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"

            compute_type = self.config.whisper_compute_type
            if compute_type == "auto":
                compute_type = "float16" if device == "cuda" else "int8"

            logger.info("Loading faster-whisper model: %s on %s", self.config.whisper_model, device)
            self._model = WhisperModel(
                self.config.whisper_model,
                device=device,
                compute_type=compute_type,
            )
        return self._model

    async def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe using faster-whisper."""
        import time

        path = Path(audio_path)
        self._validate_file(path)

        lang = language or self.config.language
        model = self._get_model()

        start_time = time.time()

        # Run in thread pool since faster-whisper is synchronous
        loop = asyncio.get_running_loop()
        segments_gen, info = await loop.run_in_executor(
            None,
            lambda: model.transcribe(
                str(path),
                language=lang,
                word_timestamps=self.config.enable_word_timestamps,
                vad_filter=True,
            ),
        )

        # Collect segments
        segments = []
        full_text = []
        for i, seg in enumerate(segments_gen):
            segments.append(
                TranscriptionSegment(
                    id=i,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    avg_logprob=seg.avg_logprob,
                    compression_ratio=seg.compression_ratio,
                    no_speech_prob=seg.no_speech_prob,
                )
            )
            full_text.append(seg.text)

        processing_time = time.time() - start_time

        return TranscriptionResult(
            text=" ".join(full_text).strip(),
            segments=segments,
            language=info.language or lang or "en",
            duration=info.duration or 0,
            backend=self.name,
            model=self.config.whisper_model,
            processing_time=processing_time,
        )


# =============================================================================
# Whisper.cpp Backend (Local C++)
# =============================================================================


class WhisperCppBackend(TranscriptionBackend):
    """Local transcription using whisper.cpp."""

    name = "whisper-cpp"

    def is_available(self) -> bool:
        """Check if whisper.cpp is available."""
        whisper_cpp = os.getenv("WHISPER_CPP_PATH") or shutil.which("whisper-cpp")
        return whisper_cpp is not None and Path(whisper_cpp).exists()

    async def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe using whisper.cpp."""
        import json
        import time

        path = Path(audio_path)
        self._validate_file(path)

        whisper_cpp = os.getenv("WHISPER_CPP_PATH") or shutil.which("whisper-cpp")
        if not whisper_cpp:
            raise RuntimeError("whisper.cpp not found")

        lang = language or self.config.language or "en"

        # Convert to WAV if needed (whisper.cpp prefers WAV)
        wav_path = path
        if path.suffix.lower() != ".wav":
            fd, tmp_name = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            wav_path = Path(tmp_name)
            await self._convert_to_wav(path, wav_path)

        start_time = time.time()

        try:
            # Run whisper.cpp
            cmd = [
                whisper_cpp,
                "-m",
                self._get_model_path(),
                "-f",
                str(wav_path),
                "-l",
                lang,
                "--output-json",
            ]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                raise RuntimeError(f"whisper.cpp failed: {stderr.decode()}")

            # Parse JSON output
            data = json.loads(stdout.decode())

        finally:
            # Cleanup temp WAV
            if wav_path != path and wav_path.exists():
                wav_path.unlink()

        processing_time = time.time() - start_time

        # Parse segments
        segments = []
        for i, seg in enumerate(data.get("transcription", [])):
            segments.append(
                TranscriptionSegment(
                    id=i,
                    start=seg.get("offsets", {}).get("from", 0) / 1000,
                    end=seg.get("offsets", {}).get("to", 0) / 1000,
                    text=seg.get("text", ""),
                )
            )

        return TranscriptionResult(
            text=" ".join(s.text for s in segments).strip(),
            segments=segments,
            language=lang,
            duration=segments[-1].end if segments else 0,
            backend=self.name,
            model=self.config.whisper_model,
            processing_time=processing_time,
        )

    def _get_model_path(self) -> str:
        """Get path to whisper.cpp model file."""
        model_dir = os.getenv("WHISPER_CPP_MODELS") or Path.home() / ".cache/whisper"
        model_file = f"ggml-{self.config.whisper_model}.bin"
        return str(Path(model_dir) / model_file)

    async def _convert_to_wav(self, input_path: Path, output_path: Path) -> None:
        """Convert audio to WAV format using ffmpeg."""
        cmd = [
            "ffmpeg",
            "-i",
            str(input_path),
            "-ar",
            "16000",  # 16kHz sample rate
            "-ac",
            "1",  # Mono
            "-c:a",
            "pcm_s16le",  # 16-bit PCM
            "-y",  # Overwrite
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()


# =============================================================================
# Backend Registry and Factory
# =============================================================================

# Registry of available backends
_BACKENDS: dict[str, type[TranscriptionBackend]] = {
    "openai": OpenAIWhisperBackend,
    "faster-whisper": FasterWhisperBackend,
    "whisper-cpp": WhisperCppBackend,
}

# Singleton instances
_backend_instances: dict[str, TranscriptionBackend] = {}


def _normalize_backend_name(name: str) -> str | None:
    """Normalize backend name aliases.

    Returns None for 'auto' to indicate auto-selection should be used.
    """
    lower_name = name.lower()
    # Handle auto-selection keywords
    if lower_name in ("auto", "none", ""):
        return None
    aliases = {
        "openai-whisper": "openai",
        "whisper-api": "openai",
        "local": "faster-whisper",
        "ctranslate2": "faster-whisper",
        "cpp": "whisper-cpp",
        "whisper.cpp": "whisper-cpp",
    }
    return aliases.get(lower_name, lower_name)


def get_available_backends() -> list[str]:
    """Get list of available transcription backends."""
    config = TranscriptionConfig.from_env()
    available = []
    for name, backend_cls in _BACKENDS.items():
        backend = backend_cls(config)
        if backend.is_available():
            available.append(name)
    return available


def get_transcription_backend(
    name: str | None = None,
    config: TranscriptionConfig | None = None,
) -> TranscriptionBackend:
    """Get a transcription backend by name or auto-select best available.

    Args:
        name: Backend name (openai, faster-whisper, whisper-cpp). Auto-select if None.
        config: Optional configuration. Uses env vars if not provided.

    Returns:
        TranscriptionBackend instance

    Raises:
        RuntimeError: If no backend is available
    """
    config = config or TranscriptionConfig.from_env()

    if name:
        normalized_name = _normalize_backend_name(name)
        # If normalized to None (e.g., "auto"), fall through to auto-selection
        if normalized_name is not None:
            if normalized_name not in _BACKENDS:
                raise ValueError(
                    f"Unknown backend: {normalized_name}. Available: {list(_BACKENDS.keys())}"
                )

            backend_cls = _BACKENDS[normalized_name]
            backend = backend_cls(config)
            if not backend.is_available():
                raise RuntimeError(
                    f"Backend '{normalized_name}' is not available. Check dependencies/config."
                )
            return backend

    # Auto-select first available backend from priority list
    for backend_name in config.backend_priority:
        normalized_backend_name = _normalize_backend_name(backend_name)
        if normalized_backend_name is None or normalized_backend_name not in _BACKENDS:
            continue

        backend_cls = _BACKENDS[normalized_backend_name]
        backend = backend_cls(config)
        if backend.is_available():
            logger.info("Auto-selected transcription backend: %s", normalized_backend_name)
            return backend

    available = get_available_backends()
    if not available:
        raise RuntimeError(
            "No transcription backend available. Install one of:\n"
            "  - pip install openai (requires OPENAI_API_KEY)\n"
            "  - pip install faster-whisper\n"
            "  - Install whisper.cpp and set WHISPER_CPP_PATH"
        )

    # Fallback to first available
    return _BACKENDS[available[0]](config)


# =============================================================================
# Convenience Functions
# =============================================================================


async def transcribe_audio(
    audio_path: str | Path,
    language: str | None = None,
    backend: str | None = None,
) -> TranscriptionResult:
    """Convenience function to transcribe audio.

    Args:
        audio_path: Path to audio file
        language: Language code (auto-detect if None)
        backend: Backend name (auto-select if None)

    Returns:
        TranscriptionResult
    """
    transcriber = get_transcription_backend(backend)
    return await transcriber.transcribe(audio_path, language)


async def transcribe_video(
    video_path: str | Path,
    language: str | None = None,
    backend: str | None = None,
) -> TranscriptionResult:
    """Transcribe audio from a video file.

    Extracts audio track and transcribes it.

    Args:
        video_path: Path to video file
        language: Language code (auto-detect if None)
        backend: Backend name (auto-select if None)

    Returns:
        TranscriptionResult
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {path}")

    # Extract audio to temp file (mkstemp avoids TOCTOU race condition)
    fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    audio_path = Path(tmp_name)

    try:
        cmd = [
            "ffmpeg",
            "-i",
            str(path),
            "-vn",  # No video
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",  # High quality
            "-y",  # Overwrite
            str(audio_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Failed to extract audio: {stderr.decode()}")

        # Transcribe extracted audio
        return await transcribe_audio(audio_path, language, backend)

    finally:
        # Cleanup
        if audio_path.exists():
            audio_path.unlink()
