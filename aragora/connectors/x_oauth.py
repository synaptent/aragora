"""OAuth2 user-context token management for the X (Twitter) API v2.

Bookmarks and likes are only readable with an OAuth2 *user-context* token
(scopes ``bookmark.read`` / ``like.read``), not the app-only bearer token the
:class:`~aragora.connectors.twitter.TwitterConnector` uses for search.

Tokens live in ``.aragora/x_intake/oauth.json`` (written by
``scripts/x_oauth_setup.py``). X rotates the refresh token on every refresh,
so the rotated pair is persisted immediately after each refresh — losing a
rotated refresh token strands the grant.

Environment variables ``X_OAUTH2_ACCESS_TOKEN`` / ``X_OAUTH2_REFRESH_TOKEN`` /
``X_OAUTH2_CLIENT_ID`` seed the store when the file does not exist yet.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
# CWD-relative by default; override with ARAGORA_X_OAUTH_TOKEN_PATH (must
# match any custom --token-path given to scripts/x_oauth_setup.py).
DEFAULT_TOKEN_PATH = Path(
    os.environ.get("ARAGORA_X_OAUTH_TOKEN_PATH", ".aragora/x_intake/oauth.json")
)

__all__ = ["XOAuthTokenStore", "XOAuthTokens"]


@dataclass
class XOAuthTokens:
    """An OAuth2 user-context token pair."""

    access_token: str
    refresh_token: str = ""
    client_id: str = ""
    expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        # 60s of slack so a token never expires mid-request
        return bool(self.expires_at) and time.time() > self.expires_at - 60


class XOAuthTokenStore:
    """Load, refresh, and persist X OAuth2 user-context tokens."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_TOKEN_PATH

    def load(self) -> XOAuthTokens | None:
        """Load tokens from file, falling back to environment seeds."""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return XOAuthTokens(
                    access_token=data.get("access_token", ""),
                    refresh_token=data.get("refresh_token", ""),
                    client_id=data.get("client_id", ""),
                    expires_at=float(data.get("expires_at", 0.0)),
                )
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning("Could not read X OAuth token file %s: %s", self.path, exc)

        access = os.environ.get("X_OAUTH2_ACCESS_TOKEN", "")
        if not access and not os.environ.get("X_OAUTH2_REFRESH_TOKEN"):
            return None
        return XOAuthTokens(
            access_token=access,
            refresh_token=os.environ.get("X_OAUTH2_REFRESH_TOKEN", ""),
            client_id=os.environ.get("X_OAUTH2_CLIENT_ID", ""),
        )

    def save(self, tokens: XOAuthTokens) -> None:
        """Persist tokens (0600 from creation) — runs after every rotation."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "client_id": tokens.client_id,
            "expires_at": tokens.expires_at,
        }
        # O_CREAT with 0600 so the file never exists world-readable, even
        # briefly; fchmod covers rewrites of a pre-existing file whose mode
        # was looser (the create-time 0600 only applies to new files).
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    @contextlib.asynccontextmanager
    async def _flock(self) -> AsyncIterator[None]:
        """Cross-process exclusive lock: X rotates the refresh token on every
        refresh, so a CLI run racing the launchd digest could persist a stale
        pair and strand the grant. All refresh decisions happen under this
        lock, re-reading the file first.

        Acquired non-blocking with async backoff — a blocking LOCK_EX would
        pin the event loop, deadlocking two coroutines in the same loop."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.2)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    async def refresh(self, tokens: XOAuthTokens) -> XOAuthTokens | None:
        """Refresh the access token; persists the rotated pair on success."""
        if not tokens.refresh_token or not tokens.client_id:
            logger.warning("X OAuth refresh needs refresh_token and client_id")
            return None
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available; cannot refresh X OAuth token")
            return None

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens.refresh_token,
                        "client_id": tokens.client_id,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("X OAuth token refresh failed: %s", exc)
            return None

        refreshed = XOAuthTokens(
            access_token=data.get("access_token", ""),
            # X rotates the refresh token; fall back to the old one if absent
            refresh_token=data.get("refresh_token", tokens.refresh_token),
            client_id=tokens.client_id,
            expires_at=time.time() + float(data.get("expires_in", 7200)),
        )
        if not refreshed.access_token:
            logger.warning("X OAuth refresh response had no access_token")
            return None
        self.save(refreshed)
        logger.info("X OAuth token refreshed (expires in %ss)", data.get("expires_in"))
        return refreshed

    async def refresh_rejected(self, stale: XOAuthTokens) -> XOAuthTokens | None:
        """Refresh after the API rejected ``stale`` (e.g. a 401), under lock.

        Re-reads the store first: if another process already rotated the pair
        while we held a stale copy, its tokens are returned without burning a
        second rotation (X rotates the refresh token on every refresh).
        """
        async with self._flock():
            current = self.load()
            if current and current.access_token and current.access_token != stale.access_token:
                return current
            return await self.refresh(current or stale)

    async def get_valid(self) -> XOAuthTokens | None:
        """Return a non-expired token pair, refreshing (under lock) if needed."""
        tokens = self.load()
        if tokens is None:
            return None
        if tokens.is_expired or not tokens.access_token:
            async with self._flock():
                # Another process may have refreshed while we waited for the
                # lock — reload and only refresh if still needed.
                tokens = self.load() or tokens
                if not (tokens.is_expired or not tokens.access_token):
                    return tokens
                return await self.refresh(tokens)
        return tokens
