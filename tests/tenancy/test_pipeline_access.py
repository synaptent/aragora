"""Tests for aragora.tenancy.pipeline_access (scope, fail-closed permission, ownership)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aragora.rbac.models import AuthorizationDecision
from aragora.tenancy import pipeline_access
from aragora.tenancy.pipeline_access import (
    authorize_pipeline_request,
    check_pipeline_permission,
    record_owned,
    store_owner_org,
)
from aragora.tenancy.record_scope import OrgScope

pytestmark = pytest.mark.no_auto_auth

SCOPE_A = OrgScope(org_id="org-a", user_id="user-a", role="owner")


def _body(result) -> dict:
    return json.loads(result.body)


def _user(org_id: str | None = "org-a", role: str = "owner", authenticated: bool = True):
    return SimpleNamespace(
        is_authenticated=authenticated,
        user_id="user-a" if authenticated else None,
        org_id=org_id,
        role=role,
    )


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
@pytest.mark.parametrize(
    "permission",
    [pipeline_access.PIPELINE_READ, pipeline_access.PIPELINE_CREATE, pipeline_access.PIPELINE_RUN],
)
def test_org_roles_hold_pipeline_read_create_run(role: str, permission: str) -> None:
    scope = OrgScope(org_id="org-a", user_id="user-a", role=role)
    assert check_pipeline_permission(scope, permission) is None


def test_viewer_cannot_create() -> None:
    scope = OrgScope(org_id="org-a", user_id="user-v", role="viewer")
    denial = check_pipeline_permission(scope, pipeline_access.PIPELINE_CREATE)
    assert denial is not None and denial.status_code == 403


@pytest.mark.parametrize("exc", [ImportError, AttributeError, ValueError, RuntimeError])
def test_checker_failure_denies(exc: type[Exception]) -> None:
    with patch("aragora.rbac.checker.get_permission_checker", side_effect=exc("boom")):
        denial = check_pipeline_permission(SCOPE_A, pipeline_access.PIPELINE_READ)
    assert denial is not None
    assert denial.status_code == 403
    assert _body(denial)["code"] == "permission_denied"


def test_checker_module_import_failure_denies() -> None:
    with patch.dict(sys.modules, {"aragora.rbac.checker": None}):
        denial = check_pipeline_permission(SCOPE_A, pipeline_access.PIPELINE_READ)
    assert denial is not None and denial.status_code == 403


def test_non_boolean_decision_denies() -> None:
    checker = MagicMock()
    checker.check_permission.return_value = MagicMock()
    with patch("aragora.rbac.checker.get_permission_checker", return_value=checker):
        denial = check_pipeline_permission(SCOPE_A, pipeline_access.PIPELINE_READ)
    assert denial is not None and denial.status_code == 403


def test_explicit_deny_denies() -> None:
    checker = MagicMock()
    checker.check_permission.return_value = AuthorizationDecision(
        allowed=False, reason="no", permission_key="canvas:read"
    )
    with patch("aragora.rbac.checker.get_permission_checker", return_value=checker):
        denial = check_pipeline_permission(SCOPE_A, pipeline_access.PIPELINE_READ)
    assert denial is not None and denial.status_code == 403


def test_authorize_returns_scope_for_org_member() -> None:
    with patch("aragora.billing.jwt_auth.extract_user_from_request", return_value=_user()):
        scope, denial = authorize_pipeline_request(MagicMock(), pipeline_access.PIPELINE_READ)
    assert denial is None
    assert scope == OrgScope(org_id="org-a", user_id="user-a", role="owner")


def test_authorize_anonymous_is_401_before_permission() -> None:
    handler = MagicMock()
    handler.headers = {}
    with (
        patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=_user(authenticated=False),
        ),
        patch("aragora.rbac.checker.get_permission_checker") as checker,
    ):
        scope, denial = authorize_pipeline_request(handler, pipeline_access.PIPELINE_READ)
    assert scope is None
    assert denial.status_code == 401
    assert _body(denial)["code"] == "auth_required"
    checker.assert_not_called()


def test_authorize_user_without_org_is_403_org_required() -> None:
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request", return_value=_user(org_id=None)
    ):
        scope, denial = authorize_pipeline_request(MagicMock(), pipeline_access.PIPELINE_READ)
    assert scope is None
    assert denial.status_code == 403
    assert _body(denial)["code"] == "org_required"


def test_authorize_permission_denied_is_403() -> None:
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request", return_value=_user(role="viewer")
    ):
        scope, denial = authorize_pipeline_request(MagicMock(), pipeline_access.PIPELINE_CREATE)
    assert scope is None
    assert denial.status_code == 403
    assert _body(denial)["code"] == "permission_denied"


def test_record_owned() -> None:
    store = MagicMock()
    store.get_owner_org.side_effect = {"p-a": "org-a", "p-b": "org-b"}.get

    assert record_owned(store, "p-a", SCOPE_A) is True
    assert record_owned(store, "p-b", SCOPE_A) is False
    assert record_owned(store, "p-missing", SCOPE_A) is False
    assert record_owned(store, "p-a", None) is False
    assert record_owned(store, "", SCOPE_A) is False


def test_store_owner_org_ignores_stores_without_ownership() -> None:
    assert store_owner_org(object(), "p-a") is None
    store = MagicMock()
    store.get_owner_org.return_value = MagicMock()
    assert store_owner_org(store, "p-a") is None
