"""Tests for the AGT-04 batch market emitter.

Uses a real MarketStore backed by tmp_path (no live GitHub calls).
gh_runner=None on the adapter so no subprocess is ever started.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aragora.connectors.prediction_markets.synthetic_github import (
    SYNTHETIC_MARKETS_FLAG,
    SyntheticGitHubAdapter,
)
from aragora.markets.emitter import (
    BatchEmitError,
    IssueEntry,
    PrEntry,
    emit_markets_for_issues,
    emit_markets_for_prs,
)
from aragora.markets.store import MarketStore


@pytest.fixture()
def adapter(tmp_path: Path) -> SyntheticGitHubAdapter:
    return SyntheticGitHubAdapter(
        store=MarketStore(tmp_path / "markets"), gh_runner=None, require_expiry=False
    )


class TestEntryValidation:
    def test_pr_entry_rejects_empty_repo(self) -> None:
        with pytest.raises(ValueError, match="repo"):
            PrEntry(repo="", number=1)

    def test_pr_entry_rejects_zero_number(self) -> None:
        with pytest.raises(ValueError, match="positive int"):
            PrEntry(repo="owner/repo", number=0)


class TestFlagGate:
    def test_prs_raises_when_disabled(
        self, adapter: SyntheticGitHubAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(SYNTHETIC_MARKETS_FLAG, raising=False)
        with pytest.raises(BatchEmitError, match="disabled"):
            emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=1)])

    def test_issues_raises_when_disabled(
        self, adapter: SyntheticGitHubAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(SYNTHETIC_MARKETS_FLAG, raising=False)
        with pytest.raises(BatchEmitError, match="disabled"):
            emit_markets_for_issues(adapter, [IssueEntry(repo="owner/repo", number=1)])

    @pytest.mark.parametrize("val", ["0", "false", "no", ""])
    def test_prs_falsy_values_raise(
        self, val: str, adapter: SyntheticGitHubAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SYNTHETIC_MARKETS_FLAG, val)
        with pytest.raises(BatchEmitError):
            emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=1)])

    def test_truthy_value_enables(
        self, adapter: SyntheticGitHubAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SYNTHETIC_MARKETS_FLAG, "1")
        assert (
            emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=1)]).created_count == 1
        )


class TestEmitPrs:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SYNTHETIC_MARKETS_FLAG, "1")

    def test_empty_input(self, adapter: SyntheticGitHubAdapter) -> None:
        assert emit_markets_for_prs(adapter, []).total_seen == 0

    def test_creates_pr_market(self, adapter: SyntheticGitHubAdapter) -> None:
        r = emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=1)])
        assert r.created_count == 1
        assert r.created[0].question_kind == "pr_merge"
        assert r.created[0].target["number"] == 1

    def test_idempotent(self, adapter: SyntheticGitHubAdapter) -> None:
        prs = [PrEntry(repo="owner/repo", number=1)]
        emit_markets_for_prs(adapter, prs)
        r = emit_markets_for_prs(adapter, prs)
        assert r.created_count == 0 and r.skipped_count == 1

    def test_partial_overlap(self, adapter: SyntheticGitHubAdapter) -> None:
        emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=1)])
        r = emit_markets_for_prs(
            adapter, [PrEntry(repo="owner/repo", number=1), PrEntry(repo="owner/repo", number=2)]
        )
        assert r.created_count == 1 and r.skipped_count == 1

    def test_title_in_description(self, adapter: SyntheticGitHubAdapter) -> None:
        r = emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=7, title="Add X")])
        assert "Add X" in r.created[0].description

    def test_invalid_repo_is_error(self, adapter: SyntheticGitHubAdapter) -> None:
        r = emit_markets_for_prs(adapter, [PrEntry(repo="badrepo", number=1)])
        assert r.error_count == 1 and r.created_count == 0

    def test_error_does_not_abort_batch(self, adapter: SyntheticGitHubAdapter) -> None:
        r = emit_markets_for_prs(
            adapter, [PrEntry(repo="bad", number=1), PrEntry(repo="owner/repo", number=2)]
        )
        assert r.error_count == 1 and r.created_count == 1

    def test_to_json_shape(self, adapter: SyntheticGitHubAdapter) -> None:
        j = emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=1)]).to_json()
        assert {"created_count", "skipped_count", "error_count", "total_seen"} <= j.keys()


class TestEmitIssues:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SYNTHETIC_MARKETS_FLAG, "1")

    def test_creates_issue_market(self, adapter: SyntheticGitHubAdapter) -> None:
        r = emit_markets_for_issues(adapter, [IssueEntry(repo="owner/repo", number=42)])
        assert r.created_count == 1
        assert r.created[0].question_kind == "issue_close"

    def test_idempotent(self, adapter: SyntheticGitHubAdapter) -> None:
        issues = [IssueEntry(repo="owner/repo", number=10)]
        emit_markets_for_issues(adapter, issues)
        r = emit_markets_for_issues(adapter, issues)
        assert r.created_count == 0 and r.skipped_count == 1

    def test_pr_and_issue_markets_are_distinct(self, adapter: SyntheticGitHubAdapter) -> None:
        emit_markets_for_prs(adapter, [PrEntry(repo="owner/repo", number=5)])
        r = emit_markets_for_issues(adapter, [IssueEntry(repo="owner/repo", number=5)])
        assert r.created_count == 1
