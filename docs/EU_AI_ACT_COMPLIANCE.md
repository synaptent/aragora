# EU AI Act Compliance with Aragora

> **Enforcement date: August 2, 2026.**
> Organizations deploying high-risk AI systems in the EU must demonstrate
> audit trails, transparency, human oversight, and risk management --
> or face penalties of up to EUR 35 million or 7% of global annual revenue.
>
> Aragora generates the compliance artifacts you need. Today.

---

## 1. EU AI Act Overview

The **EU AI Act** (Regulation 2024/1689) is the world's first comprehensive
AI regulation. It applies to any organization that places AI systems on the
EU market or deploys AI that affects people in the EU -- regardless of where
the organization is headquartered.

### Who is affected

- Any company deploying AI for decisions that impact EU citizens
- AI providers selling into the EU market
- Organizations using AI in any of the 8 Annex III high-risk categories
- U.S., UK, and APAC companies with EU customers or employees

### What it requires for high-risk AI systems

High-risk AI systems (Article 6 + Annex III) must implement:

1. **Risk management** (Art. 9) -- continuous identification and mitigation of risks
2. **Data governance** (Art. 10) -- quality controls on training and reference data
3. **Technical documentation** (Art. 11) -- pre-market documentation, kept current
4. **Record-keeping** (Art. 12) -- automatic event logging over the system lifetime
5. **Transparency** (Art. 13) -- interpretable output with known limitations
6. **Human oversight** (Art. 14) -- effective human control and intervention capability
7. **Accuracy and robustness** (Art. 15) -- resilience to errors and adversarial attacks
8. **Quality management** (Art. 17) -- documented quality assurance processes

### Penalties

| Violation | Maximum Fine |
|-----------|-------------|
| Prohibited AI practices (Art. 5) | EUR 35M or 7% of global annual revenue |
| High-risk obligations (Art. 9-15) | EUR 15M or 3% of global annual revenue |
| Incorrect information to authorities | EUR 7.5M or 1% of global annual revenue |

### Key dates

```
  Aug 2024          Feb 2025          Aug 2025          Aug 2026          Aug 2027
    |                 |                 |                 |                 |
    v                 v                 v                 v                 v
  Entered          Prohibitions     GPAI rules       FULL HIGH-RISK    Annex I
  into force       apply            apply            ENFORCEMENT       systems
                                                         ^
                                                         |
                                              YOU ARE HERE (March 2026)
                                              ~5 months remaining
```

---

## 2. Aragora Compliance Matrix

Aragora's multi-agent debate architecture produces compliance artifacts as a
natural byproduct of its decision-vetting process. Every debate generates a
cryptographically signed decision receipt that maps directly to EU AI Act
obligations.

| EU AI Act Requirement | Article | Aragora Feature | Module | Status |
|---|---|---|---|---|
| Risk management system | Art. 9 | Gauntlet adversarial stress-testing: 3-phase red team attacks, capability probes, scenario matrix. ELO + Brier score calibration tracks per-agent reliability. `ComplianceArtifactGenerator` emits a dedicated `Article9Artifact` with identified risks, misuse scenarios, mitigations, residual risk level, and monitoring plan. | `aragora/gauntlet/`, `aragora/compliance/eu_ai_act.py` | Ready |
| Data governance | Art. 10 | Knowledge Mound with 42 registered adapter specs, provenance tracking, validation feedback, contradiction detection, and confidence decay. | `aragora/knowledge/mound/` | Ready |
| Technical documentation | Art. 11 | Decision receipts capture full system configuration: agents, protocol, consensus thresholds, Annex IV sections auto-populated. | `aragora/export/decision_receipt.py` | Ready |
| Record-keeping / logging | Art. 12 | `Article12Artifact`: provenance chain event log, Annex IV tech doc summary, reference databases, retention policy (6-month minimum per Art. 26(6)). | `aragora/compliance/eu_ai_act.py` | Ready |
| Transparency | Art. 13 | `Article13Artifact`: provider identity, intended purpose, accuracy/robustness metrics, known risks (automation bias, hollow consensus, hallucination), output interpretation with confidence context. | `aragora/compliance/eu_ai_act.py` | Ready |
| Human oversight | Art. 14 | `Article14Artifact`: HITL/HOTL oversight model, automation bias safeguards, override mechanisms (reject, override with reason, reverse), intervention capability (stop debate, cancel decision). | `aragora/compliance/eu_ai_act.py` | Ready |
| Accuracy, robustness, cybersecurity | Art. 15 | Heterogeneous multi-model consensus (Claude, GPT, Gemini, Mistral), circuit breakers, Trickster hollow-consensus detection, AES-256-GCM encryption, key rotation, RBAC with MFA. | `aragora/resilience/`, `aragora/security/` | Ready |
| Quality management | Art. 17 | Gauntlet receipts with SHA-256 integrity hashing, calibration tracking, 208,000+ automated tests, observability with Prometheus metrics and OpenTelemetry tracing. | `aragora/gauntlet/`, `aragora/observability/` | Ready |
| Risk classification | Art. 6 | `RiskClassifier` auto-classifies use cases across all 4 risk tiers and all 8 Annex III high-risk categories using keyword and pattern matching. | `aragora/compliance/eu_ai_act.py` | Ready |
| Conformity assessment | Art. 43 | `ConformityReportGenerator` maps receipt fields to article requirements, scores compliance per-article, generates markdown or JSON conformity reports. | `aragora/compliance/eu_ai_act.py` | Ready |
| Explainability | Art. 13(1) | Factor decomposition, counterfactual analysis, evidence chains linking claims to sources, vote pivot analysis showing which arguments changed outcomes. | `aragora/explainability/` | Ready |
| Privacy and data protection | Art. 10(5) | Anonymization, consent management, data retention policies, right-to-deletion, PII classifier. | `aragora/privacy/` | Ready |

