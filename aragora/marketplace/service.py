"""
MarketplaceService -- unified service layer for the marketplace pilot.

Combines the existing MarketplaceCatalog (templates, agent packs, skills,
connectors) with user-facing operations such as listing, searching,
installing, and rating items.

This service is the single entry point used by HTTP handlers and will be
the foundation for the full marketplace GA release.

Usage:
    from aragora.marketplace.service import MarketplaceService

    svc = MarketplaceService()

    # Browse
    listings = svc.list_listings(item_type="template")

    # Detail
    item = svc.get_listing("tpl-code-review")

    # Install
    result = svc.install_listing("tpl-code-review", user_id="user-1")

    # Rate
    svc.rate_listing("tpl-code-review", user_id="user-1", score=5, review="Great!")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import uuid

from .catalog import MarketplaceCatalog, MarketplaceItem
from .installer import InstallBridgeResult, MarketplaceInstaller

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rating model (per-item, not template-specific)
# ---------------------------------------------------------------------------


@dataclass
class ListingRating:
    """A user rating for a marketplace listing."""

    user_id: str
    item_id: str
    score: int  # 1-5
    review: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not 1 <= self.score <= 5:
            raise ValueError("Score must be between 1 and 5")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "user_id": self.user_id,
            "item_id": self.item_id,
            "score": self.score,
            "review": self.review,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MarketplaceService:
    """
    Unified marketplace service for the pilot launch.

    Wraps ``MarketplaceCatalog`` and adds rating, per-user install tracking,
    and rich query support.

    Thread-safe: all mutations operate on simple dicts guarded by the GIL.
    For production, the backing store will be replaced with Postgres.
    """

    def __init__(
        self,
        catalog: MarketplaceCatalog | None = None,
        installer: MarketplaceInstaller | None = None,
        skill_registry: Any | None = None,
        template_registry: Any | None = None,
    ) -> None:
        self._catalog = catalog or MarketplaceCatalog(seed=True)
        self._installer = installer or MarketplaceInstaller(
            catalog=self._catalog,
            skill_registry=skill_registry,
            template_registry=template_registry,
        )
        # item_id -> list of ratings
        self._ratings: dict[str, list[ListingRating]] = {}
        # user_id -> set of installed item_ids
        self._user_installs: dict[str, set[str]] = {}

    # ----- Listing queries --------------------------------------------------

    def list_listings(
        self,
        *,
        item_type: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        category: str | None = None,
        featured_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Browse marketplace listings with optional filters.

        Args:
            item_type: Filter by type (template, agent_pack, skill, connector).
            tag: Filter to items containing this tag.
            search: Free-text search over name and description.
            category: Alias for ``tag`` (kept for backwards compat with frontend).
            featured_only: If True, return only featured items.
            limit: Maximum items to return.
            offset: Pagination offset.

        Returns:
            Dict with ``items``, ``total``, ``limit``, ``offset`` keys.
        """
        if featured_only:
            items = self._catalog.get_featured()
        else:
            effective_tag = tag or category
            items = self._catalog.list_items(
                item_type=item_type,
                tag=effective_tag,
                search=search,
            )

        total = len(items)
        page = items[offset : offset + limit]

        return {
            "items": [self._enrich(i) for i in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_listing(self, item_id: str) -> dict[str, Any] | None:
        """Get full details for a single listing.

        Args:
            item_id: The marketplace item identifier.

        Returns:
            Enriched item dict or None if not found.
        """
        item = self._catalog.get_item(item_id)
        if item is None:
            return None
        return self._enrich(item)

    # ----- Install ----------------------------------------------------------

    def install_listing(self, item_id: str, user_id: str) -> InstallBridgeResult:
        """Install a marketplace listing for a user.

        Delegates to :class:`MarketplaceInstaller` which handles both the
        catalog-level install (download counter) **and** bridges the item
        into the appropriate live registry (SkillRegistry for skills,
        TemplateRegistry for workflow templates).

        Args:
            item_id: The item to install.
            user_id: The installing user.

        Returns:
            InstallBridgeResult with catalog result and registry details.
        """
        result = self._installer.install(item_id)
        if result.catalog_result.success:
            self._user_installs.setdefault(user_id, set()).add(item_id)
            logger.info("User %s installed marketplace item %s", user_id, item_id)
        return result

    def uninstall_listing(self, item_id: str, user_id: str) -> bool:
        """Uninstall a marketplace listing for a user.

        Removes the item from the appropriate registry and the user's
        install tracking.

        Args:
            item_id: The item to uninstall.
            user_id: The uninstalling user.

        Returns:
            True if the item was successfully unregistered.
        """
        removed = self._installer.uninstall(item_id)
        if removed:
            installs = self._user_installs.get(user_id, set())
            installs.discard(item_id)
            logger.info("User %s uninstalled marketplace item %s", user_id, item_id)
        return removed

    def get_user_installs(self, user_id: str) -> list[str]:
        """Return list of item IDs installed by a user."""
        return sorted(self._user_installs.get(user_id, set()))

    # ----- Rating -----------------------------------------------------------

    def rate_listing(
        self,
        item_id: str,
        *,
        user_id: str,
        score: int,
        review: str | None = None,
    ) -> dict[str, Any]:
        """Rate or update rating for a listing.

        If the user already rated this item, the existing rating is replaced.

        Args:
            item_id: Item to rate.
            user_id: Rating user.
            score: 1-5 integer.
            review: Optional review text.

        Returns:
            Dict with ``success``, ``average_rating``, ``total_ratings``.

        Raises:
            ValueError: If score is outside 1-5.
            KeyError: If item_id not found in catalog.
        """
        if self._catalog.get_item(item_id) is None:
            raise KeyError(f"Item not found: {item_id}")

        rating = ListingRating(
            user_id=user_id,
            item_id=item_id,
            score=score,
            review=review,
        )

        # Upsert: replace existing rating by same user
        ratings = self._ratings.setdefault(item_id, [])
        self._ratings[item_id] = [r for r in ratings if r.user_id != user_id]
        self._ratings[item_id].append(rating)

        avg = self.get_average_rating(item_id)
        total = len(self._ratings[item_id])

        logger.info(
            "User %s rated item %s: %d/5 (avg now %.1f from %d ratings)",
            user_id,
            item_id,
            score,
            avg,
            total,
        )

        return {
            "success": True,
            "average_rating": avg,
            "total_ratings": total,
        }

    def get_ratings(self, item_id: str) -> list[dict[str, Any]]:
        """Get all ratings for an item."""
        return [r.to_dict() for r in self._ratings.get(item_id, [])]

    def get_average_rating(self, item_id: str) -> float:
        """Compute average rating for an item, or 0.0 if no ratings."""
        ratings = self._ratings.get(item_id, [])
        if not ratings:
            return 0.0
        return round(sum(r.score for r in ratings) / len(ratings), 1)

    # ----- Stats ------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics for the marketplace."""
        type_counts = self._catalog.get_types()
        return {
            "total_items": self._catalog.item_count,
            "types": type_counts,
            "total_ratings": sum(len(rs) for rs in self._ratings.values()),
            "total_installs": sum(len(ids) for ids in self._user_installs.values()),
        }

    # ----- Debate launch ------------------------------------------------------

    def launch_debate_from_listing(
        self,
        item_id: str,
        question: str,
        user_id: str = "anonymous",
        *,
        rounds_override: int | None = None,
    ) -> dict[str, Any]:
        """Build a debate configuration from a marketplace listing.

        Looks up the catalog item, extracts template configuration (rounds,
        consensus_mode, agent_roles), and returns a debate configuration dict
        suitable for passing to the Arena.  The caller (handler) is responsible
        for actually executing the debate.

        Args:
            item_id: Marketplace catalog item ID.
            question: The debate question / topic.
            user_id: ID of the user launching the debate.
            rounds_override: If provided, overrides the template's default rounds.

        Returns:
            Dict with ``debate_id``, ``template_used``, ``config`` keys.

        Raises:
            KeyError: If *item_id* is not found in the catalog.
        """
        item = self._catalog.get_item(item_id)
        if item is None:
            raise KeyError(f"Listing not found: {item_id}")

        # Try to load the matching DebateTemplate from the models registry
        template_config: dict[str, Any] = {}
        agent_roles: list[dict[str, Any]] = []
        default_rounds = 3
        consensus_mode = "majority"

        try:
            from .models import BUILTIN_DEBATE_TEMPLATES

            for tpl in BUILTIN_DEBATE_TEMPLATES:
                if tpl.metadata.id == item_id or tpl.metadata.name == item.name:
                    agent_roles = list(tpl.agent_roles)
                    default_rounds = tpl.protocol.get("rounds", 3)
                    consensus_mode = tpl.protocol.get("consensus_mode", "majority")
                    template_config = {
                        "task_template": tpl.task_template,
                        "evaluation_criteria": list(tpl.evaluation_criteria),
                        "protocol": dict(tpl.protocol),
                    }
                    break
        except (ImportError, AttributeError, TypeError) as exc:
            logger.warning("Could not load debate templates: %s", exc)

        rounds = rounds_override if rounds_override is not None else default_rounds
        debate_id = f"mkt-{uuid.uuid4().hex[:12]}"

        config: dict[str, Any] = {
            "debate_id": debate_id,
            "question": question,
            "rounds": rounds,
            "consensus_mode": consensus_mode,
            "agent_roles": agent_roles,
            "user_id": user_id,
            "source_listing": item_id,
            **template_config,
        }

        logger.info(
            "Prepared debate config from listing %s for user %s (debate_id=%s)",
            item_id,
            user_id,
            debate_id,
        )

        return {
            "debate_id": debate_id,
            "template_used": item_id,
            "config": config,
        }

    # ----- Internal ---------------------------------------------------------

    def _enrich(self, item: MarketplaceItem) -> dict[str, Any]:
        """Enrich a catalog item with computed fields (ratings etc.)."""
        d = item.to_dict()
        d["average_rating"] = self.get_average_rating(item.id)
        d["total_ratings"] = len(self._ratings.get(item.id, []))
        return d


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_service: MarketplaceService | None = None


def get_marketplace_service() -> MarketplaceService:
    """Get or create the global MarketplaceService instance."""
    global _service
    if _service is None:
        _service = MarketplaceService()
    return _service


def reset_marketplace_service() -> None:
    """Reset the global instance (for testing)."""
    global _service
    _service = None
