"""
Chat Platform Connectors - Unified interface for chat integrations.

This module provides a consistent API for interacting with various
chat platforms including Slack, Microsoft Teams, Discord, and Google Chat.

Usage:
    from aragora.connectors.chat import get_connector, get_registry

    # Get a specific connector
    slack = get_connector("slack")
    await slack.send_message(channel_id, "Hello!")

    # Get all configured connectors
    registry = get_registry()
    for platform, connector in registry.all().items():
        await connector.send_message(channel, f"Hello from {platform}!")

    # Broadcast to multiple platforms
    await registry.broadcast(
        "Important announcement!",
        channels={"slack": "C123", "teams": "channel-guid", "discord": "456"}
    )
"""

from .base import ChatPlatformConnector
from .models import (
    BotCommand,
    ChatChannel,
    ChatMessage,
    ChatUser,
    FileAttachment,
    InteractionType,
    MessageBlock,
    MessageButton,
    MessageType,
    SendMessageRequest,
    SendMessageResponse,
    UserInteraction,
    VoiceMessage,
    WebhookEvent,
)
from .registry import (
    ChatPlatformRegistry,
    get_connector,
    get_registry,
    get_configured_platforms,
    list_available_platforms,
    register_connector,
)
from .voice_bridge import VoiceBridge, get_voice_bridge
from .tts_bridge import TTSBridge, TTSConfig, get_tts_bridge, clear_tts_bridge
from .thread_manager import (
    ThreadInfo,
    ThreadStats,
    ThreadParticipant,
    ThreadManager,
    ThreadNotFoundError,
)
from aragora.core.decision_route_hooks import (
    register_tts_bridge_factory as _register_tts_bridge_factory,
)

# The core decision router synthesizes voice responses through this registration.
_register_tts_bridge_factory(get_tts_bridge)

__all__ = [
    # Base class
    "ChatPlatformConnector",
    # Models
    "BotCommand",
    "ChatChannel",
    "ChatMessage",
    "ChatUser",
    "FileAttachment",
    "InteractionType",
    "MessageBlock",
    "MessageButton",
    "MessageType",
    "SendMessageRequest",
    "SendMessageResponse",
    "UserInteraction",
    "VoiceMessage",
    "WebhookEvent",
    # Registry
    "ChatPlatformRegistry",
    "get_connector",
    "get_registry",
    "get_configured_platforms",
    "list_available_platforms",
    "register_connector",
    # Voice (STT)
    "VoiceBridge",
    "get_voice_bridge",
    # TTS (Text-to-Speech)
    "TTSBridge",
    "TTSConfig",
    "get_tts_bridge",
    "clear_tts_bridge",
    # Thread Management
    "ThreadInfo",
    "ThreadStats",
    "ThreadParticipant",
    "ThreadManager",
    "ThreadNotFoundError",
    "SlackThreadManager",
    "TeamsThreadManager",
]


def __getattr__(name: str):
    """Lazy-load connector classes."""
    if name == "SlackConnector":
        from .slack import SlackConnector

        return SlackConnector
    elif name == "TeamsConnector":
        from .teams import TeamsConnector

        return TeamsConnector
    elif name == "DiscordConnector":
        from .discord import DiscordConnector

        return DiscordConnector
    elif name == "GoogleChatConnector":
        from .google_chat import GoogleChatConnector

        return GoogleChatConnector
    elif name == "TelegramConnector":
        from .telegram import TelegramConnector

        return TelegramConnector
    elif name == "WhatsAppConnector":
        from .whatsapp import WhatsAppConnector

        return WhatsAppConnector
    elif name == "SlackThreadManager":
        from .slack import SlackThreadManager

        return SlackThreadManager
    elif name == "TeamsThreadManager":
        from .teams import TeamsThreadManager

        return TeamsThreadManager

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
