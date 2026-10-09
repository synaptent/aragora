"""Read a new-decision request body into an :class:`IntakeForm`.

``parse_multipart_intake`` and ``parse_json_intake`` only check the shape of
the request (framing, encodings, field names and types); the values are
validated by :func:`aragora.decision_workspace.intake.prepare_decision`.
Every refusal is an :class:`IntakeError` naming the offending field.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from email.message import Message
from typing import Any

from aragora.decision_workspace.config import WorkspaceLimits

_SCALAR_FIELDS = ("question", "pasted_text", "rounds")
_AGENT_FIELDS = ("agents", "agents[]")
_FILE_FIELDS = ("files", "files[]")
_ECHO_LIMIT = 200
# Multipart framing and the small fields (question, agents, rounds) on top of
# the largest valid files and pasted text.
_PART_OVERHEAD_BYTES = 64 * 1024
_FORM_OVERHEAD_BYTES = 1024 * 1024


class IntakeError(Exception):
    """A refused intake request: HTTP status plus a field-specific error body."""

    def __init__(
        self,
        status: int,
        field: str | None,
        code: str,
        message: str,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.field = field
        self.code = code
        self.message = message
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"error": self.message, "code": self.code, "field": self.field, **self.extra}


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """One file part as received (filename already stripped of client paths)."""

    form_field: str
    filename: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _PastedMarker:
    """Position of the pasted text among the uploads."""


PASTED = _PastedMarker()


@dataclass
class IntakeForm:
    """Raw intake fields in request order, before validation."""

    question: str | None = None
    pasted_text: str | None = None
    agents: list[str] = field(default_factory=list)
    rounds: Any = None
    items: list[UploadedFile | _PastedMarker] = field(default_factory=list)


def max_request_bytes(limits: WorkspaceLimits) -> int:
    """Largest request body read for a decision; anything bigger is refused unread."""
    return (
        limits.max_documents * (limits.max_file_bytes + _PART_OVERHEAD_BYTES)
        + limits.max_pasted_chars * 4
        + _FORM_OVERHEAD_BYTES
    )


def clip(value: str) -> str:
    """Shorten a client-supplied value before echoing it in an error message."""
    return value if len(value) <= _ECHO_LIMIT else value[:_ECHO_LIMIT] + "..."


def parse_multipart_intake(body: bytes, content_type: str) -> IntakeForm:
    """Parse a ``multipart/form-data`` body.

    Fields: ``question``, ``pasted_text``, ``rounds`` (each at most once),
    ``agents[]``/``agents`` (repeated) and ``files[]``/``files`` (file
    parts). A file part with an empty filename and no content is an unused
    file input and is ignored. Unknown text fields are ignored; a file in any
    other field is refused.
    """
    form = IntakeForm()
    seen: set[str] = set()
    for headers, content in _multipart_parts(body, _boundary(content_type)):
        name, filename = _disposition(headers)
        if filename is not None:
            if name not in _FILE_FIELDS:
                raise IntakeError(
                    400,
                    name,
                    "unexpected_file",
                    f"Field '{clip(name)}' does not accept files; send files as 'files[]'.",
                )
            if filename == "" and not content:
                continue
            form.items.append(
                UploadedFile(form_field=name, filename=_base_name(filename), content=content)
            )
            continue
        if name in _FILE_FIELDS:
            raise IntakeError(400, "files", "invalid_file", "Send each file as a file upload.")
        if name in _AGENT_FIELDS:
            form.agents.append(_decode_field(content, "agents"))
            continue
        if name not in _SCALAR_FIELDS:
            continue
        if name in seen:
            raise IntakeError(400, name, "duplicate_field", f"Send the {name} field only once.")
        seen.add(name)
        value = _decode_field(content, name)
        if name == "question":
            form.question = value
        elif name == "rounds":
            form.rounds = value
        else:
            form.pasted_text = value
            form.items.append(PASTED)
    return form


def parse_json_intake(body: bytes) -> IntakeForm:
    """Parse a JSON object body: text-only decisions (no files)."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise IntakeError(400, None, "invalid_json", "Request body must be a JSON object.")
    if data.get("files") not in (None, []):
        raise IntakeError(
            400,
            "files",
            "invalid_file",
            "Files can only be uploaded with multipart/form-data.",
        )

    form = IntakeForm()
    form.question = _json_text(data.get("question"), "question")
    form.pasted_text = _json_text(data.get("pasted_text"), "pasted_text")
    if form.pasted_text is not None:
        form.items.append(PASTED)

    agents = data.get("agents")
    if agents is not None:
        if not isinstance(agents, list) or not all(isinstance(a, str) for a in agents):
            raise IntakeError(
                400, "agents", "invalid_field", "agents must be a list of agent specs."
            )
        form.agents = [_ensure_encodable(a, "agents") for a in agents]

    # Any JSON value is passed on: prepare_decision refuses non-integer rounds.
    form.rounds = data.get("rounds")
    return form


