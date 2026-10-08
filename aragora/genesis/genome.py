"""
Agent Genome - Genetic representation for evolutionary agent systems.

Extends Persona with genetic-specific fields for:
- Lineage tracking (parent genomes)
- Generation counting
- Fitness scoring from debate outcomes
- Serialization for persistence
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aragora.agents.personas import Persona
from aragora.config import resolve_db_path
from aragora.genesis.database import GenesisDatabase


def generate_genome_id(traits: dict, expertise: dict, parents: list[str]) -> str:
    """Generate a unique genome ID from its characteristics."""
    content = json.dumps(
        {
            "traits": sorted(traits.items()),
            "expertise": sorted(expertise.items()),
            "parents": sorted(parents),
            "timestamp": datetime.now().isoformat(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:12]


@dataclass
class AgentGenome:
    """
    Genetic representation of an agent's persona.

    Extends Persona with evolutionary tracking:
    - Lineage via parent_genomes
    - Generation depth
    - Fitness score updated by debate outcomes
    """

    genome_id: str
    name: str  # Agent name (e.g., "claude-grok-security-v1")
    traits: dict[str, float] = field(default_factory=dict)  # trait -> weight 0-1
    expertise: dict[str, float] = field(default_factory=dict)  # domain -> score 0-1
    model_preference: str = "claude"  # Preferred model backend
    parent_genomes: list[str] = field(default_factory=list)  # Parent genome IDs
    generation: int = 0  # How many generations from base
    fitness_score: float = 0.5  # Updated by debate outcomes
    birth_debate_id: str | None = None  # Debate where this genome was created
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Fitness components (for transparency)
    consensus_contributions: int = 0
    critiques_accepted: int = 0
    predictions_correct: int = 0
    debates_participated: int = 0

    @classmethod
    def from_persona(cls, persona: Persona, model: str = "claude") -> AgentGenome:
        """Create a base genome from an existing Persona."""
        # Convert trait list to weighted dict (all equal weight for base)
        trait_weights = dict.fromkeys(persona.traits, 1.0)

        return cls(
            genome_id=generate_genome_id(trait_weights, persona.expertise, []),
            name=persona.agent_name,
            traits=trait_weights,
            expertise=persona.expertise.copy(),
            model_preference=model,
            parent_genomes=[],
            generation=0,
            fitness_score=0.5,
        )

    def to_persona(self) -> Persona:
        """Convert genome back to Persona for debate use."""
        # Get top traits (those with weight > 0.5)
        active_traits = [t for t, w in self.traits.items() if w > 0.5]

        return Persona(
            agent_name=self.name,
            description=f"Generation {self.generation} agent (fitness: {self.fitness_score:.2f})",
            traits=active_traits,
            expertise=self.expertise.copy(),
        )

    def get_dominant_traits(self, top_n: int = 3) -> list[str]:
        """Get the most prominent traits."""
        sorted_traits = sorted(self.traits.items(), key=lambda x: x[1], reverse=True)
        return [t for t, _ in sorted_traits[:top_n]]

    def get_top_expertise(self, top_n: int = 3) -> list[tuple[str, float]]:
        """Get highest expertise areas."""
        sorted_exp = sorted(self.expertise.items(), key=lambda x: x[1], reverse=True)
        return sorted_exp[:top_n]

    def update_fitness(
        self,
        consensus_win: bool = False,
        critique_accepted: bool = False,
        prediction_correct: bool = False,
    ) -> None:
        """Update fitness based on debate outcome."""
        self.debates_participated += 1

        if consensus_win:
            self.consensus_contributions += 1
        if critique_accepted:
            self.critiques_accepted += 1
        if prediction_correct:
            self.predictions_correct += 1

        # Calculate weighted fitness
        if self.debates_participated > 0:
            consensus_rate = self.consensus_contributions / self.debates_participated
            critique_rate = self.critiques_accepted / max(1, self.debates_participated)
            prediction_rate = self.predictions_correct / max(1, self.debates_participated)

            # Weighted combination
            self.fitness_score = 0.4 * consensus_rate + 0.3 * critique_rate + 0.3 * prediction_rate

        self.updated_at = datetime.now()

    def similarity_to(self, other: AgentGenome) -> float:
        """Calculate genetic similarity to another genome (0-1)."""
        # Trait similarity
        all_traits = set(self.traits.keys()) | set(other.traits.keys())
        if all_traits:
            trait_sim = sum(
                1 - abs(self.traits.get(t, 0) - other.traits.get(t, 0)) for t in all_traits
            ) / len(all_traits)
        else:
            trait_sim = 1.0

        # Expertise similarity
        all_domains = set(self.expertise.keys()) | set(other.expertise.keys())
        if all_domains:
            exp_sim = sum(
                1 - abs(self.expertise.get(d, 0) - other.expertise.get(d, 0)) for d in all_domains
            ) / len(all_domains)
        else:
            exp_sim = 1.0

        return 0.5 * trait_sim + 0.5 * exp_sim

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "genome_id": self.genome_id,
            "name": self.name,
            "traits": self.traits,
            "expertise": self.expertise,
            "model_preference": self.model_preference,
            "parent_genomes": self.parent_genomes,
            "generation": self.generation,
            "fitness_score": self.fitness_score,
            "birth_debate_id": self.birth_debate_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "consensus_contributions": self.consensus_contributions,
            "critiques_accepted": self.critiques_accepted,
            "predictions_correct": self.predictions_correct,
            "debates_participated": self.debates_participated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentGenome:
        """Deserialize from dictionary."""
        return cls(
            genome_id=data["genome_id"],
            name=data["name"],
            traits=data.get("traits", {}),
            expertise=data.get("expertise", {}),
            model_preference=data.get("model_preference", "claude"),
            parent_genomes=data.get("parent_genomes", []),
            generation=data.get("generation", 0),
            fitness_score=data.get("fitness_score", 0.5),
            birth_debate_id=data.get("birth_debate_id"),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if "created_at" in data
                else datetime.now()
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"])
                if "updated_at" in data
                else datetime.now()
            ),
            consensus_contributions=data.get("consensus_contributions", 0),
            critiques_accepted=data.get("critiques_accepted", 0),
            predictions_correct=data.get("predictions_correct", 0),
            debates_participated=data.get("debates_participated", 0),
        )

    def __repr__(self) -> str:
        top_traits = self.get_dominant_traits(2)
        top_exp = self.get_top_expertise(2)
        exp_str = ", ".join(f"{d}:{s:.0%}" for d, s in top_exp)
        return f"Genome({self.name}, gen={self.generation}, fit={self.fitness_score:.2f}, traits={top_traits}, exp=[{exp_str}])"


class GenomeStore:
    """SQLite-based storage for genomes."""

    def __init__(self, db_path: str = "genesis.db"):
        resolved_path = resolve_db_path(db_path)
        self.db_path = Path(resolved_path)
        self.db = GenesisDatabase(resolved_path)

    def save(self, genome: AgentGenome) -> None:
        """Save or update a genome."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO genomes (
                    genome_id, name, traits, expertise, model_preference,
                    parent_genomes, generation, fitness_score, birth_debate_id,
                    created_at, updated_at, consensus_contributions,
                    critiques_accepted, predictions_correct, debates_participated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(genome_id) DO UPDATE SET
                    fitness_score = excluded.fitness_score,
                    updated_at = excluded.updated_at,
                    consensus_contributions = excluded.consensus_contributions,
                    critiques_accepted = excluded.critiques_accepted,
                    predictions_correct = excluded.predictions_correct,
                    debates_participated = excluded.debates_participated
            """,
                (
                    genome.genome_id,
                    genome.name,
                    json.dumps(genome.traits),
                    json.dumps(genome.expertise),
                    genome.model_preference,
                    json.dumps(genome.parent_genomes),
                    genome.generation,
                    genome.fitness_score,
                    genome.birth_debate_id,
                    genome.created_at.isoformat(),
                    genome.updated_at.isoformat(),
                    genome.consensus_contributions,
                    genome.critiques_accepted,
                    genome.predictions_correct,
                    genome.debates_participated,
                ),
            )

            conn.commit()

    def get(self, genome_id: str) -> AgentGenome | None:
        """Get a genome by ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM genomes WHERE genome_id = ?", (genome_id,))
            row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_genome(row)

    def get_by_name(self, name: str) -> AgentGenome | None:
        """Get the latest genome with a given name."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM genomes WHERE name = ? ORDER BY generation DESC LIMIT 1", (name,)
            )
            row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_genome(row)

    def get_top_by_fitness(self, n: int = 10) -> list[AgentGenome]:
        """Get top genomes by fitness score."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM genomes ORDER BY fitness_score DESC LIMIT ?", (n,))
            rows = cursor.fetchall()

        return [self._row_to_genome(row) for row in rows]

    def get_all(self) -> list[AgentGenome]:
        """Get all genomes."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM genomes")
            rows = cursor.fetchall()

        return [self._row_to_genome(row) for row in rows]

    def get_lineage(self, genome_id: str) -> list[AgentGenome]:
        """Get full lineage (ancestors) of a genome."""
        lineage = []
        current = self.get(genome_id)

        visited = set()
        while current and current.genome_id not in visited:
            lineage.append(current)
            visited.add(current.genome_id)

            if current.parent_genomes:
                # Get first parent (primary lineage)
                current = self.get(current.parent_genomes[0])
            else:
                break

        return lineage

    def delete(self, genome_id: str) -> bool:
        """Delete a genome."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM genomes WHERE genome_id = ?", (genome_id,))
            deleted = cursor.rowcount > 0

            conn.commit()

        return deleted

    def _row_to_genome(self, row: tuple) -> AgentGenome:
        """Convert a database row to AgentGenome."""
        return AgentGenome(
            genome_id=row[0],
            name=row[1],
            traits=json.loads(row[2]) if row[2] else {},
            expertise=json.loads(row[3]) if row[3] else {},
            model_preference=row[4] or "claude",
            parent_genomes=json.loads(row[5]) if row[5] else [],
            generation=row[6] or 0,
            fitness_score=row[7] or 0.5,
            birth_debate_id=row[8],
            created_at=datetime.fromisoformat(row[9]) if row[9] else datetime.now(),
            updated_at=datetime.fromisoformat(row[10]) if row[10] else datetime.now(),
            consensus_contributions=row[11] or 0,
            critiques_accepted=row[12] or 0,
            predictions_correct=row[13] or 0,
            debates_participated=row[14] or 0,
        )
