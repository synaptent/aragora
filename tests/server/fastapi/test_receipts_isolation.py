"""Org isolation of the FastAPI v2 receipt and gauntlet routes.

Two orgs (real JWTs) and an anonymous caller exercise every route against a
real SQLite receipt store and gauntlet store holding records of org A, org B
and records with no owner:

* another org's record answers exactly like a missing one (same 404 body),
  and sharing or sending it has no side effect;
* lists, search, stats and batch operations only see the caller org's
  receipts; an unowned receipt is seen by nobody;
* anonymous callers get 401, except on the public share-token view;
* the owner keeps full access.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.export.decision_receipt import DecisionReceipt
from aragora.gauntlet.storage import GauntletStorage
from aragora.server.fastapi import create_app
from aragora.server.handlers.gauntlet.storage import get_gauntlet_runs
from aragora.server.handlers.utils.receipt_delivery_history import (
    DELIVERY_ORG_KEY,
    get_receipt_delivery_history_store,
)
from aragora.storage.receipt_store import ReceiptStore

ORG_A = "org-a"
ORG_B = "org-b"
RECEIPT_NOT_FOUND = {"error": "Receipt not found", "code": "not_found"}
ORG_REQUIRED_BODY = {
    "error": "This resource belongs to an organization; sign in as a member of one",
    "code": "org_required",
}
RUN_NOT_FOUND = {"error": "Gauntlet run not found", "code": "not_found"}

GID_A = "gauntlet-20261004130000-aaaaaa"
GID_B = "gauntlet-20261004130000-bbbbbb"
GID_NULL = "gauntlet-20261004130000-000000"
GID_LIVE_A = "gauntlet-20261004130100-cccccc"
GID_INFLIGHT_A = "gauntlet-20261004130200-dddddd"
GID_MISSING = "gauntlet-20261004130000-ffffff"


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


class _StoredResult:
    """The attributes ``GauntletStorage.save`` reads from a gauntlet result."""

    def __init__(self, gauntlet_id: str) -> None:
        self.gauntlet_id = gauntlet_id
        self.input_summary = f"isolation probe {gauntlet_id}"
        self.input_hash = f"hash-{gauntlet_id}"
        self.verdict = "pass"
        self.confidence = 0.9
        self.robustness_score = 0.8
        self.total_findings = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "gauntlet_id": self.gauntlet_id,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "findings": [
                {
                    "id": f"f-{self.gauntlet_id[-6:]}",
                    "category": "security",
                    "severity": "HIGH",
                    "title": f"sentinel finding {self.gauntlet_id}",
                    "description": "sentinel",
                }
            ],
        }


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
    runs = get_gauntlet_runs()
    history.clear()
    runs.clear()
    yield
    history.clear()
    runs.clear()


def _bearer(user_id: str, org_id: str | None, role: str = "owner") -> dict[str, str]:
    from aragora.billing.auth.tokens import create_access_token

    # Only the owner role is granted receipts:share, which the share and send routes require.
    token = create_access_token(user_id, f"{user_id}@example.test", org_id, role)
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
def gauntlet_storage(tmp_path) -> GauntletStorage:
    storage = GauntletStorage(db_path=str(tmp_path / "gauntlet.db"))
    storage.save(_StoredResult(GID_A), org_id=ORG_A)
    storage.save(_StoredResult(GID_B), org_id=ORG_B)
    storage.save(_StoredResult(GID_NULL))
    storage.save_inflight(
        gauntlet_id=GID_INFLIGHT_A,
        status="running",
        input_type="spec",
        input_summary="inflight probe",
        input_hash="hash-inflight",
        persona=None,
        profile="default",
        agents=["demo"],
        org_id=ORG_A,
    )
    get_gauntlet_runs()[GID_LIVE_A] = {
        "gauntlet_id": GID_LIVE_A,
        "status": "completed",
        "input_type": "spec",
        "input_summary": "in-memory probe",
        "org_id": ORG_A,
        "created_by": "user-a",
        "result": _StoredResult(GID_LIVE_A).to_dict(),
    }
    return storage


@pytest.fixture
def client(receipt_store, share_store, gauntlet_storage, fastapi_context_builder):
    app = create_app()
    app.state.context = fastapi_context_builder(
        receipt_store=receipt_store,
        receipt_share_store=share_store,
        gauntlet_storage=gauntlet_storage,
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
    ("POST", "/api/v2/gauntlet/run", {"input_content": "probe"}),
    ("GET", f"/api/v2/gauntlet/{GID_A}/status", None),
    ("GET", f"/api/v2/gauntlet/{GID_A}/findings", None),
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


class TestCallerWithoutOrg:
    # viewer holds neither receipts:share nor gauntlet:run; member holds only gauntlet:run.
    @pytest.mark.parametrize("role", ["viewer", "member", "owner"])
    @pytest.mark.parametrize(("method", "path", "body"), _ALL_SCOPED_ROUTES)
    def test_every_scoped_route_answers_403_org_required(
        self, client, share_store, method, path, body, role
    ):
        response = client.request(method, path, json=body, headers=_bearer("user-n", None, role))

        assert (response.status_code, response.json()) == (403, ORG_REQUIRED_BODY)
        assert share_store.links == {}
        assert get_receipt_delivery_history_store() == []
        assert list(get_gauntlet_runs()) == [GID_LIVE_A]

    def test_org_member_without_receipts_share_is_still_refused(self, client, share_store):
        response = client.post(
            "/api/v2/receipts/rcpt-a/share", json={}, headers=_bearer("user-a3", ORG_A, "member")
        )

        assert response.status_code == 403
        assert "org_required" not in response.text
        assert share_store.links == {}


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

    @pytest.mark.parametrize("gauntlet_id", [GID_A, GID_LIVE_A, GID_INFLIGHT_A, GID_NULL])
    @pytest.mark.parametrize("suffix", ["status", "findings"])
    def test_gauntlet_runs_answer_like_a_missing_run(self, client, as_b, gauntlet_id, suffix):
        hidden = client.get(f"/api/v2/gauntlet/{gauntlet_id}/{suffix}", headers=as_b)
        missing = client.get(f"/api/v2/gauntlet/{GID_MISSING}/{suffix}", headers=as_b)

        assert (hidden.status_code, hidden.json()) == (404, RUN_NOT_FOUND)
        assert (missing.status_code, missing.json()) == (404, RUN_NOT_FOUND)


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

    @pytest.mark.parametrize("gauntlet_id", [GID_A, GID_LIVE_A, GID_INFLIGHT_A])
    def test_gauntlet_status_succeeds(self, client, as_a, gauntlet_id):
        response = client.get(f"/api/v2/gauntlet/{gauntlet_id}/status", headers=as_a)

        assert response.status_code == 200
        assert response.json()["gauntlet_id"] == gauntlet_id

    @pytest.mark.parametrize("gauntlet_id", [GID_A, GID_LIVE_A])
    def test_gauntlet_findings_succeed(self, client, as_a, gauntlet_id):
        response = client.get(f"/api/v2/gauntlet/{gauntlet_id}/findings", headers=as_a)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_gauntlet_findings_accept_numeric_severity_scores(self, client, as_a):
        get_gauntlet_runs()[GID_LIVE_A]["result"]["findings"] = [
            {
                "id": "f-numeric",
                "category": "probe",
                "severity": 0.5,
                "severity_level": "MEDIUM",
                "title": "Probe: sycophancy",
                "description": "sentinel",
            }
        ]

        response = client.get(
            f"/api/v2/gauntlet/{GID_LIVE_A}/findings?severity=medium", headers=as_a
        )

        assert response.status_code == 200
        assert [(f["severity"], f["severity_level"]) for f in response.json()["findings"]] == [
            ("0.5", "MEDIUM")
        ]

    def test_started_run_belongs_to_the_caller(self, client, as_a, as_b, gauntlet_storage):
        response = client.post(
            "/api/v2/gauntlet/run", json={"input_content": "ownership probe"}, headers=as_a
        )

        assert response.status_code == 202
        gauntlet_id = response.json()["gauntlet_id"]
        run = get_gauntlet_runs()[gauntlet_id]
        assert (run["org_id"], run["created_by"]) == (ORG_A, "user-a")
        assert gauntlet_storage.get_inflight(gauntlet_id).org_id == ORG_A
        hidden = client.get(f"/api/v2/gauntlet/{gauntlet_id}/status", headers=as_b)
        assert (hidden.status_code, hidden.json()) == (404, RUN_NOT_FOUND)


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


class TestDeliveryWorkspaceOwnership:
    @pytest.mark.parametrize("channel_type", ["slack", "teams"])
    @pytest.mark.parametrize("workspace_id", ["W-B", "W-NULL", "W-missing"])
    def test_other_org_workspace_answers_like_a_missing_one(
        self, client, as_a, connector_sends, channel_type, workspace_id
    ):
        response = client.post(
            "/api/v2/receipts/rcpt-a/send-to-channel",
            json={"channel_type": channel_type, "channel_id": "C1", "workspace_id": workspace_id},
            headers=as_a,
        )

        assert (response.status_code, response.json()) == (404, WORKSPACE_NOT_FOUND)
        assert connector_sends == []
        assert get_receipt_delivery_history_store() == []

    @pytest.mark.parametrize("channel_type", ["slack", "teams"])
    def test_own_workspace_is_sent_and_recorded(self, client, as_a, connector_sends, channel_type):
        response = client.post(
            "/api/v2/receipts/rcpt-a/send-to-channel",
            json={"channel_type": channel_type, "channel_id": "C1", "workspace_id": "W-A"},
            headers=as_a,
        )

        assert response.status_code == 200, response.text[:300]
        assert connector_sends == [(channel_type, "C1")]
        assert [
            (e["receiptId"], e["workspaceId"], e[DELIVERY_ORG_KEY])
            for e in get_receipt_delivery_history_store()
        ] == [("rcpt-a", "W-A", ORG_A)]
