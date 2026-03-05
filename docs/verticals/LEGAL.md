# Aragora for Legal

**Adversarial Decision Integrity for Contract Review, Due Diligence, and Litigation Risk**

---

## The Problem

Legal work is inherently adversarial. Contracts are negotiated between opposing interests. Litigation involves competing interpretations of the same facts. Due diligence requires finding the risks that someone else has an incentive to hide. Yet the AI tools available to legal teams today are consensus-seeking by design -- they produce a single analysis without challenge, without dissent, and without the structured argumentation that lawyers depend on.

A single AI model reviewing a contract might identify obvious issues like missing termination clauses or unusual indemnification provisions. But it will not argue against its own analysis. It will not consider the counterparty's likely interpretation. It will not stress-test its conclusions under adverse scenarios.

Aragora brings the adversarial structure that legal work demands. Multiple independent AI models analyze, challenge, and refine each other's reasoning -- the same dialectical process that good legal analysis requires, but documented in an auditable Decision Receipt with cryptographic integrity verification. Every argument, every counterargument, every cited authority is preserved.

---

## How Aragora Applies to Legal

### Contract Review and Clause Analysis

Aragora's debate engine transforms contract review from a single-pass analysis into a structured adversarial examination:

- **Clause-by-clause analysis**: Models independently extract and categorize key terms (payment, termination, indemnification, liability caps, IP, confidentiality, governing law), then debate the risk implications of each
- **Risk scoring**: Each agent provides an independent risk assessment, and the adversarial process forces models to justify their scoring with specific contractual language and precedent
- **Counterparty perspective**: One agent is specifically tasked with arguing the counterparty's likely interpretation, surfacing provisions that appear neutral but favor the other side
- **Missing clause detection**: The adversarial structure is particularly effective at finding what is *not* in a contract -- the absence of a most-favored-nation clause, a missing data breach notification requirement, or an omitted change-of-control provision

### Due Diligence Acceleration

Aragora includes a complete due diligence workflow that runs parallel review streams across six document categories simultaneously:

- **Corporate document review**: Charter, bylaws, board minutes, shareholder agreements
- **Financial review**: Audited statements, tax filings, debt obligations, off-balance-sheet items
- **Material contracts review**: Change of control provisions, assignment restrictions, termination rights, material obligations
- **IP review**: Patent registrations, trademark portfolio, licensing agreements, IP litigation history
- **Litigation review**: Pending cases, threatened claims, judgment liens, settlement history
- **Compliance review**: Regulatory licenses, compliance history, pending investigations, environmental matters

All six streams run concurrently and feed into a multi-agent synthesis debate that produces a unified risk matrix. Critical findings ("deal-breaker" issues) automatically escalate to human review within 12 hours; significant issues route to detailed review within 24 hours.

### Litigation Risk Assessment

For litigation matters, Aragora's adversarial debate mirrors the analytical structure of case evaluation:

- **Merits analysis**: One agent argues the strongest case for the plaintiff's position, another argues the strongest defense, and a third synthesizes a realistic risk assessment
- **Damages estimation**: Models debate quantum independently, then negotiate toward a consensus range
- **Settlement analysis**: Agents debate BATNA (best alternative to negotiated agreement) for both sides, producing a structured settlement recommendation

---

## Use Cases

### 1. Contract Negotiation Support

**Scenario**: Your company is reviewing a SaaS vendor agreement with a $500K annual commitment. The vendor's paper includes broad indemnification obligations, a unilateral termination clause, and an auto-renewal provision.

**Without Aragora**: A junior associate reviews the contract, flags a few issues, and sends a redline. The review depends entirely on that associate's experience with similar agreements.

