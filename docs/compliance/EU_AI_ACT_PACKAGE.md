# EU AI Act Compliance Package (H1-05)

> **One-page hand-off artifact for buyers in regulated verticals**
> (fintech, healthcare, legal, HR, education). Bundles the compliance
> artifacts Aragora already produces into a sellable form ahead of the
> **August 2, 2026** high-risk enforcement deadline.
>
> **Status:** packaging only. No new enforcement code is added in H1.
> Everything described here ships from existing modules:
> `aragora.compliance`, `aragora.receipts`, `aragora.policy`, and the
> Gauntlet + Knowledge Mound subsystems that already back the decision
> receipt pipeline.

---

## What this package is

A single entry point that lets a regulated buyer understand, in one read,
what Aragora generates today that directly maps to EU AI Act obligations —
and what the buyer still owns.

- **Audience:** compliance officers, CISOs, AI governance leads in fintech,
  healthcare, legal, HR, education, law enforcement, and critical
  infrastructure organizations subject to Annex III obligations.
- **Form factor:** this doc (publishable as-is) + the existing artifact
  bundle generator (`aragora compliance export`) + the CLI/SDK listed
  below.
- **Non-form factor:** no new models, no new enforcement engine, no
  notified-body relationship, no Annex IV technical file template, no
  certification claim.

---

## What Aragora provides (already shipping)

| Capability | Where it lives today | How it maps to the EU AI Act |
|---|---|---|
| **Decision receipts** with cryptographic chain of custody | `aragora/compliance/artifacts.py`, `aragora/receipts/` | Art. 12 (record-keeping), Art. 15 (integrity) |
| **Policy gates** that run before execution | `aragora/policy/` | Art. 9 (risk management measures), Art. 14 (human oversight) |
| **Dissent capture** at debate time | `aragora/debate/` → `DebateResult.dissenting_opinions` | Art. 13 (transparency), Art. 14 (override capability) |
| **Provenance links** from evidence → claim → decision | `aragora/knowledge/`, `aragora/reasoning/provenance.py` | Art. 12 (traceability), Art. 13 (reasoning chain) |
| **Audit trail exports** in regulator-ready formats | `aragora compliance export`, `aragora compliance eu-ai-act generate` | Art. 12 (automatic logging), Art. 11 supporting content |
| **Adversarial stress tests** (Gauntlet) | `aragora/gauntlet/` | Art. 9 (foreseeable misuse), Art. 15 (robustness) |
| **Risk classifier** for Annex III use cases | `aragora/compliance/risk_classifier.py` | Art. 6 (classification), Art. 5 (prohibited-practice detection) |
| **Human-in-the-loop / human-on-the-loop** oversight model | `aragora/debate/protocol.py`, approval flows | Art. 14 (oversight capability, override, stop) |
| **Multi-model consensus** across heterogeneous agents | `aragora/agents/` (46 agent types) | Art. 10 bias mitigation (supplementary) |

### One-sentence pitch

> Aragora produces EU AI Act Article 9, 12, 13, 14, and 15 evidence as a
> side effect of running the decision, with SHA-256 integrity hashes and
> a regulator-ready artifact bundle, on every decision.

---

## What the buyer still owns

Aragora does **not** certify, assess, register, or legally attest. These
obligations stay with the deploying organization:

| Article | Obligation | Owner | Aragora's role |
|---|---|---|---|
| Art. 10 | Training data governance | Model providers (Anthropic, OpenAI, Google, Mistral, …) | Multi-model consensus reduces single-provider training bias |
| Art. 11 / Annex IV | Technical documentation file | Buyer | Generated artifacts feed Sections 1, 2, 5 of the Annex IV file |
| Art. 43 | Conformity assessment | Buyer + notified body | Bundle feeds the assessor; Aragora does not perform the assessment |
| Art. 47 | Declaration of conformity | Buyer | Issued after Art. 43 assessment |
| Art. 49 | EU database registration | Buyer | Classification output can be used as supporting input |

This boundary is intentional and kept explicit in the customer playbook
(`EU_AI_ACT_CUSTOMER_PLAYBOOK.md` → "Shared Responsibility" section) and
in the legal-review language of this package.

---

## Runbook: generate the bundle for a real decision

Three commands, no API keys required for the first one.

```bash
# 1. Classify your AI use case (returns risk tier + applicable articles)
aragora compliance classify \
  "AI-assisted CV screening for automated hiring decisions"

# 2. Export the per-article compliance bundle
aragora compliance export \
  --debate-id <DEBATE_ID> \
  --output-dir ./compliance-bundle/

# 3. (Regulated submission) Generate formal Article 12/13/14 artifacts
aragora compliance eu-ai-act generate receipt.json \
  --output ./regulator-bundle/ \
  --provider-name "Your Organization" \
  --provider-contact "compliance@your-org.eu" \
  --eu-representative "Your EU Rep, Berlin, Germany" \
  --system-name "Your Decision Platform" \
  --system-version "1.0.0"
```

