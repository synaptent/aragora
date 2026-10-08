"""Org isolation of the decision receipt routes (ReceiptsHandler, v2 and v1).

Two orgs and an anonymous caller exercise every receipt route against a real
SQLite receipt store holding receipts of org A, org B and one with no owner:

* another org's receipt answers exactly like a missing one (same 404 body),
  and acting on it has no side effect;
* lists, search, stats, retention status, DSAR and delivery history only
  show the caller org's receipts; an unowned receipt is shown to nobody;
* anonymous callers get 401 and static-API-token-only callers 403
  ``org_required``;
* the public-by-design routes (share-token read, signing keys, stateless
  verify) stay reachable anonymously;
* the owner keeps full access.
"""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.export.decision_receipt import DecisionReceipt
from aragora.server.handlers.decisions.receipts import ReceiptsHandler
from aragora.server.handlers.utils.receipt_delivery_history import (
    DELIVERY_ORG_KEY,
    get_receipt_delivery_history_store,
)
from aragora.storage.receipt_store import ReceiptStore

ORG_A = "org-a"
ORG_B = "org-b"
NOT_FOUND = {"error": "Receipt not found", "code": "not_found"}

USER_A = UserAuthContext(
    authenticated=True,
    user_id="user-a",
    email="a@example.com",
    org_id=ORG_A,
    role="admin",
    token_type="access",
)
USER_B = UserAuthContext(
    authenticated=True,
    user_id="user-b",
    email="b@example.com",
    org_id=ORG_B,
    role="admin",
    token_type="access",
)
ANONYMOUS = UserAuthContext(authenticated=False)


def _payload(receipt_id: str, user_id: str) -> dict[str, Any]:
    payload = DecisionReceipt(
        receipt_id=receipt_id,
        gauntlet_id=f"g-{receipt_id}",
        verdict="PASS",
        confidence=0.9,
        risk_level="LOW",
        input_summary=f"isolation probe {receipt_id}",
        # Debate receipts store one mapping per agent.
        agents_involved=[{"name": "gpt55", "model": "gpt-5.5", "role": "proposer"}],
    ).to_dict()
    payload["user_id"] = user_id
    return payload


class _ShareStore:
    """In-memory share-link store with the methods the handler calls."""

    def __init__(self) -> None:
        self.links: dict[str, dict[str, Any]] = {}

    def save(self, *, token, receipt_id, expires_at, max_accesses) -> None:
        self.links[token] = {
            "token": token,
            "receipt_id": receipt_id,
            "expires_at": expires_at,
            "max_accesses": max_accesses,
            "access_count": 0,
        }

    def get_by_token(self, token: str) -> dict[str, Any] | None:
        return self.links.get(token)

    def increment_access(self, token: str) -> None:
        self.links[token]["access_count"] += 1


@pytest.fixture
def store(tmp_path) -> ReceiptStore:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    store.save(_payload("rcpt-a", "subject-1"), org_id=ORG_A, created_by="user-a")
    store.save(_payload("rcpt-a2", "subject-2"), org_id=ORG_A, created_by="user-a")
    store.save(_payload("rcpt-b", "subject-1"), org_id=ORG_B, created_by="user-b")
    store.save(_payload("rcpt-null", "subject-1"))
    return store


@pytest.fixture
def share_store() -> _ShareStore:
    return _ShareStore()


@pytest.fixture
def receipts(store, share_store) -> ReceiptsHandler:
    handler = ReceiptsHandler(MagicMock())
    handler._store = store
    handler._share_store = share_store
    handler._send_to_slack = AsyncMock(return_value={"ok": True, "channel": "C1"})
    return handler


@pytest.fixture(autouse=True)
def _empty_delivery_history():
    history = get_receipt_delivery_history_store()
    history.clear()
    yield
    history.clear()


@pytest.fixture
def act_as(monkeypatch):
    """Make every following request come from ``user``."""

    def _act_as(user: UserAuthContext) -> None:
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )

    return _act_as


