# EU AI Act Compliance with Aragora

> Comprehensive guide to generating audit-ready compliance artifacts for the
> EU AI Act (Regulation (EU) 2024/1689) using the Aragora Decision Integrity
> Platform. Enforcement deadline for high-risk AI systems: **August 2, 2026**.

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
| **High** (Art. 6 + Annex III) | Employment, credit scoring, critical infrastructure, law enforcement, etc. | Artifact bundles generated for Art. 12 (Record-keeping), 13 (Transparency), 14 (Human Oversight). Article 9 (Risk Management) conformity checking included in the compliance report. |
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

### Step 3: Generate Conformity Report

Generate a conformity assessment from a saved receipt:

```bash
# Markdown output (human-readable)
aragora compliance audit receipt.json --format markdown --output report.md

# JSON output (machine-readable)
aragora compliance audit receipt.json --format json --output report.json
```

### Step 4: Generate Full Artifact Bundle

Generate the complete compliance artifact bundle:

```bash
aragora compliance eu-ai-act generate receipt.json \
    --output ./compliance-bundle/ \
    --provider-name "Acme Corp" \
    --provider-contact "compliance@acme.com" \
    --eu-representative "Acme EU GmbH, Berlin" \
    --system-name "Acme Hiring Assistant" \
    --system-version "2.1.0"
```

This produces the following files:

```
compliance-bundle/
  compliance_bundle.json          # Full artifact bundle (all articles)
  article_12_record_keeping.json  # Event log, tech docs, retention policy
  article_13_transparency.json    # Provider identity, risks, interpretation
  article_14_human_oversight.json # Oversight model, override, stop mechanisms
  conformity_report.md            # Human-readable conformity assessment
  conformity_report.json          # Machine-readable conformity assessment
```

### Step 5 (Optional): Generate Demo Bundle

To see what the output looks like without a real receipt, omit the receipt file:

```bash
aragora compliance eu-ai-act generate --output ./demo-bundle/
```

This generates a bundle from synthetic data so you can review the artifact
structure before integrating with your production pipeline.

---

## CLI Commands Reference

### `aragora compliance classify <description>`

Classify a free-text AI use case description by EU AI Act risk level.

| Flag | Description |
|------|-------------|
| `description` | Free-text description of the AI use case (required) |

### `aragora compliance audit <receipt_file>`

Generate an EU AI Act conformity report from a decision receipt JSON file.

| Flag | Description |
|------|-------------|
| `receipt_file` | Path to a DecisionReceipt JSON file (required) |
| `--format` | Output format: `json` or `markdown` (default: markdown) |
| `--output`, `-o` | Write report to file instead of stdout |

### `aragora compliance eu-ai-act generate [receipt_file]`

Generate a complete EU AI Act compliance artifact bundle.

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

### Compliance Bundle Structure (JSON)

Below is an abbreviated example of what `compliance_bundle.json` looks like:

```json
{
  "bundle_id": "EUAIA-a3f8c2d1",
  "regulation": "EU AI Act (Regulation 2024/1689)",
  "compliance_deadline": "2026-08-02",
  "receipt_id": "RCP-HR-2026-0041",
  "generated_at": "2026-02-12T10:15:00.000000+00:00",
  "risk_classification": {
    "risk_level": "high",
    "annex_iii_category": "Employment and worker management",
    "annex_iii_number": 4,
    "rationale": "Use case falls under Annex III category 4...",
    "matched_keywords": ["recruitment", "cv screening", "hiring decision"],
    "applicable_articles": [
      "Article 6 (Classification)",
      "Article 9 (Risk management)",
      "Article 13 (Transparency)",
      "Article 14 (Human oversight)",
      "Article 15 (Accuracy, robustness, cybersecurity)"
    ],
    "obligations": [
      "Establish and maintain a risk management system (Art. 9).",
      "Maintain technical documentation (Art. 11).",
      "Implement automatic logging of events (Art. 12).",
      "Ensure transparency and provide instructions for deployers (Art. 13).",
      "Design for effective human oversight (Art. 14).",
      "..."
    ]
  },
  "conformity_report": {
    "report_id": "EUAIA-b7e9d4f2",
    "overall_status": "conformant",
    "article_mappings": [
      {
        "article": "Article 9",
        "requirement": "Identify and analyze known and reasonably foreseeable risks",
        "status": "satisfied",
        "evidence": "Risk assessment performed: 5 risks identified (0 critical). Confidence: 78.0%."
      },
      {
        "article": "Article 12",
        "requirement": "Automatic logging of events with traceability",
        "status": "satisfied",
        "evidence": "Provenance chain contains 10 events."
      },
      {
        "article": "Article 13",
        "requirement": "Identify participating agents, their arguments, and decision rationale",
        "status": "satisfied",
        "evidence": "4 agents participated. Verdict reasoning: The recruitment screening..."
      },
      {
        "article": "Article 14",
        "requirement": "Enable human oversight, including ability to override or halt",
        "status": "satisfied",
        "evidence": "Human approval/override mechanism detected in receipt configuration."
      },
      {
        "article": "Article 15",
        "requirement": "Appropriate levels of accuracy and robustness; resilience to attacks",
        "status": "satisfied",
        "evidence": "Robustness score: 72.0%. Integrity hash: present. Cryptographic signature: present."
      }
    ],
    "integrity_hash": "a3f8c2d1e5b7..."
  },
  "article_12_record_keeping": {
    "event_log": [
      {"event_id": "evt_0001", "event_type": "debate_started", "actor": "system"},
      {"event_id": "evt_0002", "event_type": "proposal_submitted", "actor": "claude-analyst"},
      {"event_id": "evt_0009", "event_type": "human_approval", "actor": "hr-director@acme.com"},
      {"event_id": "evt_0010", "event_type": "receipt_generated", "actor": "system"}
    ],
    "technical_documentation": {
      "annex_iv_sec1_general": {
        "system_name": "Aragora Decision Integrity Platform",
        "version": "2.6.3",
        "provider": "Aragora Inc."
      }
    },
    "retention_policy": {
      "minimum_months": 6,
      "basis": "Art. 26(6) -- minimum 6 months for high-risk systems",
      "integrity_mechanism": "SHA-256 hash chain"
    }
  },
  "article_13_transparency": {
    "provider_identity": {
      "name": "Aragora Inc.",
      "contact": "compliance@aragora.ai",
      "eu_representative": "Aragora EU GmbH, Berlin, Germany"
    },
    "known_risks": [
      {"risk": "Automation bias", "mitigation": "Mandatory human review, dissent highlighting"},
      {"risk": "Hollow consensus", "mitigation": "Trickster detection module, evidence grounding"},
      {"risk": "Model hallucination", "mitigation": "Multi-agent challenge, calibration tracking"}
    ],
    "output_interpretation": {
      "confidence": 0.78,
      "confidence_interpretation": "Moderate confidence -- some reservations",
      "dissent_count": 1
    }
  },
  "article_14_human_oversight": {
    "oversight_model": {
      "primary": "Human-in-the-Loop (HITL)",
      "human_approval_detected": true
    },
    "override_capability": {
      "override_available": true,
      "mechanisms": [
        {"action": "Reject verdict", "audit_logged": true},
        {"action": "Override with reason", "audit_logged": true},
        {"action": "Reverse prior decision", "audit_logged": true}
      ]
    },
    "intervention_capability": {
      "stop_available": true,
      "mechanisms": [
        {"action": "Stop debate", "safe_state": true},
        {"action": "Cancel decision", "safe_state": true}
      ]
    }
  },
  "integrity_hash": "6f32616ade73e6ab7fd470dbe0c2f92ef617e2d9049a6ea98506eb34a4461066"
}
```

