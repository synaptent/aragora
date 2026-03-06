"""Integration tests for Handler Registration system.

Tests the handler registration, routing, and validation system including:
- HANDLER_REGISTRY completeness and correctness
- RouteIndex O(1) lookup functionality
- Handler validation functions
- Handler initialization and lifecycle
- API versioning support
"""

import pytest
from unittest.mock import MagicMock, patch
import json

from aragora.server.handler_registry.core import _DeferredImport


def _resolve(handler_class):
    """Resolve _DeferredImport proxies to actual handler classes."""
    if isinstance(handler_class, _DeferredImport):
        return handler_class.resolve()
    return handler_class


class TestHandlerRegistry:
    """Test HANDLER_REGISTRY configuration."""

    def test_handler_registry_not_empty(self):
        """HANDLER_REGISTRY should contain handlers."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        assert len(HANDLER_REGISTRY) > 0
        assert len(HANDLER_REGISTRY) >= 50  # Should have 55+ handlers

    def test_handler_registry_format(self):
        """Each entry should be (attr_name, handler_class) tuple."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        for entry in HANDLER_REGISTRY:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            attr_name, handler_class = entry
            assert isinstance(attr_name, str)
            assert attr_name.startswith("_")
            assert attr_name.endswith("_handler")

    def test_handler_registry_unique_attr_names(self):
        """Attribute names should be unique."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        attr_names = [attr for attr, _ in HANDLER_REGISTRY]
        assert len(attr_names) == len(set(attr_names))

    def test_handlers_available_flag(self):
        """HANDLERS_AVAILABLE should be True when handlers import."""
        from aragora.server.handler_registry import HANDLERS_AVAILABLE

        # In a properly configured environment, handlers should be available
        assert HANDLERS_AVAILABLE is True

    def test_handler_classes_are_valid(self):
        """Handler classes should have required methods."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        for attr_name, handler_class in HANDLER_REGISTRY:
            if handler_class is None:
                continue

            handler_class = _resolve(handler_class)
            if handler_class is None:
                continue

            # Handlers use varied dispatch patterns:
            # - can_handle + handle (standard BaseHandler)
            # - routes/ROUTES + handle (SSO-style)
            # - handle_* methods (cost, voice, inbox)
            # - register_routes (alert, autonomous)
            # - ROUTES only (facade handlers for OpenAPI discovery)
            has_handle = hasattr(handler_class, "handle")
            has_handle_methods = any(
                attr.startswith("handle_")
                for attr in dir(handler_class)
                if not attr.startswith("__")
            )
            has_register = hasattr(handler_class, "register_routes")
            has_routes_only = hasattr(handler_class, "ROUTES")

            assert has_handle or has_handle_methods or has_register or has_routes_only, (
                f"{attr_name} missing handle, handle_*, register_routes, or ROUTES"
            )


