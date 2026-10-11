"""Batch market emitter for synthetic GitHub markets (AGT-04, issue #6065).

Flag-gated via ``ARAGORA_SYNTHETIC_MARKETS_ENABLED``. Idempotently creates
markets for open PRs or issues; existing markets are skipped. Scheduling
is out of scope — the caller decides when to invoke.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aragora.connectors.prediction_markets.synthetic_github import (
    SYNTHETIC_MARKETS_FLAG,
    SyntheticGitHubAdapter,
    SyntheticGitHubError,
    synthetic_markets_enabled,
)
from aragora.markets.types import Market

logger = logging.getLogger(__name__)


class BatchEmitError(RuntimeError):
    """Raised when the feature flag is off."""


@dataclass(frozen=True)
class PrEntry:
    """Pull request for which a prediction market should be created."""

    repo: str
    number: int
    title: str = ""

    def __post_init__(self) -> None:
        if not str(self.repo).strip():
            raise ValueError("PrEntry.repo must be non-empty")
        if not isinstance(self.number, int) or self.number < 1:
            raise ValueError("PrEntry.number must be a positive int")


@dataclass(frozen=True)
class IssueEntry:
    """Issue for which a prediction market should be created."""

    repo: str
    number: int
    title: str = ""

    def __post_init__(self) -> None:
        if not str(self.repo).strip():
            raise ValueError("IssueEntry.repo must be non-empty")
        if not isinstance(self.number, int) or self.number < 1:
            raise ValueError("IssueEntry.number must be a positive int")


@dataclass
class BatchEmitResult:
    """Outcome of a single ``emit_markets_for_*`` call."""

    created: list[Market] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_ids)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def total_seen(self) -> int:
        return self.created_count + self.skipped_count + self.error_count

    def to_json(self) -> dict[str, Any]:
        return {
            "created_count": self.created_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "total_seen": self.total_seen,
            "created": [m.to_json() for m in self.created],
            "skipped_ids": list(self.skipped_ids),
            "errors": [{"target": t, "error": e} for t, e in self.errors],
        }


def emit_markets_for_prs(
    adapter: SyntheticGitHubAdapter,
    prs: list[PrEntry],
    *,
    resolution_window_days: int = 7,
) -> BatchEmitResult:
    """Create markets for PRs that don't already have one; skip others."""
    if not synthetic_markets_enabled():
        raise BatchEmitError(
            f"batch market emission is disabled; set {SYNTHETIC_MARKETS_FLAG}=1 to enable"
        )
    result = BatchEmitResult()
    for pr in prs:
        label = f"{pr.repo}#PR{pr.number}"
        try:
            probe = Market.create(
                question_kind="pr_merge",
                target={"repo": pr.repo, "number": pr.number},
                description=f"Will PR #{pr.number} in {pr.repo} merge within {resolution_window_days}d?",
                resolution_window_days=resolution_window_days,
            )
            if adapter.store.get_market(probe.market_id) is not None:
                result.skipped_ids.append(probe.market_id)
                continue
            desc = f"{pr.title} — will merge within {resolution_window_days}d?" if pr.title else ""
            result.created.append(
                adapter.create_pr_merge_market(
                    repo=pr.repo,
                    pr_number=pr.number,
                    resolution_window_days=resolution_window_days,
                    description=desc,
                )
            )
        except (SyntheticGitHubError, ValueError) as exc:
            result.errors.append((label, str(exc)))
            logger.warning("emit_prs: error for %s: %s", label, exc)
    return result


def emit_markets_for_issues(
    adapter: SyntheticGitHubAdapter,
    issues: list[IssueEntry],
    *,
    resolution_window_days: int = 30,
) -> BatchEmitResult:
    """Create markets for issues that don't already have one; skip others."""
    if not synthetic_markets_enabled():
        raise BatchEmitError(
            f"batch market emission is disabled; set {SYNTHETIC_MARKETS_FLAG}=1 to enable"
        )
    result = BatchEmitResult()
    for issue in issues:
        label = f"{issue.repo}#I{issue.number}"
        try:
            probe = Market.create(
                question_kind="issue_close",
                target={"repo": issue.repo, "number": issue.number},
                description=f"Will issue #{issue.number} in {issue.repo} close within {resolution_window_days}d?",
                resolution_window_days=resolution_window_days,
            )
            if adapter.store.get_market(probe.market_id) is not None:
                result.skipped_ids.append(probe.market_id)
                continue
            desc = (
                f"{issue.title} — will close within {resolution_window_days}d?"
                if issue.title
                else ""
            )
            result.created.append(
                adapter.create_issue_close_market(
                    repo=issue.repo,
                    issue_number=issue.number,
                    resolution_window_days=resolution_window_days,
                    description=desc,
                )
            )
        except (SyntheticGitHubError, ValueError) as exc:
            result.errors.append((label, str(exc)))
            logger.warning("emit_issues: error for %s: %s", label, exc)
    return result


__all__ = [
    "BatchEmitError",
    "BatchEmitResult",
    "IssueEntry",
    "PrEntry",
    "emit_markets_for_issues",
    "emit_markets_for_prs",
]
