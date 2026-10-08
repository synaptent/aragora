"""
Fork and follow-up debate operations handler mixin.

Extracted from debates.py for modularity. Provides counterfactual forking,
outcome verification, and crux-based follow-up debate creation.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from aragora.rbac.decorators import require_permission
from aragora.tenancy.record_scope import OrgScope

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    require_storage,
    safe_error_message,
)
from ..openapi_decorator import api_endpoint
from ..utils.rate_limit import rate_limit, user_rate_limit

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _owner_fields(scope: OrgScope | None) -> dict[str, str | None]:
    """The org and user a fork or follow-up record is created for."""
    if scope is None:
        return {"org_id": None, "created_by": None}
    return {"org_id": scope.org_id, "created_by": scope.user_id}


def _new_followup_id() -> str:
    return f"followup-{uuid.uuid4().hex}"


def _write_new_followup(followups_dir: Path, record: dict[str, Any]) -> str:
    """Store ``record`` under a fresh id and return the id.

    The record is written to a temporary file and hard-linked into place, so a
    write that fails partway leaves no follow-up file, and an existing one is
    never replaced (the link fails instead and a fresh id is tried).
    """
    for _attempt in range(2):
        fd, tmp_name = tempfile.mkstemp(dir=followups_dir, prefix=".followup-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(record, f, indent=2)
            os.link(tmp_name, followups_dir / f"{record['id']}.json")
            return record["id"]
        except FileExistsError:
            record["id"] = _new_followup_id()
        finally:
            Path(tmp_name).unlink(missing_ok=True)
    raise OSError("Could not allocate an unused follow-up id")


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by ForkOperationsMixin.

    This protocol enables proper type checking for mixin classes that
    expect to be mixed into a class providing these methods/attributes.
    """

    ctx: dict[str, Any]

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        """Read and parse JSON body from request handler."""
        ...

    def get_storage(self) -> Any:
        """Get debate storage instance (``@require_storage`` routes never see None)."""
        ...

    def get_nomic_dir(self) -> Path | None:
        """Get nomic directory path."""
        ...


