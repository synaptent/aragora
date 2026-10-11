"""
Smart Upload Handler - Auto-detect file types and route to appropriate processors.

Routes:
- POST /api/upload/smart - Upload and auto-process files
- POST /api/upload/batch - Batch upload with per-file processing options
- GET  /api/upload/status/{id} - Check processing status
"""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from aragora.server.handlers.utils.responses import error_dict
from aragora.server.handlers.utils.file_validation import (
    validate_file_upload,
)

logger = logging.getLogger(__name__)

# Knowledge processing enabled by default (can be disabled via env var)
KNOWLEDGE_PROCESSING_DEFAULT = (
    os.environ.get("ARAGORA_KNOWLEDGE_AUTO_PROCESS", "true").lower() == "true"
)

# Magic byte signatures for content-type validation
# Maps file signatures to (expected_mime_type, expected_extensions)
MAGIC_SIGNATURES: dict[bytes, tuple[str, list[str]]] = {
    # Images
    b"\x89PNG\r\n\x1a\n": ("image/png", [".png"]),
    b"\xff\xd8\xff": ("image/jpeg", [".jpg", ".jpeg"]),
    b"GIF87a": ("image/gif", [".gif"]),
    b"GIF89a": ("image/gif", [".gif"]),
    b"RIFF": ("image/webp", [".webp"]),  # WebP (check for WEBP after RIFF)
    # Documents
    b"%PDF": ("application/pdf", [".pdf"]),
    # Archives (also covers Office docs which are ZIP-based)
    b"PK\x03\x04": ("application/zip", [".zip", ".docx", ".xlsx", ".pptx", ".odt"]),
    b"PK\x05\x06": ("application/zip", [".zip"]),  # Empty archive
    b"PK\x07\x08": ("application/zip", [".zip"]),  # Spanned archive
    # Executables (DANGEROUS)
    b"MZ": ("application/x-executable", [".exe", ".dll"]),
    b"\x7fELF": ("application/x-executable", [".elf", ".so", ".out"]),
    b"\xca\xfe\xba\xbe": ("application/x-mach-binary", [".dylib"]),  # Mach-O
    b"\xcf\xfa\xed\xfe": ("application/x-mach-binary", [".dylib", ".bundle"]),  # Mach-O 64
    b"\xfe\xed\xfa\xce": ("application/x-mach-binary", []),  # Mach-O 32-bit BE
    b"\xfe\xed\xfa\xcf": ("application/x-mach-binary", []),  # Mach-O 64-bit BE
    # Scripts (potentially dangerous)
    b"#!": ("text/x-script", [".sh", ".bash", ".py", ".pl", ".rb"]),
    # Audio
    b"ID3": ("audio/mpeg", [".mp3"]),
    b"\xff\xfb": ("audio/mpeg", [".mp3"]),
    b"\xff\xfa": ("audio/mpeg", [".mp3"]),
    b"fLaC": ("audio/flac", [".flac"]),
    b"OggS": ("audio/ogg", [".ogg"]),
    # Video
    b"\x00\x00\x00\x1cftyp": ("video/mp4", [".mp4", ".m4v", ".m4a"]),
    b"\x00\x00\x00\x20ftyp": ("video/mp4", [".mp4", ".m4v", ".m4a"]),
    # Compressed
    b"\x1f\x8b": ("application/gzip", [".gz", ".tgz"]),
    b"BZh": ("application/x-bzip2", [".bz2"]),
    b"\xfd7zXZ\x00": ("application/x-xz", [".xz"]),
    b"Rar!\x1a\x07": ("application/x-rar", [".rar"]),
    b"7z\xbc\xaf\x27\x1c": ("application/x-7z-compressed", [".7z"]),
}

# Dangerous MIME types that should be blocked
DANGEROUS_MIME_TYPES: set[str] = {
    "application/x-executable",
    "application/x-mach-binary",
    "application/x-dosexec",
    "application/x-msdownload",
    "application/x-sharedlib",
    "application/vnd.microsoft.portable-executable",
}

# Dangerous extensions that should be blocked
DANGEROUS_EXTENSIONS: set[str] = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".msi",
    ".msp",
    ".vbs",
    ".vbe",
    ".jse",
    ".ws",
    ".wsf",
    ".wsc",
    ".wsh",
    ".ps1",
    ".psm1",
    ".psd1",
}


