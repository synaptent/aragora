"""
Gmail Enterprise Connector.

Provides full integration with Gmail inboxes:
- OAuth2 authentication flow
- Message and thread fetching
- Label/folder management
- Incremental sync via History API
- Search with Gmail query syntax

Requires Google Cloud OAuth2 credentials with Gmail scopes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aragora.connectors.enterprise.base import EnterpriseConnector

from ..models import GmailSyncState, GmailWebhookPayload

from .client import (
    GMAIL_SCOPES,
    GMAIL_SCOPES_FULL,
    GMAIL_SCOPES_READONLY,
    GmailClientMixin,
    _load_refresh_token_fallback,
)
from .labels import GmailLabelsMixin
from .messages import GmailMessagesMixin
from .state import GmailStateMixin
from .watch import GmailWatchMixin

logger = logging.getLogger(__name__)


class GmailConnector(  # type: ignore[misc]  # mypy does not support mixin Protocol bases in MRO
    GmailClientMixin,
    GmailMessagesMixin,
    GmailLabelsMixin,
    GmailWatchMixin,
    GmailStateMixin,
    EnterpriseConnector,
):
    """
    Enterprise connector for Gmail.

    Features:
    - OAuth2 authentication with refresh tokens
    - Full message content retrieval
    - Thread-based conversation view
    - Label/folder filtering
    - Incremental sync via History API
    - Gmail search query support

    Authentication:
    - OAuth2 with refresh token (required)

    Usage:
        connector = GmailConnector(
            labels=["INBOX", "IMPORTANT"],
            max_results=100,
        )

        # Get OAuth URL for user authorization
        url = connector.get_oauth_url(redirect_uri, state)

        # After user authorizes, exchange code for tokens
        await connector.authenticate(code=auth_code, redirect_uri=redirect_uri)

        # Sync messages
        result = await connector.sync()
    """

    def __init__(
        self,
        labels: list[str] | None = None,
        exclude_labels: list[str] | None = None,
        max_results: int = 100,
        include_spam_trash: bool = False,
        user_id: str = "me",
        **kwargs: Any,
    ):
        """
        Initialize Gmail connector.

        Args:
            labels: Labels to sync (None = all)
            exclude_labels: Labels to exclude
            max_results: Max messages per sync batch
            include_spam_trash: Include spam/trash folders
            user_id: Gmail user ID ("me" for authenticated user)
        """
        super().__init__(connector_id="gmail", **kwargs)
        # Set connector_id directly since MRO through Protocol does not
        # forward kwargs to EnterpriseConnector.__init__
        self.connector_id = "gmail"

        self.labels = labels
        self.exclude_labels = set(exclude_labels or [])
        self.max_results = max_results
        self.include_spam_trash = include_spam_trash
        self.user_id = user_id

        # OAuth tokens (protected by _token_lock for thread-safety)
        self._access_token: str | None = None
        self._refresh_token: str | None = _load_refresh_token_fallback()
        self._token_expiry = None
        self._token_lock: asyncio.Lock = asyncio.Lock()

        # Gmail-specific state
        self._gmail_state: GmailSyncState | None = None

        # Watch management for Pub/Sub notifications
        self._watch_task: asyncio.Task[Any] | None = None
        self._watch_running: bool = False


__all__ = [
    "GmailConnector",
    "GmailWebhookPayload",
    "GMAIL_SCOPES",
    "GMAIL_SCOPES_READONLY",
    "GMAIL_SCOPES_FULL",
]
