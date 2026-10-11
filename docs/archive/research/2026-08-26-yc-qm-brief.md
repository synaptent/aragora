# YC QM (Quartermaster) — Research & Feasibility Analysis

> **Status:** NON-CANONICAL RESEARCH BRIEF. Authority: none. Source triage: [2026-08-26-x-bookmarks-triage.md](2026-08-26-x-bookmarks-triage.md), candidate 3.
> **Date:** 2026-08-26 (research verified 2026-08-29; stars/forks move fast)

## The Concept

QM ("quartermaster") is Y Combinator's internal multi-agent harness, open-sourced Jul 31 2026 (<https://github.com/yc-software/qm>, MIT, TypeScript; 14.3k stars / 1.7k forks within a month). "Multiplayer agent harness for work. In Slack and on the web." Used across YC accounting, legal, events, engineering. Crucially it is **scaffolding around other harnesses** — Claude Code, Codex, OpenCode, Pi all drive the same core — and a multi-*user* system: one agent per scope, acting *as* the person it works for, with their credentials.

## Architecture (verified)

- **Scope** is the central primitive: a person or room owns isolated memory, files, keychain view, permissions, crons, web apps, and a durable sandbox. Departments are emergent (shared scope + granted skills), not config files.
- Memory: dated atomic-bullet markdown notebook with explicit consolidation commands (`UPDATE/DELETE/ADD/NONE`); no embeddings in the hot path.
- Skills: `SKILL.md` files (YAML frontmatter + markdown), scope-owned, admin-gated promotion to org-wide.
- Governance: three org security postures (Strict = every tool call pauses for human approval; Auto = classifier screening; Dangerous), narrower scopes can only tighten; predeclared command policy; Slack approval cards (Allow once/session/always/Deny); three actions permanently agent-inaccessible (grant changes, impersonation, approval decisions).

## The governance & audit story (the differentiation crux, verified)

QM's governance is **access-control-shaped, not decision-integrity-shaped**:

- Per-scope audit logging exists, but the audit interface has **no hash-chaining, no signing, no tamper evidence** (verified in `src/audit/audit-log.ts`).
- **No decision receipts, no multi-agent cross-checking, adversarial vetting, debate, consensus, or dissent capture anywhere.** Model-checks-model appears only as an injection-screening classifier and a "should I speak" Slack judge.
- No compliance framework mapping; SECURITY.md itself disclaims certification and lists unfinished controls (org kill switch, uniform rollback, secret scanning; browser actions bypass command policy and the egress proxy).
- QM hard-codes that approval judgment must not collapse "into a single model decision" — but offers only a human click as the alternative. Structured multi-model adjudication with a receipt is the missing third option, i.e., Aragora's exact slot.

## Aragora Integration Assessment

**Where QM is stronger:** Slack-native everyday UX (thread-following turn detection that posts *nothing* when not addressed; streamed edits; approval cards), one-primitive org model, breadth of mundane org work, harness-agnostic distribution, brand momentum.

**Positioning:** complementary more than competitive — "run QM for the daily grind; route anything consequential through Aragora for a receipt." QM's pluggable-harness + skill-pack design would admit an "escalate to adversarial review" integration.

**Patterns worth stealing:** posture monotonicity ("narrower scopes can only tighten"); the agent-inaccessible action list as a named policy object; Slack turn-detection + approval-card UX for `aragora/bots/`; audience-filtered transcripts (substitute, don't delete) for receipt redaction; byte-identical-core deploy layering for enterprise self-hosting; npm `min-release-age=7`.

## Conclusion

Add QM to COMPARISON_MATRIX.md with the verified receipt-story gap; fold the reusable patterns into existing surfaces (bots, policy) as candidate items rather than new tracks.

## Sources

- <https://github.com/yc-software/qm> (+ README, SECURITY.md, `src/slack/README.md`, `src/audit/audit-log.ts`, `skills-seed/`) — all architecture/governance claims.
- <https://qm.ycombinator.com> — name, history, self-hosting rationale.
- <https://news.ycombinator.com/item?id=49126604> — reception (682 pts): impersonation-model criticism.
- <https://wavect.io/blog/qm-ai-agent-harness-review/> — "not production-ready by default" verdict.
- <https://x.com/ycombinator/status/2083243960684908768> — announcement (the bookmark).
