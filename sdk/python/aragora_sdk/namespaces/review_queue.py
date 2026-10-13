"""
Review Queue Namespace API

Provides methods for the PDB (PR intelligence brief) review queue:
- List open PRs eligible for settlement
- Fetch brief content for a specific PR
- Approve / request-changes / defer settlement actions
- Read session stats (streak, decision time, totals)

All mutating actions preserve the settlement gate: the approve and
request-changes endpoints proxy a GitHub review using the caller's
authenticated identity, not automation credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class ReviewQueueAPI:
    """
    Synchronous Review Queue API.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> prs = client.review_queue.list_prs()
        >>> for pr in prs["prs"]:
        ...     print(pr["number"], pr["title"])
    """

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def list_prs(self, *, include_deferred: bool = False) -> dict[str, Any]:
        """List open PRs currently in the review queue.

        Args:
            include_deferred: If True, include PRs that were deferred. Defaults to False.
        """
        params: dict[str, Any] = {}
        if include_deferred:
            params["include_deferred"] = "1"
        return self._client.request("GET", "/api/v1/review-queue/prs", params=params)

    def get_brief(self, pr_number: int) -> dict[str, Any]:
        """Fetch the PDB brief for a specific PR, or 404 if no brief exists."""
        return self._client.request("GET", f"/api/v1/review-queue/prs/{pr_number}/brief")

    def approve(self, pr_number: int, *, note: str | None = None) -> dict[str, Any]:
        """Submit a GitHub APPROVE review for the PR using the caller's identity."""
        body: dict[str, Any] = {}
        if note is not None:
            body["note"] = note
        return self._client.request(
            "POST", f"/api/v1/review-queue/prs/{pr_number}/approve", json=body
        )

    def request_changes(self, pr_number: int, *, reason: str) -> dict[str, Any]:
        """Submit a GitHub REQUEST_CHANGES review for the PR with a required reason."""
        return self._client.request(
            "POST",
            f"/api/v1/review-queue/prs/{pr_number}/request-changes",
            json={"reason": reason},
        )

    def defer(self, pr_number: int) -> dict[str, Any]:
        """Defer the PR locally (hides it from the queue for ~4 hours)."""
        return self._client.request("POST", f"/api/v1/review-queue/prs/{pr_number}/defer")

    def stats(self) -> dict[str, Any]:
        """Fetch session stats: approvals today, median decision time, streak."""
        return self._client.request("GET", "/api/v1/review-queue/stats")

    def triage_metrics(self) -> dict[str, Any]:
        """Fetch rolling-window triage metrics (7-day and 30-day windows)."""
        return self._client.request("GET", "/api/v1/review-queue/triage-metrics")


class AsyncReviewQueueAPI:
    """
    Asynchronous Review Queue API.

    Example:
        >>> client = AragoraAsyncClient(base_url="https://api.aragora.ai")
        >>> prs = await client.review_queue.list_prs()
    """

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def list_prs(self, *, include_deferred: bool = False) -> dict[str, Any]:
        """List open PRs currently in the review queue."""
        params: dict[str, Any] = {}
        if include_deferred:
            params["include_deferred"] = "1"
        return await self._client.request("GET", "/api/v1/review-queue/prs", params=params)

    async def get_brief(self, pr_number: int) -> dict[str, Any]:
        """Fetch the PDB brief for a specific PR, or 404 if no brief exists."""
        return await self._client.request("GET", f"/api/v1/review-queue/prs/{pr_number}/brief")

    async def approve(self, pr_number: int, *, note: str | None = None) -> dict[str, Any]:
        """Submit a GitHub APPROVE review for the PR using the caller's identity."""
        body: dict[str, Any] = {}
        if note is not None:
            body["note"] = note
        return await self._client.request(
            "POST", f"/api/v1/review-queue/prs/{pr_number}/approve", json=body
        )

    async def request_changes(self, pr_number: int, *, reason: str) -> dict[str, Any]:
        """Submit a GitHub REQUEST_CHANGES review for the PR with a required reason."""
        return await self._client.request(
            "POST",
            f"/api/v1/review-queue/prs/{pr_number}/request-changes",
            json={"reason": reason},
        )

    async def defer(self, pr_number: int) -> dict[str, Any]:
        """Defer the PR locally (hides it from the queue for ~4 hours)."""
        return await self._client.request("POST", f"/api/v1/review-queue/prs/{pr_number}/defer")

    async def stats(self) -> dict[str, Any]:
        """Fetch session stats: approvals today, median decision time, streak."""
        return await self._client.request("GET", "/api/v1/review-queue/stats")

    async def triage_metrics(self) -> dict[str, Any]:
        """Fetch rolling-window triage metrics (7-day and 30-day windows)."""
        return await self._client.request("GET", "/api/v1/review-queue/triage-metrics")