class TestRouteIndex:
    """Test RouteIndex O(1) lookup functionality."""

    def test_route_index_creation(self):
        """RouteIndex should be creatable."""
        from aragora.server.handler_registry import RouteIndex

        index = RouteIndex()
        assert index is not None
        assert hasattr(index, "_exact_routes")
        assert hasattr(index, "_prefix_routes")

    def test_get_route_index_singleton(self):
        """get_route_index should return the same instance."""
        from aragora.server.handler_registry import get_route_index

        index1 = get_route_index()
        index2 = get_route_index()
        assert index1 is index2

    def test_route_index_exact_path_lookup(self):
        """Exact paths should be O(1) lookup."""
        from aragora.server.handler_registry import RouteIndex

        index = RouteIndex()

        # Add a test route directly
        mock_handler = MagicMock()
        index._exact_routes["/api/test"] = ("_test_handler", mock_handler)

        result = index.get_handler("/api/test")
        assert result is not None
        attr_name, handler = result
        assert attr_name == "_test_handler"
        assert handler is mock_handler

    def test_route_index_prefix_matching(self):
        """Prefix patterns should match dynamic routes."""
        from aragora.server.handler_registry import RouteIndex

        index = RouteIndex()

        # Add a prefix route
        mock_handler = MagicMock()
        mock_handler.can_handle = MagicMock(return_value=True)
        index._prefix_routes.append(("/api/prefix/", "_test_handler", mock_handler))

        # Clear LRU cache before test
        index._get_handler_cached.cache_clear()

        result = index.get_handler("/api/prefix/123")
        assert result is not None
        attr_name, handler = result
        assert attr_name == "_test_handler"

    def test_route_index_no_match(self):
        """Non-matching paths should return None."""
        from aragora.server.handler_registry import RouteIndex

        index = RouteIndex()
        index._get_handler_cached.cache_clear()

        result = index.get_handler("/api/nonexistent/path")
        assert result is None

    def test_notification_templates_dynamic_routes_resolve_before_generic_notifications(self):
        """Template detail/reset/preview routes must not fall through to generic notifications."""
        from aragora.server.handler_registry import RouteIndex
        from aragora.server.handlers.notifications.templates import NotificationTemplatesHandler
        from aragora.server.handlers.social.notifications import NotificationsHandler

        class StubRegistry:
            _notifications_handler = NotificationsHandler({})
            _notification_templates_handler = NotificationTemplatesHandler({})

        index = RouteIndex()
        index.build(
            StubRegistry,
            [
                ("_notifications_handler", NotificationsHandler),
                ("_notification_templates_handler", NotificationTemplatesHandler),
            ],
        )

        for path in (
            "/api/v1/notifications/templates/debate_completed",
            "/api/v1/notifications/templates/debate_completed/reset",
            "/api/v1/notifications/templates/debate_completed/preview",
        ):
            result = index.get_handler(path)
            assert result is not None
            attr_name, _handler = result
            assert attr_name == "_notification_templates_handler"


class TestHandlerValidation:
    """Test handler validation functions."""

    def test_validate_handler_class_valid(self):
        """validate_handler_class should pass for valid handlers."""
        from aragora.server.handler_registry import validate_handler_class

        class ValidHandler:
            ROUTES = ["/api/valid"]

            @classmethod
            def can_handle(cls, path):
                return path.startswith("/api/valid")

            def handle(self, path, query, request_handler):
                return None

        errors = validate_handler_class(ValidHandler, "ValidHandler")
        assert len(errors) == 0

    def test_validate_handler_class_missing_methods(self):
        """validate_handler_class should detect missing methods."""
        from aragora.server.handler_registry import validate_handler_class

        class InvalidHandler:
            pass

        errors = validate_handler_class(InvalidHandler, "InvalidHandler")
        assert len(errors) > 0
        assert any("can_handle" in e for e in errors)
        assert any("handle" in e for e in errors)

    def test_validate_handler_class_none(self):
        """validate_handler_class should handle None handler."""
        from aragora.server.handler_registry import validate_handler_class

        errors = validate_handler_class(None, "NoneHandler")
        assert len(errors) > 0
        assert any("None" in e for e in errors)

    def test_validate_handler_instance_valid(self):
        """validate_handler_instance should pass for valid instances."""
        from aragora.server.handler_registry import validate_handler_instance

        class ValidHandler:
            def can_handle(self, path):
                return False

            def handle(self, path, query, request_handler):
                return None

        instance = ValidHandler()
        errors = validate_handler_instance(instance, "ValidHandler")
        assert len(errors) == 0

    def test_validate_handler_instance_broken_can_handle(self):
        """validate_handler_instance should detect broken can_handle."""
        from aragora.server.handler_registry import validate_handler_instance

        class BrokenHandler:
            def can_handle(self, path):
                raise RuntimeError("Broken!")

            def handle(self, path, query, request_handler):
                return None

        instance = BrokenHandler()
        errors = validate_handler_instance(instance, "BrokenHandler")
        assert len(errors) > 0
        assert any("exception" in e.lower() for e in errors)

    def test_validate_all_handlers(self):
        """validate_all_handlers should check all registry entries."""
        from aragora.server.handler_registry import (
            HANDLER_REGISTRY,
            HANDLERS_AVAILABLE,
            validate_all_handlers,
        )

        # Resolve deferred imports before validation
        resolved_registry = [(name, _resolve(cls)) for name, cls in HANDLER_REGISTRY]

        results = validate_all_handlers(
            handler_registry=resolved_registry,
            handlers_available=HANDLERS_AVAILABLE,
            raise_on_error=False,
        )

        assert "valid" in results
        assert "invalid" in results
        assert "missing" in results
        assert "status" in results

        # Most handlers should be valid
        assert len(results["valid"]) > 40


