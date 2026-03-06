# EU AI Act Compliance Playbook

> For enterprise customers deploying AI decision-making systems in the EU.
> **Deadline: August 2, 2026** -- full enforcement for high-risk AI systems.

---

## The Problem

The **EU AI Act** (Regulation 2024/1689) enters full enforcement for high-risk AI systems on **August 2, 2026**. If your organization uses AI for hiring, credit scoring, critical infrastructure, law enforcement, or any Annex III domain, you must prove compliance with five core articles -- or face fines of up to **EUR 15 million or 3% of global annual turnover**.

The five requirements you must satisfy:

| # | Article | What You Must Prove |
|---|---------|---------------------|
| 1 | **Art. 9** | You have a documented risk management system |
| 2 | **Art. 12** | Every AI decision is automatically logged with traceability |
| 3 | **Art. 13** | Deployers can understand how the AI reached its conclusion |
| 4 | **Art. 14** | A human can override, intervene, or stop the system |
| 5 | **Art. 15** | The system meets accuracy and robustness standards |

These are not future obligations. Organizations must have documentation infrastructure in place by the enforcement date.

## Why Aragora

Most compliance tools generate reports *about* your AI. Aragora generates compliance evidence *from* your AI -- automatically, at decision time, with no manual documentation burden.

Every decision that passes through Aragora's multi-agent debate engine produces a **decision receipt**: a cryptographically signed record containing the full provenance chain, agent participation, voting records, confidence scores, and risk assessments. The compliance module maps these receipts directly to EU AI Act article requirements and produces audit-ready bundles.

**What this means for your team:**
- **Zero manual documentation** -- compliance artifacts are generated as a side effect of using the platform
- **Regulator-ready output** -- per-article files with SHA-256 integrity hashes, ready for notified-body review
- **Continuous compliance** -- every decision is logged, not just the ones you remember to document
- **5 minutes to first bundle** -- classify your use case and generate a demo bundle with two CLI commands

---

## What You Get

Each compliance bundle contains per-article files and a machine-readable master record:

| File | Article | What It Proves |
|------|---------|----------------|
| `receipt.md` | Art. 9 | Risk assessment with confidence scores and robustness metrics |
| `risk_management.md` | Art. 9 | Risk management system, known risks, mitigations, residual risk |
| `audit_trail.md` | Art. 12 | Chronological event log with timestamps, actors, and integrity hashes |
| `transparency_report.md` | Art. 13 | Agent identities, reasoning chains, dissent records, consensus method |
| `human_oversight.md` | Art. 14 | Oversight model (HITL/HOTL), voting record, override/stop capabilities |
| `accuracy_report.md` | Art. 15 | Confidence metrics, robustness score, adversarial test results |
| `bundle.json` | All | Complete machine-readable bundle with SHA-256 integrity hash |

Every bundle includes a **compliance readiness score** (0--100) indicating how thoroughly the decision artifacts satisfy each article's requirements.

---

## Getting Started in 5 Minutes

No API keys required. No server needed. Copy-paste these three commands.

### 1. Classify your AI use case

```bash
aragora compliance classify \
  "AI-powered CV screening for automated hiring decisions"
```

Returns: risk tier (UNACCEPTABLE / HIGH / LIMITED / MINIMAL), the Annex III category, and which articles apply to you.

### 2. Generate a compliance bundle

```bash
# Demo mode -- synthetic data, works immediately
aragora compliance export --demo --output-dir ./my-compliance-pack
```

For real decisions, use one of:

```bash
# From a completed debate
aragora compliance export --debate-id <DEBATE_ID> --output-dir ./compliance-pack

# From a saved receipt file
aragora compliance export --receipt-file ./receipt.json --output-dir ./compliance-pack
```

### 3. Review your compliance score

```bash
cat ./my-compliance-pack/README.md
```

You will see a compliance readiness score with pass/partial/fail per article, days remaining until the deadline, and recommendations for any gaps.

### 4. Generate regulator-ready artifacts (when needed)

For formal submissions to notified bodies:

```bash
aragora compliance eu-ai-act generate receipt.json \
  --output ./compliance-bundle/ \
  --provider-name "Your Organization" \
  --provider-contact "compliance@your-org.com" \
  --eu-representative "Your EU Rep GmbH, Berlin" \
  --system-name "Decision Platform" \
  --system-version "2.1.0"
```

