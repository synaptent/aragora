# Next Roadmap Items: Design Document

**Date:** 2026-03-05
**Status:** Approved for implementation
**Tracks:** 4 (executed in priority order)

---

## Context

Four highest-value engineering items from the P0/P1/P2 priority stack and G1-G4 security
roadmap. Semantic convergence (P2 #16) is already complete — sentence-transformers with 3-tier
fallback is in production. Removed from scope.

**Execution order:** Track 1 (GTM gate) -> Track 2 (public demo) -> Track 3 (EU AI Act) -> Track 4 (taint tracking)

---

## Track 1: GitHub Actions Pre-Merge Gate (aragora review)

**Priority:** P1 #9 — GTM-critical, enables the core "aragora review" selling motion

### What Exists
- `aragora/cli/review.py` (850+ lines) — fully functional CLI: PR URL parsing, `--post-comment`,
  `--output-format github`, `--demo` mode (no API key required), `--gauntlet`
- `.github/workflows/aragora-review-demo.yml` — manual `workflow_dispatch` trigger only
- `aragora/cli/parser.py` — `review` subcommand fully wired

### What's Missing
- `.github/actions/aragora-code-review/action.yml` — composite action (referenced but absent)
- An `on: pull_request` triggered workflow that auto-runs on every PR

### Design

**Composite action** (`.github/actions/aragora-code-review/action.yml`):
- Inputs: `anthropic-api-key` (optional), `rounds` (default 2), `focus`, `output-format`
  (default `github`), `post-comment` (default `true`)
- Steps: set up Python 3.11, `pip install aragora`, run
  `aragora review $PR_URL --post-comment --output-format github`
- Falls back to `--demo` mode if `anthropic-api-key` is absent (gate always runs)
- Uses `GITHUB_TOKEN` for PR comment posting

**Workflow** (`.github/workflows/aragora-review.yml`):
- Trigger: `on: pull_request` (all branches), skip draft PRs
- `permissions: pull-requests: write, contents: read`
- Constructs `PR_URL` from `${{ github.event.pull_request.html_url }}`
- Calls the composite action with `anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}`
- Non-required check, cancellable in-progress, skipped on draft

### Success Criteria
- Every non-draft PR gets an aragora review comment within 5 minutes of opening
- Works in demo mode (no secrets) so forks/external contributors are not blocked
- Comment includes findings summary, confidence score, and link to full receipt

---

## Track 2: Public Demo Page at aragora.ai/demo

**Priority:** P1 #10 — needed to convert landing page visitors, no-auth showcase

### What Exists
- `/api/v1/demo/adversarial` — POST endpoint, no auth required
- `aragora/live/src/app/(app)/demo/instant/page.tsx` — instant demo UI inside auth layout
- `aragora/server/handlers/demo/adversarial_demo.py` — works in online + offline mode
- `aragora/live/src/fixtures/demo-data.ts` — fixture data for offline rendering

### What's Missing
- Public route outside `(app)/` layout
- Landing page CTA linking to the demo

### Design

**New page:** `aragora/live/src/app/(standalone)/demo/page.tsx`
- Outside auth layout (no session check, no login redirect)
- Single topic input -> calls `/api/v1/demo/adversarial` -> polls result
- Shows: agents, positions, consensus verdict, confidence bar, receipt hash, sign-up CTA
- Consistent with existing standalone pages (e.g., debate viewer at `(standalone)/debate/`)

**Landing page update** (`aragora/live/src/app/page.tsx`):
- Add "Try a live debate" button linking to `/demo`
- Positioned as secondary CTA below primary hero

### Success Criteria
- `https://aragora.ai/demo` loads without authentication
- User can submit a topic and see a real debate result
- Clear path to sign-up from the demo result page

---

## Track 3: EU AI Act Article 9 + 15 Artifacts

**Priority:** P1 #5 — August 2, 2026 enforcement deadline; compliance package is a GTM wedge

### What Exists
- `aragora/compliance/eu_ai_act.py` (1,442 lines) — Articles 12, 13, 14 fully implemented
- `ComplianceArtifactBundle` has `.article_12`, `.article_13`, `.article_14`
- Articles 9 and 15 only appear as `ArticleMapping` rows in the conformity report
- `aragora/compliance/artifact_generator.py` — `EUAIActBundleGenerator` maps 12, 13, 14 only

### What's Missing
- `Article9Artifact` dataclass + `_generate_art9()` method
- `Article15Artifact` dataclass + `_generate_art15()` method
- `.article_9` and `.article_15` fields on `ComplianceArtifactBundle`
- Annex IV sections 3, 4, 6, 7, 8 (currently only 1, 2, 5)

### Design

**`Article9Artifact`** (mirrors Article12Artifact pattern):
- `risk_identification_methodology: str`
- `identified_risks: list[dict]` — [{risk_id, description, likelihood, severity, category}]
- `foreseeable_misuse_scenarios: list[str]`
- `risk_mitigation_measures: list[dict]` — [{risk_id, measure, residual_risk_level}]
- `residual_risks: list[dict]`
- `overall_residual_risk_level: str` — "acceptable" | "conditional" | "unacceptable"
- `post_market_monitoring_plan: str`
- `integrity_hash: str`

Derived from: receipt `risk_summary`, `confidence`, `consensus_reached`, `dissenting_agents`,
`topic`, `participants`, `votes`.

**`Article15Artifact`** (mirrors Article14Artifact pattern):
- `accuracy_metrics: dict` — {consensus_confidence, agreement_ratio, calibration_score}
- `robustness_score: float`
- `adversarial_testing: dict` — {dissent_detected, hollow_consensus_detected}
- `cryptographic_controls: dict` — {signing_algorithm, hash_algorithm, integrity_hash_present}
- `error_indicators: list[str]` — dissent reasons, unresolved tensions
- `continuous_monitoring: str`
- `integrity_hash: str`

Derived from: `robustness_score`, `receipt_hash`, `signature`, `consensus_proof`,
`dissenting_agents`, vote confidence distribution.

**Bundle + generator updates:** Add `.article_9`, `.article_15` to `ComplianceArtifactBundle`.
Update `EUAIActBundleGenerator` article mapping. Update `to_dict()` / `to_json()`.

**Annex IV extension:** Sections 3 (input/output specs), 4 (performance characteristics),
6 (post-market monitoring), 7 (relevant changes), 8 (user instructions) added to
`Article12Artifact.technical_documentation`.

### Success Criteria
- `aragora compliance eu-ai-act generate receipt.json` produces bundle with all 5 articles
- Each artifact serializes to JSON with integrity hash
- Tests cover Article 9 and 15 generation from a minimal receipt fixture

---

## Track 4: G2 Trust-Tier Taint Tracking

**Priority:** Security roadmap G2 — highest-leverage gap from AI attack vector analysis

### What Exists
- `aragora/debate/distributed_events.py` — `AgentProposal` with `metadata: dict`
- `aragora/gauntlet/receipt_models.py` — `ConsensusProof` with `dissenting_agents`, no taint
- `aragora/debate/consensus.py` — `Evidence` dataclass with `source`, `evidence_type`
- Settlement hooks framework as the injection point

### What's Missing
- `trust_tier`, `taint_source`, `taint_evidence` on `AgentProposal`
- `tainted_proposals`, `trust_score` on `ConsensusProof`
- `taint_analysis` on `DecisionReceipt`
- Propagation logic in `proposal_phase.py`

### Design

**No breaking changes.** All new fields have defaults. Existing code paths unaffected.

**`AgentProposal` additions** (`distributed_events.py`):
- `trust_tier: str = "standard"` — "untrusted" | "standard" | "vetted" | "system"
- `taint_source: str | None = None` — e.g., "retrieved_context", "config_file"
- `taint_evidence: list[str] = field(default_factory=list)` — evidence IDs

**`ConsensusProof` additions** (`receipt_models.py`):
- `tainted_proposals: list[str] = field(default_factory=list)`
- `trust_score: float = 1.0` — 1.0 = fully clean; lower = tainted proposals influenced consensus

**`DecisionReceipt` addition** (`receipt_models.py`):
- `taint_analysis: dict[str, Any] | None = None`
  - Keys: taint_level ("none"|"low"|"medium"|"high"), tainted_proposal_count, trust_score,
    sources, recommendation

**Propagation in `proposal_phase.py`:**
- Proposals with `metadata.source_type in ("retrieved", "config_file")` get
  `trust_tier = "untrusted"` and `taint_source` recorded
- `ConsensusProof` assembly collects tainted proposal IDs, computes
  `trust_score = clean_proposals / total_proposals`
- `taint_level`: trust_score >= 0.9 -> "none", >= 0.7 -> "low", >= 0.5 -> "medium", < 0.5 -> "high"
- Recommendation: "none"/"low" -> proceed, "medium"/"high" -> human approval required

### Success Criteria
- Proposals from retrieved/config context carry `trust_tier = "untrusted"` in receipt
- `taint_analysis.taint_level` appears in the JSON receipt
- High-taint receipts include `"recommendation": "human approval required"`
- Zero breaking changes — all fields optional with defaults
- Tests: tainted metadata proposal -> taint propagates to receipt

---

## Summary

| Track | Files | GTM Value | Security Value |
|-------|-------|-----------|----------------|
| 1: GitHub Actions gate | 2 new (.github) | Critical | Low |
| 2: Public demo page | 2 files (1 new, 1 edit) | High | Low |
| 3: EU AI Act Art. 9+15 | 1 file (eu_ai_act.py additions) | High | Low |
| 4: G2 Taint tracking | 3 files (dataclass + propagation) | Low | High |

---

*Design approved 2026-03-05. Next: writing-plans implementation plan.*
