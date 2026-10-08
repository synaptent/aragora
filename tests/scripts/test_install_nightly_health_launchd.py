"""Focused coverage for the nightly health/throughput/digest LaunchAgent installer."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install_nightly_health_launchd.sh"

CASES = [
    (
        "pristine-main-health",
        "com.aragora.pristine-main-health",
        {"Hour": 3, "Minute": 30},
        "pristine_main_health.py",
        ["--pristine-dir", "--halt-file", "--suite required"],
    ),
    (
        "throughput-snapshot",
        "com.aragora.throughput-snapshot",
        {"Hour": 7, "Minute": 30},
        "throughput_ledger.py",
        ["snapshot", "--limit 40"],
    ),
    (
        "weekly-digest",
        "com.aragora.weekly-digest",
        {"Weekday": 5, "Hour": 7, "Minute": 45},
        "weekly_digest.py",
        ["--out", "weekly-digest-$(date +%F).md"],
    ),
]


def _render(tmp_path: Path, short_label: str) -> tuple[str, dict]:
    repo = tmp_path / "repo & state"
    home = tmp_path / "home & state"
    repo.mkdir()
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "REPO_ROOT": str(repo),
    }
    proc = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--dry-run", short_label],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, plistlib.loads(proc.stdout.encode("utf-8"))


@pytest.mark.parametrize("short_label,label,schedule,script_name,command_parts", CASES)
def test_dry_run_renders_valid_escaped_plist(
    tmp_path: Path,
    short_label: str,
    label: str,
    schedule: dict[str, int],
    script_name: str,
    command_parts: list[str],
) -> None:
    raw, data = _render(tmp_path, short_label)

    assert data["Label"] == label
    assert data["StartCalendarInterval"] == schedule
    assert data["ProgramArguments"][:2] == ["/bin/bash", "-lc"]
    command = data["ProgramArguments"][2]
    assert "resolve_aragora_python" in command
    if short_label == "pristine-main-health":
        assert (
            "resolve_aragora_python import\\ pytest pytest pristine-main\\ health\\ runtime"
            in command
        )
    else:
        assert "import\\ pytest" not in command
    assert 'exec "$PYTHON_BIN"' in command
    assert "quot;" not in command
    assert script_name in command
    assert all(part in command for part in command_parts)
    assert data["WorkingDirectory"].endswith("repo & state")
    assert data["StandardOutPath"].endswith(f"home & state/.aragora/{label}.log")
    assert data["StandardErrorPath"] == data["StandardOutPath"]

    # Both command chaining and ampersands in interpolated paths must survive
    # XML serialization and plist parsing without becoming invalid markup.
    assert "&amp;&amp;" in raw
    assert "&amp;" in raw
    assert " && " in command


def test_dry_run_rejects_unknown_label(tmp_path: Path) -> None:
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    }
    proc = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--dry-run", "unknown"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 64
    assert "unknown label" in proc.stderr


def test_pristine_command_rejects_runtime_without_pytest_before_suite(tmp_path: Path) -> None:
    _, data = _render(tmp_path, "pristine-main-health")
    repo = tmp_path / "repo & state"
    home = tmp_path / "home & state"
    scripts = repo / "scripts"
    scripts.mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "aragora_runtime.sh", scripts / "aragora_runtime.sh")

    suite_started = tmp_path / "suite-started"
    probe_log = tmp_path / "probe.log"
    bad_python = repo / ".venv" / "bin" / "python3"
    bad_python.parent.mkdir(parents=True)
    bad_python.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-c" ]]; then\n'
        '  printf \'%s\\n\' "${2:-}" >> "$PROBE_LOG"\n'
        "  exit 1\n"
        "fi\n"
        'touch "$SUITE_STARTED"\n',
        encoding="utf-8",
    )
    bad_python.chmod(0o755)

    proc = subprocess.run(
        ["/bin/bash", "-c", data["ProgramArguments"][2]],
        cwd=repo,
        env={
            "HOME": str(home),
            "PATH": str(bad_python.parent),
            "ARAGORA_REPO_ROOT": str(repo),
            "PROBE_LOG": str(probe_log),
            "SUITE_STARTED": str(suite_started),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert not suite_started.exists()
    assert set(probe_log.read_text(encoding="utf-8").splitlines()) == {"import pytest"}
    assert "without usable pytest imports" in proc.stderr


def test_install_writes_and_loads_all_valid_plists(tmp_path: Path) -> None:
    repo = tmp_path / "repo & state"
    home = tmp_path / "home & state"
    tools = tmp_path / "tools"
    repo.mkdir()
    home.mkdir()
    tools.mkdir()
    launchctl_log = tmp_path / "launchctl.log"

    plutil = tools / "plutil"
    plutil.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    plutil.chmod(0o755)
    launchctl = tools / "launchctl"
    launchctl.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$LAUNCHCTL_LOG"\n',
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "REPO_ROOT": str(repo),
        "PLUTIL_BIN": str(plutil),
        "LAUNCHCTL_BIN": str(launchctl),
        "LAUNCHCTL_LOG": str(launchctl_log),
    }
    proc = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--install"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    launch_agents = home / "Library" / "LaunchAgents"
    for _, label, schedule, _, _ in CASES:
        plist_path = launch_agents / f"{label}.plist"
        assert plist_path.exists()
        data = plistlib.loads(plist_path.read_bytes())
        assert data["Label"] == label
        assert data["StartCalendarInterval"] == schedule

    loaded = launchctl_log.read_text(encoding="utf-8").splitlines()
    assert len(loaded) == len(CASES)
    assert all(line.startswith("load ") for line in loaded)
