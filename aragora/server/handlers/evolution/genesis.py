"""
Genesis (evolution visibility) endpoint handlers.

Endpoints:
- GET /api/genesis/stats - Get overall genesis statistics
- GET /api/genesis/events - Get recent genesis events
- GET /api/genesis/lineage/:genome_id - Get genome ancestry
- GET /api/genesis/tree/:debate_id - Get debate tree structure
- GET /api/genesis/genomes - List all genomes
- GET /api/genesis/genomes/top - Get top genomes by fitness
- GET /api/genesis/genomes/:genome_id - Get single genome details
"""

from __future__ import annotations

__all__ = [
    "GenesisHandler",
]

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.server.validation import validate_debate_id, validate_genome_id
from aragora.server.versioning.compat import strip_version_prefix
from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    json_response,
    safe_json_parse,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for genesis endpoints (10 requests per minute - evolution ops are expensive)
_genesis_limiter = RateLimiter(requests_per_minute=10)

# Lazy imports for optional dependencies using centralized utility
_genesis_imports, GENESIS_AVAILABLE = try_import(
    "aragora.genesis.ledger", "GenesisLedger", "GenesisEventType"
)
GenesisLedger = _genesis_imports["GenesisLedger"]
GenesisEventType = _genesis_imports["GenesisEventType"]

_genome_imports, GENOME_AVAILABLE = try_import(
    "aragora.genesis.genome", "GenomeStore", "AgentGenome"
)
GenomeStore = _genome_imports["GenomeStore"]
AgentGenome = _genome_imports["AgentGenome"]

from aragora.server.errors import safe_error_message as _safe_error_message


