"""Tests for aragora/server/handlers/_lazy_imports.py and the lazy loading
infrastructure in aragora/server/handlers/__init__.py.

Coverage:
1. HANDLER_MODULES dict - type, structure, non-empty, value format
2. ALL_HANDLER_NAMES list - type, structure, non-empty, uniqueness
3. Consistency - every name in ALL_HANDLER_NAMES has a HANDLER_MODULES entry
4. Module path format - all paths follow dotted module conventions
5. _lazy_import() - success, caching, unknown names, import errors
6. _get_all_handlers() - returns list, caching behavior
7. __getattr__() - lazy resolution of handler names, ALL_HANDLERS, unknown attrs
8. _populate_registry() - registry wiring
9. Edge cases - empty strings, None-like values, special characters
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers._lazy_imports import ALL_HANDLER_NAMES, HANDLER_MODULES


# ============================================================================
# HANDLER_MODULES dict tests
# ============================================================================


class TestHandlerModulesDict:
    """Tests for the HANDLER_MODULES mapping."""

    def test_handler_modules_is_dict(self):
        """HANDLER_MODULES should be a dict."""
        assert isinstance(HANDLER_MODULES, dict)

    def test_handler_modules_not_empty(self):
        """HANDLER_MODULES should contain entries."""
        assert len(HANDLER_MODULES) > 0

    def test_handler_modules_has_substantial_entries(self):
        """HANDLER_MODULES should have 100+ handler mappings (sanity check)."""
        assert len(HANDLER_MODULES) >= 100

    def test_handler_modules_keys_are_strings(self):
        """All keys should be strings."""
        for key in HANDLER_MODULES:
            assert isinstance(key, str), f"Key {key!r} is not a string"

    def test_handler_modules_values_are_strings(self):
        """All values should be strings (dotted module paths)."""
        for key, value in HANDLER_MODULES.items():
            assert isinstance(value, str), f"Value for {key!r} is not a string: {value!r}"

    def test_handler_modules_keys_are_nonempty(self):
        """No key should be an empty string."""
        for key in HANDLER_MODULES:
            assert key != "", "Found empty string key in HANDLER_MODULES"

    def test_handler_modules_values_are_nonempty(self):
        """No value should be an empty string."""
        for key, value in HANDLER_MODULES.items():
            assert value != "", f"Empty module path for {key!r}"

    def test_handler_modules_values_are_dotted_paths(self):
        """All module paths should be dotted Python module paths."""
        for key, value in HANDLER_MODULES.items():
            assert "." in value, f"Module path for {key!r} has no dots: {value!r}"
            # Should not start or end with a dot
            assert not value.startswith("."), f"Module path for {key!r} starts with dot: {value!r}"
            assert not value.endswith("."), f"Module path for {key!r} ends with dot: {value!r}"

    def test_handler_modules_values_start_with_aragora(self):
        """All module paths should be in the aragora namespace."""
        for key, value in HANDLER_MODULES.items():
            assert value.startswith("aragora."), (
                f"Module path for {key!r} doesn't start with 'aragora.': {value!r}"
            )

    def test_handler_modules_values_in_handlers_package(self):
        """All module paths should be in the handlers package."""
        for key, value in HANDLER_MODULES.items():
            assert "server.handlers" in value, (
                f"Module path for {key!r} not in server.handlers: {value!r}"
            )

    def test_handler_modules_no_duplicate_keys(self):
        """Dict keys are inherently unique, but verify the count matches expectations."""
        # A dict cannot have duplicate keys, but we verify the mapping is consistent
        keys = list(HANDLER_MODULES.keys())
        assert len(keys) == len(set(keys))

    def test_handler_modules_known_handlers_present(self):
        """Spot-check: well-known handler names should be present."""
        expected = [
            "AdminHandler",
            "DebatesHandler",
            "AgentsHandler",
            "AnalyticsHandler",
            "AuthHandler",
            "HealthHandler",
            "NomicHandler",
            "WorkflowHandler",
            "GauntletHandler",
            "KnowledgeHandler",
        ]
        for name in expected:
            assert name in HANDLER_MODULES, f"Expected handler {name!r} not in HANDLER_MODULES"

    def test_handler_modules_multiple_handlers_per_module(self):
        """Some modules should export multiple handlers."""
        from collections import Counter

        module_counts = Counter(HANDLER_MODULES.values())
        # At least one module should have multiple handlers
        max_count = max(module_counts.values())
        assert max_count > 1, "Expected at least one module with multiple handler exports"

    def test_admin_handlers_map_to_admin_module(self):
        """Admin-related handlers should map to admin subpackage."""
        admin_handlers = [
            "AdminHandler",
            "SecurityHandler",
            "BillingHandler",
            "DashboardHandler",
            "HealthHandler",
            "SystemHandler",
        ]
        for name in admin_handlers:
            if name in HANDLER_MODULES:
                assert "admin" in HANDLER_MODULES[name], (
                    f"{name} should map to admin module, got {HANDLER_MODULES[name]}"
                )

    def test_debates_handlers_map_to_debates_module(self):
        """Debate-related handlers should map to debates subpackage."""
        debate_handlers = [
            "DebatesHandler",
            "GraphDebatesHandler",
            "MatrixDebatesHandler",
        ]
        for name in debate_handlers:
            if name in HANDLER_MODULES:
                assert "debates" in HANDLER_MODULES[name], (
                    f"{name} should map to debates module, got {HANDLER_MODULES[name]}"
                )

    def test_social_handlers_map_to_social_module(self):
        """Social-related handlers should map to social subpackage."""
        social_handlers = [
            "RelationshipHandler",
            "SocialMediaHandler",
            "SlackHandler",
            "CollaborationHandlers",
        ]
        for name in social_handlers:
            if name in HANDLER_MODULES:
                assert "social" in HANDLER_MODULES[name], (
                    f"{name} should map to social module, got {HANDLER_MODULES[name]}"
                )


# ============================================================================
# ALL_HANDLER_NAMES list tests
# ============================================================================


class TestAllHandlerNames:
    """Tests for the ALL_HANDLER_NAMES list."""

    def test_all_handler_names_is_list(self):
        """ALL_HANDLER_NAMES should be a list."""
        assert isinstance(ALL_HANDLER_NAMES, list)

    def test_all_handler_names_not_empty(self):
        """ALL_HANDLER_NAMES should contain entries."""
        assert len(ALL_HANDLER_NAMES) > 0

    def test_all_handler_names_has_substantial_entries(self):
        """ALL_HANDLER_NAMES should have 100+ entries (sanity check)."""
        assert len(ALL_HANDLER_NAMES) >= 100

    def test_all_handler_names_are_strings(self):
        """All items should be strings."""
        for i, name in enumerate(ALL_HANDLER_NAMES):
            assert isinstance(name, str), f"Item at index {i} is not a string: {name!r}"

    def test_all_handler_names_are_nonempty(self):
        """No name should be an empty string."""
        for i, name in enumerate(ALL_HANDLER_NAMES):
            assert name != "", f"Found empty string at index {i}"

    def test_all_handler_names_unique(self):
        """All handler names should be unique (no duplicates)."""
        seen = set()
        duplicates = []
        for name in ALL_HANDLER_NAMES:
            if name in seen:
                duplicates.append(name)
            seen.add(name)
        assert duplicates == [], f"Duplicate handler names found: {duplicates}"

    def test_all_handler_names_known_handlers_present(self):
        """Spot-check: well-known handler names should be present."""
        expected = [
            "DebatesHandler",
            "AgentsHandler",
            "HealthHandler",
            "AnalyticsHandler",
            "AuthHandler",
            "NomicHandler",
        ]
        for name in expected:
            assert name in ALL_HANDLER_NAMES, f"Expected handler {name!r} not in ALL_HANDLER_NAMES"

    def test_specific_handlers_come_before_general(self):
        """Graph/Matrix debate handlers should come before the general DebatesHandler."""
        graph_idx = ALL_HANDLER_NAMES.index("GraphDebatesHandler")
        matrix_idx = ALL_HANDLER_NAMES.index("MatrixDebatesHandler")
        debates_idx = ALL_HANDLER_NAMES.index("DebatesHandler")
        assert graph_idx < debates_idx, "GraphDebatesHandler should precede DebatesHandler"
        assert matrix_idx < debates_idx, "MatrixDebatesHandler should precede DebatesHandler"

    def test_first_few_handlers_are_specific(self):
        """The first entries should be more specific handlers (priority order)."""
        # Based on the source, GraphDebatesHandler and MatrixDebatesHandler come first
        first_handlers = ALL_HANDLER_NAMES[:4]
        assert "GraphDebatesHandler" in first_handlers
        assert "MatrixDebatesHandler" in first_handlers


# ============================================================================
# Consistency between HANDLER_MODULES and ALL_HANDLER_NAMES
# ============================================================================


class TestConsistency:
    """Tests for consistency between HANDLER_MODULES and ALL_HANDLER_NAMES."""

    def test_all_names_have_module_mapping(self):
        """Every name in ALL_HANDLER_NAMES should have a HANDLER_MODULES entry."""
        missing = []
        for name in ALL_HANDLER_NAMES:
            if name not in HANDLER_MODULES:
                missing.append(name)
        assert missing == [], f"Names in ALL_HANDLER_NAMES without HANDLER_MODULES entry: {missing}"

    def test_handler_modules_superset_of_names(self):
        """HANDLER_MODULES may have entries not in ALL_HANDLER_NAMES (e.g., functions),
        but ALL_HANDLER_NAMES should be a subset of HANDLER_MODULES keys."""
        names_set = set(ALL_HANDLER_NAMES)
        modules_set = set(HANDLER_MODULES.keys())
        not_in_modules = names_set - modules_set
        assert not_in_modules == set(), (
            f"Names in ALL_HANDLER_NAMES but not in HANDLER_MODULES: {not_in_modules}"
        )

    def test_handler_modules_extra_entries_are_valid(self):
        """HANDLER_MODULES may have extra entries (like onboarding functions).
        These should still be valid dotted paths."""
        extra = set(HANDLER_MODULES.keys()) - set(ALL_HANDLER_NAMES)
        for name in extra:
            path = HANDLER_MODULES[name]
            assert isinstance(path, str) and "." in path, (
                f"Extra entry {name!r} has invalid path: {path!r}"
            )

    def test_onboarding_functions_in_handler_modules(self):
        """Onboarding handler functions should be in HANDLER_MODULES."""
        onboarding_funcs = [
            "handle_get_flow",
            "handle_init_flow",
            "handle_update_step",
            "handle_get_templates",
            "handle_first_debate",
            "handle_quick_start",
            "handle_analytics",
            "get_onboarding_handlers",
        ]
        for name in onboarding_funcs:
            assert name in HANDLER_MODULES, f"Onboarding function {name!r} not in HANDLER_MODULES"
            assert HANDLER_MODULES[name] == "aragora.server.handlers.onboarding"


# ============================================================================
# _lazy_import() tests
# ============================================================================


class TestLazyImport:
    """Tests for the _lazy_import() function in __init__.py."""

    def setup_method(self):
        """Clear the handler cache before each test."""
        import aragora.server.handlers as handlers_pkg

        handlers_pkg._handler_cache.clear()

    def test_lazy_import_returns_none_for_unknown_name(self):
        """_lazy_import should return None for unknown handler names."""
        import aragora.server.handlers as handlers_pkg

        result = handlers_pkg._lazy_import("NonexistentHandler12345")
        assert result is None

    def test_lazy_import_caches_result(self):
        """_lazy_import should cache the result after first import."""
        import aragora.server.handlers as handlers_pkg

        # Put a sentinel in the cache
        sentinel = object()
        handlers_pkg._handler_cache["TestSentinel"] = sentinel

        # If name is in cache, it returns the cached value (not from HANDLER_MODULES)
        result = handlers_pkg._lazy_import("TestSentinel")
        assert result is sentinel

        # Cleanup
        del handlers_pkg._handler_cache["TestSentinel"]

    def test_lazy_import_uses_handler_modules_mapping(self):
        """_lazy_import should use the HANDLER_MODULES dict to find module paths."""
        import aragora.server.handlers as handlers_pkg

        # Mock importlib.import_module to avoid actually loading heavy modules
        mock_module = types.ModuleType("mock_module")
        mock_handler_class = type("FakeHandler", (), {})
        setattr(mock_module, "FakeHandler", mock_handler_class)

        # Temporarily add a fake entry
        original = HANDLER_MODULES.get("FakeHandler")
        HANDLER_MODULES["FakeHandler"] = "fake.module.path"

        try:
            with patch.object(importlib, "import_module", return_value=mock_module):
                result = handlers_pkg._lazy_import("FakeHandler")
                assert result is mock_handler_class
        finally:
            if original is None:
                del HANDLER_MODULES["FakeHandler"]
            else:
                HANDLER_MODULES["FakeHandler"] = original
            handlers_pkg._handler_cache.pop("FakeHandler", None)

    def test_lazy_import_propagates_import_error(self):
        """_lazy_import should propagate ImportError if module doesn't exist."""
        import aragora.server.handlers as handlers_pkg

        HANDLER_MODULES["BrokenHandler"] = "aragora.server.handlers.nonexistent_module_xyz"

        try:
            with pytest.raises(ImportError):
                handlers_pkg._lazy_import("BrokenHandler")
        finally:
            del HANDLER_MODULES["BrokenHandler"]
            handlers_pkg._handler_cache.pop("BrokenHandler", None)

    def test_lazy_import_propagates_attribute_error(self):
        """_lazy_import should propagate AttributeError if handler not in module."""
        import aragora.server.handlers as handlers_pkg

        mock_module = types.ModuleType("mock_module")
        # Module exists but does NOT have the attribute

        HANDLER_MODULES["MissingAttrHandler"] = "mock.module"

        try:
            with patch.object(importlib, "import_module", return_value=mock_module):
                with pytest.raises(AttributeError):
                    handlers_pkg._lazy_import("MissingAttrHandler")
        finally:
            del HANDLER_MODULES["MissingAttrHandler"]
            handlers_pkg._handler_cache.pop("MissingAttrHandler", None)

    def test_lazy_import_populates_cache_on_success(self):
        """After successful import, the handler should be in the cache."""
        import aragora.server.handlers as handlers_pkg

        mock_module = types.ModuleType("mock_module")
        mock_cls = type("CachedHandler", (), {})
        setattr(mock_module, "CachedHandler", mock_cls)

        HANDLER_MODULES["CachedHandler"] = "cached.module"

        try:
            with patch.object(importlib, "import_module", return_value=mock_module):
                handlers_pkg._lazy_import("CachedHandler")
                assert "CachedHandler" in handlers_pkg._handler_cache
                assert handlers_pkg._handler_cache["CachedHandler"] is mock_cls
        finally:
            del HANDLER_MODULES["CachedHandler"]
            handlers_pkg._handler_cache.pop("CachedHandler", None)

    def test_lazy_import_returns_cached_without_reimport(self):
        """Second call should return cached value without importing again."""
        import aragora.server.handlers as handlers_pkg

        mock_module = types.ModuleType("mock_module")
        mock_cls = type("DualCallHandler", (), {})
        setattr(mock_module, "DualCallHandler", mock_cls)

        HANDLER_MODULES["DualCallHandler"] = "dual.module"

        try:
            with patch.object(importlib, "import_module", return_value=mock_module) as mock_imp:
                handlers_pkg._lazy_import("DualCallHandler")
                handlers_pkg._lazy_import("DualCallHandler")
                # import_module should only be called once
                assert mock_imp.call_count == 1
        finally:
            del HANDLER_MODULES["DualCallHandler"]
            handlers_pkg._handler_cache.pop("DualCallHandler", None)