@dataclass
class ContentValidationResult:
    """Result of content-type validation."""

    valid: bool
    detected_mime: str | None = None
    expected_extensions: list[str] | None = None
    is_dangerous: bool = False
    mismatch_warning: str | None = None


def validate_content_type(
    content: bytes,
    filename: str,
    claimed_mime: str | None = None,
) -> ContentValidationResult:
    """
    Validate file content matches the claimed type using magic bytes.

    Args:
        content: Raw file bytes
        filename: Claimed filename
        claimed_mime: Optional claimed MIME type

    Returns:
        ContentValidationResult with validation details
    """
    ext = Path(filename).suffix.lower()

    # Check for dangerous extensions first
    if ext in DANGEROUS_EXTENSIONS:
        logger.warning("[SECURITY] Blocked dangerous file extension: %s", filename)
        return ContentValidationResult(
            valid=False,
            is_dangerous=True,
            mismatch_warning=f"Dangerous file extension blocked: {ext}",
        )

    # Check magic bytes
    detected_mime = None
    expected_extensions = None

    for signature, (mime_type, extensions) in MAGIC_SIGNATURES.items():
        if content.startswith(signature):
            # Special case for WEBP: check for "WEBP" marker after RIFF
            if signature == b"RIFF":
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    detected_mime = "image/webp"
                    expected_extensions = [".webp"]
                else:
                    # RIFF but not WEBP (could be WAV, AVI, etc.)
                    continue
            else:
                detected_mime = mime_type
                expected_extensions = extensions
            break

    # Check for ftyp-based video (variable offset)
    if detected_mime is None and len(content) >= 12:
        # ftyp can appear at offset 4 with variable box size
        for offset in (4, 8):
            if offset + 4 <= len(content) and content[offset : offset + 4] == b"ftyp":
                detected_mime = "video/mp4"
                expected_extensions = [".mp4", ".m4v", ".m4a", ".mov"]
                break

    # Block dangerous detected MIME types
    if detected_mime in DANGEROUS_MIME_TYPES:
        logger.warning(
            "[SECURITY] Blocked dangerous file type detected in %s: %s",
            filename,
            detected_mime,
        )
        return ContentValidationResult(
            valid=False,
            detected_mime=detected_mime,
            is_dangerous=True,
            mismatch_warning=f"Dangerous file type blocked: {detected_mime}",
        )

    # Check for extension mismatch
    mismatch_warning = None
    if detected_mime and expected_extensions:
        if ext and ext not in expected_extensions:
            # Special case: Office documents are ZIP-based
            office_extensions = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
            if detected_mime == "application/zip" and ext in office_extensions:
                # This is expected - Office docs are ZIP files
                pass
            else:
                mismatch_warning = (
                    f"Content-type mismatch: file '{filename}' has extension '{ext}' "
                    f"but content appears to be {detected_mime} "
                    f"(expected extensions: {', '.join(expected_extensions)})"
                )
                logger.warning("[SECURITY] %s", mismatch_warning)

    # Check claimed MIME vs detected
    if claimed_mime and detected_mime:
        # Normalize MIME types for comparison
        claimed_base = claimed_mime.split(";")[0].strip().lower()
        if claimed_base != detected_mime.lower():
            # Allow some common variations
            mime_aliases = {
                ("image/jpg", "image/jpeg"),
                ("audio/mp3", "audio/mpeg"),
                ("video/quicktime", "video/mp4"),
            }
            if (claimed_base, detected_mime.lower()) not in mime_aliases and (
                detected_mime.lower(),
                claimed_base,
            ) not in mime_aliases:
                warning = (
                    f"Claimed MIME type '{claimed_mime}' doesn't match "
                    f"detected type '{detected_mime}' for file '{filename}'"
                )
                if mismatch_warning:
                    mismatch_warning += f"; {warning}"
                else:
                    mismatch_warning = warning
                logger.warning("[SECURITY] %s", warning)

    return ContentValidationResult(
        valid=True,
        detected_mime=detected_mime,
        expected_extensions=expected_extensions,
        is_dangerous=False,
        mismatch_warning=mismatch_warning,
    )


