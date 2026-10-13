"""Org isolation of the FastAPI v2 receipt routes.

Two orgs (real JWTs) and an anonymous caller exercise every route against a
real SQLite receipt store holding receipts of org A, org B and receipts with
no owner:

* another org's record answers exactly like a missing one (same 404 body),
  and sharing or sending it has no side effect;
* lists, search, stats and batch operations only see the caller org's
  receipts; an unowned receipt is seen by nobody;
* anonymous callers get 401, except on the public share-token view;
* the owner keeps full access.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.export.decision_receipt import DecisionReceipt
from aragora.server.fastapi import create_app
from aragora.server.handlers.utils.receipt_delivery_history import (
    DELIVERY_ORG_KEY,
    get_receipt_delivery_history_store,
)
from aragora.storage.receipt_store import ReceiptStore

ORG_A = "org-a"
ORG_B = "org-b"
RECEIPT_NOT_FOUND = {"error": "Receipt not found", "code": "not_found"}


def _receipt_payload(receipt_id: str) -> dict[str, Any]:
    return DecisionReceipt(
        receipt_id=receipt_id,
        gauntlet_id=f"g-{receipt_id}",
        verdict="PASS",
        confidence=0.9,
        risk_level="LOW",
        input_summary=f"isolation probe {receipt_id}",
        agents_involved=["claude", "codex"],
    ).to_dict()


class _ShareStore:
    """In-memory share-link store with the methods the routes call."""

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


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.server import auth as server_auth

    for name in (
        "ARAGORA_ENV",
        "ARAGORA_ENVIRONMENT",
        "ARAGORA_SECRETS_STRICT",
        "ARAGORA_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "fastapi-receipt-isolation-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)


@pytest.fixture(autouse=True)
def _clean_shared_state():
    history = get_receipt_delivery_history_store()
    history.clear()
    yield
    history.clear()


def _bearer(user_id: str, org_id: str) -> dict[str, str]:
    from aragora.billing.auth.tokens import create_access_token

    # Only the owner role is granted receipts:share, which the share and send routes require.
    token = create_access_token(user_id, f"{user_id}@example.test", org_id, "owner")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def as_a() -> dict[str, str]:
    return _bearer("user-a", ORG_A)


@pytest.fixture
def as_b() -> dict[str, str]:
    return _bearer("user-b", ORG_B)


@pytest.fixture
def receipt_store(tmp_path) -> ReceiptStore:
    store = ReceiptStore(db_path=tmp_path / "receipts.db", file_receipt_dirs=[])
    store.save(_receipt_payload("rcpt-a"), org_id=ORG_A, created_by="user-a")
    store.save(_receipt_payload("rcpt-b"), org_id=ORG_B, created_by="user-b")
    store.save(_receipt_payload("rcpt-null"))
    return store


@pytest.fixture
def share_store() -> _ShareStore:
    return _ShareStore()


@pytest.fixture
def client(receipt_store, share_store, fastapi_context_builder):
    app = create_app()
    app.state.context = fastapi_context_builder(
        receipt_store=receipt_store,
        receipt_share_store=share_store,
    )
    # Not entered as a context manager: the app's startup would replace this context.
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    test_client.close()


def _ids(response) -> list[str]:
    return sorted(receipt["receipt_id"] for receipt in response.json()["receipts"])


_PER_ID_READS = [
    ("GET", "/api/v2/receipts/{id}"),
    ("GET", "/api/v2/receipts/{id}/verify"),
    ("POST", "/api/v2/receipts/{id}/verify"),
    ("GET", "/api/v2/receipts/{id}/export"),
    ("GET", "/api/v2/receipts/{id}/export?format=markdown&raw=true"),
    ("GET", "/api/v2/receipts/{id}/formatted/slack"),
    ("POST", "/api/v2/receipts/{id}/verify-signature"),
]

_ALL_SCOPED_ROUTES = [
    ("GET", "/api/v2/receipts", None),
    ("GET", "/api/v2/receipts/search?q=probe", None),
    ("GET", "/api/v2/receipts/stats", None),
    ("POST", "/api/v2/receipts/batch-verify", {"receipt_ids": ["rcpt-a"]}),
    ("POST", "/api/v2/receipts/batch-export", {"receipt_ids": ["rcpt-a"], "raw": False}),
    *[(method, path.format(id="rcpt-a"), None) for method, path in _PER_ID_READS],
    ("POST", "/api/v2/receipts/rcpt-a/share", {}),
    (
        "POST",
        "/api/v2/receipts/rcpt-a/send-to-channel",
        {"channel_type": "slack", "channel_id": "C1"},
    ),
]


class TestAnonymous:
    @pytest.mark.parametrize(("method", "path", "body"), _ALL_SCOPED_ROUTES)
    def test_every_scoped_route_answers_401(self, client, share_store, method, path, body):
        response = client.request(method, path, json=body)

        assert response.status_code == 401
        assert share_store.links == {}
        assert get_receipt_delivery_history_store() == []

    def test_share_token_view_stays_public(self, client, as_a):
        token = client.post("/api/v2/receipts/rcpt-a/share", json={}, headers=as_a).json()["token"]

        response = client.get(f"/api/v2/receipts/share/{token}")

        assert response.status_code == 200
        assert response.json()["receipt"]["receipt_id"] == "rcpt-a"


class TestOtherOrg:
    @pytest.mark.parametrize(("method", "path"), _PER_ID_READS)
    @pytest.mark.parametrize("receipt_id", ["rcpt-a", "rcpt-null"])
    def test_per_id_routes_answer_like_a_missing_receipt(
        self, client, as_b, method, path, receipt_id
    ):
        hidden = client.request(method, path.format(id=receipt_id), headers=as_b)
        missing = client.request(method, path.format(id="rcpt-missing"), headers=as_b)

        assert (hidden.status_code, hidden.json()) == (404, RECEIPT_NOT_FOUND)
        assert (missing.status_code, missing.json()) == (404, RECEIPT_NOT_FOUND)

    def test_list_search_and_stats_only_count_own_receipts(self, client, as_b):
        assert _ids(client.get("/api/v2/receipts", headers=as_b)) == ["rcpt-b"]
        assert client.get("/api/v2/receipts", headers=as_b).json()["total"] == 1
        search = client.get("/api/v2/receipts/search?q=probe", headers=as_b)
        assert (_ids(search), search.json()["total"]) == (["rcpt-b"], 1)
        assert client.get("/api/v2/receipts/stats", headers=as_b).json()["total"] == 1

    @pytest.mark.parametrize("receipt_id", ["rcpt-a", "rcpt-null"])
    def test_batch_routes_report_hidden_receipts_as_not_found(self, client, as_b, receipt_id):
        verify = client.post(
            "/api/v2/receipts/batch-verify", json={"receipt_ids": [receipt_id]}, headers=as_b
        )
        export = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": [receipt_id], "raw": False},
            headers=as_b,
        )

        assert verify.json()["results"][0]["error"] == "Receipt not found"
        assert export.json()["exported_count"] == 0
        assert export.json()["failed_ids"] == [receipt_id]

    @pytest.mark.parametrize("receipt_id", ["rcpt-a", "rcpt-null"])
    def test_share_has_no_side_effect(self, client, as_b, share_store, receipt_id):
        response = client.post(f"/api/v2/receipts/{receipt_id}/share", json={}, headers=as_b)

        assert (response.status_code, response.json()) == (404, RECEIPT_NOT_FOUND)
        assert share_store.links == {}

    @pytest.mark.parametrize("receipt_id", ["rcpt-a", "rcpt-null"])
    def test_send_has_no_side_effect(self, client, as_b, receipt_id):
        send = AsyncMock(return_value={"channel": "C1"})
        with patch(
            "aragora.server.handlers.decisions.receipts.ReceiptsHandler._send_to_slack", send
        ):
            response = client.post(
                f"/api/v2/receipts/{receipt_id}/send-to-channel",
                json={"channel_type": "slack", "channel_id": "C1"},
                headers=as_b,
            )

        assert (response.status_code, response.json()) == (404, RECEIPT_NOT_FOUND)
        send.assert_not_called()
        assert get_receipt_delivery_history_store() == []

    def test_stats_ignore_other_org_and_unowned_deliveries(self, client, as_a):
        get_receipt_delivery_history_store().extend(
            [
                {"receiptId": "rcpt-a", "status": "success", DELIVERY_ORG_KEY: ORG_A},
                {"receiptId": "rcpt-b", "status": "failed", DELIVERY_ORG_KEY: ORG_B},
                {"receiptId": "rcpt-null", "status": "failed"},
            ]
        )

        stats = client.get("/api/v2/receipts/stats", headers=as_a).json()

        assert (stats["delivered"], stats["failed"], stats["pending"]) == (1, 0, 0)


class TestOwner:
    @pytest.mark.parametrize(("method", "path"), _PER_ID_READS)
    def test_per_id_routes_succeed(self, client, as_a, method, path):
        response = client.request(method, path.format(id="rcpt-a"), headers=as_a)

        assert response.status_code == 200

    def test_receipt_detail_names_debate_agents(self, client, as_a, receipt_store):
        payload = _receipt_payload("rcpt-a-debate")
        payload["agents_involved"] = [
            {
                "name": "proposer-1",
                "model": "gpt-5.5",
                "provider": "openai-api",
                "role": "proposer",
            },
            {"name": "critic-1", "model": "haiku", "provider": "openai-api", "role": "critic"},
        ]
        receipt_store.save(payload, org_id=ORG_A, created_by="user-a")

        response = client.get("/api/v2/receipts/rcpt-a-debate", headers=as_a)

        assert response.status_code == 200
        assert response.json()["agents_involved"] == ["proposer-1", "critic-1"]

    def test_lists_show_own_receipts_only(self, client, as_a):
        assert _ids(client.get("/api/v2/receipts", headers=as_a)) == ["rcpt-a"]
        assert _ids(client.get("/api/v2/receipts/search?q=probe", headers=as_a)) == ["rcpt-a"]
        assert client.get("/api/v2/receipts/stats", headers=as_a).json()["total"] == 1

    def test_batch_routes_include_own_receipt(self, client, as_a):
        verify = client.post(
            "/api/v2/receipts/batch-verify", json={"receipt_ids": ["rcpt-a"]}, headers=as_a
        )
        export = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt-a"], "raw": False},
            headers=as_a,
        )

        assert verify.status_code == 200
        assert verify.json()["results"][0]["error"] != "Receipt not found"
        assert (export.json()["exported_count"], export.json()["failed_ids"]) == (1, [])

    def test_share_creates_a_link(self, client, as_a, share_store):
        response = client.post("/api/v2/receipts/rcpt-a/share", json={}, headers=as_a)

        assert response.status_code == 200
        assert [link["receipt_id"] for link in share_store.links.values()] == ["rcpt-a"]

    def test_send_records_the_owning_org(self, client, as_a):
        with patch(
            "aragora.server.handlers.decisions.receipts.ReceiptsHandler._send_to_slack",
            AsyncMock(return_value={"channel": "C1"}),
        ):
            response = client.post(
                "/api/v2/receipts/rcpt-a/send-to-channel",
                json={"channel_type": "slack", "channel_id": "C1"},
                headers=as_a,
            )

        assert response.status_code == 200
        assert [entry[DELIVERY_ORG_KEY] for entry in get_receipt_delivery_history_store()] == [
            ORG_A
        ]
