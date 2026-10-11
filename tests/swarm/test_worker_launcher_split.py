"""WorkerLauncher keeps its import path while command and git helpers live in mixins."""

from __future__ import annotations

import inspect

from aragora.swarm import worker_launcher, worker_launcher_command
from aragora.swarm.worker_launcher import WorkerLauncher
from aragora.swarm.worker_launcher_command import WorkerLauncherCommandMixin
from aragora.swarm.worker_launcher_git import WorkerLauncherGitMixin

MIXINS = (WorkerLauncherCommandMixin, WorkerLauncherGitMixin)


def test_worker_launcher_inherits_the_helper_mixins() -> None:
    for mixin in MIXINS:
        assert issubclass(WorkerLauncher, mixin)
    assert "_build_agent_command" in vars(WorkerLauncherCommandMixin)
    assert "_enrich_task_context" in vars(WorkerLauncherCommandMixin)
    assert "_collect_changed_paths" in vars(WorkerLauncherGitMixin)


def test_moved_helpers_resolve_from_the_mixins_only() -> None:
    for mixin in MIXINS:
        moved = [name for name in vars(mixin) if name.startswith("_") and name[1] != "_"]
        assert moved
        for name in moved:
            assert name not in vars(WorkerLauncher), name
            assert inspect.getattr_static(WorkerLauncher, name) is vars(mixin)[name]


def test_facade_logger_name_and_helper_calls_are_unchanged() -> None:
    assert worker_launcher_command.logger.name == "aragora.swarm.worker_launcher"
    assert worker_launcher.logger.name == "aragora.swarm.worker_launcher"
    assert WorkerLauncher._strip_session_artifacts({"b.py", "a.py"}) == ["a.py", "b.py"]
    assert WorkerLauncher._resolve_worktree_gitdir("") == ""
