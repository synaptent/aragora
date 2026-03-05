"""
Bots Namespace API.

Provides webhook helpers for bot integrations (Teams, Discord, Telegram,
WhatsApp, Google Chat, Zoom).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class BotsAPI:
    """Synchronous bots API."""

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def teams_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.request("POST", "/api/v1/bots/teams/messages", json=payload)

    def teams_status(self) -> dict[str, Any]:
        return self._client.request("GET", "/api/v1/bots/teams/status")

    def discord_interactions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.request("POST", "/api/v1/bots/discord/interactions", json=payload)

    def discord_status(self) -> dict[str, Any]:
        return self._client.request("GET", "/api/v1/bots/discord/status")

    def telegram_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.request("POST", "/api/v1/bots/telegram/webhook", json=payload)

    def telegram_status(self) -> dict[str, Any]:
        return self._client.request("GET", "/api/v1/bots/telegram/status")

    def whatsapp_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.request("POST", "/api/v1/bots/whatsapp/webhook", json=payload)

    def whatsapp_status(self) -> dict[str, Any]:
        return self._client.request("GET", "/api/v1/bots/whatsapp/status")

    def google_chat_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.request("POST", "/api/v1/bots/google-chat/webhook", json=payload)

    def google_chat_status(self) -> dict[str, Any]:
        return self._client.request("GET", "/api/v1/bots/google-chat/status")

    def zoom_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.request("POST", "/api/v1/bots/zoom/events", json=payload)

    def zoom_status(self) -> dict[str, Any]:
        return self._client.request("GET", "/api/v1/bots/zoom/status")

    def slack_status(self) -> dict[str, Any]:
        """Get Slack integration status."""
        return self._client.request("GET", "/api/v1/bots/slack/status")


class AsyncBotsAPI:
    """Asynchronous bots API."""

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def teams_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.request("POST", "/api/v1/bots/teams/messages", json=payload)

    async def teams_status(self) -> dict[str, Any]:
        return await self._client.request("GET", "/api/v1/bots/teams/status")

    async def discord_interactions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.request("POST", "/api/v1/bots/discord/interactions", json=payload)

    async def discord_status(self) -> dict[str, Any]:
        return await self._client.request("GET", "/api/v1/bots/discord/status")

    async def telegram_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.request("POST", "/api/v1/bots/telegram/webhook", json=payload)

    async def telegram_status(self) -> dict[str, Any]:
        return await self._client.request("GET", "/api/v1/bots/telegram/status")

    async def whatsapp_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.request("POST", "/api/v1/bots/whatsapp/webhook", json=payload)

    async def whatsapp_status(self) -> dict[str, Any]:
        return await self._client.request("GET", "/api/v1/bots/whatsapp/status")

    async def google_chat_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.request("POST", "/api/v1/bots/google-chat/webhook", json=payload)

    async def google_chat_status(self) -> dict[str, Any]:
        return await self._client.request("GET", "/api/v1/bots/google-chat/status")

    async def zoom_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.request("POST", "/api/v1/bots/zoom/events", json=payload)

    async def zoom_status(self) -> dict[str, Any]:
        return await self._client.request("GET", "/api/v1/bots/zoom/status")

    async def slack_status(self) -> dict[str, Any]:
        """Get Slack integration status."""
        return await self._client.request("GET", "/api/v1/bots/slack/status")
