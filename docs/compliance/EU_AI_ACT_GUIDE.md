# EU AI Act Compliance with Aragora

> **The EU AI Act enforcement deadline for high-risk AI systems is August 2, 2026.**
> That gives organizations deploying Annex III AI roughly 5 months to have
> risk management systems, audit trails, transparency documentation, and human
> oversight mechanisms in place -- or face fines of up to **EUR 15 million or 3%
> of global annual turnover.**
>
> Aragora generates the compliance artifacts you need, automatically, from every
> decision your AI system makes.

---

## What Aragora Proves -- Automatically

| EU AI Act Requirement | What Aragora Generates | Article |
|-----------------------|------------------------|---------|
| Risk management system | Decision receipts with risk assessment, confidence scores, adversarial stress-test results | Art. 9 |
| Automatic event logging | Cryptographic provenance chain -- every agent, every round, every vote, timestamped and hashed | Art. 12 |
| Transparency for deployers | Agent identities, reasoning chains, dissent records, consensus rationale | Art. 13 |
| Human oversight capability | HITL/HOTL audit trail, override mechanisms, voting records, escalation paths | Art. 14 |
| Accuracy and robustness | Confidence scores, robustness metrics, integrity hashes, multi-agent consensus | Art. 15 |

**What Aragora cannot generate for you:** Training data governance (Art. 10),
EU database registration (Art. 49), and formal notified-body conformity assessment
(Art. 43). Aragora produces the supporting documentation that feeds those processes.

---

## 2-Minute Quickstart

No API key needed. No server running. Uses synthetic demo data.

```bash
# Install (if not already)
pip install -e .

# Step 1: Classify your AI use case by risk tier
aragora compliance classify \
  "AI-powered CV screening for automated hiring decisions"

# Step 2: Export a compliance bundle (demo mode -- no real debate required)
aragora compliance export \
  --demo \
  --output-dir ./my-compliance-pack

# Step 3: Review what was generated
ls -la ./my-compliance-pack/
cat ./my-compliance-pack/README.md
```

**Expected output from Step 2:**

```
EU AI Act Compliance Bundle
=======================================================
  Regulation:  EU AI Act (Regulation 2024/1689)
  Receipt ID:  DEMO-RCP-001
  Risk Level:  HIGH

  Compliance Score:  87/100 -- Substantially Conformant
  Deadline:          August 2, 2026 (150 days remaining)

  Article        Requirement                                        Status
  -------------- -------------------------------------------------- ------
  Article 9      Identify and analyze known and reasonably fo...    [PASS]
  Article 12     Automatic logging of events with traceability      [PASS]
  Article 13     Identify participating agents, their argument...   [PASS]
  Article 14     Enable human oversight, including ability to...    [PASS]
  Article 15     Appropriate levels of accuracy and robustness...   [PASS]

  Output: ./my-compliance-pack/
    README.md                         Manifest with compliance score
    bundle.json                       Full bundle (all articles, machine-readable)
    receipt.md                 Art. 9  -- Risk assessment
    audit_trail.md             Art. 12 -- Record-keeping & provenance
    transparency_report.md     Art. 13 -- Agent participation & reasoning
    human_oversight.md         Art. 14 -- Human oversight & override
    accuracy_report.md         Art. 15 -- Confidence & robustness
```

For the interactive demo script that walks through all steps:

```bash
./scripts/demo_compliance.sh
```

---

## Table of Contents

