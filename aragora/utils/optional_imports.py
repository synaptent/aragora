"""
Optional dependency import utilities.

Provides consistent, DRY handling of optional imports across the codebase.
Replaces repeated try/except ImportError patterns with reusable functions.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


def try_import(
    module_path: str,
    *names: str,
    log_on_failure: bool = False,
    log_level: str = "debug",
) -> tuple[dict[str, Any], bool]:
    """
    Safely import optional dependencies with consistent handling.

    Args:
        module_path: Full module path (e.g., "aragora.ranking.elo")
        *names: Names to import from the module (e.g., "EloSystem", "EloRating")
        log_on_failure: Whether to log when import fails
        log_level: Log level for failures ("debug", "info", "warning")

    Returns:
        Tuple of (imported_dict, is_available) where:
        - imported_dict: {"Name": class_or_none, ...} for each requested name
        - is_available: True if import succeeded, False otherwise

    Examples:
        # Single import
        imported, available = try_import("aragora.ranking.elo", "EloSystem")
        EloSystem = imported["EloSystem"]
        RANKING_AVAILABLE = available

        # Multiple imports
        imported, available = try_import(
            "aragora.memory.consensus",
            "ConsensusMemory", "DissentRetriever"
        )
        ConsensusMemory = imported["ConsensusMemory"]
        DissentRetriever = imported["DissentRetriever"]
        CONSENSUS_AVAILABLE = available

        # With logging
        imported, available = try_import(
            "aragora.verification.formal",
            "FormalVerificationManager",
            log_on_failure=True
        )
    """
    result = dict.fromkeys(names)

    try:
        module = importlib.import_module(module_path)
        for name in names:
            if hasattr(module, name):
                result[name] = getattr(module, name)
            else:
                # Attribute doesn't exist - partial import failure
                if log_on_failure:
                    _log(f"Module {module_path} has no attribute '{name}'", log_level)
                return result, False
        return result, True

    except ImportError as e:
        if log_on_failure:
            _log(f"Optional module not available: {module_path} ({e})", log_level)
        return result, False
    except (AttributeError, TypeError, RuntimeError) as e:
        if log_on_failure:
            _log(f"Error importing {module_path}: {e}", log_level)
        return result, False


def try_import_class(
    module_path: str,
    class_name: str,
    log_on_failure: bool = False,
) -> tuple[type | None, bool]:
    """
    Convenience function for importing a single class.

    Args:
        module_path: Full module path
        class_name: Name of the class to import
        log_on_failure: Whether to log when import fails

    Returns:
        Tuple of (class_or_none, is_available)

    Example:
        EloSystem, RANKING_AVAILABLE = try_import_class(
            "aragora.ranking.elo", "EloSystem"
        )
    """
    imported, available = try_import(module_path, class_name, log_on_failure=log_on_failure)
    return imported[class_name], available


class LazyImport:
    """
    Lazy import wrapper for circular import avoidance.

    Use this when imports must be deferred until first use.

    Example:
        # At module level
        _belief_imports = LazyImport("aragora.reasoning.belief", "BeliefNetwork", "BeliefPropagationAnalyzer")

        # In function
        def analyze():
            BeliefNetwork = _belief_imports.get("BeliefNetwork")
            if BeliefNetwork is None:
                return None
            return BeliefNetwork()
    """

    def __init__(self, module_path: str, *names: str, log_on_failure: bool = False):
        self._module_path = module_path
        self._names = names
        self._log_on_failure = log_on_failure
        self._imported: dict[str, Any] | None = None
        self._available: bool | None = None

    def _ensure_imported(self) -> None:
        """Import on first access."""
        if self._imported is None:
            self._imported, self._available = try_import(
                self._module_path,
                *self._names,
                log_on_failure=self._log_on_failure,
            )

    def get(self, name: str) -> Any:
        """Get an imported item by name."""
        self._ensure_imported()
        return self._imported.get(name) if self._imported else None

    @property
    def available(self) -> bool:
        """Check if import succeeded."""
        self._ensure_imported()
        return bool(self._available)

    def all(self) -> tuple[dict[str, Any], bool]:
        """Get all imports and availability flag."""
        self._ensure_imported()
        return self._imported or {}, bool(self._available)


def _log(message: str, level: str) -> None:
    """Log at the specified level."""
    log_func = getattr(logger, level.lower(), logger.debug)
    log_func(message)
