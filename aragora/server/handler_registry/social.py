"""
Social and chat handler imports and registry entries.

This module contains imports and registry entries for:
- Social media handlers (Slack, Teams, Discord, etc.)
- Chat and bot handlers (Telegram, WhatsApp, etc.)
- Email handlers
- Voice and audio handlers
- Collaboration handlers
"""

from __future__ import annotations

from .core import _safe_import

# =============================================================================
# Social Media Handler Imports
# =============================================================================

SocialMediaHandler = _safe_import("aragora.server.handlers", "SocialMediaHandler")

# Slack handlers
SlackHandler = _safe_import("aragora.server.handlers", "SlackHandler")
SlackOAuthHandler = _safe_import("aragora.server.handlers.social.slack_oauth", "SlackOAuthHandler")
SlackWorkspaceHandler = _safe_import(
    "aragora.server.handlers.sme.slack_workspace", "SlackWorkspaceHandler"
)

# Teams handlers
TeamsIntegrationHandler = _safe_import(
    "aragora.server.handlers.social.teams", "TeamsIntegrationHandler"
)
TeamsOAuthHandler = _safe_import("aragora.server.handlers.social.teams_oauth", "TeamsOAuthHandler")
TeamsHandler = _safe_import("aragora.server.handlers.bots.teams", "TeamsHandler")
TeamsWorkspaceHandler = _safe_import(
    "aragora.server.handlers.sme.teams_workspace", "TeamsWorkspaceHandler"
)

# Discord handlers
DiscordOAuthHandler = _safe_import(
    "aragora.server.handlers.social.discord_oauth", "DiscordOAuthHandler"
)
DiscordHandler = _safe_import("aragora.server.handlers.bots.discord", "DiscordHandler")

# Google Chat handler
GoogleChatHandler = _safe_import("aragora.server.handlers", "GoogleChatHandler")

# Zoom handler
ZoomHandler = _safe_import("aragora.server.handlers.bots.zoom", "ZoomHandler")

# =============================================================================
# Chat and Bot Handler Imports
# =============================================================================

ChatHandler = _safe_import("aragora.server.handlers.chat.router", "ChatHandler")
TelegramHandler = _safe_import("aragora.server.handlers.bots.telegram", "TelegramHandler")
WhatsAppHandler = _safe_import("aragora.server.handlers.bots.whatsapp", "WhatsAppHandler")

# =============================================================================
# Email Handler Imports
# =============================================================================

EmailHandler = _safe_import("aragora.server.handlers", "EmailHandler")
EmailServicesHandler = _safe_import("aragora.server.handlers", "EmailServicesHandler")
GmailIngestHandler = _safe_import("aragora.server.handlers.features", "GmailIngestHandler")
GmailLabelsHandler = _safe_import("aragora.server.handlers.features", "GmailLabelsHandler")
GmailQueryHandler = _safe_import("aragora.server.handlers.features", "GmailQueryHandler")
GmailThreadsHandler = _safe_import("aragora.server.handlers.features", "GmailThreadsHandler")
EmailWebhookHandler = _safe_import(
    "aragora.server.handlers.bots.email_webhook", "EmailWebhookHandler"
)
EmailWebhooksHandler = _safe_import(
    "aragora.server.handlers.features.email_webhooks", "EmailWebhooksHandler"
)

# Outlook handler
OutlookHandler = _safe_import("aragora.server.handlers.features.outlook", "OutlookHandler")

# =============================================================================
# Audio and Voice Handler Imports
# =============================================================================

AudioHandler = _safe_import("aragora.server.handlers", "AudioHandler")
BroadcastHandler = _safe_import("aragora.server.handlers", "BroadcastHandler")
TranscriptionHandler = _safe_import("aragora.server.handlers", "TranscriptionHandler")
VoiceHandler = _safe_import("aragora.server.handlers.voice.handler", "VoiceHandler")
# =============================================================================
# Collaboration and Notifications Handler Imports
# =============================================================================

CollaborationHandler = _safe_import(
    "aragora.server.handlers.social.collaboration", "CollaborationHandler"
)
NotificationsHandler = _safe_import(
    "aragora.server.handlers.social.notifications", "NotificationsHandler"
)
ChannelHealthHandler = _safe_import(
    "aragora.server.handlers.social.channel_health", "ChannelHealthHandler"
)

# =============================================================================
# Inbox Handler Imports
# =============================================================================

UnifiedInboxHandler = _safe_import("aragora.server.handlers.features", "UnifiedInboxHandler")
InboxCommandHandler = _safe_import("aragora.server.handlers.inbox_command", "InboxCommandHandler")
SharedInboxHandler = _safe_import(
    "aragora.server.handlers.shared_inbox.handler", "SharedInboxHandler"
)
InboxTrustWedgeHandler = _safe_import(
    "aragora.server.handlers.inbox.trust_wedge_handler", "InboxTrustWedgeHandler"
)

