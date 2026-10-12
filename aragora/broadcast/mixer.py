"""
Audio mixing and concatenation for Aragora Broadcast.

Combines individual audio segments into a single podcast file.
"""

from __future__ import annotations

import logging
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AudioSegment: Any
try:
    with warnings.catch_warnings():
        # audioop is deprecated in Python 3.11+ and removed in 3.13.
        # Suppress the warning when pydub imports it.
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            message=".*audioop.*",
        )
        from pydub import AudioSegment  # type: ignore[no-redef]

    PYDUB_AVAILABLE = True
except Exception as exc:  # noqa: F841
    # Import failed (pydub/ffmpeg not available) - exc captured for debugging
    AudioSegment = None  # type: ignore[no-redef,assignment]
    PYDUB_AVAILABLE = False

# Maximum audio files for FFmpeg filter_complex to prevent command overflow
MAX_AUDIO_FILES = 500


def _detect_audio_codec(audio_file: Path) -> str | None:
    """
    Detect audio codec of a file using ffprobe.

    Args:
        audio_file: Path to audio file

    Returns:
        Codec name (e.g., 'mp3', 'pcm_s16le') or None if detection fails
    """
    import subprocess

    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(audio_file),
        ]
        # subprocess with fixed args, no shell
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=False)
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("ffprobe codec detection failed for %s: %s", audio_file, e)
    return None


def _has_mixed_codecs(audio_files: list[Path]) -> bool:
    """
    Check if audio files have different codecs.

    Args:
        audio_files: List of audio file paths

    Returns:
        True if files have different codecs (require re-encoding)
    """
    codecs = set()
    for audio_file in audio_files:
        if audio_file.exists():
            codec = _detect_audio_codec(audio_file)
            if codec:
                codecs.add(codec)
    return len(codecs) > 1


def mix_audio(audio_files: list[Path], output_path: Path, format: str = "mp3") -> bool:
    """
    Mix and concatenate audio files into a single output file.

    Args:
        audio_files: List of audio file paths to concatenate
        output_path: Path for the final mixed audio file
        format: Output format ('mp3', 'wav', etc.)

    Returns:
        True if successful, False otherwise
    """
    if not audio_files:
        logger.warning("No audio files to mix")
        return False

    # Prefer ffmpeg when pydub is unavailable (Python 3.13+ compatibility).
    if not PYDUB_AVAILABLE:
        existing_files = [audio_file for audio_file in audio_files if audio_file.exists()]
        if not existing_files:
            logger.error("No valid audio files to mix")
            return False
        return mix_audio_with_ffmpeg(existing_files, output_path)

    try:
        # Load and concatenate audio segments
        combined = AudioSegment.empty()
        mixed_count = 0

        for audio_file in audio_files:
            if not audio_file.exists():
                logger.warning("Audio file not found: %s", audio_file)
                continue

            segment = AudioSegment.from_file(str(audio_file))
            combined += segment
            mixed_count += 1

        # Fail if no files were actually mixed
        if mixed_count == 0:
            logger.error("No valid audio files to mix from %s provided", len(audio_files))
            return False

        # Export the combined audio
        combined.export(str(output_path), format=format)
        return True

    except OSError as e:
        logger.error("File I/O error mixing audio: %s", e)
        return False
    except PermissionError as e:
        logger.error("Permission denied mixing audio: %s", e)
        return False
    except (RuntimeError, ValueError, TypeError) as e:
        # Catch pydub errors and other unexpected issues
        logger.error("Unexpected error mixing audio: %s: %s", type(e).__name__, e)
        return False


def mix_audio_with_ffmpeg(audio_files: list[Path], output_path: Path) -> bool:
    """
    Fallback mixing using ffmpeg directly.

    Args:
        audio_files: List of audio file paths
        output_path: Output path

    Returns:
        True if successful
    """
    if not audio_files:
        return False

    # Enforce max file limit to prevent FFmpeg command overflow
    if len(audio_files) > MAX_AUDIO_FILES:
        logger.error(
            "Too many audio files (%s > %s). Split into smaller batches.",
            len(audio_files),
            MAX_AUDIO_FILES,
        )
        return False

    import subprocess

    try:
        # Use TemporaryDirectory for secure temp file handling (auto-cleanup, restricted perms)
        with tempfile.TemporaryDirectory(prefix="aragora_ffmpeg_") as temp_dir:
            # Detect if we need to re-encode (mixed codecs like XTTS .wav + ElevenLabs .mp3)
            needs_reencode = _has_mixed_codecs(audio_files)

            if needs_reencode:
                # For mixed codecs, use filter_complex concat which decodes all inputs
                # The concat demuxer (-f concat) doesn't handle mixed formats well
                logger.info("Mixed audio formats detected, using filter_complex concat")

                # Build input arguments
                cmd = ["ffmpeg", "-y"]
                for audio_file in audio_files:
                    cmd.extend(["-i", str(audio_file.absolute())])

                # Build filter_complex for concatenating decoded audio
                # Example: [0:a][1:a][2:a]concat=n=3:v=0:a=1[out]
                n = len(audio_files)
                filter_inputs = "".join(f"[{i}:a]" for i in range(n))
                filter_str = f"{filter_inputs}concat=n={n}:v=0:a=1[out]"

                cmd.extend(
                    [
                        "-filter_complex",
                        filter_str,
                        "-map",
                        "[out]",
                        "-c:a",
                        "libmp3lame",
                        "-q:a",
                        "2",  # High quality MP3
                        str(output_path),
                    ]
                )
            else:
                # Same codec - use concat demuxer with stream copy (faster, no quality loss)
                file_list = os.path.join(temp_dir, "filelist.txt")

                # Write file list for ffmpeg concat demuxer
                with open(file_list, "w") as f:
                    for audio_file in audio_files:
                        # Escape single quotes in file paths for ffmpeg concat format
                        escaped_path = str(audio_file.absolute()).replace("'", "'\\''")
                        f.write(f"file '{escaped_path}'\n")

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    file_list,
                    "-c",
                    "copy",
                    str(output_path),
                ]

            # subprocess with fixed args, no shell
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, shell=False)
            if result.returncode != 0:
                logger.error("FFmpeg mixing failed (exit %s): %s", result.returncode, result.stderr)
                return False
            return True

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg mixing timed out after 5 minutes")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg not found. Install ffmpeg to use audio mixing.")
        return False
    except OSError as e:
        logger.error("File I/O error in FFmpeg mixing: %s", e)
        return False
    except (RuntimeError, ValueError, TypeError) as e:
        logger.error("Unexpected error in FFmpeg mixing: %s: %s", type(e).__name__, e)
        return False