def _request(headers: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    request._auth_context = None
    return request


async def _call(
    receipts: ReceiptsHandler,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
):
    return await receipts.handle(
        method, path, dict(body or {}), dict(query or {}), {}, _request(headers)
    )


def _json(result) -> Any:
    return json.loads(result.body)


# (method, path template, body, query) for every route acting on one receipt.
PER_RECEIPT_ROUTES = [
    ("GET", "/api/v2/receipts/{id}", None, None),
    ("GET", "/api/v2/receipts/{id}/formatted/slack", None, None),
    ("GET", "/api/v2/receipts/{id}/export", None, {"format": "json"}),
    ("GET", "/api/v2/receipts/{id}/export", None, {"format": "md"}),
    ("GET", "/api/v2/receipts/{id}/export", None, {"format": "odr"}),
    ("GET", "/api/v2/receipts/{id}/verify", None, None),
    ("POST", "/api/v2/receipts/{id}/verify", None, None),
    ("POST", "/api/v2/receipts/{id}/verify-signature", None, None),
    ("POST", "/api/v2/receipts/{id}/share", {"expires_in_hours": 1}, None),
    (
        "POST",
        "/api/v2/receipts/{id}/send-to-channel",
        {"channel_type": "slack", "channel_id": "C1"},
        None,
    ),
    ("GET", "/api/v1/receipts/{id}", None, None),
    ("GET", "/api/v1/receipts/{id}/export", None, {"format": "json"}),
    ("GET", "/api/v1/receipts/{id}/verify", None, None),
    ("POST", "/api/v1/receipts/{id}/verify", None, None),
    ("POST", "/api/v1/receipts/{id}/deliver", {"channel": "slack", "destination": "C1"}, None),
]
ROUTE_IDS = [f"{m} {p} {q or ''}".strip() for m, p, _b, q in PER_RECEIPT_ROUTES]

COLLECTION_ROUTES = [
    ("GET", "/api/v2/receipts", None, None),
    ("GET", "/api/v2/receipts/search", None, {"q": "isolation"}),
    ("GET", "/api/v2/receipts/stats", None, None),
    ("GET", "/api/v2/receipts/retention-status", None, None),
    ("GET", "/api/v2/receipts/dsar/subject-1", None, None),
    ("POST", "/api/v2/receipts/verify-batch", {"receipt_ids": ["rcpt-a"]}, None),
    ("POST", "/api/v2/receipts/sign-batch", {"receipt_ids": ["rcpt-a"]}, None),
    ("POST", "/api/v2/receipts/batch-export", {"receipt_ids": ["rcpt-a"]}, None),
    ("GET", "/api/v1/receipts", None, None),
    ("GET", "/api/v1/receipts/deliveries", None, None),
]
ALL_SCOPED_ROUTES = [
    (m, p.format(id="rcpt-a"), b, q) for m, p, b, q in PER_RECEIPT_ROUTES
] + COLLECTION_ROUTES


class TestForeignReceiptIsIndistinguishableFromMissing:
    @pytest.mark.parametrize(("method", "path", "body", "query"), PER_RECEIPT_ROUTES, ids=ROUTE_IDS)
    @pytest.mark.asyncio
    async def test_other_org_gets_the_missing_receipt_404(
        self, receipts, act_as, method, path, body, query
    ):
        act_as(USER_B)
        foreign = await _call(receipts, method, path.format(id="rcpt-a"), body=body, query=query)
        missing = await _call(
            receipts, method, path.format(id="rcpt-missing"), body=body, query=query
        )

        assert foreign.status_code == missing.status_code == 404
        assert foreign.body == missing.body
        assert _json(foreign) == NOT_FOUND
        assert "X-ODR-Digest" not in (foreign.headers or {})

    @pytest.mark.parametrize(("method", "path", "body", "query"), PER_RECEIPT_ROUTES, ids=ROUTE_IDS)
    @pytest.mark.asyncio
    async def test_unowned_receipt_is_invisible_to_every_org(
        self, receipts, act_as, method, path, body, query
    ):
        for user in (USER_A, USER_B):
            act_as(user)
            result = await _call(
                receipts, method, path.format(id="rcpt-null"), body=body, query=query
            )
            assert result.status_code == 404
            assert _json(result) == NOT_FOUND

    @pytest.mark.asyncio
    async def test_gauntlet_id_lookup_is_scoped_too(self, receipts, act_as):
        act_as(USER_B)
        result = await _call(receipts, "GET", "/api/v2/receipts/g-rcpt-a")
        assert result.status_code == 404
        act_as(USER_A)
        result = await _call(receipts, "GET", "/api/v2/receipts/g-rcpt-a")
        assert _json(result)["receipt_id"] == "rcpt-a"


class TestForeignActionsHaveNoSideEffect:
    @pytest.mark.asyncio
    async def test_share_creates_no_link(self, receipts, act_as, share_store):
        act_as(USER_B)
        await _call(receipts, "POST", "/api/v2/receipts/rcpt-a/share", body={})
        assert share_store.links == {}

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (
                "/api/v2/receipts/rcpt-a/send-to-channel",
                {"channel_type": "slack", "channel_id": "C1"},
            ),
            ("/api/v1/receipts/rcpt-a/deliver", {"channel": "slack", "destination": "C1"}),
        ],
    )
    @pytest.mark.asyncio
    async def test_delivery_sends_and_records_nothing(self, receipts, act_as, path, body):
        act_as(USER_B)
        await _call(receipts, "POST", path, body=body)
        receipts._send_to_slack.assert_not_awaited()
        assert list(get_receipt_delivery_history_store()) == []

    @pytest.mark.asyncio
    async def test_sign_batch_reports_not_found_and_signs_nothing(self, receipts, act_as, store):
        act_as(USER_B)
        result = await _call(
            receipts, "POST", "/api/v2/receipts/sign-batch", body={"receipt_ids": ["rcpt-a"]}
        )
        assert result.status_code == 200
        assert _json(result)["results"] == [{"receipt_id": "rcpt-a", "status": "not_found"}]
        assert store.get("rcpt-a").signature is None

    @pytest.mark.asyncio
    async def test_batch_export_reports_not_found_and_exports_nothing(self, receipts, act_as):
        act_as(USER_B)
        result = await _call(
            receipts,
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": ["rcpt-a", "rcpt-b"]},
        )
        archive = zipfile.ZipFile(io.BytesIO(result.body))
        manifest = json.loads(archive.read("manifest.json"))
        assert sorted(archive.namelist()) == ["manifest.json", "receipt-rcpt-b.json"]
        assert manifest["not_found"] == ["rcpt-a"]
        assert manifest["exported"] == 1

    @pytest.mark.parametrize(("user", "own"), [(USER_A, "rcpt-a"), (USER_B, "rcpt-b")])
    @pytest.mark.asyncio
    async def test_batch_export_reports_unowned_receipt_like_a_missing_one(
        self, receipts, act_as, user, own
    ):
        act_as(user)
        result = await _call(
            receipts,
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": ["rcpt-null", "rcpt-missing", own]},
        )
        archive = zipfile.ZipFile(io.BytesIO(result.body))
        manifest = json.loads(archive.read("manifest.json"))
        assert sorted(archive.namelist()) == ["manifest.json", f"receipt-{own}.json"]
        assert manifest["not_found"] == ["rcpt-null", "rcpt-missing"]
        assert manifest["exported"] == 1

    @pytest.mark.asyncio
    async def test_verify_batch_does_not_see_other_orgs(self, receipts, act_as):
        act_as(USER_B)
        result = await _call(
            receipts,
            "POST",
            "/api/v2/receipts/verify-batch",
            body={"receipt_ids": ["rcpt-a", "rcpt-b"]},
        )
        errors = {r["receipt_id"]: r["error"] for r in _json(result)["results"]}
        assert errors["rcpt-a"] == "Receipt not found"
        assert errors["rcpt-b"] != "Receipt not found"


