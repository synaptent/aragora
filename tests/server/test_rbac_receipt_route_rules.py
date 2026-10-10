"""Receipt and gauntlet export RBAC route rules through the real dispatch.

The receipts handler passes the caller's auth context to its permission
checks, so a role holding the key gets 200 and a role without it 403 (never
500), with the static API token set or unset.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aragora.gauntlet.storage import GauntletStorage
from aragora.server.handlers.utils.receipt_delivery_history import (
    get_receipt_delivery_history_store,
)
from aragora.storage.receipt_store import ReceiptStore
from tests.security.test_rbac_route_rule_hygiene import DEFERRED_ROUTES
from tests.server.handlers.gauntlet.test_gauntlet_isolation import _StoredResult
from tests.server.handlers.test_receipts_isolation import _payload, _ShareStore
from tests.server.rbac_dispatch import (
    AUTH_REQUIRED_BODY,
    ORG_REQUIRED_BODY,
    STATIC_TOKEN,
    build_server,
    dispatch,
    handler_for,
    install_api_token,
    isolate_auth,
    jwt,
)

pytestmark = pytest.mark.no_auto_auth

ORG_A = "org-a-receipt-rules"
ORG_B = "org-b-receipt-rules"
GID_A = "gauntlet-20261004130000-aaaaaa"
GID_MISSING = "gauntlet-20261004130000-ffffff"
TOKEN_STATES = pytest.mark.parametrize(
    "api_token", [STATIC_TOKEN, None], ids=["token-set", "token-unset"]
)

# (method, path template, body, query) of every mapped receipt route.
RECEIPT_ROUTES = [
    ("GET", "/api/v2/receipts", None, None),
    ("GET", "/api/v2/receipts/", None, None),
    ("GET", "/api/v2/receipts/search", None, {"q": "isolation"}),
    ("GET", "/api/v2/receipts/stats", None, None),
    ("GET", "/api/v2/receipts/retention-status", None, None),
    ("GET", "/api/v2/receipts/{id}", None, None),
    ("GET", "/api/v2/receipts/{id}/formatted/slack", None, None),
    ("GET", "/api/v2/receipts/{id}/verify", None, None),
    ("POST", "/api/v2/receipts/{id}/verify", None, None),
    ("POST", "/api/v2/receipts/{id}/verify-signature", None, None),
    ("POST", "/api/v2/receipts/verify-batch", {"receipt_ids": ["rcpt-a"]}, None),
    ("POST", "/api/v2/receipts/sign-batch", {"receipt_ids": ["rcpt-a"]}, None),
    ("POST", "/api/v2/receipts/{id}/share", {"expires_in_hours": 1}, None),
    (
        "POST",
        "/api/v2/receipts/{id}/send-to-channel",
        {"channel_type": "slack", "channel_id": "C1"},
        None,
    ),
    ("POST", "/api/v1/receipts/{id}/deliver", {"channel": "slack", "destination": "C1"}, None),
    ("GET", "/api/v1/receipts/deliveries", None, None),
]
RECEIPT_IDS = [f"{m} {p}" for m, p, _b, _q in RECEIPT_ROUTES]
PER_RECEIPT_ROUTES = [r for r in RECEIPT_ROUTES if "{id}" in r[1]]


@pytest.fixture(scope="module")
def server():
    return build_server()


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    isolate_auth(monkeypatch)


@pytest.fixture
def users() -> SimpleNamespace:
    return SimpleNamespace(
        a=jwt("user-a", ORG_A, "owner"),
        a2=jwt("user-a2", ORG_A, "admin"),
        a3=jwt("user-a3", ORG_A, "member"),
        b=jwt("user-b", ORG_B, "owner"),
    )


@pytest.fixture
def receipts(server, tmp_path, monkeypatch) -> SimpleNamespace:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    store.save(_payload("rcpt-a", "subject-1"), org_id=ORG_A, created_by="user-a")
    store.save(_payload("rcpt-b", "subject-1"), org_id=ORG_B, created_by="user-b")
    shares = _ShareStore()
    handler = handler_for(server, "/api/v2/receipts")
    monkeypatch.setattr(handler, "_store", store)
    monkeypatch.setattr(handler, "_share_store", shares)
    monkeypatch.setattr(handler, "_send_to_slack", AsyncMock(return_value={"ok": True}))
    history = get_receipt_delivery_history_store()
    history.clear()
    yield SimpleNamespace(store=store, shares=shares, history=history)
    history.clear()


@pytest.fixture
def gauntlet_run(tmp_path, monkeypatch) -> None:
    storage = GauntletStorage(db_path=str(tmp_path / "gauntlet.db"))
    storage.save(_StoredResult(GID_A), org_id=ORG_A)
    monkeypatch.setattr("aragora.server.handlers.gauntlet._get_storage", lambda: storage)


def _receipt_request(server, route, auth, receipt_id="rcpt-a"):
    method, template, body, query = route
    return dispatch(server, method, template.format(id=receipt_id), auth, body=body, query=query)


class TestReceiptRoutes:
    @TOKEN_STATES
    @pytest.mark.parametrize("route", RECEIPT_ROUTES, ids=RECEIPT_IDS)
    def test_owner_gets_200(self, server, users, receipts, monkeypatch, route, api_token):
        install_api_token(monkeypatch, api_token)
        status, body = _receipt_request(server, route, users.a)

        assert status == 200, body

    @pytest.mark.parametrize("route", PER_RECEIPT_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
    def test_other_org_gets_the_missing_receipt_404(self, server, users, receipts, route):
        foreign = _receipt_request(server, route, users.b)
        missing = _receipt_request(server, route, users.b, receipt_id="rcpt-missing")

        assert foreign == missing
        assert foreign[0] == 404
        assert receipts.shares.links == {}
        assert list(receipts.history) == []

    @pytest.mark.parametrize("route", RECEIPT_ROUTES, ids=RECEIPT_IDS)
    def test_anonymous_gets_401(self, server, receipts, route):
        assert _receipt_request(server, route, None) == (401, AUTH_REQUIRED_BODY)

    @pytest.mark.parametrize("route", RECEIPT_ROUTES, ids=RECEIPT_IDS)
    def test_static_token_only_gets_403_org_required(self, server, receipts, route):
        result = _receipt_request(server, route, f"Bearer {STATIC_TOKEN}")

        assert result == (403, ORG_REQUIRED_BODY)
        assert receipts.shares.links == {}


@TOKEN_STATES
class TestReceiptsHandlerSeesTheCaller:
    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch, api_token):
        install_api_token(monkeypatch, api_token)

    @pytest.mark.parametrize(
        "route",
        [RECEIPT_ROUTES[i] for i in (0, 5, 6, 11, 12)],
        ids=["list", "read", "formatted", "sign-batch", "share"],
    )
    def test_same_org_admin_without_receipt_keys_gets_403(self, server, users, receipts, route):
        status, body = _receipt_request(server, route, users.a2)

        assert status == 403
        assert body["code"] == "permission_denied"
        assert receipts.shares.links == {}
        assert receipts.store.get("rcpt-a").signature is None


class TestDeferredRoutesStayDefaultDeny:
    @pytest.mark.parametrize(("method", "path"), DEFERRED_ROUTES)
    def test_owner_jwt_matches_no_rule(self, server, users, receipts, method, path):
        status, body = dispatch(server, method, path, users.a)

        assert status == 403
        assert (body["code"], body["required_permission"]) == ("permission_denied", None)

    def test_share_token_read_stays_401_for_anonymous_callers(self, server, receipts):
        assert dispatch(server, "GET", "/api/v2/receipts/share/tok-1") == (401, AUTH_REQUIRED_BODY)


@TOKEN_STATES
class TestGauntletExport:
    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch, api_token):
        install_api_token(monkeypatch, api_token)

    @pytest.mark.parametrize("who", ["a", "a2"], ids=["owner", "admin"])
    def test_org_owner_and_admin_export_the_run(self, server, users, gauntlet_run, who):
        status, body = dispatch(
            server, "GET", f"/api/v1/gauntlet/{GID_A}/export", getattr(users, who)
        )

        assert (status, body.get("gauntlet_id")) == (200, GID_A), body

    def test_other_org_gets_the_missing_run_404(self, server, users, gauntlet_run):
        foreign = dispatch(server, "GET", f"/api/v1/gauntlet/{GID_A}/export", users.b)
        missing = dispatch(server, "GET", f"/api/v1/gauntlet/{GID_MISSING}/export", users.b)

        assert foreign == missing
        assert foreign[0] == 404

    def test_same_org_role_without_export_key_gets_403(self, server, users, gauntlet_run):
        status, _ = dispatch(server, "GET", f"/api/v1/gauntlet/{GID_A}/export", users.a3)

        assert status == 403

    def test_anonymous_gets_401(self, server, gauntlet_run):
        assert dispatch(server, "GET", f"/api/v1/gauntlet/{GID_A}/export")[0] == 401

    def test_static_token_only_is_refused(self, server, gauntlet_run, api_token):
        result = dispatch(
            server, "GET", f"/api/v1/gauntlet/{GID_A}/export", f"Bearer {STATIC_TOKEN}"
        )

        # Unconfigured, the static token is just an unknown bearer.
        expected = (403, ORG_REQUIRED_BODY) if api_token else (401, AUTH_REQUIRED_BODY)
        assert result == expected
