#!/usr/bin/env python3
"""One composed situation view for an agent operating this repo (READ-ONLY).

An agent starting work here currently pays ~24k tokens across 7 calls to learn
what is true, and ~4k tokens per tick to be told nothing changed. Both figures
are measured -- see ``scripts/agent_surface/measure.py`` and
``docs/agent-surface/DIAGNOSIS.md``. The cost is not that the information is
missing; aragora has ~188 machine-readable state instruments. The cost is that
nothing composes them, so the agent performs the join in its own context window
and pays for every intermediate byte.

This composes instead. The joining and the diffing happen *below the context
boundary*: this tool may spend several thousand tokens of GitHub JSON
internally, but the agent reads back only the answer. That distinction is the
whole design -- an agent pays for what enters its context, not for what the
tool does on its behalf.

Six fields, fixed order, always present (the capsule contract):

1. ANCHOR       identity and the exact revision every other field is true of
2. OBJECTIVE    what is being worked on, and progress
3. BELIEFS      derived facts, each with provenance, freshness, and confidence
4. UNKNOWNS     open questions, each with the cheapest probe that would answer it
5. FRONTIER     actions legal RIGHT NOW, with cost, risk, and reversibility
6. OBLIGATIONS  effects in flight, what they are waiting on, how they verify

Modes:

  situation.py                 compact view, emits a cursor        (measured 552 tokens)
  situation.py --since CURSOR  delta only; ~30 tokens when quiet   (measured  32 tokens)
  situation.py --json          full structured payload

Every belief carries its own ``source`` field, so provenance is already in the
payload; there is no separate --explain mode.

Anchoring rule: every belief is true as of ``anchor.head`` and ``anchor.main``.
If either moved, the capsule is stale and says so rather than silently mixing
revisions -- the failure mode documented across this repo's runbooks, where a
settlement signal from an old head is read as authority for a new one.

Authority rule: this view SUMMARIZES lower-authority sources; it never upgrades
them. A belief sourced from a stale cache is reported as stale, never promoted
to fact. Where this tool cannot establish something it says so in UNKNOWNS
rather than defaulting to a reassuring value. Absence of evidence is never
rendered as evidence of absence.

Inputs: ``git`` (local, cheap), two ``gh`` calls, and -- unless ``--no-fleet``
-- one ``scripts/loop_control_status.py`` subprocess (~15s, ~3,100 tokens of
JSON reduced to about 40 on the way out). With ``--pr N`` it also runs
``scripts/settle_status.py``, supplying the ``--repo`` slug that tool requires
and cannot infer for itself. Writes nothing at all; the cursor is returned to
the caller to hold, not cached on disk.

Exit codes: 0 -- capsule produced. 1 -- could not establish an anchor (the one
condition under which no useful capsule exists).

Safety model: read-only against the repo and GitHub. Never mutates, never
merges, never posts. Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GH_TIMEOUT = 90


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def sh(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a probe. A failed probe is data (it becomes an UNKNOWN), not a crash."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} not installed"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001 - a broken probe must not kill the capsule
        return 1, str(exc)


@dataclass
class Belief:
    """A derived fact that knows where it came from and when it stops being true."""

    key: str
    value: Any
    source: str
    freshness: str  # "live" | "cached:<age>" | "stale:<age>" | "unknown"
    confidence: str  # "observed" | "derived" | "assumed"
    note: str = ""


@dataclass
class Unknown:
    question: str
    why_it_matters: str
    cheapest_probe: str
    est_tokens: int


@dataclass
class Action:
    label: str
    command: str
    cost: str  # "cheap" | "moderate" | "expensive"
    risk: str  # "none" | "low" | "high"
    reversible: bool
    prerequisite: str = ""


@dataclass
class Capsule:
    anchor: dict[str, Any] = field(default_factory=dict)
    objective: dict[str, Any] = field(default_factory=dict)
    beliefs: list[Belief] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    frontier: list[Action] = field(default_factory=list)
    obligations: list[dict[str, Any]] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)

    def cursor(self) -> str:
        """Digest of the volatile part only.

        Deliberately excludes ``generated_at`` -- otherwise every tick would
        report a change and the delta path would be worthless.
        """
        material = {
            "head": self.anchor.get("head"),
            "main": self.anchor.get("main"),
            "beliefs": {b.key: b.value for b in self.beliefs},
            "obligations": self.obligations,
        }
        blob = json.dumps(material, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------


def build_anchor(cap: Capsule) -> bool:
    code, branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        cap.degraded.append("not a git repository; no anchor possible")
        return False
    _, head = sh(["git", "rev-parse", "--short=12", "HEAD"])
    main_code, main_sha = sh(["git", "rev-parse", "--short=12", "origin/main"])
    _, slug = sh(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])

    cap.anchor = {
        "repo": slug if slug and "/" in slug else "unknown",
        "branch": branch,
        "head": head,
        "main": main_sha if main_code == 0 else "unresolved",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if main_code != 0:
        cap.degraded.append("origin/main unresolved; ahead/behind beliefs withheld")
    return True


def add_local_beliefs(cap: Capsule) -> None:
    code, porcelain = sh(["git", "status", "--porcelain"])
    if code == 0:
        dirty = [ln for ln in porcelain.splitlines() if ln.strip()]
        cap.beliefs.append(
            Belief(
                "working_tree",
                "clean" if not dirty else f"{len(dirty)} uncommitted path(s)",
                "git status --porcelain",
                "live",
                "observed",
            )
        )

    if cap.anchor.get("main") != "unresolved":
        _, behind = sh(["git", "rev-list", "--count", "HEAD..origin/main"])
        _, ahead = sh(["git", "rev-list", "--count", "origin/main..HEAD"])
        if behind.isdigit() and ahead.isdigit():
            cap.beliefs.append(
                Belief(
                    "branch_position",
                    f"{ahead} ahead / {behind} behind origin/main",
                    "git rev-list",
                    "live",
                    "observed",
                    note="squash merges can make 'ahead' misleading; not merge proof",
                )
            )


def add_github_beliefs(cap: Capsule) -> dict[str, Any]:
    """One `gh pr list` and one `gh run list`. Returns raw PR rows for delta use."""
    raw: dict[str, Any] = {"prs": []}

    if not shutil.which("gh"):
        cap.degraded.append("gh not installed; all GitHub beliefs withheld")
        cap.unknowns.append(
            Unknown(
                "What is in flight on GitHub?",
                "Cannot judge queue pressure or pick safe work without it.",
                "install gh and re-run",
                0,
            )
        )
        return raw

    code, out = sh(
        [
            "gh",
            "pr",
            "list",
            "--limit",
            "100",
            "--json",
            "number,title,isDraft,updatedAt,headRefName,author",
        ],
        timeout=GH_TIMEOUT,
    )
    if code == 0:
        try:
            prs = json.loads(out)
        except json.JSONDecodeError:
            prs = []
            cap.degraded.append("gh pr list returned unparseable JSON")
        raw["prs"] = prs
        drafts = sum(1 for p in prs if p.get("isDraft"))
        cap.beliefs.append(
            Belief(
                "prs_open",
                len(prs),
                "gh pr list --limit 100",
                "live",
                "observed",
                note="capped at 100; a full queue may be larger" if len(prs) >= 100 else "",
            )
        )
        cap.beliefs.append(Belief("prs_ready", len(prs) - drafts, "gh pr list", "live", "derived"))
        cap.beliefs.append(Belief("prs_draft", drafts, "gh pr list", "live", "derived"))
        if len(prs) >= 100:
            cap.unknowns.append(
                Unknown(
                    "Is the open-PR count actually 100, or is it capped?",
                    "A cap read as a total understates queue pressure and has "
                    "previously hidden hundreds of items.",
                    "gh pr list --limit 500 --json number --jq length",
                    30,
                )
            )
    else:
        cap.degraded.append(f"gh pr list failed: {out[:120]}")
        cap.unknowns.append(
            Unknown(
                "What is in flight?",
                "Queue pressure unknown.",
                "gh pr list --limit 100 --json number",
                40,
            )
        )

    code, out = sh(
        [
            "gh",
            "run",
            "list",
            "--branch",
            "main",
            "--limit",
            "15",
            "--json",
            "conclusion,name,createdAt",
        ],
        timeout=GH_TIMEOUT,
    )
    if code == 0:
        try:
            runs = json.loads(out)
        except json.JSONDecodeError:
            runs = []
        failures = [r for r in runs if r.get("conclusion") == "failure"]
        skipped = sum(1 for r in runs if r.get("conclusion") == "skipped")
        cap.beliefs.append(
            Belief(
                "main_recent_failures",
                len(failures),
                "gh run list --branch main --limit 15",
                "live",
                "derived",
                note=(
                    f"{skipped}/{len(runs)} runs skipped -- skipped is correct "
                    "self-gating here, NOT a red main"
                )
                if skipped
                else "",
            )
        )
        # Deliberately an UNKNOWN, not a belief: run conclusions are not the
        # required-check set, and conflating them is a documented misread.
        cap.unknowns.append(
            Unknown(
                "Is main actually green on its 5 REQUIRED checks?",
                "Run conclusions are not branch protection. Reading skipped runs "
                "as failure is a documented misread of this repo's telemetry.",
                "gh api repos/{owner}/{repo}/branches/main/protection/"
                "required_status_checks --jq .contexts",
                60,
            )
        )
    else:
        cap.degraded.append(f"gh run list failed: {out[:120]}")

    return raw


def add_fleet_beliefs(cap: Capsule) -> None:
    """Summarize scripts/loop_control_status.py without embedding it.

    That tool emits ~3,100 tokens of JSON. The agent must read back about 40.
    This is the composition rule in miniature: summarize downward, and never let
    the summary claim more certainty than the thing it summarizes.
    """
    code, out = sh(["python3", "scripts/loop_control_status.py", "--json"], timeout=120)
    if code != 0:
        cap.degraded.append(f"loop_control_status unavailable: {out[:100]}")
        cap.unknowns.append(
            Unknown(
                "Are the background loops safe to continue?",
                "Dispatching work into a halted or blocked fleet wastes the run.",
                "python3 scripts/loop_control_status.py --json",
                3100,
            )
        )
        return

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        cap.degraded.append("loop_control_status returned unparseable JSON")
        return

    summary = data.get("summary", {})
    by_state = summary.get("by_state", {})
    unknown_n = int(by_state.get("unknown", 0))
    total = sum(int(v) for v in by_state.values()) or len(data.get("records", []))
    shape = " / ".join(f"{n} {s}" for s, n in sorted(by_state.items()))

    cap.beliefs.append(
        Belief(
            "fleet_loops",
            shape or "none reported",
            "scripts/loop_control_status.py --json",
            "live",
            "derived",
        )
    )

    safe = summary.get("fleet_safe_to_continue")
    # Do NOT restate a green verdict computed over loops that could not be read.
    caveat = (
        (
            f"computed while {unknown_n}/{total} loops report state=unknown; "
            "this verdict does not cover them"
        )
        if unknown_n
        else ""
    )
    cap.beliefs.append(
        Belief(
            "fleet_safe_to_continue",
            safe,
            "loop_control_status summary",
            "live",
            "derived",
            note=caveat,
        )
    )

    if summary.get("any_blocked"):
        cap.beliefs.append(
            Belief(
                "fleet_blocked",
                True,
                "loop_control_status summary",
                "live",
                "observed",
                note="at least one loop reports a blocker",
            )
        )

    if unknown_n:
        cap.unknowns.append(
            Unknown(
                f"Why do {unknown_n} of {total} background loops report state=unknown?",
                "fleet_safe_to_continue is computed without them, so a green "
                "fleet verdict is partial rather than complete.",
                "python3 scripts/loop_control_status.py --json "
                '| python3 -c "import json,sys; '
                "print([r['loop_id'] for r in json.load(sys.stdin)['records'] "
                "if r.get('state')=='unknown'])\"",
                60,
            )
        )


def add_pr_beliefs(cap: Capsule, pr: int) -> None:
    """Compose settle_status.py for one PR, inferring --repo from the anchor.

    settle_status.py requires --repo and cannot infer it; passing the wrong slug
    yields a bare traceback. The anchor already knows the slug, so the capsule
    supplies it.
    """
    slug = cap.anchor.get("repo", "")
    if "/" not in slug:
        cap.degraded.append(f"cannot resolve repo slug; settlement for PR {pr} withheld")
        return

    code, out = sh(
        ["python3", "scripts/settle_status.py", "--repo", slug, "--pr", str(pr), "--json"],
        timeout=120,
    )
    if code != 0:
        cap.degraded.append(f"settle_status failed for PR {pr}")
        cap.unknowns.append(
            Unknown(
                f"Where does PR {pr} stand in settlement?",
                "Without it, merge-readiness is unknown and must not be assumed.",
                f"python3 scripts/settle_status.py --repo {slug} --pr {pr}",
                80,
            )
        )
        return

    try:
        s = json.loads(out)
    except json.JSONDecodeError:
        cap.degraded.append(f"settle_status returned unparseable JSON for PR {pr}")
        return

    pr_head = s.get("head_sha", "")
    cap.beliefs.append(Belief(f"pr{pr}_tier", s.get("tier"), "settle_status.py", "live", "derived"))
    cap.beliefs.append(
        Belief(
            f"pr{pr}_quorum",
            s.get("quorum_conclusion"),
            "settle_status.py",
            "live",
            "derived",
            note=f"true only at head {pr_head[:12]}; a new push invalidates it",
        )
    )
    cap.beliefs.append(
        Belief(f"pr{pr}_signals", s.get("signal_count"), "settle_status.py", "live", "derived")
    )
    cap.beliefs.append(
        Belief(
            f"pr{pr}_human_settlement",
            "present" if s.get("human_settlement_present") else "absent",
            "commit status aragora/human-settlement",
            "live",
            "observed",
        )
    )

    nxt = s.get("next_action")
    if nxt:
        # Attributed, not adopted. Four instruments in this repo compute a
        # next_action from overlapping sources and nothing arbitrates them, so
        # the capsule must never launder one into "the" answer.
        cap.obligations.append(
            {
                "kind": "advisory_next_action",
                "detail": f"settle_status.py says for PR {pr}: {nxt}",
                "verifies_by": f"re-run settle_status.py --pr {pr} at the same head",
            }
        )


def add_objective(cap: Capsule) -> None:
    branch = cap.anchor.get("branch", "")
    _, subject = sh(["git", "log", "-1", "--pretty=%s"])
    cap.objective = {
        "branch": branch,
        "last_commit": subject[:100],
        "inferred": (
            "detached/main -- no branch-scoped objective"
            if branch in {"main", "HEAD"}
            else f"work on branch {branch}"
        ),
    }


def add_frontier(cap: Capsule) -> None:
    """Actions legal RIGHT NOW, given what we established above."""
    b = {x.key: x.value for x in cap.beliefs}
    branch = cap.anchor.get("branch", "")
    dirty = isinstance(b.get("working_tree"), str) and "uncommitted" in b["working_tree"]

    # Hand over a command that runs as written. A frontier entry containing a
    # placeholder the agent must resolve has pushed the join back onto it.
    slug = cap.anchor.get("repo", "")
    if "/" in slug:
        cap.frontier.append(
            Action(
                "Inspect a specific PR's settlement",
                f"python3 scripts/agent_surface/situation.py --pr N   "
                f"# direct: scripts/settle_status.py --repo {slug} --pr N",
                "cheap",
                "none",
                True,
            )
        )
    else:
        cap.frontier.append(
            Action(
                "Inspect a specific PR's settlement",
                "python3 scripts/settle_status.py --repo <slug> --pr <N>",
                "cheap",
                "none",
                True,
                prerequisite="repo slug unresolved here; settle_status.py "
                "requires --repo and cannot infer it",
            )
        )
    if dirty:
        cap.frontier.append(
            Action(
                "Review uncommitted work before anything else",
                "git status && git diff --stat",
                "cheap",
                "none",
                True,
            )
        )
    if branch in {"main", "HEAD"}:
        cap.frontier.append(
            Action(
                "Create an isolated worktree (required before edits)",
                "python3 scripts/codex_worktree_autopilot.py ensure "
                "--agent claude --base main --force-new --print-path",
                "moderate",
                "low",
                True,
                prerequisite="CLAUDE.md forbids editing from the main checkout",
            )
        )
    cap.frontier.append(
        Action(
            "Check whether a lane owner is alive before re-dispatching",
            "python3 scripts/identify_lane_owner.py --pr <N>",
            "moderate",
            "low",
            True,
            prerequisite="fails closed if unpushed work may exist",
        )
    )

    # Explicitly named as NOT on the frontier. A frontier that lists only what
    # is allowed leaves the agent to infer prohibitions, which is where
    # governance accidents happen.
    cap.obligations.append(
        {
            "kind": "standing_prohibition",
            "detail": "No merge, settle, or evidence-post action is on this "
            "frontier. Tier 3/4 settlement requires a human status on "
            "the exact head and is never agent-authorized.",
            "verifies_by": "docs/AGENT_OPERATING_CONTRACT.md",
        }
    )


def add_standing_unknowns(cap: Capsule) -> None:
    open_prs = next((b.value for b in cap.beliefs if b.key == "prs_open"), None)
    scope = f"{open_prs} open PRs" if open_prs is not None else "the open PRs"
    cap.unknowns.append(
        Unknown(
            f"Which of the {scope}, if any, is mine to act on?",
            "Ownership is the difference between progress and lane contamination.",
            "python3 scripts/check_work_lease.py --json",
            200,
        )
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render(cap: Capsule) -> str:
    a = cap.anchor
    L = [
        f"ANCHOR   {a['repo']} @ {a['branch']} | head {a['head']} | main {a['main']}",
        f"         as of {a['generated_at']} | cursor {cap.cursor()}",
        "",
        f"OBJECTIVE {cap.objective.get('inferred', 'unknown')}",
        f"          last: {cap.objective.get('last_commit', '')}",
        "",
        "BELIEFS",
    ]
    for b in cap.beliefs:
        line = f"  {b.key:<22} {str(b.value):<28} [{b.freshness}/{b.confidence}]"
        L.append(line)
        if b.note:
            L.append(f"  {'':<22} ! {b.note}")

    L += ["", "UNKNOWNS  (ranked; each shows the cheapest probe)"]
    for i, u in enumerate(cap.unknowns, 1):
        L.append(f"  {i}. {u.question}")
        L.append(f"     why: {u.why_it_matters}")
        L.append(f"     probe (~{u.est_tokens}tk): {u.cheapest_probe}")

    L += ["", "FRONTIER  (legal now)"]
    for act in cap.frontier:
        rev = "reversible" if act.reversible else "IRREVERSIBLE"
        L.append(f"  - {act.label}  [{act.cost}/{act.risk}/{rev}]")
        L.append(f"    $ {act.command}")
        if act.prerequisite:
            L.append(f"    prereq: {act.prerequisite}")

    L += ["", "OBLIGATIONS"]
    for o in cap.obligations:
        L.append(f"  - [{o['kind']}] {o['detail']}")

    if cap.degraded:
        L += ["", "DEGRADED  (this capsule is incomplete in these ways)"]
        L += [f"  ! {d}" for d in cap.degraded]

    return "\n".join(L)


def build(repo_root: Path, pr: int | None = None, fleet: bool = True) -> Capsule:
    cap = Capsule()
    if not build_anchor(cap):
        return cap
    add_local_beliefs(cap)
    add_github_beliefs(cap)
    if fleet:
        add_fleet_beliefs(cap)
    if pr is not None:
        add_pr_beliefs(cap, pr)
    add_objective(cap)
    add_standing_unknowns(cap)
    add_frontier(cap)
    return cap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", metavar="CURSOR", help="emit a delta against this cursor")
    ap.add_argument("--json", action="store_true", help="full structured payload")
    ap.add_argument("--pr", type=int, help="also compose settlement state for this PR")
    ap.add_argument(
        "--no-fleet",
        action="store_true",
        help="skip loop_control_status (saves ~15s wall time, loses fleet beliefs)",
    )
    ap.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = ap.parse_args()

    cap = build(args.repo_root, pr=args.pr, fleet=not args.no_fleet)
    if not cap.anchor:
        print("no anchor: not a git repository", file=sys.stderr)
        return 1

    cursor = cap.cursor()

    if args.since:
        if args.since == cursor:
            # The whole point of the quiet path: ~30 tokens to say "nothing".
            print(json.dumps({"changed": False, "cursor": cursor, "anchor": cap.anchor["head"]}))
            return 0
        changed = {b.key: b.value for b in cap.beliefs}
        print(
            json.dumps(
                {
                    "changed": True,
                    "cursor": cursor,
                    "anchor": cap.anchor["head"],
                    "beliefs": changed,
                    "degraded": cap.degraded,
                },
                indent=None,
            )
        )
        return 0

    if args.json:
        print(
            json.dumps(
                {
                    "anchor": cap.anchor,
                    "cursor": cursor,
                    "objective": cap.objective,
                    "beliefs": [vars(b) for b in cap.beliefs],
                    "unknowns": [vars(u) for u in cap.unknowns],
                    "frontier": [vars(f) for f in cap.frontier],
                    "obligations": cap.obligations,
                    "degraded": cap.degraded,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    print(render(cap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
