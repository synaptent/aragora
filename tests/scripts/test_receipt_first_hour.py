"""Tests for ``scripts/receipt_first_hour.sh``.

The script is exercised against a fake toolchain: a stand-in ``python3`` whose
``-m venv`` populates the target directory with fake ``pip``, ``aragora`` and
``aragora-verify`` executables. That keeps the transcript, exit-code, pin and
environment assertions hermetic (no PyPI, no real install) while still running
the real script logic end to end.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "receipt_first_hour.sh"

# The fake shadows python3 on PATH, so the fallthrough must name the real
# interpreter by absolute path or it would re-exec itself.
FAKE_PYTHON = f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "venv" ]; then
  mkdir -p "${{@: -1}}/bin"
  for tool in pip aragora aragora-verify; do
    cp "$FAKE_BIN/$tool" "${{@: -1}}/bin/$tool"
  done
  exit 0
fi
exec {sys.executable} "$@"
"""

FAKE_PIP = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_LOG/pip.log"
printf 'INDEX=%s EXTRA_INDEX=%s FIND_LINKS=%s CONSTRAINT=%s CONFIG_FILE=%s\\n' \\
  "${PIP_INDEX_URL-<unset>}" \\
  "${PIP_EXTRA_INDEX_URL-<unset>}" \\
  "${PIP_FIND_LINKS-<unset>}" \\
  "${PIP_CONSTRAINT-<unset>}" \\
  "${PIP_CONFIG_FILE-<unset>}" >> "$FAKE_LOG/pip-env.log"
for arg in "$@"; do
  case "$arg" in
    *==99.9.9)
      printf 'ERROR: No matching distribution found for %s\\n' "$arg" >&2
      exit 1
      ;;
  esac
done
exit 0
"""

FAKE_ARAGORA = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_LOG/aragora.log"
printf 'KEY_FILE=%s SECRET=%s PYTHONPATH=%s SECRETS_MANAGER=%s ENV=%s\\n' \\
  "${ARAGORA_ODR_SIGNING_KEY_FILE-<unset>}" \\
  "${ARAGORA_ODR_SIGNING_KEY_SECRET-<unset>}" \\
  "${PYTHONPATH-<unset>}" \\
  "${ARAGORA_USE_SECRETS_MANAGER-<unset>}" \\
  "${ARAGORA_ENV-<unset>}" >> "$FAKE_LOG/env.log"
out=""
prev=""
for arg in "$@"; do
  case "$prev" in
    --receipt|--output) out="$arg" ;;
  esac
  prev="$arg"
done
if [ -n "$out" ]; then
  printf '{"odr_version": "0.1", "signatures": []}\\n' > "$out"
fi
exit "${FAKE_ARAGORA_EXIT:-0}"
"""

FAKE_VERIFY = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_LOG/verify.log"
printf 'Open Decision Receipt\\n'
exit "${FAKE_VERIFY_EXIT:-0}"
"""

# `gh` answers only the two subcommands the self-resolve path uses. ``release
# list`` stands in for gh's own `--json ... --jq ...` filtering and prints the
# already-resolved tag (``FAKE_GH_TAG``, empty when no receipts-* release
# exists); ``release download`` drops ``FAKE_GH_ASSETS`` into the ``-D`` target.
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_LOG/gh.log"
if [ "${1:-}" = "release" ] && [ "${2:-}" = "list" ]; then
  [ -z "${FAKE_GH_TAG:-}" ] || printf '%s\\n' "$FAKE_GH_TAG"
  exit "${FAKE_GH_LIST_EXIT:-0}"
fi
if [ "${1:-}" = "release" ] && [ "${2:-}" = "download" ]; then
  dest=""
  prev=""
  for arg in "$@"; do
    case "$prev" in
      -D) dest="$arg" ;;
    esac
    prev="$arg"
  done
  [ -n "$dest" ] || exit 1
  for name in ${FAKE_GH_ASSETS-pr1-clean.odr.json aragora-odr-signing.pub.pem}; do
    printf 'x\\n' > "$dest/$name"
  done
  exit "${FAKE_GH_DOWNLOAD_EXIT:-0}"
fi
exit 1
"""