class TestHandlerRegistryMixin:
    """Test HandlerRegistryMixin functionality."""

    def test_mixin_has_handler_attributes(self):
        """Mixin should define core handler infrastructure."""
        from aragora.server.handler_registry import HandlerRegistryMixin

        # Check core mixin infrastructure
        assert hasattr(HandlerRegistryMixin, "_init_handlers")
        assert hasattr(HandlerRegistryMixin, "_try_modular_handler")
        assert hasattr(HandlerRegistryMixin, "_handlers_initialized")
        assert hasattr(HandlerRegistryMixin, "_get_handler_stats")

    def test_mixin_init_handlers_method(self):
        """Mixin should have _init_handlers method."""
        from aragora.server.handler_registry import HandlerRegistryMixin

        assert hasattr(HandlerRegistryMixin, "_init_handlers")
        assert callable(HandlerRegistryMixin._init_handlers)

    def test_mixin_try_modular_handler_method(self):
        """Mixin should have _try_modular_handler method."""
        from aragora.server.handler_registry import HandlerRegistryMixin

        assert hasattr(HandlerRegistryMixin, "_try_modular_handler")

    def test_get_handler_stats_uninitialized(self):
        """_get_handler_stats should work when uninitialized."""
        from aragora.server.handler_registry import HandlerRegistryMixin

        class TestMixin(HandlerRegistryMixin):
            pass

        mixin = TestMixin()
        mixin._handlers_initialized = False

        stats = mixin._get_handler_stats()

        assert stats["initialized"] is False
        assert stats["count"] == 0
        assert stats["handlers"] == []


class TestAPIVersioning:
    """Test API versioning support in routing."""

    def test_version_extraction(self):
        """Version should be extracted from paths."""
        from aragora.server.versioning import extract_version
        from aragora.server.versioning.router import APIVersion

        version, is_legacy = extract_version("/api/v1/debates", {})
        assert version == APIVersion.V1
        assert is_legacy is False

    def test_version_strip_prefix(self):
        """Version prefix should be stripped for handler matching."""
        from aragora.server.versioning import strip_version_prefix

        normalized = strip_version_prefix("/api/v1/debates")
        assert normalized == "/api/debates"

        # Non-versioned paths should be unchanged
        normalized = strip_version_prefix("/api/debates")
        assert normalized == "/api/debates"

    def test_version_response_headers(self):
        """Version headers should be generated."""
        from aragora.server.versioning import version_response_headers
        from aragora.server.versioning.router import APIVersion

        headers = version_response_headers(APIVersion.V1, False)
        assert "X-API-Version" in headers
        assert headers["X-API-Version"] == "v1"


