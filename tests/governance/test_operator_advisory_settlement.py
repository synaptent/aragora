"""Tests for the operator-advisory-settlement relief valve.

Spec: docs/specs/OPERATOR_ADVISORY_SETTLEMENT.md (#8933 incident, PR #8939).

These pin the two new load-bearing helpers directly (the valve's family
accounting and its trusted-author marker check), the flag gate, AND the
assembled verdict through ``_build_model_review_quorum`` — the last of these
guards the self-check-independent reachability signal (a packet-level test is
what catches a valve gated on the always-False-in-CI ``quorum_only_failure``).
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.cli.commands import review_queue as rq
from aragora.cli.commands.review_queue import _build_model_review_quorum

HEAD = "abfea376c6216173b6f4ed84306893acc9563545"
COMMITTED_AT = "2026-07-10T23:00:00Z"


def _review(family: str, *, verdict: str = "approve", body_extra: str = "") -> dict[str, Any]:
    """A grounded, non-bot, countable model-review comment for ``family``."""
    return {
        "author": {"login": "an0mium"},
        "createdAt": "2026-07-11T00:00:00Z",
        "body": (
            f"## {family} independent model review\n"
            f"**Model family:** {family}\n"
            f"Head: {HEAD}\n"
            f"Verdict: {verdict}.\n"
            f"{body_extra}"
        ),
    }


# --- validated-family accounting (condition 4) -----------------------------


class TestValidatedFamilies:
    def test_two_distinct_families_are_counted(self) -> None:
        comments = [_review("claude"), _review("openai")]
        _wf, _diss, blocking, families = rq._advisory_settle_review_signals(
            comments, head_sha=HEAD, head_committed_at=COMMITTED_AT
        )
        assert families == frozenset({"claude", "openai"})
        assert blocking is False

    def test_settlement_marker_and_plain_prose_do_not_inflate_family_count(self) -> None:
        # Family attribution uses the SAME validated pass advisory_settle uses:
        # a comment must be a RECOGNIZED model review (not raw text) to attribute
        # a family. The settlement marker comment and ordinary prose are not
        # recognized reviews, so a single genuine review cannot be padded to a
        # false quorum-of-two by non-review chatter. (Family attribution for a
        # recognized review follows advisory_settle's self-declared-header
        # standard by design; the valve's binding authorization is the
        # trusted-creator commit status, not this corroborating count.)
        prose = {
            "author": {"login": "an0mium"},
            "createdAt": "2026-07-11T00:00:00Z",
            "body": f"Looks good to me, thanks. (reviewed {HEAD})",
        }
        marker = _marker("scarmani")
        marker["createdAt"] = "2026-07-11T00:00:00Z"
        _wf, _diss, _block, families = rq._advisory_settle_review_signals(
            [_review("claude"), prose, marker], head_sha=HEAD, head_committed_at=COMMITTED_AT
        )
        assert families == frozenset({"claude"})

    def test_bot_authored_review_does_not_count_family(self) -> None:
        # Positive family attribution requires a non-bot author (the blocking
        # scan still consults bot reviews, but they never ADD a countable family).
        bot = _review("openai")
        bot["author"] = {"login": "github-actions[bot]"}
        _wf, _diss, _block, families = rq._advisory_settle_review_signals(
            [_review("claude"), bot], head_sha=HEAD, head_committed_at=COMMITTED_AT
        )
        assert families == frozenset({"claude"})

    def test_blocking_finding_is_reported(self) -> None:
        comments = [_review("claude", verdict="request changes", body_extra="- [P1] real bug")]
        _wf, _diss, blocking, _families = rq._advisory_settle_review_signals(
            comments, head_sha=HEAD, head_committed_at=COMMITTED_AT
        )
        assert blocking is True

    def test_stale_comment_excluded(self) -> None:
        stale = _review("claude")
        stale["createdAt"] = "2020-01-01T00:00:00Z"
        stale["body"] = stale["body"].replace(f"Head: {HEAD}\n", "")  # no SHA cite either
        _wf, _diss, _block, families = rq._advisory_settle_review_signals(
            [stale], head_sha=HEAD, head_committed_at=COMMITTED_AT
        )
        assert families == frozenset()


# --- trusted-author marker comment (condition 6) ---------------------------


def _marker(author: str, *, head: str = HEAD, token: str = "admin_squash_merge") -> dict[str, Any]:
    return {
        "author": {"login": author},
        "body": (
            "Tier-4 Human Settlement Authorization\n\n"
            f"PR: #8939\nExact head: {head}\n"
            f"Authorized action: {token}.\n"
            "Human-risk settlement: I accept the Tier 4 risk for this PR.\n"
        ),
    }


class TestOperatorSettlementComment:
    def _pr(self, *comments: dict[str, Any]) -> dict[str, Any]:
        return {"comments": list(comments)}

    def test_trusted_author_marker_accepted(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        pr = self._pr(_marker("scarmani"))
        assert rq._has_operator_settlement_comment(pr, head_sha=HEAD) is True

    def test_untrusted_author_marker_rejected(self, monkeypatch: Any) -> None:
        # Same marker text, non-operator author — must NOT authorize.
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        pr = self._pr(_marker("an0mium"))
        assert rq._has_operator_settlement_comment(pr, head_sha=HEAD) is False

    def test_trusted_author_case_insensitive(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        pr = self._pr(_marker("ScarMani"))
        assert rq._has_operator_settlement_comment(pr, head_sha=HEAD) is True

    def test_wrong_head_rejected(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        pr = self._pr(_marker("scarmani", head="0" * 40))
        assert rq._has_operator_settlement_comment(pr, head_sha=HEAD) is False

    def test_missing_merge_token_rejected(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        pr = self._pr(_marker("scarmani", token="please merge"))
        assert rq._has_operator_settlement_comment(pr, head_sha=HEAD) is False

    def test_empty_head_rejected(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        pr = self._pr(_marker("scarmani"))
        assert rq._has_operator_settlement_comment(pr, head_sha="") is False


# --- flag gate (condition 1) -----------------------------------------------


class TestFlagGate:
    def test_default_off(self) -> None:
        assert rq._operator_advisory_settlement_enabled(env={}) is False

    def test_on_values(self) -> None:
        for value in ("1", "true", "yes", "on", "ON", "True"):
            assert (
                rq._operator_advisory_settlement_enabled(
                    env={"ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT": value}
                )
                is True
            )

    def test_off_values(self) -> None:
        for value in ("0", "false", "no", "", "off"):
            assert (
                rq._operator_advisory_settlement_enabled(
                    env={"ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT": value}
                )
                is False
            )


# --- assembled verdict through _build_model_review_quorum -------------------


def _advisory_review(
    family: str, *, receipt: bool = True, author: str = "an0mium"
) -> dict[str, Any]:
    """A grounded advisory (CHANGES-REQUESTED, [P2]-only) review — non-blocking,
    non-counting under severity gating, but a validated family that was HEARD.

    ``receipt=True`` + the default trusted ``author`` mirror a real
    collector-posted review; ``receipt=False`` or an untrusted ``author`` model
    the spoof shapes the valve's strict pass must ignore (claude #9203 P2 /
    openai #9203 P1: the receipt LINE is forgeable text — authorship is the
    API-real guard)."""
    receipt_line = (
        f"**Receipt artifact:** .aragora/receipts/{family}-review.json\n" if receipt else ""
    )
    return {
        "author": {"login": author},
        "createdAt": "2026-07-11T00:00:00Z",
        "body": (
            f"## {family} independent model review\n"
            f"**Model family:** {family}\n"
            f"{receipt_line}"
            f"Current head: {HEAD}\n\n"
            "Verdict: request changes.\n"
            "- [P2] a non-blocking nit worth polishing."
        ),
    }


class TestAssembledValve:
    """Exercise the full valve through _build_model_review_quorum.

    This is the level that catches a valve gated on the wrong reachability
    signal: quorum_only_failure is always False inside the enforcing job, so a
    unit test of the primitives alone would pass while the valve stayed dead.
    """

    def _tier4_pr(self) -> dict[str, Any]:
        return {
            "number": 8939,
            "title": "gate-code change",
            "state": "OPEN",
            "isDraft": False,
            "headRefOid": HEAD,
            "mergeable": "MERGEABLE",
            "comments": [
                _advisory_review("claude"),
                _advisory_review("openai"),
                _marker("scarmani"),
            ],
            "statusCheckRollup": [
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"context": "aragora/human-settlement", "state": "SUCCESS"},
            ],
            "commits": [{"commit": {"committedDate": COMMITTED_AT}}],
        }

    _SURFACE_CLEAR = {
        # Self-check-independent: no NON-quorum required check is failing, so the
        # surface is clear even though quorum_only_failure is False (the quorum
        # row is the excluded self-check inside the enforcing job).
        "required_pr_checks": {
            "quorum_only_failure": False,
            "advisory_settle_surface_clear": True,
        }
    }

    def _build(self, monkeypatch: Any, files: list[str]) -> dict[str, Any]:
        # Mirror the enforcing CI env: severity-gated dissent turns the [P2]-only
        # CHANGES-REQUESTED reviews into advisory (non-blocking) dissent, so
        # unresolved_dissent is False and the valve can consider them. Without
        # this flag a [P2] CR is a hard dissent and the valve correctly refuses.
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        monkeypatch.setattr(
            rq,
            "_human_settlement_status_creator_verified",
            lambda **_kw: (True, "verified"),
        )
        return _build_model_review_quorum(
            pr=self._tier4_pr(),
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=True,  # the quorum row is the failing required check
            check_surfaces=self._SURFACE_CLEAR,
            repo_slug="synaptent/aragora",
        )

    def test_valve_fires_flag_on(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", "1")
        q = self._build(monkeypatch, ["aragora/cli/commands/review_queue.py"])
        assert q["tier"] == 4
        assert q["operator_advisory_settlement"] is True
        assert q["status"] == "satisfied"
        assert q["verdict"] == "operator_advisory_settlement"
        assert sorted(q["validated_review_families"]) == ["claude", "openai"]

    def test_valve_silent_flag_off(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", raising=False)
        q = self._build(monkeypatch, ["aragora/cli/commands/review_queue.py"])
        # Flag off → the valve is inert and the PR is NOT settled, regardless of
        # which not-ready status the surrounding ladder reports.
        assert q["operator_advisory_settlement"] is False
        assert q["status"] != "satisfied"
        assert q["verdict"] != "operator_advisory_settlement"
        assert q["admin_squash_allowed"] is False

    def test_valve_refuses_tier_two(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", "1")
        q = self._build(monkeypatch, ["aragora/cli/commands/swarm.py"])
        assert q["tier"] <= 2
        assert q["operator_advisory_settlement"] is False

    def test_valve_refuses_on_blocking_finding(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        monkeypatch.setattr(
            rq, "_human_settlement_status_creator_verified", lambda **_kw: (True, "verified")
        )
        pr = self._tier4_pr()
        pr["comments"][0]["body"] += "\n- [P1] a genuine blocking bug."
        q = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/review_queue.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=True,
            check_surfaces=self._SURFACE_CLEAR,
            repo_slug="synaptent/aragora",
        )
        assert q["operator_advisory_settlement"] is False

    def test_valve_ignores_untrusted_author_even_with_receipt_line(self, monkeypatch: Any) -> None:
        """openai #9203 P1: a fabricated 'Receipt artifact:' line is just text.
        A drive-by login posting perfect-looking reviews (receipt line included)
        must not establish heard families — authorship is the API-real guard."""
        monkeypatch.setenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        monkeypatch.setattr(
            rq, "_human_settlement_status_creator_verified", lambda **_kw: (True, "verified")
        )
        pr = self._tier4_pr()
        pr["comments"] = [
            _advisory_review("claude", receipt=True, author="drive-by-account"),
            _advisory_review("openai", receipt=True, author="drive-by-account"),
            _marker("scarmani"),
        ]
        q = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/review_queue.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=True,
            check_surfaces=self._SURFACE_CLEAR,
            repo_slug="synaptent/aragora",
        )
        assert q["operator_advisory_settlement"] is False
        assert q["validated_review_families"] == []

    def test_trusted_author_without_receipt_line_counts(self, monkeypatch: Any) -> None:
        """openai #9203 round-6 P2: compose_evidence_comment never emits a
        Receipt artifact line, so trusted-author evidence WITHOUT one is the
        production shape and must count — a receipt requirement would make the
        valve unfireable against every real collector-posted review. The guard
        against spoofing is authorship (API-real), not body text."""
        monkeypatch.setenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        monkeypatch.setattr(
            rq, "_human_settlement_status_creator_verified", lambda **_kw: (True, "verified")
        )
        pr = self._tier4_pr()
        pr["comments"] = [
            _advisory_review("claude", receipt=False),
            _advisory_review("openai", receipt=False),
            _marker("scarmani"),
        ]
        q = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/review_queue.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=True,
            check_surfaces=self._SURFACE_CLEAR,
            repo_slug="synaptent/aragora",
        )
        assert q["operator_advisory_settlement"] is True
        assert sorted(q["validated_review_families"]) == ["claude", "openai"]

    def test_valve_refuses_all_pass_non_counting(self, monkeypatch: Any) -> None:
        """openai #9203 P1 (behavioral): an all-PASS non-counting Tier-4 PR — no
        genuine advisory dissent — must NOT settle via the valve; its path is the
        normal front door (get the passes to count). The `_genuine_advisory_dissent`
        requirement is the load-bearing guard here; this asserts the resulting
        behavior end-to-end (defense in depth may also refuse via other bars)."""
        monkeypatch.setenv("ARAGORA_ENABLE_OPERATOR_ADVISORY_SETTLEMENT", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        monkeypatch.setattr(rq, "_trusted_settlement_creator", lambda: "scarmani")
        monkeypatch.setattr(
            rq, "_human_settlement_status_creator_verified", lambda **_kw: (True, "verified")
        )
        pr = self._tier4_pr()
        # Replace the advisory (CR) reviews with PASS reviews from both families:
        # heard + validated, but no genuine advisory dissent — the infra-failure
        # shape the valve must refuse.
        pass_bodies = []
        for family in ("claude", "openai"):
            pass_bodies.append(
                {
                    "author": {"login": "an0mium"},
                    "createdAt": "2026-07-11T00:00:00Z",
                    "body": (
                        f"## {family} independent model review\n"
                        f"**Model family:** {family}\n"
                        f"Current head: {HEAD}\n\n"
                        "Verdict: pass.\n"
                        "Looks good."
                    ),
                }
            )
        pr["comments"] = [*pass_bodies, _marker("scarmani")]
        q = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/review_queue.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=True,
            check_surfaces=self._SURFACE_CLEAR,
            repo_slug="synaptent/aragora",
        )
        assert q["operator_advisory_settlement"] is False
