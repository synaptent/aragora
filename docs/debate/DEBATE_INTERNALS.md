# Debate Engine Internals

The `aragora/debate/` module contains 114 Python files implementing the core debate orchestration system. This document covers the internal architecture.

## Module Structure

```
aragora/debate/
├── orchestrator.py       # Arena class - main entry point
├── service.py            # DebateService abstraction layer
├── consensus.py          # Consensus detection and proofs
├── convergence.py        # Semantic similarity detection
├── team_selector.py      # Agent team selection (ELO + calibration)
├── memory_manager.py     # Memory coordination
├── prompt_builder.py     # Prompt construction
├── phases/               # Phase implementations (20+ files)
│   ├── base.py           # Base phase class
│   ├── opening.py        # Opening statements
│   ├── argumentation.py  # Main debate rounds
│   ├── rebuttal.py       # Rebuttal phase
│   ├── synthesis.py      # Synthesis phase
│   └── voting.py         # Voting phase
├── similarity/           # Semantic similarity
├── cache/                # Response caching
├── trickster.py          # Hollow consensus detection
├── rhetorical_observer.py # Rhetoric pattern tracking
├── chaos_theater.py      # Chaos engineering
├── evidence_quality.py   # Evidence scoring
├── cross_proposal_analyzer.py # Cross-proposal analysis
├── context_delegation.py # Context delegation
└── ...
```

## Core Components

### Arena (orchestrator.py)

The `Arena` class is the main entry point for running debates.

```python
from aragora.debate import Arena, Environment, DebateProtocol

# Create arena
arena = Arena(
    environment=Environment(task="Should we use microservices?"),
    agents=[agent1, agent2, agent3],
    protocol=DebateProtocol(
        rounds=3,
        consensus="supermajority",
        enable_trickster=True,
        enable_rhetorical_observer=True,
    ),
    config=ArenaConfig(
        use_airlock=True,
        enable_breakpoints=True,
    )
)

# Run debate
result = await arena.run()
```

### DebateService (service.py)

Singleton service providing a simplified interface:

```python
from aragora.debate.service import DebateService

service = DebateService.get_instance()

# Create and run debate
debate_id = await service.create_debate(
    topic="AI regulation",
    agents=["gpt-4", "claude-3", "gemini"],
    rounds=3
)

# Get status
status = await service.get_status(debate_id)

# Subscribe to events
async for event in service.stream_events(debate_id):
    print(event)
```

### Request-Scoped Batch Loaders

Debate execution uses request-scoped DataLoaders to prevent N+1 query patterns
when fetching agent stats and ELO ratings.

```python
from aragora.debate.batch_loaders import get_debate_loaders

loaders = get_debate_loaders()
ratings = await loaders.elo.load_many(["anthropic-api", "openai-api"])
stats = await loaders.stats.load_many(["anthropic-api", "openai-api"])
```

### Agent Failure Tracking

Debate execution records per-agent failures (timeouts, empty responses, and
exceptions). These are stored in `DebateContext.agent_failures` and persisted
to the final `DebateResult.agent_failures`.

When streaming events, failure summaries can surface in the `consensus` event
(`status`, `agent_failures`) and as individual `agent_error` events.

## Phase System

Debates progress through configurable phases.

### Phase Interface

```python
from aragora.debate.phases.base import BasePhase, PhaseResult

class CustomPhase(BasePhase):
    """Custom debate phase."""

    name = "custom"
    order = 5  # Execution order

    async def execute(self, context: PhaseContext) -> PhaseResult:
        # Phase logic
        messages = await self.collect_responses(context)

        return PhaseResult(
            phase=self.name,
            messages=messages,
            metadata={"custom_data": ...}
        )
```

### Built-in Phases

| Phase | Order | Description |
|-------|-------|-------------|
| `opening` | 1 | Opening statements |
| `argumentation` | 2 | Main debate rounds |
| `rebuttal` | 3 | Counterarguments |
| `cross_examination` | 4 | Agent questions |
| `synthesis` | 5 | Find common ground |
| `voting` | 6 | Agent votes |
| `verdict` | 7 | Final verdict |

### Phase Flow

```
Opening → Argumentation (rounds) → Rebuttal → Synthesis → Voting → Verdict
              ↑                        ↓
              └──────── Repeat ────────┘
```

## Debate Interventions

Aragora supports mid‑debate controls for pausing, resuming, injecting user input,
and adjusting consensus parameters. Interventions are audited and can be
consumed by orchestration layers to alter the next round.

**REST Endpoints:**
- `POST /api/debates/{debate_id}/intervention/pause`
- `POST /api/debates/{debate_id}/intervention/resume`
- `POST /api/debates/{debate_id}/intervention/inject`
- `POST /api/debates/{debate_id}/intervention/weights`
- `POST /api/debates/{debate_id}/intervention/threshold`
- `GET  /api/debates/{debate_id}/intervention/state`
- `GET  /api/debates/{debate_id}/intervention/log`

