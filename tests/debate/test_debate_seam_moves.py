"""Triage diagnostics, skill types and the workspace stores hook sit at or below the debate layer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aragora.debate import workspace_stores
from aragora.debate.workspace_stores import (
    WorkspaceStoresNotRegisteredError,
    get_workspace_stores,
    register_workspace_stores_factory,
)
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_inbox_triage_diagnostics_reexports_the_debate_module() -> None:
    import aragora.debate.triage_diagnostics as moved
    import aragora.inbox.triage_diagnostics as shim

    assert shim.__all__ == moved.__all__
    for name in moved.__all__:
        assert getattr(shim, name) is getattr(moved, name), name


def test_run_activated_through_inbox_path_receives_debate_records(tmp_path: Path) -> None:
    from aragora.debate.performance_monitor import _record_triage_perf_event
    from aragora.debate.phases.debate_rounds import _should_emit_slow_round_warning
    from aragora.debate.triage_diagnostics import get_active_triage_diagnostics as moved_get_active
    from aragora.inbox.triage_diagnostics import TriageRunDiagnostics

    assert _record_triage_perf_event(code="slow_round", summary="no run") is False
    diagnostics = TriageRunDiagnostics(
        profile="baseline",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    with diagnostics.activate():
        assert moved_get_active() is diagnostics
        assert _record_triage_perf_event(code="slow_round", summary="round 1 slow") is True
        assert _should_emit_slow_round_warning() is False

    assert _should_emit_slow_round_warning() is True
    assert [event.code for event in diagnostics._events] == ["slow_round"]


def test_skill_types_live_in_aragora_types() -> None:
    import aragora.skills
    import aragora.skills.base as shim
    import aragora.types.skills as moved

    assert shim.__all__ == moved.__all__
    for name in moved.__all__:
        assert getattr(shim, name) is getattr(moved, name), name
    for name in ("Skill", "SkillCapability", "SkillContext", "SkillResult", "SkillStatus"):
        assert getattr(aragora.skills, name) is getattr(moved, name), name

    caps = [moved.SkillCapability.EXTERNAL_API]
    assert shim.CapabilityLevel.from_capabilities(caps) is moved.CapabilityLevel.from_capabilities(
        caps
    )
    assert shim.SkillStatus("success") is moved.SkillStatus.SUCCESS


@pytest.fixture
def isolated_factory(monkeypatch: pytest.MonkeyPatch) -> DeclaredRegistrations:
    """No factory, and the declared registrations count as already run."""
    monkeypatch.setattr(workspace_stores, "_factory", None)
    declared = DeclaredRegistrations(workspace_stores.WORKSPACE_STORES_ENTRY_POINT_GROUP)
    monkeypatch.setattr(declared, "load", lambda: None)
    monkeypatch.setattr(workspace_stores, "_declared", declared)
    return declared


def test_unregistered_workspace_stores_raise(isolated_factory: DeclaredRegistrations) -> None:
    with pytest.raises(WorkspaceStoresNotRegisteredError, match="aragora.workspace_stores"):
        get_workspace_stores()


def test_registered_factory_receives_the_store_options(
    isolated_factory: DeclaredRegistrations,
) -> None:
    calls: list[dict] = []
    register_workspace_stores_factory(lambda **kwargs: calls.append(kwargs) or "first")
    register_workspace_stores_factory(lambda **kwargs: calls.append(kwargs) or "second")

    assert get_workspace_stores(bead_dir="/tmp/beads", auto_commit=True) == "second"
    assert calls == [{"bead_dir": "/tmp/beads", "git_enabled": True, "auto_commit": True}]


def test_first_lookup_runs_the_declared_stores_registration(
    isolated_factory: DeclaredRegistrations, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aragora.stores import CanonicalWorkspaceStores

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "aragora"\n'
        '[project.entry-points."aragora.workspace_stores"]\n'
        'stores = "aragora.stores.debate_registration:register_debate_workspace_stores"\n',
        encoding="utf-8",
    )
    declared = DeclaredRegistrations(
        workspace_stores.WORKSPACE_STORES_ENTRY_POINT_GROUP, source_pyproject=pyproject
    )
    monkeypatch.setattr(workspace_stores, "_declared", declared)

    stores = get_workspace_stores(bead_dir=str(tmp_path), git_enabled=False)

    assert declared.loaded
    assert isinstance(stores, CanonicalWorkspaceStores)
    assert (stores.bead_dir, stores.git_enabled, stores.auto_commit) == (
        str(tmp_path),
        False,
        False,
    )


async def test_bead_store_resolution_goes_through_the_hook(
    isolated_factory: DeclaredRegistrations,
) -> None:
    from aragora.debate.orchestrator_hooks import _resolve_bead_store

    bead_store = object()
    calls: list[dict] = []

    def factory(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(bead_store=AsyncMock(return_value=bead_store))

    register_workspace_stores_factory(factory)
    holder = SimpleNamespace()
    env = SimpleNamespace(context={"bead_dir": "/tmp/beads"})
    protocol = SimpleNamespace(bead_auto_commit=True)

    assert await _resolve_bead_store(protocol, env, holder) is bead_store
    assert await _resolve_bead_store(protocol, env, holder) is bead_store
    assert calls == [{"bead_dir": "/tmp/beads", "git_enabled": True, "auto_commit": True}]


def test_importing_stores_does_not_load_the_debate_engine() -> None:
    code = (
        "import sys, aragora.stores\n"
        "assert 'aragora.debate' not in sys.modules, 'aragora.stores imported aragora.debate'\n"
        "print('LIGHT')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300
    )
    assert proc.returncode == 0, proc.stderr
    assert "LIGHT" in proc.stdout
