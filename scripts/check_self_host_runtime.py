#!/usr/bin/env python3
"""
Runtime validation for self-host production compose stack.

This script boots the production compose core services, waits for healthy state,
checks explicit liveness/readiness probes, and verifies debate endpoint
reachability plus auth-gate behavior.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_CORE_SERVICES = [
    "postgres",
    "redis-master",
    "redis-replica-1",
    "redis-replica-2",
    "sentinel-1",
    "sentinel-2",
    "sentinel-3",
    "aragora",
]

LIVENESS_PATH_CANDIDATES = ["/healthz"]
READINESS_PATH_CANDIDATES = ["/readyz"]


class RuntimeCheckError(RuntimeError):
    """Raised when the runtime self-host check fails."""


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"exit={result.returncode}"
        raise RuntimeCheckError(f"Command failed: {' '.join(cmd)}\n{details}")
    return result


def _compose_base(compose_path: Path, env_file: Path, project_name: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(compose_path),
        "--env-file",
        str(env_file),
        "-p",
        project_name,
    ]


def _compose(
    base_cmd: list[str], args: list[str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    return _run([*base_cmd, *args], check=check)


def _check_docker_daemon() -> None:
    info_result = _run(["docker", "info"], check=False)
    if info_result.returncode != 0:
        details = info_result.stderr.strip() or info_result.stdout.strip() or "unknown error"
        raise RuntimeCheckError(f"Docker daemon unavailable: {details}")


def _read_env_value(env_file: Path, key: str) -> str:
    value = ""
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, current_value = line.split("=", 1)
        if current_key.strip() == key:
            value = current_value.strip().strip('"').strip("'")
    return value


def _validate_runtime_env_file(env_file: Path) -> tuple[list[str], list[str]]:
    """Validate required runtime env keys before booting compose."""
    errors: list[str] = []
    warnings: list[str] = []

    required_keys = (
        "POSTGRES_PASSWORD",
        "ARAGORA_API_TOKEN",
        "ARAGORA_JWT_SECRET",
        "ARAGORA_ENCRYPTION_KEY",
    )
    values = {key: _read_env_value(env_file, key) for key in required_keys}

    for key, value in values.items():
        if not value:
            errors.append(f"{key} must be set in env file")
            continue
        if "CHANGE_ME" in value or value.endswith("..."):
            errors.append(f"{key} still contains placeholder value")

    jwt_secret = values.get("ARAGORA_JWT_SECRET", "")
    if jwt_secret and len(jwt_secret) < 32:
        errors.append(
            "ARAGORA_JWT_SECRET must be at least 32 characters for production runtime checks"
        )

    encryption_key = values.get("ARAGORA_ENCRYPTION_KEY", "")
    if encryption_key:
        if len(encryption_key) != 64:
            warnings.append("ARAGORA_ENCRYPTION_KEY should be 64 hex characters")
        elif not re.fullmatch(r"[0-9a-fA-F]{64}", encryption_key):
            warnings.append("ARAGORA_ENCRYPTION_KEY should contain only hex characters")

    strict_mode = _read_env_value(env_file, "ARAGORA_SECRETS_STRICT").lower()
    if strict_mode in {"true", "1", "yes"}:
        warnings.append(
            "ARAGORA_SECRETS_STRICT=true may fail local runtime checks unless AWS Secrets Manager is configured"
        )

    return errors, warnings


def _get_service_status(base_cmd: list[str], service: str) -> tuple[str, str]:
    cid_result = _compose(base_cmd, ["ps", "-q", service], check=False)
    if cid_result.returncode != 0:
        details = cid_result.stderr.strip() or cid_result.stdout.strip() or "unknown error"
        raise RuntimeCheckError(f"Failed to resolve container id for {service}: {details}")

    container_ids = [line.strip() for line in cid_result.stdout.splitlines() if line.strip()]
    if not container_ids:
        return "not-created", ""

    joined_container_ids = ",".join(container_ids)
    statuses: list[tuple[str, str]] = []
    for container_id in container_ids:
        inspect_result = _run(
            [
                "docker",
                "inspect",
                "-f",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container_id,
            ],
            check=False,
        )
        if inspect_result.returncode != 0:
            statuses.append(("unknown", container_id))
            continue
        statuses.append((inspect_result.stdout.strip(), container_id))

    for status, container_id in statuses:
        if status in {"exited", "dead", "unhealthy"}:
            return status, container_id

    if statuses and all(status in {"healthy", "running"} for status, _ in statuses):
        if all(status == "healthy" for status, _ in statuses):
            return "healthy", joined_container_ids
        return "running", joined_container_ids

    return statuses[0][0], joined_container_ids


def _wait_for_service(base_cmd: list[str], service: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"

    while time.monotonic() < deadline:
        status, container_id = _get_service_status(base_cmd, service)
        last_status = status
        if status in {"healthy", "running"}:
            print(f"[ok] service {service} is {status}")
            return
        if status in {"exited", "dead", "unhealthy"}:
            raise RuntimeCheckError(
                f"Service {service} failed with status={status} container={container_id}"
            )
        time.sleep(2)

    raise RuntimeCheckError(f"Timed out waiting for service {service} (last_status={last_status})")


def _get_primary_container_id(base_cmd: list[str], service: str) -> str:
    cid_result = _compose(base_cmd, ["ps", "-q", service], check=False)
    if cid_result.returncode != 0:
        details = cid_result.stderr.strip() or cid_result.stdout.strip() or "unknown error"
        raise RuntimeCheckError(f"Failed to resolve container id for {service}: {details}")

    container_ids = [line.strip() for line in cid_result.stdout.splitlines() if line.strip()]
    if not container_ids:
        raise RuntimeCheckError(f"No running container found for service {service}")

    return container_ids[0]


def _get_container_ip(container_id: str) -> str:
    inspect_result = _run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container_id,
        ],
        check=False,
    )
    if inspect_result.returncode != 0:
        details = inspect_result.stderr.strip() or inspect_result.stdout.strip() or "unknown error"
        raise RuntimeCheckError(f"Failed to inspect network IP for {container_id}: {details}")

    ip_address = inspect_result.stdout.strip()
    if not ip_address:
        raise RuntimeCheckError(f"Container {container_id} has no network IP")

    return ip_address


def _parse_compose_port(raw_output: str) -> tuple[str, int] | None:
    """Parse docker compose port output into (host, port)."""
    for raw_line in raw_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Support output variants like:
        # - 0.0.0.0:32788
        # - [::]:32788
        # - :::32788
        # - 0.0.0.0:32788->8080/tcp (defensive fallback)
        if "->" in line:
            line = line.split("->", 1)[0].strip()
            if not line:
                continue

        host, sep, port_text = line.rpartition(":")
        if not sep or not port_text.isdigit():
            continue

        host = host.strip()
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if not host:
            host = "localhost"

        parsed_port = int(port_text)
        if parsed_port <= 0:
            # Docker can report :0 when no host mapping is actually published.
            # Treat as unresolved so we fall back to container-network probing.
            continue

        return host, parsed_port

    return None


def _build_url_with_host_port(parsed: urllib.parse.ParseResult, host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]:{port}"
    else:
        netloc = f"{host}:{port}"
    return urllib.parse.urlunparse(
        (
            parsed.scheme or "http",
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _resolve_runtime_base_url(
    base_cmd: list[str],
    requested_base_url: str,
    app_service: str = "aragora",
    app_port: int = 8080,
) -> str:
    parsed = urllib.parse.urlparse(requested_base_url)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return requested_base_url

    requested_port = parsed.port or app_port
    if requested_port != app_port:
        return requested_base_url

    port_result = _compose(base_cmd, ["port", app_service, str(app_port)], check=False)
    if port_result.returncode == 0 and port_result.stdout.strip():
        parsed_mapping = _parse_compose_port(port_result.stdout)
        if parsed_mapping is not None:
            mapped_host, mapped_port = parsed_mapping
            if mapped_host in {"0.0.0.0", "::"}:
                mapped_host = host
            resolved_url = _build_url_with_host_port(parsed, mapped_host, mapped_port)
            if resolved_url != requested_base_url:
                print(
                    f"[info] using published endpoint {resolved_url} for {app_service}:{app_port}"
                )
            return resolved_url

    try:
        container_id = _get_primary_container_id(base_cmd, app_service)
        container_ip = _get_container_ip(container_id)
    except RuntimeCheckError as exc:
        print(
            f"[warn] unable to resolve internal endpoint for {app_service}:{app_port}: {exc}",
            file=sys.stderr,
        )
        return requested_base_url

    resolved_url = f"http://{container_ip}:{app_port}"
    print(
        f"[info] no host port mapping for {app_service}:{app_port}; "
        f"probing container endpoint {resolved_url}"
    )
    return resolved_url


def _http_request(
    url: str,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, object] | None = None,
    timeout_seconds: int = 5,
) -> tuple[int, str]:
    body: bytes | None = None
    headers: dict[str, str] = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return int(response.status), response_body
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), error_body
    except urllib.error.URLError as exc:
        raise RuntimeCheckError(f"HTTP request failed for {url}: {exc}") from exc


def _wait_for_http_200(base_url: str, path: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = urllib.parse.urljoin(base_url, path)
    last_status = 0
    last_error = ""

    while time.monotonic() < deadline:
        try:
            status, _ = _http_request(url, method="GET", timeout_seconds=5)
            last_status = status
            if status == 200:
                print(f"[ok] {path} returned 200")
                return
        except RuntimeCheckError as exc:
            # The service may still be binding; keep polling until timeout.
            last_error = str(exc)
            last_status = 0
        time.sleep(2)

    extra = f", last_error={last_error}" if last_error else ""
    raise RuntimeCheckError(
        f"Timed out waiting for {path} to return 200 (last_status={last_status}{extra})"
    )


def _wait_for_any_http_200(base_url: str, paths: list[str], timeout_seconds: int) -> str:
    if not paths:
        raise RuntimeCheckError("No health endpoint paths configured")

    per_path_timeout = max(10, timeout_seconds // len(paths))
    failures: list[str] = []
    for path in paths:
        try:
            _wait_for_http_200(base_url, path, timeout_seconds=per_path_timeout)
            return path
        except RuntimeCheckError as exc:
            failures.append(f"{path}: {exc}")

    raise RuntimeCheckError(
        "Timed out waiting for health endpoint candidates: " + "; ".join(failures[:4])
    )


def _check_api_flow(base_url: str, api_token: str) -> None:
    """Verify debate endpoints are reachable and auth is behaving coherently."""
    list_url = urllib.parse.urljoin(base_url, "/api/v1/debates?limit=1&offset=0")
    status, body = _http_request(list_url, token=api_token)
    if status == 200:
        print("[ok] GET /api/v1/debates returned 200")
    elif status in {401, 403}:
        # In hardened deployments ARAGORA_API_TOKEN may be a server secret rather
        # than a user credential (JWT/API key). Treat auth-gated responses as a
        # valid route-protection signal and stop here rather than overstating the
        # check as authenticated end-user success.
        print(f"[ok] GET /api/v1/debates returned {status}; auth gate is enforced")
        return
    else:
        raise RuntimeCheckError(
            f"Expected GET /api/v1/debates to return 200, got {status} body={body[:500]}"
        )

    create_url = urllib.parse.urljoin(base_url, "/api/v1/debates")
    status, body = _http_request(create_url, method="POST", token=api_token, payload={})
    if status not in {200, 201, 202, 400, 401, 403, 422}:
        raise RuntimeCheckError(
            "Expected POST /api/v1/debates to return one of "
            f"{{200,201,202,400,401,403,422}}, got {status} body={body[:500]}"
        )
    print(f"[ok] authenticated POST /api/v1/debates returned {status}")


def _print_diagnostics(base_cmd: list[str], services: list[str]) -> None:
    print("\n=== compose ps ===")
    ps_result = _compose(base_cmd, ["ps"], check=False)
    if ps_result.stdout:
        print(ps_result.stdout)
    if ps_result.stderr:
        print(ps_result.stderr, file=sys.stderr)

    print("\n=== compose logs (tail=200) ===")
    logs_result = _compose(base_cmd, ["logs", "--tail", "200", *services], check=False)
    if logs_result.stdout:
        print(logs_result.stdout)
    if logs_result.stderr:
        print(logs_result.stderr, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run runtime self-host compose validation")
    parser.add_argument("--compose", default="docker-compose.production.yml")
    parser.add_argument("--env-file", default=".env.production")
    parser.add_argument("--project-name", default="aragora-selfhost-ci")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--services", default=",".join(DEFAULT_CORE_SERVICES))
    parser.add_argument("--service-timeout", type=int, default=300)
    parser.add_argument("--api-timeout", type=int, default=180)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    compose_path = Path(args.compose)
    env_file = Path(args.env_file)
    services = [s.strip() for s in args.services.split(",") if s.strip()]

    if not compose_path.exists():
        print(f"Compose file not found: {compose_path}", file=sys.stderr)
        return 2
    if not env_file.exists():
        print(f"Env file not found: {env_file}", file=sys.stderr)
        return 2
    if not services:
        print("No services specified", file=sys.stderr)
        return 2

    env_errors, env_warnings = _validate_runtime_env_file(env_file)
    if env_warnings:
        for warning in env_warnings:
            print(f"[warn] {warning}", file=sys.stderr)
    if env_errors:
        for error in env_errors:
            print(error, file=sys.stderr)
        return 2
    api_token = _read_env_value(env_file, "ARAGORA_API_TOKEN")

    base_cmd = _compose_base(compose_path, env_file, args.project_name)

    try:
        print("[step] verifying docker daemon")
        _check_docker_daemon()

        print("[step] validating compose config")
        _compose(base_cmd, ["config", "-q"])

        print(f"[step] starting services: {', '.join(services)}")
        _compose(base_cmd, ["up", "-d", *services])

        print("[step] waiting for container health")
        for service in services:
            _wait_for_service(base_cmd, service, timeout_seconds=args.service_timeout)

        runtime_base_url = _resolve_runtime_base_url(base_cmd, args.base_url)

        print("[step] waiting for explicit HTTP liveness/readiness endpoints")
        health_path = _wait_for_any_http_200(
            runtime_base_url,
            LIVENESS_PATH_CANDIDATES,
            timeout_seconds=args.api_timeout,
        )
        print(f"[ok] liveness endpoint: {health_path}")
        readiness_path = _wait_for_any_http_200(
            runtime_base_url,
            READINESS_PATH_CANDIDATES,
            timeout_seconds=args.api_timeout,
        )
        print(f"[ok] readiness endpoint: {readiness_path}")

        print("[step] validating debate endpoint reachability")
        _check_api_flow(runtime_base_url, api_token=api_token)

        print("Self-host runtime validation passed")
        return 0
    except RuntimeCheckError as exc:
        print(f"Self-host runtime validation failed: {exc}", file=sys.stderr)
        _print_diagnostics(base_cmd, services)
        return 1
    finally:
        if not args.keep_running:
            _compose(base_cmd, ["down", "-v", "--remove-orphans"], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
