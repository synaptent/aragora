"""
GraphQL DataLoaders for batching database queries.

DataLoaders solve the N+1 query problem by batching multiple individual
requests into a single database query. They collect all requests within
a single event loop tick and execute them together.

Usage:
    from aragora.server.graphql.dataloaders import DataLoaderContext, create_loaders

    # Create loaders with server context
    loaders = create_loaders(server_context)

    # Use in resolvers
    agent = await loaders.agent_loader.load("claude")
    agents = await loaders.agent_loader.load_many(["claude", "gpt4", "gemini"])
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from aragora.ranking.elo import EloSystem

logger = logging.getLogger(__name__)

K = TypeVar("K")
V = TypeVar("V")


class DataLoader(Generic[K, V]):
    """
    Generic DataLoader that batches individual load requests.

    Collects all load() calls within a single event loop tick and executes
    them together via the batch_load_fn.

    Attributes:
        batch_load_fn: Async function that takes list of keys and returns list of values
        cache: Optional dict for caching results (default: enabled)
        max_batch_size: Maximum keys per batch (default: 100)
    """

    def __init__(
        self,
        batch_load_fn: Any,  # Callable[[list[K]], Awaitable[list[V | None]]]
        cache: bool = True,
        max_batch_size: int = 100,
    ):
        self._batch_load_fn = batch_load_fn
        self._cache_enabled = cache
        self._cache: dict[K, V] = {} if cache else {}
        self._max_batch_size = max_batch_size
        self._queue: list[tuple[K, asyncio.Future[V | None]]] = []
        self._dispatch_scheduled = False

    async def load(self, key: K) -> V | None:
        """
        Load a single value by key.

        Multiple calls within the same event loop tick will be batched.

        Args:
            key: The key to load

        Returns:
            The value for the key, or None if not found
        """
        # Check cache first
        if self._cache_enabled and key in self._cache:
            return self._cache[key]

        # Create a future for this request
        loop = asyncio.get_running_loop()
        future: asyncio.Future[V | None] = loop.create_future()
        self._queue.append((key, future))

        # Schedule dispatch if not already scheduled
        if not self._dispatch_scheduled:
            self._dispatch_scheduled = True
            loop.call_soon(lambda: asyncio.create_task(self._dispatch()))

        return await future

    async def load_many(self, keys: list[K]) -> list[V | None]:
        """
        Load multiple values by keys.

        Args:
            keys: List of keys to load

        Returns:
            List of values (or None for missing keys), in same order as keys
        """
        return await asyncio.gather(*[self.load(key) for key in keys])

    async def _dispatch(self) -> None:
        """Execute batched load and resolve futures."""
        self._dispatch_scheduled = False

        if not self._queue:
            return

        # Take all queued items
        batch = self._queue[: self._max_batch_size]
        self._queue = self._queue[self._max_batch_size :]

        keys = [item[0] for item in batch]

        try:
            # Execute batch load
            values = await self._batch_load_fn(keys)

            # Resolve futures and cache results
            for i, (key, future) in enumerate(batch):
                value = values[i] if i < len(values) else None
                if self._cache_enabled and value is not None:
                    self._cache[key] = value
                if not future.done():
                    future.set_result(value)

        except Exception as e:  # noqa: BLE001 - Must propagate any batch load error to all waiting futures
            logger.exception("DataLoader batch load failed: %s", e)
            # Resolve all futures with error
            for _, future in batch:
                if not future.done():
                    future.set_exception(e)

        # If there are more items, schedule another dispatch
        if self._queue:
            self._dispatch_scheduled = True
            asyncio.get_running_loop().call_soon(lambda: asyncio.create_task(self._dispatch()))

    def clear(self, key: K | None = None) -> None:
        """
        Clear cached values.

        Args:
            key: Specific key to clear, or None to clear all
        """
        if key is None:
            self._cache.clear()
        elif key in self._cache:
            del self._cache[key]

    def prime(self, key: K, value: V) -> None:
        """
        Pre-populate cache with a known value.

        Args:
            key: The key
            value: The value to cache
        """
        if self._cache_enabled:
            self._cache[key] = value


@dataclass
class AgentData:
    """Resolved agent data for GraphQL responses."""

    id: str
    name: str
    elo: float = 1500.0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_games: int = 0
    win_rate: float = 0.0
    calibration_accuracy: float | None = None
    consistency_score: float | None = None

    @classmethod
    def from_agent_rating(cls, rating: Any) -> AgentData:
        """Create from AgentRating dataclass."""
        total_games = rating.wins + rating.losses + rating.draws
        win_rate = rating.wins / total_games if total_games > 0 else 0.0

        calibration_accuracy = None
        if rating.calibration_total > 0:
            calibration_accuracy = rating.calibration_correct / rating.calibration_total

        return cls(
            id=rating.agent_name,
            name=rating.agent_name,
            elo=rating.elo,
            wins=rating.wins,
            losses=rating.losses,
            draws=rating.draws,
            total_games=total_games,
            win_rate=win_rate,
            calibration_accuracy=calibration_accuracy,
        )

    @classmethod
    def default(cls, agent_name: str) -> AgentData:
        """Create default agent data for unknown agents."""
        return cls(
            id=agent_name,
            name=agent_name,
            elo=1500.0,
            wins=0,
            losses=0,
            draws=0,
            total_games=0,
            win_rate=0.0,
        )


@dataclass
class DataLoaderContext:
    """
    Container for all DataLoaders used in GraphQL resolution.

    Create via create_loaders() and pass to ResolverContext.
    """

    agent_loader: DataLoader[str, AgentData]
    _elo_system: Any = field(repr=False)

    def clear_all(self) -> None:
        """Clear all loader caches."""
        self.agent_loader.clear()


async def _batch_load_agents(
    elo_system: EloSystem,
    agent_names: list[str],
) -> list[AgentData | None]:
    """
    Batch load function for agents.

    Args:
        elo_system: EloSystem instance
        agent_names: List of agent names to load

    Returns:
        List of AgentData in same order as input names
    """
    if not agent_names:
        return []

    try:
        # Use the existing batch method
        ratings = elo_system.get_ratings_batch(agent_names)

        # Return results in same order as input
        results: list[AgentData | None] = []
        for name in agent_names:
            if name in ratings:
                results.append(AgentData.from_agent_rating(ratings[name]))
            else:
                # Return default data for unknown agents
                results.append(AgentData.default(name))
        return results

    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
        logger.exception("Failed to batch load agents: %s", e)
        # Return defaults for all on error
        return [AgentData.default(name) for name in agent_names]


def create_loaders(server_context: dict[str, Any]) -> DataLoaderContext:
    """
    Create DataLoaders for a request.

    Call this once per request and pass to ResolverContext.

    Args:
        server_context: Server context with ELO system and storage

    Returns:
        DataLoaderContext with initialized loaders
    """
    elo_system = server_context.get("elo_system")

    # Create agent loader with bound elo_system
    async def batch_fn(keys: list[str]) -> list[AgentData | None]:
        if elo_system is None:
            return [AgentData.default(name) for name in keys]
        return await _batch_load_agents(elo_system, keys)

    agent_loader: DataLoader[str, AgentData] = DataLoader(
        batch_load_fn=batch_fn,
        cache=True,
        max_batch_size=100,
    )

    return DataLoaderContext(
        agent_loader=agent_loader,
        _elo_system=elo_system,
    )


# Convenience function for resolvers
async def load_agent_stats(
    loaders: DataLoaderContext | None,
    agent_name: str,
) -> dict[str, Any]:
    """
    Load agent stats for GraphQL response.

    Args:
        loaders: DataLoaderContext (optional)
        agent_name: Agent name to load

    Returns:
        Dict with agent stats for GraphQL schema
    """
    data: AgentData | None = None
    if loaders is not None:
        data = await loaders.agent_loader.load(agent_name)
    if data is None:
        data = AgentData.default(agent_name)

    return {
        "totalGames": data.total_games,
        "wins": data.wins,
        "losses": data.losses,
        "draws": data.draws,
        "winRate": data.win_rate,
        "elo": data.elo,
        "calibrationAccuracy": data.calibration_accuracy,
        "consistencyScore": data.consistency_score,
    }


async def load_agents_batch(
    loaders: DataLoaderContext | None,
    agent_names: list[str],
) -> list[dict[str, Any]]:
    """
    Load multiple agents' data for GraphQL response.

    Args:
        loaders: DataLoaderContext (optional)
        agent_names: List of agent names

    Returns:
        List of dicts with agent data for GraphQL schema
    """
    if loaders is None or not agent_names:
        return [
            {
                "id": name,
                "name": name,
                "status": "AVAILABLE",
                "capabilities": [],
                "region": None,
                "currentTask": None,
                "stats": {
                    "totalGames": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "winRate": 0.0,
                    "elo": 1500,
                    "calibrationAccuracy": None,
                    "consistencyScore": None,
                },
                "elo": 1500,
                "model": None,
                "provider": None,
            }
            for name in agent_names
        ]

    agents = await loaders.agent_loader.load_many(agent_names)

    results: list[dict[str, Any]] = []
    for i, name in enumerate(agent_names):
        loaded = agents[i]
        data = loaded if loaded else AgentData.default(name)
        results.append(
            {
                "id": data.id,
                "name": data.name,
                "status": "AVAILABLE",
                "capabilities": [],
                "region": None,
                "currentTask": None,
                "stats": {
                    "totalGames": data.total_games,
                    "wins": data.wins,
                    "losses": data.losses,
                    "draws": data.draws,
                    "winRate": data.win_rate,
                    "elo": data.elo,
                    "calibrationAccuracy": data.calibration_accuracy,
                    "consistencyScore": data.consistency_score,
                },
                "elo": data.elo,
                "model": None,
                "provider": None,
            }
        )

    return results
