# ELO Rating and Calibration System

This document describes how Aragora tracks agent skill ratings and calibration quality.

## Overview

The ELO system provides:
- **Global ELO ratings** for overall agent skill
- **Domain-specific ELO** for specialized expertise
- **Calibration scores** measuring prediction accuracy
- **Relationship tracking** for agent dynamics

## ELO Rating Basics

### Standard ELO Formula

Expected score for agent A against agent B:

```
E(A) = 1 / (1 + 10^((R_B - R_A) / 400))
```

New rating after a match:

```
R'_A = R_A + K * (S_A - E(A))
```

Where:
- `R_A`, `R_B`: Current ratings
- `K`: K-factor (default: 32)
- `S_A`: Actual score (1=win, 0.5=draw, 0=loss)
- `E(A)`: Expected score

### Default Values

| Parameter | Value | Description |
|-----------|-------|-------------|
| Initial ELO | 1500 | Starting rating for new agents |
| K-factor | 32 | Rating volatility |
| Min calibration | 5 | Predictions needed for calibration score |

## Recording Matches

```python
from aragora.ranking.elo import EloSystem

elo = EloSystem()

# Modern API: multi-agent with scores
changes = elo.record_match(
    debate_id="debate-001",
    participants=["claude", "gpt4", "gemini"],
    scores={"claude": 0.8, "gpt4": 0.6, "gemini": 0.4},
    domain="security",
    confidence_weight=0.9
)

# Legacy API: two-player
> **Deprecated:** The two-player match API is no longer supported. Use `record_match()` with the full agent list.
changes = elo.record_match(
    winner="claude",
    loser="gpt4",
    draw=False,
    task="code review"
)
```

### Confidence Weighting

Low-confidence debates have reduced ELO impact:

```python
confidence_weight = max(0.1, min(1.0, confidence_weight))
effective_k = K_FACTOR * confidence_weight
```

### Pairwise ELO Changes

For multi-agent matches, ELO changes are computed pairwise:

```python
def calculate_pairwise_elo_changes(participants, scores, ratings):
    changes = {p: 0.0 for p in participants}

    for a, b in combinations(participants, 2):
        expected_a = expected_score(ratings[a].elo, ratings[b].elo)

        # Normalize scores to 0-1 range
        total = scores[a] + scores[b]
        actual_a = scores[a] / total if total > 0 else 0.5

        delta = K_FACTOR * (actual_a - expected_a)
        changes[a] += delta
        changes[b] -= delta

    return changes
```

## Domain-Specific ELO

Agents have separate ratings per domain:

```python
rating = elo.get_rating("claude")

# Global ELO
print(rating.elo)  # 1623

# Domain ELOs
print(rating.domain_elos)  # {"security": 1580, "legal": 1490, ...}
```

### Domain Rating Update

When a match has a domain:

```python
# Update domain ELO (starts at global ELO if new)
if domain:
    domain_elo = rating.domain_elos.get(domain, rating.elo)
    rating.domain_elos[domain] = domain_elo + elo_change
```

## Calibration Scoring

Calibration measures how well agents predict outcomes with appropriate confidence.

### Brier Score

The Brier score measures prediction accuracy:

```
Brier = (predicted_probability - actual_outcome)^2
```

Range: 0 (perfect) to 1 (worst)

### Recording Predictions

> **Note:** Tournament prediction API is not yet implemented in the current version.

```python
# Tournament winner prediction
elo.record_winner_prediction(
    tournament_id="tourney-001",
    predictor_agent="claude",
    predicted_winner="gpt4",
    confidence=0.75
)

# Resolve tournament
brier_scores = elo.resolve_tournament_calibration(
    tournament_id="tourney-001",
    actual_winner="claude"
)
```

### Calibration Score

Combined calibration score (higher is better):

```python
@property
def calibration_score(self) -> float:
    if self.calibration_total < MIN_COUNT:
        return 0.0

    # Confidence scales with sample size
    confidence = min(1.0, 0.5 + 0.5 * (count - MIN_COUNT) / 40)

    # Score = (1 - Brier) weighted by confidence
    return (1 - brier_score) * confidence
```

### Calibration-Based K-Factor

Poorly calibrated agents receive higher K-factors, making their ratings more volatile:

```python
def compute_calibration_k_multipliers(participants, calibration_tracker):
    multipliers = {}
    for agent in participants:
        if calibration_tracker:
            quality = calibration_tracker.get_quality(agent)
            # Poor calibration -> higher K -> more volatile
            multipliers[agent] = 2.0 - quality  # Range: 1.0-2.0
        else:
            multipliers[agent] = 1.0
    return multipliers
```

## Domain Calibration

Track calibration per domain for grounded personas:

