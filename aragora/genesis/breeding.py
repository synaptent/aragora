"""
Genome Breeding - Genetic operators for agent evolution.

Provides:
- GenomeBreeder: Crossover, mutation, and selection operators
- PopulationManager: Persistent population management across debates
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aragora.agents.personas import EXPERTISE_DOMAINS, PERSONALITY_TRAITS
from aragora.config import resolve_db_path
from aragora.genesis.database import GenesisDatabase
from aragora.genesis.genome import AgentGenome, GenomeStore, generate_genome_id


@dataclass
class Population:
    """A population of agent genomes."""

    population_id: str
    genomes: list[AgentGenome] = field(default_factory=list)
    generation: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    debate_history: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.genomes)

    @property
    def average_fitness(self) -> float:
        if not self.genomes:
            return 0.0
        return sum(g.fitness_score for g in self.genomes) / len(self.genomes)

    @property
    def best_genome(self) -> AgentGenome | None:
        if not self.genomes:
            return None
        return max(self.genomes, key=lambda g: g.fitness_score)

    def get_by_id(self, genome_id: str) -> AgentGenome | None:
        for g in self.genomes:
            if g.genome_id == genome_id:
                return g
        return None

    def to_dict(self) -> dict:
        return {
            "population_id": self.population_id,
            "genomes": [g.genome_id for g in self.genomes],
            "generation": self.generation,
            "created_at": self.created_at.isoformat(),
            "debate_history": self.debate_history,
        }


class GenomeBreeder:
    """
    Genetic operators for evolving agent genomes.

    Provides crossover, mutation, and selection operations
    inspired by evolutionary algorithms.
    """

    def __init__(
        self, mutation_rate: float = 0.1, crossover_ratio: float = 0.5, elite_ratio: float = 0.2
    ):
        """
        Args:
            mutation_rate: Probability of mutating each trait/expertise
            crossover_ratio: Blend ratio for crossover (0.5 = equal parents)
            elite_ratio: Fraction of top performers to preserve unchanged
        """
        self.mutation_rate = mutation_rate
        self.crossover_ratio = crossover_ratio
        self.elite_ratio = elite_ratio

    def crossover(
        self,
        parent_a: AgentGenome,
        parent_b: AgentGenome,
        name: str | None = None,
        debate_id: str | None = None,
    ) -> AgentGenome:
        """
        Blend two parent genomes into a child.

        Uses weighted average for numerical values and random selection
        for categorical values.
        """
        # Blend traits (weighted average)
        all_traits = set(parent_a.traits.keys()) | set(parent_b.traits.keys())
        child_traits = {}
        for trait in all_traits:
            val_a = parent_a.traits.get(trait, 0)
            val_b = parent_b.traits.get(trait, 0)
            child_traits[trait] = self.crossover_ratio * val_a + (1 - self.crossover_ratio) * val_b

        # Blend expertise (weighted average)
        all_domains = set(parent_a.expertise.keys()) | set(parent_b.expertise.keys())
        child_expertise = {}
        for domain in all_domains:
            val_a = parent_a.expertise.get(domain, 0)
            val_b = parent_b.expertise.get(domain, 0)
            child_expertise[domain] = (
                self.crossover_ratio * val_a + (1 - self.crossover_ratio) * val_b
            )

        # Model preference: random selection from parents
        model = random.choice([parent_a.model_preference, parent_b.model_preference])

        # Generate name if not provided
        if not name:
            parent_names = [parent_a.name.split("-")[0], parent_b.name.split("-")[0]]
            name = f"{parent_names[0]}-{parent_names[1]}-gen{max(parent_a.generation, parent_b.generation) + 1}"

        # New generation is max of parents + 1
        generation = max(parent_a.generation, parent_b.generation) + 1

        return AgentGenome(
            genome_id=generate_genome_id(
                child_traits, child_expertise, [parent_a.genome_id, parent_b.genome_id]
            ),
            name=name,
            traits=child_traits,
            expertise=child_expertise,
            model_preference=model,
            parent_genomes=[parent_a.genome_id, parent_b.genome_id],
            generation=generation,
            fitness_score=0.5,  # Start neutral
            birth_debate_id=debate_id,
        )

    def mutate(self, genome: AgentGenome, rate: float | None = None) -> AgentGenome:
        """
        Apply random mutations to a genome.

        Returns a new genome with mutated values (original unchanged).
        """
        rate = rate if rate is not None else self.mutation_rate

        # Copy values
        new_traits = genome.traits.copy()
        new_expertise = genome.expertise.copy()

        # Mutate traits
        for trait in list(new_traits.keys()):
            if random.random() < rate:
                # Add/subtract up to 0.2
                delta = random.uniform(-0.2, 0.2)
                new_traits[trait] = max(0, min(1, new_traits[trait] + delta))

        # Possibly add new trait
        if random.random() < rate / 2:
            available = [t for t in PERSONALITY_TRAITS if t not in new_traits]
            if available:
                new_trait = random.choice(available)
                new_traits[new_trait] = random.uniform(0.3, 0.7)

        # Mutate expertise
        for domain in list(new_expertise.keys()):
            if random.random() < rate:
                delta = random.uniform(-0.15, 0.15)
                new_expertise[domain] = max(0, min(1, new_expertise[domain] + delta))

        # Possibly add new expertise
        if random.random() < rate / 2:
            available = [d for d in EXPERTISE_DOMAINS if d not in new_expertise]
            if available:
                new_domain = random.choice(available)
                new_expertise[new_domain] = random.uniform(0.3, 0.6)

        # Possibly mutate model preference
        model = genome.model_preference
        if random.random() < rate / 3:
            models = ["claude", "gemini", "grok", "codex"]
            model = random.choice([m for m in models if m != model])

        return AgentGenome(
            genome_id=generate_genome_id(
                new_traits, new_expertise, genome.parent_genomes + ["mutated"]
            ),
            name=f"{genome.name}-mut",
            traits=new_traits,
            expertise=new_expertise,
            model_preference=model,
            parent_genomes=[genome.genome_id],
            generation=genome.generation,  # Same generation (mutation, not breeding)
            fitness_score=genome.fitness_score,  # Inherit fitness
            birth_debate_id=genome.birth_debate_id,
        )

    def spawn_specialist(
        self, domain: str, parent_pool: list[AgentGenome], debate_id: str | None = None
    ) -> AgentGenome:
        """
        Create a domain-specialized agent from best-fit parents.

        Selects parents with highest expertise in the target domain
        and boosts that domain in the offspring.
        """
        if not parent_pool:
            raise ValueError("Cannot spawn specialist from empty parent pool")

        # Sort by expertise in target domain
        sorted_parents = sorted(parent_pool, key=lambda g: g.expertise.get(domain, 0), reverse=True)

        # Take top 2 (or 1 if only 1 available)
        if len(sorted_parents) >= 2:
            parent_a, parent_b = sorted_parents[0], sorted_parents[1]
            child = self.crossover(parent_a, parent_b, debate_id=debate_id)
        elif sorted_parents:
            child = self.mutate(sorted_parents[0])
        else:
            raise ValueError("Cannot create domain specialist: no parents in pool")

        # Boost target domain expertise
        child.expertise[domain] = min(1.0, child.expertise.get(domain, 0.5) + 0.3)

        # Update name to reflect specialization
        child.name = f"{domain}-specialist-gen{child.generation}"

        return child

    def natural_selection(
        self, population: Population, keep_top_n: int = 4, breed_n: int = 2, mutate_n: int = 1
    ) -> Population:
        """
        Apply natural selection to evolve a population.

        1. Keep top performers (elitism)
        2. Breed new offspring from top performers
        3. Add mutations for diversity
        4. Cull poor performers
        """
        if not population.genomes:
            return population

        # Sort by fitness
        sorted_genomes = sorted(population.genomes, key=lambda g: g.fitness_score, reverse=True)

        # Keep elites
        n_elite = min(keep_top_n, len(sorted_genomes))
        new_genomes = sorted_genomes[:n_elite]

        # Breed new offspring
        if len(sorted_genomes) >= 2:
            for _ in range(breed_n):
                # Tournament selection (pick 2 from top half)
                top_half = sorted_genomes[: max(2, len(sorted_genomes) // 2)]
                parents = random.sample(top_half, 2)
                child = self.crossover(parents[0], parents[1])
                new_genomes.append(child)

        # Add mutations
        for _ in range(mutate_n):
            if sorted_genomes:
                parent = random.choice(sorted_genomes[: max(1, len(sorted_genomes) // 2)])
                mutant = self.mutate(parent)
                new_genomes.append(mutant)

        return Population(
            population_id=population.population_id,
            genomes=new_genomes,
            generation=population.generation + 1,
            debate_history=population.debate_history.copy(),
        )

    def protect_endangered(self, population: Population, min_similarity: float = 0.3) -> Population:
        """
        Preserve rare trait combinations for genetic diversity.

        Identifies genomes that are significantly different from others
        and protects them from culling.
        """
        if len(population.genomes) <= 2:
            return population

        # Calculate average similarity to rest of population for each genome
        uniqueness_scores = []
        for i, genome in enumerate(population.genomes):
            similarities = []
            for j, other in enumerate(population.genomes):
                if i != j:
                    similarities.append(genome.similarity_to(other))
            avg_sim = sum(similarities) / len(similarities) if similarities else 1.0
            uniqueness_scores.append((genome, 1 - avg_sim))

        # Boost fitness of unique genomes (those with avg similarity < threshold)
        protected = []
        for genome, uniqueness in uniqueness_scores:
            if uniqueness > (1 - min_similarity):
                # This genome is unique - boost its fitness to protect it
                genome.fitness_score = max(genome.fitness_score, 0.6)
            protected.append(genome)

        return Population(
            population_id=population.population_id,
            genomes=protected,
            generation=population.generation,
            debate_history=population.debate_history.copy(),
        )


class PopulationManager:
    """
    Manages persistent populations across debates.

    Provides:
    - Population creation from base agents
    - Fitness updates from debate outcomes
    - Generational evolution
    - Domain-specific agent selection
    """

    def __init__(self, db_path: str = "genesis.db", max_population_size: int = 8):
        resolved_path = resolve_db_path(db_path)
        self.db_path = Path(resolved_path)
        self.db = GenesisDatabase(resolved_path)
        self.max_population_size = max_population_size
        self.genome_store = GenomeStore(resolved_path)
        self.breeder = GenomeBreeder()

    def get_or_create_population(
        self, base_agents: list[str], population_id: str | None = None
    ) -> Population:
        """
        Load existing population or create from base agents.

        Args:
            base_agents: List of base agent names (e.g., ["claude", "gemini", "grok"])
            population_id: Optional specific population ID to load
        """
        # Try to load active population
        if not population_id:
            population_id = self._get_active_population_id()

        if population_id:
            population = self._load_population(population_id)
            if population:
                return population

        # Create new population from base agents
        from aragora.agents.personas import DEFAULT_PERSONAS

        genomes = []
        for agent_name in base_agents:
            # Get default persona or create minimal one
            if agent_name in DEFAULT_PERSONAS:
                persona = DEFAULT_PERSONAS[agent_name]
            else:
                from aragora.agents.personas import Persona

                persona = Persona(agent_name=agent_name)

            genome = AgentGenome.from_persona(persona, model=agent_name)
            self.genome_store.save(genome)
            genomes.append(genome)

        population = Population(
            population_id=f"pop-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            genomes=genomes,
            generation=0,
        )

        self._save_population(population)
        self._set_active_population(population.population_id)

        return population

    def update_fitness(
        self,
        genome_id: str,
        consensus_win: bool = False,
        critique_accepted: bool = False,
        prediction_correct: bool = False,
        fitness_delta: float = 0.0,
        **kwargs: object,
    ) -> None:
        """Update genome fitness based on debate outcome.

        Args:
            genome_id: Genome to update.
            consensus_win: Whether the agent won consensus.
            critique_accepted: Whether the agent's critique was accepted.
            prediction_correct: Whether the agent's prediction was correct.
            fitness_delta: Direct additive fitness adjustment (e.g. from ELO).
        """
        genome = self.genome_store.get(genome_id)
        if genome:
            genome.update_fitness(
                consensus_win=consensus_win,
                critique_accepted=critique_accepted,
                prediction_correct=prediction_correct,
            )
            if fitness_delta != 0.0:
                genome.fitness_score = max(0.0, min(1.0, genome.fitness_score + fitness_delta))
            self.genome_store.save(genome)

    def evolve_population(self, population: Population) -> Population:
        """
        Run one generation of evolution.

        1. Protect endangered (unique) genomes
        2. Apply natural selection
        3. Enforce population cap
        4. Save results
        """
        # Protect rare genomes
        population = self.breeder.protect_endangered(population)

        # Apply selection, breeding, mutation
        evolved = self.breeder.natural_selection(
            population,
            keep_top_n=max(2, self.max_population_size // 2),
            breed_n=max(1, self.max_population_size // 4),
            mutate_n=1,
        )

        # Enforce population cap
        if len(evolved.genomes) > self.max_population_size:
            evolved.genomes = sorted(evolved.genomes, key=lambda g: g.fitness_score, reverse=True)[
                : self.max_population_size
            ]

        # Save all genomes
        for genome in evolved.genomes:
            self.genome_store.save(genome)

        # Save population
        self._save_population(evolved)

        return evolved

    def get_best_for_domain(self, domain: str, n: int = 2) -> list[AgentGenome]:
        """Get top-performing genomes for a specific domain."""
        all_genomes = self.genome_store.get_all()

        # Sort by domain expertise, then by fitness
        sorted_genomes = sorted(
            all_genomes, key=lambda g: (g.expertise.get(domain, 0), g.fitness_score), reverse=True
        )

        return sorted_genomes[:n]

    def spawn_specialist_for_debate(
        self, domain: str, population: Population, debate_id: str
    ) -> AgentGenome:
        """Spawn a domain specialist for a specific debate."""
        specialist = self.breeder.spawn_specialist(
            domain=domain,
            parent_pool=population.genomes,
            debate_id=debate_id,
        )
        self.genome_store.save(specialist)
        return specialist

    def record_debate(self, population: Population, debate_id: str) -> None:
        """Record that a population participated in a debate."""
        population.debate_history.append(debate_id)
        self._save_population(population)

    def _get_active_population_id(self) -> str | None:
        """Get the currently active population ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT population_id FROM active_population WHERE id = 1")
            row = cursor.fetchone()

        return row[0] if row else None

    def _set_active_population(self, population_id: str) -> None:
        """Set the active population."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO active_population (id, population_id)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET population_id = excluded.population_id
            """,
                (population_id,),
            )

            conn.commit()

    def _load_population(self, population_id: str) -> Population | None:
        """Load a population from database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM populations WHERE population_id = ?", (population_id,))
            row = cursor.fetchone()

        if not row:
            return None

        genome_ids = json.loads(row[1]) if row[1] else []
        genomes = [self.genome_store.get(gid) for gid in genome_ids]
        genomes = [g for g in genomes if g is not None]

        return Population(
            population_id=row[0],
            genomes=genomes,
            generation=row[2] or 0,
            created_at=datetime.fromisoformat(row[3]) if row[3] else datetime.now(),
            debate_history=json.loads(row[4]) if row[4] else [],
        )

    def _save_population(self, population: Population) -> None:
        """Save a population to database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            genome_ids = [g.genome_id for g in population.genomes]

            cursor.execute(
                """
                INSERT INTO populations (population_id, genome_ids, generation, created_at, debate_history)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(population_id) DO UPDATE SET
                    genome_ids = excluded.genome_ids,
                    generation = excluded.generation,
                    debate_history = excluded.debate_history
            """,
                (
                    population.population_id,
                    json.dumps(genome_ids),
                    population.generation,
                    population.created_at.isoformat(),
                    json.dumps(population.debate_history),
                ),
            )

            conn.commit()


