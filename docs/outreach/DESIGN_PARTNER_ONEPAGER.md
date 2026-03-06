# Aragora: Design Partner Program

**Stop shipping decisions you can't explain.**

---

## The Problem

Your team uses AI every day — generating code, drafting plans, evaluating options.
But when something goes wrong, nobody can answer: *why did we decide that?*

- **No audit trail.** AI outputs are ephemeral. Decisions evaporate.
- **Single-model blind spots.** One LLM = one perspective. No adversarial vetting.
- **Compliance gaps.** Regulators want explainability. You have chat logs.

## What Aragora Does

Aragora is a **Decision Integrity Platform**. It orchestrates multiple AI agents
to adversarially vet decisions, then delivers audit-ready **decision receipts**
to any channel.

```
Your question → 43 agents debate → Consensus + receipt → Slack / GitHub / API
```

**Three things that make it different:**

1. **Multi-agent consensus.** Claude, GPT-4, Mistral, Gemini debate each decision.
   Disagreements surface blind spots before they become incidents.

2. **Cryptographic receipts.** Every decision produces a SHA-256 signed receipt
   with agent votes, agreement scores, and provenance chains.

3. **Zero-config autonomous actions.** Point it at your GitHub repo and it
   reviews PRs, identifies next steps, and posts findings — no setup required.

## What You Get Today

| Capability | Status |
|------------|--------|
| Multi-agent debate engine (43 agent types) | Production |
| PR code review (`aragora openclaw review --pr <url>`) | Production |
| Next-steps scanner (`aragora openclaw next-steps`) | Production |
| Decision receipts with SHA-256 audit trail | Production |
| SARIF export for GitHub Security tab | Production |
| WebSocket real-time streaming (190+ events) | Production |
| Python + TypeScript SDKs | Production |
| Docker one-command deployment | Production |
| EU AI Act compliance artifacts (Art. 12/13/14) | Production |
| RBAC with 360+ permissions | Production |
| OpenTelemetry observability | Production |

## Quick Demo (60 seconds)

```bash
# Install
pip install aragora

# Review a PR
aragora openclaw review --pr https://github.com/your-org/repo/pull/123 --dry-run

# Scan for next steps
aragora openclaw next-steps --path /your/repo

# Start the full platform
docker compose -f deploy/demo/docker-compose.yml up
# Open http://localhost:3000
```

## Who This Is For

We're looking for **3-5 design partners** who:

- Ship software with AI assistance (Copilot, Claude, Cursor, etc.)
- Need to explain AI-assisted decisions to stakeholders or regulators
- Want autonomous code review beyond what a single LLM provides
- Are willing to give candid feedback in exchange for early access

**Ideal verticals:** FinTech, HealthTech, Legal Tech, GovTech, or any
regulated industry where decision provenance matters.

## What We're Asking

| From You | From Us |
|----------|---------|
| 30 min onboarding call | Free access during partner period |
| Run on 1-2 real repos | Priority feature requests |
| 15 min feedback call every 2 weeks | Direct Slack access to the team |
| Permission to use anonymized case study | Co-marketing opportunity |

## How It Works (Architecture)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Your Repo  │────▶│  Aragora CLI │────▶│  Debate Engine   │
│  or PR URL  │     │  / SDK / API │     │  (43 agent types)│
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                          ┌────────────────────────┼────────────────────┐
                          │                        │                    │
                    ┌─────▼─────┐          ┌──────▼──────┐    ┌───────▼───────┐
                    │ Consensus │          │   Receipt    │    │  Connectors   │
                    │  Engine   │          │  Generator   │    │ Slack/GitHub/ │
                    │           │          │ (SHA-256)    │    │ Teams/Email   │
                    └───────────┘          └─────────────┘    └───────────────┘
```

## Numbers

- **129,000+ tests** across 3,000+ test files
- **3,000+ API operations** across 2,900+ handler routes
- **33 knowledge adapters** for cross-system learning
- **190+ WebSocket event types** for real-time streaming
- **Python + TypeScript SDKs** with 100% route coverage

## Next Step

**Interested?** Reply to this email or book a 15-minute call:

- Email: [your-email]
- Calendar: [booking-link]
- GitHub: https://github.com/an0mium/aragora

---

*Aragora is open source under the Apache 2.0 license.*
*Design partners get priority support, roadmap influence, and early access to enterprise features.*
