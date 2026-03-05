# Use Cases

Ten real-world scenarios where adversarial multi-agent debate improves decision quality. Each follows the same pattern: the problem, how Aragora addresses it, and what the output looks like.

---

## 1. Healthcare Clinical Decisions

**Problem**: A clinical decision support system recommends a treatment plan. One model's recommendation is not sufficient for patient safety -- biases in training data, missing drug interactions, and sycophantic agreement with the physician's initial impression all create risk. Regulatory requirements (HIPAA, EU AI Act) demand an auditable trail.

**Aragora Solution**: Route the clinical question through a structured debate with the `healthcare_hipaa` weight profile, which up-weights accuracy and safety dimensions. Multiple models independently evaluate the treatment plan, challenge each other on drug interactions, contraindications, and evidence quality, then produce a consensus with calibrated confidence.

**Connectors Used**: FHIR/HL7 ingestors for patient data, debate engine with healthcare rubrics, receipt exporter for HIPAA-compliant documentation.

**Receipt Output**: A Decision Receipt containing the treatment recommendation, dissent points (where models disagreed on risk), evidence citations, confidence calibration, and a SHA-256 signed audit hash. Exported as HTML for the clinical record and SARIF for integration with quality management systems.

**Value Delivered**: The hospital gets a defensible clinical decision -- not "GPT said to prescribe X" but "three independent AI models debated the treatment, two agreed on X while one flagged a potential interaction with the patient's existing medication, confidence was 78%, and the full debate transcript is cryptographically signed."

---

## 2. Financial Risk Assessment

**Problem**: A risk committee needs to evaluate a credit portfolio, an acquisition target, or a market position. Single-model analysis inherits the biases of its training data and tends to produce overconfident assessments. Regulators expect documented due diligence.

**Aragora Solution**: Run the risk assessment through a debate with the `financial_audit` weight profile. Models with different training data independently analyze the risk factors, challenge each other's assumptions about market conditions, correlation estimates, and tail risks. The Trickster detects hollow consensus where models agree without genuine reasoning -- a critical check for groupthink in financial analysis.

**Connectors Used**: Salesforce/CRM for portfolio data, debate engine with financial rubrics, Kafka for real-time market data via Pulse.

**Receipt Output**: Decision Receipt with risk scores from each model, specific disagreement points (e.g., correlation assumptions, stress test scenarios), calibrated confidence, and the full adversarial exchange. Exportable to CSV for integration with existing risk reporting tools.

**Value Delivered**: The risk committee sees not just the assessment, but exactly where the models disagreed and why. Split opinions on tail risk or correlation assumptions are surfaced explicitly rather than averaged away. The signed receipt satisfies regulatory documentation requirements.

---

## 3. Legal Contract Review

**Problem**: A legal team reviews a vendor contract, acquisition agreement, or regulatory filing. Single-model review misses clauses that interact in complex ways, and different legal traditions interpret the same language differently. Partner review time is expensive and slow.

**Aragora Solution**: Debate with the `legal_contract` weight profile. Models independently review the contract, flag risks, and challenge each other on clause interactions, jurisdictional issues, and precedent applicability. The `legal_due_diligence` profile adds extra weight to evidence and completeness dimensions.

**Connectors Used**: Document ingestion (PDF/DOCX via connectors), debate engine with legal rubrics, GitHub/Jira for tracking action items.

**Receipt Output**: Decision Receipt listing flagged clauses with severity, models that agreed vs. dissented on each issue, suggested revisions with consensus scores, and the full debate transcript.

**Value Delivered**: Junior associates get a multi-perspective first-pass review that catches cross-clause interactions. Partners see a prioritized list of genuine issues (high consensus) vs. judgment calls (split opinions). The receipt provides documentation that AI-assisted review was adversarially rigorous, not rubber-stamped.

---

## 4. Engineering Code Review

**Problem**: Pull requests get reviewed by one developer or one AI model, both of whom have blind spots. Single-model code review tends toward sycophantic "looks good" responses or flag superficial style issues while missing architectural problems.

