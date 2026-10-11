"""Cold-process pins for ``python -m aragora.server`` under mounted secret custody.

Each probe runs the real entry point in a fresh interpreter, with synthetic
values in a protected ``ARAGORA_SECRETS_DIR`` and an environment built from
scratch (no inherited provider keys, AWS neutralized). Pinned behavior:

1. ``main()``'s first import hydrates mounted provider keys and ``DATABASE_URL``
   into the environment, so the runtime defaults it chooses next (demo mode, the
   SQLite backend) see them.
2. ``check_production_requirements`` sees a mounted ``DATABASE_URL`` when
   ``ARAGORA_REQUIRE_DATABASE=true``.
3. Strict secrets mode with no managed custody refuses at startup; it does not
   serve in degraded mode.
4. A rejected mounted ``ARAGORA_API_TOKEN`` stops the multi-worker parent with one
   line before any worker starts.

Probes 1, 2 and 4 replace ``asyncio`` and ``multiprocessing`` inside the entry
module with recorders, so nothing serves and no worker process starts. Probe 3
runs the launcher unmodified with an un-creatable ``--nomic-dir``: a boot that
got past startup validation, degraded or not, stops there before binding a port,
and a non-strict control boot shows that the stop is reachable. Every probe
still points each listening port at a free one.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_SYNTHETIC_VALUES = {
    "OPENAI_API_KEY": "sk-synthetic-entrypoint-probe-0000000000",
    "DATABASE_URL": "postgresql://probe:probe@127.0.0.1:1/probe",
    "ARAGORA_API_TOKEN": "synthetic-entrypoint-probe-token-000000",
}

_REPORT_PREFIX = "PROBE_REPORT "

_ENTRY_PROBE = """
import json
import os
import sys
from types import SimpleNamespace

WATCHED = ("OPENAI_API_KEY", "DATABASE_URL", "ARAGORA_API_TOKEN")
report = {
    "before_import": {name: name in os.environ for name in WATCHED},
    "handoff": None,
    "workers_started": 0,
}

import aragora.server.__main__ as entry


def record_handoff(coro):
    coro.close()
    from aragora.server.startup.validation import check_production_requirements

    report["handoff"] = {
        "environ": {name: name in os.environ for name in WATCHED},
        "ARAGORA_DEMO_MODE": os.environ.get("ARAGORA_DEMO_MODE"),
        "ARAGORA_DB_BACKEND": os.environ.get("ARAGORA_DB_BACKEND"),
        "missing_requirements": check_production_requirements(),
    }


class WorkerStub:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        report["workers_started"] += 1

    def join(self):
        pass

    def is_alive(self):
        return False


entry.asyncio = SimpleNamespace(run=record_handoff)
entry.multiprocessing = SimpleNamespace(Process=WorkerStub)
sys.argv = ["aragora.server", *sys.argv[1:]]
try:
    exit_code = entry._run_main()
finally:
    print("PROBE_REPORT " + json.dumps(report), flush=True)
