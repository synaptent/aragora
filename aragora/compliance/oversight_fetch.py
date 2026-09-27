"""Fetch human-settlement attestations from the GitHub trail (#8230 follow-up).

Walks recently merged PRs and converts each head-bound
``aragora/human-settlement`` commit status into an oversight attestation via
:mod:`aragora.gauntlet.attestation` — automating the ``--attestations`` input
of the Article 14 oversight pack with real, resolvable trail evidence.

Honesty rules:

- A settlement status whose creator equals the PR's executing author is NOT
  independent oversight — the attestation builder refuses it (TET H2), and
  the PR is reported in ``skipped`` with the reason, never silently dropped.
- PRs with no human-settlement status are simply not attested (they remain
  ``autonomous`` in the pack); only genuinely attested settlements appear.

Requires the ``gh`` CLI (already the repo's sanctioned GitHub transport);
inject ``gh_runner`` for tests.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from aragora.gauntlet.attestation import (
    HUMAN_SETTLEMENT_CONTEXT,
    attestation_from_settlement_status,
)

logger = logging.getLogger(__name__)

__all__ = ["fetch_settlement_attestations"]

GhRunner = Callable[[list[str]], Any]


def _run_gh(args: list[str]) -> Any:
    """Run ``gh`` and parse its JSON stdout."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fetch_settlement_attestations(
    *,
    repo: str | None = None,
    window_days: int = 30,
    limit: int = 500,
    now: datetime | None = None,
    gh_runner: GhRunner | None = None,
) -> dict[str, Any]:
    """Fetch attestations for human-settled merged PRs in the window.

    Args:
        repo: ``owner/name``; resolved from the current directory when omitted.
        window_days: Only settlements attested within this window are kept.
        limit: Maximum in-window merged PRs to scan. When the scan fills
            this limit the result is flagged ``truncated`` (and a warning is
            logged) instead of silently undercounting settlements.
        now: Window anchor (defaults to current UTC; injectable for tests).
        gh_runner: ``gh``-invocation override for tests.

    Returns:
        ``{"attestations": [...], "skipped": [...], "scanned_prs": int,
        "repo": str}`` where each attestation entry carries the PR reference
        and the validated attestation block.
    """
    run = gh_runner or _run_gh
    anchor = now or datetime.now(timezone.utc)
    cutoff = anchor - timedelta(days=window_days)

    if not repo:
        view = run(["repo", "view", "--json", "nameWithOwner"]) or {}
        repo = str(view.get("nameWithOwner", "") or "")
    if not repo:
        raise ValueError("could not resolve repo; pass repo='owner/name'")

    # Date-bounded search so `limit` only applies to in-window merges; a
    # fixed recency limit alone silently omits older in-window PRs in
    # high-churn repos. If the result still fills `limit`, the scan is
    # truncated and reported as such — never silently.
    prs = (
        run(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "merged",
                "--search",
                f"merged:>={cutoff.date().isoformat()}",
                "--limit",
                str(limit),
                "--json",
                "number,url,mergedAt,headRefOid,author",
            ]
        )
        or []
    )
    truncated = len(prs) >= limit

    attestations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    scanned = 0
    for pr in prs:
        merged_at = _parse_iso(pr.get("mergedAt"))
        if merged_at is None or merged_at < cutoff or merged_at > anchor:
            continue
        head_sha = str(pr.get("headRefOid", "") or "")
        if not head_sha:
            continue
        scanned += 1
        try:
            # Busy heads can carry >100 statuses; paginate so an older
            # settlement status is never missed (--slurp wraps pages in an
            # outer array — flattened below; plain arrays also handled for
            # older gh versions and test fakes).
            raw = (
                run(
                    [
                        "api",
                        f"repos/{repo}/commits/{head_sha}/statuses?per_page=100",
                        "--paginate",
                        "--slurp",
                    ]
                )
                or []
            )
            statuses = [
                status for page in raw for status in (page if isinstance(page, list) else [page])
            ]
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            skipped.append({"pr": pr.get("number"), "reason": f"statuses fetch failed: {exc}"})
            continue
        # Statuses API returns newest first; take the latest settlement status.
        settlement = next(
            (
                s
                for s in statuses
                if s.get("context") == HUMAN_SETTLEMENT_CONTEXT and s.get("state") == "success"
            ),
            None,
        )
        if settlement is None:
            continue
        attested_at = _parse_iso(settlement.get("created_at"))
        if attested_at is None or attested_at < cutoff or attested_at > anchor:
            continue
        author = pr.get("author") or {}
        execution_id = str(author.get("login", "") or "") or None
        if execution_id is None:
            # Without a resolvable executing author the attestor≠execution
            # separation check cannot run — unverifiable oversight is
            # skipped with the reason, never assumed valid.
            skipped.append(
                {
                    "pr": pr.get("number"),
                    "reason": "PR author unresolvable; identity separation unverifiable",
                }
            )
            continue
        try:
            attestation = attestation_from_settlement_status(
                settlement,
                head_sha=head_sha,
                execution_identity_id=execution_id,
            )
        except ValueError as exc:
            # e.g. settlement recorded by the executing identity itself —
            # refused as oversight (TET H2); reported, never silently kept.
            skipped.append({"pr": pr.get("number"), "reason": str(exc)})
            continue
        attestations.append(
            {
                "pr": pr.get("number"),
                "pr_url": pr.get("url"),
                "merged_at": pr.get("mergedAt"),
                "head_sha": head_sha,
                "attestation": attestation.to_dict(),
            }
        )

    logger.info(
        "oversight_fetch repo=%s scanned=%d attested=%d skipped=%d",
        repo,
        scanned,
        len(attestations),
        len(skipped),
    )
    if truncated:
        logger.warning(
            "oversight_fetch: merged-PR scan hit limit=%d and may be truncated; "
            "raise limit= to cover the full window",
            limit,
        )
    return {
        "repo": repo,
        "scanned_prs": scanned,
        "attestations": attestations,
        "skipped": skipped,
        "truncated": truncated,
    }