**Aragora Solution**: `aragora review` runs your diff through multiple models in a structured debate. Models independently identify issues, then challenge each other's findings. When Claude flags a potential race condition and GPT disagrees, the debate transcript shows exactly why -- and whether the disagreement was resolved.

**Connectors Used**: GitHub connector for PR diffs, debate engine with code review rubrics, SARIF exporter for IDE integration.

**Receipt Output**: SARIF-format output with findings categorized by consensus level: unanimous issues (high confidence), majority issues, and split opinions requiring human judgment. Each finding includes the models that flagged it, the critique exchange, and a confidence score.

**Value Delivered**: Engineers see more than "3 issues found." They see which issues all models agree on (fix these), which had split opinions (review these), and where one model caught something the others missed (investigate these). The SARIF output integrates with existing CI/CD pipelines.

```bash
# Review your current changes
git diff main | aragora review --demo

# Review a GitHub PR with SARIF output
aragora review --pr https://github.com/org/repo/pull/123 --format sarif
```

---

## 5. Compliance Auditing

**Problem**: Organizations need to verify compliance with SOC 2, GDPR, HIPAA, or the upcoming EU AI Act. Manual audits are expensive, infrequent, and miss edge cases. Single-model compliance checks generate false positives and miss nuanced violations.

**Aragora Solution**: The Gauntlet runs adversarial stress tests against policies, architectures, and specifications using compliance-specific attack personas. Models assume the role of a GDPR auditor, a HIPAA inspector, or an AI Act assessor and try to find violations.

**Connectors Used**: Document ingestion for policy documents, Gauntlet runner with compliance personas, receipt exporter for audit documentation.

**Receipt Output**: Decision Receipt with identified compliance gaps, severity ratings based on model consensus, specific regulatory article references, and recommended remediations. Exportable to HTML for audit committee review.

**Value Delivered**: Continuous compliance validation rather than point-in-time audits. The adversarial approach means models actively try to find violations rather than passively confirming compliance. Receipts provide the documentation auditors need.

```bash
# Stress-test a policy document
aragora gauntlet policy.yaml --input-type policy --persona gdpr

# Full compliance audit with HTML report
aragora gauntlet architecture.md --profile thorough --output report.html
```

---

## 6. Knowledge Curation

**Problem**: Enterprise knowledge bases accumulate contradictions over time. Department A's documentation says one thing, Department B's says another. Single-model summarization inherits whichever source it reads first without flagging the conflict.

**Aragora Solution**: The Knowledge Mound with 41 adapters ingests knowledge from across the organization. Cross-debate learning means that when a debate surfaces new information, it is validated against existing knowledge. Contradiction detection identifies when new findings conflict with established knowledge.

**Connectors Used**: Confluence/Notion/SharePoint connectors for source ingestion, Knowledge Mound with contradiction detection, debate engine for validation.

**Receipt Output**: Knowledge validation reports showing newly added facts, detected contradictions with confidence scores, and resolution recommendations from adversarial debate.

**Value Delivered**: A knowledge base that gets more accurate over time rather than more stale. Contradictions are surfaced and resolved through adversarial debate rather than silently overwritten. Confidence decay ensures outdated information is flagged for re-validation.

---

## 7. Agent Governance

**Problem**: Your organization deploys autonomous AI agents (via CrewAI, LangGraph, AutoGen, or custom frameworks) that make decisions affecting customers, employees, or operations. You need policy-gated execution: agents must not exceed their authority.

**Aragora Solution**: The OpenClaw gateway provides policy-gated execution for external agents. Agent outputs are routed through adversarial debate before execution. Skill scanning blocks dangerous operations. RBAC ensures agents only access what they're authorized for. Audit logging records every invocation.

**Connectors Used**: OpenClaw gateway for agent integration, RBAC for policy enforcement, audit logging for compliance, debate engine for output vetting.