class TestHandlerCanHandlePaths:
    """Test that handlers correctly implement can_handle."""

    def test_health_handler_paths(self):
        """HealthHandler should handle health paths."""
        from aragora.server.handler_registry import HealthHandler

        handler = _resolve(HealthHandler)({})

        assert handler.can_handle("/healthz")
        assert handler.can_handle("/readyz")
        assert handler.can_handle("/api/v1/health")
        assert not handler.can_handle("/api/v1/debates")

    def test_debates_handler_paths(self):
        """DebatesHandler should handle debate paths."""
        from aragora.server.handler_registry import DebatesHandler

        handler = _resolve(DebatesHandler)({})

        assert handler.can_handle("/api/v1/debates")
        assert handler.can_handle("/api/v1/debates/123")
        assert handler.can_handle("/api/v1/search")
        assert not handler.can_handle("/api/v1/agents")

    def test_control_plane_handler_paths(self):
        """ControlPlaneHandler should handle control plane paths."""
        from aragora.server.handlers.control_plane import ControlPlaneHandler

        handler = ControlPlaneHandler({})

        assert handler.can_handle("/api/v1/control-plane/agents")
        assert handler.can_handle("/api/v1/control-plane/tasks")
        assert handler.can_handle("/api/v1/control-plane/health")
        assert handler.can_handle("/api/v1/control-plane/queue")
        assert handler.can_handle("/api/v1/control-plane/metrics")
        assert not handler.can_handle("/api/v1/debates")


class TestHandlerRoutes:
    """Test handler ROUTES attribute."""

    def test_handlers_have_routes(self):
        """Handlers should define ROUTES for exact matching."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        handlers_with_routes = 0

        for attr_name, handler_class in HANDLER_REGISTRY:
            if handler_class is None:
                continue

            handler_class = _resolve(handler_class)
            if handler_class is None:
                continue

            if hasattr(handler_class, "ROUTES"):
                routes = handler_class.ROUTES
                # ROUTES can be a list, tuple, or dict (mapping paths to method names)
                assert isinstance(routes, (list, tuple, dict)), (
                    f"{attr_name} ROUTES is {type(routes)}"
                )
                handlers_with_routes += 1

        # Most handlers should have ROUTES defined
        assert handlers_with_routes > 30

    def test_routes_are_valid_paths(self):
        """ROUTES entries should be valid API paths."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        for attr_name, handler_class in HANDLER_REGISTRY:
            if handler_class is None:
                continue

            handler_class = _resolve(handler_class)
            if handler_class is None:
                continue

            routes = getattr(handler_class, "ROUTES", [])
            for route in routes:
                # Routes can be strings ("/path" or "METHOD /path") or
                # tuples (method, path, handler_name)
                if isinstance(route, (tuple, list)):
                    path = route[1] if len(route) >= 2 else route[0]
                elif isinstance(route, str):
                    path = route.split(" ", 1)[-1] if " " in route else route
                else:
                    pytest.fail(f"{attr_name} route has unexpected type: {type(route)}")
                assert path.startswith("/"), (
                    f"{attr_name} route '{route}' path doesn't start with /"
                )


