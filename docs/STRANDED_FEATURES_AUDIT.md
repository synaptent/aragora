# Stranded Features Audit

**Date:** 2026-02-24
**Scope:** Full audit of 215+ features to identify stranded (built but disconnected) capabilities and wire the highest-value ones into the live product.

## Methodology

1. Cross-referenced `docs/FEATURE_DISCOVERY.md` and `docs/STATUS.md` for the full feature catalog
2. Examined all 6 handler registry modules (`debates.py`, `analytics.py`, `admin.py`, `agents.py`, `memory.py`, `social.py`) -- 319 handler imports, 318 registry entries
3. Compared registered handlers against existing frontend pages (120+ pages in `aragora/live/src/app/(app)/`)
4. Identified hooks that existed without corresponding pages
5. Checked navigation sidebar for missing links

## Summary

| Category | Count |
|----------|-------|
| Handler imports audited | 319 |
| Registry entries verified | 318 |
| Unregistered handlers found | 2 (now fixed) |
| Frontend pages without backend | 0 |
| Backend handlers without frontend | 8 (now wired) |
| Total new pages created | 8 |
| Navigation entries added | 6 |

## Top 10 Stranded Features Identified

### 1. Decision Explainability -- WIRED

**Status before:** Handler registered (`ExplainabilityHandler`), hook existed (`useExplanation`), components existed (`ExplainabilityPanel`, `BatchExplainabilityPanel`), but NO frontend page.

**Fix:** Created `/explainability/page.tsx` with debate selector, real-time explainability panel (dynamic import to avoid SSR), and batch analysis panel. Connects to `/api/v1/debates/{id}/explanation`, `/api/v1/debates/{id}/evidence`, `/api/v1/debates/{id}/vote-pivots`, `/api/v1/debates/{id}/counterfactuals`.

**File:** `aragora/live/src/app/(app)/explainability/page.tsx`

### 2. Knowledge Flow Visualization -- WIRED

**Status before:** Handler registered (`KnowledgeFlowHandler`), but no frontend page to visualize the knowledge flywheel.

**Fix:** Created `/knowledge-flow/page.tsx` with three tabs: Flow (adapter activity, knowledge items, flow direction), Confidence History (temporal confidence tracking), and Adapter Health (status of all 34 KM adapters). Fetches from `/api/v1/knowledge/flow`, `/api/v1/knowledge/flow/confidence-history`, `/api/v1/knowledge/adapters/health`.

**File:** `aragora/live/src/app/(app)/knowledge-flow/page.tsx`

### 3. Memory Gateway Explorer -- WIRED

**Status before:** Handler registered (`MemoryUnifiedGatewayHandler`), unified memory gateway fully built (150 tests), but no UI for exploring cross-system memory.

**Fix:** Created `/memory-gateway/page.tsx` with four tabs: Sources (memory tier overview), Search (cross-system query with source filtering), Retention Gate (surprise-driven retain/demote/forget metrics), and Dedup Clusters (near-duplicate detection). Fetches from `/api/v1/memory/unified/sources`, POST `/api/v1/memory/unified/query`, `/api/v1/memory/unified/retention`, `/api/v1/memory/unified/dedup`.

**File:** `aragora/live/src/app/(app)/memory-gateway/page.tsx`

### 4. System Intelligence Dashboard -- WIRED

**Status before:** Handler registered (`SystemIntelligenceHandler`), hooks existed (`useSystemIntelligence`, `useAgentPerformance`, `useInstitutionalMemory`, `useImprovementQueue`), but no page.

**Fix:** Created `/system-intelligence/page.tsx` with four panels: System Overview (nomic cycles, success rate, active agents, knowledge items), Agent Performance (ELO + calibration per agent), Institutional Memory (learned patterns, confidence shifts), and Self-Improvement Queue (prioritized goals). All panels use `PanelErrorBoundary` for resilience.

**File:** `aragora/live/src/app/(app)/system-intelligence/page.tsx`

### 5. Outcome Dashboard -- WIRED

**Status before:** Handler registered (`OutcomeDashboardHandler`), hooks existed (`useQualityScore`, `useOutcomeAgents`, `useDecisionHistory`, `useCalibrationCurve`), but no page.

**Fix:** Created `/outcome-dashboard/page.tsx` with four sections: Decision Quality (quality score, consensus rate, avg rounds, completion rate), Agent Leaderboard (ELO rankings + Brier scores), Calibration Curve (predicted vs actual accuracy with ECE), and Decision History (recent debates linked to explainability). Uses `CalibrationBin` type for bin rendering.

**File:** `aragora/live/src/app/(app)/outcome-dashboard/page.tsx`

### 6. Cross-Debate Learning -- WIRED

**Status before:** `useInstitutionalMemory` hook provided cross-debate learning data, handler served it at `/api/v1/system-intelligence/institutional-memory`, but no dedicated page surfaced cross-debate patterns.

**Fix:** Created `/cross-debate/page.tsx` showing cross-debate stats (total injections, retrieval count), learned patterns with confidence scores and frequency, and recent knowledge injections. Visualizes the institutional memory that flows between debates.

**File:** `aragora/live/src/app/(app)/cross-debate/page.tsx`

