#!/usr/bin/env python3
"""
Static validation for self-host production compose stack.

This is a lightweight CI guard that validates:
- required services exist in docker-compose.production.yml
- aragora depends_on includes postgres + 3 sentinels
- sentinel Redis env wiring is present
- required vars exist in .env.production.example
- session/rate-limit defaults are wired for distributed deployments
- self-host runbook includes startup/health/recovery sections
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


CORE_REQUIRED_SERVICES = {"aragora", "postgres"}

SENTINEL_REQUIRED_SERVICES = {
    "redis-master",
    "redis-replica-1",
    "redis-replica-2",
    "sentinel-1",
    "sentinel-2",
    "sentinel-3",
}

STANDALONE_REQUIRED_SERVICES = {"redis"}

BASE_REQUIRED_ENV_KEYS = {
    "POSTGRES_PASSWORD",
    "ARAGORA_API_TOKEN",
    "ARAGORA_JWT_SECRET",
    "ARAGORA_ENCRYPTION_KEY",
    "ARAGORA_RATE_LIMIT_BACKEND",
    "ARAGORA_REDIS_MODE",
    "ARAGORA_STRICT_DEPLOYMENT",
}

DOMAIN_ENV_ALIASES = {"DOMAIN", "ARAGORA_DOMAIN"}

BASE_REQUIRED_ARAGORA_ENV_KEYS = {
    "DATABASE_URL",
    "ARAGORA_DB_BACKEND",
    "ARAGORA_SECRETS_STRICT",
    "ARAGORA_REDIS_MODE",
    "ARAGORA_JWT_SECRET",
    "ARAGORA_ENCRYPTION_KEY",
    "ARAGORA_RATE_LIMIT_BACKEND",
}

SENTINEL_REQUIRED_ARAGORA_ENV_KEYS = {
    "ARAGORA_REDIS_SENTINEL_HOSTS",
    "ARAGORA_REDIS_SENTINEL_MASTER",
}

RUNBOOK_MARKER_ALIASES = {
    "Production Compose Semantics": ("Production Compose Semantics",),
    "Production Ingress Verification": (
        "Production Ingress Verification",
        "Startup and Readiness Verification",
        "Verify Installation",
    ),
    "Startup and Readiness Verification": (
        "Startup and Readiness Verification",
        "Verify Installation",
    ),
    "Health Checks": (
        "Health Checks",
        "Verify Installation",
    ),
    "Failure Recovery Playbook": (
        "Failure Recovery Playbook",
        "Troubleshooting",
    ),
}


def _parse_env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=", line)
        if m:
            keys.add(m.group(1))
    return keys


def _parse_service_env(service: dict[str, object]) -> dict[str, str]:
    raw_env = service.get("environment", [])
    parsed: dict[str, str] = {}
    if isinstance(raw_env, dict):
        for key, value in raw_env.items():
            parsed[str(key)] = "" if value is None else str(value)
        return parsed

    if isinstance(raw_env, list):
        for item in raw_env:
            text = str(item)
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def _contains_required_runbook_markers(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    missing: list[str] = []
    for canonical, aliases in sorted(RUNBOOK_MARKER_ALIASES.items()):
        if not any(alias in text for alias in aliases):
            missing.append(canonical)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate production self-host compose configuration"
    )
    parser.add_argument("--compose", default="docker-compose.production.yml")
    parser.add_argument("--env-example", default=".env.production.example")
    parser.add_argument("--runbook", default="docs/SELF_HOSTING.md")
    args = parser.parse_args()

    compose_path = Path(args.compose)
    env_path = Path(args.env_example)
    runbook_path = Path(args.runbook)

    if not compose_path.exists():
        print(f"Compose file not found: {compose_path}", file=sys.stderr)
        return 2
    if not env_path.exists():
        print(f"Env example file not found: {env_path}", file=sys.stderr)
        return 2
    if not runbook_path.exists():
        print(f"Runbook file not found: {runbook_path}", file=sys.stderr)
        return 2

    try:
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"Failed to parse compose YAML: {exc}", file=sys.stderr)
        return 2

    services = compose.get("services")
    if not isinstance(services, dict):
        print("Compose file has no valid 'services' section", file=sys.stderr)
        return 2

    errors: list[str] = []

    service_names = set(services.keys())
    missing_core_services = sorted(CORE_REQUIRED_SERVICES - service_names)
    if missing_core_services:
        errors.append(f"Missing required services: {missing_core_services}")

    has_sentinel_topology = {"sentinel-1", "sentinel-2", "sentinel-3"}.issubset(service_names)
    has_standalone_topology = "redis" in service_names
    redis_topology = "none"
    if has_sentinel_topology:
        redis_topology = "sentinel"
        missing_sentinel_services = sorted(SENTINEL_REQUIRED_SERVICES - service_names)
        if missing_sentinel_services:
            errors.append(f"Missing required services: {missing_sentinel_services}")
    elif has_standalone_topology:
        redis_topology = "standalone"
    else:
        errors.append("Missing Redis topology services (expected sentinel-* or redis)")

    aragora_service = services.get("aragora", {})
    depends_on = aragora_service.get("depends_on", {})
    if isinstance(depends_on, dict):
        dependency_names = set(depends_on.keys())
    elif isinstance(depends_on, list):
        dependency_names = {str(item) for item in depends_on}
    else:
        dependency_names = set()

    required_dependencies = {"postgres"}
    if redis_topology == "sentinel":
        required_dependencies.update({"sentinel-1", "sentinel-2", "sentinel-3"})
    elif redis_topology == "standalone":
        required_dependencies.add("redis")
    missing_dependencies = sorted(required_dependencies - dependency_names)
    if missing_dependencies:
        errors.append(f"aragora service missing required dependencies: {missing_dependencies}")

    parsed_aragora_env = _parse_service_env(aragora_service)

    required_aragora_env = set(BASE_REQUIRED_ARAGORA_ENV_KEYS)
    if redis_topology == "sentinel":
        required_aragora_env.update(SENTINEL_REQUIRED_ARAGORA_ENV_KEYS)

    missing_aragora_env = sorted(
        key for key in required_aragora_env if key not in parsed_aragora_env
    )
    if missing_aragora_env:
        errors.append(f"aragora service missing required env wiring: {missing_aragora_env}")

    db_backend = parsed_aragora_env.get("ARAGORA_DB_BACKEND", "")
    if "postgres" not in db_backend:
        errors.append(
            "aragora service should set ARAGORA_DB_BACKEND=postgres for production compose"
        )

    rate_limit_backend = parsed_aragora_env.get("ARAGORA_RATE_LIMIT_BACKEND", "")
    if "redis" not in rate_limit_backend:
        errors.append(
            "aragora service should set ARAGORA_RATE_LIMIT_BACKEND=redis for distributed limits"
        )

    redis_mode = parsed_aragora_env.get("ARAGORA_REDIS_MODE", "")
    normalized_mode = redis_mode.strip().lower()
    if redis_topology == "sentinel" and normalized_mode and "sentinel" not in normalized_mode:
        errors.append("aragora service should set ARAGORA_REDIS_MODE=sentinel")
    if redis_topology == "standalone" and normalized_mode:
        if "standalone" not in normalized_mode and "single" not in normalized_mode:
            errors.append("aragora service should set ARAGORA_REDIS_MODE=standalone")

    if redis_topology == "standalone":
        if not (parsed_aragora_env.get("REDIS_URL") or parsed_aragora_env.get("ARAGORA_REDIS_URL")):
            errors.append(
                "aragora service should set REDIS_URL or ARAGORA_REDIS_URL for standalone Redis"
            )

    required_healthcheck_services = set(CORE_REQUIRED_SERVICES)
    if redis_topology == "sentinel":
        required_healthcheck_services.update(SENTINEL_REQUIRED_SERVICES)
    elif redis_topology == "standalone":
        required_healthcheck_services.update(STANDALONE_REQUIRED_SERVICES)

    missing_healthcheck = sorted(
        name
        for name in required_healthcheck_services
        if name in services
        and isinstance(services[name], dict)
        and "healthcheck" not in services[name]
    )
    if missing_healthcheck:
        errors.append(f"services missing healthcheck configuration: {missing_healthcheck}")

    env_keys = _parse_env_keys(env_path)
    missing_env_keys = sorted(BASE_REQUIRED_ENV_KEYS - env_keys)
    if missing_env_keys:
        errors.append(f".env production example missing required keys: {missing_env_keys}")

    if not any(domain_key in env_keys for domain_key in DOMAIN_ENV_ALIASES):
        errors.append(
            ".env production example missing required domain key: one of "
            f"{sorted(DOMAIN_ENV_ALIASES)}"
        )

    if redis_topology == "sentinel":
        missing_sentinel_env_keys = sorted(
            {"ARAGORA_REDIS_SENTINEL_HOSTS", "ARAGORA_REDIS_SENTINEL_MASTER"} - env_keys
        )
        if missing_sentinel_env_keys:
            errors.append(
                f".env production example missing required keys: {missing_sentinel_env_keys}"
            )

    missing_markers = _contains_required_runbook_markers(runbook_path)
    if missing_markers:
        errors.append(f"self-host runbook missing required sections: {missing_markers}")

    if errors:
        print("Self-host compose validation failed:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(
        "Self-host compose validation passed "
        f"(services={len(services)}, redis_topology={redis_topology})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
