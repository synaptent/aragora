"""Hygiene of the route rules that map existing keys onto org-owned routes.

The rules only route existing permission keys: no role gains a grant, no key
is added, every rule names its method and matches a whole path, and the
routes left for a later decision still fall through to default-deny.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aragora.rbac.defaults import SYSTEM_PERMISSIONS, SYSTEM_ROLES, get_role_permissions
from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS, RBACMiddleware
from aragora.rbac.models import AuthorizationContext

# (count, sha256 prefix) of the sorted "role=key" grants of every system role,
# inheritance included, and of the permission registry keys. A deliberate
# grant or key change updates the snapshot in the same PR.
ROLE_GRANTS_DIGEST = (1005, "2859128188227e2e")
PERMISSION_KEYS_DIGEST = (868, "bb99c13fecdeda65")
MAPPED_KEYS = set(
    "debates.create documents.create documents.delete documents.read gauntlet.export_data "
    "receipts.read receipts.share receipts.sign receipts.verify upload.create".split()
)
# Rules carrying a mapped key that predate the mapping (two are prefix rules).
OLDER_RULES = {
    ("POST", r"^/api/(?:v1/)?debates?$"),
    ("POST", r"^/api/(?:v1/)?interrogation/start$"),
    ("POST", r"^/api/(?:v1/)?interrogation/answer$"),
    ("POST", r"^/api/(?:v1/)?interrogation/crystallize$"),
    ("GET", r"^/api/documents"),
    ("DELETE", r"^/api/documents"),
}
# Receipts DSAR, batch export and share-token read; debate reads without org scope.
DEFERRED_ROUTES = [
    ("GET", "/api/v2/receipts/dsar/user-1"),
    ("POST", "/api/v2/receipts/batch-export"),
    ("GET", "/api/v2/receipts/share/tok-1"),
    ("GET", "/api/debates/batch/"),
    ("GET", "/api/v1/debates/batch/"),
    ("GET", "/api/v1/debates/batch/batch-1/status"),
    ("GET", "/api/v1/debates/queue/status"),
    ("GET", "/api/v2/debates"),
    ("GET", "/api/v2/debates/deb-1"),
]


def _digest(lines) -> tuple[int, str]:
    lines = sorted(lines)
    return len(lines), hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def test_role_grants_are_unchanged():
    grants = [
        f"{role}={key}"
        for role in SYSTEM_ROLES
        for key in get_role_permissions(role, include_inherited=True)
    ]

    assert _digest(grants) == ROLE_GRANTS_DIGEST


def test_no_permission_key_is_added():
    assert _digest(SYSTEM_PERMISSIONS) == PERMISSION_KEYS_DIGEST


def test_mapped_rules_are_method_explicit_anchored_and_authenticated():
    rules = [
        rule
        for rule in DEFAULT_ROUTE_PERMISSIONS
        if rule.permission_key in MAPPED_KEYS
        and (rule.method, rule.pattern.pattern) not in OLDER_RULES
    ]

    assert len(rules) == 30
    for rule in rules:
        assert rule.method in {"GET", "POST", "DELETE"}, rule
        assert rule.pattern.pattern.startswith("^") and rule.pattern.pattern.endswith("$"), rule
        assert rule.permission_key in SYSTEM_PERMISSIONS, rule
        assert not rule.allow_unauthenticated, rule


@pytest.mark.parametrize(("method", "path"), DEFERRED_ROUTES)
def test_deferred_routes_stay_default_deny_for_every_role(method, path):
    middleware = RBACMiddleware()

    assert middleware.get_required_permission(path, method) is None
    for role in SYSTEM_ROLES:
        context = AuthorizationContext(user_id="u-1", org_id="org-1", roles={role})
        allowed, reason, _ = middleware.check_request(path, method, context)
        assert not allowed and "default-deny" in reason, (role, reason)


def test_folder_delete_uses_a_registered_key():
    root = Path(__file__).resolve().parents[2]
    source = (root / "aragora/server/handlers/features/folder_upload.py").read_text()

    assert "upload:delete" not in source and "folders:delete" not in source
