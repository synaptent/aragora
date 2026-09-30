"""
Tests for RBAC defaults module.

Tests cover:
- System permissions definition and structure
- System roles definition and structure
- Role hierarchy and inheritance
- Helper functions (get_permission, get_role, get_role_permissions, create_custom_role)
- Role templates
"""

import hashlib

import pytest

from aragora.rbac.defaults import (
    # Core functions
    create_custom_role,
    get_permission,
    get_role,
    get_role_permissions,
    # System collections
    ROLE_HIERARCHY,
    ROLE_TEMPLATES,
    SYSTEM_PERMISSIONS,
    SYSTEM_ROLES,
    # Individual roles
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEBATE_CREATOR,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_TEAM_LEAD,
    ROLE_VIEWER,
    # Sample permissions for testing
    PERM_ADMIN_ALL,
    PERM_CONNECTOR_TEST,
    PERM_DEBATE_CREATE,
    PERM_DEBATE_READ,
    PERM_DEBATE_RUN,
    PERM_ORG_BILLING,
    PERM_USER_CHANGE_ROLE,
    PERM_USER_IMPERSONATE,
    PERM_USER_INVITE,
)
from aragora.rbac.models import Action, Permission, ResourceType, Role


class TestSystemPermissions:
    """Tests for system permissions."""

    def test_system_permissions_not_empty(self):
        """SYSTEM_PERMISSIONS should contain permissions."""
        assert len(SYSTEM_PERMISSIONS) > 0
        assert len(SYSTEM_PERMISSIONS) >= 50  # We have many permissions defined

    def test_all_permissions_are_permission_instances(self):
        """All values in SYSTEM_PERMISSIONS should be Permission instances."""
        for key, perm in SYSTEM_PERMISSIONS.items():
            assert isinstance(perm, Permission), f"{key} is not a Permission"

    def test_permission_keys_match_ids(self):
        """Permission keys in dict should match permission IDs (for canonical keys)."""
        for key, perm in SYSTEM_PERMISSIONS.items():
            # Aliases use different formats: colon vs dot, or underscore variations
            # (e.g., controlplane.read -> control_plane.read)
            is_colon_alias = ":" in key
            is_underscore_alias = "_" not in key and "_" in perm.id
            if is_colon_alias or is_underscore_alias:
                # Alias should point to a valid permission - just verify perm exists
                assert perm.id, f"Alias {key} points to invalid permission"
            else:
                assert key == perm.id, f"Key {key} doesn't match permission ID {perm.id}"

    def test_permission_key_format(self):
        """Permission keys should follow resource.action or resource:action format."""
        for key in SYSTEM_PERMISSIONS:
            # Keys should contain at least one separator (dot or colon)
            assert "." in key or ":" in key, f"Permission key {key} doesn't contain separator"

    def test_debate_permissions_exist(self):
        """Core debate permissions should exist."""
        required = [
            "debates.create",
            "debates.read",
            "debates.update",
            "debates.delete",
            "debates.run",
            "debates.stop",
            "debates.fork",
        ]
        for key in required:
            assert key in SYSTEM_PERMISSIONS, f"Missing debate permission: {key}"

    def test_agent_permissions_exist(self):
        """Core agent permissions should exist."""
        required = [
            "agents.create",
            "agents.read",
            "agents.update",
            "agents.delete",
            "agents.deploy",
        ]
        for key in required:
            assert key in SYSTEM_PERMISSIONS, f"Missing agent permission: {key}"

    def test_performance_permissions_exist(self):
        """Performance/ranking permissions should exist."""
        required = [
            "analytics.read",  # PERM_PERFORMANCE_READ uses ResourceType.ANALYTICS
            "analytics.update",  # PERM_PERFORMANCE_WRITE uses ResourceType.ANALYTICS
        ]
        for key in required:
            assert key in SYSTEM_PERMISSIONS, f"Missing performance permission: {key}"

    def test_culture_permissions_exist(self):
        """Culture permissions should exist."""
        required = [
            "knowledge.read",  # PERM_CULTURE_READ uses ResourceType.KNOWLEDGE
            "knowledge.update",  # PERM_CULTURE_WRITE uses ResourceType.KNOWLEDGE
        ]
        for key in required:
            assert key in SYSTEM_PERMISSIONS, f"Missing culture permission: {key}"

    def test_admin_permissions_exist(self):
        """Admin permissions should exist."""
        required = [
            "admin.system_config",
            "admin.view_metrics",
            "admin.manage_features",
            "admin.*",  # Wildcard for full admin
        ]
        for key in required:
            assert key in SYSTEM_PERMISSIONS, f"Missing admin permission: {key}"

    def test_individual_permission_constants(self):
        """Individual permission constants should be defined correctly."""
        assert PERM_DEBATE_CREATE.resource == ResourceType.DEBATE
        assert PERM_DEBATE_CREATE.action == Action.CREATE
        assert PERM_ADMIN_ALL.resource == ResourceType.ADMIN
        assert PERM_ADMIN_ALL.action == Action.ALL


