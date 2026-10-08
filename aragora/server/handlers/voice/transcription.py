"""
Transcription endpoint handlers for speech-to-text and media processing.

Stability: STABLE

Endpoints:
- POST /api/transcription/audio - Transcribe audio file
- POST /api/transcription/video - Extract and transcribe audio from video
- POST /api/transcription/youtube - Transcribe YouTube video
- GET  /api/transcription/status/:id - Get transcription job status
- GET  /api/transcription/config - Get supported formats and limits

Features:
- Circuit breaker pattern for resilient transcription service access
- Rate limiting (10 requests/minute for audio/video, 5/minute for YouTube)
- RBAC permission checks (transcription:read, transcription:create)
- Magic byte validation for file security
- Comprehensive input validation and error handling
- Job persistence with durable store support
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
    handle_errors,
)
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip, rate_limit

logger = logging.getLogger(__name__)


# ===========================================================================
# Circuit Breaker for Transcription Services
# ===========================================================================

from aragora.resilience.simple_circuit_breaker import (
    SimpleCircuitBreaker as TranscriptionCircuitBreaker,
)

# Global circuit breaker for transcription services
_transcription_circuit_breaker = TranscriptionCircuitBreaker(
    "transcription", cooldown_seconds=60.0, half_open_max_calls=2
)


def get_transcription_circuit_breaker_status() -> dict[str, Any]:
    """Get the current status of the transcription circuit breaker.

    Returns:
        Dictionary with circuit breaker state and metrics.
    """
    return _transcription_circuit_breaker.get_status()


def reset_transcription_circuit_breaker() -> None:
    """Reset the transcription circuit breaker to closed state.

    Useful for testing or manual recovery.
    """
    _transcription_circuit_breaker.reset()


# ===========================================================================
# File Security Validation
# ===========================================================================

# Magic byte signatures for audio formats
# Format: extension -> list of (offset, signature_bytes) tuples
ALLOWED_AUDIO_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    ".mp3": [
        (0, b"\xff\xfb"),  # MP3 frame sync (MPEG Audio Layer 3)
        (0, b"\xff\xfa"),  # MP3 frame sync variant
        (0, b"\xff\xf3"),  # MP3 frame sync variant (MPEG 2.5)
        (0, b"\xff\xf2"),  # MP3 frame sync variant
        (0, b"ID3"),  # ID3v2 tag header
    ],
    ".wav": [
        (0, b"RIFF"),  # RIFF header (must also have WAVE at offset 8)
    ],
    ".m4a": [
        (4, b"ftyp"),  # ISO base media file format
    ],
    ".webm": [
        (0, b"\x1a\x45\xdf\xa3"),  # EBML header (WebM/Matroska)
    ],
    ".ogg": [
        (0, b"OggS"),  # Ogg container format
    ],
    ".flac": [
        (0, b"fLaC"),  # FLAC audio format
    ],
    ".aac": [
        (0, b"\xff\xf1"),  # ADTS AAC
        (0, b"\xff\xf9"),  # ADTS AAC variant
    ],
}

# Magic byte signatures for video formats
ALLOWED_VIDEO_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    ".mp4": [
        (4, b"ftyp"),  # ISO base media file format
    ],
    ".mov": [
        (4, b"ftyp"),  # QuickTime container (also uses ftyp)
        (4, b"moov"),  # QuickTime legacy
        (4, b"mdat"),  # QuickTime data atom
        (4, b"free"),  # QuickTime free space
        (4, b"wide"),  # QuickTime wide atom
    ],
    ".webm": [
        (0, b"\x1a\x45\xdf\xa3"),  # EBML header (WebM/Matroska)
    ],
    ".mkv": [
        (0, b"\x1a\x45\xdf\xa3"),  # EBML header (Matroska)
    ],
    ".avi": [
        (0, b"RIFF"),  # RIFF header (must also have AVI at offset 8)
    ],
}

# Pattern to detect double extensions (e.g., .mp3.exe, .wav.bat)
DOUBLE_EXTENSION_PATTERN = re.compile(
    r"\.(mp3|wav|m4a|webm|ogg|flac|aac|mp4|mov|mkv|avi)"
    r"\.(exe|bat|cmd|sh|ps1|vbs|js|jar|py|pl|rb|php|asp|aspx|jsp|cgi|com|scr|pif|msi|dll|sys)$",
    re.IGNORECASE,
)


def _validate_filename_security(filename: str) -> tuple[bool, str | None]:
    """Validate filename for security issues.

    Checks for:
    - Null bytes (path traversal prevention)
    - Double extensions (e.g., .mp3.exe)

    Args:
        filename: The filename to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    # Check for null bytes (path traversal attack)
    if "\x00" in filename:
        return False, "Invalid filename: contains null bytes"

    # Check for double extensions
    if DOUBLE_EXTENSION_PATTERN.search(filename):
        return False, "Invalid filename: double extensions not allowed"

    return True, None


