"""
Tests for OpenAPI specification sync and API drift detection.

Validates that:
1. The OpenAPI spec exists and is valid JSON with required structure.
2. The stability manifest is a subset of the OpenAPI spec (no orphaned stable entries).
3. TypeScript SDK namespace endpoints match the OpenAPI spec (drift detection).
4. Python SDK namespace endpoints match the OpenAPI spec (drift detection).
5. No new drift regressions relative to the recorded baseline.
6. Endpoint count snapshot tests detect unexpected additions/removals.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_JSON = PROJECT_ROOT / "docs" / "api" / "openapi.json"
OPENAPI_GENERATED = PROJECT_ROOT / "docs" / "api" / "openapi_generated.json"
STABILITY_MANIFEST = PROJECT_ROOT / "aragora" / "server" / "openapi" / "stability_manifest.json"
BASELINE_PATH = PROJECT_ROOT / "scripts" / "baselines" / "verify_sdk_contracts.json"
TS_NAMESPACES = PROJECT_ROOT / "sdk" / "typescript" / "src" / "namespaces"
PY_NAMESPACES = PROJECT_ROOT / "sdk" / "python" / "aragora_sdk" / "namespaces"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def _load_spec(path: Path) -> dict:
    """Load and return an OpenAPI spec as a dict."""
    assert path.exists(), f"OpenAPI spec not found: {path}"
    return json.loads(path.read_text())


def _spec_endpoints(spec: dict) -> set[tuple[str, str]]:
    """Extract (method, normalized_path) pairs from an OpenAPI spec."""
    endpoints: set[tuple[str, str]] = set()
    for path, ops in spec.get("paths", {}).items():
        for method in ops:
            if method.lower() in HTTP_METHODS:
                endpoints.add((method.lower(), _normalize(path)))
    return endpoints


def _normalize(path: str) -> str:
    """Normalize a path for comparison."""
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{param}", path)
    path = re.sub(r"\{[^}]+\}", "{param}", path)
    path = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "{param}", path)
    path = re.sub(r"^/api/v\d+/", "/api/", path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path.lower()


def _extract_ts_endpoints(content: str) -> set[tuple[str, str]]:
    """Extract endpoints from TypeScript SDK source."""
    eps: set[tuple[str, str]] = set()
    # Pattern: this.client.request('METHOD', ...)
    for m in re.finditer(
        r"this\.client\.request\(\s*['\"](?P<method>[A-Z]+)['\"]\s*,"
        r"\s*(?P<path>`[^`]+`|'[^']+'|\"[^\"]+\")",
        content,
    ):
        eps.add((m.group("method").lower(), _normalize(m.group("path")[1:-1])))
    # Pattern: this.client.get/post/etc(...)
    for m in re.finditer(
        r"this\.client\.(?P<method>get|post|put|delete|patch)\("
        r"\s*(?P<path>`[^`]+`|'[^']+'|\"[^\"]+\")",
        content,
    ):
        eps.add((m.group("method").lower(), _normalize(m.group("path")[1:-1])))
    return eps


def _extract_py_endpoints(content: str) -> set[tuple[str, str]]:
    """Extract endpoints from Python SDK source."""
    eps: set[tuple[str, str]] = set()
    for m in re.finditer(
        r'self\._client\._?request\(\s*["\'](?P<method>GET|POST|PUT|PATCH|DELETE)["\']'
        r'\s*,\s*(?:f?["\'])(?P<path>/api/[^"\']+)["\']',
        content,
    ):
        path = _normalize(m.group("path"))
        if path.startswith("/api/"):
            eps.add((m.group("method").lower(), path))
    return eps


def _load_baseline() -> dict[str, set[str]]:
    """Load the drift baseline."""
    if not BASELINE_PATH.exists():
        return {"python_sdk_drift": set(), "typescript_sdk_drift": set(), "missing_stable": set()}
    data = json.loads(BASELINE_PATH.read_text())
    return {
        "python_sdk_drift": set(data.get("python_sdk_drift", [])),
        "typescript_sdk_drift": set(data.get("typescript_sdk_drift", [])),
        "missing_stable": set(data.get("missing_stable", [])),
    }


def _internal_prefixes() -> tuple[str, ...]:
    """Internal-route policy prefixes in normalized (version-stripped) form.

    The canonical checkers (scripts/verify_sdk_contracts.py,
    scripts/validate_openapi_routes.py) exclude served-but-internal endpoint
    families from public-spec verification under a single policy file. These
    tests must apply the same policy, or they re-flag exactly the endpoints
    the policy excludes (first hit: the #9360 route-gate re-arm)."""
    from scripts.validate_openapi_routes import load_internal_prefixes

    return tuple(_normalize(p) for p in load_internal_prefixes())


def _is_internal(normalized_path: str, internal_prefixes: tuple[str, ...]) -> bool:
    from scripts.validate_openapi_routes import is_internal_route

    return is_internal_route(normalized_path, internal_prefixes)


# ---------------------------------------------------------------------------
# Tests: OpenAPI Spec Structure
# ---------------------------------------------------------------------------


class TestOpenAPISpecStructure:
    """Validate the OpenAPI spec has the required structure."""

    def test_openapi_json_exists(self):
        """The canonical OpenAPI spec must exist."""
        assert OPENAPI_JSON.exists(), f"OpenAPI spec not found: {OPENAPI_JSON}"

    def test_openapi_is_valid_json(self):
        """The spec must be valid JSON."""
        spec = _load_spec(OPENAPI_JSON)
        assert isinstance(spec, dict)

    def test_openapi_version(self):
        """The spec must declare an OpenAPI version."""
        spec = _load_spec(OPENAPI_JSON)
        version = spec.get("openapi", "")
        assert version.startswith("3."), f"OpenAPI version should be 3.x, got: {version}"

    def test_openapi_has_info(self):
        """The spec must have an info section with title and version."""
        spec = _load_spec(OPENAPI_JSON)
        info = spec.get("info", {})
        assert info.get("title"), "OpenAPI spec missing info.title"
        assert info.get("version"), "OpenAPI spec missing info.version"

    def test_openapi_has_paths(self):
        """The spec must have at least one path."""
        spec = _load_spec(OPENAPI_JSON)
        paths = spec.get("paths", {})
        assert len(paths) > 0, "OpenAPI spec has no paths"

    def test_openapi_has_security_scheme(self):
        """The spec should define at least one security scheme."""
        spec = _load_spec(OPENAPI_JSON)
        schemes = spec.get("components", {}).get("securitySchemes", {})
        assert len(schemes) > 0, "OpenAPI spec should define at least one security scheme"

    def test_all_paths_start_with_api_or_system(self):
        """All paths should start with /api/ or be known system paths."""
        spec = _load_spec(OPENAPI_JSON)
        allowed_system_exact = {
            "/healthz",
            "/readyz",
            "/readyz/dependencies",
            "/status",
            "/audio",
            "/metrics",
        }
        allowed_system_prefixes = (
            "/.well-known/",
            "/audio/",
            "/auth/sso/",
            "/health/",
            "/inbox/",
            "/scim/v2/",
        )
        bad_paths = []
        for path in spec.get("paths", {}):
            if path.startswith("/api/"):
                continue
            if path in allowed_system_exact:
                continue
            if any(path.startswith(prefix) for prefix in allowed_system_prefixes):
                continue
            bad_paths.append(path)
        assert not bad_paths, f"{len(bad_paths)} paths do not start with /api/: {bad_paths[:10]}"


# ---------------------------------------------------------------------------
# Tests: Endpoint Count Snapshot
# ---------------------------------------------------------------------------


class TestEndpointCountSnapshot:
    """Snapshot tests to detect unexpected additions or removals."""

    # These thresholds allow normal growth but catch major regressions.
    # Update them when the API legitimately changes in a major way.
    MIN_EXPECTED_ENDPOINTS = 500  # Floor: spec should not shrink below this
    MAX_EXPECTED_ENDPOINTS = 10000  # Ceiling: sanity check against bloat

    def test_endpoint_count_within_bounds(self):
        """The number of endpoints in the spec should be within expected bounds."""
        spec = _load_spec(OPENAPI_JSON)
        endpoints = _spec_endpoints(spec)
        count = len(endpoints)
        assert count >= self.MIN_EXPECTED_ENDPOINTS, (
            f"OpenAPI spec has only {count} endpoints, expected >= {self.MIN_EXPECTED_ENDPOINTS}. "
            f"This may indicate a generation regression."
        )
        assert count <= self.MAX_EXPECTED_ENDPOINTS, (
            f"OpenAPI spec has {count} endpoints, expected <= {self.MAX_EXPECTED_ENDPOINTS}. "
            f"This may indicate accidental duplication."
        )

    def test_paths_count_within_bounds(self):
        """The number of unique paths should be reasonable."""
        spec = _load_spec(OPENAPI_JSON)
        path_count = len(spec.get("paths", {}))
        assert path_count >= 200, f"OpenAPI spec has only {path_count} paths, expected >= 200"


# ---------------------------------------------------------------------------
# Tests: Stability Manifest
# ---------------------------------------------------------------------------


class TestStabilityManifest:
    """The stability manifest must be a subset of the OpenAPI spec."""

    def test_manifest_exists(self):
        """The stability manifest must exist."""
        assert STABILITY_MANIFEST.exists(), f"Stability manifest not found: {STABILITY_MANIFEST}"

    def test_manifest_is_valid_json(self):
        """The manifest must be valid JSON."""
        data = json.loads(STABILITY_MANIFEST.read_text())
        assert "stable" in data, "Stability manifest missing 'stable' key"
        assert isinstance(data["stable"], list), "'stable' must be a list"

    def test_manifest_entries_in_openapi(self):
        """All stable entries must exist in the OpenAPI spec."""
        spec = _load_spec(OPENAPI_JSON)
        openapi_eps = _spec_endpoints(spec)

        manifest = json.loads(STABILITY_MANIFEST.read_text())
        stable = manifest.get("stable", [])

        internal = _internal_prefixes()
        missing = []
        for entry in stable:
            parts = entry.split(" ", 1)
            if len(parts) != 2:
                continue
            method, path = parts[0].lower(), _normalize(parts[1])
            if _is_internal(path, internal):
                # Internal-route policy: served-but-internal families are
                # excluded from the public spec by design.
                continue
            if (method, path) not in openapi_eps:
                missing.append(entry)

        baseline = _load_baseline()
        baseline_missing = baseline.get("missing_stable", set())
        new_missing = [e for e in missing if e not in baseline_missing]

        assert not new_missing, (
            f"{len(new_missing)} NEW stable endpoints missing from OpenAPI spec "
            f"(total missing: {len(missing)}): {new_missing[:10]}"
        )


# ---------------------------------------------------------------------------
# Tests: TypeScript SDK Drift
# ---------------------------------------------------------------------------


class TestTypeScriptSDKDrift:
    """TypeScript SDK endpoints should match the OpenAPI spec."""

    _IGNORED_TS_NAMESPACES = {"openapi"}

    def test_ts_namespaces_directory_exists(self):
        """The TypeScript namespaces directory must exist."""
        assert TS_NAMESPACES.exists(), f"TypeScript namespaces not found: {TS_NAMESPACES}"

    def test_ts_namespace_count(self):
        """There should be a reasonable number of TypeScript namespaces."""
        assert TS_NAMESPACES.exists(), "TypeScript namespaces not found"
        ns_files = [
            p
            for p in TS_NAMESPACES.glob("*.ts")
            if (
                p.stem != "index"
                and not p.name.startswith("_")
                and p.stem not in self._IGNORED_TS_NAMESPACES
            )
        ]
        assert len(ns_files) >= 50, (
            f"Expected >= 50 TypeScript namespace files, found {len(ns_files)}"
        )

    def test_no_new_ts_drift(self):
        """No new TypeScript SDK endpoints should drift from the OpenAPI spec."""
        spec = _load_spec(OPENAPI_JSON)
        openapi_eps = _spec_endpoints(spec)

        # Also include generated spec if available
        if OPENAPI_GENERATED.exists():
            gen_spec = json.loads(OPENAPI_GENERATED.read_text())
            openapi_eps |= _spec_endpoints(gen_spec)

        assert TS_NAMESPACES.exists(), "TypeScript namespaces not found"

        internal = _internal_prefixes()
        ts_drift: list[tuple[str, str, str]] = []
        for ts_file in sorted(TS_NAMESPACES.glob("*.ts")):
            if (
                ts_file.stem == "index"
                or ts_file.name.startswith("_")
                or ts_file.stem in self._IGNORED_TS_NAMESPACES
            ):
                continue
            content = ts_file.read_text()
            eps = _extract_ts_endpoints(content)
            for ep in sorted(eps - openapi_eps):
                if _is_internal(ep[1], internal):
                    # Internal-route policy: internal families cannot be
                    # verified against the public spec.
                    continue
                ts_drift.append((ts_file.stem, ep[0].upper(), ep[1]))

        baseline = _load_baseline()
        baseline_ts = baseline.get("typescript_sdk_drift", set())
        new_drift = [(ns, m, p) for ns, m, p in ts_drift if f"{m} {p}" not in baseline_ts]

        assert not new_drift, (
            f"{len(new_drift)} NEW TypeScript SDK drift entries "
            f"(total drift: {len(ts_drift)}): "
            + "; ".join(f"{ns}: {m} {p}" for ns, m, p in new_drift[:10])
        )


# ---------------------------------------------------------------------------
# Tests: Python SDK Drift
# ---------------------------------------------------------------------------


class TestPythonSDKDrift:
    """Python SDK endpoints should match the OpenAPI spec."""

    def test_extract_py_endpoints_matches_public_request_calls(self):
        """The dominant `self._client.request(...)` form must be extracted.

        Regression: the extractor only matched the private `_request` form,
        leaving ~96% of Python SDK call sites invisible to drift detection.
        """
        content = (
            '        return self._client.request("POST", "/api/v1/memory/critiques", json=body)\n'
            '        return self._client._request("GET", "/api/v1/memory/stats")\n'
        )
        eps = _extract_py_endpoints(content)
        assert ("post", "/api/memory/critiques") in eps
        assert ("get", "/api/memory/stats") in eps

    def test_py_namespaces_directory_exists(self):
        """The Python namespaces directory must exist."""
        assert PY_NAMESPACES.exists(), f"Python namespaces not found: {PY_NAMESPACES}"

    def test_no_new_py_drift(self):
        """No new Python SDK endpoints should drift from the OpenAPI spec."""
        spec = _load_spec(OPENAPI_JSON)
        openapi_eps = _spec_endpoints(spec)

        if OPENAPI_GENERATED.exists():
            gen_spec = json.loads(OPENAPI_GENERATED.read_text())
            openapi_eps |= _spec_endpoints(gen_spec)

        assert PY_NAMESPACES.exists(), "Python namespaces not found"

        # Mirror the TS-side exclusion: the autogenerated catch-all OpenAPI
        # namespace is generated from the spec, so judging the spec against
        # it is circular.
        ignored_py_namespaces = {"openapi"}
        internal = _internal_prefixes()
        py_drift: list[tuple[str, str, str]] = []
        for py_file in sorted(PY_NAMESPACES.glob("*.py")):
            if py_file.name.startswith("_") or py_file.stem in ignored_py_namespaces:
                continue
            content = py_file.read_text()
            eps = _extract_py_endpoints(content)
            for ep in sorted(eps - openapi_eps):
                if _is_internal(ep[1], internal):
                    # Internal-route policy: internal families cannot be
                    # verified against the public spec (same exclusion the
                    # canonical checkers and the TS test above apply).
                    continue
                py_drift.append((py_file.stem, ep[0].upper(), ep[1]))

        baseline = _load_baseline()
        baseline_py = baseline.get("python_sdk_drift", set())
        new_drift = [(ns, m, p) for ns, m, p in py_drift if f"{m} {p}" not in baseline_py]

        assert not new_drift, (
            f"{len(new_drift)} NEW Python SDK drift entries "
            f"(total drift: {len(py_drift)}): "
            + "; ".join(f"{ns}: {m} {p}" for ns, m, p in new_drift[:10])
        )


# ---------------------------------------------------------------------------
# Tests: Cross-SDK Parity
# ---------------------------------------------------------------------------


class TestCrossSDKParity:
    """TypeScript and Python SDKs should have similar namespace coverage."""

    def test_namespace_parity(self):
        """Both SDKs should cover the same core namespaces."""
        assert TS_NAMESPACES.exists() and PY_NAMESPACES.exists(), (
            "One or both SDK namespace directories missing"
        )

        ts_ns = {
            p.stem.replace("-", "_")
            for p in TS_NAMESPACES.glob("*.ts")
            if p.stem != "index" and not p.name.startswith("_")
        }
        py_ns = {p.stem for p in PY_NAMESPACES.glob("*.py") if not p.name.startswith("_")}

        # Core namespaces that must be in both SDKs
        core = {
            "debates",
            "agents",
            "knowledge",
            "analytics",
            "auth",
            "workflows",
            "memory",
            "consensus",
        }

        ts_missing_core = core - ts_ns
        py_missing_core = core - py_ns

        assert not ts_missing_core, f"TypeScript SDK missing core namespaces: {ts_missing_core}"
        assert not py_missing_core, f"Python SDK missing core namespaces: {py_missing_core}"


# ---------------------------------------------------------------------------
# Tests: OpenAPI Spec Integrity
# ---------------------------------------------------------------------------


class TestOpenAPISpecIntegrity:
    """Deep checks on OpenAPI spec content quality."""

    def test_no_empty_paths(self):
        """Every path should have at least one operation."""
        spec = _load_spec(OPENAPI_JSON)
        empty_paths = []
        for path, ops in spec.get("paths", {}).items():
            methods = [m for m in ops if m.lower() in HTTP_METHODS]
            if not methods:
                empty_paths.append(path)
        assert not empty_paths, f"{len(empty_paths)} paths have no operations: {empty_paths[:10]}"

    def test_operations_have_responses(self):
        """Every operation should define at least one response."""
        spec = _load_spec(OPENAPI_JSON)
        missing_responses = []
        for path, ops in spec.get("paths", {}).items():
            for method, op_def in ops.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                if not isinstance(op_def, dict):
                    continue
                responses = op_def.get("responses", {})
                if not responses:
                    missing_responses.append(f"{method.upper()} {path}")
        # Allow a threshold since some operations may legitimately omit responses
        # during development
        max_missing = 50
        assert len(missing_responses) <= max_missing, (
            f"{len(missing_responses)} operations missing responses "
            f"(threshold={max_missing}): {missing_responses[:10]}"
        )
