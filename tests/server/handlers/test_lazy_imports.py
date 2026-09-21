"""
Tests for aragora.server.handlers._lazy_imports.

Tests cover:
1. HANDLER_MODULES mapping integrity and consistency
2. ALL_HANDLER_NAMES list integrity
3. Every handler in ALL_HANDLER_NAMES has a corresponding module mapping
4. Module path format validation
5. No duplicate handler names
"""

from __future__ import annotations

import pytest

from aragora.server.handlers._lazy_imports import (
    ALL_HANDLER_NAMES,
    HANDLER_MODULES,
)


class TestHandlerModules:
    """Test the HANDLER_MODULES mapping."""

    def test_is_dict(self):
        assert isinstance(HANDLER_MODULES, dict)

    def test_not_empty(self):
        assert len(HANDLER_MODULES) > 0

    def test_all_keys_are_strings(self):
        for key in HANDLER_MODULES:
            assert isinstance(key, str), f"Key {key!r} is not a string"

    def test_all_values_are_strings(self):
        for key, value in HANDLER_MODULES.items():
            assert isinstance(value, str), f"Value for {key!r} is not a string: {value!r}"

    def test_all_module_paths_start_with_aragora(self):
        """All module paths should be within the aragora package."""
        for handler_name, module_path in HANDLER_MODULES.items():
            assert module_path.startswith("aragora."), (
                f"Module path for {handler_name!r} does not start with 'aragora.': {module_path!r}"
            )

    def test_all_module_paths_are_dotted(self):
        """Module paths should use dot notation."""
        for handler_name, module_path in HANDLER_MODULES.items():
            assert "." in module_path, (
                f"Module path for {handler_name!r} has no dots: {module_path!r}"
            )

    def test_no_trailing_dots_in_module_paths(self):
        for handler_name, module_path in HANDLER_MODULES.items():
            assert not module_path.endswith("."), (
                f"Module path for {handler_name!r} has trailing dot: {module_path!r}"
            )

    def test_no_leading_dots_in_module_paths(self):
        for handler_name, module_path in HANDLER_MODULES.items():
            assert not module_path.startswith("."), (
                f"Module path for {handler_name!r} has leading dot: {module_path!r}"
            )

    def test_contains_core_handlers(self):
        """Core handler names should be present."""
        core_handlers = [
            "DebatesHandler",
            "AnalyticsHandler",
            "AuthHandler",
            "GauntletHandler",
            "MemoryHandler",
            "NomicHandler",
        ]
        for name in core_handlers:
            assert name in HANDLER_MODULES, f"Core handler {name!r} missing from HANDLER_MODULES"

    def test_ralph_dashboard_handler_is_registered(self):
        assert (
            HANDLER_MODULES["RalphDashboardHandler"]
            == "aragora.server.handlers.autonomous.ralph_dashboard"
        )
        assert "RalphDashboardHandler" in ALL_HANDLER_NAMES

    def test_handler_names_use_handler_suffix_convention(self):
        """Most handler class names should end with 'Handler' or 'Handlers'."""
        # Count how many follow the convention
        conventional = sum(
            1 for name in HANDLER_MODULES if name.endswith("Handler") or name.endswith("Handlers")
        )
        # Allow some exceptions (e.g., GAUNTLET_V1_HANDLERS, get_collaboration_handlers)
        # but the vast majority should follow convention
        total = len(HANDLER_MODULES)
        ratio = conventional / total
        assert ratio > 0.8, (
            f"Only {conventional}/{total} ({ratio:.0%}) handler names follow the Handler suffix convention"
        )

    def test_significant_count(self):
        """Should have a large number of handlers registered."""
        assert len(HANDLER_MODULES) > 50, (
            f"Expected 50+ handler modules but found {len(HANDLER_MODULES)}"
        )


class TestAllHandlerNames:
    """Test the ALL_HANDLER_NAMES list."""

    def test_is_list(self):
        assert isinstance(ALL_HANDLER_NAMES, list)

    def test_not_empty(self):
        assert len(ALL_HANDLER_NAMES) > 0

    def test_all_elements_are_strings(self):
        for name in ALL_HANDLER_NAMES:
            assert isinstance(name, str), f"Element {name!r} is not a string"

    def test_no_duplicates(self):
        """ALL_HANDLER_NAMES should not contain duplicates."""
        seen = set()
        duplicates = []
        for name in ALL_HANDLER_NAMES:
            if name in seen:
                duplicates.append(name)
            seen.add(name)
        assert duplicates == [], f"Duplicate handler names found: {duplicates}"

    def test_significant_count(self):
        """Should have a large number of handler names."""
        assert len(ALL_HANDLER_NAMES) > 50


class TestConsistency:
    """Test consistency between HANDLER_MODULES and ALL_HANDLER_NAMES."""

    def test_all_handler_names_have_module_mapping(self):
        """Every handler in ALL_HANDLER_NAMES should have a HANDLER_MODULES entry."""
        missing = []
        for name in ALL_HANDLER_NAMES:
            if name not in HANDLER_MODULES:
                missing.append(name)
        assert missing == [], f"Handler names without module mapping: {missing}"

    def test_handler_modules_coverage(self):
        """Most handlers in HANDLER_MODULES should be in ALL_HANDLER_NAMES.

        Some helpers (like get_collaboration_handlers, GAUNTLET_V1_HANDLERS)
        may not be in the dispatch list, so we check for high coverage.
        """
        names_set = set(ALL_HANDLER_NAMES)
        in_both = sum(1 for name in HANDLER_MODULES if name in names_set)
        total = len(HANDLER_MODULES)
        ratio = in_both / total if total > 0 else 0
        assert ratio > 0.7, (
            f"Only {in_both}/{total} ({ratio:.0%}) HANDLER_MODULES entries are in ALL_HANDLER_NAMES"
        )
