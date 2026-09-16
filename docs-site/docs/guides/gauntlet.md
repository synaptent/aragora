---
title: Gauntlet Mode - Adversarial Stress Testing
description: Gauntlet Mode - Adversarial Stress Testing
---

# Gauntlet Mode - Adversarial Stress Testing

> **Last Updated:** 2026-01-18

Gauntlet is Aragora's adversarial validation engine for stress-testing high-stakes decisions through multi-agent debate.

## Related Documentation

| Document | Purpose |
|----------|---------|
| **GAUNTLET.md** (this) | Overview and usage guide |
| [GAUNTLET_ARCHITECTURE.md](./gauntlet-architecture) | Package structure and internals |
| [PROBE_STRATEGIES.md](./probe-strategies) | Probing strategy reference |
| [MODES_REFERENCE.md](./modes-reference) | Debate modes (RedTeam, Prober) |

## Overview

Unlike standard code review which checks for bugs, Gauntlet **actively attacks** your specifications, architectures, and policies to find weaknesses before they become problems. It combines:

- **Red Team Attacks** - Security, compliance, scalability challenges
- **Capability Probing** - Hallucination, sycophancy, consistency testing
- **Scenario Matrix Testing** - Test across parameter variations
- **Formal Verification** - Z3/Lean proof attempts where applicable
- **Decision Receipts** - Audit-ready artifacts for compliance

## Quick Start

```bash
# Validate a specification
aragora gauntlet spec.md --input-type spec

# Quick security check (2 minutes)
aragora gauntlet api_design.md --profile quick

# Thorough compliance audit (15 minutes)
aragora gauntlet policy.yaml --input-type policy --profile thorough

# Code security review
aragora gauntlet src/auth.py --input-type code --profile code

# Generate decision receipt
aragora gauntlet contract.md --output receipt.html
```

## Use Cases

### 1. API/Specification Validation
Catch design flaws before implementation:
```bash
aragora gauntlet api_spec.yaml --input-type spec --profile thorough
```

Attacks run:
- Edge case injection
- Scalability stress tests
- Security boundary violations
- Logical consistency checks

### 2. Compliance Audits
Verify GDPR, HIPAA, AI Act compliance:
```bash
# GDPR compliance check
aragora gauntlet data_policy.md --input-type policy --persona gdpr

# HIPAA compliance check
aragora gauntlet health_api.yaml --input-type spec --persona hipaa

# AI Act compliance check
aragora gauntlet ml_model_spec.md --input-type spec --persona ai_act
```

### 3. Architecture Stress Testing
Validate system designs under adversarial conditions:
```bash
aragora gauntlet architecture.md --input-type architecture --profile thorough
```

Attacks run:
- Dependency failure scenarios
- Race condition probing
- Scalability limit testing
- Single points of failure detection

### 4. Security Reviews
Deep security analysis of code or designs:
```bash
aragora gauntlet src/ --input-type code --profile code
```

Attacks run:
- Injection vulnerabilities
- Privilege escalation paths
- Adversarial input handling
- Authentication/authorization gaps

## Profiles

Pre-configured profiles optimize for different scenarios:

| Profile | Duration | Focus | Use Case |
|---------|----------|-------|----------|
| `quick` | ~2 min | High-severity issues | Quick sanity check |
| `default` | ~5 min | Balanced coverage | Standard validation |
| `thorough` | ~15 min | Comprehensive | Pre-release validation |
| `code` | ~10 min | Security + quality | Code reviews |
| `policy` | ~10 min | Compliance + legal | Policy/contract review |

```bash
aragora gauntlet input.md --profile thorough
```

## Attack Categories

### Security Attacks
| Attack | Description |
|--------|-------------|
| `security` | General security vulnerabilities |
| `injection` | SQL, command, prompt injection |
| `privilege_escalation` | Unauthorized access paths |
| `adversarial_input` | Malformed/malicious inputs |

### Compliance Attacks
| Attack | Description |
|--------|-------------|
| `compliance` | General compliance gaps |
| `gdpr` | GDPR-specific violations |
| `hipaa` | HIPAA-specific violations |
| `ai_act` | EU AI Act violations |

### Architecture Attacks
| Attack | Description |
|--------|-------------|
| `architecture` | Design pattern issues |
| `scalability` | Scale limit testing |
| `performance` | Bottleneck detection |

### Logic Attacks
| Attack | Description |
|--------|-------------|
| `logic` | Logical consistency |
| `logical_fallacy` | Reasoning errors |
| `edge_cases` | Boundary conditions |
| `assumptions` | Unstated assumptions |
| `counterexamples` | Disproving claims |

### Operational Attacks
| Attack | Description |
|--------|-------------|
| `operational` | Runtime issues |
| `dependency_failure` | External dependency risks |
| `race_conditions` | Concurrency issues |

