"""Tests for AGT-04 StakeableClaim in-memory store and resolution adapter stub.

Covers:
- Feature gate off/on semantics
- StakeableClaim dataclass construction and to_dict shape
- InMemoryStakeableClaimStore: add, get, list_open, list_by_type, all, __len__
- InMemoryStakeableClaimStore: record_position, resolve, expire_stale
- Error paths: unknown ID, already-resolved, bad probability, duplicate add
- GithubResolutionAdapterStub: can_resolve coverage, resolve raises NotImplementedError
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from aragora.prediction.stakeable_claim import (
    GithubResolutionAdapterStub,
    InMemoryStakeableClaimStore,
    QuestionType,
    ResolutionStatus,
    StakeableClaim,
    _ENV_FLAG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_expiry(days: int = 7) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).isoformat()


def _past_expiry(days: int = 1) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()


def _make_claim(
    claim_id: str = "c1",
    question_type: QuestionType = QuestionType.PR_MERGE,
    expiry: str | None = None,
) -> StakeableClaim:
    return StakeableClaim(
        claim_id=claim_id,
        question=f"Will PR #42 merge within 7 days? ({claim_id})",
        question_type=question_type,
        target_ref="synaptent/aragora#42",
        expiry=expiry or _future_expiry(),
    )


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------


class TestFeatureGate:
    def test_store_blocked_when_flag_off(self, monkeypatch):
        monkeypatch.delenv(_ENV_FLAG, raising=False)
        store = InMemoryStakeableClaimStore()
        with pytest.raises(RuntimeError, match="disabled"):
            store.add(_make_claim())

    def test_store_allowed_when_flag_on(self, monkeypatch):
        monkeypatch.setenv(_ENV_FLAG, "1")
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim())
        assert len(store) == 1

    @pytest.mark.parametrize("val", ["true", "True", "yes", "on", "1"])
    def test_truthy_flag_values(self, monkeypatch, val):
        monkeypatch.setenv(_ENV_FLAG, val)
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim())

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_flag_values(self, monkeypatch, val):
        monkeypatch.setenv(_ENV_FLAG, val)
        store = InMemoryStakeableClaimStore()
        with pytest.raises(RuntimeError):
            store.add(_make_claim())

    def test_dataclasses_importable_without_flag(self, monkeypatch):
        monkeypatch.delenv(_ENV_FLAG, raising=False)
        # Construction must not raise — flag only gates store methods
        claim = _make_claim()
        assert claim.claim_id == "c1"

    def test_get_blocked_when_flag_off(self, monkeypatch):
        monkeypatch.delenv(_ENV_FLAG, raising=False)
        store = InMemoryStakeableClaimStore()
        with pytest.raises(RuntimeError):
            store.get("anything")

    def test_list_open_blocked_when_flag_off(self, monkeypatch):
        monkeypatch.delenv(_ENV_FLAG, raising=False)
        store = InMemoryStakeableClaimStore()
        with pytest.raises(RuntimeError):
            store.list_open()


# ---------------------------------------------------------------------------
# StakeableClaim dataclass
# ---------------------------------------------------------------------------


class TestStakeableClaimDataclass:
    def test_defaults(self):
        claim = _make_claim()
        assert claim.resolution_status == ResolutionStatus.OPEN
        assert claim.resolution_value is None
        assert claim.positions == {}
        assert claim.credit_cap == 100
        assert claim.resolution_evidence == ""

    def test_is_open_true_for_new(self):
        assert _make_claim().is_open()

    def test_to_dict_keys(self):
        d = _make_claim().to_dict()
        expected = {
            "claim_id",
            "question",
            "question_type",
            "target_ref",
            "expiry",
            "resolution_window_days",
            "resolution_status",
            "resolution_value",
            "resolution_evidence",
            "positions",
            "credit_cap",
            "created_at",
        }
        assert set(d.keys()) == expected

    def test_to_dict_question_type_is_string(self):
        d = _make_claim(question_type=QuestionType.ISSUE_CLOSE).to_dict()
        assert d["question_type"] == "issue_close"

    def test_to_dict_status_is_string(self):
        d = _make_claim().to_dict()
        assert d["resolution_status"] == "open"

    def test_created_at_is_iso_utc(self):
        claim = _make_claim()
        # Must parse without error and be timezone-aware
        dt = datetime.fromisoformat(claim.created_at)
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# InMemoryStakeableClaimStore — happy paths
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch):
    monkeypatch.setenv(_ENV_FLAG, "1")


class TestStoreHappyPaths:
    def test_add_and_get(self):
        store = InMemoryStakeableClaimStore()
        claim = _make_claim("x1")
        store.add(claim)
        assert store.get("x1") is claim

    def test_len_tracks_adds(self):
        store = InMemoryStakeableClaimStore()
        assert len(store) == 0
        store.add(_make_claim("a"))
        store.add(_make_claim("b"))
        assert len(store) == 2

    def test_all_returns_all(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("a"))
        store.add(_make_claim("b"))
        assert {c.claim_id for c in store.all()} == {"a", "b"}

    def test_list_open_returns_open_only(self, monkeypatch):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("open1"))
        store.add(_make_claim("open2"))
        store.resolve("open2", False)
        open_ids = {c.claim_id for c in store.list_open()}
        assert open_ids == {"open1"}

    def test_list_by_type_filters(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("pr1", QuestionType.PR_MERGE))
        store.add(_make_claim("ic1", QuestionType.ISSUE_CLOSE))
        store.add(_make_claim("ci1", QuestionType.CI_PASS))
        pr_claims = store.list_by_type(QuestionType.PR_MERGE)
        assert len(pr_claims) == 1
        assert pr_claims[0].claim_id == "pr1"

    def test_record_position_stores_probability(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("p1"))
        store.record_position("p1", "agent_alpha", 0.75)
        assert store.get("p1").positions["agent_alpha"] == pytest.approx(0.75)

    def test_record_position_overwrites_previous(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("p2"))
        store.record_position("p2", "agent_alpha", 0.6)
        store.record_position("p2", "agent_alpha", 0.8)
        assert store.get("p2").positions["agent_alpha"] == pytest.approx(0.8)

    def test_resolve_yes(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("r1"))
        result = store.resolve("r1", True, "PR merged at 12:00 UTC")
        assert result.resolution_status == ResolutionStatus.RESOLVED_YES
        assert result.resolution_value is True
        assert result.resolution_evidence == "PR merged at 12:00 UTC"

    def test_resolve_no(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("r2"))
        store.resolve("r2", False)
        assert store.get("r2").resolution_status == ResolutionStatus.RESOLVED_NO
        assert store.get("r2").resolution_value is False

    def test_expire_stale_marks_past_claims(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("past", expiry=_past_expiry(2)))
        store.add(_make_claim("future", expiry=_future_expiry(7)))
        expired = store.expire_stale()
        assert "past" in expired
        assert "future" not in expired
        assert store.get("past").resolution_status == ResolutionStatus.EXPIRED
        assert store.get("future").resolution_status == ResolutionStatus.OPEN

    def test_expire_stale_skips_already_resolved(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("done", expiry=_past_expiry(1)))
        store.resolve("done", True)
        expired = store.expire_stale()
        assert "done" not in expired

    def test_expire_stale_custom_cutoff(self):
        store = InMemoryStakeableClaimStore()
        far_future = _future_expiry(365)
        store.add(_make_claim("far", expiry=far_future))
        # cutoff 400 days ahead — should expire even "far future" claim
        cutoff = datetime.now(tz=UTC) + timedelta(days=400)
        expired = store.expire_stale(cutoff)
        assert "far" in expired

    def test_expire_stale_rejects_negative_grace(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("negative-grace", expiry=_past_expiry(1)))

        with pytest.raises(ValueError, match="non-negative"):
            store.expire_stale(grace=-1)

    def test_expire_stale_accepts_z_suffix_expiry(self):
        store = InMemoryStakeableClaimStore()
        expiry = _past_expiry(2).replace("+00:00", "Z")
        store.add(_make_claim("z-expiry", expiry=expiry))

        expired = store.expire_stale()

        assert expired == ["z-expiry"]
        assert store.get("z-expiry").resolution_status == ResolutionStatus.EXPIRED

    def test_expire_stale_treats_naive_cutoff_as_utc(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("naive-cutoff", expiry=_past_expiry(2)))
        cutoff = datetime.now(tz=UTC).replace(tzinfo=None)

        expired = store.expire_stale(cutoff)

        assert expired == ["naive-cutoff"]


# ---------------------------------------------------------------------------
# InMemoryStakeableClaimStore — error paths
# ---------------------------------------------------------------------------


class TestStoreErrorPaths:
    def test_add_duplicate_raises(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("dup"))
        with pytest.raises(ValueError, match="already exists"):
            store.add(_make_claim("dup"))

    def test_get_unknown_raises_key_error(self):
        store = InMemoryStakeableClaimStore()
        with pytest.raises(KeyError):
            store.get("missing")

    def test_resolve_unknown_raises(self):
        store = InMemoryStakeableClaimStore()
        with pytest.raises(KeyError):
            store.resolve("missing", True)

    def test_resolve_already_resolved_raises(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("done"))
        store.resolve("done", True)
        with pytest.raises(ValueError, match="already"):
            store.resolve("done", False)

    def test_record_position_bad_probability_low(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("bad"))
        with pytest.raises(ValueError, match="probability"):
            store.record_position("bad", "agent", -0.1)

    def test_record_position_bad_probability_high(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("bad2"))
        with pytest.raises(ValueError, match="probability"):
            store.record_position("bad2", "agent", 1.1)

    def test_record_position_on_resolved_claim_raises(self):
        store = InMemoryStakeableClaimStore()
        store.add(_make_claim("res"))
        store.resolve("res", True)
        with pytest.raises(ValueError, match="already"):
            store.record_position("res", "agent", 0.5)


# ---------------------------------------------------------------------------
# GithubResolutionAdapterStub
# ---------------------------------------------------------------------------


class TestGithubResolutionAdapterStub:
    def test_can_resolve_pr_merge(self):
        stub = GithubResolutionAdapterStub()
        assert stub.can_resolve(_make_claim(question_type=QuestionType.PR_MERGE))

    def test_can_resolve_issue_close(self):
        stub = GithubResolutionAdapterStub()
        assert stub.can_resolve(_make_claim(question_type=QuestionType.ISSUE_CLOSE))

    def test_can_resolve_ci_pass(self):
        stub = GithubResolutionAdapterStub()
        assert stub.can_resolve(_make_claim(question_type=QuestionType.CI_PASS))

    def test_cannot_resolve_dependency_release(self):
        stub = GithubResolutionAdapterStub()
        assert not stub.can_resolve(_make_claim(question_type=QuestionType.DEPENDENCY_RELEASE))

    def test_resolve_raises_not_implemented(self):
        stub = GithubResolutionAdapterStub()
        with pytest.raises(NotImplementedError, match="placeholder"):
            stub.resolve(_make_claim())


class TestMalformedExpiryQuarantine:
    """#8777: malformed expiry must quarantine, never leave a zombie claim."""

    def test_malformed_expiry_is_quarantined_as_expired(self, caplog):
        import logging as _logging

        store = InMemoryStakeableClaimStore()
        claim = StakeableClaim(
            claim_id="zombie-1",
            question="Will a/b#99 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#99",
            expiry="not-a-datetime",
        )
        store.add(claim)
        with caplog.at_level(_logging.WARNING):
            expired = store.expire_stale()
        assert "zombie-1" in expired
        assert claim.resolution_status == ResolutionStatus.EXPIRED
        assert any("malformed expiry" in rec.message for rec in caplog.records)
