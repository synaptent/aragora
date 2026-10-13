"""Characterization of how team selection reaches the control plane and the marketplace.

``aragora.debate`` (domain layer) must not import ``aragora.control_plane`` or
``aragora.marketplace`` (application layer). Health scoring reads the agent status enum
from ``aragora.types.agent_status``; the control plane hands its registry to the selector
(``aragora.control_plane.arena_bridge``). The default marketplace template registry comes
from the factory hook in ``aragora.debate.template_registry_hooks``, which the marketplace
fills through the ``aragora.debate_template_registries`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.debate import template_registry_hooks as hooks
from aragora.debate.team_selector import TeamSelector
from aragora.types.agent_status import AgentStatus
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE_REGISTRATION = (
    "marketplace",
    "aragora.marketplace.debate_registration:register_debate_template_registry",
)


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hooks, "_factory", None)
    monkeypatch.setattr(
        hooks,
        "_declared_registrations",
        DeclaredRegistrations(
            hooks.TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP,
            source_pyproject=tmp_path / "missing.toml",
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hooks


def _declare(monkeypatch, *registrations):
    entry_points = [
        SimpleNamespace(name=f"d{i}", value=f"tests.declared:d{i}", load=lambda fn=fn: fn)
        for i, fn in enumerate(registrations)
    ]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            entry_points if group == hooks.TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP else []
        ),
    )


class _StatusRegistry:
    def __init__(self, info):
        self._info = info

    def get_sync(self, name):
        return self._info if name == "a1" else None


# --------------------------------------------------------------------------- health scoring


def test_a_selector_built_without_a_registry_does_not_build_one():
    assert TeamSelector().control_plane_registry is None


def test_an_unconnected_control_plane_registry_contributes_no_health_score():
    # The registry the selector used to build by default exposes neither get_sync nor
    # _agents, so it always scored 0.0; dropping the default removes no contribution.
    from aragora.control_plane.registry import AgentRegistry

    selector = TeamSelector(control_plane_registry=AgentRegistry())
    assert selector._compute_health_score(SimpleNamespace(name="a1")) == 0.0


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (AgentStatus.READY, 1.0),
        (AgentStatus.BUSY, 0.5),
        (AgentStatus.OFFLINE, 0.0),
        (AgentStatus.FAILED, 0.0),
        ("ready", 0.0),
    ],
)
def test_the_health_score_follows_the_registered_status(status, expected):
    info = SimpleNamespace(status=status, is_alive=lambda: True)
    selector = TeamSelector(control_plane_registry=_StatusRegistry(info))
    assert selector._compute_health_score(SimpleNamespace(name="a1")) == expected


def test_a_control_plane_agent_record_scores_through_the_types_enum():
    from aragora.control_plane.registry import AgentInfo

    info = AgentInfo(agent_id="a1", capabilities={"debate"}, status=AgentStatus.BUSY)
    selector = TeamSelector(control_plane_registry=_StatusRegistry(info))
    assert selector._compute_health_score(SimpleNamespace(name="a1")) == 0.5

    info.last_heartbeat = time.time() - 3600
    assert selector._compute_health_score(SimpleNamespace(name="a1")) == 0.0


# --------------------------------------------------------------------------- template hook


def test_an_unregistered_template_registry_raises(isolated_hook):
    with pytest.raises(
        hooks.TemplateRegistryNotRegisteredError, match="aragora.debate_template_registries"
    ):
        hooks.create_template_registry()


def test_registering_again_replaces_the_factory(isolated_hook):
    first, second = object(), object()
    hooks.register_template_registry_factory(lambda: first)
    hooks.register_template_registry_factory(lambda: second)
    assert hooks.create_template_registry() is second


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hooks.register_template_registry_factory(object)

    _declare(monkeypatch, register)

    first = hooks.create_template_registry()
    assert hooks.create_template_registry() is not first
    assert calls == ["register"]


def test_without_any_template_registry_the_selection_is_empty(isolated_hook, caplog):
    with caplog.at_level(logging.WARNING, logger="aragora.debate.team_selector"):
        assert TeamSelector().select_from_template("oxford-style") == []
    assert "could not initialise TemplateRegistry" in caplog.text


def test_an_injected_registry_skips_the_hook(isolated_hook):
    from aragora.marketplace.models import BUILTIN_DEBATE_TEMPLATES

    template = BUILTIN_DEBATE_TEMPLATES[0]
    registry = MagicMock()
    registry.get.return_value = template

    roles = TeamSelector(marketplace_registry=registry).select_from_template(template.metadata.id)

    assert roles == [entry["role"] for entry in template.agent_roles]
    assert not hooks._declared_registrations.loaded


def test_pyproject_declares_the_marketplace_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(
        hooks.TEMPLATE_REGISTRIES_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [MARKETPLACE_REGISTRATION]


def test_the_marketplace_registration_builds_the_registry_class_read_at_call_time(
    isolated_hook, monkeypatch
):
    from aragora.marketplace import registry as marketplace_registry
    from aragora.marketplace.debate_registration import register_debate_template_registry

    class PatchedRegistry:
        pass

    register_debate_template_registry()
    register_debate_template_registry()
    monkeypatch.setattr(marketplace_registry, "TemplateRegistry", PatchedRegistry)
    assert type(hooks.create_template_registry()) is PatchedRegistry


# --------------------------------------------------------------------------- template roles


def _workflow_template():
    from aragora.marketplace.models import TemplateCategory, TemplateMetadata, WorkflowTemplate

    metadata = TemplateMetadata(
        id="wf",
        name="wf",
        description="",
        version="1",
        author="t",
        category=TemplateCategory.CUSTOM,
    )
    return WorkflowTemplate(metadata=metadata, nodes=[], edges=[])


def _builtin(kind: str):
    from aragora.marketplace import models

    return getattr(models, f"BUILTIN_{kind}_TEMPLATES")[0]


@pytest.mark.parametrize(
    ("template_factory", "expected"),
    [
        (lambda: _builtin("DEBATE"), lambda t: [entry["role"] for entry in t.agent_roles]),
        (lambda: _builtin("AGENT"), lambda t: [t.agent_type]),
        (_workflow_template, lambda t: []),
        (MagicMock, lambda t: []),
    ],
    ids=["debate", "agent", "workflow", "unrelated-object"],
)
def test_the_roles_follow_the_template_kind(template_factory, expected):
    template = template_factory()
    registry = MagicMock()
    registry.get.return_value = template

    roles = TeamSelector(marketplace_registry=registry).select_from_template("t")

    assert roles == expected(template)


# --------------------------------------------------------------------------- processes


def _run(script: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "ARAGORA_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )


def test_importing_the_marketplace_does_not_load_the_debate_engine(tmp_path):
    result = _run(
        "import sys\nimport aragora.marketplace\nprint('aragora.debate' in sys.modules)\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-1] == "False"


def test_a_debate_only_process_reaches_the_marketplace_templates(tmp_path):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    result = _run(
        "import sys\n"
        "from aragora.debate.team_selector import TeamSelector\n"
        "assert not any(m.startswith('aragora.marketplace') for m in sys.modules), 'preloaded'\n"
        "print(','.join(TeamSelector().select_from_template('oxford-style')))\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    from aragora.marketplace.models import BUILTIN_DEBATE_TEMPLATES

    oxford = next(t for t in BUILTIN_DEBATE_TEMPLATES if t.metadata.id == "oxford-style")
    assert result.stdout.split()[-1] == ",".join(entry["role"] for entry in oxford.agent_roles)


# --------------------------------------------------------------------------- import sites


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        return [node.module or ""]
    return []


def _type_checking_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
            for child in node.body:
                lines.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
    return lines


@pytest.mark.parametrize(
    "relative", ["aragora/debate/team_selector.py", "aragora/debate/template_registry_hooks.py"]
)
def test_the_module_has_no_runtime_import_of_the_control_plane_or_marketplace(relative):
    tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
    annotation_only = _type_checking_lines(tree)
    offenders = [
        f"{relative}:{node.lineno}: {name}"
        for node in ast.walk(tree)
        if getattr(node, "lineno", None) not in annotation_only
        for name in _imported_names(node)
        for package in ("aragora.control_plane", "aragora.marketplace")
        if name == package or name.startswith(f"{package}.")
    ]
    assert offenders == []