Produces `article_12_record_keeping.json`, `article_13_transparency.json`, `article_14_human_oversight.json`, and formal conformity reports.

### 5. Make it ongoing

```bash
# After each high-stakes decision
aragora compliance export --debate-id <ID> --output-dir ./compliance-pack

# Periodic standalone audit
aragora compliance audit receipt.json --format markdown --output report.md

# Build your Annex III risk register
aragora compliance classify "description of each AI use case"
```

---

## Article-by-Article Coverage

| Article | Requirement | Aragora Artifact | What It Proves |
|---------|-------------|------------------|----------------|
| **Art. 9** | Risk management system | `receipt.md`, `risk_management.md` | Risks identified and assessed; confidence and robustness scores; adversarial stress-test results; residual risk level |
| **Art. 12** | Automatic event logging | `audit_trail.md` | SHA-256 hash chain of every event (proposals, critiques, votes, approvals); protocol and round count; retention policy reference |
| **Art. 13** | Transparency for deployers | `transparency_report.md` | Agent identities and model providers; reasoning chain and verdict rationale; dissent records; consensus method and agreement ratio |
| **Art. 14** | Human oversight | `human_oversight.md` | HITL/HOTL oversight model; human approval events; voting record; override and intervention (stop) capabilities; escalation paths |
| **Art. 15** | Accuracy and robustness | `accuracy_report.md` | Confidence score; robustness score; integrity hash verification; adversarial attacks attempted vs. successful; cryptographic signature |

### Shared Responsibility: What Aragora Covers vs. What You Own

The EU AI Act places obligations on both **providers** (those who build the AI) and **deployers** (those who use it). Aragora handles the platform-level evidence generation. Four articles require action from your organization:

| Article | Requirement | Who Owns It | How Aragora Helps |
|---------|-------------|-------------|-------------------|
| **Art. 10** | Training data governance | **Model providers** (Anthropic, OpenAI, Google, etc.) | Aragora mitigates single-provider bias through multi-model consensus. You do not train models -- your providers do. |
| **Art. 11** | Technical documentation (Annex IV) | **Your organization** | Aragora generates per-article artifacts that form the core of your technical file. You maintain the overall document and organizational context. |
| **Art. 43** | Conformity assessment | **Your organization** + notified body | Aragora bundles provide structured input for a conformity assessment. The formal assessment is performed by a notified body or through your internal procedure. |
| **Art. 49** | EU database registration | **Your organization** | Registration is your obligation. Aragora conformity reports provide the supporting documentation you need to complete it. |

**Bottom line:** Aragora automates the evidence layer (Art. 9, 12, 13, 14, 15). Your compliance and legal teams own the organizational layer (Art. 11, 43, 49). Model providers own the training layer (Art. 10).

---

## Countdown to August 2, 2026: What to Do When

| When | What to Do | CLI Command |
|------|-----------|-------------|
| **Now** | Classify all your AI use cases by risk tier | `aragora compliance classify "your use case"` |
| **Now** | Generate a demo bundle to see what output looks like | `aragora compliance export --demo --output-dir ./demo-pack` |
| **Apr 2026** | Run adversarial stress tests on high-risk systems | `aragora gauntlet run --suite fairness` |
| **Apr 2026** | Generate compliance bundles for each high-risk system | `aragora compliance export --debate-id <ID> --output-dir ./pack` |
| **May 2026** | Establish human oversight procedures and document them | Configure HITL/HOTL in debate protocol |
| **May 2026** | Designate EU authorized representative (if non-EU org) | `--eu-representative` flag on `eu-ai-act generate` |
| **Jun 2026** | Generate formal regulator-ready artifact bundles | `aragora compliance eu-ai-act generate receipt.json --output ./bundle/` |
| **Jun 2026** | Configure log retention (Art. 12 requires min. 6 months) | Retention policy in Art. 12 artifact |
| **Jul 2026** | Register in EU database (Art. 49) | Use conformity reports as supporting documentation |
| **Jul 2026** | Complete conformity assessment (Art. 43) | Submit artifact bundles to notified body |
| **Aug 2, 2026** | **Full enforcement begins** | `aragora compliance export` on every decision going forward |

