# Execution Safety Gate

The execution safety gate is the final control before high-impact automation (plan execution, PR creation, execution bridge) runs after debate.

It is enforced in:
- `aragora/debate/post_debate_coordinator.py`
- `aragora/debate/orchestrator_runner.py` (`_auto_execute_plan`)

## What It Enforces

1. Verified signed consensus receipt
2. Optional signer-key allowlist enforcement (key rotation control)
3. Signed-receipt timestamp freshness checks
4. Provider diversity floor
5. Model-family diversity floor
6. Context taint blocking (prompt-injection signals)
7. High-severity dissent blocking
8. Correlated-failure and suspicious-unanimity risk blocking

This is designed to reduce both:
- Context-level compromise (Brainworm-class prompt/context hijack)
- Model-level compromise in participant sets (OBLITERATUS-class refusal-ablation in open-weight participants)

## Policy Knobs (PostDebateConfig)

| Setting | Default | Purpose |
|---|---:|---|
| `enforce_execution_safety_gate` | `True` | Turns gate on/off |
| `execution_gate_require_verified_signed_receipt` | `True` | Require signed + verified receipt |
| `execution_gate_enforce_receipt_signer_allowlist` | `False` | If enabled, signer key ID must be in allowlist |
| `execution_gate_allowed_receipt_signer_keys` | `()` | Allowed signer key IDs when allowlist mode is enabled |
| `execution_gate_require_signed_receipt_timestamp` | `True` | Require `signed_at` timestamp on receipt |
| `execution_gate_receipt_max_age_seconds` | `86400` | Max receipt age before auto-execution is blocked |
| `execution_gate_receipt_max_future_skew_seconds` | `120` | Max tolerated future clock skew on `signed_at` |
| `execution_gate_min_provider_diversity` | `2` | Minimum unique providers |
| `execution_gate_min_model_family_diversity` | `2` | Minimum unique model families |
| `execution_gate_block_on_context_taint` | `True` | Block when taint signals exist |
| `execution_gate_block_on_high_severity_dissent` | `True` | Block when unresolved severe dissent exists |
| `execution_gate_high_severity_dissent_threshold` | `0.7` | Dissent threshold on 0..1 scale |

## Recommended Production Baseline

- Keep all defaults above.
- Do not lower diversity floors below `2` unless execution is already human-gated.
- Keep taint blocking enabled.
- Keep signed receipt verification required for all high-impact automations.
- If signer allowlists are enabled, keep key IDs synchronized with key rotation playbooks.
- Keep receipt age/future-skew bounds tight and ensure NTP sync on workers.

## Reason Codes

| Code | Meaning |
|---|---|
| `receipt_verification_failed` | Receipt missing/invalid signature or integrity |
| `receipt_signer_not_allowlisted` | Receipt signer key not in approved key allowlist |
| `receipt_missing_signed_timestamp` | Receipt missing or malformed `signed_at` timestamp |
| `receipt_stale` | Receipt age exceeds configured max age |
| `receipt_timestamp_in_future` | Receipt timestamp exceeds allowed future skew |
| `provider_diversity_below_minimum` | Too few distinct providers |
| `model_family_diversity_below_minimum` | Too few distinct model families |
| `tainted_context_detected` | Untrusted context contains suspicious instruction patterns |
| `high_severity_dissent_detected` | Unresolved dissent above configured threshold |
| `correlated_failure_risk` | Ensemble diversity/risk indicates correlated failure risk |
| `suspicious_unanimity_risk` | Very high confidence unanimity with low operator/provider diversity |

When denied, plans are forced to human approval (`ApprovalMode.ALWAYS`, `PlanStatus.AWAITING_APPROVAL`).

## Telemetry Metrics

The server metrics module emits gate telemetry for dashboarding:

- `aragora_execution_gate_decisions_total{path,domain,decision}`
- `aragora_execution_gate_blocks_total{path,domain,reason}`
- `aragora_execution_gate_receipt_verification_total{path,domain,status}`
- `aragora_execution_gate_context_taint_total{path,domain,state}`
- `aragora_execution_gate_correlated_risk_total{path,domain,state}`
- `aragora_execution_gate_provider_diversity{path,domain,...}`
- `aragora_execution_gate_model_family_diversity{path,domain,...}`

Prebuilt Grafana dashboard:
- `deploy/grafana/dashboards/execution-safety-gate.json`

Prometheus alert rules for this metric family:
- `deploy/alerting/prometheus-rules.yml` (`ExecutionGateDenySpike`, `ExecutionGateReceiptVerificationFailures`)
- `deploy/monitoring/alerts.yaml` (`AragoraExecutionGateDenySpike`, `AragoraExecutionGateReceiptVerificationFailures`)

Useful PromQL panels:

```promql
sum by (decision, path) (rate(aragora_execution_gate_decisions_total[15m]))
```

```promql
topk(10, sum by (reason) (rate(aragora_execution_gate_blocks_total[1h])))
```

```promql
sum by (status) (rate(aragora_execution_gate_receipt_verification_total[15m]))
```

```promql
sum by (state, path) (rate(aragora_execution_gate_context_taint_total[1h]))
```

```promql
histogram_quantile(
  0.5,
  sum by (le) (rate(aragora_execution_gate_provider_diversity_bucket[1h]))
)
```

## Threshold Tuning Workflow

Run mixed-ensemble threshold sweeps with:

```bash
python scripts/tune_execution_gate.py --output docs/status/EXECUTION_GATE_TUNING_2026-03-05.md
```

This produces a dated calibration report with:
- scenario coverage
- policy sweep ranking
- recommended threshold set

Latest run in this repo: `docs/status/EXECUTION_GATE_TUNING_2026-03-05.md`

## Regression Guard

CI enforces secure defaults and fallback values for execution-gate policy knobs:

```bash
python scripts/check_execution_gate_defaults.py
```

CI also enforces policy-version/change-control metadata with checksum/signature validation:

```bash
python scripts/check_execution_gate_policy_control.py
```

Policy document:
- `security/policies/execution_gate_defaults_policy.json`
