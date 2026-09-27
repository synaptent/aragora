#!/usr/bin/env python3
"""Probe VibeProxy readiness without sending an inference request."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.agents.transports.vibeproxy import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_CATALOG_TTL_SECONDS,
    VibeProxyClient,
    VibeProxyConfigurationError,
    VibeProxyRedirectError,
    VibeProxyResponseError,
    VibeProxyTimeoutError,
    VibeProxyUnavailableError,
)

SCHEMA_VERSION = 1
DEFAULT_TOTAL_TIMEOUT_SECONDS = 3.0
ARAGORA_IMPLEMENTED_NOT_PROBED = (
    "POST /v1/chat/completions",
    "POST /v1/messages",
    "POST /v1/responses",
)
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check VibeProxy readiness using metadata-only GET requests."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ARAGORA_VIBEPROXY_BASE_URL", DEFAULT_BASE_URL),
        help="VibeProxy base URL (default: ARAGORA_VIBEPROXY_BASE_URL or loopback :8318)",
    )
    parser.add_argument(
        "--timeout-seconds",
        default=os.environ.get(
            "ARAGORA_VIBEPROXY_DIAGNOSTIC_TIMEOUT_SECONDS",
            str(DEFAULT_TOTAL_TIMEOUT_SECONDS),
        ),
        help="One total deadline shared by all diagnostic requests",
    )
    parser.add_argument(
        "--catalog-ttl-seconds",
        default=os.environ.get(
            "ARAGORA_VIBEPROXY_CATALOG_TTL_SECONDS",
            str(DEFAULT_CATALOG_TTL_SECONDS),
        ),
        help="Process-local catalog cache TTL reported in the result",
    )
    parser.add_argument("--json", action="store_true", help="Emit one JSON object")
    return parser


def _number(value: str | int | float, *, name: str, minimum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise VibeProxyConfigurationError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < minimum:
        raise VibeProxyConfigurationError(f"{name} must be finite and >= {minimum}")
    return result


def _empty_result() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "endpoint": {"url": None, "loopback": None},
        "version": {"value": None, "source": "unknown"},
        "protocols": {
            "advertised": [],
            "advertised_redacted_count": 0,
            "verified_no_inference": [],
            "aragora_implemented_not_probed": list(ARAGORA_IMPLEMENTED_NOT_PROBED),
            "metadata_status": "not_attempted",
        },
        "model_inventory": {"count": 0, "models": [], "redacted_count": 0},
        "catalog_freshness": {
            "scope": "process_local",
            "source": "none",
            "age_seconds": None,
            "ttl_seconds": None,
            "fresh": False,
        },
        "latency_ms": {"catalog": None, "metadata": None, "total": None},
        "error": None,
    }


def _error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, VibeProxyConfigurationError):
        category = "configuration"
        message = str(exc)
    elif isinstance(exc, VibeProxyRedirectError):
        category = "redirect_denied"
        message = "VibeProxy attempted a redirect"
    elif isinstance(exc, VibeProxyTimeoutError):
        category = "timeout"
        message = "VibeProxy did not respond within the diagnostic deadline"
    elif isinstance(exc, VibeProxyResponseError):
        category = "malformed_response"
        message = str(exc)
    elif isinstance(exc, VibeProxyUnavailableError):
        category = "unavailable"
        message = str(exc)
    else:
        category = "internal"
        message = "VibeProxy diagnostic failed"
    return {"category": category, "message": message}


def _elapsed_ms(started: float, *, now: float | None = None) -> float:
    finished = time.monotonic() if now is None else now
    return round(max(0.0, finished - started) * 1000.0, 3)


def _credential_safe(value: str, *, credential: str) -> bool:
    """Return whether a server-controlled value is safe for operator output."""

    return not credential or credential not in value


def diagnose(
    *,
    base_url: str,
    api_key: str | None,
    timeout_seconds: str | float,
    catalog_ttl_seconds: str | float,
) -> dict[str, Any]:
    """Return one stable, sanitized readiness result."""

    result = _empty_result()
    started = time.monotonic()
    try:
        total_timeout = _number(timeout_seconds, name="diagnostic timeout", minimum=0.1)
        ttl = _number(catalog_ttl_seconds, name="catalog TTL", minimum=0.0)
        client = VibeProxyClient(
            base_url,
            api_key,
            catalog_ttl_seconds=ttl,
            connect_timeout_seconds=total_timeout,
        )
        result["endpoint"] = {
            "url": client.base_url,
            "loopback": client.is_loopback,
        }
        result["catalog_freshness"]["ttl_seconds"] = ttl
        deadline = started + total_timeout

        catalog_started = time.monotonic()
        try:
            remaining = deadline - catalog_started
            if remaining <= 0:
                raise VibeProxyTimeoutError("VibeProxy request timed out")
            catalog = client.catalog(force=True, timeout=remaining)
        finally:
            catalog_finished = time.monotonic()
            result["latency_ms"]["catalog"] = _elapsed_ms(catalog_started, now=catalog_finished)
        models = sorted(catalog.models)
        credential = client.api_key or ""
        safe_models = [
            model
            for model in models
            if _SAFE_MODEL_ID.fullmatch(model) and _credential_safe(model, credential=credential)
        ]
        result["model_inventory"] = {
            "count": len(models),
            "models": safe_models,
            "redacted_count": len(models) - len(safe_models),
        }
        age = max(0.0, catalog_finished - catalog.fetched_at)
        result["catalog_freshness"].update(
            {
                "source": "live",
                "age_seconds": round(age, 6),
                "fresh": age < ttl,
            }
        )
        result["protocols"]["verified_no_inference"] = ["GET /v1/models"]

        metadata_started = time.monotonic()
        remaining = deadline - metadata_started
        if remaining <= 0:
            result["protocols"]["metadata_status"] = "timeout"
        else:
            try:
                metadata = client.metadata(timeout=remaining)
            except VibeProxyUnavailableError as exc:
                result["protocols"]["metadata_status"] = _error(exc)["category"]
            else:
                advertised = list(metadata.advertised_routes)
                safe_advertised = [
                    route for route in advertised if _credential_safe(route, credential=credential)
                ]
                result["protocols"]["advertised"] = safe_advertised
                result["protocols"]["advertised_redacted_count"] = len(advertised) - len(
                    safe_advertised
                )
                result["protocols"]["metadata_status"] = "verified"
                if metadata.version is not None and not _credential_safe(
                    metadata.version, credential=credential
                ):
                    result["version"] = {"value": None, "source": "redacted"}
                else:
                    result["version"] = {
                        "value": metadata.version,
                        "source": metadata.version_source,
                    }
            finally:
                result["latency_ms"]["metadata"] = _elapsed_ms(metadata_started)

        result["ok"] = True
    except Exception as exc:  # Keep --json machine-readable for operational failures.
        result["error"] = _error(exc)
    finally:
        result["latency_ms"]["total"] = _elapsed_ms(started)
    return result


def _render_human(result: dict[str, Any]) -> None:
    status = "ready" if result["ok"] else "not ready"
    print(f"VibeProxy: {status}")
    endpoint = result["endpoint"]
    if endpoint["url"] is not None:
        print(f"endpoint={endpoint['url']} loopback={str(endpoint['loopback']).lower()}")
    inventory = result["model_inventory"]
    print(f"models={inventory['count']}")
    if inventory["redacted_count"]:
        print(f"models_redacted={inventory['redacted_count']}")
    if inventory["models"]:
        print("model_ids=" + ",".join(inventory["models"]))
    protocols = result["protocols"]
    print("verified_no_inference=" + ",".join(protocols["verified_no_inference"]))
    print("advertised=" + ",".join(protocols["advertised"]))
    version = result["version"]
    print(f"version={version['value'] or 'unknown'} source={version['source']}")
    print(f"total_latency_ms={result['latency_ms']['total']}")
    if result["error"]:
        print(
            f"error={result['error']['category']}: {result['error']['message']}",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = diagnose(
        base_url=args.base_url,
        api_key=os.environ.get("ARAGORA_VIBEPROXY_API_KEY") or None,
        timeout_seconds=args.timeout_seconds,
        catalog_ttl_seconds=args.catalog_ttl_seconds,
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        _render_human(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