# Email triage, feedback hub, notification history/preferences
EmailTriageHandler = _safe_import("aragora.server.handlers.email_triage", "EmailTriageHandler")
FeedbackHubHandler = _safe_import("aragora.server.handlers.feedback_hub", "FeedbackHubHandler")
NotificationHistoryHandler = _safe_import(
    "aragora.server.handlers.notifications.history", "NotificationHistoryHandler"
)
NotificationPreferencesHandler = _safe_import(
    "aragora.server.handlers.notifications.preferences", "NotificationPreferencesHandler"
)
NotificationTemplatesHandler = _safe_import(
    "aragora.server.handlers.notifications.templates", "NotificationTemplatesHandler"
)

# =============================================================================
# Social Handler Registry Entries
# =============================================================================

SOCIAL_HANDLER_REGISTRY: list[tuple[str, object]] = [
    ("_social_handler", SocialMediaHandler),
    # Slack
    ("_slack_handler", SlackHandler),
    ("_slack_oauth_handler", SlackOAuthHandler),
    ("_slack_workspace_handler", SlackWorkspaceHandler),
    # Teams
    ("_teams_integration_handler", TeamsIntegrationHandler),
    ("_teams_oauth_handler", TeamsOAuthHandler),
    ("_teams_handler", TeamsHandler),
    ("_teams_workspace_handler", TeamsWorkspaceHandler),
    # Discord
    ("_discord_oauth_handler", DiscordOAuthHandler),
    ("_discord_handler", DiscordHandler),
    # Google Chat
    ("_google_chat_handler", GoogleChatHandler),
    # Zoom
    ("_zoom_handler", ZoomHandler),
    # Chat and bots
    ("_chat_handler", ChatHandler),
    ("_telegram_handler", TelegramHandler),
    ("_whatsapp_handler", WhatsAppHandler),
    # Email
    ("_email_handler", EmailHandler),
    ("_email_services_handler", EmailServicesHandler),
    ("_gmail_ingest_handler", GmailIngestHandler),
    ("_gmail_labels_handler", GmailLabelsHandler),
    ("_gmail_query_handler", GmailQueryHandler),
    ("_gmail_threads_handler", GmailThreadsHandler),
    ("_email_webhook_handler", EmailWebhookHandler),
    ("_email_webhooks_handler", EmailWebhooksHandler),
    ("_outlook_handler", OutlookHandler),
    # Audio and voice
    ("_audio_handler", AudioHandler),
    ("_broadcast_handler", BroadcastHandler),
    ("_transcription_handler", TranscriptionHandler),
    ("_voice_handler", VoiceHandler),
    # Collaboration
    ("_collaboration_handler", CollaborationHandler),
    ("_notifications_handler", NotificationsHandler),
    ("_channel_health_handler", ChannelHealthHandler),
    # Inbox
    ("_inbox_trust_wedge_handler", InboxTrustWedgeHandler),
    ("_unified_inbox_handler", UnifiedInboxHandler),
    ("_inbox_command_handler", InboxCommandHandler),
    ("_shared_inbox_handler", SharedInboxHandler),
    # Email triage
    ("_email_triage_handler", EmailTriageHandler),
    # Feedback hub
    ("_feedback_hub_handler", FeedbackHubHandler),
    # Notification history, preferences, and templates
    ("_notification_history_handler", NotificationHistoryHandler),
    ("_notification_preferences_handler", NotificationPreferencesHandler),
    ("_notification_templates_handler", NotificationTemplatesHandler),
]

__all__ = [
    # Social media handlers
    "SocialMediaHandler",
    "SlackHandler",
    "SlackOAuthHandler",
    "SlackWorkspaceHandler",
    "TeamsIntegrationHandler",
    "TeamsOAuthHandler",
    "TeamsHandler",
    "TeamsWorkspaceHandler",
    "DiscordOAuthHandler",
    "DiscordHandler",
    "GoogleChatHandler",
    "ZoomHandler",
    # Chat and bots
    "ChatHandler",
    "TelegramHandler",
    "WhatsAppHandler",
    # Email handlers
    "EmailHandler",
    "EmailServicesHandler",
    "GmailIngestHandler",
    "GmailLabelsHandler",
    "GmailQueryHandler",
    "GmailThreadsHandler",
    "EmailWebhookHandler",
    "EmailWebhooksHandler",
    "OutlookHandler",
    # Audio and voice
    "AudioHandler",
    "BroadcastHandler",
    "TranscriptionHandler",
    "VoiceHandler",
    # Collaboration
    "CollaborationHandler",
    "NotificationsHandler",
    "ChannelHealthHandler",
    # Inbox
    "InboxTrustWedgeHandler",
    "UnifiedInboxHandler",
    "InboxCommandHandler",
    "SharedInboxHandler",
    "NotificationHistoryHandler",
    "NotificationPreferencesHandler",
    "NotificationTemplatesHandler",
    # Registry
    "SOCIAL_HANDLER_REGISTRY",
]
