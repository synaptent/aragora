"""The debate engine reaches the nomic loop through ``aragora.debate.nomic_backends``.

``aragora.debate`` (domain layer) must not import ``aragora.nomic`` (application layer) at
runtime. The nomic package registers its backend through the ``aragora.debate_nomic_backends``
entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.debate import nomic_backends as hook
from aragora.debate import orchestrator_hooks
from aragora.debate.phases.feedback_phase import FeedbackPhase
from aragora.debate.post_debate_config import PostDebateConfig
from aragora.debate.post_debate_coordinator import PostDebateCoordinator
from aragora.debate.protocol_resolver import resolve_default_protocol
from aragora.debate.service import DebateOptions
from aragora.protocols.debate import DebateProtocol
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
NOMIC_REGISTRATION = ("nomic", "aragora.nomic.debate_registration:register_debate_nomic_backend")
FLIPPED_MODULES = (
    "aragora/debate/codebase_context.py",
    "aragora/debate/execution_bridge.py",
    "aragora/debate/orchestrator_hooks.py",
    "aragora/debate/phases/feedback_phase.py",
    "aragora/debate/post_debate_coordinator.py",
    "aragora/debate/protocol_resolver.py",
    "aragora/debate/service.py",
)


class FakeBead:
    created: list[dict] = []

    @classmethod
    def create(cls, **fields):
        cls.created.append(fields)
        return SimpleNamespace(**fields)


class FakeBeadPriority:
    HIGH, NORMAL, LOW = "high", "normal", "low"


class FakeBeadStatus:
    COMPLETED, FAILED, PENDING = "completed", "failed", "pending"


class FakeBeadType:
    DEBATE_DECISION = "debate_decision"


class FakeBeadStore:
    def __init__(self, bead=None):
        self.bead = bead
        self.created = []
        self.statuses = []

    async def create(self, bead):
        self.created.append(bead)
        return "bead-0123456789"

    async def get(self, bead_id):
        return self.bead

    async def update_status(self, bead_id, status):
        self.statuses.append((bead_id, status))


class FakeQueue:
    def __init__(self):
        self.pushed = []

    async def push(self, bead_id, priority, max_attempts):
        self.pushed.append(bead_id)
        return SimpleNamespace(id=f"entry-{bead_id}")


class FakeHookQueueRegistry:
    recovered: dict = {}

    def __init__(self, bead_store):
        self.bead_store = bead_store
        self.queues: dict[str, FakeQueue] = {}

    async def get_queue(self, agent_id):
        return self.queues.setdefault(agent_id, FakeQueue())

    async def recover_all(self):
        return self.recovered


class FakeBridge:
    calls: list[str] = []

    def queue_improvement_suggestions(self):
        self.calls.append("queue")
        return 2

    def run_feedback_cycle(self):
        self.calls.append("cycle")
        return {"goals_generated": 0, "suggestions_queued": 0}


class FakeProfile:
    rounds = 7
    consensus_mode = "supermajority"

    @classmethod
    def from_env(cls):
        return cls()

    def to_protocol(self):
        return DebateProtocol(rounds=self.rounds, consensus=self.consensus_mode)


class FakeOutcomeTracker:
    pass


class RecordingBackend:
    def bead_classes(self):
        return FakeBead, FakeBeadPriority, FakeBeadStatus, FakeBeadType

    def hook_queue_registry(self):
        return FakeHookQueueRegistry

    def outcome_feedback_bridge(self):
        return FakeBridge

    def debate_profile(self):
        return FakeProfile

    def outcome_tracker(self):
        return FakeOutcomeTracker


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_backend", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.NOMIC_BACKENDS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    FakeBead.created = []
    FakeBridge.calls = []
    FakeHookQueueRegistry.recovered = {}
    return hook


def _result():
    return SimpleNamespace(
        debate_id="debate-0123456789",
        task="the task",
        final_answer="Ship it",
        confidence=0.95,
        consensus_reached=True,
        rounds_used=2,
        participants=["a1"],
        winner="a1",
        status="completed",
    )


def _protocol(**flags):
    return SimpleNamespace(bead_min_confidence=0.5, **flags)


def _feedback_ctx():
    protocol = SimpleNamespace(post_debate_config=PostDebateConfig(auto_outcome_feedback=True))
    return SimpleNamespace(protocol=protocol, debate_id="d1")


def test_an_unregistered_backend_raises(isolated_hook):
    with pytest.raises(hook.NomicBackendNotRegisteredError, match="aragora.debate_nomic_backends"):
        hook.nomic_backend()


@pytest.mark.asyncio
async def test_without_a_backend_the_bead_and_hook_sites_degrade(isolated_hook):
    store = FakeBeadStore(bead=SimpleNamespace(metadata={}))
    holder = SimpleNamespace(_bead_store=store)
    agents = [SimpleNamespace(name="a1")]
    protocol = _protocol(enable_bead_tracking=True, enable_hook_tracking=True)

    assert await orchestrator_hooks.create_debate_bead(_result(), protocol, None, holder) is None
    pending = await orchestrator_hooks.create_pending_debate_bead(
        "debate-0123456789", "the task", protocol, None, agents, holder
    )
    assert pending is None
    await orchestrator_hooks.update_debate_bead("bead-0123456789", _result(), True, holder)
    assert store.statuses == []
    hooks = await orchestrator_hooks.init_hook_tracking(
        "debate-0123456789", "bead-0123456789", protocol, agents, holder
    )
    assert hooks == {}
    assert await orchestrator_hooks.recover_pending_debates(bead_store=store) == []
    assert store.created == []


def test_without_a_backend_the_feedback_and_profile_sites_degrade(isolated_hook, monkeypatch):
    FeedbackPhase()._queue_outcome_feedback(_feedback_ctx())
    assert PostDebateCoordinator()._step_outcome_feedback("d1") is None

    monkeypatch.delenv("ARAGORA_DEBATE_PROFILE", raising=False)
    default_options = DebateOptions()
    monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", "nomic")
    assert resolve_default_protocol().rounds == DebateProtocol().rounds
    options = DebateOptions()
    assert (options.rounds, options.consensus) == (
        default_options.rounds,
        default_options.consensus,
    )


@pytest.mark.asyncio
async def test_the_bead_and_hook_sites_use_the_backend(isolated_hook):
    hook.register_nomic_backend(RecordingBackend())
    store = FakeBeadStore(bead=SimpleNamespace(metadata={}))
    holder = SimpleNamespace(_bead_store=store)
    agents = [SimpleNamespace(name="a1")]
    protocol = _protocol(enable_bead_tracking=True, enable_hook_tracking=True)

    bead_id = await orchestrator_hooks.create_debate_bead(_result(), protocol, None, holder)
    assert bead_id == "bead-0123456789"
    assert FakeBead.created[-1]["bead_type"] == FakeBeadType.DEBATE_DECISION
    assert FakeBead.created[-1]["priority"] == FakeBeadPriority.HIGH

    pending = await orchestrator_hooks.create_pending_debate_bead(
        "debate-0123456789", "the task", protocol, None, agents, holder
    )
    assert pending == "bead-0123456789"
    assert FakeBead.created[-1]["priority"] == FakeBeadPriority.NORMAL

    await orchestrator_hooks.update_debate_bead("bead-0123456789", _result(), False, holder)
    assert store.statuses == [("bead-0123456789", FakeBeadStatus.FAILED)]

    hooks = await orchestrator_hooks.init_hook_tracking(
        "debate-0123456789", "bead-0123456789", protocol, agents, holder
    )
    assert hooks == {"a1": "entry-bead-0123456789"}
    assert isinstance(holder._hook_registry, FakeHookQueueRegistry)


@pytest.mark.asyncio
async def test_recovery_uses_the_backend(isolated_hook):
    hook.register_nomic_backend(RecordingBackend())
    now = datetime.now(timezone.utc)
    live = SimpleNamespace(
        id="bead-live-0001",
        bead_type=FakeBeadType.DEBATE_DECISION,
        status=FakeBeadStatus.PENDING,
        created_at=now,
        metadata={"debate_id": "debate-1"},
    )
    done = SimpleNamespace(
        id="bead-done-0001",
        bead_type=FakeBeadType.DEBATE_DECISION,
        status=FakeBeadStatus.COMPLETED,
        created_at=now,
        metadata={"debate_id": "debate-2"},
    )
    FakeHookQueueRegistry.recovered = {"a1": [live, done]}

    recovered = await orchestrator_hooks.recover_pending_debates(bead_store=FakeBeadStore())
    assert [(r["debate_id"], r["agents"]) for r in recovered] == [("debate-1", ["a1"])]


def test_the_feedback_and_profile_sites_use_the_backend(isolated_hook, monkeypatch):
    hook.register_nomic_backend(RecordingBackend())
    FeedbackPhase()._queue_outcome_feedback(_feedback_ctx())
    assert PostDebateCoordinator()._step_outcome_feedback("d1") == {
        "goals_generated": 0,
        "suggestions_queued": 0,
    }
    assert FakeBridge.calls == ["queue", "cycle"]

    monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", "full")
    protocol = resolve_default_protocol()
    assert (protocol.rounds, protocol.consensus) == (7, "supermajority")
    options = DebateOptions()
    assert (options.rounds, options.consensus) == (7, "supermajority")


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_nomic_backend(RecordingBackend())

    entry_point = SimpleNamespace(name="n0", value="tests.declared:n0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.NOMIC_BACKENDS_ENTRY_POINT_GROUP else [],
    )
    assert hook.nomic_backend() is hook.nomic_backend()
    assert calls == ["register"]


def test_pyproject_declares_the_nomic_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.NOMIC_BACKENDS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [NOMIC_REGISTRATION]


def test_the_registered_backend_returns_the_nomic_objects(isolated_hook):
    from aragora.nomic import beads
    from aragora.nomic.debate_profile import NomicDebateProfile
    from aragora.nomic.debate_registration import register_debate_nomic_backend
    from aragora.nomic.hook_queue import HookQueueRegistry
    from aragora.nomic.outcome_feedback import OutcomeFeedbackBridge
    from aragora.nomic.outcome_tracker import NomicOutcomeTracker

    register_debate_nomic_backend()
    backend = hook.nomic_backend()
    assert backend.bead_classes() == (
        beads.Bead,
        beads.BeadPriority,
        beads.BeadStatus,
        beads.BeadType,
    )
    assert backend.hook_queue_registry() is HookQueueRegistry
    assert backend.outcome_feedback_bridge() is OutcomeFeedbackBridge
    assert backend.debate_profile() is NomicDebateProfile
    assert backend.outcome_tracker() is NomicOutcomeTracker


def test_the_registered_backend_reads_nomic_at_call_time(isolated_hook, monkeypatch):
    from aragora.nomic import outcome_feedback
    from aragora.nomic.debate_registration import register_debate_nomic_backend

    register_debate_nomic_backend()
    replacement = object()
    monkeypatch.setattr(outcome_feedback, "OutcomeFeedbackBridge", replacement)
    assert hook.nomic_backend().outcome_feedback_bridge() is replacement

    monkeypatch.setitem(sys.modules, "aragora.nomic.debate_profile", None)
    with pytest.raises(ImportError):
        hook.nomic_backend().debate_profile()


def test_a_debate_only_process_reaches_the_nomic_backend():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "import aragora.debate.orchestrator_hooks\n"
        "loaded_before = 'aragora.nomic' in sys.modules\n"
        "from aragora.debate.nomic_backends import nomic_backend\n"
        "backend = nomic_backend()\n"
        "print(loaded_before, type(backend).__module__, type(backend).__name__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-3:] == [
        "False",
        "aragora.nomic.debate_registration",
        "NomicDebateBackend",
    ]


def _runtime_imports(tree):
    """Absolute imports outside ``if TYPE_CHECKING:`` blocks."""
    type_only = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            type_only.update(id(child) for stmt in node.body for child in ast.walk(stmt))
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


@pytest.mark.parametrize("relative_path", FLIPPED_MODULES)
def test_flipped_modules_hold_no_runtime_import_of_nomic(relative_path):
    tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    offenders = [
        f"{relative_path}:{line}: {name}"
        for line, name in _runtime_imports(tree)
        if name == "aragora.nomic" or name.startswith("aragora.nomic.")
    ]
    assert offenders == []
