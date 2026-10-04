"""FastAPI: static-API-token-only callers get 403 org_required on org-scoped routes."""

from __future__ import annotations

from typing import Any

import pytest

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.dependencies.auth import require_authenticated

STATIC_TOKEN = "fastapi-static-token-org-required-0123456789"
ORG_REQUIRED_BODY = {
    "error": "This resource belongs to an organization; sign in as a member of one",
    "code": "org_required",
}
CREATE_BODY = {"question": "Should we adopt a four-day week?", "agents": ["demo", "demo"]}


def _install_api_token(monkeypatch: pytest.MonkeyPatch, value: str | None) -> Any:
    from aragora.server import auth as server_auth

    if value is None:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_API_TOKEN", value)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)
    return config


@pytest.fixture(autouse=True)
def api_token(monkeypatch):
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "fastapi-static-token-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    return _install_api_token(monkeypatch, STATIC_TOKEN)


def _jwt(org_id: str | None, role: str = "member") -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token("user-a", "user-a@example.test", org_id, role)


def _create(client, authorization: str | None):
    headers = {} if authorization is None else {"Authorization": authorization}
    return client.post("/api/v2/debates", json=CREATE_BODY, headers=headers)


class TestCreateDebate:
    def test_static_token_gets_403_org_required_with_no_side_effect(self, client, fastapi_context):
        response = _create(client, f"Bearer {STATIC_TOKEN}")

        assert (response.status_code, response.json()) == (403, ORG_REQUIRED_BODY)
        assert fastapi_context["storage"].method_calls == []
        assert fastapi_context["decision_service"].method_calls == []

    def test_token_signed_with_static_token_gets_403_org_required(self, client, api_token):
        signed = api_token.generate_token("loop-1", expires_in=600)

        response = _create(client, f"Bearer {signed}")

        assert (response.status_code, response.json()) == (403, ORG_REQUIRED_BODY)

    @pytest.mark.parametrize("authorization", [None, "Bearer not-the-token"])
    def test_missing_or_invalid_credential_still_gets_401(self, client, authorization):
        assert _create(client, authorization).status_code == 401

    def test_jwt_user_without_org_gets_403_org_required(self, client):
        response = _create(client, _jwt(None, role="admin"))

        assert response.status_code == 403
        assert response.json()["code"] == "org_required"

    def test_without_api_token_configured_the_value_is_just_invalid(self, client, monkeypatch):
        _install_api_token(monkeypatch, None)

        assert _create(client, f"Bearer {STATIC_TOKEN}").status_code == 401


class TestRequireAuthenticated:
    def test_route_outside_the_matcher_still_answers_401(self, client):
        response = client.get(
            "/api/v2/analytics/summary", headers={"Authorization": f"Bearer {STATIC_TOKEN}"}
        )

        assert response.status_code == 401

    async def test_direct_call_without_request_keeps_previous_contract(self):
        auth = AuthorizationContext(user_id="user-a", org_id="org-a", roles={"member"})

        assert await require_authenticated(auth) is auth