The per-article bundle produced by step 2 is listed in
[`EU_AI_ACT_CUSTOMER_PLAYBOOK.md`](EU_AI_ACT_CUSTOMER_PLAYBOOK.md#what-you-get).
The formal submission bundle produced by step 3 is fully worked in
[`EU_AI_ACT_SAMPLE.md`](EU_AI_ACT_SAMPLE.md).

### SDK-equivalent (Python)

```python
from aragora.compliance import ComplianceArtifactGenerator, RiskClassifier

# 1. Classify
classifier = RiskClassifier()
classification = classifier.classify(
    "AI-assisted CV screening for automated hiring decisions",
)

# 2. Export bundle from a receipt
generator = ComplianceArtifactGenerator()
bundle = generator.generate_bundle(
    receipt=my_decision_receipt,
    classification=classification,
    output_dir="./compliance-bundle/",
)
print(bundle.compliance_score, bundle.article_status)
```

Full reference: [`EU_AI_ACT_GUIDE.md`](EU_AI_ACT_GUIDE.md) → "Python API
Reference".

---

## Buyer journey

1. **Scoping call (15 min)** — buyer shares their highest-risk AI
   use-case description. Aragora runs `compliance classify` live;
   hand back the risk tier, Annex III category, and applicable articles.
2. **Demo bundle (5 min)** — run `aragora compliance export --demo
   --output-dir ./demo-pack` and walk through the per-article markdown
   and `bundle.json`. This is the fit check: buyer sees exactly what
   Aragora produces before signing anything.
3. **Pilot scoping (30 min)** — pick one real decision the buyer cares
   about (vendor selection, hiring shortlist, credit tier, treatment
   recommendation). Scope the decision as an Aragora debate.
4. **Pilot run** — buyer runs the decision through Aragora, receives the
   bundle, reviews compliance score and per-article status.
5. **Follow-on** — if the pilot clears, move to production rollout with
   periodic bundle generation per Art. 12 retention.

Target conversion: a regulated fintech / healthcare / legal / HR
prospect can receive this package, understand what Aragora provides
for EU AI Act compliance, and make a buying decision within one call.

---

## Sellable artifacts in this package

| Artifact | Path | Use in the sale |
|---|---|---|
| This package doc | `docs/compliance/EU_AI_ACT_PACKAGE.md` | Primary leave-behind; one-page fit summary |
| Customer playbook | [`docs/compliance/EU_AI_ACT_CUSTOMER_PLAYBOOK.md`](EU_AI_ACT_CUSTOMER_PLAYBOOK.md) | Onboarding and 5-minute quickstart |
| Full technical guide | [`docs/compliance/EU_AI_ACT_GUIDE.md`](EU_AI_ACT_GUIDE.md) | Deep-dive for compliance / CISO evaluation |
| Article-by-article checklist | [`docs/compliance/EU_AI_ACT_CHECKLIST.md`](EU_AI_ACT_CHECKLIST.md) | Buyer compliance-tracking spreadsheet |
| Worked sample bundle | [`docs/compliance/EU_AI_ACT_SAMPLE.md`](EU_AI_ACT_SAMPLE.md) | Reference output for procurement review |
| Combined compliance bundle (SOC 2, GDPR, EU AI Act, etc.) | [`docs/compliance/COMPLIANCE_BUNDLE.md`](COMPLIANCE_BUNDLE.md) | Shows EU AI Act inside broader posture |

All artifacts are kept in this repo; none require Aragora Enterprise to
generate.

---

## Legal-safe claim language (use verbatim in buyer collateral)

- "Aragora generates the Article 9, 12, 13, 14, and 15 evidence required
  for a high-risk AI system's technical file."
- "Aragora produces SHA-256 integrity hashes for every decision receipt
  and audit trail."
- "Aragora supports the Annex IV technical documentation file; it does
  not replace the file, nor perform a conformity assessment."
- "The final compliance determination, notified-body engagement,
  declaration of conformity, and EU database registration are the
  responsibility of the deploying organization."

**Do not claim** (legal review blockers):

- "Aragora is EU AI Act certified."
- "Using Aragora guarantees EU AI Act compliance."
- "Aragora's compliance score is an official regulatory metric."
- "Aragora performs a conformity assessment under Article 43."

---

## Non-goals (explicit H1 boundary)

Per [H1-05 scope](../plans/2026-04-18-3-horizon-roadmap.md) the 30-day
horizon packages what exists. It does **not**:

- build new Annex IV technical-file generation
- engage a notified body or pursue certification
- implement ERC-8004 live-chain attestation of receipts
- add new enforcement code paths beyond packaging docs and pointers
- onboard regulated design partners (that is H2-07)
- ship changes to the compliance module's Python API
- restructure existing `docs/compliance/EU_AI_ACT_*.md` files

Deeper engineering (certification-body engagement, Annex IV automation,
ERC-8004 graduated writes) remains planning-only until H2/H3 per the
3-horizon roadmap.

---

## Exit proof (H1-05 acceptance)

A regulated fintech / healthcare / legal / HR prospect can be sent this
file and:

1. Understand what Aragora produces for EU AI Act compliance **without
   further engineering**.
2. Understand what their organization still owns (Art. 10, 11, 43, 49).
3. Run a demo bundle in under 5 minutes with the commands above.
4. Make an initial pilot decision within a single call.

## Related

- [3-Horizon Execution Roadmap H1-05](../plans/2026-04-18-3-horizon-roadmap.md)
- [ARAGORA_EVOLUTION_ROADMAP.md Track F5](../plans/ARAGORA_EVOLUTION_ROADMAP.md)
- GitHub: epic #6226, subtask #6231
