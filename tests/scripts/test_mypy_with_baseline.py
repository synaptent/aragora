"""Focused tests for the fail-closed baseline-aware mypy gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
from types import ModuleType

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "mypy_with_baseline.py"
LINT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lint.yml"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mypy_with_baseline_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gate() -> ModuleType:
    return _load_script()


def _write_pyproject(path: Path, mypy_requirement: str = "mypy==2.2.0") -> None:
    path.write_text(
        "[project.optional-dependencies]\n"
        "dev = [\n"
        f'  "{mypy_requirement}",\n'
        '  "mypy-baseline==0.7.4",\n'
        '  "pyjwt[crypto]==2.13.0",\n'
        "]\n",
        encoding="utf-8",
    )


def _configure_gate(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    create_baseline: bool = True,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    baseline = tmp_path / ".mypy-baseline"
    _write_pyproject(pyproject)
    if create_baseline:
        baseline.write_text("", encoding="utf-8")
    monkeypatch.setattr(gate, "PYPROJECT_PATH", pyproject)
    monkeypatch.setattr(gate, "BASELINE_PATH", baseline)
    monkeypatch.setattr(
        gate,
        "_installed_distribution_version",
        lambda distribution: {
            "mypy": "2.2.0",
            "mypy-baseline": "0.7.4",
            "pyjwt": "2.13.0",
        }[distribution],
    )


def test_print_install_requirements_uses_structured_pyproject(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path)

    assert gate.main(["--print-install-requirements"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "mypy==2.2.0",
        "mypy-baseline==0.7.4",
        "pyjwt[crypto]==2.13.0",
    ]


def test_ci_mypy_installs_use_declared_requirements() -> None:
    workflow = LINT_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("scripts/ci/mypy_with_baseline.py --print-install-requirements") == 2
    assert "pip install --user mypy " not in workflow
    assert "pip install mypy " not in workflow
    assert workflow.count('"pyjwt[crypto]==2.13.0"') == 0


def test_local_hook_uses_declared_typecheck_toolchain() -> None:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    hooks = [
        hook
        for repo in config["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
        if hook["id"] == "typecheck-changed"
    ]

    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["language"] == "system"
    assert hook["require_serial"] is True
    assert "uv run --frozen --extra dev" in hook["entry"]
    assert "TYPECHECK_PYTHON=python bash scripts/test_tiers.sh typecheck" in hook["entry"]
    assert "additional_dependencies" not in hook


def test_python_310_toml_fallback_is_declared_before_dev_requirements_load() -> None:
    with PYPROJECT.open("rb") as handle:
        document = tomllib.load(handle)

    assert "tomli>=2.0.1,<3.0; python_version < '3.11'" in document["project"]["dependencies"]


def test_rejects_non_exact_mypy_requirement(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, "mypy>=2.1,<3")
    monkeypatch.setattr(gate, "PYPROJECT_PATH", pyproject)

    assert gate.main(["--print-install-requirements"]) == 2
    assert "must use one exact" in capsys.readouterr().err


def test_version_mismatch_fails_before_mypy_runs(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path)
    monkeypatch.setattr(
        gate,
        "_installed_distribution_version",
        lambda distribution: {
            "mypy": "2.1.0",
            "mypy-baseline": "0.7.4",
            "pyjwt": "2.13.0",
        }[distribution],
    )
    monkeypatch.setattr(
        gate,
        "_run_mypy",
        lambda args: pytest.fail("mypy must not run after a version mismatch"),
    )

    assert gate.main([]) == 2
    assert "does not match pinned version" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("distribution", "actual"),
    (("mypy-baseline", "0.7.5"), ("pyjwt", "2.12.0")),
)
def test_dependency_version_mismatch_fails_before_mypy_runs(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    distribution: str,
    actual: str,
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path)
    versions = {"mypy": "2.2.0", "mypy-baseline": "0.7.4", "pyjwt": "2.13.0"}
    versions[distribution] = actual
    monkeypatch.setattr(gate, "_installed_distribution_version", versions.__getitem__)
    monkeypatch.setattr(
        gate,
        "_run_mypy",
        lambda args: pytest.fail("mypy must not run after a version mismatch"),
    )

    assert gate.main([]) == 2
    assert distribution in capsys.readouterr().err


def test_missing_baseline_fails_closed(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path, create_baseline=False)

    assert gate.main([]) == 2
    assert "committed baseline is missing" in capsys.readouterr().err


def test_unexpected_mypy_status_is_propagated(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path)
    monkeypatch.setattr(
        gate,
        "_run_mypy",
        lambda args: subprocess.CompletedProcess(args=[], returncode=2, stdout="mypy crashed\n"),
    )

    assert gate.main([]) == 2
    captured = capsys.readouterr()
    assert "mypy crashed" in captured.out
    assert "unexpected status 2" in captured.err


def test_mypy_failure_without_diagnostics_fails_parser_drift(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path)
    monkeypatch.setattr(
        gate,
        "_run_mypy",
        lambda args: subprocess.CompletedProcess(args=[], returncode=1, stdout="opaque failure\n"),
    )
    monkeypatch.setattr(
        gate,
        "_run_baseline",
        lambda output, sync: pytest.fail("unparseable output must not reach the baseline"),
    )

    assert gate.main([]) == 1
    assert "without any recognized" in capsys.readouterr().err


def test_line_only_mypy_diagnostic_reaches_baseline(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_gate(gate, monkeypatch, tmp_path)
    output = "aragora/example.py:12: error: incompatible type [assignment]\n"
    monkeypatch.setattr(
        gate,
        "_run_mypy",
        lambda args: subprocess.CompletedProcess(args=[], returncode=1, stdout=output),
    )
    observed: dict[str, object] = {}

    def fake_baseline(value: str, *, sync: bool) -> int:
        observed.update(output=value, sync=sync)
        return 0

    monkeypatch.setattr(gate, "_run_baseline", fake_baseline)

    assert gate.main([]) == 0
    assert observed == {"output": output, "sync": False}
