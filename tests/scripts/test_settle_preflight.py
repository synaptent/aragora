from __future__ import annotations

import json
from pathlib import Path

import scripts.settle_preflight as settle_preflight


def _entry(**overrides):
    base = {
        "pr_number": 9001,
        "title": "test pr",
        "head_sha": "a" * 40,
        "tier": 0,
        "status": "satisfied",
        "verdict": "admin_squash_allowed",
        "admin_squash_allowed": True,
        "requires_human_risk_settlement": False,
        "checks_summary": "6/6 green",
        "reasons": ["docs/tests/status-only"],
    }
    base.update(overrides)
    return base


def _metadata(**overrides):
    base = {
        "number": 9001,
        "title": "test pr",
        "headRefOid": "a" * 40,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "",
        "files": [{"path": "docs/example.md"}],
    }
    base.update(overrides)
    return base


def _check(name, state="SUCCESS"):
    return {"name": name, "state": state, "workflow": name, "link": ""}


def _required_checks(**overrides):
    states = {
        "lint": "SUCCESS",
        "typecheck": "SUCCESS",
        "sdk-parity": "SUCCESS",
        "Generate & Validate": "SUCCESS",
        "TypeScript SDK Type Check": "SUCCESS",
        "aragora-merge-quorum": "FAILURE",
    }
    states.update(overrides)
    return [_check(name, state) for name, state in states.items()]


def _blocked_metadata(**overrides):
    base = {"mergeStateStatus": "BLOCKED", "required_checks": _required_checks()}
    base.update(overrides)
    return _metadata(**base)


def _light_metadata(**overrides):
    metadata = _metadata(**overrides)
    metadata.pop("files", None)
    return metadata


def _packet(entry=None):
    return {"entries": [entry or _entry()]}


def test_main_red_halt_verdict() -> None:
    result = settle_preflight.classify_pr(entry=_entry(), metadata=_metadata(), main_red=True)

    assert result.verdict == settle_preflight.MAIN_RED_HALT
    assert "main-red" in result.action
    assert result.recheck_rule == settle_preflight.RECHECK_RULE


def test_draft_skip_verdict() -> None:
    result = settle_preflight.classify_pr(entry=_entry(), metadata=_metadata(isDraft=True))

    assert result.verdict == settle_preflight.DRAFT_SKIP
    assert "marked ready" in result.action


def test_human_gated_for_tier_above_two() -> None:
    result = settle_preflight.classify_pr(entry=_entry(tier=4), metadata=_metadata())

    assert result.verdict == settle_preflight.HUMAN_GATED
    assert "Tier 4" in result.reasons
    assert "human settlement" in result.action


def test_human_gated_for_unsettled_human_risk() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(tier=2, requires_human_risk_settlement=True),
        metadata=_metadata(),
    )

    assert result.verdict == settle_preflight.HUMAN_GATED
    assert any("requires_human_risk_settlement" in reason for reason in result.reasons)


def test_recorded_human_settlement_clears_human_risk_reason() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(
            tier=2,
            requires_human_risk_settlement=True,
            human_preapproval_recorded=True,
        ),
        metadata=_metadata(),
    )

    assert result.verdict == settle_preflight.READY


def test_human_gated_for_unsettled_human_preapproval() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(tier=2, requires_human_preapproval=True),
        metadata=_metadata(),
    )

    assert result.verdict == settle_preflight.HUMAN_GATED
    assert any("requires_human_preapproval" in reason for reason in result.reasons)


def test_policy_exclusions_do_not_become_ready() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_metadata(files=[{"path": ".github/workflows/build.yml"}]),
    )

    assert result.verdict == settle_preflight.HUMAN_GATED
    assert settle_preflight.settle_one_pr.SURFACE_EXCLUDE_REASON in result.reasons


def test_head_blocked_for_conflicting_or_behind_state() -> None:
    dirty = settle_preflight.classify_pr(
        entry=_entry(admin_squash_allowed=False),
        metadata=_metadata(mergeable="CONFLICTING", mergeStateStatus="DIRTY"),
    )
    behind = settle_preflight.classify_pr(
        entry=_entry(admin_squash_allowed=False),
        metadata=_metadata(mergeStateStatus="BEHIND"),
    )

    assert dirty.verdict == settle_preflight.HEAD_BLOCKED
    assert behind.verdict == settle_preflight.HEAD_BLOCKED


def test_head_blocked_for_packet_head_drift() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(head_sha="b" * 40),
        metadata=_metadata(headRefOid="a" * 40),
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert any("head drift" in reason for reason in result.reasons)


