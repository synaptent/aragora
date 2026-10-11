# Claude Capacity Inventory

`python3 scripts/claude_capacity_inventory.py` reads Claude credential files and
queries only the OAuth `profile` and `usage` GET endpoints at api.anthropic.com.
It makes no inference, refresh, login, routing, lease, or evidence changes. It
does not read Keychain or establish the installed CLI's credential precedence.

Run from a clean checkout after checking operator/reviewer reservations:

```bash
python3 scripts/claude_capacity_inventory.py --timeout 10 --budget 120
```

Use `--output /absolute/private/directory/new-report.json` for an explicit
durable report. The parent directory must exist; the new file is mode 0600 and
existing paths are never overwritten. Default stdout and saved reports omit
tokens, emails, raw account/org IDs, local paths, and upstream error bodies.

## Interpretation

- Exit 0 means an inventory was produced, **not** that any reviewer can run.
- `quota_state=available` means validated included-usage windows had headroom
  when observed. Extra-usage credits are separate; disabling them does not by
  itself exhaust included quota. Non-null model-specific weekly limits are
  included conservatively, without promising capacity for a selected model.
- `quota_state=restricted` means at least one observed window is exhausted,
  not necessarily every model. The newer `limits` array is included: a Fable
  limit at 100% can coexist with `base_window_headroom=true`. That latter field
  describes only `five_hour` and `seven_day`, never model-specific availability.
  `seven_day_breakdown` is display metadata, not a quota window. Unsupported
  limit shapes fail to `unknown` with a fixed reason code; raw scopes are omitted.
  An active limit below 100% is shown with its percentage and severity but stays
  unknown (`active_limit_needs_interpretation`), not an inferred routing grant.
- Missing/malformed limits, stale resets, and provider locks are unknown.
  HTTP 429 is `rate_limited`, not proof of exhausted inference allowance.
- `identity_key` hashes both live account and organization UUIDs. Credentials
  for one identity are not extra seats; different members of a Team organization
  are not automatically collapsed into one identity. Shared organization-wide
  budgets still require separate confirmation before concurrent execution.
- `cached_identity=mismatch` is an observation, never a metadata rewrite.
  File-token equality does not prove that the CLI consumes that credential.
  Discovery checks the named `.claude/.claude.json` before the older HOME-level
  `.claude.json`; this is cached metadata selection, not CLI-auth verification.
- `expires_at` is at most five minutes after identity observation, bounded by
  credential expiry. Old observations must not authorize new work.
- `execution_verified`, `admission_authorized`, and `countability_evaluated`
  are always false. No existing health snapshot or profile selector consumes
  this report. The scalar allowance count is diagnostic, not a concurrency cap.

Identical file tokens are queried once per invocation. Requests are serial and
never retried or redirected. Each socket operation is bounded by `--timeout`;
`--budget` stops admission of further requests, not a hard process deadline.
Responses/files are size-bounded. No API key or paid inference fallback exists.

## Staged Integration Boundary

This inventory complements the failure-reason work in PR #10067; it does not
replace its existing completion probes or unpublished transport planner.
Next steps require separately validated CLI identity/credential precedence,
explicit stale metadata reconciliation, then identity-scoped execution leases
and conservative concurrency admission. Keep existing global reservations
until those guards are implemented and reviewed. Quota alone cannot lift them.
Multiple Claude accounts remain one reviewer family. Quorum grounding, dissent,
and Tier-appropriate human authority remain unchanged.
