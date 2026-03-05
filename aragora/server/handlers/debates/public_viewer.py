"""
Public Debate Viewer Handler.

Serves debate results publicly (no auth required) for shared links,
plus OG metadata for social previews when sharing on Twitter/Slack/LinkedIn.

Routes:
    GET /api/v1/debates/public/{debate_id}      - Public debate JSON
    GET /api/v1/debates/public/{debate_id}/og    - OG meta tags HTML
"""

from __future__ import annotations

import html as html_mod
import logging
import re
import time
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting: 30 req/min per IP for public viewer
# ---------------------------------------------------------------------------

_PUBLIC_VIEWER_RATE_LIMIT = 30
_PUBLIC_VIEWER_RATE_WINDOW = 60.0  # seconds
_public_viewer_timestamps: dict[str, list[float]] = {}


def _check_public_viewer_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check rate limit for public viewer endpoints.

    Returns:
        (allowed, retry_after_seconds)
    """
    now = time.monotonic()
    cutoff = now - _PUBLIC_VIEWER_RATE_WINDOW

    timestamps = _public_viewer_timestamps.get(client_ip, [])
    timestamps = [t for t in timestamps if t > cutoff]

    if len(timestamps) >= _PUBLIC_VIEWER_RATE_LIMIT:
        oldest_in_window = timestamps[0]
        retry_after = int(oldest_in_window + _PUBLIC_VIEWER_RATE_WINDOW - now) + 1
        _public_viewer_timestamps[client_ip] = timestamps
        return False, max(retry_after, 1)

    timestamps.append(now)
    _public_viewer_timestamps[client_ip] = timestamps
    return True, 0


def _reset_public_viewer_rate_limits() -> None:
    """Reset rate limit state. Used by tests."""
    _public_viewer_timestamps.clear()


# ---------------------------------------------------------------------------
# Debate retrieval helpers
# ---------------------------------------------------------------------------

# Debate ID: hex string, 16-32 chars (matches playground IDs)
_DEBATE_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")

# Also support playground-prefixed IDs like playground_abcd1234
_PLAYGROUND_ID_RE = re.compile(r"^playground_[a-f0-9]{8,16}$")


def _is_valid_debate_id(debate_id: str) -> bool:
    """Validate debate ID format to prevent path traversal."""
    return bool(_DEBATE_ID_RE.match(debate_id) or _PLAYGROUND_ID_RE.match(debate_id))


def _get_debate_result(debate_id: str) -> dict[str, Any] | None:
    """Retrieve a debate from the debate store.

    Returns the full result dict, or None if not found/expired.
    """
    try:
        from aragora.storage.debate_store import get_debate_store

        store = get_debate_store()
        return store.get(debate_id)
    except (ImportError, RuntimeError, OSError) as exc:
        logger.debug("Debate store unavailable: %s", exc)
        return None


def _is_shareable(result: dict[str, Any]) -> bool:
    """Check whether a debate result is allowed to be viewed publicly.

    A debate is shareable if:
    - It has a share_url field (set by _persist_and_respond in playground.py)
    - OR it has visibility == "public" (set by _persist_playground_debate)
    - OR its source is "playground" or "landing" (playground debates are public by default)
    """
    if result.get("share_url"):
        return True
    if result.get("visibility") == "public":
        return True
    source = result.get("source", "")
    if source in ("playground", "landing", "oracle"):
        return True
    return False


# ---------------------------------------------------------------------------
# OG metadata rendering
# ---------------------------------------------------------------------------

_DEFAULT_OG_IMAGE = "https://aragora.ai/og-card.png"


def _render_og_html(debate: dict[str, Any], debate_id: str) -> str:
    """Render an HTML page with Open Graph meta tags for social previews."""
    esc = html_mod.escape

    topic = debate.get("topic", "Untitled Debate")
    # Truncate to 60 chars for OG title
    if len(topic) > 60:
        og_title = topic[:57] + "..."
    else:
        og_title = topic
    og_title = f"Aragora Debate: {og_title}"

    verdict = debate.get("verdict") or debate.get("final_answer") or "Pending"
    confidence = debate.get("confidence", 0.0)
    participants = debate.get("participants", [])
    agent_count = len(participants)
    consensus = debate.get("consensus_reached", False)

    # Build description
    desc_parts = []
    if verdict and verdict != "Pending":
        verdict_preview = verdict[:120] if len(str(verdict)) > 120 else verdict
        desc_parts.append(f"Verdict: {verdict_preview}")
    desc_parts.append(f"Confidence: {confidence:.0%}")
    desc_parts.append(f"{agent_count} AI agents")
    if consensus:
        desc_parts.append("Consensus reached")
    og_description = " | ".join(desc_parts)

    og_image = _DEFAULT_OG_IMAGE
    canonical_url = f"https://aragora.ai/debate/{debate_id}/"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(og_title)}</title>

    <!-- Open Graph -->
    <meta property="og:type" content="article">
    <meta property="og:title" content="{esc(og_title)}">
    <meta property="og:description" content="{esc(og_description)}">
    <meta property="og:image" content="{esc(og_image)}">
    <meta property="og:url" content="{esc(canonical_url)}">
    <meta property="og:site_name" content="Aragora">

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{esc(og_title)}">
    <meta name="twitter:description" content="{esc(og_description)}">
    <meta name="twitter:image" content="{esc(og_image)}">

    <meta name="description" content="{esc(og_description)}">
    <link rel="canonical" href="{esc(canonical_url)}">

    <!-- Redirect to the live viewer after a brief delay for crawlers -->
    <meta http-equiv="refresh" content="0;url={esc(canonical_url)}">
</head>
<body>
    <h1>{esc(og_title)}</h1>
    <p>{esc(og_description)}</p>
    <p><a href="{esc(canonical_url)}">View this debate on Aragora</a></p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class PublicDebateViewerHandler(BaseHandler):
    """Handler for public debate viewing and OG metadata.

    No authentication required. Rate limited to 30 req/min per IP.
    """

    ROUTES = [
        "/api/v1/debates/public/*",
        "/api/v1/debates/public/*/og",
    ]

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Match /api/v1/debates/public/{id} and /api/v1/debates/public/{id}/og."""
        if not path.startswith("/api/v1/debates/public/"):
            return False
        parts = path.rstrip("/").split("/")
        # /api/v1/debates/public/{id} -> 6 parts
        # /api/v1/debates/public/{id}/og -> 7 parts
        if len(parts) == 6:
            return True
        if len(parts) == 7 and parts[6] == "og":
            return True
        return False

    def _extract_client_ip(self, handler: Any) -> str:
        """Extract client IP from the handler."""
        if handler and hasattr(handler, "client_address"):
            addr = handler.client_address
            if isinstance(addr, (list, tuple)) and len(addr) >= 1:
                return str(addr[0])
        return "unknown"

    def _extract_debate_id(self, path: str) -> str | None:
        """Extract debate ID from path.

        /api/v1/debates/public/{id} -> parts[5]
        /api/v1/debates/public/{id}/og -> parts[5]
        """
        parts = path.rstrip("/").split("/")
        if len(parts) >= 6:
            return parts[5]
        return None

    # ------------------------------------------------------------------
    # GET /api/v1/debates/public/{id}
    # GET /api/v1/debates/public/{id}/og
    # ------------------------------------------------------------------

    @handle_errors("public debate viewer")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        # Rate limit
        client_ip = self._extract_client_ip(handler)
        allowed, retry_after = _check_public_viewer_rate_limit(client_ip)
        if not allowed:
            return json_response(
                {
                    "error": "Rate limit exceeded. Please try again later.",
                    "retry_after": retry_after,
                },
                status=429,
            )

        debate_id = self._extract_debate_id(path)
        if not debate_id:
            return error_response("Missing debate ID", 400)

        if not _is_valid_debate_id(debate_id):
            return error_response("Invalid debate ID format", 400)

        parts = path.rstrip("/").split("/")

        # OG endpoint: /api/v1/debates/public/{id}/og
        if len(parts) == 7 and parts[6] == "og":
            return self._handle_og(debate_id)

        # JSON endpoint: /api/v1/debates/public/{id}
        return self._handle_public_debate(debate_id)

    def _handle_public_debate(self, debate_id: str) -> HandlerResult:
        """Return the debate result JSON for a publicly shared debate."""
        result = _get_debate_result(debate_id)
        if result is None:
            return error_response("Debate not found", 404)

        if not _is_shareable(result):
            return error_response("Debate not found", 404)

        return json_response(result)

    def _handle_og(self, debate_id: str) -> HandlerResult:
        """Return HTML with Open Graph meta tags for social previews."""
        result = _get_debate_result(debate_id)
        if result is None:
            return error_response("Debate not found", 404)

        if not _is_shareable(result):
            return error_response("Debate not found", 404)

        html_content = _render_og_html(result, debate_id)

        return HandlerResult(
            body=html_content.encode("utf-8"),
            status_code=200,
            content_type="text/html; charset=utf-8",
            headers={"Cache-Control": "public, max-age=300"},
        )


__all__ = [
    "PublicDebateViewerHandler",
    "_reset_public_viewer_rate_limits",
]
