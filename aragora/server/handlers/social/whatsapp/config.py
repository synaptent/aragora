"""
WhatsApp integration configuration, constants, and shared utilities.

Contains environment variable loading, RBAC permission constants,
and helper functions used across the WhatsApp handler submodules.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

# =============================================================================
# RBAC Permission constants for WhatsApp integration
# =============================================================================
# These permissions control access to WhatsApp bot functionality.
# We reuse existing RBAC permissions from the system defaults where appropriate,
# and define WhatsApp-specific permissions for platform-specific operations.
#
# Existing permissions used:
# - bots.read: View bot integration status (for /status endpoint)
# - debates.create: Create new debates
# - debates.read: View debate details
# - gauntlet.run: Run gauntlet stress tests
# - debates.update: Record votes on debates (update debate state)
#
# WhatsApp-specific permissions (for future registration):
PERM_WHATSAPP_READ = "bots.read"  # Use existing bot read permission for status
PERM_WHATSAPP_MESSAGES = "bots.read"  # Message handling uses basic bot permission
PERM_WHATSAPP_DEBATES = "debates.create"  # Create debates from WhatsApp
PERM_WHATSAPP_GAUNTLET = "gauntlet.run"  # Run gauntlet stress tests
PERM_WHATSAPP_VOTES = "debates.update"  # Record votes (update debate state)
PERM_WHATSAPP_DETAILS = "debates.read"  # View debate details
PERM_WHATSAPP_ADMIN = "bots.*"  # Full admin access to bot integrations

# TTS support
TTS_VOICE_ENABLED = os.environ.get("WHATSAPP_TTS_ENABLED", "false").lower() == "true"

# Environment variables for WhatsApp integration
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET")
WHATSAPP_API_BASE = "https://graph.facebook.com/v18.0"

# Log at debug level for unconfigured optional integrations
if not WHATSAPP_ACCESS_TOKEN:
    logger.debug("WHATSAPP_ACCESS_TOKEN not configured - WhatsApp messaging disabled")
if not WHATSAPP_VERIFY_TOKEN:
    logger.debug("WHATSAPP_VERIFY_TOKEN not configured - webhook verification disabled")
if not WHATSAPP_APP_SECRET:
    logger.debug("WHATSAPP_APP_SECRET not configured - signature verification disabled")


# =============================================================================
# Task utilities
# =============================================================================


def _handle_task_exception(task: asyncio.Task[Any], task_name: str) -> None:
    """Handle exceptions from fire-and-forget async tasks."""
    if task.cancelled():
        logger.debug("Task %s was cancelled", task_name)
    elif task.exception():
        exc = task.exception()
        logger.error("Task %s failed with exception: %s", task_name, exc, exc_info=exc)


def create_tracked_task(coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
    """Create an async task with exception logging."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(lambda t: _handle_task_exception(t, name))
    return task


# =============================================================================
# RBAC imports - optional dependency
# =============================================================================
check_permission: Callable[..., Any] | None
extract_user_from_request: Callable[..., Any] | None
AuthorizationContext: type[Any] | None

try:
    from aragora.rbac.checker import check_permission as _check_perm  # noqa: F401
    from aragora.rbac.models import AuthorizationContext as _AuthCtx  # noqa: F401

    check_permission = _check_perm
    AuthorizationContext = _AuthCtx

    # extract_user_from_request is in billing.auth.context, not rbac.middleware
    # Import it from the correct location for proper typing
    try:
        from aragora.billing.auth.context import (
            extract_user_from_request as _extract_user,
        )

        extract_user_from_request = _extract_user
    except ImportError:
        extract_user_from_request = None

    RBAC_AVAILABLE = True
except (ImportError, AttributeError):
    RBAC_AVAILABLE = False
    check_permission = None
    extract_user_from_request = None
    AuthorizationContext = None
