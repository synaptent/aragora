"""
Emergent Persona Laboratory v2.

Experimental framework for evolving agent personas through:
- A/B testing of persona configurations
- Cross-pollination of successful traits between agents
- Detection of emergent specializations
- Automated trait mutation and selection

Inspired by Project Sid's emergent civilization dynamics.
"""

from __future__ import annotations

__all__ = [
    "PersonaExperiment",
    "EmergentTrait",
    "TraitTransfer",
    "PersonaLaboratory",
]

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.agents.personas import (
    EXPERTISE_DOMAINS,
    PERSONALITY_TRAITS,
    Persona,
    PersonaManager,
)
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.insights.database import InsightsDatabase
from aragora.utils.json_helpers import safe_json_loads

logger = logging.getLogger(__name__)


@dataclass
class PersonaExperiment:
    """An A/B experiment comparing persona configurations."""

    experiment_id: str
    agent_name: str
    control_persona: Persona
    variant_persona: Persona
    hypothesis: str
    status: str = "running"  # running, completed, aborted
    control_successes: int = 0
    control_trials: int = 0
    variant_successes: int = 0
    variant_trials: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None

    @property
    def control_rate(self) -> float:
        """Control success rate."""
        return self.control_successes / self.control_trials if self.control_trials > 0 else 0.0

    @property
    def variant_rate(self) -> float:
        """Variant success rate."""
        return self.variant_successes / self.variant_trials if self.variant_trials > 0 else 0.0

    @property
    def relative_improvement(self) -> float:
        """Relative improvement of variant over control."""
        if self.control_rate == 0:
            return 0.0
        return (self.variant_rate - self.control_rate) / self.control_rate

    @property
    def is_significant(self) -> bool:
        """
        Simple significance check (minimum trials and meaningful difference).

        For production use, consider proper statistical testing.
        """
        min_trials = 20
        if self.control_trials < min_trials or self.variant_trials < min_trials:
            return False
        return abs(self.relative_improvement) >= 0.1  # 10% difference


