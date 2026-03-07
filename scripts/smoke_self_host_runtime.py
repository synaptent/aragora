#!/usr/bin/env python3
"""
Runtime smoke test for self-hosted Aragora deployments.

Validates that a running Aragora server is responding correctly on its core
health, readiness, and API endpoints.  Uses only the Python standard library
(no pip install needed).

Usage:
    python scripts/smoke_self_host_runtime.py
    python scripts/smoke_self_host_runtime.py --base-url http://aragora:8080
    python scripts/smoke_self_host_runtime.py --api-token "$ARAGORA_API_TOKEN"
    python scripts/smoke_self_host_runtime.py --quiet

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_results: list[tuple[str, bool, str]] = []
_quiet = False


def _log(msg: str) -> None:
    if not _quiet:
        print(msg, flush=True)


def _check(name: str, passed: bool, detail: str = "") -> bool:
    _results.append((name, passed, detail))
    marker = "[PASS]" if passed else "[FAIL]"
    suffix = f"  ({detail})" if detail else ""
    _log(f"  {marker} {name}{suffix}")
    return passed


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _fetch(
    url: str,
    token: str | None = None,
    timeout: int = 10,
) -> tuple[int, dict[str, Any] | None, str]:
    """Fetch a URL and return (status_code, parsed_json_or_None, raw_body).

    Returns (-1, None, error_message) on connection failure.
    """
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                data = None
            return status, data, body
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            data = None
        return exc.code, data, body
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return -1, None, str(exc)


def _status_value(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    status = data.get("status", "")
    if not isinstance(status, str):
        return ""
    return status.strip().lower()


def _body_value(raw: str) -> str:
    return raw.strip().lower()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_liveness(base_url: str, token: str | None, timeout: int) -> bool:
    """GET /healthz -> expect 200 with status 'ok'."""
    url = f"{base_url}/healthz"
    status, data, raw = _fetch(url, token, timeout)
    if status == -1:
        return _check("/healthz (liveness)", False, f"connection failed: {raw}")
    if status != 200:
        return _check("/healthz (liveness)", False, f"HTTP {status}")
    normalized_status = _status_value(data)
    if normalized_status in {"ok", "healthy"}:
        return _check("/healthz (liveness)", True, f"status={normalized_status}")
    normalized_body = _body_value(raw)
    if normalized_body in {"ok", "healthy"}:
        return _check("/healthz (liveness)", True, f"body={normalized_body}")
    return _check("/healthz (liveness)", False, f"unexpected body: {raw[:80]}")


def check_readiness(base_url: str, token: str | None, timeout: int) -> bool:
    """GET /readyz -> expect 200 with status 'ready'."""
    url = f"{base_url}/readyz"
    status, data, raw = _fetch(url, token, timeout)
    if status == -1:
        return _check("/readyz (readiness)", False, f"connection failed: {raw}")
    if status == 503 and data:
        reason = data.get("reason", data.get("status", "not_ready"))
        return _check("/readyz (readiness)", False, f"HTTP 503: {reason}")
    if status != 200:
        return _check("/readyz (readiness)", False, f"HTTP {status}")
    normalized_status = _status_value(data)
    if normalized_status in {"ready", "ok"}:
        return _check("/readyz (readiness)", True, f"status={normalized_status}")
    normalized_body = _body_value(raw)
    if normalized_body in {"ready", "ok"}:
        return _check("/readyz (readiness)", True, f"body={normalized_body}")
    return _check("/readyz (readiness)", False, f"unexpected body: {raw[:80]}")


def check_health_api(base_url: str, token: str | None, timeout: int) -> bool:
    """GET /api/v1/health -> expect 200 with JSON body."""
    url = f"{base_url}/api/v1/health"
    status, data, raw = _fetch(url, token, timeout)
    if status == -1:
        return _check("/api/v1/health", False, f"connection failed: {raw}")
    if status != 200:
        return _check("/api/v1/health", False, f"HTTP {status}")
    if data is None:
        return _check("/api/v1/health", False, "response is not valid JSON")
    health_status = _status_value(data)
    if not health_status:
        return _check("/api/v1/health", False, "missing status field")
    return _check("/api/v1/health", True, f"status={health_status}")


def check_openapi(base_url: str, token: str | None, timeout: int) -> bool:
    """GET /api/v1/openapi.json -> expect 200 with valid JSON."""
    url = f"{base_url}/api/v1/openapi.json"
    status, data, raw = _fetch(url, token, timeout)
    if status == -1:
        return _check("/api/v1/openapi.json", False, f"connection failed: {raw}")
    if status != 200:
        return _check("/api/v1/openapi.json", False, f"HTTP {status}")
    if data is None:
        return _check("/api/v1/openapi.json", False, "response is not valid JSON")
    if not isinstance(data, dict):
        return _check("/api/v1/openapi.json", False, "response is not a JSON object")
    spec_version = data.get("openapi") or data.get("swagger")
    paths = data.get("paths")
    if not isinstance(spec_version, str):
        return _check("/api/v1/openapi.json", False, "missing openapi/swagger version field")
    if not isinstance(paths, dict) or not paths:
        return _check("/api/v1/openapi.json", False, "missing or empty paths object")
    return _check("/api/v1/openapi.json", True, f"openapi={spec_version}")


def check_build_info(base_url: str, token: str | None, timeout: int) -> bool:
    """GET /health/build -> expect 200 with JSON body."""
    url = f"{base_url}/health/build"
    status, data, raw = _fetch(url, token, timeout)
    if status == -1:
        return _check("/health/build", False, f"connection failed: {raw}")
    if status != 200:
        # Build endpoint may not be registered in minimal deployments
        return _check("/health/build", True, f"HTTP {status} (optional endpoint)")
    if data is None:
        return _check("/health/build", False, "response is not valid JSON")
    return _check("/health/build", True, "build info returned")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Runtime smoke test for self-hosted Aragora",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the Aragora server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-token",
        default=None,
        help="Optional API token for authenticated endpoints",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output; exit code only",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP request timeout in seconds (default: 10)",
    )
    args = parser.parse_args()

    global _quiet
    _quiet = args.quiet

    base = args.base_url.rstrip("/")
    token = args.api_token

    _log("Aragora runtime smoke test")
    _log(f"Target: {base}")
    _log("")

    # Run checks
    check_liveness(base, token, args.timeout)
    check_readiness(base, token, args.timeout)
    check_health_api(base, token, args.timeout)
    check_openapi(base, token, args.timeout)
    check_build_info(base, token, args.timeout)

    # Summary
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)

    _log("")
    _log(f"Results: {passed}/{total} passed, {failed} failed")

    if failed > 0:
        _log("")
        _log("Failed checks:")
        for name, ok, detail in _results:
            if not ok:
                _log(f"  - {name}: {detail}")
        return 1

    _log("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
