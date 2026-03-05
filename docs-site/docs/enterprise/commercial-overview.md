---
title: Aragora Commercial Overview
description: Aragora Commercial Overview
---

# Aragora Commercial Overview

**The Decision Integrity Platform** -- adversarial multi-agent debate that produces decisions you can audit and trust.

---

## Product Positioning

Aragora is the first **Decision Integrity Platform**: software that uses adversarial multi-agent debate across heterogeneous LLM providers to vet, challenge, and audit important decisions before they ship.

The output is not just an answer -- it is a cryptographic **Decision Receipt** proving the answer was rigorously examined, complete with consensus proofs, dissent trails, and confidence calibration. This receipt is the audit artifact that regulators, compliance teams, and boards need.

Individual LLMs are unreliable. [Stanford's taxonomy of LLM reasoning failures](https://arxiv.org/abs/2602.06176) documents systematic breakdowns in formal logic, unfaithful chain-of-thought reasoning, and robustness failures under minor prompt variations -- even in frontier models. Confidence scores do not correlate with accuracy. Models converge on whatever the user seems to want rather than whatever is correct.

Aragora treats each model as an **unreliable witness** and uses structured debate (Propose / Critique / Revise / Vote / Synthesize) across models with genuinely different training data and failure modes to extract signal from their disagreements. When heterogeneous models converge after adversarial challenge, that convergence is meaningful. When they disagree, the dissent trail tells you exactly where human judgment is needed.

### What Aragora Is

- A multi-agent debate engine that runs 43 agent types across 6+ LLM providers
- A decision audit system that produces cryptographic receipts for every decision
- An adversarial stress-testing tool (Gauntlet mode) for specs, policies, and architectures
- An AI code review system with multi-model consensus
- A platform with 3,000+ API operations, SDKs in Python and TypeScript, and connectors for Slack, Teams, Discord, and dozens more

### What Aragora Is Not

- Not an LLM. Aragora orchestrates existing models from Anthropic, OpenAI, Google, xAI, Mistral, and others.
- Not a chatbot. Aragora is infrastructure for decision quality, not conversation.
- Not a replacement for LangChain/CrewAI. Those are cooperative orchestration frameworks. Aragora is adversarial decision vetting. They are complementary -- use them upstream, route decisions through Aragora for vetting.

---

## Target Markets

### Primary: SMB Teams (5-200 people)

Small and medium businesses making consequential decisions with AI -- engineering teams reviewing architecture, operations teams vetting vendor selections, legal teams assessing contract risk, product teams evaluating strategy.

**Value proposition:** Multi-agent debate gives a 5-person team access to decision rigor that used to require a 50-person committee. Decision receipts give small teams the audit trail that enterprise compliance requires.

**Entry point:** AI code review (`aragora review`) and spec stress-testing (`aragora gauntlet`) for engineering-led organizations.

### Secondary: Enterprise Scale-Up

Regulated enterprises in healthcare, finance, legal, and government that need auditable AI decisions for EU AI Act compliance (enforcement begins August 2, 2026), SOC 2 audits, HIPAA workflows, and board-level decision documentation.

**Value proposition:** Compliance-ready decision receipts generated as a byproduct of improving the decision itself. Enterprise security features -- OIDC/SAML SSO, multi-tenant isolation, RBAC with 390+ permissions, AES-256-GCM encryption -- are built in, not bolted on.

### Verticals with Strongest Fit

| Vertical | Use Case | Why Aragora |
|---|---|---|
| **Software Engineering** | AI code review, architecture vetting, spec stress-testing | Multi-model consensus catches issues single reviewers miss; CI/CD integration |
| **Healthcare** | Clinical decision support, protocol review, HIPAA compliance | Audit trails required; adversarial vetting reduces diagnostic errors; field-level encryption |
| **Financial Services** | Risk assessment, trading strategy review, regulatory compliance | Regulatory audit trails; multi-model reduces correlated risk; vertical weight profiles |
| **Legal** | Contract review, due diligence, regulatory analysis | Decision receipts document reasoning; dissent trails flag uncertainty |
| **Government / Defense** | Policy analysis, procurement decisions, classified environments | Audit-grade documentation; self-hosted and offline deployment; air-gapped support |
| **Compliance** | SOC 2 audit prep, GDPR assessment, EU AI Act readiness | Compliance artifact generation as a byproduct of decision vetting |

---

## Pricing Tiers

### Free Tier

For individual developers and experimentation.

| Feature | Included |
|---|---|
| Demo mode (no API keys needed) | Unlimited |
| CLI code review | 10 reviews/month |
| Gauntlet stress tests | 5 runs/month |
| Debates | 10/month |
| Agents | Up to 3 per debate |
| Decision receipts | Markdown export |
| Python + TypeScript SDKs | Read-only access |

Bring your own API keys. Aragora does not mark up LLM provider costs on the Free tier.

### Pro (~$49/month per seat)

For small teams that need decision rigor and audit trails.

| Feature | Included |
|---|---|
| CLI code review | Unlimited |
| Gauntlet stress tests | Unlimited |
| Debates | Unlimited |
| Agents | Up to 10 per debate |
| Decision receipts | Markdown, HTML, PDF, SARIF, CSV |
| Cryptographic signing | HMAC-SHA256, RSA-SHA256, Ed25519 |
| CI/CD integration | GitHub Actions, GitLab CI |
| Channel delivery | Slack, Teams, Discord, email |
| 4-tier Continuum Memory | Fast / medium / slow / glacial |
| Knowledge Mound | 41 adapters |
| ELO rankings + Brier calibration | Per-agent, per-domain tracking |
| Workflow engine | 50+ templates across 6 categories |
| Vertical weight profiles | Healthcare, financial, legal |
| API access | Full REST + WebSocket (3,000+ operations) |
| Python + TypeScript SDKs | Full access (184 Python / 183 TypeScript namespaces) |

Bring your own API keys. LLM costs billed directly by your providers.

### Enterprise (Custom Pricing)

For organizations with compliance, security, and governance requirements.

| Feature | Included |
|---|---|
| Everything in Pro | Yes |
| SSO (OIDC / SAML) | Azure AD, Okta, Google Workspace, Auth0, Keycloak |
| MFA | TOTP / HOTP |
| SCIM 2.0 provisioning | Automatic user sync from identity providers |
| RBAC v2 | 390+ permissions, 7 default roles, role hierarchy, middleware enforcement |
| Multi-tenancy | Tenant isolation, resource quotas, usage metering |
| Encryption | AES-256-GCM at rest, field-level encryption for HIPAA |
| Key rotation | Versioned keys with automatic rotation schedules |
| Compliance frameworks | SOC 2 controls, GDPR (deletion/export/consent), HIPAA, EU AI Act |
| EU AI Act artifacts | Article 12/13/14 artifact bundles with SHA-256 integrity |
| Deployment | Self-hosted, offline mode, air-gapped environments |
| Backup / DR | Incremental backups, retention policies, DR drill framework |
| Observability | Prometheus metrics, Grafana dashboards, OpenTelemetry tracing |
| Control plane | Agent registry, task scheduler, health monitoring, policy governance |
| Streaming connectors | Apache Kafka, RabbitMQ for enterprise event ingestion |
| Anomaly detection | Security anomaly detection and SSRF protection |
| SLA | Custom uptime commitments |
| Support | Dedicated account team |

---

## Feature Matrix

| Feature | Free | Pro | Enterprise |
|---|:---:|:---:|:---:|
| **Core Debate** | | | |
| Multi-agent debate | 10/mo | Unlimited | Unlimited |
| Agents per debate | 3 | 10 | Unlimited |
| AI code review | 10/mo | Unlimited | Unlimited |
| Gauntlet stress testing | 5/mo | Unlimited | Unlimited |
| **Decision Receipts** | | | |
| Markdown export | Yes | Yes | Yes |
| HTML / PDF / SARIF / CSV export | -- | Yes | Yes |
| Cryptographic signing (HMAC/RSA/Ed25519) | -- | Yes | Yes |
| Receipt retention policies | -- | -- | Yes |
| **Trust & Calibration** | | | |
| ELO rankings per domain | -- | Yes | Yes |
| Brier score calibration | -- | Yes | Yes |
| Hollow consensus detection (Trickster) | -- | Yes | Yes |
| Vertical weight profiles | -- | Yes | Yes |
| Anti-fragile agent reassignment | -- | Yes | Yes |
| **Memory & Knowledge** | | | |
| 4-tier Continuum Memory | -- | Yes | Yes |
| Knowledge Mound (41 adapters) | -- | Yes | Yes |
| Cross-debate institutional memory | -- | Yes | Yes |
| **Integrations** | | | |
| REST API + WebSocket | Limited | Full | Full |
| Python SDK (184 namespaces) | Yes | Yes | Yes |
| TypeScript SDK (183 namespaces) | Yes | Yes | Yes |
| Slack / Teams / Discord | -- | Yes | Yes |
| Telegram / WhatsApp / email / voice | -- | Yes | Yes |
| CI/CD (GitHub Actions, GitLab) | -- | Yes | Yes |
| Kafka / RabbitMQ | -- | -- | Yes |
| **Workflow** | | | |
| Workflow engine | -- | Yes | Yes |
| 50+ pre-built templates | -- | Yes | Yes |
| Custom workflow patterns | -- | Yes | Yes |
| **Security** | | | |
| SSO (OIDC / SAML) | -- | -- | Yes |
| MFA (TOTP / HOTP) | -- | -- | Yes |
| SCIM 2.0 provisioning | -- | -- | Yes |
| RBAC v2 (390+ permissions) | -- | -- | Yes |
| Multi-tenancy | -- | -- | Yes |
| AES-256-GCM encryption | -- | -- | Yes |
| Field-level encryption (HIPAA) | -- | -- | Yes |
| Key rotation | -- | -- | Yes |
| Anomaly detection | -- | -- | Yes |
| SSRF protection | -- | -- | Yes |
| **Compliance** | | | |
| SOC 2 controls | -- | -- | Yes |
| GDPR (deletion/export/consent) | -- | -- | Yes |
| HIPAA framework | -- | -- | Yes |
| EU AI Act artifact generation | -- | Yes | Yes |
| **Operations** | | | |
| Self-hosted deployment | -- | -- | Yes |
| Offline / air-gapped mode | -- | -- | Yes |
| Backup / disaster recovery | -- | -- | Yes |
| Prometheus + Grafana + OTLP | -- | -- | Yes |
| Control plane + policy governance | -- | -- | Yes |
| Custom SLA | -- | -- | Yes |

---

## Deployment Options

### SaaS (Managed)

Hosted by Aragora. No infrastructure to manage.

- Multi-region availability (US, EU, APAC)
- Automatic updates and scaling
- SOC 2 compliant infrastructure
- Data residency options for EU (GDPR) and regulated industries

### Self-Hosted

Deploy on your own infrastructure. Full control over data and networking.

- **Docker Compose** -- Single-command deployment for evaluation and small teams (`deploy/docker-compose.yml`)
- **Docker Compose Production** -- Production-grade with separate service definitions (`deploy/docker-compose.production.yml`)
- **Kubernetes + Helm** -- Full Helm chart with HPA, PDB, network policies, resource quotas, and per-region value files (US, EU, APAC)
- **Terraform** -- Infrastructure-as-code for AWS with single-region and multi-region EC2 configurations
- Bring your own PostgreSQL, Redis, and object storage
- No phone-home telemetry

### Offline / Air-Gapped

For classified, regulated, or disconnected environments.

- `aragora serve --offline` starts with SQLite backend, no external dependencies
- Sets `ARAGORA_OFFLINE` and `DEMO_MODE` automatically
- Local model support via Ollama, llama.cpp, or any OpenAI-compatible API
- No internet connectivity required after initial deployment
- Decision receipts and audit trails work identically in offline mode

---

## Compliance Readiness

| Framework | Status | What Aragora Provides |
|---|---|---|
| **SOC 2** | Controls implemented | Audit logging, RBAC access controls, AES-256-GCM encryption, backup/DR, change management trails |
| **GDPR** | Framework ready | Data deletion with grace period and verification (Article 17), data export (Article 20), consent management, retention policies, anonymization (Safe Harbor de-identification) |
| **HIPAA** | Framework ready | Field-level AES-256-GCM encryption for PHI, audit trails, RBAC access controls, BAA-compatible architecture |
| **EU AI Act** | Artifacts generated | Article 9 (risk management via adversarial debate), Article 12 (event logs, technical documentation, retention), Article 13 (transparency, known risks, output interpretation), Article 14 (human oversight, override mechanisms), Article 15 (accuracy tracking via calibration scores) |
| **SOX** | Partial | Audit trails and access controls applicable to financial reporting decisions |

**Important caveat:** Aragora provides the technical controls and artifacts. Compliance certification requires organizational processes, legal review, and (for SOC 2) third-party auditor engagement. Aragora does not certify compliance -- it provides the infrastructure that makes certification achievable.

---

## Integration Ecosystem

### Communication Platforms

Slack, Microsoft Teams, Discord, Telegram, WhatsApp, email (IMAP/SMTP), voice (TTS integration with voice stream management)

### Developer Tools

GitHub (PR review, Actions CI), GitLab CI, Jira, VS Code (via MCP server)

### Enterprise Connectors

Salesforce, SAP, ServiceNow, Zendesk, HubSpot, Zapier (200+ app connections via webhook automation)

### Data & Streaming

Apache Kafka, RabbitMQ, PostgreSQL, Redis (with HA/cluster support), S3-compatible object storage

### Healthcare

HL7 FHIR connectors for clinical decision support workflows

### AI Framework Integration

LangChain, CrewAI, AutoGen integration examples included in the repository. OpenClaw gateway for portable agent governance with 22 endpoints and full SDK support.

### SDKs

| SDK | Package | Namespaces | Install |
|---|---|---|---|
| Python | `aragora-sdk` | 184 | `pip install aragora-sdk` |
| TypeScript | `@aragora/sdk` | 183 | `npm install @aragora/sdk` |

Both SDKs provide typed clients for all 3,000+ API operations with full IntelliSense / type-ahead support. 99.3% feature parity between Python and TypeScript.

---

## Platform Scale

| Metric | Value |
|---|---|
| Python modules | 3,200+ |
| Lines of code | 1,490,000 |
| Tests | 208,000+ |
| Test files | 4,300+ |
| API operations | 3,000+ across 2,900+ paths |
| WebSocket event types | 190+ |
| SDK namespaces | 184 Python / 183 TypeScript (99.3% parity) |
| Knowledge Mound adapters | 41 |
| RBAC permissions | 390+ |
| Agent types | 43 |
| LLM providers | 6+ (Anthropic, OpenAI, Google, xAI, Mistral, OpenRouter) |
| Workflow templates | 50+ across 6 categories |
| Debate modules | 210+ |
| Handler modules | 580+ |
| Current version | v2.8.0 |
| GA readiness | 98% |

---

## Competitive Position

| Category | Examples | Relationship to Aragora |
|---|---|---|
| **Agent orchestration** | CrewAI ($25M), LangGraph ($260M), AutoGen | Complementary -- use them upstream, route decisions through Aragora for vetting |
| **AI governance** | Credo AI, Holistic AI, IBM watsonx | Different approach -- they audit AI from outside; Aragora improves decisions through adversarial debate |
| **AI observability** | LangSmith, Weights & Biases | Complementary -- they monitor after deployment; Aragora vets before shipping |
| **Single-provider agents** | OpenAI Agents SDK | Limited -- single-provider lock-in means correlated failures; no genuine adversarial diversity |

**Aragora's structural advantage:** No well-funded competitor builds adversarial decision vetting with heterogeneous models. The category -- Decision Integrity -- is new. The EU AI Act enforcement timeline (August 2026) creates urgency for exactly this capability. Mitsubishi Electric's January 2026 announcement of adversarial multi-agent debate for manufacturing validates the approach at industrial scale.

---

## Why Now

The EU AI Act high-risk enforcement begins **August 2, 2026** -- six months away. Organizations deploying AI in regulated industries have a narrowing window to build decision governance infrastructure.

Retrofitting auditability onto existing single-model architectures is architecturally inferior: it observes decisions but does not improve them. Aragora produces compliance-ready audit trails as a **byproduct** of improving decision quality. The same system that makes decisions more reliable also makes them auditable. That convergence is the product.

---

## Getting Started

```bash
# Install
pip install aragora

# Try AI code review (no API keys needed in demo mode)
git diff main | aragora review --demo

# Stress-test a specification
aragora gauntlet spec.md --profile thorough --output receipt.html

# Run a multi-agent debate
export ANTHROPIC_API_KEY=your-key
aragora ask "Should we adopt microservices?" --agents anthropic-api,openai-api --rounds 3

# Start the API server
aragora serve
```

**Documentation:** [Getting Started](../getting-started/overview) | [Developer Quickstart](../getting-started/quickstart) | [API Reference](../api/reference) | [Enterprise Features](./features)

---

*See [WHY_ARAGORA.md](./why-aragora) for the full positioning document. See [ENTERPRISE_FEATURES.md](./features) for detailed enterprise capabilities.*
