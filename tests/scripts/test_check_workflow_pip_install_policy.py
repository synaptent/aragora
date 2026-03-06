from __future__ import annotations

from pathlib import Path

from scripts.check_workflow_pip_install_policy import (
    check_repo,
    find_bare_pip_install_violations,
)


def test_detects_bare_pip_install() -> None:
    text = """
jobs:
  build:
    steps:
      - run: pip install -e .
"""
    violations = find_bare_pip_install_violations(text)
    assert violations
    assert violations[0][0] == 5
    assert "python -m pip install" in violations[0][2]


def test_allows_python_module_pip_install() -> None:
    text = """
jobs:
  build:
    steps:
      - run: python -m pip install -e .
"""
    violations = find_bare_pip_install_violations(text)
    assert violations == []


def test_detects_fallback_bare_pip_install() -> None:
    text = """
jobs:
  build:
    steps:
      - run: python -m pip install -e . || pip install -e . || true
"""
    violations = find_bare_pip_install_violations(text)
    assert violations
    assert len(violations) == 1


def test_ignores_step_name_text() -> None:
    text = """
jobs:
  lint:
    steps:
      - name: Enforce workflow pip install policy
        run: python -m pip install -e .
"""
    violations = find_bare_pip_install_violations(text)
    assert violations == []


def test_repo_policy_passes_for_current_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = check_repo(repo_root)
    assert violations == []