class TestListsShowOnlyTheCallersOrg:
    @pytest.mark.parametrize(
        ("user", "expected"), [(USER_A, {"rcpt-a", "rcpt-a2"}), (USER_B, {"rcpt-b"})]
    )
    @pytest.mark.parametrize(
        ("path", "query"),
        [
            ("/api/v2/receipts", None),
            ("/api/v2/receipts/search", {"q": "isolation"}),
            ("/api/v1/receipts", None),
        ],
    )
    @pytest.mark.asyncio
    async def test_listings(self, receipts, act_as, user, expected, path, query):
        act_as(user)
        result = await _call(receipts, "GET", path, query=query)
        assert result.status_code == 200
        assert {r["receipt_id"] for r in _json(result)["receipts"]} == expected

    @pytest.mark.asyncio
    async def test_v1_list_has_the_frontend_shape(self, receipts, act_as):
        act_as(USER_A)
        body = _json(await _call(receipts, "GET", "/api/v1/receipts"))
        assert body["total"] == 2
        assert {"receipts", "total", "limit", "offset"} <= set(body)

    @pytest.mark.asyncio
    async def test_v1_list_items_keep_the_audit_trail_store_fields(self, receipts, act_as, store):
        # The keys AuditTrailStore.list_receipts returned for this route.
        base_keys = {
            "receipt_id",
            "gauntlet_id",
            "created_at",
            "verdict",
            "confidence",
            "risk_level",
            "checksum",
            "audit_trail_id",
        }
        traced = _payload("rcpt-a3", "subject-3")
        traced["audit_trail_id"] = "trail-a3"
        store.save(traced, org_id=ORG_A, created_by="user-a")
        act_as(USER_A)
        items = _json(await _call(receipts, "GET", "/api/v1/receipts"))["receipts"]

        assert len(items) == 3
        assert {i.get("audit_trail_id") for i in items} == {"trail-a3", None}
        for item in items:
            stored = store.get(item["receipt_id"])
            assert base_keys <= set(item)
            assert item["created_at"] == stored.created_at
            assert item["audit_trail_id"] == stored.audit_trail_id

    @pytest.mark.asyncio
    async def test_counts_cover_only_the_callers_org(self, receipts, act_as):
        act_as(USER_A)
        stats = _json(await _call(receipts, "GET", "/api/v2/receipts/stats"))
        retention = _json(await _call(receipts, "GET", "/api/v2/receipts/retention-status"))
        assert stats["stats"]["total"] == 2
        assert retention["total_receipts"] == 2

    @pytest.mark.asyncio
    async def test_dsar_returns_only_the_callers_org(self, receipts, act_as):
        act_as(USER_B)
        body = _json(await _call(receipts, "GET", "/api/v2/receipts/dsar/subject-1"))
        assert [r["receipt_id"] for r in body["receipts"]] == ["rcpt-b"]

    @pytest.mark.asyncio
    async def test_delivery_history_shows_only_the_callers_org(self, receipts, act_as):
        act_as(USER_A)
        await _call(
            receipts,
            "POST",
            "/api/v1/receipts/rcpt-a/deliver",
            body={"channel": "slack", "destination": "C1"},
        )
        get_receipt_delivery_history_store().append({"receiptId": "legacy", "channel": "slack"})

        own = _json(await _call(receipts, "GET", "/api/v1/receipts/deliveries"))
        assert [d["receiptId"] for d in own["deliveries"]] == ["rcpt-a"]
        assert all("_org_id" not in d for d in own["deliveries"])

        act_as(USER_B)
        other = _json(await _call(receipts, "GET", "/api/v1/receipts/deliveries"))
        assert other == {"deliveries": [], "total": 0, "limit": 50, "offset": 0}


