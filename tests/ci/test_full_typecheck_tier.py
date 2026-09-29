"""The required full tier must count real errors and reject new debt."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "scripts/baselines/root-mypy-full.json"
MYPY_ARGS = ["aragora/", "--ignore-missing-imports", "--show-error-codes"]


@pytest.fixture
def wrapper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "full_typecheck_wrapper", ROOT / "scripts/ci/mypy_with_baseline.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    # Unit tests fake the tool, including its version and host, not the ambient test venv.
    monkeypatch.setattr(module, "version", lambda name: "2.1.0")
    monkeypatch.setattr(module, "_host_python_version", lambda: "3.11")
    return module


def diagnostic(location: str = "2", path: str = "aragora/a.py") -> str:
    return f"{path}:{location}: error: Incompatible return value type  [return-value]\n"


def output(*errors: str) -> str:
    count = len(errors)
    return "".join(errors) + (
        f"Found {count} errors in 1 file (checked 2 source files)\n"
        if count
        else "Success: no issues found in 2 source files\n"
    )


def fake_run(wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, text: str, rc: int = 1) -> None:
    monkeypatch.setattr(wrapper, "run_tool", lambda *args: (rc, text, ""))


def invoke(wrapper: ModuleType, *options: str) -> int:
    return wrapper.main(["--baseline", BASELINE, *options, "--", *MYPY_ARGS])


@pytest.mark.parametrize("location", ["2", "2:5"])
def test_counts_both_mypy_formats_and_baselines_only_existing(
    wrapper: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    location: str,
) -> None:
    fake_run(wrapper, monkeypatch, output(diagnostic(location)))
    assert invoke(wrapper, "--update") == 0
    baseline = tmp_path / BASELINE
    before = baseline.read_bytes()
    assert invoke(wrapper) == 0
    printed = capsys.readouterr().out
    assert "Found 1 mypy error(s)" in printed
    assert "0 NEW errors" in printed
    fake_run(
        wrapper,
        monkeypatch,
        output(diagnostic(location), diagnostic(location, "aragora/_val_typecheck_probe.py")),
    )
    assert invoke(wrapper) == 1
    printed = capsys.readouterr().out
    assert "Found 2 mypy error(s)" in printed
    assert "1 NEW errors" in printed
    assert "_val_typecheck_probe.py" in printed
    assert baseline.read_bytes() == before


def test_new_count_is_occurrences_not_distinct_keys(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_run(wrapper, monkeypatch, output(diagnostic()))
    assert invoke(wrapper, "--update") == 0
    fake_run(wrapper, monkeypatch, output(diagnostic(), diagnostic(), diagnostic()))
    assert invoke(wrapper) == 1
    assert "2 NEW errors" in capsys.readouterr().out


def test_update_is_sorted_relative_idempotent_and_shrink_only(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_run(
        wrapper,
        monkeypatch,
        output(diagnostic(path=str(tmp_path / "aragora/z.py")), diagnostic()),
    )
    assert invoke(wrapper, "--update") == 0
    baseline = tmp_path / BASELINE
    before = baseline.read_bytes()
    findings = json.loads(before)["findings"]
    assert list(findings) == sorted(findings)
    assert all(key.startswith("aragora/") for key in findings)
    assert invoke(wrapper, "--update") == 0
    assert baseline.read_bytes() == before
    fake_run(wrapper, monkeypatch, output(diagnostic(path="aragora/new.py")))
    assert invoke(wrapper, "--update") == 1
    assert baseline.read_bytes() == before
    fake_run(wrapper, monkeypatch, output(), rc=0)
    assert invoke(wrapper) == 0
    assert baseline.read_bytes() == before
    assert invoke(wrapper, "--update") == 0
    assert json.loads(baseline.read_text())["findings"] == {}


@pytest.mark.parametrize(
    ("text", "rc"),
    [
        ("", 1),
        ("mypy: error: broken config", 2),
        (output(diagnostic()), 2),
        (diagnostic() + "Found 2 errors in 1 file (checked 2 source files)", 1),
        (diagnostic(), 1),
        (output(), 1),
        (output(diagnostic()), 0),
        ("", 0),
    ],
)
def test_tool_failure_or_partial_count_cannot_pass_or_refresh(
    wrapper: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    text: str,
    rc: int,
) -> None:
    fake_run(wrapper, monkeypatch, output(diagnostic()))
    assert invoke(wrapper, "--update") == 0
    baseline = tmp_path / BASELINE
    before = baseline.read_bytes()
    fake_run(wrapper, monkeypatch, text, rc)
    assert invoke(wrapper, "--update") == 3
    assert baseline.read_bytes() == before


def test_notes_are_not_errors(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_run(wrapper, monkeypatch, "aragora/a.py:1: note: hint\n" + output(), rc=0)
    assert invoke(wrapper, "--update") == 0
    assert "Found 0 mypy error(s)" in capsys.readouterr().out


def test_wrong_mypy_pin_fails_before_running(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(wrapper, "version", lambda name: "2.3.1")
    monkeypatch.setattr(wrapper, "run_tool", lambda *args: pytest.fail("must not run mypy"))
    assert invoke(wrapper, "--update") == 3
    assert "2.1.0" in capsys.readouterr().err


def test_json_gate_refuses_foreign_host_interpreter(
    wrapper: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_run(wrapper, monkeypatch, output(diagnostic()))
    assert invoke(wrapper, "--update") == 0
    capsys.readouterr()
    baseline = tmp_path / BASELINE
    before = baseline.read_bytes()
    monkeypatch.setattr(wrapper, "_host_python_version", lambda: "3.12")
    monkeypatch.setattr(wrapper, "run_tool", lambda *args: pytest.fail("must not run mypy"))
    for options in ((), ("--update",)):
        assert invoke(wrapper, *options) == 3
        captured = capsys.readouterr()
        assert "3.12" in captured.err
        assert "3.11" in captured.err
        assert sys.executable in captured.err
        assert "Found " not in captured.out
        assert " NEW " not in captured.out
        assert baseline.read_bytes() == before


def test_typecheck_host_pin_is_single_sourced(wrapper: ModuleType) -> None:
    import tomllib

    job = yaml.safe_load((ROOT / ".github/workflows/lint.yml").read_text())["jobs"]["typecheck-run"]
    steps = job["steps"]
    setup_index = next(
        i for i, s in enumerate(steps) if s.get("uses") == "./.github/actions/setup-python-safe"
    )
    resolve_index = next(i for i, s in enumerate(steps) if s.get("id") == "typecheck_python")
    assert setup_index < resolve_index
    workflow_pin = steps[setup_index]["with"]["python-version"]
    resolve = steps[resolve_index]["run"]
    assert "python_bin=" in resolve
    assert "::error::" in resolve
    assert "exit 1" in resolve
    assert '!= "3.11"' in resolve
    assert not any("python3.12" in step.get("run", "") for step in steps)
    assert not any("python3.13" in step.get("run", "") for step in steps)

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    tier = (ROOT / "scripts/test_tiers.sh").read_text()
    case = tier[tier.index("  typecheck)") : tier.index(";;", tier.index("  typecheck)"))]
    assert "--python-version=3.11" in case

    assert (
        workflow_pin
        == wrapper.HOST_PYTHON_VERSION
        == pyproject["tool"]["mypy"]["python_version"]
        == "3.11"
    )


@pytest.mark.parametrize("status", [0, 1, 2, 3])
def test_shell_tier_forwards_wrapper_exit_and_selected_interpreter(
    tmp_path: Path, status: int
) -> None:
    fake = tmp_path / "python"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\"\nexit {status}\n")
    fake.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/test_tiers.sh"), "typecheck"],
        cwd=ROOT,
        env={**os.environ, "TYPECHECK_PYTHON": str(fake)},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == status, result.stdout + result.stderr
    assert "scripts/ci/mypy_with_baseline.py" in result.stdout
    assert BASELINE in result.stdout
    for flag in ("--no-site-packages", "--platform=linux", "--python-version=3.11"):
        assert flag in result.stdout
    assert "--follow-imports=skip" not in result.stdout
    assert "--update" not in result.stdout
    assert ("completed successfully" in result.stdout) == (status == 0)


def test_workflow_pins_mypy_and_runs_tier_with_install_interpreter() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/lint.yml").read_text())["jobs"]
    worker = jobs["typecheck-run"]
    steps = {step.get("name"): step for step in worker["steps"]}
    assert "mypy==2.1.0" in steps["Install mypy and type stubs"]["run"]
    full = steps["Run full typecheck tier"]
    assert full["if"] == "steps.typecheck_plan.outputs.mode == 'full'"
    assert "bash scripts/test_tiers.sh typecheck" in full["run"]
    assert full["env"]["TYPECHECK_PYTHON"] == "${{ steps.typecheck_python.outputs.python_bin }}"
    assert "draft" not in worker["if"]
    assert jobs["typecheck"]["needs"] == ["changes", "typecheck-run"]


@pytest.mark.parametrize(
    "path",
    [
        "scripts/ci/mypy_with_baseline.py",
        "scripts/ci/check_tool_baseline.py",
        "scripts/ci/tool_baseline_parsers.py",
        BASELINE,
    ],
)
def test_full_gate_implementation_changes_force_full_mode(path: str) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_typecheck_gate import build_typecheck_plan

    assert build_typecheck_plan(repo_root=ROOT, changed_files=[path]).mode == "full"
