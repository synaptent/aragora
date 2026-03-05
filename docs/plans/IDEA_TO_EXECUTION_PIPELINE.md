# Idea-to-Execution Pipeline: Strategic Plan

## The Vision

A unified visual interface where users:
1. **Organize ideas** into relationship graphs (like Obsidian, but visual DAGs)
2. **Derive goals/principles** from idea clusters (AI-powered state transition planning)
3. **Turn goals into project plans** with dependency-aware action sequences
4. **Execute plans via multi-agent orchestration** (heterogeneous AI agents, not manual work)

All four stages share a unified DAG visual language with blockchain-like cryptographic provenance.

---

## Market Analysis: This Is Genuinely Novel

**No existing tool bridges all four stages.** The market is fragmented:

| Stage | Best-in-class tools | Gap |
|-------|-------------------|-----|
| Ideas | Obsidian, Heptabase, Tana, Miro | Dead-end at "organized information" |
| Goals | Quantive StrategyAI, ITONICS | Enterprise-only, assume goals already exist |
| Projects | Linear, Asana, ClickUp | No upstream ideation, no agent execution |
| Orchestration | LangGraph, CrewAI, Dify, n8n | Code-first, no upstream planning stages |

**Closest competitors:**
- **Taskade** bridges ideas + PM with shallow AI agents (no heterogeneous orchestration)
- **ITONICS** bridges ideas + strategy + portfolio (enterprise-only, no AI execution)
- **Dify** has excellent visual agent orchestration (but zero upstream stages)

**What's uniquely novel:**
1. Unified DAG visual language across all four stages
2. AI-driven stage transitions (not mechanical 1:1 conversion)
3. Cryptographic provenance from idea through execution result
4. Heterogeneous multi-agent orchestration driven by project plans
5. Designed for people who are idea-rich but execution-poor

**Market opportunity:** AI orchestration market $11B → $30B by 2030 (22% CAGR). 73% of SMBs using AI agents report gains within 90 days, but >40% of projects cancelled due to complexity.

---

## Codebase Inventory: ~70% Already Exists

The Aragora codebase has extensive infrastructure across all four stages:

| Stage | Backend | Frontend | LOC | Maturity |
|-------|---------|----------|-----|----------|
| 1: Ideas | `ArgumentCartographer` + `canvas/models.py` | `IdeaCanvas` + palette + editor | ~800 | Implemented |
| 2: Goals | `GoalExtractor` (structural + AI modes) | `GoalCanvas` + palette + editor | ~1,200 | Implemented |
| 3: Actions | `WorkflowEngine` + step types | `ActionCanvas` + palette + editor | ~2,000 | Implemented |
| 4: Orchestration | `AutonomousOrchestrator` + `MetaPlanner` | `OrchestrationCanvas` + palette + editor | ~4,000 | Production-ready |
| Cross-stage | `IdeaToExecutionPipeline` | `PipelineCanvas` + `StageNavigator` | ~1,173 | Integrated |

**Key existing infrastructure:**
- **Canvas data models** (`aragora/canvas/models.py`, `stages.py`): Full type system with 9 idea node types, 6 goal types, 5 action types, 6 orchestration types
- **Stage transitions** with `ProvenanceLink` (SHA-256 content hashes) and `StageTransition` (approval gates, confidence scores)
- **IdeaToExecutionPipeline** (`aragora/pipeline/idea_to_execution.py`, 1,173 LOC): Master orchestrator with `from_debate()`, `from_ideas()`, `run()`, `advance_stage()`
- **React Flow canvases** with drag-and-drop, real-time collaboration, keyboard navigation (1/2/3/4 keys + 'a' for all)
- **REST endpoints**: 15+ covering full pipeline lifecycle
- **135+ test files** across pipeline, workflow, goals, and canvas modules

---

## What's Missing (The ~30%)

### Gap 1: Frontend polish and real user experience
The canvases exist but need production polish:
- No onboarding flow guiding users from "dump your ideas" to "watch agents execute"
- No natural-language idea input (e.g., paste a brainstorm → auto-organize into graph)
- Stage transitions require API calls, not one-click "Generate Goals from Ideas"
- No template library for common idea-to-execution patterns

### Gap 2: AI-quality stage transitions
- `GoalExtractor` has structural mode but the AI-assisted mode needs real LLM integration testing
- Goal → Action decomposition uses fixed templates per goal type; needs more nuanced decomposition
- No learning from past transitions (which idea clusters produced successful goals?)

### Gap 3: End-to-end orchestration is not wired to the canvas
- `IdeaToExecutionPipeline` exists but isn't invoked from the pipeline canvas UI
- Agent execution in Stage 4 isn't reflected in real-time canvas updates
- No "Run Pipeline" button that triggers the full `from_ideas()` → `run()` flow

### Gap 4: Self-improvement cannot yet direct itself effectively
- `SelfImprovePipeline` has the mechanics (scan → prioritize → execute → verify)
- But: no access to user feedback, market signals, or business objectives
- It optimizes for codebase health, not product-market fit
- The debug loop works for iterating on test failures but not for creative design decisions

---

## Can Aragora Direct Its Own Development?

**Honest assessment: Not yet, but close.**