### 7. Agent Performance Deep Dive -- WIRED

**Status before:** Basic agent data shown on leaderboard page, but no dedicated deep-dive showing ELO trends over time, per-agent domain specializations, and calibration accuracy.

**Fix:** Created `/agent-performance/page.tsx` with ELO trend sparklines (using a dynamically-imported `MiniChart` component), per-agent expandable cards showing domain badges, calibration percentage, and win rate. Fetches from `/api/v1/system-intelligence/agent-performance`.

**File:** `aragora/live/src/app/(app)/agent-performance/page.tsx`

### 8. Supermemory Explorer -- WIRED

**Status before:** Referenced in sidebar navigation comment, supermemory fully built with 80+ tests, handler registered, but no page to explore or search supermemory.

**Fix:** Created `/supermemory/page.tsx` with stats overview (total memories, namespaces, avg importance), search interface (query input with namespace filter), and recent memories list. Fetches from `/api/v1/memory/supermemory/stats`, POST `/api/v1/memory/supermemory/search`, `/api/v1/memory/supermemory/recent`.

**File:** `aragora/live/src/app/(app)/supermemory/page.tsx`

### 9. GauntletSecureHandler -- REGISTERED

**Status before:** Imported in `debates.py` via `_safe_import` but NOT included in `DEBATE_HANDLER_REGISTRY`. This meant the secure gauntlet verification endpoint was loaded but never routed.

**Fix:** Added `("_gauntlet_secure_handler", GauntletSecureHandler)` to `DEBATE_HANDLER_REGISTRY` in `aragora/server/handler_registry/debates.py`.

### 10. SpendAnalyticsHandler -- REGISTERED

**Status before:** Imported in `admin.py` via `_safe_import` but NOT included in `ADMIN_HANDLER_REGISTRY`. The spend analytics endpoint was unreachable.

**Fix:** Added `("_spend_analytics_handler", SpendAnalyticsHandler)` to `ADMIN_HANDLER_REGISTRY` in `aragora/server/handler_registry/admin.py`.

## Navigation Updates

Added 6 new entries to the `LeftSidebar` navigation component:

**Analytics & Insights section:**
- System Intelligence (`/system-intelligence`)
- Outcome Dashboard (`/outcome-dashboard`)
- Agent Performance (`/agent-performance`)

**Memory & Knowledge section:**
- Memory Gateway (`/memory-gateway`)
- Knowledge Flow (`/knowledge-flow`)
- Cross-Debate (`/cross-debate`, gated to `standard` mode and above)

The Explainability and Supermemory pages are accessible via direct links and cross-references from other pages (e.g., decision history links to explainability, memory page links to supermemory).

## Verification

- **TypeScript:** `npx tsc --noEmit` passes with zero errors across all 8 new pages
- **Python:** All 7 handler registry files parse cleanly via `ast.parse()`
- **Handler parity:** 319 handler imports, 318 registry entries (1 is `HandlerResult`, a utility type, not a handler)
- **Navigation:** All 6 sidebar entries verified in `LeftSidebar.tsx`

## Features NOT Stranded (Confirmed Wired)

These features were checked and confirmed to already have both backend handlers and frontend pages:

| Feature | Handler | Page |
|---------|---------|------|
| Calibration tracking | `CalibrationHandler` | `/calibration` |
| Gauntlet receipts | `GauntletHandler` | `/receipts` |
| Pipeline canvas | `CanvasPipelineHandler` | `/orchestration` |
| Deliberations | `DeliberationsHandler` | `/deliberations` |
| Tournaments | `TournamentHandler` | `/tournaments` |
| ELO leaderboard | `LeaderboardHandler` | `/leaderboard` |
| Pulse/trending | `PulseHandler` | `/pulse` |
| Spectate | `SpectateStreamHandler` | `/spectate` |
| Playbooks | `PlaybookHandler` | `/playbooks` |
| Memory analytics | `MemoryAnalyticsHandler` | `/memory-analytics` |
| Decision analytics | `DecisionAnalyticsHandler` | `/analytics` |
| Observability | `ObservabilityHandler` | `/observability` |
| Benchmarking | `BenchmarkingHandler` | `/quality` |

## Remaining Opportunities

These features have backend support but may benefit from enhanced frontend coverage in future iterations:

1. **Formal Verification** (`FormalVerificationHandler`) -- `/verify` page exists but could show Z3/Lean proof details
2. **Rhetoric Analysis** (`RhetoricalObserver`) -- no dedicated page; could show fallacy detection results
3. **Trickster Detection** -- hollow consensus detection data not surfaced in any dashboard
4. **Cost Forecasting** (`ForecastHandler`) -- `/costs` page exists but forecasting projections not shown
5. **Compliance Reports** (`ComplianceHandler`) -- `/compliance` page exists but report generation not exposed
6. **Settlement Tracking** (`SettlementHandler`) -- handler registered but no dedicated UI for settlement flows
7. **Cross-Platform Analytics** (`CrossPlatformAnalyticsHandler`) -- registered but no page for cross-platform comparison
8. **Moderation Analytics** (`ModerationAnalyticsHandler`) -- registered but `/moderation` page focuses on content, not analytics