def test_head_blockers_take_precedence_over_github_unstable() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(checks_summary="5/6 green, 1 failing"),
        metadata=_metadata(mergeStateStatus="UNSTABLE"),
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert any("checks failing" in reason for reason in result.reasons)


def test_github_unstable_for_model_authorized_unstable_state() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_metadata(mergeStateStatus="UNSTABLE"),
    )

    assert result.verdict == settle_preflight.GITHUB_UNSTABLE
    assert "do not merge" in result.action


def test_github_unstable_for_unknown_merge_state() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_metadata(mergeStateStatus=""),
    )

    assert result.verdict == settle_preflight.GITHUB_UNSTABLE
    assert any("mergeStateStatus=unknown" in reason for reason in result.reasons)


def test_ready_for_model_authorized_clean_state() -> None:
    result = settle_preflight.classify_pr(entry=_entry(), metadata=_metadata())

    assert result.verdict == settle_preflight.READY
    assert "normal protected squash merge" in result.action


def test_ready_for_model_authorized_blocked_quorum_state() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_blocked_metadata(),
    )

    assert result.verdict == settle_preflight.READY
    assert any("aragora-merge-quorum" in reason for reason in result.reasons)


def test_blocked_required_red_context_does_not_become_ready() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_blocked_metadata(required_checks=_required_checks(typecheck="FAILURE")),
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert any("typecheck" in reason for reason in result.reasons)


def test_blocked_review_changes_requested_does_not_become_ready() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_blocked_metadata(reviewDecision="CHANGES_REQUESTED"),
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert "reviewDecision=CHANGES_REQUESTED" in result.reasons


def test_empty_file_scope_does_not_become_ready() -> None:
    result = settle_preflight.classify_pr(entry=_entry(), metadata=_metadata(files=[]))

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert settle_preflight.POLICY_METADATA_REASON in result.reasons


def test_active_owner_signal_parks_head() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(),
        metadata=_metadata(),
        active_owned_prs={9001},
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert settle_preflight.ACTIVE_OWNER_REASON in result.reasons


def test_status_and_verdict_do_not_authorize_without_boolean() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(admin_squash_allowed=False),
        metadata=_metadata(),
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert "satisfied model packet" in result.action


def test_head_blocked_when_packet_not_authorized() -> None:
    result = settle_preflight.classify_pr(
        entry=_entry(
            status="needs_model_review_quorum",
            verdict="collect_model_quorum_before_merge",
            admin_squash_allowed=False,
        ),
        metadata=_metadata(),
    )

    assert result.verdict == settle_preflight.HEAD_BLOCKED
    assert "satisfied model packet" in result.action


