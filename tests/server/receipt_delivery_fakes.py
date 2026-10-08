"""Workspace stores and connector stubs for the receipt channel-delivery tests.

Slack keeps the real ``SlackConnector`` constructor and stubs only its
transport (``_slack_api_request``), with the process-wide ``SLACK_BOT_TOKEN``
set to a sentinel: a constructor kwarg the connector ignores, or a fallback to
the global token, shows up as the wrong bearer token on the recorded request.
The Teams connector is a fake whose constructor takes exactly the keywords the
handler passes today, so an unknown keyword fails.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

GLOBAL_SLACK_TOKEN = "xoxb-global-sentinel-never-sent"
EMPTY_TOKEN_WORKSPACE = "W-A-EMPTY"


def slack_token(workspace_id: str) -> str:
    """The bot token stored for ``workspace_id`` (empty for the token-less one)."""
    return "" if workspace_id == EMPTY_TOKEN_WORKSPACE else f"xoxb-{workspace_id.lower()}-token"


def teams_bot_id(workspace_id: str) -> str:
    return f"bot-{workspace_id.lower()}"


class WorkspaceStore:
    """Workspace store keyed by id; ``org_attr`` names the field holding the owning org."""

    def __init__(self, org_attr: str, owners: dict[str, str | None]) -> None:
        self._workspaces = {
            workspace_id: SimpleNamespace(
                **{org_attr: owner},
                workspace_id=workspace_id,
                access_token=slack_token(workspace_id),
                signing_secret=f"signing-secret-{workspace_id.lower()}",
                bot_id=teams_bot_id(workspace_id),
                service_url="https://smba.invalid/",
            )
            for workspace_id, owner in owners.items()
        }

    def get(self, workspace_id: str) -> Any:
        return self._workspaces.get(workspace_id)


def install_delivery_fakes(
    monkeypatch: pytest.MonkeyPatch, owners: dict[str, str | None]
) -> list[tuple[str, str, str]]:
    """Install the fakes; return the sends as ``(channel_type, channel_id, credential)``.

    The credential is the bearer token of the Slack request, or the app id the
    Teams connector was built with.
    """
    from aragora.connectors.chat import slack as slack_module
    from aragora.connectors.chat.slack import client as slack_client

    sends: list[tuple[str, str, str]] = []

    async def slack_transport(self, endpoint, payload=None, operation="api_call", **_options):
        assert endpoint == "chat.postMessage", endpoint
        bearer = self._get_headers()["Authorization"].removeprefix("Bearer ")
        sends.append(("slack", payload["channel"], bearer))
        return True, {"ts": "1700000000.000100", "channel": payload["channel"]}, None

    class TeamsConnector:
        def __init__(self, *, app_id: str, app_password: str, service_url: str) -> None:
            self.app_id = app_id

        async def send_message(
            self, *, channel_id: str, text: str, blocks: list[Any], conversation_id: str
        ) -> Any:
            sends.append(("teams", channel_id, self.app_id))
            return SimpleNamespace(timestamp="1.0", channel_id=channel_id, message_id="m-1")

    monkeypatch.setattr(slack_module, "SLACK_BOT_TOKEN", GLOBAL_SLACK_TOKEN)
    monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", GLOBAL_SLACK_TOKEN)
    monkeypatch.setenv("SLACK_BOT_TOKEN", GLOBAL_SLACK_TOKEN)
    monkeypatch.setattr(slack_module.SlackConnector, "_slack_api_request", slack_transport)
    monkeypatch.setattr("aragora.connectors.chat.teams.TeamsConnector", TeamsConnector)
    monkeypatch.setattr(
        "aragora.storage.slack_workspace_store.get_slack_workspace_store",
        lambda: WorkspaceStore("tenant_id", owners),
    )
    monkeypatch.setattr(
        "aragora.storage.teams_workspace_store.get_teams_workspace_store",
        lambda: WorkspaceStore("aragora_tenant_id", owners),
    )
    return sends
