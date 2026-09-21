"""Comprehensive tests for OpenClaw base module.

Covers all exported symbols from aragora/server/handlers/openclaw/_base.py:

Functions:
- _has_permission(role, permission) -> bool
  Permission check helper that delegates to an override on the
  openclaw_gateway module when present, otherwise falls back to the
  canonical has_permission from utils.decorators.

Classes:
- OpenClawMixinBase
  Base class declaring stub methods (_get_user_id, _get_tenant_id,
  get_current_user) that raise NotImplementedError with a descriptive
  message including the class name and MRO.

Test categories:
- _has_permission: default delegation, override delegation, override
  identity check, exception suppression, edge cases
- OpenClawMixinBase: stub methods raise NotImplementedError, error
  message content, subclass behavior, MRO display, __all__ exports
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.openclaw._base import (
    OpenClawMixinBase,
    _has_permission,
)


# ============================================================================
# _has_permission tests
# ============================================================================


class TestHasPermissionDefault:
    """Tests for _has_permission when no gateway override is present."""

    @pytest.fixture(autouse=True)
    def _clear_gateway_module(self):
        saved = sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)
        try:
            yield
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved

    def test_delegates_to_canonical_has_permission(self):
        """When no gateway module override exists, delegates to the canonical function."""
        with patch(
            "aragora.server.handlers.openclaw._base.has_permission",
            return_value=True,
        ) as mock_hp:
            result = _has_permission("admin", "debates:create")
            mock_hp.assert_called_once_with("admin", "debates:create")
            assert result is True

    def test_returns_false_from_canonical(self):
        """Canonical function returning False is propagated."""
        with patch(
            "aragora.server.handlers.openclaw._base.has_permission",
            return_value=False,
        ) as mock_hp:
            result = _has_permission("member", "admin:delete")
            mock_hp.assert_called_once_with("member", "admin:delete")
            assert result is False

    def test_no_gateway_module_loaded(self):
        """When openclaw_gateway module is not in sys.modules, falls back."""
        # Ensure the gateway module is absent
        saved = sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)
        try:
            with patch(
                "aragora.server.handlers.openclaw._base.has_permission",
                return_value=True,
            ) as mock_hp:
                result = _has_permission("owner", "openclaw:manage")
                mock_hp.assert_called_once_with("owner", "openclaw:manage")
                assert result is True
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved

    def test_gateway_module_without_has_permission_attr(self):
        """When gateway module exists but lacks has_permission, uses canonical."""
        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")
        # No has_permission attr on it
        saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module
        try:
            with patch(
                "aragora.server.handlers.openclaw._base.has_permission",
                return_value=False,
            ) as mock_hp:
                result = _has_permission("member", "read")
                mock_hp.assert_called_once_with("member", "read")
                assert result is False
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved
            else:
                sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)


class TestHasPermissionOverride:
    """Tests for _has_permission when gateway provides an override."""

    def _install_override(self, override_fn):
        """Install a fake gateway module with a custom has_permission override."""
        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")
        fake_module.has_permission = override_fn
        self._saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module

    def _restore(self):
        if self._saved is not None:
            sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = self._saved
        else:
            sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)

    def test_override_called_instead_of_canonical(self):
        """When override is present and different from canonical, it is called."""
        override = MagicMock(return_value=True)
        self._install_override(override)
        try:
            result = _has_permission("admin", "sessions:create")
            override.assert_called_once_with("admin", "sessions:create")
            assert result is True
        finally:
            self._restore()

    def test_override_returning_false(self):
        """Override returning False is propagated."""
        override = MagicMock(return_value=False)
        self._install_override(override)
        try:
            result = _has_permission("guest", "sessions:delete")
            override.assert_called_once_with("guest", "sessions:delete")
            assert result is False
        finally:
            self._restore()

    def test_override_same_identity_as_canonical_skips_override(self):
        """When override IS the same object as the module-level has_permission,
        the identity check (override is not has_permission) is False, so the
        override path is skipped and the canonical fallback is used."""
        # Import the actual has_permission from the _base module
        import aragora.server.handlers.openclaw._base as base_mod

        canonical_hp = base_mod.has_permission

        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")
        fake_module.has_permission = canonical_hp  # Same object identity
        saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module
        try:
            # Don't patch has_permission - keep it as the real function so
            # override IS has_permission (same identity) and the check skips
            # We just verify the function returns without going through override
            # by confirming it gives the same result as calling canonical directly
            result = _has_permission("admin", "debates:create")
            expected = canonical_hp("admin", "debates:create")
            assert result == expected
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved
            else:
                sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)

    def test_override_with_empty_role(self):
        """Override is still called with empty role string."""
        override = MagicMock(return_value=False)
        self._install_override(override)
        try:
            result = _has_permission("", "some:perm")
            override.assert_called_once_with("", "some:perm")
            assert result is False
        finally:
            self._restore()

    def test_override_with_none_role(self):
        """Override is still called with None as role."""
        override = MagicMock(return_value=False)
        self._install_override(override)
        try:
            result = _has_permission(None, "some:perm")
            override.assert_called_once_with(None, "some:perm")
            assert result is False
        finally:
            self._restore()


class TestHasPermissionExceptionHandling:
    """Tests for _has_permission exception suppression in shim lookup."""

    def test_import_error_falls_through(self):
        """ImportError during override call falls back to canonical."""
        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")

        def bad_override(role, perm):
            raise ImportError("simulated import error")

        fake_module.has_permission = bad_override
        saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module
        try:
            with patch(
                "aragora.server.handlers.openclaw._base.has_permission",
                return_value=True,
            ) as mock_hp:
                result = _has_permission("admin", "perm")
                mock_hp.assert_called_once_with("admin", "perm")
                assert result is True
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved
            else:
                sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)

    def test_attribute_error_falls_through(self):
        """AttributeError during override call falls back to canonical."""
        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")

        def bad_override(role, perm):
            raise AttributeError("simulated attr error")

        fake_module.has_permission = bad_override
        saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module
        try:
            with patch(
                "aragora.server.handlers.openclaw._base.has_permission",
                return_value=True,
            ) as mock_hp:
                result = _has_permission("admin", "perm")
                mock_hp.assert_called_once_with("admin", "perm")
                assert result is True
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved
            else:
                sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)

    def test_type_error_falls_through(self):
        """TypeError from override call falls back to canonical."""
        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")

        def bad_override(role, perm):
            raise TypeError("bad call")

        fake_module.has_permission = bad_override
        saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module
        try:
            # The TypeError is raised by the override *call*, not the shim lookup.
            # The except clause catches ImportError, AttributeError, TypeError, KeyError
            # but only around the lookup section, not the call. Let's verify behavior:
            # The try block includes the override call: `return override(role, permission)`
            # So TypeError from override IS caught.
            with patch(
                "aragora.server.handlers.openclaw._base.has_permission",
                return_value=True,
            ) as mock_hp:
                result = _has_permission("admin", "perm")
                mock_hp.assert_called_once_with("admin", "perm")
                assert result is True
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved
            else:
                sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)

    def test_debug_log_on_exception(self, caplog):
        """Exception during shim lookup emits a debug log."""
        fake_module = types.ModuleType("aragora.server.handlers.openclaw.openclaw_gateway")

        def bad_override(role, perm):
            raise TypeError("test type err")

        fake_module.has_permission = bad_override
        saved = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = fake_module
        try:
            with patch(
                "aragora.server.handlers.openclaw._base.has_permission",
                return_value=True,
            ):
                with caplog.at_level(
                    logging.DEBUG, logger="aragora.server.handlers.openclaw._base"
                ):
                    _has_permission("admin", "perm")
                    assert any("Permission shim lookup failed" in r.message for r in caplog.records)
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = saved
            else:
                sys.modules.pop("aragora.server.handlers.openclaw.openclaw_gateway", None)


# ============================================================================
# OpenClawMixinBase tests
# ============================================================================


class TestOpenClawMixinBaseGetUserId:
    """Tests for OpenClawMixinBase._get_user_id stub."""

    def test_raises_not_implemented(self):
        """Calling _get_user_id raises NotImplementedError."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError):
            base._get_user_id(MagicMock())

    def test_error_includes_class_name(self):
        """Error message includes the class name."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="OpenClawMixinBase._get_user_id"):
            base._get_user_id(MagicMock())

    def test_error_mentions_parent_class(self):
        """Error message mentions OpenClawGatewayHandler as expected parent."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="OpenClawGatewayHandler"):
            base._get_user_id(MagicMock())

    def test_error_includes_mro(self):
        """Error message includes MRO information."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="Current MRO"):
            base._get_user_id(MagicMock())

    def test_subclass_error_shows_subclass_name(self):
        """When called on a subclass, error message shows the subclass name."""

        class MyMixin(OpenClawMixinBase):
            pass

        mixin = MyMixin()
        with pytest.raises(NotImplementedError, match="MyMixin._get_user_id"):
            mixin._get_user_id(MagicMock())


class TestOpenClawMixinBaseGetTenantId:
    """Tests for OpenClawMixinBase._get_tenant_id stub."""

    def test_raises_not_implemented(self):
        """Calling _get_tenant_id raises NotImplementedError."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError):
            base._get_tenant_id(MagicMock())

    def test_error_includes_class_name(self):
        """Error message includes the class name."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="OpenClawMixinBase._get_tenant_id"):
            base._get_tenant_id(MagicMock())

    def test_error_mentions_parent_class(self):
        """Error message mentions OpenClawGatewayHandler as expected parent."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="OpenClawGatewayHandler"):
            base._get_tenant_id(MagicMock())

    def test_subclass_error_shows_subclass_name(self):
        """When called on a subclass, error message shows the subclass name."""

        class TenantMixin(OpenClawMixinBase):
            pass

        mixin = TenantMixin()
        with pytest.raises(NotImplementedError, match="TenantMixin._get_tenant_id"):
            mixin._get_tenant_id(MagicMock())


