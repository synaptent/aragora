"""Base ingestor interface for Idea Cloud sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from aragora.ideacloud.graph.node import IdeaNode


class BaseIdeaIngestor(ABC):
    """Abstract base for all idea ingestors.

    Subclasses implement ``ingest()`` to parse a specific source format
    and return a list of IdeaNode objects.
    """

    source_type: str = "unknown"
    # Deferred side-effect (e.g. advancing incremental-sync state) staged by
    # ingest(); the caller invokes commit_ingest() only AFTER the returned
    # nodes are durably stored, so a crash in between cannot lose entries.
    _pending_commit: Callable[[], None] | None = None

    def commit_ingest(self) -> None:
        """Run and clear any deferred post-ingest commit staged by ingest()."""
        if self._pending_commit is not None:
            commit, self._pending_commit = self._pending_commit, None
            commit()

    @abstractmethod
    async def ingest(self, source: Any) -> list[IdeaNode]:
        """Parse source data and return idea nodes.

        Implementations should:
        1. Parse the source format
        2. Create IdeaNode objects with appropriate metadata
        3. Set source_type, source_url, source_author, tags
        4. Return all parsed nodes (filtering happens in quality.py)
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source_type={self.source_type!r})"
