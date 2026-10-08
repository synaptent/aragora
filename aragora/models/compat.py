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

Both helpers are deliberately string-based rather than catalog-backed: they must
give a correct answer for every id the code may carry (including ids that are
not, or not yet, in ``aragora.models.CATALOG`` — e.g. ``claude-opus-4-7``,
``claude-sonnet-5``, OpenRouter spellings and ``-fast`` variants).
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["first_text_block", "rejects_sampling_params", "strip_sampling_params"]


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

    Applies to Claude Opus 4.7 and later, Sonnet 5, Fable 5 and Mythos.
    Unknown/None ids return ``False`` so non-Anthropic providers (which still
    accept ``temperature``) are never silently degraded.
    """
    if not model_id:
        return False
    return bool(_MODERN_CLAUDE.search(str(model_id)))


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