**Receipt Output**: Per-invocation audit records showing the agent's proposed action, the debate verdict (approved/denied/modified), policy rules that triggered, and the final executed action.

**Value Delivered**: Autonomous agents gain a governance layer without rebuilding them. The organization can deploy agents with confidence that policy violations will be caught, and regulators can see the audit trail proving governance was enforced.

---

## 8. Strategic Planning

**Problem**: A leadership team evaluates strategic options -- market entry, product direction, organizational restructuring. Single-model analysis tends to produce plausible-sounding recommendations without genuinely stress-testing the assumptions.

**Aragora Solution**: Frame each strategic option as a debate topic. Multiple models independently analyze the option, then play devil's advocate against each other's reasoning. The Gauntlet's adversarial personas (scaling critic, devil's advocate, red team) stress-test assumptions about market size, competitive response, and execution risk.

**Connectors Used**: Document ingestion for market research and internal data, debate engine with strategic rubrics, Slack/Teams for delivering results to stakeholders.

**Receipt Output**: Decision Receipt with each model's position, the adversarial challenges that were raised, which assumptions survived scrutiny and which didn't, and a calibrated confidence score for each strategic option.

**Value Delivered**: Leadership sees not just "here's what we should do" but "here are the three strongest objections to this plan, and here's how well they survived scrutiny." The difference between a confident recommendation and a genuinely stress-tested one.

---

## 9. Research Synthesis

**Problem**: Synthesizing findings across multiple papers, studies, or data sources. Single-model synthesis tends to produce plausible narratives that smooth over genuine disagreements in the literature.

**Aragora Solution**: Models independently review the source material and produce synthesis proposals. The critique phase specifically targets: are there contradictions between sources that the synthesis glosses over? Are confidence claims warranted by the underlying evidence? Is the synthesis cherry-picking supportive findings?

**Connectors Used**: Document ingestion for papers and datasets, Knowledge Mound for cross-reference, debate engine with research rubrics, webhook delivery for integration with research tools.

**Receipt Output**: Research synthesis with explicit annotation of where sources agree, where they disagree, the strength of evidence for each claim, and which conclusions survived adversarial challenge. Full provenance tracking to source documents.

**Value Delivered**: Research teams get a synthesis that honestly represents the state of the evidence rather than constructing a neat narrative. Disagreements in the literature are surfaced as features, not bugs.

---

## 10. Policy Analysis

**Problem**: Government and institutional policy decisions affect millions of people. Analysis produced by a single model or a single perspective risks encoding blind spots into policy. Stakeholder impact assessment needs to consider perspectives that the analyst might not naturally adopt.

**Aragora Solution**: Debate with models assigned different stakeholder perspectives. One model argues from the perspective of affected communities, another from implementation feasibility, another from fiscal impact, another from legal precedent. The adversarial structure ensures that each perspective genuinely challenges the others rather than producing a bland "on the one hand, on the other hand" summary.

**Connectors Used**: Document ingestion for policy drafts and impact data, debate engine with policy rubrics, email/webhook delivery for stakeholder distribution.

**Receipt Output**: Decision Receipt with each stakeholder perspective's strongest arguments, the points of genuine conflict, which tradeoffs the policy makes, and a calibrated assessment of implementation feasibility.

**Value Delivered**: Policy makers see a genuine multi-perspective analysis rather than a single model's attempt at "balanced" analysis. The adversarial structure prevents the analysis from defaulting to the perspective of whoever wrote the prompt.

---

## Getting Started

Each use case is supported by Aragora today. To try the simplest path:

```bash
# Install
pip install aragora

# Run a basic debate (demo mode, no API keys needed)
aragora ask "Should we adopt microservices?" --demo

# Review code with multi-model consensus
git diff main | aragora review --demo

# Stress-test a document
aragora gauntlet spec.md --profile quick
```

See [examples/quickstart/](../examples/quickstart/) for runnable code, or [WHY_ARAGORA.md](WHY_ARAGORA.md) for the technical thesis behind the platform.