**Note:** The default handler stores intervention state in memory for simplicity.
Production deployments should back this with Redis or a database to preserve
state across restarts and allow horizontal scaling.

## Execution Safety Gate

High-impact automation after debates (execution bridge, plan execution, PR creation)
is protected by an execution safety gate that evaluates:

- signed receipt verification
- provider/model-family diversity
- context taint signals from untrusted prompt context
- high-severity dissent and correlated-failure risk

See [Execution Safety Gate](./EXECUTION_SAFETY_GATE.md) for policy knobs, defaults,
reason codes, and telemetry/dashboard queries.

## Agent Channel Integration

When enabled in the debate protocol, agents can send peer‑to‑peer messages
alongside the standard debate loop. This is useful for proposals, critiques,
and direct questions between agents.

**Integration helper:** `aragora/debate/channel_integration.py`  
**Protocol flags:** `enable_agent_channels` (default: true), `agent_channel_max_history` (default: 100)

```python
from aragora.debate.channel_integration import ChannelIntegration

integration = ChannelIntegration(debate_id, agents, protocol)
await integration.setup()
context = integration.get_context_for_prompt(limit=5)
```

## Declarative Hooks

Aragora supports YAML-defined hooks that attach automation to debate and audit
events. Hooks are loaded via `HookConfigLoader` and applied to the
`HookManager` used by the arena runtime.

See [Workflow Guide](../workflow/WORKFLOWS.md) for lifecycle orchestration patterns and built-in actions.

## Hook Tracking (GUPP Recovery)

When enabled in the debate protocol, the orchestrator records hook events and
creates a **pending bead** at debate start. This supports GUPP‑style recovery
(Guaranteed Unconditional Processing Priority) so incomplete debates can be
recovered after crashes.

**Protocol Flags:**
- `enable_bead_tracking` – persist final decisions as beads
- `enable_hook_tracking` – record hook queues and create pending beads
- `hook_max_recovery_age_hours` – cap recovery window
**Defaults:** `enable_bead_tracking=true`, `enable_hook_tracking=true`

**Storage:** Hook queues and beads are stored in the `.beads/` directory when
the Nomic bead store is available.

## Checkpoint Bridge

`CheckpointBridge` unifies molecule tracking and checkpoint persistence. It
captures molecule progress, message history, and optional channel history in a
single recovery structure.

**Location:** `aragora/debate/checkpoint_bridge.py`

```python
from aragora.debate.checkpoint_bridge import CheckpointBridge

bridge = CheckpointBridge(molecule_orchestrator, checkpoint_manager)
state = await bridge.save_checkpoint(
    debate_id="deb-123",
    current_round=2,
    phase="voting",
)
```

## Propulsion Engine (Gastown Pattern)

Aragora includes a propulsion engine for push‑based work assignment between
stages. Propulsion handlers register for event types and the engine retries
failed tasks with backoff.

```python
from aragora.debate.propulsion import propulsion_handler, PropulsionPayload

@propulsion_handler("proposals_ready")
async def on_proposals(payload: PropulsionPayload) -> None:
    ...
```

## Consensus Detection

The `consensus.py` module detects agreement and generates cryptographic proofs.

### Consensus Types

```python
from aragora.debate.consensus import ConsensusType

ConsensusType.UNANIMOUS      # 100% agreement
ConsensusType.SUPERMAJORITY  # 66%+ agreement
ConsensusType.MAJORITY       # 50%+ agreement
ConsensusType.PLURALITY      # Most votes wins
ConsensusType.NO_CONSENSUS   # No clear winner
```

### Consensus Proofs

```python
from aragora.debate.consensus import ConsensusProof

proof = ConsensusProof(
    debate_id="debate_123",
    consensus_type=ConsensusType.SUPERMAJORITY,
    winning_position="Position A",
    vote_counts={"Position A": 5, "Position B": 2},
    confidence=0.85,
    signatures=agent_signatures,
    timestamp=datetime.utcnow(),
)

# Verify proof
is_valid = proof.verify()

# Export for compliance
proof_json = proof.to_json()
```

## Convergence Detection

The `convergence.py` module detects semantic similarity between positions.

```python
from aragora.debate.convergence import ConvergenceDetector

detector = ConvergenceDetector(
    similarity_threshold=0.85,
    min_rounds_before_check=2,
)

# Check for convergence
result = detector.check_convergence(
    positions=[agent1_position, agent2_position, agent3_position]
)

if result.converged:
    print(f"Convergence detected: {result.common_ground}")
```

## Trickster (Hollow Consensus Detection)

The `trickster.py` module detects and challenges hollow consensus.

### Architecture

```
Monitor → Detect → Intervene
   │         │         │
   │         │         └── Challenge shallow agreement
   │         └── Identify hollow patterns
   └── Track voting patterns
```

