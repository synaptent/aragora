"""Classification of GitHub CLI failures as transient transport errors.

Review-queue gates and quorum evidence collection use this to tell a network or
rate-limit failure (retry, fail closed without mutating) from a real GitHub
error.
"""

from __future__ import annotations

__all__ = [
    "GITHUB_TRANSPORT_BLOCKED_STATUS",
    "GITHUB_TRANSPORT_ERROR_KIND",
    "GITHUB_TRANSPORT_ERROR_MARKERS",
    "gh_error_kind",
    "is_github_transport_error",
]

GITHUB_TRANSPORT_ERROR_KIND = "github_transport"
GITHUB_TRANSPORT_BLOCKED_STATUS = "transport_blocked"
GITHUB_TRANSPORT_ERROR_MARKERS = (
    "api rate limit already exceeded",
    "check your internet connection",
    "client.timeout exceeded",
    "command timed out",
    "connection refused",
    "connection reset",
    "connection timed out",
    "context deadline exceeded",
    "could not resolve host",
    "error connecting",
    "failed to start",
    "http 502",
    "http 503",
    "http 504",
    "i/o timeout",
    "net/http",
    "no such host",
    "operation timed out",
    "rate limit exceeded",
    "temporary failure in name resolution",
    "timeout awaiting response headers",
    "timed out after",
    "tls handshake timeout",
)


def gh_error_kind(error: object) -> str:
    """Return a stable machine-readable kind for GitHub helper failures."""
    text = str(error or "").lower()
    if any(marker in text for marker in GITHUB_TRANSPORT_ERROR_MARKERS):
        return GITHUB_TRANSPORT_ERROR_KIND
    return "github_error"


def is_github_transport_error(error: object) -> bool:
    return gh_error_kind(error) == GITHUB_TRANSPORT_ERROR_KIND