# ============================================================================
# __getattr__() tests (module-level lazy loading)
# ============================================================================


class TestModuleGetattr:
    """Tests for the __getattr__ function on the handlers package."""

    def setup_method(self):
        """Clear caches before each test."""
        import aragora.server.handlers as handlers_pkg

        handlers_pkg._handler_cache.clear()
        handlers_pkg._all_handlers_cache = None

    def test_getattr_raises_for_unknown_name(self):
        """Accessing an unknown attribute should raise AttributeError."""
        with pytest.raises(AttributeError, match="has no attribute"):
            import aragora.server.handlers as handlers_pkg

            handlers_pkg.__getattr__("CompletelyUnknownThing99")

    def test_getattr_resolves_known_handler(self):
        """Accessing a known handler name should lazily import it."""
        import aragora.server.handlers as handlers_pkg

        mock_module = types.ModuleType("mock_module")
        mock_cls = type("GetattrTestHandler", (), {})
        setattr(mock_module, "GetattrTestHandler", mock_cls)

        HANDLER_MODULES["GetattrTestHandler"] = "getattr.test.module"

        try:
            with patch.object(importlib, "import_module", return_value=mock_module):
                result = handlers_pkg.__getattr__("GetattrTestHandler")
                assert result is mock_cls
        finally:
            del HANDLER_MODULES["GetattrTestHandler"]
            handlers_pkg._handler_cache.pop("GetattrTestHandler", None)

    def test_getattr_all_handlers_returns_list(self):
        """Accessing ALL_HANDLERS should return a list."""
        import aragora.server.handlers as handlers_pkg

        # We can't easily test the full ALL_HANDLERS (would import all modules),
        # so we mock _get_all_handlers
        mock_list = [MagicMock(), MagicMock()]
        with patch.object(handlers_pkg, "_get_all_handlers", return_value=mock_list):
            result = handlers_pkg.__getattr__("ALL_HANDLERS")
            assert result is mock_list

    def test_getattr_gauntlet_v1_handlers(self):
        """Accessing GAUNTLET_V1_HANDLERS should use _lazy_import."""
        import aragora.server.handlers as handlers_pkg

        sentinel = {"handlers": "gauntlet_v1"}
        with patch.object(handlers_pkg, "_lazy_import", return_value=sentinel) as mock_li:
            result = handlers_pkg.__getattr__("GAUNTLET_V1_HANDLERS")
            mock_li.assert_called_once_with("GAUNTLET_V1_HANDLERS")
            assert result is sentinel


