from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_publisher_wrapper_passes_shared_outbox_to_branch_publisher() -> None:
    script = (REPO_ROOT / "scripts" / "run_codex_automation_publisher.sh").read_text(
        encoding="utf-8"
    )

    assert "repo_root_available()" in script
    assert '--repo "${REPO_ROOT}"' in script
    assert '--outbox-dir "${HANDOFF_OUTBOX_DIR}"' in script


def test_publisher_wrapper_sets_unattended_guardrail_defaults() -> None:
    script = (REPO_ROOT / "scripts" / "run_codex_automation_publisher.sh").read_text(
        encoding="utf-8"
    )

    assert 'ARAGORA_AUTOMATION_MIN_FREE_GIB="${ARAGORA_AUTOMATION_MIN_FREE_GIB:-50}"' in script
    assert (
        'ARAGORA_AUTOMATION_CODEX_RSS_MAX_GIB="${ARAGORA_AUTOMATION_CODEX_RSS_MAX_GIB:-25}"'
        in script
    )
    assert (
        'ARAGORA_AUTOMATION_SPEND_DAILY_CAP_USD="${ARAGORA_AUTOMATION_SPEND_DAILY_CAP_USD:-200}"'
        in script
    )
    assert (
        'ARAGORA_AUTOMATION_SPEND_WEEKLY_CAP_USD="${ARAGORA_AUTOMATION_SPEND_WEEKLY_CAP_USD:-500}"'
        in script
    )


def test_publisher_wrapper_accepts_direct_dot_aragora_state_root() -> None:
    script = (REPO_ROOT / "scripts" / "run_codex_automation_publisher.sh").read_text(
        encoding="utf-8"
    )

    assert 'AUTOMATION_STATE_ROOT##*/}" == ".aragora"' in script
    assert 'AUTOMATION_STATE_ROOT="$(cd "${AUTOMATION_STATE_ROOT}/.." && pwd)"' in script


def test_publisher_wrapper_handles_missing_gh_as_unavailable() -> None:
    script = (REPO_ROOT / "scripts" / "run_codex_automation_publisher.sh").read_text(
        encoding="utf-8"
    )

    assert "command -v gh" not in script
    assert "gh CLI not found" not in script
    assert "GitHub unavailable; leaving automations in handoff-only mode" in script


def test_launchd_installer_prefers_canonical_git_worktree_root() -> None:
    script = (REPO_ROOT / "scripts" / "install_codex_automation_publisher_launchd.sh").read_text(
        encoding="utf-8"
    )

    assert "ARAGORA_AUTOMATION_PUBLISHER_REPO_ROOT" in script
    assert 'git -C "${SCRIPT_REPO_ROOT}" worktree list --porcelain' in script
    assert 'REPO_ROOT="${CANONICAL_REPO_ROOT}"' in script
    assert 'LOG_PATH="${REPO_ROOT}/.aragora/overnight/codex-automation-publisher.log"' in script


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_publisher_wrapper_cache_only_skips_all_publish_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "run_codex_automation_publisher.sh", scripts)
    (repo / ".git").mkdir()
    (repo / ".aragora" / "automation-outbox").mkdir(parents=True)
    (repo / ".aragora" / "automation-receipts").mkdir(parents=True)

    (scripts / "github_cli_health.py").write_text(
        'print("{\\"ready\\": true}")\n', encoding="utf-8"
    )
    (scripts / "cache_codex_automation_github_status.py").write_text(
        "import os, pathlib\npathlib.Path(os.environ['CACHE_CALL_LOG']).write_text('cache\\n')\n",
        encoding="utf-8",
    )
    for name in (
        "drain_codex_automation_value.py",
        "publish_codex_automation_branches.py",
        "publish_automation_handoffs.py",
    ):
        (scripts / name).write_text(
            "raise SystemExit('forbidden publish path invoked')\n", encoding="utf-8"
        )

    cache_log = tmp_path / "cache.log"
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_AUTOMATION_CACHE_ONLY": "1",
            "ARAGORA_AUTOMATION_STATE_ROOT": str(repo),
            "CACHE_CALL_LOG": str(cache_log),
            "TMPDIR": str(tmp_path),
        }
    )
    proc = subprocess.run(
        ["/bin/bash", str(scripts / "run_codex_automation_publisher.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert cache_log.read_text(encoding="utf-8") == "cache\n"
    assert (
        "cache-only mode: skipping value drain, branch publish, and handoff publish" in proc.stdout
    )
    assert "starting branch publish pass" not in proc.stdout
    assert "starting handoff publish pass" not in proc.stdout


def test_launchd_installer_cache_only_dry_run_never_calls_launchctl(tmp_path: Path) -> None:
    installer = REPO_ROOT / "scripts" / "install_codex_automation_publisher_launchd.sh"
    plist_path = tmp_path / "publisher.plist"
    launchctl_marker = tmp_path / "launchctl-called"
    bindir = tmp_path / "bin"
    _write_executable(
        bindir / "launchctl",
        f"#!/bin/bash\ntouch {launchctl_marker}\nexit 99\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_AUTOMATION_PUBLISHER_REPO_ROOT": str(REPO_ROOT),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bindir}:{env['PATH']}",
        }
    )
    proc = subprocess.run(
        [
            "/bin/bash",
            str(installer),
            "--cache-only",
            "--dry-run",
            "--plist-path",
            str(plist_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert plist_path.exists()
    payload = plistlib.loads(plist_path.read_bytes())
    assert "ARAGORA_AUTOMATION_CACHE_ONLY=1" in payload["ProgramArguments"][-1]
    assert not launchctl_marker.exists()
