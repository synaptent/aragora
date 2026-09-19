"""Keep the documented test extra sufficient for readiness pytest options."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_PLUGINS = [("-n", "pytest-xdist"), ("--timeout", "pytest-timeout")]


@pytest.mark.parametrize(("flag", "package"), PYTEST_PLUGINS)
def test_readiness_pytest_flags_have_declared_plugins(flag: str, package: str) -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"(?m)^readiness-test-root:\n((?:\t[^\n]*\n)+)", makefile)
    assert recipe is not None
    assert re.search(rf"(?<!\S){re.escape(flag)}(?:=|\s)", recipe.group(1))

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = {
        canonicalize_name(requirement.name): requirement
        for requirement in map(Requirement, project["project"]["optional-dependencies"]["test"])
    }
    assert package in requirements, f"readiness-test-root's {flag} requires {package}"
    assert requirements[package].marker is None


@pytest.mark.parametrize("package", [package for _, package in PYTEST_PLUGINS])
def test_readiness_pytest_plugins_are_locked_in_test_extra(package: str) -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    root = next(item for item in lock["package"] if item["name"] == "aragora")
    assert package in {item["name"] for item in root["optional-dependencies"]["test"]}

    requirement = next(
        requirement
        for requirement in map(Requirement, project["project"]["optional-dependencies"]["test"])
        if canonicalize_name(requirement.name) == package
    )
    versions = [item["version"] for item in lock["package"] if item["name"] == package]
    assert versions
    assert all(version in requirement.specifier for version in versions)