class TestTierFiltering:
    """Test handler tier filtering logic."""

    def test_get_active_tiers_default(self):
        """Default tiers should include all for backward compatibility."""
        from aragora.server.handler_registry.core import get_active_tiers

        with patch.dict("os.environ", {}, clear=True):
            tiers = get_active_tiers()

        assert "core" in tiers
        assert "extended" in tiers
        assert "optional" in tiers
        assert "enterprise" in tiers
        assert "experimental" in tiers

    def test_get_active_tiers_explicit_filter(self):
        """Explicit ARAGORA_HANDLER_TIERS should filter tiers."""
        from aragora.server.handler_registry.core import get_active_tiers

        with patch.dict("os.environ", {"ARAGORA_HANDLER_TIERS": "extended,optional"}, clear=True):
            tiers = get_active_tiers()

        assert "core" in tiers  # Always included
        assert "extended" in tiers
        assert "optional" in tiers
        assert "enterprise" not in tiers
        assert "experimental" not in tiers

    def test_get_active_tiers_core_always_included(self):
        """Core tier is always included even when not listed."""
        from aragora.server.handler_registry.core import get_active_tiers

        with patch.dict("os.environ", {"ARAGORA_HANDLER_TIERS": "enterprise"}, clear=True):
            tiers = get_active_tiers()

        assert "core" in tiers
        assert "enterprise" in tiers
        assert "extended" not in tiers

    def test_get_active_tiers_enterprise_flag(self):
        """ARAGORA_ENTERPRISE=1 should enable enterprise tier."""
        from aragora.server.handler_registry.core import get_active_tiers

        with patch.dict("os.environ", {"ARAGORA_ENTERPRISE": "1"}, clear=True):
            tiers = get_active_tiers()

        assert "enterprise" in tiers
        assert "core" in tiers

    def test_get_active_tiers_experimental_flag(self):
        """ARAGORA_EXPERIMENTAL=true should enable experimental tier."""
        from aragora.server.handler_registry.core import get_active_tiers

        with patch.dict("os.environ", {"ARAGORA_EXPERIMENTAL": "true"}, clear=True):
            tiers = get_active_tiers()

        assert "experimental" in tiers
        assert "core" in tiers

    def test_get_active_tiers_whitespace_handling(self):
        """Whitespace in tier list should be stripped."""
        from aragora.server.handler_registry.core import get_active_tiers

        with patch.dict("os.environ", {"ARAGORA_HANDLER_TIERS": " core , extended , "}, clear=True):
            tiers = get_active_tiers()

        assert "core" in tiers
        assert "extended" in tiers
        assert "" not in tiers

    def test_filter_registry_by_tier_core_only(self):
        """Core-only filter should exclude non-core handlers."""
        from aragora.server.handler_registry.core import filter_registry_by_tier

        registry = [
            ("_health_handler", MagicMock()),  # core
            ("_genesis_handler", MagicMock()),  # experimental
            ("_admin_handler", MagicMock()),  # enterprise
            ("_belief_handler", MagicMock()),  # extended
        ]

        filtered = filter_registry_by_tier(registry, active_tiers={"core"})

        attr_names = [name for name, _ in filtered]
        assert "_health_handler" in attr_names
        assert "_genesis_handler" not in attr_names
        assert "_admin_handler" not in attr_names
        assert "_belief_handler" not in attr_names

    def test_filter_registry_by_tier_unknown_defaults_to_extended(self):
        """Handlers not in HANDLER_TIERS should default to 'extended'."""
        from aragora.server.handler_registry.core import filter_registry_by_tier

        registry = [
            ("_unknown_handler", MagicMock()),  # not in HANDLER_TIERS → defaults to extended
        ]

        filtered = filter_registry_by_tier(registry, active_tiers={"extended"})
        assert len(filtered) == 1

        filtered = filter_registry_by_tier(registry, active_tiers={"core"})
        assert len(filtered) == 0

    def test_filter_registry_preserves_order(self):
        """Filtering should preserve registry order."""
        from aragora.server.handler_registry.core import filter_registry_by_tier

        registry = [
            ("_health_handler", MagicMock()),  # core
            ("_debates_handler", MagicMock()),  # core
            ("_agents_handler", MagicMock()),  # core
        ]

        filtered = filter_registry_by_tier(registry, active_tiers={"core"})
        names = [name for name, _ in filtered]
        assert names == ["_health_handler", "_debates_handler", "_agents_handler"]

    def test_filter_registry_enterprise_excluded_by_default_tier_env(self):
        """Enterprise handlers excluded when only core+extended tiers active."""
        from aragora.server.handler_registry.core import filter_registry_by_tier

        registry = [
            ("_health_handler", MagicMock()),  # core
            ("_admin_handler", MagicMock()),  # enterprise
            ("_gateway_handler", MagicMock()),  # optional
        ]

        filtered = filter_registry_by_tier(registry, active_tiers={"core", "extended", "optional"})
        names = [name for name, _ in filtered]
        assert "_health_handler" in names
        assert "_gateway_handler" in names
        assert "_admin_handler" not in names

    def test_handler_tiers_all_valid(self):
        """All HANDLER_TIERS values should be valid tier names."""
        from aragora.server.handler_registry.core import HANDLER_TIERS

        valid_tiers = {"core", "extended", "enterprise", "experimental", "optional"}
        for attr_name, tier in HANDLER_TIERS.items():
            assert tier in valid_tiers, f"{attr_name} has invalid tier '{tier}'"

    def test_handler_tiers_covers_core_handlers(self):
        """Core handlers should be listed in HANDLER_TIERS."""
        from aragora.server.handler_registry.core import HANDLER_TIERS

        core_handlers = [k for k, v in HANDLER_TIERS.items() if v == "core"]
        assert len(core_handlers) >= 5, "Should have at least 5 core handlers"
        assert "_health_handler" in core_handlers
        assert "_debates_handler" in core_handlers