@pytest.fixture
def fake_toolchain(tmp_path: Path) -> dict[str, Path]:
    """Build the fake ``python3``/``pip``/``aragora``/``aragora-verify`` set."""
    bindir = tmp_path / "fakebin"
    pathdir = tmp_path / "pathbin"
    logdir = tmp_path / "logs"
    tmpdir = tmp_path / "scratch"
    for d in (bindir, pathdir, logdir, tmpdir):
        d.mkdir()
    for name, body in (
        ("pip", FAKE_PIP),
        ("aragora", FAKE_ARAGORA),
        ("aragora-verify", FAKE_VERIFY),
    ):
        target = bindir / name
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)
    python = pathdir / "python3"
    python.write_text(FAKE_PYTHON, encoding="utf-8")
    python.chmod(0o755)
    gh = pathdir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    return {"bin": bindir, "path": pathdir, "log": logdir, "tmp": tmpdir}


def _run(
    toolchain: dict[str, Path],
    args: list[str] | None = None,
    env_extra: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("ARAGORA_ODR_SIGNING_KEY_FILE", None)
    env.pop("ARAGORA_ODR_SIGNING_KEY_SECRET", None)
    env["PATH"] = f"{toolchain['path']}{os.pathsep}{env['PATH']}"
    env["FAKE_BIN"] = str(toolchain["bin"])
    env["FAKE_LOG"] = str(toolchain["log"])
    # the script leaves its scratch root behind on purpose, so keep it under tmp_path
    env["TMPDIR"] = str(toolchain["tmp"])
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(SCRIPT), *(args or [])],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
    )


def _log(toolchain: dict[str, Path], name: str) -> str:
    path = toolchain["log"] / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_transcript_grammar_and_clean_exit(fake_toolchain: dict[str, Path]) -> None:
    """The four step lines, venv/odr paths and wall time match architecture 2.7."""
    proc = _run(fake_toolchain)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    lines = proc.stdout.splitlines()
    steps = [ln for ln in lines if re.match(r"^step: (install|demo|export|verify)$", ln)]
    assert steps == ["step: install", "step: demo", "step: export", "step: verify"]

    venv = [ln for ln in lines if re.match(r"^venv: /.+$", ln)]
    odr = [ln for ln in lines if re.match(r"^odr: /.+\.odr\.json$", ln)]
    assert len(venv) == 1, lines
    assert len(odr) == 1, lines

    tail = re.match(r"^total wall time: ([0-9]+)s$", lines[-1])
    assert tail is not None, lines
    assert int(tail.group(1)) <= 300

    # the venv and the exported document survive the run (the tamper proof reuses them)
    venv_path = Path(venv[0].split(" ", 1)[1])
    odr_path = Path(odr[0].split(" ", 1)[1])
    assert venv_path.is_dir()
    assert odr_path.is_file()


def test_help_exits_zero_and_lists_published_receipt_flags(
    fake_toolchain: dict[str, Path],
) -> None:
    """``--help``/``-h`` exit 0 and document the published-receipt path."""
    for flag in ("--help", "-h"):
        proc = _run(fake_toolchain, [flag])
        assert proc.returncode == 0, (flag, proc.stderr)
        assert "--published-receipt" in proc.stdout
        assert "--pubkey-url" in proc.stdout


def test_verifier_exit_three_is_a_failure_with_the_code_printed(
    fake_toolchain: dict[str, Path],
) -> None:
    """Only verifier exit 0 is success here; exit 3 fails loudly with ``exit=3``."""
    proc = _run(fake_toolchain, env_extra={"FAKE_VERIFY_EXIT": "3"})

    assert proc.returncode == 3, (proc.stdout, proc.stderr)
    assert "exit=3" in proc.stdout + proc.stderr
    assert re.search(r"^total wall time: [0-9]+s$", proc.stdout, re.MULTILINE)