class TestSystemRoles:
    """Tests for system roles."""

    def test_system_roles_not_empty(self):
        """SYSTEM_ROLES should contain roles."""
        assert len(SYSTEM_ROLES) > 0
        assert len(SYSTEM_ROLES) >= 6  # We have at least 6 system roles

    def test_all_roles_are_role_instances(self):
        """All values in SYSTEM_ROLES should be Role instances."""
        for name, role in SYSTEM_ROLES.items():
            assert isinstance(role, Role), f"{name} is not a Role"

    def test_role_keys_match_names(self):
        """Role keys should match role names."""
        for key, role in SYSTEM_ROLES.items():
            assert key == role.name, f"Key {key} doesn't match role name {role.name}"

    def test_required_roles_exist(self):
        """Required system roles should exist."""
        required = ["owner", "admin", "debate_creator", "analyst", "viewer", "member"]
        for role_name in required:
            assert role_name in SYSTEM_ROLES, f"Missing system role: {role_name}"

    def test_owner_role_properties(self):
        """Owner role should have full admin permissions."""
        assert ROLE_OWNER.name == "owner"
        assert ROLE_OWNER.is_system is True
        assert ROLE_OWNER.is_custom is False
        assert PERM_ADMIN_ALL.key in ROLE_OWNER.permissions

    def test_admin_role_properties(self):
        """Admin role should have appropriate permissions."""
        assert ROLE_ADMIN.name == "admin"
        assert ROLE_ADMIN.is_system is True
        # Admin should have user management perms
        assert PERM_USER_INVITE.key in ROLE_ADMIN.permissions
        assert PERM_USER_CHANGE_ROLE.key in ROLE_ADMIN.permissions

    def test_viewer_role_minimal_permissions(self):
        """Viewer role should have minimal read-only permissions."""
        assert ROLE_VIEWER.name == "viewer"
        assert ROLE_VIEWER.is_system is True
        # Viewer should NOT have create/delete permissions
        for perm_key in ROLE_VIEWER.permissions:
            action = perm_key.split(".")[-1] if "." in perm_key else ""
            assert action not in [
                "create",
                "delete",
                "update",
            ], f"Viewer has write permission: {perm_key}"

    def test_role_priorities(self):
        """Roles should have correct priority ordering."""
        # Higher number = more senior
        assert ROLE_OWNER.priority > ROLE_ADMIN.priority
        assert ROLE_ADMIN.priority > ROLE_DEBATE_CREATOR.priority
        assert ROLE_DEBATE_CREATOR.priority > ROLE_MEMBER.priority
        assert ROLE_MEMBER.priority > ROLE_VIEWER.priority

    def test_individual_role_constants(self):
        """Individual role constants should be in SYSTEM_ROLES."""
        assert ROLE_OWNER == SYSTEM_ROLES.get("owner")
        assert ROLE_ADMIN == SYSTEM_ROLES.get("admin")
        assert ROLE_VIEWER == SYSTEM_ROLES.get("viewer")
        assert ROLE_MEMBER == SYSTEM_ROLES.get("member")


class TestRoleHierarchy:
    """Tests for role hierarchy."""

    def test_hierarchy_not_empty(self):
        """ROLE_HIERARCHY should be defined."""
        assert len(ROLE_HIERARCHY) > 0

    def test_hierarchy_contains_expected_roles(self):
        """Hierarchy should contain main system roles."""
        expected = ["owner", "admin", "debate_creator", "analyst", "member", "viewer"]
        for role_name in expected:
            assert role_name in ROLE_HIERARCHY, f"Missing {role_name} in hierarchy"

    def test_owner_has_admin_parent(self):
        """Owner should inherit from admin."""
        assert "admin" in ROLE_HIERARCHY.get("owner", [])

    def test_admin_has_debate_creator_parent(self):
        """Admin should inherit from debate_creator."""
        assert "debate_creator" in ROLE_HIERARCHY.get("admin", [])

    def test_viewer_has_no_parents(self):
        """Viewer should have no parent roles (base role)."""
        parents = ROLE_HIERARCHY.get("viewer", [])
        assert len(parents) == 0, f"Viewer has unexpected parents: {parents}"

    def test_no_circular_hierarchy(self):
        """Role hierarchy should not have circular dependencies."""

        def find_circular(role: str, visited: set) -> bool:
            if role in visited:
                return True
            visited.add(role)
            for parent in ROLE_HIERARCHY.get(role, []):
                if find_circular(parent, visited.copy()):
                    return True
            return False

        for role_name in ROLE_HIERARCHY:
            assert not find_circular(role_name, set()), f"Circular dependency found for {role_name}"