### Usage

```python
from aragora.debate.trickster import Trickster, TricksterConfig

trickster = Trickster(
    config=TricksterConfig(
        detection_threshold=0.7,
        challenge_probability=0.5,
        min_rounds_before_challenge=2,
    )
)

# Monitor round
trickster.observe_round(round_data)

# Check for hollow consensus
if trickster.detect_hollow_consensus():
    challenge = trickster.generate_challenge()
    # Inject challenge into next round
```

### Detection Patterns

- **Quick unanimous agreement** - Suspiciously fast consensus
- **Shallow reasoning** - Agreement without substance
- **Echo chamber** - Agents repeating each other
- **Groupthink** - No dissenting opinions

## Rhetorical Observer

The `rhetorical_observer.py` module tracks rhetorical patterns.

```python
from aragora.debate.rhetorical_observer import (
    RhetoricalObserver,
    RhetoricalPattern,
)

observer = RhetoricalObserver()

# Analyze message
patterns = observer.analyze(message)
# [RhetoricalPattern.CONCESSION, RhetoricalPattern.REBUTTAL]

# Track over debate
observer.observe_debate(debate_messages)
report = observer.generate_report()
```

### Pattern Types

| Pattern | Description |
|---------|-------------|
| `CONCESSION` | Acknowledging opponent's point |
| `REBUTTAL` | Directly countering argument |
| `SYNTHESIS` | Combining multiple viewpoints |
| `APPEAL_TO_AUTHORITY` | Citing expert sources |
| `APPEAL_TO_EVIDENCE` | Using data/facts |
| `STRAWMAN` | Misrepresenting opponent |
| `AD_HOMINEM` | Attacking character |
| `EMOTIONAL_APPEAL` | Using emotion over logic |

## Evidence Quality

The `evidence_quality.py` module scores evidence strength.

```python
from aragora.debate.evidence_quality import (
    EvidenceScorer,
    EvidenceQuality,
)

scorer = EvidenceScorer()

score = scorer.score(evidence)
print(score.quality)    # HIGH, MEDIUM, LOW
print(score.factors)    # Contributing factors
print(score.confidence) # 0.0 - 1.0
```

### Scoring Factors

- **Source reliability** - Trustworthiness of source
- **Recency** - How current is the evidence
- **Relevance** - How relevant to the claim
- **Corroboration** - Supported by other evidence
- **Specificity** - Concrete vs vague

## Chaos Theater

The `chaos_theater.py` module injects controlled chaos for testing.

```python
from aragora.debate.chaos_theater import ChaosTheater

theater = ChaosTheater(
    failure_rate=0.1,       # 10% chance of failure
    latency_multiplier=2.0, # Double latencies
    enabled=True,
)

# Wrap agent call
result = await theater.wrap(agent.respond)(prompt)
```

### Chaos Modes

- **Latency injection** - Add random delays
- **Failure injection** - Random failures
- **Timeout injection** - Simulate timeouts
- **Corrupt response** - Return malformed data

## Team Selection

The `team_selector.py` module selects agent teams using ELO and calibration.

```python
from aragora.debate.team_selector import TeamSelector

selector = TeamSelector(
    calibration_weight=0.3,
    diversity_weight=0.2,
    elo_weight=0.5,
)

# Select team
team = selector.select(
    available_agents=all_agents,
    team_size=4,
    topic="technical architecture",
)
```

## Memory Manager

The `memory_manager.py` module coordinates agent memories.

```python
from aragora.debate.memory_manager import MemoryManager

manager = MemoryManager(arena)

# Store debate memory
await manager.store_round_memory(round_data)

# Recall relevant context
context = await manager.recall_context(
    agent=agent,
    topic=current_topic,
    limit=5,
)
```

## Prompt Builder

The `prompt_builder.py` module constructs prompts for agents.

```python
from aragora.debate.prompt_builder import PromptBuilder

builder = PromptBuilder(config)

prompt = builder.build(
    phase="argumentation",
    agent=agent,
    context=debate_context,
    history=message_history,
)
```

## Events

The debate engine emits events via WebSocket:

| Event | Description |
|-------|-------------|
| `debate_start` | Debate begins |
| `phase_start` | Phase begins |
| `phase_end` | Phase ends |
| `agent_message` | Agent response |
| `vote` | Agent vote |
| `consensus` | Consensus detected |
| `trickster_alert` | Hollow consensus detected |
| `rhetorical_pattern` | Pattern detected |
| `debate_end` | Debate ends |

## See Also

- [DEBATE_PHASES.md](DEBATE_PHASES.md) - Phase system details
- [TRICKSTER.md](TRICKSTER.md) - Hollow consensus detection
- [CONSENSUS.md](../algorithms/CONSENSUS.md) - Consensus algorithms
- [CONVERGENCE.md](../algorithms/CONVERGENCE.md) - Convergence detection