# Try to import handler base
try:
    from ..base import (
        BaseHandler,
        HandlerResult,
        auto_error_response,  # noqa: F401
        error_response,
        json_response,
        handle_errors,
    )
    from ..utils.rate_limit import rate_limit  # noqa: F401
    from aragora.rbac.decorators import require_permission

    HANDLER_BASE_AVAILABLE = True
except ImportError:
    HANDLER_BASE_AVAILABLE = False
    logger.warning(
        "Handler base not available - SmartUploadHandler will have limited functionality"
    )


class FileCategory(str, Enum):
    """Categories of files for processing."""

    CODE = "code"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE = "image"
    DATA = "data"
    ARCHIVE = "archive"
    UNKNOWN = "unknown"


class ProcessingAction(str, Enum):
    """Processing actions based on file category."""

    INDEX = "index"  # Repository/code indexing
    EXTRACT = "extract"  # Document text extraction
    TRANSCRIBE = "transcribe"  # Audio/video transcription
    OCR = "ocr"  # Image text extraction
    PARSE = "parse"  # Data file parsing
    EXPAND = "expand"  # Archive extraction
    SKIP = "skip"  # No processing


# File type detection patterns
FILE_PATTERNS: dict[FileCategory, dict[str, list[str]]] = {
    FileCategory.CODE: {
        "extensions": [
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".scala",
            ".r",
            ".jl",
            ".lua",
            ".sh",
            ".bash",
            ".zsh",
            ".ps1",
            ".sql",
            ".graphql",
            ".proto",
            ".ex",
            ".exs",
        ],
        "mime_patterns": ["text/x-", "application/x-python", "application/javascript"],
    },
    FileCategory.DOCUMENT: {
        "extensions": [
            ".pdf",
            ".docx",
            ".doc",
            ".txt",
            ".md",
            ".markdown",
            ".rtf",
            ".odt",
            ".pptx",
            ".ppt",
            ".xlsx",
            ".xls",
            ".epub",
            ".mobi",
        ],
        "mime_patterns": [
            "application/pdf",
            "application/vnd.openxmlformats",
            "application/msword",
            "text/plain",
            "text/markdown",
        ],
    },
    FileCategory.AUDIO: {
        "extensions": [".mp3", ".m4a", ".wav", ".webm", ".ogg", ".flac", ".aac", ".wma"],
        "mime_patterns": ["audio/"],
    },
    FileCategory.VIDEO: {
        "extensions": [".mp4", ".webm", ".mov", ".mkv", ".avi", ".wmv", ".m4v"],
        "mime_patterns": ["video/"],
    },
    FileCategory.IMAGE: {
        "extensions": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff", ".bmp", ".svg", ".heic"],
        "mime_patterns": ["image/"],
    },
    FileCategory.DATA: {
        "extensions": [".json", ".xml", ".csv", ".yaml", ".yml", ".toml", ".ini", ".conf"],
        "mime_patterns": ["application/json", "application/xml", "text/csv", "text/yaml"],
    },
    FileCategory.ARCHIVE: {
        "extensions": [".zip", ".tar", ".gz", ".tgz", ".rar", ".7z", ".bz2", ".xz"],
        "mime_patterns": ["application/zip", "application/x-tar", "application/gzip"],
    },
}

# Map categories to default processing actions
CATEGORY_ACTIONS: dict[FileCategory, ProcessingAction] = {
    FileCategory.CODE: ProcessingAction.INDEX,
    FileCategory.DOCUMENT: ProcessingAction.EXTRACT,
    FileCategory.AUDIO: ProcessingAction.TRANSCRIBE,
    FileCategory.VIDEO: ProcessingAction.TRANSCRIBE,
    FileCategory.IMAGE: ProcessingAction.OCR,
    FileCategory.DATA: ProcessingAction.PARSE,
    FileCategory.ARCHIVE: ProcessingAction.EXPAND,
    FileCategory.UNKNOWN: ProcessingAction.SKIP,
}


@dataclass
class UploadResult:
    """Result of a file upload and processing."""

    id: str
    filename: str
    size: int
    category: FileCategory
    action: ProcessingAction
    status: str  # pending, processing, completed, failed
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


# In-memory storage for upload status (would use Redis/DB in production)
_upload_results: dict[str, UploadResult] = {}


