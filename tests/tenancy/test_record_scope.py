"""Tests for the org-scope layer in aragora.tenancy.record_scope.

Covers record_visible, the legacy-handler helper, the FastAPI dependency
(through TestClient on the real app factory) and the shared not-found
responses. Every identity case runs with ARAGORA_API_TOKEN unset and set.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_not_found_error,
    record_visible,
    require_org_scope,
    require_org_scope_fastapi,
)

ORG_A = "org-a-96d2f357"
ORG_B = "org-b-59edef89"
USER_A = "user-a-9f964e24"
USER_B = "user-b-5a0814ad"
STATIC_TOKEN = "rs-static-api-token-0123456789abcdef"

AUTH_REQUIRED_BODY = {"error": "Authentication required", "code": "auth_required"}


@pytest.fixture(autouse=True)
def _isolated_jwt(monkeypatch):
    """Deterministic JWT secret and an in-memory revocation list for every test."""
    monkeypatch.delenv("ARAGORA_ENV", raising=False)
    monkeypatch.delenv("ARAGORA_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ARAGORA_SECRETS_STRICT", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "record-scope-test-secret-" + "s" * 32)

    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store

    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())


def _install_api_token(monkeypatch: pytest.MonkeyPatch, value: str | None) -> Any:
    """Configure ARAGORA_API_TOKEN and give the server a fresh AuthConfig for it."""
    from aragora.server import auth as server_auth

    if value is None:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_API_TOKEN", value)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)
    return config


@pytest.fixture(params=[None, STATIC_TOKEN], ids=["api_token_unset", "api_token_set"])
def api_token(request, monkeypatch) -> str | None:
    _install_api_token(monkeypatch, request.param)
    return request.param


@pytest.fixture
def api_token_set(monkeypatch) -> Any:
    return _install_api_token(monkeypatch, STATIC_TOKEN)


def _jwt(user_id: str, org_id: str | None, role: str = "member") -> str:
    from aragora.billing.auth.tokens import create_access_token

    return create_access_token(user_id, f"{user_id}@example.test", org_id, role)


class _LegacyRequest:
    """Minimal stand-in for the ThreadingHTTPServer request handler."""

    def __init__(self, authorization: str | None = None) -> None:
        self.headers: dict[str, str] = {}
        if authorization is not None:
            self.headers["Authorization"] = authorization
        self.client_address = ("127.0.0.1", 50000)


def _legacy(authorization: str | None) -> tuple[OrgScope | None, Any]:
    return require_org_scope(_LegacyRequest(authorization))


def _legacy_outcome(authorization: str | None) -> tuple[int, Any]:
    scope, err = _legacy(authorization)
    if err is not None:
        assert scope is None
        return err.status_code, json.loads(err.body)
    assert scope is not None
    return 200, {"org_id": scope.org_id, "user_id": scope.user_id, "role": scope.role}


# =============================================================================
# OrgScope and record_visible
# =============================================================================


class TestRecordVisible:
    def test_same_org_is_visible(self):
        assert record_visible(ORG_A, OrgScope(ORG_A, USER_A, "owner")) is True

    def test_null_record_org_is_invisible(self):
        assert record_visible(None, OrgScope(ORG_A, USER_A, "owner")) is False

    def test_empty_record_org_is_invisible(self):
        assert record_visible("", OrgScope(ORG_A, USER_A, "owner")) is False

    def test_other_org_is_invisible(self):
        assert record_visible(ORG_B, OrgScope(ORG_A, USER_A, "owner")) is False

    def test_missing_scope_is_invisible(self):
        assert record_visible(ORG_A, None) is False


class TestOrgScope:
    def test_fields_are_positional_org_user_role(self):
        scope = OrgScope(ORG_A, USER_A, "admin")
        assert (scope.org_id, scope.user_id, scope.role) == (ORG_A, USER_A, "admin")

    @pytest.mark.parametrize("org_id", ["", "   "])
    def test_blank_org_is_rejected(self, org_id):
        with pytest.raises(ValueError):
            OrgScope(org_id, USER_A, "member")

    def test_scope_is_immutable(self):
        scope = OrgScope(ORG_A, USER_A, "member")
        with pytest.raises(AttributeError):
            scope.org_id = ORG_B  # type: ignore[misc]


# =============================================================================
# Legacy handler helper
# =============================================================================


class TestLegacyHelper:
    def test_no_token_is_401(self, api_token):
        scope, err = _legacy(None)
        assert scope is None
        assert err.status_code == 401
        assert json.loads(err.body) == AUTH_REQUIRED_BODY

    def test_invalid_bearer_is_401(self, api_token):
        scope, err = _legacy("Bearer not-a-valid-token")
        assert scope is None
        assert err.status_code == 401
        assert json.loads(err.body) == AUTH_REQUIRED_BODY

    def test_jwt_user_without_org_is_403_org_required(self, api_token):
        scope, err = _legacy(f"Bearer {_jwt(USER_A, None)}")
        assert scope is None
        assert err.status_code == 403
        body = json.loads(err.body)
        assert body["code"] == "org_required"
        assert set(body) == {"error", "code"}

    def test_jwt_user_with_org_returns_scope_from_token(self, api_token):
        scope, err = _legacy(f"Bearer {_jwt(USER_A, ORG_A, role='admin')}")
        assert err is None
        assert scope == OrgScope(ORG_A, USER_A, "admin")

    def test_user_store_defaults_to_request_attribute(self, api_token):
        request = _LegacyRequest(f"Bearer {_jwt(USER_B, ORG_B, role='owner')}")
        request.user_store = None  # type: ignore[attr-defined]
        scope, err = require_org_scope(request)
        assert err is None
        assert scope == OrgScope(ORG_B, USER_B, "owner")

    def test_static_api_token_only_is_403_org_required(self, api_token_set):
        scope, err = _legacy(f"Bearer {STATIC_TOKEN}")
        assert scope is None
        assert err.status_code == 403
        assert json.loads(err.body)["code"] == "org_required"

    def test_token_signed_with_static_api_token_is_403_org_required(self, api_token_set):
        signed = api_token_set.generate_token("loop-1")
        scope, err = _legacy(f"Bearer {signed}")
        assert scope is None
        assert err.status_code == 403
        assert json.loads(err.body)["code"] == "org_required"

    def test_unconfigured_static_token_value_is_just_invalid(self, monkeypatch):
        _install_api_token(monkeypatch, None)
        scope, err = _legacy(f"Bearer {STATIC_TOKEN}")
        assert scope is None
        assert err.status_code == 401

    def test_results_identical_with_api_token_set_and_unset(self, monkeypatch):
        cases = [
            None,
            "Bearer not-a-valid-token",
            f"Bearer {_jwt(USER_A, None)}",
            f"Bearer {_jwt(USER_A, ORG_A, role='owner')}",
        ]
        _install_api_token(monkeypatch, None)
        unset = [_legacy_outcome(case) for case in cases]
        _install_api_token(monkeypatch, STATIC_TOKEN)
        token_set = [_legacy_outcome(case) for case in cases]
        assert unset == token_set
        assert [status for status, _ in unset] == [401, 401, 403, 200]


# =============================================================================
# FastAPI dependency (TestClient against the real app factory)
# =============================================================================

_FASTAPI_RECORDS: dict[str, dict[str, Any]] = {
    "rec-a": {"id": "rec-a", "org_id": ORG_A, "text": "SENTINEL-ORG-A"},
    "rec-null": {"id": "rec-null", "org_id": None, "text": "SENTINEL-NULL-OWNER"},
}


@pytest.fixture(scope="module")
def scope_client():
    from fastapi import Depends
    from fastapi.testclient import TestClient

    from aragora.server.fastapi import create_app

    app = create_app()

    @app.get("/__test__/org-scope")
    async def _probe(scope: OrgScope = Depends(require_org_scope_fastapi)) -> dict[str, str]:
        return {"org_id": scope.org_id, "user_id": scope.user_id, "role": scope.role}

    @app.get("/__test__/records/{record_id}")
    async def _record(
        record_id: str, scope: OrgScope = Depends(require_org_scope_fastapi)
    ) -> dict[str, Any]:
        record = _FASTAPI_RECORDS.get(record_id)
        if record is None or not record_visible(record["org_id"], scope):
            raise record_not_found_error("Record")
        return record

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        client.close()


def _fastapi_outcome(client: Any, authorization: str | None) -> tuple[int, Any]:
    headers = {} if authorization is None else {"Authorization": authorization}
    response = client.get("/__test__/org-scope", headers=headers)
    return response.status_code, response.json()


class TestFastAPIDependency:
    def test_no_token_is_401(self, scope_client, api_token):
        status, body = _fastapi_outcome(scope_client, None)
        assert status == 401
        assert body == AUTH_REQUIRED_BODY

    def test_invalid_bearer_is_401(self, scope_client, api_token):
        status, body = _fastapi_outcome(scope_client, "Bearer not-a-valid-token")
        assert status == 401
        assert body == AUTH_REQUIRED_BODY

    def test_jwt_user_without_org_is_403_org_required(self, scope_client, api_token):
        status, body = _fastapi_outcome(scope_client, f"Bearer {_jwt(USER_A, None)}")
        assert status == 403
        assert body["code"] == "org_required"
        assert set(body) == {"error", "code"}

    def test_jwt_user_with_org_returns_scope_from_token(self, scope_client, api_token):
        status, body = _fastapi_outcome(scope_client, f"Bearer {_jwt(USER_A, ORG_A, role='admin')}")
        assert status == 200
        assert body == {"org_id": ORG_A, "user_id": USER_A, "role": "admin"}

    def test_static_api_token_only_is_403_org_required(self, scope_client, api_token_set):
        status, body = _fastapi_outcome(scope_client, f"Bearer {STATIC_TOKEN}")
        assert status == 403
        assert body["code"] == "org_required"

    def test_mirrors_legacy_helper(self, scope_client, api_token):
        cases = [
            None,
            "Bearer not-a-valid-token",
            f"Bearer {_jwt(USER_B, None)}",
            f"Bearer {_jwt(USER_B, ORG_B, role='owner')}",
        ]
        if api_token:
            cases.append(f"Bearer {STATIC_TOKEN}")
        for case in cases:
            assert _fastapi_outcome(scope_client, case) == _legacy_outcome(case), case


# =============================================================================
# Not-found responses
# =============================================================================


class TestNotFound:
    def test_legacy_body_is_byte_identical_for_missing_other_org_and_unknown_owner(self):
        records = {
            "rec-a": {"org_id": ORG_A, "text": "SENTINEL-ORG-A"},
            "rec-null": {"org_id": None, "text": "SENTINEL-NULL-OWNER"},
        }
        scope_b = OrgScope(ORG_B, USER_B, "owner")

        def lookup(record_id: str) -> Any:
            record = records.get(record_id)
            if record is None or not record_visible(record["org_id"], scope_b):
                return record_not_found("Record")
            raise AssertionError("org B must not see this record")

        missing = lookup("rec-does-not-exist")
        other_org = lookup("rec-a")
        unknown_owner = lookup("rec-null")
        assert missing.status_code == other_org.status_code == unknown_owner.status_code == 404
        assert missing.body == other_org.body == unknown_owner.body
        assert json.loads(missing.body) == {"error": "Record not found", "code": "not_found"}
        assert b"SENTINEL" not in other_org.body
        assert ORG_A.encode() not in other_org.body

    def test_fastapi_body_is_byte_identical_for_missing_other_org_and_unknown_owner(
        self, scope_client
    ):
        headers = {"Authorization": f"Bearer {_jwt(USER_B, ORG_B, role='owner')}"}
        missing = scope_client.get("/__test__/records/rec-does-not-exist", headers=headers)
        other_org = scope_client.get("/__test__/records/rec-a", headers=headers)
        unknown_owner = scope_client.get("/__test__/records/rec-null", headers=headers)
        assert missing.status_code == other_org.status_code == unknown_owner.status_code == 404
        assert missing.content == other_org.content == unknown_owner.content
        assert missing.json() == json.loads(record_not_found("Record").body)
        assert b"SENTINEL" not in other_org.content

    def test_fastapi_owner_still_sees_own_record(self, scope_client):
        headers = {"Authorization": f"Bearer {_jwt(USER_A, ORG_A, role='owner')}"}
        response = scope_client.get("/__test__/records/rec-a", headers=headers)
        assert response.status_code == 200
        assert response.json()["text"] == "SENTINEL-ORG-A"
