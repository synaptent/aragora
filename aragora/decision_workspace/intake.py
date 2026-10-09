"""Validate an :class:`IntakeForm` into a :class:`PreparedDecision`, without side effects.

``prepare_decision`` checks the form (read by
:mod:`aragora.decision_workspace.forms`) against the offered agents and the
limits and returns every source and passage computed in memory. Nothing is
stored here, so a request that fails any check leaves no trace.

Every refusal is an :class:`IntakeError` naming the offending field. The
first failing check wins, in this order: agent configuration, question,
agents, rounds, pasted text, files.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from aragora.decision_workspace.config import AgentOptions, WorkspaceLimits
from aragora.decision_workspace.forms import IntakeError, IntakeForm, UploadedFile, clip
from aragora.decision_workspace.passages import (
    PassageSpan,
    decode_source_bytes,
    sha256_text,
    split_passages,
)

ACCEPTED_EXTENSIONS = (".md", ".txt")
MAX_FILENAME_CHARS = 255
MIN_ROUNDS = 1
MAX_ROUNDS = 2
DEFAULT_ROUNDS = 1

KIND_PASTED = "pasted"
KIND_UPLOAD = "upload"


@dataclass(frozen=True, slots=True)
class PreparedSource:
    """A validated source with its passages, not yet stored."""

    label: str
    kind: str
    filename: str | None
    text: str = field(repr=False)
    content_sha256: str
    char_count: int
    passages: tuple[PassageSpan, ...] = field(repr=False)
    content: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class PreparedDecision:
    """A fully validated decision request."""

    question: str
    agents: tuple[str, ...]
    rounds: int
    sources: tuple[PreparedSource, ...]


def prepare_decision(
    form: IntakeForm, *, options: AgentOptions, limits: WorkspaceLimits
) -> PreparedDecision:
    """Validate ``form`` and compute its sources and passages (no side effects)."""
    if not options.configured:
        raise IntakeError(
            400,
            "agents",
            "agents_not_configured",
            options.error or "No agents are configured for the decision workspace.",
        )
    question = _validate_question(form.question)
    agents = _validate_agents(form.agents, options)
    rounds = _validate_rounds(form.rounds)
    pasted = _validate_pasted(form.pasted_text, limits)
    uploads = [item for item in form.items if isinstance(item, UploadedFile)]
    if len(uploads) > limits.max_documents:
        raise IntakeError(
            400,
            "files",
            "too_many_documents",
            f"At most {limits.max_documents} files can be attached to a decision; "
            f"{len(uploads)} were sent.",
            limit=limits.max_documents,
        )

    sources: list[PreparedSource] = []
    for item in form.items:
        label = f"S{len(sources) + 1}"
        if isinstance(item, UploadedFile):
            sources.append(_prepare_upload(item, label, limits))
        elif pasted is not None:
            text, passages = pasted
            sources.append(
                PreparedSource(
                    label=label,
                    kind=KIND_PASTED,
                    filename=None,
                    text=text,
                    content_sha256=sha256_text(text),
                    char_count=len(text),
                    passages=passages,
                )
            )
    return PreparedDecision(question=question, agents=agents, rounds=rounds, sources=tuple(sources))


def _validate_question(question: str | None) -> str:
    stripped = (question or "").strip()
    if not stripped:
        raise IntakeError(400, "question", "question_required", "Enter a question to decide.")
    return stripped


def _validate_agents(agents: Sequence[str], options: AgentOptions) -> tuple[str, ...]:
    chosen: list[str] = []
    for raw in agents:
        agent = raw.strip()
        if not agent:
            continue
        if agent not in options.specs:
            raise IntakeError(
                400,
                "agents",
                "agent_not_offered",
                f"Agent '{clip(agent)}' is not one of the offered agents.",
                agent=clip(agent),
            )
        if agent in chosen:
            raise IntakeError(
                400,
                "agents",
                "duplicate_agent",
                f"Agent '{agent}' was selected more than once.",
                agent=agent,
            )
        chosen.append(agent)
    if not chosen:
        raise IntakeError(400, "agents", "agents_required", "Select at least one agent.")
    return tuple(chosen)


def _validate_rounds(rounds: Any) -> int:
    if rounds is None:
        return DEFAULT_ROUNDS
    if isinstance(rounds, int) and not isinstance(rounds, bool):
        value = rounds
    else:
        text = str(rounds).strip()
        # The length cap keeps int() away from its digit limit on hostile input.
        valid = text.isascii() and text.isdigit() and len(text) <= 3
        value = int(text) if valid else -1
    if not MIN_ROUNDS <= value <= MAX_ROUNDS:
        raise IntakeError(
            400,
            "rounds",
            "invalid_rounds",
            f"rounds must be a whole number from {MIN_ROUNDS} to {MAX_ROUNDS}.",
        )
    return value


def _validate_pasted(
    pasted: str | None, limits: WorkspaceLimits
) -> tuple[str, tuple[PassageSpan, ...]] | None:
    if pasted is None:
        return None
    # Browsers submit textarea line breaks as CRLF; count each as one character.
    text = pasted.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return None
    if len(text) > limits.max_pasted_chars:
        raise IntakeError(
            413,
            "pasted_text",
            "pasted_text_too_long",
            f"Pasted text is {len(text)} characters; the limit is "
            f"{limits.max_pasted_chars} characters.",
            limit=limits.max_pasted_chars,
        )
    passages = tuple(split_passages(text))
    if not passages:
        raise IntakeError(
            400,
            "pasted_text",
            "pasted_text_empty",
            "Pasted text has no passages to use as evidence.",
        )
    return text, passages


def _prepare_upload(item: UploadedFile, label: str, limits: WorkspaceLimits) -> PreparedSource:
    name = item.filename
    if not name:
        raise IntakeError(400, "files", "invalid_filename", "Every uploaded file needs a name.")
    if len(name) > MAX_FILENAME_CHARS:
        raise IntakeError(
            400,
            "files",
            "invalid_filename",
            f"File names can be at most {MAX_FILENAME_CHARS} characters.",
            filename=clip(name),
        )
    extension = os.path.splitext(name)[1].lower()
    if extension == ".pdf":
        raise IntakeError(
            400,
            "files",
            "pdf_not_supported",
            f"'{name}' was not accepted: PDF support is planned for a later stage. "
            "Upload .md or .txt files.",
            filename=name,
        )
    if extension not in ACCEPTED_EXTENSIONS:
        raise IntakeError(
            400,
            "files",
            "unsupported_file_type",
            f"'{name}' was not accepted: only .md and .txt are accepted.",
            filename=name,
        )
    size = len(item.content)
    if size > limits.max_file_bytes:
        raise IntakeError(
            413,
            "files",
            "file_too_large",
            f"'{name}' is {size} bytes; the limit is {limits.max_file_bytes} bytes per file.",
            filename=name,
            limit=limits.max_file_bytes,
        )
    text = decode_source_bytes(item.content)
    passages = tuple(split_passages(text))
    if not passages:
        raise IntakeError(
            400,
            "files",
            "empty_file",
            f"'{name}' is empty: it has no passages to use as evidence.",
            filename=name,
        )
    return PreparedSource(
        label=label,
        kind=KIND_UPLOAD,
        filename=name,
        text=text,
        content_sha256=hashlib.sha256(item.content).hexdigest(),
        char_count=len(text),
        passages=passages,
        content=item.content,
    )


__all__ = [
    "ACCEPTED_EXTENSIONS",
    "DEFAULT_ROUNDS",
    "KIND_PASTED",
    "KIND_UPLOAD",
    "MAX_ROUNDS",
    "MIN_ROUNDS",
    "PreparedDecision",
    "PreparedSource",
    "prepare_decision",
]