---

## 3. Quick Start: Generate Compliance Artifacts

### Step 1: Classify a use case by risk level

```python
from aragora.compliance.eu_ai_act import RiskClassifier

classifier = RiskClassifier()
result = classifier.classify("AI system for recruitment and CV screening")

result.risk_level          # RiskLevel.HIGH
result.annex_iii_category  # "Employment and worker management"
result.annex_iii_number    # 4
result.applicable_articles # ["Article 6 (Classification)", "Article 9 (Risk management)", ...]
result.obligations         # ["Establish and maintain a risk management system (Art. 9).", ...]
```

### Step 2: Generate a conformity report from a decision receipt

```python
from aragora.compliance.eu_ai_act import ConformityReportGenerator

generator = ConformityReportGenerator()

# receipt_dict is the output of DecisionReceipt.to_dict()
receipt_dict = {
    "receipt_id": "DR-2026-0212-001",
    "input_summary": "Evaluate hiring algorithm for recruitment decisions",
    "verdict": "CONDITIONAL",
    "confidence": 0.78,
    "robustness_score": 0.72,
    "verdict_reasoning": "Recruitment system shows bias risk in CV screening",
    "risk_summary": {"total": 3, "critical": 0, "high": 1, "medium": 2, "low": 0},
    "consensus_proof": {
        "method": "weighted_majority",
        "supporting_agents": ["Claude-3.5", "GPT-4o"],
        "dissenting_agents": ["Gemini-1.5"],
    },
    "dissenting_views": ["Gemini-1.5: potential gender bias not fully mitigated"],
    "provenance_chain": [
        {"event_type": "debate_started", "timestamp": "2026-02-12T10:00:00Z", "actor": "system"},
        {"event_type": "human_approval", "timestamp": "2026-02-12T10:15:00Z", "actor": "admin@co.com"},
    ],
    "config_used": {"require_approval": True, "protocol": "adversarial", "rounds": 3},
    "artifact_hash": "a3f8c2d1e5b7...",
}

report = generator.generate(receipt_dict)
report.to_markdown()      # Human-readable conformity report
report.to_json()          # Machine-readable for GRC platform import
report.overall_status     # "conformant", "partial", or "non_conformant"
```

### Step 3: Generate a full Article 12/13/14 artifact bundle

```python
from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

gen = ComplianceArtifactGenerator(
    provider_name="Your Company Inc.",
    provider_contact="compliance@yourcompany.com",
    eu_representative="Your Company EU GmbH",
    system_name="Your Decision Platform",
    system_version="2.8.0",
)

bundle = gen.generate(receipt_dict)
bundle.bundle_id           # "EUAIA-a1b2c3d4"
bundle.integrity_hash      # SHA-256 hash of bundle contents
bundle.article_12          # Record-keeping: event log, tech doc, retention policy
bundle.article_13          # Transparency: provider identity, known risks, output guidance
bundle.article_14          # Human oversight: oversight model, overrides, stop mechanisms
bundle.to_json(indent=2)   # Export complete bundle
```

