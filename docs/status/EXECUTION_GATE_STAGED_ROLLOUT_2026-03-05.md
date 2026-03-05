# Execution Gate Staged Rollout Plan (2026-03-05)

## Objective

Roll out execution-gate hardening (receipt signer controls, freshness checks, deny-reason telemetry, adversarial regressions) without disrupting approved automation throughput.

## Scope

- Runtime gate policy changes:
  - signer allowlist support
  - signed timestamp requirement
  - receipt freshness / future-skew checks
- Control-plane governance:
  - policy versioning + checksum/signature guard in CI
- Observability and operations:
  - dedicated execution-gate alert routing
  - runbooks for deny spikes and receipt verification failures
  - nightly adversarial regression suite

## Rollout Phases

### Phase 0: Baseline (Day 0)

- Deploy with:
  - `execution_gate_enforce_receipt_signer_allowlist = false`
  - `execution_gate_require_signed_receipt_timestamp = true`
  - `execution_gate_receipt_max_age_seconds = 86400`
  - `execution_gate_receipt_max_future_skew_seconds = 120`
- Success criteria:
  - no increase in `auto_execution_error`
  - receipt verification failures remain <0.5% (15m window)

### Phase 1: Observe + Calibrate (Days 1-3)

- Monitor:
  - deny ratio by `path/domain`
  - top `reason_codes`
  - receipt verification failures
- Tune only if thresholds are clearly noisy.
- Success criteria:
  - deny ratio stable within +/-10% of baseline
  - no critical receipt verification alert incidents

### Phase 2: Signer Allowlist Dry Run (Days 4-7)

- Populate `execution_gate_allowed_receipt_signer_keys` in environment/config.
- Keep enforcement disabled (`execution_gate_enforce_receipt_signer_allowlist = false`).
- Validate no unexpected signer IDs in telemetry.
- Success criteria:
  - 100% of observed signer key IDs represented in allowlist

### Phase 3: Signer Allowlist Enforced (Days 8-14)

- Enable `execution_gate_enforce_receipt_signer_allowlist = true` in canary/control-plane subset.
- Expand to full production after 48h if clean.
- Success criteria:
  - zero sustained (>10m) `receipt_signer_not_allowlisted` spikes
  - no automation incident attributable to signer enforcement

## Guardrails

- Keep automatic execution disabled for any debate with execution-gate denial.
- Keep manual approval fallback active for blocked plans.
- Do not lower provider/model diversity below `2` in production.

## Rollback Criteria

Rollback immediately if any are true:

1. `ExecutionGateReceiptVerificationFailures` critical alert fires for >15 minutes.
2. auto-execution throughput drops by >30% for >2 hours due new receipt reasons.
3. recurring `receipt_timestamp_in_future` indicates time-sync regression across workers.

Rollback actions:

1. Disable signer allowlist enforcement.
2. Temporarily widen `receipt_max_future_skew_seconds` to 300 if required.
3. Keep timestamp requirement on; investigate clock sync before relaxing.
4. Escalate to platform + security on-call.

## Ownership

- Platform Reliability: rollout execution, monitoring, rollback.
- Security Engineering: signer allowlist approvals and rotation controls.
- ML Platform: debate ensemble diversity validation.

## Weekly Checkpoints

### Week 1 Review

- Compare deny-reason distribution before/after rollout.
- Confirm nightly adversarial suite has zero regressions.

### Week 2 Review

- Validate signer rotation workflow with one planned key rotation drill.
- Confirm policy checksum/signature updates are applied through reviewed PRs only.