## Capability Probes

Probes test the AI agents themselves for reliability:

| Probe | Description |
|-------|-------------|
| `hallucination` | Factual accuracy |
| `sycophancy` | Agreement bias |
| `contradiction` | Internal consistency |
| `persistence` | Opinion stability |
| `calibration` | Confidence accuracy |
| `reasoning_depth` | Logical rigor |

## Verdicts

Gauntlet produces one of three verdicts:

| Verdict | Meaning | Action |
|---------|---------|--------|
| **PASS** | Safe to proceed | No critical issues found |
| **CONDITIONAL** | Proceed with mitigations | High issues require attention |
| **FAIL** | Do not proceed | Critical issues block deployment |

### Command exit status

Local and API-backed `aragora gauntlet` invocations use the same shell contract:

| Exit | Verdicts (case-insensitive) | Meaning for scripts |
|------|----------------------------|---------------------|
| `0` | `PASS`, `APPROVED` | Unconditional approval |
| `2` | `CONDITIONAL`, `APPROVED_WITH_CONDITIONS`, `NEEDS_REVIEW` | Human review or mitigations required; not shell success |
| `1` | `FAIL`, `REJECTED`, missing or unknown verdict | Rejected or invalid result; do not proceed |

An explicit completion status must be `completed` (case-insensitive). Failed,
cancelled, pending, running, or unrecognized statuses exit `1` even if the verdict
says `APPROVED`. Valid legacy receipts and local results without a status field
remain supported. Exit `1` is also used for fatal operational errors.

**Behavior change:** conditional approval now exits `2`, rather than implicitly
succeeding. Scripts must handle that outcome explicitly; `aragora gauntlet ... &&
deploy` proceeds only on unconditional approval. This exit contract reflects the
reported result; it is not a guarantee that the stress-test found every defect.

### Verdict Criteria
```python
# Default pass/fail criteria
max_critical_findings: 0    # Any critical = FAIL
max_high_findings: 2        # >2 high = CONDITIONAL
min_robustness_score: 0.7   # &lt;0.7 = CONDITIONAL
```

### Waiting for API runs

`client.gauntlet.run_and_wait(...)` polls only `pending`/`running`; `completed` fetches the receipt.
HTTP `400` / `GAUNTLET_406` alone does not mean pending. Failed/cancelled, missing, malformed,
or mismatched results stop waiting; operational errors propagate. Terminal diagnostics omit backend details.
`timeout` bounds monotonic polling after submission, not active transport; no request starts after expiry.
API/queued runs retain their submitted ID; standalone runs generate one. Legacy receipts may omit status,
but mismatched IDs are rejected, not migrated. Durable results outrank stale caches/inflight records;
exhausted jobs fail while analysis retries stay nonterminal. Lookup faults are errors, not missing runs.
Saved results survive cleanup faults with diagnostics. No delivery retries or resubmission: inspect the run.

## Decision Receipts

Decision Receipts are audit-ready artifacts documenting the validation:

```bash
# Generate HTML receipt
aragora gauntlet spec.md --output receipt.html

# Generate JSON receipt
aragora gauntlet spec.md --output receipt.json --format json

# Generate Markdown receipt
aragora gauntlet spec.md --output receipt.md --format md
```

Receipt contents:
- **Verdict** with justification
- **Attack results** with severity ratings
- **Agent agreement** scores
- **Recommendations** for remediation
- **Cryptographic checksum** for integrity
- **Timestamp** for audit trail

## Decision Gate (CI-Friendly)

The CLI exits with non-zero codes to make Gauntlet usable as a decision gate:

- `1` = rejected (critical/high findings exceeded)
- `2` = needs review (borderline or conditional)

Example:

```bash
aragora gauntlet spec.md --profile thorough --output receipt.html
```

Use this in CI to fail builds when a decision does not pass the stress-test.

### GitHub Action

A ready-to-use workflow is available at:

- `.github/workflows/aragora-gauntlet.yml`

Configure provider keys in repository secrets to enable PR reviews.

## Evaluation Harness

For deterministic, no-key evaluation, use the fixture-based harness:

```bash
python benchmarks/gauntlet_evaluation.py
```

You can add fixtures in `benchmarks/fixtures/gauntlet` and export results:

```bash
python benchmarks/gauntlet_evaluation.py --output benchmarks/results/gauntlet_eval.json
```

## Case Study: Epic Strategic Debate

See `docs/case-studies/epic-strategic-debate.md` for a real multi-agent debate that converged on the “Automated Adversarial Validation” positioning and clarified the core wedge for Aragora.

## Compliance Personas

Gauntlet includes specialized compliance personas:

