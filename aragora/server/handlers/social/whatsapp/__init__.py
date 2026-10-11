"""
WhatsApp Business API integration package.

This package provides endpoint handlers for WhatsApp Business API integration,
including webhook verification, message handling, and bot commands.

Submodules:
- config: Constants, environment variables, RBAC permissions
- webhooks: Webhook verification and incoming event processing
- messaging: WhatsApp Cloud API message sending
- commands: Bot command implementations (debate, gauntlet, etc.)
- handler: Main WhatsAppHandler class with routing
"""

from .config import (  # noqa: F401
    PERM_WHATSAPP_ADMIN,
    PERM_WHATSAPP_DEBATES,
    PERM_WHATSAPP_DETAILS,
    PERM_WHATSAPP_GAUNTLET,
    PERM_WHATSAPP_MESSAGES,
    PERM_WHATSAPP_READ,
    PERM_WHATSAPP_VOTES,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_BASE,
    WHATSAPP_APP_SECRET,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_VERIFY_TOKEN,
    TTS_VOICE_ENABLED,
    create_tracked_task,
)
from .handler import WhatsAppHandler, get_whatsapp_handler  # noqa: F401

__all__ = ["WhatsAppHandler", "get_whatsapp_handler"]