def test_main_red_pr_short_circuits_packet_loading(monkeypatch, capsys) -> None:
    def fail_load_single(*_args, **_kwargs):
        raise AssertionError("main-red should not load PR packets")

    monkeypatch.setattr(settle_preflight, "_load_single", fail_load_single)

    rc = settle_preflight.main(["--pr", "9001", "--main-red", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["pr_number"] == 9001
    assert payload["results"][0]["verdict"] == settle_preflight.MAIN_RED_HALT


def test_main_red_queue_short_circuits_packet_loading(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: (
            {
                9001: _metadata(number=9001, files=[]),
                9002: _metadata(number=9002, title="other", headRefOid="b" * 40, files=[]),
            },
            {},
        ),
    )

    def fail_packet(*_args, **_kwargs):
        raise AssertionError("main-red queue should not load merge packets")

    monkeypatch.setattr(settle_preflight.settle_one_pr, "_load_single_pr_packet", fail_packet)

    rc = settle_preflight.main(["--queue", "--main-red", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["verdict"] for item in payload["results"]] == [
        settle_preflight.MAIN_RED_HALT,
        settle_preflight.MAIN_RED_HALT,
    ]


def test_load_single_degrades_packet_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_pr_policy_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_live_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_required_checks",
        lambda *_args, **_kwargs: (_required_checks(), {}),
    )

    def fail_packet(*_args, **_kwargs):
        raise RuntimeError("packet unavailable")

    monkeypatch.setattr(settle_preflight.settle_one_pr, "_load_single_pr_packet", fail_packet)

    entry, metadata = settle_preflight._load_single(Path.cwd(), 9001, None)

    assert entry["status"] == "packet_unavailable"
    assert entry["verdict"] == "packet_unavailable"
    assert entry["reasons"] == ["packet unavailable"]
    assert metadata["number"] == 9001


def test_queue_mode_uses_policy_files_for_unsafe_surface(monkeypatch) -> None:
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: ({9001: _light_metadata()}, {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_live_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_pr_policy_metadata",
        lambda *_args, **_kwargs: (
            _metadata(
                files=[
                    {"path": ".github/workflows/build.yml"},
                    {"path": "aragora/server/auth/session.py"},
                ]
            ),
            {},
        ),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_required_checks",
        lambda *_args, **_kwargs: (_required_checks(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "_load_single_pr_packet",
        lambda *_args, **_kwargs: _packet(),
    )

    results = settle_preflight._classify_queue(Path.cwd(), "synaptent/aragora", 10)

    assert len(results) == 1
    assert results[0].verdict == settle_preflight.HUMAN_GATED
    assert settle_preflight.settle_one_pr.SURFACE_EXCLUDE_REASON in results[0].reasons


def test_queue_mode_policy_metadata_failure_does_not_classify_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: ({9001: _light_metadata()}, {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_live_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_pr_policy_metadata",
        lambda *_args, **_kwargs: (
            {},
            {"returncode": 1, "stderr": "gh pr view failed"},
        ),
    )

    def fail_packet(*_args, **_kwargs):
        raise AssertionError("queue mode should not load packet without policy files")

    monkeypatch.setattr(settle_preflight.settle_one_pr, "_load_single_pr_packet", fail_packet)

    results = settle_preflight._classify_queue(Path.cwd(), "synaptent/aragora", 10)

    assert len(results) == 1
    assert results[0].verdict == settle_preflight.HEAD_BLOCKED
    assert results[0].verdict != settle_preflight.READY
    assert any(
        settle_preflight.QUEUE_POLICY_METADATA_REASON in reason for reason in results[0].reasons
    )


def test_queue_policy_exclusion_uses_policy_file_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: ({9001: _light_metadata()}, {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_live_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_pr_policy_metadata",
        lambda *_args, **_kwargs: (
            _metadata(files=[{"path": ".github/workflows/build.yml"}]),
            {},
        ),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_required_checks",
        lambda *_args, **_kwargs: (_required_checks(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "_load_single_pr_packet",
        lambda **_kwargs: _packet(),
    )

    results = settle_preflight._classify_queue(Path.cwd(), None, 50)

    assert len(results) == 1
    assert results[0].verdict == settle_preflight.HUMAN_GATED
    assert settle_preflight.settle_one_pr.SURFACE_EXCLUDE_REASON in results[0].reasons


def test_policy_metadata_failure_exits_nonzero_and_parks(monkeypatch, capsys) -> None:
    monkeypatch.setattr(settle_preflight, "_load_active_owner_scope", lambda *_args: (set(), None))
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: ({9001: _light_metadata()}, {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_live_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_pr_policy_metadata",
        lambda *_args, **_kwargs: (
            {},
            {"returncode": 1, "stderr": "gh pr view failed"},
        ),
    )

    def fail_packet(*_args, **_kwargs):
        raise AssertionError("preflight should not load packet without policy files")

    monkeypatch.setattr(settle_preflight.settle_one_pr, "_load_single_pr_packet", fail_packet)

    rc = settle_preflight.main(["--queue", "--json"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["verdict"] == settle_preflight.HEAD_BLOCKED
    assert any(
        settle_preflight.POLICY_METADATA_REASON in reason
        for reason in payload["results"][0]["reasons"]
    )


def test_open_queue_metadata_failure_exits_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(settle_preflight, "_load_active_owner_scope", lambda *_args: (set(), None))
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: (
            {},
            {"returncode": 1, "stderr": "gh pr list failed"},
        ),
    )

    rc = settle_preflight.main(["--queue", "--json"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["verdict"] == settle_preflight.HEAD_BLOCKED
    assert any(
        settle_preflight.OPEN_QUEUE_METADATA_REASON in reason
        for reason in payload["results"][0]["reasons"]
    )


def test_queue_and_single_pr_modes_share_classification_path(monkeypatch) -> None:
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_open_pr_metadata",
        lambda *_args, **_kwargs: ({9001: _light_metadata()}, {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_live_metadata",
        lambda *_args, **_kwargs: (_blocked_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "load_pr_policy_metadata",
        lambda *_args, **_kwargs: (_metadata(), {}),
    )
    monkeypatch.setattr(
        settle_preflight,
        "_load_required_checks",
        lambda *_args, **_kwargs: (_required_checks(), {}),
    )
    monkeypatch.setattr(
        settle_preflight.settle_one_pr,
        "_load_single_pr_packet",
        lambda *_args, **_kwargs: _packet(),
    )

    single = settle_preflight._classify_single(Path.cwd(), 9001, None)
    queue = settle_preflight._classify_queue(Path.cwd(), None, 50)[0]

    assert queue.to_dict() == single.to_dict()
