# Ship & Verify: Landing Page, Debate Quality, Nomic Proof, GH Actions Gate

**Date:** 2026-03-02
**Status:** Approved
**Approach:** Prioritized Parallel (Wave 1 + Wave 2)

## Overview

Four workstreams executed in two waves to ship and verify Aragora's core value loop:

- **Wave 1** (parallel): Landing page verification + Debate quality fix
- **Wave 2** (parallel): Nomic Loop proof run + GitHub Actions pre-merge gate

## Workstream 1: Landing Page Verification

**Goal:** Verify aragora.ai landing page works end-to-end — theme switching, debate submission, result display.

**Scope:**
- Confirm `(standalone)/landing/page.tsx` is the deployed route
- Verify debate form submits to backend and returns results
- Test all 3 themes render correctly (warm, dark, professional)
- Fix broken imports, missing env vars, or API connection issues
- Deploy fix if needed via Vercel

**Key files:**
- `aragora/live/src/app/(standalone)/landing/page.tsx`
- `aragora/live/src/components/landing/LandingPage.tsx`
- `aragora/live/src/components/landing/HeroSection.tsx`
- `aragora/live/src/components/landing/ThemeContext.tsx`
- `aragora/live/src/app/globals.css`

**Success criteria:** User can visit aragora.ai, switch themes, submit a debate topic, and see structured results.

## Workstream 2: Debate Quality → 80%+

**Goal:** Tune practicality scoring and synthesis to achieve 80%+ good-run rate on dogfood benchmarks.

**Three changes:**
1. Fix `first_batch_concreteness` — score best-of-3 lines instead of first line only
2. Enable contract-guided synthesis by default (code exists, not default)
3. Expand placeholder detection patterns (add "TBD", "TK", "as needed", "future enhancement")

**Key files:**
- `aragora/debate/output_quality.py`
- `aragora/debate/repo_grounding.py`
- `aragora/debate/phases/synthesis_generator.py`
- `tests/debate/test_output_quality.py`

**Benchmark:** Run 5 dogfood debates, measure pass rate. Target: 4/5 (80%).

**Success criteria:** 4 out of 5 dogfood benchmark runs pass the quality gate.

## Workstream 3: Nomic Loop Proof Run

**Goal:** Run self-improvement system on a real Aragora improvement, prove it works end-to-end.

**Approach:** Use `scripts/nomic_staged.py all` or `scripts/self_develop.py` with a scoped goal like "Improve debate quality gate placeholder detection."

**Key files:**
- `scripts/nomic_staged.py`
- `scripts/self_develop.py`
- `aragora/nomic/hardened_orchestrator.py`
- `docs/HONEST_ASSESSMENT.md` (update after proof)

**Success criteria:** System debates an improvement, designs it, implements code, verifies tests pass, and commits to a branch autonomously.

## Workstream 4: GitHub Actions Pre-Merge Gate

**Goal:** Create a reusable GitHub Action that runs `aragora review` on PR diffs.

**Deliverables:**
- `.github/actions/aragora-review/action.yml` — composite action
- Installs aragora from PyPI, runs `aragora review --diff` on PR
- Posts structured comment on PR with findings
- Configurable: model selection, agent count, quality threshold
- Example workflow for users to copy

**Key files:**
- `.github/actions/aragora-review/action.yml`
- `.github/workflows/aragora-review-example.yml`

**Success criteria:** Action runs on a test PR and posts a meaningful review comment.

## Execution Order

```
Wave 1 (parallel, independent codepaths):
  ├── Workstream 1: Landing page verification
  └── Workstream 2: Debate quality fix + benchmark

Wave 2 (parallel, after Wave 1):
  ├── Workstream 3: Nomic Loop proof (benefits from improved debate quality)
  └── Workstream 4: GitHub Actions gate (independent)
```
