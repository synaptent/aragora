"""Keep the documented test extra sufficient for readiness pytest options."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_PLUGINS = [("-n", "pytest-xdist"), ("--timeout", "pytest-timeout")]
# Workflows whose pull-request trigger must fire on every manifest that feeds
# root uv.lock validity: the root project plus each uv workspace member.
LOCK_CHECK_WORKFLOWS = {
    ".github/workflows/security-gate.yml": "pull_request",
    ".github/workflows/dependabot-uv-lock.yml": "pull_request_target",
}


def _workspace_members() -> list[str]:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = project["tool"]["uv"]["workspace"]["members"]
    assert members, "root pyproject.toml must declare uv workspace members"
    return list(members)


def _workflow_trigger_paths(workflow: Path, event: str) -> list[str]:
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    # PyYAML 1.1 parses the bare ``on:`` key as the boolean True.
    triggers = data["on"] if "on" in data else data[True]
    return list(triggers[event]["paths"])


@pytest.mark.parametrize(("workflow", "event"), sorted(LOCK_CHECK_WORKFLOWS.items()))
def test_lock_check_workflows_trigger_on_workspace_member_manifests(
    workflow: str, event: str
) -> None:
    paths = _workflow_trigger_paths(REPO_ROOT / workflow, event)
    assert "pyproject.toml" in paths
    assert "uv.lock" in paths
    for member in _workspace_members():
        manifest = f"{member}/pyproject.toml"
        assert manifest in paths, (
            f"{workflow} must trigger on {manifest}: a member-only manifest change "
            "invalidates the shared root uv.lock"
        )


def test_workspace_member_manifest_change_invalidates_root_lock(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    members = _workspace_members()
    for rel in ("pyproject.toml", "uv.lock", *(f"{member}/pyproject.toml" for member in members)):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / rel).read_bytes())

    def lock_check() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [uv, "lock", "--check", "--offline", "--project", str(tmp_path)],
            capture_output=True,
            text=True,
            env={**os.environ, "UV_NO_PROGRESS": "1"},
            timeout=120,
            check=False,
        )

    baseline = lock_check()
    assert baseline.returncode == 0, baseline.stderr

    # Bump the first member with a static version; the root lock records it.
    for member in members:
        manifest = tmp_path / member / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        match = re.search(r'(?m)^version = "(\d+)\.(\d+)\.(\d+)"', text)
        if match is None:
            continue
        bumped = f'version = "{match[1]}.{match[2]}.{int(match[3]) + 1}"'
        manifest.write_text(text.replace(match[0], bumped, 1), encoding="utf-8")
        break
    else:
        pytest.fail("no workspace member declares a static version to bump")

    stale = lock_check()
    assert stale.returncode != 0, "a member-only manifest change must fail uv lock --check"


def test_dependabot_cooldown_respects_ecosystem_support() -> None:
    config = yaml.safe_load((REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    actions = [
        entry for entry in config["updates"] if entry["package-ecosystem"] == "github-actions"
    ]
    assert len(actions) == 1
    # Actions supports a default cooldown, but not SemVer-specific cooldown keys.
    assert actions[0]["cooldown"] == {"default-days": 7}
    for entry in config["updates"]:
        if entry["package-ecosystem"] != "github-actions":
            assert entry["cooldown"] == {"default-days": 7, "semver-major-days": 14}


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