**What works:**
- MetaPlanner can scan codebase signals (test failures, lint, TODOs, git changes) and prioritize work
- TaskDecomposer can break goals into subtasks with file scope
- DebugLoop can iterate on implementation until tests pass
- SelfImprovePipeline orchestrates the full cycle

**What doesn't work yet:**
1. **No market awareness** — The system optimizes for code quality, not user value. It can't know that "idea-to-execution pipeline" is more valuable than "fix a lint warning."
2. **No creative design capability** — It can refactor code and fix bugs, but can't design new UX flows or make product decisions.
3. **No multi-session coordination** — Each Claude Code session starts fresh. The system can't maintain a multi-day plan across sessions.
4. **No evaluation of its own product impact** — It can check if tests pass, but can't determine if a change made the product more useful.

**To close the gap:** The self-improvement pipeline needs external signal injection — user feedback, business metrics, product analytics. The `_scan_prioritize()` method we just enhanced is the right insertion point.

---

## Implementation Plan

### Phase 1: Wire the Golden Path (1-2 sessions)
**Goal:** A user can paste ideas into the PipelineCanvas and click "Generate" to see AI-organized ideas → goals → actions → orchestration plan.

1. Add "Generate Goals" button to IdeaCanvas that calls `POST /api/v1/canvas/pipeline/extract-goals`
2. Add "Generate Actions" button to GoalCanvas that calls pipeline advance endpoint
3. Add "Run Pipeline" button to PipelineCanvas that triggers full `IdeaToExecutionPipeline.run()`
4. Wire WebSocket events from `pipeline_stream.py` to update canvas nodes in real-time
5. Add natural-language input box on Ideas stage: paste text → `from_ideas()` → auto-populate canvas

### Phase 2: Polish the User Experience (2-3 sessions)
**Goal:** The interface is intuitive enough for a non-technical SME user.

1. Onboarding wizard: "What are you trying to decide?" → guided pipeline creation
2. Template library: pre-built pipeline templates for common decisions (hiring, product launch, market entry, compliance audit)
3. Stage transition animations showing provenance links
4. Human-in-the-loop approval gates with clear UI (approve/reject/revise)
5. Progress dashboard showing pipeline status across stages

### Phase 3: Improve AI Quality (2-3 sessions)
**Goal:** Stage transitions produce genuinely useful output, not generic decomposition.

1. Integrate debate into goal extraction: run a mini-debate about which goals are most impactful
2. Add domain-specific decomposition templates (healthcare, financial, legal verticals)
3. Learn from past transitions: which idea clusters → goal structures produced successful outcomes
4. Agent capability matching: assign the right agent type based on action requirements
5. Feedback loop: user ratings on generated goals/actions train better transitions

### Phase 4: Differentiate with Provenance (1-2 sessions)
**Goal:** Every output is traceable to its source ideas with cryptographic integrity.

1. Render provenance chain in the UI (click any action → see the goal → see the ideas it came from)
2. Export provenance as audit artifact (PDF/JSON) for compliance
3. Sign transitions with ERC-8004 identity for blockchain verification
4. Add "Decision Receipt" generation at pipeline completion

### Phase 5: Self-Improvement Integration (1-2 sessions)
**Goal:** The self-improvement pipeline can take "improve the idea-to-execution pipeline" as a goal and execute it.

1. Add user feedback signals to `_scan_prioritize()` (ratings, usage analytics, feature requests)
2. Wire `SelfImprovePipeline` to use `IdeaToExecutionPipeline` for its own planning
3. Add business metric injection: conversion rates, user retention, feature adoption
4. Create a "meta-pipeline" that uses the pipeline to improve the pipeline

---

## Open Source Leverage

All MIT-licensed, already in the project or ready to integrate:

| Library | Usage | Status |
|---------|-------|--------|
| **React Flow / Xyflow** | All canvas UIs | Already integrated |
| **Zustand** | Frontend state management | Already integrated |
| **Mermaid.js** | DAG serialization/rendering | Available |
| **dagre** | Layout algorithm for canvases | Used by React Flow |
| **LangGraph** | Agent orchestration patterns | Pattern reference |
| **Temporal** | Durable workflow execution | Architecture reference |

---

## Defensibility

1. **Format network effects** — If the unified DAG format becomes standard for idea-to-execution pipelines, switching costs are high
2. **Regulatory moat** — EU AI Act requires audit trails; cryptographic provenance from idea through execution is uniquely positioned
3. **Institutional memory** — Each completed pipeline trains the system; compounding intelligence is nearly impossible to replicate
4. **Integration depth** — 41 KM adapters, multiple LLM providers, external tool connectors create a web that's expensive to copy
5. **SME-specific design** — Large platforms optimize for broad markets; this targets "10-200 person company that needs AI-orchestrated execution"

---

## Recommended Execution Order

1. **Phase 1** (highest impact, lowest effort) — Wire the golden path. This makes the existing infrastructure usable and demonstrates the vision end-to-end.
2. **Phase 4** (high differentiation) — Provenance visualization is a unique differentiator and regulatory advantage.
3. **Phase 2** (user adoption) — Polish makes the difference between demo and product.
4. **Phase 3** (quality) — Better AI transitions increase user trust and retention.
5. **Phase 5** (long-term) — Meta-improvement closes the loop on autonomous development.
