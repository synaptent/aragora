# Aragora Business Summary

**The Decision Integrity Platform**

*Version 2.8.0 | February 2026*

---

## 1. Executive Summary

Aragora is the first **Decision Integrity Platform**: software that uses adversarial multi-agent debate across heterogeneous LLM providers to vet, challenge, and audit important decisions before they ship.

Every consequential AI decision today rests on a single model's output. This is structurally unsound. Models share training data, exhibit sycophantic agreement, and produce no audit trail. Stanford's taxonomy of LLM reasoning failures documents systematic breakdowns even in frontier models. Confidence scores do not correlate with accuracy.

Aragora treats each model as an **unreliable witness** and uses a structured debate protocol to extract signal from disagreement:

```
PROPOSE → CRITIQUE → REVISE → VOTE → SYNTHESIZE → DECISION RECEIPT
```

When 43 agent types across 6+ LLM providers (Anthropic, OpenAI, Google, xAI, Mistral, OpenRouter) independently converge after adversarial challenge, that convergence is meaningful. When they disagree, the dissent trail tells you exactly where human judgment is needed.

The output is a cryptographic **Decision Receipt** -- a tamper-evident audit artifact with SHA-256 hash chains, consensus proofs, and confidence calibration. This is the document that regulators, compliance teams, and boards need.

**Category:** Decision Integrity is a new category. No well-funded competitor builds adversarial decision vetting with heterogeneous models. The EU AI Act high-risk enforcement begins **August 2, 2026**, creating urgency for exactly this capability.

---

## 2. Use Cases & Verticals

### Primary Market: SMB Teams (5-200 people)

Engineering, operations, legal, and product teams making consequential decisions with AI. Multi-agent debate gives a 5-person team the decision rigor that used to require a 50-person committee.

**Entry points:** AI code review (`aragora review`) and spec stress-testing (`aragora gauntlet`) for engineering-led organizations. Zero-config demo mode lowers onboarding friction to 30 seconds.

### Secondary Market: Regulated Enterprise

Healthcare, finance, legal, and government organizations that need auditable AI decisions for EU AI Act compliance, SOC 2 audits, HIPAA workflows, and board-level decision documentation.

### Verticals

| Vertical | Use Case | Value Proposition | Compliance Fit |
|---|---|---|---|
| **Software Engineering** | AI code review, architecture vetting, spec stress-testing | Multi-model consensus catches issues single reviewers miss; CI/CD integration via GitHub Actions | SOC 2 change management |
| **Healthcare** | Clinical decision support, protocol review, drug interaction analysis | FHIR R4 integration (Epic, Cerner); adversarial vetting reduces diagnostic errors | HIPAA (field-level AES-256-GCM encryption) |
| **Financial Services** | Risk assessment, trading strategy review, fraud investigation | Audit-grade decision trails with SHA-256 integrity; multi-model reduces correlated risk | SOX audit trails, regulatory examination |
| **Legal** | Contract review, due diligence, litigation risk analysis | Adversarial clause analysis mirrors legal dialectic; counterparty perspective built in | Decision receipts document reasoning chain |
| **Government / Defense** | Policy analysis, procurement decisions, classified environments | Self-hosted and air-gapped deployment; no phone-home telemetry | FedRAMP-ready architecture |
| **Compliance** | SOC 2 audit prep, GDPR assessment, EU AI Act readiness | Compliance artifacts generated as byproduct of decision improvement | SOC 2, GDPR, HIPAA, EU AI Act |

### Hero Use Cases

1. **AI Code Review** -- `git diff main | aragora review --demo` runs multi-agent consensus review with zero configuration. Models from different providers catch different classes of bugs, security issues, and design problems. Results in minutes, not days.

