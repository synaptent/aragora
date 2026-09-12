from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.settle_one_pr as settle_one_pr
from scripts.settle_one_pr import (
    CONVERGENCE_SENTENCE,
    build_report,
    entry_blockers,
    head_blockers,
    load_broad_packet_lazily,
    load_open_pr_metadata,
    no_candidate_diagnostics,
    no_candidate_next_action,
    owner_blockers,
    policy_exclusion_reasons,
    recursive_prompt,
    required_check_report,
    required_check_source_report,
    select_candidate,
)

SURFACE_REASON = (
    "security/auth/RBAC/secrets/deploy/workflow/legal/compliance/destructive/"
    "migration/public-API surface"
)
MERGE_PACKET_PREFIX = [
    settle_one_pr.PYTHON_EXECUTABLE,
    "-m",
    "aragora.cli.main",
    "review-queue",
    "merge-packet",
]
OPERATOR_SNAPSHOT_PREFIX = [
    settle_one_pr.PYTHON_EXECUTABLE,
    "scripts/agent_bridge.py",
    "operator-snapshot",
]
OWNER_PREFIX = [settle_one_pr.PYTHON_EXECUTABLE, "scripts/identify_lane_owner.py", "--pr"]
STEERING_PREFIX = [settle_one_pr.PYTHON_EXECUTABLE, "scripts/read_operator_steering.py", "--pr"]


def test_pr_policy_fields_include_live_draft_state() -> None:
    assert "isDraft" in settle_one_pr.PR_POLICY_FIELDS.split(",")


def _entry(
    pr_number: int,
    *,
    tier: int = 2,
    status: str = "needs_model_review_quorum",
    verdict: str = "collect_model_quorum_before_merge",
    admin_squash_allowed: bool = False,
    requires_human_risk_settlement: bool = False,
    checks_summary: str = "10/10 green",
    reasons: list[str] | None = None,
) -> dict:
    return {
        "pr_number": pr_number,
        "title": f"PR {pr_number}",
        "head_sha": f"{pr_number:040d}",
        "checks_summary": checks_summary,
        "tier": tier,
        "status": status,
        "verdict": verdict,
        "admin_squash_allowed": admin_squash_allowed,
        "requires_human_risk_settlement": requires_human_risk_settlement,
        "unresolved_dissent": False,
        "reviewer_signals": [],
        "dogfood_evidence": [],
        "counted_reviewer_ids": [],
        "reasons": reasons or ["live automation surface", "model quorum incomplete: 0/2 signal(s)"],
    }


def _packet(*entries: dict, admin_order: list[int] | None = None) -> dict:
    return {
        "entries": list(entries),
        "admin_squash_order": admin_order or [],
        "not_ready": [entry["pr_number"] for entry in entries],
        "human_risk_settlement_required": [
            entry["pr_number"] for entry in entries if entry["requires_human_risk_settlement"]
        ],
    }


