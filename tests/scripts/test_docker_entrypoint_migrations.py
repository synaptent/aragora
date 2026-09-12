from pathlib import Path
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("skip,failure", [("0", "0"), ("1", "0"), ("0", "1")])
def test_entrypoint_migration_control_flow(tmp_path, skip, failure) -> None:
    entrypoint = Path(__file__).resolve().parents[2] / "deploy/scripts/docker-entrypoint.sh"
    python = tmp_path / "python"
    python.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "-m" ]; then\n'
        '  echo "$*|$DATABASE_URL|$ARAGORA_POSTGRES_DSN" >> "$CALLS"\n'
        '  exit "$FAILURE"\n'
        "fi\n"
    )
    python.chmod(0o700)
    calls = tmp_path / "calls"
    preferred = "postgresql://test:fixture@127.0.0.1:15432/preferred"
    result = subprocess.run(
        ["bash", str(entrypoint), "true"],
        env={
            "PATH": f"{tmp_path}{os.pathsep}/usr/bin:/bin",
            "DATABASE_URL": "postgresql://test:fixture@127.0.0.1:15432/other",
            "ARAGORA_POSTGRES_DSN": preferred,
            "SKIP_MIGRATIONS": skip,
            "CALLS": str(calls),
            "FAILURE": failure,
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    if skip == "1":
        assert not calls.exists()
        assert "SKIP_MIGRATIONS=1, skipping migrations." in result.stdout
    else:
        assert calls.read_text() == f"-m aragora.migrations upgrade|{preferred}|{preferred}\n"
    assert result.stdout.count("Migrations complete") == int(skip == "0" and failure == "0")
    assert result.stdout.count("Migration failed") == int(skip == "0" and failure == "1")


def test_docker_entrypoint_invokes_the_migration_cli() -> None:
    entrypoint = (
        Path(__file__).resolve().parents[2] / "deploy/scripts/docker-entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert 'DATABASE_URL="${ARAGORA_POSTGRES_DSN:-${DATABASE_URL}}"' in entrypoint
    assert 'ARAGORA_POSTGRES_DSN="$DATABASE_URL"' in entrypoint
    assert "export DATABASE_URL ARAGORA_POSTGRES_DSN" in entrypoint
    assert "python -m aragora.migrations upgrade" in entrypoint
    assert 'upgrade --database-url "${' not in entrypoint
    assert "python -m aragora.migrations.runner upgrade" not in entrypoint


def test_migration_module_exposes_upgrade_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "aragora.migrations", "upgrade", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--database-url" in result.stdout
