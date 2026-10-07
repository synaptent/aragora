"""
Video generator for YouTube uploads.

Converts debate audio files to video format by combining
audio with static thumbnails or animated visualizations.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    """Metadata for generated video."""

    title: str
    description: str
    duration_seconds: int
    file_size_bytes: int
    format: str = "mp4"
    resolution: str = "1920x1080"


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available (internal)."""
    return shutil.which("ffmpeg") is not None


def _check_ffprobe() -> bool:
    """Check if ffprobe is available."""
    return shutil.which("ffprobe") is not None


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available for video generation.

    Returns:
        True if ffmpeg is installed and in PATH, False otherwise
    """
    return _check_ffmpeg()


# Subprocess timeout constants
FFPROBE_TIMEOUT = 30  # seconds
FFMPEG_TIMEOUT = 600  # 10 minutes for video encoding
IMAGEMAGICK_TIMEOUT = 60  # seconds

# =============================================================================
# Input Validation Constants
# =============================================================================

# Resolution limits (width x height)
MIN_RESOLUTION = (320, 240)  # Minimum reasonable video size
MAX_RESOLUTION = (3840, 2160)  # 4K max
DEFAULT_RESOLUTION = (1920, 1080)  # Full HD

# Duration limits (seconds)
MIN_DURATION_SECONDS = 1
MAX_DURATION_SECONDS = 3600 * 4  # 4 hours max

# Audio file size limit (500 MB)
MAX_AUDIO_FILE_SIZE = 500 * 1024 * 1024

# Audio bitrate limits (kbps)
MIN_AUDIO_BITRATE = 64
MAX_AUDIO_BITRATE = 320
DEFAULT_AUDIO_BITRATE = 192


def _validate_resolution(width: int, height: int) -> tuple[int, int]:
    """Validate and clamp resolution to safe bounds.

    Args:
        width: Requested width
        height: Requested height

    Returns:
        Tuple of (clamped_width, clamped_height)

    Raises:
        ValueError: If resolution values are invalid types
    """
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError(
            f"Resolution must be integers, got width={type(width)}, height={type(height)}"
        )

    if width < 0 or height < 0:
        raise ValueError(f"Resolution cannot be negative: {width}x{height}")

    # Clamp to valid range
    clamped_width = max(MIN_RESOLUTION[0], min(width, MAX_RESOLUTION[0]))
    clamped_height = max(MIN_RESOLUTION[1], min(height, MAX_RESOLUTION[1]))

    if clamped_width != width or clamped_height != height:
        logger.warning(
            "Resolution %sx%s clamped to %sx%s", width, height, clamped_width, clamped_height
        )

    return clamped_width, clamped_height


def _validate_bitrate(bitrate: int) -> int:
    """Validate and clamp audio bitrate.

    Args:
        bitrate: Requested bitrate in kbps

    Returns:
        Clamped bitrate value
    """
    if not isinstance(bitrate, int):
        logger.warning("Invalid bitrate type %s, using default", type(bitrate))
        return DEFAULT_AUDIO_BITRATE

    clamped = max(MIN_AUDIO_BITRATE, min(bitrate, MAX_AUDIO_BITRATE))
    if clamped != bitrate:
        logger.warning("Bitrate %skbps clamped to %skbps", bitrate, clamped)

    return clamped


def _validate_audio_file(audio_path: Path) -> bool:
    """Validate audio file exists and is within size limits.

    Args:
        audio_path: Path to audio file

    Returns:
        True if valid, False otherwise
    """
    if not audio_path.exists():
        logger.error("Audio file not found: %s", audio_path)
        return False

    file_size = audio_path.stat().st_size
    if file_size > MAX_AUDIO_FILE_SIZE:
        logger.error(
            "Audio file too large: %s bytes > %s bytes limit",
            format(file_size, ","),
            format(MAX_AUDIO_FILE_SIZE, ","),
        )
        return False

    if file_size == 0:
        logger.error("Audio file is empty: %s", audio_path)
        return False

    return True


def _validate_duration(duration: int | None) -> bool:
    """Validate duration is within acceptable bounds.

    Args:
        duration: Duration in seconds

    Returns:
        True if valid or None, False if invalid
    """
    if duration is None:
        return True

    if duration < MIN_DURATION_SECONDS:
        logger.warning("Audio duration %ss is below minimum %ss", duration, MIN_DURATION_SECONDS)
        return False

    if duration > MAX_DURATION_SECONDS:
        logger.error(
            "Audio duration %ss exceeds maximum %ss (%s hours)",
            duration,
            MAX_DURATION_SECONDS,
            MAX_DURATION_SECONDS // 3600,
        )
        return False

    return True


async def get_audio_duration(audio_path: Path) -> int | None:
    """
    Get audio duration in seconds using ffprobe.

    Args:
        audio_path: Path to audio file

    Returns:
        Duration in seconds or None if failed
    """
    if not _check_ffprobe():
        logger.warning("ffprobe not available")
        return None

    process = None
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(audio_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=FFPROBE_TIMEOUT)

        if process.returncode == 0:
            duration_str = stdout.decode("utf-8", errors="replace").strip()
            return int(float(duration_str))
    except asyncio.TimeoutError:
        logger.error("ffprobe timed out after %ss for %s", FFPROBE_TIMEOUT, audio_path)
        if process:
            process.kill()
            await process.wait()
    except (RuntimeError, OSError, ValueError) as e:
        logger.error("Failed to get audio duration: %s", e)

    return None


async def generate_thumbnail(
    title: str,
    agents: list[str],
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
) -> bool:
    """
    Generate a simple thumbnail image for the video.

    Uses ImageMagick if available, otherwise creates a basic solid color image.

    Args:
        title: Video title
        agents: List of agent names
        output_path: Where to save the thumbnail
        width: Image width (clamped to valid range)
        height: Image height (clamped to valid range)

    Returns:
        True if successful
    """
    # Validate and clamp resolution
    try:
        width, height = _validate_resolution(width, height)
    except ValueError as e:
        logger.error("Invalid thumbnail resolution: %s", e)
        return False
    # Check for ImageMagick
    if not shutil.which("convert"):
        # Create a simple blank PNG using pure Python
        # This creates a minimal valid 1920x1080 PNG
        try:
            # Use a simple approach - create solid color thumbnail
            # For production, you'd want a proper image generation library
            import struct
            import zlib

            def create_png(width: int, height: int, color: tuple) -> bytes:
                """Create a minimal PNG with solid color."""
                # PNG header
                header = b"\x89PNG\r\n\x1a\n"

                # IHDR chunk
                ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
                ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
                ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

                # IDAT chunk - scanlines with filter byte
                raw_data = b""
                for _ in range(height):
                    raw_data += b"\x00"  # Filter byte
                    for _ in range(width):
                        raw_data += bytes(color)

                compressed = zlib.compress(raw_data, 9)
                idat_crc = zlib.crc32(b"IDAT" + compressed)
                idat = (
                    struct.pack(">I", len(compressed))
                    + b"IDAT"
                    + compressed
                    + struct.pack(">I", idat_crc)
                )

                # IEND chunk
                iend_crc = zlib.crc32(b"IEND")
                iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

                return header + ihdr + idat + iend

            # Dark blue background
            png_data = create_png(width, height, (30, 40, 80))
            output_path.write_bytes(png_data)
            return True

        except (RuntimeError, OSError, ValueError, OverflowError) as e:
            logger.error("Failed to create thumbnail: %s", e)
            return False

    # Use ImageMagick for nicer thumbnail
    process = None
    try:
        agent_text = ", ".join(agents[:3])
        if len(agents) > 3:
            agent_text += f" +{len(agents) - 3}"

        # Truncate title if too long
        display_title = title[:60] + "..." if len(title) > 60 else title

        cmd = [
            "convert",
            "-size",
            f"{width}x{height}",
            "xc:#1e2850",  # Dark blue background
            "-font",
            "Helvetica",
            "-pointsize",
            "72",
            "-fill",
            "white",
            "-gravity",
            "center",
            "-annotate",
            "+0-100",
            display_title,
            "-pointsize",
            "36",
            "-fill",
            "#aaaaaa",
            "-annotate",
            "+0+100",
            "Aragora Debate",
            "-annotate",
            "+0+160",
            agent_text,
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=IMAGEMAGICK_TIMEOUT)
        return process.returncode == 0 and output_path.exists()

    except asyncio.TimeoutError:
        logger.error("ImageMagick timed out after %ss", IMAGEMAGICK_TIMEOUT)
        if process:
            process.kill()
            await process.wait()
        return False
    except (RuntimeError, OSError, ValueError) as e:
        logger.error("Failed to generate thumbnail with ImageMagick: %s", e)
        return False


class VideoGenerator:
    """
    Convert audio to video for YouTube upload.

    Uses ffmpeg to combine audio with static or animated visuals.
    """

    def __init__(self, output_dir: Path | None = None):
        """
        Initialize video generator.

        Args:
            output_dir: Directory for output videos. Defaults to temp dir.
        """
        self.output_dir = output_dir or Path(tempfile.gettempdir()) / "aragora_videos"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ffmpeg_available = _check_ffmpeg()
        if not self.ffmpeg_available:
            logger.warning("ffmpeg not available - video generation disabled")

    async def generate_static_video(
        self,
        audio_path: Path,
        title: str,
        agents: list[str],
        output_path: Path | None = None,
        audio_bitrate: int = DEFAULT_AUDIO_BITRATE,
        width: int = 1920,
        height: int = 1080,
    ) -> Path | None:
        """
        Generate video with static thumbnail and audio track.

        This is the simplest approach - just a still image with audio.

        Args:
            audio_path: Path to audio file
            title: Video title (used for thumbnail)
            agents: List of agents (used for thumbnail)
            output_path: Output video path. Auto-generated if not provided.
            audio_bitrate: Audio bitrate in kbps (default 192, clamped to valid range)
            width: Video width in pixels (default 1920)
            height: Video height in pixels (default 1080)

        Returns:
            Path to video file or None if failed
        """
        if not self.ffmpeg_available:
            logger.error("ffmpeg not available")
            return None

        # Validate audio file (exists, size limits)
        if not _validate_audio_file(audio_path):
            return None

        # Validate bitrate
        audio_bitrate = _validate_bitrate(audio_bitrate)

        # Generate output path
        if output_path is None:
            output_path = self.output_dir / f"{audio_path.stem}.mp4"

        # Create temporary thumbnail
        thumb_path = self.output_dir / f"{audio_path.stem}_thumb.png"

        process = None
        try:
            # Generate thumbnail
            if not await generate_thumbnail(title, agents, thumb_path):
                logger.warning("Using fallback thumbnail generation")
                # Create minimal valid PNG as fallback
                thumb_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

            # Get audio duration and validate
            duration = await get_audio_duration(audio_path)
            if not _validate_duration(duration):
                return None

            # Generate video with ffmpeg
            # -loop 1: loop the image
            # -tune stillimage: optimize for static content
            # -shortest: end when audio ends
            # -vf scale: scale to target resolution
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-loop",
                "1",
                "-i",
                str(thumb_path),
                "-i",
                str(audio_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                f"{audio_bitrate}k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                "-movflags",
                "+faststart",  # Web optimization
                str(output_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=FFMPEG_TIMEOUT)

            if process.returncode != 0:
                logger.error("ffmpeg failed: %s", stderr.decode("utf-8", errors="replace")[:500])
                return None

            if output_path.exists():
                logger.info("Generated video: %s", output_path)
                return output_path

        except asyncio.TimeoutError:
            logger.error("ffmpeg timed out after %ss for %s", FFMPEG_TIMEOUT, audio_path)
            if process:
                process.kill()
                await process.wait()

        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Video generation failed: %s", e)

        finally:
            # Cleanup thumbnail
            if thumb_path.exists():
                thumb_path.unlink()

        return None

    async def generate_waveform_video(
        self,
        audio_path: Path,
        output_path: Path | None = None,
        color: str = "0x4488ff",
        audio_bitrate: int = DEFAULT_AUDIO_BITRATE,
    ) -> Path | None:
        """
        Generate video with animated audio waveform.

        More visually interesting than static image.

        Args:
            audio_path: Path to audio file
            output_path: Output video path
            color: Waveform color in hex (validated to prevent injection)
            audio_bitrate: Audio bitrate in kbps (default 192, clamped to valid range)

        Returns:
            Path to video file or None if failed
        """
        # Validate color to prevent ffmpeg filter injection
        # Only allow hex colors (0xRRGGBB or #RRGGBB) or named colors (alphanumeric)
        import re

        if not re.match(r"^(0x[0-9a-fA-F]{6}|#[0-9a-fA-F]{6}|[a-zA-Z]+)$", color):
            logger.warning("Invalid color format '%s', using default", color)
            color = "0x4488ff"

        if not self.ffmpeg_available:
            logger.error("ffmpeg not available")
            return None

        # Validate audio file (exists, size limits)
        if not _validate_audio_file(audio_path):
            return None

        # Validate bitrate
        audio_bitrate = _validate_bitrate(audio_bitrate)

        if output_path is None:
            output_path = self.output_dir / f"{audio_path.stem}_waveform.mp4"

        process = None
        try:
            # Get duration and validate
            duration = await get_audio_duration(audio_path)
            if not _validate_duration(duration):
                return None

            # Generate waveform video using ffmpeg's showwaves filter
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-filter_complex",
                f"[0:a]showwaves=s=1920x1080:mode=cline:colors={color}[v]",
                "-map",
                "[v]",
                "-map",
                "0:a",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-b:a",
                f"{audio_bitrate}k",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=FFMPEG_TIMEOUT)

            if process.returncode != 0:
                logger.error(
                    "ffmpeg waveform failed: %s", stderr.decode("utf-8", errors="replace")[:500]
                )
                return None

            if output_path.exists():
                logger.info("Generated waveform video: %s", output_path)
                return output_path

        except asyncio.TimeoutError:
            logger.error("ffmpeg waveform timed out after %ss for %s", FFMPEG_TIMEOUT, audio_path)
            if process:
                process.kill()
                await process.wait()

        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Waveform video generation failed: %s", e)

        return None

    def get_video_metadata(self, video_path: Path) -> VideoMetadata | None:
        """
        Get metadata for a generated video.

        Args:
            video_path: Path to video file

        Returns:
            VideoMetadata or None if failed
        """
        if not video_path.exists():
            return None

        try:
            file_size = video_path.stat().st_size

            # Get duration using ffprobe synchronously
            import subprocess

            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [  # noqa: S607 -- fixed command
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=FFPROBE_TIMEOUT,
                shell=False,
            )

            if result.returncode != 0:
                logger.warning("ffprobe failed for %s: %s", video_path, result.stderr)
                duration = 0
            else:
                try:
                    duration = int(float(result.stdout.strip()))
                except ValueError:
                    logger.warning("ffprobe returned invalid duration: %r", result.stdout)
                    duration = 0

            return VideoMetadata(
                title=video_path.stem,
                description="",
                duration_seconds=duration,
                file_size_bytes=file_size,
            )

        except subprocess.TimeoutExpired:
            logger.error("ffprobe timed out after %ss for %s", FFPROBE_TIMEOUT, video_path)
            return None
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Failed to get video metadata: %s", e)
            return None

    def cleanup(self, video_path: Path) -> None:
        """Remove a generated video file."""
        if video_path.exists():
            video_path.unlink()


async def generate_video(
    audio_path: Path,
    output_path: Path,
    title: str,
    description: str,
    resolution: tuple[int, int] = (1920, 1080),
    thumbnail_path: str | None = None,
) -> bool:
    """
    Generate a video from audio with a static thumbnail.

    Convenience function that wraps VideoGenerator for simple use cases.

    Args:
        audio_path: Path to source audio file
        output_path: Path for output video file
        title: Video title (used for thumbnail generation)
        description: Video description (metadata only, not rendered)
        resolution: Video resolution as (width, height) tuple (default (1920, 1080))
        thumbnail_path: Optional path to custom thumbnail image. If not provided, one is generated.

    Returns:
        True if video was generated successfully, False otherwise
    """
    generator = VideoGenerator(output_dir=output_path.parent)

    # Extract width and height from tuple
    try:
        width, height = resolution
    except (ValueError, TypeError):
        logger.warning("Invalid resolution format '%s', using default 1920x1080", resolution)
        width, height = 1920, 1080

    # Convert thumbnail_path string to Path if provided
    thumb_path: Path | None = Path(thumbnail_path) if thumbnail_path else None

    # If custom thumbnail provided, use it directly with ffmpeg
    if thumb_path and thumb_path.exists():
        # Use ffmpeg directly with the provided thumbnail
        if not generator.ffmpeg_available:
            logger.error("ffmpeg not available")
            return False

        if not _validate_audio_file(audio_path):
            return False

        duration = await get_audio_duration(audio_path)
        if not _validate_duration(duration):
            return False

        process = None
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(thumb_path),
                "-i",
                str(audio_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                f"{DEFAULT_AUDIO_BITRATE}k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=FFMPEG_TIMEOUT)

            if process.returncode != 0:
                logger.error("ffmpeg failed: %s", stderr.decode("utf-8", errors="replace")[:500])
                return False

            return output_path.exists()

        except asyncio.TimeoutError:
            logger.error("ffmpeg timed out after %ss", FFMPEG_TIMEOUT)
            if process:
                process.kill()
                await process.wait()
            return False
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Video generation failed: %s", e)
            return False

    # Generate video with auto-generated thumbnail
    result = await generator.generate_static_video(
        audio_path=audio_path,
        title=title,
        agents=[],  # No agents list available at this level
        output_path=output_path,
        width=width,
        height=height,
    )

    return result is not None
