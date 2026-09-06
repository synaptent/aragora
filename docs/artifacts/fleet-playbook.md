# Fleet Operational Playbook

This advisory playbook is maintained incrementally by `scripts/ace_curator.py`.
Lessons are grounded in cited fleet exhaust and cannot override repository gates,
the operating contract, or human settlement requirements.

<!-- ACE-CURATOR:LESSON
{"change_reason": "Prepared evidence was invalidated by head drift, and an unstable merge state separately blocked otherwise plausible evidence publication.", "id": "FL-D5CB19447A11", "sources": ["SRC-E4C4C9A5D1DB@.aragora/conductor_cycles/long_run_ledger.jsonl:30", "SRC-98CA4A3D216B@.aragora/conductor_cycles/long_run_ledger.jsonl:8"], "stable_key": "exact-head-and-settlement-stability-before-evidence", "updated_at": "2026-07-11T05:58:10.785050Z"}
-->
- **FL-D5CB19447A11**: Before posting evidence or taking an irreversible settlement action, re-read the exact PR head and require a settlement-stable merge state; discard prepared artifacts after head drift.
<!-- ACE-CURATOR:END -->

<!-- ACE-CURATOR:LESSON
{"change_reason": "Focused reproduction exposed both a genuine main-red failure and a mixed rollup containing inherited and PR-local failures.", "id": "FL-6616FCC6E1C1", "sources": ["SRC-235413454637@.aragora/conductor_cycles/long_run_ledger.jsonl:3", "SRC-6900EBAF1153@.aragora/conductor_cycles/long_run_ledger.jsonl:9"], "stable_key": "focused-reproduction-separates-pr-local-from-main-red", "updated_at": "2026-07-11T05:58:10.785050Z"}
-->
- **FL-6616FCC6E1C1**: Reproduce each failing surface against current origin/main before assigning it to a PR; classify inherited main-red failures separately from PR-local regressions.
<!-- ACE-CURATOR:END -->

<!-- ACE-CURATOR:LESSON
{"change_reason": "Multiple exact-head reviews requested changes, and the no-repeat rule correctly stopped a second autonomous repair on the same lane.", "id": "FL-133B12921898", "sources": ["SRC-998C8EA6A251@.aragora/conductor_cycles/long_run_ledger.jsonl:11", "SRC-8CC0F99108AE@.aragora/conductor_cycles/long_run_ledger.jsonl:13", "SRC-CDFC9145E280@.aragora/conductor_cycles/long_run_ledger.jsonl:17"], "stable_key": "bounded-repair-after-model-dissent", "updated_at": "2026-07-11T05:58:10.785050Z"}
-->
- **FL-133B12921898**: Treat concrete P0-P2 model dissent as a hard stop; after one bounded repair, rotate or request fresh authorization instead of entering an autonomous repair treadmill.
<!-- ACE-CURATOR:END -->

<!-- ACE-CURATOR:LESSON
{"change_reason": "A checkout-time cancellation was shown to be unrelated to the guard, while a later scoped rerun cleared an unstable state and enabled a normal merge.", "id": "FL-347FEFCFF664", "sources": ["SRC-BFE5C29531E0@.aragora/conductor_cycles/long_run_ledger.jsonl:14", "SRC-0276C9BBB0FA@.aragora/conductor_cycles/long_run_ledger.jsonl:38"], "stable_key": "classify-cancelled-ci-before-scoped-rerun", "updated_at": "2026-07-11T05:58:10.785050Z"}
-->
- **FL-347FEFCFF664**: When a CI job is cancelled before repository code executes, classify it as infrastructure noise, compare the same context on current main, and rerun only the stale scoped job rather than treating it as a terminal product failure.
<!-- ACE-CURATOR:END -->

<!-- ACE-CURATOR:LESSON
{"change_reason": "Resolver dry-runs became safe after mailbox receipts, yet the apply operation correctly remained blocked until explicit operator authorization existed.", "id": "FL-092E504531B0", "sources": ["SRC-13E27E7144AB@.aragora/conductor_cycles/long_run_ledger.jsonl:19", "SRC-423E73919513@.aragora/conductor_cycles/long_run_ledger.jsonl:27", "SRC-B766F31F9471@.aragora/conductor_cycles/long_run_ledger.jsonl:28"], "stable_key": "receipts-do-not-substitute-for-operator-authorization", "updated_at": "2026-07-11T05:58:10.785050Z"}
-->
- **FL-092E504531B0**: Use receipts to expose and clear observable lane blockers, but require the exact operator token before applying stale-owner or closed-lane mutations.
<!-- ACE-CURATOR:END -->
