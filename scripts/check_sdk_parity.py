#!/usr/bin/env python3
"""SDK Parity Checker.

Compares handler endpoints against SDK namespace methods to detect
coverage drift. Intended for CI integration to fail when new handler
routes lack corresponding SDK bindings.

Budget enforcement compares measured debt against the explicit committed
ceilings in the budget file; wall-clock dates and timezones never affect
pass/fail. ``--today`` only shapes the non-enforcing advisory target.

Usage:
    python scripts/check_sdk_parity.py             # Report only
    python scripts/check_sdk_parity.py --strict    # Exit 1 if gaps found
    python scripts/check_sdk_parity.py --strict --allow-missing  # transitional override
    python scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json
    python scripts/check_sdk_parity.py --json       # JSON output
    python scripts/check_sdk_parity.py --tighten    # Lower committed ceilings to measured debt
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import inspect
import json
import os
import re
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. Extract handler routes from ROUTES class variables
# ---------------------------------------------------------------------------

# Known internal/system routes that don't need SDK coverage
INTERNAL_ROUTES = {
    "/api/v1/webhooks/stripe",
    "/api/health",
    "/api/v1/health",
    "/health",
    "/api/v1/system",
    "/api/v1/system/mode",
    "/api/v1/docs",
    "/api/v1/docs/openapi.json",
    "/api/v1/status",
    # Legacy OpenClaw gateway aliases -- canonical /api/v1/openclaw/ paths
    # are covered by both SDKs; these unversioned gateway aliases share the
    # same handler via _normalize_path() and don't need separate SDK surface.
    "/api/gateway/openclaw/sessions",
    "/api/gateway/openclaw/actions",
    "/api/gateway/openclaw/credentials",
    "/api/gateway/openclaw/health",
    "/api/gateway/openclaw/metrics",
    "/api/gateway/openclaw/audit",
}

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
CAN_HANDLE_PREFIX_ALLOWLIST = {
    "/api/v1/actions",
    "/api/v1/audit-trails",
    "/api/v1/orchestration/canvas",
    "/api/pipeline/transitions",
    "/api/plans",
}


@dataclass(frozen=True)
class HandlerRouteExtractionResult:
    routes: dict[str, list[str]]
    available: bool
    error: str | None = None


def _normalize_route_candidate(candidate: str) -> str | None:
    """Normalize a handler route candidate string.

    Supports plain paths (`/api/v1/foo`) and method-prefixed entries
    (`GET /api/v1/foo`) used by some handler route maps.
    """
    route = candidate.strip()
    if not route:
        return None

    if " " in route:
        method, remainder = route.split(" ", 1)
        if method.upper() in HTTP_METHODS:
            route = remainder.strip()

    if not route.startswith("/"):
        return None

    return route


def _collect_routes_from_handler_class(handler_cls: type[Any]) -> list[str]:
    """Collect route strings from common handler class route attributes."""
    collected: set[str] = set()

    def add_candidate(value: str) -> None:
        normalized = _normalize_route_candidate(value)
        if normalized:
            collected.add(normalized)

    for attr in (
        "ROUTES",
        "DYNAMIC_ROUTES",
        "_DYNAMIC_ROUTES",
        "ROUTE_MAP",
        "_ROUTE_MAP",
        "PREFIX_ROUTES",
        "_PREFIX_ROUTES",
    ):
        value = getattr(handler_cls, attr, None)
        if value is None:
            continue

        is_prefix_attr = "PREFIX" in attr.upper()

        if isinstance(value, dict):
            for key in value.keys():
                if isinstance(key, str):
                    add_candidate(key)
            continue

        if isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, str):
                    add_candidate(item)
                    # PREFIX_ROUTES entries end with "/" and match sub-paths;
                    # generate a {param} variant so SDK paths like
                    # /api/v1/selection/scorers/{name} are recognized.
                    if is_prefix_attr and isinstance(item, str) and item.endswith("/"):
                        add_candidate(f"{item}{{param}}")

    # Some handlers are prefix-dispatched and only expose can_handle(path)
    # with startswith() checks rather than explicit ROUTES declarations.
    can_handle = getattr(handler_cls, "can_handle", None)
    if callable(can_handle):
        try:
            source = inspect.getsource(can_handle)
        except (OSError, TypeError):
            source = ""
        if source:
            # Extract literal API path prefixes from startswith("...") or
            # startswith(("...", "...")) expressions.
            for expr in re.findall(r"startswith\(([^)]*)\)", source):
                for prefix in re.findall(r'["\'](/api[^"\']*)["\']', expr):
                    normalized_prefix = prefix.rstrip("/")
                    if normalized_prefix not in CAN_HANDLE_PREFIX_ALLOWLIST:
                        continue
                    add_candidate(prefix)
                    if normalized_prefix:
                        add_candidate(f"{normalized_prefix}/{{param}}")

    return sorted(collected)


# Modules the handler cascade still reaches transitively that emit a
# module-level DeprecationWarning on first import: compatibility shims, plus
# one handler module carrying a module-level notice for a single deprecated
# function. Their remaining in-tree importers are migrated on separate
# tracks, so this diagnostic script imports each module once under a locally
# scoped filter instead. sys.modules caching guarantees the warning cannot
# fire again during the cascade, and the filter list is restored on scope
# exit, so no global warning state (and no package __init__) is ever touched.
_LEGACY_WARNING_MODULES: tuple[str, ...] = (
    "aragora.server.errors",
    "aragora.debate.protocol",
    "aragora.server.metrics",
    "aragora.server.redis_config",
    "aragora.server.storage",
    "aragora.server.http_client_pool",
    "aragora.server.handlers.webhooks",
)


def _preimport_legacy_warning_modules_quietly() -> None:
    """Import the known modules, muting only their own DeprecationWarnings.

    Capture-and-replay instead of an ignore filter: third-party imports deep
    in these chains call ``warnings.simplefilter`` themselves, which would
    front-run any filter installed here. ``record=True`` intercepts at the
    ``showwarning`` level, which such filter mutations cannot bypass, and the
    scope exit restores the pre-existing filter state so nothing leaks out.
    """
    for module_path in _LEGACY_WARNING_MODULES:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                importlib.import_module(module_path)
            except (ImportError, AttributeError, ModuleNotFoundError):
                # Same tolerance as the handler cascade below; a module that
                # fails here fails identically there and is reported there.
                continue
        for captured in caught:
            is_known_notice = issubclass(captured.category, DeprecationWarning) and str(
                captured.message
            ).startswith(_LEGACY_WARNING_MODULES)
            if is_known_notice:
                continue
            # Replay everything else through the real (restored) filters so
            # only the known notices above are actually silenced.
            warnings.warn_explicit(
                captured.message,
                captured.category,
                captured.filename,
                captured.lineno,
            )


def extract_handler_routes_with_status() -> HandlerRouteExtractionResult:
    """Extract ROUTES from handler classes and report availability state."""
    _preimport_legacy_warning_modules_quietly()
    try:
        from aragora.server.handlers._lazy_imports import ALL_HANDLER_NAMES, HANDLER_MODULES
    except (ImportError, ModuleNotFoundError) as exc:
        return HandlerRouteExtractionResult(
            routes={},
            available=False,
            error=f"handler registry import failed: {exc}",
        )

    handler_routes: dict[str, list[str]] = {}
    import_failures: list[str] = []

    for name in ALL_HANDLER_NAMES:
        module_path = HANDLER_MODULES.get(name)
        if not module_path:
            continue

        try:
            module = importlib.import_module(module_path)
            handler_cls = getattr(module, name, None)
            if handler_cls is None:
                continue

            routes = _collect_routes_from_handler_class(handler_cls)
            if routes:
                handler_routes[name] = routes
        except (ImportError, AttributeError, ModuleNotFoundError) as exc:
            import_failures.append(f"{module_path}: {exc}")
            continue

    if handler_routes:
        return HandlerRouteExtractionResult(routes=handler_routes, available=True)

    if import_failures:
        sample_failures = "; ".join(import_failures[:5])
        if len(import_failures) > 5:
            sample_failures += f"; ... and {len(import_failures) - 5} more"
        return HandlerRouteExtractionResult(
            routes={},
            available=False,
            error=f"handler modules unavailable in this environment: {sample_failures}",
        )

    return HandlerRouteExtractionResult(routes={}, available=True)


def extract_handler_routes() -> dict[str, list[str]]:
    """Extract ROUTES from all handler classes."""
    return extract_handler_routes_with_status().routes


def extract_openapi_routes(spec_path: Path | None = None) -> set[str]:
    """Extract normalized route paths documented in OpenAPI."""
    if spec_path is None:
        spec_path = PROJECT_ROOT / "docs" / "api" / "openapi.json"
    if not spec_path.exists():
        return set()

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()

    documented: set[str] = set()
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return documented

    for path, methods in paths.items():
        if not isinstance(path, str) or not isinstance(methods, dict):
            continue
        # Keep path only if at least one HTTP operation is present.
        has_http_op = any(
            isinstance(method, str)
            and method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}
            for method in methods
        )
        if has_http_op:
            documented.add(normalize_route(path))

    return documented


try:
    # Direct script execution (python scripts/check_sdk_parity.py)
    from sdk_path_normalize import normalize_sdk_path
    from validate_openapi_routes import is_internal_route, load_internal_prefixes
except ModuleNotFoundError:
    # Module import context (pytest importing scripts.check_sdk_parity)
    from scripts.sdk_path_normalize import normalize_sdk_path
    from scripts.validate_openapi_routes import is_internal_route, load_internal_prefixes


def normalize_route(route: str) -> str:
    """Normalize a route for comparison.

    Delegates to the shared ``normalize_sdk_path`` helper so all SDK
    validation scripts use a single normalization algorithm.
    """
    return normalize_sdk_path(route)


_INTERNAL_PREFIX_CACHE: tuple[str, ...] | None = None


def _internal_prefix_families() -> tuple[str, ...]:
    """Internal-route policy prefixes, normalized like every route here.

    Internal route families (control-plane, v1 SSO, SME, emergency admin, ...)
    are excluded from the public OpenAPI spec by policy
    (scripts/baselines/internal_route_prefixes.json), so SDK methods that
    call them cannot be validated against public-contract route sources.
    Fails closed (SystemExit) when the policy file is unusable.
    """
    global _INTERNAL_PREFIX_CACHE
    if _INTERNAL_PREFIX_CACHE is None:
        _INTERNAL_PREFIX_CACHE = tuple(normalize_route(p) for p in load_internal_prefixes())
    return _INTERNAL_PREFIX_CACHE


def _is_internal_family(normalized_path: str) -> bool:
    return is_internal_route(normalized_path, _internal_prefix_families())


# ---------------------------------------------------------------------------
# 2. Extract SDK endpoint paths from Python namespace files
# ---------------------------------------------------------------------------


def extract_sdk_paths_python() -> dict[str, set[str]]:
    """Extract HTTP paths from Python SDK namespace files.

    Parses client request calls in SDK namespaces, including both:
    - self._client.request(...)
    - self._client._request(...)
    and async forms with optional ``await``.

    Returns:
        Dict mapping namespace name -> set of endpoint paths
    """
    sdk_dir = PROJECT_ROOT / "sdk" / "python" / "aragora_sdk" / "namespaces"
    if not sdk_dir.exists():
        return {}

    path_pattern = re.compile(
        r"(?:await\s+)?self\._client\._?request\(\s*['\"][A-Z]+['\"]\s*,\s*f?['\"]([^'\"]+)['\"]"
    )

    namespace_paths: dict[str, set[str]] = {}

    for py_file in sorted(sdk_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        ns_name = py_file.stem
        paths: set[str] = set()

        try:
            content = py_file.read_text(encoding="utf-8")
        except OSError:
            continue

        # Match regular strings and f-strings for both request/_request.
        for match in path_pattern.finditer(content):
            raw_path = match.group(1)
            # Replace f-string expressions with {param}
            cleaned = re.sub(r"\{[^}]+\}", "{param}", raw_path)
            paths.add(cleaned)

        if paths:
            namespace_paths[ns_name] = paths

    return namespace_paths


def extract_sdk_paths_typescript() -> dict[str, set[str]]:
    """Extract HTTP paths from TypeScript SDK namespace files.

    Returns:
        Dict mapping namespace name -> set of endpoint paths
    """
    sdk_dir = PROJECT_ROOT / "sdk" / "typescript" / "src" / "namespaces"
    if not sdk_dir.exists():
        return {}

    # Match patterns like: request("GET", "/api/v1/...") or request('GET', '/api/v1/...')
    # Also match template literals: `...`
    # The generic type parameter can contain nested angle brackets, e.g.
    # request<Record<string, unknown>>(...) -- so we use (?:<[^(]*>)? to match
    # everything between the first < and the last > before the opening paren.
    request_path_pattern = re.compile(
        r'request(?:<[^(]*>)?\(\s*["\'][A-Z]+["\']\s*,\s*[`"\']([^`"\']+)[`"\']'
    )

    # Compatibility wrappers in some namespaces use:
    # invoke('legacyMethod', [...], 'GET', '/api/v1/...')
    invoke_path_pattern = re.compile(
        r'invoke(?:<[^(]*>)?\(\s*["\'][^"\']+["\']\s*,\s*\[[^\]]*\]\s*,\s*["\'][A-Z]+["\']\s*,\s*[`"\']([^`"\']+)[`"\']'
    )

    namespace_paths: dict[str, set[str]] = {}

    for ts_file in sorted(sdk_dir.glob("*.ts")):
        if ts_file.name.startswith("_") or ts_file.name == "index.ts":
            continue

        ns_name = ts_file.stem
        paths: set[str] = set()

        try:
            content = ts_file.read_text(encoding="utf-8")
        except OSError:
            continue

        for match in request_path_pattern.finditer(content):
            raw_path = match.group(1)
            # Replace template expressions ${...} with {param}
            cleaned = re.sub(r"\$\{[^}]+\}", "{param}", raw_path)
            paths.add(cleaned)

        for match in invoke_path_pattern.finditer(content):
            raw_path = match.group(1)
            # Replace template expressions ${...} with {param}
            cleaned = re.sub(r"\$\{[^}]+\}", "{param}", raw_path)
            paths.add(cleaned)

        if paths:
            namespace_paths[ns_name] = paths

    return namespace_paths


# ---------------------------------------------------------------------------
# 3. Compare and report
# ---------------------------------------------------------------------------


def build_parity_report(
    handler_routes: dict[str, list[str]],
    python_sdk: dict[str, set[str]],
    typescript_sdk: dict[str, set[str]],
    documented_routes: set[str] | None = None,
    *,
    handler_routes_available: bool = True,
    handler_routes_error: str | None = None,
) -> dict[str, Any]:
    """Build a parity report comparing handlers vs SDKs.

    Returns structured report with coverage stats and gaps.
    """
    # Flatten all SDK paths (normalized)
    all_py_paths = set()
    for paths in python_sdk.values():
        for p in paths:
            all_py_paths.add(normalize_route(p))

    all_ts_paths = set()
    for paths in typescript_sdk.values():
        for p in paths:
            all_ts_paths.add(normalize_route(p))

    # Flatten all handler routes (normalized)
    all_handler_paths = set()
    handler_to_routes: dict[str, list[str]] = {}
    for handler_name, routes in handler_routes.items():
        normalized = [normalize_route(r) for r in routes]
        handler_to_routes[handler_name] = normalized
        all_handler_paths.update(normalized)

    # Filter out internal routes — both the exact-route legacy set and the
    # internal-route policy families (scripts/baselines/internal_route_prefixes.json),
    # so internal handler routes are never flagged as public SDK-coverage gaps
    # even when no documented-route source is available.
    internal_normalized = {normalize_route(r) for r in INTERNAL_ROUTES}
    public_handler_paths = {
        p for p in all_handler_paths - internal_normalized if not _is_internal_family(p)
    }
    if documented_routes is not None:
        # SDK coverage should be enforced for documented API routes.
        public_handler_paths = public_handler_paths & documented_routes

    # Find gaps (wildcard-aware: handler routes ending with /{param}
    # are considered covered if any SDK path shares the prefix)
    def _is_covered(route: str, sdk_paths: set[str]) -> bool:
        if route in sdk_paths:
            return True
        if route.endswith("/{param}"):
            prefix = route[: -len("/{param}")]
            return any(sp.startswith(prefix + "/") for sp in sdk_paths)
        return False

    missing_from_py_sdk = {r for r in public_handler_paths if not _is_covered(r, all_py_paths)}
    missing_from_ts_sdk = {r for r in public_handler_paths if not _is_covered(r, all_ts_paths)}
    missing_from_both = missing_from_py_sdk & missing_from_ts_sdk

    # SDK paths not in route sources (potential stale SDK methods)
    # Prefer handler ROUTES, but also include documented routes when available
    # because some handlers are dispatch-based and do not expose ROUTES.
    stale_reference_paths = set(all_handler_paths)
    if documented_routes is not None:
        stale_reference_paths.update(documented_routes)

    # Build wildcard prefixes from route templates ending with {param}
    # to match SDK sub-paths like /api/integrations/stats against /api/integrations/{param}
    wildcard_prefixes = set()
    for p in stale_reference_paths:
        if p.endswith("/{param}"):
            wildcard_prefixes.add(p[: -len("/{param}")])

    def _covered_by_handler(sdk_path: str) -> bool:
        if sdk_path in stale_reference_paths:
            return True
        # Check if any wildcard handler covers this path
        for prefix in wildcard_prefixes:
            if sdk_path.startswith(prefix + "/"):
                return True
        return False

    # Internal-family SDK paths are excluded: the internal-route policy keeps
    # those families out of the public spec (documented_routes), so their
    # only route source is handler ROUTES — and several internal handlers are
    # dispatch-based without ROUTES. Staleness of internal SDK surface is not
    # a public-contract question this gate can answer.
    stale_py = {
        p for p in all_py_paths if not _covered_by_handler(p) and not _is_internal_family(p)
    }
    stale_ts = {
        p for p in all_ts_paths if not _covered_by_handler(p) and not _is_internal_family(p)
    }
    if not handler_routes_available:
        stale_py = set()
        stale_ts = set()

    # Helper: check if an SDK path set covers a handler route.
    # For wildcard routes ending with /{param}, any SDK path starting with
    # the prefix counts as coverage (mirrors _covered_by_handler logic).
    def _sdk_covers_route(route: str, sdk_paths: set[str]) -> bool:
        if route in sdk_paths:
            return True
        if route.endswith("/{param}"):
            prefix = route[: -len("/{param}")]
            return any(sp.startswith(prefix + "/") for sp in sdk_paths)
        return False

    # Per-handler coverage (same internal-route policy as the global buckets)
    handler_coverage: list[dict[str, Any]] = []
    for handler_name, normalized_routes in sorted(handler_to_routes.items()):
        public_routes = [
            r
            for r in normalized_routes
            if r not in internal_normalized and not _is_internal_family(r)
        ]
        if not public_routes:
            continue

        py_covered = sum(1 for r in public_routes if _sdk_covers_route(r, all_py_paths))
        ts_covered = sum(1 for r in public_routes if _sdk_covers_route(r, all_ts_paths))

        handler_coverage.append(
            {
                "handler": handler_name,
                "total_routes": len(public_routes),
                "python_sdk_covered": py_covered,
                "typescript_sdk_covered": ts_covered,
                "missing_python": [
                    r for r in public_routes if not _sdk_covers_route(r, all_py_paths)
                ],
                "missing_typescript": [
                    r for r in public_routes if not _sdk_covers_route(r, all_ts_paths)
                ],
            }
        )

    # Summary stats
    total_public = len(public_handler_paths)
    py_coverage = (
        (total_public - len(missing_from_py_sdk)) / total_public * 100 if total_public else 0
    )
    ts_coverage = (
        (total_public - len(missing_from_ts_sdk)) / total_public * 100 if total_public else 0
    )

    return {
        "summary": {
            "total_handlers": len(handler_routes),
            "total_public_routes": total_public,
            "python_sdk_namespaces": len(python_sdk),
            "typescript_sdk_namespaces": len(typescript_sdk),
            "python_sdk_paths": len(all_py_paths),
            "typescript_sdk_paths": len(all_ts_paths),
            "python_sdk_coverage_pct": round(py_coverage, 1),
            "typescript_sdk_coverage_pct": round(ts_coverage, 1),
            "routes_missing_from_both_sdks": len(missing_from_both),
            "handler_routes_available": handler_routes_available,
            "handler_routes_error": handler_routes_error,
        },
        "gaps": {
            "missing_from_python_sdk": sorted(missing_from_py_sdk),
            "missing_from_typescript_sdk": sorted(missing_from_ts_sdk),
            "missing_from_both_sdks": sorted(missing_from_both),
            "stale_python_sdk_paths": sorted(stale_py),
            "stale_typescript_sdk_paths": sorted(stale_ts),
        },
        "handler_coverage": handler_coverage,
    }


def print_report(report: dict[str, Any]) -> None:
    """Print human-readable parity report."""
    s = report["summary"]

    print("=" * 70)
    print("SDK Parity Report")
    print("=" * 70)
    print(f"Handlers scanned:           {s['total_handlers']}")
    print(f"Public routes found:        {s['total_public_routes']}")
    print(f"Python SDK namespaces:      {s['python_sdk_namespaces']}")
    print(f"TypeScript SDK namespaces:  {s['typescript_sdk_namespaces']}")
    print(f"Python SDK coverage:        {s['python_sdk_coverage_pct']}%")
    print(f"TypeScript SDK coverage:    {s['typescript_sdk_coverage_pct']}%")
    print(f"Missing from BOTH SDKs:     {s['routes_missing_from_both_sdks']}")
    if not s["handler_routes_available"]:
        print("Handler route source:       unavailable in this environment")
    print()

    gaps = report["gaps"]

    if gaps["missing_from_both_sdks"]:
        print("-" * 70)
        print(f"Routes missing from BOTH SDKs ({len(gaps['missing_from_both_sdks'])}):")
        for route in gaps["missing_from_both_sdks"][:30]:
            print(f"  {route}")
        if len(gaps["missing_from_both_sdks"]) > 30:
            print(f"  ... and {len(gaps['missing_from_both_sdks']) - 30} more")
        print()

    # Per-handler gaps (only show handlers with missing coverage)
    uncovered = [
        h for h in report["handler_coverage"] if h["missing_python"] or h["missing_typescript"]
    ]
    if uncovered:
        print("-" * 70)
        print(f"Handlers with SDK gaps ({len(uncovered)}):")
        for h in uncovered[:20]:
            py_gap = len(h["missing_python"])
            ts_gap = len(h["missing_typescript"])
            print(f"  {h['handler']}: {h['total_routes']} routes (py: -{py_gap}, ts: -{ts_gap})")
        if len(uncovered) > 20:
            print(f"  ... and {len(uncovered) - 20} more handlers")
        print()

    if gaps["stale_python_sdk_paths"]:
        print("-" * 70)
        print(f"Stale Python SDK paths ({len(gaps['stale_python_sdk_paths'])}):")
        for path in gaps["stale_python_sdk_paths"][:10]:
            print(f"  {path}")
        if len(gaps["stale_python_sdk_paths"]) > 10:
            print(f"  ... and {len(gaps['stale_python_sdk_paths']) - 10} more")
        print()

    print("=" * 70)
    if not s["handler_routes_available"]:
        print("INFO: Handler route inspection unavailable; parity enforcement is skipped.")
    elif s["routes_missing_from_both_sdks"] == 0:
        print("PASS: All public routes have SDK coverage in at least one SDK.")
    else:
        print(f"WARN: {s['routes_missing_from_both_sdks']} routes lack SDK coverage.")


def _expected_budget_max(
    *,
    initial: int,
    weekly_reduction: int,
    start_date: dt.date,
    today: dt.date,
) -> int:
    """Compute the advisory-only paydown target after a weekly reduction cadence."""
    if weekly_reduction <= 0 or today <= start_date:
        return initial
    weeks_elapsed = (today - start_date).days // 7
    return max(0, initial - (weeks_elapsed * weekly_reduction))


BUDGET_SCHEMA = "check-sdk-parity-committed-budget-v1"
COMMITTED_MISSING_KEY = "committed_max_missing_from_both_sdks"
COMMITTED_STALE_KEY = "committed_max_stale_python_sdk_paths"
ADVISORY_CADENCE_KEY = "advisory_cadence"
_LEGACY_CADENCE_KEYS = (
    "start_date",
    "initial_missing_from_both_sdks",
    "weekly_reduction_missing_from_both_sdks",
    "initial_stale_python_sdk_paths",
    "weekly_reduction_stale_python_sdk_paths",
)


@dataclass(frozen=True)
class CommittedBudget:
    max_missing_from_both: int
    max_stale_python: int
    advisory_cadence: dict[str, Any] | None = None


@dataclass(frozen=True)
class BudgetLoadResult:
    budget: CommittedBudget | None = None
    error_kind: str | None = None  # "missing" | "malformed" | "legacy"
    error_detail: str | None = None
    raw: dict[str, Any] | None = None
    raw_bytes: bytes | None = None


def _as_committed_ceiling(value: Any, key: str) -> int:
    # bool is an int subclass and must not slip through as a ceiling.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a nonnegative integer, got {value!r}")
    return value


def load_committed_budget(path: Path) -> BudgetLoadResult:
    """Load and classify a committed-ceiling budget file.

    Only explicit committed ceilings are enforceable; a file carrying just
    the retired clock-derived cadence keys classifies as ``legacy``.
    """
    if not path.exists():
        return BudgetLoadResult(error_kind="missing", error_detail=f"{path} does not exist")
    try:
        raw_bytes = path.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return BudgetLoadResult(error_kind="malformed", error_detail=str(exc))
    if not isinstance(data, dict):
        return BudgetLoadResult(error_kind="malformed", error_detail="budget must be a JSON object")

    if COMMITTED_MISSING_KEY not in data or COMMITTED_STALE_KEY not in data:
        legacy_keys = [key for key in _LEGACY_CADENCE_KEYS if key in data]
        detail = (
            f"clock-derived cadence keys ({', '.join(legacy_keys)}) without committed ceilings"
            if legacy_keys
            else f"missing required keys {COMMITTED_MISSING_KEY} and {COMMITTED_STALE_KEY}"
        )
        kind = "legacy" if legacy_keys else "malformed"
        return BudgetLoadResult(error_kind=kind, error_detail=detail, raw=data, raw_bytes=raw_bytes)

    try:
        max_missing = _as_committed_ceiling(data[COMMITTED_MISSING_KEY], COMMITTED_MISSING_KEY)
        max_stale = _as_committed_ceiling(data[COMMITTED_STALE_KEY], COMMITTED_STALE_KEY)
    except ValueError as exc:
        return BudgetLoadResult(error_kind="malformed", error_detail=str(exc), raw=data)

    advisory = data.get(ADVISORY_CADENCE_KEY)
    if not isinstance(advisory, dict) or not advisory:
        advisory = None
    return BudgetLoadResult(
        budget=CommittedBudget(
            max_missing_from_both=max_missing,
            max_stale_python=max_stale,
            advisory_cadence=advisory,
        ),
        raw=data,
        raw_bytes=raw_bytes,
    )


def _resolve_advisory_date(today_arg: dt.date | None) -> dt.date:
    """Resolve the date used ONLY for the non-enforcing advisory target."""
    return today_arg if today_arg is not None else dt.date.today()


def _advisory_target(cadence: dict[str, Any], as_of: dt.date) -> dict[str, Any] | None:
    """Compute the non-enforcing advisory paydown target, or None when unusable."""
    try:
        start_date = dt.date.fromisoformat(str(cadence["start_date"]).strip())
        initial_missing = int(cadence["initial_missing_from_both_sdks"])
        weekly_missing = int(cadence.get("weekly_reduction_missing_from_both_sdks", 0))
        initial_stale = int(cadence["initial_stale_python_sdk_paths"])
        weekly_stale = int(cadence.get("weekly_reduction_stale_python_sdk_paths", 0))
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "as_of": as_of.isoformat(),
        "missing_from_both_sdks_max": _expected_budget_max(
            initial=initial_missing,
            weekly_reduction=weekly_missing,
            start_date=start_date,
            today=as_of,
        ),
        "stale_python_sdk_paths_max": _expected_budget_max(
            initial=initial_stale,
            weekly_reduction=weekly_stale,
            start_date=start_date,
            today=as_of,
        ),
    }


def _canonical_budget_bytes(
    max_missing: int, max_stale: int, advisory_cadence: dict[str, Any] | None
) -> bytes:
    payload: dict[str, Any] = {
        "schema": BUDGET_SCHEMA,
        COMMITTED_MISSING_KEY: max_missing,
        COMMITTED_STALE_KEY: max_stale,
    }
    if advisory_cadence:
        payload[ADVISORY_CADENCE_KEY] = advisory_cadence
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _run_tighten(args: argparse.Namespace) -> int:
    """Write measured debt as the committed ceilings (never raises a ceiling)."""
    handler_result = extract_handler_routes_with_status()
    if not handler_result.available:
        print(f"FAIL: --tighten requires handler route extraction ({handler_result.error})")
        return 2
    report = build_parity_report(
        handler_result.routes,
        extract_sdk_paths_python(),
        extract_sdk_paths_typescript(),
        None if args.include_undocumented else extract_openapi_routes(),
        handler_routes_available=handler_result.available,
        handler_routes_error=handler_result.error,
    )
    measured_missing = int(report["summary"]["routes_missing_from_both_sdks"])
    measured_stale = len(report["gaps"]["stale_python_sdk_paths"])

    loaded = load_committed_budget(args.budget)
    if loaded.error_kind == "malformed":
        print(
            f"FAIL: refusing to overwrite malformed budget file ({args.budget}): "
            f"{loaded.error_detail}"
        )
        return 2

    advisory_cadence: dict[str, Any] | None = None
    if loaded.budget is not None:
        ceilings = loaded.budget
        over = []
        if measured_missing > ceilings.max_missing_from_both:
            over.append(
                f"missing_from_both {measured_missing} > committed {ceilings.max_missing_from_both}"
            )
        if measured_stale > ceilings.max_stale_python:
            over.append(f"stale_python {measured_stale} > committed {ceilings.max_stale_python}")
        if over:
            print("FAIL: --tighten refuses to raise committed ceilings: " + "; ".join(over))
            return 1
        advisory_cadence = ceilings.advisory_cadence
    elif loaded.error_kind == "legacy" and loaded.raw is not None:
        advisory_cadence = {
            key: loaded.raw[key] for key in _LEGACY_CADENCE_KEYS if key in loaded.raw
        }

    target_bytes = _canonical_budget_bytes(measured_missing, measured_stale, advisory_cadence)
    if loaded.raw_bytes == target_bytes:
        print(
            f"Budget already tight: missing_from_both<={measured_missing} "
            f"| stale_python<={measured_stale} (no write)"
        )
        return 0

    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=".check_sdk_parity_budget.", dir=str(args.budget.parent)
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(target_bytes)
        os.chmod(tmp_name, 0o644)  # mkstemp defaults to 0600; keep the budget world-readable
        os.replace(tmp_name, str(args.budget))
        tmp_name = None
    except OSError as exc:
        print(f"FAIL: cannot write budget file ({args.budget}): {exc}")
        return 2
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    print(
        "Tightened committed budget ceilings to measured debt: "
        f"missing_from_both<={measured_missing} | stale_python<={measured_stale} "
        f"-> {args.budget}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SDK parity with handler endpoints")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any gaps found")
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="When used with --strict, allow routes missing from both SDKs (transitional override)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("scripts/baselines/check_sdk_parity.json"),
        help="Path to parity drift baseline file (default: scripts/baselines/check_sdk_parity.json)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument(
        "--include-undocumented",
        action="store_true",
        help="Include handler routes not present in docs/api/openapi.json (default: documented routes only)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum coverage %% for --strict mode (default: 0)",
    )
    parser.add_argument(
        "--budget",
        type=Path,
        default=Path("scripts/baselines/check_sdk_parity_budget.json"),
        help="Optional budget file for progressive parity debt reduction",
    )
    parser.add_argument(
        "--today",
        type=dt.date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Advisory-only date for the non-enforcing paydown target; "
            "never affects exit status or enforced ceilings"
        ),
    )
    parser.add_argument(
        "--tighten",
        action="store_true",
        help=(
            "Measure current debt and write it as the committed budget ceilings "
            "(bootstraps missing/legacy files; never raises an existing ceiling)"
        ),
    )
    args = parser.parse_args()

    if args.tighten:
        return _run_tighten(args)

    # Extract data
    handler_result = extract_handler_routes_with_status()
    handler_routes = handler_result.routes
    python_sdk = extract_sdk_paths_python()
    typescript_sdk = extract_sdk_paths_typescript()
    documented_routes = None if args.include_undocumented else extract_openapi_routes()

    # Build report
    report = build_parity_report(
        handler_routes,
        python_sdk,
        typescript_sdk,
        documented_routes,
        handler_routes_available=handler_result.available,
        handler_routes_error=handler_result.error,
    )

    if not args.json:
        print_report(report)
        if handler_result.error:
            print(f"\nHandler route detail: {handler_result.error}")

    baseline_missing: set[str] = set()
    if args.baseline and args.baseline.exists():
        baseline_data = json.loads(args.baseline.read_text())
        baseline_missing = set(baseline_data.get("missing_from_both_sdks", []))
    missing_set = set(report["gaps"]["missing_from_both_sdks"])
    new_missing = missing_set - baseline_missing
    if args.baseline and not args.json:
        print(f"\nBaseline regressions: missing_from_both={len(new_missing)}")
        for route in sorted(new_missing)[:20]:
            print(f"  NEW: {route}")
        if len(new_missing) > 20:
            print(f"  ... and {len(new_missing) - 20} more")

    # Committed ceilings are the only enforced budget; the clock never affects pass/fail.
    loaded_budget = load_committed_budget(args.budget)
    budget_block: dict[str, Any] = {"path": str(args.budget)}
    budget_failure_rc: int | None = None
    budget_failure_msg: str | None = None
    budget_passing: bool | None = None
    committed: CommittedBudget | None = None

    if loaded_budget.error_kind is not None:
        budget_block["error"] = loaded_budget.error_kind
        budget_block["detail"] = loaded_budget.error_detail
    if loaded_budget.error_kind == "missing":
        if args.strict:
            budget_failure_rc = 2
            budget_failure_msg = (
                f"FAIL: SDK parity budget file not found ({args.budget}); "
                "strict mode requires explicit committed ceilings"
            )
    elif loaded_budget.error_kind == "legacy":
        budget_failure_rc = 2
        budget_failure_msg = (
            f"FAIL: Legacy clock-derived SDK parity budget ({args.budget}): "
            f"{loaded_budget.error_detail}; bootstrap committed ceilings with --tighten"
        )
    elif loaded_budget.error_kind == "malformed":
        budget_failure_rc = 2
        budget_failure_msg = (
            f"FAIL: Invalid SDK parity budget file ({args.budget}): {loaded_budget.error_detail}"
        )
    else:
        committed = loaded_budget.budget

    if committed is not None:
        budget_block["schema"] = BUDGET_SCHEMA
        budget_block[COMMITTED_MISSING_KEY] = committed.max_missing_from_both
        budget_block[COMMITTED_STALE_KEY] = committed.max_stale_python
        if handler_result.available:
            current_missing = int(report["summary"]["routes_missing_from_both_sdks"])
            current_stale = len(report["gaps"]["stale_python_sdk_paths"])
            budget_passing = (
                current_missing <= committed.max_missing_from_both
                and current_stale <= committed.max_stale_python
            )
            budget_block["current_missing_from_both_sdks"] = current_missing
            budget_block["current_stale_python_sdk_paths"] = current_stale
            budget_block["passing"] = budget_passing
            advisory_target = None
            if committed.advisory_cadence:
                advisory_target = _advisory_target(
                    committed.advisory_cadence, _resolve_advisory_date(args.today)
                )
            budget_block["advisory_target"] = advisory_target
            if not args.json:
                print(
                    "\nBudget status (committed ceilings): "
                    f"missing_from_both {current_missing}/{committed.max_missing_from_both} "
                    f"| stale_python {current_stale}/{committed.max_stale_python}"
                )
                if advisory_target is not None:
                    print(
                        "Advisory paydown target (non-enforcing, as of "
                        f"{advisory_target['as_of']}): missing_from_both<="
                        f"{advisory_target['missing_from_both_sdks_max']} | stale_python<="
                        f"{advisory_target['stale_python_sdk_paths_max']}"
                    )
                if budget_passing and (
                    current_missing < committed.max_missing_from_both
                    or current_stale < committed.max_stale_python
                ):
                    # Ceilings never decay on their own, so unbanked slack after a
                    # real paydown stays silently consumable until someone tightens.
                    print(
                        "Advisory: current debt is below the committed ceilings "
                        f"(missing_from_both {current_missing}/"
                        f"{committed.max_missing_from_both} "
                        f"| stale_python {current_stale}/{committed.max_stale_python}); "
                        "run --tighten to bank this progress as the new ceilings."
                    )
        else:
            budget_block["skipped"] = "handler routes unavailable in this environment"
            if not args.json:
                print(
                    "\nBudget status: skipped because handler routes are unavailable "
                    "in this environment"
                )

    report["budget"] = budget_block

    if args.json:
        print(json.dumps(report, indent=2))

    # In --json mode stdout must stay exactly one parseable JSON document
    # (sdk-parity.yml redirects it into an artifact), so every human
    # diagnostic below is routed to stderr instead.
    diagnostics = sys.stderr if args.json else sys.stdout

    if budget_failure_rc is not None:
        if budget_failure_msg:
            print(f"\n{budget_failure_msg}", file=diagnostics)
        return budget_failure_rc

    # Strict mode: fail if gaps exceed threshold
    if args.strict:
        if not handler_result.available:
            print(
                "\nSKIP: Handler route extraction unavailable; strict parity enforcement skipped.",
                file=diagnostics,
            )
            return 0
        py_cov = report["summary"]["python_sdk_coverage_pct"]
        ts_cov = report["summary"]["typescript_sdk_coverage_pct"]
        if py_cov < args.threshold or ts_cov < args.threshold:
            print(f"\nFAIL: Coverage below threshold ({args.threshold}%)", file=diagnostics)
            return 1
        missing = report["summary"]["routes_missing_from_both_sdks"]
        if len(new_missing) > 0 and not args.allow_missing:
            print(
                f"\nFAIL: {len(new_missing)} new routes lack SDK coverage "
                f"(total missing: {missing}).",
                file=diagnostics,
            )
            print(
                "Run with --allow-missing only as a temporary migration override.",
                file=diagnostics,
            )
            return 1
        if committed is not None and budget_passing is False:
            current = budget_block["current_missing_from_both_sdks"]
            if current > committed.max_missing_from_both:
                print(
                    "\nFAIL: Missing-from-both debt exceeds committed ceiling "
                    f"({current} > {committed.max_missing_from_both}).",
                    file=diagnostics,
                )
                return 1
            stale = budget_block["current_stale_python_sdk_paths"]
            print(
                "\nFAIL: Stale Python SDK debt exceeds committed ceiling "
                f"({stale} > {committed.max_stale_python}).",
                file=diagnostics,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
