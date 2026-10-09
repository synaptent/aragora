"""Build ``multipart/form-data`` request bodies the way browsers and curl do."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

Field = tuple[str, str]
FilePart = tuple[str, str, bytes]


def encode_multipart(
    fields: Iterable[Field] = (),
    files: Iterable[FilePart] = (),
    *,
    boundary: str | None = None,
    files_first: bool = False,
) -> tuple[bytes, str]:
    """Return ``(body, content_type)``; ``files`` are ``(field, filename, content)``."""
    boundary = boundary or f"----aragoraTestBoundary{uuid.uuid4().hex}"
    text_parts = [_text_part(boundary, name, value) for name, value in fields]
    file_parts = [_file_part(boundary, *part) for part in files]
    parts = file_parts + text_parts if files_first else text_parts + file_parts
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _text_part(boundary: str, name: str, value: str) -> bytes:
    return (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
    ).encode()


def _file_part(boundary: str, name: str, filename: str, content: bytes) -> bytes:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    return head + content + b"\r\n"