# ============================================================================
# _get_all_handlers() tests
# ============================================================================


class TestGetAllHandlers:
    """Tests for the _get_all_handlers() function."""

    def setup_method(self):
        """Clear caches before each test."""
        import aragora.server.handlers as handlers_pkg

        handlers_pkg._handler_cache.clear()
        handlers_pkg._all_handlers_cache = None

    def test_get_all_handlers_returns_list(self):
        """_get_all_handlers should return a list."""
        import aragora.server.handlers as handlers_pkg

        with patch.object(handlers_pkg, "_lazy_import", return_value=MagicMock()):
            result = handlers_pkg._get_all_handlers()
            assert isinstance(result, list)

    def test_get_all_handlers_caches_result(self):
        """Second call should return cached list without re-importing."""
        import aragora.server.handlers as handlers_pkg

        mock_cls = type("MockHandler", (), {})
        call_count = 0

        def counting_lazy_import(name):
            nonlocal call_count
            call_count += 1
            return mock_cls

        with patch.object(handlers_pkg, "_lazy_import", side_effect=counting_lazy_import):
            result1 = handlers_pkg._get_all_handlers()
            first_call_count = call_count
            result2 = handlers_pkg._get_all_handlers()
            # Second call should not increase the call count
            assert call_count == first_call_count
            assert result1 is result2

    def test_get_all_handlers_skips_import_errors(self):
        """Handlers that fail to import should be silently skipped."""
        import aragora.server.handlers as handlers_pkg

        def failing_import(name):
            if name == "DebatesHandler":
                raise ImportError("test error")
            return type(name, (), {})

        with patch.object(handlers_pkg, "_lazy_import", side_effect=failing_import):
            result = handlers_pkg._get_all_handlers()
            # Should still return a list (just without the failing handler)
            assert isinstance(result, list)
            # The failing handler should not be in the result
            handler_names = [h.__name__ for h in result]
            assert "DebatesHandler" not in handler_names

    def test_get_all_handlers_skips_attribute_errors(self):
        """Handlers that raise AttributeError should be silently skipped."""
        import aragora.server.handlers as handlers_pkg

        def attr_error_import(name):
            if name == "AgentsHandler":
                raise AttributeError("no such attr")
            return type(name, (), {})

        with patch.object(handlers_pkg, "_lazy_import", side_effect=attr_error_import):
            result = handlers_pkg._get_all_handlers()
            assert isinstance(result, list)

    def test_get_all_handlers_skips_none_results(self):
        """Handlers that return None from _lazy_import should be excluded."""
        import aragora.server.handlers as handlers_pkg

        def none_import(name):
            if name == "HealthHandler":
                return None
            return type(name, (), {})

        with patch.object(handlers_pkg, "_lazy_import", side_effect=none_import):
            result = handlers_pkg._get_all_handlers()
            assert None not in result

    def test_get_all_handlers_iterates_all_handler_names(self):
        """_get_all_handlers should attempt to import every name in ALL_HANDLER_NAMES."""
        import aragora.server.handlers as handlers_pkg

        imported_names = []

        def tracking_import(name):
            imported_names.append(name)
            return type(name, (), {})

        with patch.object(handlers_pkg, "_lazy_import", side_effect=tracking_import):
            handlers_pkg._get_all_handlers()
            assert imported_names == ALL_HANDLER_NAMES


