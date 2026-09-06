from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.check_aragora_verify_dependency_policy import check_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_MANIFEST = """
[build-system]
requires = ["hatchling>=1"]

[project]
dependencies = ["cryptography>=48"]

[project.optional-dependencies]
schema = ["jsonschema>=4"]
dev = ["pytest>=8", "pytest-cov>=7", "pytest-randomly>=4", "pytest-timeout>=2", "pytest-xdist>=3"]
"""


def _check(tmp_path: Path, content: str) -> list[str]:
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(content, encoding="utf-8")
    return check_manifest(manifest)


def test_current_manifest_matches_policy() -> None:
    assert check_manifest(REPO_ROOT / "aragora-verify" / "pyproject.toml") == []


@pytest.mark.parametrize(
    ("needle", "replacement", "dependency"),
    [
        ('requires = ["hatchling>=1"]', 'requires = ["hatchling>=1", "setuptools"]', "setuptools"),
        (
            'dependencies = ["cryptography>=48"]',
            'dependencies = ["cryptography>=48", "httpx"]',
            "httpx",
        ),
        ('schema = ["jsonschema>=4"]', 'schema = ["jsonschema>=4", "referencing"]', "referencing"),
        ('"pytest>=8"', '"pytest>=8", "ruff"', "ruff"),
    ],
)
def test_rejects_unadopted_dependency(
    tmp_path: Path, needle: str, replacement: str, dependency: str
) -> None:
    errors = _check(tmp_path, BASE_MANIFEST.replace(needle, replacement))
    assert any("unadopted dependency" in error and dependency in error for error in errors)


def test_rejects_new_optional_dependency_group(tmp_path: Path) -> None:
    errors = _check(tmp_path, BASE_MANIFEST + 'qa = ["tox"]\n')
    assert any("optional-dependencies.qa" in error and "tox" in error for error in errors)


def test_normalizes_names_with_extras_and_markers(tmp_path: Path) -> None:
    content = BASE_MANIFEST.replace(
        '"hatchling>=1"', "\"Hatchling[cli]>=1; python_version >= '3.10'\""
    ).replace('"jsonschema>=4"', "\"JSONSchema[format]>=4; platform_system != 'Plan9'\"")
    assert _check(tmp_path, content) == []


@pytest.mark.parametrize(
    "requirement",
    ["pytest>=8", "pytest-cov>=7", "pytest-randomly>=4", "pytest-timeout>=2", "pytest-xdist>=3"],
)
def test_rejects_missing_adopted_dependency(tmp_path: Path, requirement: str) -> None:
    content = BASE_MANIFEST.replace(f'"{requirement}", ', "").replace(f', "{requirement}"', "")
    errors = _check(tmp_path, content)
    assert any(f"missing adopted dependency '{requirement.split('>=')[0]}'" in e for e in errors)


def test_fails_closed_on_malformed_toml(tmp_path: Path) -> None:
    errors = _check(tmp_path, "[project\ndependencies = []")
    assert len(errors) == 1
    assert errors[0].startswith("cannot parse ")


def test_fails_closed_on_malformed_requirement(tmp_path: Path) -> None:
    errors = _check(tmp_path, BASE_MANIFEST.replace('"pytest>=8"', '"@@@"'))
    assert any("invalid PEP 508 requirement" in error for error in errors)


def test_lint_workflow_invokes_checker_once() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/lint.yml").read_text())
    steps = workflow["jobs"]["lint-run"]["steps"]
    matching = [
        step
        for step in steps
        if "scripts/check_aragora_verify_dependency_policy.py" in str(step.get("run", ""))
    ]
    assert len(matching) == 1
    assert matching[0]["name"] == "Enforce aragora-verify dependency policy"


def test_verifier_changes_enter_lint_scope() -> None:
    classifier = yaml.safe_load(
        (REPO_ROOT / ".github/actions/pr-scope-classifier/action.yml").read_text()
    )
    filters = classifier["runs"]["steps"][0]["with"]["filters"]
    lint_python = filters.split("lint_python:", 1)[1].split("quality:", 1)[0]
    assert "- 'aragora-verify/**'" in lint_python