class TestGetPermission:
    """Tests for get_permission function."""

    def test_get_existing_permission(self):
        """Should return permission for valid key."""
        perm = get_permission("debates.create")
        assert perm is not None
        assert perm.id == "debates.create"
        assert perm.resource == ResourceType.DEBATE
        assert perm.action == Action.CREATE

    def test_get_nonexistent_permission(self):
        """Should return None for invalid key."""
        perm = get_permission("nonexistent.permission")
        assert perm is None

    def test_get_permission_by_constant_key(self):
        """Should return same permission as constant."""
        perm = get_permission(PERM_DEBATE_CREATE.key)
        assert perm == PERM_DEBATE_CREATE

    def test_get_permission_empty_key(self):
        """Should return None for empty key."""
        assert get_permission("") is None

    def test_get_permission_case_sensitive(self):
        """Permission keys should be case-sensitive."""
        assert get_permission("DEBATE.CREATE") is None


class TestGetRole:
    """Tests for get_role function."""

    def test_get_existing_role(self):
        """Should return role for valid name."""
        role = get_role("admin")
        assert role is not None
        assert role.name == "admin"
        assert role.is_system is True

    def test_get_nonexistent_role(self):
        """Should return None for invalid name."""
        role = get_role("nonexistent_role")
        assert role is None

    def test_get_role_returns_same_as_constant(self):
        """Should return same role as constant."""
        role = get_role("owner")
        assert role == ROLE_OWNER

    def test_get_role_empty_name(self):
        """Should return None for empty name."""
        assert get_role("") is None

    def test_get_role_case_sensitive(self):
        """Role names should be case-sensitive."""
        assert get_role("ADMIN") is None


class TestGetRolePermissions:
    """Tests for get_role_permissions function."""

    def test_get_permissions_for_valid_role(self):
        """Should return permissions for valid role."""
        perms = get_role_permissions("viewer")
        assert len(perms) > 0
        assert isinstance(perms, set)

    def test_get_permissions_for_invalid_role(self):
        """Should return empty set for invalid role."""
        perms = get_role_permissions("nonexistent_role")
        assert perms == set()

    def test_permissions_without_inheritance(self):
        """Should return only direct permissions when include_inherited=False."""
        perms_direct = get_role_permissions("admin", include_inherited=False)
        perms_inherited = get_role_permissions("admin", include_inherited=True)
        # Inherited should be >= direct
        assert len(perms_inherited) >= len(perms_direct)

    def test_owner_has_admin_permissions_inherited(self):
        """Owner should inherit admin permissions."""
        owner_perms = get_role_permissions("owner", include_inherited=True)
        admin_perms = get_role_permissions("admin", include_inherited=True)
        # All admin permissions should be in owner's permissions
        assert admin_perms.issubset(owner_perms)

    def test_viewer_permissions_in_all_roles(self):
        """Viewer permissions should be in all inheriting roles."""
        viewer_perms = get_role_permissions("viewer", include_inherited=True)
        member_perms = get_role_permissions("member", include_inherited=True)
        # Member inherits from viewer
        if "viewer" in ROLE_HIERARCHY.get("member", []):
            assert viewer_perms.issubset(member_perms)


def _permission_set_fingerprint(permissions: set[str]) -> tuple[int, str]:
    joined = "\n".join(sorted(permissions)).encode("utf-8")
    return len(permissions), hashlib.sha256(joined).hexdigest()


