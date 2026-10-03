#!/usr/bin/env python3
"""
Verify SDK contracts against OpenAPI specification.

Checks that all SDK namespace endpoints exist in the OpenAPI spec and
reports coverage metrics. Used as a CI gate for SDK generation.

Usage:
    python scripts/verify_sdk_contracts.py
    python scripts/verify_sdk_contracts.py --strict  # Fail on any drift
    python scripts/verify_sdk_contracts.py --strict --baseline scripts/baselines/verify_sdk_contracts.json
    python scripts/verify_sdk_contracts.py --extra-spec docs/api/openapi_generated.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}

PY_REQUEST_RE = re.compile(
    r'self\._client\._?request\(\s*["\'](?P<method>GET|POST|PUT|PATCH|DELETE)["\']'
    r'\s*,\s*(?:f?["\'])(?P<path>/api/[^"\']+)["\']'
)
TS_REQUEST_RE = re.compile(
    r"this\.client\.request\(\s*['\"](?P<method>[A-Z]+)['\"]\s*,"
    r"\s*(?P<path>`[^`]+`|'[^']+'|\"[^\"]+\")"
)
TS_DIRECT_RE = re.compile(
    r"this\.client\.(?P<method>get|post|put|delete|patch)\("
    r"\s*(?P<path>`[^`]+`|'[^']+'|\"[^\"]+\")"
)


try:
    # Direct script execution (python scripts/verify_sdk_contracts.py)
    from sdk_path_normalize import normalize_sdk_path
    from validate_openapi_routes import is_internal_route, load_internal_prefixes
except ModuleNotFoundError:
    # Module import context (pytest importing scripts.verify_sdk_contracts)
    from scripts.sdk_path_normalize import normalize_sdk_path
    from scripts.validate_openapi_routes import is_internal_route, load_internal_prefixes


def _normalize(path: str) -> str:
    return normalize_sdk_path(path)


def _normalized_internal_prefixes() -> tuple[str, ...]:
    """Internal-route policy prefixes in SDK-normalized (version-stripped) form.

    Internal route families (control-plane, SSO, emergency admin, ...) are
    excluded from the public OpenAPI spec by generate_openapi.py, and the
    route-coverage gate excludes them from both sides of its comparison.
    SDK namespaces and the stability manifest may still reference those
    served-but-internal endpoints; they cannot be verified against the
    public spec, so this checker excludes them under the same policy file.
    Fails closed (SystemExit) when the policy is unusable.
    """
    return tuple(_normalize(p) for p in load_internal_prefixes())


def _is_internal(normalized_path: str, internal_prefixes: tuple[str, ...]) -> bool:
    return is_internal_route(normalized_path, internal_prefixes)


def _load_openapi_endpoints(spec_path: Path) -> set[tuple[str, str]]:
    spec = json.loads(spec_path.read_text())
    endpoints: set[tuple[str, str]] = set()
    for path, ops in spec.get("paths", {}).items():
        for method in ops:
            if method.lower() in HTTP_METHODS:
                endpoints.add((method.lower(), _normalize(path)))
    return endpoints


def _load_openapi_endpoints_multi(spec_paths: list[Path]) -> set[tuple[str, str]]:
    endpoints: set[tuple[str, str]] = set()
    for path in spec_paths:
        if path.exists():
            endpoints |= _load_openapi_endpoints(path)
    return endpoints


def _extract_py(content: str) -> set[tuple[str, str]]:
    eps: set[tuple[str, str]] = set()
    for m in PY_REQUEST_RE.finditer(content):
        path = _normalize(m.group("path"))
        if path.startswith("/api/"):
            eps.add((m.group("method").lower(), path))
    return eps


def _extract_ts(content: str) -> set[tuple[str, str]]:
    eps: set[tuple[str, str]] = set()
    for m in TS_REQUEST_RE.finditer(content):
        eps.add((m.group("method").lower(), _normalize(m.group("path")[1:-1])))
    for m in TS_DIRECT_RE.finditer(content):
        eps.add((m.group("method").lower(), _normalize(m.group("path")[1:-1])))
    return eps


def _entry(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def _load_baseline(path: Path | None) -> dict[str, set[str]]:
    if path is None:
        return {"python_sdk_drift": set(), "typescript_sdk_drift": set(), "missing_stable": set()}
    if not path.exists():
        print(f"WARNING: Baseline file not found: {path}")
        return {"python_sdk_drift": set(), "typescript_sdk_drift": set(), "missing_stable": set()}

    data = json.loads(path.read_text())
    return {
        "python_sdk_drift": set(data.get("python_sdk_drift", [])),
        "typescript_sdk_drift": set(data.get("typescript_sdk_drift", [])),
        "missing_stable": set(data.get("missing_stable", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SDK contracts against OpenAPI.")
    parser.add_argument("--strict", action="store_true", help="Fail on any drift")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("scripts/baselines/verify_sdk_contracts.json"),
        help="Path to drift baseline file (default: scripts/baselines/verify_sdk_contracts.json)",
    )
    parser.add_argument(
        "--extra-spec",
        action="append",
        default=[],
        help="Additional OpenAPI JSON spec path(s) to union for drift comparison",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    spec_path = repo / "docs/api/openapi.json"
    if not spec_path.exists():
        print("ERROR: docs/api/openapi.json not found", file=sys.stderr)
        return 1

    spec_paths = [spec_path]
    default_generated = repo / "docs/api/openapi_generated.json"
    if default_generated.exists():
        spec_paths.append(default_generated)
    for extra in args.extra_spec:
        p = Path(extra)
        if not p.is_absolute():
            p = repo / p
        spec_paths.append(p)

    openapi_eps = _load_openapi_endpoints_multi(spec_paths)

    def _label(path: Path) -> str:
        try:
            return str(path.relative_to(repo))
        except ValueError:
            return str(path)

    spec_labels = ", ".join(_label(p) for p in spec_paths)
    print(f"OpenAPI spec (union: {spec_labels}): {len(openapi_eps)} endpoints")

    internal_prefixes = _normalized_internal_prefixes()
    internal_skipped = 0

    # Check Python SDK
    py_dir = repo / "sdk/python/aragora_sdk/namespaces"
    # Ignore the autogenerated catch-all OpenAPI helper namespace here, same
    # as the TypeScript side below: it is generated from the spec, so judging
    # the spec against it is circular, and it is validated by the OpenAPI
    # generation pipeline rather than by namespace contract drift.
    ignored_py_namespaces = {"openapi"}
    py_ns = sorted(
        p.stem
        for p in py_dir.glob("*.py")
        if not p.stem.startswith("_") and p.stem not in ignored_py_namespaces
    )
    py_total = 0
    py_drift: list[tuple[str, str, str]] = []

    for ns in py_ns:
        content = (py_dir / f"{ns}.py").read_text()
        eps = _extract_py(content)
        py_total += len(eps)
        for ep in sorted(eps - openapi_eps):
            if _is_internal(ep[1], internal_prefixes):
                internal_skipped += 1
                continue
            py_drift.append((ns, ep[0].upper(), ep[1]))

    # Check TypeScript SDK
    ts_dir = repo / "sdk/typescript/src/namespaces"
    # Ignore the autogenerated catch-all OpenAPI helper namespace here.
    # It is intentionally broader than the curated SDK surface and is validated
    # by the OpenAPI generation pipeline rather than by namespace contract drift.
    ignored_ts_namespaces = {"openapi"}
    ts_ns = sorted(
        p.stem
        for p in ts_dir.glob("*.ts")
        if not p.stem.startswith("_") and p.stem not in ignored_ts_namespaces
    )
    ts_total = 0
    ts_drift: list[tuple[str, str, str]] = []

    for ns in ts_ns:
        content = (ts_dir / f"{ns}.ts").read_text()
        eps = _extract_ts(content)
        ts_total += len(eps)
        for ep in sorted(eps - openapi_eps):
            if _is_internal(ep[1], internal_prefixes):
                internal_skipped += 1
                continue
            ts_drift.append((ns, ep[0].upper(), ep[1]))

    if internal_skipped:
        print(
            f"\nInternal-route policy: {internal_skipped} SDK endpoint reference(s) in "
            "internal families excluded from public-spec drift"
        )

    # Parity check
    py_ns_set = set(py_ns)
    ts_ns_set = {name.replace("-", "_") for name in ts_ns}
    py_only = sorted(py_ns_set - ts_ns_set)
    ts_only = sorted(ts_ns_set - py_ns_set)

    # Report
    print(f"\nPython SDK:     {len(py_ns)} namespaces, {py_total} endpoint references")
    print(f"TypeScript SDK: {len(ts_ns)} namespaces, {ts_total} endpoint references")

    print(f"\nParity: Python-only={len(py_only)}, TypeScript-only={len(ts_only)}")
    if py_only:
        print(f"  Python-only namespaces: {py_only[:10]}")
    if ts_only:
        print(f"  TypeScript-only namespaces: {ts_only[:10]}")

    has_drift = False
    py_drift_entries = {_entry(m, p) for _, m, p in py_drift}
    ts_drift_entries = {_entry(m, p) for _, m, p in ts_drift}
    baseline = _load_baseline(args.baseline)
    if py_drift:
        print(f"\nPython SDK drift ({len(py_drift)} endpoints not in spec):")
        for ns, method, path in py_drift[:20]:
            print(f"  {ns}: {method} {path}")
        has_drift = True

    if ts_drift:
        print(f"\nTypeScript SDK drift ({len(ts_drift)} endpoints not in spec):")
        for ns, method, path in ts_drift[:20]:
            print(f"  {ns}: {method} {path}")
        has_drift = True

    # Stability manifest check
    manifest_path = repo / "aragora/server/openapi/stability_manifest.json"
    missing_stable_entries: set[str] = set()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        stable = manifest.get("stable", [])
        missing_stable = []
        stable_internal = 0
        for entry in stable:
            parts = entry.split(" ", 1)
            if len(parts) == 2:
                method, path = parts[0].lower(), _normalize(parts[1])
                if _is_internal(path, internal_prefixes):
                    # Internal families are excluded from the public spec by
                    # policy; served-but-internal stable entries cannot be
                    # verified against it.
                    stable_internal += 1
                    continue
                if (method, path) not in openapi_eps:
                    missing_stable.append(entry)
        print(
            f"\nStability manifest: {len(stable)} stable, {len(missing_stable)} missing from spec"
            + (f", {stable_internal} internal (excluded by policy)" if stable_internal else "")
        )
        if missing_stable:
            for entry in missing_stable[:10]:
                print(f"  MISSING: {entry}")
            has_drift = True
        missing_stable_entries = set(missing_stable)

    new_py = py_drift_entries - baseline["python_sdk_drift"]
    new_ts = ts_drift_entries - baseline["typescript_sdk_drift"]
    new_missing_stable = missing_stable_entries - baseline["missing_stable"]
    if args.baseline:
        print(
            "\nBaseline regressions:"
            f" py={len(new_py)} ts={len(new_ts)} stable={len(new_missing_stable)}"
        )
        if new_py:
            for entry in sorted(new_py)[:10]:
                print(f"  NEW PY: {entry}")
        if new_ts:
            for entry in sorted(new_ts)[:10]:
                print(f"  NEW TS: {entry}")
        if new_missing_stable:
            for entry in sorted(new_missing_stable)[:10]:
                print(f"  NEW STABLE MISSING: {entry}")

    if not has_drift:
        print("\nAll SDK contracts verified!")
        return 0

    if args.strict:
        if new_py or new_ts or new_missing_stable:
            print("\nFAILED: SDK/API drift regression detected (--strict mode)")
            return 1
        print("\nPASS: No new SDK/API drift relative to baseline (--strict mode)")
        return 0

    print("\nWARNING: SDK/API drift detected (use --strict to fail)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
