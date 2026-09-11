"""Provider-behaviour compatibility helpers for current Anthropic models.

Two behaviours changed in the Claude Opus 4.7+ generation (which includes Opus
5, Sonnet 5, Fable 5 and Mythos 5) and broke call sites that were written
against Opus 4.6-era semantics:

1. **Sampling parameters were removed.** ``temperature`` / ``top_p`` / ``top_k``
   return ``400 invalid_request_error`` when set to a non-default value. Guide
   the model with prompting instead.
2. **Thinking is on by default.** A response's *first* content block is a
   thinking block, not a text block, so ``content[0].text`` raises
   ``AttributeError`` (SDK objects) or ``KeyError`` (raw JSON). Thinking blocks
   are emitted even when ``display`` is ``"omitted"`` — they just carry empty
   text.

``rejects_sampling_params`` (and the newer catalog-flag helpers below it) are
catalog-backed as of Task 7 (frontier-model-refresh, 2026-09-04): a model
present in ``aragora.models.CATALOG`` answers from its ``ModelSpec`` flags
(``supports_sampling_params``, ``thinking_default_on``,
``forced_tool_choice_allowed``, ``max_tokens_param``,
``reasoning_effort_default``), set once per catalog row instead of
maintained by hand at every call site. An id the catalog does not (yet) know
about — a legacy spelling, an OpenRouter alias, a ``-fast`` variant — falls
back to the regex below (``rejects_sampling_params`` only) or a documented
conservative default, so behaviour for uncatalogued ids never regresses.
"""

from __future__ import annotations

import re
from typing import Any

from aragora.models.catalog import spec_or_none

__all__ = [
    "allows_forced_tool_choice",
    "first_text_block",
    "max_tokens_param",
    "reasoning_effort_default",
    "rejects_sampling_params",
    "strip_sampling_params",
    "thinks_by_default",
]


# Families that removed temperature/top_p/top_k and think by default.
# Matches bare ids, OpenRouter spellings ("anthropic/claude-opus-5") and
# suffixed deployment variants ("claude-opus-4-8-fast").
_MODERN_CLAUDE = re.compile(
    r"claude[-/]?(?:"
    r"opus[-.]?(?:4[-.]?[789]|5)"  # opus 4.7 / 4.8 / 4.9 / 5
    r"|sonnet[-.]?5"
    r"|fable[-.]?5"
    r"|mythos"
    r")",
    re.IGNORECASE,
)


def rejects_sampling_params(model_id: str | None) -> bool:
    """True when ``model_id`` returns 400 for non-default sampling params.

    Catalog-backed (Task 7, frontier-model-refresh): a known model answers
    from its ``ModelSpec.supports_sampling_params`` flag. Unknown ids (not in
    ``aragora.models.CATALOG`` — legacy spellings, OpenRouter aliases not yet
    catalogued, etc.) fall back to the regex below so behaviour for ids the
    catalog has never seen stays unchanged. Unknown/None ids that also miss
    the regex return ``False`` so non-Anthropic providers (which still accept
    ``temperature``) are never silently degraded.
    """
    if not model_id:
        return False
    spec = spec_or_none(model_id)
    if spec is not None:
        return not spec.supports_sampling_params
    return bool(_MODERN_CLAUDE.search(str(model_id)))


def thinks_by_default(model_id: str | None) -> bool:
    """True when ``model_id``'s catalog row thinks by default (Fable 5.1,
    Opus 5, ...): its first response content block is a thinking block, not
    text, and an explicit ``thinking_budget`` cannot be honoured the way it
    is for older models. Unknown/None ids return ``False``."""
    spec = spec_or_none(model_id)
    return bool(spec and spec.thinking_default_on)


def allows_forced_tool_choice(model_id: str | None) -> bool:
    """False when ``model_id``'s catalog row forbids a forced ``tool_choice``
    (type ``any``/``tool``) and it must be downgraded to ``auto``. Unknown/
    None ids return ``True`` (conservative: do not change behaviour for a
    model the catalog has no opinion on)."""
    spec = spec_or_none(model_id)
    return True if spec is None else spec.forced_tool_choice_allowed


def max_tokens_param(model_id: str | None) -> str:
    """The request field name for the output-token cap: ``"max_tokens"`` or
    ``"max_completion_tokens"``. Unknown/None ids default to ``"max_tokens"``
    (today's behaviour)."""
    spec = spec_or_none(model_id)
    return spec.max_tokens_param if spec else "max_tokens"


def reasoning_effort_default(model_id: str | None) -> str | None:
    """The catalog's default ``reasoning_effort`` for ``model_id``, or
    ``None`` when the model has no documented default (or is unknown)."""
    spec = spec_or_none(model_id)
    return spec.reasoning_effort_default if spec else None


def strip_sampling_params(payload: dict[str, Any], model_id: str | None) -> dict[str, Any]:
    """Remove sampling params from ``payload`` when ``model_id`` rejects them.

    Mutates and returns ``payload`` for convenience at call sites that build a
    request dict incrementally.
    """
    if rejects_sampling_params(model_id):
        for key in ("temperature", "top_p", "top_k"):
            payload.pop(key, None)
    return payload


def first_text_block(content: Any) -> str:
    """Return the first text block's text from an Anthropic response body.

    Handles both shapes the codebase uses:

    * SDK objects — ``response.content`` of ``TextBlock``/``ThinkingBlock``/...
    * Raw JSON — ``data["content"]``, a list of ``{"type": ..., "text": ...}``

    Returns ``""`` when there is no text block, rather than raising, so callers
    keep their existing "empty means unusable" handling. Never index
    ``content[0]`` directly: on a thinking-by-default model that block is a
    thinking block.
    """
    if not content:
        return ""
    for block in content:
        if isinstance(block, dict):
            block_type = block.get("type")
            text = block.get("text")
        else:
            block_type = getattr(block, "type", None)
            text = getattr(block, "text", None)

        if not isinstance(text, str):
            # Thinking blocks carry "thinking", tool blocks carry "input"/
            # "content"; neither exposes a str "text".
            continue
        if isinstance(block_type, str):
            # The block declares a type — honour it strictly.
            if block_type == "text":
                return text
            continue
        # No usable declared type (absent, None, or a test double's auto-attr):
        # a block exposing a str "text" is unambiguously the text block.
        return text
    return ""
