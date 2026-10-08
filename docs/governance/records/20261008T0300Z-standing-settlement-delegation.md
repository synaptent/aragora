# Standing settlement delegation (operator decision, 2026-10-08)

- **Date:** 2026-10-08, about 03:00Z
- **Decided by:** the operator; directly reiterated in the Aragora Codex coordinator conversation on 2026-10-08, together with the two options below
- **Recorded by:** Claude Code; clarified by Codex from the operator's direct request to update the rules and heartbeat
- **Rules this record backs:** [`docs/AGENT_OPERATING_CONTRACT.md` § Standing settlement delegation](../../AGENT_OPERATING_CONTRACT.md#standing-settlement-delegation)

## What the operator said

Verbatim:

> I want missions to merge and settle all PRs that are good and useful for the mission all the time provided review requirements are met and meaningful findings are addressed.

The operator then picked these two options when asked:

1. **Scope:** "All but gate/secrets/deploy". Agents may settle and merge Tier 0-3 PRs and Tier 4 PRs, except changes to the review gate itself (the quorum, evidence and settlement code and their governance docs), to secrets, or to deployment and workflow policy. Those stay with the operator.
2. **Audit trail:** "Labeled as delegated". Agents use the existing exact-head settlement receipt and `aragora/human-settlement` status mechanism when the normal helper permits it. The receipt and a PR comment say the settlement was delegated, name the agent, and cite this record. This does not claim that the operator personally accepted that head, or permit bypassing a helper refusal.

## Why

The operator reported that blanket no-merge rules had accumulated in Receipt-First, Decision Workspace and PR Rescue. Codex verified those restrictions in the current mission rule files. The operator explicitly says that "no merge or settlement by agents" is the opposite of their intent. Historical PR counts and readiness claims in the earlier report are not evidence that any PR is currently ready; each owner must use live exact-head evidence.

## Risk the operator accepts

`docs/REVIEW_AUTHORITY_PRINCIPLES.md` states that current AI reviewers have not shown enough calibration to replace human risk settlement for escalated classes. The report supplied by the operator cites a cross-organization isolation miss in #10224; this record does not independently adjudicate that incident or waive any finding. The operator delegates settlement outside the carve-outs while retaining required review, validation and meaningful-finding resolution. A daily settlement list makes the agent's decisions auditable; it is not a substitute for those gates.

## Revocation

The operator may revoke or narrow the delegation at any time. A merge halt file or auto-halt trigger suspends affected actions under the existing contract; it does not silently revoke the delegation forever. Changes to this record are themselves governance carve-outs and cannot be self-approved under the delegation. Until an authorized change lands, a proposed deletion or amendment is not a new policy.