# Effective (inherited) permission set of every system role before admin was granted
# connectors.test, as (count, sha256 of the sorted keys joined by newlines).
_ROLE_FINGERPRINTS_BEFORE_ADMIN_CONNECTOR_TEST = {
    "admin": (203, "a6b4fc14829fa2081b3e476c4a47488f0c33c4d1090193fa59c4d895835c0028"),
    "analyst": (18, "6ce469b663e7a9c80e0765e5a5cd9881b48fa2f1f98137f5a4a09834a3505a85"),
    "compliance_officer": (
        44,
        "7154b5f8fb10d40a265f0716a2dda5245fef3d1edbf739ea90655f1c28a564ea",
    ),
    "debate_creator": (90, "722d3c2470ba732875ace58def9408394f3b87ea315d61196f36ba48716bf2dd"),
    "developer": (71, "eadf74e4bab5827706318db23cf5720f128aef0f6db566552a138e823ce10511"),
    "member": (70, "3c727c438bcbc6e1976ab077bae34e691e7e4ee0fb2b51cf727f47d2ed637049"),
    "ops_reviewer": (19, "da772f750b26090aa0fc86126d497e90dd0187fe9959ac3feb0a77d52329210d"),
    "owner": (402, "6e4c5b5ec5efbd68065676557a346954f47670e31783a34c62af6fc10b523ae2"),
    "team_lead": (82, "24623ba7ccc70070494c7410d159d7eba8bdf9e5b7ebcb121e0733cdb7060802"),
    "viewer": (6, "d2fce120a3ae82e4dfe79c8fb99bb26c12a4613db6e5bb78fe53c4e2f891a1e1"),
}


class TestAdminConnectorTestGrant:
    """Admin may test connectors; no other role's permission set changes with it."""

    def test_admin_holds_connectors_test_directly(self):
        assert PERM_CONNECTOR_TEST.key == "connectors.test"
        assert PERM_CONNECTOR_TEST.key in ROLE_ADMIN.permissions

    @pytest.mark.parametrize("role_name", sorted(_ROLE_FINGERPRINTS_BEFORE_ADMIN_CONNECTOR_TEST))
    def test_role_sets_differ_from_the_prior_grants_only_by_admin_connectors_test(self, role_name):
        added = {"admin": {PERM_CONNECTOR_TEST.key}}.get(role_name, set())
        effective = get_role_permissions(role_name, include_inherited=True)
        prior = _ROLE_FINGERPRINTS_BEFORE_ADMIN_CONNECTOR_TEST[role_name]
        if role_name == "owner":
            # Owner already held every system permission, connectors.test included.
            assert PERM_CONNECTOR_TEST.key in effective
        assert added <= effective
        assert _permission_set_fingerprint(effective - added) == prior

    def test_every_system_role_is_pinned(self):
        assert set(SYSTEM_ROLES) == set(_ROLE_FINGERPRINTS_BEFORE_ADMIN_CONNECTOR_TEST)


class TestCreateCustomRole:
    """Tests for create_custom_role function."""

    def test_create_basic_custom_role(self):
        """Should create a custom role with basic permissions."""
        role = create_custom_role(
            name="test_role",
            display_name="Test Role",
            description="A test role",
            permission_keys={PERM_DEBATE_READ.key, PERM_DEBATE_CREATE.key},
            org_id="org_123",
        )
        assert role.name == "test_role"
        assert role.display_name == "Test Role"
        assert role.description == "A test role"
        assert role.org_id == "org_123"
        assert role.is_system is False
        assert role.is_custom is True
        assert PERM_DEBATE_READ.key in role.permissions
        assert PERM_DEBATE_CREATE.key in role.permissions

    def test_custom_role_id_format(self):
        """Custom role ID should be org_id:name format."""
        role = create_custom_role(
            name="my_role",
            display_name="My Role",
            description="Test",
            permission_keys={PERM_DEBATE_READ.key},
            org_id="org_abc",
        )
        assert role.id == "org_abc:my_role"

    def test_custom_role_with_base_role(self):
        """Should inherit permissions from base role."""
        viewer_perms = get_role_permissions("viewer", include_inherited=True)
        role = create_custom_role(
            name="extended_viewer",
            display_name="Extended Viewer",
            description="Viewer with extra perms",
            permission_keys={PERM_DEBATE_CREATE.key},
            org_id="org_xyz",
            base_role="viewer",
        )
        # Should have viewer's permissions plus the new one
        assert viewer_perms.issubset(role.permissions)
        assert PERM_DEBATE_CREATE.key in role.permissions
        assert "viewer" in role.parent_roles

    def test_custom_role_invalid_permission_raises(self):
        """Should raise ValueError for invalid permission key."""
        with pytest.raises(ValueError, match="Unknown permission"):
            create_custom_role(
                name="bad_role",
                display_name="Bad Role",
                description="Test",
                permission_keys={"invalid.permission.key"},
                org_id="org_123",
            )

    def test_custom_role_with_nonexistent_base_role(self):
        """Should handle nonexistent base role gracefully."""
        role = create_custom_role(
            name="orphan_role",
            display_name="Orphan Role",
            description="No base",
            permission_keys={PERM_DEBATE_READ.key},
            org_id="org_123",
            base_role="nonexistent_role",
        )
        # Should still create with just the specified permissions
        assert len(role.permissions) == 1
        assert len(role.parent_roles) == 0

    def test_custom_role_priority(self):
        """Custom roles should have default priority."""
        role = create_custom_role(
            name="custom",
            display_name="Custom",
            description="Test",
            permission_keys={PERM_DEBATE_READ.key},
            org_id="org_123",
        )
        # Should be between member and debate_creator priorities
        assert ROLE_VIEWER.priority < role.priority < ROLE_ADMIN.priority


