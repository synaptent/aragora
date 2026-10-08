"""
Debates API resource for the Aragora client.

Provides methods for creating, managing, and querying debates.
"""

from __future__ import annotations

import builtins
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import AsyncIterator, Iterator

from ..models import (
    ConsensusType,
    Debate,
    DebateCreateRequest,
    DebateCreateResponse,
    DebateStatus,
    DebateUpdateRequest,
    SearchResponse,
    VerificationReport,
)

from aragora.config import DEFAULT_AGENTS, DEFAULT_CONSENSUS, DEFAULT_ROUNDS

if TYPE_CHECKING:
    from ..client import AragoraClient

logger = logging.getLogger(__name__)


def _default_agent_list() -> list[str]:
    return [a.strip() for a in DEFAULT_AGENTS.split(",") if a.strip()]


class DebatesAPI:
    """API interface for debates."""

    def __init__(self, client: AragoraClient):
        self._client = client

    def create(
        self,
        task: str,
        agents: list[Any] | None = None,
        rounds: int = DEFAULT_ROUNDS,
        consensus: str = DEFAULT_CONSENSUS,
        context: str | None = None,
        auto_select: bool | None = None,
        auto_select_config: dict[str, Any] | None = None,
        debate_format: str | None = None,
        use_trending: bool | None = None,
        trending_category: str | None = None,
        documents: list[str] | None = None,
        enable_verticals: bool | None = None,
        vertical_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> DebateCreateResponse:
        """
        Create and start a new debate.

        Args:
            task: The question or topic to debate.
            agents: List of agent IDs to participate (default: config default agents).
            rounds: Number of debate rounds (default: config default rounds).
            consensus: Consensus mechanism (unanimous, majority, supermajority, hybrid).
            context: Additional context for the debate.

        Returns:
            DebateCreateResponse with debate_id and status.
        """
        metadata_payload: dict[str, Any] = dict(metadata or {})
        if kwargs:
            metadata_payload.update(kwargs)

        if agents is None:
            agents_payload: list[Any] = [] if auto_select else _default_agent_list()
        else:
            agents_payload = agents

        request = DebateCreateRequest(
            task=task,
            agents=agents_payload,
            rounds=rounds,
            consensus=ConsensusType(consensus),
            context=context,
            debate_format=debate_format,
            auto_select=auto_select,
            auto_select_config=auto_select_config,
            use_trending=use_trending,
            trending_category=trending_category,
            documents=documents,
            enable_verticals=enable_verticals,
            vertical_id=vertical_id,
            metadata=metadata_payload or None,
        )

        response = self._client._post("/api/debates", request.model_dump(exclude_none=True))
        return DebateCreateResponse(**response)

    async def create_async(
        self,
        task: str,
        agents: list[Any] | None = None,
        rounds: int = DEFAULT_ROUNDS,
        consensus: str = DEFAULT_CONSENSUS,
        context: str | None = None,
        auto_select: bool | None = None,
        auto_select_config: dict[str, Any] | None = None,
        debate_format: str | None = None,
        use_trending: bool | None = None,
        trending_category: str | None = None,
        documents: list[str] | None = None,
        enable_verticals: bool | None = None,
        vertical_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> DebateCreateResponse:
        """Async version of create()."""
        metadata_payload: dict[str, Any] = dict(metadata or {})
        if kwargs:
            metadata_payload.update(kwargs)

        if agents is None:
            agents_payload: list[Any] = [] if auto_select else _default_agent_list()
        else:
            agents_payload = agents

        request = DebateCreateRequest(
            task=task,
            agents=agents_payload,
            rounds=rounds,
            consensus=ConsensusType(consensus),
            context=context,
            debate_format=debate_format,
            auto_select=auto_select,
            auto_select_config=auto_select_config,
            use_trending=use_trending,
            trending_category=trending_category,
            documents=documents,
            enable_verticals=enable_verticals,
            vertical_id=vertical_id,
            metadata=metadata_payload or None,
        )

        response = await self._client._post_async(
            "/api/debates", request.model_dump(exclude_none=True)
        )
        return DebateCreateResponse(**response)

    def get(self, debate_id: str) -> Debate:
        """
        Get debate details by ID.

        Args:
            debate_id: The debate ID.

        Returns:
            Debate with full details including rounds and consensus.
        """
        response = self._client._get(f"/api/debates/{debate_id}")
        return Debate(**response)

    async def get_async(self, debate_id: str) -> Debate:
        """Async version of get()."""
        response = await self._client._get_async(f"/api/debates/{debate_id}")
        return Debate(**response)

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> builtins.list[Debate]:
        """
        List recent debates.

        Args:
            limit: Maximum number of debates to return.
            offset: Number of debates to skip.
            status: Filter by status (pending, running, completed, failed).

        Returns:
            List of Debate objects.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        response = self._client._get("/api/debates", params=params)
        debates = response.get("debates", response) if isinstance(response, dict) else response
        return [Debate(**d) for d in debates]

    async def list_async(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> builtins.list[Debate]:
        """Async version of list()."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        response = await self._client._get_async("/api/debates", params=params)
        debates = response.get("debates", response) if isinstance(response, dict) else response
        return [Debate(**d) for d in debates]

    def run(
        self,
        task: str,
        agents: builtins.list[Any] | None = None,
        rounds: int = DEFAULT_ROUNDS,
        consensus: str = DEFAULT_CONSENSUS,
        timeout: int = 600,
        auto_select: bool | None = None,
        auto_select_config: dict[str, Any] | None = None,
        debate_format: str | None = None,
        use_trending: bool | None = None,
        trending_category: str | None = None,
        documents: builtins.list[str] | None = None,
        enable_verticals: bool | None = None,
        vertical_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Debate:
        """
        Create a debate and wait for completion.

        This is a convenience method that creates a debate and polls
        until it completes or times out.

        Args:
            task: The question or topic to debate.
            agents: List of agent IDs to participate.
            rounds: Number of debate rounds.
            consensus: Consensus mechanism.
            timeout: Maximum wait time in seconds.

        Returns:
            Completed Debate with full results.
        """
        import time

        response = self.create(
            task=task,
            agents=agents,
            rounds=rounds,
            consensus=consensus,
            auto_select=auto_select,
            auto_select_config=auto_select_config,
            debate_format=debate_format,
            use_trending=use_trending,
            trending_category=trending_category,
            documents=documents,
            enable_verticals=enable_verticals,
            vertical_id=vertical_id,
            metadata=metadata,
            **kwargs,
        )
        debate_id = response.debate_id

        start = time.time()
        while time.time() - start < timeout:
            debate = self.get(debate_id)
            if debate.status in (DebateStatus.COMPLETED, DebateStatus.FAILED):
                return debate
            time.sleep(2)

        raise TimeoutError(f"Debate {debate_id} did not complete within {timeout}s")

    async def run_async(
        self,
        task: str,
        agents: builtins.list[Any] | None = None,
        rounds: int = DEFAULT_ROUNDS,
        consensus: str = DEFAULT_CONSENSUS,
        timeout: int = 600,
        auto_select: bool | None = None,
        auto_select_config: dict[str, Any] | None = None,
        debate_format: str | None = None,
        use_trending: bool | None = None,
        trending_category: str | None = None,
        documents: builtins.list[str] | None = None,
        enable_verticals: bool | None = None,
        vertical_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Debate:
        """Async version of run()."""
        import asyncio

        response = await self.create_async(
            task=task,
            agents=agents,
            rounds=rounds,
            consensus=consensus,
            auto_select=auto_select,
            auto_select_config=auto_select_config,
            debate_format=debate_format,
            use_trending=use_trending,
            trending_category=trending_category,
            documents=documents,
            enable_verticals=enable_verticals,
            vertical_id=vertical_id,
            metadata=metadata,
            **kwargs,
        )
        debate_id = response.debate_id

        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < timeout:
            debate = await self.get_async(debate_id)
            if debate.status in (DebateStatus.COMPLETED, DebateStatus.FAILED):
                return debate
            await asyncio.sleep(2)

        raise TimeoutError(f"Debate {debate_id} did not complete within {timeout}s")

    def wait_for_completion(
        self,
        debate_id: str,
        timeout: int = 600,
        poll_interval: float = 2.0,
    ) -> Debate:
        """
        Wait for an existing debate to complete.

        Args:
            debate_id: The debate ID to wait for.
            timeout: Maximum wait time in seconds (default: 600).
            poll_interval: Time between status checks in seconds (default: 2.0).

        Returns:
            Completed Debate with full results.

        Raises:
            TimeoutError: If debate doesn't complete within timeout.
        """
        import time

        start = time.time()
        while time.time() - start < timeout:
            debate = self.get(debate_id)
            if debate.status in (DebateStatus.COMPLETED, DebateStatus.FAILED):
                return debate
            time.sleep(poll_interval)

        raise TimeoutError(f"Debate {debate_id} did not complete within {timeout}s")

    async def wait_for_completion_async(
        self,
        debate_id: str,
        timeout: int = 600,
        poll_interval: float = 2.0,
    ) -> Debate:
        """
        Async version of wait_for_completion().

        Args:
            debate_id: The debate ID to wait for.
            timeout: Maximum wait time in seconds (default: 600).
            poll_interval: Time between status checks in seconds (default: 2.0).

        Returns:
            Completed Debate with full results.

        Raises:
            TimeoutError: If debate doesn't complete within timeout.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < timeout:
            debate = await self.get_async(debate_id)
            if debate.status in (DebateStatus.COMPLETED, DebateStatus.FAILED):
                return debate
            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Debate {debate_id} did not complete within {timeout}s")

    def compare(
        self,
        debate_ids: builtins.list[str],
    ) -> builtins.list[Debate]:
        """
        Get multiple debates for side-by-side comparison.

        Args:
            debate_ids: List of debate IDs to compare.

        Returns:
            List of Debate objects.
        """
        return [self.get(debate_id) for debate_id in debate_ids]

    async def compare_async(
        self,
        debate_ids: builtins.list[str],
    ) -> builtins.list[Debate]:
        """
        Async version of compare().

        Args:
            debate_ids: List of debate IDs to compare.

        Returns:
            List of Debate objects.
        """
        import asyncio

        return await asyncio.gather(*[self.get_async(debate_id) for debate_id in debate_ids])

    def decision_integrity(
        self,
        debate_id: str,
        *,
        include_receipt: bool | None = None,
        include_plan: bool | None = None,
        include_context: bool | None = None,
        plan_strategy: str | None = None,
        execution_mode: str | None = None,
        execution_engine: str | None = None,
        parallel_execution: bool | None = None,
        notify_origin: bool | None = None,
        risk_level: str | None = None,
        approval_mode: str | None = None,
        max_auto_risk: str | None = None,
        budget_limit_usd: float | None = None,
        openclaw_actions: builtins.list[dict[str, Any]] | None = None,
        computer_use_actions: builtins.list[dict[str, Any]] | None = None,
        openclaw_session: str | None = None,
        implementation_profile: dict[str, Any] | None = None,
        fabric_models: builtins.list[str] | None = None,
        channel_targets: builtins.list[str] | None = None,
        thread_id: str | None = None,
        thread_id_by_platform: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Build a Decision Integrity package for a completed debate.

        Returns receipt + implementation plan + optional context snapshot.
        """
        body: dict[str, Any] = {}
        if include_receipt is not None:
            body["include_receipt"] = include_receipt
        if include_plan is not None:
            body["include_plan"] = include_plan
        if include_context is not None:
            body["include_context"] = include_context
        if plan_strategy is not None:
            body["plan_strategy"] = plan_strategy
        if execution_mode is not None:
            body["execution_mode"] = execution_mode
        if execution_engine is not None:
            body["execution_engine"] = execution_engine
        if parallel_execution is not None:
            body["parallel_execution"] = parallel_execution
        if notify_origin is not None:
            body["notify_origin"] = notify_origin
        if risk_level is not None:
            body["risk_level"] = risk_level
        if approval_mode is not None:
            body["approval_mode"] = approval_mode
        if max_auto_risk is not None:
            body["max_auto_risk"] = max_auto_risk
        if budget_limit_usd is not None:
            body["budget_limit_usd"] = budget_limit_usd
        if openclaw_actions is not None:
            body["openclaw_actions"] = openclaw_actions
        if computer_use_actions is not None:
            body["computer_use_actions"] = computer_use_actions
        if openclaw_session is not None:
            body["openclaw_session"] = openclaw_session
        if implementation_profile is not None:
            body["implementation_profile"] = implementation_profile
        if fabric_models is not None:
            body["fabric_models"] = fabric_models
        if channel_targets is not None:
            body["channel_targets"] = channel_targets
        if thread_id is not None:
            body["thread_id"] = thread_id
        if thread_id_by_platform is not None:
            body["thread_id_by_platform"] = thread_id_by_platform

        return self._client._post(
            f"/api/v1/debates/{debate_id}/decision-integrity",
            body,
        )

    async def decision_integrity_async(
        self,
        debate_id: str,
        *,
        include_receipt: bool | None = None,
        include_plan: bool | None = None,
        include_context: bool | None = None,
        plan_strategy: str | None = None,
        execution_mode: str | None = None,
        execution_engine: str | None = None,
        parallel_execution: bool | None = None,
        notify_origin: bool | None = None,
        risk_level: str | None = None,
        approval_mode: str | None = None,
        max_auto_risk: str | None = None,
        budget_limit_usd: float | None = None,
        openclaw_actions: builtins.list[dict[str, Any]] | None = None,
        computer_use_actions: builtins.list[dict[str, Any]] | None = None,
        openclaw_session: str | None = None,
        implementation_profile: dict[str, Any] | None = None,
        fabric_models: builtins.list[str] | None = None,
        channel_targets: builtins.list[str] | None = None,
        thread_id: str | None = None,
        thread_id_by_platform: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Async version of decision_integrity()."""
        body: dict[str, Any] = {}
        if include_receipt is not None:
            body["include_receipt"] = include_receipt
        if include_plan is not None:
            body["include_plan"] = include_plan
        if include_context is not None:
            body["include_context"] = include_context
        if plan_strategy is not None:
            body["plan_strategy"] = plan_strategy
        if execution_mode is not None:
            body["execution_mode"] = execution_mode
        if execution_engine is not None:
            body["execution_engine"] = execution_engine
        if parallel_execution is not None:
            body["parallel_execution"] = parallel_execution
        if notify_origin is not None:
            body["notify_origin"] = notify_origin
        if risk_level is not None:
            body["risk_level"] = risk_level
        if approval_mode is not None:
            body["approval_mode"] = approval_mode
        if max_auto_risk is not None:
            body["max_auto_risk"] = max_auto_risk
        if budget_limit_usd is not None:
            body["budget_limit_usd"] = budget_limit_usd
        if openclaw_actions is not None:
            body["openclaw_actions"] = openclaw_actions
        if computer_use_actions is not None:
            body["computer_use_actions"] = computer_use_actions
        if openclaw_session is not None:
            body["openclaw_session"] = openclaw_session
        if implementation_profile is not None:
            body["implementation_profile"] = implementation_profile
        if fabric_models is not None:
            body["fabric_models"] = fabric_models
        if channel_targets is not None:
            body["channel_targets"] = channel_targets
        if thread_id is not None:
            body["thread_id"] = thread_id
        if thread_id_by_platform is not None:
            body["thread_id_by_platform"] = thread_id_by_platform

        return await self._client._post_async(
            f"/api/v1/debates/{debate_id}/decision-integrity",
            body,
        )

    def batch_get(
        self,
        debate_ids: builtins.list[str],
        max_concurrent: int = 10,
    ) -> builtins.list[Debate]:
        """
        Batch fetch multiple debates efficiently.

        Fetches debates sequentially in sync mode but allows controlling
        the batch size to avoid overwhelming the server.

        Args:
            debate_ids: List of debate IDs to fetch.
            max_concurrent: Maximum concurrent requests (for pacing).

        Returns:
            List of Debate objects (in same order as input IDs).
        """
        results = []
        for i, debate_id in enumerate(debate_ids):
            results.append(self.get(debate_id))
            # Add small delay every max_concurrent requests
            if (i + 1) % max_concurrent == 0 and i < len(debate_ids) - 1:
                import time

                time.sleep(0.1)
        return results

    async def batch_get_async(
        self,
        debate_ids: builtins.list[str],
        max_concurrent: int = 10,
    ) -> builtins.list[Debate]:
        """
        Batch fetch multiple debates with concurrency control.

        Uses asyncio.Semaphore to limit concurrent requests.

        Args:
            debate_ids: List of debate IDs to fetch.
            max_concurrent: Maximum concurrent requests (default: 10).

        Returns:
            List of Debate objects (in same order as input IDs).
        """
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_limit(debate_id: str) -> Debate:
            async with semaphore:
                return await self.get_async(debate_id)

        return await asyncio.gather(*[fetch_with_limit(did) for did in debate_ids])

    def iterate(
        self,
        status: str | None = None,
        page_size: int = 50,
        max_items: int | None = None,
    ) -> Iterator[Debate]:
        """
        Iterate through all debates with automatic pagination.

        Lazily fetches pages as needed, making it memory-efficient
        for large result sets.

        Args:
            status: Optional status filter.
            page_size: Number of items per page (default: 50).
            max_items: Maximum total items to return (default: unlimited).

        Yields:
            Debate objects one at a time.
        """
        offset = 0
        count = 0

        while True:
            debates = self.list(limit=page_size, offset=offset, status=status)
            if not debates:
                break

            for debate in debates:
                yield debate
                count += 1
                if max_items and count >= max_items:
                    return

            if len(debates) < page_size:
                break
            offset += page_size

    async def iterate_async(
        self,
        status: str | None = None,
        page_size: int = 50,
        max_items: int | None = None,
    ) -> AsyncIterator[Debate]:
        """
        Async iterate through all debates with automatic pagination.

        Lazily fetches pages as needed, making it memory-efficient
        for large result sets.

        Args:
            status: Optional status filter.
            page_size: Number of items per page (default: 50).
            max_items: Maximum total items to return (default: unlimited).

        Yields:
            Debate objects one at a time.
        """
        offset = 0
        count = 0

        while True:
            debates = await self.list_async(limit=page_size, offset=offset, status=status)
            if not debates:
                break

            for debate in debates:
                yield debate
                count += 1
                if max_items and count >= max_items:
                    return

            if len(debates) < page_size:
                break
            offset += page_size

    def update(
        self,
        debate_id: str,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
        archived: bool | None = None,
        notes: str | None = None,
    ) -> Debate:
        """
        Update debate metadata.

        Args:
            debate_id: The debate ID.
            status: New status.
            metadata: Metadata to update.
            tags: Tags to set.
            archived: Archive status.
            notes: Notes to add.

        Returns:
            Updated Debate.
        """
        request = DebateUpdateRequest(
            status=DebateStatus(status) if status else None,
            metadata=metadata,
            tags=tags,
            archived=archived,
            notes=notes,
        )
        response = self._client._patch(
            f"/api/v1/debates/{debate_id}", request.model_dump(exclude_none=True)
        )
        return Debate(**response)

    async def update_async(
        self,
        debate_id: str,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
        archived: bool | None = None,
        notes: str | None = None,
    ) -> Debate:
        """Async version of update()."""
        request = DebateUpdateRequest(
            status=DebateStatus(status) if status else None,
            metadata=metadata,
            tags=tags,
            archived=archived,
            notes=notes,
        )
        response = await self._client._patch_async(
            f"/api/v1/debates/{debate_id}", request.model_dump(exclude_none=True)
        )
        return Debate(**response)

    def get_verification_report(self, debate_id: str) -> VerificationReport:
        """
        Get verification report for a debate.

        Args:
            debate_id: The debate ID.

        Returns:
            VerificationReport with claim verification details.
        """
        response = self._client._get(f"/api/v1/debates/{debate_id}/verification-report")
        return VerificationReport(**response)

    async def get_verification_report_async(self, debate_id: str) -> VerificationReport:
        """Async version of get_verification_report()."""
        response = await self._client._get_async(f"/api/v1/debates/{debate_id}/verification-report")
        return VerificationReport(**response)

    def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """
        Search debates.

        Args:
            query: Search query string.
            limit: Maximum results to return.
            offset: Results to skip.

        Returns:
            SearchResponse with results and facets.
        """
        params: dict[str, Any] = {"q": query, "limit": limit, "offset": offset}
        response = self._client._get("/api/v1/search", params=params)
        return SearchResponse(**response)

    async def search_async(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Async version of search()."""
        params: dict[str, Any] = {"q": query, "limit": limit, "offset": offset}
        response = await self._client._get_async("/api/v1/search", params=params)
        return SearchResponse(**response)