class TestHandlerInstantiation:
    """Test handler instantiation with context."""

    def test_handlers_accept_context(self):
        """Handlers should accept context dict."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        ctx = {
            "storage": None,
            "elo_system": None,
            "debate_embeddings": None,
            "document_store": None,
            "nomic_dir": None,
        }

        instantiated = 0

        for attr_name, handler_class in HANDLER_REGISTRY:
            if handler_class is None:
                continue

            handler_class = _resolve(handler_class)
            if handler_class is None:
                continue

            try:
                handler = handler_class(ctx)
                assert handler is not None
                instantiated += 1
            except Exception as e:
                # Some handlers may require specific context
                pass

        # Most handlers should instantiate without errors
        assert instantiated > 40

    def test_handler_has_ctx_attribute(self):
        """Instantiated handlers should have ctx attribute."""
        from aragora.server.handler_registry import HealthHandler

        ctx = {"storage": None}
        handler = _resolve(HealthHandler)(ctx)

        assert hasattr(handler, "ctx")
        assert handler.ctx == ctx


class TestHandlerValidationError:
    """Test HandlerValidationError exception."""

    def test_validation_error_raised(self):
        """validate_all_handlers should raise on error when requested."""
        from aragora.server.handler_registry import (
            HandlerValidationError,
            validate_all_handlers,
        )

        # With a mock registry that has missing handlers
        mock_registry = [("_test_handler", None)]
        with pytest.raises(HandlerValidationError):
            validate_all_handlers(
                handler_registry=mock_registry,
                handlers_available=True,
                raise_on_error=True,
            )


class TestKnowledgeHandler:
    """Test KnowledgeHandler registration and paths."""

    def test_knowledge_handler_registered(self):
        """KnowledgeHandler should be in registry."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        handler_names = [attr for attr, _ in HANDLER_REGISTRY]
        assert "_knowledge_handler" in handler_names

    def test_knowledge_handler_paths(self):
        """KnowledgeHandler should handle knowledge paths."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})

        # KnowledgeHandler handles these specific routes
        assert handler.can_handle("/api/v1/knowledge/facts")
        assert handler.can_handle("/api/v1/knowledge/stats")
        assert handler.can_handle("/api/v1/knowledge/query")
        assert handler.can_handle("/api/v1/knowledge/search")
        assert not handler.can_handle("/api/v1/debates")


class TestWorkflowHandler:
    """Test WorkflowHandler registration and paths."""

    def test_workflow_handler_registered(self):
        """WorkflowHandler should be in registry."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        handler_names = [attr for attr, _ in HANDLER_REGISTRY]
        assert "_workflow_handler" in handler_names

    def test_workflow_handler_exists(self):
        """WorkflowHandler should be importable."""
        from aragora.server.handlers.workflows.handler import WorkflowHandler

        assert WorkflowHandler is not None


class TestFeaturesHandler:
    """Test FeaturesHandler registration and paths."""

    def test_features_handler_registered(self):
        """FeaturesHandler should be in registry."""
        from aragora.server.handler_registry import HANDLER_REGISTRY

        handler_names = [attr for attr, _ in HANDLER_REGISTRY]
        assert "_features_handler" in handler_names

    def test_features_handler_paths(self):
        """FeaturesHandler should handle features paths."""
        from aragora.server.handlers.features.features import FeaturesHandler

        handler = FeaturesHandler({})

        assert handler.can_handle("/api/v1/features")
        assert not handler.can_handle("/api/v1/debates")

        assert handler.can_handle("/api/v1/features")
        assert not handler.can_handle("/api/v1/debates")