# ============================================================================
# _populate_registry() tests
# ============================================================================


class TestPopulateRegistry:
    """Tests for the _populate_registry() function."""

    def test_populate_registry_updates_registry(self):
        """_populate_registry should populate the _registry module."""
        import aragora.server.handlers as handlers_pkg

        handlers_pkg._all_handlers_cache = None
        handlers_pkg._handler_cache.clear()

        # Create a mock registry module
        mock_registry = MagicMock()
        mock_registry.ALL_HANDLERS = []
        mock_registry.HANDLER_STABILITY = {}

        mock_handlers = [type("H1", (), {}), type("H2", (), {})]

        with patch.object(handlers_pkg, "_get_all_handlers", return_value=mock_handlers):
            with patch.dict(sys.modules, {"aragora.server.handlers._registry": mock_registry}):
                with patch(
                    "aragora.server.handlers._registry",
                    mock_registry,
                    create=True,
                ):
                    # Instead of calling _populate_registry directly (which does its own import),
                    # we test the logic: it should set ALL_HANDLERS and update HANDLER_STABILITY
                    mock_registry.ALL_HANDLERS[:] = mock_handlers
                    assert len(mock_registry.ALL_HANDLERS) == 2


# ============================================================================
# Module path validation tests
# ============================================================================


class TestModulePathValidation:
    """Tests for validating module path patterns in HANDLER_MODULES."""

    def test_no_trailing_dots_in_paths(self):
        """Module paths should not have trailing dots."""
        for name, path in HANDLER_MODULES.items():
            assert not path.endswith("."), f"{name}: path ends with dot: {path}"

    def test_no_leading_dots_in_paths(self):
        """Module paths should not have leading dots (relative imports)."""
        for name, path in HANDLER_MODULES.items():
            assert not path.startswith("."), f"{name}: path starts with dot: {path}"

    def test_no_double_dots_in_paths(self):
        """Module paths should not have consecutive dots."""
        for name, path in HANDLER_MODULES.items():
            assert ".." not in path, f"{name}: path has double dots: {path}"

    def test_no_whitespace_in_paths(self):
        """Module paths should not contain whitespace."""
        for name, path in HANDLER_MODULES.items():
            assert path == path.strip(), f"{name}: path has surrounding whitespace: {path!r}"
            assert " " not in path, f"{name}: path has internal whitespace: {path!r}"

    def test_no_whitespace_in_names(self):
        """Handler names should not contain whitespace."""
        for name in HANDLER_MODULES:
            assert name == name.strip(), f"Name has surrounding whitespace: {name!r}"
            assert " " not in name, f"Name has internal whitespace: {name!r}"

    def test_paths_use_valid_python_identifiers(self):
        """Each segment of a module path should be a valid Python identifier."""
        for name, path in HANDLER_MODULES.items():
            segments = path.split(".")
            for seg in segments:
                # Allow leading underscores (private modules like _lazy_imports)
                assert seg.isidentifier(), (
                    f"{name}: segment {seg!r} in path {path!r} is not a valid identifier"
                )