def test_failing_demo_step_stops_before_export(fake_toolchain: dict[str, Path]) -> None:
    """A failing CLI step aborts the run and reports its exit code."""
    proc = _run(fake_toolchain, env_extra={"FAKE_ARAGORA_EXIT": "2"})

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "exit=2" in proc.stdout + proc.stderr
    assert "step: export" not in proc.stdout
    assert "step: verify" not in proc.stdout


def test_default_pins_and_explicit_pins_reach_pip(fake_toolchain: dict[str, Path]) -> None:
    """Positional ``<pkg>==<ver>`` arguments replace the unpinned defaults."""
    assert _run(fake_toolchain).returncode == 0
    assert _log(fake_toolchain, "pip.log").splitlines()[-1].split() == [
        "install",
        "--quiet",
        "aragora",
        "aragora-verify",
    ]

    proc = _run(fake_toolchain, ["aragora==2.9.0", "aragora-verify==0.1.1"])
    assert proc.returncode == 0, proc.stderr
    last = _log(fake_toolchain, "pip.log").splitlines()[-1]
    assert "aragora==2.9.0" in last
    assert "aragora-verify==0.1.1" in last


def test_unresolvable_pin_exits_non_zero(fake_toolchain: dict[str, Path]) -> None:
    """An unresolvable pin fails the install step instead of silently continuing."""
    proc = _run(fake_toolchain, ["aragora-verify==99.9.9"])

    assert proc.returncode != 0
    assert "aragora-verify==99.9.9" in _log(fake_toolchain, "pip.log")
    assert "step: demo" not in proc.stdout


def test_local_wheels_replace_the_pypi_specs(
    fake_toolchain: dict[str, Path], tmp_path: Path
) -> None:
    """Pre-publish runs install local wheels instead of the published packages."""
    wheel_a = tmp_path / "aragora-2.11.0-py3-none-any.whl"
    wheel_v = tmp_path / "aragora_verify-0.2.0-py3-none-any.whl"
    wheel_a.write_text("", encoding="utf-8")
    wheel_v.write_text("", encoding="utf-8")

    proc = _run(
        fake_toolchain,
        ["--aragora-wheel", str(wheel_a), "--verify-wheel", str(wheel_v)],
    )

    assert proc.returncode == 0, proc.stderr
    last = _log(fake_toolchain, "pip.log").splitlines()[-1].split()
    assert last == ["install", "--quiet", str(wheel_a), str(wheel_v)]


