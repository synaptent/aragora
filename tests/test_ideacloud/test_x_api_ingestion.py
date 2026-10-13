"""Tests for the live X API mode of the bookmark/like ingestors.

All tests use a fake connector — no network, no real tokens.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from aragora.ideacloud.ingestion.twitter_bookmarks import TwitterBookmarksIngestor
from aragora.ideacloud.ingestion.twitter_likes import TwitterLikesIngestor
from aragora.ideacloud.ingestion.x_api import (
    fetch_live_entries,
    is_api_source,
)


def _entry(tweet_id: str, text: str = "Some insight #ai") -> dict:
    return {
        "tweetId": tweet_id,
        "fullText": text,
        "screenName": "someone",
        "created_at": "2026-08-28T12:00:00.000Z",
        "public_metrics": {},
    }


class FakeConnector:
    """Pages of export-shaped entries, mimicking TwitterConnector's pager."""

    def __init__(self, pages: list[list[dict]], user_id: str | None = "42"):
        self.pages = pages
        self.user_id = user_id
        self.calls = 0

    async def get_authenticated_user_id(self) -> str | None:
        return self.user_id

    async def _page(self, pagination_token):
        index = int(pagination_token) if pagination_token else 0
        self.calls += 1
        if index >= len(self.pages):
            return [], None
        next_token = str(index + 1) if index + 1 < len(self.pages) else None
        return self.pages[index], next_token

    async def fetch_bookmarks_page(self, user_id, pagination_token=None, max_results=100):
        return await self._page(pagination_token)

    async def fetch_liked_page(self, user_id, pagination_token=None, max_results=100):
        return await self._page(pagination_token)


class TestIsApiSource:
    def test_recognizes_api_strings(self):
        assert is_api_source("api:")
        assert is_api_source("api:500")
        assert is_api_source(" API: ")

    def test_rejects_paths(self):
        assert not is_api_source("data/bookmarks.js")
        assert not is_api_source("/tmp/api:weird")
        from pathlib import Path

        assert not is_api_source(Path("bookmarks.js"))