def test_run_reports_timeout_and_terminates_process_group(monkeypatch) -> None:
    killed: list[tuple[int, int]] = []

    class SlowProc:
        pid = 4242
        returncode = None

        def __init__(self) -> None:
            self.communicate_calls = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd=["slow"],
                    timeout=timeout if timeout is not None else 0.0,
                )
            self.returncode = -9
            return "", ""

        def kill(self) -> None:
            self.returncode = -9

    proc = SlowProc()

    def fake_popen(*args, **kwargs):
        assert args[0] == ["slow"]
        assert kwargs["start_new_session"] is True
        return proc

    monkeypatch.setattr(settle_one_pr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        settle_one_pr.os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    result = settle_one_pr._run(["slow"], cwd=Path.cwd(), timeout=7)

    assert result["returncode"] == 124
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == 7
    assert "timed out after 7s" in result["stderr"]
    assert killed == [(4242, settle_one_pr.signal.SIGKILL)]


def test_run_reports_process_start_failure(monkeypatch) -> None:
    def fake_popen(*args, **kwargs):
        assert args[0] == ["missing-helper"]
        assert kwargs["start_new_session"] is True
        raise FileNotFoundError("missing-helper")

    monkeypatch.setattr(settle_one_pr.subprocess, "Popen", fake_popen)

    result = settle_one_pr._run(["missing-helper"], cwd=Path.cwd(), timeout=7)

    assert result["returncode"] == 127
    assert result["start_failed"] is True
    assert result["stdout"] == ""
    assert "command failed to start" in result["stderr"]
    assert "missing-helper" in result["stderr"]


def test_load_single_pr_packet_uses_current_interpreter(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        return _packet(_entry(8185)), {"command": "packet", "returncode": 0}

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = settle_one_pr._load_single_pr_packet(cwd=Path.cwd(), pr=8185, repo=None)

    assert packet["entries"][0]["pr_number"] == 8185
    assert commands[0][:5] == [
        sys.executable,
        "-m",
        "aragora.cli.main",
        "review-queue",
        "merge-packet",
    ]


def test_load_single_pr_packet_summarizes_transport_envelope(monkeypatch) -> None:
    packet_error = {
        "status": "transport_blocked",
        "transport_blocked": True,
        "error_kind": "github_transport",
        "error": "gh pr view 7841 failed: GraphQL: API rate limit already exceeded",
    }

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del args, cwd, timeout
        return None, {
            "command": "packet",
            "returncode": 1,
            "stdout": json.dumps(packet_error),
            "stderr": "",
        }

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    try:
        settle_one_pr._load_single_pr_packet(cwd=Path.cwd(), pr=7841, repo=None)
    except RuntimeError as exc:
        message = str(exc)
    else:  # pragma: no cover - the assertion below is clearer than pytest.raises here.
        raise AssertionError("expected RuntimeError")

    assert message == (
        "merge-packet transport blocked: "
        "gh pr view 7841 failed: GraphQL: API rate limit already exceeded"
    )
    assert "transport_blocked" not in message


def test_select_candidate_prefers_admin_order() -> None:
    unauthorized = _entry(1001)
    authorized = _entry(
        1002,
        status="satisfied",
        verdict="admin_squash_allowed",
        admin_squash_allowed=True,
        reasons=["bounded internal code surface"],
    )

    selected, blockers = select_candidate(_packet(unauthorized, authorized, admin_order=[1002]))

    assert blockers == []
    assert selected is authorized


def test_select_candidate_reports_no_eligible_pr() -> None:
    selected, blockers = select_candidate(
        _packet(
            _entry(
                1003,
                tier=4,
                requires_human_risk_settlement=True,
                reasons=["workflow/deploy/destructive surface touched"],
            )
        )
    )

    assert selected is None
    assert blockers == ["no Tier 0-2 non-human-risk green PR needs only settlement evidence"]


def test_no_candidate_diagnostics_names_next_check_blocked_pr() -> None:
    packet = _packet(
        _entry(
            1003,
            checks_summary="5/6 green; pending: aragora-merge-quorum",
            reasons=["live automation surface", "model quorum incomplete: 0/2 signal(s)"],
        ),
        _entry(
            1004,
            tier=4,
            requires_human_risk_settlement=True,
            reasons=["workflow/deploy/destructive surface touched"],
        ),
    )
    diagnostics = no_candidate_diagnostics(
        packet,
        policy_exclusions=[
            {
                "pr_number": 1004,
                "title": "PR 1004",
                "head_sha": "sha1004",
                "reasons": ["Tier 4", "requires_human_risk_settlement=true"],
            }
        ],
    )

    assert diagnostics["packet_entry_count"] == 2
    assert diagnostics["policy_exclusion_reason_counts"] == {
        "Tier 4": 1,
        "requires_human_risk_settlement=true": 1,
    }
    assert diagnostics["top_check_blocked_candidate"]["pr_number"] == 1003
    assert diagnostics["top_human_risk_candidate"]["pr_number"] == 1004

    action = no_candidate_next_action(diagnostics)
    assert action["kind"] == "recheck_or_clear_required_checks"
    assert action["pr_number"] == 1003
    assert "Do not merge" in action["operator_action"]


def test_no_candidate_diagnostics_prioritizes_independent_of_packet_order() -> None:
    packet = _packet(
        _entry(
            1010,
            tier=2,
            checks_summary="5/6 green; pending: aragora-merge-quorum",
            reasons=["live automation surface", "model quorum incomplete: 0/2 signal(s)"],
        ),
        _entry(
            1009,
            tier=1,
            checks_summary="5/6 green; pending: lint",
            reasons=["internal surface", "model quorum incomplete: 0/2 signal(s)"],
        ),
    )

    diagnostics = no_candidate_diagnostics(packet, policy_exclusions=[])

    assert diagnostics["top_check_blocked_candidate"]["pr_number"] == 1009


def test_select_candidate_skips_repair_first_prs() -> None:
    selected, blockers = select_candidate(
        _packet(
            {
                **_entry(1007),
                "machine_recommendation": "repair_first",
            }
        )
    )

    assert selected is None
    assert blockers == ["no Tier 0-2 non-human-risk green PR needs only settlement evidence"]


def test_select_candidate_excludes_adc_and_continues() -> None:
    adc = _entry(7376, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
    next_entry = _entry(
        7450, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )

    selected, blockers, exclusions = select_candidate(
        _packet(adc, next_entry),
        policy_metadata={7376: {"title": "docs(governance): ADC follow-on deepening packet"}},
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is next_entry
    assert exclusions[0]["pr_number"] == 7376
    assert exclusions[0]["reasons"] == ["ADC PR"]


def test_select_candidate_excludes_draft_and_continues() -> None:
    draft = _entry(7449, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
    next_entry = _entry(
        7450, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )

    selected, blockers, exclusions = select_candidate(
        _packet(draft, next_entry),
        policy_metadata={7449: {"isDraft": True}},
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is next_entry
    assert exclusions[0]["pr_number"] == 7449
    assert exclusions[0]["reasons"] == ["draft PR"]


def test_live_not_draft_metadata_overrides_stale_packet_draft() -> None:
    stale_draft = {
        **_entry(
            7449,
            tier=0,
            reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"],
        ),
        "isDraft": True,
    }

    selected, blockers, exclusions = select_candidate(
        _packet(stale_draft),
        policy_metadata={7449: {"isDraft": False}},
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is stale_draft
    assert exclusions == []


def test_select_candidate_excludes_active_owned_and_dependabot() -> None:
    active = _entry(7460, tier=0, reasons=["docs/tests/status-only"])
    dependabot = _entry(7300, tier=1, reasons=["docs/tests/status-only"])
    next_entry = _entry(
        7450, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )

    selected, blockers, exclusions = select_candidate(
        _packet(active, dependabot, next_entry),
        active_owned_prs={7460},
        policy_metadata={7300: {"author": {"login": "dependabot[bot]"}}},
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is next_entry
    assert [item["pr_number"] for item in exclusions] == [7460, 7300]
    assert exclusions[0]["reasons"] == ["active-owned lane"]
    assert exclusions[1]["reasons"] == ["Dependabot PR"]


def test_policy_exclusion_reasons_uses_reliable_dependabot_signals() -> None:
    human_entry = _entry(
        7301,
        tier=0,
        reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"],
    )

    assert (
        policy_exclusion_reasons(
            human_entry,
            policy_metadata={
                7301: {
                    "author": {"login": "human-maintainer"},
                    "headRefName": "codex/docs-dependabot-mention",
                    "title": "docs: explain dependabot/ branch handling",
                }
            },
        )
        == []
    )

    dependabot_entry = _entry(
        7302,
        tier=0,
        reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"],
    )

    assert policy_exclusion_reasons(
        dependabot_entry,
        policy_metadata={
            7302: {
                "author": {"login": "human-maintainer"},
                "headRefName": "dependabot/npm_and_yarn/qs-6.15.2",
            }
        },
    ) == ["Dependabot PR"]


def test_select_candidate_excludes_dirty_and_continues() -> None:
    dirty = _entry(7408, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
    next_entry = _entry(
        7450, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )

    selected, blockers, exclusions = select_candidate(
        _packet(dirty, next_entry),
        policy_metadata={7408: {"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY"}},
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is next_entry
    assert exclusions[0]["pr_number"] == 7408
    assert exclusions[0]["reasons"] == ["dirty/conflicting PR"]


def test_select_candidate_excludes_plural_workflow_and_migration_paths() -> None:
    workflow = _entry(
        7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )
    migration = _entry(
        7452, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )
    next_entry = _entry(
        7453, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )

    selected, blockers, exclusions = select_candidate(
        _packet(workflow, migration, next_entry),
        policy_metadata={
            7451: {"files": [{"path": ".github/workflows/ci.yml"}]},
            7452: {"files": [{"path": "db/migrations/001.sql"}]},
        },
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is next_entry
    assert [item["pr_number"] for item in exclusions] == [7451, 7452]
    assert all(item["reasons"] == [SURFACE_REASON] for item in exclusions)


def test_select_candidate_excludes_auth_variants_and_public_api_paths() -> None:
    authn = _entry(7454, tier=0, reasons=["docs/tests/status-only"])
    authz = _entry(7455, tier=0, reasons=["docs/tests/status-only"])
    oauth = _entry(7456, tier=0, reasons=["docs/tests/status-only"])
    public_api = _entry(7457, tier=0, reasons=["docs/tests/status-only"])
    next_entry = _entry(
        7458, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
    )

    selected, blockers, exclusions = select_candidate(
        _packet(authn, authz, oauth, public_api, next_entry),
        policy_metadata={
            7454: {"files": [{"path": "aragora/authentication/providers.py"}]},
            7455: {"files": [{"path": "authorization/policies.py"}]},
            7456: {"files": [{"path": "oauth/providers.py"}]},
            7457: {"files": [{"path": "public/api/routes.py"}]},
        },
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is next_entry
    assert [item["pr_number"] for item in exclusions] == [7454, 7455, 7456, 7457]
    assert all(item["reasons"] == [SURFACE_REASON] for item in exclusions)


def test_select_candidate_does_not_treat_authored_text_as_auth_surface() -> None:
    authored = {
        **_entry(7459, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]),
        "title": "docs: Authored by queue steward",
    }

    selected, blockers, exclusions = select_candidate(
        _packet(authored),
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is authored
    assert exclusions == []


def test_policy_exclusion_reasons_does_not_flag_plain_unsafe_words_in_docs() -> None:
    docs = _entry(
        7460,
        tier=0,
        reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"],
    )

    reasons = policy_exclusion_reasons(
        docs,
        policy_metadata={
            7460: {
                "title": "docs(compliance): clarify legal disclaimer for destructive cleanup",
                "headRefName": "codex/legal-disclaimer-docs",
                "files": [{"path": "README.md"}, {"path": "docs/status/cleanup.md"}],
            }
        },
    )

    assert reasons == []


def test_policy_exclusion_reasons_allows_docs_site_generated_secrets_deploy_docs() -> None:
    docs = _entry(
        7485,
        tier=0,
        reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"],
    )

    reasons = policy_exclusion_reasons(
        docs,
        policy_metadata={
            7485: {
                "title": "docs: refresh generated deployment status",
                "headRefName": "codex/docs-site-status-refresh",
                "files": [
                    {"path": "docs-site/docs/contributing/b0-benchmark-truth-status.md"},
                    {"path": "docs-site/docs/deployment/secrets-management.md"},
                    {"path": "docs-site/docs/getting-started/environment.md"},
                    {"path": "docs-site/docs/operations/overview.md"},
                    {"path": "docs/FOCUS.md"},
                    {"path": "docs/status/B0_BENCHMARK_TRUTH_STATUS.md"},
                ],
            }
        },
    )

    assert reasons == []


def test_policy_exclusion_reasons_scopes_adc_to_title_and_branch() -> None:
    entry = _entry(
        7461,
        tier=0,
        reasons=["docs/tests/status-only", "downstream classifier mentioned adc token"],
    )

    reasons = policy_exclusion_reasons(
        entry,
        policy_metadata={
            7461: {
                "title": "docs: explain bridge glossary",
                "headRefName": "codex/docs-glossary",
                "files": [{"path": "docs/adc/glossary.md"}],
            }
        },
    )

    assert reasons == []


def test_policy_exclusion_reasons_reports_file_path_only_unsafe_surface() -> None:
    entry = _entry(7461, tier=0, reasons=["docs/tests/status-only"])

    reasons = policy_exclusion_reasons(
        entry,
        policy_metadata={7461: {"files": [{"path": "public/api/routes.py"}]}},
    )

    assert reasons == [SURFACE_REASON]


def test_policy_exclusion_reasons_reports_common_unsafe_path_variants() -> None:
    unsafe_paths = [
        "aragora/auth_helpers/providers.py",
        "aragora/security_utils.py",
        "aragora/secrets_manager.py",
        "infra/secrets-prod.yaml",
        "infra/deploy-prod.yaml",
        "scripts/migrate_users.py",
    ]

    for index, path in enumerate(unsafe_paths, start=7463):
        reasons = policy_exclusion_reasons(
            _entry(index, tier=0, reasons=["docs/tests/status-only"]),
            policy_metadata={index: {"files": [{"path": path}]}},
        )
        assert reasons == [SURFACE_REASON], path


def test_policy_exclusion_reasons_does_not_overmatch_auth_or_workflow_words() -> None:
    harmless_paths = [
        "aragora/authoring/foo.py",
        "authors.py",
        "authority_check.py",
        "tests/authoring_test.py",
        "aragora/workflow/orchestrator.py",
        "tests/fixtures/migrations/sample.py",
    ]

    for index, path in enumerate(harmless_paths, start=7470):
        reasons = policy_exclusion_reasons(
            _entry(index, tier=0, reasons=["docs/tests/status-only"]),
            policy_metadata={index: {"files": [{"path": path}]}},
        )
        assert reasons == [], path


def test_explicit_pr_policy_exclusion_surfaces_in_blockers_and_exclusions() -> None:
    report = build_report(
        _packet(_entry(7462)),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=7462,
        exclude_prs={7462},
        live=False,
        validate=False,
    )

    assert report["selected_pr"] == 7462
    assert report["policy_exclusions"] == [
        {
            "pr_number": 7462,
            "title": "PR 7462",
            "head_sha": "0000000000000000000000000000000000007462",
            "reasons": ["explicitly excluded by steward scope"],
        }
    ]
    assert "excluded_by_policy: explicitly excluded by steward scope" in report["blockers"]


def test_open_pr_metadata_uses_light_list_fields(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        return [], {"command": "metadata", "returncode": 0}

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    metadata, command = load_open_pr_metadata(Path.cwd(), limit=100)

    assert metadata == {}
    assert command["returncode"] == 0
    fields = commands[0][commands[0].index("--json") + 1]
    assert "files" not in fields
    assert "statusCheckRollup" not in fields


def test_broad_packet_lazy_loader_uses_single_bulk_packet(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        if args[:5] == MERGE_PACKET_PREFIX:
            assert "--limit" in args
            assert "--pr" not in args
            return _packet(_entry(7376), _entry(7449)), {"command": "packet", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert [entry["pr_number"] for entry in packet["entries"]] == [7376, 7449]
    assert len(commands) == 1


def test_broad_packet_lazy_loader_falls_back_when_bulk_packet_fails(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    bulk_calls = 0

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        nonlocal bulk_calls
        del cwd, timeout
        commands.append(args)
        if args[:5] == MERGE_PACKET_PREFIX:
            if "--limit" in args:
                bulk_calls += 1
                return None, {"command": "bulk-packet", "returncode": 1, "stderr": "HTTP 504"}
            pr_number = int(args[args.index("--pr") + 1])
            return _packet(_entry(pr_number)), {"command": "packet", "returncode": 0}
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7376,
                        "title": "docs(governance): ADC follow-on deepening packet",
                        "headRefName": "adc-follow-on",
                    },
                    {
                        "number": 7449,
                        "title": "fix(settlement): exclude unsafe PR surfaces",
                        "headRefName": "codex/settle-one-policy-exclusions-20260523",
                    },
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert [entry["pr_number"] for entry in packet["entries"]] == [7449]
    assert packet["load_warnings"] == ["bulk merge-packet failed; using fallback: HTTP 504"]
    assert bulk_calls == 1
    targeted = [command for command in commands if "--pr" in command]
    assert len(targeted) == 1
    assert targeted[0][targeted[0].index("--pr") + 1] == "7449"


def test_broad_packet_lazy_loader_falls_back_when_bulk_packet_times_out(
    monkeypatch,
) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:5] == MERGE_PACKET_PREFIX:
            if "--limit" in args:
                return None, {
                    "command": "bulk-packet",
                    "returncode": 124,
                    "stderr": "command timed out after 90s and was terminated",
                    "timed_out": True,
                }
            pr_number = int(args[args.index("--pr") + 1])
            return _packet(_entry(pr_number)), {"command": "packet", "returncode": 0}
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7449,
                        "title": "fix(settlement): exclude unsafe PR surfaces",
                        "headRefName": "codex/settle-one-policy-exclusions-20260523",
                    },
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert [entry["pr_number"] for entry in packet["entries"]] == [7449]
    assert packet["load_warnings"] == [
        "bulk merge-packet failed; using fallback: command timed out after 90s and was terminated"
    ]


def test_broad_packet_lazy_loader_returns_empty_when_bulk_and_light_metadata_fail(
    monkeypatch,
) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:5] == MERGE_PACKET_PREFIX:
            return None, {"command": "bulk-packet", "returncode": 1, "stderr": "HTTP 504"}
        if args[:3] == ["gh", "pr", "list"]:
            return None, {"command": "metadata", "returncode": 1, "stderr": "HTTP 504"}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert packet["entries"] == []
    assert packet["load_blockers"] == ["HTTP 504", "HTTP 504"]


def test_broad_packet_lazy_loader_surfaces_targeted_packet_failures(
    monkeypatch,
) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:5] == MERGE_PACKET_PREFIX:
            if "--limit" in args:
                return None, {"command": "bulk-packet", "returncode": 1, "stderr": "HTTP 504"}
            pr_number = args[args.index("--pr") + 1]
            return None, {
                "command": f"packet {pr_number}",
                "returncode": 1,
                "stderr": "GraphQL timeout",
            }
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7449,
                        "title": "fix(settlement): exclude unsafe PR surfaces",
                        "headRefName": "codex/settle-one-policy-exclusions-20260523",
                    },
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert packet["entries"] == []
    assert packet["load_warnings"] == ["bulk merge-packet failed; using fallback: HTTP 504"]
    assert packet["load_blockers"] == ["merge-packet for #7449 failed: GraphQL timeout"]


def test_broad_packet_lazy_loader_surfaces_targeted_packet_timeout(
    monkeypatch,
) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:5] == MERGE_PACKET_PREFIX:
            if "--limit" in args:
                return None, {"command": "bulk-packet", "returncode": 1, "stderr": "HTTP 504"}
            return None, {
                "command": "packet",
                "returncode": 124,
                "stderr": "command timed out after 90s and was terminated",
                "timed_out": True,
            }
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7449,
                        "title": "fix(settlement): exclude unsafe PR surfaces",
                        "headRefName": "codex/settle-one-policy-exclusions-20260523",
                    },
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert packet["entries"] == []
    assert packet["load_warnings"] == ["bulk merge-packet failed; using fallback: HTTP 504"]
    assert packet["load_blockers"] == [
        "merge-packet for #7449 failed: command timed out after 90s and was terminated"
    ]


def test_broad_packet_lazy_loader_warns_on_large_fallback_fanout(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:5] == MERGE_PACKET_PREFIX:
            if "--limit" in args:
                return None, {"command": "bulk-packet", "returncode": 1, "stderr": "HTTP 504"}
            pr_number = int(args[args.index("--pr") + 1])
            return (
                _packet(
                    _entry(
                        pr_number,
                        checks_summary="1/2 failing",
                        reasons=["docs/tests/status-only"],
                    )
                ),
                {"command": "packet", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {"number": number, "title": f"fix {number}", "headRefName": f"codex/{number}"}
                    for number in range(7449, 7460)
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert any(
        warning.startswith("fallback per-PR merge-packet queries:")
        for warning in packet["load_warnings"]
    )


def test_combine_packets_preserves_source_packet_timestamps(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:5] == MERGE_PACKET_PREFIX:
            if "--limit" in args:
                return None, {"command": "bulk-packet", "returncode": 1, "stderr": "HTTP 504"}
            pr_number = int(args[args.index("--pr") + 1])
            packet = _packet(_entry(pr_number))
            packet["generated_at"] = f"packet-{pr_number}-generated-at"
            return packet, {"command": "packet", "returncode": 0}
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {"number": 7449, "title": "fix(settlement)", "headRefName": "codex/settle"},
                    {"number": 7450, "title": "fix(next)", "headRefName": "codex/next"},
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = load_broad_packet_lazily(cwd=Path.cwd(), limit=100, repo=None)

    assert packet["source_generated_at"] == [
        "packet-7449-generated-at",
        "packet-7450-generated-at",
    ]


def test_broad_selection_continues_past_excluded_candidate_from_bulk_packet() -> None:
    adc = _entry(7376, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
    candidate = _entry(
        7449,
        tier=2,
        reasons=["live automation surface", "model quorum incomplete: 0/2"],
    )

    selected, blockers, exclusions = select_candidate(
        _packet(adc, candidate),
        policy_metadata={7376: {"title": "docs(governance): ADC follow-on deepening packet"}},
        return_exclusions=True,
    )

    assert blockers == []
    assert selected is candidate
    assert exclusions[0]["pr_number"] == 7376
    assert exclusions[0]["reasons"] == ["ADC PR"]


def test_build_report_threads_repo_to_policy_metadata(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7451,
                        "title": "fix: candidate",
                        "headRefName": "codex/candidate",
                    }
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return (
                {
                    "number": 7451,
                    "title": "fix: candidate",
                    "headRefName": "codex/candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": ".github/workflows/ci.yml"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
        repo="example/repo",
    )

    assert report["selected_pr"] is None
    list_command = next(args for args in commands if args[:3] == ["gh", "pr", "list"])
    view_command = next(args for args in commands if args[:3] == ["gh", "pr", "view"])
    assert list_command[-2:] == ["--repo", "example/repo"]
    assert view_command[-2:] == ["--repo", "example/repo"]


def test_build_report_explicit_pr_loads_policy_metadata_without_broad_list(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            raise AssertionError("explicit --pr settlement must not call gh pr list")
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return (
                {
                    "number": 7451,
                    "title": "fix: candidate",
                    "headRefName": "codex/candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "aragora/server/routes.py"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                7451,
                tier=3,
                requires_human_risk_settlement=True,
                reasons=["semantic, persistence, security, API, or SDK surface touched"],
            )
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=7451,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["selected_pr"] == 7451
    assert report["status"] == "blocked"
    assert commands[0][:3] == ["gh", "pr", "view"]
    assert all(command[:3] != ["gh", "pr", "list"] for command in commands)


def test_build_report_bounds_policy_command_output(monkeypatch) -> None:
    large_stdout = "stdout-line\n" * 1200
    large_stderr = "stderr-line\n" * 900

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return (
                {
                    "number": 7451,
                    "title": "fix: candidate",
                    "headRefName": "codex/candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "aragora/server/routes.py"}],
                },
                {
                    "command": "policy-view",
                    "returncode": 0,
                    "stdout": large_stdout,
                    "stderr": large_stderr,
                },
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return (
                {"lanes": []},
                {
                    "command": "snapshot",
                    "returncode": 0,
                    "stdout": large_stdout,
                    "stderr": large_stderr,
                },
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                7451,
                tier=3,
                requires_human_risk_settlement=True,
                reasons=["semantic, persistence, security, API, or SDK surface touched"],
            )
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=7451,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    policy_context = report["policy_context"]
    command_reports = [
        policy_context["operator_snapshot_command"],
        policy_context["policy_metadata_commands"][0],
    ]
    limit = getattr(settle_one_pr, "COMMAND_OUTPUT_REPORT_LIMIT", 4096)
    for command_report in command_reports:
        assert command_report["stdout_length"] == len(large_stdout)
        assert command_report["stderr_length"] == len(large_stderr)
        assert command_report["stdout_truncated"] is True
        assert command_report["stderr_truncated"] is True
        assert len(command_report["stdout"]) <= limit + 128
        assert len(command_report["stderr"]) <= limit + 128
        assert command_report["stdout"] != large_stdout
        assert command_report["stderr"] != large_stderr


def test_build_report_fails_closed_when_operator_snapshot_fails(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [{"number": 7451, "title": "fix: candidate", "headRefName": "codex/candidate"}],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return None, {"command": "snapshot", "returncode": 1, "stderr": "snapshot failed"}
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return (
                {
                    "number": 7451,
                    "title": "fix: candidate",
                    "headRefName": "codex/candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "scripts/settle_one_pr.py"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["status"] == "blocked"
    assert any(
        blocker.startswith(
            "operator-snapshot unavailable; active-owned exclusions cannot be trusted"
        )
        for blocker in report["blockers"]
    )


def test_build_report_does_not_reload_snapshot_when_packet_already_failed_closed(
    monkeypatch,
) -> None:
    snapshot_called = False
    blocker = "operator-snapshot unavailable; active-owned exclusions cannot be trusted: outage"

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        nonlocal snapshot_called
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return [], {"command": "metadata", "returncode": 0}
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            snapshot_called = True
            return None, {"command": "snapshot", "returncode": 1, "stderr": "outage"}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    packet = _packet()
    packet["load_blockers"] = [blocker]
    report = build_report(
        packet,
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert snapshot_called is False
    assert report["blockers"].count(blocker) == 1


def test_build_report_blocks_repo_mismatch_when_repo_override_supplied(monkeypatch) -> None:
    snapshot_called = False

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        nonlocal snapshot_called
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [{"number": 7451, "title": "fix: candidate", "headRefName": "codex/candidate"}],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            snapshot_called = True
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return (
                {
                    "number": 7451,
                    "title": "fix: candidate",
                    "headRefName": "codex/candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "scripts/settle_one_pr.py"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        raise AssertionError(args)

    def fake_run(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args == ["git", "remote", "get-url", "origin"]:
            return {
                "command": "git remote get-url origin",
                "returncode": 0,
                "stdout": "git@github.com:synaptent/aragora.git",
                "stderr": "",
            }
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)
    monkeypatch.setattr(settle_one_pr, "_run", fake_run)

    report = build_report(
        _packet(
            _entry(7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
        repo="other/repo",
    )

    assert report["status"] == "blocked"
    assert "--repo other/repo does not match cwd origin synaptent/aragora" in report["blockers"]
    assert snapshot_called is False


def test_lazy_policy_metadata_continues_past_failed_pr_view(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {"number": 7451, "title": "fix: flaky", "headRefName": "codex/flaky"},
                    {"number": 7452, "title": "fix: next", "headRefName": "codex/next"},
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return None, {"command": "policy-view-7451", "returncode": 1, "stderr": "timeout"}
        if args[:2] == ["gh", "api"] and args[2] == "repos/{owner}/{repo}/pulls/7451":
            return None, {"command": "pull-rest-7451", "returncode": 404, "stderr": "not found"}
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "7452"
            and "statusCheckRollup" in args[5]
        ):
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000007452",
                    "baseRefName": "main",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "aragora-merge-quorum",
                            "conclusion": "SUCCESS",
                        }
                    ],
                },
                {"command": "view-7452", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7452":
            return (
                {
                    "number": 7452,
                    "title": "fix: next",
                    "headRefName": "codex/next",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "scripts/settle_one_pr.py"}],
                },
                {"command": "policy-view-7452", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return (
                {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
                {"command": "protection", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return (
                {
                    "check_runs": [
                        {
                            "name": "aragora-merge-quorum",
                            "conclusion": "success",
                            "app": {"id": 15368},
                        }
                    ]
                },
                {"command": "check-runs", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return (
                [],
                {"command": "checks", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
            ),
            _entry(
                7452, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
            ),
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["selected_pr"] == 7452
    assert report["status"] == "ready_for_minimum_evidence"
    assert report["policy_exclusions"][0]["pr_number"] == 7451
    assert report["policy_exclusions"][0]["reasons"] == [
        "selected-candidate policy metadata unavailable"
    ]


def test_explicit_pr_reuses_preloaded_policy_file_scope(monkeypatch) -> None:
    policy_view_calls = 0

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        nonlocal policy_view_calls
        del cwd, timeout
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "7451"
            and args[5] == settle_one_pr.PR_POLICY_FIELDS
        ):
            policy_view_calls += 1
            if policy_view_calls > 1:
                return None, {
                    "command": "policy-view-7451",
                    "returncode": 1,
                    "stderr": "error connecting to api.github.com",
                }
            return (
                {
                    "number": 7451,
                    "title": "docs: candidate",
                    "headRefName": "codex/docs-candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "docs/status/example.md"}],
                },
                {"command": "policy-view-7451", "returncode": 0},
            )
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "7451"
            and "statusCheckRollup" in args[5]
        ):
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000007451",
                    "baseRefName": "main",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "aragora-merge-quorum",
                            "conclusion": "SUCCESS",
                        }
                    ],
                },
                {"command": "view-7451", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return (
                {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
                {"command": "protection", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return (
                {
                    "check_runs": [
                        {
                            "name": "aragora-merge-quorum",
                            "conclusion": "success",
                            "app": {"id": 15368},
                        }
                    ]
                },
                {"command": "check-runs", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return (
                [],
                {"command": "checks", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"]
            ),
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=7451,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert policy_view_calls == 1
    assert report["selected_pr"] == 7451
    assert report["status"] == "ready_for_minimum_evidence"
    assert report["policy_exclusions"] == []


def test_pr_policy_metadata_uses_rest_fallback_when_graphql_unavailable(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return None, {
                "command": "policy-view-7451",
                "returncode": 1,
                "stderr": "GraphQL: API rate limit already exceeded",
            }
        if args[:2] == ["gh", "api"] and args[2] == "repos/{owner}/{repo}/pulls/7451":
            return (
                {
                    "number": 7451,
                    "title": "docs: candidate",
                    "head": {"ref": "codex/docs-candidate"},
                    "draft": False,
                    "user": {"login": "alice"},
                    "mergeable": True,
                    "mergeable_state": "clean",
                },
                {"command": "pull-rest", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2] == "repos/{owner}/{repo}/pulls/7451/files":
            return (
                [{"filename": "docs/status/example.md", "additions": 2, "deletions": 1}],
                {"command": "files-rest", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    metadata, command = settle_one_pr.load_pr_policy_metadata(Path.cwd(), 7451)

    assert metadata == {
        "number": 7451,
        "title": "docs: candidate",
        "headRefName": "codex/docs-candidate",
        "isDraft": False,
        "author": {"login": "alice"},
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "files": [
            {
                "path": "docs/status/example.md",
                "additions": 2,
                "deletions": 1,
                "changeType": None,
            }
        ],
        "metadata_source": "rest_pull_files",
    }
    assert command["rest_fallback"] is True
    assert command["primary_command"]["returncode"] == 1
    assert command["fallback_reason"] == "GraphQL: API rate limit already exceeded"


def test_build_report_fails_closed_when_selected_policy_metadata_unavailable(
    monkeypatch,
) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7451,
                        "title": "fix: candidate",
                        "headRefName": "codex/candidate",
                    }
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return None, {"command": "policy-view", "returncode": 1, "stderr": "timeout"}
        if args[:2] == ["gh", "api"] and args[2] == "repos/{owner}/{repo}/pulls/7451":
            return None, {"command": "pull-rest", "returncode": 404, "stderr": "not found"}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["selected_pr"] is None
    assert report["blockers"] == ["selected-candidate policy metadata unavailable"]


def test_build_report_lazy_loads_file_scope_for_selected_candidate(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            return (
                [
                    {
                        "number": 7451,
                        "title": "fix: candidate",
                        "headRefName": "codex/candidate",
                    }
                ],
                {"command": "metadata", "returncode": 0},
            )
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"] and args[3] == "7451":
            return (
                {
                    "number": 7451,
                    "title": "fix: candidate",
                    "headRefName": "codex/candidate",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": ".github/workflows/ci.yml"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(7451, tier=0, reasons=["docs/tests/status-only", "model quorum incomplete: 0/1"])
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["selected_pr"] is None
    assert report["status"] == "no_candidate"
    assert report["policy_exclusions"][0]["pr_number"] == 7451
    assert report["policy_exclusions"][0]["reasons"] == [SURFACE_REASON]
    list_fields = commands[0][commands[0].index("--json") + 1]
    assert "files" not in list_fields
    assert any(args[:3] == ["gh", "pr", "view"] and args[3] == "7451" for args in commands)


def test_tier3_or_human_risk_is_report_only() -> None:
    blockers = entry_blockers(
        _entry(
            1004,
            tier=3,
            requires_human_risk_settlement=True,
            reasons=["semantic, persistence, security, API, or SDK surface touched"],
        )
    )

    assert "Tier 3 requires report-only handling" in blockers
    assert "requires_human_risk_settlement=true" in blockers


def test_entry_blockers_use_effective_required_checks_gate() -> None:
    entry = _entry(
        1005,
        status="satisfied",
        verdict="admin_squash_allowed",
        admin_squash_allowed=True,
        reasons=["bounded helper reliability surface"],
        checks_summary="2 pending / 21 total",
    )
    entry["check_surfaces"] = {
        "effective_gate": {
            "source": "required_pr_checks",
            "summary": "6/6 required green (required PR checks)",
        },
        "required_pr_checks": {
            "available": True,
            "gate_selected": True,
            "summary": "6/6 required green",
            "pending": [],
            "failing_or_cancelled": [],
        },
    }

    blockers = entry_blockers(entry)

    assert blockers == []


def test_owner_payload_blocks_active_owner() -> None:
    blockers = owner_blockers(
        {
            "owner": {
                "lane_id": "Q99-live-owner",
                "status": "active",
            }
        }
    )

    assert blockers == ["active owner Q99-live-owner"]


def test_head_drift_blocks_settlement() -> None:
    blockers = head_blockers(
        {"head_sha": "expected"},
        {
            "headRefOid": "actual",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
        },
    )

    assert blockers == ["head drift: packet expected live actual"]


def test_missing_evidence_yields_ready_for_minimum_evidence() -> None:
    report = build_report(
        _packet(_entry(1005)),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=1005,
        exclude_prs=set(),
        live=False,
        validate=False,
    )

    assert report["status"] == "ready_for_minimum_evidence"
    assert "model quorum incomplete: 0/2 signal(s)" in report["evidence"]["missing_model_quorum"]
    assert report["recursive_best_next_prompt"].endswith(CONVERGENCE_SENTENCE)


def test_no_candidate_report_includes_actionable_diagnostics() -> None:
    report = build_report(
        _packet(
            _entry(
                1006,
                checks_summary="5/6 green; pending: aragora-merge-quorum",
                reasons=["live automation surface", "model quorum incomplete: 0/2 signal(s)"],
            )
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=None,
        exclude_prs=set(),
        live=False,
        validate=False,
    )

    assert report["status"] == "no_candidate"
    assert report["candidate_diagnostics"]["top_check_blocked_candidate"]["pr_number"] == 1006
    assert report["next_bounded_action"]["kind"] == "recheck_or_clear_required_checks"
    assert report["suggested_commands"] == [report["next_bounded_action"]["operator_action"]]
    assert "Then: Re-check PR #1006" in report["recursive_best_next_prompt"]
    assert report["recursive_best_next_prompt"].endswith(CONVERGENCE_SENTENCE)


def test_cancelled_merge_quorum_suggests_rerun() -> None:
    report = required_check_report(
        [
            {
                "name": "aragora-merge-quorum",
                "workflow": "Aragora Merge Quorum",
                "state": "CANCELLED",
                "link": "https://github.com/synaptent/aragora/actions/runs/123456789",
            },
            {"name": "lint", "state": "SUCCESS"},
        ]
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == ["aragora-merge-quorum is cancelled"]
    assert report["suggestions"] == ["gh run rerun 123456789 --failed"]


def test_app_pinned_required_check_blocks_manual_status_spoof() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "StatusContext",
                    "context": "aragora-merge-quorum",
                    "state": "SUCCESS",
                }
            ]
        },
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == [
        "aragora-merge-quorum is app-pinned to app_id 15368, but only a manual "
        "StatusContext is green"
    ]
    assert report["suggestions"] == [
        "rerun the app-sourced aragora-merge-quorum check; do not satisfy it with a manual status"
    ]


def test_app_pinned_required_check_accepts_successful_check_run() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "StatusContext",
                    "context": "aragora-merge-quorum",
                    "state": "SUCCESS",
                },
                {
                    "__typename": "CheckRun",
                    "name": "aragora-merge-quorum",
                    "conclusion": "SUCCESS",
                    "workflowName": "Aragora Merge Quorum",
                    "checkSuite": {"app": {"databaseId": 15368}},
                },
            ]
        },
    )

    assert report == {"status": "pass", "blockers": [], "suggestions": []}


def test_app_pinned_required_check_blocks_wrong_app_check_run() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "aragora-merge-quorum",
                    "conclusion": "SUCCESS",
                    "checkSuite": {"app": {"databaseId": 42}},
                }
            ]
        },
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == [
        "aragora-merge-quorum is app-pinned to app_id 15368, but successful "
        "CheckRun app_id(s) were [42]"
    ]
    assert report["suggestions"] == ["rerun the app-sourced aragora-merge-quorum check"]


def test_app_pinned_required_check_blocks_unverified_check_run_source() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "aragora-merge-quorum",
                    "conclusion": "SUCCESS",
                }
            ]
        },
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == [
        "aragora-merge-quorum is app-pinned to app_id 15368, but CheckRun "
        "source app could not be verified"
    ]
    assert report["suggestions"] == ["fetch commit check-runs with app metadata before settlement"]


def test_app_pinned_required_check_accepts_rest_check_run_source() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
        {"statusCheckRollup": []},
        {
            "check_runs": [
                {
                    "name": "aragora-merge-quorum",
                    "status": "completed",
                    "conclusion": "success",
                    "app": {"id": 15368, "slug": "github-actions"},
                }
            ]
        },
    )

    assert report == {"status": "pass", "blockers": [], "suggestions": []}


def test_app_pinned_required_check_treats_neutral_check_run_as_passing() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "aragora-merge-quorum",
                    "conclusion": "NEUTRAL",
                    "checkSuite": {"app": {"databaseId": 15368}},
                }
            ]
        },
    )

    assert report == {"status": "pass", "blockers": [], "suggestions": []}


def test_unpinned_null_required_check_allows_status_context() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "legacy-status", "app_id": None}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "StatusContext",
                    "context": "legacy-status",
                    "state": "SUCCESS",
                }
            ]
        },
    )

    assert report == {"status": "pass", "blockers": [], "suggestions": []}


def test_unpinned_any_source_required_check_allows_status_context() -> None:
    report = required_check_source_report(
        {"checks": [{"context": "legacy-status", "app_id": -1}]},
        {
            "statusCheckRollup": [
                {
                    "__typename": "StatusContext",
                    "context": "legacy-status",
                    "state": "SUCCESS",
                }
            ]
        },
    )

    assert report == {"status": "pass", "blockers": [], "suggestions": []}


def test_required_check_source_report_fails_closed_without_protection_json() -> None:
    report = required_check_source_report(
        None,
        {"statusCheckRollup": []},
    )

    assert report["status"] == "unknown"
    assert report["blockers"] == ["branch protection required_status_checks JSON unavailable"]
    assert report["suggestions"] == [
        "ensure gh can read branch protection required_status_checks before settlement"
    ]


def test_required_check_source_report_falls_back_to_required_checks_and_check_runs() -> None:
    report = required_check_source_report(
        None,
        {"statusCheckRollup": []},
        {
            "check_runs": [
                {
                    "name": "aragora-merge-quorum",
                    "conclusion": "success",
                    "app": {"id": 15368, "slug": "github-actions"},
                }
            ]
        },
        [{"name": "aragora-merge-quorum", "state": "SUCCESS"}],
    )

    assert report == {"status": "pass", "blockers": [], "suggestions": []}


def test_required_check_source_report_fallback_blocks_empty_required_checks() -> None:
    report = required_check_source_report(
        None,
        {"statusCheckRollup": []},
        {
            "check_runs": [
                {
                    "name": "aragora-merge-quorum",
                    "conclusion": "success",
                    "app": {"id": 15368, "slug": "github-actions"},
                }
            ]
        },
        [],
    )

    assert report["status"] == "unknown"
    assert report["blockers"] == ["required checks JSON empty"]


def test_required_check_source_report_fallback_blocks_non_green_required_check() -> None:
    report = required_check_source_report(
        None,
        {"statusCheckRollup": []},
        {
            "check_runs": [
                {
                    "name": "aragora-merge-quorum",
                    "conclusion": "success",
                    "app": {"id": 15368, "slug": "github-actions"},
                }
            ]
        },
        [{"name": "aragora-merge-quorum", "state": "FAILURE"}],
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == ["aragora-merge-quorum is FAILURE"]


def test_required_check_source_report_fallback_blocks_status_only_required_check() -> None:
    report = required_check_source_report(
        None,
        {
            "statusCheckRollup": [
                {
                    "__typename": "StatusContext",
                    "context": "aragora-merge-quorum",
                    "state": "SUCCESS",
                }
            ]
        },
        {"check_runs": []},
        [{"name": "aragora-merge-quorum", "state": "SUCCESS"}],
    )

    assert report["status"] == "blocked"
    assert report["blockers"] == [
        "aragora-merge-quorum lacks a matching successful exact-head GitHub Actions CheckRun"
    ]


def test_build_report_blocks_merge_suggestion_for_current_head_park_record() -> None:
    entry = _entry(
        9005,
        tier=0,
        status="satisfied",
        verdict="admin_squash_allowed",
        admin_squash_allowed=True,
        reasons=["docs-only change"],
    )
    entry["park_record"] = {
        "blocked": True,
        "head_sha": entry["head_sha"],
        "park_marker": "Current-head repeat-blocker park",
        "created_at": "2026-07-08T05:20:08Z",
        "comment_url": "https://github.example/comment/park",
        "reason": "Do not merge this PR on this head.",
    }

    report = build_report(
        _packet(entry, admin_order=[9005]),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=9005,
        exclude_prs=set(),
        live=False,
        validate=False,
    )

    assert report["status"] == "blocked"
    assert report["suggested_commands"] == []
    assert any("current-head park record present" in blocker for blocker in report["blockers"])


def test_build_report_reads_required_checks_from_pr_base_branch(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            return [], {"command": "metadata", "returncode": 0}
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"]:
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000001008",
                    "baseRefName": "release/2026.05",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "aragora-merge-quorum",
                            "conclusion": "SUCCESS",
                        }
                    ],
                },
                {"command": "view", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return (
                {"checks": [{"context": "aragora-merge-quorum", "app_id": 15368}]},
                {"command": "protection", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return (
                {
                    "check_runs": [
                        {
                            "name": "aragora-merge-quorum",
                            "conclusion": "success",
                            "app": {"id": 15368},
                        }
                    ]
                },
                {"command": "check-runs", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return [], {"command": "checks", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                1008,
                status="satisfied",
                verdict="admin_squash_allowed",
                admin_squash_allowed=True,
                reasons=["bounded internal code surface"],
            ),
            admin_order=[1008],
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=1008,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["status"] == "packet_authorized_dry_run"
    assert any(
        cmd[:2] == ["gh", "api"]
        and cmd[2]
        == "repos/{owner}/{repo}/branches/release%2F2026.05/protection/required_status_checks"
        for cmd in commands
    )


def test_build_report_fails_closed_when_required_check_sources_unreadable(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return [], {"command": "metadata", "returncode": 0}
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"]:
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000001009",
                    "baseRefName": "main",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "aragora-merge-quorum",
                            "conclusion": "SUCCESS",
                        }
                    ],
                },
                {"command": "view", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return None, {"command": "protection", "returncode": 403}
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return {"check_runs": []}, {"command": "check-runs", "returncode": 0}
        if args[:3] == ["gh", "pr", "checks"]:
            return (
                [{"name": "aragora-merge-quorum", "state": "SUCCESS"}],
                {"command": "checks", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                1009,
                status="satisfied",
                verdict="admin_squash_allowed",
                admin_squash_allowed=True,
                reasons=["bounded internal code surface"],
            ),
            admin_order=[1009],
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=1009,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["status"] == "blocked"
    assert (
        "aragora-merge-quorum lacks a matching successful exact-head GitHub Actions CheckRun"
        in report["blockers"]
    )


def test_build_report_falls_back_when_required_checks_and_check_runs_are_green(
    monkeypatch,
) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return [], {"command": "metadata", "returncode": 0}
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if args[:3] == ["gh", "pr", "view"]:
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000001010",
                    "baseRefName": "main",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                },
                {"command": "view", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return None, {"command": "protection", "returncode": 404}
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return (
                {
                    "check_runs": [
                        {
                            "name": "aragora-merge-quorum",
                            "conclusion": "success",
                            "app": {"id": 15368, "slug": "github-actions"},
                        }
                    ]
                },
                {"command": "check-runs", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return (
                [{"name": "aragora-merge-quorum", "state": "SUCCESS"}],
                {"command": "checks", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    report = build_report(
        _packet(
            _entry(
                1010,
                status="satisfied",
                verdict="admin_squash_allowed",
                admin_squash_allowed=True,
                reasons=["bounded internal code surface"],
            ),
            admin_order=[1010],
        ),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=1010,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["status"] == "packet_authorized_dry_run"


def test_build_report_uses_packet_required_check_metadata_when_app_token_cannot_read_protection(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        commands.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            return [], {"command": "metadata", "returncode": 0}
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "8372"
            and args[5] == settle_one_pr.PR_POLICY_FIELDS
        ):
            return (
                {
                    "number": 8372,
                    "title": "docs: ODR mission",
                    "headRefName": "claude/odr-completion-mission",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "docs/superpowers/plans/odr.md"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "8372"
            and "statusCheckRollup" in args[5]
        ):
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000008372",
                    "baseRefName": "main",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                },
                {"command": "view", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return None, {
                "command": "protection",
                "returncode": 403,
                "stderr": "Resource not accessible by integration",
            }
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return (
                {
                    "check_runs": [
                        {
                            "name": "aragora-merge-quorum",
                            "conclusion": "success",
                            "app": {"id": 15368},
                        }
                    ]
                },
                {"command": "check-runs", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return (
                [{"name": "aragora-merge-quorum", "state": "SUCCESS"}],
                {"command": "checks", "returncode": 0},
            )
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    entry = _entry(
        8372,
        status="satisfied",
        verdict="admin_squash_allowed",
        admin_squash_allowed=True,
        reasons=["bounded internal code surface"],
    )
    entry["check_surfaces"] = {
        "direct_commit_check_runs": {
            "required_contexts_satisfied": True,
            "non_success_required_contexts": [],
            "required_checks": [{"context": "aragora-merge-quorum", "app_id": 15368}],
        }
    }
    report = build_report(
        _packet(entry, admin_order=[8372]),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=8372,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["status"] == "packet_authorized_dry_run"
    assert report["blockers"] == []
    assert report["checks"]["required_source_fallback"] == {
        "used": True,
        "source": "merge_packet_direct_commit_check_runs.required_checks",
        "reason": "Resource not accessible by integration",
        "contexts": ["aragora-merge-quorum"],
    }
    assert report["checks"]["required_sources"]["source"] == (
        "merge_packet_direct_commit_check_runs.required_checks"
    )
    assert any(
        cmd[:2] == ["gh", "api"] and cmd[2].endswith("/required_status_checks") for cmd in commands
    )


def test_build_report_still_fails_closed_when_required_contexts_are_unknown(monkeypatch) -> None:
    def fake_run_json(args: list[str], *, cwd: Path, timeout: int = 120):
        del cwd, timeout
        if args[:3] == ["gh", "pr", "list"]:
            return [], {"command": "metadata", "returncode": 0}
        if args[:3] == OPERATOR_SNAPSHOT_PREFIX:
            return {"lanes": []}, {"command": "snapshot", "returncode": 0}
        if args[:3] == OWNER_PREFIX:
            return {"status": "completed"}, {"command": "owner", "returncode": 0}
        if args[:3] == STEERING_PREFIX:
            return {"message_count": 0}, {"command": "mailbox", "returncode": 0}
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "8373"
            and args[5] == settle_one_pr.PR_POLICY_FIELDS
        ):
            return (
                {
                    "number": 8373,
                    "title": "docs: unknown required contexts",
                    "headRefName": "codex/docs",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "files": [{"path": "docs/status/example.md"}],
                },
                {"command": "policy-view", "returncode": 0},
            )
        if (
            args[:3] == ["gh", "pr", "view"]
            and args[3] == "8373"
            and "statusCheckRollup" in args[5]
        ):
            return (
                {
                    "headRefOid": "0000000000000000000000000000000000008373",
                    "baseRefName": "main",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                },
                {"command": "view", "returncode": 0},
            )
        if args[:2] == ["gh", "api"] and args[2].endswith("/required_status_checks"):
            return None, {"command": "protection", "returncode": 403}
        if args[:2] == ["gh", "api"] and args[2].endswith("/check-runs?per_page=100"):
            return (
                {
                    "check_runs": [
                        {
                            "name": "aragora-merge-quorum",
                            "conclusion": "success",
                            "app": {"id": 15368},
                        }
                    ]
                },
                {"command": "check-runs", "returncode": 0},
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return [], {"command": "checks", "returncode": 0}
        raise AssertionError(args)

    monkeypatch.setattr(settle_one_pr, "_run_json", fake_run_json)

    entry = _entry(
        8373,
        status="satisfied",
        verdict="admin_squash_allowed",
        admin_squash_allowed=True,
        reasons=["bounded internal code surface"],
    )
    entry["check_surfaces"] = {
        "direct_commit_check_runs": {
            "required_contexts_satisfied": True,
            "non_success_required_contexts": [],
            "required_checks": [],
        }
    }
    report = build_report(
        _packet(entry, admin_order=[8373]),
        cwd=Path.cwd(),
        state_root=Path.cwd(),
        explicit_pr=8373,
        exclude_prs=set(),
        live=True,
        validate=False,
    )

    assert report["status"] == "blocked"
    assert "required checks JSON empty" in report["blockers"]
    assert "required_source_fallback" not in report["checks"]


def test_recursive_prompt_always_contains_convergence_sentence() -> None:
    assert recursive_prompt({"selected_pr": None}).endswith(CONVERGENCE_SENTENCE)
    assert recursive_prompt({"selected_pr": 1006}).endswith(CONVERGENCE_SENTENCE)