2. **Gauntlet Stress-Testing** -- `aragora gauntlet spec.md` runs 4 adversarial attack personas (Security, Devil's Advocate, Scaling Critic, Compliance) against any specification, architecture, or policy document. Produces a go/no-go report suitable for leadership.

3. **Idea-to-Execution Pipeline** -- A 4-stage pipeline (Ideas → Goals → Workflows → Orchestration) that transforms debate outcomes into executable plans with DAG-based workflow automation, bridging the gap between decision and implementation.

---

## 3. Feature Inventory

### Platform Capabilities

| Category | Capabilities | Scale |
|---|---|---|
| **Core Debate** | Propose/Critique/Revise/Vote/Synthesize loop; 8+ consensus modes; 50+ round extended debates; graph and matrix debate topologies; debate breakpoints (pause/resume) | 50+ concurrent debates |
| **Decision Receipts** | SHA-256 hash chains; HMAC-SHA256, RSA-SHA256, Ed25519 signing; Markdown, HTML, PDF, SARIF, CSV export; retention policies | Tamper-evident audit artifacts |
| **Pipeline** | 4-stage Idea-to-Execution; canvas orchestration; post-debate automated workflows; argument cartography | DAG-based automation |
| **Knowledge & Memory** | 4-tier Continuum Memory (fast/medium/slow/glacial); Knowledge Mound with 41 adapters; cross-debate institutional memory; unified memory gateway | Semantic search + dedup |
| **Agent System** | 43 agent types; 6+ LLM providers; ELO rankings per domain; Brier score calibration; Trickster hollow consensus detection; automatic OpenRouter fallback | Heterogeneous multi-provider |
| **Enterprise Security** | OIDC/SAML SSO (Azure AD, Okta, Google, Auth0, Keycloak); MFA (TOTP/HOTP); SCIM 2.0 provisioning; RBAC v2 with 390+ permissions; multi-tenancy with isolation | 7 default roles |
| **Compliance** | SOC 2 controls; GDPR (deletion/export/consent/anonymization); HIPAA (field-level encryption); EU AI Act artifact generation (Articles 9, 12-15) | 5 regulatory frameworks |
| **Connectors** | Slack, Teams, Discord, Telegram, WhatsApp, email, voice; Salesforce, SAP, ServiceNow, Zendesk, HubSpot; Zapier (200+ apps) | 15+ platform integrations |
| **Workflow** | DAG engine; 50+ pre-built templates across 6 categories; pattern factories; custom workflow nodes | Template marketplace |
| **Gauntlet** | 4 adversarial attack personas; automated stress-testing; cryptographic receipts; CI/CD gate integration; proposer defense cycles | Go/no-go reports |
| **Verification** | Z3 SMT solver for formal proofs; Lean verification backend; argument structural soundness checking | Mathematical proof generation |
| **Self-Improvement** | Nomic Loop (autonomous debate → design → implement → verify); MetaPlanner with 12 signal sources; outcome feedback bridge; cross-cycle learning | Compounds over time |
| **Voice** | TTS integration; voice stream management; real-time debate narration | Multi-channel delivery |
| **Blockchain** | ERC-8004 agent identity; reputation registries; on-chain decision anchoring | Immutable agent records |
| **SDKs** | Python SDK (184 namespaces); TypeScript SDK (183 namespaces); typed clients for all API operations; full IntelliSense | 99.3% cross-language parity |
| **Deployment** | Docker Compose; Kubernetes + Helm (HPA, PDB, network policies); Terraform (AWS); offline/air-gapped mode; multi-region (US, EU, APAC) | Zero external dependencies in offline mode |

### Platform Scale

| Metric | Value |
|---|---|
| Python modules | 3,200+ |
| Lines of code | 1,490,000 |
| Automated tests | 208,000+ |
| Test files | 4,300+ |
| API operations | 3,000+ across 2,900+ paths |
| WebSocket event types | 190+ |
| Debate modules | 210+ |
| Handler modules | 580+ |
| Current version | v2.8.0 |
| GA readiness | 98% |

---

## 4. Go-to-Market Strategy

### GTM Thesis: Developer-First, Bottom-Up

Developers adopt code review and gauntlet stress-testing → teams adopt for decision governance → enterprises adopt for compliance. This mirrors the adoption patterns of GitHub, Datadog, and Snyk.

### Phase 1: Developer Adoption (Months 1-3)

| Activity | Detail |
|---|---|
| **PyPI launch** | `pip install aragora` and `pip install aragora-debate` (standalone debate engine) |
| **GitHub Action** | Pre-merge debate gate for CI/CD pipelines |
| **Demo mode** | Zero-config experience with no API keys needed |
| **Content** | Technical blog posts: "Multi-Agent Code Review", "Stress-Testing Specs with Gauntlet", "EU AI Act Compliance Artifacts" |
| **Community** | Open-source core (MIT license); Discord community; example repositories |
| **Target** | 500 free users; initial organic adoption from engineering teams |

### Phase 2: Free-to-Pro Conversion (Months 4-6)

| Activity | Detail |
|---|---|
| **Conversion levers** | Unlimited debates, cryptographic signing, channel delivery, workflow engine |
| **EU AI Act urgency** | Enforcement August 2, 2026 -- "6 months to comply" messaging for regulated industries |
| **Vertical content** | Healthcare FHIR guide, Financial SOX workflow, Legal due diligence accelerator |
| **Channel partners** | SOC 2 auditors, GDPR consultants who need decision audit tooling for their clients |
| **Target** | 12 Pro teams ($49/seat/month); 2 enterprise pilots initiated |

### Phase 3: Enterprise Expansion (Months 7-12)

| Activity | Detail |
|---|---|
| **Enterprise pilots → contracts** | Convert Phase 2 pilots to annual contracts |
| **Vertical packages** | Pre-configured debate profiles, compliance templates, and connector bundles per industry |
| **Cloud marketplace** | AWS Marketplace and Azure Marketplace listings for procurement ease |
| **SOC 2 Type II** | Complete certification to unlock enterprise purchasing |
| **Target** | 60 Pro teams; 6 enterprise contracts; marketplace revenue share |

### Pricing

| Tier | Price | Target | Key Features |
|---|---|---|---|
| **Free** | $0 forever | Individual developers | 10 debates/month, 3 agents/debate, demo mode, Markdown receipts |
| **Pro** | $49/seat/month | SMB teams (5-50) | Unlimited debates, 10 agents/debate, cryptographic signing, all export formats, CI/CD integration, channel delivery, 4-tier memory, workflow engine |
| **Enterprise** | Custom | Regulated orgs (50+) | Everything in Pro + SSO/MFA/SCIM, RBAC (390+ permissions), multi-tenancy, field-level encryption, compliance frameworks, self-hosted/air-gapped, Kafka/RabbitMQ, custom SLA |

**BYOK model:** Customers bring their own LLM provider API keys. Aragora does not mark up LLM costs. Near-zero cost of goods sold on the platform side -- infrastructure costs are ~$5/month base per customer. This produces software-like gross margins (85%+) without the typical AI infrastructure cost burden.

### Channel Partners

| Partner Type | Value Exchange |
|---|---|
| **SOC 2 auditors** | Recommend Aragora for decision audit trails; receive referral revenue |
| **GDPR consultants** | Bundle Aragora's EU AI Act artifacts with compliance advisory |
| **Systems integrators** | Deploy and customize enterprise Aragora instances |
| **Cloud marketplaces** | AWS/Azure listings for streamlined enterprise procurement |

---

## 5. Revenue Projections

### Assumptions (Conservative, Bottoms-Up)

| Assumption | Value | Rationale |
|---|---|---|
| Free-to-Pro conversion rate | 2-3% | Industry standard for developer tools (Snyk ~2.5%, GitLab ~3%) |
| Average Pro team size | 5 seats | SMB engineering/ops teams |
| Pro monthly churn | 5% | Early-stage SaaS benchmark |
| Enterprise ACV | $15,000-$25,000 | Mid-market entry point; vertical compliance value justifies premium |
| Enterprise sales cycle | 3-6 months | Pilots in Phase 2 → contracts in Phase 3 |
| Time to first enterprise close | Month 7 | Allows for pilot + procurement cycle |

### Month-by-Month Projection

| Month | Free Users | Pro Teams | Enterprise | Pro MRR | Enterprise MRR | Total MRR |
|---|---|---|---|---|---|---|
| 1 | 50 | 0 | 0 | $0 | $0 | $0 |
| 2 | 150 | 1 | 0 | $245 | $0 | $245 |
| 3 | 500 | 2 | 0 | $490 | $0 | $490 |
| 4 | 900 | 4 | 0 | $980 | $0 | $980 |
| 5 | 1,500 | 7 | 0 | $1,715 | $0 | $1,715 |
| 6 | 2,500 | 12 | 0 (2 pilots) | $2,940 | $0 | $2,940 |
| 7 | 3,500 | 18 | 1 | $4,410 | $1,667 | $6,077 |
| 8 | 4,500 | 25 | 2 | $6,125 | $3,333 | $9,458 |
| 9 | 5,500 | 32 | 3 | $7,840 | $5,000 | $12,840 |
| 10 | 6,500 | 40 | 4 | $9,800 | $6,667 | $16,467 |
| 11 | 7,500 | 50 | 5 | $12,250 | $8,333 | $20,583 |
| 12 | 8,500 | 60 | 6 | $14,700 | $10,000 | $24,700 |

*Pro MRR = teams x 5 seats x $49/seat. Enterprise MRR = contracts x $20,000 ACV / 12.*

### Revenue Milestones

| Milestone | Month | MRR | ARR | Key Indicators |
|---|---|---|---|---|
| **First revenue** | 2 | $245 | $2,940 | First Pro conversion from organic adoption |
| **Product-market signal** | 3 | $490 | $5,880 | 500 free users, 2 Pro teams, retention > 90% |
| **Enterprise pipeline** | 6 | $2,940 | $35,280 | 12 Pro teams, 2 enterprise pilots active |
| **Enterprise revenue** | 7 | $6,077 | $72,924 | First enterprise contract closed |
| **Scaling** | 12 | $24,700 | $296,400 | 60 Pro teams, 6 enterprise contracts, ~60/40 Pro/Enterprise mix |

### Revenue Mix at Month 12

- **Pro revenue:** $14,700/month (59%)
- **Enterprise revenue:** $10,000/month (41%)
- **Total MRR:** $24,700
- **Total ARR:** ~$296,000

By month 18-24 (beyond this projection), enterprise revenue is expected to exceed Pro revenue as the sales cycle matures and vertical packages drive larger contract values.

### Path to Profitability

The BYOK model is Aragora's structural cost advantage. Customers use their own LLM provider API keys, so Aragora bears no inference costs. Platform infrastructure costs ~$5/customer/month. At 60 Pro teams and 6 enterprise contracts:

- **Gross margin:** 85-90% (infrastructure only, no LLM COGS)
- **Monthly infrastructure cost:** ~$500 (hosting, CI/CD, monitoring)
- **Monthly revenue:** $24,700
- **Contribution margin:** ~$24,200/month

Profitability depends on team size and go-to-market spend, but the unit economics are favorable from Day 1.

### Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Slow developer adoption** | Delayed Pro conversions | Demo mode removes all friction; code review is immediately useful; EU AI Act creates urgency |
| **Enterprise sales cycle longer than expected** | Revenue ramp delay | Focus on SMB Pro revenue first; enterprise is upside, not dependency |
| **LLM provider pricing changes** | Customer cost concerns | BYOK model insulates Aragora; multi-provider support prevents lock-in |
| **Competitor entry** | Category pressure | 1.49M LOC, 208K tests, 41 KM adapters create deep technical moat; self-improving Nomic Loop compounds advantage |
| **EU AI Act enforcement delayed** | Reduced urgency | Product value stands without regulation (decision quality + audit trails); regulation is accelerant, not dependency |

---

## 6. Competitive Landscape

### Market Positioning

```
                    Adversarial
                        ^
                        |
                   Aragora (alone)
                        |
    Single-provider ----+---- Multi-provider
                        |
         OpenAI Agents  |  LangGraph, CrewAI, AutoGen
                        |
                        v
                    Cooperative
```

Aragora is the only platform in the adversarial + multi-provider quadrant. Competitors build cooperative orchestration with single or multiple providers. None produce cryptographic decision receipts, track agent calibration, or self-improve through autonomous debate.

### Competitive Comparison

| Capability | Aragora | LangGraph ($260M) | CrewAI ($25M) | AutoGen |
|---|---|---|---|---|
| Adversarial debate protocol | Built-in | Manual (build yourself) | No | No |
| Cryptographic decision receipts | SHA-256, RSA, Ed25519 | No | No | No |
| Agent calibration (ELO + Brier) | Per-agent, per-domain | No | No | No |
| Multi-model consensus | 43 agents, 6+ providers | Multi-provider | Single-provider focus | Multi-provider |
| Compliance artifact generation | SOC 2, GDPR, HIPAA, EU AI Act | No | No | No |
| Self-improvement (Nomic Loop) | Autonomous, safety-gated | No | No | No |
| Enterprise security (SSO/RBAC/encryption) | Production-ready | No | No | No |

### Honest Assessment

**Strengths:** Category definition (Decision Integrity), cryptographic receipts, agent calibration, self-improvement, regulatory timing.

**Gaps:** Community size (LangChain has massive adoption), funding (bootstrapped vs. $260M+), documentation breadth (competitors have video walkthroughs and large example libraries), simplicity for basic automation tasks (CrewAI's decorator API is simpler for cooperative pipelines).

**Strategic position:** Aragora is not competing with cooperative orchestration frameworks. It is complementary -- use LangGraph to build your agent pipeline, route the output through Aragora to vet the decision before it ships. The competitive risk is a well-funded player adding adversarial features to an existing framework, but the depth of Aragora's debate engine (210+ modules, calibrated trust, formal verification) creates a meaningful technical moat.

---

*For technical details, see [COMMERCIAL_OVERVIEW.md](COMMERCIAL_OVERVIEW.md). For the full positioning narrative, see [WHY_ARAGORA.md](WHY_ARAGORA.md). For enterprise capabilities, see [enterprise/ENTERPRISE_FEATURES.md](enterprise/ENTERPRISE_FEATURES.md).*
