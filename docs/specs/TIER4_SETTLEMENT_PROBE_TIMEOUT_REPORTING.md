# Tier 4 Settlement Probe Timeout Reporting

**Status:** design doc / pre-approval artifact for a narrow Tier 4
settlement-helper reliability change.

This document and
`tests/governance/test_tier4_settlement_probe_timeout_reporting.py` are
the governance artifact required by `docs/strategy/FOCUS.md` for changes to
`scripts/settle_tier4_pr.py`.

## Problem

`scripts/settle_tier4_pr.py --json` is used by automation and operator
handoffs to prove whether a Tier 4 PR is blocked, settlement-ready, or
unsafe to mutate. Its live probes call GitHub helpers with a bounded
timeout.

When one of those subprocess probes times out, Python raises
`subprocess.TimeoutExpired`. Before the implementation change, that
exception escaped the helper's `RuntimeError` handling path. The CLI
could therefore print a traceback instead of the documented
machine-readable JSON error:

```json
{
  "ok": false,
  "error": "..."
}
```

That failure is operator-confusing. It does not authorize a merge, but
it makes fail-closed automation harder to distinguish from a crash.

## Proposed Change

Catch live-probe timeout and process-start failures inside the helper's
JSON subprocess wrappers:

- `subprocess.TimeoutExpired` becomes a `RuntimeError` that names the
  exact command and timeout.
- `OSError` becomes a `RuntimeError` that names the exact command and
  start failure.
- Existing non-zero exits and malformed JSON handling stay unchanged.
- The top-level `--json` error path continues to emit `ok=false` and
  exit `2`.

## Safety Boundaries

This change must not alter merge authority semantics:

- no branch-protection mutation
- no workflow or required-check change
- no change to trusted-operator rules
- no change to exact-head matching
- no change to Tier 4 model/dogfood evidence requirements
- no change to `--settle-only` or `--merge-apply` authorization gates

Timeouts remain blockers. They become structured blockers instead of
tracebacks.

## Governance Test Intent

`tests/governance/test_tier4_settlement_probe_timeout_reporting.py`
pins the gap that the implementation inverts:

- a live `gh pr view ... --json ...` probe timeout under
  `settle_tier4_pr.py --check --json` must fail closed,
- the command must return exit code `2`,
- stdout must remain valid JSON with `ok=false`,
- the JSON error must preserve the exact timed-out probe command.

The test fails against the pre-implementation behavior because the
`TimeoutExpired` exception escapes before JSON output.

## Review And Settlement

Because the implementation touches `scripts/settle_tier4_pr.py`, the
implementation PR remains Tier 4-adjacent even though the behavior is
reporting-only. It still requires exact-head review evidence and
operator settlement before merge.
