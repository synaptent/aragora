# EU AI Act Compliance Playbook

> For enterprise customers deploying AI decision-making systems in the EU.

---

## Why This Matters

The **EU AI Act** (Regulation 2024/1689) enters full enforcement for high-risk AI systems on **August 2, 2026**. Organizations deploying AI in domains such as hiring, credit scoring, critical infrastructure, or law enforcement must demonstrate compliance with Articles 9, 12, 13, 14, and 15 -- or face fines of up to EUR 15 million or 3% of global annual turnover.

Article 6(1) requires providers and deployers of high-risk AI systems to maintain:
- A documented risk management system (Art. 9)
- Automatic event logging with traceability (Art. 12)
- Transparency documentation for deployers (Art. 13)
- Human oversight mechanisms (Art. 14)
- Evidence of accuracy and robustness (Art. 15)

These are not future obligations. Organizations must have documentation infrastructure in place by the enforcement date.

---

## What Aragora Provides

Aragora generates compliance artifacts automatically from every AI decision that passes through its debate engine. Each decision produces a **decision receipt** -- a cryptographically signed record containing the provenance chain, agent participation, voting records, confidence scores, and risk assessments.

The compliance module maps these receipts to EU AI Act article requirements and produces audit-ready bundles:

| Artifact | Article | Contents |
|----------|---------|----------|
| `receipt.md` | Art. 9 | Risk assessment with confidence scores and robustness metrics |
| `risk_management.md` | Art. 9 | Risk management system, known risks, mitigations, residual risk |
| `audit_trail.md` | Art. 12 | Chronological event log with timestamps, actors, and integrity hashes |
| `transparency_report.md` | Art. 13 | Agent identities, reasoning chains, dissent records, consensus method |
| `human_oversight.md` | Art. 14 | Oversight model (HITL/HOTL), voting record, override/stop capabilities |
| `accuracy_report.md` | Art. 15 | Confidence metrics, robustness score, adversarial test results |
| `bundle.json` | All | Complete machine-readable bundle with SHA-256 integrity hash |

Every bundle includes a **compliance readiness score** (0--100) indicating how thoroughly the decision artifacts satisfy each article's requirements.

---

## How to Use It

### Step 1: Classify Your AI Use Case

Determine whether your system falls under Annex III high-risk categories:

```bash
aragora compliance classify \
  "AI-powered CV screening for automated hiring decisions"
```

This returns the risk tier (UNACCEPTABLE / HIGH / LIMITED / MINIMAL), the applicable Annex III category, and the list of articles you must comply with.

### Step 2: Generate a Compliance Bundle

Three input modes are available:

```bash
# From a completed debate
aragora compliance export \
  --debate-id <DEBATE_ID> \
  --output-dir ./compliance-pack

# From a saved receipt file
aragora compliance export \
  --receipt-file ./receipt.json \
  --output-dir ./compliance-pack

# Demo mode (synthetic data, no API keys required)
aragora compliance export \
  --demo \
  --output-dir ./compliance-pack
```

The bundle is written to the output directory with per-article files in your chosen format (`--format markdown`, `html`, or `json`).

### Step 3: Review the Bundle

Open `README.md` in the output directory. It contains:
- Compliance readiness score with pass/partial/fail breakdown per article
- Days remaining until the enforcement deadline
- Table of all generated files with their article mappings
- Recommendations for any gaps detected

### Step 4: Generate Regulator-Ready Artifacts (Optional)

For formal submissions requiring dedicated per-article JSON files with Annex IV documentation:

```bash
aragora compliance eu-ai-act generate receipt.json \
  --output ./compliance-bundle/ \
  --provider-name "Your Organization" \
  --provider-contact "compliance@your-org.com" \
  --eu-representative "Your EU Rep GmbH, Berlin" \
  --system-name "Decision Platform" \
  --system-version "2.1.0"
```

This produces `article_12_record_keeping.json`, `article_13_transparency.json`, `article_14_human_oversight.json`, and formal conformity reports.

### Step 5: Integrate Into Your Compliance Program

- **Ongoing monitoring:** Run `aragora compliance export` after each high-stakes decision. Store bundles in a tamper-evident system.
- **Periodic audits:** Use `aragora compliance audit receipt.json` to generate standalone conformity assessments.
- **Risk inventory:** Use `aragora compliance classify` across all your AI use cases to build an Annex III risk register.

---

## Article-by-Article Coverage

| Article | Requirement | Aragora Artifact | What It Proves |
|---------|-------------|------------------|----------------|
| **Art. 9** | Risk management system | `receipt.md`, `risk_management.md` | Risks identified and assessed; confidence and robustness scores; adversarial stress-test results; residual risk level |
| **Art. 12** | Automatic event logging | `audit_trail.md` | SHA-256 hash chain of every event (proposals, critiques, votes, approvals); protocol and round count; retention policy reference |
| **Art. 13** | Transparency for deployers | `transparency_report.md` | Agent identities and model providers; reasoning chain and verdict rationale; dissent records; consensus method and agreement ratio |
| **Art. 14** | Human oversight | `human_oversight.md` | HITL/HOTL oversight model; human approval events; voting record; override and intervention (stop) capabilities; escalation paths |
| **Art. 15** | Accuracy and robustness | `accuracy_report.md` | Confidence score; robustness score; integrity hash verification; adversarial attacks attempted vs. successful; cryptographic signature |

**Not covered by Aragora (requires your organization):**

| Article | Requirement | Your Responsibility |
|---------|-------------|---------------------|
| Art. 10 | Training data governance | Obligation falls on model providers (Anthropic, OpenAI, etc.). Aragora mitigates single-provider bias through multi-model consensus. |
| Art. 11 | Technical documentation | Aragora generates supporting artifacts; your organization maintains the overall technical file. |
| Art. 43 | Conformity assessment | Formal assessment by a notified body or internal procedure. Aragora bundles provide input to this process. |
| Art. 49 | EU database registration | Registration is your obligation; conformity reports provide supporting documentation. |

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

*For the full technical reference, see [EU AI Act Compliance Guide](./EU_AI_ACT_GUIDE.md). For the interactive demo, run `./scripts/demo_compliance.sh`.*
