"""Social handlers - collaboration, notifications, sharing, slack, telegram, relationships, and social media."""

from .channel_health import ChannelHealthHandler
from .collaboration import (
    CollaborationHandler,
    CollaborationHandlers,
    get_collaboration_handlers,
)
from .notifications import NotificationsHandler
from .relationship import (
    RelationshipHandler,
    RelationshipScores,
    compute_alliance_score,
    compute_relationship_scores,
    compute_rivalry_score,
    determine_relationship_type,
)
from aragora.storage.share_models import DebateVisibility, ShareSettings

from .sharing import SharingHandler
from .slack import SlackHandler
from .telegram import TelegramHandler, get_telegram_handler
from .teams import TeamsIntegrationHandler
from .telemetry import (
    PROMETHEUS_AVAILABLE as SOCIAL_PROMETHEUS_AVAILABLE,
    get_metrics_summary as get_social_metrics_summary,
)
from .whatsapp import WhatsAppHandler, get_whatsapp_handler
from .relationship import _safe_error_message
from .social_media import (
    ALLOWED_OAUTH_HOSTS,
    MAX_OAUTH_STATES,
    SocialMediaHandler,
    _OAUTH_STATE_TTL,
    _oauth_states,
    _oauth_states_lock,
    _store_oauth_state,
    _validate_oauth_state,
)

__all__ = [
    "ALLOWED_OAUTH_HOSTS",
    "ChannelHealthHandler",
    "CollaborationHandler",
    "CollaborationHandlers",
    "MAX_OAUTH_STATES",
    "NotificationsHandler",
    "DebateVisibility",
    "RelationshipHandler",
    "RelationshipScores",
    "ShareSettings",
    "SharingHandler",
    "SlackHandler",
    "SocialMediaHandler",
    "SOCIAL_PROMETHEUS_AVAILABLE",
    "TelegramHandler",
    "TeamsIntegrationHandler",
    "WhatsAppHandler",
    "_OAUTH_STATE_TTL",
    "_oauth_states",
    "_oauth_states_lock",
    "_safe_error_message",
    "_store_oauth_state",
    "_validate_oauth_state",
    "compute_alliance_score",
    "compute_relationship_scores",
    "compute_rivalry_score",
    "determine_relationship_type",
    "get_collaboration_handlers",
    "get_social_metrics_summary",
    "get_telegram_handler",
    "get_whatsapp_handler",
]