def test_relative_wheel_paths_survive_the_scratch_directory(
    fake_toolchain: dict[str, Path], tmp_path: Path
) -> None:
    """Wheels given as ``dist/<name>.whl`` still resolve once the script cd's away."""
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel_a = dist / "aragora-2.11.0-py3-none-any.whl"
    wheel_v = dist / "aragora_verify-0.2.0-py3-none-any.whl"
    wheel_a.write_text("", encoding="utf-8")
    wheel_v.write_text("", encoding="utf-8")

    proc = _run(
        fake_toolchain,
        [
            "--aragora-wheel",
            "dist/aragora-2.11.0-py3-none-any.whl",
            "--verify-wheel",
            "dist/aragora_verify-0.2.0-py3-none-any.whl",
        ],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    last = _log(fake_toolchain, "pip.log").splitlines()[-1].split()
    assert last == ["install", "--quiet", str(wheel_a), str(wheel_v)]


def test_missing_wheel_is_reported_before_the_venv_is_built(
    fake_toolchain: dict[str, Path], tmp_path: Path
) -> None:
    """A wheel path that does not exist is a usage error, not a pip surprise."""
    proc = _run(fake_toolchain, ["--aragora-wheel", str(tmp_path / "nope.whl")])

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "nope.whl" in proc.stdout + proc.stderr
    assert "step: install" not in proc.stdout


def test_caller_env_is_scrubbed_for_the_install_demo_and_export_steps(
    fake_toolchain: dict[str, Path], tmp_path: Path
) -> None:
    """No signing input reaches the CLI that writes the receipt, and no caller
    index reaches pip.

    The key variables are the obvious channel; the secrets-manager switches are
    the second one, since the exporter falls back to a remote key when they say
    it may (``aragora/gauntlet/odr_export.py`` → ``aragora/config/secrets.py``).
    Absence is not enough there: an AWS-hosted runner opts in through
    ``AWS_EXECUTION_ENV`` unless the flag says false outright. pip's index
    variables are scrubbed for a related reason: the transcript is evidence
    about the published packages only if the caller cannot substitute them.
    The variables are only half of that channel, since pip.conf carries the
    same settings, so the install also pins ``PIP_CONFIG_FILE`` at /dev/null.
    """
    key = tmp_path / "key.pem"
    key.write_text("not-a-key\n", encoding="utf-8")

    proc = _run(
        fake_toolchain,
        env_extra={
            "ARAGORA_ODR_SIGNING_KEY_FILE": str(key),
            "ARAGORA_ODR_SIGNING_KEY_SECRET": "mission-secret",
            "PYTHONPATH": str(REPO_ROOT),
            "ARAGORA_USE_SECRETS_MANAGER": "true",
            "ARAGORA_ENV": "production",
            "AWS_EXECUTION_ENV": "AWS_ECS_FARGATE",
            "PIP_INDEX_URL": "https://mirror.invalid/simple",
            "PIP_EXTRA_INDEX_URL": "https://extra.invalid/simple",
            "PIP_FIND_LINKS": str(tmp_path),
            "PIP_CONSTRAINT": str(tmp_path / "constraints.txt"),
            "PIP_CONFIG_FILE": str(tmp_path / "pip.conf"),
        },
    )

    assert proc.returncode == 0, proc.stderr
    env_log = _log(fake_toolchain, "env.log").splitlines()
    assert len(env_log) == 2, env_log
    for line in env_log:
        assert line == (
            "KEY_FILE=<unset> SECRET=<unset> PYTHONPATH=<unset> SECRETS_MANAGER=false ENV=<unset>"
        )

    assert _log(fake_toolchain, "pip-env.log").splitlines() == [
        "INDEX=<unset> EXTRA_INDEX=<unset> FIND_LINKS=<unset> "
        "CONSTRAINT=<unset> CONFIG_FILE=/dev/null"
    ]


def test_published_receipt_requires_a_pubkey_url(fake_toolchain: dict[str, Path]) -> None:
    """The explicit published-receipt path needs both URLs, or it is a usage error."""
    proc = _run(fake_toolchain, ["--published-receipt", "https://example.invalid/r.odr.json"])

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "--pubkey-url" in proc.stdout + proc.stderr


def test_no_flag_run_skips_cleanly_when_no_receipts_release_exists(
    fake_toolchain: dict[str, Path],
) -> None:
    """Without a published release the run still succeeds and says why."""
    proc = _run(fake_toolchain)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "published receipt: skipped (no receipts-* release)" in proc.stdout
    assert "gh release download" not in _log(fake_toolchain, "gh.log")


def test_no_flag_run_self_resolves_the_newest_receipts_release(
    fake_toolchain: dict[str, Path],
) -> None:
    """With a release present the run downloads and verifies its clean receipt."""
    proc = _run(fake_toolchain, env_extra={"FAKE_GH_TAG": "receipts-2026-09-22"})

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "step: published" in proc.stdout
    assert "published receipt: synaptent/aragora receipts-2026-09-22" in proc.stdout

    gh_log = _log(fake_toolchain, "gh.log")
    assert "release list -R synaptent/aragora --limit 100" in gh_log
    assert "release download receipts-2026-09-22" in gh_log

    # the receipt AND the key both come from that release, checked together
    verify_args = _log(fake_toolchain, "verify.log").splitlines()[-1]
    assert verify_args.endswith("aragora-odr-signing.pub.pem")
    assert "pr1-clean.odr.json --pubkey" in verify_args


def test_self_resolved_release_without_the_expected_assets_fails(
    fake_toolchain: dict[str, Path],
) -> None:
    """A receipts-* release missing the receipt/key pair is an error, not a pass."""
    proc = _run(
        fake_toolchain,
        env_extra={"FAKE_GH_TAG": "receipts-2026-09-22", "FAKE_GH_ASSETS": ""},
    )

    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert "no pr*-clean.odr.json" in proc.stdout + proc.stderr


def test_self_resolve_is_skipped_when_gh_is_absent(fake_toolchain: dict[str, Path]) -> None:
    """A host without ``gh`` still finishes the offline first hour successfully."""
    gh_free = [
        d
        for d in os.environ["PATH"].split(os.pathsep)
        if d and not os.access(os.path.join(d, "gh"), os.X_OK)
    ]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PATH"] = os.pathsep.join([str(fake_toolchain["path"]), *gh_free])
    env["FAKE_BIN"] = str(fake_toolchain["bin"])
    env["FAKE_LOG"] = str(fake_toolchain["log"])
    env["TMPDIR"] = str(fake_toolchain["tmp"])
    os.remove(fake_toolchain["path"] / "gh")
    proc = subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, check=False, env=env
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "published receipt: skipped (gh not available)" in proc.stdout


def test_published_receipt_path_labels_its_step_and_its_two_downloads(
    fake_toolchain: dict[str, Path],
) -> None:
    """The explicit path announces itself and names which download failed."""
    proc = _run(
        fake_toolchain,
        [
            "--published-receipt",
            "https://127.0.0.1:1/r.odr.json",
            "--pubkey-url",
            "https://127.0.0.1:1/k.pem",
        ],
    )

    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert "step: published" in proc.stdout
    assert "receipt-download step failed" in proc.stderr
    assert "pubkey-download step failed" not in proc.stderr


def test_public_key_fetch_pins_https_and_bounds_its_redirects() -> None:
    """The key fetch cannot be redirected off https or led on a long chain."""
    text = SCRIPT.read_text(encoding="utf-8")
    fetch = text.split("fetch_pubkey() {", 1)[1].split("}", 1)[0]

    assert "--proto '=https'" in fetch
    assert "--proto-redir '=https'" in fetch
    assert "--max-redirs 2" in fetch


def test_budget_stops_a_hung_step_instead_of_waiting_for_it(
    fake_toolchain: dict[str, Path], tmp_path: Path
) -> None:
    """A step that outlasts the budget is stopped mid-run, with the exit contract."""
    hang = fake_toolchain["bin"] / "aragora"
    hang.write_text("#!/usr/bin/env bash\nsleep 120\n", encoding="utf-8")
    hang.chmod(0o755)

    started = time.monotonic()
    proc = _run(fake_toolchain, env_extra={"RECEIPT_FIRST_HOUR_BUDGET": "3"})
    elapsed = time.monotonic() - started

    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert elapsed < 60, elapsed
    assert re.search(r"receipt-first-hour: demo step failed, exit=\d+", proc.stderr)
    assert "step was stopped at the 3s budget" in proc.stderr
    assert re.search(r"^total wall time: [0-9]+s$", proc.stdout, re.MULTILINE)


def test_missing_ensurepip_is_named_instead_of_a_bare_exit_code(
    fake_toolchain: dict[str, Path], tmp_path: Path
) -> None:
    """A host without ``ensurepip`` gets an actionable message, not exit 127 alone."""
    stub = fake_toolchain["path"] / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = "-c" ]; then\n'
        '  case "${2:-}" in *ensurepip*) exit 1 ;; esac\n'
        "fi\n"
        f'exec {sys.executable} "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    proc = _run(fake_toolchain)

    assert proc.returncode == 127, (proc.stdout, proc.stderr)
    assert "ensurepip" in proc.stderr
    assert "python3-venv" in proc.stderr
    assert "install step failed, exit=127" in proc.stderr