def detect_file_category(filename: str, mime_type: str | None = None) -> FileCategory:
    """
    Detect file category from filename and optional MIME type.

    Args:
        filename: Name of the file
        mime_type: Optional MIME type hint

    Returns:
        Detected FileCategory
    """
    ext = Path(filename).suffix.lower()

    # Check extension-based patterns first
    for category, patterns in FILE_PATTERNS.items():
        if ext in patterns["extensions"]:
            return category

    # Fallback to MIME type patterns
    if mime_type:
        for category, patterns in FILE_PATTERNS.items():
            for pattern in patterns["mime_patterns"]:
                if mime_type.startswith(pattern):
                    return category

    # Try guessing MIME type from extension
    guessed_mime, _ = mimetypes.guess_type(filename)
    if guessed_mime:
        for category, patterns in FILE_PATTERNS.items():
            for pattern in patterns["mime_patterns"]:
                if guessed_mime.startswith(pattern):
                    return category

    return FileCategory.UNKNOWN


def get_processing_action(category: FileCategory) -> ProcessingAction:
    """Get the default processing action for a category."""
    return CATEGORY_ACTIONS.get(category, ProcessingAction.SKIP)


async def process_file(
    file_content: bytes,
    filename: str,
    category: FileCategory,
    action: ProcessingAction,
    options: dict[str, Any] | None = None,
    *,
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    Process a file based on its category and action.

    Args:
        file_content: Raw file bytes
        filename: Original filename
        category: Detected file category
        action: Processing action to perform
        options: Optional processing options
        org_id: Verified organization that owns any extracted knowledge;
            never read from ``options``

    Returns:
        Processing result dict
    """
    options = options or {}
    result: dict[str, Any] = {
        "filename": filename,
        "category": category.value,
        "action": action.value,
        "size": len(file_content),
    }

    try:
        if action == ProcessingAction.TRANSCRIBE:
            result.update(await _transcribe_audio_video(file_content, filename, options))

        elif action == ProcessingAction.EXTRACT:
            result.update(await _extract_document_text(file_content, filename, options))

        elif action == ProcessingAction.OCR:
            result.update(await _ocr_image(file_content, filename, options))

        elif action == ProcessingAction.PARSE:
            result.update(await _parse_data_file(file_content, filename, options))

        elif action == ProcessingAction.INDEX:
            result.update(await _index_code_file(file_content, filename, options))

        elif action == ProcessingAction.EXPAND:
            result.update(await _expand_archive(file_content, filename, options))

        else:
            # Skip or unknown - just store the file
            result["stored"] = True

        if _resolve_bool(options.get("process_knowledge"), KNOWLEDGE_PROCESSING_DEFAULT):
            knowledge_result = await _queue_knowledge_from_result(
                options=options,
                category=category,
                action=action,
                filename=filename,
                processing_result=result,
                org_id=org_id,
            )
            if knowledge_result and knowledge_result.get("knowledge_processing"):
                result["knowledge_processing"] = knowledge_result.get("knowledge_processing")

    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
        logger.error("Error processing %s: %s", filename, e)
        result["error"] = "Internal server error"

    return result


def _resolve_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return default


def _build_ingest_metadata(
    options: dict[str, Any],
    category: FileCategory,
    action: ProcessingAction,
    filename: str,
    processing_result: dict[str, Any],
) -> dict[str, Any]:
    metadata = options.get("metadata")
    base_metadata: dict[str, Any] = metadata if isinstance(metadata, dict) else {}

    merged = dict(base_metadata)
    merged.setdefault("source", "smart_upload")
    merged.setdefault("source_category", category.value)
    merged.setdefault("source_action", action.value)
    merged.setdefault("filename", filename)
    if options.get("mime_type"):
        merged.setdefault("mime_type", options.get("mime_type"))

    if action == ProcessingAction.TRANSCRIBE:
        if processing_result.get("language"):
            merged.setdefault("transcription_language", processing_result.get("language"))
        if processing_result.get("duration"):
            merged.setdefault("transcription_duration", processing_result.get("duration"))
        if processing_result.get("segments"):
            merged.setdefault("segment_count", len(processing_result.get("segments") or []))
    elif action == ProcessingAction.OCR:
        if processing_result.get("confidence") is not None:
            merged.setdefault("ocr_confidence", processing_result.get("confidence"))

    return merged


def _build_knowledge_filename(filename: str, suffix: str) -> str:
    if not suffix:
        return filename
    base = Path(filename).name
    return f"{base}.{suffix}.txt"


async def _queue_knowledge_from_result(
    *,
    options: dict[str, Any],
    category: FileCategory,
    action: ProcessingAction,
    filename: str,
    processing_result: dict[str, Any],
    org_id: str | None = None,
) -> dict[str, Any] | None:
    text: str | None = None
    suffix = ""

    if action == ProcessingAction.TRANSCRIBE:
        text = processing_result.get("transcription")
        suffix = "transcript"
    elif action == ProcessingAction.EXTRACT:
        text = processing_result.get("text")
        suffix = "extracted"
    elif action == ProcessingAction.OCR:
        text = processing_result.get("text")
        suffix = "ocr"

    if not text or not isinstance(text, str) or not text.strip():
        return None

    if _resolve_bool(options.get("skip_placeholder_text"), True):
        if text.strip().startswith("[") and text.strip().endswith("]"):
            return None

    workspace_id = options.get("workspace_id")
    metadata = options.get("metadata")
    if not workspace_id and isinstance(metadata, dict):
        workspace_id = metadata.get("workspace_id")
    if not workspace_id:
        workspace_id = "default"

    tags = options.get("knowledge_tags") or options.get("tags")
    async_processing = _resolve_bool(options.get("async_knowledge"), True)
    knowledge_filename = _build_knowledge_filename(filename, suffix)
    ingest_metadata = _build_ingest_metadata(options, category, action, filename, processing_result)

    try:
        from aragora.knowledge.integration import process_uploaded_text

        return process_uploaded_text(
            text=text,
            filename=knowledge_filename,
            workspace_id=str(workspace_id),
            async_processing=async_processing,
            tags=tags,
            metadata=ingest_metadata,
            org_id=org_id,
        )
    except ImportError:
        logger.warning("Knowledge pipeline not available, skipping knowledge ingestion")
    except (KeyError, ValueError, TypeError) as e:
        logger.warning("Knowledge ingestion failed: %s", e)

    return None


async def _transcribe_audio_video(
    content: bytes,
    filename: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Transcribe audio/video using Whisper connector."""
    try:
        from aragora.connectors.whisper import WhisperConnector

        connector = WhisperConnector()

        # Write to temp file for processing
        with tempfile.NamedTemporaryFile(
            suffix=Path(filename).suffix,
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Transcribe
            transcription = await connector.transcribe(
                audio_content=content,
                filename=filename,
                prompt=options.get("prompt"),
            )

            return {
                "transcription": transcription.text,
                "duration": transcription.duration_seconds,
                "language": transcription.language,
                "segments": [
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                    }
                    for s in (transcription.segments or [])
                ],
            }
        finally:
            os.unlink(tmp_path)

    except ImportError:
        # Fallback to simple metadata
        return {"transcription": "[Whisper connector not available]", "segments": []}


async def _extract_document_text(
    content: bytes,
    filename: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Extract text from documents."""
    ext = Path(filename).suffix.lower()
    text = ""

    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF

            pdf = fitz.open(stream=content, filetype="pdf")
            text = "\n\n".join(page.get_text() for page in pdf)
            page_count = len(pdf)
            return {
                "text": text,
                "page_count": page_count,
                "word_count": len(text.split()),
            }
        except ImportError:
            return {"text": "[PDF extraction requires PyMuPDF]"}

    elif ext in (".txt", ".md", ".markdown"):
        text = content.decode("utf-8", errors="replace")
        return {"text": text, "word_count": len(text.split())}

    elif ext in (".docx",):
        try:
            from docx import Document

            doc = Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs)
            return {"text": text, "word_count": len(text.split())}
        except ImportError:
            return {"text": "[DOCX extraction requires python-docx]"}

    return {"text": text or "[Unsupported document format]"}


async def _ocr_image(
    content: bytes,
    filename: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Extract text from images using OCR."""
    try:
        from aragora.connectors.enterprise.documents.ocr import OCRConnector

        connector = OCRConnector()
        result = await connector.extract_text(content, filename)
        return {
            "text": result.text,
            "confidence": result.confidence,
            "regions": result.regions,
        }
    except ImportError:
        # Try tesseract directly
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(io.BytesIO(content))
            text = pytesseract.image_to_string(img, lang=options.get("language", "eng"))
            return {"text": text}
        except ImportError:
            return {"text": "[OCR requires tesseract or OCRConnector]"}


async def _parse_data_file(
    content: bytes,
    filename: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Parse data files (JSON, CSV, YAML, etc.)."""
    import csv
    import json

    ext = Path(filename).suffix.lower()
    text_content = content.decode("utf-8", errors="replace")

    if ext == ".json":
        try:
            data = json.loads(text_content)
            return {
                "parsed": True,
                "type": "json",
                "record_count": len(data) if isinstance(data, list) else 1,
                "preview": str(data)[:500],
            }
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed: %s", e)
            return {"parsed": False, "error": "Internal server error"}

    elif ext == ".csv":
        try:
            reader = csv.DictReader(io.StringIO(text_content))
            rows = list(reader)
            return {
                "parsed": True,
                "type": "csv",
                "columns": reader.fieldnames,
                "record_count": len(rows),
            }
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("CSV parse failed: %s", e)
            return {"parsed": False, "error": "Internal server error"}

    elif ext in (".yaml", ".yml"):
        try:
            import yaml

            data = yaml.safe_load(text_content)
            return {
                "parsed": True,
                "type": "yaml",
                "preview": str(data)[:500],
            }
        except ImportError:
            return {"parsed": False, "error": "YAML parsing requires PyYAML"}

    return {"parsed": False, "type": ext, "text": text_content[:1000]}


async def _index_code_file(
    content: bytes,
    filename: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Index a code file for search/analysis."""
    text_content = content.decode("utf-8", errors="replace")
    lines = text_content.split("\n")

    # Simple code analysis
    result = {
        "indexed": True,
        "line_count": len(lines),
        "char_count": len(text_content),
        "language": _detect_language(filename),
    }

    # Try to extract symbols (functions, classes)
    symbols = _extract_symbols(text_content, filename)
    if symbols:
        result["symbols"] = symbols

    return result


def _detect_language(filename: str) -> str:
    """Detect programming language from filename."""
    ext = Path(filename).suffix.lower()
    language_map = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
    }
    return language_map.get(ext, "unknown")


def _extract_symbols(content: str, filename: str) -> list[dict[str, Any]]:
    """Extract function/class symbols from code."""
    import re

    symbols = []
    language = _detect_language(filename)

    if language == "python":
        # Match class and function definitions
        for match in re.finditer(r"^(class|def)\s+(\w+)", content, re.MULTILINE):
            symbols.append(
                {
                    "type": "class" if match.group(1) == "class" else "function",
                    "name": match.group(2),
                }
            )

    elif language in ("javascript", "typescript"):
        # Match function/class declarations
        for match in re.finditer(
            r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+(\w+)",
            content,
            re.MULTILINE,
        ):
            symbols.append({"type": "function", "name": match.group(1)})

    return symbols[:50]  # Limit to first 50 symbols


async def _expand_archive(
    content: bytes,
    filename: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """List contents of an archive (don't extract for security)."""
    import zipfile
    import tarfile

    ext = Path(filename).suffix.lower()
    files = []

    if ext == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for info in zf.infolist():
                    files.append(
                        {
                            "name": info.filename,
                            "size": info.file_size,
                            "compressed": info.compress_size,
                        }
                    )
        except (zipfile.BadZipFile, OSError, ValueError) as e:
            logger.warning("Archive expansion failed: %s", e)
            return error_dict("Archive expansion failed", code="INTERNAL_ERROR", status=500)

    elif ext in (".tar", ".gz", ".tgz"):
        try:
            mode = "r:gz" if ext in (".gz", ".tgz") else "r"
            # tarfile.open accepts fileobj parameter for stream reading
            bio = io.BytesIO(content)
            with tarfile.open(fileobj=bio, mode=mode) as tf:  # type: ignore[call-overload]
                for member in tf.getmembers():
                    files.append(
                        {
                            "name": member.name,
                            "size": member.size,
                        }
                    )
        except (tarfile.TarError, OSError, ValueError) as e:
            logger.warning("Archive expansion failed: %s", e)
            return error_dict("Archive expansion failed", code="INTERNAL_ERROR", status=500)

    return {
        "expanded": True,
        "file_count": len(files),
        "files": files[:100],  # Limit listing
    }


async def smart_upload(
    file_content: bytes,
    filename: str,
    mime_type: str | None = None,
    override_action: ProcessingAction | None = None,
    options: dict[str, Any] | None = None,
    *,
    org_id: str | None = None,
) -> UploadResult:
    """
    Smart upload with auto-detection and processing.

    Args:
        file_content: Raw file bytes
        filename: Original filename
        mime_type: Optional MIME type hint
        override_action: Override the auto-detected action
        options: Processing options
        org_id: Verified organization of the uploader. Without it, knowledge
            ingestion fails closed.

    Returns:
        UploadResult with processing status
    """
    # Generate unique ID
    content_hash = hashlib.sha256(file_content).hexdigest()[:16]
    upload_id = f"{uuid.uuid4().hex[:8]}_{content_hash}"

    # Comprehensive file validation (size, MIME type, extension, path traversal)
    file_validation = validate_file_upload(
        filename=filename,
        size=len(file_content),
        content_type=mime_type,
    )
    if not file_validation.valid:
        ext = Path(filename).suffix.lower()
        error_message = file_validation.error_message or "File validation failed"
        if ext in DANGEROUS_EXTENSIONS:
            error_message = f"Dangerous file extension blocked: {ext}"
        result = UploadResult(
            id=upload_id,
            filename=filename,
            size=len(file_content),
            category=FileCategory.UNKNOWN,
            action=ProcessingAction.SKIP,
            status="rejected",
            error=error_message,
        )
        _upload_results[upload_id] = result
        return result

    # Validate content type against magic bytes
    validation = validate_content_type(file_content, filename, mime_type)

    if not validation.valid:
        # Block dangerous or invalid files
        result = UploadResult(
            id=upload_id,
            filename=filename,
            size=len(file_content),
            category=FileCategory.UNKNOWN,
            action=ProcessingAction.SKIP,
            status="rejected",
            error=validation.mismatch_warning or "Content validation failed",
        )
        _upload_results[upload_id] = result
        return result

    # Detect category and action
    category = detect_file_category(filename, mime_type)
    action = override_action or get_processing_action(category)

    # Create result entry
    result = UploadResult(
        id=upload_id,
        filename=filename,
        size=len(file_content),
        category=category,
        action=action,
        status="processing",
    )
    _upload_results[upload_id] = result

    try:
        options = dict(options or {})
        if mime_type and "mime_type" not in options:
            options["mime_type"] = mime_type

        # Process the file
        processing_result = await process_file(
            file_content,
            filename,
            category,
            action,
            options,
            org_id=org_id,
        )

        result.status = "completed"
        result.completed_at = time.time()
        result.result = processing_result

        # Add validation warning if present (file passed but had mismatch)
        if validation.mismatch_warning:
            if result.result is None:
                result.result = {}
            result.result["content_type_warning"] = validation.mismatch_warning

    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
        logger.error("Smart upload failed for %s: %s", filename, e)
        result.status = "failed"
        result.error = "Internal server error"

    return result


def get_upload_status(upload_id: str) -> UploadResult | None:
    """Get the status of an upload by ID."""
    return _upload_results.get(upload_id)


# HTTP Handler
if HANDLER_BASE_AVAILABLE:

    class SmartUploadHandler(BaseHandler):
        """HTTP handler for smart file uploads."""

        ROUTES = [
            "/api/v1/upload/smart",
            "/api/v1/upload/batch",
            "/api/v1/upload/status",
        ]

        def can_handle(self, path: str, method: str = "GET") -> bool:
            """Check if this handler can process the given path."""
            return path.startswith("/api/v1/upload/")

        async def _attach_auth_metadata(
            self,
            handler: Any,
            options: dict[str, Any] | None,
        ) -> dict[str, Any]:
            """Attach auth-derived metadata for knowledge ingestion."""
            options = dict(options or {})
            try:
                from aragora.server.handlers.utils.auth import get_auth_context

                auth_context = await get_auth_context(handler, require_auth=True)
            except (ImportError, AttributeError):
                logger.debug(
                    "Auth context unavailable for upload metadata enrichment", exc_info=True
                )
                return options

            metadata = options.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            metadata.setdefault("user_id", getattr(auth_context, "user_id", None))
            metadata["org_id"] = getattr(auth_context, "org_id", None)
            metadata.setdefault("workspace_id", getattr(auth_context, "workspace_id", None))
            metadata.setdefault(
                "tenant_id",
                getattr(auth_context, "workspace_id", None)
                or getattr(auth_context, "org_id", None),
            )

            options["metadata"] = metadata

            if metadata.get("workspace_id") and "workspace_id" not in options:
                options["workspace_id"] = metadata.get("workspace_id")

            return options

        async def _verified_org_id(self, handler: Any) -> str | None:
            """Organization of the verified caller, never taken from the request body."""
            try:
                from aragora.server.handlers.utils.auth import get_auth_context

                auth_context = await get_auth_context(handler, require_auth=True)
            except (ImportError, AttributeError):
                return None
            return getattr(auth_context, "org_id", None)

        def handle(
            self,
            path: str,
            query_params: dict[str, Any],
            handler: Any,
        ) -> HandlerResult | None:
            """Route upload requests."""
            if path.startswith("/api/v1/upload/status/"):
                upload_id = path.split("/")[-1]
                return self._get_status(upload_id)

            # POST endpoints handled by handle_post
            if handler.command != "POST":
                return error_response("Method not allowed", 405)

            return None

        @handle_errors("smart upload creation")
        @require_permission("upload:create")
        @rate_limit(requests_per_minute=20)
        async def handle_post(
            self,
            path: str,
            body: dict[str, Any],
            handler: Any,
        ) -> HandlerResult | None:
            """Handle POST uploads."""

            if path == "/api/v1/upload/smart":
                return await self._handle_smart_upload(body, handler)

            elif path == "/api/v1/upload/batch":
                return await self._handle_batch_upload(body, handler)

            return error_response("Not found", 404)

        @require_permission("upload:create")
        async def _handle_smart_upload(
            self,
            body: dict[str, Any],
            handler: Any,
        ) -> HandlerResult:
            """Handle single smart upload."""
            import base64

            # Get file from multipart form or base64 body
            file_content = body.get("content")
            filename = body.get("filename", "unknown")
            mime_type = body.get("mime_type")
            action = body.get("action")
            options = await self._attach_auth_metadata(handler, body.get("options", {}))

            if not file_content:
                return error_response("No file content provided", 400)

            # Decode base64 if needed
            if isinstance(file_content, str):
                file_content = base64.b64decode(file_content)

            override_action = ProcessingAction(action) if action else None
            result = await smart_upload(
                file_content,
                filename,
                mime_type,
                override_action,
                options,
                org_id=await self._verified_org_id(handler),
            )

            return json_response(
                {
                    "id": result.id,
                    "filename": result.filename,
                    "size": result.size,
                    "category": result.category.value,
                    "action": result.action.value,
                    "status": result.status,
                    "result": result.result,
                    "error": result.error,
                }
            )

        @require_permission("upload:create")
        async def _handle_batch_upload(
            self,
            body: dict[str, Any],
            handler: Any,
        ) -> HandlerResult:
            """Handle batch upload."""
            import base64

            files = body.get("files", [])
            if not files:
                return error_response("No files provided", 400)

            org_id = await self._verified_org_id(handler)
            results = []
            for file_info in files:
                content = file_info.get("content", "")
                if isinstance(content, str):
                    content = base64.b64decode(content)

                options = await self._attach_auth_metadata(handler, file_info.get("options"))
                result = await smart_upload(
                    content,
                    file_info.get("filename", "unknown"),
                    file_info.get("mime_type"),
                    ProcessingAction(file_info["action"]) if file_info.get("action") else None,
                    options,
                    org_id=org_id,
                )
                results.append(
                    {
                        "id": result.id,
                        "filename": result.filename,
                        "status": result.status,
                        "category": result.category.value,
                        "error": result.error,
                    }
                )

            return json_response({"files": results, "count": len(results)})

        def _get_status(self, upload_id: str) -> HandlerResult:
            """Get upload status."""
            result = get_upload_status(upload_id)
            if not result:
                return error_response("Upload not found", 404)

            return json_response(
                {
                    "id": result.id,
                    "filename": result.filename,
                    "size": result.size,
                    "category": result.category.value,
                    "action": result.action.value,
                    "status": result.status,
                    "created_at": result.created_at,
                    "completed_at": result.completed_at,
                    "result": result.result,
                    "error": result.error,
                }
            )
