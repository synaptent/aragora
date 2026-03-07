"""Tests for scripts/check_self_host_compose.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_self_host_compose.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=dict(os.environ),
    )


def _write_valid_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    compose = tmp_path / "docker-compose.production.yml"
    compose.write_text(
        """
services:
  aragora:
    depends_on:
      postgres: {}
      sentinel-1: {}
      sentinel-2: {}
      sentinel-3: {}
    environment:
      - DATABASE_URL=postgresql://aragora:secret@postgres:5432/aragora
      - ARAGORA_DB_BACKEND=postgres
      - ARAGORA_SECRETS_STRICT=true
      - ARAGORA_REDIS_MODE=sentinel
      - ARAGORA_REDIS_SENTINEL_HOSTS=sentinel-1:26379,sentinel-2:26379,sentinel-3:26379
      - ARAGORA_REDIS_SENTINEL_MASTER=mymaster
      - ARAGORA_JWT_SECRET=jwt
      - ARAGORA_ENCRYPTION_KEY=0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      - ARAGORA_RATE_LIMIT_BACKEND=redis
    healthcheck:
      test: ["CMD", "true"]
  postgres:
    healthcheck:
      test: ["CMD", "true"]
  redis-master:
    healthcheck:
      test: ["CMD", "true"]
  redis-replica-1:
    healthcheck:
      test: ["CMD", "true"]
  redis-replica-2:
    healthcheck:
      test: ["CMD", "true"]
  sentinel-1:
    healthcheck:
      test: ["CMD", "true"]
  sentinel-2:
    healthcheck:
      test: ["CMD", "true"]
  sentinel-3:
    healthcheck:
      test: ["CMD", "true"]
""".strip()
    )

    env = tmp_path / ".env.production.example"
    env.write_text(
        "\n".join(
            [
                "DOMAIN=example.com",
                "POSTGRES_PASSWORD=secret",
                "ARAGORA_API_TOKEN=token",
                "ARAGORA_JWT_SECRET=jwt",
                "ARAGORA_ENCRYPTION_KEY=0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ARAGORA_RATE_LIMIT_BACKEND=redis",
                "ARAGORA_REDIS_MODE=sentinel",
                "ARAGORA_REDIS_SENTINEL_HOSTS=sentinel-1:26379,sentinel-2:26379,sentinel-3:26379",
                "ARAGORA_REDIS_SENTINEL_MASTER=mymaster",
                "ARAGORA_STRICT_DEPLOYMENT=true",
            ]
        )
    )

    runbook = tmp_path / "SELF_HOSTING.md"
    runbook.write_text(
        "\n".join(
            [
                "# Self Hosting",
                "## Production Compose Semantics",
                "## Startup and Readiness Verification",
                "## Production Ingress Verification",
                "## Health Checks",
                "## Failure Recovery Playbook",
            ]
        )
    )

    return compose, env, runbook


def _write_valid_standalone_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    compose = tmp_path / "docker-compose.production.yml"
    compose.write_text(
        """
services:
  aragora:
    depends_on:
      postgres: {}
      redis: {}
    environment:
      - DATABASE_URL=postgresql://aragora:secret@postgres:5432/aragora
      - ARAGORA_DB_BACKEND=postgres
      - ARAGORA_SECRETS_STRICT=false
      - ARAGORA_REDIS_MODE=standalone
      - REDIS_URL=redis://:secret@redis:6379/0
      - ARAGORA_REDIS_URL=redis://:secret@redis:6379/0
      - ARAGORA_JWT_SECRET=jwt
      - ARAGORA_ENCRYPTION_KEY=0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      - ARAGORA_RATE_LIMIT_BACKEND=redis
    healthcheck:
      test: ["CMD", "true"]
  postgres:
    healthcheck:
      test: ["CMD", "true"]
  redis:
    healthcheck:
      test: ["CMD", "true"]
""".strip()
    )

    env = tmp_path / ".env.production.example"
    env.write_text(
        "\n".join(
            [
                "ARAGORA_DOMAIN=example.com",
                "POSTGRES_PASSWORD=secret",
                "ARAGORA_API_TOKEN=token",
                "ARAGORA_JWT_SECRET=jwt",
                "ARAGORA_ENCRYPTION_KEY=0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ARAGORA_RATE_LIMIT_BACKEND=redis",
                "ARAGORA_REDIS_MODE=standalone",
                "ARAGORA_STRICT_DEPLOYMENT=true",
            ]
        )
    )

    runbook = tmp_path / "SELF_HOSTING.md"
    runbook.write_text(
        "\n".join(
            [
                "# Self Hosting",
                "## Production Compose Semantics",
                "## Verify Installation",
                "## Troubleshooting",
            ]
        )
    )

    return compose, env, runbook


def test_repo_compose_validation_passes():
    result = _run()
    assert result.returncode == 0
    assert "validation passed" in result.stdout.lower()


def test_fails_with_missing_services(tmp_path: Path):
    compose = tmp_path / "docker-compose.production.yml"
    compose.write_text(
        """
services:
  aragora:
    depends_on:
      postgres: {}
    environment:
      - ARAGORA_REDIS_MODE=sentinel
      - ARAGORA_REDIS_SENTINEL_HOSTS=sentinel-1:26379,sentinel-2:26379,sentinel-3:26379
""".strip()
    )

    env = tmp_path / ".env.production.example"
    env.write_text(
        "\n".join(
            [
                "DOMAIN=example.com",
                "POSTGRES_PASSWORD=secret",
                "ARAGORA_API_TOKEN=token",
                "ARAGORA_JWT_SECRET=jwt",
            ]
        )
    )

    result = _run("--compose", str(compose), "--env-example", str(env))
    assert result.returncode == 1
    assert "missing required services" in result.stdout.lower()


def test_fails_when_runbook_markers_missing(tmp_path: Path):
    compose, env, runbook = _write_valid_fixture(tmp_path)
    runbook.write_text("# Self Hosting\n## Production Compose Semantics\n## Health Checks\n")

    result = _run("--compose", str(compose), "--env-example", str(env), "--runbook", str(runbook))
    assert result.returncode == 1
    assert "runbook missing required sections" in result.stdout.lower()


def test_fails_when_aragora_missing_rate_limit_backend(tmp_path: Path):
    compose, env, runbook = _write_valid_fixture(tmp_path)
    compose.write_text(
        compose.read_text().replace("      - ARAGORA_RATE_LIMIT_BACKEND=redis\n", ""),
        encoding="utf-8",
    )

    result = _run("--compose", str(compose), "--env-example", str(env), "--runbook", str(runbook))
    assert result.returncode == 1
    assert "aragora service missing required env wiring" in result.stdout.lower()
    assert "aragora_rate_limit_backend" in result.stdout.lower()


def test_fails_when_aragora_missing_secrets_strict_wiring(tmp_path: Path):
    compose, env, runbook = _write_valid_fixture(tmp_path)
    compose.write_text(
        compose.read_text().replace("      - ARAGORA_SECRETS_STRICT=true\n", ""),
        encoding="utf-8",
    )

    result = _run("--compose", str(compose), "--env-example", str(env), "--runbook", str(runbook))
    assert result.returncode == 1
    assert "aragora service missing required env wiring" in result.stdout.lower()
    assert "aragora_secrets_strict" in result.stdout.lower()


def test_standalone_redis_topology_passes(tmp_path: Path):
    compose, env, runbook = _write_valid_standalone_fixture(tmp_path)

    result = _run("--compose", str(compose), "--env-example", str(env), "--runbook", str(runbook))
    assert result.returncode == 0
    assert "redis_topology=standalone" in result.stdout
