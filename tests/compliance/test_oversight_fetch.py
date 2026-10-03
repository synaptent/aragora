"""Settlement-attestation fetcher (#8230 follow-up).

Walks merged PRs' ``aragora/human-settlement`` statuses into attestation
blocks. Honesty: self-settled PRs (creator == executing author) are refused
and reported in ``skipped``; unattested PRs simply don't appear.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aragora.compliance.oversight_fetch import fetch_settlement_attestations
from aragora.compliance.oversight_pack import (
    build_oversight_pack,
    render_oversight_pack_markdown,
)

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
HEAD_A = "a" * 40
HEAD_B = "b" * 40
HEAD_C = "c" * 40


def _gh_fixture(calls: list[list[str]]):
    """A fake gh runner over a small merged-PR universe."""

    def run(args: list[str]):
        calls.append(args)
        if args[:2] == ["repo", "view"]:
            return {"nameWithOwner": "acme/widgets"}
        if args[:2] == ["pr", "list"]:
            assert "--search" in args and any(a.startswith("merged:>=") for a in args)
            return [
                {  # human-settled by a distinct oversight identity
                    "number": 101,
                    "url": "https://github.com/acme/widgets/pull/101",
                    "mergedAt": "2026-07-16T10:00:00Z",
                    "headRefOid": HEAD_A,
                    "author": {"login": "agent-bot"},
                },
                {  # self-settled: creator == author → must be skipped
                    "number": 102,
                    "url": "https://github.com/acme/widgets/pull/102",
                    "mergedAt": "2026-07-15T10:00:00Z",
                    "headRefOid": HEAD_B,
                    "author": {"login": "overseer"},
                },
                {  # no settlement status → autonomous, not listed
                    "number": 103,
                    "url": "https://github.com/acme/widgets/pull/103",
                    "mergedAt": "2026-07-14T10:00:00Z",
                    "headRefOid": HEAD_C,
                    "author": {"login": "agent-bot"},
                },
                {  # out of window
                    "number": 90,
                    "url": "https://github.com/acme/widgets/pull/90",
                    "mergedAt": "2026-01-01T10:00:00Z",
                    "headRefOid": "d" * 40,
                    "author": {"login": "agent-bot"},
                },
            ]
        if args[0] == "api" and HEAD_A in args[1]:
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "overseer"},
                    "created_at": "2026-07-16T11:00:00Z",
                    "description": "Settlement receipt " + "e" * 64 + " recorded for PR #101",
                    "url": f"https://api.github.com/repos/acme/widgets/statuses/{HEAD_A}",
                },
                {"context": "ci/other", "state": "success"},
            ]
        if args[0] == "api" and HEAD_B in args[1]:
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "overseer"},
                    "created_at": "2026-07-15T11:00:00Z",
                    "description": "settled",
                    "url": f"https://api.github.com/repos/acme/widgets/statuses/{HEAD_B}",
                }
            ]
        if args[0] == "api" and HEAD_C in args[1]:
            return [{"context": "ci/other", "state": "success"}]
        raise AssertionError(f"unexpected gh call: {args}")

    return run


class TestFetcher:
    def test_fetches_attestations_and_skips_self_settled(self) -> None:
        calls: list[list[str]] = []
        result = fetch_settlement_attestations(
            window_days=30, now=NOW, gh_runner=_gh_fixture(calls)
        )
        assert result["repo"] == "acme/widgets"
        assert result["scanned_prs"] == 3  # out-of-window PR not scanned
        assert len(result["attestations"]) == 1
        entry = result["attestations"][0]
        assert entry["pr"] == 101
        block = entry["attestation"]
        assert block["disposition"] == "human_attested"
        assert block["attestor"]["id"] == "overseer"
        assert block["execution_identity"]["id"] == "agent-bot"
        assert block["observed"]["head_sha"] == HEAD_A
        assert block["observed"]["evidence_digest"] == "sha256:" + "e" * 64
        assert block["mechanism"]["type"] == "settlement_status"
        # Self-settled PR reported, not silently dropped.
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["pr"] == 102
        assert "must differ" in result["skipped"][0]["reason"]

    def test_explicit_repo_skips_resolution(self) -> None:
        calls: list[list[str]] = []
        fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=_gh_fixture(calls)
        )
        assert ["repo", "view", "--json", "nameWithOwner"] not in calls

    def test_truncated_scan_reported(self) -> None:
        """Round-8 finding: filling the scan limit must be reported as
        truncation, never a silent undercount."""

        def run(args):
            if args[:2] == ["pr", "list"]:
                return [
                    {
                        "number": 400 + i,
                        "url": "u",
                        "mergedAt": "2026-07-16T10:00:00Z",
                        "headRefOid": str(i) * 40,
                        "author": {"login": "agent-bot"},
                    }
                    for i in range(2)
                ]
            return []

        result = fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=run, limit=2
        )
        assert result["truncated"] is True
        below_limit = fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=run, limit=5
        )
        assert below_limit["truncated"] is False

    def test_paginated_status_pages_flattened(self) -> None:
        """Round-6 finding (openai P2): the settlement status must be found
        even when it sits on a later status page (gh --paginate --slurp
        returns an array of pages)."""

        def run(args):
            if args[:2] == ["pr", "list"]:
                return [
                    {
                        "number": 300,
                        "url": "u",
                        "mergedAt": "2026-07-16T10:00:00Z",
                        "headRefOid": "9" * 40,
                        "author": {"login": "agent-bot"},
                    }
                ]
            assert "--paginate" in args and "--slurp" in args
            assert "per_page=100" in args[1]
            page1 = [{"context": f"ci/noise-{i}", "state": "success"} for i in range(3)]
            page2 = [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "overseer"},
                    "created_at": "2026-07-16T11:00:00Z",
                    "description": "settled",
                    "url": "https://api.github.com/repos/acme/widgets/statuses/9",
                }
            ]
            return [page1, page2]

        result = fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=run
        )
        assert len(result["attestations"]) == 1
        assert result["attestations"][0]["pr"] == 300

    def test_unresolvable_author_skipped(self) -> None:
        """Round-5 finding (claude P3): without a resolvable executing author
        the separation check cannot run — skip with reason, never assume."""

        def run(args):
            if args[:2] == ["pr", "list"]:
                return [
                    {
                        "number": 200,
                        "url": "u",
                        "mergedAt": "2026-07-16T10:00:00Z",
                        "headRefOid": "f" * 40,
                        "author": {},
                    }
                ]
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "overseer"},
                    "created_at": "2026-07-16T11:00:00Z",
                    "description": "settled",
                    "url": "https://api.github.com/repos/acme/widgets/statuses/f",
                }
            ]

        result = fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=run
        )
        assert result["attestations"] == []
        assert result["skipped"][0]["pr"] == 200
        assert "identity separation unverifiable" in result["skipped"][0]["reason"]

    def test_unresolvable_repo_raises(self) -> None:
        def run(args):
            return {} if args[:2] == ["repo", "view"] else []

        with pytest.raises(ValueError, match="could not resolve repo"):
            fetch_settlement_attestations(window_days=30, now=NOW, gh_runner=run)

    def test_statuses_fetch_failure_skipped_with_reason(self) -> None:
        """A malformed statuses payload (json.loads ValueError in the real
        gh path) must skip that PR with the reason — never abort the scan or
        silently drop the PR."""

        def run(args):
            if args[:2] == ["pr", "list"]:
                return [
                    {
                        "number": 500,
                        "url": "u",
                        "mergedAt": "2026-07-16T10:00:00Z",
                        "headRefOid": "a" * 40,
                        "author": {"login": "agent-bot"},
                    },
                    {
                        "number": 501,
                        "url": "u",
                        "mergedAt": "2026-07-15T10:00:00Z",
                        "headRefOid": "b" * 40,
                        "author": {"login": "agent-bot"},
                    },
                ]
            if "a" * 40 in args[1]:
                raise ValueError("Expecting value: line 1 column 1 (char 0)")
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "overseer"},
                    "created_at": "2026-07-15T11:00:00Z",
                    "description": "settled",
                    "url": "https://api.github.com/repos/acme/widgets/statuses/b",
                }
            ]

        result = fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=run
        )
        # The healthy PR is still attested; the broken one is reported.
        assert [e["pr"] for e in result["attestations"]] == [501]
        assert result["skipped"][0]["pr"] == 500
        assert "statuses fetch failed" in result["skipped"][0]["reason"]

    def test_settlement_attested_outside_window_not_counted(self) -> None:
        """A settlement status attested before the window cutoff (e.g. an old
        settlement on a recently re-merged head) must not be counted as
        in-window oversight."""

        def run(args):
            if args[:2] == ["pr", "list"]:
                return [
                    {
                        "number": 600,
                        "url": "u",
                        "mergedAt": "2026-07-16T10:00:00Z",
                        "headRefOid": "c" * 40,
                        "author": {"login": "agent-bot"},
                    }
                ]
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "overseer"},
                    "created_at": "2026-01-01T11:00:00Z",  # far before cutoff
                    "description": "settled",
                    "url": "https://api.github.com/repos/acme/widgets/statuses/c",
                }
            ]

        result = fetch_settlement_attestations(
            repo="acme/widgets", window_days=30, now=NOW, gh_runner=run
        )
        assert result["attestations"] == []
        assert result["scanned_prs"] == 1


class TestFetchReportPersistence:
    def test_fetch_report_persisted_in_pack_and_markdown(self) -> None:
        """Round-9 finding: skipped/truncated fetch metadata must live in the
        persisted artifact, not only the console output."""
        report = {
            "repo": "acme/widgets",
            "scanned_prs": 7,
            "skipped": [{"pr": 102, "reason": "oversight identity must differ"}],
            "truncated": True,
        }
        pack = build_oversight_pack([], window_days=30, now=NOW, settlement_fetch_report=report)
        assert pack["settlement_fetch"]["truncated"] is True
        assert pack["settlement_fetch"]["skipped"][0]["pr"] == 102
        md = render_oversight_pack_markdown(pack)
        assert "Settlement fetch completeness" in md
        assert "undercounted" in md
        assert "#102" in md

    def test_no_report_stays_none(self) -> None:
        pack = build_oversight_pack([], window_days=30, now=NOW)
        assert pack["settlement_fetch"] is None


class TestPackIntegration:
    def _fetched(self) -> list[dict]:
        calls: list[list[str]] = []
        return fetch_settlement_attestations(window_days=30, now=NOW, gh_runner=_gh_fixture(calls))[
            "attestations"
        ]

    def test_settlements_flow_into_pack(self) -> None:
        pack = build_oversight_pack(
            [], window_days=30, now=NOW, settlement_attestations=self._fetched()
        )
        assert pack["summary"]["settlement_attestations"] == 1
        assert "overseer" in pack["summary"]["attestor_identities"]
        assert pack["summary"]["mechanisms"]["settlement_status"] == 1
        assert pack["settlement_attestations"][0]["pr"] == 101

    def test_trail_settlements_alone_cap_identity_clauses_at_partial(self) -> None:
        """Round-7 finding: trail settlements demonstrate the mechanism
        operating but are not matched to windowed receipts, so alone they
        never flip identity clauses to satisfied (no per-decision
        overstatement). The basis names the settlements explicitly."""
        pack = build_oversight_pack(
            [
                {
                    "receipt_id": "r1",
                    "timestamp": "2026-07-10T00:00:00+00:00",
                    "verdict": "PASS",
                    "confidence": 0.9,
                }
            ],
            window_days=30,
            now=NOW,
            settlement_attestations=self._fetched(),
        )
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "partial"
        assert (
            "demonstrate the oversight mechanism operating" in (by_clause["14(1)"]["status_basis"])
        )
        assert by_clause["14(4)(e)"]["status"] == "partial"

    def test_receipt_attestation_plus_settlements_satisfied(self) -> None:
        attested_odr = {
            "odr_version": "0.1",
            "receipt_id": "r-att",
            "issued_at": "2026-07-10T00:00:00+00:00",
            "claim": {"verdict": "PASS"},
            "confidence": {"value": 0.8},
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer2"},
                "execution_identity": {"id": "agent-bot"},
                "attested_at": "2026-07-10T00:00:00+00:00",
                "mechanism": {"type": "preapproval_comment"},
            },
        }
        pack = build_oversight_pack(
            [attested_odr],
            window_days=30,
            now=NOW,
            settlement_attestations=self._fetched(),
        )
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "satisfied"
        assert (
            "human-settlement attestation(s) from the trail" in (by_clause["14(1)"]["status_basis"])
        )

    def test_without_settlements_behavior_unchanged(self) -> None:
        pack = build_oversight_pack([], window_days=30, now=NOW)
        assert pack["summary"]["settlement_attestations"] == 0
        assert pack["settlement_attestations"] == []
        assert all(c["status"] == "partial" for c in pack["article_14_mapping"])

    def test_markdown_lists_settlements(self) -> None:
        pack = build_oversight_pack(
            [], window_days=30, now=NOW, settlement_attestations=self._fetched()
        )
        md = render_oversight_pack_markdown(pack)
        assert "Human-settlement attestations" in md
        assert "#101" in md
        assert "overseer" in md
