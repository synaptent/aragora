"""
YouTube audio fetching and transcription.

Provides utilities for:
1. Fetching video metadata
2. Downloading audio from YouTube videos
3. Transcribing YouTube content

Usage:
    from aragora.transcription.youtube import transcribe_youtube

    # Transcribe a YouTube video
    result = await transcribe_youtube("https://youtube.com/watch?v=dQw4w9WgXcQ")
    print(result.text)

    # Or fetch audio first
    from aragora.transcription.youtube import fetch_youtube_audio, YouTubeFetcher

    fetcher = YouTubeFetcher()
    info = await fetcher.get_video_info("https://youtube.com/watch?v=...")
    audio_path = await fetcher.download_audio("https://youtube.com/watch?v=...")
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aragora.transcription.whisper_backend import (
    TranscriptionResult,
    get_transcription_backend,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Maximum video duration (2 hours)
MAX_DURATION_SECONDS = 7200

# Cache directory for downloaded audio
CACHE_DIR = Path(os.getenv("ARAGORA_YOUTUBE_CACHE", tempfile.gettempdir())) / "aragora_youtube"

# Supported URL patterns
YOUTUBE_PATTERNS = [
    r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
    r"(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
]

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class YouTubeVideoInfo:
    """Information about a YouTube video."""

    video_id: str
    title: str
    duration: int  # seconds
    channel: str
    description: str
    upload_date: str | None = None
    view_count: int | None = None
    thumbnail_url: str | None = None

    @property
    def url(self) -> str:
        return f"https://youtube.com/watch?v={self.video_id}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with formatted duration."""
        hours, remainder = divmod(self.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            duration_formatted = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            duration_formatted = f"{minutes}:{seconds:02d}"

        return {
            "video_id": self.video_id,
            "title": self.title,
            "duration": self.duration,
            "duration_formatted": duration_formatted,
            "channel": self.channel,
            "description": self.description,
            "upload_date": self.upload_date,
            "view_count": self.view_count,
            "thumbnail_url": self.thumbnail_url,
            "url": self.url,
        }


# =============================================================================
# YouTube Fetcher
# =============================================================================


class YouTubeFetcher:
    """Fetches audio from YouTube videos using yt-dlp."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_duration: int = MAX_DURATION_SECONDS,
    ):
        self.cache_dir = cache_dir or CACHE_DIR
        self.max_duration = max_duration
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def extract_video_id(url: str) -> str | None:
        """Extract video ID from YouTube URL."""
        for pattern in YOUTUBE_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        """Check if URL is a valid YouTube URL."""
        return YouTubeFetcher.extract_video_id(url) is not None

    def _get_cache_path(self, video_id: str) -> Path:
        """Get cached audio file path for a video."""
        return self.cache_dir / f"{video_id}.mp3"

    def _is_cached(self, video_id: str) -> bool:
        """Check if audio is already cached."""
        cache_path = self._get_cache_path(video_id)
        return cache_path.exists() and cache_path.stat().st_size > 0

    async def get_video_info(self, url: str) -> YouTubeVideoInfo:
        """Get video metadata without downloading.

        Args:
            url: YouTube video URL

        Returns:
            YouTubeVideoInfo with video metadata

        Raises:
            ValueError: If URL is not a valid YouTube URL
            RuntimeError: If yt-dlp fails
        """
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError(f"Invalid YouTube URL: {url}")

        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "yt-dlp is required for YouTube transcription. Install with: pip install yt-dlp"
            )

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        loop = asyncio.get_running_loop()

        def _extract() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result: dict[str, Any] = ydl.extract_info(url, download=False)
                return result

        try:
            info = await loop.run_in_executor(None, _extract)
        except (OSError, ValueError, RuntimeError) as e:
            raise RuntimeError(f"Failed to fetch video info: {e}")

        return YouTubeVideoInfo(
            video_id=video_id,
            title=info.get("title", "Unknown"),
            duration=info.get("duration", 0),
            channel=info.get("channel", info.get("uploader", "Unknown")),
            description=info.get("description", ""),
            upload_date=info.get("upload_date"),
            view_count=info.get("view_count"),
            thumbnail_url=info.get("thumbnail"),
        )

    async def download_audio(
        self,
        url: str,
        use_cache: bool = True,
    ) -> Path:
        """Download audio from YouTube video.

        Args:
            url: YouTube video URL
            use_cache: Whether to use cached audio if available

        Returns:
            Path to downloaded audio file (MP3)

        Raises:
            ValueError: If video is too long or URL is invalid
            RuntimeError: If download fails
        """
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError(f"Invalid YouTube URL: {url}")

        # Check cache
        cache_path = self._get_cache_path(video_id)
        if use_cache and self._is_cached(video_id):
            logger.info("Using cached audio for %s", video_id)
            return cache_path

        # Get video info to check duration
        info = await self.get_video_info(url)
        if info.duration > self.max_duration:
            raise ValueError(f"Video too long: {info.duration}s (max: {self.max_duration}s)")

        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "yt-dlp is required for YouTube transcription. Install with: pip install yt-dlp"
            )

        # Download audio
        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": str(self.cache_dir / f"{video_id}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }

        loop = asyncio.get_running_loop()

        def _download() -> None:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        try:
            logger.info("Downloading audio for %s: %s", video_id, info.title)
            await loop.run_in_executor(None, _download)
        except (OSError, ValueError, RuntimeError) as e:
            raise RuntimeError(f"Failed to download audio: {e}")

        if not cache_path.exists():
            raise RuntimeError(f"Download completed but audio file not found: {cache_path}")

        logger.info(
            "Downloaded audio: %s (%.1fMB)", cache_path, cache_path.stat().st_size / 1024 / 1024
        )
        return cache_path

    def clear_cache(self, video_id: str | None = None) -> int:
        """Clear cached audio files.

        Args:
            video_id: Specific video ID to clear, or None to clear all

        Returns:
            Number of files deleted
        """
        if video_id:
            cache_path = self._get_cache_path(video_id)
            if cache_path.exists():
                cache_path.unlink()
                return 1
            return 0

        deleted = 0
        for f in self.cache_dir.glob("*.mp3"):
            f.unlink()
            deleted += 1
        return deleted


# =============================================================================
# Convenience Functions
# =============================================================================


async def fetch_youtube_audio(
    url: str,
    use_cache: bool = True,
) -> Path:
    """Fetch audio from a YouTube video.

    Args:
        url: YouTube video URL
        use_cache: Whether to use cached audio

    Returns:
        Path to audio file
    """
    fetcher = YouTubeFetcher()
    return await fetcher.download_audio(url, use_cache)


async def transcribe_youtube(
    url: str,
    language: str | None = None,
    backend: str | None = None,
    use_cache: bool = True,
) -> TranscriptionResult:
    """Transcribe a YouTube video.

    Downloads the audio and transcribes it using the specified backend.

    Args:
        url: YouTube video URL
        language: Language code (auto-detect if None)
        backend: Transcription backend (auto-select if None)
        use_cache: Whether to use cached audio

    Returns:
        TranscriptionResult with transcription and metadata

    Example:
        result = await transcribe_youtube("https://youtube.com/watch?v=dQw4w9WgXcQ")
        print(f"Transcription: {result.text}")
        print(f"Duration: {result.duration}s")
    """
    # Download audio
    fetcher = YouTubeFetcher()
    video_info = await fetcher.get_video_info(url)
    audio_path = await fetcher.download_audio(url, use_cache)

    # Transcribe
    transcriber = get_transcription_backend(backend)
    result = await transcriber.transcribe(audio_path, language)

    # Add video metadata to result
    result.model = f"{result.model} (YouTube: {video_info.video_id})"

    return result


async def get_youtube_info(url: str) -> YouTubeVideoInfo:
    """Get information about a YouTube video.

    Args:
        url: YouTube video URL

    Returns:
        YouTubeVideoInfo with video metadata
    """
    fetcher = YouTubeFetcher()
    return await fetcher.get_video_info(url)