### CLI usage

```bash
aragora compliance classify "AI for credit scoring decisions"
aragora compliance audit receipt.json --format markdown --output report.md
aragora compliance audit receipt.json --format json --output report.json
```

---

## 4. Compliance Artifact Bundle

The `ComplianceArtifactBundle` packages all EU AI Act compliance evidence into a
single auditable unit with cryptographic integrity verification. The bundle now
includes dedicated artifacts for Articles 9, 10, 11, 12, 13, 14, 15, and 43.

### Bundle structure

| Component | Contents |
|---|---|
| **bundle_id** | `EUAIA-{uuid}` unique identifier |
| **integrity_hash** | SHA-256 hash of bundle metadata (tamper detection) |
| **risk_classification** | RiskLevel + Annex III category + obligations list |
| **conformity_report** | Per-article status (satisfied/partial/not_satisfied), overall status, recommendations |
| **article_9** (Risk Management) | Identified risks, foreseeable misuse scenarios, mitigation measures, residual risk level, post-market monitoring plan |
| **article_10** (Data Governance) | Data sources, quality measures, bias detection methods, training-data provenance, governance policy notes |
| **article_11** (Technical Documentation) | System description, design specifications, monitoring capabilities, performance metrics, compliance notes |
| **article_12** (Record-Keeping) | Event log, reference databases, input record with SHA-256 hash, Annex IV technical documentation (3 sections), retention policy (6-month min per Art. 26(6)) |
| **article_13** (Transparency) | Provider identity + EU representative, intended purpose, accuracy/robustness metrics, known risks, output interpretation with confidence context |
| **article_14** (Human Oversight) | HITL/HOTL oversight model, automation bias safeguards, factor decomposition + counterfactuals, override capability, intervention capability |
| **article_15** (Accuracy / Robustness / Cybersecurity) | Consensus confidence, robustness score, adversarial-testing indicators, cryptographic controls, error indicators |
| **article_43** (Conformity Assessment) | Assessment type, assessor, standards applied, findings, conformity status, compliance notes |

### Integrity verification

Every bundle includes a SHA-256 integrity hash computed over the bundle ID,
receipt ID, risk level, and conformity status. This hash can be independently
verified to detect tampering.

```python
import hashlib, json

# Recompute the integrity hash
content = json.dumps({
    "bundle_id": bundle.bundle_id,
    "receipt_id": bundle.receipt_id,
    "risk_level": bundle.risk_classification.risk_level.value,
    "conformity_status": bundle.conformity_report.overall_status,
}, sort_keys=True)
expected_hash = hashlib.sha256(content.encode()).hexdigest()

assert bundle.integrity_hash == expected_hash  # Passes
```

---

## 5. Integration with Governance Platforms

Aragora compliance artifacts export as structured JSON, making them compatible
with enterprise governance, risk, and compliance (GRC) platforms.

| Platform | Integration Method | What to Export |
|---|---|---|
| **IBM watsonx.governance** | REST API ingest | `bundle.to_json()` as AI factsheet entries. Map `article_mappings` to watsonx governance controls. |
| **OneTrust AI Governance** | CSV/JSON import | `conformity_report.to_dict()` maps to OneTrust assessment questionnaire responses. |
| **Credo AI** | API integration | Export `risk_classification` and `article_mappings` as Credo AI policy evidence. |
| **AuditBoard** | Document upload | `conformity_report.to_markdown()` as audit working papers. Bundle JSON as supporting evidence. |
| **ServiceNow GRC** | REST API / CMDB | Push `article_mappings` as control assessment records with status and evidence fields. |
| **Prometheus / Grafana** | Metrics endpoint | Aragora's built-in `/metrics` endpoint exposes SLO conformance, debate throughput, and calibration drift. |

### Example: Push to a GRC platform

```python
import requests
bundle = generator.generate(receipt_dict)

requests.post("https://grc.yourcompany.com/api/v1/ai-assessments", json={
    "assessment_type": "eu_ai_act",
    "bundle": bundle.to_dict(),
    "status": bundle.conformity_report.overall_status,
    "risk_level": bundle.risk_classification.risk_level.value,
}, headers={"Authorization": "Bearer <token>"})
```