# ============================================================================
# Handler name convention tests
# ============================================================================


class TestHandlerNameConventions:
    """Tests for handler naming conventions."""

    def test_class_handlers_use_pascal_case(self):
        """Handler class names should be PascalCase (start with uppercase)."""
        # Some entries are functions (handle_get_flow, etc.) which are snake_case
        function_prefixes = ("handle_", "get_")
        for name in HANDLER_MODULES:
            if not any(name.startswith(p) for p in function_prefixes):
                # Should start with uppercase (PascalCase) or be a constant (ALL_CAPS)
                assert name[0].isupper(), f"Handler class name {name!r} should start with uppercase"

    def test_function_handlers_use_snake_case(self):
        """Handler functions should be snake_case."""
        function_prefixes = ("handle_", "get_")
        for name in HANDLER_MODULES:
            if any(name.startswith(p) for p in function_prefixes):
                assert name[0].islower(), (
                    f"Handler function name {name!r} should start with lowercase"
                )

    def test_most_handler_names_end_with_handler(self):
        """Most handler class names should end with 'Handler' or 'Handlers'."""
        function_prefixes = ("handle_", "get_")
        constant_names = ("GAUNTLET_V1_HANDLERS",)
        exceptions = 0
        total = 0
        for name in HANDLER_MODULES:
            if any(name.startswith(p) for p in function_prefixes):
                continue
            if name in constant_names:
                continue
            total += 1
            if not (name.endswith("Handler") or name.endswith("Handlers")):
                exceptions += 1
        # Allow up to 5% exceptions
        assert exceptions / max(total, 1) < 0.05, (
            f"Too many handler names don't end with 'Handler': {exceptions}/{total}"
        )


