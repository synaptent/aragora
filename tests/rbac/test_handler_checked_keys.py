"""Registration and role grants for permission keys that handlers already check.

The connectors, analytics-platforms and cross-pollination handlers check
``connectors:configure``, ``analytics:configure``, ``analytics:query``,
``cross_pollination:read`` and ``cross_pollination:write``. A key missing from
SYSTEM_PERMISSIONS is denied to every role, owner included, because the owner
role is built from SYSTEM_PERMISSIONS.
"""

from __future__ import annotations

import pytest

from aragora.rbac.checker import PermissionChecker
from aragora.rbac.defaults import (
    SYSTEM_PERMISSIONS,
    SYSTEM_ROLES,
    get_permission,
    get_role_permissions,
)
from aragora.rbac.models import AuthorizationContext

DIRECT_GRANTS: dict[str, frozenset[str]] = {
    "connectors.configure": frozenset({"owner", "admin"}),
    "analytics.configure": frozenset({"owner", "admin"}),
    "analytics.query": frozenset({"owner", "admin", "analyst"}),
    "cross_pollination.read": frozenset({"owner", "admin", "member", "analyst"}),
    "cross_pollination.write": frozenset({"owner", "admin"}),
}
NEW_KEYS = frozenset(DIRECT_GRANTS)

# Effective grants after ROLE_HIERARCHY inheritance: member's grant reaches
# team_lead, developer and debate_creator; analyst's grants reach
# compliance_officer and ops_reviewer.
EFFECTIVE_GRANTS: dict[str, frozenset[str]] = {
    "owner": NEW_KEYS,
    "admin": NEW_KEYS,
    "analyst": frozenset({"analytics.query", "cross_pollination.read"}),
    "compliance_officer": frozenset({"analytics.query", "cross_pollination.read"}),
    "ops_reviewer": frozenset({"analytics.query", "cross_pollination.read"}),
    "member": frozenset({"cross_pollination.read"}),
    "team_lead": frozenset({"cross_pollination.read"}),
    "developer": frozenset({"cross_pollination.read"}),
    "debate_creator": frozenset({"cross_pollination.read"}),
    "viewer": frozenset(),
}


def _handler_spelling(key: str) -> str:
    return key.replace(".", ":", 1)


@pytest.mark.parametrize("key", sorted(NEW_KEYS))
def test_key_is_registered(key: str) -> None:
    perm = get_permission(key)
    assert perm is not None, f"{key} is not in SYSTEM_PERMISSIONS"
    assert perm.key == key
    assert SYSTEM_PERMISSIONS.get(_handler_spelling(key)) is perm


def test_every_system_role_is_covered() -> None:
    assert set(EFFECTIVE_GRANTS) == set(SYSTEM_ROLES)


@pytest.mark.parametrize("role_name", sorted(SYSTEM_ROLES))
def test_direct_grants_are_exactly_the_approved_roles(role_name: str) -> None:
    expected = {key for key, roles in DIRECT_GRANTS.items() if role_name in roles}
    assert SYSTEM_ROLES[role_name].permissions & NEW_KEYS == expected


@pytest.mark.parametrize("role_name", sorted(SYSTEM_ROLES))
def test_inherited_grants_follow_role_hierarchy(role_name: str) -> None:
    assert get_role_permissions(role_name) & NEW_KEYS == EFFECTIVE_GRANTS[role_name]


@pytest.mark.parametrize("role_name", sorted(EFFECTIVE_GRANTS))
@pytest.mark.parametrize("key", sorted(NEW_KEYS))
def test_checker_decision_for_handler_spelling(role_name: str, key: str) -> None:
    checker = PermissionChecker(enable_cache=False)
    context = AuthorizationContext(user_id=f"user-{role_name}", roles={role_name})
    decision = checker.check_permission(context, _handler_spelling(key))
    assert decision.allowed is (key in EFFECTIVE_GRANTS[role_name])
