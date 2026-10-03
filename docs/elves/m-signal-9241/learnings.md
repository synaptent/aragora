# Learnings — m-signal-9241

Session-derived facts the run must not rediscover the hard way (2026-07-11):

1. **Never run bare `mypy`/`make ci-required` as a health check.** The PATH pyenv shim is mypy
   1.19.1 (< the 2.1.0 floor) and raw full-tree mypy carries ~2,570 frozen campaign errors
   (#9099). CI's required typecheck is a changed-file gate. Use
   `$ARAGORA_PYTHON -m mypy <changed files>` (resolve via scripts/aragora_runtime.sh resolve_aragora_python).
2. **Reviewer CLI states change hourly.** claude walls on 5h subscription windows; codex quota
   resets on the hour boundary (today 16:50); gemini hallucinates import errors on hunk-only
   context (3 false P1s on #8809 — B3's rationale); grok CLI returns preamble-only, verdict
   unknown (B1's rationale). Probe before relying; classify walls as infra, not red.
3. **GitHub API budget is one shared 5k/hr user quota** across this run, two droid missions,
   conductor loops, and goal cycles. We exhausted GraphQL today mid-settlement. Batch gh calls;
   `gh api rate_limit` before bursts; B5 exists to fix this properly.
4. **Tier-gated posting:** collect_quorum_evidence never posts without supportive quorum;
   Tier 3-4 prepare-only. The operator path is prepared-json → operator posts. Don't fight it.
5. **The harness blocks self-approval**: an agent that authored commits AND collected evidence
   cannot merge/settle its own PR. Design batches so settlement is founder-morning work, not a
   blocker (park + packet).
6. **Cancelled ≠ failed:** the Required-Check-Priority canceller makes non-required jobs read
   as "fail"; `gh run rerun <id> --failed` clears them. Don't debug phantom failures.
7. **Main-red status check:** merges through quorum with green required checks = main healthy;
   pristine-main full-suite timeouts are infra_error by contract (#9175), never red evidence.
8. **VibeProxy is the debate-gate provider.** /Applications/VibeProxy.app, listening on
   127.0.0.1:8317, speaks BOTH OpenAI (/v1/models) and Anthropic (/v1/messages) shapes,
   subscription-backed (verified live 2026-07-11 CT: claude-sonnet-4-6 answered). For the gate:
   ANTHROPIC_BASE_URL=http://127.0.0.1:8317 ANTHROPIC_API_KEY=vibeproxy-local → anthropic-api
   agent works keylessly. Heterogeneous pair: claude-via-VibeProxy + codex CLI (openai family)
   via per-PR collect_quorum_evidence. kimi via VibeProxy is Chinese-routed: advisory only.
