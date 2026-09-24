"""
MCP Agent Tools.

Agent management, history, lineage, and breeding.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def list_agents_tool() -> dict[str, Any]:
    """
    List available AI agents.

    Returns:
        Dict with list of available agent IDs and count
    """
    try:
        from aragora.agents.base import list_available_agents

        agents_dict = list_available_agents()
        agents = list(agents_dict.keys())
        return {
            "agents": agents,
            "count": len(agents),
        }
    except Exception as e:  # noqa: BLE001 - graceful degradation, fail closed
        logger.warning("Could not list agents: %s", e)
        return {
            "agents": [],
            "count": 0,
            "error": "Could not list agents",
        }


async def get_agent_history_tool(
    agent_name: str,
    include_debates: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Get an agent's debate history, ELO rating, and performance stats.

    Args:
        agent_name: The agent name (e.g., 'anthropic-api', 'openai-api')
        include_debates: Include recent debate summaries
        limit: Max debates to include

    Returns:
        Dict with agent stats, ELO rating, and optionally recent debates
    """
    if not agent_name:
        return {"error": "agent_name is required"}

    result: dict[str, Any] = {
        "agent_name": agent_name,
        "elo_rating": 1500,
        "total_debates": 0,
        "consensus_rate": 0.0,
        "win_rate": 0.0,
    }

    # Get ELO rating
    try:
        from aragora.ranking.elo import EloSystem

        elo_system = EloSystem()
        agent_rating = elo_system.get_rating(agent_name)
        if agent_rating:
            result["elo_rating"] = agent_rating.elo
            result["wins"] = agent_rating.wins
            result["losses"] = agent_rating.losses
            result["total_debates"] = agent_rating.debates_count
    except Exception as e:  # noqa: BLE001 - graceful degradation, ELO lookup is non-critical
        logger.debug("Could not get ELO: %s", e)

    # Get performance stats from storage
    try:
        from aragora.storage.debate_storage import get_debates_db

        db = get_debates_db()
        if db and hasattr(db, "get_agent_stats"):
            stats = db.get_agent_stats(agent_name)
            if stats:
                result.update(
                    {
                        "total_debates": stats.get("total_debates", 0),
                        "consensus_rate": stats.get("consensus_rate", 0.0),
                        "win_rate": stats.get("win_rate", 0.0),
                        "avg_confidence": stats.get("avg_confidence", 0.0),
                    }
                )

        # Get recent debates if requested
        if include_debates and db and hasattr(db, "search"):
            search_result = db.search(query="", limit=limit)
            # search returns tuple (list, count) - extract list and filter by agent
            all_debates = search_result[0] if isinstance(search_result, tuple) else search_result
            filtered_debates: list[dict[str, Any]] = []
            for debate in all_debates:
                debate_dict = debate if isinstance(debate, dict) else vars(debate)
                agents_list = debate_dict.get("agents", [])
                if any(agent_name.lower() in str(a).lower() for a in agents_list):
                    filtered_debates.append(debate_dict)
            result["recent_debates"] = [
                {
                    "debate_id": d.get("debate_id"),
                    "task": d.get("task", "")[:80],
                    "consensus_reached": d.get("consensus_reached", False),
                    "timestamp": d.get("timestamp", ""),
                }
                for d in filtered_debates[:limit]
            ]
    except Exception as e:  # noqa: BLE001 - graceful degradation, history lookup is non-critical
        logger.debug("Could not get agent history: %s", e)

    return result


