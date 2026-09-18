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
printf 'INDEX=%s EXTRA_INDEX=%s FIND_LINKS=%s CONSTRAINT=%s\\n' \\
  "${PIP_INDEX_URL-<unset>}" \\
  "${PIP_EXTRA_INDEX_URL-<unset>}" \\
  "${PIP_FIND_LINKS-<unset>}" \\
  "${PIP_CONSTRAINT-<unset>}" >> "$FAKE_LOG/pip-env.log"
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
        "INDEX=<unset> EXTRA_INDEX=<unset> FIND_LINKS=<unset> CONSTRAINT=<unset>"
    ]


def test_published_receipt_requires_a_pubkey_url(fake_toolchain: dict[str, Path]) -> None:
    """The explicit published-receipt path needs both URLs, or it is a usage error."""
    proc = _run(fake_toolchain, ["--published-receipt", "https://example.invalid/r.odr.json"])

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "--pubkey-url" in proc.stdout + proc.stderr


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