class TestOpenClawMixinBaseGetCurrentUser:
    """Tests for OpenClawMixinBase.get_current_user stub."""

    def test_raises_not_implemented(self):
        """Calling get_current_user raises NotImplementedError."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError):
            base.get_current_user(MagicMock())

    def test_error_includes_class_name(self):
        """Error message includes the class name."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="OpenClawMixinBase.get_current_user"):
            base.get_current_user(MagicMock())

    def test_error_mentions_parent_class(self):
        """Error message mentions OpenClawGatewayHandler as expected parent."""
        base = OpenClawMixinBase()
        with pytest.raises(NotImplementedError, match="OpenClawGatewayHandler"):
            base.get_current_user(MagicMock())

    def test_subclass_error_shows_subclass_name(self):
        """When called on a subclass, error message shows the subclass name."""

        class UserMixin(OpenClawMixinBase):
            pass

        mixin = UserMixin()
        with pytest.raises(NotImplementedError, match="UserMixin.get_current_user"):
            mixin.get_current_user(MagicMock())


class TestOpenClawMixinBaseSubclassing:
    """Tests for OpenClawMixinBase subclassing and override behavior."""

    def test_subclass_can_override_get_user_id(self):
        """Subclass can override _get_user_id without error."""

        class MyHandler(OpenClawMixinBase):
            def _get_user_id(self, handler: Any) -> str:
                return "user-123"

        h = MyHandler()
        assert h._get_user_id(MagicMock()) == "user-123"

    def test_subclass_can_override_get_tenant_id(self):
        """Subclass can override _get_tenant_id without error."""

        class MyHandler(OpenClawMixinBase):
            def _get_tenant_id(self, handler: Any) -> str | None:
                return "tenant-456"

        h = MyHandler()
        assert h._get_tenant_id(MagicMock()) == "tenant-456"

    def test_subclass_can_override_get_current_user(self):
        """Subclass can override get_current_user without error."""

        class MyHandler(OpenClawMixinBase):
            def get_current_user(self, handler: Any) -> Any:
                return {"id": "u1", "role": "admin"}

        h = MyHandler()
        assert h.get_current_user(MagicMock()) == {"id": "u1", "role": "admin"}

    def test_partial_override_still_raises_for_unimplemented(self):
        """A subclass overriding only one method still raises for the others."""

        class PartialHandler(OpenClawMixinBase):
            def _get_user_id(self, handler: Any) -> str:
                return "user-ok"

        h = PartialHandler()
        assert h._get_user_id(MagicMock()) == "user-ok"
        with pytest.raises(NotImplementedError, match="PartialHandler._get_tenant_id"):
            h._get_tenant_id(MagicMock())
        with pytest.raises(NotImplementedError, match="PartialHandler.get_current_user"):
            h.get_current_user(MagicMock())

    def test_diamond_inheritance_mro(self):
        """MRO is displayed correctly in diamond inheritance."""

        class MixinA(OpenClawMixinBase):
            pass

        class MixinB(OpenClawMixinBase):
            pass

        class Combined(MixinA, MixinB):
            pass

        c = Combined()
        with pytest.raises(NotImplementedError) as exc_info:
            c._get_user_id(MagicMock())
        msg = str(exc_info.value)
        assert "Combined" in msg
        assert "MixinA" in msg


class TestModuleExports:
    """Tests for __all__ exports."""

    def test_all_exports(self):
        """__all__ exports exactly the expected symbols."""
        from aragora.server.handlers.openclaw._base import __all__

        assert set(__all__) == {"OpenClawMixinBase", "_has_permission"}

    def test_openclaw_mixin_base_is_a_class(self):
        """OpenClawMixinBase is a class."""
        assert isinstance(OpenClawMixinBase, type)

    def test_has_permission_is_callable(self):
        """_has_permission is callable."""
        assert callable(_has_permission)