def fitness_from_elo(elo_delta: float, scale: float = 400.0) -> float:
    """Convert an ELO rating delta into a genome fitness adjustment.

    Maps ELO changes to a [-0.2, +0.2] fitness range using a sigmoid-like
    transform. This allows ELO performance signals to flow into the
    Genesis breeding pipeline so that agents who gain ELO are more likely
    to be selected as parents.

    Args:
        elo_delta: ELO points gained (positive) or lost (negative).
        scale: Normalization factor. 400 means +400 ELO maps to ~+0.2.

    Returns:
        Fitness adjustment value in [-0.2, +0.2].
    """
    import math

    # Sigmoid: maps (-inf, +inf) -> (-1, +1), then scale to [-0.2, +0.2]
    normalized = elo_delta / scale
    sigmoid = 2.0 / (1.0 + math.exp(-normalized)) - 1.0
    return round(sigmoid * 0.2, 4)


def select_by_fitness(population: list, count: int = 2) -> list:
    """Select top agents from a population based on fitness.

    Sorts agents by fitness score (or ELO rating) in descending order
    and returns the top ``count`` agents.

    Args:
        population: List of agents with ``fitness_score`` or ``elo_rating``.
        count: Number of agents to select.

    Returns:
        List of selected agents, highest fitness first.
    """
    if not population:
        return []
    count = min(count, len(population))

    def _fitness_key(agent):
        for attr in ("fitness_score", "elo_rating"):
            val = getattr(agent, attr, None)
            if isinstance(val, (int, float)):
                return val
        return 0

    ranked = sorted(population, key=_fitness_key, reverse=True)
    return ranked[:count]
