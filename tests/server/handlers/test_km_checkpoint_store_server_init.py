"""KM checkpoint routes served from the server's KnowledgeMound, without store injection.

Every test builds handlers through the real ``HandlerRegistryMixin._init_handlers``
(server context taken from the server class's ``knowledge_mound``) and dispatches
through ``_try_modular_handler`` with real RBAC. Nothing patches
``KMCheckpointHandler._get_checkpoint_store`` or ``get_km_checkpoint_store``; the
only patches are request authentication, the org tier lookup, the registry subset
and the route index.
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.knowledge.mound import KnowledgeMound
from aragora.knowledge.mound.checkpoint import get_km_checkpoint_store, reset_km_checkpoint_store
from aragora.knowledge.mound.types import IngestionRequest, MoundBackend, MoundConfig
from aragora.server.handler_registry import HandlerRegistryMixin
from aragora.server.handler_registry.core import RouteIndex
from aragora.server.handlers.knowledge.checkpoints import KMCheckpointHandler
from aragora.server.handlers.knowledge_base.mound.handler import KnowledgeMoundHandler

pytestmark = pytest.mark.no_auto_auth

WORKSPACE = "kmcp-server-ws"
COLLECTION = "/api/v1/km/checkpoints"

# Real registry order: the checkpoint handler precedes the mound handler.
_REGISTRY = [
    ("_km_checkpoint_handler", KMCheckpointHandler),
    ("_knowledge_mound_handler", KnowledgeMoundHandler),
]


@dataclass
class _RoleSetUser(UserAuthContext):
    # KMCheckpointHandler's inner RBAC check reads ``roles``; UserAuthContext
    # itself carries only the single ``role`` string.
    roles: set[str] = field(default_factory=set)


def _user(role: str, *, authenticated: bool = True) -> _RoleSetUser:
    return _RoleSetUser(
        authenticated=authenticated,
        user_id=f"{role}-1",
        email=f"{role}@example.com",
        org_id="org-km",
        role=role,
        token_type="access",
        roles={role},
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
        assert (store.checkpoint_dir / checkpoint_id).is_dir()

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

    def test_member_cannot_create(self, server_mound: KnowledgeMound) -> None:
        server = _Server(server_mound)
        _, status, body = server.request(
            "POST", COLLECTION, _user("member"), body={"name": "cp-member"}
        )
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
