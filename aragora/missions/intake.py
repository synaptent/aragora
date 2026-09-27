"""Intake bridge — turn a seeded mission-intake feature into dispatchable work.

``aragora mission seed --goal "..."`` creates a single intake feature with no
``metadata.branch``. :class:`~aragora.missions.dispatch.BossLoopDispatch`
(correctly) refuses to drive such a feature — the merge gate needs a live
branch — so before this bridge a freshly seeded mission parked forever (#8758).

:class:`IntakeBridgeDispatch` wraps any inner ``Dispatch``. When the picked
feature is intake-shaped it decomposes the goal via the existing nomic
:class:`~aragora.nomic.task_decomposer.TaskDecomposer` (heuristic by default —
its LLM paths are key-gated and fall through silently, so no API keys are
required) into 1+ child Features. The children ride back through the
orchestrator's own propose/accept handoff triage (``follow_ups`` +
``accept_follow_ups=True``), so no new state-mutation path is introduced:
triage inserts the children, completes the intake (non-terminal), and folds
the provenance note into ``notes``. Child ids derive from subtask content
(never list position), so a crash-retried decomposition converges on the same
ids and triage's duplicate check makes the re-tick a no-op.

Children do **not** carry a fabricated ``metadata.branch`` — the merge gate
rev-parses that value, and a branch nobody has created yet would turn every
follow-up tick into a crash/retry loop mislabeled as a poison dispatch. They
instead carry a deterministic ``metadata.branch_hint`` a worker should adopt
when it claims the unit, and are born in :data:`Status.AWAITING_CLAIM` — the
first-class claimable-wait state: ``ledger.select_for`` claims it exactly like
PENDING, while the orchestrator never dispatches it (there is nothing the
merge gate can do without a branch), so an auto-drain run leaves every child
claimable with zero retry-counter burn and zero BLOCKED children. A child
that is nevertheless PENDING without a branch (hand-reset state, pre-fix
state file) is triaged back to AWAITING_CLAIM via the non-failure
``Handoff.awaiting_claim`` disposition — an accurate "awaiting worker
claim/branch creation" note, zero git subprocesses, no retry accounting.
Once a live ``metadata.branch`` is recorded, the child flows through to the
inner dispatch and the merge gate as before.

Failure to decompose parks the intake **non-terminally** (#8758 design
decision): the feature moves to the retryable, reconciler-owned
``Status.PARKED`` with ``parked_reason``/``parked_at`` recorded — a raising
decomposer is a transient provider failure, so each reconciler tick releases
the park for a bounded retry (``retry_count`` → ``Status.TERMINAL`` after
``max_retries`` attempts, default 3) and it never crashes the tick loop. Only
a blank goal, which no retry can fix, is terminal immediately. The bridge is
default-ON for auto-drain and only ever activates on
intake-shaped or intake-derived features (i.e. freshly seeded missions); the
``ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE=1`` kill-switch restores the previous
park-on-intake behavior.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .handoff import Dispatch, Handoff
from .state import PARK_KIND_DECOMPOSITION, Feature, Status

if TYPE_CHECKING:
    from aragora.nomic.task_decomposer import SubTask

logger = logging.getLogger(__name__)

INTAKE_FEATURE_ID = "mission-intake"
INTAKE_KIND = "intake"
DISABLE_ENV = "ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE"

# (goal, path allowlist hints) -> subtasks. Injectable for tests/alternate planners.
Decompose = Callable[[str, list[str]], "list[SubTask]"]


def is_intake_feature(feature: Feature) -> bool:
    """True iff ``feature`` is seed-shaped work awaiting decomposition.

    Intake = no live ``metadata.branch`` AND explicitly marked as intake
    (the seeded ``mission-intake`` id, or a ``metadata.kind == "intake"``
    marker). A branch-backed feature is never intake, whatever its id.
    """
    if _has_live_branch(feature):
        return False
    if feature.metadata.get("kind") == INTAKE_KIND:
        return True
    return feature.id == INTAKE_FEATURE_ID


def intake_bridge_enabled() -> bool:
    """Default ON; ``ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE=1`` opts out."""
    return os.environ.get(DISABLE_ENV, "").strip().lower() not in {"1", "true", "yes"}


class IntakeBridgeDispatch:
    """Dispatch wrapper: decompose intake features, delegate everything else.

    Composes existing primitives only: ``TaskDecomposer`` produces subtasks,
    and the orchestrator's handoff triage (``accept_follow_ups``) inserts the
    children and completes the intake. Provenance (which decomposer, when,
    child ids) travels on the children's metadata and the intake's notes.

    A decomposed child without a live ``metadata.branch`` never reaches the
    inner dispatch: the live merge gate would rev-parse a branch that does not
    exist yet, and the resulting raise would be miscounted as a crash-looping
    poison dispatch. Children are born in the claimable ``AWAITING_CLAIM``
    state; if one is dispatched anyway (hand-reset to PENDING), it is triaged
    back there via ``Handoff.awaiting_claim`` — never retried toward BLOCKED.
    """

    def __init__(
        self,
        inner: Dispatch,
        *,
        decompose: Decompose | None = None,
        max_children: int = 5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.inner = inner
        self.max_children = max_children
        self.clock = clock
        if decompose is None:
            self._decompose: Decompose = _task_decomposer_decompose
            self.decomposer_name = "nomic.TaskDecomposer.analyze"
        else:
            self._decompose = decompose
            self.decomposer_name = getattr(decompose, "__qualname__", repr(decompose))

    def __call__(self, feature: Feature) -> Handoff:
        if is_intake_feature(feature):
            return self._decompose_intake(feature)
        if _awaiting_live_branch(feature):
            # Claimable park: this is worker-bound work, not a failure — the
            # awaiting_claim disposition moves it to Status.AWAITING_CLAIM
            # (claimable by select_for) with no retry accounting, so it can
            # never age into BLOCKED while waiting. No git is touched.
            hint = feature.metadata.get("branch_hint")
            return Handoff(
                success=False,
                awaiting_claim=True,
                blocked_reason=(
                    f"decomposed feature {feature.id} is awaiting worker claim/branch "
                    "creation; no live metadata.branch yet"
                    + (f" (suggested branch_hint: {hint})" if hint else "")
                ),
            )
        return self.inner(feature)

    # ---- intake decomposition ---------------------------------------------------

    def _decompose_intake(self, feature: Feature) -> Handoff:
        goal = feature.description.strip()
        if not goal:
            # Permanent decomposition failure: no retry fixes a blank goal.
            # parked_kind routes triage to TERMINAL (#8758 design decision).
            return Handoff(
                success=False,
                terminal=True,
                parked_kind=PARK_KIND_DECOMPOSITION,
                blocked_reason="intake feature has no goal/description to decompose",
                discovered=[f"intake feature {feature.id} arrived with a blank goal"],
            )

        paths = _path_hints(feature)
        try:
            all_subtasks = list(self._decompose(goal, paths))
            subtasks = all_subtasks[: self.max_children]
        except Exception as exc:  # noqa: BLE001 - decomposer is an external boundary; park, never crash the tick loop
            logger.exception("intake decomposition failed for feature %s", feature.id)
            # NON-terminal park (#8758 design decision): a raising decomposer is
            # a transient provider failure — the feature moves to the retryable
            # PARKED state (parked_reason/parked_at recorded) and the reconciler
            # releases it each tick for a bounded retry; after max_retries
            # failed attempts triage marks it TERMINAL.
            return Handoff(
                success=False,
                parked=True,
                parked_kind=PARK_KIND_DECOMPOSITION,
                blocked_reason=f"intake decomposition failed: {exc}",
                discovered=[f"intake feature {feature.id} parked: {self.decomposer_name} raised"],
            )

        selected_ids = {subtask.id for subtask in subtasks}
        truncated_ids = {subtask.id for subtask in all_subtasks} - selected_ids
        broken_dependencies = sorted(
            {
                dependency
                for subtask in subtasks
                for dependency in subtask.dependencies
                if dependency in truncated_ids
            }
        )
        if broken_dependencies:
            return Handoff(
                success=False,
                terminal=True,
                parked_kind=PARK_KIND_DECOMPOSITION,
                blocked_reason=(
                    "max_children truncation would remove required dependencies: "
                    + ", ".join(broken_dependencies)
                ),
            )

        children = self._child_features(feature, subtasks)
        discovered = []
        if len(all_subtasks) > len(subtasks):
            discovered.append(
                f"intake decomposition truncated from {len(all_subtasks)} to "
                f"{len(subtasks)} child feature(s) by max_children={self.max_children}"
            )
        note = (
            f"intake decomposed via {self.decomposer_name} into "
            f"{len(children)} feature(s): {', '.join(c.id for c in children)}"
        )
        discovered.append(note)
        logger.info("feature %s: %s", feature.id, note)
        return Handoff(
            success=True,
            follow_ups=children,
            accept_follow_ups=True,
            discovered=discovered,
        )

    # ---- child construction ---------------------------------------------------

    def _child_features(self, intake: Feature, subtasks: list[SubTask]) -> list[Feature]:
        """Deterministic children, born AWAITING_CLAIM for the lease machinery.

        Awaiting-claim (not PENDING) from birth: the orchestrator has nothing to
        dispatch until a worker records a branch, so the children sit directly in
        the claimable-wait state — auto-drain leaves them for ``select_for`` with
        zero retry burn. An empty decomposition means the goal is a bounded,
        single-unit change — mirror it into one child rather than parking a
        perfectly workable goal.
        """
        if not subtasks:
            return [self._mirrored_child(intake)]

        decomposed_at = self.clock()
        child_ids = _assign_child_ids(intake.id, subtasks)

        children: list[Feature] = []
        seen: set[str] = set()
        for subtask in subtasks:
            child_id = child_ids[subtask.id]
            if child_id in seen:  # exact-content duplicate: same work, one child
                continue
            seen.add(child_id)
            preconditions = sorted(
                {
                    f"feature:{child_ids[dep]}"
                    for dep in subtask.dependencies
                    if dep in child_ids and child_ids[dep] != child_id
                }
            )
            metadata = self._child_metadata(intake, child_id, decomposed_at)
            if subtask.file_scope:
                metadata["paths"] = sorted(set(subtask.file_scope))
            description = subtask.description.strip() or subtask.title.strip() or intake.description
            children.append(
                Feature(
                    id=child_id,
                    description=description,
                    milestone=intake.milestone,
                    skill=intake.skill,
                    status=Status.AWAITING_CLAIM,
                    preconditions=preconditions,
                    metadata=metadata,
                )
            )
        return children

    def _mirrored_child(self, intake: Feature) -> Feature:
        child_id = f"{intake.id}-{_slug(intake.description)}"
        return Feature(
            id=child_id,
            description=intake.description.strip(),
            milestone=intake.milestone,
            skill=intake.skill,
            status=Status.AWAITING_CLAIM,
            metadata=self._child_metadata(intake, child_id, self.clock()),
        )

    def _child_metadata(
        self, intake: Feature, child_id: str, decomposed_at: float
    ) -> dict[str, Any]:
        metadata = {k: v for k, v in intake.metadata.items() if k != "kind"}
        metadata.update(
            # NOT "branch": the merge gate rev-parses that value. The hint is
            # the deterministic name a worker should adopt when it does the work.
            branch_hint=f"mission/{child_id}",
            intake_parent=intake.id,
            decomposer=self.decomposer_name,
            decomposed_at=decomposed_at,
        )
        return metadata


def _assign_child_ids(intake_id: str, subtasks: list[SubTask]) -> dict[str, str]:
    """subtask.id -> child feature id; stable under subtask reordering.

    Ids derive from slugged titles. When several subtasks share a slug, every
    member of that group gets a content-derived suffix (never a positional
    one), so a crash-retried decomposition that returns the same subtasks in a
    different order still converges on identical ids. Exact-content duplicates
    within a group intentionally share one id (collapsed by the caller).
    """
    groups: dict[str, list[SubTask]] = {}
    for subtask in subtasks:
        base = f"{intake_id}-{_slug(subtask.title or subtask.id)}"
        groups.setdefault(base, []).append(subtask)

    child_ids: dict[str, str] = {}
    for base, group in groups.items():
        distinct = {_content_digest(s) for s in group}
        for subtask in group:
            child_ids[subtask.id] = (
                base if len(distinct) == 1 else f"{base}-{_content_digest(subtask)}"
            )
    return child_ids


def _content_digest(subtask: SubTask) -> str:
    payload = "\n".join([subtask.title, subtask.description, *sorted(subtask.file_scope)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def _task_decomposer_decompose(goal: str, paths: list[str]) -> list[SubTask]:
    """Default planner: the existing nomic TaskDecomposer.

    Heuristic by default — its LLM extraction paths are key-gated and return
    empty when no provider is configured, so this never *requires* API keys.
    Imported lazily so the missions spine stays importable without the nomic
    extras loaded.
    """
    from aragora.nomic.task_decomposer import TaskDecomposer

    result = TaskDecomposer().analyze(goal, file_scope_hints=paths or None)
    return list(result.subtasks)


def _has_live_branch(feature: Feature) -> bool:
    branch = feature.metadata.get("branch")
    return isinstance(branch, str) and bool(branch.strip())


def _awaiting_live_branch(feature: Feature) -> bool:
    """True iff ``feature`` is a decomposed child with no live branch yet."""
    return feature.metadata.get("intake_parent") is not None and not _has_live_branch(feature)


def _path_hints(feature: Feature) -> list[str]:
    raw = feature.metadata.get("paths")
    if not isinstance(raw, list):
        return []
    return [str(p).strip() for p in raw if str(p).strip()]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48].rstrip("-") or "work"