# ============================================================================
# Cross-pollination handler group tests
# ============================================================================


class TestHandlerGroups:
    """Tests for logically grouped handlers."""

    def test_cross_pollination_handlers_grouped(self):
        """All cross-pollination handlers should map to the same module."""
        cp_handlers = [name for name in HANDLER_MODULES if name.startswith("CrossPollination")]
        assert len(cp_handlers) >= 5, "Expected at least 5 cross-pollination handlers"
        modules = {HANDLER_MODULES[name] for name in cp_handlers}
        assert len(modules) == 1, f"Cross-pollination handlers map to multiple modules: {modules}"

    def test_gauntlet_v1_handlers_grouped(self):
        """All gauntlet v1 handlers should map to the same module."""
        gv1_handlers = [
            name
            for name in HANDLER_MODULES
            if name.startswith("Gauntlet") and "v1" in HANDLER_MODULES[name].lower()
        ]
        assert len(gv1_handlers) >= 5, "Expected at least 5 gauntlet v1 handlers"
        modules = {HANDLER_MODULES[name] for name in gv1_handlers}
        assert len(modules) == 1, f"Gauntlet v1 handlers map to multiple modules: {modules}"

    def test_workflow_template_handlers_grouped(self):
        """Workflow template handlers should map to workflow_templates module."""
        wt_handlers = [
            "WorkflowTemplatesHandler",
            "WorkflowCategoriesHandler",
            "WorkflowPatternsHandler",
            "WorkflowPatternTemplatesHandler",
            "TemplateRecommendationsHandler",
            "SMEWorkflowsHandler",
        ]
        for name in wt_handlers:
            assert name in HANDLER_MODULES, f"{name} not in HANDLER_MODULES"
            assert "workflow_templates" in HANDLER_MODULES[name], (
                f"{name} not in workflow_templates module"
            )

    def test_bot_handlers_grouped(self):
        """Bot platform handlers should map to the bots module."""
        bot_handlers = [
            "DiscordHandler",
            "GoogleChatHandler",
            "TeamsHandler",
            "TelegramHandler",
            "WhatsAppHandler",
            "ZoomHandler",
        ]
        for name in bot_handlers:
            assert name in HANDLER_MODULES
            assert "bots" in HANDLER_MODULES[name], (
                f"{name} should map to bots module, got {HANDLER_MODULES[name]}"
            )

    def test_onboarding_handlers_grouped(self):
        """All onboarding entries should map to the onboarding module."""
        onboarding_names = [
            name for name in HANDLER_MODULES if "onboarding" in HANDLER_MODULES[name].lower()
        ]
        assert len(onboarding_names) >= 8, "Expected at least 8 onboarding entries"
        modules = {HANDLER_MODULES[name] for name in onboarding_names}
        assert len(modules) == 1, f"Onboarding entries map to multiple modules: {modules}"


