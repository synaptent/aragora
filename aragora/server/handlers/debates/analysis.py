"""
Analysis operations handler mixin.

Extracted from handler.py for modularity. Provides meta-critique analysis
and argument graph statistics methods.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    json_response,
)
from ..openapi_decorator import api_endpoint

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by AnalysisOperationsMixin.

    This protocol enables proper type checking for mixin classes that
    expect to be mixed into a class providing these methods/attributes.
    """

    ctx: dict[str, Any]

    def get_storage(self) -> Any | None:
        """Get debate storage instance."""
        ...

    def get_nomic_dir(self) -> Path | None:
        """Get nomic directory path."""
        ...


class AnalysisOperationsMixin:
    """Mixin providing analysis operations for DebatesHandler."""

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/meta-critique",
        summary="Get meta-critique analysis",
        description="Get meta-level analysis of a debate including repetition and circular argument detection.",
        tags=["Debates", "Analysis"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {
                "description": "Meta-critique analysis returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debate_id": {"type": "string"},
                                "overall_quality": {"type": "number"},
                                "productive_rounds": {"type": "integer"},
                                "unproductive_rounds": {"type": "integer"},
                                "observations": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "type": {"type": "string"},
                                            "severity": {"type": "number"},
                                            "agent": {"type": "string"},
                                            "round": {"type": "integer"},
                                            "description": {"type": "string"},
                                        },
                                    },
                                },
                                "recommendations": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate trace not found"},
            "503": {"description": "Module not available"},
        },
    )
    @require_permission("analysis:read")
    def _get_meta_critique(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """Get meta-level analysis of a debate (repetition, circular arguments, etc)."""
        from aragora.exceptions import (
            DatabaseError,
            RecordNotFoundError,
            StorageError,
        )

        try:
            from aragora.debate.meta import MetaCritiqueAnalyzer
            from aragora.debate.traces import DebateTrace
        except ImportError:
            return error_response("Meta critique module not available", 503)

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        try:
            trace_path = nomic_dir / "traces" / f"{debate_id}.json"
            if not trace_path.exists():
                return error_response("Debate trace not found", 404)

            trace = DebateTrace.load(trace_path)
            result = trace.to_debate_result()

            analyzer = MetaCritiqueAnalyzer()
            critique = analyzer.analyze(result)

            return json_response(
                {
                    "debate_id": debate_id,
                    "overall_quality": critique.overall_quality,
                    "productive_rounds": critique.productive_rounds,
                    "unproductive_rounds": critique.unproductive_rounds,
                    "observations": [
                        {
                            "type": o.observation_type,
                            "severity": o.severity,
                            "agent": getattr(o, "agent", None),
                            "round": getattr(o, "round_num", None),
                            "description": o.description,
                        }
                        for o in critique.observations
                    ],
                    "recommendations": critique.recommendations,
                }
            )
        except RecordNotFoundError:
            logger.info("Meta critique failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Failed to get meta critique for %s: %s: %s",
                debate_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response("Database error retrieving meta critique", 500)
        except ValueError as e:
            logger.warning("Invalid meta critique request for %s: %s", debate_id, e)
            return error_response("Invalid request", 400)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/argument-graph",
        summary="Get argument graph",
        description="Reconstruct the full argument graph for a debate. Supports JSON and Mermaid output formats.",
        tags=["Debates", "Analysis"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
            {
                "name": "format",
                "in": "query",
                "schema": {"type": "string", "enum": ["json", "mermaid"]},
                "required": False,
            },
        ],
        responses={
            "200": {"description": "Argument graph returned"},
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
            "503": {"description": "Module not available"},
        },
    )
    @require_permission("analysis:read")
    def _get_argument_graph(
        self: _DebatesHandlerProtocol,
        debate_id: str,
        output_format: str = "json",
    ) -> HandlerResult:
        """Get the full argument graph for a debate.

        Reconstructs the graph from stored debate messages via ArgumentCartographer.
        Supports JSON (default) and Mermaid diagram output.
        """
        import json as json_mod

        from aragora.exceptions import (
            DatabaseError,
            RecordNotFoundError,
            StorageError,
        )

        try:
            from aragora.debate.traces import DebateTrace
            from aragora.visualization.mapper import ArgumentCartographer
        except ImportError:
            return error_response("Graph analysis module not available", 503)

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        try:
            trace_path = nomic_dir / "traces" / f"{debate_id}.json"
            if not trace_path.exists():
                return error_response("Debate not found", 404)

            trace = DebateTrace.load(trace_path)
            result = trace.to_debate_result()

            cartographer = ArgumentCartographer()
            cartographer.set_debate_context(debate_id, result.task or "")

            for msg in result.messages:
                cartographer.update_from_message(
                    agent=msg.agent,
                    content=msg.content,
                    role=msg.role,
                    round_num=msg.round,
                )

            for critique in result.critiques:
                cartographer.update_from_critique(
                    critic_agent=critique.agent,
                    target_agent=critique.target or "",
                    severity=critique.severity,
                    round_num=getattr(critique, "round", 1),
                    critique_text=critique.reasoning,
                )

            if output_format == "mermaid":
                mermaid_code = cartographer.export_mermaid()
                return json_response(
                    {
                        "debate_id": debate_id,
                        "format": "mermaid",
                        "graph": mermaid_code,
                    }
                )

            # Default: JSON graph
            graph_json = json_mod.loads(cartographer.export_json())
            return json_response(
                {
                    "debate_id": debate_id,
                    "format": "json",
                    "graph": graph_json,
                }
            )

        except RecordNotFoundError:
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Failed to get argument graph for %s: %s: %s",
                debate_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response("Database error retrieving argument graph", 500)
        except ValueError as e:
            logger.warning("Invalid argument graph request for %s: %s", debate_id, e)
            return error_response("Invalid request", 400)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/graph/stats",
        summary="Get argument graph statistics",
        description="Get argument graph statistics including node counts, edge counts, depth, and complexity.",
        tags=["Debates", "Analysis"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {
                "description": "Graph statistics returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "node_count": {"type": "integer"},
                                "edge_count": {"type": "integer"},
                                "depth": {"type": "integer"},
                                "clusters": {"type": "integer"},
                                "avg_branching_factor": {"type": "number"},
                                "avg_path_length": {"type": "number"},
                            },
                        },
                    },
                },
            },
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
            "503": {"description": "Module not available"},
        },
    )
    @require_permission("analysis:read")
    def _get_graph_stats(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """Get argument graph statistics for a debate.

        Returns node counts, edge counts, depth, branching factor, and complexity.
        """
        from aragora.exceptions import (
            DatabaseError,
            RecordNotFoundError,
            StorageError,
        )

        try:
            from aragora.debate.traces import DebateTrace
            from aragora.visualization.mapper import ArgumentCartographer
        except ImportError:
            return error_response("Graph analysis module not available", 503)

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        try:
            trace_path = nomic_dir / "traces" / f"{debate_id}.json"

            if not trace_path.exists():
                # Try replays directory as fallback
                replay_path = nomic_dir / "replays" / debate_id / "events.jsonl"
                if replay_path.exists():
                    return _build_graph_from_replay(debate_id, replay_path)
                return error_response("Debate trace not found", 404)

            # Load from trace file
            trace = DebateTrace.load(trace_path)
            result = trace.to_debate_result()

            # Build cartographer from debate result
            cartographer = ArgumentCartographer()
            cartographer.set_debate_context(debate_id, result.task or "")

            # Process messages from the debate
            for msg in result.messages:
                cartographer.update_from_message(
                    agent=msg.agent,
                    content=msg.content,
                    role=msg.role,
                    round_num=msg.round,
                )

            # Process critiques
            for critique in result.critiques:
                cartographer.update_from_critique(
                    critic_agent=critique.agent,
                    target_agent=critique.target or "",
                    severity=critique.severity,
                    round_num=getattr(critique, "round", 1),
                    critique_text=critique.reasoning,
                )

            stats = cartographer.get_statistics()
            return json_response(stats)

        except RecordNotFoundError:
            logger.info("Graph stats failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Failed to get graph stats for %s: %s: %s",
                debate_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response("Database error retrieving graph stats", 500)
        except ValueError as e:
            logger.warning("Invalid graph stats request for %s: %s", debate_id, e)
            return error_response("Invalid request", 400)

    def _get_rhetorical_observations(
        self: _DebatesHandlerProtocol, debate_id: str
    ) -> HandlerResult:
        """Get rhetorical pattern observations for a debate.

        Returns detected patterns like concession, rebuttal, synthesis,
        with audience-friendly commentary.
        """
        from aragora.exceptions import RecordNotFoundError

        try:
            from aragora.debate.rhetorical_observer import (
                RhetoricalAnalysisObserver,
                RhetoricalPattern,
            )
            from aragora.debate.traces import DebateTrace
        except ImportError:
            return error_response("Rhetorical observer module not available", 503)

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        try:
            trace_path = nomic_dir / "traces" / f"{debate_id}.json"
            if not trace_path.exists():
                return error_response("Debate trace not found", 404)

            trace = DebateTrace.load(trace_path)
            result = trace.to_debate_result()

            # Create observer and analyze messages
            observer = RhetoricalAnalysisObserver()
            all_observations = []

            for msg in result.messages:
                observations = observer.observe(
                    agent=msg.agent,
                    content=msg.content,
                    round_num=msg.round,
                )
                all_observations.extend([obs.to_dict() for obs in observations])

            # Get debate dynamics summary
            dynamics = observer.get_debate_dynamics()

            return json_response(
                {
                    "debate_id": debate_id,
                    "observations": all_observations,
                    "dynamics": dynamics,
                    "pattern_counts": {
                        pattern.value: sum(
                            1 for o in all_observations if o["pattern"] == pattern.value
                        )
                        for pattern in RhetoricalPattern
                    },
                    "total_observations": len(all_observations),
                }
            )
        except RecordNotFoundError:
            logger.info("Rhetorical analysis failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.error(
                "Failed to get rhetorical observations for %s: %s",
                debate_id,
                e,
                exc_info=True,
            )
            return error_response("Error analyzing rhetorical patterns", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/trickster",
        summary="Get trickster status",
        description="Get hollow consensus detection status and any trickster interventions for a debate.",
        tags=["Debates", "Analysis"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {"description": "Trickster status returned"},
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
            "503": {"description": "Module not available"},
        },
    )
    def _get_trickster_status(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """Get trickster intervention status for a debate.

        Returns hollow consensus alerts and any interventions that were triggered.
        """
        from aragora.exceptions import RecordNotFoundError

        try:
            from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig
            from aragora.debate.traces import DebateTrace
        except ImportError:
            return error_response("Trickster module not available", 503)

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        try:
            trace_path = nomic_dir / "traces" / f"{debate_id}.json"
            if not trace_path.exists():
                return error_response("Debate trace not found", 404)

            trace = DebateTrace.load(trace_path)
            result = trace.to_debate_result()

            # Create trickster and analyze the debate
            config = TricksterConfig()
            trickster = EvidencePoweredTrickster(config)

            # Analyze evidence quality across rounds
            alerts = []
            interventions = []

            for round_num in range(1, result.rounds_used + 1):
                # Check for hollow consensus via check_and_intervene
                messages = [m for m in result.messages if getattr(m, "round", 0) == round_num]
                responses = {
                    getattr(m, "agent", "unknown"): getattr(m, "content", "") for m in messages
                }
                intervention = trickster.check_and_intervene(
                    responses=responses,
                    convergence_similarity=getattr(result, "convergence_similarity", 0.0),
                    round_num=round_num,
                )
                if intervention:
                    alerts.append(
                        {
                            "round": round_num,
                            "severity": getattr(intervention, "severity", "medium"),
                            "intervention_type": intervention.intervention_type.value,
                        }
                    )
                    interventions.append(
                        {
                            "round": round_num,
                            "type": intervention.intervention_type.value,
                            "target_agents": intervention.target_agents,
                            "challenge": intervention.challenge_text,
                            "priority": intervention.priority,
                        }
                    )

            return json_response(
                {
                    "debate_id": debate_id,
                    "trickster_enabled": True,
                    "hollow_consensus_alerts": alerts,
                    "interventions": interventions,
                    "total_alerts": len(alerts),
                    "total_interventions": len(interventions),
                    "config": {
                        "sensitivity": config.sensitivity,
                        "min_quality_threshold": config.min_quality_threshold,
                        "hollow_detection_threshold": config.hollow_detection_threshold,
                    },
                }
            )
        except RecordNotFoundError:
            logger.info("Trickster analysis failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.error(
                "Failed to get trickster status for %s: %s",
                debate_id,
                e,
                exc_info=True,
            )
            return error_response("Error analyzing trickster status", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/positions",
        summary="Get position evolution",
        description="Get per-agent stance evolution across rounds with pivot point detection.",
        tags=["Debates", "Analysis"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {"description": "Position evolution data returned"},
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
            "503": {"description": "Module not available"},
        },
    )
    @require_permission("analysis:read")
    def _get_positions(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """Get per-agent stance evolution across rounds with pivot point detection."""
        from aragora.exceptions import RecordNotFoundError

        try:
            from aragora.debate.traces import DebateTrace
            from aragora.reasoning.position_tracker import (
                PositionStance,
                PositionTracker,
            )
        except ImportError:
            return error_response("Position tracking module not available", 503)

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        try:
            trace_path = nomic_dir / "traces" / f"{debate_id}.json"
            if not trace_path.exists():
                return error_response("Debate trace not found", 404)

            trace = DebateTrace.load(trace_path)
            result = trace.to_debate_result()

            # Build position evolution from debate messages
            tracker = PositionTracker()
            evolution = tracker.create_evolution(debate_id, result.task)

            for msg in result.messages:
                # Infer stance from sentiment/content heuristics
                content_lower = msg.content.lower() if msg.content else ""
                if any(
                    w in content_lower for w in ("strongly agree", "fully support", "absolutely")
                ):
                    stance = PositionStance.STRONGLY_AGREE
                elif any(w in content_lower for w in ("agree", "support", "endorse")):
                    stance = PositionStance.AGREE
                elif any(w in content_lower for w in ("disagree", "oppose", "reject")):
                    stance = PositionStance.DISAGREE
                elif any(w in content_lower for w in ("strongly disagree", "completely oppose")):
                    stance = PositionStance.STRONGLY_DISAGREE
                elif any(w in content_lower for w in ("lean toward", "somewhat")):
                    stance = PositionStance.LEAN_AGREE
                else:
                    stance = PositionStance.NEUTRAL

                confidence = getattr(msg, "confidence", 0.5) or 0.5
                evolution.record_position(
                    agent=msg.agent,
                    round_number=msg.round,
                    stance=stance,
                    confidence=confidence,
                    key_argument=(msg.content or "")[:200],
                )

            return json_response(evolution.to_dict())
        except RecordNotFoundError:
            logger.info("Position analysis failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.error(
                "Failed to get positions for %s: %s",
                debate_id,
                e,
                exc_info=True,
            )
            return error_response("Error analyzing position evolution", 500)


def _build_graph_from_replay(debate_id: str, replay_path: Path) -> HandlerResult:
    """Build graph stats from replay events file."""
    import json as json_mod

    from aragora.exceptions import (
        DatabaseError,
        StorageError,
    )

    try:
        from aragora.visualization.mapper import ArgumentCartographer
    except ImportError:
        return error_response("Graph analysis module not available", 503)

    try:
        cartographer = ArgumentCartographer()
        cartographer.set_debate_context(debate_id, "")

        with replay_path.open() as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        event = json_mod.loads(line)
                    except json_mod.JSONDecodeError:
                        logger.warning("Skipping malformed JSONL line %s", line_num)
                        continue

                    if event.get("type") == "agent_message":
                        cartographer.update_from_message(
                            agent=event.get("agent", "unknown"),
                            content=event.get("data", {}).get("content", ""),
                            role=event.get("data", {}).get("role", "proposer"),
                            round_num=event.get("round", 1),
                        )
                    elif event.get("type") == "critique":
                        cartographer.update_from_critique(
                            critic_agent=event.get("agent", "unknown"),
                            target_agent=event.get("data", {}).get("target", "unknown"),
                            severity=event.get("data", {}).get("severity", 0.5),
                            round_num=event.get("round", 1),
                            critique_text=event.get("data", {}).get("content", ""),
                        )

        stats = cartographer.get_statistics()
        return json_response(stats)
    except FileNotFoundError:
        logger.info("Build graph failed - replay file not found: %s", replay_path)
        return error_response(f"Replay file not found: {debate_id}", 404)
    except (StorageError, DatabaseError) as e:
        logger.error(
            "Failed to build graph from replay %s: %s: %s",
            debate_id,
            type(e).__name__,
            e,
            exc_info=True,
        )
        return error_response("Database error building graph", 500)
    except ValueError as e:
        logger.warning("Invalid replay data for %s: %s", debate_id, e)
        return error_response("Invalid replay data", 400)


__all__ = ["AnalysisOperationsMixin"]
