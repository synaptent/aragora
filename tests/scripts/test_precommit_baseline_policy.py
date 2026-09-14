"""Regression coverage for repository-wide pre-commit policy."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _hook(hook_id: str) -> dict[str, object]:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    for repository in config["repos"]:
        for hook in repository["hooks"]:
            if hook["id"] == hook_id:
                return hook
    raise AssertionError(f"missing pre-commit hook: {hook_id}")


def _ruff_ignore_codes(path_pattern: str) -> set[str]:
    config = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assignment = re.search(
        rf'^\s*"{re.escape(path_pattern)}"\s*=\s*(\[[^\n]+\])\s*$',
        config,
        re.MULTILINE,
    )
    assert assignment, f"missing Ruff per-file ignore for {path_pattern}"
    values = ast.literal_eval(assignment.group(1))
    assert isinstance(values, list)
    assert all(isinstance(value, str) for value in values)
    return set(values)


@pytest.mark.parametrize("hook_id", ["trailing-whitespace", "end-of-file-fixer"])
def test_text_normalizers_exclude_nested_markdown(hook_id: str) -> None:
    pattern = re.compile(str(_hook(hook_id)["exclude"]))
    assert pattern.search("tests/server/handlers/CLAUDE.md")
    assert pattern.search("aragora/server/handlers/oracle_essay.md")
    assert not pattern.search("aragora/live/e2e/export.spec.ts")


@pytest.mark.parametrize("path", [".grok/settings.json", "replays/demo.json", "uv.lock"])
def test_eof_normalizer_excludes_structured_artifacts(path: str) -> None:
    pattern = re.compile(str(_hook("end-of-file-fixer")["exclude"]))
    assert pattern.search(path)


@pytest.mark.parametrize("hook_id", ["end-of-file-fixer", "ruff", "ruff-format"])
def test_python_rewriters_exclude_integrity_pinned_launcher(hook_id: str) -> None:
    pattern = re.compile(str(_hook(hook_id)["exclude"]))
    assert pattern.search(".github/workflows/contract_drift_trusted_launcher.py")
    assert not pattern.search(".github/workflows/contract_drift_trusted_bootstrap.py")


def test_yaml_hook_excludes_only_helm_template_trees() -> None:
    pattern = re.compile(str(_hook("check-yaml")["exclude"]))
    assert pattern.search("deploy/kubernetes/helm/aragora/templates/deployment-backend.yaml")
    assert pattern.search("deploy/helm/aragora/templates/deployment.yaml")
    assert not pattern.search("deploy/kubernetes/ordinary-config.yaml")


def test_typecheck_hook_uses_authoritative_merge_base_delta() -> None:
    hook = _hook("typecheck-changed")
    entry = str(hook["entry"])

    assert "scripts/run_typecheck_gate.py" in entry
    assert "--base-ref main --head-ref HEAD" in entry
    assert "--files" not in entry
    assert "$@" not in entry
    assert hook["pass_filenames"] is False
    assert hook["always_run"] is True


def test_documentation_does_not_embed_pem_markers() -> None:
    guide = (REPO_ROOT / "docs/guides/GITHUB_APP_SETUP.md").read_text(encoding="utf-8")
    assert "BEGIN RSA PRIVATE KEY" not in guide
    assert re.search(r'^GITHUB_APP_PRIVATE_KEY="[^"]+"$', guide, re.MULTILINE)
    assert "GITHUB_APP_PRIVATE_KEY_PATH=" not in guide


def test_ruff_exceptions_are_narrow_and_explicit() -> None:
    assert "S101" in _ruff_ignore_codes("benchmarks/*.py")
    assert {"T201", "BLE001"} <= _ruff_ignore_codes("deploy/liftmode/briefing.py")