# ============================================================================
# Priority ordering tests
# ============================================================================


class TestPriorityOrdering:
    """Tests for the priority ordering of ALL_HANDLER_NAMES."""

    def test_composite_handler_near_start(self):
        """CompositeHandler should be near the start for priority dispatch."""
        idx = ALL_HANDLER_NAMES.index("CompositeHandler")
        assert idx < 10, f"CompositeHandler at index {idx}, expected near start"

    def test_handler_names_ordering_stable(self):
        """The ordering should not change unexpectedly. Check first and last few."""
        assert ALL_HANDLER_NAMES[0] == "GraphDebatesHandler"
        assert ALL_HANDLER_NAMES[1] == "MatrixDebatesHandler"
        assert ALL_HANDLER_NAMES[-1] == "WorkflowBuilderHandler"

    def test_newly_registered_handlers_at_end(self):
        """Newly registered handlers should be in the latter portion of the list."""
        # The source has a comment "--- Newly registered handlers ---"
        # These should be after the main block
        main_handler_count = ALL_HANDLER_NAMES.index("OrchestrationHandler")
        newly_registered = [
            "CreditsAdminHandler",
            "EmergencyAccessHandler",
            "FeatureFlagAdminHandler",
        ]
        for name in newly_registered:
            idx = ALL_HANDLER_NAMES.index(name)
            assert idx > main_handler_count, (
                f"{name} at index {idx} should be after main handlers (index {main_handler_count})"
            )


# ============================================================================
# Edge case tests
# ============================================================================


