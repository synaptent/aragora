# Aragora for Healthcare

**Adversarial Decision Integrity for Clinical and Compliance Workflows**

---

## The Problem

Healthcare decisions carry the highest stakes of any industry. A formulary committee adding a new drug, a utilization review team approving a procedure, or a clinician choosing between treatment pathways -- each decision must be evidence-based, defensible, and documented. Yet the tools available to support these decisions are either rigid rule engines that miss nuance, or single-model AI systems that hallucinate without accountability.

Single-model AI is particularly dangerous in healthcare. When one model confidently recommends a drug without flagging a contraindication, there is no adversarial check. There is no dissenting voice. There is no audit trail showing the reasoning was challenged.

Aragora changes this by putting every clinical decision through adversarial multi-agent debate -- multiple independent AI models that challenge, critique, and refine each other's reasoning before a consensus recommendation is produced. The result is a HIPAA-compliant Decision Receipt documenting exactly what was considered, what was challenged, and why the final recommendation was reached.

---

## How Aragora Applies to Healthcare

### Clinical Decision Support

Aragora's debate engine evaluates clinical scenarios through multiple lenses simultaneously:

- **Drug interaction analysis**: Independent models cross-check proposed medications against the patient's full medication list, flagging interactions that a single model might miss
- **Treatment pathway selection**: When multiple treatment options exist (e.g., GLP-1 agonist vs. second antihypertensive), models argue the case for each approach, citing specific guidelines
- **Triage and prioritization**: For utilization review, agents debate whether a proposed procedure meets medical necessity criteria, with each agent challenging the others' reasoning
- **Contraindication detection**: The adversarial structure means at least one model is specifically tasked with finding reasons *not* to proceed -- catching edge cases that consensus-seeking systems miss

### FHIR Integration

Aragora connects directly to your EHR systems through its FHIR R4 connector:

- **Epic and Cerner connectors**: Pull patient data via SMART on FHIR OAuth2 authentication
- **Structured clinical input**: FHIR Bundles (Patient, Condition, MedicationRequest, Observation resources) are automatically parsed into clinical narratives for debate context
- **Supported FHIR resource types**: Patient, Condition, Observation, Procedure, MedicationRequest, MedicationStatement, AllergyIntolerance, Immunization, DiagnosticReport, CarePlan, Encounter, and more
- **Bidirectional**: Decision Receipts can be written back as DocumentReference resources for inclusion in the patient record

```
FHIR Bundle (Patient, Conditions, Medications, Labs)
         |
         v
   Clinical Narrative Extraction
         |
         v
   Multi-Agent Adversarial Debate
   (Proposer --> Critic --> Synthesizer, 5 rounds)
         |
         v
   HIPAA-Compliant Decision Receipt
   (PHI redacted, SHA-256 integrity hash)
```

### HIPAA Compliance

Every component of Aragora's healthcare pipeline is designed for HIPAA compliance:

| Safeguard | Implementation |
|-----------|---------------|
| **PHI Redaction** | Safe Harbor de-identification strips all 18 HIPAA identifiers from Decision Receipts before storage or export |
| **Encryption** | AES-256-GCM field-level encryption for sensitive data at rest; TLS 1.3 in transit |
| **Audit Trails** | Every debate round, every agent contribution, every vote is logged with tamper-evident SHA-256 hashing |
| **Access Control** | RBAC v2 with 360+ permissions; role-based access to clinical debate results |
| **Data Retention** | Configurable retention policies aligned with state and federal requirements |
| **Breach Notification** | Built-in breach assessment workflow template with HHS notification timelines |
| **Minimum Necessary** | Only clinical data relevant to the specific decision is included in the debate context |

PHI fields that are automatically stripped from all receipts and outputs:

```
patient_name, patient_id, mrn, ssn, date_of_birth, phone,
email, address, ip_address, device_id, photo
```

---

## Use Cases

### 1. Formulary Decision Review

**Scenario**: A pharmacy and therapeutics (P&T) committee is evaluating whether to add a new biologic to the hospital formulary.

**Without Aragora**: Committee members review the drug manufacturer's data, possibly one independent review, and make a decision in a meeting. The reasoning is captured in minutes with limited detail.

**With Aragora**: The committee submits the formulary question to Aragora. Three independent models analyze efficacy data, safety profiles, cost-effectiveness, and formulary overlap. One model explicitly argues against inclusion, stress-testing the case. The resulting Decision Receipt documents every argument, counterargument, and the evidence cited -- providing a defensible record for any future challenge.

