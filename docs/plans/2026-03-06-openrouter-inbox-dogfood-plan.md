# OpenRouter Inbox Dogfood Plan

Last updated: 2026-03-06
Status: Foundation merged on `main`; ready for first live Gmail dogfood run
Source debate: `ecf28f2d-3c60-4964-9ec8-c4822f5abfc5`

## Objective

Make one path real enough to trust and use daily:

`real Gmail inbox -> adversarial triage debate -> persisted signed receipt -> human or narrow auto-approval -> gmail.modify action`

This is the first wedge because it maps directly to the founder's painful real problem, and because it forces Aragora to prove its strongest claim under real pressure: debate-backed, receipt-gated actioning.

## Delivered Foundation In Main

The core implementation foundation for this wedge has already landed:

- `#742` consolidated trust-wedge receipt gating and inbox integrations
- `#732` removed demo fallbacks from inbox mutation paths
- `#736` and `#740` added OpenRouter session circuit-breaker routing
- `#741` added the Gmail OAuth setup helper for dogfood

This document is therefore no longer a pre-merge implementation plan. It is the post-merge dogfood checklist for proving the wedge on real email.

## Evidence From The Live Run

- The direct provider agent classes were used with no native provider keys present.
- `anthropic-api` resolved to OpenRouter fallback model `anthropic/claude-opus-4.6`.
- `openai-api` resolved to OpenRouter fallback model `openai/gpt-5.4`.
- `gemini` resolved to OpenRouter fallback model `google/gemini-3.1-pro-preview`.
- The live debate completed with consensus, `0.8` confidence, and `gemini_synthesizer` as the winning synthesizer/judge.
- The live debate converged on the same narrow wedge the audit suggested: inbox triage plus gated `gmail.modify` actioning, with reply/send explicitly deferred.
- The local idea-to-execution pipeline completed on the same conversation summary and produced `6` idea nodes, `2` goals, `8` action nodes, and `9` orchestration nodes.

## Product Wedge

Build a CLI-first inbox triage loop for the founder's own business.

Allowed v1 actions:

- `ARCHIVE`
- `STAR`
- `LABEL`
- `IGNORE`

Optional v1.5 action:

- `CREATE_TASK_EXTERNAL`, but only behind the same receipt validation and explicit human approval path

Explicitly deferred:

- reply or forward generation
- broad OpenClaw autonomy
- on-chain anchoring
- dashboard-first UX
- push/webhook ingestion
- automated-company scope

## Immediate Dogfood Checklist

### 1. First live setup

- Run `python scripts/gmail_oauth_setup.py` to configure founder Gmail access.
- Confirm durable signing is configured for the dogfood lane rather than relying on ephemeral development fallback.
- Confirm `OPENROUTER_API_KEY` is present and direct-provider classes can fall back cleanly through OpenRouter.

### 2. First live run

- Run `aragora triage run --batch 1` on a real unread Gmail message.
- Verify the path is fully real:
  - debate runs with the intended model mix
  - a receipt is persisted before execution
  - approval/review happens through the wedge path
  - the final action uses `gmail.modify`

### 3. Daily founder loop

- Process small unread batches sequentially.
- Keep the allowed action surface narrow:
  - `ARCHIVE`
  - `STAR`
  - `LABEL`
  - `IGNORE`
- Keep reply, forward, and send actions out of scope.

### 4. Measurement loop

- Use receipt/report output to capture:
  - provider route
  - cost per email
  - latency per email
  - approval vs override outcome
- Export a small labeled inbox evaluation slice to measure important-email recall.

### 5. Expansion gate

Only broaden beyond this wedge if the live founder loop is working well enough that its removal would be painful.

## Metrics And Kill Criteria

### Hard gates

- `100%` of executed actions must validate a pre-existing persisted receipt.
- `0` silent demo fallbacks in the wedge path.
- `0` autonomous sends, replies, or forwards.

### Operating thresholds

- Average cost per processed email must stay at or below `$0.20`.
- End-to-end latency per email must stay at or below `30s`.
- Founder override rate during the first week of manual review should stay at or below `30%`.
- Important-email recall on the first labeled evaluation slice should be at or above `90%`.

### Kill criteria

- If any action executes without a previously persisted valid receipt, stop the rollout.
- If cost stays above threshold after prompt and routing cleanup, stop the rollout and simplify the debate shape.
- If latency stays above threshold, stop the rollout and reduce agent count, prompt size, or model mix.
- If override rate stays above `30%`, disable auto-approval and treat the prompts as not yet fit for use.
- If the system misses critical business email in the labeled set or in live use, keep the lane human-reviewed until recall improves.

## Dogfood Findings About Aragora Itself

The live debate layer was materially more useful than the downstream prose-to-plan layers.

- The debate output was coherent, narrow, and high-signal.
- `DecisionPlanFactory` extracted a plan artifact, but its risk register stayed empty and its implementation tasks were mostly markdown fragments, which means the debate-to-plan handoff is still too lossy for prose-heavy outputs.
- `IdeaToExecutionPipeline` completed successfully, but it compressed the conversation into only two generic goals. That is useful as a structural canvas, not yet as the primary planner for this kind of strategic input.

Implication:

For this wedge, treat the live debate output as the primary planning artifact. Treat `DecisionPlanFactory` and `IdeaToExecutionPipeline` as supporting instrumentation until their structured extraction contracts are tightened.

## Recommended Follow-On After The Wedge Works

Only after the inbox lane is reliable should Aragora expand to:

- more SaaS connectors
- richer action types
- broader OpenClaw delegation
- dashboard polish
- self-improvement loops driven by outcome feedback from real use