class GenesisHandler(BaseHandler):
    """Handler for genesis (evolution visibility) endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/genesis/stats",
        "/api/genesis/events",
        "/api/genesis/genomes",
        "/api/genesis/genomes/top",
        "/api/genesis/genomes/*",
        "/api/genesis/population",
        "/api/genesis/lineage/*",
        "/api/genesis/tree/*",
        "/api/genesis/descendants/*",
        "/api/v1/genesis/stats",
        "/api/v1/genesis/events",
        "/api/v1/genesis/genomes",
        "/api/v1/genesis/genomes/top",
        "/api/v1/genesis/genomes/*",
        "/api/v1/genesis/population",
        "/api/v1/genesis/lineage",
        "/api/v1/genesis/lineage/*",
        "/api/v1/genesis/tree",
        "/api/v1/genesis/tree/*",
        "/api/v1/genesis/descendants",
        "/api/v1/genesis/descendants/*",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in self.ROUTES:
            return True
        # Dynamic routes
        if normalized.startswith("/api/genesis/lineage/"):
            return True
        if normalized.startswith("/api/genesis/tree/"):
            return True
        if (
            normalized.startswith("/api/genesis/genomes/")
            and normalized != "/api/genesis/genomes/top"
        ):
            return True
        if normalized.startswith("/api/genesis/descendants/"):
            return True
        return False

    @require_permission("genesis:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route genesis requests to appropriate methods."""
        normalized = strip_version_prefix(path)
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _genesis_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for genesis endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        nomic_dir = self.ctx.get("nomic_dir")

        if normalized == "/api/genesis/stats":
            return self._get_genesis_stats(nomic_dir)

        if normalized == "/api/genesis/events":
            limit = get_int_param(query_params, "limit", 20)
            limit = min(limit, 100)
            event_type = query_params.get("event_type")
            if isinstance(event_type, list):
                event_type = event_type[0] if event_type else None
            return self._get_genesis_events(nomic_dir, limit, event_type)

        if normalized == "/api/genesis/genomes":
            limit = get_int_param(query_params, "limit", 50)
            limit = min(limit, 200)
            offset = get_int_param(query_params, "offset", 0)
            return self._get_genomes(nomic_dir, limit, offset)

        if normalized == "/api/genesis/genomes/top":
            limit = get_int_param(query_params, "limit", 10)
            limit = min(limit, 50)
            return self._get_top_genomes(nomic_dir, limit)

        if normalized == "/api/genesis/population":
            return self._get_population(nomic_dir)

        if normalized.startswith("/api/genesis/genomes/"):
            # Block path traversal attempts
            if ".." in normalized:
                return error_response("Invalid genome ID", 400)
            genome_id = normalized.split("/")[-1]
            is_valid, err = validate_genome_id(genome_id)
            if not is_valid:
                return error_response(err, 400)
            return self._get_genome(nomic_dir, genome_id)

        if normalized.startswith("/api/genesis/lineage/"):
            # Block path traversal attempts
            if ".." in normalized:
                return error_response("Invalid genome ID", 400)
            genome_id = normalized.split("/")[-1]
            is_valid, err = validate_genome_id(genome_id)
            if not is_valid:
                return error_response(err, 400)
            max_depth = get_int_param(query_params, "max_depth", 10)
            max_depth = min(max(max_depth, 1), 50)  # Clamp to 1-50
            return self._get_genome_lineage(nomic_dir, genome_id, max_depth)

        if normalized.startswith("/api/genesis/tree/"):
            # Block path traversal attempts
            if ".." in normalized:
                return error_response("Invalid debate ID", 400)
            debate_id = normalized.split("/")[-1]
            is_valid, err = validate_debate_id(debate_id)
            if not is_valid:
                return error_response(err, 400)
            return self._get_debate_tree(nomic_dir, debate_id)

        if normalized.startswith("/api/genesis/descendants/"):
            # Block path traversal attempts
            if ".." in normalized:
                return error_response("Invalid genome ID", 400)
            genome_id = normalized.split("/")[-1]
            is_valid, err = validate_genome_id(genome_id)
            if not is_valid:
                return error_response(err, 400)
            max_depth = get_int_param(query_params, "max_depth", 5)
            max_depth = min(max(max_depth, 1), 20)
            return self._get_genome_descendants(nomic_dir, genome_id, max_depth)

        return None

    def _get_genesis_stats(self, nomic_dir: Path | None) -> HandlerResult:
        """Get overall genesis statistics for evolution visibility."""
        if not GENESIS_AVAILABLE:
            return error_response("Genesis module not available", 503)

        try:
            ledger_path = "genesis.db"
            if nomic_dir:
                ledger_path = str(nomic_dir / "genesis.db")

            ledger = GenesisLedger(ledger_path)

            # Count events by type
            event_counts = {}
            for event_type in GenesisEventType:
                events = ledger.get_events_by_type(event_type)
                event_counts[event_type.value] = len(events)

            # Get recent births and deaths
            births = ledger.get_events_by_type(GenesisEventType.AGENT_BIRTH)
            deaths = ledger.get_events_by_type(GenesisEventType.AGENT_DEATH)

            # Get fitness updates for trend
            fitness_updates = ledger.get_events_by_type(GenesisEventType.FITNESS_UPDATE)
            avg_fitness_change = 0.0
            if fitness_updates:
                changes = [e.data.get("change", 0) for e in fitness_updates[-50:]]
                avg_fitness_change = sum(changes) / len(changes) if changes else 0.0

            return json_response(
                {
                    "event_counts": event_counts,
                    "total_events": sum(event_counts.values()),
                    "total_births": len(births),
                    "total_deaths": len(deaths),
                    "net_population_change": len(births) - len(deaths),
                    "avg_fitness_change_recent": round(avg_fitness_change, 4),
                    "integrity_verified": ledger.verify_integrity(),
                    "merkle_root": ledger.get_merkle_root()[:32] + "...",
                }
            )
        except Exception as e:  # noqa: BLE001 - handler catch-all returns 500
            return error_response(_safe_error_message(e, "genesis_stats"), 500)

    def _get_genesis_events(
        self, nomic_dir: Path | None, limit: int, event_type: str | None
    ) -> HandlerResult:
        """Get recent genesis events."""
        if not GENESIS_AVAILABLE:
            return error_response("Genesis module not available", 503)

        try:
            ledger_path = "genesis.db"
            if nomic_dir:
                ledger_path = str(nomic_dir / "genesis.db")

            # Filter by type if specified
            if event_type:
                # Validate event_type: must be alphanumeric/underscore and bounded length
                if not isinstance(event_type, str) or len(event_type) > 64:
                    return error_response("Invalid event type parameter", 400)
                import re as _re

                if not _re.fullmatch(r"[a-zA-Z0-9_]+", event_type):
                    return error_response("Invalid event type parameter", 400)

                # Validate against known enum values
                valid_types = {et.value for et in GenesisEventType}
                if event_type not in valid_types:
                    return error_response(
                        "Unknown event type. Valid types: " + ", ".join(sorted(valid_types)),
                        400,
                    )

                etype = GenesisEventType(event_type)
                ledger = GenesisLedger(ledger_path)
                events = ledger.get_events_by_type(etype)[-limit:]
                return json_response(
                    {
                        "events": [e.to_dict() for e in events],
                        "count": len(events),
                        "filter": event_type,
                    }
                )

            # Get all recent events
            ledger = GenesisLedger(ledger_path)
            with ledger.db.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT event_id, event_type, timestamp, parent_event_id, content_hash, data
                    FROM genesis_events
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (limit,),
                )

                events = []
                for row in cursor.fetchall():
                    events.append(
                        {
                            "event_id": row[0],
                            "event_type": row[1],
                            "timestamp": row[2],
                            "parent_event_id": row[3],
                            "content_hash": row[4][:16] + "..." if row[4] else None,
                            "data": safe_json_parse(row[5], {}),
                        }
                    )

            return json_response(
                {
                    "events": events,
                    "count": len(events),
                }
            )
        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "genesis_events"), 500)

    def _get_genome_lineage(
        self, nomic_dir: Path | None, genome_id: str, max_depth: int = 10
    ) -> HandlerResult:
        """Get the lineage (ancestry) of a genome.

        Returns enriched lineage data including event types and timestamps.

        Parameters:
            genome_id: The genome to trace
            max_depth: Maximum depth to trace (default 10)

        Response:
        {
            "genome_id": "genome_abc",
            "lineage": [
                {
                    "genome_id": "...",
                    "name": "...",
                    "generation": 5,
                    "fitness_score": 0.85,
                    "parent_ids": [...],
                    "event_type": "mutation",
                    "created_at": "2026-01-13T..."
                }
            ],
            "generations": 5
        }
        """
        if not GENESIS_AVAILABLE:
            return error_response("Genesis module not available", 503)

        try:
            ledger_path = "genesis.db"
            if nomic_dir:
                ledger_path = str(nomic_dir / "genesis.db")

            ledger = GenesisLedger(ledger_path)

            # Get basic lineage
            basic_lineage = ledger.get_lineage(genome_id)

            if not basic_lineage:
                return error_response(f"Genome not found: {genome_id}", 404)

            # Enrich with event data
            enriched_lineage = []
            for i, node in enumerate(basic_lineage[:max_depth]):
                enriched_node = {
                    "genome_id": node.get("genome_id"),
                    "name": node.get("name"),
                    "generation": node.get("generation", 0),
                    "fitness_score": node.get("fitness_score"),
                    "parent_ids": node.get("parent_genomes", []),
                }

                # Try to get creation event for this genome
                try:
                    birth_events = ledger.get_events_by_type(GenesisEventType.AGENT_BIRTH)
                    for event in birth_events:
                        if event.data.get("genome_id") == node.get("genome_id"):
                            enriched_node["event_type"] = "agent_birth"
                            enriched_node["created_at"] = event.timestamp
                            break

                    # Also check mutation events
                    if "event_type" not in enriched_node:
                        mutation_events = ledger.get_events_by_type(GenesisEventType.MUTATION)
                        for event in mutation_events:
                            if event.data.get("genome_id") == node.get("genome_id"):
                                enriched_node["event_type"] = "mutation"
                                enriched_node["created_at"] = event.timestamp
                                break

                    # Check crossover events
                    if "event_type" not in enriched_node:
                        crossover_events = ledger.get_events_by_type(GenesisEventType.CROSSOVER)
                        for event in crossover_events:
                            if event.data.get("genome_id") == node.get("genome_id"):
                                enriched_node["event_type"] = "crossover"
                                enriched_node["created_at"] = event.timestamp
                                break
                except Exception as e:  # noqa: BLE001 - graceful degradation, lineage works without event details
                    logger.debug(
                        "Optional event lookup failed for genome lineage: %s", type(e).__name__
                    )

                enriched_lineage.append(enriched_node)

            return json_response(
                {
                    "genome_id": genome_id,
                    "lineage": enriched_lineage,
                    "generations": len(enriched_lineage),
                }
            )

        except Exception as e:  # noqa: BLE001 - handler catch-all returns 500
            return error_response(_safe_error_message(e, "genome_lineage"), 500)

    def _get_debate_tree(self, nomic_dir: Path | None, debate_id: str) -> HandlerResult:
        """Get the fractal tree structure for a debate."""
        if not GENESIS_AVAILABLE:
            return error_response("Genesis module not available", 503)

        try:
            ledger_path = "genesis.db"
            if nomic_dir:
                ledger_path = str(nomic_dir / "genesis.db")

            ledger = GenesisLedger(ledger_path)
            tree = ledger.get_debate_tree(debate_id)

            return json_response(
                {
                    "debate_id": debate_id,
                    "tree": tree.to_dict(),
                    "total_nodes": len(tree.nodes),
                }
            )

        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "debate_tree"), 500)

    def _get_genomes(self, nomic_dir: Path | None, limit: int, offset: int) -> HandlerResult:
        """Get all genomes with pagination."""
        if not GENOME_AVAILABLE:
            return error_response("Genesis genome module not available", 503)

        try:
            db_path = "genesis.db"
            if nomic_dir:
                db_path = str(nomic_dir / "genesis.db")

            store = GenomeStore(db_path)
            all_genomes = store.get_all()

            # Apply pagination
            total = len(all_genomes)
            paginated = all_genomes[offset : offset + limit]

            return json_response(
                {
                    "genomes": [g.to_dict() for g in paginated],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "genomes_list"), 500)

    def _get_top_genomes(self, nomic_dir: Path | None, limit: int) -> HandlerResult:
        """Get top genomes by fitness score."""
        if not GENOME_AVAILABLE:
            return error_response("Genesis genome module not available", 503)

        try:
            db_path = "genesis.db"
            if nomic_dir:
                db_path = str(nomic_dir / "genesis.db")

            store = GenomeStore(db_path)
            top_genomes = store.get_top_by_fitness(limit)

            return json_response(
                {
                    "genomes": [g.to_dict() for g in top_genomes],
                    "count": len(top_genomes),
                }
            )

        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "genomes_top"), 500)

    def _get_genome(self, nomic_dir: Path | None, genome_id: str) -> HandlerResult:
        """Get a single genome by ID."""
        if not GENOME_AVAILABLE:
            return error_response("Genesis genome module not available", 503)

        try:
            db_path = "genesis.db"
            if nomic_dir:
                db_path = str(nomic_dir / "genesis.db")

            store = GenomeStore(db_path)
            genome = store.get(genome_id)

            if genome:
                return json_response(
                    {
                        "genome": genome.to_dict(),
                    }
                )
            else:
                return error_response(f"Genome not found: {genome_id}", 404)

        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "genome_get"), 500)

    def _get_population(self, nomic_dir: Path | None) -> HandlerResult:
        """Get the active population and its status.

        Returns:
            Population details including genomes, generation, and average fitness
        """
        try:
            db_path = "genesis.db"
            if nomic_dir:
                db_path = str(nomic_dir / "genesis.db")

            # Try to import PopulationManager
            try:
                from aragora.genesis.breeding import PopulationManager
            except ImportError:
                return error_response("Genesis breeding module not available", 503)

            manager = PopulationManager(db_path=db_path)

            # Get or create population with common agent names
            population = manager.get_or_create_population(
                base_agents=["claude", "gemini", "codex", "grok"]
            )

            # Build response
            genomes_list: list[dict] = []
            result: dict = {
                "population_id": population.population_id,
                "generation": population.generation,
                "size": population.size,
                "average_fitness": population.average_fitness,
                "genomes": genomes_list,
                "best_genome": None,
                "debate_history_count": len(population.debate_history),
            }

            # Add genome summaries
            for genome in population.genomes:
                # Get top traits and expertise
                top_traits = (
                    genome.get_dominant_traits(3)
                    if hasattr(genome, "get_dominant_traits")
                    else list(genome.traits.keys())[:3]
                )
                top_expertise = list(genome.expertise.keys())[:3] if genome.expertise else []

                result["genomes"].append(
                    {
                        "genome_id": genome.genome_id,
                        "agent_name": genome.name,  # Use 'name' not 'agent_name'
                        "fitness_score": genome.fitness_score,
                        "generation": genome.generation,
                        "personality_traits": top_traits,
                        "expertise_domains": top_expertise,
                    }
                )

            # Add best genome
            best = population.best_genome
            if best:
                result["best_genome"] = {
                    "genome_id": best.genome_id,
                    "agent_name": best.name,  # Use 'name' not 'agent_name'
                    "fitness_score": best.fitness_score,
                }

            return json_response(result)

        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "population"), 500)

    def _get_genome_descendants(
        self, nomic_dir: Path | None, genome_id: str, max_depth: int = 5
    ) -> HandlerResult:
        """Get all descendants of a genome (genomes that have this as ancestor).

        This is useful for visualizing the "family tree" going forward from
        a specific genome to see what evolved from it.

        Parameters:
            genome_id: The genome to find descendants of
            max_depth: Maximum depth to search (default 5)

        Response:
        {
            "genome_id": "genome_abc",
            "descendants": [
                {
                    "genome_id": "...",
                    "name": "...",
                    "generation": 6,
                    "fitness_score": 0.87,
                    "parent_ids": [...],
                    "depth": 1
                }
            ],
            "total_descendants": 15,
            "max_generation": 8
        }
        """
        if not GENOME_AVAILABLE:
            return error_response("Genesis genome module not available", 503)

        try:
            db_path = "genesis.db"
            if nomic_dir:
                db_path = str(nomic_dir / "genesis.db")

            store = GenomeStore(db_path)

            # Verify the root genome exists
            root = store.get(genome_id)
            if not root:
                return error_response(f"Genome not found: {genome_id}", 404)

            # Get all genomes and find descendants by traversing parent links
            all_genomes = store.get_all()

            # Build a mapping of genome_id -> genomes that have it as a parent
            children_map: dict[str, list] = {}
            for g in all_genomes:
                for parent_id in g.parent_genomes or []:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(g)

            # BFS to find all descendants
            descendants = []
            visited = {genome_id}
            queue = [(genome_id, 0)]
            max_generation = root.generation

            while queue:
                current_id, depth = queue.pop(0)

                if depth >= max_depth:
                    continue

                for child in children_map.get(current_id, []):
                    if child.genome_id not in visited:
                        visited.add(child.genome_id)
                        descendants.append(
                            {
                                "genome_id": child.genome_id,
                                "name": child.name,
                                "generation": child.generation,
                                "fitness_score": child.fitness_score,
                                "parent_ids": child.parent_genomes or [],
                                "depth": depth + 1,
                            }
                        )
                        queue.append((child.genome_id, depth + 1))
                        max_generation = max(max_generation, child.generation)

            # Sort by depth, then by fitness
            descendants.sort(key=lambda x: (x["depth"], -(x["fitness_score"] or 0)))

            return json_response(
                {
                    "genome_id": genome_id,
                    "root_genome": {
                        "name": root.name,
                        "generation": root.generation,
                        "fitness_score": root.fitness_score,
                    },
                    "descendants": descendants,
                    "total_descendants": len(descendants),
                    "max_generation": max_generation,
                }
            )

        except (KeyError, ValueError, AttributeError, OSError) as e:
            return error_response(_safe_error_message(e, "genome_descendants"), 500)
