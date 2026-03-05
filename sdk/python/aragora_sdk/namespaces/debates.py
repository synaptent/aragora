"""
Debates Namespace API

Provides methods for creating, managing, and analyzing debates.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient
    from ..pagination import AsyncPaginator, SyncPaginator
    from ..websocket import WebSocketEvent


_List = list  # Preserve builtin list for type annotations


class DebatesAPI:
    """
    Synchronous Debates API.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> debate = client.debates.create(task="Should we use microservices?")
        >>> messages = client.debates.get_messages(debate["debate_id"])
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    def create(
        self,
        task: str,
        agents: _List[str] | None = None,
        protocol: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Create a new debate.

        Args:
            task: The topic or question to debate
            agents: List of agent names to participate (optional)
            protocol: Debate protocol configuration (optional)
            **kwargs: Additional debate options

        Returns:
            Created debate with debate_id
        """
        data = {"task": task, **kwargs}
        if agents:
            data["agents"] = agents
        if protocol:
            data["protocol"] = protocol

        return self._client.request("POST", "/api/v1/debates", json=data)

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        """
        List debates with pagination.

        Args:
            limit: Maximum number of debates to return
            offset: Number of debates to skip
            status: Filter by status (active, completed, etc.)

        Returns:
            List of debates with pagination info
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return self._client.request("GET", "/api/v1/debates", params=params)

    def list_all(
        self,
        status: str | None = None,
        page_size: int = 20,
    ) -> SyncPaginator:
        """
        Iterate through all debates with automatic pagination.

        Args:
            status: Filter by status (active, completed, etc.)
            page_size: Number of debates per page (default 20)

        Returns:
            SyncPaginator yielding debate dictionaries

        Example::

            for debate in client.debates.list_all(status="active"):
                print(debate["id"])
        """
        from ..pagination import SyncPaginator

        params: dict[str, Any] = {}
        if status:
            params["status"] = status

        return SyncPaginator(self._client, "/api/v1/debates", params, page_size)

    def get_messages(self, debate_id: str) -> dict[str, Any]:
        """
        Get messages from a debate.

        Args:
            debate_id: The debate ID

        Returns:
            List of messages
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/messages")

    def add_message(
        self,
        debate_id: str,
        content: str,
        role: str = "user",
    ) -> dict[str, Any]:
        """
        Add a message to a debate.

        Args:
            debate_id: The debate ID
            content: Message content
            role: Message role (user, system, etc.)

        Returns:
            Created message
        """
        return self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/messages",
            json={"content": content, "role": role},
        )

    def get_export(
        self,
        debate_id: str,
        format: str = "json",
    ) -> dict[str, Any]:
        """
        Export a debate.

        Args:
            debate_id: The debate ID
            format: Export format (json, pdf, etc.)

        Returns:
            Exported debate data
        """
        return self._client.request(
            "GET",
            f"/api/v1/debates/{debate_id}/export",
            params={"format": format},
        )

    def cancel(self, debate_id: str) -> dict[str, Any]:
        """
        Cancel a debate.

        Args:
            debate_id: The debate ID

        Returns:
            Cancellation result
        """
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/cancel")

    def get_citations(self, debate_id: str) -> dict[str, Any]:
        """Get citations used in debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/citations")

    def get_convergence(self, debate_id: str) -> dict[str, Any]:
        """Get convergence analysis."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/convergence")

    def get_evidence(self, debate_id: str) -> dict[str, Any]:
        """Get evidence collected during debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/evidence")

    def get_impasse(self, debate_id: str) -> dict[str, Any]:
        """Get impasse analysis if debate is stuck."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/impasse")

    def capability_probe(self, task: str, agents: _List[str] | None = None) -> dict[str, Any]:
        """Run a capability probe debate."""
        data: dict[str, Any] = {"task": task}
        if agents:
            data["agents"] = agents
        return self._client.request("POST", "/api/v1/debates/capability-probe", json=data)

    def deep_audit(self, task: str, agents: _List[str] | None = None) -> dict[str, Any]:
        """Run a deep audit debate."""
        data: dict[str, Any] = {"task": task}
        if agents:
            data["agents"] = agents
        return self._client.request("POST", "/api/v1/debates/deep-audit", json=data)

    def broadcast(self, debate_id: str, channels: _List[str] | None = None) -> dict[str, Any]:
        """Broadcast debate to channels."""
        data: dict[str, Any] = {"channels": channels} if channels else {}
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/broadcast", json=data)

    def fork(self, debate_id: str, changes: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fork a debate with optional changes."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/fork", json=changes or {})

    def publish_twitter(self, debate_id: str, message: str | None = None) -> dict[str, Any]:
        """Publish debate summary to Twitter."""
        data: dict[str, Any] = {"message": message} if message else {}
        return self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/publish/twitter", json=data
        )

    def publish_youtube(self, debate_id: str, title: str | None = None) -> dict[str, Any]:
        """Publish debate to YouTube."""
        data: dict[str, Any] = {"title": title} if title else {}
        return self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/publish/youtube", json=data
        )

    def get_dashboard(self) -> dict[str, Any]:
        """Get debates dashboard view."""
        return self._client.request("GET", "/api/v1/dashboard/debates")

    def get_debate_graph_stats(self, debate_id: str) -> dict[str, Any]:
        """Get graph stats via debate endpoint."""
        return self._client.request("GET", f"/api/v1/debate/{debate_id}/graph-stats")

    def get_history(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """Get debate history."""
        return self._client.request(
            "GET", "/api/v1/history/debates", params={"limit": limit, "offset": offset}
        )

    def get_summary(self, debate_id: str) -> dict[str, Any]:
        """Get a human-readable summary of the debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/summary")

    def get_verification_report(self, debate_id: str) -> dict[str, Any]:
        """Get the verification report for debate conclusions."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/verification-report")

    # ========== Follow-up & Continuation ==========

    def get_followup_suggestions(self, debate_id: str) -> dict[str, Any]:
        """Get suggestions for follow-up debates."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/followups")

    def follow_up(
        self,
        debate_id: str,
        crux_id: str | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Create a follow-up debate from an existing one."""
        payload: dict[str, Any] = {}
        if crux_id:
            payload["cruxId"] = crux_id
        if context:
            payload["context"] = context
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/followup", json=payload)

    def list_forks(self, debate_id: str) -> dict[str, Any]:
        """List all forks created from a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/forks")

    def add_evidence(
        self,
        debate_id: str,
        evidence: str,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add evidence to a debate."""
        payload: dict[str, Any] = {"evidence": evidence}
        if source:
            payload["source"] = source
        if metadata:
            payload["metadata"] = metadata
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/evidence", json=payload)

    # ========== Search ==========

    def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        domain: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Search across all debates."""
        params: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if domain:
            params["domain"] = domain
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        return self._client.request("GET", "/api/v1/search", params=params)

    # ========== Batch Operations ==========

    def submit_batch(self, requests: _List[dict[str, Any]]) -> dict[str, Any]:
        """Submit multiple debates for batch processing."""
        return self._client.request("POST", "/api/v1/debates/batch", json={"requests": requests})

    def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        """Get the status of a batch job."""
        return self._client.request("GET", f"/api/v1/debates/batch/{batch_id}/status")

    def list_batches(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List all batch jobs."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self._client.request("GET", "/api/v1/debates/batch", params=params)

    def get_queue_status(self) -> dict[str, Any]:
        """Get the current queue status."""
        return self._client.request("GET", "/api/v1/debates/queue/status")

    # ========== RLM / Compression ==========

    def compress(
        self,
        debate_id: str,
        target_levels: _List[str] | None = None,
        compression_ratio: float = 0.3,
    ) -> dict[str, Any]:
        """Compress debate context using RLM hierarchical abstraction.

        Args:
            debate_id: The debate ID
            target_levels: Abstraction levels to generate (e.g. ["ABSTRACT", "SUMMARY", "DETAILED"])
            compression_ratio: Target compression ratio (0.0-1.0, default 0.3)

        Returns:
            Compression result with original_tokens, compressed_tokens, compression_ratios,
            time_seconds, and levels_created
        """
        payload: dict[str, Any] = {"compression_ratio": compression_ratio}
        if target_levels:
            payload["target_levels"] = target_levels
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/compress", json=payload)

    def get_context_level(self, debate_id: str, level: str) -> dict[str, Any]:
        """Get debate content at a specific abstraction level.

        Args:
            debate_id: The debate ID
            level: Abstraction level (ABSTRACT, SUMMARY, DETAILED, or RAW)

        Returns:
            Context at the requested level with content, token_count, and nodes
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/context/{level}")

    def query_rlm(
        self,
        debate_id: str,
        query: str,
        strategy: str = "auto",
        max_iterations: int = 3,
        start_level: str = "SUMMARY",
    ) -> dict[str, Any]:
        """Query a debate using RLM with iterative refinement.

        Args:
            debate_id: The debate ID
            query: The question to ask about the debate
            strategy: Query strategy (auto, peek, grep, partition_map, summarize, hierarchical)
            max_iterations: Maximum refinement iterations (1-10, default 3)
            start_level: Starting abstraction level (ABSTRACT, SUMMARY, DETAILED, RAW)

        Returns:
            Query result with answer, confidence, refinement_history, and token usage
        """
        return self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/query-rlm",
            json={
                "query": query,
                "strategy": strategy,
                "max_iterations": max_iterations,
                "start_level": start_level,
            },
        )

    def get_refinement_status(self, debate_id: str) -> dict[str, Any]:
        """Get the status of an ongoing RLM refinement process.

        Args:
            debate_id: The debate ID

        Returns:
            Refinement status with active_queries, cached_contexts, and status
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/refinement-status")

    # ========== Decision Integrity ==========

    def get_decision_integrity(self, debate_id: str) -> dict[str, Any]:
        """Get the decision integrity package for a debate.

        Generates a decision receipt and implementation plan bundle
        containing audit-ready documentation of the debate outcome.

        Args:
            debate_id: The debate ID

        Returns:
            Decision integrity package with receipt and implementation plan
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/decision-integrity")

    # ========== Cost Estimation ==========

    def estimate_cost(
        self,
        num_agents: int = 3,
        num_rounds: int = 9,
        model_types: _List[str] | None = None,
    ) -> dict[str, Any]:
        """Estimate the cost of a debate before creation.

        Args:
            num_agents: Number of participating agents (1-8, default 3)
            num_rounds: Number of debate rounds (1-12, default 9)
            model_types: List of model names to use (optional)

        Returns:
            Cost estimation with total, per-model breakdown, and assumptions
        """
        params: dict[str, Any] = {
            "num_agents": num_agents,
            "num_rounds": num_rounds,
        }
        if model_types:
            params["model_types"] = ",".join(model_types)
        return self._client.request("GET", "/api/v1/debates/estimate-cost", params=params)

    # ========== Quick Debate ==========

    def quick_debate(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """Create a debate via the non-versioned quick endpoint."""
        data: dict[str, Any] = {"task": task, **kwargs}
        return self._client.request("POST", "/api/debate", json=data)

    # ========== Analytics ==========

    def get_consensus_analytics(self) -> dict[str, Any]:
        """Get consensus analytics across debates."""
        return self._client.request("GET", "/api/v1/debates/analytics/consensus")

    def get_trend_analytics(self) -> dict[str, Any]:
        """Get debate trend analytics."""
        return self._client.request("GET", "/api/v1/debates/analytics/trends")

    # ========== Archive ==========

    def archive_batch(self, debate_ids: _List[str]) -> dict[str, Any]:
        """Archive multiple debates."""
        return self._client.request(
            "POST", "/api/v1/debates/archive/batch", json={"debate_ids": debate_ids}
        )

    def list_archived(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List archived debates."""
        return self._client.request(
            "GET", "/api/v1/debates/archived", params={"limit": limit, "offset": offset}
        )

    # ========== Compare & Import ==========

    def compare(self, debate_ids: _List[str]) -> dict[str, Any]:
        """Compare multiple debates."""
        return self._client.request(
            "POST", "/api/v1/debates/compare", json={"debate_ids": debate_ids}
        )

    def get_health(self) -> dict[str, Any]:
        """Get debate system health."""
        return self._client.request("GET", "/api/v1/debates/health")

    def import_debate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import a debate from external data."""
        return self._client.request("POST", "/api/v1/debates/import", json=data)

    def get_statistics(self) -> dict[str, Any]:
        """Get aggregate debate statistics."""
        return self._client.request("GET", "/api/v1/debates/statistics")

    def stream_debate(self, debate_id: str) -> dict[str, Any]:
        """Get streaming info for a debate."""
        return self._client.request(
            "GET", "/api/v1/debates/stream", params={"debate_id": debate_id}
        )

    # ========== Stats & Diagnostics ==========

    def get_stats(self) -> dict[str, Any]:
        """Get debate stats (active, completed, consensus rate, etc.)."""
        return self._client.request("GET", "/api/debates/stats")

    def get_agent_stats(self) -> dict[str, Any]:
        """Get per-agent debate statistics."""
        return self._client.request("GET", "/api/debates/stats/agents")

    def get_diagnostics(self, debate_id: str) -> dict[str, Any]:
        """
        Get diagnostics for a debate (timing, token usage, errors).

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with diagnostic data for debugging.
        """
        return self._client.request("GET", f"/api/debates/{debate_id}/diagnostics")

    def get_costs(self, debate_id: str) -> dict[str, Any]:
        """Get per-debate cost breakdown.

        Queries the DebateCostTracker for granular per-agent, per-round,
        and per-model cost data.

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with cost breakdown by agent, round, and model.
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/costs")

    def get_events(
        self,
        debate_id: str,
        *,
        since: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get debate events for polling fallback.

        Retrieves events that may have been missed during WebSocket
        disconnections.

        Args:
            debate_id: The debate ID.
            since: Sequence number to start from (default: 0).
            limit: Maximum number of events to return (default: 100).

        Returns:
            Dict with events list and latest sequence number.
        """
        return self._client.request(
            "GET",
            f"/api/v1/debates/{debate_id}/events",
            params={"since": since, "limit": limit},
        )

    def get_positions(self, debate_id: str) -> dict[str, Any]:
        """Get position evolution per agent.

        Tracks how each agent's position changed throughout the debate.

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with per-agent position evolution data.
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/positions")

    # ========== Package & Share ==========

    def get_package(self, debate_id: str) -> dict[str, Any]:
        """
        Get a portable debate package (receipt + transcript + evidence).

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with full debate package.
        """
        return self._client.request("GET", f"/api/debates/{debate_id}/package")

    def get_package_markdown(self, debate_id: str) -> dict[str, Any]:
        """
        Get a debate package in Markdown format.

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with markdown-formatted debate package.
        """
        return self._client.request("GET", f"/api/debates/{debate_id}/package/markdown")

    def share(self, debate_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        Create a shareable link for a debate.

        Args:
            debate_id: The debate ID.
            **kwargs: Share options (expiry, permissions, etc.)

        Returns:
            Dict with share URL and token.
        """
        return self._client.request("POST", f"/api/debates/{debate_id}/share", json=kwargs)

    def revoke_share(self, debate_id: str) -> dict[str, Any]:
        """
        Revoke a shared debate link.

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with revocation confirmation.
        """
        return self._client.request("POST", f"/api/debates/{debate_id}/share/revoke")

    def get_shared(self, share_token: str) -> dict[str, Any]:
        """View a publicly shared debate by share token."""
        return self._client.request("GET", f"/api/v1/shared/{share_token}")

    def get_public_spectate(self, debate_id: str) -> dict[str, Any]:
        """
        Get the public spectate view for a debate.

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with public spectate data (no auth required).
        """
        return self._client.request("GET", f"/api/debates/{debate_id}/spectate/public")

    def get_public_debate(self, debate_id: str) -> dict[str, Any]:
        """Get a publicly shared debate by ID (no auth required).

        Args:
            debate_id: The debate ID to retrieve.

        Returns:
            Dict with public debate data including verdict and consensus.
        """
        return self._client.request("GET", f"/api/debates/public/{debate_id}")

    def get_public_debate_og(self, debate_id: str) -> dict[str, Any]:
        """Get Open Graph metadata for a publicly shared debate.

        Args:
            debate_id: The debate ID.

        Returns:
            Dict with OG metadata (title, description, image) for social previews.
        """
        return self._client.request("GET", f"/api/debates/public/{debate_id}/og")

    # ========== One-Click Debate ==========

    def debate_this(
        self,
        question: str,
        *,
        context: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """
        One-click debate launcher.

        POST /api/v1/debate-this

        Convenience endpoint for quick debate creation. Only requires a
        question; auto-detects format and selects agents.

        Args:
            question: The topic to debate (required).
            context: Optional additional context string.
            source: Source surface identifier (default: "debate_this").

        Returns:
            Created debate response with debate_id and spectate_url.
        """
        data: dict[str, Any] = {"question": question}
        if context is not None:
            data["context"] = context
        if source is not None:
            data["source"] = source
        return self._client.request("POST", "/api/v1/debate-this", json=data)

    # ========== Intervention & Reasoning ==========

    def intervene(
        self,
        debate_id: str,
        intervention_type: str,
        content: str,
        apply_at_round: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Submit a mid-debate intervention.

        Args:
            debate_id: The debate ID
            intervention_type: Type of intervention (redirect, constraint, challenge, evidence_request)
            content: Intervention content
            apply_at_round: Round to apply at (0 = next available)
            **kwargs: Additional metadata

        Returns:
            Dict with intervention_id, status, and apply_at_round
        """
        data: dict[str, Any] = {
            "type": intervention_type,
            "content": content,
            "apply_at_round": apply_at_round,
            **kwargs,
        }
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/intervene", json=data)

    def get_reasoning(self, debate_id: str) -> dict[str, Any]:
        """Get per-agent reasoning summary for a debate.

        Returns agent reasoning chains, key cruxes, and unresolved
        disagreements.

        Args:
            debate_id: The debate ID

        Returns:
            Dict with agents, cruxes, unresolved_disagreements, and interventions
        """
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/reasoning")

    # ========== CRUD & Lifecycle ==========

    def get(self, debate_id: str) -> dict[str, Any]:
        """Get a debate by ID."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}")

    def get_by_slug(self, slug: str) -> dict[str, Any]:
        """Get a debate by its URL slug."""
        return self._client.request("GET", f"/api/v1/debates/slug/{slug}")

    def delete(self, debate_id: str) -> dict[str, Any]:
        """Delete a debate."""
        return self._client.request("DELETE", f"/api/v1/debates/{debate_id}")

    def update(self, debate_id: str, **updates: Any) -> dict[str, Any]:
        """Update an existing debate."""
        return self._client.request("PUT", f"/api/v1/debates/{debate_id}", json=updates)

    def get_metadata(self, debate_id: str) -> dict[str, Any]:
        """Get debate metadata."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/metadata")

    def start(self, debate_id: str) -> dict[str, Any]:
        """Start a debate."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/start")

    def stop(self, debate_id: str) -> dict[str, Any]:
        """Stop a running debate."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/stop")

    def pause(self, debate_id: str) -> dict[str, Any]:
        """Pause a running debate."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/pause")

    def resume(self, debate_id: str) -> dict[str, Any]:
        """Resume a paused debate."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/resume")

    def restore(self, debate_id: str) -> dict[str, Any]:
        """Restore an archived debate."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/restore")

    def make_permanent(self, debate_id: str) -> dict[str, Any]:
        """Make a debate permanent."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/make-permanent")

    def clone(self, debate_id: str, **options: Any) -> dict[str, Any]:
        """Clone a debate with fresh state."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/clone", json=options)

    def archive(self, debate_id: str) -> dict[str, Any]:
        """Archive a single debate."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/archive")

    def export_format(self, debate_id: str, format: str = "json") -> dict[str, Any]:
        """Export a debate in a specific format."""
        return self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/export", params={"format": format}
        )

    # ========== Rounds, Agents, Votes ==========

    def get_rounds(self, debate_id: str) -> dict[str, Any]:
        """Get rounds from a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/rounds")

    def get_agents(self, debate_id: str) -> dict[str, Any]:
        """Get agents participating in a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/agents")

    def get_votes(self, debate_id: str) -> dict[str, Any]:
        """Get votes from a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/votes")

    def get_consensus(self, debate_id: str) -> dict[str, Any]:
        """Get consensus information for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/consensus")

    def add_user_input(
        self, debate_id: str, input: str, input_type: str = "suggestion"
    ) -> dict[str, Any]:
        """Add user input to a debate."""
        return self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/user-input",
            json={"input": input, "type": input_type},
        )

    def get_timeline(self, debate_id: str) -> dict[str, Any]:
        """Get the timeline of events in a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/timeline")

    def get_tags(self, debate_id: str) -> dict[str, Any]:
        """Get tags for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/tags")

    def find_similar(self, debate_id: str, limit: int = 5) -> dict[str, Any]:
        """Find debates similar to this one."""
        return self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/similar", params={"limit": limit}
        )

    # ========== Graph & Matrix ==========

    def get_graph(self, debate_id: str) -> dict[str, Any]:
        """Get the argument graph for a debate."""
        return self._client.request("GET", f"/api/v1/debates/graph/{debate_id}")

    def get_graph_branches(self, debate_id: str) -> dict[str, Any]:
        """Get branches in the argument graph."""
        return self._client.request("GET", f"/api/v1/debates/graph/{debate_id}/branches")

    def get_matrix_comparison(self, debate_id: str) -> dict[str, Any]:
        """Get matrix comparison for a multi-scenario debate."""
        return self._client.request("GET", f"/api/v1/debates/matrix/{debate_id}")

    # ========== Explainability ==========

    def get_explainability(self, debate_id: str) -> dict[str, Any]:
        """Get explainability data for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/explainability")

    def get_explainability_factors(self, debate_id: str) -> dict[str, Any]:
        """Get factor decomposition for a debate decision."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/explainability/factors")

    def get_explainability_narrative(self, debate_id: str) -> dict[str, Any]:
        """Get natural language narrative explanation."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/explainability/narrative")

    def get_explainability_provenance(self, debate_id: str) -> dict[str, Any]:
        """Get provenance chain for debate claims."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/explainability/provenance")

    def get_explainability_counterfactual(self, debate_id: str) -> dict[str, Any]:
        """Get counterfactual analysis."""
        return self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/explainability/counterfactual"
        )

    def create_counterfactual(self, debate_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Create a counterfactual scenario."""
        return self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/explainability/counterfactual", json=changes
        )

    # ========== Red Team & Analysis ==========

    def get_red_team(self, debate_id: str) -> dict[str, Any]:
        """Get red team analysis for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/red-team")

    def get_rhetorical(self, debate_id: str) -> dict[str, Any]:
        """Get rhetorical pattern observations."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/rhetorical")

    def get_trickster(self, debate_id: str) -> dict[str, Any]:
        """Get trickster hollow consensus detection status."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/trickster")

    def get_meta_critique(self, debate_id: str) -> dict[str, Any]:
        """Get meta-level critique of the debate."""
        return self._client.request("GET", f"/api/v1/debate/{debate_id}/meta-critique")

    def get_quality(self, debate_id: str) -> dict[str, Any]:
        """Get argument quality analysis."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/quality")

    def verify_claim(
        self, debate_id: str, claim_id: str, evidence: str | None = None
    ) -> dict[str, Any]:
        """Verify a specific claim from the debate."""
        data: dict[str, Any] = {"claim_id": claim_id}
        if evidence is not None:
            data["evidence"] = evidence
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/verify", json=data)

    # ========== Notes ==========

    def get_notes(self, debate_id: str) -> dict[str, Any]:
        """Get notes attached to a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/notes")

    def add_note(self, debate_id: str, content: str) -> dict[str, Any]:
        """Add a note to a debate."""
        return self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/notes", json={"content": content}
        )

    def delete_note(self, debate_id: str, note_id: str) -> dict[str, Any]:
        """Delete a note from a debate."""
        return self._client.request("DELETE", f"/api/v1/debates/{debate_id}/notes/{note_id}")

    # ========== Batch Results ==========

    def get_batch_results(self, batch_id: str) -> dict[str, Any]:
        """Get results of a batch job."""
        return self._client.request("GET", f"/api/v1/debates/batch/{batch_id}/results")

    def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        """Cancel a batch job."""
        return self._client.request("POST", f"/api/v1/debates/batch/{batch_id}/cancel")

    def retry_batch(self, batch_id: str) -> dict[str, Any]:
        """Retry failed jobs in a batch."""
        return self._client.request("POST", f"/api/v1/debates/batch/{batch_id}/retry")

    # ========== Agent & Debate Health ==========

    def get_agent_statistics(self, debate_id: str) -> dict[str, Any]:
        """Get per-agent statistics for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/agent-statistics")

    def get_debate_health(self, debate_id: str) -> dict[str, Any]:
        """Get health status for a specific debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/health")

    # ========== Intervention ==========

    def intervention_pause(self, debate_id: str) -> dict[str, Any]:
        """Pause debate via intervention."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/intervention/pause")

    def intervention_resume(self, debate_id: str) -> dict[str, Any]:
        """Resume debate via intervention."""
        return self._client.request("POST", f"/api/v1/debates/{debate_id}/intervention/resume")

    def intervention_inject(self, debate_id: str, content: str, **kwargs: Any) -> dict[str, Any]:
        """Inject content into a debate via intervention."""
        return self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/intervention/inject",
            json={"content": content, **kwargs},
        )

    def get_intervention_log(self, debate_id: str) -> dict[str, Any]:
        """Get the intervention log for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/intervention/log")

    def get_intervention_state(self, debate_id: str) -> dict[str, Any]:
        """Get current intervention state for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/intervention/state")

    def set_intervention_threshold(self, debate_id: str, threshold: float) -> dict[str, Any]:
        """Set the intervention threshold for a debate."""
        return self._client.request(
            "PUT",
            f"/api/v1/debates/{debate_id}/intervention/threshold",
            json={"threshold": threshold},
        )

    def set_intervention_weights(self, debate_id: str, weights: dict[str, float]) -> dict[str, Any]:
        """Set intervention weights for a debate."""
        return self._client.request(
            "PUT", f"/api/v1/debates/{debate_id}/intervention/weights", json={"weights": weights}
        )

    def get_youtube_publish_status(self, debate_id: str) -> dict[str, Any]:
        """Get YouTube publish status for a debate."""
        return self._client.request("GET", f"/api/v1/debates/{debate_id}/publish/youtube/status")


class AsyncDebatesAPI:
    """
    Asynchronous Debates API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     debate = await client.debates.create(task="Should we use microservices?")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def create(
        self,
        task: str,
        agents: _List[str] | None = None,
        protocol: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new debate."""
        data = {"task": task, **kwargs}
        if agents:
            data["agents"] = agents
        if protocol:
            data["protocol"] = protocol

        return await self._client.request("POST", "/api/v1/debates", json=data)

    async def list(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List debates with pagination."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return await self._client.request("GET", "/api/v1/debates", params=params)

    def list_all(
        self,
        status: str | None = None,
        page_size: int = 20,
    ) -> AsyncPaginator:
        """
        Iterate through all debates with automatic pagination.

        Args:
            status: Filter by status (active, completed, etc.)
            page_size: Number of debates per page (default 20)

        Returns:
            AsyncPaginator yielding debate dictionaries

        Example::

            async for debate in client.debates.list_all(status="active"):
                print(debate["id"])
        """
        from ..pagination import AsyncPaginator

        params = {}
        if status:
            params["status"] = status

        return AsyncPaginator(self._client, "/api/v1/debates", params, page_size)

    async def stream(self, debate_id: str) -> AsyncIterator[WebSocketEvent]:
        """
        Stream debate events via WebSocket.

        Yields events as they occur during the debate. Automatically connects
        and disconnects the WebSocket.

        Args:
            debate_id: The ID of the debate to stream

        Yields:
            WebSocketEvent objects with typed_data for structured access

        Example::

            async for event in client.debates.stream(debate_id):
                print(event.type, event.data)
                if event.type == "debate_end":
                    break
        """
        from ..websocket import AragoraWebSocket

        ws = AragoraWebSocket(
            base_url=self._client.base_url,
            api_key=self._client.api_key,
        )
        await ws.connect(debate_id=debate_id)
        try:
            async for event in ws.events():
                yield event
                if event.type in ("debate_end", "error"):
                    break
        finally:
            await ws.close()

    async def get_messages(self, debate_id: str) -> dict[str, Any]:
        """Get messages from a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/messages")

    async def add_message(
        self,
        debate_id: str,
        content: str,
        role: str = "user",
    ) -> dict[str, Any]:
        """Add a message to a debate."""
        return await self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/messages",
            json={"content": content, "role": role},
        )

    async def get_export(
        self,
        debate_id: str,
        format: str = "json",
    ) -> dict[str, Any]:
        """Export a debate."""
        return await self._client.request(
            "GET",
            f"/api/v1/debates/{debate_id}/export",
            params={"format": format},
        )

    async def cancel(self, debate_id: str) -> dict[str, Any]:
        """Cancel a debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/cancel")

    async def get_citations(self, debate_id: str) -> dict[str, Any]:
        """Get citations used in debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/citations")

    async def get_convergence(self, debate_id: str) -> dict[str, Any]:
        """Get convergence analysis."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/convergence")

    async def get_evidence(self, debate_id: str) -> dict[str, Any]:
        """Get evidence collected during debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/evidence")

    async def get_impasse(self, debate_id: str) -> dict[str, Any]:
        """Get impasse analysis if debate is stuck."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/impasse")

    async def capability_probe(self, task: str, agents: _List[str] | None = None) -> dict[str, Any]:
        """Run a capability probe debate."""
        data: dict[str, Any] = {"task": task}
        if agents:
            data["agents"] = agents
        return await self._client.request("POST", "/api/v1/debates/capability-probe", json=data)

    async def deep_audit(self, task: str, agents: _List[str] | None = None) -> dict[str, Any]:
        """Run a deep audit debate."""
        data: dict[str, Any] = {"task": task}
        if agents:
            data["agents"] = agents
        return await self._client.request("POST", "/api/v1/debates/deep-audit", json=data)

    async def broadcast(self, debate_id: str, channels: _List[str] | None = None) -> dict[str, Any]:
        """Broadcast debate to channels."""
        data: dict[str, Any] = {"channels": channels} if channels else {}
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/broadcast", json=data
        )

    async def fork(self, debate_id: str, changes: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fork a debate with optional changes."""
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/fork", json=changes or {}
        )

    async def publish_twitter(self, debate_id: str, message: str | None = None) -> dict[str, Any]:
        """Publish debate summary to Twitter."""
        data: dict[str, Any] = {"message": message} if message else {}
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/publish/twitter", json=data
        )

    async def publish_youtube(self, debate_id: str, title: str | None = None) -> dict[str, Any]:
        """Publish debate to YouTube."""
        data: dict[str, Any] = {"title": title} if title else {}
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/publish/youtube", json=data
        )

    async def get_dashboard(self) -> dict[str, Any]:
        """Get debates dashboard view."""
        return await self._client.request("GET", "/api/v1/dashboard/debates")

    async def get_debate_graph_stats(self, debate_id: str) -> dict[str, Any]:
        """Get graph stats via debate endpoint."""
        return await self._client.request("GET", f"/api/v1/debate/{debate_id}/graph-stats")

    async def get_history(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """Get debate history."""
        return await self._client.request(
            "GET", "/api/v1/history/debates", params={"limit": limit, "offset": offset}
        )

    async def get_summary(self, debate_id: str) -> dict[str, Any]:
        """Get a human-readable summary of the debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/summary")

    async def get_verification_report(self, debate_id: str) -> dict[str, Any]:
        """Get the verification report for debate conclusions."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/verification-report")

    # ========== Follow-up & Continuation ==========

    async def get_followup_suggestions(self, debate_id: str) -> dict[str, Any]:
        """Get suggestions for follow-up debates."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/followups")

    async def follow_up(
        self,
        debate_id: str,
        crux_id: str | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Create a follow-up debate from an existing one."""
        payload: dict[str, Any] = {}
        if crux_id:
            payload["cruxId"] = crux_id
        if context:
            payload["context"] = context
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/followup", json=payload
        )

    async def list_forks(self, debate_id: str) -> dict[str, Any]:
        """List all forks created from a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/forks")

    async def add_evidence(
        self,
        debate_id: str,
        evidence: str,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add evidence to a debate."""
        payload: dict[str, Any] = {"evidence": evidence}
        if source:
            payload["source"] = source
        if metadata:
            payload["metadata"] = metadata
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/evidence", json=payload
        )

    # ========== Search ==========

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        domain: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Search across all debates."""
        params: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if domain:
            params["domain"] = domain
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        return await self._client.request("GET", "/api/v1/search", params=params)

    # ========== Batch Operations ==========

    async def submit_batch(self, requests: _List[dict[str, Any]]) -> dict[str, Any]:
        """Submit multiple debates for batch processing."""
        return await self._client.request(
            "POST", "/api/v1/debates/batch", json={"requests": requests}
        )

    async def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        """Get the status of a batch job."""
        return await self._client.request("GET", f"/api/v1/debates/batch/{batch_id}/status")

    async def list_batches(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List all batch jobs."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return await self._client.request("GET", "/api/v1/debates/batch", params=params)

    async def get_queue_status(self) -> dict[str, Any]:
        """Get the current queue status."""
        return await self._client.request("GET", "/api/v1/debates/queue/status")

    # ========== RLM / Compression ==========

    async def compress(
        self,
        debate_id: str,
        target_levels: _List[str] | None = None,
        compression_ratio: float = 0.3,
    ) -> dict[str, Any]:
        """Compress debate context using RLM hierarchical abstraction.

        Args:
            debate_id: The debate ID
            target_levels: Abstraction levels to generate (e.g. ["ABSTRACT", "SUMMARY", "DETAILED"])
            compression_ratio: Target compression ratio (0.0-1.0, default 0.3)

        Returns:
            Compression result with original_tokens, compressed_tokens, compression_ratios,
            time_seconds, and levels_created
        """
        payload: dict[str, Any] = {"compression_ratio": compression_ratio}
        if target_levels:
            payload["target_levels"] = target_levels
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/compress", json=payload
        )

    async def get_context_level(self, debate_id: str, level: str) -> dict[str, Any]:
        """Get debate content at a specific abstraction level.

        Args:
            debate_id: The debate ID
            level: Abstraction level (ABSTRACT, SUMMARY, DETAILED, or RAW)

        Returns:
            Context at the requested level with content, token_count, and nodes
        """
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/context/{level}")

    async def query_rlm(
        self,
        debate_id: str,
        query: str,
        strategy: str = "auto",
        max_iterations: int = 3,
        start_level: str = "SUMMARY",
    ) -> dict[str, Any]:
        """Query a debate using RLM with iterative refinement.

        Args:
            debate_id: The debate ID
            query: The question to ask about the debate
            strategy: Query strategy (auto, peek, grep, partition_map, summarize, hierarchical)
            max_iterations: Maximum refinement iterations (1-10, default 3)
            start_level: Starting abstraction level (ABSTRACT, SUMMARY, DETAILED, RAW)

        Returns:
            Query result with answer, confidence, refinement_history, and token usage
        """
        return await self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/query-rlm",
            json={
                "query": query,
                "strategy": strategy,
                "max_iterations": max_iterations,
                "start_level": start_level,
            },
        )

    async def get_refinement_status(self, debate_id: str) -> dict[str, Any]:
        """Get the status of an ongoing RLM refinement process.

        Args:
            debate_id: The debate ID

        Returns:
            Refinement status with active_queries, cached_contexts, and status
        """
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/refinement-status")

    # ========== Decision Integrity ==========

    async def get_decision_integrity(self, debate_id: str) -> dict[str, Any]:
        """Get the decision integrity package for a debate.

        Generates a decision receipt and implementation plan bundle
        containing audit-ready documentation of the debate outcome.

        Args:
            debate_id: The debate ID

        Returns:
            Decision integrity package with receipt and implementation plan
        """
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/decision-integrity")

    # ========== Cost Estimation ==========

    async def estimate_cost(
        self,
        num_agents: int = 3,
        num_rounds: int = 9,
        model_types: _List[str] | None = None,
    ) -> dict[str, Any]:
        """Estimate the cost of a debate before creation.

        Args:
            num_agents: Number of participating agents (1-8, default 3)
            num_rounds: Number of debate rounds (1-12, default 9)
            model_types: List of model names to use (optional)

        Returns:
            Cost estimation with total, per-model breakdown, and assumptions
        """
        params: dict[str, Any] = {
            "num_agents": num_agents,
            "num_rounds": num_rounds,
        }
        if model_types:
            params["model_types"] = ",".join(model_types)
        return await self._client.request("GET", "/api/v1/debates/estimate-cost", params=params)

    # ========== Quick Debate ==========

    async def quick_debate(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """Create a debate via the non-versioned quick endpoint."""
        data: dict[str, Any] = {"task": task, **kwargs}
        return await self._client.request("POST", "/api/debate", json=data)

    # ========== Analytics ==========

    async def get_consensus_analytics(self) -> dict[str, Any]:
        """Get consensus analytics across debates."""
        return await self._client.request("GET", "/api/v1/debates/analytics/consensus")

    async def get_trend_analytics(self) -> dict[str, Any]:
        """Get debate trend analytics."""
        return await self._client.request("GET", "/api/v1/debates/analytics/trends")

    # ========== Archive ==========

    async def archive_batch(self, debate_ids: _List[str]) -> dict[str, Any]:
        """Archive multiple debates."""
        return await self._client.request(
            "POST", "/api/v1/debates/archive/batch", json={"debate_ids": debate_ids}
        )

    async def list_archived(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List archived debates."""
        return await self._client.request(
            "GET", "/api/v1/debates/archived", params={"limit": limit, "offset": offset}
        )

    # ========== Compare & Import ==========

    async def compare(self, debate_ids: _List[str]) -> dict[str, Any]:
        """Compare multiple debates."""
        return await self._client.request(
            "POST", "/api/v1/debates/compare", json={"debate_ids": debate_ids}
        )

    async def get_health(self) -> dict[str, Any]:
        """Get debate system health."""
        return await self._client.request("GET", "/api/v1/debates/health")

    async def import_debate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import a debate from external data."""
        return await self._client.request("POST", "/api/v1/debates/import", json=data)

    async def get_statistics(self) -> dict[str, Any]:
        """Get aggregate debate statistics."""
        return await self._client.request("GET", "/api/v1/debates/statistics")

    async def stream_debate(self, debate_id: str) -> dict[str, Any]:
        """Get streaming info for a debate."""
        return await self._client.request(
            "GET", "/api/v1/debates/stream", params={"debate_id": debate_id}
        )

    # ========== Stats & Diagnostics ==========

    async def get_stats(self) -> dict[str, Any]:
        """Get debate stats."""
        return await self._client.request("GET", "/api/debates/stats")

    async def get_agent_stats(self) -> dict[str, Any]:
        """Get per-agent debate statistics."""
        return await self._client.request("GET", "/api/debates/stats/agents")

    async def get_diagnostics(self, debate_id: str) -> dict[str, Any]:
        """Get diagnostics for a debate."""
        return await self._client.request("GET", f"/api/debates/{debate_id}/diagnostics")

    async def get_costs(self, debate_id: str) -> dict[str, Any]:
        """Get per-debate cost breakdown."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/costs")

    async def get_events(
        self,
        debate_id: str,
        *,
        since: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get debate events for polling fallback."""
        return await self._client.request(
            "GET",
            f"/api/v1/debates/{debate_id}/events",
            params={"since": since, "limit": limit},
        )

    async def get_positions(self, debate_id: str) -> dict[str, Any]:
        """Get position evolution per agent."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/positions")

    # Package & Share
    async def get_package(self, debate_id: str) -> dict[str, Any]:
        """Get a portable debate package."""
        return await self._client.request("GET", f"/api/debates/{debate_id}/package")

    async def get_package_markdown(self, debate_id: str) -> dict[str, Any]:
        """Get a debate package in Markdown format."""
        return await self._client.request("GET", f"/api/debates/{debate_id}/package/markdown")

    async def share(self, debate_id: str, **kwargs: Any) -> dict[str, Any]:
        """Create a shareable link for a debate."""
        return await self._client.request("POST", f"/api/debates/{debate_id}/share", json=kwargs)

    async def revoke_share(self, debate_id: str) -> dict[str, Any]:
        """Revoke a shared debate link."""
        return await self._client.request("POST", f"/api/debates/{debate_id}/share/revoke")

    async def get_shared(self, share_token: str) -> dict[str, Any]:
        """View a publicly shared debate by share token."""
        return await self._client.request("GET", f"/api/v1/shared/{share_token}")

    async def get_public_spectate(self, debate_id: str) -> dict[str, Any]:
        """Get the public spectate view for a debate."""
        return await self._client.request("GET", f"/api/debates/{debate_id}/spectate/public")

    async def get_public_debate(self, debate_id: str) -> dict[str, Any]:
        """Get a publicly shared debate by ID (no auth required)."""
        return await self._client.request("GET", f"/api/debates/public/{debate_id}")

    async def get_public_debate_og(self, debate_id: str) -> dict[str, Any]:
        """Get Open Graph metadata for a publicly shared debate."""
        return await self._client.request("GET", f"/api/debates/public/{debate_id}/og")

    # ========== One-Click Debate ==========

    async def debate_this(
        self,
        question: str,
        *,
        context: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """One-click debate launcher. POST /api/v1/debate-this"""
        data: dict[str, Any] = {"question": question}
        if context is not None:
            data["context"] = context
        if source is not None:
            data["source"] = source
        return await self._client.request("POST", "/api/v1/debate-this", json=data)

    # ========== Intervention & Reasoning ==========

    async def intervene(
        self,
        debate_id: str,
        intervention_type: str,
        content: str,
        apply_at_round: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Submit a mid-debate intervention.

        Args:
            debate_id: The debate ID
            intervention_type: Type of intervention (redirect, constraint, challenge, evidence_request)
            content: Intervention content
            apply_at_round: Round to apply at (0 = next available)
            **kwargs: Additional metadata

        Returns:
            Dict with intervention_id, status, and apply_at_round
        """
        data: dict[str, Any] = {
            "type": intervention_type,
            "content": content,
            "apply_at_round": apply_at_round,
            **kwargs,
        }
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/intervene", json=data
        )

    async def get_reasoning(self, debate_id: str) -> dict[str, Any]:
        """Get per-agent reasoning summary for a debate.

        Returns agent reasoning chains, key cruxes, and unresolved
        disagreements.

        Args:
            debate_id: The debate ID

        Returns:
            Dict with agents, cruxes, unresolved_disagreements, and interventions
        """
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/reasoning")

    # ========== CRUD & Lifecycle ==========

    async def get(self, debate_id: str) -> dict[str, Any]:
        """Get a debate by ID."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}")

    async def get_by_slug(self, slug: str) -> dict[str, Any]:
        """Get a debate by its URL slug."""
        return await self._client.request("GET", f"/api/v1/debates/slug/{slug}")

    async def delete(self, debate_id: str) -> dict[str, Any]:
        """Delete a debate."""
        return await self._client.request("DELETE", f"/api/v1/debates/{debate_id}")

    async def update(self, debate_id: str, **updates: Any) -> dict[str, Any]:
        """Update an existing debate."""
        return await self._client.request("PUT", f"/api/v1/debates/{debate_id}", json=updates)

    async def get_metadata(self, debate_id: str) -> dict[str, Any]:
        """Get debate metadata."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/metadata")

    async def start(self, debate_id: str) -> dict[str, Any]:
        """Start a debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/start")

    async def stop(self, debate_id: str) -> dict[str, Any]:
        """Stop a running debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/stop")

    async def pause(self, debate_id: str) -> dict[str, Any]:
        """Pause a running debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/pause")

    async def resume(self, debate_id: str) -> dict[str, Any]:
        """Resume a paused debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/resume")

    async def restore(self, debate_id: str) -> dict[str, Any]:
        """Restore an archived debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/restore")

    async def make_permanent(self, debate_id: str) -> dict[str, Any]:
        """Make a debate permanent."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/make-permanent")

    async def clone(self, debate_id: str, **options: Any) -> dict[str, Any]:
        """Clone a debate with fresh state."""
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/clone", json=options
        )

    async def archive(self, debate_id: str) -> dict[str, Any]:
        """Archive a single debate."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/archive")

    async def export_format(self, debate_id: str, format: str = "json") -> dict[str, Any]:
        """Export a debate in a specific format."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/export", params={"format": format}
        )

    # ========== Rounds, Agents, Votes ==========

    async def get_rounds(self, debate_id: str) -> dict[str, Any]:
        """Get rounds from a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/rounds")

    async def get_agents(self, debate_id: str) -> dict[str, Any]:
        """Get agents participating in a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/agents")

    async def get_votes(self, debate_id: str) -> dict[str, Any]:
        """Get votes from a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/votes")

    async def get_consensus(self, debate_id: str) -> dict[str, Any]:
        """Get consensus information for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/consensus")

    async def add_user_input(
        self, debate_id: str, input: str, input_type: str = "suggestion"
    ) -> dict[str, Any]:
        """Add user input to a debate."""
        return await self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/user-input",
            json={"input": input, "type": input_type},
        )

    async def get_timeline(self, debate_id: str) -> dict[str, Any]:
        """Get the timeline of events in a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/timeline")

    async def get_tags(self, debate_id: str) -> dict[str, Any]:
        """Get tags for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/tags")

    async def find_similar(self, debate_id: str, limit: int = 5) -> dict[str, Any]:
        """Find debates similar to this one."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/similar", params={"limit": limit}
        )

    # ========== Graph & Matrix ==========

    async def get_graph(self, debate_id: str) -> dict[str, Any]:
        """Get the argument graph for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/graph/{debate_id}")

    async def get_graph_branches(self, debate_id: str) -> dict[str, Any]:
        """Get branches in the argument graph."""
        return await self._client.request("GET", f"/api/v1/debates/graph/{debate_id}/branches")

    async def get_matrix_comparison(self, debate_id: str) -> dict[str, Any]:
        """Get matrix comparison for a multi-scenario debate."""
        return await self._client.request("GET", f"/api/v1/debates/matrix/{debate_id}")

    # ========== Explainability ==========

    async def get_explainability(self, debate_id: str) -> dict[str, Any]:
        """Get explainability data for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/explainability")

    async def get_explainability_factors(self, debate_id: str) -> dict[str, Any]:
        """Get factor decomposition for a debate decision."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/explainability/factors"
        )

    async def get_explainability_narrative(self, debate_id: str) -> dict[str, Any]:
        """Get natural language narrative explanation."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/explainability/narrative"
        )

    async def get_explainability_provenance(self, debate_id: str) -> dict[str, Any]:
        """Get provenance chain for debate claims."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/explainability/provenance"
        )

    async def get_explainability_counterfactual(self, debate_id: str) -> dict[str, Any]:
        """Get counterfactual analysis."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/explainability/counterfactual"
        )

    async def create_counterfactual(
        self, debate_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a counterfactual scenario."""
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/explainability/counterfactual", json=changes
        )

    # ========== Red Team & Analysis ==========

    async def get_red_team(self, debate_id: str) -> dict[str, Any]:
        """Get red team analysis for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/red-team")

    async def get_rhetorical(self, debate_id: str) -> dict[str, Any]:
        """Get rhetorical pattern observations."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/rhetorical")

    async def get_trickster(self, debate_id: str) -> dict[str, Any]:
        """Get trickster hollow consensus detection status."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/trickster")

    async def get_meta_critique(self, debate_id: str) -> dict[str, Any]:
        """Get meta-level critique of the debate."""
        return await self._client.request("GET", f"/api/v1/debate/{debate_id}/meta-critique")

    async def get_quality(self, debate_id: str) -> dict[str, Any]:
        """Get argument quality analysis."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/quality")

    async def verify_claim(
        self, debate_id: str, claim_id: str, evidence: str | None = None
    ) -> dict[str, Any]:
        """Verify a specific claim from the debate."""
        data: dict[str, Any] = {"claim_id": claim_id}
        if evidence is not None:
            data["evidence"] = evidence
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/verify", json=data)

    # ========== Notes ==========

    async def get_notes(self, debate_id: str) -> dict[str, Any]:
        """Get notes attached to a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/notes")

    async def add_note(self, debate_id: str, content: str) -> dict[str, Any]:
        """Add a note to a debate."""
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/notes", json={"content": content}
        )

    async def delete_note(self, debate_id: str, note_id: str) -> dict[str, Any]:
        """Delete a note from a debate."""
        return await self._client.request("DELETE", f"/api/v1/debates/{debate_id}/notes/{note_id}")

    # ========== Batch Results ==========

    async def get_batch_results(self, batch_id: str) -> dict[str, Any]:
        """Get results of a batch job."""
        return await self._client.request("GET", f"/api/v1/debates/batch/{batch_id}/results")

    async def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        """Cancel a batch job."""
        return await self._client.request("POST", f"/api/v1/debates/batch/{batch_id}/cancel")

    async def retry_batch(self, batch_id: str) -> dict[str, Any]:
        """Retry failed jobs in a batch."""
        return await self._client.request("POST", f"/api/v1/debates/batch/{batch_id}/retry")

    # ========== Agent & Debate Health ==========

    async def get_agent_statistics(self, debate_id: str) -> dict[str, Any]:
        """Get per-agent statistics for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/agent-statistics")

    async def get_debate_health(self, debate_id: str) -> dict[str, Any]:
        """Get health status for a specific debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/health")

    # ========== Intervention ==========

    async def intervention_pause(self, debate_id: str) -> dict[str, Any]:
        """Pause debate via intervention."""
        return await self._client.request("POST", f"/api/v1/debates/{debate_id}/intervention/pause")

    async def intervention_resume(self, debate_id: str) -> dict[str, Any]:
        """Resume debate via intervention."""
        return await self._client.request(
            "POST", f"/api/v1/debates/{debate_id}/intervention/resume"
        )

    async def intervention_inject(
        self, debate_id: str, content: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Inject content into a debate via intervention."""
        return await self._client.request(
            "POST",
            f"/api/v1/debates/{debate_id}/intervention/inject",
            json={"content": content, **kwargs},
        )

    async def get_intervention_log(self, debate_id: str) -> dict[str, Any]:
        """Get the intervention log for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/intervention/log")

    async def get_intervention_state(self, debate_id: str) -> dict[str, Any]:
        """Get current intervention state for a debate."""
        return await self._client.request("GET", f"/api/v1/debates/{debate_id}/intervention/state")

    async def set_intervention_threshold(self, debate_id: str, threshold: float) -> dict[str, Any]:
        """Set the intervention threshold for a debate."""
        return await self._client.request(
            "PUT",
            f"/api/v1/debates/{debate_id}/intervention/threshold",
            json={"threshold": threshold},
        )

    async def set_intervention_weights(
        self, debate_id: str, weights: dict[str, float]
    ) -> dict[str, Any]:
        """Set intervention weights for a debate."""
        return await self._client.request(
            "PUT", f"/api/v1/debates/{debate_id}/intervention/weights", json={"weights": weights}
        )

    async def get_youtube_publish_status(self, debate_id: str) -> dict[str, Any]:
        """Get YouTube publish status for a debate."""
        return await self._client.request(
            "GET", f"/api/v1/debates/{debate_id}/publish/youtube/status"
        )
