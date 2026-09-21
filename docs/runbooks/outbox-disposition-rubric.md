# Outbox Disposition Rubric

This rubric classifies active `.aragora/automation-outbox/*.json` items before any
executor mutates the outbox, receipts, owners, branches, issues, or PRs. It is a
read-only triage layer: a disposition is not authorization by itself.

Use it when `fleet_sentinel.py` reports an `outbox_depth` breach, when
`publish_automation_handoffs.py --dry-run --json` skips outbox files, or when
`reconcile_automation_outbox.py --dry-run --json` keeps stale-looking handoffs
because they still protect branch work.

## Required Inputs

Collect these read-only facts for each item:

- Filename and observed file mtime or creation evidence.
- Handoff type, usually `requested_action.type`.
- Target branch, PR, issue, and desired head when present.
- Publisher dry-run state.
- Reconcile dry-run state.
- Live GitHub state for the target branch/PR/issue.
- Owner and steering state from the lane registry or steering mailbox.

Recommended commands:

```bash
python3 scripts/publisher_freshness_check.py --json
python3 scripts/fleet_sentinel.py --json --no-ledger
python3 scripts/publish_automation_handoffs.py --dry-run --json
python3 scripts/classify_handoff_state.py --json
python3 scripts/reconcile_automation_outbox.py --dry-run --json
```

## Dispositions

| Disposition | Definition | Safe executor action | Required authorization |
| --- | --- | --- | --- |
| `PUBLISH-READY` | Publisher dry-run would publish the item, the target is current, no owner or steering gate blocks it, and the queue cap permits publication. | Use only a supported executor that loads exactly the selected handoff, then verify the issue/PR/receipt result. If the available publisher command lacks an exact outbox-file or idempotency-key selector, add that tooling first or stop with `NEEDS-REPAIR`. | Normal publisher authority for the selected handoff; exact state must be rechecked immediately before apply. |
| `EXPIRED-ARCHIVE` | The item has expired or is skipped by publisher expiration logic, while reconcile still keeps it because branch work, open PR representation, or owner steering may still matter. | Preserve first. Archive only through the supported reconcile path after terminal proof, owner release, or explicit human/operator authorization. | Terminal proof or explicit owner/operator release. Expiration alone is not enough to delete or archive protected work. |
| `ORPHANED-TARGET` | The item points to a branch, PR, issue, or receipt target that no longer exists or cannot be resolved, and no remote/local preservation proof is available. | Build a preservation packet, recover or prove absence of unique work, then archive or repair the handoff. | Human/operator authorization when preservation cannot be proven mechanically. |
| `BLOCKED-ON-PARKED-PR` | The item points to a PR/head that is parked by no-treadmill policy, unresolved dissent, or an explicit conductor stop record. | Do not publish, post evidence, repair, settle, or merge through the parked path. Wait for a new head or explicit override. | Explicit operator authorization for a second repair/override, or a new head that invalidates the parked disposition. |
| `NON-HANDOFF-REPORT` | The payload is valid JSON with a non-empty `idempotency_key`, no branch target, no `requested_action` handoff contract, no preservation-shaped fields, and multiple report-specific markers such as `candidate_notes`, `cycle_dir`, `main_required_check_state`, or `verified_8992`; generic `rows` or `required_contexts` alone are not enough. | Archive only through the supported `reconcile_automation_outbox.py --apply` path, which preserves the original payload and records `terminal_disposition.disposition=non_handoff_report`. Do not raw-move or delete the file. | Normal reconcile authority for report disposal after dry-run proves this exact disposition. |
| `NEEDS-REPAIR` | The item is malformed, missing required handoff contract fields, has stale desired-head evidence, or otherwise cannot be safely interpreted by publisher/reconcile. | Repair the handoff contract or target representation in an isolated branch; rerun publisher/classifier/reconcile dry-runs before any outbox mutation. | Normal code/docs PR authority for additive tooling/docs, plus owner/operator authorization if target work would be changed or released. |

## Guardrails

- Re-run the read-only probes immediately before any executor action; the ledger
  can go stale as PRs merge, close, or move.
- Do not treat `EXPIRED-ARCHIVE` as permission to archive. It means the publisher
  will skip the item and a terminal preservation decision is needed.
- Do not use the outbox to store ad hoc reports unless the payload satisfies the
  documented handoff contract. Non-handoff reports should move to a report,
  receipt, or conductor artifact path. If a historical report is already in the
  outbox, dispose of it only through the `NON-HANDOFF-REPORT` reconcile path.
- If a target is Tier 3/4, parked under current-head dissent, or governed by a
  human-settlement rule, the outbox disposition cannot bypass that rule.