def _boundary(content_type: str) -> bytes:
    message = Message()
    message["content-type"] = content_type or ""
    boundary = (
        message.get_param("boundary")
        if message.get_content_type() == "multipart/form-data"
        else None
    )
    if not isinstance(boundary, str) or not boundary or len(boundary) > 200:
        raise IntakeError(
            400, None, "invalid_multipart", "Send the form as multipart/form-data with a boundary."
        )
    try:
        return boundary.encode("ascii")
    except UnicodeEncodeError as exc:
        raise IntakeError(400, None, "invalid_multipart", "Invalid multipart boundary.") from exc


def _multipart_parts(body: bytes, boundary: bytes) -> list[tuple[str, bytes]]:
    malformed = IntakeError(400, None, "invalid_multipart", "The multipart form could not be read.")
    dash = b"--" + boundary
    separator = b"\r\n" + dash
    if body.startswith(dash):
        position = len(dash)
    else:
        found = body.find(separator)
        if found < 0:
            raise malformed
        position = found + len(separator)

    parts: list[tuple[str, bytes]] = []
    while True:
        if body.startswith(b"--", position):
            return parts
        line_end = body.find(b"\r\n", position)
        if line_end < 0 or body[position:line_end].strip(b" \t"):
            raise malformed
        start = line_end + 2
        end = body.find(separator, start)
        if end < 0:
            raise malformed
        header_end = body.find(b"\r\n\r\n", start, end)
        if header_end < 0:
            raise malformed
        try:
            headers = body[start:header_end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise malformed from exc
        parts.append((headers, body[header_end + 4 : end]))
        position = end + len(separator)


def _disposition(headers: str) -> tuple[str, str | None]:
    value = None
    for line in headers.split("\r\n"):
        key, _, rest = line.partition(":")
        if key.strip().lower() == "content-disposition":
            value = rest.strip()
    message = Message()
    message["content-disposition"] = value or ""
    name = message.get_param("name", header="content-disposition")
    if message.get_content_disposition() != "form-data" or not isinstance(name, str) or not name:
        raise IntakeError(400, None, "invalid_multipart", "Every form part needs a form-data name.")
    filename = message.get_filename()
    if filename is None and message.get_param("filename", header="content-disposition") == "":
        filename = ""
    return name, filename


def _decode_field(content: bytes, name: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntakeError(
            400, name, "invalid_encoding", f"The {name} field must be UTF-8 text."
        ) from exc


def _json_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntakeError(400, name, "invalid_field", f"{name} must be a string.")
    return _ensure_encodable(value, name)


def _ensure_encodable(value: str, name: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise IntakeError(
            400, name, "invalid_encoding", f"The {name} field must be valid text."
        ) from exc
    return value


def _base_name(filename: str) -> str:
    return re.split(r"[\\/]", filename)[-1].strip()


__all__ = [
    "PASTED",
    "IntakeError",
    "IntakeForm",
    "UploadedFile",
    "clip",
    "max_request_bytes",
    "parse_json_intake",
    "parse_multipart_intake",
]