**CLI**:
```bash
aragora ask "Should we add adalimumab biosimilar to the formulary given \
  current TNF-alpha inhibitor coverage? Consider cost-effectiveness, \
  therapeutic interchange protocols, and patient switching risks." \
  --vertical healthcare \
  --rounds 5 \
  --consensus unanimous
```

### 2. Clinical Pathway Selection

**Scenario**: A patient with Type 2 Diabetes (HbA1c 8.2%) and uncontrolled hypertension (145/92 mmHg) needs treatment intensification. The clinical question: add a GLP-1 receptor agonist for dual cardiometabolic benefit, or address the hypertension first?

**With Aragora**: The FHIR connector pulls the patient's conditions, medications, and recent lab values. Models debate the clinical evidence: ADA Standards of Care recommendations, cardiovascular outcome trial data (LEADER, SUSTAIN-6), drug interaction profiles, and adherence burden. The debate surfaces that the GLP-1 agonist provides both glycemic and cardiovascular benefit, but one model raises the contraindication concern if the patient has a history of pancreatitis.

**CLI**:
```bash
aragora healthcare review \
  --fhir patient_bundle.json \
  "Should we add semaglutide for dual cardiometabolic benefit, or \
  add amlodipine for BP control first? Consider ADA 2026 guidelines, \
  cardiovascular outcome data, and drug interactions." \
  --output-dir ./receipts \
  --verbose
```

### 3. Utilization Review

**Scenario**: A payer's utilization management team must decide whether to authorize a high-cost imaging study (cardiac MRI) or recommend a less expensive alternative (echocardiogram).

**With Aragora**: Models debate medical necessity against AUC (Appropriate Use Criteria), arguing both for and against the higher-cost study. The Decision Receipt documents the clinical justification, the alternatives considered, and the specific criteria met or unmet -- exactly what is needed if the decision is appealed.

### 4. HIPAA Compliance Assessment

Aragora includes a pre-built HIPAA Compliance Assessment workflow that evaluates your organization against:

- **Privacy Rule**: Notice of privacy practices, patient rights, minimum necessary standard, business associate agreements
- **Security Rule**: Administrative, physical, and technical safeguards across all required and addressable specifications
- **Breach Notification**: Identification procedures, risk assessment process, notification timelines, documentation

The workflow runs a multi-agent risk analysis with compliance, security, and privacy specialist personas, then routes findings through human checkpoints based on severity.

**CLI**:
```bash
aragora ask "Assess our HIPAA Security Rule compliance for the new \
  patient portal deployment. Focus on technical safeguards: access control, \
  audit controls, integrity controls, and transmission security." \
  --vertical healthcare \
  --enable-verticals \
  --rounds 5
```

---

## Healthcare Evaluation Framework

### Weight Profiles

Aragora uses domain-specific weight profiles that control how agent contributions are scored. Healthcare profiles prioritize safety and accuracy over creativity:

| Dimension | `healthcare_hipaa` | `healthcare_clinical` | General |
|-----------|-------------------:|---------------------:|--------:|
| Safety | **25%** | 10% | 5% |
| Accuracy | **25%** | **25%** | 15% |
| Completeness | 15% | 15% | 15% |
| Evidence | 10% | **20%** | 15% |
| Relevance | 10% | 15% | 15% |
| Reasoning | 10% | 10% | 25% |
| Clarity | 5% | 5% | 10% |
| Creativity | **0%** | **0%** | 0% |

Key design decisions:
- **Creativity is zero** in both healthcare profiles. Clinical decision support must be evidence-based, not novel.
- **Safety is weighted 25%** in the HIPAA profile, catching PHI exposure and unsafe recommendations.
- **Evidence is weighted 20%** in the clinical profile, ensuring guideline citations are present and current.

### Healthcare-Specific Rubrics

Agent contributions are evaluated against healthcare-specific criteria:

**Accuracy Rubric** -- "Are clinical claims evidence-based and medically accurate?"
- Score 1: Contains dangerous medical misinformation
- Score 3: Generally accurate but lacks clinical precision
- Score 5: Impeccable clinical accuracy with cited evidence

**Safety Rubric** -- "Does the response protect patient safety and PHI?"
- Score 1: Exposes PHI or recommends harmful treatments
- Score 3: Generally safe but missing HIPAA safeguards
- Score 5: Full HIPAA compliance, PHI redacted, safe recommendations

**Completeness Rubric** -- "Does the assessment cover all relevant clinical and regulatory aspects?"
- Score 1: Missing critical clinical or compliance areas
- Score 3: Adequate coverage of main clinical concerns
- Score 5: Exhaustive coverage including edge cases and contraindications

### Agent Team Composition

Healthcare debates use specialized agent personas:

