"""Plan lifecycle notifications carry the plan's org and stay within it.

Approving or rejecting an org-A plan through the plans handler fires a
background notification task. With a captured notifier (the server's Slack
channel plus webhook endpoints of org A, org B and the operator, posting to a
fake HTTP session), every emitted notification must carry org A's id and
nothing may reach org B's endpoint. The task re-checks the org it was given
against the plan's own org and sends nothing when they differ or the plan has
no org.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationResult,
    SlackConfig,
    WebhookEndpoint,
)
from aragora.notifications.providers import SlackProvider, WebhookProvider
from aragora.notifications.retry_queue import RetryEntry
from aragora.notifications.service import NotificationService
from aragora.pipeline.decision_plan.core import ApprovalMode, DecisionPlan, PlanStatus
from aragora.server.handlers.decisions import plans as plans_mod
from aragora.tenancy.record_scope import OrgScope

ORG_A = "org-a"
ORG_B = "org-b"
SCOPE_A = OrgScope(org_id=ORG_A, user_id="user-a", role="admin")
OPS_CHANNEL = "#aragora-ops"
ENDPOINTS = {
    "hook-a": ("https://a.invalid/hook", ORG_A),
    "hook-b": ("https://b.invalid/hook", ORG_B),
    "hook-ops": ("https://ops.invalid/hook", None),
}
_ENDPOINT_BY_URL = {url: endpoint_id for endpoint_id, (url, _org) in ENDPOINTS.items()}

#: (channel, recipient, delivered payload) for every captured delivery.
Sent = list[tuple[str, str, dict[str, Any]]]


class _CapturedSlack(SlackProvider):
    """The server's Slack channel, recording instead of posting."""

    def __init__(self, sent: Sent) -> None:
        super().__init__(
            SlackConfig(webhook_url="https://slack.invalid/hook", default_channel=OPS_CHANNEL)
        )
        self._sent = sent

    async def send(self, notification: Notification, recipient: str) -> NotificationResult:
        self._sent.append(("slack", recipient, notification.to_dict()))
        return NotificationResult(
            success=True,
            channel=NotificationChannel.SLACK,
            recipient=recipient,
            notification_id=notification.id,
        )


class _FakeResponse:
    status = 200

    async def text(self) -> str:
        return ""

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSession:
    """Stands in for ``aiohttp.ClientSession``: records each webhook POST."""

    def __init__(self, sent: Sent) -> None:
        self._sent = sent

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def post(self, url: str, data: str, headers: dict[str, str]) -> _FakeResponse:
        self._sent.append(("webhook", _ENDPOINT_BY_URL[url], json.loads(data)))
        return _FakeResponse()


@pytest.fixture
def sent(monkeypatch) -> Sent:
    import aiohttp

    captured: Sent = []
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **kw: _FakeSession(captured))
    monkeypatch.setattr(
        "aragora.security.ssrf_protection.validate_url",
        lambda url: SimpleNamespace(is_safe=True, error=None),
    )
    monkeypatch.setattr("aragora.notifications.providers._log_delivery", AsyncMock())
    return captured


@pytest.fixture
def notifier(sent):
    webhooks = WebhookProvider()
    for endpoint_id, (url, org_id) in ENDPOINTS.items():
        webhooks.add_endpoint(WebhookEndpoint(id=endpoint_id, url=url, org_id=org_id))
    service = NotificationService(enable_circuit_breakers=False)
    service.providers = {
        NotificationChannel.SLACK: _CapturedSlack(sent),
        NotificationChannel.WEBHOOK: webhooks,
    }
    with patch("aragora.notifications.service.get_notification_service", return_value=service):
        yield service


def _plan(plan_id: str, org_id: str | None) -> DecisionPlan:
    plan = DecisionPlan(
        id=plan_id,
        debate_id=f"debate-{plan_id}",
        task=f"Task of {plan_id}",
        status=PlanStatus.AWAITING_APPROVAL,
        approval_mode=ApprovalMode.ALWAYS,
    )
    plan.org_id = org_id
    plan.created_by = "user-a" if org_id == ORG_A else None
    return plan


async def _drain_background_tasks() -> None:
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current]
    await asyncio.gather(*pending, return_exceptions=True)


def _handler(plan: DecisionPlan, body: dict[str, Any]) -> tuple[Any, MagicMock]:
    store = MagicMock()
    store.get.return_value = plan
    store.update_status_for_org.return_value = True
    handler = plans_mod.PlansHandler(ctx={})
    user = MagicMock()
    user.user_id = "user-a"
    handler.require_permission_or_error = MagicMock(return_value=(user, None))
    handler.read_json_body = MagicMock(return_value=body)
    return handler, store


def _summary(sent: Sent) -> list[dict[str, Any]]:
    return [
        {
            "channel": channel,
            "recipient": recipient,
            "org_id": payload.get("org_id"),
            "resource_id": payload.get("resource_id"),
            "event": payload.get("metadata", {}).get("event"),
        }
        for channel, recipient, payload in sent
    ]


