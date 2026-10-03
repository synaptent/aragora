"""Chat connector adapters for billing budget-alert delivery."""

from __future__ import annotations

from typing import Any, cast

from aragora.billing.budget_alert_notifier import register_budget_alert_sink


class SlackBudgetAlertSink:
    """Deliver billing budget alerts through a configured Slack workspace."""

    async def deliver(
        self,
        *,
        workspace_id: str,
        channel_id: str,
        message: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        from aragora.connectors.chat.slack import SlackConnector
        from aragora.storage.slack_workspace_store import get_slack_workspace_store

        workspace = get_slack_workspace_store().get(workspace_id)
        if not workspace or not workspace.access_token:
            raise ValueError(f"No Slack workspace found: {workspace_id}")

        connector = SlackConnector(bot_token=workspace.access_token)
        await connector.send_message(
            channel_id=channel_id,
            text=message["text"],
            blocks=cast(list[dict[str, Any] | None], message.get("blocks")),
        )


class TeamsBudgetAlertSink:
    """Deliver billing budget alerts through a configured Teams tenant."""

    async def deliver(
        self,
        *,
        workspace_id: str,
        channel_id: str,
        message: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        from aragora.connectors.chat.teams import TeamsConnector
        from aragora.storage.teams_workspace_store import get_teams_workspace_store

        workspace = get_teams_workspace_store().get(workspace_id)
        if not workspace or not workspace.access_token:
            raise ValueError(f"No Teams workspace found: {workspace_id}")

        connector = TeamsConnector(app_password=workspace.access_token)
        await connector.send_message(
            channel_id=channel_id,
            text=message["text"],
        )


def register_budget_alert_sinks() -> None:
    """Register chat adapters with the billing-owned sink registry."""
    register_budget_alert_sink("slack", SlackBudgetAlertSink())
    register_budget_alert_sink("teams", TeamsBudgetAlertSink())