class ForkOperationsMixin:
    """Mixin providing fork and follow-up operations for DebatesHandler."""

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{debate_id}/fork",
        summary="Fork a debate",
        description="Create a counterfactual fork of a debate at a specific branch point.",
        tags=["Debates", "Fork"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {
                "description": "Fork created successfully",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "branch_id": {"type": "string"},
                                "parent_debate_id": {"type": "string"},
                                "branch_point": {"type": "integer"},
                                "messages_inherited": {"type": "integer"},
                                "modified_context": {"type": "string"},
                                "status": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "400": {"description": "Invalid request"},
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
        },
    )
    @require_permission("debates:create")
    @user_rate_limit(action="debate_create")
    @rate_limit(requests_per_minute=5, limiter_name="debates_fork")
    @require_storage
    def _fork_debate(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate_id: str,
        *,
        scope: OrgScope | None = None,
    ) -> HandlerResult:
        """Create a counterfactual fork of a debate at a specific branch point.

        The fork record is stamped with ``scope``'s org and user.

        Request body:
            {
                "branch_point": int,  # Round number to branch from
                "modified_context": str  # Optional: context for the counterfactual
            }

        Returns:
            Information about the created branch
        """
        from aragora.server.validation import FORK_REQUEST_SCHEMA, validate_against_schema

        # Read and validate request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        validation = validate_against_schema(body, FORK_REQUEST_SCHEMA)
        if not validation.is_valid:
            return error_response(validation.error, 400)

        branch_point = body.get("branch_point", 0)
        modified_context = body.get("modified_context")

        # Get the original debate
        storage = self.get_storage()
        try:
            debate = storage.get_debate(debate_id)
            if not debate:
                return error_response(f"Debate not found: {debate_id}", 404)

            messages = debate.get("messages", [])
            if branch_point > len(messages):
                return error_response(
                    f"Branch point {branch_point} exceeds message count {len(messages)}", 400
                )

            # Import counterfactual module
            try:
                from aragora.debate.counterfactual import (
                    CounterfactualBranch,
                    PivotClaim,
                )
            except ImportError as e:
                module_name = getattr(e, "name", None)
                logger.error("Failed to import counterfactual module: %s", e, exc_info=True)
                if "counterfactual" in str(module_name or e).lower():
                    return error_response("Counterfactual forking feature not available", 503)
                else:
                    return error_response("Internal error loading fork feature", 500)

            # Create a pivot claim from the context
            import uuid as uuid_mod

            pivot = PivotClaim(
                claim_id=f"pivot-{uuid_mod.uuid4().hex[:8]}",
                statement=modified_context or f"Branch at round {branch_point}",
                author="user",
                disagreement_score=1.0,
                importance_score=1.0,
                blocking_agents=[],
                branch_reason=f"User-initiated fork at round {branch_point}",
            )

            # Create the branch record
            branch_id = f"fork-{debate_id}-r{branch_point}-{uuid_mod.uuid4().hex[:8]}"

            branch = CounterfactualBranch(
                branch_id=branch_id,
                parent_debate_id=debate_id,
                pivot_claim=pivot,
                assumption=True,  # Default to exploring the "true" branch
                messages=messages[:branch_point] if branch_point > 0 else [],
            )

            # Store the branch info
            branch_data = {
                "branch_id": branch.branch_id,
                "parent_debate_id": branch.parent_debate_id,
                "branch_point": branch_point,
                "modified_context": modified_context,
                "pivot_claim": branch.pivot_claim.statement,
                "status": "created",
                "messages_inherited": branch_point,
                **_owner_fields(scope),
            }

            # Try to store in nomic dir
            nomic_dir = self.get_nomic_dir()
            if nomic_dir:
                import json as json_mod

                branches_dir = nomic_dir / "branches"
                branches_dir.mkdir(exist_ok=True)
                branch_file = branches_dir / f"{branch_id}.json"
                with open(branch_file, "w") as f:
                    json_mod.dump(branch_data, f, indent=2)

            return json_response(
                {
                    "success": True,
                    "branch_id": branch_id,
                    "parent_debate_id": debate_id,
                    "branch_point": branch_point,
                    "messages_inherited": branch_point,
                    "modified_context": modified_context,
                    "status": "created",
                    "message": f"Created fork '{branch_id}' from debate '{debate_id}' at round {branch_point}",
                }
            )

        except (KeyError, ValueError, TypeError, AttributeError, OSError, RuntimeError) as e:
            logger.error(
                "Failed to create fork for %s at round %s: %s: %s",
                debate_id,
                branch_point,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response(safe_error_message(e, "create fork"), 500)

    @user_rate_limit(action="vote")
    @rate_limit(requests_per_minute=10, limiter_name="debates_verify_outcome")
    @handle_errors("verify debate outcome")
    def _verify_outcome(
        self: _DebatesHandlerProtocol, handler: Any, debate_id: str
    ) -> HandlerResult:
        """Record verification of whether a debate's winning position was correct.

        POST body:
            correct: bool - whether the winning position was actually correct
            source: str - verification source (default: "manual")

        Completes the truth-grounding feedback loop by linking positions to outcomes.
        """
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        correct = body.get("correct", False)
        source = body.get("source", "manual")

        # Get position tracker from context
        position_tracker = self.ctx.get("position_tracker")

        if position_tracker:
            position_tracker.record_verification(debate_id, correct, source)
            return json_response(
                {
                    "status": "verified",
                    "debate_id": debate_id,
                    "correct": correct,
                    "source": source,
                }
            )

        # Try to create a temporary tracker
        try:
            from aragora.agents.truth_grounding import PositionTracker

            nomic_dir = self.get_nomic_dir()
            if nomic_dir:
                db_path = nomic_dir / "aragora_positions.db"
                if db_path.exists():
                    tracker = PositionTracker(db_path=str(db_path))
                    tracker.record_verification(debate_id, correct, source)
                    return json_response(
                        {
                            "status": "verified",
                            "debate_id": debate_id,
                            "correct": correct,
                            "source": source,
                        }
                    )
            return error_response("Position tracking not configured", 503)
        except ImportError as e:
            module_name = getattr(e, "name", None)
            logger.error("Failed to import PositionTracker module: %s", e, exc_info=True)
            if "truth_grounding" in str(module_name or e).lower():
                return error_response("Position tracking feature not available", 503)
            else:
                return error_response("Internal error loading position tracker", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/followups",
        summary="Get follow-up suggestions",
        description="Get follow-up debate suggestions based on identified cruxes and uncertainty metrics.",
        tags=["Debates", "Fork"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {
                "description": "Follow-up suggestions returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debate_id": {"type": "string"},
                                "suggestions": {"type": "array", "items": {"type": "object"}},
                                "count": {"type": "integer"},
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
        },
    )
    @require_storage
    def _get_followup_suggestions(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """Get follow-up debate suggestions based on identified cruxes.

        Analyzes the debate's uncertainty metrics and generates suggestions
        for follow-up debates to resolve key disagreement points.

        Returns:
            List of follow-up suggestions with priority and suggested task
        """
        storage = self.get_storage()

        try:
            debate = storage.get_debate(debate_id)
            if not debate:
                return error_response(f"Debate not found: {debate_id}", 404)

            # Import uncertainty analysis components
            from aragora.uncertainty.estimator import DisagreementAnalyzer, DisagreementCrux

            # Extract cruxes from debate data
            cruxes = []

            # Check for stored uncertainty metrics
            uncertainty = debate.get("uncertainty_metrics", {})
            if uncertainty and "cruxes" in uncertainty:
                for crux_data in uncertainty["cruxes"]:
                    crux = DisagreementCrux(
                        description=crux_data.get("description", ""),
                        divergent_agents=crux_data.get("agents", []),
                        evidence_needed=crux_data.get("evidence_needed", ""),
                        severity=crux_data.get("severity", 0.5),
                    )
                    cruxes.append(crux)

            # If no stored cruxes, analyze the debate
            if not cruxes:
                from aragora.core import Message, Vote

                votes_data = debate.get("votes", [])
                messages_data = debate.get("messages", [])
                proposals = debate.get("proposals", {})

                # Convert to Vote/Message objects if needed
                votes = []
                for v in votes_data:
                    if hasattr(v, "choice"):
                        votes.append(v)
                    else:
                        votes.append(
                            Vote(
                                agent=v.get("agent", "unknown"),
                                choice=v.get("choice", ""),
                                confidence=v.get("confidence", 0.5),
                                reasoning=v.get("reasoning", ""),
                            )
                        )

                messages = []
                for m in messages_data:
                    if hasattr(m, "content"):
                        messages.append(m)
                    else:
                        messages.append(
                            Message(
                                agent=m.get("agent", "unknown"),
                                content=m.get("content", ""),
                                role=m.get("role", "proposer"),
                                round=m.get("round", 1),
                            )
                        )

                # Run disagreement analysis
                analyzer = DisagreementAnalyzer()
                metrics = analyzer.analyze_disagreement(messages, votes, proposals)
                cruxes = metrics.cruxes

            if not cruxes:
                return json_response(
                    {
                        "debate_id": debate_id,
                        "suggestions": [],
                        "message": "No significant disagreement cruxes identified",
                    }
                )

            # Generate follow-up suggestions
            analyzer = DisagreementAnalyzer()
            available_agents = debate.get("agents", [])
            suggestions = analyzer.suggest_followups(
                cruxes=cruxes,
                parent_debate_id=debate_id,
                available_agents=available_agents,
            )

            return json_response(
                {
                    "debate_id": debate_id,
                    "suggestions": [s.to_dict() for s in suggestions],
                    "count": len(suggestions),
                }
            )

        except (
            ImportError,
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as e:
            logger.error(
                "Failed to get followup suggestions for %s: %s: %s",
                debate_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response(safe_error_message(e, "get followup suggestions"), 500)

    @user_rate_limit(action="debate_create")
    @rate_limit(requests_per_minute=5, limiter_name="debates_followup")
    @require_storage
    def _create_followup_debate(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate_id: str,
        *,
        scope: OrgScope | None = None,
    ) -> HandlerResult:
        """Create a follow-up debate to resolve a specific crux.

        The follow-up record is stamped with ``scope``'s org and user.

        POST body:
            crux_id: str - ID of the crux to explore
            task: str (optional) - Custom task, otherwise generated from crux
            agents: list[str] (optional) - Specific agents to include

        Returns:
            Created debate metadata with parent lineage
        """
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        crux_id = body.get("crux_id")
        custom_task = body.get("task")
        requested_agents = body.get("agents", [])

        if not crux_id and not custom_task:
            return error_response("Either crux_id or task is required", 400)

        storage = self.get_storage()

        try:
            # Get parent debate
            parent_debate = storage.get_debate(debate_id)
            if not parent_debate:
                return error_response(f"Parent debate not found: {debate_id}", 404)

            # Find the crux if crux_id provided
            crux_data = None
            if crux_id:
                uncertainty = parent_debate.get("uncertainty_metrics", {})
                for c in uncertainty.get("cruxes", []):
                    if c.get("id") == crux_id:
                        crux_data = c
                        break

                if not crux_data:
                    return error_response(f"Crux not found: {crux_id}", 404)

            # Generate task
            if custom_task:
                task = custom_task
            elif crux_data:
                # Generate task from crux description
                from aragora.uncertainty.estimator import DisagreementAnalyzer, DisagreementCrux

                analyzer = DisagreementAnalyzer()
                crux = DisagreementCrux(
                    description=crux_data.get("description", ""),
                    divergent_agents=crux_data.get("agents", []),
                    severity=crux_data.get("severity", 0.5),
                )
                task = analyzer._generate_followup_task(crux)
            else:
                return error_response("Could not generate task", 400)

            # Determine agents
            if requested_agents:
                agents = requested_agents
            elif crux_data:
                agents = crux_data.get("agents", [])
                # Add parent debate agents if not enough
                if len(agents) < 2:
                    for agent in parent_debate.get("agents", []):
                        if agent not in agents:
                            agents.append(agent)
                        if len(agents) >= 3:
                            break
            else:
                agents = parent_debate.get("agents", [])[:3]

            import time

            # Store follow-up debate metadata
            followup_data = {
                "id": _new_followup_id(),
                "task": task,
                "agents": agents,
                "parent_debate_id": debate_id,
                "crux_id": crux_id,
                "crux_description": crux_data.get("description") if crux_data else None,
                "status": "pending",
                "created_at": time.time(),
                **_owner_fields(scope),
            }

            # Store in nomic dir
            nomic_dir = self.get_nomic_dir()
            if nomic_dir:
                followups_dir = nomic_dir / "followups"
                followups_dir.mkdir(exist_ok=True)
                _write_new_followup(followups_dir, followup_data)
            followup_id = followup_data["id"]

            logger.info("Created follow-up debate %s from parent %s", followup_id, debate_id)

            return json_response(
                {
                    "success": True,
                    "followup_id": followup_id,
                    "parent_debate_id": debate_id,
                    "task": task,
                    "agents": agents,
                    "crux_id": crux_id,
                    "status": "pending",
                    "message": f"Created follow-up debate to explore: {task[:100]}",
                }
            )

        except (
            ImportError,
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as e:
            logger.error(
                "Failed to create followup debate for %s: %s: %s",
                debate_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response(safe_error_message(e, "create followup debate"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{debate_id}/forks",
        summary="List debate forks",
        description="List all forks (counterfactual branches) of a debate.",
        tags=["Debates", "Fork"],
        parameters=[
            {"name": "debate_id", "in": "path", "schema": {"type": "string"}, "required": True},
        ],
        responses={
            "200": {
                "description": "List of forks returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debate_id": {"type": "string"},
                                "forks": {"type": "array", "items": {"type": "object"}},
                                "tree": {"type": "object"},
                                "total": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            "401": {"description": "Unauthorized"},
            "404": {"description": "Debate not found"},
        },
    )
    @require_storage
    def _list_debate_forks(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """List all forks for a debate with tree structure.

        Returns:
            forks: List of fork data
            tree: Hierarchical tree structure
            total: Total fork count
        """
        import json as json_mod

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return json_response(
                {
                    "debate_id": debate_id,
                    "forks": [],
                    "tree": None,
                    "total": 0,
                }
            )

        branches_dir = nomic_dir / "branches"
        if not branches_dir.exists():
            return json_response(
                {
                    "debate_id": debate_id,
                    "forks": [],
                    "tree": None,
                    "total": 0,
                }
            )

        forks = []
        try:
            # Scan for forks related to this debate
            for branch_file in branches_dir.glob(f"fork-{debate_id}*.json"):
                try:
                    with open(branch_file) as f:
                        fork_data = json_mod.load(f)
                        # Add timestamp if missing
                        if "created_at" not in fork_data:
                            fork_data["created_at"] = branch_file.stat().st_mtime
                        forks.append(fork_data)
                except (json_mod.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read fork file %s: %s", branch_file, e)
                    continue

            # Also check for child forks (forks of forks)
            for fork in list(forks):
                fork_id = fork.get("branch_id", "")
                for child_file in branches_dir.glob(f"fork-{fork_id}*.json"):
                    try:
                        with open(child_file) as f:
                            child_data = json_mod.load(f)
                            if child_data not in forks:
                                if "created_at" not in child_data:
                                    child_data["created_at"] = child_file.stat().st_mtime
                                forks.append(child_data)
                    except (json_mod.JSONDecodeError, OSError):
                        continue

            # Sort by creation time
            forks.sort(key=lambda x: x.get("created_at", 0))

            # Build tree structure
            tree = _build_fork_tree(debate_id, forks)

            return json_response(
                {
                    "debate_id": debate_id,
                    "forks": forks,
                    "tree": tree,
                    "total": len(forks),
                }
            )

        except OSError as e:
            logger.error("Failed to list forks for %s: %s", debate_id, e)
            return error_response(safe_error_message(e, "list forks"), 500)


def _build_fork_tree(
    root_id: str,
    forks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a hierarchical tree structure from flat fork list.

    Args:
        root_id: The root debate ID
        forks: List of fork data dicts

    Returns:
        Tree structure with nested children
    """
    # Create lookup by branch_id
    fork_lookup = {f.get("branch_id"): f for f in forks}

    # Build tree recursively
    def build_node(node_id: str, is_root: bool = False) -> dict[str, Any]:
        children: list[dict[str, Any]] = []
        if is_root:
            # Root node is the original debate
            node: dict[str, Any] = {
                "id": node_id,
                "type": "root",
                "branch_point": 0,
                "children": children,
            }
        else:
            # Fork node
            fork_data = fork_lookup.get(node_id, {})
            node = {
                "id": node_id,
                "type": "fork",
                "branch_point": fork_data.get("branch_point", 0),
                "pivot_claim": fork_data.get("pivot_claim"),
                "status": fork_data.get("status", "unknown"),
                "modified_context": fork_data.get("modified_context"),
                "messages_inherited": fork_data.get("messages_inherited", 0),
                "created_at": fork_data.get("created_at"),
                "children": children,
            }

        # Find children (forks that have this node as parent)
        for fork in forks:
            if fork.get("parent_debate_id") == node_id:
                child_id = fork.get("branch_id")
                if child_id:
                    child_node = build_node(child_id)
                    children.append(child_node)

        return node

    tree = build_node(root_id, is_root=True)

    # Calculate tree stats
    def count_nodes(node: dict[str, Any]) -> tuple[int, int]:
        """Count total nodes and max depth."""
        if not node.get("children"):
            return 1, 1
        total = 1
        max_depth = 1
        for child in node["children"]:
            child_count, child_depth = count_nodes(child)
            total += child_count
            max_depth = max(max_depth, child_depth + 1)
        return total, max_depth

    total_nodes, max_depth = count_nodes(tree)
    tree["total_nodes"] = total_nodes
    tree["max_depth"] = max_depth

    return tree


__all__ = ["ForkOperationsMixin"]