### Penalties for Non-Compliance

| Violation | Maximum Fine |
|-----------|-------------|
| Prohibited AI practices (Art. 5) | EUR 35M or 7% of global turnover |
| High-risk non-compliance (Art. 9-15) | EUR 15M or 3% of global turnover |
| Providing incorrect information | EUR 7.5M or 1% of global turnover |

---

## CLI Quick Reference

All compliance commands at a glance:

```bash
# Classify risk tier
aragora compliance classify "your AI use case description"

# Export compliance bundle (3 input modes)
aragora compliance export --demo --output-dir ./pack              # demo
aragora compliance export --debate-id <ID> --output-dir ./pack    # from debate
aragora compliance export --receipt-file r.json --output-dir ./pack # from receipt

# Standalone conformity audit
aragora compliance audit receipt.json --format markdown --output report.md

# Full regulator submission bundle
aragora compliance eu-ai-act generate receipt.json \
  --output ./bundle/ \
  --provider-name "Org" \
  --provider-contact "compliance@org.com" \
  --system-name "System" \
  --system-version "1.0"

# Check compliance status
aragora compliance status
aragora compliance report
aragora compliance check
```

---

## FAQ

**Does Aragora replace legal counsel?**
No. Aragora generates the technical compliance artifacts that your legal and compliance teams need. It does not provide legal advice, determine your organization's risk classification, or substitute for a conformity assessment. Use Aragora's artifacts as input to your compliance program, not as a replacement for it.

**What if my AI system is classified as "unacceptable risk"?**
Article 5 prohibits certain AI practices entirely (social scoring, subliminal manipulation, real-time biometric identification in public spaces). If `aragora compliance classify` returns UNACCEPTABLE, the practice is banned in the EU regardless of documentation. Aragora flags this and identifies the specific prohibition triggered.

**How does Aragora handle high-risk classification under Article 6?**
The `RiskClassifier` matches your use-case description against all 8 Annex III categories using keyword and semantic matching. It returns the matched category, applicable articles, and obligations. You should validate this classification with your legal team -- Aragora's classification is a starting point, not a legal determination.

**Do I need to generate a bundle for every decision?**
Article 12 requires automatic logging over the system's lifetime. Aragora logs every debate automatically. Generate formal compliance bundles periodically (e.g., monthly) or on demand for decisions subject to regulatory review. The `bundle.json` is designed for bulk storage and automated processing.

**What compliance score do I need?**
The score is Aragora's readiness indicator, not an official regulatory metric. 95--100 indicates full conformity across all articles. 75--94 indicates minor gaps worth reviewing. Below 75 indicates material gaps requiring remediation before submission. The score reflects the presence and completeness of required evidence fields.

**How do I verify bundle integrity?**
Every bundle includes an `integrity_hash` (SHA-256) computed from the receipt ID, framework, timestamp, risk classification, and conformity status. Recalculate the hash from `bundle.json` and compare to detect tampering. The underlying decision receipt also carries its own `artifact_hash` and cryptographic `signature`.

**Where should compliance bundles be stored?**
Store bundles in a system with access controls and tamper detection. Options include Aragora's Knowledge Mound (built-in SHA-256 integrity), an enterprise document management system, or a dedicated compliance repository. Article 26(6) requires deployers to retain automatically generated logs for a minimum of 6 months.

**What is the difference between `export` and `eu-ai-act generate`?**
`aragora compliance export` produces per-article markdown/HTML reports with a compliance readiness score -- best for day-to-day review by compliance officers. `aragora compliance eu-ai-act generate` produces formal Article 12/13/14 JSON artifacts and conformity reports -- best for regulator submissions and notified-body assessments. Use both as appropriate.

---

## Next Steps

- **Try it now:** `aragora compliance export --demo --output-dir ./demo-pack`
- **See it live:** [aragora.ai/demo](https://aragora.ai/demo)
- **Full technical reference:** [EU AI Act Compliance Guide](./EU_AI_ACT_GUIDE.md)
- **Interactive walkthrough:** `./scripts/demo_compliance.sh`
- **Questions:** sales@aragora.ai
