"""Fixtures for the debate write-isolation tests (see ``support.py``)."""

from __future__ import annotations

from typing import Any

import pytest

from aragora.server.handlers.debates import DebatesHandler
from aragora.storage.debate_storage import DebateStorage
from tests.server.handlers.debates.write_isolation.support import (
    DA,
    DA_TASK,
    DB,
    DB_TASK,
    DN,
    DP,
    ORG_A,
    ORG_B,
    Request,
    act_as,
    debate_record,
    route,
)


@pytest.fixture(autouse=True)
def _no_rate_limits(monkeypatch):
    from aragora.server.middleware.rate_limit import decorators as rl_decorators
    from aragora.server.middleware.rate_limit.limiter import RateLimitResult
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    def _always_allowed(*args, **kwargs):
        return RateLimitResult(allowed=True, remaining=99, limit=100, key="test")

    monkeypatch.setattr(rl_decorators, "check_user_rate_limit", _always_allowed)
    reset_rate_limiters()
    yield
    reset_rate_limiters()


@pytest.fixture(autouse=True)
def state_manager():
    """A fresh StateManager per test; the process-wide one is restored afterwards."""
    from aragora.server.state import StateManager, get_state_manager
    from aragora.services import ServiceRegistry

    registry, inherited, owned = ServiceRegistry.get(), get_state_manager(), StateManager()
    registry.unregister(StateManager)
    registry.register(StateManager, owned)
    try:
        yield owned
    finally:
        registry.unregister(StateManager)
        registry.register(StateManager, inherited)
        owned.shutdown()


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    store = DebateStorage(str(tmp_path / "debates.db"))
    store.save_dict(debate_record(DA, DA_TASK), org_id=ORG_A)
    store.save_dict(debate_record(DB, DB_TASK), org_id=ORG_B)
    store.save_dict(debate_record(DN, "Write isolation topic with no recorded org"))
    store.save_dict(debate_record(DP, "Write isolation topic shared publicly by A"), org_id=ORG_A)
    assert store.set_public(DP, True)
    return store


@pytest.fixture
def debates(storage, tmp_path) -> DebatesHandler:
    return DebatesHandler(ctx={"storage": storage, "nomic_dir": tmp_path})


@pytest.fixture
def send(monkeypatch, debates):
    """``send(user, method, path, body)`` runs ``DebatesHandler`` as ``user``."""

    def _send(user: Any, method: str, path: str, body: dict[str, Any] | None = None):
        act_as(monkeypatch, user)
        return route(debates, method, path, Request(method, user, body))

    return _send


@pytest.fixture
def server(monkeypatch, storage, tmp_path, request):
    """The real server dispatch path (route index, auth gates, RBAC) over ``storage``.

    Parametrize indirectly with the static API token, or None to leave it unset.
    """
    from tests.server.rbac_dispatch import build_server, isolate_auth

    isolate_auth(monkeypatch, api_token=getattr(request, "param", None))
    server = build_server()
    server.cls._debates_handler.ctx.update({"storage": storage, "nomic_dir": tmp_path})
    server.cls._debate_share_handler.ctx["storage"] = storage
    return server