1. [What the EU AI Act Requires](#what-the-eu-ai-act-requires)
2. [How Aragora Satisfies Each Requirement](#how-aragora-satisfies-each-requirement)
3. [Generating Compliance Artifacts](#generating-compliance-artifacts)
4. [CLI Commands Reference](#cli-commands-reference)
5. [Python API Reference](#python-api-reference)
6. [Example Artifact Output](#example-artifact-output)
7. [Compliance Timeline](#compliance-timeline)
8. [FAQ](#faq)

---

## What the EU AI Act Requires

The EU AI Act classifies AI systems into four risk tiers. Organizations deploying
**high-risk** AI systems face the most stringent requirements. Aragora's compliance
module focuses on the articles that apply to high-risk systems under Annex III.

### Risk Tiers

| Tier | Description | Aragora Coverage |
|------|-------------|-----------------|
| **Unacceptable** (Art. 5) | Social scoring, subliminal manipulation, real-time biometric ID | Detected and flagged by `RiskClassifier` |
| **High** (Art. 6 + Annex III) | Employment, credit scoring, critical infrastructure, law enforcement, etc. | Full artifact generation (Art. 9, 12, 13, 14, 15) |
| **Limited** (Art. 50) | Chatbots, deepfakes, AI-generated content | Transparency obligations flagged |
| **Minimal** | Spam filters, weather models | No obligations; voluntary codes of conduct |

### Annex III High-Risk Categories

The EU AI Act defines 8 categories of high-risk AI systems:

| # | Category | Examples |
|---|----------|----------|
| 1 | Biometrics | Facial recognition, emotion recognition, iris scans |
| 2 | Critical infrastructure | Power grids, water supply, traffic management |
| 3 | Education and vocational training | Student assessment, exam proctoring, grading |
| 4 | Employment and worker management | CV screening, hiring decisions, performance evaluation |
| 5 | Access to essential services | Credit scoring, insurance risk, benefit eligibility |
| 6 | Law enforcement | Predictive policing, evidence evaluation, profiling |
| 7 | Migration, asylum and border control | Visa processing, border surveillance, risk assessment |
| 8 | Administration of justice | Judicial research, sentencing support, election systems |

### Key Articles for High-Risk Systems

#### Article 9: Risk Management System

Providers must establish, implement, document, and maintain a risk management
system. This includes identifying known and foreseeable risks (Art. 9(2)(a)),
estimating risks from intended use (Art. 9(2)(b)), and evaluating risks from
reasonably foreseeable misuse (Art. 9(2)(c)).

**Aragora maps this to:** Risk summary fields in decision receipts, confidence
scores, and the Gauntlet adversarial stress-testing framework.

#### Article 12: Record-Keeping (Automatic Logging)

High-risk AI systems must technically allow for automatic recording of events
("logs") over the lifetime of the system. Logs must enable traceability of
system functioning and facilitate post-market monitoring.

**Aragora maps this to:** The provenance chain in every decision receipt, with
SHA-256 integrity hashing, plus Annex IV technical documentation and log
retention policies per Art. 26(6).

#### Article 13: Transparency and Provision of Information to Deployers

Systems must be sufficiently transparent for deployers to interpret output
and use it appropriately. Providers must document the system's identity,
intended purpose, accuracy/robustness metrics, known risks, and output
interpretation guidance.

**Aragora maps this to:** Provider identity fields, known risk catalogs,
confidence interpretation context, dissent records, and agent participation
transparency.

#### Article 14: Human Oversight

High-risk systems must be designed for effective human oversight. This includes
enabling humans to understand capabilities and limitations (Art. 14(4)(a)),
correctly interpret output (Art. 14(4)(b)), decide not to use the system
(Art. 14(4)(c)), and intervene or stop the system (Art. 14(4)(d)).

**Aragora maps this to:** Human-in-the-Loop (HITL) or Human-on-the-Loop (HOTL)
oversight models, automation bias safeguards, override capabilities, and
intervention (stop) mechanisms.

#### Article 15: Accuracy, Robustness and Cybersecurity

Systems must achieve appropriate levels of accuracy, robustness, and
cybersecurity, and be resilient to errors, faults, and adversarial attacks.

**Aragora maps this to:** Robustness scores, artifact hash integrity,
cryptographic signatures, and multi-agent consensus metrics.

---

## How Aragora Satisfies Each Requirement

### Risk Classification (Art. 6 + Annex III)

Aragora's `RiskClassifier` automatically classifies AI use cases by matching
descriptions against Annex III categories and Article 5 prohibited practices.

```python
from aragora.compliance.eu_ai_act import RiskClassifier

classifier = RiskClassifier()
result = classifier.classify("AI-powered CV screening for hiring decisions")

print(result.risk_level)          # RiskLevel.HIGH
print(result.annex_iii_category)  # "Employment and worker management"
print(result.annex_iii_number)    # 4
print(result.obligations)         # List of 9 article requirements
```

### Conformity Assessment Reports

The `ConformityReportGenerator` maps decision receipt fields to article
requirements and produces a conformity assessment:

```python
from aragora.compliance.eu_ai_act import ConformityReportGenerator

generator = ConformityReportGenerator()
report = generator.generate(receipt_dict)

print(report.overall_status)   # "conformant", "partial", or "non_conformant"
print(report.to_markdown())    # Human-readable report
print(report.to_json())        # Machine-readable report
```

### Full Artifact Bundles (Art. 12 + 13 + 14)

The `ComplianceArtifactGenerator` produces complete, audit-ready bundles:

```python
from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

generator = ComplianceArtifactGenerator(
    provider_name="Acme Corp",
    provider_contact="compliance@acme.com",
    eu_representative="Acme EU GmbH, Berlin, Germany",
    system_name="Acme Hiring Assistant",
    system_version="2.1.0",
)

bundle = generator.generate(receipt_dict)

# Access individual article artifacts
bundle.article_12  # Record-keeping: event log, tech docs, retention policy
bundle.article_13  # Transparency: provider identity, risks, interpretation
bundle.article_14  # Human oversight: model, safeguards, override, stop

# Integrity verification
print(bundle.integrity_hash)  # SHA-256 hash of bundle contents
```

---

## Generating Compliance Artifacts

### Step 1: Classify Your Use Case

Before generating artifacts, determine the risk level of your AI system:

```bash
aragora compliance classify "AI system for employee performance evaluation and promotion decisions"
```

Output:

```
Risk Level: HIGH
Rationale:  Use case falls under Annex III category 4: Employment and worker
            management. Recruitment, CV screening, performance evaluation, task
            allocation, termination.
Annex III:  4. Employment and worker management
Keywords:   performance evaluation, promotion decision

Applicable Articles:
  - Article 6 (Classification)
  - Article 9 (Risk management)
  - Article 13 (Transparency)
  - Article 14 (Human oversight)
  - Article 15 (Accuracy, robustness, cybersecurity)

Obligations:
  - Establish and maintain a risk management system (Art. 9).
  - Use high-quality training, validation, and testing data (Art. 10).
  - Maintain technical documentation (Art. 11).
  - Implement automatic logging of events (Art. 12).
  - Ensure transparency and provide instructions for deployers (Art. 13).
  - Design for effective human oversight (Art. 14).
  - Achieve appropriate accuracy, robustness, and cybersecurity (Art. 15).
  - Register in the EU database before placing on market (Art. 49).
  - Undergo conformity assessment (Art. 43).
```

### Step 2: Run a Decision Through Aragora

Run your AI decision through Aragora's debate engine to produce a decision
receipt:

```bash
aragora ask "Should we deploy the hiring algorithm?" \
    --agents anthropic-api,openai-api,mistral,gemini \
    --rounds 3 \
    --decision-integrity
```

Or use the full pipeline:

```bash
aragora decide "Evaluate hiring algorithm for bias compliance" \
    --agents anthropic-api,openai-api,mistral,gemini \
    --auto-approve
```

### Step 3: Export a Compliance Bundle

Export a structured compliance bundle for any debate:

```bash
# From a debate ID (after running aragora ask/decide)
aragora compliance export \
    --debate-id <DEBATE_ID> \
    --output-dir ./compliance-pack

# From a saved receipt file
aragora compliance export \
    --receipt-file ./receipt.json \
    --output-dir ./compliance-pack

# Demo mode (no real debate needed -- runs in 30 seconds)
aragora compliance export \
    --demo \
    --output-dir ./compliance-pack
```

This produces:

```
compliance-pack/
  README.md                     Manifest with compliance score and article mapping
  bundle.json                   Full bundle (all articles, machine-readable)
  receipt.md                    Art. 9  -- Risk assessment
  audit_trail.md                Art. 12 -- Event log & provenance chain
  transparency_report.md        Art. 13 -- Agent participation & reasoning
  human_oversight.md            Art. 14 -- Override capability & voting record
  accuracy_report.md            Art. 15 -- Confidence & robustness metrics
```

### Step 4: Generate Conformity Report (Optional Deep-Dive)

Generate a standalone conformity assessment from a saved receipt:

```bash
# Markdown output (human-readable)
aragora compliance audit receipt.json --format markdown --output report.md

# JSON output (machine-readable)
aragora compliance audit receipt.json --format json --output report.json
```

### Step 5: Generate Full Artifact Bundle (Regulator Submission)

For submissions requiring dedicated per-article files with Annex IV documentation:

```bash
aragora compliance eu-ai-act generate receipt.json \
    --output ./compliance-bundle/ \
    --provider-name "Acme Corp" \
    --provider-contact "compliance@acme.com" \
    --eu-representative "Acme EU GmbH, Berlin" \
    --system-name "Acme Hiring Assistant" \
    --system-version "2.1.0"
```

This produces:

```
compliance-bundle/
  compliance_bundle.json          # Full artifact bundle (all articles)
  article_12_record_keeping.json  # Event log, tech docs, retention policy
  article_13_transparency.json    # Provider identity, risks, interpretation
  article_14_human_oversight.json # Oversight model, override, stop mechanisms
  conformity_report.md            # Human-readable conformity assessment
  conformity_report.json          # Machine-readable conformity assessment
```

---

## CLI Commands Reference

### `aragora compliance classify <description>`

Classify a free-text AI use case description by EU AI Act risk level.

| Flag | Description |
|------|-------------|
| `description` | Free-text description of the AI use case (required) |

### `aragora compliance export`

Export a structured compliance bundle mapping debate artifacts to EU AI Act articles.
Includes a compliance readiness score and per-article markdown/HTML reports.

| Flag | Description |
|------|-------------|
| `--debate-id` | Debate ID to export compliance pack for |
| `--receipt-file` | Path to an existing receipt JSON file |
| `--output-dir` | Output directory (default: `./compliance-pack`) |
| `--format` | Output format: `markdown`, `html`, or `json` (default: markdown) |
| `--demo` | Generate a sample bundle from synthetic data (no real debate needed) |

### `aragora compliance audit <receipt_file>`

Generate an EU AI Act conformity report from a decision receipt JSON file.

| Flag | Description |
|------|-------------|
| `receipt_file` | Path to a DecisionReceipt JSON file (required) |
| `--format` | Output format: `json` or `markdown` (default: markdown) |
| `--output`, `-o` | Write report to file instead of stdout |

### `aragora compliance eu-ai-act generate [receipt_file]`

Generate a complete EU AI Act compliance artifact bundle with per-article JSON files.

| Flag | Description |
|------|-------------|
| `receipt_file` | Path to a DecisionReceipt JSON file (optional; omit for demo) |
| `--output`, `-o` | Output directory (default: `./compliance-bundle/`) |
| `--provider-name` | Organization name for provider identity |
| `--provider-contact` | Contact email for compliance inquiries |
| `--eu-representative` | EU authorized representative (non-EU providers) |
| `--system-name` | Name of the AI system under assessment |
| `--system-version` | Version of the AI system |
| `--format` | `json` for bundle only, `all` for bundle + per-article files (default: all) |

---

## Python API Reference

### `RiskClassifier`

```python
from aragora.compliance.eu_ai_act import RiskClassifier, RiskLevel

classifier = RiskClassifier()

# Classify from free text
result = classifier.classify("credit scoring for loan applications")
assert result.risk_level == RiskLevel.HIGH
assert result.annex_iii_number == 5

# Classify from a receipt dict
result = classifier.classify_receipt(receipt_dict)
```

### `ConformityReportGenerator`

```python
from aragora.compliance.eu_ai_act import ConformityReportGenerator

generator = ConformityReportGenerator()
report = generator.generate(receipt_dict)

report.overall_status       # "conformant", "partial", "non_conformant"
report.article_mappings     # List of ArticleMapping objects
report.recommendations      # List of improvement suggestions
report.integrity_hash       # SHA-256 hash for tamper detection

report.to_json()            # Machine-readable JSON string
report.to_markdown()        # Human-readable markdown string
```

### `ComplianceArtifactGenerator`

```python
from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

generator = ComplianceArtifactGenerator(
    provider_name="Your Org",
    provider_contact="compliance@your-org.com",
    eu_representative="Your EU Rep GmbH",
    system_name="Decision Platform",
    system_version="1.0.0",
)

bundle = generator.generate(receipt_dict)

bundle.bundle_id            # "EUAIA-xxxxxxxx"
bundle.integrity_hash       # SHA-256 of bundle contents
bundle.risk_classification  # RiskClassification object
bundle.conformity_report    # ConformityReport object
bundle.article_12           # Article12Artifact
bundle.article_13           # Article13Artifact
bundle.article_14           # Article14Artifact

bundle.to_json()            # Full bundle as JSON string
bundle.to_dict()            # Full bundle as Python dict
```

### Key Data Classes

| Class | Article | Contents |
|-------|---------|----------|
| `Article12Artifact` | Art. 12 (Record-Keeping) | `event_log`, `reference_databases`, `input_record`, `technical_documentation`, `retention_policy` |
| `Article13Artifact` | Art. 13 (Transparency) | `provider_identity`, `intended_purpose`, `accuracy_robustness`, `known_risks`, `output_interpretation`, `human_oversight_reference` |
| `Article14Artifact` | Art. 14 (Human Oversight) | `oversight_model`, `understanding_monitoring`, `automation_bias_safeguards`, `interpretation_features`, `override_capability`, `intervention_capability` |
| `ComplianceArtifactBundle` | All | Combines all artifacts with `integrity_hash` |
| `ConformityReport` | All | Article-by-article compliance status with recommendations |
| `RiskClassification` | Art. 6 | `risk_level`, `annex_iii_category`, `obligations` |

---

## Example Artifact Output

### Bundle Structure (JSON)

Below is an abbreviated example of what `bundle.json` looks like:

```json
{
  "meta": {
    "framework": "eu-ai-act",
    "receipt_id": "RCP-HR-2026-0041",
    "generated_at": "2026-02-12T10:15:00.000000+00:00",
    "integrity_hash": "6f32616ade73e6ab7fd470dbe0c2f92ef617e2d9049a6ea98506eb34a4461066",
    "compliance_deadline": "2026-08-02",
    "days_until_deadline": 171,
    "regulation": "EU AI Act (Regulation 2024/1689)",
    "generated_by": "Aragora Decision Integrity Platform"
  },
  "compliance_score": {
    "score": 87,
    "level": "substantial",
    "label": "Substantially Conformant",
    "breakdown": {
      "pass": ["Article 9", "Article 12", "Article 13", "Article 14"],
      "partial": ["Article 15"],
      "fail": []
    }
  },
  "risk_classification": {
    "risk_level": "high",
    "annex_iii_category": "Employment and worker management",
    "annex_iii_number": 4,
    "obligations": ["Establish and maintain a risk management system (Art. 9).", "..."]
  },
  "conformity_report": {
    "overall_status": "conformant",
    "article_mappings": [
      {
        "article": "Article 9",
        "status": "satisfied",
        "evidence": "Risk assessment performed: 5 risks identified (0 critical). Confidence: 78.0%."
      },
      {
        "article": "Article 12",
        "status": "satisfied",
        "evidence": "Provenance chain contains 10 events."
      },
      {
        "article": "Article 13",
        "status": "satisfied",
        "evidence": "4 agents participated. Verdict reasoning logged."
      },
      {
        "article": "Article 14",
        "status": "satisfied",
        "evidence": "Human approval/override mechanism detected."
      },
      {
        "article": "Article 15",
        "status": "satisfied",
        "evidence": "Robustness score: 72.0%. Integrity hash: present."
      }
    ]
  }
}
```

### Bundle Manifest (README.md)

The `README.md` manifest looks like this:

```markdown
# EU AI Act Compliance Bundle

> Generated by Aragora Decision Integrity Platform -- EU AI Act (Regulation 2024/1689)

## Compliance Readiness

  Score:   87/100  [=========-]  Substantially Conformant
  Risk:    HIGH
  Status:  CONFORMANT
  Deadline: August 2, 2026  (171 days remaining)

- Passing: Article 9, Article 12, Article 13, Article 14
- Partial: Article 15
- Failing: --

## Bundle Contents

| File | EU AI Act Article | What It Proves |
|------|-------------------|----------------|
| bundle.json | All | Complete machine-readable compliance record |
| receipt.md | Article 9 | Risk assessment, confidence, robustness score |
| audit_trail.md | Article 12 | Event log -- who did what and when |
| transparency_report.md | Article 13 | Agent identities, reasoning chain, dissent |
| human_oversight.md | Article 14 | Override capability, voting record, escalation |
| accuracy_report.md | Article 15 | Confidence metrics, robustness, integrity hash |
```

---

## Compliance Timeline

### What Organizations Need to Do Before August 2, 2026

| When | Action | Aragora Feature |
|------|--------|----------------|
| **Now** | Classify your AI systems by risk level | `aragora compliance classify` |
| **Now** | Inventory all AI use cases against Annex III | `RiskClassifier` API |
| **Q2 2026** | Run adversarial stress tests on high-risk systems | `aragora gauntlet` |
| **Q2 2026** | Generate compliance artifact bundles | `aragora compliance export` |
| **Q2 2026** | Establish human oversight procedures | Debate engine with approval gates |
| **Q2 2026** | Configure log retention (min. 6 months) | Art. 12 retention policy artifacts |
| **Q2 2026** | Designate EU authorized representative (if non-EU) | `--eu-representative` flag |
| **Q3 2026** | Register in EU database (Art. 49) | Conformity report provides supporting docs |
| **Q3 2026** | Undergo conformity assessment (Art. 43) | Artifact bundles provide assessment input |
| **Aug 2, 2026** | Full enforcement begins | Ongoing artifact generation |

### Key Dates

| Date | Milestone |
|------|-----------|
| August 1, 2024 | EU AI Act entered into force |
| February 2, 2025 | Prohibitions on unacceptable-risk AI apply |
| August 2, 2025 | Governance rules and general-purpose AI obligations |
| **August 2, 2026** | **Full enforcement for Annex III high-risk AI** |
| August 2, 2027 | Obligations for Annex I (product safety) high-risk AI |

### Penalties for Non-Compliance (Article 72)

| Violation | Maximum Fine |
|-----------|-------------|
| Prohibited AI practices (Art. 5) | EUR 35M or 7% of global turnover |
| High-risk non-compliance | EUR 15M or 3% of global turnover |
| Providing incorrect information | EUR 7.5M or 1% of global turnover |

---

## FAQ

### Q: Does Aragora itself qualify as a high-risk AI system?

Aragora is a decision *support* platform -- it orchestrates adversarial debate
among AI models and produces receipts, but does not make autonomous decisions.
The risk classification depends on the *use case* it is deployed for. An HR
department using Aragora to vet hiring decisions would fall under Annex III
Category 4 (Employment). A team using it for internal code review would not.

### Q: What if my use case is classified as "unacceptable"?

The EU AI Act prohibits certain AI practices entirely under Article 5. If
`RiskClassifier` returns `UNACCEPTABLE`, the practice is banned and cannot be
deployed in the EU regardless of compliance measures. Aragora will flag this
and list the specific prohibition triggered.

### Q: Do I need to generate artifacts for every decision?

For high-risk systems, Article 12 requires automatic logging of events over the
system's lifetime. Aragora generates receipts automatically for every debate.
You should generate compliance artifact bundles periodically (e.g., monthly)
or on demand for specific decisions that require regulatory review.

### Q: Can I use Aragora's artifacts for conformity assessment under Art. 43?

Aragora's artifact bundles provide substantial supporting documentation for
a conformity assessment. However, formal conformity assessment must be
performed by a notified body or through internal procedures depending on the
AI system category. The artifacts serve as input to this process, not a
substitute for it.

### Q: What about Article 10 (Data Governance)?

Article 10 covers training data quality, bias testing, and data governance.
Aragora does not train AI models -- it orchestrates debate among pre-trained
models from different providers. Data governance obligations for training data
fall on the model providers (Anthropic, OpenAI, Google, etc.). Aragora's
contribution is in the decision-making layer: multi-model consensus reduces
single-provider bias, and the Gauntlet stress-testing framework tests for
fairness across demographic groups.

### Q: What is the difference between `export` and `eu-ai-act generate`?

- `aragora compliance export` -- structured bundle with per-article markdown/HTML
  reports and a compliance readiness score. Best for **review by compliance
  officers and legal teams** during day-to-day operations.
- `aragora compliance eu-ai-act generate` -- dedicated Art. 12, 13, and 14
  JSON artifacts plus a formal conformity report. Best for **submission to
  regulators or notified bodies**.

Use `export` for ongoing monitoring and review. Use `eu-ai-act generate`
when preparing formal documentation for regulatory submission.

### Q: How do I verify the integrity of a compliance bundle?

Every bundle includes an `integrity_hash` field -- a SHA-256 hash computed from
the bundle ID, receipt ID, risk level, and conformity status. Recalculate the
hash and compare to detect tampering. The conformity report also has its own
independent integrity hash.

### Q: Where should I store compliance artifacts?

Store artifacts in a tamper-evident system with access controls. Options include:

- Aragora's Knowledge Mound (built-in, with SHA-256 integrity)
- An enterprise document management system
- A dedicated compliance repository with audit logging

Article 26(6) requires deployers to retain automatically generated logs for
a minimum of 6 months. Aragora's retention policy artifact documents this
requirement.

### Q: What compliance score do I need?

The `compliance_score` in the bundle is Aragora's readiness indicator, not
an official regulatory score. It reflects how many article requirements are
satisfied (100%), partially satisfied (50%), or not satisfied (0%):

| Score | Label | Interpretation |
|-------|-------|----------------|
| 95-100 | Full Conformity | All articles satisfied; ready for submission |
| 75-94 | Substantially Conformant | Minor gaps; review recommendations |
| 40-74 | Partial Conformity | Material gaps; remediation required |
| 0-39 | Not Ready | Significant gaps; engage compliance counsel |

---

## Related Documentation

- [Enterprise Compliance Guide](../enterprise/COMPLIANCE.md) -- Operational controls and governance model
- [API Reference](../api/API_REFERENCE.md) -- REST API documentation
- [Gauntlet Testing](../../aragora/gauntlet/README.md) -- Adversarial stress testing
- [Decision Receipts](../reference/CLI_REFERENCE.md) -- Receipt command and verification workflow
- [Demo Script](../../scripts/demo_compliance.sh) -- End-to-end walkthrough in 2 minutes