| Persona | Role | Focus |
|---------|------|-------|
| `clinical_reviewer` | Primary analyst | Evidence-based clinical evaluation |
| `hipaa_auditor` | Compliance check | PHI handling, regulatory alignment |
| `medical_coder` | Coding accuracy | ICD-10, CPT/HCPCS validation |
| `research_analyst_clinical` | Evidence review | Clinical trial data, guideline concordance |

The default healthcare debate team uses three agents with distinct providers to prevent single-model bias:
```
anthropic-api:proposer, openai-api:critic, anthropic-api:synthesizer
```

---

## Regulatory Alignment

### HIPAA (Health Insurance Portability and Accountability Act)

- **Privacy Rule**: PHI is stripped from all outputs using the Safe Harbor method; minimum necessary principle enforced by limiting debate context to relevant clinical data only
- **Security Rule**: AES-256-GCM encryption, RBAC access controls, comprehensive audit logging
- **Breach Notification Rule**: Pre-built assessment workflow with timelines and human checkpoints

### 21st Century Cures Act

- **Information Blocking**: Aragora's FHIR connectors support the Act's interoperability requirements; decision data can be shared in standard formats
- **Patient Access**: Decision Receipts can be exported as patient-readable summaries

### EU AI Act (if applicable)

Aragora includes an EU AI Act compliance artifact generator covering Articles 12, 13, and 14 -- relevant for healthcare AI systems classified as high-risk under the Act.

---

## Example: Clinical Decision Debate Flow

The following illustrates the complete flow of a clinical decision through Aragora:

```
1. INPUT
   Clinician submits: "Patient with CKD Stage 3a on metformin + lisinopril.
   Evaluate adding ibuprofen 400mg TID for knee pain."
   FHIR Bundle attached with conditions, medications, lab values.

2. CONTEXT EXTRACTION
   FHIR connector parses:
   - Conditions: Type 2 DM (active), Essential Hypertension (active), CKD Stage 3a
   - Medications: Metformin 1000mg BID, Lisinopril 20mg, Atorvastatin 40mg
   - Labs: eGFR 52, Creatinine 1.4, HbA1c 7.8%

3. ROUND 1 - PROPOSAL
   Agent A (Claude): "AGAINST ibuprofen. NSAIDs contraindicated with eGFR 52
   per KDIGO 2024 Guidelines. Ibuprofen-lisinopril interaction reduces
   antihypertensive effect and compounds renal risk. Recommend acetaminophen
   or topical NSAID."

4. ROUND 2 - CRITIQUE
   Agent B (GPT): "Agree on contraindication. Adding: triple whammy risk
   (NSAID + ACE inhibitor + potential diuretic). Dreischulte et al. (2015)
   shows 25-30% increased AKI risk. Age 68 also increases GI bleeding risk
   per AGS Beers Criteria 2023. Recommend duloxetine or PT referral."

5. ROUND 3 - COUNTER
   Agent C (Gemini): "Concur on systemic NSAID contraindication. However,
   topical diclofenac has lower systemic exposure -- Cochrane review (Derry
   2015) supports limited-duration use. Recommend rheumatology consult to
   rule out inflammatory arthritis."

6. ROUNDS 4-5 - REFINEMENT
   Agents debate topical NSAID safety in CKD.
   Agent A maintains all NSAIDs should be avoided.
   Agents B and C accept topical as option with monitoring.
   Dissent is documented.

7. CONSENSUS
   STRONG CONSENSUS (86% confidence): Do not prescribe systemic ibuprofen.
   Alternatives: acetaminophen (first-line), topical NSAID (limited duration
   with renal monitoring), duloxetine, physical therapy, rheumatology referral.
   Dissent recorded: disagreement on topical NSAID safety.

8. DECISION RECEIPT
   - Receipt ID: CR-2026-0212-001
   - PHI: Redacted (Safe Harbor)
   - Agents consulted: 3
   - Rounds completed: 5
   - Evidence chain: KDIGO 2024, FDA Drug Safety 2023, AGS Beers 2023,
     Dreischulte 2015, Derry 2015 Cochrane, ACR/AF 2019
   - Integrity hash: SHA-256 (tamper-evident)
   - Dissenting views: 1 (topical NSAID disagreement)
```

---

## Decision Receipt Format

Every healthcare debate produces a HIPAA-compliant Decision Receipt:

```json
{
  "receipt_id": "CR-2026-0212-001",
  "timestamp": "2026-02-12T14:30:00Z",
  "schema_version": "1.0",
  "profile": "healthcare_hipaa",
  "compliance": {
    "hipaa_compliant": true,
    "phi_redacted": true,
    "safe_harbor_method": true
  },
  "input": {
    "input_hash": "a3f8c2...",
    "has_fhir_data": true,
    "resource_count": 7
  },
  "verdict": {
    "consensus_reached": true,
    "confidence": 0.86,
    "final_answer": "Do not prescribe systemic ibuprofen..."
  },
  "audit_trail": {
    "agents_consulted": 3,
    "rounds_completed": 5,
    "votes_cast": 3,
    "dissenting_views_count": 1
  },
  "integrity": {
    "artifact_hash": "b7e4d1..."
  }
}
```

The receipt is designed for inclusion in clinical records, compliance audits, and quality improvement programs. The SHA-256 integrity hash ensures the receipt has not been modified after generation.

---

## Getting Started

### 1. Install Aragora

```bash
pip install aragora
```

### 2. Configure API Keys

At least one LLM provider is required. For multi-model consensus (recommended for clinical use), configure two or more:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

### 3. Run a Healthcare Demo

Try the built-in clinical decision demo with sample FHIR data:

```bash
aragora healthcare review --demo
```

This runs a full adversarial debate on a sample scenario (Type 2 Diabetes treatment intensification) with mock FHIR data, producing a formatted Decision Receipt.

### 4. Run a Clinical Review with Your Data

```bash
# With a FHIR Bundle
aragora healthcare review \
  --fhir patient_bundle.json \
  "Evaluate adding empagliflozin to current regimen for cardiorenal benefit" \
  --output-dir ./clinical-receipts \
  --verbose

# With a plain clinical question
aragora ask "Evaluate the appropriateness of MRI lumbar spine for a patient \
  with 3 weeks of low back pain, no red flags, and no prior imaging" \
  --vertical healthcare \
  --rounds 5 \
  --consensus unanimous
```

### 5. Run a HIPAA Compliance Assessment

```bash
aragora ask "Assess HIPAA Security Rule compliance for our telehealth platform. \
  Focus on: access control (unique user IDs, emergency access), audit controls \
  (activity logging), integrity (mechanism to authenticate ePHI), and \
  transmission security (encryption of ePHI in transit)." \
  --vertical healthcare \
  --enable-verticals \
  --rounds 5
```

### 6. Programmatic Usage

```python
from aragora import Arena, Environment, DebateProtocol

env = Environment(
    task="Evaluate drug interaction risk: metformin + lisinopril + ibuprofen in CKD Stage 3a",
    context=fhir_clinical_summary,
)

protocol = DebateProtocol(
    rounds=5,
    consensus="unanimous",
    weight_profile="healthcare_hipaa",
)

arena = Arena(env, agents, protocol)
result = await arena.run()

# Result includes Decision Receipt with PHI redacted
receipt = result.receipt
print(f"Consensus: {receipt.verdict.consensus_reached}")
print(f"Confidence: {receipt.verdict.confidence:.0%}")
print(f"Integrity hash: {receipt.integrity.artifact_hash}")
```

### 7. Connect to Your EHR

```python
from aragora.connectors.enterprise.healthcare.fhir import FHIRConnector

connector = FHIRConnector(
    base_url="https://fhir.epic.example.com/R4",
    client_id="your-smart-client-id",
    auth_type="smart_on_fhir",
)

# Pull patient data as FHIR Bundle
bundle = await connector.get_patient_bundle(patient_id="...", resources=[
    "Condition", "MedicationRequest", "Observation", "AllergyIntolerance"
])
```

---

## Frequently Asked Questions

**Does Aragora replace clinical judgment?**
No. Aragora is a clinical decision *support* tool. It surfaces evidence, identifies risks, and documents the reasoning -- but the final decision always rests with the clinician. Decision Receipts explicitly state they are for support, not directive care.

**How does adversarial debate improve safety?**
When a single AI model analyzes a clinical question, it may miss contraindications or overweight certain evidence. By having multiple independent models critique each other, Aragora catches errors that any one model would miss. The adversarial structure ensures at least one agent is specifically looking for reasons the proposed action could cause harm.

**What happens when models disagree?**
Disagreement is a feature, not a bug. Dissenting views are documented in the Decision Receipt, giving clinicians visibility into the full range of clinical considerations. The healthcare_hipaa profile requires high consensus (90% threshold) before a recommendation is labeled as consensus.

**Can we use Aragora in an air-gapped environment?**
Yes. Aragora supports offline operation with local models. Use `--local` mode with locally hosted models for environments that cannot connect to external APIs.

**Is the system validated for clinical use?**
Aragora provides decision *support infrastructure* -- the orchestration, documentation, and audit trail layer. It does not itself make clinical claims. The accuracy of recommendations depends on the underlying LLM providers and the clinical data provided. Organizations should validate the system within their clinical governance framework.