class TestUnauthenticatedCallers:
    @pytest.mark.parametrize(("method", "path", "body", "query"), ALL_SCOPED_ROUTES)
    @pytest.mark.asyncio
    async def test_anonymous_gets_401(self, receipts, act_as, method, path, body, query):
        act_as(ANONYMOUS)
        result = await _call(receipts, method, path, body=body, query=query)
        assert result.status_code == 401
        assert _json(result)["code"] == "auth_required"

    @pytest.mark.parametrize(("method", "path", "body", "query"), ALL_SCOPED_ROUTES)
    @pytest.mark.asyncio
    async def test_static_token_only_gets_403_org_required(
        self, receipts, act_as, monkeypatch, method, path, body, query
    ):
        from aragora.server import auth as server_auth

        monkeypatch.setattr(server_auth.auth_config, "api_token", "static-token-123")
        act_as(ANONYMOUS)
        result = await _call(
            receipts,
            method,
            path,
            body=body,
            query=query,
            headers={"Authorization": "Bearer static-token-123"},
        )
        assert result.status_code == 403
        assert _json(result)["code"] == "org_required"

    @pytest.mark.asyncio
    async def test_anonymous_actions_have_no_side_effect(self, receipts, act_as, share_store):
        act_as(ANONYMOUS)
        await _call(receipts, "POST", "/api/v2/receipts/rcpt-a/share", body={})
        await _call(
            receipts,
            "POST",
            "/api/v1/receipts/rcpt-a/deliver",
            body={"channel": "slack", "destination": "C1"},
        )
        assert share_store.links == {}
        receipts._send_to_slack.assert_not_awaited()


