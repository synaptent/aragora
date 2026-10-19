# Aragora-Native Agent Flywheel Map

The [Agent Operating Loop](architecture/agent-operating-loop.md) is the canonical
read-only projection through which flywheel recommendations meet live authority.

This document maps Agent Flywheel concepts into Aragora-native primitives. The
first implementation is intentionally a **read-only kernel**: it observes,
normalizes, scores, and recommends. It does not claim work, launch agents, close
issues, send broker mail, create leases, or index CASS memory.

## Concept Map

| Agent Flywheel concept | Aragora-native primitive | First kernel behavior |
|---|---|---|
| Bead / atomic work | `WorkItem` over PRs, automation handoffs, beads, convoys, broker runs, missions | Normalize into stable JSON |
| Board / current work | `aragora work list --scope current --json` | Exclude terminal and stale historical records |
| Plan-space graph | `WorkGraph` | Expose dependencies, shared branches, and evidence refs |
| Robot / next action | `aragora work robot --json` | Rank current work with explicit scoring dimensions |
| Agent Mail | Future broker mail | Not implemented here |
| File leases | Future work leases | Not implemented here |
| `work pick` / execution | Future brokered claim path | Not implemented here |
| CASS / memory review | Future review memory index | Not implemented here |

## Scoring Dimensions

`WorkScore` uses normalized `0..1` dimensions where higher means more
actionable now:

- `readiness`: is the item close to review, settlement, or operator action?
- `impact`: does it affect queue health, proof, reliability, or high-value work?
- `risk`: risk-controlled / safely settleable surface, not raw danger.
- `parallel_safety`: can another agent work on it without conflict?
- `staleness`: freshness of the operational signal.
- `owner_clarity`: explicit branch, assignee, harness, or owner evidence.
- `test_obligation`: whether code-like surfaces show nearby test evidence.
- `dependency_clarity`: whether dependencies are explicit.
- `bead_quality`: quality of bead/convoy-style task shape.

`WorkRecommendation.classification` uses the stable routing vocabulary
`ready`, `needs-polish`, `blocked`, `duplicate`, `stale`, `review-only`, and
`human-gated`. The kernel only recommends; it does not claim or mutate the item.

## Current-Truth Boundary

`--scope current` intentionally excludes completed broker runs, terminal receipts,
old bead records, and static mission files unless they are fresh active records.
Use `--scope all` for audit/context views.

This is the main dogfood protection: historical Claude/Factory/Codex artifacts
remain inspectable without polluting the live operational queue.

## Non-Goals For This PR

- No `aragora work pick`.
- No `aragora work ready`.
- No broker mail.
- No file leases.
- No worktree creation.
- No agent launch.
- No issue closure.
- No dependency on external `bd`, `bv`, `br`, Agent Mail, or CASS tools.

The output is designed to be stable enough for a later brokered
Claude/Factory/Codex decision loop.