```python
# Record domain-specific prediction
elo.record_domain_prediction(
    agent_name="claude",
    domain="legal",
    confidence=0.8,
    correct=True
)

# Get calibration curve (by confidence bucket)
buckets = elo.get_calibration_by_bucket("claude", domain="legal")
# Returns: [{"bucket_key": "0.8-0.9", "accuracy": 0.82, ...}, ...]

# Expected Calibration Error
ece = elo.get_expected_calibration_error("claude")
```

### Confidence Buckets

Predictions are grouped into 10% buckets:

| Bucket | Confidence Range | Expected Accuracy |
|--------|------------------|-------------------|
| 0.0-0.1 | 0-10% | 5% |
| 0.1-0.2 | 10-20% | 15% |
| ... | ... | ... |
| 0.9-1.0 | 90-100% | 95% |

Well-calibrated agents have actual accuracy matching expected accuracy.

## Agent Rating Structure

```python
@dataclass
class AgentRating:
    agent_name: str
    elo: float = 1500
    domain_elos: dict[str, float] = {}

    # Win/loss record
    wins: int = 0
    losses: int = 0
    draws: int = 0
    debates_count: int = 0

    # Critique tracking
    critiques_accepted: int = 0
    critiques_total: int = 0

    # Calibration
    calibration_correct: int = 0
    calibration_total: int = 0
    calibration_brier_sum: float = 0.0

    # Computed properties
    win_rate: float              # wins / total games
    critique_acceptance_rate: float
    calibration_accuracy: float  # correct / total predictions
    calibration_brier_score: float
    calibration_score: float     # Combined metric
```

## Leaderboards

```python
# Global leaderboard
top_agents = elo.get_leaderboard(limit=20)

# Domain leaderboard
top_security = elo.get_leaderboard(limit=10, domain="security")

# Calibration leaderboard
best_calibrated = elo.get_calibration_leaderboard(limit=10)
```

### Leaderboard Caching

Leaderboards are cached with configurable TTL:

```python
# Cache settings (from config)
CACHE_TTL_LEADERBOARD = 300      # 5 minutes
CACHE_TTL_RECENT_MATCHES = 60    # 1 minute
CACHE_TTL_LB_STATS = 600         # 10 minutes
CACHE_TTL_CALIBRATION_LB = 300   # 5 minutes
```

## Relationship Tracking

Track dynamics between agent pairs:

```python
# Update relationship
elo.update_relationship(
    agent_a="claude",
    agent_b="gpt4",
    debate_increment=1,
    agreement_increment=1,
    critique_a_to_b=2,
    critique_accepted_a_to_b=1,
    a_win=1
)

# Get relationship metrics
metrics = elo.compute_relationship_metrics("claude", "gpt4")
# Returns: {"rivalry_score": 0.4, "alliance_score": 0.6, ...}

# Find rivals and allies
rivals = elo.get_rivals("claude", limit=5)
allies = elo.get_allies("claude", limit=5)
```

### Relationship Metrics

| Metric | Description |
|--------|-------------|
| `rivalry_score` | Competition intensity (0-1) |
| `alliance_score` | Collaboration tendency (0-1) |
| `relationship` | Classification: "rival", "ally", "neutral" |
| `agreement_rate` | How often they agree |
| `head_to_head` | Win/loss record |

## Red Team Integration

Adjust ELO based on vulnerability testing:

```python
elo_change = elo.record_redteam_result(
    agent_name="claude",
    robustness_score=0.85,
    successful_attacks=3,
    total_attacks=20,
    critical_vulnerabilities=0,
    session_id="session-001"
)

summary = elo.get_vulnerability_summary("claude")
```

## Formal Verification Integration

Adjust ELO based on verified/disproven claims:

```python
elo_change = elo.update_from_verification(
    agent_name="claude",
    domain="mathematics",
    verified_count=5,
    disproven_count=1,
    k_factor=16.0
)
```

Verified claims boost ELO; disproven claims reduce it.

## Performance Optimizations

### Batch Operations

```python
# Batch rating fetch
ratings = elo.get_ratings_batch(["claude", "gpt4", "gemini"])

# Batch relationship updates
elo.update_relationships_batch([
    {"agent_a": "claude", "agent_b": "gpt4", "debate_increment": 1},
    {"agent_a": "gpt4", "agent_b": "gemini", "agreement_increment": 1},
])
```

### JSON Snapshots

For high-read scenarios, snapshots avoid SQLite locking:

```python
# Fast leaderboard from snapshot
leaderboard = elo.get_snapshot_leaderboard(limit=20)

# Fast recent matches from snapshot
matches = elo.get_cached_recent_matches(limit=10)
```

## Related Documentation

- [Consensus Mechanism](./CONSENSUS.md) - How consensus is determined
- [Convergence Detection](./CONVERGENCE.md) - How convergence is detected
- [Agent Selection](../debate/AGENT_SELECTION.md) - How agents are selected for debates