class TestPublicRoutes:
    @pytest.mark.asyncio
    async def test_share_token_read_works_anonymously(self, receipts, act_as):
        act_as(USER_A)
        shared = _json(await _call(receipts, "POST", "/api/v2/receipts/rcpt-a/share", body={}))

        act_as(ANONYMOUS)
        result = await _call(receipts, "GET", shared["share_url"])
        assert result.status_code == 200
        assert _json(result)["receipt"]["receipt_id"] == "rcpt-a"

    @pytest.mark.parametrize(
        "path", ["/api/v2/receipts/signing-key", "/.well-known/aragora-odr-signing-key"]
    )
    @pytest.mark.asyncio
    async def test_signing_keys_are_served_anonymously(self, receipts, act_as, path):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from aragora.gauntlet import odr_signing

        act_as(ANONYMOUS)
        key = Ed25519PrivateKey.generate()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(odr_signing, "load_signing_key_from_secrets", lambda: key)
            result = await _call(receipts, "GET", path)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_stateless_verify_works_anonymously(self, receipts, act_as):
        act_as(USER_A)
        document = _json(
            await _call(receipts, "GET", "/api/v2/receipts/rcpt-a/export", query={"format": "odr"})
        )

        act_as(ANONYMOUS)
        result = await _call(receipts, "POST", "/api/v2/receipts/verify", body=document)
        assert result.status_code == 200
        assert _json(result)["receipt_id"] == "rcpt-a"


class TestOwnerKeepsAccess:
    @pytest.mark.parametrize(("method", "path", "body", "query"), PER_RECEIPT_ROUTES, ids=ROUTE_IDS)
    @pytest.mark.asyncio
    async def test_owner_succeeds_on_every_receipt_route(
        self, receipts, act_as, method, path, body, query
    ):
        act_as(USER_A)
        result = await _call(receipts, method, path.format(id="rcpt-a"), body=body, query=query)
        assert result.status_code == 200, result.body[:300]

    @pytest.mark.asyncio
    async def test_owner_can_sign_and_export_in_batch(self, receipts, act_as, store):
        act_as(USER_A)
        signed = await _call(
            receipts,
            "POST",
            "/api/v2/receipts/sign-batch",
            body={"receipt_ids": ["rcpt-a", "rcpt-b"]},
        )
        assert _json(signed)["results"] == [
            {"receipt_id": "rcpt-a", "status": "signed"},
            {"receipt_id": "rcpt-b", "status": "not_found"},
        ]
        assert store.get("rcpt-a").signature
        assert store.get("rcpt-b").signature is None

        exported = await _call(
            receipts, "POST", "/api/v2/receipts/batch-export", body={"receipt_ids": ["rcpt-a"]}
        )
        names = zipfile.ZipFile(io.BytesIO(exported.body)).namelist()
        assert sorted(names) == ["manifest.json", "receipt-rcpt-a.json"]

    @pytest.mark.asyncio
    async def test_owner_delivery_is_sent_and_recorded(self, receipts, act_as):
        act_as(USER_A)
        result = await _call(
            receipts,
            "POST",
            "/api/v2/receipts/rcpt-a/send-to-channel",
            body={"channel_type": "slack", "channel_id": "C1"},
        )
        assert result.status_code == 200
        receipts._send_to_slack.assert_awaited_once()
        assert [e["receiptId"] for e in get_receipt_delivery_history_store()] == ["rcpt-a"]