**With Aragora**: Three independent models analyze the contract. Agent A extracts all key terms and identifies the indemnification as disproportionate (unlimited liability for IP infringement, but capped at 12 months' fees for all other claims). Agent B argues the counterparty's likely position -- that the indemnification structure is standard for SaaS agreements and the IP carve-out reflects their actual risk exposure. Agent C identifies that the auto-renewal provision combined with the termination clause creates a lock-in: 60-day notice required before a renewal date that is not prominently stated, and early termination requires paying the remaining term. The Decision Receipt documents all three perspectives, giving the negotiating team a comprehensive brief.

**CLI**:
```bash
aragora ask "Review this SaaS vendor agreement ($500K/year, 3-year term). \
  Key concerns: (1) Indemnification is unlimited for IP but capped at 12 months' \
  fees otherwise, (2) vendor can terminate for convenience on 30 days' notice but \
  customer requires 60 days before renewal date, (3) auto-renewal with no \
  price cap on renewal terms. Assess risk and recommend negotiation priorities." \
  --vertical legal \
  --rounds 5 \
  --consensus unanimous
```

### 2. M&A Due Diligence

**Scenario**: Your firm is advising on a $50M acquisition. The target company has 200+ contracts, a patent portfolio, pending litigation, and operations in three jurisdictions.

**Without Aragora**: A team of associates spends weeks reviewing documents manually. Findings are compiled in a memo that may miss cross-category issues (e.g., a contract obligation that creates litigation exposure, or an IP license that restricts the planned post-acquisition integration).

**With Aragora**: The due diligence workflow template runs all six review streams concurrently. The multi-agent synthesis debate surfaces cross-category findings: the target's largest customer contract has a change-of-control provision that allows termination on 30 days' notice (material revenue risk), and the pending patent litigation relates to technology licensed under an agreement with an assignability restriction (integration risk). The Decision Receipt provides a structured risk matrix for the deal team.

**CLI**:
```bash
aragora ask "Due diligence review for $50M acquisition of a B2B software company. \
  Key areas: (1) Change-of-control provisions in top 10 customer contracts, \
  (2) IP portfolio strength and freedom-to-operate, (3) pending patent litigation \
  ($3.5M claimed damages), (4) data privacy compliance across US, UK, and Germany \
  operations. Identify deal-breaker risks and recommend protections." \
  --vertical legal \
  --enable-verticals \
  --rounds 5
```

### 3. Regulatory Compliance Review

**Scenario**: A fintech company needs to assess its compliance posture before launching a new product in a regulated market. Multiple regulatory frameworks apply: state money transmitter laws, federal BSA/AML requirements, and potentially GDPR for European customers.

**With Aragora**: Models debate the regulatory landscape from different angles. One agent focuses on the state-by-state licensing requirements, another on federal BSA/AML obligations, and a third on the GDPR implications of processing European customer data. The adversarial debate surfaces conflicts between frameworks (e.g., AML record retention requirements that may conflict with GDPR data minimization principles) that a single-pass analysis would miss.

### 4. Patent Analysis

**Scenario**: Before launching a new product feature, the engineering team needs a freedom-to-operate assessment across 15 potentially relevant patents.

**With Aragora**: Each patent's claims are analyzed by multiple models. One agent argues the broadest plausible claim construction (maximum risk), another argues the narrowest (minimum risk), and a third assesses the most likely construction based on prosecution history. The resulting analysis for each patent includes a risk rating backed by specific claim language and prior art references.

### 5. Litigation Hold Assessment

**CLI**:
```bash
aragora ask "Assess litigation hold requirements for threatened trade secret \
  misappropriation claim. Former employee joined competitor 3 months ago. \
  Potentially relevant data: email (Exchange), Slack, shared drives, \
  source code repositories, CRM records, and physical notebooks. \
  Identify custodians, data sources, and preservation obligations." \
  --vertical legal \
  --rounds 5 \
  --consensus unanimous
```

---

## Legal Evaluation Framework

### Weight Profiles

Aragora's legal weight profiles are calibrated for the precision that legal work demands:

| Dimension | `legal_contract` | `legal_due_diligence` | General |
|-----------|------------------:|---------------------:|--------:|
| Accuracy | **25%** | 20% | 15% |
| Completeness | **25%** | **25%** | 15% |
| Reasoning | 15% | 15% | 25% |
| Evidence | 10% | 15% | 15% |
| Relevance | 10% | 10% | 15% |
| Safety | 5% | 10% | 5% |
| Clarity | 10% | 5% | 10% |
| Creativity | **0%** | **0%** | 0% |

Key design decisions:
- **Completeness is 25% in both legal profiles** -- missing a material clause or a red flag in due diligence is unacceptable
- **Accuracy is 25% for contract review** -- legal interpretations must be jurisdictionally correct with current case law
- **Creativity is zero** -- legal analysis must be grounded in statute, regulation, and precedent, not novel theories
- **Safety is 10% for due diligence** -- the "safety" dimension in legal contexts captures whether the analysis could expose the client to liability (e.g., waiving privilege, creating discoverable work product inadvertently)

### Legal-Specific Rubrics

Agent contributions are evaluated against legal-domain criteria:

**Accuracy Rubric** -- "Are legal interpretations, citations, and precedent references correct?"
- Score 1: Fundamental legal errors or misquoted statutes
- Score 3: Generally correct with minor citation gaps
- Score 5: Jurisdictionally accurate with comprehensive citations

**Completeness Rubric** -- "Does the analysis cover all relevant clauses, risks, and obligations?"
- Score 1: Missing critical contractual or regulatory provisions
- Score 3: Covers primary obligations and key clauses
- Score 5: Exhaustive coverage including edge cases and jurisdictional nuances

**Reasoning Rubric** -- "Is the legal reasoning sound with clear argumentation?"
- Score 1: No legal reasoning or illogical conclusions
- Score 3: Basic legal reasoning present
- Score 5: Rigorous legal analysis with alternative interpretations considered

### Agent Team Composition

Legal debates use specialized personas:

| Persona | Role | Focus |
|---------|------|-------|
| `contract_analyst` | Primary reviewer | Clause extraction, risk identification, term analysis |
| `compliance_officer` | Regulatory alignment | Applicable regulations, compliance gaps |
| `litigation_support` | Dispute perspective | Enforceability, dispute resolution, litigation exposure |
| `m_and_a_counsel` | Transaction analysis | Deal structure, due diligence, closing conditions |

The legal vertical configuration uses a deliberately low temperature ceiling (0.4) to minimize variability in legal interpretation -- legal analysis should be deterministic given the same facts and law.

---

## Privileged Decision Receipts

### Attorney-Client Privilege Considerations

> **Legal Disclaimer:** Attorney-client privilege implications of AI-assisted legal review vary by jurisdiction and specific circumstances. Nothing in this document constitutes legal advice. Organizations should consult qualified legal counsel in their jurisdiction before relying on any AI-assisted review tool in privileged communications or work product contexts.

Aragora's Decision Receipts are designed to support privilege claims when used within the appropriate context:

**When privilege may attach**:
- The debate is initiated by or at the direction of legal counsel
- The purpose is to provide or facilitate legal advice
- The analysis involves legal interpretation, not purely business analysis
- The receipt is maintained as confidential within the privilege scope

**Design features supporting privilege**:
- **Metadata control**: Receipts can be labeled with privilege designations and restricted to authorized personnel through Aragora's RBAC system
- **No third-party disclosure**: Debate content is processed through API calls to LLM providers (subject to their DPAs), but receipts are stored within your infrastructure
- **Compartmentalization**: Legal debates can be run in isolated tenants, separate from business operations, with access restricted to legal team members
- **Export control**: Receipt exports can be restricted by role, preventing inadvertent disclosure

**Important caveats**:
- The use of AI tools in legal analysis does not automatically create or destroy privilege. Consult your organization's legal ethics guidance.
- Work product protection may apply even where attorney-client privilege does not, if the analysis was prepared in anticipation of litigation.
- Sharing Decision Receipts beyond the privilege scope may result in waiver. Use Aragora's RBAC controls to enforce access boundaries.

---

## Example: Contract Review Debate Flow

```
1. INPUT
   General counsel submits: "Review proposed enterprise software license
   agreement with Vendor Corp. $1.2M/year, 5-year term. Flag high-risk
   provisions and recommend negotiation priorities."

   Contract is uploaded for clause extraction.

2. CLAUSE EXTRACTION (Pre-Debate)
   Automated extraction identifies:
   - Payment: Net 30, annual escalator of 5% (no cap)
   - Term: 5-year initial, auto-renew for successive 1-year terms
   - Termination: Vendor may terminate for convenience on 90 days' notice;
     Customer may terminate only for cause (uncured material breach)
   - Indemnification: Mutual for IP, but Customer indemnifies Vendor for
     "any claim arising from Customer's use of the Software"
   - Liability: Vendor liability capped at 12 months' fees;
     no cap on Customer's indemnification obligations
   - Data: Vendor retains "aggregated and anonymized" usage data in perpetuity
   - Governing law: Delaware (Vendor's state of incorporation)

3. ROUND 1 - INITIAL ANALYSIS
   Agent A (contract_analyst): "HIGH RISK. Three critical issues:
   (1) Asymmetric termination -- vendor can walk away, customer cannot.
   Combined with 5% annual escalator and no price cap on renewal,
   total 5-year commitment could reach $6.9M with no exit.
   (2) Customer indemnification is uncapped and overbroad -- 'any claim
   arising from use' could include Vendor's own defects.
   (3) Data retention clause creates perpetual license to Customer's
   usage patterns, which may include trade secrets."

4. ROUND 2 - COUNTERPARTY PERSPECTIVE
   Agent B (compliance_officer): "Vendor's likely position on each:
   (1) Termination asymmetry is justified because Vendor has made
   infrastructure investments specific to Customer. Market standard
   for enterprise SaaS is mutual termination for convenience.
   (2) Indemnification language is intentionally broad -- Vendor will
   argue it only covers misuse. But as drafted, it covers all use,
   including use exactly as intended. This must be narrowed.
   (3) Data retention: 'Aggregated and anonymized' is undefined.
   Vendor may argue de-identified data is not Customer's data.
   Recommend defining aggregation methodology and requiring
   certification of anonymization."

5. ROUND 3 - RISK ASSESSMENT
   Agent C (litigation_support): "Adding litigation risk analysis:
   (1) If Vendor terminates during a critical business period, Customer
   has no remedy beyond 'reasonable wind-down' -- which is undefined.
   In litigation, courts have interpreted similar clauses as 30-90 days.
   (2) The indemnification clause, if enforced as written, could expose
   Customer to uncapped liability for Vendor's own software defects
   discovered by third parties during Customer's use.
   (3) Governing law in Delaware may be disadvantageous -- Customer
   should push for home jurisdiction or neutral forum."

6. ROUNDS 4-5 - NEGOTIATION STRATEGY
   Agents synthesize into prioritized negotiation items:

   Priority 1 (Must-Have):
   - Add mutual termination for convenience with 180-day notice
   - Cap Customer indemnification at 24 months' fees
   - Narrow indemnification trigger to "Customer's breach of agreement
     or gross negligence"

   Priority 2 (Should-Have):
   - Cap annual price escalator at 3% or tie to CPI
   - Define "aggregated and anonymized" with specific methodology
   - Add right to audit Vendor's data anonymization practices

   Priority 3 (Nice-to-Have):
   - Mutual governing law (neutral jurisdiction)
   - Add SLA with financial penalties for downtime
   - Include MFN clause for pricing

7. DECISION RECEIPT
   - Receipt ID: LR-2026-0212-007
   - Risk Level: HIGH
   - Consensus: REACHED (88% confidence)
   - Agents consulted: 3 (contract_analyst, compliance_officer,
     litigation_support)
   - Rounds completed: 5
   - Key findings: 3 critical, 3 significant, 3 moderate
   - Integrity hash: SHA-256
```

---

## Contract Review Workflow

Aragora's contract review workflow template automates the full review pipeline:

```
Extract Key Terms (automated clause parsing)
         |
         v
Legal Analysis Debate (3 agents, 3 rounds)
   contract_analyst + risk_assessor + compliance_officer
         |
         v
Risk Assessment (automated routing)
    /        |        \
High Risk  Medium    Low Risk
    |       Risk        |
Human       |      Auto-Approve
Legal    Senior       |
Review   Review       |
    \       |        /
     +------+------+
            |
            v
     Store Analysis (Knowledge Mound)
```

- **High-risk contracts** (risk score > 0.7) route to senior legal counsel with a 48-hour review window and a structured checklist covering risk factors, compliance, indemnification exposure, termination provisions, and governing law
- **Medium-risk contracts** (risk score 0.4-0.7) route to senior review with a 24-hour window
- **Low-risk contracts** (risk score < 0.4) receive auto-approval with the full analysis stored for audit purposes

---

## Decision Receipt Format

```json
{
  "receipt_id": "LR-2026-0212-007",
  "timestamp": "2026-02-12T18:15:00Z",
  "schema_version": "1.0",
  "profile": "legal_contract",
  "verdict": {
    "consensus_reached": true,
    "confidence": 0.88,
    "final_answer": "HIGH RISK. Three critical provisions require negotiation..."
  },
  "audit_trail": {
    "agents_consulted": 3,
    "rounds_completed": 5,
    "votes_cast": 3,
    "dissenting_views_count": 0,
    "agent_summaries": [
      {"agent": "contract_analyst", "role": "proposer", "content_preview": "..."},
      {"agent": "compliance_officer", "role": "critic", "content_preview": "..."},
      {"agent": "litigation_support", "role": "synthesizer", "content_preview": "..."}
    ]
  },
  "integrity": {
    "artifact_hash": "d8f2a1..."
  }
}
```

Receipts are exportable as Markdown (for inclusion in legal memos), HTML (for client portals), SARIF (for integration with legal tech platforms), and CSV (for matter management systems).

---

## Getting Started

### 1. Install Aragora

```bash
pip install aragora
```

### 2. Configure API Keys

For legal analysis, multi-model consensus is strongly recommended to prevent single-model bias in interpretation:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

### 3. Run a Contract Review

```bash
aragora ask "Review this vendor agreement: 3-year SaaS license, $200K/year, \
  auto-renewal, vendor can terminate for convenience on 30 days' notice, \
  customer must provide 90 days' notice before renewal date. Indemnification \
  is mutual for IP infringement but one-way (customer only) for data breaches. \
  Liability cap is 6 months' fees. Assess risk and negotiation priorities." \
  --vertical legal \
  --rounds 5 \
  --consensus unanimous
```

### 4. Run a Due Diligence Assessment

```bash
aragora ask "Conduct preliminary due diligence assessment for acquisition of \
  a healthcare SaaS company. Key areas: (1) HIPAA compliance posture, \
  (2) customer contract assignability (change-of-control provisions), \
  (3) IP ownership for software developed by contractors, \
  (4) pending litigation and threatened claims. Identify top 5 risks." \
  --vertical legal \
  --enable-verticals \
  --rounds 5 \
  --decision-integrity
```

### 5. Run a Regulatory Compliance Review

```bash
aragora ask "Assess compliance requirements for launching a consumer lending \
  product in California, Texas, and New York. Cover: state licensing requirements, \
  federal TILA/Regulation Z disclosures, ECOA/Regulation B fair lending, \
  and FCRA obligations for credit reporting. Identify gaps in current compliance \
  program." \
  --vertical legal \
  --rounds 5
```

### 6. Programmatic Usage

```python
from aragora import Arena, Environment, DebateProtocol

env = Environment(
    task="Review indemnification clause: 'Customer shall indemnify Vendor against "
         "any and all claims arising from Customer's use of the Software.'",
    context="Enterprise SaaS agreement, $500K/year, Customer is a regulated entity.",
)

protocol = DebateProtocol(
    rounds=5,
    consensus="unanimous",
    weight_profile="legal_contract",
)

arena = Arena(env, agents, protocol)
result = await arena.run()

# Export for legal memo
from aragora.gauntlet.receipt import receipt_to_markdown
memo_content = receipt_to_markdown(result.receipt)
```

### 7. Use Pre-Built Workflow Templates

```python
from aragora.workflow.engine import WorkflowEngine

engine = WorkflowEngine()

# Run a contract review workflow
result = await engine.run_template(
    "template_legal_contract_review",
    inputs={
        "document": contract_text,
        "jurisdiction": "Delaware",
        "contract_type": "Enterprise SaaS License",
    },
)

# Run a due diligence workflow
result = await engine.run_template(
    "template_legal_due_diligence",
    inputs={
        "target_entity": "TargetCo, Inc.",
        "scope": "full",
        "deadline": "2026-03-15",
    },
)
```

---

## Frequently Asked Questions

**Does Aragora replace outside counsel?**
No. Aragora accelerates legal analysis and ensures comprehensive coverage, but it does not provide legal advice. The platform is designed as a force multiplier for legal teams -- surfacing issues faster, ensuring nothing is missed, and documenting the analysis for the record. Final legal judgment remains with qualified attorneys.

**How does adversarial debate improve contract review?**
A single model may identify obvious issues but miss subtle ones -- the interaction between a termination clause and an auto-renewal provision, for example, or the implication of an indemnification trigger that applies to "use" rather than "misuse." By structuring the review as a debate where one agent specifically argues the counterparty's position and another stress-tests enforceability, Aragora catches issues that single-pass review misses.

**What about attorney-client privilege?**
Aragora's architecture supports privilege claims through RBAC access controls, tenant isolation, and export restrictions. However, the use of AI tools does not automatically create or destroy privilege. Organizations should evaluate privilege implications within their specific practice context and applicable rules of professional conduct.

**Can I use Aragora for high-volume contract review?**
Yes. Aragora's batch processing mode can process contract portfolios in parallel. The pre-built contract review workflow automatically routes contracts by risk level -- low-risk contracts get auto-approved with a documented analysis, while high-risk contracts route to human review. This allows legal teams to focus human attention where it matters most.

**How accurate is the legal analysis?**
Accuracy depends on the underlying LLM providers and the specificity of the input. Aragora's legal weight profile allocates 25% weight to accuracy, and the adversarial debate structure means errors flagged by any one model are challenged by the others. The `legal_contract` profile uses a low temperature (0.4) to minimize variability in interpretation. That said, AI-generated legal analysis should always be reviewed by qualified counsel before reliance.

**Does Aragora support jurisdictional differences?**
Yes. The contract review workflow accepts a `jurisdiction` parameter, and agents are instructed to consider jurisdictional nuances in their analysis. For multi-jurisdictional matters (e.g., due diligence across US, UK, and EU), the agents factor in applicable local law. However, for matters requiring deep expertise in a specific jurisdiction's law, human legal review is essential.