def test_a_completed_earlier_scratch_tree_is_reclaimed_and_a_failed_one_is_not(
    fake_toolchain: dict[str, Path],
) -> None:
    """The persistent-runner leak stops without destroying a failure's evidence."""
    scratch = fake_toolchain["tmp"]
    old_clean = scratch / "receipt-first-hour.oldok"
    old_failed = scratch / "receipt-first-hour.oldbad"
    fresh_clean = scratch / "receipt-first-hour.recent"
    for d in (old_clean, old_failed, fresh_clean):
        (d / "venv" / "lib").mkdir(parents=True)
    stale = time.time() - 3600
    for marker in (old_clean / ".complete", fresh_clean / ".complete"):
        marker.write_text("", encoding="utf-8")
    os.utime(old_clean / ".complete", (stale, stale))

    proc = _run(fake_toolchain)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert not old_clean.exists(), "an idle completed tree is the leak and must go"
    assert old_failed.is_dir(), "a failed run's tree is the reader's evidence"
    assert fresh_clean.is_dir(), "a just-finished tree may still be in use"
    assert f"reclaimed: {old_clean}" in proc.stdout

    # this run's own tree survives: `venv:` and `odr:` still point at real paths
    venv = next(ln for ln in proc.stdout.splitlines() if ln.startswith("venv: "))
    assert Path(venv.split(" ", 1)[1]).is_dir()


