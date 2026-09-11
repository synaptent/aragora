"""Runtime contracts for the backend image and the Hetzner deployment."""

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_python_userbase_matches_copied_packages() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.backend").read_text()
    userbase = "ENV PYTHONUSERBASE=/home/aragora/.local"
    assert dockerfile.count(userbase) == 1
    assert (
        dockerfile.index("ENV PATH=/home/aragora/.local/bin:$PATH")
        < dockerfile.index(userbase)
        < dockerfile.index("USER aragora")
    )


def test_backend_installs_database_cache_and_monitoring_dependencies() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.backend").read_text()
    assert "--extras postgres,redis,monitoring" in dockerfile
    assert 'python -m pip install --user "psycopg2-binary>=2.9,<3.0"' in dockerfile


def test_compose_uses_secret_file_and_real_migration_cli() -> None:
    text = (ROOT / "deploy/hetzner/docker-compose.yml").read_text()
    services = yaml.safe_load(text)["services"]
    assert "${" not in text
    for name in ("postgres", "migrate", "app", "backup"):
        assert services[name]["env_file"] == ["./secrets.env"]
        assert "DATABASE_URL" not in services[name].get("environment", {})
    assert services["migrate"]["command"] == ["python", "-m", "aragora.migrations", "upgrade"]
    assert services["app"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    # get_storage_backend() and the debate-origin store only pick Postgres when told so
    # explicitly; DATABASE_URL alone leaves them on SQLite.
    for name in ("migrate", "app"):
        assert services[name]["environment"]["ARAGORA_DB_BACKEND"] == "postgres"


def test_app_service_sets_no_entrypoint_only_variables() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile.backend").read_text()
    assert "ENTRYPOINT" not in dockerfile
    services = yaml.safe_load((ROOT / "deploy/hetzner/docker-compose.yml").read_text())["services"]
    assert "SKIP_MIGRATIONS" not in services["app"]["environment"]


def test_backup_reports_success_only_after_pg_dump_succeeds() -> None:
    services = yaml.safe_load((ROOT / "deploy/hetzner/docker-compose.yml").read_text())["services"]
    # Compose turns the file's ``$$`` escapes into ``$`` before the shell sees them.
    script = services["backup"]["entrypoint"][-1].replace("$$", "$")
    assert "| gzip" not in script
    dump = re.search(r"if PGPASSWORD=.* pg_dump .*-Z \d+ -f \"\$F\.part\" aragora; then", script)
    assert dump is not None
    wrote = script.index('mv "$F.part" "$F" && echo "[backup] wrote')
    prune = script.index("find /backups -name '*.sql.gz' -mtime +14 -delete")
    assert dump.start() < wrote < prune < script.index("else")
    assert script.index('rm -f "$F.part"') < script.index("[backup] FAILED")
    # Dump first, sleep last: a container restart must not postpone the next dump by a day.
    assert script.index("sleep 86400") > script.index("fi")


def test_tunnel_routes_only_the_websocket_path_to_the_ws_port() -> None:
    ingress = yaml.safe_load((ROOT / "deploy/hetzner/cloudflared-config.yml").read_text())[
        "ingress"
    ]
    ws, http, fallback = ingress
    assert ws["service"] == "http://127.0.0.1:8765"
    pattern = re.compile(ws["path"])
    assert all(pattern.search(p) for p in ("/ws", "/ws/spectate", "/ws/voice/abc"))
    assert not any(pattern.search(p) for p in ("/api/v1/debates/ws", "/wsgi", "/readyz"))
    assert http == {"hostname": "api.aragora.ai", "service": "http://127.0.0.1:8080"}
    assert fallback == {"service": "http_status:404"}


def test_readme_restores_dump_into_a_fresh_database_before_migrating() -> None:
    readme = (ROOT / "deploy/hetzner/README.md").read_text()
    order = [
        "docker compose stop app",
        "DROP DATABASE aragora WITH (FORCE)",
        "psql -v ON_ERROR_STOP=1 -U aragora -d aragora",
        "docker compose run --rm migrate",
        "docker compose up -d app",
    ]
    positions = [readme.index(step) for step in order]
    assert positions == sorted(positions)
    assert readme.count("psql -v ON_ERROR_STOP=1") == 2


def test_secret_template_is_empty_and_required_keys_are_checked() -> None:
    template = (ROOT / "deploy/hetzner/secrets.env.template").read_text()
    values = dict(line.split("=", 1) for line in template.splitlines() if re.match(r"^\w+=", line))
    assert values == dict.fromkeys(
        (
            "ARAGORA_ENCRYPTION_KEY",
            "ARAGORA_JWT_SECRET",
            "POSTGRES_PASSWORD",
            "ARAGORA_API_TOKEN",
            "DATABASE_URL",
        ),
        "",
    )
    assert "openssl rand -hex 32" in template
    assert not re.search(r"=.{20,}", template)
    bring_up = (ROOT / "deploy/hetzner/bring-up.sh").read_text()
    required = re.search(r"for k in ([^;]+); do", bring_up)
    assert required is not None
    assert set(values) <= set(required[1].split())
    assert "secrets.env" in (ROOT / "deploy/hetzner/.gitignore").read_text().splitlines()


def test_ci_probes_backend_dependencies_and_both_migration_systems() -> None:
    docker = yaml.safe_load((ROOT / ".github/workflows/docker.yml").read_text())
    runs = "\n".join(step.get("run", "") for step in docker["jobs"]["build-backend"]["steps"])
    assert runs.index("docker build -f deploy/Dockerfile.backend") < runs.index(
        'docker run --rm test-backend:latest python -c "import pydantic, psycopg2, aragora.config'
    )
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    migration = workflow["jobs"]["migration-test"]
    assert migration["services"]["postgres"]["image"] == "postgres:15"
    runs = "\n".join(step.get("run", "") for step in migration["steps"])
    assert "alembic upgrade head" in runs
    assert 'python -m aragora.migrations upgrade --database-url "$DATABASE_URL"' in runs
    assert "python -m aragora.migrations status" in runs