WORKSPACE_NOT_FOUND = {"error": "Workspace not found", "code": "not_found"}


class _WorkspaceStore:
    """Workspace store keyed by id; ``org_attr`` names the field holding the owning org."""

    def __init__(self, org_attr: str, owners: dict[str, str | None]) -> None:
        self._workspaces = {
            workspace_id: SimpleNamespace(
                **{org_attr: owner},
                access_token="xoxb-test",
                signing_secret="secret",
                bot_id="bot-1",
                service_url="https://smba.invalid/",
            )
            for workspace_id, owner in owners.items()
        }

    def get(self, workspace_id: str) -> Any:
        return self._workspaces.get(workspace_id)


@pytest.fixture
def connector_sends(monkeypatch) -> list[tuple[str, str]]:
    """Real Slack/Teams send paths over fake workspace stores and recording connectors."""
    sends: list[tuple[str, str]] = []
    owners = {"W-A": ORG_A, "W-B": ORG_B, "W-NULL": None}

    def _connector(kind: str):
        def build(**_kwargs):
            async def send_message(*, channel_id, **_kw):
                sends.append((kind, channel_id))
                return SimpleNamespace(timestamp="1.0", channel_id=channel_id, message_id="m-1")

            return SimpleNamespace(send_message=send_message)

        return build

    monkeypatch.setattr(
        "aragora.storage.slack_workspace_store.get_slack_workspace_store",
        lambda: _WorkspaceStore("tenant_id", owners),
    )
    monkeypatch.setattr(
        "aragora.storage.teams_workspace_store.get_teams_workspace_store",
        lambda: _WorkspaceStore("aragora_tenant_id", owners),
    )
    monkeypatch.setattr("aragora.connectors.chat.slack.SlackConnector", _connector("slack"))
    monkeypatch.setattr("aragora.connectors.chat.teams.TeamsConnector", _connector("teams"))
    return sends


@pytest.fixture
def real_senders(store, share_store) -> ReceiptsHandler:
    handler = ReceiptsHandler(MagicMock())
    handler._store = store
    handler._share_store = share_store
    return handler


def _delivery_requests(channel_type: str, workspace_id: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "/api/v2/receipts/rcpt-a/send-to-channel",
            {"channel_type": channel_type, "channel_id": "C1", "workspace_id": workspace_id},
        ),
        (
            "/api/v1/receipts/rcpt-a/deliver",
            {"channel": channel_type, "destination": "C1", "workspace_id": workspace_id},
        ),
    ]


class TestDeliveryWorkspaceOwnership:
    @pytest.mark.parametrize("channel_type", ["slack", "teams"])
    @pytest.mark.parametrize("workspace_id", ["W-B", "W-NULL", "W-missing"])
    @pytest.mark.asyncio
    async def test_other_org_workspace_answers_like_a_missing_one(
        self, real_senders, act_as, connector_sends, channel_type, workspace_id
    ):
        act_as(USER_A)
        for path, body in _delivery_requests(channel_type, workspace_id):
            result = await _call(real_senders, "POST", path, body=body)
            assert (result.status_code, _json(result)) == (404, WORKSPACE_NOT_FOUND), path

        assert connector_sends == []
        assert get_receipt_delivery_history_store() == []

    @pytest.mark.parametrize("channel_type", ["slack", "teams"])
    @pytest.mark.asyncio
    async def test_own_workspace_is_sent_and_recorded(
        self, real_senders, act_as, connector_sends, channel_type
    ):
        act_as(USER_A)
        for path, body in _delivery_requests(channel_type, "W-A"):
            result = await _call(real_senders, "POST", path, body=body)
            assert result.status_code == 200, (path, result.body[:300])

        assert connector_sends == [(channel_type, "C1"), (channel_type, "C1")]
        assert [
            (e["receiptId"], e["workspaceId"], e[DELIVERY_ORG_KEY])
            for e in get_receipt_delivery_history_store()
        ] == [("rcpt-a", "W-A", ORG_A), ("rcpt-a", "W-A", ORG_A)]