def test_a_failed_run_leaves_no_completion_marker(fake_toolchain: dict[str, Path]) -> None:
    """Only a clean finish marks a tree reclaimable by a later run."""
    proc = _run(fake_toolchain, env_extra={"FAKE_VERIFY_EXIT": "3"})

    assert proc.returncode == 3
    roots = list(fake_toolchain["tmp"].glob("receipt-first-hour.*"))
    assert roots, "the failing run's scratch tree is left behind"
    assert not any((root / ".complete").exists() for root in roots)


def test_script_honours_the_contract_greps() -> None:
    """Static contract from architecture 2.7 / VAL-ODR-022 / VAL-ODR-029."""
    text = SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert "\n".join(lines[:30]).count("aragora==") >= 1
    assert "mktemp -d" in text
    assert re.search(r"python3? -m venv", text)

    # never pins a profile version: the published default path is the contract
    assert not re.search(r"odr-version|ODR_PROFILE_VERSION", text)

    # PYTHONPATH appears only in unset form
    pythonpath_lines = [ln for ln in lines if "PYTHONPATH" in ln]
    assert pythonpath_lines
    assert all("unset PYTHONPATH" in ln or "env -u PYTHONPATH" in ln for ln in pythonpath_lines)

    # both signing variables are removed for the demo/export step
    assert re.search(
        r"unset[^#]*ARAGORA_ODR_SIGNING_KEY_FILE|env -u ARAGORA_ODR_SIGNING_KEY_FILE", text
    )
    assert re.search(
        r"unset[^#]*ARAGORA_ODR_SIGNING_KEY_SECRET|-u ARAGORA_ODR_SIGNING_KEY_SECRET", text
    )

    # the verifier's exit code is never swallowed, and exit 3 is not accepted
    verify_lines = [ln for ln in lines if "aragora-verify" in ln]
    assert verify_lines
    assert not [ln for ln in verify_lines if "|| true" in ln or "-eq 3" in ln]
    assert re.search(r"exit=|exit code", text)

    # the 300 s budget sits on a non-zero exit path
    budget = [i for i, ln in enumerate(lines) if "300" in ln]
    assert budget
    assert any(re.search(r"exit [1-9]", ln) for i in budget for ln in lines[max(0, i - 2) : i + 3])