@dataclass
class EmergentTrait:
    """A trait that emerged from agent performance patterns."""

    trait_name: str
    source_agents: list[str]
    supporting_evidence: list[str]  # Performance patterns that led to emergence
    confidence: float  # 0-1 confidence in the emergence
    first_detected: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TraitTransfer:
    """Record of trait cross-pollination between agents."""

    from_agent: str
    to_agent: str
    trait: str
    expertise_domain: str | None
    success_rate_before: float
    success_rate_after: float | None = None
    transferred_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PersonaLaboratory:
    """
    Experimental laboratory for evolving agent personas.

    Provides tools for:
    - Running A/B experiments on persona configurations
    - Detecting emergent specializations from performance data
    - Cross-pollinating successful traits between agents
    - Automated persona mutation and evolution
    """

    def __init__(
        self,
        persona_manager: PersonaManager,
        db_path: str | Path | None = None,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.LABORATORY)
        self.persona_manager = persona_manager
        self.db_path = Path(db_path)
        self.db = InsightsDatabase(str(db_path))

    # =========================================================================
    # A/B Experiments
    # =========================================================================

    def create_experiment(
        self,
        agent_name: str,
        variant_traits: list[str] | None = None,
        variant_expertise: dict[str, float] | None = None,
        hypothesis: str = "",
    ) -> PersonaExperiment:
        """
        Create a new persona experiment.

        Uses current persona as control and creates a variant with specified changes.
        """
        import uuid

        control = self.persona_manager.get_persona(agent_name)
        if not control:
            control = self.persona_manager.create_persona(agent_name)

        # Create variant with modifications
        variant_traits_list = variant_traits if variant_traits else control.traits.copy()
        variant_expertise_dict = (
            variant_expertise if variant_expertise else control.expertise.copy()
        )

        variant = Persona(
            agent_name=f"{agent_name}_variant",
            description=control.description,
            traits=variant_traits_list,
            expertise=variant_expertise_dict,
        )

        experiment_id = f"exp_{uuid.uuid4().hex[:8]}"
        experiment = PersonaExperiment(
            experiment_id=experiment_id,
            agent_name=agent_name,
            control_persona=control,
            variant_persona=variant,
            hypothesis=hypothesis,
        )

        self._save_experiment(experiment)
        return experiment

    def _save_experiment(self, exp: PersonaExperiment) -> None:
        """Save experiment to database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO experiments (
                    experiment_id, agent_name, control_persona, variant_persona,
                    hypothesis, status, control_successes, control_trials,
                    variant_successes, variant_trials, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp.experiment_id,
                    exp.agent_name,
                    json.dumps(
                        {
                            "traits": exp.control_persona.traits,
                            "expertise": exp.control_persona.expertise,
                        }
                    ),
                    json.dumps(
                        {
                            "traits": exp.variant_persona.traits,
                            "expertise": exp.variant_persona.expertise,
                        }
                    ),
                    exp.hypothesis,
                    exp.status,
                    exp.control_successes,
                    exp.control_trials,
                    exp.variant_successes,
                    exp.variant_trials,
                    exp.created_at,
                    exp.completed_at,
                ),
            )

            conn.commit()

    def record_experiment_result(
        self,
        experiment_id: str,
        is_variant: bool,
        success: bool,
    ):
        """Record a trial result for an experiment."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            if is_variant:
                cursor.execute(
                    """
                    UPDATE experiments SET
                        variant_trials = variant_trials + 1,
                        variant_successes = variant_successes + ?
                    WHERE experiment_id = ?
                    """,
                    (1 if success else 0, experiment_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE experiments SET
                        control_trials = control_trials + 1,
                        control_successes = control_successes + ?
                    WHERE experiment_id = ?
                    """,
                    (1 if success else 0, experiment_id),
                )
            conn.commit()

    def conclude_experiment(self, experiment_id: str) -> PersonaExperiment | None:
        """
        Conclude an experiment and optionally apply the winning variant.

        If variant is significantly better, updates the agent's persona.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,))
            row = cursor.fetchone()

            if not row:
                return None

            exp = self._row_to_experiment(row)

        if exp.is_significant and exp.variant_rate > exp.control_rate:
            # Apply variant as new persona
            self.persona_manager.create_persona(
                agent_name=exp.agent_name,
                description=exp.control_persona.description,
                traits=exp.variant_persona.traits,
                expertise=exp.variant_persona.expertise,
            )
            self._record_evolution(
                exp.agent_name,
                "experiment_adoption",
                exp.control_persona,
                exp.variant_persona,
                f"Experiment {experiment_id}: {exp.relative_improvement:.1%} improvement",
            )

        exp.status = "completed"
        exp.completed_at = datetime.now().isoformat()
        self._save_experiment(exp)

        return exp

    def _row_to_experiment(self, row) -> PersonaExperiment:
        """Convert database row to PersonaExperiment."""
        control_data: dict[str, Any] = safe_json_loads(row[2], {})
        variant_data: dict[str, Any] = safe_json_loads(row[3], {})

        return PersonaExperiment(
            experiment_id=row[0],
            agent_name=row[1],
            control_persona=Persona(
                agent_name=row[1],
                traits=control_data.get("traits", []),
                expertise=control_data.get("expertise", {}),
            ),
            variant_persona=Persona(
                agent_name=f"{row[1]}_variant",
                traits=variant_data.get("traits", []),
                expertise=variant_data.get("expertise", {}),
            ),
            hypothesis=row[4] or "",
            status=row[5],
            control_successes=row[6],
            control_trials=row[7],
            variant_successes=row[8],
            variant_trials=row[9],
            created_at=row[10],
            completed_at=row[11],
        )

    def get_running_experiments(self) -> list[PersonaExperiment]:
        """Get all running experiments."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM experiments WHERE status = 'running'")
            rows = cursor.fetchall()

            return [self._row_to_experiment(row) for row in rows]

    # =========================================================================
    # Emergent Trait Detection
    # =========================================================================

    def detect_emergent_traits(self) -> list[EmergentTrait]:
        """
        Analyze performance patterns to detect emergent specializations.

        Looks for:
        - Agents consistently outperforming in unlabeled domains
        - Novel trait combinations that correlate with success
        - Behavioral patterns not captured by existing traits
        """
        emergent = []

        # Get all personas and their performance summaries
        personas = self.persona_manager.get_all_personas()

        for persona in personas:
            summary = self.persona_manager.get_performance_summary(persona.agent_name)

            for domain, stats in summary.items():
                if stats["total"] < 10:
                    continue

                # Check for high performance in unexpected domains
                current_expertise = persona.expertise.get(domain, 0)
                if stats["rate"] > 0.7 and current_expertise < 0.3:
                    # Agent is good at something they're not known for
                    emergent.append(
                        EmergentTrait(
                            trait_name=f"emergent_{domain}_specialist",
                            source_agents=[persona.agent_name],
                            supporting_evidence=[
                                f"Success rate {stats['rate']:.0%} in {domain}",
                                f"Current labeled expertise: {current_expertise:.0%}",
                            ],
                            confidence=min(1.0, stats["rate"] * (stats["total"] / 30)),
                        )
                    )

        # Save detected traits
        for trait in emergent:
            self._save_emergent_trait(trait)

        return emergent

    def _save_emergent_trait(self, trait: EmergentTrait) -> None:
        """Save emergent trait to database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO emergent_traits (trait_name, source_agents, supporting_evidence, confidence)
                VALUES (?, ?, ?, ?)
                """,
                (
                    trait.trait_name,
                    json.dumps(trait.source_agents),
                    json.dumps(trait.supporting_evidence),
                    trait.confidence,
                ),
            )

            conn.commit()

    def get_emergent_traits(self, min_confidence: float = 0.5) -> list[EmergentTrait]:
        """Get detected emergent traits above confidence threshold."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT trait_name, source_agents, supporting_evidence, confidence, first_detected
                FROM emergent_traits
                WHERE confidence >= ?
                ORDER BY confidence DESC
                """,
                (min_confidence,),
            )
            rows = cursor.fetchall()

            return [
                EmergentTrait(
                    trait_name=row[0],
                    source_agents=safe_json_loads(row[1], []),
                    supporting_evidence=safe_json_loads(row[2], []),
                    confidence=row[3],
                    first_detected=row[4],
                )
                for row in rows
            ]

    # =========================================================================
    # Cross-Pollination
    # =========================================================================

    def cross_pollinate(
        self,
        from_agent: str,
        to_agent: str,
        trait: str | None = None,
        expertise_domain: str | None = None,
    ) -> TraitTransfer | None:
        """
        Transfer a successful trait or expertise from one agent to another.

        Either trait OR expertise_domain should be specified.
        """
        source = self.persona_manager.get_persona(from_agent)
        target = self.persona_manager.get_persona(to_agent)

        if not source or not target:
            return None

        # Get baseline performance
        target_summary = self.persona_manager.get_performance_summary(to_agent)
        baseline_rate = 0.0
        if expertise_domain and expertise_domain in target_summary:
            baseline_rate = target_summary[expertise_domain]["rate"]

        transfer = TraitTransfer(
            from_agent=from_agent,
            to_agent=to_agent,
            trait=trait or "",
            expertise_domain=expertise_domain,
            success_rate_before=baseline_rate,
        )

        # Apply the transfer
        new_traits = target.traits.copy()
        new_expertise = target.expertise.copy()

        if trait and trait in PERSONALITY_TRAITS and trait not in new_traits:
            new_traits.append(trait)

        if expertise_domain and expertise_domain in EXPERTISE_DOMAINS:
            source_level = source.expertise.get(expertise_domain, 0.5)
            target_level = target.expertise.get(expertise_domain, 0.5)
            # Blend expertise levels
            new_expertise[expertise_domain] = 0.7 * target_level + 0.3 * source_level

        # Update target persona
        self.persona_manager.create_persona(
            agent_name=to_agent,
            description=target.description,
            traits=new_traits,
            expertise=new_expertise,
        )

        self._save_transfer(transfer)
        self._record_evolution(
            to_agent,
            "cross_pollination",
            target,
            Persona(to_agent, traits=new_traits, expertise=new_expertise),
            f"Transferred from {from_agent}: trait={trait}, domain={expertise_domain}",
        )

        return transfer

    def _save_transfer(self, transfer: TraitTransfer) -> None:
        """Save trait transfer to database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO trait_transfers (
                    from_agent, to_agent, trait, expertise_domain,
                    success_rate_before, success_rate_after, transferred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer.from_agent,
                    transfer.to_agent,
                    transfer.trait,
                    transfer.expertise_domain,
                    transfer.success_rate_before,
                    transfer.success_rate_after,
                    transfer.transferred_at,
                ),
            )

            conn.commit()

    def suggest_cross_pollinations(self, target_agent: str) -> list[tuple[str, str, str]]:
        """
        Suggest beneficial trait transfers for a target agent.

        Returns list of (source_agent, trait_or_domain, reason) tuples.
        """
        suggestions: list[tuple[str, str, str]] = []

        target = self.persona_manager.get_persona(target_agent)
        if not target:
            return suggestions

        target_summary = self.persona_manager.get_performance_summary(target_agent)

        # Find domains where target is weak
        weak_domains = [
            domain
            for domain, stats in target_summary.items()
            if stats["total"] >= 5 and stats["rate"] < 0.5
        ]

        # Find agents strong in those domains
        all_personas = self.persona_manager.get_all_personas()
        for persona in all_personas:
            if persona.agent_name == target_agent:
                continue

            source_summary = self.persona_manager.get_performance_summary(persona.agent_name)

            for domain in weak_domains:
                if domain in source_summary and source_summary[domain]["rate"] > 0.7:
                    suggestions.append(
                        (
                            persona.agent_name,
                            domain,
                            f"Source has {source_summary[domain]['rate']:.0%} success, target has {target_summary[domain]['rate']:.0%}",
                        )
                    )

        return suggestions

    # =========================================================================
    # Persona Mutation
    # =========================================================================

    def mutate_persona(
        self,
        agent_name: str,
        mutation_rate: float = 0.1,
    ) -> Persona | None:
        """
        Apply random mutations to a persona based on mutation rate.

        Used for evolutionary exploration of persona space.
        """
        persona = self.persona_manager.get_persona(agent_name)
        if not persona:
            return None

        new_traits = persona.traits.copy()
        new_expertise = persona.expertise.copy()
        mutations = []

        # Trait mutation
        if random.random() < mutation_rate:
            available_traits = [t for t in PERSONALITY_TRAITS if t not in new_traits]
            if available_traits and len(new_traits) < 4:
                new_trait = random.choice(available_traits)
                new_traits.append(new_trait)
                mutations.append(f"Added trait: {new_trait}")
            elif new_traits and random.random() < 0.5:
                removed = random.choice(new_traits)
                new_traits.remove(removed)
                mutations.append(f"Removed trait: {removed}")

        # Expertise mutation
        for domain in EXPERTISE_DOMAINS:
            if random.random() < mutation_rate:
                current = new_expertise.get(domain, 0.5)
                delta = random.uniform(-0.1, 0.1)
                new_expertise[domain] = max(0.0, min(1.0, current + delta))
                mutations.append(f"Adjusted {domain}: {current:.2f} -> {new_expertise[domain]:.2f}")

        if not mutations:
            return persona

        new_persona = self.persona_manager.create_persona(
            agent_name=agent_name,
            description=persona.description,
            traits=new_traits,
            expertise=new_expertise,
        )

        self._record_evolution(
            agent_name,
            "mutation",
            persona,
            new_persona,
            "; ".join(mutations),
        )

        return new_persona

    def _record_evolution(
        self,
        agent_name: str,
        mutation_type: str,
        before: Persona,
        after: Persona,
        reason: str,
    ):
        """Record evolution history."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO evolution_history (agent_name, mutation_type, before_state, after_state, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    agent_name,
                    mutation_type,
                    json.dumps({"traits": before.traits, "expertise": before.expertise}),
                    json.dumps({"traits": after.traits, "expertise": after.expertise}),
                    reason,
                ),
            )

            conn.commit()

    def get_evolution_history(self, agent_name: str, limit: int = 20) -> list[dict]:
        """Get evolution history for an agent."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT mutation_type, before_state, after_state, reason, created_at
                FROM evolution_history
                WHERE agent_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_name, limit),
            )
            rows = cursor.fetchall()

            return [
                {
                    "mutation_type": row[0],
                    "before": safe_json_loads(row[1], {}),
                    "after": safe_json_loads(row[2], {}),
                    "reason": row[3],
                    "created_at": row[4],
                }
                for row in rows
            ]

    # =========================================================================
    # Laboratory Statistics
    # =========================================================================

    def get_lab_stats(self) -> dict:
        """Get laboratory statistics."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*), SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) FROM experiments"
            )
            exp_row = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) FROM emergent_traits WHERE confidence >= 0.5")
            trait_row = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) FROM trait_transfers")
            transfer_row = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) FROM evolution_history")
            evolution_row = cursor.fetchone()

            return {
                "total_experiments": exp_row[0] or 0,
                "completed_experiments": exp_row[1] or 0,
                "emergent_traits_detected": trait_row[0] or 0,
                "trait_transfers": transfer_row[0] or 0,
                "total_evolutions": evolution_row[0] or 0,
            }
