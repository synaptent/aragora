# Aragora Product Roadmap

**Last Updated:** March 2026

---

## Current Status (March 2026)

Aragora is **98% GA-ready**. The platform has shipped all core infrastructure and is pending only external vendor-dependent milestones before public launch.

**By the numbers:**
- 208,000+ tests across 4,000+ test files (0 failures on main)
- 41 Knowledge Mound adapters registered (up from 34 in Q4 2025)
- 3,000+ API operations across 2,900+ paths
- 14 RBAC resource types, 8 actions, 360+ permissions
- SOC 2 controls framework: 98% implemented

**Completed since January 2026:**
- Nomic Loop end-to-end self-improvement (66 E2E tests passing)
- Knowledge Mound Phase A2 (contradiction detection, confidence decay, RBAC governance, analytics)
- Unified Memory Gateway (MemoryGateway + RetentionGate + CrossSystemDedupEngine + RLMMemoryNavigator + ClaudeMemAdapter)
- Pipeline orchestration — 4-stage Idea-to-Execution (Ideas → Goals → Workflows → Orchestration)
- Compliance CLI (`aragora compliance export`) for EU AI Act artifact bundles
- Settlement hooks with cryptographic Gauntlet receipts
- Voice/TTS integration wired end-to-end (STT + TTS)
- Multi-tenancy isolation, resource quotas, and usage metering
- RBAC v2 fully integrated across all KM adapters

**Remaining blockers before GA:**
- External penetration test (vendor-dependent; kickoff target Mar 3, 2026)
- Agent-first beta: OpenClaw instances running reviews via REST API on real PRs
- Public demo at aragora.ai/demo

**EU AI Act enforcement date: August 2, 2026** — the compliance CLI and audit trail infrastructure
position Aragora as a natural adoption path for enterprises facing this deadline.

---

## Vision

Aragora is the control plane for multi-agent vetted decisionmaking across organizational knowledge and channels. We orchestrate heterogeneous AI agents to debate, synthesize, and deliver defensible decisions through structured vetted decisionmaking—building institutional memory with full audit trails.

---

## Current Capabilities (v2.5)

### Core Platform
- Multi-agent debate orchestration with configurable protocols
- 15+ AI provider integrations (Anthropic, OpenAI, Google, xAI, DeepSeek, etc.)
- Real-time WebSocket streaming of debate progress
- Consensus detection with formal verification proofs
- ELO-based agent skill tracking and team selection

### Knowledge & Memory
- Knowledge Mound for organizational knowledge accumulation
- Continuum Memory with 4-tier retention (fast/medium/slow/glacial)
- Evidence collection from 11+ sources (ArXiv, GitHub, Wikipedia, etc.)
- Cross-debate learning and pattern recognition

### Enterprise Features
- Multi-tenant workspaces with RBAC
- OIDC/SAML authentication
- Audit logging and compliance reporting
- Control Plane for multi-instance orchestration
- Workflow engine for complex debate pipelines

### Integrations
- Slack, Discord, Microsoft Teams bots
- Email-to-debate routing
- REST API with 3,000+ operations across 2,900+ paths
- WebSocket real-time API
- MCP server for Claude Desktop

---

## Q1-Q2 2026: SME & Developer Focus

> **Backlog:** See `docs/FEATURE_GAP_LIST.md` for current backlog.

### Track 1: SME Starter Pack
- [x] Slack integration (OAuth, slash commands, thread debates)
- [x] Microsoft Teams integration (Bot Framework, Adaptive Cards)
- [x] Decision Receipts v1 (cryptographic signatures, PDF/JSON/HTML export)
- [x] Budget controls and cost tracking per debate
- [x] Usage dashboard with spend analytics

### Track 2: Developer Platform
- [x] OpenAPI 3.1 specification (3,000+ operations)
- [x] TypeScript SDK feature parity with Python
- [x] SDK code generation pipeline
- [ ] Interactive API explorer at docs.aragora.ai/api
- [ ] Example apps (Slack code review, document analysis)

### Track 3: Self-Hosted Deployment
- [x] Docker Compose production stack
- [ ] Guided setup CLI (`aragora setup`)
- [x] Minimal dependency mode (SQLite + in-memory)
- [x] Backup & restore CLI
- [x] Helm chart for Kubernetes

### Enterprise Readiness (Ongoing)
- [ ] Complete third-party penetration testing (kickoff Mar 3, 2026 — vendor-dependent)
- [ ] Deploy public status page at status.aragora.ai
- [x] Implement quarterly disaster recovery drills (BackupScheduler with DR integration)
- [x] Finalize data classification policy (runtime enforcement, CI PII gate, evidence bundles)
- [x] MFA enforcement for admin access (TOTP/HOTP)
- [x] Enhanced circuit breaker coverage for all connectors
- [x] Redis Sentinel/Cluster support (RedisHAClient)
- [ ] 99.9% uptime target with public SLA

---

## Q3 2026: Scale & Performance

### Performance Optimization
- [ ] Debate execution time reduction (target: 50%)
- [ ] Streaming response improvements
- [ ] Efficient batch debate processing
- [ ] Memory optimization for large knowledge bases