class TestHandlerNotificationsStayInTheOrg:
    @pytest.mark.parametrize(
        ("action", "body", "event"),
        [
            ("approve", {}, "plan.approved"),
            ("reject", {"reason": "not now"}, "plan.rejected"),
        ],
    )
    @pytest.mark.asyncio
    async def test_org_a_decision_notifies_only_org_a(self, notifier, sent, action, body, event):
        handler, store = _handler(_plan("plan-a", ORG_A), body)
        method = handler._approve_plan if action == "approve" else handler._reject_plan

        with (
            patch.object(plans_mod, "_get_plan_store", return_value=store),
            patch.object(plans_mod, "BackboneRuntime", MagicMock()),
        ):
            result = method({"plan_id": "plan-a"}, MagicMock(), SCOPE_A)
            await _drain_background_tasks()

        assert result.status_code == 200
        captured = _summary(sent)
        print("captured notifications:", json.dumps(captured, indent=1))
        assert {entry["org_id"] for entry in captured} == {ORG_A}
        assert {entry["event"] for entry in captured} == {event}
        assert {entry["resource_id"] for entry in captured} == {"plan-a"}
        recipients = {(entry["channel"], entry["recipient"]) for entry in captured}
        assert ("webhook", "hook-b") not in recipients
        assert {("webhook", "hook-a"), ("slack", OPS_CHANNEL)} <= recipients


class TestBackgroundTaskRechecksTheOrg:
    @pytest.mark.parametrize("plan_org", [ORG_B, None, ""])
    @pytest.mark.asyncio
    async def test_plan_not_owned_by_the_given_org_sends_nothing(self, notifier, sent, plan_org):
        plans_mod._fire_plan_notification(
            "approved", _plan("plan-x", plan_org), org_id=ORG_A, approved_by="user-a"
        )
        await _drain_background_tasks()

        assert sent == []

    @pytest.mark.parametrize("given_org", [None, ""])
    @pytest.mark.asyncio
    async def test_task_without_an_org_sends_nothing(self, notifier, sent, given_org):
        plans_mod._fire_plan_notification("created", _plan("plan-a", ORG_A), org_id=given_org)
        await _drain_background_tasks()

        assert sent == []


class TestNotifyFunctionsRequireTheOwningOrg:
    @pytest.fixture
    def service(self):
        service = MagicMock()
        service.notify = AsyncMock(return_value=[])
        service.notify_all_webhooks = AsyncMock(return_value=[])
        with patch("aragora.notifications.service.get_notification_service", return_value=service):
            yield service

    @pytest.mark.asyncio
    async def test_mismatched_org_is_refused_before_the_notifier(self, service):
        from aragora.pipeline.notifications import notify_plan_approved

        results = await notify_plan_approved(_plan("plan-b", ORG_B), "user-a", org_id=ORG_A)

        assert results == []
        service.notify.assert_not_called()
        service.notify_all_webhooks.assert_not_called()

    @pytest.mark.asyncio
    async def test_unowned_plan_is_refused(self, service):
        from aragora.pipeline.notifications import notify_plan_created

        results = await notify_plan_created(_plan("plan-null", None))

        assert results == []
        service.notify.assert_not_called()
        service.notify_all_webhooks.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_carries_the_plans_org(self, service):
        from aragora.pipeline.notifications import notify_execution_failed

        await notify_execution_failed(_plan("plan-a", ORG_A), "boom")

        assert service.notify.call_args.args[0].org_id == ORG_A
        assert service.notify_all_webhooks.call_args.args[0].org_id == ORG_A


class TestWebhookEndpointsOwnedByAnOrg:
    @staticmethod
    def _note(org_id: str | None) -> Notification:
        return Notification(title="t", message="m", org_id=org_id)

    @pytest.mark.asyncio
    async def test_send_refuses_another_orgs_endpoint(self, notifier, sent):
        result = await notifier.webhook_provider.send(self._note(ORG_A), "hook-b")

        assert result.success is False
        assert result.error == "Webhook endpoint not found: hook-b"
        assert sent == []

    def test_endpoint_org_rules(self):
        owned = WebhookEndpoint(id="hook-b", url="https://b.invalid/hook", org_id=ORG_B)
        operator = WebhookEndpoint(id="hook-ops", url="https://ops.invalid/hook")

        assert owned.receives_org(ORG_B)
        assert not owned.receives_org(ORG_A)
        assert not owned.receives_org(None)
        assert operator.receives_org(ORG_A)
        assert operator.receives_org(None)

    @pytest.mark.asyncio
    async def test_default_recipients_skip_other_orgs_endpoints(self, notifier, sent):
        await notifier.notify(self._note(ORG_A), channels=[NotificationChannel.WEBHOOK])

        assert sorted(recipient for _c, recipient, _p in sent) == ["hook-a", "hook-ops"]

    @pytest.mark.asyncio
    async def test_matching_webhooks_skip_other_orgs_endpoints(self, notifier, sent):
        await notifier.notify_all_webhooks(self._note(ORG_A), "plan.approved")

        assert sorted(recipient for _c, recipient, _p in sent) == ["hook-a", "hook-ops"]

    @pytest.mark.asyncio
    async def test_org_less_notification_skips_every_org_endpoint(self, notifier, sent):
        await notifier.notify_all_webhooks(self._note(None), "system.event")

        assert [recipient for _c, recipient, _p in sent] == ["hook-ops"]

    @pytest.mark.asyncio
    async def test_retry_keeps_the_notification_org(self, notifier, sent):
        note = self._note(ORG_A)
        notifier.retry_queue.enqueue(
            RetryEntry(
                id="retry-1",
                notification_id=note.id,
                channel=NotificationChannel.WEBHOOK.value,
                recipient="hook-a",
                payload=note.to_dict(),
            )
        )

        await notifier.process_retry_queue()

        assert [(recipient, payload["org_id"]) for _c, recipient, payload in sent] == [
            ("hook-a", ORG_A)
        ]
