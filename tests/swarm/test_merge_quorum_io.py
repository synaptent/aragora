"""Tests for I/O helpers in aragora.swarm.merge_quorum_io.

Focused on ``fetch_pr_tier``, which must read the tier from the per-PR rows
under the merge-packet ``entries`` envelope (not the top-level object).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from aragora.swarm import merge_quorum_io as m


def _proc(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr="")


_OLDER = "2026-08-17T10:00:00Z"
_NEWER = "2026-08-17T11:00:00Z"


def _rest_context_stub(
    head: str,
    pr: int,
    check_runs: list[dict],
    required: list[str] | None,
    *,
    rules: object = None,
):
    def fake(args, *, env=None, timeout=m._GH_TIMEOUT):
        if args[1:3] == ["pr", "view"]:
            raise RuntimeError("GraphQL unavailable")
        endpoint = args[-1]
        if endpoint == f"repos/o/r/pulls/{pr}":
            return {
                "state": "open",
                "draft": False,
                "mergeable": True,
                "mergeable_state": "blocked",
                "head": {"sha": head},
                "base": {"ref": "main"},
            }
        if endpoint == f"repos/o/r/commits/{head}":
            return {"commit": {"committer": {"date": "2026-08-17T12:00:00Z"}}}
        if "/check-runs" in endpoint:
            return {"check_runs": check_runs}
        if "/statuses" in endpoint:
            return []
        if endpoint.endswith("branches/main/protection/required_status_checks"):
            if required is None:
                raise RuntimeError("403")
            return {"contexts": required, "checks": []}
        if "rules/branches/main" in endpoint:
            if isinstance(rules, Exception):
                raise rules
            return [] if rules is None else rules
        raise AssertionError(args)

    return fake


def test_read_env_prefers_app_installation_token(monkeypatch) -> None:
    from aragora.swarm import github_app_auth

    monkeypatch.setattr(
        github_app_auth, "get_github_app_installation_token", lambda env=None: "fake-app-token"
    )
    env = m._read_env()
    assert env["GH_TOKEN"] == "fake-app-token"
    assert env["GITHUB_TOKEN"] == "fake-app-token"
    assert env["ARAGORA_GITHUB_AUTH_SOURCE"] == "github_app_installation"


def test_read_env_degrades_to_ambient_auth_without_app_config(monkeypatch) -> None:
    from aragora.swarm import github_app_auth

    # No App config -> mint returns None -> read env carries no App-source tag, so
    # gh falls back to the operator's ambient auth instead of crashing.
    monkeypatch.setattr(github_app_auth, "get_github_app_installation_token", lambda env=None: None)
    env = m._read_env()
    assert env.get("ARAGORA_GITHUB_AUTH_SOURCE") != "github_app_installation"


def test_fetch_pr_context_routes_reads_through_app_token(monkeypatch) -> None:
    from aragora.swarm import github_app_auth

    monkeypatch.setattr(
        github_app_auth, "get_github_app_installation_token", lambda env=None: "fake-app-token"
    )
    captured_envs: list[dict] = []

    def capture_run(args, *, env=None, timeout=m._GH_TIMEOUT):
        captured_envs.append(env or {})
        payload = [] if args[1:3] == ["pr", "checks"] else {"headRefOid": "abc"}
        return _proc(json.dumps(payload))

    monkeypatch.setattr(m, "run", capture_run)
    m.fetch_pr_context("o/r", 1)
    assert captured_envs, "expected fetch_pr_context to shell out to gh"
    assert captured_envs[0].get("GH_TOKEN") == "fake-app-token"
    assert captured_envs[0].get("ARAGORA_GITHUB_AUTH_SOURCE") == "github_app_installation"


def test_fetch_pr_context_uses_required_check_surface_not_raw_rollup(monkeypatch) -> None:
    view = {
        "headRefOid": "abc",
        "commits": [{"oid": "abc", "committedDate": "2026-08-17T12:00:00Z"}],
        "statusCheckRollup": [
            {"name": m.QUORUM_CHECK_NAME, "conclusion": "FAILURE", "startedAt": _NEWER},
            {"name": "non-required historical job", "conclusion": "FAILURE"},
            {"name": m.QUORUM_CHECK_NAME, "conclusion": "SUCCESS", "startedAt": _OLDER},
        ],
        "isDraft": False,
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "BLOCKED",
    }
    required = [
        {"name": "lint", "state": "SUCCESS", "bucket": "pass"},
        {"name": m.QUORUM_CHECK_NAME, "state": "FAILURE", "bucket": "fail"},
    ]

    def fake_run(args, *, env=None, timeout=m._GH_TIMEOUT):
        if args[1:3] == ["pr", "view"]:
            return _proc(json.dumps(view))
        if args[1:3] == ["pr", "checks"]:
            return _proc(json.dumps(required))
        raise AssertionError(args)

    monkeypatch.setattr(m, "run", fake_run)

    context = m.fetch_pr_context("o/r", 1)

    assert context["quorum_conclusion"] == "FAILURE"
    assert context["has_real_required_failure"] is False
    assert context["has_real_required_pending"] is False


def test_fetch_pr_context_falls_back_to_rest_with_complete_stability_state(monkeypatch) -> None:
    head = "a" * 40
    runs = [
        {"name": m.QUORUM_CHECK_NAME, "conclusion": "failure"},
        {"name": "lint", "conclusion": "success", "completed_at": _OLDER},
        {"name": "lint", "conclusion": "failure", "completed_at": _NEWER},
        {"name": "typecheck", "conclusion": "success", "started_at": _OLDER},
        {"name": "typecheck", "status": "in_progress", "started_at": _NEWER},
    ]
    monkeypatch.setattr(
        m,
        "run_json",
        _rest_context_stub(head, 7, runs, [m.QUORUM_CHECK_NAME, "lint", "typecheck"]),
    )

    context = m.fetch_pr_context("o/r", 7)

    assert context["context_source"] == "rest"
    assert context["head_sha"] == head
    assert context["head_committed_at"] == "2026-08-17T12:00:00Z"
    assert context["pr_state"] == "OPEN"
    assert context["is_draft"] is False
    assert context["mergeable"] == "MERGEABLE"
    assert context["merge_state_status"] == "BLOCKED"
    assert context["quorum_conclusion"] == "FAILURE"
    assert context["has_real_required_failure"] is True
    assert context["has_real_required_pending"] is True
    assert context["required_checks_disclosed"] is True
    assert "GraphQL unavailable" in context["graphql_error"]


def test_fetch_pr_context_rest_fails_closed_when_required_set_unavailable(monkeypatch) -> None:
    head = "b" * 40
    runs = [
        {"name": "optional integration", "conclusion": "failure"},
        {"name": "preview shadow", "conclusion": "failure"},
    ]
    monkeypatch.setattr(m, "run_json", _rest_context_stub(head, 8, runs, None))
    context = m.fetch_pr_context("o/r", 8)
    assert context["required_checks_disclosed"] is False
    assert context["has_real_required_failure"] is True


def test_fetch_pr_context_reports_graphql_and_rest_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        m,
        "run_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("service unavailable")),
    )

    with pytest.raises(RuntimeError, match="GraphQL.*or REST"):
        m.fetch_pr_context("o/r", 9)


def test_summarize_checks_required_state_and_newest_status() -> None:
    assert m._summarize_checks([], required_names={"lint"}) == ("", False, True)
    assert m._summarize_checks(
        [{"name": "lint", "conclusion": "new-provider-state"}],
        required_names={"lint"},
    ) == ("", False, True)
    assert m._summarize_checks(
        [{"name": "lint", "conclusion": "success"}, {"context": "types", "state": "success"}],
        required_names={"lint", "types"},
    ) == ("", False, False)
    assert m._summarize_checks(
        [
            {"context": "lint", "state": "failure", "updated_at": _OLDER},
            {"context": "lint", "state": "success", "updated_at": _NEWER},
        ],
        required_names={"lint"},
    ) == ("", False, False)


def test_summarize_checks_missing_or_tied_ordering_fails_closed() -> None:
    cases = (
        [
            {"name": "lint", "conclusion": "success"},
            {"name": "lint", "conclusion": "failure"},
        ],
        [
            {"name": "lint", "conclusion": "success", "startedAt": _OLDER},
            {"name": "lint", "conclusion": "failure", "startedAt": _OLDER},
        ],
    )
    for rows in cases:
        assert m._summarize_checks(rows, required_names={"lint"}) == ("", False, True)


def test_required_check_names_unions_classic_and_ruleset_requirements(monkeypatch) -> None:
    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        endpoint = args[-1]
        if "/protection/required_status_checks" in endpoint:
            return {"contexts": ["lint"], "checks": [{"context": "types", "app_id": 1}]}
        if "/rules/branches/" in endpoint:
            return [
                {"type": "non_fast_forward"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "ruleset-only", "integration_id": 1},
                            {"name": "named-requirement"},
                        ]
                    },
                },
            ]
        raise AssertionError(args)

    monkeypatch.setattr(m, "run_json", fake_run_json)
    names = m._required_check_names("o/r", "release/2026-08-17", env={})
    assert names == {"lint", "types", "ruleset-only", "named-requirement"}


def test_required_check_names_accepts_ruleset_only_requirements(monkeypatch) -> None:
    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        if "/protection/required_status_checks" in args[-1]:
            return {"contexts": [], "checks": []}
        return [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "ruleset-only"}]},
            }
        ]

    monkeypatch.setattr(m, "run_json", fake_run_json)
    assert m._required_check_names("o/r", "main", env={}) == {"ruleset-only"}


@pytest.mark.parametrize(
    ("check_runs", "has_failure", "has_pending"),
    [
        ([{"name": "ruleset-only", "conclusion": "failure"}], True, False),
        ([], False, True),
    ],
)
def test_fetch_pr_context_rest_blocks_failed_or_missing_ruleset_requirement(
    monkeypatch, check_runs, has_failure, has_pending
) -> None:
    head = "c" * 40
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "ruleset-only"}]},
        }
    ]
    monkeypatch.setattr(
        m,
        "run_json",
        _rest_context_stub(head, 10, check_runs, [], rules=rules),
    )

    context = m.fetch_pr_context("o/r", 10)

    assert context["required_checks_disclosed"] is True
    assert context["has_real_required_failure"] is has_failure
    assert context["has_real_required_pending"] is has_pending


@pytest.mark.parametrize(
    "rules",
    [
        RuntimeError("403"),
        {"unexpected": "object"},
        ["not-a-rule"],
        [{"ruleset_id": 1}],
        [{"type": "required_status_checks"}],
        [{"type": "required_status_checks", "parameters": {}}],
        [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": "lint"},
            }
        ],
        [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{}]},
            }
        ],
        [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": " lint"}]},
            }
        ],
        [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "lint", "name": "types"}]},
            }
        ],
    ],
)
def test_required_check_names_fails_closed_on_unavailable_or_malformed_rules(
    monkeypatch, rules
) -> None:
    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        if "/protection/required_status_checks" in args[-1]:
            return {"contexts": ["lint"], "checks": []}
        if isinstance(rules, Exception):
            raise rules
        return rules

    monkeypatch.setattr(m, "run_json", fake_run_json)
    assert m._required_check_names("o/r", "main", env={}) is None


@pytest.mark.parametrize(
    "classic",
    [None, {}, {"contexts": "lint", "checks": []}, {"contexts": [], "checks": [{}]}],
)
def test_required_check_names_fails_closed_on_malformed_classic_policy(
    monkeypatch, classic
) -> None:
    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        return classic if "/protection/required_status_checks" in args[-1] else []

    monkeypatch.setattr(m, "run_json", fake_run_json)
    assert m._required_check_names("o/r", "main", env={}) is None


def test_required_check_names_accepts_applied_rules_without_status_checks(monkeypatch) -> None:
    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        if "/protection/required_status_checks" in args[-1]:
            return {"contexts": ["lint"], "checks": []}
        return [{"type": "non_fast_forward"}, {"type": "deletion"}]

    monkeypatch.setattr(m, "run_json", fake_run_json)
    assert m._required_check_names("o/r", "main", env={}) == {"lint"}


def test_required_check_names_fails_closed_when_classic_protection_unavailable(
    monkeypatch,
) -> None:
    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        if "/protection/required_status_checks" in args[-1]:
            raise RuntimeError("404")
        return [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "ruleset-only"}]},
            }
        ]

    monkeypatch.setattr(m, "run_json", fake_run_json)
    assert m._required_check_names("o/r", "main", env={}) is None


def test_applied_branch_rules_reads_every_page(monkeypatch) -> None:
    pages: list[int] = []

    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        page = int(args[-1].rsplit("page=", 1)[-1])
        pages.append(page)
        return [{"type": "deletion"}] * 100 if page == 1 else [{"type": "non_fast_forward"}]

    monkeypatch.setattr(m, "run_json", fake_run_json)
    assert len(m._applied_branch_rules("o/r", "main", env={})) == 101
    assert pages == [1, 2]


def test_required_check_names_retries_complete_policy_with_ambient_operator_auth(
    monkeypatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def fake_run_json(args, *, env=None, timeout=m._GH_TIMEOUT):
        token = str((env or {}).get("GH_TOKEN") or "")
        endpoint = args[-1]
        surface = "rules" if "/rules/branches/" in endpoint else "classic"
        seen.append((token, surface))
        if token == "app-token" and surface == "rules":
            raise RuntimeError("403 Resource not accessible by integration")
        if surface == "classic":
            return {"contexts": ["lint"], "checks": []}
        return [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "types"}]},
            }
        ]

    monkeypatch.setattr(m, "run_json", fake_run_json)
    monkeypatch.setattr(m, "aragora_env", lambda: {"GH_TOKEN": "operator-token"})
    names = m._required_check_names("o/r", "release/2026-08-17", env={"GH_TOKEN": "app-token"})
    assert names == {"lint", "types"}
    assert seen == [
        ("app-token", "classic"),
        ("app-token", "rules"),
        ("operator-token", "classic"),
        ("operator-token", "rules"),
    ]


def test_fetch_pr_tier_reads_nested_entries(monkeypatch) -> None:
    payload = {
        "version": "merge_authorization_packet.v1",
        "entries": [{"pr_number": 7742, "tier": 4, "tier_name": "tier_4_preapproval_required"}],
    }
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(payload)))
    assert m.fetch_pr_tier("o/r", 7742) == 4


def test_fetch_merge_packet_classification_reads_semantic_fields(monkeypatch) -> None:
    payload = {
        "version": "merge_authorization_packet.v1",
        "entries": [
            {
                "pr_number": 7754,
                "head_sha": "abc123",
                "tier": 2,
                "status": "repair_or_wait",
                "verdict": "not_ready_for_settlement",
                "requires_human_risk_settlement": False,
            }
        ],
    }
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(payload)))

    packet = m.fetch_merge_packet_classification("o/r", 7754)

    assert packet is not None
    assert packet.pr_number == 7754
    assert packet.head_sha == "abc123"
    assert packet.tier == 2
    assert packet.status == "repair_or_wait"
    assert packet.verdict == "not_ready_for_settlement"
    assert packet.requires_human_risk_settlement is False


def test_fetch_quorum_run_packet_classification_parses_log(monkeypatch) -> None:
    log = (
        "PR #7754 | Tier 4 | status=human_preapproval_required | "
        "verdict=tier_4_human_preapproval_required\n"
    )
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(log))

    packet = m.fetch_quorum_run_packet_classification("o/r", run_id=123, pr=7754, head_sha="abc123")

    assert packet is not None
    assert packet.source == "ci"
    assert packet.tier == 4
    assert packet.requires_human_risk_settlement is True


def test_fetch_pr_tier_filters_by_pr_number(monkeypatch) -> None:
    # A multi-PR envelope must resolve the requested PR, never the first row.
    payload = {"entries": [{"pr_number": 111, "tier": 1}, {"pr_number": 7742, "tier": 4}]}
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(payload)))
    assert m.fetch_pr_tier("o/r", 7742) == 4
    assert m.fetch_pr_tier("o/r", 111) == 1


def test_fetch_pr_tier_coerces_string_pr_number(monkeypatch) -> None:
    payload = {"entries": [{"pr_number": "7742", "tier": "4"}]}
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(payload)))
    assert m.fetch_pr_tier("o/r", 7742) == 4


def test_fetch_pr_tier_none_when_pr_number_absent_from_envelope(monkeypatch) -> None:
    # Rows disclose pr_number but none match the request -> no wrong-PR fallback.
    payload = {"entries": [{"pr_number": 111, "tier": 1}]}
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(payload)))
    assert m.fetch_pr_tier("o/r", 999) is None


def test_fetch_pr_tier_accepts_bare_list(monkeypatch) -> None:
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps([{"tier": 2}])))
    assert m.fetch_pr_tier("o/r", 1) == 2


def test_fetch_pr_tier_accepts_single_entry_dict(monkeypatch) -> None:
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps({"tier": 1})))
    assert m.fetch_pr_tier("o/r", 1) == 1


def test_fetch_pr_tier_none_when_no_tier(monkeypatch) -> None:
    monkeypatch.setattr(
        m, "run", lambda *a, **k: _proc(json.dumps({"entries": [{"pr_number": 1}]}))
    )
    assert m.fetch_pr_tier("o/r", 1) is None


def test_fetch_pr_tier_none_on_bad_json(monkeypatch) -> None:
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc("not json"))
    assert m.fetch_pr_tier("o/r", 1) is None


def test_fetch_pr_tier_none_on_nonzero(monkeypatch) -> None:
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc("", returncode=1))
    assert m.fetch_pr_tier("o/r", 1) is None


def test_fetch_pr_tier_none_on_timeout(monkeypatch) -> None:
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=1)

    monkeypatch.setattr(m, "run", _boom)
    assert m.fetch_pr_tier("o/r", 1) is None


# --- lint_comment: infra failures are explicit and retried once, never {} ---


_LINT_ARGS = (9073, "a" * 40, "2026-07-09T22:44:49Z", "an0mium", "## body", {})


def test_lint_comment_timeout_returns_explicit_infra_failure(monkeypatch) -> None:
    calls = []

    def _boom(*a, **k):
        calls.append(1)
        raise subprocess.TimeoutExpired(cmd="lint", timeout=1)

    monkeypatch.setattr(m, "run", _boom)
    lint = m.lint_comment(*_LINT_ARGS)
    assert lint["would_count"] is False
    assert lint["counted_reviewer_ids"] == []
    assert len(lint["problems"]) == 1
    assert lint["problems"][0].startswith("evidence_lint_infra_failure:")
    assert len(calls) == 1 + m._EVIDENCE_LINT_INFRA_RETRIES  # retried, then explicit


def test_lint_comment_retries_infra_failure_then_returns_parsed_result(monkeypatch) -> None:
    calls = []
    good = {"would_count": True, "problems": [], "counted_reviewer_ids": ["claude"]}

    def _flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return _proc("", returncode=1)
        return _proc(json.dumps(good))

    monkeypatch.setattr(m, "run", _flaky)
    assert m.lint_comment(*_LINT_ARGS) == good
    assert len(calls) == 2


def test_lint_comment_never_retries_a_parsed_rejection(monkeypatch) -> None:
    calls = []
    rejection = {"would_count": False, "problems": ["blocking_or_negative_verdict"]}

    def _reject(*a, **k):
        calls.append(1)
        return _proc(json.dumps(rejection))

    monkeypatch.setattr(m, "run", _reject)
    assert m.lint_comment(*_LINT_ARGS) == rejection
    assert len(calls) == 1  # a substantive rejection is final, never retried


def test_lint_comment_bad_json_returns_explicit_infra_failure(monkeypatch) -> None:
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc("not json"))
    lint = m.lint_comment(*_LINT_ARGS)
    assert lint["would_count"] is False
    assert lint["problems"] == [
        "evidence_lint_infra_failure: evidence-lint emitted undecodable JSON"
    ]


def test_lint_comment_enforces_reason_invariant_on_parsed_rejection(monkeypatch) -> None:
    """would_count == False must ALWAYS carry a reason: a parsed rejection with
    an empty problems list would still render as 'DOES NOT count ()'."""
    bare = {"would_count": False, "problems": [], "counted_reviewer_ids": []}
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(bare)))
    lint = m.lint_comment(*_LINT_ARGS)
    assert lint["would_count"] is False
    assert lint["problems"] == ["evidence_lint_rejection_without_reason"]


def test_lint_comment_reason_invariant_leaves_counting_results_alone(monkeypatch) -> None:
    counting = {"would_count": True, "problems": [], "counted_reviewer_ids": ["claude"]}
    monkeypatch.setattr(m, "run", lambda *a, **k: _proc(json.dumps(counting)))
    assert m.lint_comment(*_LINT_ARGS) == counting


def test_lint_comment_exit1_with_json_is_a_verdict_not_infra_failure(monkeypatch) -> None:
    """The evidence-lint CLI exits 1 BY DESIGN on substantive rejections while
    printing the parsed JSON (review_queue: 'return 0 if would_count else 1').
    The exit code must never be treated as a health signal (#9129 claude P1)."""
    calls = []
    rejection = {"would_count": False, "problems": ["blocking_or_negative_verdict"]}

    def _exit1(*a, **k):
        calls.append(1)
        return _proc(json.dumps(rejection), returncode=1)

    monkeypatch.setattr(m, "run", _exit1)
    assert m.lint_comment(*_LINT_ARGS) == rejection
    assert len(calls) == 1  # a verdict, even at exit 1, is final: no retry


def test_lint_comment_non_dict_json_is_infra_failure(monkeypatch) -> None:
    for payload in ("null", "[]", '"oops"'):
        monkeypatch.setattr(m, "run", lambda *a, _p=payload, **k: _proc(_p))
        lint = m.lint_comment(*_LINT_ARGS)
        assert lint["would_count"] is False
        assert lint["problems"][0].startswith(
            "evidence_lint_infra_failure: evidence-lint emitted non-dict JSON"
        )
