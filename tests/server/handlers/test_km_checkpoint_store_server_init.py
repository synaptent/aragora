"""KM checkpoint routes served from the server's KnowledgeMound, without store injection.

Every test builds handlers through the real ``HandlerRegistryMixin._init_handlers``
(server context taken from the server class's ``knowledge_mound``) and dispatches
through ``_try_modular_handler`` with real RBAC and an unmodified ``UserAuthContext``.
Nothing patches ``KMCheckpointHandler._get_checkpoint_store`` or
``get_km_checkpoint_store``; the only patches are request authentication, the org
tier lookup, the registry subset, the route index and a spy on store restores.
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.knowledge.mound import KnowledgeMound
from aragora.knowledge.mound import checkpoint as checkpoint_module
from aragora.knowledge.mound.checkpoint import (
    KMCheckpointStore,
    get_km_checkpoint_store,
    reset_km_checkpoint_store,
)
from aragora.knowledge.mound.types import IngestionRequest, MoundBackend, MoundConfig
from aragora.server.handler_registry import HandlerRegistryMixin
from aragora.server.handler_registry.core import RouteIndex
from aragora.server.handlers.knowledge.checkpoints import KMCheckpointHandler
from aragora.server.handlers.knowledge_base.mound.handler import KnowledgeMoundHandler

pytestmark = pytest.mark.no_auto_auth

WORKSPACE = "kmcp-server-ws"
COLLECTION = "/api/v1/km/checkpoints"
ORG, OTHER_ORG = "org-km", "org-other"

# Real registry order: the checkpoint handler precedes the mound handler.
_REGISTRY = [
    ("_km_checkpoint_handler", KMCheckpointHandler),
    ("_knowledge_mound_handler", KnowledgeMoundHandler),
]


def _user(role: str, *, org: str | None = ORG, authenticated: bool = True) -> UserAuthContext:
    return UserAuthContext(
        authenticated=authenticated,
        user_id=f"{role}-{org}",
        email=f"{role}@example.com",
        org_id=org,
        role=role,
        token_type="access",
    )


@pytest.fixture
def server_mound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[KnowledgeMound]:
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path / "data"))
    reset_km_checkpoint_store()
    mound = KnowledgeMound(  # type: ignore[abstract]
        config=MoundConfig(
            backend=MoundBackend.SQLITE,
            sqlite_path=str(tmp_path / "mound.db"),
            enable_staleness_detection=False,
            enable_culture_accumulator=False,
        ),
        workspace_id=WORKSPACE,
    )
    asyncio.run(mound.initialize())
    yield mound
    reset_km_checkpoint_store()
    asyncio.run(mound.close())


def _server_class(mound: KnowledgeMound | None) -> Any:
    return type(
        "_KMCheckpointServer",
        (HandlerRegistryMixin,),
        {"_handlers_initialized": False, "knowledge_mound": mound},
    )


class _Server:
    """One server class (handlers initialized once) plus its route index."""

    def __init__(self, mound: KnowledgeMound | None) -> None:
        self.cls = _server_class(mound)
        self.index = RouteIndex()

    def request(
        self,
        method: str,
        path: str,
        user: UserAuthContext,
        body: dict[str, Any] | None = None,
        tier: str = "professional",
    ) -> tuple[bool, int | None, Any]:
        instance: Any = self.cls()
        raw = json.dumps(body).encode() if body is not None else b""
        instance.command = method
        instance.path = path
        instance.headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
        instance.rfile = io.BytesIO(raw)
        instance.wfile = io.BytesIO()
        for name in (
            "send_response",
            "send_header",
            "end_headers",
            "_add_cors_headers",
            "_add_security_headers",
            "_add_trace_headers",
        ):
            setattr(instance, name, MagicMock())
        instance._auth_context = None
        instance.client_address = ("127.0.0.1", 12345)
        with (
            patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
            patch("aragora.server.handler_registry.HANDLER_REGISTRY", _REGISTRY),
            patch("aragora.server.handler_registry.get_route_index", return_value=self.index),
            patch(
                "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
                return_value=False,
            ),
            patch("aragora.billing.jwt_auth.extract_user_from_request", return_value=user),
            patch("aragora.billing.tier_gating._resolve_org_tier", return_value=tier),
        ):
            handled = instance._try_modular_handler(path, {})
        status = None
        if instance.send_response.call_args is not None:
            status = instance.send_response.call_args[0][0]
        payload = instance.wfile.getvalue()
        return handled, status, json.loads(payload) if payload else None


def _checkpoint_names(body: dict[str, Any]) -> list[str]:
    return [cp["name"] for cp in body["data"]["checkpoints"]]


class TestServerMoundBacksCheckpointStore:
    @pytest.mark.parametrize("path", [COLLECTION, "/api/km/checkpoints"])
    def test_list_returns_200_without_store_injection(
        self, server_mound: KnowledgeMound, path: str
    ) -> None:
        server = _Server(server_mound)
        handled, status, body = server.request("GET", path, _user("member"))
        assert handled is True
        assert status == 200, body
        assert body["data"] == {"checkpoints": [], "total": 0}

    def test_create_then_list_round_trip_uses_server_mound(
        self, server_mound: KnowledgeMound, tmp_path: Path
    ) -> None:
        asyncio.run(
            server_mound.store(
                IngestionRequest(content="Checkpoint round-trip fact", workspace_id=WORKSPACE)
            )
        )
        server = _Server(server_mound)

        # Create needs knowledge.write in the RBAC v2 role set, which only owner holds.
        handled, status, created = server.request(
            "POST",
            COLLECTION,
            _user("owner"),
            body={"name": "cp-roundtrip", "description": "round trip", "tags": ["t1"]},
        )
        assert handled is True
        assert status == 201, created
        assert created["name"] == "cp-roundtrip"
        assert created["node_count"] == 1

        _, list_status, listed = server.request("GET", COLLECTION, _user("member"))
        assert list_status == 200, listed
        assert _checkpoint_names(listed) == ["cp-roundtrip"]

        # Detail paths address a checkpoint by its id; the store keys entries by id.
        checkpoint_id = created["id"]
        _, detail_status, detail = server.request(
            "GET", f"{COLLECTION}/{checkpoint_id}", _user("member")
        )
        assert detail_status == 200, detail

        store = get_km_checkpoint_store()
        assert store is not None
        assert store.mound is server_mound
        assert store.checkpoint_dir == tmp_path / "data" / "km_checkpoints"
        metadata = json.loads((store.checkpoint_dir / checkpoint_id / "metadata.json").read_text())
        assert metadata["org_id"] == ORG

    def test_store_is_created_on_first_request_not_at_handler_init(
        self, server_mound: KnowledgeMound
    ) -> None:
        server = _Server(server_mound)
        with (
            patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
            patch("aragora.server.handler_registry.HANDLER_REGISTRY", _REGISTRY),
            patch("aragora.server.handler_registry.get_route_index", return_value=server.index),
        ):
            server.cls._init_handlers()
        assert server.cls._km_checkpoint_handler.ctx["knowledge_mound"] is server_mound
        assert get_km_checkpoint_store() is None

        _, status, body = server.request("GET", COLLECTION, _user("member"))
        assert status == 200, body
        assert get_km_checkpoint_store() is not None


class TestGatesPreservedWithoutInjection:
    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_free_tier_org_denied_before_store_creation(
        self, server_mound: KnowledgeMound, method: str
    ) -> None:
        server = _Server(server_mound)
        _, status, body = server.request(
            method, COLLECTION, _user("admin"), body={"name": "cp-free"}, tier="free"
        )
        assert status == 403, body
        assert (body["code"], body["required_tier"]) == ("tier_insufficient", "professional")
        assert get_km_checkpoint_store() is None

    # The decorator matrix grants admin knowledge.write; the RBAC v2 role set does not.
    @pytest.mark.parametrize("role", ["member", "admin"])
    def test_only_owner_can_create(self, server_mound: KnowledgeMound, role: str) -> None:
        server = _Server(server_mound)
        _, status, body = server.request("POST", COLLECTION, _user(role), body={"name": "cp-x"})
        assert status == 403, body

        _, list_status, listed = server.request("GET", COLLECTION, _user("member"))
        assert list_status == 200, listed
        assert _checkpoint_names(listed) == []

    def test_unauthenticated_list_gets_401(self, server_mound: KnowledgeMound) -> None:
        server = _Server(server_mound)
        _, status, body = server.request("GET", COLLECTION, _user("anon", authenticated=False))
        assert status == 401, body
        assert get_km_checkpoint_store() is None

    def test_no_server_mound_stays_503(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path / "data"))
        reset_km_checkpoint_store()
        server = _Server(None)
        _, status, body = server.request("GET", COLLECTION, _user("member"))
        assert status == 503, body
        assert get_km_checkpoint_store() is None


@pytest.fixture
def two_orgs(server_mound: KnowledgeMound) -> tuple[_Server, KMCheckpointStore, dict[str, Any]]:
    """Checkpoints created over HTTP by owners of two orgs, plus a legacy one with no org."""
    asyncio.run(server_mound.store(IngestionRequest(content="Shared fact", workspace_id=WORKSPACE)))
    server, ids = _Server(server_mound), {}
    for key, org in (("own", ORG), ("foreign", OTHER_ORG)):
        _, status, body = server.request(
            "POST", COLLECTION, _user("owner", org=org), body={"name": f"cp-{key}"}
        )
        assert status == 201, body
        ids[key] = body["id"]
    store = get_km_checkpoint_store()
    assert store is not None
    ids["legacy"] = asyncio.run(store.create_checkpoint(name="cp-legacy"))
    return server, store, ids


def _state(store: KMCheckpointStore) -> tuple[dict[Path, bytes], list[dict[str, Any]]]:
    files = {p: p.read_bytes() for p in store.checkpoint_dir.rglob("*") if p.is_file()}
    return files, asyncio.run(store._export_nodes(False, None))


class TestTenantIsolation:
    def test_list_shows_only_the_callers_org(self, two_orgs: Any) -> None:
        server, _, _ = two_orgs
        for org, names in ((ORG, ["cp-own"]), (OTHER_ORG, ["cp-foreign"]), (None, [])):
            _, status, body = server.request("GET", COLLECTION, _user("member", org=org))
            assert status == 200 and _checkpoint_names(body) == names, (org, body)

    @pytest.mark.parametrize("key", ["foreign", "legacy"])
    def test_foreign_and_legacy_checkpoints_are_404_and_untouched(
        self, two_orgs: Any, key: str
    ) -> None:
        server, store, ids = two_orgs
        before, cid = _state(store), ids[key]
        with patch.object(KMCheckpointStore, "restore_checkpoint") as restore:
            for method, path, body in (
                ("GET", f"{COLLECTION}/{cid}", None),
                ("GET", f"{COLLECTION}/{cid}/compare", None),
                (
                    "POST",
                    f"{COLLECTION}/compare",
                    {"checkpoint_a": ids["own"], "checkpoint_b": cid},
                ),
                ("DELETE", f"{COLLECTION}/{cid}", None),
                ("POST", f"{COLLECTION}/{cid}/restore", {"strategy": "replace"}),
            ):
                _, status, resp = server.request(method, path, _user("owner"), body=body)
                assert status == 404, (method, path, resp)
        assert _state(store) == before and not restore.called

    @pytest.mark.parametrize("strategy", ["merge", "replace"])
    def test_own_restore_is_refused_before_any_write(self, two_orgs: Any, strategy: str) -> None:
        server, store, ids = two_orgs
        before, path = _state(store), f"{COLLECTION}/{ids['own']}/restore"
        with patch.object(KMCheckpointStore, "restore_checkpoint") as restore:
            _, status, body = server.request(
                "POST", path, _user("owner"), body={"strategy": strategy}
            )
        assert status == 501 and body["error"]["code"] == "not_implemented", body
        assert _state(store) == before and not restore.called

    def test_own_checkpoint_compares_and_deletes_within_the_org(self, two_orgs: Any) -> None:
        server, store, ids = two_orgs
        own = ids["own"]
        _, status, body = server.request("GET", f"{COLLECTION}/{own}/compare", _user("member"))
        assert status == 200 and body["data"]["message"].startswith("Only one checkpoint"), body
        pair = {"checkpoint_a": own, "checkpoint_b": own}
        assert server.request("POST", f"{COLLECTION}/compare", _user("owner"), body=pair)[1] == 200
        assert server.request("DELETE", f"{COLLECTION}/{own}", _user("owner"))[1] == 200
        assert {p.name for p in store.checkpoint_dir.iterdir()} == {ids["foreign"], ids["legacy"]}

    def test_create_without_an_org_is_refused(self, two_orgs: Any) -> None:
        server, store, _ = two_orgs
        before = _state(store)
        _, status, body = server.request(
            "POST", COLLECTION, _user("owner", org=None), body={"name": "cp-none"}
        )
        assert status == 403, body
        assert _state(store) == before

    def test_prune_keeps_other_orgs_and_legacy(
        self, server_mound: KnowledgeMound, tmp_path: Path
    ) -> None:
        store = KMCheckpointStore(server_mound, str(tmp_path / "prune"), max_checkpoints=1)
        kept = [asyncio.run(store.create_checkpoint(org_id=org)) for org in (OTHER_ORG, None, ORG)]
        newest = asyncio.run(store.create_checkpoint(org_id=ORG))
        listed = {cp.id for cp in asyncio.run(store.list_checkpoints())}
        assert listed == {kept[0], kept[1], newest}


class TestGlobalCheckpointCeiling:
    """Total stored checkpoints, legacy ones included, stay at or below the store ceiling."""

    def test_default_ceiling_bounds_every_org_together(
        self, server_mound: KnowledgeMound, tmp_path: Path
    ) -> None:
        store = KMCheckpointStore(server_mound, str(tmp_path / "default"))
        assert store.max_total_checkpoints == 100
        assert store.max_checkpoints <= store.max_total_checkpoints

    @pytest.mark.parametrize("org", [ORG, "org-new"])
    def test_create_over_the_ceiling_is_refused_before_any_write(
        self, server_mound: KnowledgeMound, tmp_path: Path, org: str
    ) -> None:
        store = KMCheckpointStore(
            server_mound, str(tmp_path / "ceiling"), max_checkpoints=5, max_total_checkpoints=2
        )
        # The legacy checkpoint is counted, not owned: without it this create would fit.
        for existing in (OTHER_ORG, None):
            asyncio.run(store.create_checkpoint(org_id=existing))
        before = _state(store)
        with pytest.raises(checkpoint_module.CheckpointCapacityError):
            asyncio.run(store.create_checkpoint(name="cp-over", org_id=org))
        assert _state(store) == before

    def test_org_at_its_cap_still_rotates_at_the_ceiling(
        self, server_mound: KnowledgeMound, tmp_path: Path
    ) -> None:
        store = KMCheckpointStore(
            server_mound, str(tmp_path / "rotate"), max_checkpoints=1, max_total_checkpoints=3
        )
        kept = [asyncio.run(store.create_checkpoint(org_id=org)) for org in (OTHER_ORG, None)]
        asyncio.run(store.create_checkpoint(org_id=ORG))
        newest = asyncio.run(store.create_checkpoint(org_id=ORG))
        listed = {cp.id for cp in asyncio.run(store.list_checkpoints())}
        assert listed == {kept[0], kept[1], newest}

    @pytest.mark.parametrize("org", [ORG, "org-new"])
    def test_http_create_over_the_ceiling_gets_507(self, two_orgs: Any, org: str) -> None:
        server, store, _ = two_orgs
        store.max_total_checkpoints = 3
        before = _state(store)
        _, status, body = server.request(
            "POST", COLLECTION, _user("owner", org=org), body={"name": "cp-over"}
        )
        assert status == 507, body
        assert body["error"]["code"] == "checkpoint_storage_full", body
        # Other organizations' checkpoint counts are not disclosed.
        assert not any(ch.isdigit() for ch in body["error"]["message"]), body
        assert _state(store) == before