async def get_agent_lineage_tool(
    agent_name: str,
    depth: int = 5,
) -> dict[str, Any]:
    """
    Get the evolutionary lineage of an agent.

    Args:
        agent_name: Name of the agent
        depth: How many generations back to trace

    Returns:
        Dict with lineage tree
    """
    if not agent_name:
        return {"error": "agent_name is required"}

    depth = min(max(depth, 1), 20)

    try:
        from aragora.genesis.genome import GenomeStore

        # Try to get genome from the genome store
        store = GenomeStore()
        genome = store.get_by_name(agent_name)

        if not genome:
            # Try looking up by genome_id directly
            genome = store.get(agent_name)

        if not genome:
            return {
                "agent_name": agent_name,
                "lineage": [],
                "generation": 0,
                "note": "Agent not found in genesis database. May be a base agent without evolutionary history.",
            }

        # Build lineage tree
        lineage = []
        current = genome
        visited = set()

        for _ in range(depth):
            if not current or current.genome_id in visited:
                break

            visited.add(current.genome_id)
            lineage.append(
                {
                    "genome_id": current.genome_id,
                    "name": current.name,
                    "generation": current.generation,
                    "fitness_score": current.fitness_score,
                    "parent_genomes": current.parent_genomes,
                    "model_preference": current.model_preference,
                    "birth_debate_id": current.birth_debate_id,
                }
            )

            # Get first parent for next iteration
            if current.parent_genomes:
                parent_id = current.parent_genomes[0]
                parent_genome = store.get(parent_id)
                if parent_genome is None:
                    break
                current = parent_genome
            else:
                break

        return {
            "agent_name": agent_name,
            "genome_id": genome.genome_id,
            "generation": genome.generation,
            "lineage": lineage,
            "depth_traced": len(lineage),
        }

    except ImportError:
        return {"error": "Genesis module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Failed to get lineage: {e}"}


async def breed_agents_tool(
    parent_a: str,
    parent_b: str,
    mutation_rate: float = 0.1,
) -> dict[str, Any]:
    """
    Breed two agents to create a new offspring agent.

    Args:
        parent_a: First parent agent name or genome_id
        parent_b: Second parent agent name or genome_id
        mutation_rate: Mutation rate (0-1)

    Returns:
        Dict with offspring agent info
    """
    if not parent_a or not parent_b:
        return {"error": "Both parent_a and parent_b are required"}

    mutation_rate = min(max(mutation_rate, 0.0), 1.0)

    try:
        from aragora.genesis.breeding import GenomeBreeder
        from aragora.genesis.genome import GenomeStore

        store = GenomeStore()

        # Look up parent genomes (by name or genome_id)
        genome_a = store.get_by_name(parent_a) or store.get(parent_a)
        genome_b = store.get_by_name(parent_b) or store.get(parent_b)

        if not genome_a:
            return {"error": f"Parent agent '{parent_a}' not found in genesis database"}
        if not genome_b:
            return {"error": f"Parent agent '{parent_b}' not found in genesis database"}

        # Create breeder with specified mutation rate
        breeder = GenomeBreeder(mutation_rate=mutation_rate)

        # Crossover to create offspring
        offspring = breeder.crossover(
            parent_a=genome_a,
            parent_b=genome_b,
            debate_id=f"mcp_breed_{uuid.uuid4().hex[:8]}",
        )

        # Apply mutation
        if mutation_rate > 0:
            offspring = breeder.mutate(offspring, rate=mutation_rate)

        # Save to store
        store.save(offspring)

        return {
            "success": True,
            "offspring": {
                "genome_id": offspring.genome_id,
                "name": offspring.name,
                "generation": offspring.generation,
                "parent_genomes": offspring.parent_genomes,
                "model_preference": offspring.model_preference,
                "fitness_score": offspring.fitness_score,
                "traits_count": len(offspring.traits),
                "expertise_count": len(offspring.expertise),
            },
            "parents": {
                "parent_a": {
                    "genome_id": genome_a.genome_id,
                    "name": genome_a.name,
                    "generation": genome_a.generation,
                },
                "parent_b": {
                    "genome_id": genome_b.genome_id,
                    "name": genome_b.name,
                    "generation": genome_b.generation,
                },
            },
            "mutation_rate": mutation_rate,
        }

    except ImportError:
        return {"error": "Genesis/breeding module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Breeding failed: {e}"}


__all__ = [
    "list_agents_tool",
    "get_agent_history_tool",
    "get_agent_lineage_tool",
    "breed_agents_tool",
]
