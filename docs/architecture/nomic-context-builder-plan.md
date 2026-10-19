# Nomic Context Builder Plan

Verified commit-addressed packs project upward through the canonical
[Agent Operating Loop](agent-operating-loop.md); the projection never makes a
stale or unverified pack authoritative.

**Status:** Proposed  
**Owner:** Nomic/Knowledge  
**Date:** 2026-01-29

---

## Objective

Provide **deep, queryable codebase context** for Nomic debates using TRUE RLM (REPL),
scaling to **10M‑token equivalent** repos without prompt stuffing.

---

## Current Building Blocks

- `aragora/nomic/context_builder.py` (NomicContextBuilder)
- `aragora/knowledge/mound/repository_orchestrator.py`
- `aragora/knowledge/mound/api/rlm.py`
- `aragora/rlm/bridge.py`

---

## Plan (Best Order)

### 1) Index First
- Build a lightweight index of files + metadata.
- Store under `.nomic/context/` for persistence.

**Acceptance**
- Index available for browsing by path/module.
- Excludes large binaries and ignored dirs.

### 2) Enable TRUE RLM REPL Queries
- Use REPL queries for targeted retrieval:
  - `peek(path, line_range)`
  - `grep(pattern)`
  - `partition_map(dir)`
- Avoid monolithic prompt injection.

**Acceptance**
- Agents can retrieve specific modules by query without loading the entire repo.

### 3) 10M‑Token Equivalent Support
- Configure `ARAGORA_NOMIC_MAX_CONTEXT_BYTES` (default 100MB).
- Chunk ingestion; keep per‑file limits.
- Favor REPL queries over embedding raw content.

**Acceptance**
- Large repos don’t blow up memory or prompt limits.

### 4) Integrate with Context Phase
- Inject `NomicContextBuilder` output into `aragora/nomic/phases/context.py`.
- Expose env toggle: `ARAGORA_NOMIC_CONTEXT_RLM=true|false`.

**Acceptance**
- Debate context includes indexed map + REPL query entrypoints.

---

## Config Defaults

- `ARAGORA_NOMIC_MAX_CONTEXT_BYTES=100_000_000`
- `NOMIC_INCLUDE_TESTS=1`
- `ARAGORA_NOMIC_CONTEXT_RLM=true`

---

## Risks

- REPL query latency if file IO isn’t cached.
- Index updates need invalidation when code changes.

---

## Deliverables

- Index builder + storage
- REPL query wrapper
- Context phase integration
