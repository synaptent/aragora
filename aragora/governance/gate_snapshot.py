"""One immutable capture of a PR's head *and* its check verdict (#9873).

Why this type exists
--------------------
A merge may only land the exact head whose required checks produced the verdict
authorizing it. #9677 spent nine review rounds failing to achieve that by passing
a SHA around, and the failure was always the same shape:

* pass ``""`` and call it strict — an armed halt becomes unwaivable
* thread ``head_sha`` per call site — fixes one caller, leaves the rest unbound
* resolve the head inside the merge function — pairs a *stale* verdict with a
  *fresh* commit, which is the exact TOCTOU the rule forbids

The third was attempted twice and reverted twice. The lesson: **exact-head
binding is an ordering property, not a plumbing property.** No amount of careful
parameter passing fixes a head that was read after classification.

So the head stops being a parameter. ``GateSnapshot`` is captured in a single
GitHub read and is frozen; a merge takes the snapshot, never a naked SHA. Two
consequences fall out structurally rather than by convention:

* **You cannot build a snapshot without a full head.** ``__post_init__``
  rejects anything that is not 40 hex characters, so "refuse when the head is
  missing" is not a check a caller can forget — there is no valid object to
  merge with.
* **You cannot re-resolve.** The type exposes no setter and no refresh, so the
  "resolve a fresh head at merge time" mistake has no API to make.

A race between capture and merge is not prevented here — it cannot be, locally.
It is made *safe*: the merge pins ``--match-head-commit`` to the captured head,
so GitHub itself refuses when the head has moved. That refusal is the point.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from aragora.swarm.merge_halt import evaluate_merge_halt

_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_REPO_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

# mergeStateStatus values under which GitHub reports every protection requirement as met.
# Any other value (BLOCKED, BEHIND, DIRTY, UNSTABLE, UNKNOWN, absent) means ``--admin`` would
# override something this snapshot never verified, such as a required review.
_ADMIN_MERGEABLE_STATES = frozenset({"CLEAN", "HAS_HOOKS"})

# One read. Adding a second call here would reintroduce the split that this type
# exists to prevent: the head and the verdict must come from the same response.
_SNAPSHOT_FIELDS = (
    "number",
    "headRefOid",
    "headRefName",
    "baseRefName",
    "state",
    "isDraft",
    "mergeStateStatus",
    "statusCheckRollup",
)


class GateSnapshotError(RuntimeError):
    """The gate could not be captured, or was captured without a usable head."""


class MergeRefused(RuntimeError):
    """A merge was attempted without a valid captured head, and was refused."""


class CommandRunner(Protocol):
    def __call__(
        self, args: list[str], *, timeout: float = ...
    ) -> subprocess.CompletedProcess[str]: ...


def _require_repo_slug(repo: Any) -> str:
    """Return ``repo`` as an ``owner/name`` slug, or raise before it reaches gh."""
    slug = str(repo or "").strip()
    if not _REPO_SLUG.fullmatch(slug):
        raise GateSnapshotError(f"expected an owner/name repository, got {repo!r}")
    return slug


@dataclass(frozen=True)
class GateSnapshot:
    """A PR's head and check verdict, captured together and never mutated.

    ``frozen=True`` is load-bearing, not stylistic: it is what stops a caller
    from "refreshing" the head after classification.
    """

    pr_number: int
    repo: str
    head_sha: str
    required_checks_green: bool
    checks_known: bool
    state: str
    is_draft: bool
    merge_state_status: str | None
    captured_at: str

    def __post_init__(self) -> None:
        head = str(self.head_sha or "").strip().lower()
        if not _FULL_SHA.fullmatch(head):
            raise GateSnapshotError(
                f"GateSnapshot requires a full 40-character head SHA, got {self.head_sha!r}. "
                "A snapshot without a head cannot authorize a merge (#9873)."
            )
        # Normalise through object.__setattr__ because the dataclass is frozen.
        object.__setattr__(self, "head_sha", head)
        object.__setattr__(self, "repo", _require_repo_slug(self.repo))

    @property
    def mergeable_now(self) -> bool:
        """Whether this capture authorizes a merge at all."""
        return (
            self.state.upper() == "OPEN"
            and not self.is_draft
            and self.checks_known
            and self.required_checks_green
        )

    def match_head_args(self) -> list[str]:
        """The only sanctioned way to pin a merge, using the captured head."""
        return ["--match-head-commit", self.head_sha]


def _default_runner(args: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)


def _rollup_verdict(rollup: Any) -> tuple[bool, bool]:
    """Return (all_green, known). Unknown beats green — an empty rollup is not a pass."""
    if not isinstance(rollup, list) or not rollup:
        return (False, False)
    for item in rollup:
        if not isinstance(item, dict):
            return (False, False)
        status = str(item.get("status") or "").upper()
        # Commit statuses ({context, state}) share the rollup with check runs and carry no conclusion.
        conclusion = str(item.get("conclusion") or item.get("state") or "").upper()
        if status and status != "COMPLETED":
            return (False, True)
        if conclusion not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            return (False, True)
    return (True, True)


def capture_gate_snapshot(
    pr_number: int,
    repo: str,
    *,
    runner: CommandRunner | None = None,
    timeout: float = 30.0,
    now: dt.datetime | None = None,
) -> GateSnapshot:
    """Read a PR's head and checks in ONE call and freeze them together.

    Raises ``GateSnapshotError`` rather than returning a partial snapshot: a
    capture that failed must not be mistaken for a capture that said "no head".
    """
    repo = _require_repo_slug(repo)
    run = runner or _default_runner
    result = run(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            ",".join(_SNAPSHOT_FIELDS),
        ],
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "unknown gh error"
        raise GateSnapshotError(f"could not capture gate for PR #{pr_number}: {detail}")
    try:
        payload = json.loads(result.stdout or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        raise GateSnapshotError(f"gh returned invalid JSON for PR #{pr_number}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateSnapshotError(f"unexpected gh payload for PR #{pr_number}")

    raw_number = payload.get("number") or pr_number
    try:
        number = int(raw_number)
    except (TypeError, ValueError) as exc:
        raise GateSnapshotError(
            f"gh returned a non-integer number {raw_number!r} for PR #{pr_number}"
        ) from exc

    green, known = _rollup_verdict(payload.get("statusCheckRollup"))
    stamp = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    # GateSnapshot.__post_init__ raises if headRefOid was absent or malformed,
    # which is exactly the refusal this issue asks for.
    return GateSnapshot(
        pr_number=number,
        repo=repo,
        head_sha=str(payload.get("headRefOid") or ""),
        required_checks_green=green,
        checks_known=known,
        state=str(payload.get("state") or ""),
        is_draft=bool(payload.get("isDraft", False)),
        merge_state_status=(
            str(payload["mergeStateStatus"]) if payload.get("mergeStateStatus") else None
        ),
        captured_at=stamp,
    )


def require_snapshot(
    snapshot: GateSnapshot | None, *, pr_number: int | None = None
) -> GateSnapshot:
    """Refuse a merge that has no captured head.

    Call sites that still accept an optional snapshot funnel through here so the
    refusal is one behaviour in one place, not a condition each caller re-invents.
    """
    if snapshot is None:
        raise MergeRefused(
            f"refusing to merge PR #{pr_number if pr_number is not None else '?'} without a "
            "captured gate snapshot: the head its checks verified is unknown (#9873)."
        )
    return snapshot


@dataclass(frozen=True)
class MergeOutcome:
    merged: bool
    action: str
    detail: str
    head_sha: str | None = None


def merge_with_snapshot(
    snapshot: GateSnapshot | None,
    *,
    squash: bool = True,
    admin: bool = False,
    delete_branch: bool = False,
    runner: CommandRunner | None = None,
    timeout: float = 30.0,
) -> MergeOutcome:
    """Merge a PR bound to the head its checks verified.

    Takes the snapshot, never a bare SHA: there is no parameter here that a
    caller could fill with a freshly-resolved head. ``--match-head-commit`` is
    always the captured head, so if the PR moved after capture GitHub rejects
    the merge and that rejection is returned rather than retried. While the
    main-red merge halt (#9216) blocks the captured head, nothing is run.
    ``admin=True`` runs only when the captured ``mergeStateStatus`` says GitHub
    already considers the PR mergeable, so ``--admin`` never overrides a
    protection requirement the snapshot did not verify.
    """
    snap = require_snapshot(snapshot)
    if not snap.mergeable_now:
        return MergeOutcome(
            merged=False,
            action="blocked",
            detail=(
                f"snapshot does not authorize a merge (state={snap.state} draft={snap.is_draft} "
                f"checks_known={snap.checks_known} green={snap.required_checks_green})"
            ),
            head_sha=snap.head_sha,
        )
    if admin and (snap.merge_state_status or "").upper() not in _ADMIN_MERGEABLE_STATES:
        return MergeOutcome(
            merged=False,
            action="blocked",
            detail=(
                f"admin merge refused: captured mergeStateStatus={snap.merge_state_status!r} is "
                f"not one of {sorted(_ADMIN_MERGEABLE_STATES)}, so --admin would override "
                "requirements this snapshot did not verify"
            ),
            head_sha=snap.head_sha,
        )
    halt = evaluate_merge_halt(snap.pr_number, snap.head_sha)
    if not halt.allowed:
        return MergeOutcome(
            merged=False, action="blocked", detail=halt.reason, head_sha=snap.head_sha
        )

    args = ["pr", "merge", str(snap.pr_number), "--repo", snap.repo]
    if squash:
        args.append("--squash")
    if admin:
        args.append("--admin")
    if delete_branch:
        args.append("--delete-branch")
    args.extend(snap.match_head_args())

    run = runner or _default_runner
    result = run(args, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "unknown error"
        # A head that moved after capture lands here: GitHub refused the pin.
        return MergeOutcome(merged=False, action="refused", detail=detail, head_sha=snap.head_sha)
    return MergeOutcome(
        merged=True, action="merged", detail=(result.stdout or "").strip(), head_sha=snap.head_sha
    )
