"""
Email handlers subpackage.

This package contains email prioritization and management handlers split by domain:
- handler: Main EmailHandler class for routing
- storage: Store initialization, lazy connectors, RBAC helpers
- prioritization: Email scoring and ranking handlers
- categorization: Email categorization and labeling handlers
- oauth: Gmail OAuth handlers
- context: Cross-channel context handlers
- inbox: Inbox fetch and rank handlers
- config: Configuration handlers
- vip: VIP management handlers

Additional modules (import directly, without expanding eager package exports):
email_debate, email_services and email_triage.
"""

from .handler import EmailHandler
from .storage import (
    get_email_store,
    get_gmail_connector,
    get_prioritizer,
    get_context_service,
    get_user_config,
    set_user_config,
    _check_email_permission,
    _user_configs,
    _user_configs_lock,
    _email_store,
    _gmail_connector,
    _prioritizer,
    _context_service,
)
from .prioritization import (
    handle_prioritize_email,
    handle_rank_inbox,
    handle_email_feedback,
)
from .categorization import (
    get_categorizer,
    handle_categorize_email,
    handle_categorize_batch,
    handle_feedback_batch,
    handle_apply_category_label,
    _categorizer,
)
from .oauth import (
    handle_gmail_oauth_url,
    handle_gmail_oauth_callback,
    handle_gmail_status,
)
from .context import (
    handle_get_context,
    handle_get_email_context_boost,
)
from .inbox import handle_fetch_and_rank_inbox
from .config import handle_get_config, handle_update_config
from .vip import handle_add_vip, handle_remove_vip

__all__ = [
    # Core handler
    "EmailHandler",
    # Storage utilities
    "get_email_store",
    "get_gmail_connector",
    "get_prioritizer",
    "get_context_service",
    "get_categorizer",
    "get_user_config",
    "set_user_config",
    "_check_email_permission",
    "_user_configs",
    "_user_configs_lock",
    "_email_store",
    "_gmail_connector",
    "_prioritizer",
    "_context_service",
    "_categorizer",
    # Prioritization handlers
    "handle_prioritize_email",
    "handle_rank_inbox",
    "handle_email_feedback",
    # Categorization handlers
    "handle_categorize_email",
    "handle_categorize_batch",
    "handle_feedback_batch",
    "handle_apply_category_label",
    # OAuth handlers
    "handle_gmail_oauth_url",
    "handle_gmail_oauth_callback",
    "handle_gmail_status",
    # Context handlers
    "handle_get_context",
    "handle_get_email_context_boost",
    # Inbox handlers
    "handle_fetch_and_rank_inbox",
    # Config handlers
    "handle_get_config",
    "handle_update_config",
    # VIP handlers
    "handle_add_vip",
    "handle_remove_vip",
]