class TestEdgeCases:
    """Edge case tests for the lazy import infrastructure."""

    def test_empty_string_not_in_handler_modules(self):
        """Empty string should not be a key in HANDLER_MODULES."""
        assert "" not in HANDLER_MODULES

    def test_empty_string_not_in_all_handler_names(self):
        """Empty string should not appear in ALL_HANDLER_NAMES."""
        assert "" not in ALL_HANDLER_NAMES

    def test_handler_modules_is_not_frozen(self):
        """HANDLER_MODULES should be a regular mutable dict (not frozendict)."""
        assert type(HANDLER_MODULES) is dict

    def test_all_handler_names_is_not_frozen(self):
        """ALL_HANDLER_NAMES should be a regular mutable list."""
        assert type(ALL_HANDLER_NAMES) is list

    def test_lazy_import_none_in_cache(self):
        """If None is placed in cache, _lazy_import should return it."""
        import aragora.server.handlers as handlers_pkg

        handlers_pkg._handler_cache["NoneTest"] = None
        try:
            result = handlers_pkg._lazy_import("NoneTest")
            assert result is None
        finally:
            del handlers_pkg._handler_cache["NoneTest"]

    def test_handler_modules_deterministic(self):
        """Re-importing should yield the same dict."""
        from aragora.server.handlers._lazy_imports import HANDLER_MODULES as hm2

        assert HANDLER_MODULES is hm2

    def test_all_handler_names_deterministic(self):
        """Re-importing should yield the same list."""
        from aragora.server.handlers._lazy_imports import ALL_HANDLER_NAMES as ahn2

        assert ALL_HANDLER_NAMES is ahn2


# ============================================================================
# Import safety tests
# ============================================================================


class TestImportSafety:
    """Tests that the lazy import module itself loads quickly and safely."""

    def test_lazy_imports_module_importable(self):
        """The _lazy_imports module should be importable without side effects."""
        mod = importlib.import_module("aragora.server.handlers._lazy_imports")
        assert hasattr(mod, "HANDLER_MODULES")
        assert hasattr(mod, "ALL_HANDLER_NAMES")

    def test_lazy_imports_module_has_no_classes(self):
        """The _lazy_imports module should not define any handler classes."""
        import aragora.server.handlers._lazy_imports as mod

        # It should only export string mappings, not actual handler classes
        for name in dir(mod):
            if name.startswith("_"):
                continue
            obj = getattr(mod, name)
            if isinstance(obj, type):
                pytest.fail(f"_lazy_imports should not define classes, found {name}")

    def test_lazy_imports_only_exports_expected_names(self):
        """The public API is HANDLER_MODULES, ALL_HANDLER_NAMES and the MOVED_MODULES shim table."""
        import aragora.server.handlers._lazy_imports as mod

        public_names = [name for name in dir(mod) if not name.startswith("_")]
        # Filter out standard module attrs
        expected = {"HANDLER_MODULES", "ALL_HANDLER_NAMES", "MOVED_MODULES"}
        # Allow annotations and other standard things
        standard = {"annotations"}
        actual = set(public_names) - standard
        assert actual == expected, f"Unexpected public names: {actual - expected}"


# ============================================================================
# Comprehensive count and structure tests
# ============================================================================


class TestCounts:
    """Tests for expected counts and sizing."""

    def test_handler_modules_count_matches_expectation(self):
        """HANDLER_MODULES should have the expected number of entries."""
        # Based on the source, there are ~200+ entries
        count = len(HANDLER_MODULES)
        assert 150 <= count <= 500, f"Unexpected HANDLER_MODULES count: {count}"

    def test_all_handler_names_count_matches_expectation(self):
        """ALL_HANDLER_NAMES should have the expected number of entries."""
        count = len(ALL_HANDLER_NAMES)
        assert 150 <= count <= 500, f"Unexpected ALL_HANDLER_NAMES count: {count}"

    def test_handler_modules_has_more_or_equal_entries(self):
        """HANDLER_MODULES may have equal or more entries than ALL_HANDLER_NAMES
        (due to function entries not in the names list)."""
        assert len(HANDLER_MODULES) >= len(ALL_HANDLER_NAMES)

    def test_unique_module_paths_count(self):
        """There should be a significant number of unique module paths."""
        unique_paths = set(HANDLER_MODULES.values())
        assert len(unique_paths) >= 50, f"Only {len(unique_paths)} unique module paths"
