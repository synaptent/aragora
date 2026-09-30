"""Package gates must scan real code without inheriting root type exemptions."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("package", ["debate", "verify"])
def test_package_ruff_extends_root_with_strict_rules(package: str) -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]
    local = tomllib.loads((ROOT / f"aragora-{package}/pyproject.toml").read_text())["tool"]
    assert f"aragora-{package}*" not in root.get("exclude", [])
    assert local["ruff"]["extend"] == "../pyproject.toml"
    assert {"N", "C901"} <= set(local["ruff"]["lint"]["select"])
    assert local["ruff"]["lint"]["mccabe"]["max-complexity"] == 10
    assert set(root["lint"]["ignore"]) <= set(local["ruff"]["lint"]["ignore"])


@pytest.mark.parametrize("package", ["debate", "verify"])
def test_package_typecheck_uses_local_strict_config_and_pin(package: str) -> None:
    config = tomllib.loads((ROOT / f"aragora-{package}/pyproject.toml").read_text())["tool"]
    assert config["mypy"]["strict"] is True
    for override in config["mypy"].get("overrides", []):
        assert not override.get("ignore_errors")
        assert override.get("disallow_untyped_defs", True)
        assert not override.get("allow_untyped_defs")
        assert "no-untyped-def" not in override.get("disable_error_code", [])
    result = subprocess.run(
        ["make", "-n", f"readiness-typecheck-{package}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "mypy --strict src" in result.stdout
    assert "cd aragora-" + package in result.stdout
    assert '"2.1.0"' in result.stdout
    assert "strict mypy lands in M3" not in result.stdout


def test_root_no_longer_exempts_package_modules() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["mypy"]
    modules = {
        module
        for override in config["overrides"]
        for module in override["module"]
        if override.get("disallow_untyped_defs") is False
    }
    assert not modules & {
        "aragora_debate._mock",
        "aragora_debate.styled_mock",
        "aragora_verify.verifier",
    }


@pytest.mark.parametrize("package", ["debate", "verify"])
def test_package_coverage_gate_uses_its_own_module_and_recorded_floor(package: str) -> None:
    config = tomllib.loads((ROOT / f"aragora-{package}/pyproject.toml").read_text())["tool"]
    assert 0 < config["coverage"]["report"]["fail_under"] <= 100
    assert config["pytest"]["ini_options"]["python_files"] == ["test_*.py"]
    assert config["pytest"]["ini_options"]["python_functions"] == ["test_*"]
    assert config["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert config["pytest"]["ini_options"]["asyncio_mode"] == "auto"
    result = subprocess.run(
        ["make", "-n", f"readiness-test-{package}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert f"pytest aragora-{package}/tests" in result.stdout
    assert f"--cov=aragora_{package}" in result.stdout
    assert "--cov=aragora " not in result.stdout
    assert "--cov-fail-under=$fail_under" in result.stdout
    assert f'open("aragora-{package}/pyproject.toml","rb")' in result.stdout
    assert "--durations=10" in result.stdout
    assert "--junitxml=" in result.stdout


@pytest.mark.parametrize("package", ["debate", "verify"])
def test_package_lint_wires_source_ratchets_and_documented_baselines(package: str) -> None:
    config = tomllib.loads((ROOT / f"aragora-{package}/pyproject.toml").read_text())["tool"]
    assert config["deptry"]["optional_dependencies_dev_groups"] == ["dev"]
    assert {key for key in config["deptry"] if key.endswith("_groups")} == {
        "optional_dependencies_dev_groups"
    }
    assert config["deptry"]["known_first_party"] == [f"aragora_{package}"]
    assert not config["deptry"].get("ignore")
    result = subprocess.run(
        ["make", "-n", f"readiness-lint-{package}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    for command in (
        f"ruff check aragora-{package}",
        f"ruff format --check aragora-{package}",
        f"vulture aragora-{package}/src --min-confidence 80",
        f"cd aragora-{package} && deptry src",
        f"aragora-{package}/src --threshold",
        f"check_file_sizes.py --glob 'aragora-{package}/src/**/*.py'",
    ):
        assert command in result.stdout
    assert "npx --yes jscpd@" in result.stdout
    docs = (ROOT / "docs/TECH_DEBT.md").read_text()
    for tool in ("vulture", "file-sizes"):
        path = f"scripts/baselines/{package}-{tool}.json"
        assert f"--baseline {path}" in result.stdout
        data = json.loads((ROOT / path).read_text())
        findings = data["files" if tool == "file-sizes" else "findings"]
        row = next(line for line in docs.splitlines() if f"`{path}`" in line)
        assert int(row.split("|")[3].strip()) == len(findings)
