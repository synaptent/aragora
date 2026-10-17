"""Characterization of the distributed scheduler hook in ``aragora.agents.scheduler_protocol``.

``aragora.agents`` (domain layer) must not import ``aragora.control_plane`` (application
layer), whose ``TaskScheduler`` backs :class:`DistributedSchedulerAdapter`. The control
plane registers its scheduler through the ``aragora.distributed_schedulers`` entry point,
and the adapter maps the task status and priority enums it now reads from
``aragora.types.task_scheduling``.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.agents import scheduler_protocol as sp
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE_REGISTRATION = (
    "control_plane",
    "aragora.control_plane.scheduler_registration:register_distributed_scheduler",
)


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(sp, "_factory", None)
    monkeypatch.setattr(
        sp,
        "_declared_registrations",
        DeclaredRegistrations(
            sp.DISTRIBUTED_SCHEDULERS_ENTRY_POINT_GROUP,
            source_pyproject=tmp_path / "missing.toml",
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return sp


def _declare(monkeypatch, *registrations):
    entry_points = [
        SimpleNamespace(name=f"d{i}", value=f"tests.declared:d{i}", load=lambda fn=fn: fn)
        for i, fn in enumerate(registrations)
    ]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            entry_points if group == sp.DISTRIBUTED_SCHEDULERS_ENTRY_POINT_GROUP else []
        ),
    )


def test_an_unregistered_scheduler_raises(isolated_hook):
    with pytest.raises(
        sp.DistributedSchedulerNotRegisteredError, match="aragora.distributed_schedulers"
    ):
        sp.DistributedSchedulerAdapter()


def test_registering_again_replaces_the_factory(isolated_hook):
    first, second = object(), object()
    sp.register_distributed_scheduler_factory(lambda: first)
    sp.register_distributed_scheduler_factory(lambda: second)
    assert sp.DistributedSchedulerAdapter()._scheduler is second


def test_a_given_scheduler_skips_the_hook(isolated_hook):
    given = object()
    assert sp.DistributedSchedulerAdapter(scheduler=given)._scheduler is given  # type: ignore[arg-type]


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        sp.register_distributed_scheduler_factory(object)

    _declare(monkeypatch, register)

    first = sp.DistributedSchedulerAdapter()._scheduler
    assert sp.DistributedSchedulerAdapter()._scheduler is not first
    assert calls == ["register"]


def test_pyproject_declares_the_control_plane_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(
        sp.DISTRIBUTED_SCHEDULERS_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [CONTROL_PLANE_REGISTRATION]


def test_the_control_plane_registration_builds_the_pre_inversion_scheduler(isolated_hook):
    from aragora.control_plane.scheduler import TaskScheduler
    from aragora.control_plane.scheduler_registration import register_distributed_scheduler

    register_distributed_scheduler()
    register_distributed_scheduler()
    scheduler = sp.DistributedSchedulerAdapter()._scheduler

    assert type(scheduler) is TaskScheduler
    assert scheduler._redis_url == "redis://localhost:6379"


def test_the_registered_factory_reads_the_scheduler_class_at_call_time(isolated_hook, monkeypatch):
    from aragora.control_plane import scheduler as cp_scheduler
    from aragora.control_plane.scheduler_registration import register_distributed_scheduler

    class PatchedScheduler:
        pass

    register_distributed_scheduler()
    monkeypatch.setattr(cp_scheduler, "TaskScheduler", PatchedScheduler)
    assert type(sp.DistributedSchedulerAdapter()._scheduler) is PatchedScheduler


def _run(script: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    # get_scheduler lets this variable override the requested type.
    env.pop("ARAGORA_SCHEDULER_TYPE", None)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )


def test_the_control_plane_init_registers_without_the_declared_registrations():
    result = _run(
        "import aragora.control_plane\n"
        "from aragora.agents import scheduler_protocol as sp\n"
        "from aragora.control_plane import scheduler_registration as reg\n"
        "print(sp._factory is reg.build_distributed_scheduler, sp._declared_registrations.loaded)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["True", "False"]


def test_an_agents_only_process_reaches_the_control_plane_scheduler():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    result = _run(
        "import sys\n"
        "from aragora.agents.scheduler_protocol import SchedulerType, get_scheduler\n"
        "assert not any(m.startswith('aragora.control_plane') for m in sys.modules), 'preloaded'\n"
        "scheduler = get_scheduler(SchedulerType.DISTRIBUTED)._scheduler\n"
        "print(type(scheduler).__module__, type(scheduler).__name__)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["aragora.control_plane.scheduler", "TaskScheduler"]


def _imported_names(node: ast.AST, path: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return [node.module or ""]
        package = path.relative_to(REPO_ROOT).with_suffix("").parts[: -node.level]
        return [".".join(package + ((node.module,) if node.module else ()))]
    return []


def _type_checking_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
            for child in node.body:
                lines.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
    return lines


@pytest.mark.parametrize(
    "relative",
    ["aragora/agents/scheduler_protocol.py", "aragora/knowledge/mound/revalidation_scheduler.py"],
)
def test_the_module_has_no_runtime_import_of_the_control_plane(relative):
    path = REPO_ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    annotation_only = _type_checking_lines(tree)
    offenders = [
        f"{relative}:{node.lineno}: {name}"
        for node in ast.walk(tree)
        if getattr(node, "lineno", None) not in annotation_only
        for name in _imported_names(node, path)
        if name == "aragora.control_plane" or name.startswith("aragora.control_plane.")
    ]
    assert offenders == []