class TestFetchLiveEntries:
    def test_fetches_across_pages(self, tmp_path):
        connector = FakeConnector([[_entry("3"), _entry("2")], [_entry("1")]])
        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark",
                "api:",
                connector=connector,
                state_path=tmp_path / "state.json",
            )
        )
        assert [e["tweetId"] for e in entries] == ["3", "2", "1"]
        assert commit is not None  # feed exhausted -> safe to advance

    def test_stops_at_seen_id_and_updates_state(self, tmp_path):
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"twitter_bookmark": {"seen_ids": ["2"]}}))
        connector = FakeConnector([[_entry("4"), _entry("3"), _entry("2"), _entry("1")]])

        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:", connector=connector, state_path=state_path
            )
        )

        assert [e["tweetId"] for e in entries] == ["4", "3"]
        # State advances only when the caller commits (post-vault-write)
        assert json.loads(state_path.read_text()) == {"twitter_bookmark": {"seen_ids": ["2"]}}
        commit()
        state = json.loads(state_path.read_text())
        # State advances under the user-scoped key (legacy key read as seed)
        assert state["twitter_bookmark:42"]["seen_ids"][:2] == ["4", "3"]
        # Previously seen ids are retained behind the new ones
        assert "2" in state["twitter_bookmark:42"]["seen_ids"]

    def test_respects_max_items_suffix(self, tmp_path):
        connector = FakeConnector([[_entry(str(i)) for i in range(9, -1, -1)]])
        entries, _commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark",
                "api:3",
                connector=connector,
                state_path=tmp_path / "state.json",
            )
        )
        assert len(entries) == 3

    def test_truncated_run_does_not_advance_state(self, tmp_path):
        """A max_items-capped run that never bridges to the seen set must not
        mark its entries seen — otherwise the gap behind them is skipped forever."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"twitter_bookmark": {"seen_ids": ["1"]}}))
        # Two pages; seen id "1" is beyond the cap of 2
        connector = FakeConnector([[_entry("9"), _entry("8")], [_entry("7"), _entry("1")]])

        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:2", connector=connector, state_path=state_path
            )
        )

        assert [e["tweetId"] for e in entries] == ["9", "8"]
        assert commit is None
        state = json.loads(state_path.read_text())
        # State unchanged: "9"/"8" must NOT be seen, so the next (bigger) run
        # can still fetch "7" before bridging to "1"
        assert state["twitter_bookmark"]["seen_ids"] == ["1"]

    def test_first_run_truncation_advances_state(self, tmp_path):
        """With no prior seen set there is no gap to protect; the capped first
        run establishes the baseline."""
        state_path = tmp_path / "state.json"
        connector = FakeConnector([[_entry("9"), _entry("8")], [_entry("7")]])

        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:2", connector=connector, state_path=state_path
            )
        )

        assert [e["tweetId"] for e in entries] == ["9", "8"]
        commit()
        state = json.loads(state_path.read_text())
        assert state["twitter_bookmark:42"]["seen_ids"][:2] == ["9", "8"]

    def test_fetch_failure_does_not_advance_state(self, tmp_path):
        """A failed page request (None) is not feed exhaustion — the continuity
        guard must not mark this run's entries seen over the unfetched gap."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"twitter_bookmark": {"seen_ids": ["1"]}}))
        connector = FakeConnector([[_entry("9"), _entry("8")], None])

        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:", connector=connector, state_path=state_path
            )
        )

        assert [e["tweetId"] for e in entries] == ["9", "8"]
        assert commit is None
        state = json.loads(state_path.read_text())
        assert state["twitter_bookmark"]["seen_ids"] == ["1"]

    def test_state_scoped_by_user_id(self, tmp_path):
        """Seen-ids are stored per authenticated user (legacy key read as seed)."""
        state_path = tmp_path / "state.json"
        connector = FakeConnector([[_entry("5")]], user_id="42")
        _entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:", connector=connector, state_path=state_path
            )
        )
        commit()
        state = json.loads(state_path.read_text())
        assert state["twitter_bookmark:42"]["seen_ids"] == ["5"]

        # A different user does not inherit user 42's seen set
        connector_other = FakeConnector([[_entry("5")]], user_id="77")
        entries, _commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:", connector=connector_other, state_path=state_path
            )
        )
        assert [e["tweetId"] for e in entries] == ["5"]

    def test_first_run_fetch_failure_does_not_advance_state(self, tmp_path):
        """Even with no prior state, a failed fetch must not baseline the
        partial page — the next complete run must reach what this one missed."""
        state_path = tmp_path / "state.json"
        connector = FakeConnector([[_entry("9"), _entry("8")], None])

        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:", connector=connector, state_path=state_path
            )
        )

        assert [e["tweetId"] for e in entries] == ["9", "8"]
        assert commit is None

    def test_mid_final_page_truncation_is_not_exhaustion(self, tmp_path):
        """Cap hit mid-way through the LAST page (no next_token) is still a
        truncation — the dropped remainder of that page must stay fetchable."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"twitter_bookmark": {"seen_ids": ["0"]}}))
        connector = FakeConnector([[_entry("9"), _entry("8"), _entry("7")]])

        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:2", connector=connector, state_path=state_path
            )
        )

        assert [e["tweetId"] for e in entries] == ["9", "8"]
        assert commit is None  # "7" was dropped; advancing would skip it forever

    def test_ingestor_defers_commit_until_commit_ingest(self, monkeypatch, tmp_path):
        """ingest() stages the state advance; commit_ingest() runs it once."""
        calls = []

        async def fake_fetch(source_type, source, **kwargs):
            return [_entry("21")], lambda: calls.append("committed")

        monkeypatch.setattr("aragora.ideacloud.ingestion.x_api.fetch_live_entries", fake_fetch)
        ingestor = TwitterBookmarksIngestor()
        nodes = asyncio.run(ingestor.ingest("api:"))
        assert len(nodes) == 1
        assert calls == []  # not yet committed
        ingestor.commit_ingest()
        assert calls == ["committed"]
        ingestor.commit_ingest()  # idempotent: runs once
        assert calls == ["committed"]

    def test_invalid_api_suffix_raises(self, tmp_path):
        connector = FakeConnector([[_entry("5")]])
        with pytest.raises(ValueError, match="invalid api source"):
            asyncio.run(
                fetch_live_entries(
                    "twitter_bookmark",
                    "api:5OO",
                    connector=connector,
                    state_path=tmp_path / "s.json",
                )
            )

    def test_no_token_returns_empty(self, tmp_path):
        connector = FakeConnector([], user_id=None)
        entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_like", "api:", connector=connector, state_path=tmp_path / "s.json"
            )
        )
        assert entries == []
        assert commit is None

    def test_state_is_per_source_type(self, tmp_path):
        state_path = tmp_path / "state.json"
        connector = FakeConnector([[_entry("7")]])
        _entries, commit = asyncio.run(
            fetch_live_entries(
                "twitter_bookmark", "api:", connector=connector, state_path=state_path
            )
        )
        commit()
        connector_likes = FakeConnector([[_entry("7")]])
        likes, _commit = asyncio.run(
            fetch_live_entries(
                "twitter_like", "api:", connector=connector_likes, state_path=state_path
            )
        )
        # A bookmark seen-id must not suppress the same tweet arriving as a like
        assert [e["tweetId"] for e in likes] == ["7"]


class TestIngestorApiMode:
    def test_bookmarks_api_mode_maps_nodes(self, monkeypatch, tmp_path):
        async def fake_fetch(source_type, source, **kwargs):
            assert source_type == "twitter_bookmark"
            return [_entry("11", "Adversarial review beats vibes #decisions")], None

        monkeypatch.setattr("aragora.ideacloud.ingestion.x_api.fetch_live_entries", fake_fetch)
        nodes = asyncio.run(TwitterBookmarksIngestor().ingest("api:"))
        assert len(nodes) == 1
        assert nodes[0].source_type == "twitter_bookmark"
        assert nodes[0].source_url.endswith("/status/11")
        assert "decisions" in nodes[0].tags

    def test_likes_api_mode_sets_source_type(self, monkeypatch, tmp_path):
        async def fake_fetch(source_type, source, **kwargs):
            assert source_type == "twitter_like"
            return [_entry("12")], None

        monkeypatch.setattr("aragora.ideacloud.ingestion.x_api.fetch_live_entries", fake_fetch)
        nodes = asyncio.run(TwitterLikesIngestor().ingest("api:"))
        assert len(nodes) == 1
        assert nodes[0].source_type == "twitter_like"

    def test_file_mode_still_works(self, tmp_path):
        export = tmp_path / "bookmarks.js"
        export.write_text(
            'window.YTD.bookmark.part0 = [{"bookmark": {"tweetId": "99", '
            '"fullText": "hello world", "screenName": "abc"}}]'
        )
        nodes = asyncio.run(TwitterBookmarksIngestor().ingest(export))
        assert len(nodes) == 1
        assert nodes[0].source_url == "https://x.com/abc/status/99"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
