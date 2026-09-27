"""
Tournaments Namespace API

Provides methods for managing agent tournaments including brackets,
matches, standings, and results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

_List = list  # Preserve builtin list for type annotations

TournamentFormat = Literal["single_elimination", "double_elimination", "round_robin", "swiss"]
TournamentStatus = Literal["pending", "active", "completed", "cancelled"]


class TournamentsAPI:
    """
    Synchronous Tournaments API.

    Provides methods for managing tournaments:
    - Creating and listing tournaments
    - Viewing standings and brackets
    - Submitting match results
    - Advancing tournament rounds

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> tournament = client.tournaments.create(
        ...     name="Weekly Championship",
        ...     format="single_elimination",
        ...     participants=["claude", "gpt-4", "gemini", "grok"]
        ... )
        >>> standings = client.tournaments.get_standings(tournament["id"])
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    def list(
        self,
        status: TournamentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List tournaments with optional filtering.

        Args:
            status: Filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of tournaments with pagination
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return self._client.request("GET", "/api/v1/tournaments", params=params)

    def get(self, tournament_id: str) -> dict[str, Any]:
        """
        Get a tournament by ID.

        Args:
            tournament_id: Tournament identifier

        Returns:
            Tournament details
        """
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}")

    def create(
        self,
        name: str,
        format: TournamentFormat = "single_elimination",
        participants: _List[str] | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Create a new tournament.

        Args:
            name: Tournament name
            format: Tournament format
            participants: List of participant agent names
            description: Tournament description
            **kwargs: Additional tournament options

        Returns:
            Created tournament
        """
        data: dict[str, Any] = {"name": name, "format": format, **kwargs}
        if participants:
            data["participants"] = participants
        if description:
            data["description"] = description

        return self._client.request("POST", "/api/v1/tournaments", json=data)

    def get_standings(self, tournament_id: str) -> dict[str, Any]:
        """
        Get tournament standings.

        Args:
            tournament_id: Tournament identifier

        Returns:
            Tournament standings with rankings
        """
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/standings")

    def get_bracket(self, tournament_id: str) -> dict[str, Any]:
        """
        Get tournament bracket.

        Args:
            tournament_id: Tournament identifier

        Returns:
            Tournament bracket structure
        """
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/bracket")

    def list_matches(
        self,
        tournament_id: str,
        round: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """
        List matches in a tournament.

        Args:
            tournament_id: Tournament identifier
            round: Filter by round number
            status: Filter by match status

        Returns:
            List of matches
        """
        params: dict[str, Any] = {}
        if round is not None:
            params["round"] = round
        if status:
            params["status"] = status

        return self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/matches", params=params
        )

    def submit_result(
        self,
        tournament_id: str,
        match_id: str,
        winner: str,
        loser: str,
        score: dict[str, int] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a match result.

        Args:
            tournament_id: Tournament identifier
            match_id: Match identifier
            winner: Winner agent name
            loser: Loser agent name
            score: Optional match score {"winner": N, "loser": M}
            notes: Optional match notes

        Returns:
            Updated match with result
        """
        data: dict[str, Any] = {"winner": winner, "loser": loser}
        if score:
            data["score"] = score
        if notes:
            data["notes"] = notes

        return self._client.request(
            "POST",
            f"/api/v1/tournaments/{tournament_id}/matches/{match_id}/result",
            json=data,
        )

    def advance(self, tournament_id: str) -> dict[str, Any]:
        """
        Advance the tournament to the next round.

        Args:
            tournament_id: Tournament identifier

        Returns:
            Advancement result with next round info
        """
        return self._client.request("POST", f"/api/v1/tournaments/{tournament_id}/advance")

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self, tournament_id: str) -> dict[str, Any]:
        """Start a pending tournament."""
        return self._client.request("POST", f"/api/v1/tournaments/{tournament_id}/start")

    def cancel(self, tournament_id: str, reason: str | None = None) -> dict[str, Any]:
        """Cancel a tournament."""
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason
        return self._client.request(
            "POST", f"/api/v1/tournaments/{tournament_id}/cancel", json=data
        )

    def get_match(self, tournament_id: str, match_id: str) -> dict[str, Any]:
        """Get a specific match."""
        return self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/matches/{match_id}"
        )

    def schedule_match(
        self, tournament_id: str, match_id: str, scheduled_at: str
    ) -> dict[str, Any]:
        """Schedule a match."""
        return self._client.request(
            "POST",
            f"/api/v1/tournaments/{tournament_id}/matches/{match_id}/schedule",
            json={"scheduled_at": scheduled_at},
        )

    def register(
        self,
        tournament_id: str,
        participant: str,
        seed: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a participant for a tournament."""
        data: dict[str, Any] = {"participant": participant}
        if seed is not None:
            data["seed"] = seed
        if metadata is not None:
            data["metadata"] = metadata
        return self._client.request(
            "POST", f"/api/v1/tournaments/{tournament_id}/register", json=data
        )

    def withdraw(
        self, tournament_id: str, participant: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Withdraw a participant from a tournament."""
        data: dict[str, Any] = {"participant": participant}
        if reason:
            data["reason"] = reason
        return self._client.request(
            "POST", f"/api/v1/tournaments/{tournament_id}/withdraw", json=data
        )

    def list_participants(self, tournament_id: str) -> dict[str, Any]:
        """List participants in a tournament."""
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/participants")

    def get_participant_history(self, tournament_id: str, participant: str) -> dict[str, Any]:
        """Get a participant's tournament history."""
        return self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/participants/{participant}/history"
        )

    def get_seeding(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament seeding."""
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/seeding")

    def set_seeding(self, tournament_id: str, **seeding: Any) -> dict[str, Any]:
        """Set tournament seeding."""
        return self._client.request(
            "PUT", f"/api/v1/tournaments/{tournament_id}/seeding", json=seeding
        )

    def get_stats(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament statistics."""
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/stats")

    def get_results(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament results."""
        return self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/results")

    def export(self, tournament_id: str, format: str = "json") -> dict[str, Any]:
        """Export tournament data."""
        return self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/export", params={"format": format}
        )

    def generate_report(self, tournament_id: str) -> dict[str, Any]:
        """Generate tournament report."""
        return self._client.request("POST", f"/api/v1/tournaments/{tournament_id}/report")


class AsyncTournamentsAPI:
    """
    Asynchronous Tournaments API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     tournaments = await client.tournaments.list(status="active")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def list(
        self,
        status: TournamentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List tournaments with optional filtering."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return await self._client.request("GET", "/api/v1/tournaments", params=params)

    async def get(self, tournament_id: str) -> dict[str, Any]:
        """Get a tournament by ID."""
        return await self._client.request("GET", f"/api/v1/tournaments/{tournament_id}")

    async def create(
        self,
        name: str,
        format: TournamentFormat = "single_elimination",
        participants: _List[str] | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new tournament."""
        data: dict[str, Any] = {"name": name, "format": format, **kwargs}
        if participants:
            data["participants"] = participants
        if description:
            data["description"] = description

        return await self._client.request("POST", "/api/v1/tournaments", json=data)

    async def get_standings(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament standings."""
        return await self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/standings")

    async def get_bracket(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament bracket."""
        return await self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/bracket")

    async def list_matches(
        self,
        tournament_id: str,
        round: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List matches in a tournament."""
        params: dict[str, Any] = {}
        if round is not None:
            params["round"] = round
        if status:
            params["status"] = status

        return await self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/matches", params=params
        )

    async def submit_result(
        self,
        tournament_id: str,
        match_id: str,
        winner: str,
        loser: str,
        score: dict[str, int] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Submit a match result."""
        data: dict[str, Any] = {"winner": winner, "loser": loser}
        if score:
            data["score"] = score
        if notes:
            data["notes"] = notes

        return await self._client.request(
            "POST",
            f"/api/v1/tournaments/{tournament_id}/matches/{match_id}/result",
            json=data,
        )

    async def advance(self, tournament_id: str) -> dict[str, Any]:
        """Advance the tournament to the next round."""
        return await self._client.request("POST", f"/api/v1/tournaments/{tournament_id}/advance")

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self, tournament_id: str) -> dict[str, Any]:
        """Start a pending tournament."""
        return await self._client.request("POST", f"/api/v1/tournaments/{tournament_id}/start")

    async def cancel(self, tournament_id: str, reason: str | None = None) -> dict[str, Any]:
        """Cancel a tournament."""
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason
        return await self._client.request(
            "POST", f"/api/v1/tournaments/{tournament_id}/cancel", json=data
        )

    async def get_match(self, tournament_id: str, match_id: str) -> dict[str, Any]:
        """Get a specific match."""
        return await self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/matches/{match_id}"
        )

    async def schedule_match(
        self, tournament_id: str, match_id: str, scheduled_at: str
    ) -> dict[str, Any]:
        """Schedule a match."""
        return await self._client.request(
            "POST",
            f"/api/v1/tournaments/{tournament_id}/matches/{match_id}/schedule",
            json={"scheduled_at": scheduled_at},
        )

    async def register(
        self,
        tournament_id: str,
        participant: str,
        seed: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a participant for a tournament."""
        data: dict[str, Any] = {"participant": participant}
        if seed is not None:
            data["seed"] = seed
        if metadata is not None:
            data["metadata"] = metadata
        return await self._client.request(
            "POST", f"/api/v1/tournaments/{tournament_id}/register", json=data
        )

    async def withdraw(
        self, tournament_id: str, participant: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Withdraw a participant from a tournament."""
        data: dict[str, Any] = {"participant": participant}
        if reason:
            data["reason"] = reason
        return await self._client.request(
            "POST", f"/api/v1/tournaments/{tournament_id}/withdraw", json=data
        )

    async def list_participants(self, tournament_id: str) -> dict[str, Any]:
        """List participants in a tournament."""
        return await self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/participants"
        )

    async def get_participant_history(self, tournament_id: str, participant: str) -> dict[str, Any]:
        """Get a participant's tournament history."""
        return await self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/participants/{participant}/history"
        )

    async def get_seeding(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament seeding."""
        return await self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/seeding")

    async def set_seeding(self, tournament_id: str, **seeding: Any) -> dict[str, Any]:
        """Set tournament seeding."""
        return await self._client.request(
            "PUT", f"/api/v1/tournaments/{tournament_id}/seeding", json=seeding
        )

    async def get_stats(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament statistics."""
        return await self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/stats")

    async def get_results(self, tournament_id: str) -> dict[str, Any]:
        """Get tournament results."""
        return await self._client.request("GET", f"/api/v1/tournaments/{tournament_id}/results")

    async def export(self, tournament_id: str, format: str = "json") -> dict[str, Any]:
        """Export tournament data."""
        return await self._client.request(
            "GET", f"/api/v1/tournaments/{tournament_id}/export", params={"format": format}
        )

    async def generate_report(self, tournament_id: str) -> dict[str, Any]:
        """Generate tournament report."""
        return await self._client.request("POST", f"/api/v1/tournaments/{tournament_id}/report")
