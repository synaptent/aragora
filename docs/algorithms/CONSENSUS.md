# Consensus Mechanism

This document describes how Aragora determines consensus in multi-agent debates.

## Overview

The consensus mechanism generates **auditable proof artifacts** from debates. These artifacts capture:
- The final agreed-upon claim
- Which agents supported or dissented
- Evidence chains with provenance
- Unresolved tensions and tradeoffs

## Vote Types

Agents can cast four types of votes on consensus:

| Vote Type | Description |
|-----------|-------------|
| `AGREE` | Full agreement with the final claim |
| `DISAGREE` | Explicit rejection of the final claim |
| `ABSTAIN` | No position taken |
| `CONDITIONAL` | Agreement with reservations/conditions |

## Consensus Determination

### Agreement Ratio

```
agreement_ratio = supporting_agents / (supporting_agents + dissenting_agents)
```

Supporting agents include both `AGREE` and `CONDITIONAL` votes.

### Strong Consensus

A debate achieves **strong consensus** when ALL conditions are met:

1. `consensus_reached = true`
2. `agreement_ratio > 80%`
3. `confidence > 0.7`

### Confidence Calculation

Confidence is computed from vote weights:

```python
confidence = weighted_average(vote.confidence for vote in votes)
```

Each agent's vote includes a confidence score (0-1) reflecting their certainty.

## Security Hardening for Consensus

Consensus is a reliability amplifier, not a standalone safety guarantee.

Recommended hardening controls for production execution:

1. **Quorum diversity floor**: Require unique provider/operator diversity in the agreeing set, not just vote count.
2. **Dissent-aware blocking**: Block auto-execution when high-severity safety dissents remain unresolved.
3. **Appropriateness policy gate**: Evaluate policy/safety constraints separately from factual agreement.
4. **Collusion detection**: Down-weight coordinated clusters that shift together without strong evidence.
5. **Correlated-failure fallback**: Route to human review when agreement is high but evidence diversity is low.
6. **Receipt verification gate**: Require verified signed receipt before any high-impact downstream action.

## Evidence Chains

Evidence items support or refute claims:

```python
@dataclass
class Evidence:
    evidence_id: str
    source: str          # Agent name, tool output, or external reference
    content: str
    evidence_type: str   # "argument", "data", "citation", "tool_output"
    supports_claim: bool # True=support, False=refute
    strength: float      # 0-1
```

### Net Evidence Strength

Claims have a computed net evidence strength:

```python
net_strength = (supporting_strength - refuting_strength) / total_strength
```

Range: -1 (fully refuted) to +1 (fully supported)

## Dissent Tracking

Dissenting views are explicitly recorded:

| Dissent Type | Description |
|--------------|-------------|
| `full` | Complete rejection of the claim |
| `partial` | Agreement with major reservations |
| `procedural` | Objection to process, not content |

Each dissent includes:
- Severity score (0-1)
- List of reasons
- Optional alternative view
- Suggested resolution

## Unresolved Tensions

When debates identify tradeoffs that cannot be fully resolved, they are recorded as tensions:

```python
@dataclass
class UnresolvedTension:
    description: str          # What the tension is about
    agents_involved: list     # Who disagreed
    options: list             # Competing approaches
    impact: str               # What depends on resolving this
    suggested_followup: str   # How to resolve it later
```

## ConsensusProof Structure

The final artifact contains:

```python
ConsensusProof:
    proof_id: str           # Unique identifier
    debate_id: str          # Link to source debate
    task: str               # Original question/task

    # Final consensus
    final_claim: str        # The agreed-upon answer
    confidence: float       # Overall confidence (0-1)
    consensus_reached: bool # Whether consensus was achieved

    # Voting record
    votes: list[ConsensusVote]
    supporting_agents: list[str]
    dissenting_agents: list[str]

    # Detailed analysis
    claims: list[Claim]
    dissents: list[DissentRecord]
    unresolved_tensions: list[UnresolvedTension]
    evidence_chain: list[Evidence]

    # Integrity
    checksum: str  # SHA-256 hash of key fields
```

### Checksum Verification

The checksum ensures proof integrity:

```python
checksum = sha256(json.dumps({
    "final_claim": final_claim,
    "votes": votes,
    "claims": claims
}, sort_keys=True))[:16]
```

## Blind Spot Detection

The system identifies potential blind spots:

1. **High-severity dissents** (severity >= 0.7) with alternative views
2. **Unresolved tensions** between competing approaches
3. **Low agreement ratio** (< 60%) suggesting multiple valid perspectives

## Risk Correlation

Claims are grouped by agreement level:

| Category | Criteria | Interpretation |
|----------|----------|----------------|
| `unanimous` | >=90% support | Very high confidence |
| `majority` | 60-90% support | Good confidence |
| `contested` | <60% support | Requires further analysis |

## Building Consensus from Debate Results

The `ConsensusBuilder` extracts structured data from debates:

1. **Extract claims**: Each proposal becomes a claim
2. **Attach evidence**: Messages and critiques become evidence
3. **Infer votes**: Final critique severity determines vote type
   - High severity (>0.6) → DISAGREE
   - Low severity → AGREE or CONDITIONAL
4. **Record tensions**: High-severity critiques (>0.7) create tension records

## Output Formats

ConsensusProof can be exported as:

- **JSON**: Full structured data for API responses
- **Markdown**: Human-readable report with sections for voting, dissent, tensions

## Related Documentation

- [Convergence Detection](./CONVERGENCE.md) - How semantic convergence is detected
- [ELO Calibration](./ELO_CALIBRATION.md) - How agent ratings affect consensus weights
- [Debate Phases](../debate/DEBATE_PHASES.md) - The debate lifecycle