### Conformity Report (Markdown)

The `conformity_report.md` file looks like this:

```markdown
# EU AI Act Conformity Report

**Report ID:** EUAIA-b7e9d4f2
**Receipt ID:** RCP-HR-2026-0041
**Generated:** 2026-02-12T10:15:00.000000+00:00
**Integrity Hash:** `6f32616ade73e6a...`

---

## Risk Classification

**Risk Level:** HIGH
**Annex III Category:** 4. Employment and worker management
**Rationale:** Use case falls under Annex III category 4...

### Obligations

- Establish and maintain a risk management system (Art. 9).
- Maintain technical documentation (Art. 11).
- Implement automatic logging of events (Art. 12).
- ...

---

## Article Compliance Assessment

**Overall Status:** CONFORMANT

| Article | Requirement | Status | Evidence |
|---------|-------------|--------|----------|
| Article 9 | Identify and analyze known and reasonab... | PASS | Risk assessment performed: 5 risks... |
| Article 12 | Automatic logging of events with tracea... | PASS | Provenance chain contains 10 events. |
| Article 13 | Identify participating agents, their ar... | PASS | 4 agents participated... |
| Article 14 | Enable human oversight, including abilit... | PASS | Human approval/override mechanism... |
| Article 15 | Appropriate levels of accuracy and robu... | PASS | Robustness score: 72.0%... |
```

---

## Compliance Timeline

### What Organizations Need to Do Before August 2, 2026

| When | Action | Aragora Feature |
|------|--------|----------------|
| **Now** | Classify your AI systems by risk level | `aragora compliance classify` |
| **Now** | Inventory all AI use cases against Annex III | `RiskClassifier` API |
| **Q2 2026** | Run adversarial stress tests on high-risk systems | `aragora gauntlet` |
| **Q2 2026** | Generate compliance artifact bundles | `aragora compliance eu-ai-act generate` |
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
| Prohibited AI practices (Art. 5) | 35M EUR or 7% of global turnover |
| High-risk non-compliance | 15M EUR or 3% of global turnover |
| Providing incorrect information | 7.5M EUR or 1% of global turnover |

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

### Q: What is the difference between `audit` and `eu-ai-act generate`?

- `aragora compliance audit` generates a **conformity report** -- a single
  document that maps receipt fields to article requirements and flags gaps.
- `aragora compliance eu-ai-act generate` produces a **full artifact bundle**
  -- dedicated Art. 12, 13, and 14 artifacts with detailed fields suitable
  for submission to regulators, plus the conformity report.

Use `audit` for quick checks during development. Use `eu-ai-act generate`
when preparing documentation for regulatory review.

### Q: How do I verify the integrity of a compliance bundle?

Every bundle includes a `integrity_hash` field -- a SHA-256 hash computed from
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

---

## Related Documentation

- [Enterprise Compliance Guide](../enterprise/COMPLIANCE.md) -- Operational controls and governance model
- EU AI Act compliance checklist is maintained in `docs/compliance/EU_AI_ACT_CHECKLIST.md`
- [API Reference](../api/API_REFERENCE.md) -- REST API documentation
- [Gauntlet Testing](../../aragora/gauntlet/README.md) -- Adversarial stress testing
- [Decision Receipts](../reference/CLI_REFERENCE.md) -- Receipt command and verification workflow