def _validate_file_content(
    file_data: bytes,
    extension: str,
    is_video: bool = False,
) -> tuple[bool, str | None]:
    """Validate file content by checking magic bytes against expected signatures.

    Args:
        file_data: Raw file content bytes
        extension: Declared file extension (e.g., '.mp3')
        is_video: Whether to check against video signatures (vs audio)

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not file_data:
        return False, "Empty file content"

    # Select appropriate signature set
    signatures = ALLOWED_VIDEO_SIGNATURES if is_video else ALLOWED_AUDIO_SIGNATURES

    # Get expected signatures for this extension
    ext_lower = extension.lower()
    expected_sigs = signatures.get(ext_lower)

    if expected_sigs is None:
        return False, f"Unknown file extension: {extension}"

    # Check if file matches any expected signature
    for offset, signature in expected_sigs:
        # Ensure we have enough bytes to check
        if len(file_data) < offset + len(signature):
            continue

        # Check if signature matches at the expected offset
        if file_data[offset : offset + len(signature)] == signature:
            # Additional validation for formats that need secondary checks
            if ext_lower == ".wav" and len(file_data) >= 12:
                # WAV must have "WAVE" at offset 8
                if file_data[8:12] == b"WAVE":
                    return True, None
                # If RIFF but not WAVE, continue checking other signatures
                continue
            elif ext_lower == ".avi" and len(file_data) >= 12:
                # AVI must have "AVI " at offset 8
                if file_data[8:12] == b"AVI ":
                    return True, None
                # If RIFF but not AVI, continue checking
                continue
            else:
                return True, None

    return False, f"File content does not match expected {extension} format"


# Lazy-loaded job store for persistence
_job_store = LazyStoreFactory(
    store_name="job_store",
    import_path="aragora.storage.job_queue_store",
    factory_name="get_job_store",
    logger_context="Transcription",
)


# Rate limiters (per minute limits)
_audio_limiter = RateLimiter(requests_per_minute=10)
_youtube_limiter = RateLimiter(requests_per_minute=5)

# Maximum file sizes
MAX_AUDIO_SIZE_MB = 100
MAX_VIDEO_SIZE_MB = 500

# Supported formats
AUDIO_FORMATS = {".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac", ".aac"}
VIDEO_FORMATS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}

# In-memory job cache (backed by durable store)
_transcription_jobs: dict[str, dict[str, Any]] = {}


def _save_job(job_id: str, job_data: dict[str, Any]) -> None:
    """Save a transcription job to both memory and durable store."""
    _transcription_jobs[job_id] = job_data

    # Persist to job store for durability
    store = _job_store.get()
    if store:
        try:
            from aragora.storage.job_queue_store import QueuedJob, JobStatus

            status_map = {
                "processing": JobStatus.PROCESSING,
                "completed": JobStatus.COMPLETED,
                "failed": JobStatus.FAILED,
            }

            job = QueuedJob(
                id=job_id,
                job_type="transcription",
                payload=job_data,
                status=status_map.get(job_data.get("status", "pending"), JobStatus.PENDING),
                result=job_data.get("result"),
                error=job_data.get("error"),
            )

            # Use sync wrapper since handler is sync
            import asyncio

            try:
                asyncio.get_running_loop()
                # Schedule for later
                task = asyncio.ensure_future(store.enqueue(job))
                task.add_done_callback(
                    lambda t: logger.error("Transcription job enqueue failed: %s", t.exception())
                    if not t.cancelled() and t.exception()
                    else None
                )
            except RuntimeError:
                # No event loop, create one
                asyncio.run(store.enqueue(job))
        except (ImportError, RuntimeError, OSError, ConnectionError) as e:
            logger.debug("Failed to persist transcription job: %s", e)


def _get_job(job_id: str) -> dict[str, Any] | None:
    """Get a transcription job from memory cache or durable store."""
    # Check memory cache first
    if job_id in _transcription_jobs:
        return _transcription_jobs[job_id]

    # Try durable store
    store = _job_store.get()
    if store:
        try:
            import asyncio

            try:
                asyncio.get_running_loop()
                # Can't block in running loop, return None for now
                return None
            except RuntimeError:
                # No running loop, create one
                job = asyncio.run(store.get(job_id))

            if job:
                # Cache in memory
                job_data = {
                    "status": job.status.value if hasattr(job.status, "value") else job.status,
                    "progress": 100 if job.status == "completed" else 0,
                    "result": job.result,
                    "error": job.error,
                    **job.payload,
                }
                _transcription_jobs[job_id] = job_data
                return job_data
        except (RuntimeError, OSError, ConnectionError, AttributeError) as e:
            logger.debug("Failed to load transcription job from store: %s", e)

    return None


def _check_transcription_available() -> tuple[bool, str | None]:
    """Check if transcription module is available."""
    try:
        from aragora.transcription import get_available_backends

        backends = get_available_backends()
        if not backends:
            return False, (
                "No transcription backend available. Set OPENAI_API_KEY or install faster-whisper."
            )
        return True, None
    except ImportError:
        return False, "Transcription module not installed."


class TranscriptionHandler(BaseHandler):
    """Handler for audio/video transcription endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/transcription/audio",
        "/api/v1/transcription/video",
        "/api/v1/transcription/youtube",
        "/api/v1/transcription/youtube/info",
        "/api/v1/transcription/upload",
        "/api/v1/transcription/formats",
        "/api/v1/transcription/status",
        "/api/v1/transcription/status/*",
        "/api/v1/transcription/config",
        # Alias routes for frontend compatibility
        "/api/v1/transcribe/audio",
        "/api/v1/transcribe/video",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the request."""
        if path in (
            "/api/v1/transcription/audio",
            "/api/v1/transcription/video",
            "/api/v1/transcription/youtube",
            "/api/v1/transcription/youtube/info",
            "/api/v1/transcription/config",
            # Alias routes
            "/api/v1/transcribe/audio",
            "/api/v1/transcribe/video",
        ):
            return True
        if path.startswith("/api/v1/transcription/status/"):
            return True
        return False

    @rate_limit(requests_per_minute=60)
    @require_permission("transcription:read")
    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Handle GET requests."""
        if path == "/api/v1/transcription/config":
            return self._get_config()

        if path.startswith("/api/v1/transcription/status/"):
            job_id = path.split("/")[-1]
            return self._get_status(job_id)

        return None

    @handle_errors("transcription creation")
    @rate_limit(requests_per_minute=10)
    @require_permission("transcription:create")
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Handle POST requests."""
        client_ip = get_client_ip(handler)

        if path in ("/api/v1/transcription/audio", "/api/v1/transcribe/audio"):
            if not _audio_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Try again later.", 429)
            return await self._handle_audio_transcription(handler)

        if path in ("/api/v1/transcription/video", "/api/v1/transcribe/video"):
            if not _audio_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Try again later.", 429)
            return await self._handle_video_transcription(handler)

        if path == "/api/v1/transcription/youtube":
            if not _youtube_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Try again later.", 429)
            return await self._handle_youtube_transcription(handler)

        if path == "/api/v1/transcription/youtube/info":
            return await self._handle_youtube_info(handler)

        return None

    def _get_config(self) -> HandlerResult:
        """Return transcription configuration and supported formats."""
        available, error = _check_transcription_available()

        if not available:
            return json_response(
                {
                    "available": False,
                    "error": error,
                    "audio_formats": list(AUDIO_FORMATS),
                    "video_formats": list(VIDEO_FORMATS),
                    "max_audio_size_mb": MAX_AUDIO_SIZE_MB,
                    "max_video_size_mb": MAX_VIDEO_SIZE_MB,
                }
            )

        try:
            from aragora.transcription import get_available_backends
            from aragora.transcription.whisper_backend import WHISPER_MODELS

            backends = get_available_backends()

            return json_response(
                {
                    "available": True,
                    "backends": backends,
                    "audio_formats": list(AUDIO_FORMATS),
                    "video_formats": list(VIDEO_FORMATS),
                    "max_audio_size_mb": MAX_AUDIO_SIZE_MB,
                    "max_video_size_mb": MAX_VIDEO_SIZE_MB,
                    "models": list(WHISPER_MODELS.keys()),
                    "youtube_enabled": True,
                }
            )
        except (ImportError, AttributeError) as e:
            logger.warning("Transcription module not available: %s", e)
            return error_response("Transcription service not fully configured", 503)
        except (RuntimeError, KeyError) as e:
            logger.exception("Unexpected error getting transcription config: %s", e)
            return error_response("Failed to get configuration", 500)

    def _get_status(self, job_id: str) -> HandlerResult:
        """Get transcription job status."""
        job = _get_job(job_id)
        if not job:
            return error_response("Job not found", 404)

        return json_response(
            {
                "job_id": job_id,
                "status": job.get("status", "unknown"),
                "progress": job.get("progress", 0),
                "result": job.get("result"),
                "error": job.get("error"),
            }
        )

    async def _handle_audio_transcription(self, handler: Any) -> HandlerResult:
        """Handle audio file transcription."""
        # Check circuit breaker first
        if not _transcription_circuit_breaker.can_proceed():
            return error_response(
                "Transcription service temporarily unavailable. Please try again later.",
                503,
            )

        available, error = _check_transcription_available()
        if not available:
            return error_response(error, 503)

        # Parse multipart form data
        try:
            content_type = handler.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                return error_response("Expected multipart/form-data", 400)

            # Read the file from the request
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > MAX_AUDIO_SIZE_MB * 1024 * 1024:
                return error_response(f"File too large. Max: {MAX_AUDIO_SIZE_MB}MB", 413)

            # Parse multipart data
            file_data, filename, params = self._parse_multipart(handler, content_type)
            if not file_data:
                return error_response("No file provided", 400)

            # Security: Verify actual body size (don't trust Content-Length header)
            actual_size = len(file_data)
            if actual_size > MAX_AUDIO_SIZE_MB * 1024 * 1024:
                return error_response(f"File too large. Max: {MAX_AUDIO_SIZE_MB}MB", 413)

            # Security: Validate filename for path traversal and double extensions
            filename_valid, filename_error = _validate_filename_security(filename)
            if not filename_valid:
                return error_response(filename_error, 400)

            # Validate file extension
            suffix = Path(filename).suffix.lower()
            if suffix not in AUDIO_FORMATS:
                return error_response(
                    f"Unsupported format: {suffix}. Supported: {list(AUDIO_FORMATS)}", 400
                )

            # Security: Validate file content matches declared extension (magic bytes check)
            content_valid, content_error = _validate_file_content(file_data, suffix, is_video=False)
            if not content_valid:
                return error_response(content_error, 400)

            # Save to temp file (mkstemp avoids TOCTOU race condition)
            fd, tmp_name = tempfile.mkstemp(suffix=suffix)
            temp_path = Path(tmp_name)
            os.close(fd)
            temp_path.write_bytes(file_data)

            try:
                # Create job
                job_id = str(uuid.uuid4())
                _save_job(
                    job_id,
                    {
                        "status": "processing",
                        "progress": 0,
                        "filename": filename,
                    },
                )

                # Run transcription asynchronously with circuit breaker protection
                from aragora.transcription import transcribe_audio

                language = params.get("language")
                backend = params.get("backend")

                try:
                    result = await transcribe_audio(temp_path, language=language, backend=backend)
                    _transcription_circuit_breaker.record_success()
                except (ValueError, KeyError, TypeError, RuntimeError, OSError) as transcribe_error:
                    _transcription_circuit_breaker.record_failure()
                    _save_job(
                        job_id,
                        {
                            "status": "failed",
                            "error": safe_error_message(transcribe_error, "transcription"),
                        },
                    )
                    raise

                _save_job(
                    job_id,
                    {
                        "status": "completed",
                        "progress": 100,
                        "result": result.to_dict(),
                    },
                )

                return json_response(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "text": result.text,
                        "language": result.language,
                        "duration": result.duration,
                        "segments": [
                            {
                                "start": s.start,
                                "end": s.end,
                                "text": s.text,
                            }
                            for s in result.segments
                        ],
                        "backend": result.backend,
                        "processing_time": result.processing_time,
                    }
                )

            finally:
                # Cleanup temp file
                if temp_path.exists():
                    temp_path.unlink()

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid transcription request data: %s", e)
            return error_response(safe_error_message(e, "transcription"), 400)
        except OSError as e:
            logger.error("File I/O error during transcription: %s", e)
            return error_response(safe_error_message(e, "transcription"), 500)
        except (RuntimeError, AttributeError, ImportError) as e:
            logger.exception("Unexpected transcription error: %s", e)
            return error_response(safe_error_message(e, "transcription"), 500)

    async def _handle_video_transcription(self, handler: Any) -> HandlerResult:
        """Handle video file transcription (extract audio and transcribe)."""
        # Check circuit breaker first
        if not _transcription_circuit_breaker.can_proceed():
            return error_response(
                "Transcription service temporarily unavailable. Please try again later.",
                503,
            )

        available, error = _check_transcription_available()
        if not available:
            return error_response(error, 503)

        try:
            content_type = handler.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                return error_response("Expected multipart/form-data", 400)

            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > MAX_VIDEO_SIZE_MB * 1024 * 1024:
                return error_response(f"File too large. Max: {MAX_VIDEO_SIZE_MB}MB", 413)

            file_data, filename, params = self._parse_multipart(handler, content_type)
            if not file_data:
                return error_response("No file provided", 400)

            # Security: Verify actual body size (don't trust Content-Length header)
            actual_size = len(file_data)
            if actual_size > MAX_VIDEO_SIZE_MB * 1024 * 1024:
                return error_response(f"File too large. Max: {MAX_VIDEO_SIZE_MB}MB", 413)

            # Security: Validate filename for path traversal and double extensions
            filename_valid, filename_error = _validate_filename_security(filename)
            if not filename_valid:
                return error_response(filename_error, 400)

            suffix = Path(filename).suffix.lower()
            if suffix not in VIDEO_FORMATS:
                return error_response(
                    f"Unsupported format: {suffix}. Supported: {list(VIDEO_FORMATS)}", 400
                )

            # Security: Validate file content matches declared extension (magic bytes check)
            content_valid, content_error = _validate_file_content(file_data, suffix, is_video=True)
            if not content_valid:
                return error_response(content_error, 400)

            fd, tmp_name = tempfile.mkstemp(suffix=suffix)
            temp_path = Path(tmp_name)
            os.close(fd)
            temp_path.write_bytes(file_data)

            try:
                job_id = str(uuid.uuid4())
                _save_job(
                    job_id,
                    {
                        "status": "processing",
                        "progress": 0,
                        "filename": filename,
                    },
                )

                from aragora.transcription import transcribe_video

                language = params.get("language")
                backend = params.get("backend")

                try:
                    result = await transcribe_video(temp_path, language=language, backend=backend)
                    _transcription_circuit_breaker.record_success()
                except (ValueError, KeyError, TypeError, RuntimeError, OSError) as transcribe_error:
                    _transcription_circuit_breaker.record_failure()
                    _save_job(
                        job_id,
                        {
                            "status": "failed",
                            "error": safe_error_message(transcribe_error, "transcription"),
                        },
                    )
                    raise

                _save_job(
                    job_id,
                    {
                        "status": "completed",
                        "progress": 100,
                        "result": result.to_dict(),
                    },
                )

                return json_response(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "text": result.text,
                        "language": result.language,
                        "duration": result.duration,
                        "segments": [
                            {"start": s.start, "end": s.end, "text": s.text}
                            for s in result.segments
                        ],
                        "backend": result.backend,
                        "processing_time": result.processing_time,
                    }
                )

            finally:
                if temp_path.exists():
                    temp_path.unlink()

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid video transcription request data: %s", e)
            return error_response(safe_error_message(e, "transcription"), 400)
        except OSError as e:
            logger.error("File I/O error during video transcription: %s", e)
            return error_response(safe_error_message(e, "transcription"), 500)
        except (RuntimeError, AttributeError, ImportError) as e:
            logger.exception("Unexpected video transcription error: %s", e)
            return error_response(safe_error_message(e, "transcription"), 500)

    async def _handle_youtube_transcription(self, handler: Any) -> HandlerResult:
        """Handle YouTube video transcription."""
        # Check circuit breaker first
        if not _transcription_circuit_breaker.can_proceed():
            return error_response(
                "Transcription service temporarily unavailable. Please try again later.",
                503,
            )

        available, error = _check_transcription_available()
        if not available:
            return error_response(error, 503)

        try:
            # Parse JSON body
            body, err = self.read_json_body_validated(handler)
            if err:
                return err

            url = body.get("url")
            if not url:
                return error_response("Missing 'url' field", 400)

            # Validate YouTube URL
            from aragora.transcription.youtube import YouTubeFetcher

            if not YouTubeFetcher.is_youtube_url(url):
                return error_response("Invalid YouTube URL", 400)

            job_id = str(uuid.uuid4())
            _save_job(
                job_id,
                {
                    "status": "processing",
                    "progress": 0,
                    "url": url,
                },
            )

            try:
                from aragora.transcription import transcribe_youtube

                language = body.get("language")
                backend = body.get("backend")
                use_cache = body.get("use_cache", True)
                result = await transcribe_youtube(
                    url,
                    language=language,
                    backend=backend,
                    use_cache=use_cache,
                )
                _transcription_circuit_breaker.record_success()

                _save_job(
                    job_id,
                    {
                        "status": "completed",
                        "progress": 100,
                        "result": result.to_dict(),
                    },
                )

                return json_response(
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "text": result.text,
                        "language": result.language,
                        "duration": result.duration,
                        "segments": [
                            {"start": s.start, "end": s.end, "text": s.text}
                            for s in result.segments
                        ],
                        "backend": result.backend,
                        "processing_time": result.processing_time,
                    }
                )

            except ValueError as e:
                # Video too long or other validation error (not a service failure)
                logger.warning("YouTube transcription validation error: %s", e)
                _save_job(
                    job_id,
                    {
                        "status": "failed",
                        "error": "Invalid request",
                    },
                )
                return error_response("Invalid request", 400)
            except (ValueError, KeyError, TypeError, RuntimeError, OSError) as transcribe_error:
                # Service failure - record for circuit breaker
                _transcription_circuit_breaker.record_failure()
                _save_job(
                    job_id,
                    {
                        "status": "failed",
                        "error": safe_error_message(transcribe_error, "transcription"),
                    },
                )
                raise

        except (KeyError, TypeError) as e:
            logger.warning("Invalid YouTube transcription request data: %s", e)
            return error_response(safe_error_message(e, "transcription"), 400)
        except OSError as e:
            logger.error("File I/O error during YouTube transcription: %s", e)
            return error_response(safe_error_message(e, "transcription"), 500)
        except (RuntimeError, AttributeError, ImportError) as e:
            logger.exception("Unexpected YouTube transcription error: %s", e)
            return error_response(safe_error_message(e, "transcription"), 500)

    async def _handle_youtube_info(self, handler: Any) -> HandlerResult:
        """Get YouTube video info without transcribing."""
        try:
            body, err = self.read_json_body_validated(handler)
            if err:
                return err

            url = body.get("url")
            if not url:
                return error_response("Missing 'url' field", 400)

            from aragora.transcription.youtube import YouTubeFetcher

            if not YouTubeFetcher.is_youtube_url(url):
                return error_response("Invalid YouTube URL", 400)

            fetcher = YouTubeFetcher()
            info = await fetcher.get_video_info(url)

            return json_response(
                {
                    "video_id": info.video_id,
                    "title": info.title,
                    "duration": info.duration,
                    "channel": info.channel,
                    "description": info.description[:500] if info.description else None,
                    "upload_date": info.upload_date,
                    "view_count": info.view_count,
                    "thumbnail_url": info.thumbnail_url,
                }
            )

        except RuntimeError as e:
            # yt-dlp not installed or other runtime issues
            return error_response(safe_error_message(e, "transcription service"), 503)
        except ValueError as e:
            # Invalid URL
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (KeyError, TypeError) as e:
            logger.warning("Invalid YouTube info request data: %s", e)
            return error_response(safe_error_message(e, "video info"), 400)
        except (AttributeError, ImportError, OSError) as e:
            logger.exception("Unexpected error getting YouTube info: %s", e)
            return error_response(safe_error_message(e, "video info"), 500)

    def _parse_multipart(self, handler: Any, content_type: str) -> tuple[bytes | None, str, dict]:
        """Parse multipart form data.

        Returns:
            Tuple of (file_data, filename, params)
        """
        try:
            from email.message import EmailMessage
            from email.parser import BytesParser
            from email.policy import default

            # Get boundary from content type
            header_msg = EmailMessage()
            header_msg["Content-Type"] = content_type
            boundary = header_msg.get_param("boundary")
            if not boundary:
                return None, "", {}

            # Read body
            content_length = int(handler.headers.get("Content-Length", 0))
            body = handler.rfile.read(content_length)

            # Parse as email message
            msg_bytes = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
            msg = BytesParser(policy=default).parsebytes(msg_bytes)

            file_data = None
            filename = ""
            params: dict[str, Any] = {}

            if msg.is_multipart():
                for part in msg.walk():
                    name = part.get_param("name", header="Content-Disposition")
                    fname = part.get_filename()

                    if fname and isinstance(fname, str):
                        # This is a file
                        payload = part.get_payload(decode=True)
                        if isinstance(payload, bytes):
                            file_data = payload
                            filename = fname
                    elif name and isinstance(name, str):
                        # This is a form field
                        payload = part.get_payload(decode=True)
                        if isinstance(payload, bytes):
                            params[name] = payload.decode("utf-8", errors="replace")

            return file_data, filename, params

        except (ValueError, KeyError) as e:
            logger.warning("Invalid multipart form data: %s", e)
            return None, "", {}
        except OSError as e:
            logger.error("I/O error parsing multipart data: %s", e)
            return None, "", {}
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.exception("Unexpected error parsing multipart data: %s", e)
            return None, "", {}
