"""User-store resolution in the shared ``get_auth_context`` helper.

FastAPI keeps the user store in ``app.state.context["user_store"]``, while
aiohttp applications hold it as a mapping entry. ``ara_`` API keys can only be
validated against that store, so a request that cannot find it is anonymous.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import aragora.storage.user_store as user_store_module
from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.dependencies.auth import require_authenticated
from aragora.server.handlers.utils.auth import get_auth_context

API_KEY = "ara_test_key_0123456789abcdef"


class _ApiKeyUserStore:
    def __init__(self, users: dict[str, Any]) -> None:
        self._users = users
        self.lookups: list[str] = []

    def get_user_by_api_key(self, api_key: str) -> Any:
        self.lookups.append(api_key)
        return self._users.get(api_key)


def _user(user_id: str = "user-a", org_id: str = "org-a") -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email=f"{user_id}@example.com",
        org_id=org_id,
        role="member",
        is_active=True,
    )


def _whoami_app(context: dict[str, Any] | None) -> FastAPI:
    app = FastAPI()
    if context is not None:
        app.state.context = context

    @app.get("/whoami")
    async def whoami(
        auth: AuthorizationContext = Depends(require_authenticated),
    ) -> dict[str, Any]:
        return {"user_id": auth.user_id, "org_id": auth.org_id}

    return app


def _whoami(app: FastAPI, headers: dict[str, str] | None = None) -> Any:
    with TestClient(app) as client:
        return client.get("/whoami", headers=headers or {})


def _api_key_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture
def global_store_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record calls to the global store; fail loudly unless a test installs one."""
    calls: list[str] = []

    def _unexpected() -> Any:
        calls.append("get_user_store")
        raise AssertionError("global user store must not be consulted here")

    monkeypatch.setattr(user_store_module, "get_user_store", _unexpected)
    return calls


def test_api_key_on_fastapi_request_resolves_user_and_org(global_store_calls: list[str]) -> None:
    store = _ApiKeyUserStore({API_KEY: _user("user-a", "org-a")})

    response = _whoami(_whoami_app({"user_store": store}), _api_key_headers())

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-a", "org_id": "org-a"}
    assert store.lookups == [API_KEY]
    assert global_store_calls == []


def test_unknown_api_key_on_fastapi_request_stays_anonymous(global_store_calls: list[str]) -> None:
    store = _ApiKeyUserStore({})

    response = _whoami(_whoami_app({"user_store": store}), _api_key_headers())

    assert response.status_code == 401
    assert store.lookups == [API_KEY]
    assert global_store_calls == []


@pytest.mark.parametrize("context", [None, {"user_store": None}], ids=["no-context", "no-store"])
def test_api_key_falls_back_to_global_user_store(
    monkeypatch: pytest.MonkeyPatch, context: dict[str, Any] | None
) -> None:
    store = _ApiKeyUserStore({API_KEY: _user("user-g", "org-g")})
    monkeypatch.setattr(user_store_module, "get_user_store", lambda: store)

    response = _whoami(_whoami_app(context), _api_key_headers())

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-g", "org_id": "org-g"}
    assert store.lookups == [API_KEY]


def test_global_user_store_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken() -> Any:
        raise RuntimeError("user store unavailable")

    monkeypatch.setattr(user_store_module, "get_user_store", _broken)

    response = _whoami(_whoami_app({"user_store": None}), _api_key_headers())

    assert response.status_code == 401


def test_global_user_store_is_not_consulted_without_an_api_key(
    global_store_calls: list[str],
) -> None:
    response = _whoami(_whoami_app({"user_store": None}))

    assert response.status_code == 401
    assert global_store_calls == []


@pytest.mark.filterwarnings("ignore::aiohttp.web_exceptions.NotAppKeyWarning")
async def test_aiohttp_application_still_supplies_user_store(
    global_store_calls: list[str],
) -> None:
    store = _ApiKeyUserStore({API_KEY: _user("user-b", "org-b")})
    app = web.Application()
    app["user_store"] = store
    request = make_mocked_request("GET", "/", headers=_api_key_headers(), app=app)

    auth = await get_auth_context(request)

    assert (auth.user_id, auth.org_id) == ("user-b", "org-b")
    assert store.lookups == [API_KEY]
    assert global_store_calls == []


async def test_aiohttp_application_without_user_store_is_unchanged(
    global_store_calls: list[str],
) -> None:
    request = make_mocked_request("GET", "/", headers=_api_key_headers(), app=web.Application())

    auth = await get_auth_context(request)

    assert auth.user_id == "anonymous"
    assert global_store_calls == []