### GDPR Persona
Tests data protection compliance:
- Data minimization
- Consent mechanisms
- Right to erasure
- Data portability
- Cross-border transfers

### HIPAA Persona
Tests healthcare data compliance:
- PHI protection
- Access controls
- Audit logging
- Breach notification
- Business associate agreements

### AI Act Persona
Tests EU AI regulation compliance:
- Risk categorization
- Transparency requirements
- Human oversight
- Data governance
- Technical documentation

### Security Persona
Tests security best practices:
- Authentication/authorization
- Input validation
- Encryption standards
- Logging/monitoring
- Incident response

## CLI Reference

```
aragora gauntlet <input> [options]

Arguments:
  input                 Path to input file (spec, architecture, policy, code)

Options:
  -t, --input-type     Type: spec, architecture, policy, code, strategy, contract
  -p, --profile        Profile: quick, default, thorough, code, policy, gdpr, hipaa, ai_act, security, sox
  -a, --agents         Comma-separated agents (default: anthropic-api,openai-api)
  -o, --output         Output path for decision receipt
  --format             Output format: html, json, md (default: inferred)
  --persona            Regulatory persona (gdpr, hipaa, ai_act, security, soc2, sox, pci_dss, nist_csf)
  --timeout            Maximum duration in seconds (overrides profile)
  --rounds             Deep audit rounds (overrides profile)
  --verify             Enable formal verification (Z3/Lean)
  --no-redteam         Disable red team attacks
  --no-probing         Disable capability probing
  --no-audit           Disable deep audit
```

## Programmatic Usage

```python
from pathlib import Path

from aragora.gauntlet import GauntletRunner, GauntletConfig, AttackCategory
from aragora.receipts import DecisionReceipt

# Configure gauntlet
config = GauntletConfig(
    attack_categories=[AttackCategory.SECURITY, AttackCategory.COMPLIANCE],
    agents=["anthropic-api", "openai-api", "gemini"],
    timeout_seconds=600,
    deep_audit_rounds=3,
)

# Run gauntlet
runner = GauntletRunner(config)
result = await runner.run(spec_content)

# Check verdict
if result.verdict.is_failing:
    print(f"FAILED: {len(result.get_critical_vulnerabilities())} critical findings")

# Generate receipt
receipt = DecisionReceipt.from_result(result)
Path("decision_receipt.html").write_text(receipt.to_html())
```

## Risk Heatmap

Gauntlet generates a risk heatmap showing:

```
           Low    Medium    High
Security    ■■       ■■■      ■
Compliance  ■        ■■       ■■■
Architecture ■■■     ■        ■
Logic       ■■       ■■       ■
```

Access programmatically:
```python
heatmap = result.risk_heatmap
for cell in heatmap.cells:
    print(f"{cell.category}: {cell.severity} ({cell.count} findings)")
```

## Integration Examples

### GitHub Actions
```yaml
- name: Run Gauntlet
  run: |
    aragora gauntlet spec.md \
      --profile thorough \
      --output artifacts/receipt.html

- name: Upload Receipt
  uses: actions/upload-artifact@v4
  with:
    name: decision-receipt
    path: artifacts/receipt.html
```

### Pre-commit Hook
```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: gauntlet
      name: Gauntlet Validation
      entry: aragora gauntlet
      language: system
      files: \.(yaml|md)$
      args: ['--profile', 'quick']
```

### CI Pipeline
```bash
#!/bin/bash
# Run gauntlet and fail pipeline on critical issues
aragora gauntlet spec.md --profile thorough --output receipt.json --format json

CRITICAL=$(jq '.findings | map(select(.severity == "critical")) | length' receipt.json)
if [ "$CRITICAL" -gt 0 ]; then
    echo "Critical issues found: $CRITICAL"
    exit 1
fi
```

## Best Practices

1. **Start with quick profile** for rapid feedback during development
2. **Use thorough profile** before releases or major changes
3. **Store decision receipts** as audit artifacts
4. **Customize attack types** for your domain (security-heavy, compliance-heavy, etc.)
5. **Review CONDITIONAL verdicts** carefully - they indicate real risks
6. **Integrate into CI** to catch issues automatically

## Troubleshooting

### "Gauntlet module not available"
```bash
pip install aragora  # Gauntlet is included in the base install
```

### Timeout errors
```bash
aragora gauntlet input.md --timeout 1800  # Increase timeout to 30 min
```

### Rate limiting
Use OpenRouter fallback:
```bash
export OPENROUTER_API_KEY=your_key
aragora gauntlet input.md --agents anthropic-api,openrouter
```

## Related Documentation

- [Formal Verification](../advanced/formal-verification) - Z3/Lean integration details
- [Security](../security/overview) - Security best practices
- [API Reference](../api/reference) - Full API documentation