---

## 6. Timeline: Start Now

```
                                    YOU ARE HERE
                                         |
  Feb 2026           Jun 2026           Aug 2, 2026
    |                   |                   |
    v                   v                   v
  +-------------------+-------------------+------------------------+
  | START GENERATING  | EU HARMONIZED     | FULL ENFORCEMENT       |
  | COMPLIANCE        | STANDARDS         | BEGINS                 |
  | ARTIFACTS         | PUBLISHED         |                        |
  +-------------------+-------------------+------------------------+
  |                   |                   |
  | - Deploy Aragora  | - Map standards   | - Fines apply          |
  | - Enable receipts |   to your bundles | - Market surveillance  |
  | - Run Gauntlet    | - Gap analysis    |   authorities active   |
  |   stress tests    | - Update tech     | - Conformity           |
  | - Configure RBAC  |   documentation   |   assessments begin    |
  | - Set up audit    | - Prepare for     |                        |
  |   logging         |   conformity      |                        |
  |                   |   assessment      |                        |
  +-------------------+-------------------+------------------------+
```

**Start today. Compliance takes months to establish.** The EU AI Act does not
have a grace period. On August 2, 2026, organizations deploying high-risk AI
systems must already have conformity documentation in place.

### Recommended implementation phases

**Phase 1 (Now - April 2026): Foundation**
- Deploy Aragora with decision receipt generation
- Configure RBAC roles for decision approvers
- Enable audit logging with tamper-evident signatures
- Run Gauntlet adversarial testing on high-risk decision categories
- Generate initial compliance artifact bundles

**Phase 2 (April - June 2026): Integration**
- Integrate compliance artifacts with your GRC platform
- Configure multi-model consensus (minimum 3 providers for high-risk)
- Enable calibration tracking to monitor confidence accuracy
- Set up Knowledge Mound for institutional decision memory

**Phase 3 (June - August 2026): Documentation**
- Map against published EU harmonized standards
- Compile Gauntlet test reports for the risk management file
- Document human oversight procedures (approval gates, override protocols)
- Prepare calibration reports showing accuracy vs. confidence alignment
- Perform internal conformity assessment using generated bundles

---

## Appendix: Additional Article Artifacts

### Article 10 — Data and Data Governance

`Article10Artifact` captures data provenance, quality measures, and bias detection
methods. When no explicit data sources are declared in the receipt, the artifact
notes this and falls back to platform-level governance defaults (heterogeneous
model ensemble, adversarial dissent capture, Trickster hollow-consensus detection).

Fields: `data_sources`, `data_quality_measures`, `bias_detection_methods`,
`training_data_provenance`, `data_governance_policy`, `compliance_notes`.

### Article 11 — Technical Documentation

`Article11Artifact` generates Annex IV-aligned technical documentation including
system description, design specifications, development process, monitoring
capabilities, and performance metrics. When receipt fields are absent, defaults
are auto-generated from platform configuration.

Fields: `system_description`, `design_specifications`, `development_process`,
`monitoring_capabilities`, `performance_metrics`, `compliance_notes`.

### Article 43 — Conformity Assessment

`Article43Artifact` records conformity assessment metadata: assessment type
(internal or third-party), assessor identity, applied standards, findings from
risk analysis, and overall conformity status. Critical risks automatically set
status to `non_conformant`; high risks set `conditional` when no explicit status
is provided.

Fields: `assessment_type`, `assessment_date`, `assessor`, `standards_applied`,
`findings`, `conformity_status`, `compliance_notes`.

### Article 49 — Registration

`Article49Artifact` prepares the data required for EU AI database registration
per Article 49. It captures provider information, system purpose, risk level,
and registration identifiers. When no registration ID is present, a compliance
note flags that registration is required before market placement.

Fields: `registration_id`, `registered_date`, `eu_database_entry`,
`provider_info`, `system_purpose`, `risk_level`, `compliance_notes`.

---

## Further Reading

- [EU AI Act full text](https://eur-lex.europa.eu/eli/reg/2024/1689) | [Extended README](EXTENDED_README.md) | [Decision Receipt API](api/API_REFERENCE.md) | [Gauntlet Guide](../aragora/gauntlet/README.md) | [RBAC Config](reference/CONFIGURATION.md) | [Source](../aragora/compliance/eu_ai_act.py)
