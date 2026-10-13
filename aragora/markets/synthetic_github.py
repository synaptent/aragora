"""Synthetic GitHub prediction market connector (AGT-04, issue #6065).

Thin facade over the other :mod:`aragora.markets` modules;
:mod:`aragora.connectors.prediction_markets` re-exports it next to the
external-venue adapters. Gated behind ``ARAGORA_SYNTHETIC_MARKETS_ENABLED``.

Out of scope: periodic scheduling, credit bookkeeping, per-agent Brier (AGT-05).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from aragora.markets.resolver import GitHubMarketResolver, GhRunner, ResolutionError
from aragora.markets.store import MarketStore, MarketStoreError
from aragora.markets.types import MAX_POSITION_STAKE, Market, MarketPosition, ResolutionEvent

logger = logging.getLogger(__name__)

SYNTHETIC_MARKETS_FLAG = "ARAGORA_SYNTHETIC_MARKETS_ENABLED"
DEFAULT_POSITION_CAP = MAX_POSITION_STAKE


class SyntheticGitHubError(RuntimeError):
    """Raised on invariant violations in the synthetic GitHub market surface."""


def synthetic_markets_enabled() -> bool:
    return str(os.environ.get(SYNTHETIC_MARKETS_FLAG) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class SyntheticGitHubAdapter:
    """Facade for creating, predicting on, and resolving synthetic GitHub markets."""

    store: MarketStore
    gh_runner: GhRunner | None = None
    require_expiry: bool = True
    _resolver: GitHubMarketResolver | None = field(default=None, init=False, repr=False)

    def _get_resolver(self) -> GitHubMarketResolver:
        if self._resolver is None:
            self._resolver = GitHubMarketResolver(
                gh_runner=self.gh_runner, require_expiry=self.require_expiry
            )
        return self._resolver

    def _require_enabled(self) -> None:
        if not synthetic_markets_enabled():
            raise SyntheticGitHubError(
                f"synthetic GitHub markets are disabled; set {SYNTHETIC_MARKETS_FLAG}=1 to enable"
            )

    def create_pr_merge_market(
        self,
        *,
        repo: str,
        pr_number: int,
        resolution_window_days: int = 7,
        description: str = "",
        created_at: datetime | None = None,
    ) -> Market:
        self._require_enabled()
        return self.store.add_market(
            Market.create(
                question_kind="pr_merge",
                target={"repo": repo, "number": pr_number},
                description=description
                or f"Will PR #{pr_number} in {repo} merge within {resolution_window_days}d?",
                resolution_window_days=resolution_window_days,
                created_at=created_at,
            )
        )

    def create_issue_close_market(
        self,
        *,
        repo: str,
        issue_number: int,
        resolution_window_days: int = 30,
        description: str = "",
        created_at: datetime | None = None,
    ) -> Market:
        self._require_enabled()
        return self.store.add_market(
            Market.create(
                question_kind="issue_close",
                target={"repo": repo, "number": issue_number},
                description=description
                or f"Will issue #{issue_number} in {repo} close within {resolution_window_days}d?",
                resolution_window_days=resolution_window_days,
                created_at=created_at,
            )
        )

    def create_ci_pass_market(
        self,
        *,
        repo: str,
        ref: str,
        resolution_window_days: int = 7,
        description: str = "",
        created_at: datetime | None = None,
    ) -> Market:
        self._require_enabled()
        return self.store.add_market(
            Market.create(
                question_kind="ci_pass",
                target={"repo": repo, "ref": ref},
                description=description
                or f"Will CI pass for {repo}@{ref} within {resolution_window_days}d?",
                resolution_window_days=resolution_window_days,
                created_at=created_at,
            )
        )

    def place_position(
        self,
        market_id: str,
        *,
        agent_id: str,
        probability: float,
        stake: int,
        rationale: str = "",
        submitted_at: datetime | None = None,
    ) -> MarketPosition:
        self._require_enabled()
        try:
            position = MarketPosition.create(
                market_id=market_id,
                agent_id=agent_id,
                probability=probability,
                stake=stake,
                rationale=rationale,
                submitted_at=submitted_at,
            )
        except ValueError as exc:
            raise SyntheticGitHubError(str(exc)) from exc
        try:
            return self.store.add_position(position)
        except MarketStoreError as exc:
            raise SyntheticGitHubError(str(exc)) from exc

    def resolve_market(self, market: Market, *, now: datetime | None = None) -> ResolutionEvent:
        self._require_enabled()
        try:
            event = self._get_resolver().resolve(market, now=now)
        except ResolutionError as exc:
            raise SyntheticGitHubError(str(exc)) from exc
        try:
            return self.store.record_resolution(event)
        except MarketStoreError as exc:
            raise SyntheticGitHubError(str(exc)) from exc

    def resolve_expired_batch(self, *, now: datetime | None = None) -> list[ResolutionEvent]:
        """Resolve all expired unresolved markets; skip transient failures."""
        self._require_enabled()
        reference = now or datetime.now(tz=UTC)
        out: list[ResolutionEvent] = []
        for market in list(self.store.iter_unresolved_markets()):
            if not market.is_expired(now=reference):
                continue
            try:
                out.append(self.resolve_market(market, now=reference))
            except SyntheticGitHubError as exc:
                logger.warning("resolve skipped for %s: %s", market.market_id, exc)
        return out


def open_adapter(
    store_dir: Path | str, *, gh_runner: GhRunner | None = None, require_expiry: bool = True
) -> SyntheticGitHubAdapter:
    """Convenience constructor backed by ``store_dir``."""
    return SyntheticGitHubAdapter(
        store=MarketStore(store_dir), gh_runner=gh_runner, require_expiry=require_expiry
    )


__all__ = [
    "DEFAULT_POSITION_CAP",
    "SYNTHETIC_MARKETS_FLAG",
    "SyntheticGitHubAdapter",
    "SyntheticGitHubError",
    "open_adapter",
    "synthetic_markets_enabled",
]