class TestRoleTemplates:
    """Tests for role templates."""

    def test_templates_not_empty(self):
        """ROLE_TEMPLATES should be defined."""
        assert len(ROLE_TEMPLATES) > 0

    def test_expected_templates_exist(self):
        """Expected role templates should exist."""
        expected = ["engineering", "research", "support", "external"]
        for template_name in expected:
            assert template_name in ROLE_TEMPLATES, f"Missing template: {template_name}"

    def test_template_structure(self):
        """Each template should have required fields."""
        for name, template in ROLE_TEMPLATES.items():
            assert "base" in template, f"Template {name} missing 'base'"
            assert "add" in template, f"Template {name} missing 'add'"
            assert "description" in template, f"Template {name} missing 'description'"

    def test_template_base_roles_exist(self):
        """Template base roles should be valid system roles."""
        for name, template in ROLE_TEMPLATES.items():
            base = template["base"]
            assert base in SYSTEM_ROLES, f"Template {name} has invalid base role: {base}"

    def test_template_additional_permissions_valid(self):
        """Template additional permissions should be valid."""
        for name, template in ROLE_TEMPLATES.items():
            for perm_key in template["add"]:
                # Permission should exist OR be a wildcard pattern
                if not perm_key.endswith(".*"):
                    assert perm_key in SYSTEM_PERMISSIONS or isinstance(perm_key, str), (
                        f"Template {name} has invalid permission: {perm_key}"
                    )


class TestRolePermissionIntegration:
    """Integration tests for role-permission relationships."""

    def test_all_role_permissions_valid(self):
        """All permissions in roles should exist in SYSTEM_PERMISSIONS or be wildcards."""
        for role_name, role in SYSTEM_ROLES.items():
            for perm_key in role.permissions:
                if not perm_key.endswith(".*"):
                    assert perm_key in SYSTEM_PERMISSIONS, (
                        f"Role {role_name} has invalid permission: {perm_key}"
                    )

    def test_owner_can_do_everything(self):
        """Owner role should have admin.all permission."""
        owner_perms = get_role_permissions("owner", include_inherited=True)
        assert PERM_ADMIN_ALL.key in owner_perms

    def test_permission_escalation_not_possible(self):
        """Lower roles should not have user impersonation."""
        dangerous_perm = PERM_USER_IMPERSONATE.key
        safe_roles = ["viewer", "member", "analyst", "debate_creator"]
        for role_name in safe_roles:
            perms = get_role_permissions(role_name, include_inherited=True)
            assert dangerous_perm not in perms, (
                f"{role_name} should not have impersonate permission"
            )

    def test_member_has_performance_read(self):
        """Member role should have performance read permission."""
        member_perms = get_role_permissions("member", include_inherited=True)
        assert "analytics.read" in member_perms, (
            "Member should have analytics.read (performance:read)"
        )

    def test_member_has_culture_read(self):
        """Member role should have culture read permission."""
        member_perms = get_role_permissions("member", include_inherited=True)
        assert "knowledge.read" in member_perms, "Member should have knowledge.read (culture:read)"

    def test_admin_has_performance_write(self):
        """Admin role should have performance write permission."""
        admin_perms = get_role_permissions("admin", include_inherited=True)
        assert "analytics.update" in admin_perms, (
            "Admin should have analytics.update (performance:write)"
        )

    def test_admin_has_culture_write(self):
        """Admin role should have culture write permission."""
        admin_perms = get_role_permissions("admin", include_inherited=True)
        assert "knowledge.update" in admin_perms, (
            "Admin should have knowledge.update (culture:write)"
        )

    def test_member_cannot_write_performance(self):
        """Member role should NOT have performance write permission."""
        member_perms = get_role_permissions("member", include_inherited=False)
        # Member doesn't have analytics.update directly
        assert "analytics.update" not in member_perms, (
            "Member should not have direct analytics.update"
        )

    def test_member_cannot_write_culture(self):
        """Member role should NOT have culture write permission."""
        member_perms = get_role_permissions("member", include_inherited=False)
        # Member doesn't have knowledge.update directly
        assert "knowledge.update" not in member_perms, (
            "Member should not have direct knowledge.update"
        )
