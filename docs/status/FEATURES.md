# Aragora Feature Documentation

> **Last reviewed:** 2026-03-06
> **Snapshot basis:** 2026-02-03
> Historical phase-by-phase feature chronology. For current state and planning, use [STATUS](STATUS.md), [FEATURE_DISCOVERY](FEATURE_DISCOVERY.md), [FEATURE_GAP_LIST](../FEATURE_GAP_LIST.md), and [DOCUMENTATION_HYGIENE_AND_GAP_REGISTER](DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md).


This document provides a snapshot of major features and their origins. For live counts and recent updates, see `docs/status/STATUS.md`.

## Table of Contents

- [Phase 1: Foundation](#phase-1-foundation)
- [Phase 2: Learning](#phase-2-learning)
- [Phase 3: Evidence & Resilience](#phase-3-evidence--resilience)
- [Phase 4: Agent Evolution](#phase-4-agent-evolution)
- [Phase 5: Intelligence](#phase-5-intelligence)
- [Phase 6: Formal Reasoning](#phase-6-formal-reasoning)
- [Phase 7: Reliability & Audit](#phase-7-reliability--audit)
- [Phase 8: Advanced Debates](#phase-8-advanced-debates)
- [Phase 9-19: Truth Grounding, Modes, Infrastructure](#phase-9-truth-grounding-recent)
- [Phase 20: Demo Fixtures & Search](#phase-20-demo-fixtures--search-2026-01)
- [Phase 21: Feature Integration](#phase-21-feature-integration-2026-01-09)
- [Phase 22: Inbox Ops & Codebase Analysis](#phase-22-inbox-ops--codebase-analysis-2026-01-22)
- [Phase 23: Coding & Review](#phase-23-coding--review-2026-01-22)

---

## Phase 1: Foundation

### ContinuumMemory
**File:** `aragora/memory/continuum/core.py`

Multi-timescale learning system that organizes memories into fast, medium, and slow tiers based on recency and importance.

```python
from aragora.memory.continuum import ContinuumMemory

memory = ContinuumMemory(db_path="continuum.db")
memory.store("Important insight", tier="FAST", agent="anthropic-api")
recent = memory.retrieve(tier="FAST", limit=10)
```

**Key Methods:**
- `store(content, tier, agent)` - Store content in a specific tier
- `retrieve(tier, limit)` - Retrieve recent memories from a tier
- `promote(memory_id)` - Promote memory to a higher tier
- `decay()` - Age out old memories

### ReplayRecorder
**File:** `aragora/replay/replay.py`

Records all cycle events for later analysis and replay.

```python
from aragora.replay.replay import DebateRecorder, DebateReplayer

recorder = DebateRecorder(storage_dir="replays")
filepath = recorder.save_debate(result, metadata={"agents": ["anthropic-api", "codex"]})

replayer = DebateReplayer(storage_dir="replays")
debates = replayer.list_debates()
replayer.replay_debate("debate_20260103_120000_abc12345.json", speed=2.0)
```

### MetaLearner
**File:** `aragora/learning/meta.py`

Self-tuning hyperparameter optimization based on debate outcomes.

```python
from aragora.learning.meta import MetaLearner

learner = MetaLearner(db_path="meta.db")
suggestions = learner.suggest_adjustments({
    "consensus_rate": 0.75,
    "avg_rounds": 2.5,
    "avg_confidence": 0.85
})
```

### IntrospectionAPI
**File:** `aragora/introspection/api.py`

Agent self-awareness and reflection capabilities.

```python
from aragora.introspection.api import IntrospectionAPI

api = IntrospectionAPI()
state = api.get_agent_state(agent_name)
api.record_reflection(agent_name, "I noticed my critiques were too harsh")
```

### ArgumentCartographer
**File:** `aragora/visualization/mapper.py`

Builds directed graphs of debate logic in real-time for visualization.

```python
from aragora.visualization.mapper import ArgumentCartographer

cartographer = ArgumentCartographer()
cartographer.start_debate("debate-123", task="Design a cache")
cartographer.add_proposal("anthropic-api", "Use Redis with LRU")
cartographer.add_critique("codex", "anthropic-api", ["No failover strategy"], severity=0.7)
graph = cartographer.get_graph()
```

### WebhookDispatcher
**File:** `aragora/integrations/webhooks.py`

Sends notifications to external systems on debate events.

```python
from aragora.integrations.webhooks import WebhookDispatcher

dispatcher = WebhookDispatcher()
dispatcher.register("https://example.com/webhook", events=["debate_start", "consensus_reached"])
await dispatcher.dispatch("debate_start", {"task": "Design API"})
```

---

## Phase 2: Learning

### ConsensusMemory
**File:** `aragora/memory/consensus.py`

Tracks which topics have reached consensus and which remain contested.

```python
from aragora.memory.consensus import ConsensusMemory

memory = ConsensusMemory(db_path="consensus.db")
memory.record_consensus("API versioning", reached=True, confidence=0.9)
status = memory.get_topic_status("API versioning")
contested = memory.get_contested_topics(min_debates=3)
```

### InsightExtractor
**File:** `aragora/insights/extractor.py`

Extracts patterns and insights from completed debates.

```python
from aragora.insights.extractor import InsightExtractor

extractor = InsightExtractor(db_path="insights.db")
insights = extractor.extract_from_debate(result)
patterns = extractor.get_winning_patterns(min_occurrences=3)
```

---

## Phase 3: Evidence & Resilience

### MemoryStream
**File:** `aragora/memory/streams.py`

Per-agent persistent memory that survives across debates.

```python
from aragora.memory.streams import MemoryStream

stream = MemoryStream(db_path="streams.db")
stream.add_memory("anthropic-api", "User prefers functional style")
memories = stream.get_memories("anthropic-api", limit=10)
```

### LocalDocsConnector
**File:** `aragora/connectors/local_docs.py`

Searches local codebase for evidence to ground claims.

```python
from aragora.connectors.local_docs import LocalDocsConnector

connector = LocalDocsConnector(root_path=".")
evidence = await connector.search("rate limiting implementation")
content = await connector.fetch("aragora/debate/orchestrator.py")
```

### CounterfactualOrchestrator
**File:** `aragora/debate/counterfactual.py`

Resolves deadlocks by exploring alternative debate branches.

```python
from aragora.debate.counterfactual import CounterfactualOrchestrator

orchestrator = CounterfactualOrchestrator()
if orchestrator.detect_deadlock(messages):
    branches = await orchestrator.fork_debate(context)
    best = orchestrator.merge_branches(branches)
```

### CapabilityProber
**File:** `aragora/modes/prober.py`

Tests agent capabilities to ensure quality.

```python
from aragora.modes.prober import CapabilityProber

prober = CapabilityProber()
results = await prober.probe_agent(agent, tests=["code_generation", "critique"])
if results.passed:
    print(f"Agent scored {results.score}")
```

### WorkflowTemplates
**File:** `aragora/workflow/templates/`

Workflow templates are delivered in two forms:
- YAML templates loaded by `aragora.workflow.template_loader.TemplateLoader`
- Python template registry in `aragora.workflow.templates.WORKFLOW_TEMPLATES`

```python
from aragora.workflow.templates import get_template

workflow = get_template("marketing/ad-performance-review")
result = await engine.execute(workflow, inputs)
```

### AgentCircuitBreaker
**File:** `scripts/nomic_loop.py`

Prevents cascade failures when agents repeatedly fail. Trips after configurable failure threshold and auto-resets after cooldown cycles.

```python
from scripts.nomic_loop import AgentCircuitBreaker

breaker = AgentCircuitBreaker(
    failure_threshold=3,  # Trip after 3 consecutive failures
    cooldown_cycles=2     # Wait 2 cycles before retrying
)

# Check before calling agent
if breaker.is_open("anthropic-api"):
    print("Agent tripped - skipping")
else:
    try:
        result = await agent.call()
        breaker.record_success("anthropic-api")
    except Exception:
        breaker.record_failure("anthropic-api")

# Get circuit status
status = breaker.get_status()  # {"anthropic-api": {"open": True, "failures": 3}}
```

**States:**
- **CLOSED**: Normal operation, agent is healthy
- **OPEN**: Tripped, skipping agent calls
- **HALF-OPEN**: Testing if agent recovered (first call after cooldown)

### Cycle Timeout
**File:** `scripts/nomic_loop.py`

Prevents runaway cycles from consuming unlimited time. Configurable per-cycle timeout with phase-level deadline checks.

```python
loop = NomicLoop(
    max_cycle_seconds=7200  # 2 hour max per cycle (default)
)

# Or override per-run:
await loop.run_cycle(max_cycle_seconds=3600)  # 1 hour limit
```

**Behavior:**
- Logs warning at 50% time consumed
- Graceful shutdown at deadline with partial results
- Phase-level checks prevent hanging in any single phase
- Timeout triggers circuit breaker for slow agents

### Agent Health Check
**File:** `aragora/debate/orchestrator.py`

15-second connectivity probe before debates to verify agents are reachable.

```python
# Arena performs health check on startup
arena = Arena(environment=env, agents=agents)
# Logs: "[health] claude: OK (0.8s)" or "[health] codex: FAILED (timeout)"
```

Unhealthy agents are excluded from the debate automatically.

---

## Phase 4: Agent Evolution

### PersonaManager
**File:** `aragora/agents/personas.py`

Manages agent personalities, traits, and expertise evolution.

```python
from aragora.agents.personas import PersonaManager

manager = PersonaManager(db_path="personas.db")
persona = manager.get_persona("claude-visionary")
manager.update_trait("claude-visionary", "expertise", "distributed systems")
manager.record_success("claude-visionary", domain="caching")
```

### PromptEvolver
**File:** `aragora/evolution/evolver.py`

Evolves agent system prompts based on successful patterns.

```python
from aragora.evolution.evolver import PromptEvolver

evolver = PromptEvolver(db_path="prompts.db")
evolver.record_success(agent_name, prompt_version, score=0.95)
new_prompt = evolver.evolve(agent_name)
```

### Tournament
**File:** `aragora/tournaments/tournament.py`

Periodic competitive benchmarking between agents.

```python
from aragora.tournaments.tournament import Tournament

tournament = Tournament(agents=["anthropic-api", "codex", "gemini"])
results = await tournament.run(tasks=benchmark_tasks)
rankings = tournament.get_rankings()
```

---

## Phase 5: Intelligence

### ConvergenceDetector
**File:** `aragora/debate/convergence.py`

Detects when debate has converged for early stopping.

```python
from aragora.debate.convergence import ConvergenceDetector

detector = ConvergenceDetector(threshold=0.85)
status = detector.check(messages)
if status.converged:
    print(f"Converged at similarity {status.similarity:.2f}")
```

### MetaCritiqueAnalyzer
**File:** `aragora/debate/meta.py`

Analyzes the debate process itself and provides recommendations.

```python
from aragora.debate.meta import MetaCritiqueAnalyzer

analyzer = MetaCritiqueAnalyzer()
analysis = analyzer.analyze_debate(result)
recommendations = analysis.recommendations
```

### EloSystem
**File:** `aragora/ranking/elo.py`

Persistent skill tracking using Elo ratings.

```python
from aragora.ranking.elo import EloSystem

elo = EloSystem(db_path="elo.db")
elo.record_match(winner="anthropic-api", loser="codex", domain="security")
rating = elo.get_rating("anthropic-api")
```

### AgentSelector
**File:** `aragora/routing/selection.py`

Smart agent team selection based on task requirements.

```python
from aragora.routing.selection import AgentSelector

selector = AgentSelector(elo_system=elo, persona_manager=personas)
team = selector.select(task="Design authentication", team_size=3)
```

### RiskRegister
**File:** `aragora/pipeline/risk_register.py`

Tracks items with low consensus for future attention.

```python
from aragora.pipeline.risk_register import RiskRegister

register = RiskRegister(db_path="risks.db")
register.add_risk("SQL injection vectors", confidence=0.4, severity="high")
high_risks = register.get_risks(min_severity="high")
```

---

## Phase 6: Formal Reasoning

### ClaimsKernel
**File:** `aragora/reasoning/claims.py`

Structured typed claims with evidence tracking.

```python
from aragora.reasoning.claims import ClaimsKernel, Claim, ClaimType

kernel = ClaimsKernel()
claim = Claim(
    content="This algorithm is O(n log n)",
    claim_type=ClaimType.MATHEMATICAL,
    evidence=["complexity_proof.md"]
)
kernel.add_claim(claim)
```

### ProvenanceManager
**File:** `aragora/reasoning/provenance.py`

Cryptographic evidence chain integrity.

```python
from aragora.reasoning.provenance import ProvenanceManager

provenance = ProvenanceManager(db_path="provenance.db")
chain = provenance.create_chain(evidence_id, source="github.com/...")
verified = provenance.verify_chain(chain_id)
```

### BeliefNetwork
**File:** `aragora/reasoning/belief.py`

Probabilistic reasoning over uncertain claims.

```python
from aragora.reasoning.belief import BeliefNetwork

network = BeliefNetwork()
network.add_belief("system_secure", prior=0.7)
network.add_evidence("passed_audit", supports="system_secure", strength=0.9)
posterior = network.query("system_secure")
```

### ProofExecutor
**File:** `aragora/verification/proofs.py`

Executes code to verify claims programmatically.

```python
from aragora.verification.proofs import ProofExecutor

executor = ProofExecutor()
result = await executor.verify_claim(
    claim="Function returns sorted list",
    test_code="assert is_sorted(my_func([3,1,2]))"
)
```

### ScenarioMatrix
**File:** `aragora/debate/scenarios.py`

Robustness testing across multiple scenarios.

```python
from aragora.debate.scenarios import ScenarioMatrix

matrix = ScenarioMatrix()
matrix.add_scenario("high_load", {"requests_per_sec": 10000})
matrix.add_scenario("network_partition", {"partition_prob": 0.1})
results = await matrix.run_all(system_under_test)
```

---

## Phase 7: Reliability & Audit

### EnhancedProvenanceManager
**File:** `aragora/reasoning/provenance_enhanced.py`

Extends ProvenanceManager with staleness detection for living documents.

```python
from aragora.reasoning.provenance_enhanced import EnhancedProvenanceManager

provenance = EnhancedProvenanceManager(db_path="provenance.db")
provenance.set_staleness_threshold(hours=24)
stale = provenance.get_stale_evidence()
```

### CheckpointManager
**File:** `aragora/debate/checkpoint.py`

Pause/resume and crash recovery for long-running debates.

```python
from aragora.debate.checkpoint import CheckpointManager

checkpoint = CheckpointManager(db_path="checkpoints.db")
checkpoint.save(debate_id, state)
restored = checkpoint.restore(debate_id)
```

For git‑backed checkpoints, `GitCheckpointStore` supports **continuous mode**
to commit after every round for maximum crash resilience:

```python
from aragora.debate.checkpoint import GitCheckpointStore

store = GitCheckpointStore(
    repo_path=".",
    continuous_mode=True,
    commit_message_template="Debate {debate_id} round {round}",
)
```

### BreakpointManager
**File:** `aragora/debate/breakpoints.py`

Human intervention points in automated processes.

```python
from aragora.debate.breakpoints import BreakpointManager, BreakpointConfig

breakpoints = BreakpointManager(
    config=BreakpointConfig(min_confidence=0.5, max_deadlock_rounds=3)
)
if breakpoints.should_pause(state):
    await breakpoints.wait_for_human()
```

### ReliabilityScorer
**File:** `aragora/reasoning/reliability.py`

Scores claim confidence based on evidence quality.

```python
from aragora.reasoning.reliability import ReliabilityScorer

scorer = ReliabilityScorer(provenance=provenance_manager)
score = scorer.score_claim(claim_id)
report = scorer.get_reliability_report(claim_id)
```

### DebateTracer
**File:** `aragora/debate/traces.py`

Audit logs with deterministic replay capability.

```python
from aragora.debate.traces import DebateTracer

tracer = DebateTracer(debate_id="d123", task="Design API", agents=["anthropic-api", "codex"])
tracer.record_proposal("anthropic-api", "Use REST with versioning")
tracer.record_critique("codex", "anthropic-api", issues=["No GraphQL support"])
trace = tracer.finalize({"consensus": True})
```

---

## Phase 8: Advanced Debates

### PersonaLaboratory
**File:** `aragora/agents/laboratory.py`

A/B testing, emergent trait detection, and cross-pollination.

```python
from aragora.agents.laboratory import PersonaLaboratory

lab = PersonaLaboratory(persona_manager=personas, db_path="lab.db")
experiment = lab.create_experiment(
    agent="anthropic-api",
    variant_traits=["more_concise", "code_focused"]
)
lab.record_trial(experiment.id, is_control=False, success=True)
emergent = lab.detect_emergent_traits()
lab.cross_pollinate_traits("anthropic-api", "codex", "security_focus")
```

### SemanticRetriever
**File:** `aragora/memory/embeddings.py`

Find similar past critiques using embeddings.

```python
from aragora.memory.embeddings import SemanticRetriever

retriever = SemanticRetriever(db_path="embeddings.db")
await retriever.embed_and_store("critique-123", "The error handling is insufficient")
similar = await retriever.find_similar("needs better error handling", limit=5)
```

### FormalVerificationManager
**File:** `aragora/verification/formal.py`

Z3 SMT solver for verifying logical and mathematical claims.

```python
from aragora.verification.formal import FormalVerificationManager

verifier = FormalVerificationManager()
result = await verifier.verify_claim(
    "For all x > 0, x + 1 > x",
    claim_type="mathematical"
)
if result.status == "PROVED":
    print(f"Proof: {result.proof}")
```

### DebateGraph
**File:** `aragora/debate/graph.py`

DAG-based debates for complex multi-path disagreements with automatic branching and merging.

```python
from aragora.debate.graph import (
    DebateGraph,
    GraphDebateOrchestrator,
    BranchPolicy,
    ConvergencePolicy,
)

# Configure branching behavior
policy = BranchPolicy(
    disagreement_threshold=0.7,  # When to create branches
    max_branches=3,               # Limit concurrent branches
    min_depth_for_branch=1,       # Minimum rounds before branching
)

orchestrator = GraphDebateOrchestrator(agents=agents, policy=policy)

# Run with custom agent function
async def run_agent(agent, prompt, context):
    return await agent.generate(prompt, context)

result = await orchestrator.run_debate(
    task="Design a caching strategy",
    max_rounds=5,
    run_agent_fn=run_agent,  # async fn(agent, prompt, context) -> str
    on_node=lambda node: print(f"New node: {node.id}"),
    on_branch=lambda branch: print(f"Branch: {branch.hypothesis}"),
    on_merge=lambda merge: print(f"Merged: {merge.winning_branch}"),
)

# Access graph structure
graph = orchestrator.graph
paths = graph.get_all_paths()
synthesis = graph.get_final_synthesis()
```

**Key Components:**
- `DebateNode` - A node with claims, confidence, and evidence
- `Branch` - A parallel exploration path with hypothesis
- `BranchPolicy` - Rules for when to create branches
- `ConvergencePolicy` - Rules for when to merge branches
- `MergeStrategy` - How to combine branches (vote, synthesis, best_path)

**Helper Methods:**
- `_build_context(nodes)` - Build context from last 5 nodes
- `_extract_confidence(response)` - Parse confidence (0-100%) from text
- `_extract_claims(response)` - Extract numbered/bulleted claims
- `_synthesize_branches(a, b)` - Merge claims from branches

### DebateForker
**File:** `aragora/debate/forking.py`

Parallel branch exploration when agents fundamentally disagree.

```python
from aragora.debate.forking import DebateForker, ForkDetector

detector = ForkDetector()
decision = detector.should_fork(messages, round_num, agents)

if decision.should_fork:
    forker = DebateForker()
    merge_result = await forker.run_branches(decision, base_context)
    print(f"Winning hypothesis: {merge_result.winning_hypothesis}")
```

---

## Agent Cognition: Structured Thinking Protocols

Each agent in the nomic loop uses a specialized thinking protocol that guides their analysis and proposal generation.

### Overview

Structured Thinking Protocols ensure agents:
- Explore before proposing (avoid assumptions)
- Show their reasoning chain (transparent decision-making)
- Consider alternatives (avoid premature convergence)
- Ground proposals in evidence (reference specific code)

### Protocol Details

| Agent | Protocol Steps | Focus |
|-------|----------------|-------|
| **Claude** | EXPLORE → PLAN → REASON → PROPOSE | Architecture, system cohesion |
| **Codex** | TRACE → ANALYZE → DESIGN → VALIDATE | Implementation, code quality |
| **Gemini** | EXPLORE → ENVISION → REASON → PROPOSE | Product vision, user impact |
| **Grok** | DIVERGE → CONNECT → SYNTHESIZE → GROUND | Creative solutions, novel patterns |

### Implementation

The protocols are injected via system prompts in `scripts/nomic_loop.py`:

```python
# Example: Claude's structured thinking protocol
self.claude.system_prompt = """You are a visionary architect for aragora.

=== STRUCTURED THINKING PROTOCOL ===
When analyzing a task:
1. EXPLORE: First understand the current state - read relevant files, trace code paths
2. PLAN: Design your approach before implementing - consider alternatives
3. REASON: Show your thinking step-by-step - explain tradeoffs
4. PROPOSE: Make concrete, actionable proposals with clear impact

When using Claude Code:
- Use 'Explore' mode to deeply understand the codebase before proposing
- Use 'Plan' mode to design implementation approaches with user approval
"""
```

### Benefits

1. **Higher Quality Proposals**: Agents analyze before proposing
2. **Transparent Reasoning**: Other agents can critique the reasoning, not just conclusions
3. **Evidence-Grounded**: Proposals reference specific files and code patterns
4. **Complementary Perspectives**: Each agent's protocol highlights different aspects

---

## Integration in Nomic Loop

All features are integrated into the nomic loop (`scripts/nomic_loop.py`) using an optional import pattern:

```python
# Optional feature import
try:
    from aragora.feature.module import FeatureClass
    FEATURE_AVAILABLE = True
except ImportError:
    FEATURE_AVAILABLE = False
    FeatureClass = None

# Initialize if available
if FEATURE_AVAILABLE:
    self.feature = FeatureClass(db_path=str(self.nomic_dir / "feature.db"))
    print(f"[feature] Feature enabled")
```

Features degrade gracefully—if a feature's dependencies are missing, the loop continues without it.

---

## Feature Dependencies

| Feature | Dependencies |
|---------|--------------|
| SemanticRetriever | sentence-transformers OR openai |
| FormalVerificationManager | z3-solver |
| BeliefNetwork | numpy |
| ConvergenceDetector | sentence-transformers OR sklearn |

Install optional dependencies:
```bash
pip install sentence-transformers z3-solver numpy scikit-learn
```

---

## Phase 9: Truth Grounding (Recent)

### FlipDetector
**File:** `aragora/insights/flip_detector.py`

Semantic position reversal detection that tracks when agents change their positions on claims.

```python
from aragora.insights.flip_detector import FlipDetector

detector = FlipDetector(db_path="positions.db")
flips = detector.detect_flips_for_agent("anthropic-api", lookback_positions=50)
consistency = detector.get_agent_consistency("anthropic-api")
print(f"Consistency score: {consistency.consistency_score:.2%}")
```

**Flip Types:**
- `contradiction` - Direct opposite position
- `refinement` - Minor adjustment
- `retraction` - Complete withdrawal
- `qualification` - Adding nuance

### GroundedPersonaManager
**File:** `aragora/agents/grounded.py`

Truth-grounded persona tracking that links agent identities to verifiable performance history.

```python
from aragora.agents.grounded import GroundedPersonaManager

manager = GroundedPersonaManager(db_path="personas.db")
identity = manager.get_grounded_identity("anthropic-api")
print(f"Win rate: {identity.win_rate:.2%}")
print(f"Calibration: {identity.calibration_score:.2f}")
```

**Key Metrics:**
- Position history with debate outcomes
- Calibration scoring (prediction accuracy)
- Domain expertise tracking
- Inter-agent relationship metrics

### TruthGroundingSystem
**File:** `aragora/agents/truth_grounding.py`

Central system for maintaining epistemic accountability across debates.

```python
from aragora.agents.truth_grounding import TruthGroundingSystem

system = TruthGroundingSystem(db_path="grounding.db")
system.record_position("anthropic-api", "claim-123", 0.85, "debate-456")
accuracy = system.compute_calibration("anthropic-api")
```

### CalibrationTracker
**File:** `aragora/agents/calibration.py`

Tracks prediction accuracy using Brier scoring and ECE (Expected Calibration Error).

```python
from aragora.agents.calibration import CalibrationTracker

tracker = CalibrationTracker(db_path="calibration.db")
tracker.record_prediction("anthropic-api", confidence=0.85, correct=True, domain="security")
summary = tracker.get_calibration_summary("anthropic-api")
print(f"Brier score: {summary['brier_score']:.4f}")
print(f"ECE: {summary['ece']:.4f}")
curve = tracker.get_calibration_curve("anthropic-api")  # For visualization
```

**Key Metrics:**
- Brier score (lower is better calibration)
- ECE (Expected Calibration Error)
- Per-domain calibration breakdown
- Calibration curve data for plotting

### DissentRetriever (Enhanced)
**File:** `aragora/memory/consensus.py`

Enhanced dissent retrieval with contrarian views and risk warnings.

```python
from aragora.memory.consensus import DissentRetriever

retriever = DissentRetriever(memory)
contrarian = retriever.find_contrarian_views("The approach should use caching")
risks = retriever.find_risk_warnings("Database migration")
context = retriever.get_debate_preparation_context("New feature design")
```

### DebateForker
**File:** `aragora/debate/forking.py`

Parallel branch exploration for deadlock resolution.

```python
from aragora.debate.forking import ForkDetector, DebateForker

detector = ForkDetector(disagreement_threshold=0.7)
decision = detector.should_fork(messages, round_num, agents)

if decision:
    forker = DebateForker(agents, protocol)
    merge_result = await forker.run_branches(decision.branches, base_context)
    print(f"Winner: {merge_result.winning_branch}")
```

### EnhancedProvenanceManager
**File:** `aragora/reasoning/provenance_enhanced.py`

Staleness detection and evidence validation for claims.

```python
from aragora.reasoning.provenance_enhanced import EnhancedProvenanceManager

manager = EnhancedProvenanceManager()
staleness = await manager.check_staleness(claims, changed_files)
if staleness.needs_redebate:
    print(f"Stale claims: {staleness.stale_claims}")
```

### BeliefPropagationAnalyzer (Integrated)
**File:** `aragora/reasoning/belief.py`

Now integrated into Arena for automatic crux identification and evidence suggestions.

```python
from aragora.reasoning.belief import BeliefNetwork, BeliefPropagationAnalyzer

# Automatically used in Arena after consensus:
# - result.debate_cruxes: Key claims that drive disagreement
# - result.evidence_suggestions: Claims needing more evidence
```

**Crux Analysis:**
- Identifies claims with high centrality and high uncertainty
- Suggests evidence targets to reduce debate uncertainty
- Computes consensus probability

### ContinuumMemory (Integrated)
**File:** `aragora/memory/continuum/core.py`

Now integrated into Arena for cross-debate learning context.

```python
from aragora.memory.continuum import ContinuumMemory, MemoryTier

# Arena uses continuum_memory parameter:
arena = Arena(
    environment=env,
    agents=agents,
    continuum_memory=ContinuumMemory("continuum.db"),  # NEW
)
# Relevant past learnings are automatically injected into agent context
```

**Memory Tiers:**
- FAST (1 day half-life) - Recent patterns
- MEDIUM (1 week) - Recurring patterns
- SLOW (1 month) - Established patterns
- GLACIAL (1 year) - Foundational knowledge

---

## Phase 10: Thread-Safe Audience Participation

### Thread-Safe Arena Mailbox
**File:** `aragora/debate/orchestrator.py`

Decouples event ingestion from consumption using a thread-safe queue pattern for live audience interaction.

```python
from aragora.debate.orchestrator import Arena, DebateProtocol

arena = Arena(
    environment=env,
    agents=agents,
    protocol=DebateProtocol(rounds=3),
    event_emitter=emitter,
    loop_id="my-debate-123",
    strict_loop_scoping=True,  # Only accept events for this loop
)

# WebSocket thread calls _handle_user_event - enqueues to thread-safe queue
# Debate thread calls _drain_user_events before each prompt build
```

**Key Features:**
- `_user_event_queue: queue.Queue` - Thread-safe event buffer
- `_handle_user_event()` - Enqueues without blocking debate loop
- `_drain_user_events()` - Moves events to lists at safe sync points
- `strict_loop_scoping` - Rejects events not matching current loop_id

### Loop Scoping

Multi-tenant event isolation ensures votes/suggestions go to correct debate:

```python
# Events with matching loop_id are processed
event.loop_id = "my-debate-123"  # Accepted

# Events from other loops are ignored
event.loop_id = "other-debate"  # Dropped

# Strict mode also rejects events without loop_id
arena = Arena(..., strict_loop_scoping=True)
```

### Test Coverage

Comprehensive tests in `tests/test_audience_participation.py`:
- `TestMailboxThreadSafety` - Concurrent enqueue/drain safety
- `TestLoopScoping` - Multi-tenant event isolation
- `TestEdgeCases` - Empty queue, malformed events
- `TestSuggestionIntegration` - Vote/suggestion separation

---

## Phase 11: Operational Modes

### Modes System
**File:** `aragora/modes/`

The modes system allows switching between different operational configurations for agents and debates.

### OperationalModes
**File:** `aragora/modes/base.py`, `aragora/modes/custom.py`

Switches between built-in and custom operational modes:

```python
from aragora.modes import ModeRegistry, register_all_builtins

# Ensure built-ins are registered.
register_all_builtins()

mode = ModeRegistry.get("reviewer")
if mode:
    print(mode.describe())
```

### CapabilityProber
**File:** `aragora/modes/prober.py`

Tests agent capabilities for quality assurance and vulnerability detection.

```python
from aragora.modes.prober import CapabilityProber, ProbeType

prober = CapabilityProber()
report = await prober.probe_agent(
    target_agent=agent,
    probe_types=[
        ProbeType.CONTRADICTION,
        ProbeType.HALLUCINATION,
        ProbeType.CONFIDENCE_CALIBRATION,
    ],
)
print(f"Vulnerability score: {report.vulnerability_score}")
```

**Probe Types:**
- `contradiction` - Tests for logical inconsistencies
- `hallucination` - Tests for fabricated information
- `sycophancy` - Tests for agreement bias
- `confidence_calibration` - Tests confidence accuracy
- `reasoning_depth` - Tests multi-step reasoning
- `edge_case` - Tests boundary conditions

### RedTeamMode
**File:** `aragora/modes/redteam.py`

Adversarial analysis mode for stress-testing debate conclusions with full attack/defense cycles.

```python
from aragora.modes.redteam import RedTeamMode, RedTeamProtocol, AttackType

protocol = RedTeamProtocol(
    attack_rounds=3,
    include_steelman=True,  # Red team presents strongest version of proposal
    include_strawman=True,  # Verify attacks address real claims
)
mode = RedTeamMode(protocol)

result = await mode.run_redteam(
    target_proposal="Use microservices architecture",
    proposer="architect",
    red_team_agents=red_agents,
    run_agent_fn=my_agent_runner,
    max_rounds=3,
    proposer_agent=defender,  # Optional: enables defense execution
)
```

**Attack Types:**
- `devils_advocate` - Argue opposite position
- `edge_case` - Find failure scenarios
- `assumption_challenge` - Question premises
- `scale_test` - Test at different scales
- `adversarial` - Active exploitation attempts

**Defense Types (when proposer_agent provided):**
- `refute` - Attack is invalid (residual_risk=0)
- `mitigate` - Accept issue, explain fix (residual_risk=0.2)
- `acknowledge` - Understood, will review (residual_risk=0.2)
- `accept` - Risk is acceptable (residual_risk based on severity)

**Steelman/Strawman Phases:**
- Steelman: Red team presents strongest version of proposal (round 1)
- Strawman: Verify attacks address actual claims, not distortions

---

## Phase 12: Grounded Personas v2

### Overview

Grounded Personas v2 is a comprehensive system for building agent identities from verifiable performance history. Unlike traditional persona systems that rely on predefined traits, Grounded Personas emerge from actual debate outcomes, creating trustworthy agent identities backed by evidence.

**Core Philosophy:**
- Personas are *earned* through performance, not assigned
- All claims about an agent are backed by verifiable debate history
- Relationships between agents emerge from actual interactions
- Significant moments define agent identity naturally

### PositionLedger
**File:** `aragora/agents/grounded.py`

Tracks every position an agent takes across all debates, enabling historical analysis of consistency and expertise.

```python
from aragora.agents.grounded import PositionLedger, Position

ledger = PositionLedger(db_path="personas.db")

# Record a position
position_id = ledger.record_position(
    agent_name="anthropic-api",
    claim="Microservices are better for this use case",
    confidence=0.85,
    debate_id="debate-123",
    round_num=2,
    domain="architecture",
)

# Get agent's position history
positions = ledger.get_agent_positions("anthropic-api", limit=50)

# Resolve position outcome after debate
ledger.resolve_position(position_id, outcome="correct")  # or "incorrect", "pending"

# Check for position reversals
ledger.mark_reversal(position_id, reversal_debate_id="debate-456")
```

**Key Fields:**
- `claim` - The position statement
- `confidence` - Agent's stated confidence (0.0-1.0)
- `outcome` - Was the position correct? (pending/correct/incorrect)
- `reversed` - Did agent later reverse this position?
- `domain` - Topic domain for expertise tracking

### RelationshipTracker
**File:** `aragora/agents/grounded.py`

Tracks inter-agent relationships based on actual debate interactions.

```python
from aragora.agents.grounded import RelationshipTracker

tracker = RelationshipTracker(db_path="personas.db")

# Update from debate results
tracker.update_from_debate(
    debate_id="debate-123",
    participants=["anthropic-api", "gemini", "codex"],
    winner="anthropic-api",
    votes={"anthropic-api": "option_a", "gemini": "option_a", "codex": "option_b"},
    critiques=[
        {"agent": "codex", "target": "anthropic-api"},
        {"agent": "gemini", "target": "codex"},
    ],
)

# Get relationship between two agents
rel = tracker.get_relationship("anthropic-api", "gemini")
print(f"Alliance score: {rel.alliance_score:.2f}")
print(f"Rivalry score: {rel.rivalry_score:.2f}")
print(f"Influence score: {rel.influence_score:.2f}")

# Get agent's full network
network = tracker.get_agent_network("anthropic-api")
# Returns: {allies: [...], rivals: [...], influences: [...], influenced_by: [...]}
```

**Relationship Types:**
- `alliance_score` - How often agents vote together
- `rivalry_score` - How often agents oppose each other
- `influence_score` - How much this agent influences the other's positions
- `debate_count` - Number of shared debates

### MomentDetector
**File:** `aragora/agents/grounded.py`

Detects genuinely significant narrative moments from debate history.

```python
from aragora.agents.grounded import MomentDetector, SignificantMoment

detector = MomentDetector(
    elo_system=elo,
    position_ledger=ledger,
    relationship_tracker=tracker,
)

# Detect upset victory
moment = detector.detect_upset_victory(
    winner="underdog_agent",
    loser="top_ranked_agent",
    debate_id="debate-789",
)
if moment:
    detector.record_moment(moment)
    print(f"Upset! Significance: {moment.significance_score:.2%}")

# Detect calibration vindication
moment = detector.detect_calibration_vindication(
    agent_name="anthropic-api",
    prediction_confidence=0.92,
    was_correct=True,
    domain="security",
    debate_id="debate-101",
)

# Detect streak achievements
moment = detector.detect_streak_achievement(
    agent_name="gemini",
    streak_type="win",
    streak_length=7,
    debate_id="debate-102",
)

# Get narrative summary
summary = detector.get_narrative_summary("anthropic-api", limit=5)
# Returns formatted markdown of agent's defining moments
```

**Moment Types:**
- `upset_victory` - Lower-rated agent defeats higher-rated (100+ ELO diff)
- `position_reversal` - High-confidence position changed with evidence
- `calibration_vindication` - 85%+ confidence prediction proven correct
- `streak_achievement` - 5+ consecutive wins or losses
- `domain_mastery` - Becomes #1 ranked in a domain
- `consensus_breakthrough` - Rivals reach agreement

### PersonaSynthesizer
**File:** `aragora/agents/grounded.py`

Synthesizes complete agent personas from all grounded data sources.

```python
from aragora.agents.grounded import PersonaSynthesizer

synthesizer = PersonaSynthesizer(
    position_ledger=ledger,
    calibration_tracker=calibration,
    relationship_tracker=tracker,
    moment_detector=detector,
    elo_system=elo,
)

# Generate complete grounded persona
persona = synthesizer.synthesize("anthropic-api")

print(persona.identity_summary)
# "claude is a well-calibrated architect (Brier: 0.12) with expertise in
#  security and distributed systems. They've maintained 78% consistency
#  across 234 positions. Key rival: codex. Key ally: gemini."

print(persona.expertise_profile)
# {"security": 0.89, "architecture": 0.82, "testing": 0.65}

print(persona.calibration_summary)
# {"brier_score": 0.12, "ece": 0.08, "total_predictions": 156}

print(persona.relationship_brief)
# {"allies": ["gemini"], "rivals": ["codex"], "influences": ["grok"]}

# Get opponent briefing for debate prep
briefing = synthesizer.get_opponent_briefing("anthropic-api", opponent="codex")
# Returns strategic information about how claude typically debates codex
```

### Arena Integration

The Grounded Personas system is integrated into Arena for automatic tracking:

```python
from aragora.debate.orchestrator import Arena

arena = Arena(
    environment=env,
    agents=agents,
    # Grounded Personas v2 integrations
    calibration_tracker=CalibrationTracker("calibration.db"),
    relationship_tracker=RelationshipTracker("relationships.db"),
    moment_detector=MomentDetector(elo_system=elo),
)

# After each debate, Arena automatically:
# 1. Records positions to PositionLedger
# 2. Updates CalibrationTracker with prediction accuracy
# 3. Updates RelationshipTracker with debate outcomes
# 4. Detects significant moments (upsets, vindications)
# 5. Stores all data for persona synthesis
```

### API Endpoints

The following endpoints expose Grounded Personas data:

| Endpoint | Description |
|----------|-------------|
| `GET /api/agent/{name}/network` | Agent's relationship network |
| `GET /api/agent/{name}/moments?limit=N` | Significant moments |
| `GET /api/agent/{name}/consistency` | Consistency score from FlipDetector |
| `GET /api/consensus/dissents?limit=N` | Dissenting views on topics |

### Benefits

1. **Trust Through Evidence**: Agent claims are backed by verifiable history
2. **Natural Narratives**: Stories emerge from actual performance
3. **Fair Reputation**: Agents earn their standings through debate outcomes
4. **Rich Context**: Debate participants understand each other's tendencies
5. **Accountability**: Position reversals and calibration failures are tracked

---

## Phase 13: Pulse Module & Infrastructure

### Pulse Ingestors
**File:** `aragora/pulse/ingestor.py`

Real-time trending topic ingestion from social media platforms for dynamic debate topic generation.

```python
from aragora.pulse.ingestor import (
    PulseManager,
    TwitterIngestor,
    HackerNewsIngestor,
    RedditIngestor,
    TrendingTopic,
)

# Create ingestors
manager = PulseManager()
manager.add_ingestor("twitter", TwitterIngestor(bearer_token="..."))
manager.add_ingestor("hackernews", HackerNewsIngestor())
manager.add_ingestor("reddit", RedditIngestor(subreddits=["technology", "programming"]))

# Fetch trending topics from all platforms concurrently
topics = await manager.get_trending_topics(
    platforms=["hackernews", "reddit"],
    limit_per_platform=5,
    filters={"skip_toxic": True, "categories": ["tech", "ai"]},
)

# Select best topic for debate
best = manager.select_topic_for_debate(topics)
prompt = best.to_debate_prompt()
# "Debate the implications of trending topic: 'OpenAI announces GPT-5' (hackernews, 521 engagement)"
```

**Platform Support:**
- `TwitterIngestor` - Twitter/X trending topics (requires API key)
- `HackerNewsIngestor` - HN front page stories (free Algolia API)
- `RedditIngestor` - Hot posts from subreddits (public JSON API)

**Production Features:**
- Exponential backoff with configurable retries
- Circuit breaker for failing APIs
- Content toxicity filtering
- Category-based filtering
- Concurrent platform fetching

### CircuitBreaker
**File:** `aragora/pulse/ingestor.py`

Prevents cascade failures when APIs are unavailable.

```python
from aragora.resilience import CircuitBreaker

breaker = CircuitBreaker(
    failure_threshold=3,   # Open after 3 failures
    cooldown_seconds=60.0, # Auto-reset after 60 seconds
)

if breaker.can_proceed():
    try:
        result = await fetch_data()
        breaker.record_success()
    except Exception:
        breaker.record_failure()  # Opens circuit after threshold
```

**States:**
- **CLOSED**: Normal operation
- **OPEN**: Blocking calls, using fallback
- **HALF-OPEN**: Testing recovery after timeout

---

## Phase 14: Exception Hierarchy
**File:** `aragora/exceptions.py`

Structured exception types for precise error handling across the codebase.

```python
from aragora.exceptions import (
    AragoraError,       # Base class for all exceptions
    DebateError,        # Debate-related errors
    AgentError,         # Agent failures
    ValidationError,    # Input validation
    StorageError,       # Database errors
    MemoryError,        # Memory system errors
    ModeError,          # Operational mode errors
    PluginError,        # Plugin execution errors
    AuthError,          # Authentication errors
    NomicError,         # Nomic loop errors
    VerificationError,  # Formal verification errors
)

# Example: Precise error handling
try:
    result = await arena.run_debate(task)
except DebateNotFoundError as e:
    print(f"Debate {e.debate_id} not found")
except AgentTimeoutError as e:
    print(f"Agent {e.agent_name} timed out after {e.timeout_seconds}s")
except AragoraError as e:
    print(f"General error: {e.message}, details: {e.details}")
```

**Exception Categories:**

| Category | Exceptions | Use Case |
|----------|------------|----------|
| **Debate** | `DebateNotFoundError`, `ConsensusError`, `RoundLimitExceededError` | Debate lifecycle errors |
| **Agent** | `AgentNotFoundError`, `AgentTimeoutError`, `APIKeyError`, `RateLimitError` | Agent communication failures |
| **Storage** | `DatabaseError`, `DatabaseConnectionError`, `RecordNotFoundError` | Database operations |
| **Memory** | `MemoryRetrievalError`, `MemoryStorageError`, `EmbeddingError` | Memory system failures |
| **Auth** | `AuthenticationError`, `AuthorizationError`, `TokenExpiredError` | Security failures |
| **Nomic** | `NomicCycleError`, `NomicStateError` | Self-improvement loop errors |
| **Verification** | `Z3NotAvailableError`, `VerificationTimeoutError` | Formal proof errors |

**Exception Details:**
All exceptions include `message` and `details` fields:
```python
raise AgentResponseError("anthropic-api", "Connection refused")
# Error: Agent 'anthropic-api' failed to respond: Connection refused
# Details: {"agent_name": "anthropic-api", "reason": "Connection refused"}
```

---

## Phase 15: Schema Versioning
**File:** `aragora/storage/schema.py`

SQLite schema migration framework for safe database upgrades.

```python
from aragora.storage import SchemaManager, safe_add_column, Migration

# Initialize manager with target version
manager = SchemaManager(conn, "elo", current_version=3)

# Register migrations
manager.register_migration(
    from_version=1,
    to_version=2,
    sql="ALTER TABLE agents ADD COLUMN domain TEXT DEFAULT 'general';",
    description="Add domain tracking",
)

manager.register_migration(
    from_version=2,
    to_version=3,
    function=lambda conn: migrate_to_v3(conn),
    description="Normalize ratings table",
)

# Apply pending migrations (idempotent)
initial_schema = """
    CREATE TABLE agents (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        elo INTEGER DEFAULT 1500
    );
"""
manager.ensure_schema(initial_schema=initial_schema)

# Check version
print(f"Current version: {manager.get_version()}")
```

**Safe Column Addition:**
```python
# Add column only if it doesn't exist (idempotent)
added = safe_add_column(conn, "agents", "calibration_score", "REAL", default="0.5")
if added:
    print("Added calibration_score column")
```

**Schema Validation:**
```python
result = manager.validate_schema(["agents", "matches", "domains"])
# {"valid": True, "missing": [], "extra": ["temp_table"], "version": 3}
```

**Key Features:**
- Per-module version tracking in `_schema_versions` table
- SQL and Python function migrations
- Automatic version bumping on migration success
- Graceful handling of downgrades (skip with warning)
- Thread-safe migration execution

---

## Phase 16: Telemetry & Security (2026-01)

Security-focused telemetry controls for production deployments.

### TelemetryConfig
**File:** `aragora/debate/telemetry_config.py`

Controls observation levels for debug and production modes.

```python
from aragora.debate.telemetry_config import TelemetryConfig

config = TelemetryConfig()
print(f"Current level: {config.level}")  # CONTROLLED by default

# Check what's allowed
if config.should_broadcast():
    # Send telemetry to WebSocket clients
    pass

if config.should_redact():
    # Apply SecurityBarrier to sensitive content
    pass
```

**Telemetry Levels:**
| Level | Value | Description |
|-------|-------|-------------|
| `SILENT` | 0 | No telemetry broadcast |
| `DIAGNOSTIC` | 1 | Internal diagnostics only |
| `CONTROLLED` | 2 | Redacted telemetry (default) |
| `SPECTACLE` | 3 | Full transparency |

### SecurityBarrier
**File:** `aragora/debate/security_barrier.py`

Dynamic secret redaction for telemetry streams.

```python
from aragora.debate.security_barrier import SecurityBarrier

barrier = SecurityBarrier()

# Redact sensitive content
safe_text = barrier.redact("My API key is sk-ant-TESTKEY12345678901234567890")
# Returns: "My API key is [REDACTED]"

# Check if content is sensitive
if barrier.contains_sensitive(user_input):
    print("Warning: Input contains sensitive patterns")

# Add custom patterns
barrier.add_pattern(r"INTERNAL_SECRET_\d+")

# Redact nested dictionaries
safe_data = barrier.redact_dict({
    "response": "Bearer abc123",
    "nested": {"key": "OPENAI_API_KEY=sk-xxx"}
})
```

**Default Patterns:**
- API keys (`api_key`, `token`, `secret`, `password`)
- Bearer tokens
- OpenAI-style keys (`sk-*`)
- Google API keys (`AIza*`)
- Environment variables
- URLs with credentials
- Private keys

### TelemetryVerifier
**File:** `aragora/debate/security_barrier.py`

Runtime capability verification for agents.

```python
from aragora.debate.security_barrier import TelemetryVerifier

verifier = TelemetryVerifier()

# Verify agent has required capabilities
passed, missing = verifier.verify_agent(agent, ["generate", "name", "model"])
if not passed:
    print(f"Agent missing: {missing}")

# Get verification report
report = verifier.get_verification_report()
print(f"Passed: {report['passed']}/{report['total']}")
```

---

## Phase 17: Infrastructure & Maintenance (2026-01)

Automated maintenance and monitoring utilities.

### DatabaseMaintenance
**File:** `aragora/maintenance/db_maintenance.py`

Automated SQLite database upkeep.

```python
from aragora.maintenance.db_maintenance import DatabaseMaintenance

maintenance = DatabaseMaintenance()

# Checkpoint WAL files on startup
maintenance.checkpoint_all_wal()

# Run VACUUM and ANALYZE
maintenance.optimize_databases()
```

**Features:**
- WAL checkpoint flushing on startup
- VACUUM and ANALYZE operations for query optimization
- Manages 23+ database files across the system

### SimpleObserver
**File:** `aragora/monitoring/simple_observer.py`

Basic agent failure tracking.

```python
from aragora.monitoring.simple_observer import SimpleObserver

observer = SimpleObserver()

# Record events
observer.record_attempt("anthropic-api")
observer.record_completion("anthropic-api")
observer.record_timeout("openai")

# Get metrics
rate = observer.get_failure_rate("anthropic-api")
report = observer.get_report()
```

---

## Phase 18: Social Media Connectors (2026-01)

Publishing debate highlights to social platforms.

### YouTubeUploaderConnector
**File:** `aragora/connectors/youtube_uploader.py`

OAuth 2.0 video uploads to YouTube.

```python
from aragora.connectors.youtube_uploader import YouTubeUploaderConnector

uploader = YouTubeUploaderConnector(credentials_path="youtube_creds.json")

metadata = YouTubeVideoMetadata(
    title="AI Debate: Climate Policy",
    description="Multi-agent debate on carbon pricing",
    tags=["AI", "debate", "climate"],
    category="Science & Technology"
)

video_id = await uploader.upload(
    video_path="debate_recording.mp4",
    metadata=metadata
)
```

### TwitterPosterConnector
**File:** `aragora/connectors/twitter_poster.py`

OAuth 1.0a posting to Twitter/X with thread support.

```python
from aragora.connectors.twitter_poster import TwitterPosterConnector

poster = TwitterPosterConnector(
    api_key="...",
    api_secret="...",
    access_token="...",
    access_secret="..."
)

# Post single tweet
result = await poster.post("Key insight from today's debate: ...")

# Post thread (up to 25 tweets)
thread_result = await poster.post_thread([
    "Thread: AI debate highlights 🧵",
    "1/ Agent A argued for progressive carbon tax...",
    "2/ Agent B countered with economic concerns...",
    "3/ Final consensus: Phased implementation wins"
])
```

---

## Phase 19: Agent Utilities (2026-01)

Shared utilities for agent implementations.

### QuotaFallbackMixin
**File:** `aragora/agents/fallback.py`

Automatic fallback when provider quota exceeded.

```python
from aragora.agents.api_agents.base import APIAgent
from aragora.agents.fallback import QuotaFallbackMixin

class MyAgent(QuotaFallbackMixin, APIAgent):
    async def generate(self, prompt, context=None):
        try:
            return await self._primary_generate(prompt, context)
        except Exception as e:
            status_code = getattr(e, "status", 0)
            if self.is_quota_error(status_code, str(e)):
                return await self.fallback_generate(prompt, context, status_code)
            raise
```

**Quota Detection:**
- HTTP 429 (Too Many Requests)
- HTTP 403 with quota keywords
- Provider-specific error messages

### StreamingMixin
**File:** `aragora/agents/streaming.py`

Shared SSE parsing logic for API agents.

```python
from aragora.agents.api_agents.base import APIAgent
from aragora.agents.streaming import StreamingMixin

class MyStreamingAgent(APIAgent, StreamingMixin):
    async def stream_generate(self, response):
        async for chunk in self.parse_sse_stream(response, format_type="openai"):
            yield chunk
```

**Features:**
- OpenAI, Anthropic, Grok, OpenRouter format support
- DoS protection (1MB buffer limit)
- Automatic format detection

---

## Phase 20: Demo Fixtures & Search (2026-01)

Search functionality that works independently of live debates.

### Demo Consensus Fixtures
**File:** `aragora/fixtures/__init__.py`

Pre-populated consensus data for search functionality.

```python
from aragora.fixtures import load_demo_consensus, ensure_demo_data

# Load demo data into a ConsensusMemory instance
from aragora.memory.consensus import ConsensusMemory
memory = ConsensusMemory()
seeded = load_demo_consensus(memory)
print(f"Seeded {seeded} demo consensus records")

# Auto-seed on server startup (called by unified_server.py)
ensure_demo_data()  # Safe to call multiple times
```

**Demo Topics (in `demo_consensus.json`):**
- Live Debate Viewer with Shareable Permalinks
- Airlock Resilience Layer for Agent Failures
- Public Debate Archive with Stabilized IDs
- Stream Package Refactoring
- Multi-Agent Debate Consensus Mechanisms

**Key Features:**
- Auto-seeds on server startup if database is empty
- Idempotent - won't re-seed if data already exists
- Maps JSON strength values to ConsensusStrength enum
- Supports "strong", "medium"/"moderate", and "weak" strengths

### Seed Demo Endpoint
**File:** `aragora/server/handlers/consensus.py`

Manual trigger for demo data seeding.

```bash
# Seed demo data
curl https://api.aragora.ai/api/consensus/seed-demo

# Response:
{
  "success": true,
  "seeded": 5,
  "total_before": 0,
  "total_after": 5,
  "db_path": "consensus_memory.db",
  "message": "Seeded 5 demo consensus records"
}
```

### Package Data Configuration
**File:** `pyproject.toml`

JSON fixtures are included in package distribution:

```toml
[tool.setuptools.package-data]
"aragora.fixtures" = ["*.json"]
```

---

## Phase 21: Feature Integration (2026-01-09)

Comprehensive integration of stranded features via protocol flags and ArenaConfig options.

### PerformanceMonitor Integration
**Files:** `aragora/debate/orchestrator.py`, `aragora/debate/autonomic_executor.py`

Agent call telemetry for generate/critique/vote operations.

```python
from aragora import Arena, ArenaConfig

# Enable via ArenaConfig
config = ArenaConfig(
    enable_performance_monitor=True,  # Auto-create PerformanceMonitor
)
arena = Arena.from_config(config, env, agents, protocol)

# Or inject your own
from aragora.agents.performance_monitor import AgentPerformanceMonitor
monitor = AgentPerformanceMonitor()
config = ArenaConfig(performance_monitor=monitor)
```

**Tracked Metrics:**
- Call duration per agent/operation
- Success/failure rates
- Response lengths
- Phase and round context

### CalibrationTracker Integration
**Files:** `aragora/debate/protocol.py`, `aragora/debate/phases/feedback_phase.py`

Record agent prediction accuracy for calibration curves.

```python
from aragora import DebateProtocol

protocol = DebateProtocol(
    enable_calibration=True,  # Enable calibration tracking
)
```

**Key Features:**
- Records vote confidence levels
- Tracks prediction vs outcome accuracy
- Auto-initializes CalibrationTracker when flag is True
- Data available via `calibration_tracker.get_calibration_summary()`

### AirlockProxy Integration
**File:** `aragora/debate/orchestrator.py`

Wrap agents with timeout protection and fallback responses.

```python
from aragora import ArenaConfig

config = ArenaConfig(
    use_airlock=True,  # Enable airlock protection
    airlock_config=None,  # Optional AirlockConfig for customization
)
```

### AgentTelemetry Integration
**File:** `aragora/debate/autonomic_executor.py`

Prometheus and Blackbox telemetry emission.

```python
from aragora import ArenaConfig

config = ArenaConfig(
    enable_telemetry=True,  # Enable Prometheus/Blackbox emission
)
```

**Collectors:**
- Prometheus metrics
- ImmuneSystem health
- Blackbox event logging

### RhetoricalObserver Integration
**Files:** `aragora/debate/protocol.py`, `aragora/debate/phases/debate_rounds.py`

Passive commentary on debate dynamics for audience engagement.

```python
from aragora import DebateProtocol

protocol = DebateProtocol(
    enable_rhetorical_observer=True,  # Enable pattern detection
)
```

**Detected Patterns:**
- Concession, Rebuttal, Synthesis
- Appeal to authority/evidence
- Technical depth, Rhetorical questions
- Analogies, Qualifications

**Events Emitted:**
- `RHETORICAL_OBSERVATION` via WebSocket

### Trickster Integration
**File:** `aragora/debate/protocol.py`

Hollow consensus detection - challenges convergence lacking evidence quality.

```python
from aragora import DebateProtocol

protocol = DebateProtocol(
    enable_trickster=True,  # Enable hollow consensus detection
    trickster_sensitivity=0.7,  # Threshold for challenges
)
```

### Genesis Evolution Integration
**Files:** `aragora/debate/orchestrator.py`, `aragora/debate/phases/feedback_phase.py`

Agent genome evolution based on debate performance.

```python
from aragora import ArenaConfig
from aragora.genesis.ledger import PopulationManager

manager = PopulationManager()
config = ArenaConfig(
    population_manager=manager,
    auto_evolve=True,  # Trigger evolution after high-quality debates
    breeding_threshold=0.8,  # Min confidence to trigger
)
```

### Graph Debates API
**File:** `aragora/server/handlers/debates/graph_debates.py`

Graph-structured debates with automatic branching.

```bash
# Run a graph debate
curl -X POST https://api.aragora.ai/api/debates/graph \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Design a distributed caching system",
    "agents": ["anthropic-api", "openai-api"],
    "max_rounds": 5,
    "branch_policy": {
      "min_disagreement": 0.7,
      "max_branches": 3,
      "auto_merge": true,
      "merge_strategy": "synthesis"
    }
  }'
```

**Response:**
```json
{
  "debate_id": "uuid",
  "graph": {...},
  "branches": [...],
  "merge_results": [...],
  "node_count": 15,
  "branch_count": 2
}
```

### Matrix Debates API
**File:** `aragora/server/handlers/debates/matrix_debates.py`

Parallel scenario exploration with comparative analysis.

```bash
# Run parallel scenarios
curl -X POST https://api.aragora.ai/api/debates/matrix \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Design a rate limiter",
    "agents": ["anthropic-api", "openai-api"],
    "scenarios": [
      {"name": "High throughput", "parameters": {"rps": 10000}},
      {"name": "Low latency", "parameters": {"latency_ms": 10}},
      {"name": "Baseline", "is_baseline": true}
    ],
    "max_rounds": 3
  }'
```

**Response:**
```json
{
  "matrix_id": "uuid",
  "scenario_count": 3,
  "results": [...],
  "universal_conclusions": [...],
  "conditional_conclusions": [...],
  "comparison_matrix": {...}
}
```

---

## Enterprise Features

### Cross-Workspace Coordination
**File:** `aragora/coordination/cross_workspace.py`

Enables workflows that span multiple workspaces with proper isolation and permission management.

```python
from aragora.coordination import (
    CrossWorkspaceCoordinator,
    FederatedWorkspace,
    FederationPolicy,
    DataSharingConsent,
    SharingScope,
)

# Create coordinator
coordinator = CrossWorkspaceCoordinator()

# Define federation policy
policy = FederationPolicy(
    allow_data_sharing=True,
    require_explicit_consent=True,
    allowed_scopes=[SharingScope.DEBATE_RESULTS, SharingScope.AGENT_METRICS],
)

# Register federated workspace
workspace = FederatedWorkspace(
    workspace_id="partner-org",
    policy=policy,
)
coordinator.register_workspace(workspace)

# Execute cross-workspace request
result = await coordinator.execute(
    CrossWorkspaceRequest(
        source_workspace="my-org",
        target_workspace="partner-org",
        operation="run_debate",
        payload={"task": "Review architecture proposal"},
    )
)
```

**Key Features:**
- Cross-workspace data sharing with explicit consent
- Federated agent execution across organizations
- Multi-workspace workflow orchestration
- Secure inter-workspace communication
- Permission delegation and scoping

### Agent Routing & Selection
**File:** `aragora/routing/`

Intelligent agent selection and load balancing for optimal task assignment.

See [AGENT_SELECTION.md](../debate/AGENT_SELECTION.md) for routing strategies.

---

## Phase 22: Inbox Ops & Codebase Analysis (2026-01-22)

### DependencyScanner
**File:** `aragora/analysis/codebase/scanner.py`

Scans dependency lock files and queries vulnerability databases (NVD, OSV,
GitHub) for CVEs with remediation guidance.

```python
from aragora.analysis.codebase import DependencyScanner

scanner = DependencyScanner()
result = await scanner.scan_repository("/path/to/repo")
print(result.critical_count, result.high_count)
```

### CVEClient
**File:** `aragora/analysis/codebase/cve_client.py`

Async CVE lookup client with caching, circuit breaker, and multi-source
fallback (NVD -> OSV -> GitHub advisory).

```python
from aragora.analysis.codebase import CVEClient

client = CVEClient()
finding = await client.get_cve("CVE-2023-12345")
```

### Code Metrics Analysis
**File:** `aragora/analysis/codebase/metrics.py`

Computes code complexity metrics, hotspots, and duplication signals for
repository health dashboards.

```python
from aragora.analysis.codebase import CodeMetricsAnalyzer

analyzer = CodeMetricsAnalyzer()
report = analyzer.analyze_repository("/path/to/repo", scan_id="metrics_001")
```

### Dependency Intelligence
**File:** `aragora/server/handlers/dependency_analysis.py`

API endpoints for dependency graph analysis, SBOM export, CVE scanning, and
license compatibility checks.

```python
import httpx

async def run_dependency_analysis():
    async with httpx.AsyncClient(base_url="http://localhost:8080") as client:
        await client.post("/api/v1/codebase/analyze-dependencies", json={
            "repo_path": "/path/to/repo",
            "include_dev": True,
        })
```

### SecretsScanner
**File:** `aragora/analysis/codebase/secrets_scanner.py`

Detects hardcoded secrets and credentials during codebase scans.

### SAST Scanner
**File:** `aragora/analysis/codebase/sast_scanner.py`

Semgrep-backed static analysis with OWASP/CWE mappings and confidence scoring.

### Security Event Debates
**File:** `aragora/events/security_events.py`

Emits security events from scans and can auto-trigger remediation debates for
critical findings.

### Threat Intelligence Service
**File:** `aragora/services/threat_intelligence.py`, `aragora/server/handlers/threat_intel.py`

Threat intel lookups for URLs, IPs, hashes, and email content using external
feeds (VirusTotal, AbuseIPDB, PhishTank).

### Code Intelligence & Call Graph
**File:** `aragora/analysis/code_intelligence.py`, `aragora/analysis/call_graph.py`

Tree-sitter based symbol extraction and call graph construction for deeper code
understanding.

### Quick Security Scan
**File:** `aragora/server/handlers/codebase/quick_scan.py`

One-click security scan endpoints powering the UI wizard experience.

### SenderHistoryService
**File:** `aragora/services/sender_history.py`

Tracks sender reputation, response patterns, and engagement scores to inform
email prioritization decisions.

```python
from aragora.services.sender_history import SenderHistoryService

service = SenderHistoryService(db_path="sender_history.db")
await service.initialize()
```

### FollowUpTracker
**File:** `aragora/services/followup_tracker.py`

Tracks sent emails awaiting replies and surfaces overdue follow-ups.

```python
from aragora.services.followup_tracker import FollowUpTracker

tracker = FollowUpTracker()
pending = await tracker.get_pending_followups()
```

### SnoozeRecommender
**File:** `aragora/services/snooze_recommender.py`

Suggests optimal snooze times based on sender history, work schedule, and
optional calendar context.

### Spam Classifier
**File:** `aragora/services/spam_classifier.py`

ML-enhanced spam and phishing classification with online learning from user
feedback.

```python
from aragora.services.snooze_recommender import SnoozeRecommender

recommender = SnoozeRecommender()
```

### Shared Inbox & Routing Rules
**File:** `aragora/server/handlers/shared_inbox.py`

Collaborative inbox management with message assignment, status tracking, and
routing rules.

### Audit Sessions
**File:** `aragora/server/handlers/features/audit_sessions.py`

Document audit session lifecycle management, SSE event streaming, and report
export for compliance workflows.

### Gmail Labels, Threads, and Drafts
**File:** `aragora/server/handlers/features/gmail_labels.py`, `aragora/server/handlers/features/gmail_threads.py`

Advanced Gmail operations for labels, threads, filters, drafts, and message
actions.

### Outlook/M365 Email Integration
**File:** `aragora/server/handlers/features/outlook.py`

OAuth-based Outlook integration with folder, message, and search APIs.

### Knowledge Chat Bridge
**File:** `aragora/services/knowledge_chat_bridge.py`

Chat-to-knowledge context search and knowledge injection across channels.

### Audit-to-GitHub Bridge
**File:** `aragora/server/handlers/github/audit_bridge.py`

Sync audit findings into GitHub issues and PRs for remediation workflows.

### Cost Visibility Dashboard
**File:** `aragora/server/handlers/costs.py`

Spend tracking, budget alerts, and provider/feature breakdowns with a dedicated
UI dashboard under `/costs`.

### Accounting Dashboard (QuickBooks)
**File:** `aragora/server/handlers/accounting.py`

QuickBooks Online integration for receivables, customer insights, and financial
reporting under `/accounting`.

### Plaid Bank Connector
**File:** `aragora/connectors/accounting/plaid.py`

Plaid Link + transaction sync for bank feeds, with categorization and anomaly
detection hooks for accounting workflows.

### Gusto Payroll Connector
**File:** `aragora/connectors/accounting/gusto.py`

Payroll sync, employee roster import, and journal entry generation to support
finance workflows.

---

## Phase 23: Coding & Review (2026-01-22)

### GitHub PR Review API
**File:** `aragora/server/handlers/github/pr_review.py`

Automated pull request review workflows over the API. Supports triggering
review runs, fetching PR details, and submitting review verdicts.

```python
import httpx

async def trigger_pr_review():
    async with httpx.AsyncClient(base_url="http://localhost:8080") as client:
        response = await client.post("/api/v1/github/pr/review", json={
            "repository": "owner/repo",
            "pr_number": 42,
            "review_type": "comprehensive",
        })
        print(response.json())
```

### Code Review API
**File:** `aragora/server/handlers/code_review.py`

Multi-agent code review endpoints for snippets, diffs, and PR URLs with
optional security-only scans. Results are stored in-memory by default.

```python
import httpx

async def review_diff():
    async with httpx.AsyncClient(base_url="http://localhost:8080") as client:
        response = await client.post("/api/v1/code-review/diff", json={
            "diff": "diff --git a/app.py b/app.py\\n+print('hello')\\n",
            "review_types": ["security", "maintainability"],
        })
        print(response.json())
```

### Feature Development Agent
**File:** `aragora/agents/feature_agent.py`

End-to-end feature implementation with codebase understanding, debate-driven
design, TDD scaffolding, and approval gates.

### Approval Workflow
**File:** `aragora/nomic/approval.py`

Multi-level approval gates for code changes (info, review, critical) with
timeouts and structured votes.

### Nomic TDD Test Generator
**File:** `aragora/nomic/test_generator.py`

Generates test suites from function specs and debates coverage expectations.

### Test Generator
**File:** `aragora/coding/test_generator.py`

AST-based test generation utility for extracting functions and producing test
cases across multiple frameworks.

```python
from aragora.coding import TestFramework, generate_tests_for_function

cases, test_code = generate_tests_for_function(
    "def add(a, b): return a + b",
    function_name="add",
    framework=TestFramework.PYTEST,
)
print(test_code)
```

---

## API Reference

See [API_REFERENCE.md](../api/API_REFERENCE.md) for complete HTTP and WebSocket API documentation.