sys.exit(exit_code)
"""


def _secrets_dir(tmp_path: Path, files: dict[str, int]) -> Path:
    """A protected mounted directory holding the named synthetic files at the given modes."""
    directory = tmp_path / "secrets"
    directory.mkdir()
    directory.chmod(0o700)
    for name, mode in files.items():
        path = directory / name
        path.write_text(_SYNTHETIC_VALUES[name])
        path.chmod(mode)
    return directory


def _free_ports(count: int) -> list[int]:
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def _probe_env(tmp_path: Path, **settings: str) -> dict[str, str]:
    control_plane_port, nomic_loop_port, canvas_port = _free_ports(3)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(entry for entry in sys.path if entry),
        "ARAGORA_DATA_DIR": str(tmp_path / "data"),
        "ARAGORA_CONTROL_PLANE_WS_PORT": str(control_plane_port),
        "ARAGORA_NOMIC_LOOP_WS_PORT": str(nomic_loop_port),
        "ARAGORA_CANVAS_WS_PORT": str(canvas_port),
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    env.update(settings)
    return env


def _run(args: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _run_entry_probe(
    tmp_path: Path, env: dict[str, str], *argv: str
) -> tuple[subprocess.CompletedProcess[str], dict]:
    proc = _run(["-c", _ENTRY_PROBE, *argv], env, tmp_path)
    reports = [
        line[len(_REPORT_PREFIX) :]
        for line in proc.stdout.splitlines()
        if line.startswith(_REPORT_PREFIX)
    ]
    assert len(reports) == 1, _describe(proc)
    return proc, json.loads(reports[0])


def _describe(proc: subprocess.CompletedProcess[str]) -> str:
    return f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"


def _custody_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if "secret custody is unusable" in line]


def _database_requirement(missing: list[str]) -> list[str]:
    return [entry for entry in missing if entry.startswith("DATABASE_URL required")]


def test_mounted_provider_key_and_database_url_reach_runtime_defaults(tmp_path):
    secrets_dir = _secrets_dir(tmp_path, {"OPENAI_API_KEY": 0o600, "DATABASE_URL": 0o600})
    env = _probe_env(tmp_path, ARAGORA_ENV="development", ARAGORA_SECRETS_DIR=str(secrets_dir))

    proc, report = _run_entry_probe(tmp_path, env)

    assert proc.returncode == 0, _describe(proc)
    assert report["before_import"]["OPENAI_API_KEY"] is False
    assert report["before_import"]["DATABASE_URL"] is False
    handoff = report["handoff"]
    assert handoff is not None, _describe(proc)
    assert handoff["environ"]["OPENAI_API_KEY"] is True
    assert handoff["environ"]["DATABASE_URL"] is True
    assert handoff["ARAGORA_DEMO_MODE"] is None
    assert handoff["ARAGORA_DB_BACKEND"] is None


def test_runtime_defaults_fall_back_to_demo_without_mounted_keys(tmp_path):
    secrets_dir = _secrets_dir(tmp_path, {})
    env = _probe_env(tmp_path, ARAGORA_ENV="development", ARAGORA_SECRETS_DIR=str(secrets_dir))

    proc, report = _run_entry_probe(tmp_path, env)

    assert proc.returncode == 0, _describe(proc)
    handoff = report["handoff"]
    assert handoff is not None, _describe(proc)
    assert handoff["ARAGORA_DEMO_MODE"] == "true"
    assert handoff["ARAGORA_DB_BACKEND"] == "sqlite"


@pytest.mark.parametrize(
    ("mount_database_url", "expect_database_requirement"),
    [(True, False), (False, True)],
    ids=["mounted", "absent"],
)
def test_production_requirements_see_mounted_database_url(
    tmp_path, mount_database_url, expect_database_requirement
):
    files = {"ARAGORA_API_TOKEN": 0o600}
    if mount_database_url:
        files["DATABASE_URL"] = 0o600
    secrets_dir = _secrets_dir(tmp_path, files)
    env = _probe_env(
        tmp_path,
        ARAGORA_ENV="production",
        ARAGORA_REQUIRE_DATABASE="true",
        ARAGORA_SECRETS_DIR=str(secrets_dir),
    )

    proc, report = _run_entry_probe(tmp_path, env)

    assert proc.returncode == 0, _describe(proc)
    handoff = report["handoff"]
    assert handoff is not None, _describe(proc)
    assert handoff["environ"]["DATABASE_URL"] is mount_database_url
    assert bool(_database_requirement(handoff["missing_requirements"])) is (
        expect_database_requirement
    )


def _run_launcher_to_canary(tmp_path: Path, **settings: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m aragora.server`` whose ``--nomic-dir`` cannot be created."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    env = _probe_env(tmp_path, **settings)
    http_port, ws_port = _free_ports(2)
    return _run(
        [
            "-m",
            "aragora.server",
            "--http-port",
            str(http_port),
            "--port",
            str(ws_port),
            "--nomic-dir",
            str(blocker / "nomic"),
        ],
        env,
        tmp_path,
    )


_CANARY = "Cannot create nomic directory"


@pytest.mark.parametrize(
    "settings",
    [
        {"ARAGORA_ENV": "production"},
        {"ARAGORA_ENV": "development", "ARAGORA_SECRETS_STRICT": "true"},
    ],
    ids=["production", "explicit-strict"],
)
def test_strict_mode_without_custody_refuses_at_startup(tmp_path, settings):
    proc = _run_launcher_to_canary(tmp_path, **settings)

    output = proc.stdout + proc.stderr
    assert proc.returncode == 1, _describe(proc)
    assert _CANARY not in output, _describe(proc)
    assert "no managed custody backend is configured" in output, _describe(proc)
    assert "Configure ARAGORA_API_TOKEN in allowed managed custody" in output, _describe(proc)


def test_non_strict_boot_without_custody_reaches_the_canary(tmp_path):
    proc = _run_launcher_to_canary(tmp_path, ARAGORA_ENV="development")

    output = proc.stdout + proc.stderr
    assert proc.returncode == 1, _describe(proc)
    assert _CANARY in output, _describe(proc)
    assert "Configure ARAGORA_API_TOKEN in allowed managed custody" not in output


def test_rejected_api_token_stops_multi_worker_parent_before_workers(tmp_path):
    secrets_dir = _secrets_dir(tmp_path, {"ARAGORA_API_TOKEN": 0o644})
    env = _probe_env(tmp_path, ARAGORA_ENV="development", ARAGORA_SECRETS_DIR=str(secrets_dir))

    proc, report = _run_entry_probe(tmp_path, env, "--workers", "2")

    assert proc.returncode == 1, _describe(proc)
    assert _custody_lines(proc.stderr) == [
        "aragora: secret custody is unusable: Mounted secret 'ARAGORA_API_TOKEN' must use "
        "owner-readable, owner-only permissions"
    ]
    assert "Traceback" not in proc.stderr
    assert report["workers_started"] == 0


def test_usable_api_token_lets_multi_worker_parent_start_workers(tmp_path):
    secrets_dir = _secrets_dir(tmp_path, {"ARAGORA_API_TOKEN": 0o600})
    env = _probe_env(tmp_path, ARAGORA_ENV="development", ARAGORA_SECRETS_DIR=str(secrets_dir))

    proc, report = _run_entry_probe(tmp_path, env, "--workers", "2")

    assert proc.returncode == 0, _describe(proc)
    assert _custody_lines(proc.stderr) == []
    assert report["workers_started"] == 2