### Horizontal Scaling
- [ ] Kubernetes Operator for automated scaling
- [ ] Global edge deployment
- [ ] Debate sharding for high-throughput workloads
- [x] Redis Cluster mode support

### Cost Optimization
- [ ] Smart provider routing based on cost/quality
- [ ] Token usage analytics dashboard
- [x] Budget controls and alerts
- [ ] Cached response optimization

---

## Q4 2026: Platform Ecosystem

### Marketplace
- [ ] Agent marketplace for sharing custom agents
- [x] Workflow template library (50+ pre-built templates across 6 categories)
- [ ] Integration connectors from community
- [ ] Revenue sharing for creators

### Extended Integrations
- [x] Zapier / Make.com connectors
- [x] GitHub Actions for CI/CD debates (`aragora-review-gate.yml` shipped)
- [ ] Jupyter notebook integration
- [ ] VS Code extension

### Analytics & Insights
- [ ] Debate outcome analytics dashboard
- [ ] Agent performance benchmarking
- [ ] Knowledge gap identification
- [ ] ROI measurement tools

---

## 2027 Vision

### Autonomous Agents
- [x] Self-improving debate protocols (Nomic Loop, operational as of Q1 2026)
- [x] Autonomous knowledge acquisition (Knowledge Mound Phase A2)
- [ ] Proactive insight generation
- [x] Human-in-the-loop governance (approval gates in self-improvement pipeline)

### Industry Solutions
- [ ] Legal document review suite (vertical package planned Q3 2026)
- [ ] Medical diagnosis support (Healthcare FHIR vertical planned Q3 2026)
- [ ] Financial analysis platform (Financial SOX vertical planned Q3 2026)
- [ ] Research acceleration tools

### Platform Capabilities
- [ ] 1M+ concurrent debates
- [ ] Sub-second debate initiation
- [ ] 99.99% availability
- [ ] Global compliance (HIPAA, FedRAMP)

### 2027 R&D
- Prover-Estimator debate protocol
- Canvas GUI 8-stage visual pipeline
- Market resolution mechanism for long-horizon settlement
- ERC-8004 on-chain agent identity deployment to mainnet (contracts written, pending deployment)
- Decision-Integrity UI Workbench
- OpenClaw E2E demo and production integration
- Cloud marketplace listings (AWS Marketplace, Azure Marketplace)

---

## Q2-Q4 2026 Forward Plan

This section captures the prioritized forward roadmap as of March 2026, organized by quarter and theme.

**EU AI Act enforcement: August 2, 2026.** This is a hard external forcing function. The compliance CLI
(`aragora compliance export`) is already shipping artifact bundles for GPAI transparency requirements.
Enterprise teams evaluating AI governance solutions will be making decisions in Q2 2026 — the window
for capturing this cohort is now.

### Q2 2026 Priorities
- [ ] Agent-first beta: OpenClaw instances running `aragora review` on real PRs via REST API
- [x] GitHub Actions pre-merge gate (`aragora-review-gate.yml` shipped)
- [ ] Public demo at aragora.ai/demo
- [ ] EU AI Act compliance package — full audit bundle documentation and customer playbook
- [ ] SOC 2 Type II audit engagement kickoff (controls are ready; external auditor engagement pending)

### Q3 2026 Priorities
- [ ] Cloud marketplace listings: AWS Marketplace and Azure Marketplace
- [ ] Vertical packages: Healthcare (FHIR/HIPAA), Financial Services (SOX/audit), Legal
- [ ] Skills marketplace pilot (community agent templates)
- [ ] Kubernetes Operator for automated horizontal scaling

### Q4 2026 Priorities
- [ ] 10+ agent coordination at enterprise scale
- [ ] Cross-organization federation foundation
- [ ] Decision-Integrity UI Workbench (visual debate canvas)
- [ ] OpenClaw E2E demo production-ready

### 2027 Horizon
- Prover-Estimator debate protocol
- Canvas GUI 8-stage visual pipeline
- Market resolution mechanism (long-horizon settlement)
- ERC-8004 on-chain deployment to mainnet

---

## Feature Requests

We actively track feature requests from customers. Top requested features:

| Feature | Votes | Status |
|---------|-------|--------|
| Dark mode for live dashboard | 89 | **Shipped v2.1** |
| Mobile app | 67 | Under consideration |
| Offline debate mode | 45 | Researching |
| Voice input for debates | 38 | **Shipped Q1 2026** |
| Debate replay/rewind | 34 | Planned Q2 |

Submit feature requests: https://github.com/aragora/aragora/discussions

---

## Release Cadence

| Release Type | Frequency | Notes |
|--------------|-----------|-------|
| Patch (x.x.X) | Weekly | Bug fixes, security patches |
| Minor (x.X.0) | Monthly | New features, improvements |
| Major (X.0.0) | Quarterly | Breaking changes (with migration guides) |

---

## Contributing

Aragora is open to contributions. See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.

Priority contribution areas:
- Evidence connectors for new sources
- Language translations
- Documentation improvements
- Test coverage expansion

---

## Contact

- **Product Feedback**: product@aragora.ai
- **Enterprise Sales**: sales@aragora.ai
- **Security Issues**: security@aragora.ai
- **General Support**: support@aragora.ai

---

*This roadmap represents our current plans and is subject to change based on customer feedback and market conditions.*
