from pathlib import Path
import subprocess
import sys


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
