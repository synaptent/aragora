"""Contract tests for the maintained local mypy execution surfaces."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]


def _locked_package_version(name: str) -> str:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == name)
    return package["version"]


def test_precommit_mypy_pin_matches_locked_toolchain() -> None:
    locked_version = _locked_package_version("mypy")
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s+- mypy==(?P<version>[0-9.]+)\s*$", config)

    assert locked_version == "2.1.0"
    assert match is not None
    assert match.group("version") == locked_version


def test_ruff_pin_matches_locked_toolchain_and_ci() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (ruff_requirement,) = [
        requirement
        for requirement in pyproject["project"]["optional-dependencies"]["dev"]
        if requirement.startswith("ruff==")
    ]
    declared_version = ruff_requirement.removeprefix("ruff==")
    workflow = (REPO_ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")
    workflow_match = re.search(r"\bruff==(?P<version>[0-9.]+)\b", workflow)

    assert workflow_match is not None
    assert declared_version == _locked_package_version("ruff")
    assert workflow_match.group("version") == declared_version


def test_pristine_health_uses_locked_dev_runtime() -> None:
    script = (REPO_ROOT / "scripts/pristine_main_health.py").read_text(encoding="utf-8")

    assert (
        'LOCKED_DEV_RUN = ("uv", "run", "--locked", "--extra", "dev", "--extra", "test")' in script
    )
    assert 'shutil.which("mypy")' not in script
