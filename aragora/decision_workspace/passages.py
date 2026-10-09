"""Deterministic passage splitting for workspace sources.

A source's text is split on blank lines and Markdown ATX headings; every
passage carries the nearest heading above it. Paragraphs longer than
``MAX_PASSAGE_CHARS`` are split at sentence boundaries (then at whitespace,
then hard) so no passage exceeds the limit. Passages are whitespace-trimmed
and empty ones dropped. ``start_char``/``end_char`` index the source text, so
``text == source[start_char:end_char]`` always holds.

The output depends only on the input text: the same text always yields the
same passages, which is what keeps passage labels and hashes stable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_PASSAGE_CHARS = 1200

# ATX heading: up to three spaces, 1-6 '#', then whitespace or end of line.
_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+$")
# End of a sentence: terminal punctuation, optional closing quotes/brackets,
# followed by whitespace.
_SENTENCE_END = re.compile(r"[.!?\u2026]+[\"'\u201d\u2019)\]]*(?=\s)")


@dataclass(frozen=True, slots=True)
class PassageSpan:
    """One passage of a source text."""

    seq: int
    heading: str | None
    start_char: int
    end_char: int
    text: str

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decode_source_bytes(content: bytes) -> str:
    """Decode an uploaded ``.md``/``.txt`` file: UTF-8 (BOM dropped), else latin-1."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def split_passages(text: str, *, max_chars: int = MAX_PASSAGE_CHARS) -> list[PassageSpan]:
    """Split ``text`` into passages (see module docstring)."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    spans: list[tuple[str | None, int, int]] = []
    heading: str | None = None
    block_start: int | None = None
    block_end = 0
    offset = 0

    def flush() -> None:
        nonlocal block_start
        if block_start is not None:
            for start, end in _split_block(text, block_start, block_end, max_chars):
                spans.append((heading, start, end))
        block_start = None

    for line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        content = line.rstrip("\r\n")
        if not content.strip():
            flush()
            continue
        match = _HEADING.match(content)
        if match:
            flush()
            heading = _CLOSING_HASHES.sub("", (match.group(1) or "")).strip() or None
            continue
        if block_start is None:
            block_start = line_start
        block_end = line_start + len(content)
    flush()

    return [
        PassageSpan(seq=n, heading=h, start_char=s, end_char=e, text=text[s:e])
        for n, (h, s, e) in enumerate(spans, start=1)
    ]


def _split_block(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    start, end = _trim(text, start, end)
    if end <= start:
        return []
    if end - start <= max_chars:
        return [(start, end)]

    pieces: list[tuple[int, int]] = []
    chunk_start: int | None = None
    chunk_end = start
    for sentence_start, sentence_end in _sentences(text, start, end):
        if chunk_start is not None and sentence_end - chunk_start <= max_chars:
            chunk_end = sentence_end
            continue
        if chunk_start is not None:
            pieces.append((chunk_start, chunk_end))
        if sentence_end - sentence_start <= max_chars:
            chunk_start, chunk_end = sentence_start, sentence_end
        else:
            pieces.extend(_split_long(text, sentence_start, sentence_end, max_chars))
            chunk_start = None
    if chunk_start is not None:
        pieces.append((chunk_start, chunk_end))
    return pieces


def _sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Trimmed sentence spans covering ``text[start:end]``."""
    sentences: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE_END.finditer(text, start, end):
        span = _trim(text, cursor, match.end())
        if span[1] > span[0]:
            sentences.append(span)
        cursor = match.end()
    span = _trim(text, cursor, end)
    if span[1] > span[0]:
        sentences.append(span)
    return sentences


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split a span with no usable sentence boundary: at whitespace, else hard."""
    pieces: list[tuple[int, int]] = []
    while end - start > max_chars:
        limit = start + max_chars
        cut = limit
        for index in range(limit, start + max_chars // 2, -1):
            if text[index].isspace():
                cut = index
                break
        piece = _trim(text, start, cut)
        if piece[1] > piece[0]:
            pieces.append(piece)
        start, end = _trim(text, cut, end)
    if end > start:
        pieces.append((start, end))
    return pieces


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


__all__ = [
    "MAX_PASSAGE_CHARS",
    "PassageSpan",
    "decode_source_bytes",
    "sha256_text",
    "split_passages",
]
