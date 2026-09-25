"""Live X API fetch support for the bookmark/like ingestors.

Gives :class:`TwitterBookmarksIngestor` and :class:`TwitterLikesIngestor` an
``api:`` source mode: ``ingest("api:")`` fetches from the X API v2 (OAuth2
user context) instead of a data-export file, mapping API tweets into the same
entry shape the export parsers already consume.

Incremental sync: bookmarks/likes endpoints have no ``since_id``, and
bookmark order is bookmark-time (not tweet-time), so snowflake comparison is
wrong. Instead the last run's newest entry ids are remembered in
``.aragora/x_intake/state.json`` and fetching stops at the first already-seen
id (stop-when-seen).

``api:`` alone fetches up to :data:`DEFAULT_MAX_ITEMS`; ``api:500`` overrides
the cap. Full-history backfill belongs to the data-export file path, which
has no 800-item API ceiling.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

API_SOURCE_PREFIX = "api:"
DEFAULT_MAX_ITEMS = 200
# CWD-relative by default (the CLI and digest job run from the repo root);
# override with ARAGORA_X_INTAKE_STATE for other working directories.
STATE_PATH = Path(os.environ.get("ARAGORA_X_INTAKE_STATE", ".aragora/x_intake/state.json"))
# Enough remembered ids to bridge the overlap window between runs
SEEN_IDS_KEPT = 300

__all__ = ["API_SOURCE_PREFIX", "is_api_source", "fetch_live_entries"]


def is_api_source(source: Any) -> bool:
    """True when an ingest source string requests live API mode."""
    return isinstance(source, str) and source.strip().lower().startswith(API_SOURCE_PREFIX)


def _parse_max_items(source: str) -> int:
    suffix = source.strip()[len(API_SOURCE_PREFIX) :].strip()
    if not suffix:
        return DEFAULT_MAX_ITEMS
    if suffix.isdigit():
        return max(1, int(suffix))
    # A typo like 'api:5OO' silently capping at the default would interact
    # badly with the continuity guard — fail loudly instead.
    raise ValueError(f"invalid api source {source!r}: expected 'api:' or 'api:<max_items>'")


def _load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read X intake state %s: %s", path, exc)
    return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace: a crash mid-write must not corrupt state.json (a
    # corrupted file reads as first-run and triggers a duplicate refetch).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _make_state_commit(
    path: Path, state_key: str, source_type: str, newest_ids: list[str]
) -> Callable[[], None]:
    """Deferred seen-id advance, run only after entries are durably ingested."""

    def commit() -> None:
        # Re-read at commit time: another source_type's commit may have
        # written the file since the fetch loaded it.
        latest = _load_state(path)
        prior_now = latest.get(state_key) or latest.get(source_type) or {}
        merged = newest_ids + list(prior_now.get("seen_ids", []))
        latest[state_key] = {"seen_ids": merged[:SEEN_IDS_KEPT]}
        _save_state(path, latest)

    return commit


async def fetch_live_entries(
    source_type: str,
    source: str,
    *,
    connector: Any = None,
    state_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], Callable[[], None] | None]:
    """Fetch new bookmark/like entries from the X API in export-entry shape.

    Args:
        source_type: ``"twitter_bookmark"`` or ``"twitter_like"``.
        source: The ``api:`` source string (optionally ``api:<max_items>``).
        connector: Injected TwitterConnector-compatible object (tests).
        state_path: Override for the incremental-sync state file.

    Returns:
        ``(entries, commit)``: entries newest-first, stopping at the first id
        seen in a prior run, and a deferred state-advance callback (or None
        when state must not advance). Callers invoke ``commit()`` only AFTER
        the entries are durably ingested — advancing seen-ids before the
        vault write would let a crash in between drop entries forever.
    """
    max_items = _parse_max_items(source)
    path = Path(state_path) if state_path else STATE_PATH

    if connector is None:
        from aragora.connectors.twitter import TwitterConnector

        connector = TwitterConnector()

    user_id = await connector.get_authenticated_user_id()
    if not user_id:
        logger.warning(
            "X live ingestion unavailable: no user-context token at %s "
            "(run scripts/x_oauth_setup.py) — data-export --file mode still works",
            Path(".aragora/x_intake/oauth.json").resolve(),
        )
        return [], None

    fetch_page = (
        connector.fetch_bookmarks_page
        if source_type == "twitter_bookmark"
        else connector.fetch_liked_page
    )

    # State is scoped per authenticated user so switching OAuth accounts
    # against the same checkout cannot cross-contaminate seen-id sets.
    # Legacy (pre-user-scoped) state is read as a fallback seed.
    state_key = f"{source_type}:{user_id}"
    state = _load_state(path)
    prior = state.get(state_key) or state.get(source_type) or {}
    seen_ids = set(prior.get("seen_ids", []))

    entries: list[dict[str, Any]] = []
    pagination_token: str | None = None
    hit_seen = False
    fetch_failed = False
    truncated_mid_page = False
    while len(entries) < max_items and not hit_seen:
        page, pagination_token = await fetch_page(user_id, pagination_token)
        if page is None:
            # Request failure is NOT feed exhaustion — never treat it as
            # continuity or the guard would advance state over a gap.
            fetch_failed = True
            break
        if not page:
            break
        for index, entry in enumerate(page):
            tweet_id = str(entry.get("tweetId") or "")
            if tweet_id and tweet_id in seen_ids:
                hit_seen = True
                break
            entries.append(entry)
            if len(entries) >= max_items:
                # Anything left on this page was dropped — even with no
                # next_token this is a truncation, not exhaustion.
                truncated_mid_page = index + 1 < len(page)
                break
        if not pagination_token:
            break

    # Continuity guard: advancing seen_ids is only safe when this run bridged
    # to the previous seen set (hit_seen), genuinely exhausted the feed, or
    # has no prior state to protect (first run for this user). A truncated or
    # failed fetch must not advance state, or the gap behind this run's
    # entries would be skipped forever.
    feed_exhausted = not pagination_token and not fetch_failed and not truncated_mid_page
    reached_continuity = hit_seen or feed_exhausted or not seen_ids
    commit: Callable[[], None] | None = None
    # A failed fetch never advances state — even on a first run, marking the
    # partial page seen would stop the next (complete) run short of the items
    # this one failed to reach.
    if entries and reached_continuity and not fetch_failed:
        newest_ids = [str(e.get("tweetId")) for e in entries if e.get("tweetId")]
        commit = _make_state_commit(path, state_key, source_type, newest_ids)
    elif entries:
        logger.warning(
            "%s fetch stopped early (%s) before reaching previously seen ids; "
            "state not advanced — re-run%s to close the gap",
            source_type,
            "request failure" if fetch_failed else f"max_items={max_items}",
            "" if fetch_failed else f" with a higher cap (e.g. 'api:{max_items * 2}')",
        )

    logger.info(
        "Fetched %d new %s entries from X API (stopped at seen id: %s)",
        len(entries),
        source_type,
        hit_seen,
    )
    return entries, commit
