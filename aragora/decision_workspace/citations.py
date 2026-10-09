"""Mechanical citation checks for a synthesized decision result.

A citation is checked for two things only: whether its passage label is one
of this decision's passages (``passage_exists``) and, when it gives a quote,
whether the quote appears in that passage's text once runs of whitespace are
collapsed (``quote_found``). Neither check says anything about whether the
passage supports the claim, and the result never uses that wording.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

_LABEL = re.compile(r"^\[?\s*S(\d+)\s*:\s*P(\d+)\s*\]?$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


class CitablePassage(Protocol):
    @property
    def passage_id(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def text(self) -> str: ...


def normalize_label(raw: object) -> str:
    """``S1:P3`` for ``[s1 : p3]``-style variants; anything else is returned stripped."""
    text = str(raw or "").strip()
    match = _LABEL.match(text)
    if match is None:
        return text
    return f"S{int(match.group(1))}:P{int(match.group(2))}"


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def check_citation(
    citation: Mapping[str, Any], passages: Mapping[str, CitablePassage]
) -> dict[str, Any]:
    """The citation with its label normalized and the two check results added."""
    label = normalize_label(citation.get("passage_label"))
    quote = citation.get("quote")
    quote = quote if isinstance(quote, str) and quote.strip() else None
    passage = passages.get(label)
    quote_found = False
    if passage is not None and quote is not None:
        needle = normalize_whitespace(quote)
        quote_found = bool(needle) and needle in normalize_whitespace(passage.text)
    return {
        "claim": citation.get("claim", ""),
        "passage_label": label,
        "quote": quote,
        "passage_id": passage.passage_id if passage is not None else None,
        "passage_exists": passage is not None,
        "quote_provided": quote is not None,
        "quote_found": quote_found,
    }


def check_result(result: Mapping[str, Any], passages: Iterable[CitablePassage]) -> dict[str, Any]:
    """A copy of a synthesized result with every citation checked against ``passages``."""
    by_label = {passage.label: passage for passage in passages}

    def checked(items: Any) -> list[dict[str, Any]]:
        return [check_citation(item, by_label) for item in items or []]

    return {
        "recommendation": result.get("recommendation", ""),
        "citations": checked(result.get("citations")),
        "alternatives": [
            {**item, "citations": checked(item.get("citations"))}
            for item in result.get("alternatives") or []
        ],
        "dissent": [
            {**item, "citations": checked(item.get("citations"))}
            for item in result.get("dissent") or []
        ],
        "missing_evidence": [dict(item) for item in result.get("missing_evidence") or []],
        "assumptions": [dict(item) for item in result.get("assumptions") or []],
    }


__all__ = [
    "check_citation",
    "check_result",
    "normalize_label",
    "normalize_whitespace",
]
