"""Tests for ``aragora swarm`` CLI parser and command entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.cli.commands.swarm import _classify_issue_validation_status, cmd_swarm
from aragora.swarm.initiative_models import InitiativeRecord, InitiativeSlice
from aragora.swarm.initiative_store import InitiativeStore
from aragora.swarm.spec import SwarmSpec


class _FakeSpec:
    def __init__(self, yaml_text: str = "id: test-spec\n") -> None:
        self._yaml_text = yaml_text

    def to_yaml(self) -> str:
        return self._yaml_text


def _swarm_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "swarm_action_or_goal": "run",
        "swarm_goal": None,
        "swarm_campaign_target": None,
        "spec": None,
        "skip_interrogation": False,
        "dry_run": False,
        "budget_limit": 9.0,
        "require_approval": False,
        "save_spec": None,
        "from_obsidian": None,
        "obsidian_vault": None,
        "no_obsidian_receipts": False,
        "profile": "developer",
        "autonomy": "propose",
        "max_parallel": 20,
        "no_loop": False,
        "target_branch": "main",
        "skip_publication": False,
        "contract": None,
        "concurrency_cap": 8,
        "managed_dir_pattern": ".worktrees/{agent}-auto",
        "json": False,
        "run_id": None,
        "readiness": None,
        "lane_id": None,
        "receipt_id": None,
        "lease_id": None,
        "lane_branch": None,
        "decided_by": "cli-integrator",
        "rationale": "",
        "new_pr_url": None,
        "status_limit": 20,
        "findings_limit": 10,
        "refresh_scaling": False,
        "no_dispatch": False,
        "watch": False,
        "session_id": None,
        "assigned_by": None,
        "directive_status": "active",
        "scope": None,
        "constraint": None,
        "claim_intent": None,
        "ttl_minutes": 30,
        "kind": None,
        "pr": None,
        "claude_runner_profiles": None,
        "runner_rotation_interval": 1800.0,
        "boss_max_parallel_dispatches": 1,
        "interval_seconds": 5.0,
        "max_ticks": None,
        "all_runs": False,
        "dispatch_only": False,
        "no_wait": False,
        "worker_model": "claude",
        "review_model": "codex",
        "manifest": ".aragora/campaign_manifest.yaml",
        "queue": None,
        "execute_merge": False,
        "allow_admin": False,
        "max_parallel_lanes": 1,
        "intake": None,
        "rounds": 2,
        "all_completed": False,
        "all_mergeable": False,
        "approve": False,
        "max_hours": 12.0,
        "driver": False,
        "tier": "auto",
        "from_prompts": None,
        "all_ready": False,
        "owner_agent": None,
        "owner_session_id": None,
        "skip_review": False,
        "output": None,
        "audit_ref": None,
        "source_file": None,
        "initiative_dir": None,
        "feature_flag": None,
        "dependency": None,
        "validation": None,
        "milestone": None,
        "checkpoint": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _fake_supervisor_run(
    *,
    run_id: str = "run-123",
    status: str = "active",
    work_orders: list[dict[str, object]] | None = None,
) -> MagicMock:
    fake_run = MagicMock()
    fake_run.to_dict.return_value = {
        "run_id": run_id,
        "status": status,
        "target_branch": "main",
        "goal": "goal",
        "work_orders": work_orders or [],
    }
    return fake_run


class TestSwarmParser:
    def test_swarm_registered_in_root_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "improve onboarding"])
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "improve onboarding"
        assert args.swarm_goal is None
        assert args.spec is None
        assert args.dry_run is False

    def test_swarm_parser_accepts_options(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "reduce latency",
                "--skip-interrogation",
                "--budget-limit",
                "12.5",
                "--require-approval",
                "--dry-run",
                "--save-spec",
                "swarm-spec.yaml",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "reduce latency"
        assert args.skip_interrogation is True
        assert args.budget_limit == 12.5
        assert args.require_approval is True
        assert args.dry_run is True
        assert args.save_spec == "swarm-spec.yaml"

    def test_swarm_status_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "status", "--run-id", "run-123", "--json"])
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "status"
        assert args.run_id == "run-123"
        assert args.json is True

    def test_swarm_shift_status_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "shift-status",
                "--shift-ledger",
                ".aragora/custom/shift.jsonl",
                "--max-age-hours",
                "48",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "shift-status"
        assert args.shift_ledger == ".aragora/custom/shift.jsonl"
        assert args.max_age_hours == 48.0
        assert args.json is True

    def test_swarm_preflight_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "preflight",
                "--worker-model",
                "codex",
                "--target-branch",
                "origin/main",
                "--contract",
                "/tmp/worker-contract.json",
                "--skip-publication",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "preflight"
        assert args.worker_model == "codex"
        assert args.target_branch == "origin/main"
        assert args.contract == "/tmp/worker-contract.json"
        assert args.skip_publication is True
        assert args.json is True

    def test_swarm_coord_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "coord", "--findings-limit", "5", "--json"])
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "coord"
        assert args.findings_limit == 5
        assert args.json is True

    def test_swarm_assign_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "assign",
                "codex-a",
                "SDK parity consolidation",
                "--scope",
                "#2684",
                "--constraint",
                "no queue drain",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "assign"
        assert args.swarm_goal == "codex-a"
        assert args.swarm_campaign_target == "SDK parity consolidation"
        assert args.scope == ["#2684"]
        assert args.constraint == ["no queue drain"]

    def test_swarm_claim_pr_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "claim-pr", "2684", "--session-id", "codex-a", "--ttl-minutes", "15"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "claim-pr"
        assert args.swarm_goal == "2684"
        assert args.session_id == "codex-a"
        assert args.ttl_minutes == 15

    def test_swarm_report_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "report", "Verification route bug", "--kind", "blocker", "--pr", "2677"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "report"
        assert args.swarm_goal == "Verification route bug"
        assert args.kind == "blocker"
        assert args.pr == 2677

    def test_swarm_findings_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "findings", "--kind", "blocker", "--session-id", "review-codex"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "findings"
        assert args.kind == "blocker"
        assert args.session_id == "review-codex"

    def test_swarm_reconcile_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "reconcile", "--run-id", "run-123", "--watch", "--interval-seconds", "1.5"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "reconcile"
        assert args.run_id == "run-123"
        assert args.watch is True
        assert args.interval_seconds == 1.5

    def test_swarm_initiative_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "initiative",
                "plan",
                "Create an initiative registry",
                "--feature-flag",
                "initiative_registry",
                "--dependency",
                "decision-plan-core",
                "--validation",
                "python3 -m pytest tests/swarm/test_initiative_store.py -q",
                "--milestone",
                "Planning ready",
                "--checkpoint",
                "Registry validated",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "initiative"
        assert args.swarm_goal == "plan"
        assert args.swarm_campaign_target == "Create an initiative registry"
        assert args.feature_flag == "initiative_registry"
        assert args.dependency == ["decision-plan-core"]
        assert args.validation == ["python3 -m pytest tests/swarm/test_initiative_store.py -q"]

    def test_swarm_runner_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "runner",
                "probe",
                "--runner-type",
                "claude",
                "--probe-limit",
                "2",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "runner"
        assert args.swarm_goal == "probe"
        assert args.runner_type == "claude"
        assert args.probe_limit == 2
        assert args.json is True

    def test_swarm_runner_probe_codex_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "runner",
                "probe",
                "--runner-type",
                "codex",
                "--probe-limit",
                "3",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "runner"
        assert args.swarm_goal == "probe"
        assert args.runner_type == "codex"
        assert args.probe_limit == 3
        assert args.json is True

    def test_swarm_runner_probe_codex_parser_no_json(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "runner",
                "probe",
                "--runner-type",
                "codex",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "runner"
        assert args.swarm_goal == "probe"
        assert args.runner_type == "codex"
        assert args.json is False

    def test_swarm_runner_probe_gemini_cli_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "runner",
                "probe",
                "--runner-type",
                "gemini-cli",
                "--probe-limit",
                "4",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "runner"
        assert args.swarm_goal == "probe"
        assert args.runner_type == "gemini-cli"
        assert args.probe_limit == 4
        assert args.json is True

    def test_swarm_runner_probe_gemini_cli_parser_no_json(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "runner",
                "probe",
                "--runner-type",
                "gemini-cli",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "runner"
        assert args.swarm_goal == "probe"
        assert args.runner_type == "gemini-cli"
        assert args.json is False

    def test_swarm_audit_issues_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "audit-issues",
                "--boss-repo",
                "synaptent/aragora",
                "--label",
                "boss-ready",
                "--audit-ref",
                "origin/main",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "audit-issues"
        assert args.boss_repo == "synaptent/aragora"
        assert args.labels == ["boss-ready"]
        assert args.audit_ref == "origin/main"
        assert args.json is True

    def test_swarm_boss_parser_accepts_issue_list(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "boss-loop", "--boss-issue-list", "101,102", "--worker-model", "claude"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "boss-loop"
        assert args.boss_issue_list == "101,102"
        assert args.worker_model == "claude"

    def test_swarm_boss_parser_defaults_to_claude_worker_and_codex_review(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "boss-loop"])
        assert args.worker_model == "claude"
        assert args.review_model == "codex"

    def test_swarm_boss_parser_accepts_claude_profile_pool(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "boss-loop",
                "--worker-model",
                "claude",
                "--claude-runner-profiles",
                "max-02,max-03,max-04",
                "--runner-rotation-interval",
                "900",
            ]
        )
        assert args.claude_runner_profiles == "max-02,max-03,max-04"
        assert args.runner_rotation_interval == 900.0

    def test_swarm_boss_parser_accepts_parallel_dispatch_limit(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "boss-loop",
                "--boss-max-parallel-dispatches",
                "3",
            ]
        )
        assert args.boss_max_parallel_dispatches == 3

    def test_cmd_swarm_boss_loop_full_auto_enables_postprocessing(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="boss-loop",
            autonomy="full-auto",
            json=True,
            boss_repo="synaptent/aragora",
            boss_issue_list="101",
            boss_issue_number=None,
            worker_model="claude",
            review_model="codex",
            labels=["boss-ready"],
            boss_label_filter=None,
            allow_missing_validation_contract=False,
            ping_pong=False,
            no_dispatch=False,
            claude_runner_profiles=None,
            max_consecutive_failures=3,
        )
        fake_result = SimpleNamespace(
            to_dict=lambda: {
                "mode": "boss-loop",
                "run_id": "boss-run-1",
                "iterations_completed": 1,
                "stop_reason": "max_iterations",
                "issues_attempted": [],
                "issues_completed": [],
                "issues_failed": [],
                "iteration_statuses": [],
                "needs_human_reasons": [],
                "next_actions": [],
            }
        )
        fake_loop = SimpleNamespace(run=AsyncMock(return_value=fake_result))

        with patch("aragora.swarm.boss_loop.BossLoop", return_value=fake_loop) as boss_loop_cls:
            cmd_swarm(args)

        config = boss_loop_cls.call_args.kwargs["config"]
        assert config.auto_publish_deliverables is True
        assert config.auto_close_already_done_issues is True
        assert config.auto_continue_on_needs_human is True
        assert '"mode": "boss-loop"' in capsys.readouterr().out

    def test_cmd_swarm_boss_loop_json_uses_bounded_result(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="boss-loop",
            autonomy="guided",
            json=True,
            boss_repo="synaptent/aragora",
            boss_issue_list="101",
            boss_issue_number=None,
            worker_model="claude",
            review_model="codex",
            labels=["boss-ready"],
            boss_label_filter=None,
            allow_missing_validation_contract=False,
            ping_pong=False,
            no_dispatch=False,
            claude_runner_profiles=None,
            max_consecutive_failures=3,
        )

        class _FakeBossLoopResult:
            def to_dict(self):
                raise AssertionError("raw boss-loop result should not be used for --json")

            def to_bounded_dict(self):
                return {
                    "mode": "boss-loop",
                    "run_id": "boss-run-bounded",
                    "_bounded": True,
                }

        fake_loop = SimpleNamespace(run=AsyncMock(return_value=_FakeBossLoopResult()))

        with patch("aragora.swarm.boss_loop.BossLoop", return_value=fake_loop):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"run_id": "boss-run-bounded"' in out
        assert '"_bounded": true' in out

    def test_cmd_swarm_preflight_routes_to_module_without_contract(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="preflight",
            worker_model="codex",
            target_branch="origin/main",
            contract=None,
            skip_publication=True,
            json=True,
        )
        fake_result = SimpleNamespace(
            to_dict=lambda: {
                "repo_root": "/tmp/aragora",
                "base_ref": "origin/main",
                "branch": "preflight/20260411-test",
                "worktree_path": "/tmp/aragora/.worktrees/preflight-test",
                "agent": "codex",
                "published": False,
                "pull_request_created": False,
                "pull_request_closed": False,
                "cleanup_worktree_removed": True,
                "cleanup_branch_removed": True,
                "passed": True,
                "worker": {"worker_contract_checksum": "abc123", "commit_shas": ["deadbeef"]},
            }
        )

        with patch(
            "aragora.swarm.preflight.run_preflight", return_value=fake_result
        ) as run_preflight:
            cmd_swarm(args)

        kwargs = run_preflight.call_args.kwargs
        assert kwargs["agent"] == "codex"
        assert kwargs["base_ref"] == "origin/main"
        assert kwargs["skip_publication"] is True
        assert kwargs["contract_path"] is None
        assert isinstance(kwargs["repo_root"], Path)
        out = capsys.readouterr().out
        assert '"mode": "swarm-preflight"' in out
        assert '"worker_contract_checksum": "abc123"' in out

    def test_cmd_swarm_preflight_without_contract_fails_closed(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="preflight",
            worker_model="codex",
            target_branch="origin/main",
            contract=None,
            skip_publication=True,
            json=False,
        )
        fake_result = SimpleNamespace(
            to_dict=lambda: {
                "repo_root": "/tmp/aragora",
                "base_ref": "origin/main",
                "branch": "preflight/failed-push",
                "agent": "codex",
                "passed": False,
                "checks": [{"name": "git_push", "passed": False}],
                "worker": {},
            }
        )

        with (
            patch("aragora.swarm.preflight.run_preflight", return_value=fake_result),
            pytest.raises(SystemExit, match="2"),
        ):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "swarm preflight: blocked" in out
        assert "swarm preflight: ok" not in out

    def test_cmd_swarm_preflight_contract_path_emits_receipt_and_gate(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="preflight",
            worker_model="codex",
            target_branch="origin/main",
            contract="/tmp/worker-contract.json",
            skip_publication=True,
            json=True,
        )
        fake_receipt = SimpleNamespace(
            to_dict=lambda: {
                "receipt_id": "preflight-scratch-1234",
                "check_type": "scratch",
                "passed": True,
                "expires_at": "2026-04-14T03:00:00Z",
                "artifacts": {"expected_contract_checksum": "abc123"},
            },
            failure_terminal_class=None,
            artifacts={"expected_contract_checksum": "abc123"},
        )
        fake_gate = SimpleNamespace(
            to_dict=lambda: {
                "gate_type": "dispatch_ready",
                "verdict": "pass",
                "failure_classes": [],
                "notes": "receipt verified",
            }
        )

        with (
            patch(
                "aragora.swarm.preflight.run_contract_preflight_receipt",
                return_value=fake_receipt,
            ) as run_contract_preflight_receipt,
            patch(
                "aragora.swarm.preflight.evaluate_preflight_receipt_gate",
                return_value=fake_gate,
            ) as evaluate_preflight_receipt_gate,
        ):
            cmd_swarm(args)

        kwargs = run_contract_preflight_receipt.call_args.kwargs
        assert kwargs["agent"] == "codex"
        assert kwargs["base_ref"] == "origin/main"
        assert kwargs["skip_publication"] is True
        assert kwargs["contract_path"] == Path("/tmp/worker-contract.json")
        assert isinstance(kwargs["repo_root"], Path)
        gate_kwargs = evaluate_preflight_receipt_gate.call_args.kwargs
        assert gate_kwargs["check_type"] == "scratch"
        out = capsys.readouterr().out
        assert '"receipt_id": "preflight-scratch-1234"' in out
        assert '"verdict": "pass"' in out

    def test_cmd_swarm_preflight_contract_path_fails_closed(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="preflight",
            worker_model="codex",
            target_branch="main",
            contract="/tmp/worker-contract.json",
            skip_publication=True,
            json=True,
        )
        fake_receipt = SimpleNamespace(
            to_dict=lambda: {
                "receipt_id": "preflight-scratch-1234",
                "check_type": "scratch",
                "passed": False,
                "expires_at": "2026-04-14T03:00:00Z",
                "artifacts": {"expected_contract_checksum": "abc123"},
            },
            failure_terminal_class=SimpleNamespace(value="blocked_not_dispatch_bounded"),
            artifacts={"expected_contract_checksum": "abc123"},
        )
        fake_gate = SimpleNamespace(
            to_dict=lambda: {
                "gate_type": "dispatch_ready",
                "verdict": "blocked",
                "failure_classes": ["blocked_not_dispatch_bounded"],
                "notes": "receipt failed",
            }
        )

        with (
            patch(
                "aragora.swarm.preflight.run_contract_preflight_receipt",
                return_value=fake_receipt,
            ),
            patch(
                "aragora.swarm.preflight.evaluate_preflight_receipt_gate",
                return_value=fake_gate,
            ),
            pytest.raises(SystemExit, match="2"),
        ):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"failure_terminal_class": "blocked_not_dispatch_bounded"' in out

    def test_swarm_integrator_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "integrator",
                "merge",
                "--lane-id",
                "lane-1",
                "--rationale",
                "Ship it",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "integrator"
        assert args.swarm_goal == "merge"
        assert args.lane_id == "lane-1"
        assert args.rationale == "Ship it"

    def test_swarm_tranche_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "inspect",
                "--manifest",
                "docs/examples/boss-lane-manifest-2026-03-19.yaml",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "inspect"
        assert args.manifest == "docs/examples/boss-lane-manifest-2026-03-19.yaml"
        assert args.json is True

    def test_swarm_tranche_plan_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "plan",
                "--from-prompts",
                "docs/examples/pmf-prompt-pack.yaml",
                "--output",
                ".aragora/tranches/pmf/tranche.yaml",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "plan"
        assert args.from_prompts == "docs/examples/pmf-prompt-pack.yaml"
        assert args.output == ".aragora/tranches/pmf/tranche.yaml"

    def test_swarm_tranche_submit_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "submit",
                "--intake",
                "docs/examples/pmf-tranche-prompt-pack.yaml",
                "--autonomy",
                "adaptive",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "submit"
        assert args.intake == "docs/examples/pmf-tranche-prompt-pack.yaml"
        assert args.autonomy == "adaptive"
        assert args.json is True

    def test_swarm_tranche_design_review_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "design-review",
                "--manifest",
                "docs/examples/boss-lane-manifest-2026-03-19.yaml",
                "--rounds",
                "2",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "design-review"
        assert args.manifest == "docs/examples/boss-lane-manifest-2026-03-19.yaml"
        assert args.rounds == 2
        assert args.json is True

    def test_swarm_tranche_review_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "review",
                "--manifest",
                "docs/examples/boss-lane-manifest-2026-03-19.yaml",
                "--lane-id",
                "lane_a",
                "--tier",
                "1",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "review"
        assert args.lane_id == "lane_a"
        assert args.tier == "1"
        assert args.json is True

    def test_swarm_tranche_integrate_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "integrate",
                "--manifest",
                "docs/examples/boss-lane-manifest-2026-03-19.yaml",
                "--lane-id",
                "lane_a",
                "--approve",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "integrate"
        assert args.lane_id == "lane_a"
        assert args.approve is True
        assert args.json is True

    def test_swarm_tranche_watch_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "watch",
                "--manifest",
                "docs/examples/boss-lane-manifest-2026-03-19.yaml",
                "--driver",
                "--interval",
                "3",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "watch"
        assert args.driver is True
        assert args.interval_seconds == 3
        assert args.json is True

    def test_swarm_tranche_list_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "tranche", "list", "--json"])
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "list"
        assert args.json is True

    def test_swarm_tranche_status_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "status",
                "--queue",
                "docs/examples/overnight-queue.yaml",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "status"
        assert args.queue == "docs/examples/overnight-queue.yaml"
        assert args.json is True

    def test_swarm_tranche_run_queue_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "run-queue",
                "--queue",
                "docs/examples/overnight-queue.yaml",
                "--max-hours",
                "8",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "run-queue"
        assert args.queue == "docs/examples/overnight-queue.yaml"
        assert args.max_parallel_lanes == 1
        assert args.max_hours == 8
        assert args.json is True

    def test_swarm_tranche_run_queue_parser_accepts_bounded_parallel_flag(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "run-queue",
                "--queue",
                "docs/examples/overnight-queue.yaml",
                "--max-parallel-lanes",
                "2",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "run-queue"
        assert args.max_parallel_lanes == 2

    def test_swarm_tranche_reconcile_queue_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "reconcile-queue",
                "--queue",
                "docs/examples/overnight-queue.yaml",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "reconcile-queue"
        assert args.queue == "docs/examples/overnight-queue.yaml"
        assert args.json is True

    def test_swarm_tranche_harvest_queue_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "harvest-queue",
                "--queue",
                "docs/examples/overnight-queue.yaml",
                "--dry-run",
                "--execute-merge",
                "--allow-admin",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "harvest-queue"
        assert args.queue == "docs/examples/overnight-queue.yaml"
        assert args.dry_run is True
        assert args.execute_merge is True
        assert args.allow_admin is True
        assert args.json is True

    def test_swarm_tranche_compile_queue_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "tranche",
                "compile-queue",
                "--sources",
                "docs/examples/overnight-sources.yaml",
                "--output",
                "docs/examples/overnight-queue.yaml",
                "--json",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "tranche"
        assert args.swarm_goal == "compile-queue"
        assert args.sources == "docs/examples/overnight-sources.yaml"
        assert args.output == "docs/examples/overnight-queue.yaml"
        assert args.json is True

    def test_swarm_parser_accepts_spec_dispatch_options(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "--spec", "swarm-spec.yaml", "--dispatch-only", "--no-wait", "--json"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal is None
        assert args.spec == "swarm-spec.yaml"
        assert args.dispatch_only is True
        assert args.no_wait is True
        assert args.json is True


class TestSwarmCommand:
    def test_cmd_swarm_assign_and_findings_flow(self, tmp_path: Path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assign_args = _swarm_args(
            swarm_action_or_goal="assign",
            swarm_goal="codex-a",
            swarm_campaign_target="SDK parity consolidation",
            scope=["#2684"],
            constraint=["no queue drain"],
            assigned_by="boss-codex",
            json=True,
        )
        cmd_swarm(assign_args)
        assign_out = capsys.readouterr().out
        assert '"mode": "coordination-assign"' in assign_out
        assert '"target": "codex-a"' in assign_out

        report_args = _swarm_args(
            swarm_action_or_goal="report",
            swarm_goal="Verification route bug",
            session_id="review-codex",
            kind="blocker",
            pr=2677,
            json=True,
        )
        cmd_swarm(report_args)
        report_out = capsys.readouterr().out
        assert '"mode": "coordination-report"' in report_out
        assert '"kind": "blocker"' in report_out

        findings_args = _swarm_args(
            swarm_action_or_goal="findings",
            session_id="review-codex",
            kind="blocker",
            json=True,
        )
        cmd_swarm(findings_args)
        findings_out = capsys.readouterr().out
        assert '"mode": "coordination-findings"' in findings_out
        assert '"message": "Verification route bug"' in findings_out

    def test_cmd_swarm_claim_pr_reports_contested_owner(self, tmp_path: Path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)

        first_args = _swarm_args(
            swarm_action_or_goal="claim-pr",
            swarm_goal="2684",
            session_id="codex-a",
        )
        cmd_swarm(first_args)
        assert "claimed PR#2684 for codex-a" in capsys.readouterr().out

        second_args = _swarm_args(
            swarm_action_or_goal="claim-pr",
            swarm_goal="2684",
            session_id="codex-b",
        )
        cmd_swarm(second_args)
        out = capsys.readouterr().out
        assert "PR#2684 claim contested for codex-b" in out
        assert "codex-a" in out

    def test_cmd_swarm_status_includes_coordination_view(self, tmp_path: Path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cmd_swarm(
            _swarm_args(
                swarm_action_or_goal="assign",
                swarm_goal="codex-a",
                swarm_campaign_target="Own parity lane",
                assigned_by="boss-codex",
            )
        )
        capsys.readouterr()
        cmd_swarm(
            _swarm_args(
                swarm_action_or_goal="report",
                swarm_goal="Bandit B310 in auth/oidc.py",
                session_id="codex-b",
                kind="blocker",
                pr=2679,
            )
        )
        capsys.readouterr()

        with (
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=tmp_path),
            patch("aragora.worktree.fleet.build_fleet_rows", return_value=[]),
            patch("aragora.worktree.fleet.FleetCoordinationStore") as store_cls,
            patch("aragora.swarm.SwarmSupervisor") as supervisor_cls,
        ):
            store_cls.return_value.list_claims.return_value = []
            store_cls.return_value.list_merge_queue.return_value = []
            supervisor_cls.return_value.status_summary.return_value = {
                "runs": [],
                "counts": {
                    "runs": 0,
                    "queued_work_orders": 0,
                    "leased_work_orders": 0,
                    "completed_work_orders": 0,
                },
                "coordination": {"counts": {"active_leases": 0}},
            }
            cmd_swarm(_swarm_args(swarm_action_or_goal="status"))

        out = capsys.readouterr().out
        assert "coordination directives=1 sessions=0 claims=0 findings=1" in out
        assert "directive codex-a status=active task=Own parity lane" in out
        assert "finding codex-b kind=blocker pr=#2679 Bandit B310 in auth/oidc.py" in out

    def test_cmd_swarm_runner_inspect_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="inspect",
            json=True,
        )
        inspection = SimpleNamespace(
            to_dict=lambda: {
                "runner_id": "codex-runner-123",
                "runner_type": "codex",
                "auth_mode": "chatgpt_login",
                "availability": "available",
                "available": True,
                "freshness_status": "fresh",
                "heartbeat_at": "2026-03-09T12:00:00+00:00",
                "stale_after_seconds": 3600,
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "capabilities": {"max_parallel_lanes": 1},
                "next_action": "Runner is eligible for Boss-mode routing.",
            }
        )

        with patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover:
            discover.return_value = [inspection]
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"runner_id": "codex-runner-123"' in out
        assert '"auth_mode": "chatgpt_login"' in out
        assert '"availability": "available"' in out

    def test_cmd_swarm_tranche_inspect_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="inspect",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            json=True,
        )

        fake_manifest = object()
        with (
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.TrancheInspector") as inspector_cls,
        ):
            inspector_cls.return_value.inspect.return_value = {
                "mode": "tranche-inspect",
                "manifest_id": "boss-live-proof-tranche-2026-03-19",
                "preflight_status": "ok",
                "recommended_action": {"kind": "run_lane", "lane_id": "codex_a_live_gate"},
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-inspect"' in out
        assert '"manifest_id": "boss-live-proof-tranche-2026-03-19"' in out
        assert '"lane_id": "codex_a_live_gate"' in out
        assert '"action": "inspect"' in out

    def test_cmd_swarm_tranche_plan_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="plan",
            from_prompts="docs/examples/pmf-prompt-pack.yaml",
            output=".aragora/tranches/pmf/tranche.yaml",
            json=True,
        )
        fake_manifest = SimpleNamespace(
            manifest_id="pmf-tranche",
            lanes=[object(), object()],
            references={"source_refs": {}, "gates": {}},
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.TranchePlanner") as planner_cls,
        ):
            planner_cls.return_value.plan_from_prompt_bundle.return_value = (
                fake_manifest,
                Path("/tmp/repo/.aragora/tranches/pmf/tranche.yaml"),
            )
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-plan"' in out
        assert '"manifest_id": "pmf-tranche"' in out
        assert '"lane_count": 2' in out
        assert '"action": "plan"' in out

    def test_cmd_swarm_tranche_submit_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="submit",
            intake="/tmp/bundle.yaml",
            autonomy="adaptive",
            json=True,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch(
                "aragora.cli.commands.swarm._load_structured_object",
                return_value={"objective": "Submit tranche"},
            ),
            patch("aragora.swarm.tranche_submit.submit_intake_bundle") as mock_submit,
        ):
            mock_submit.return_value = {
                "inspection_status": "ok",
                "submission_status": "ready_to_prepare",
                "recommended_action": "prepare",
                "manifest_id": "test-123",
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"submission_status": "ready_to_prepare"' in out
        assert '"manifest_id": "test-123"' in out
        assert '"action": "submit"' in out

    def test_cmd_swarm_tranche_design_review_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="design-review",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            rounds=2,
            json=True,
        )
        fake_manifest = SimpleNamespace(manifest_id="pmf-tranche", objective="Ship it", lanes=[])
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheInspector") as inspector_cls,
            patch(
                "aragora.cli.commands.swarm._load_structured_object",
                return_value={"objective": "Ship it"},
            ),
            patch("aragora.swarm.tranche_design_review.run_design_review") as mock_run,
            patch("aragora.swarm.tranche_design_review.save_design_review") as mock_save,
        ):
            inspector_cls.return_value.inspect.return_value = {"preflight_status": "ok"}
            mock_run.return_value = {
                "recommendation": "approved",
                "rounds_completed": 1,
                "record": {
                    "manifest_id": "pmf-tranche",
                    "status": "approved",
                    "rounds": [],
                    "proposed_manifest": {},
                    "critique_findings": [],
                    "revised_manifest": {},
                    "unresolved_assumptions": [],
                    "recommendation": "approved",
                    "created_at": "2026-03-19T00:00:00+00:00",
                    "updated_at": "2026-03-19T00:00:00+00:00",
                },
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"recommendation": "approved"' in out
        assert '"action": "design-review"' in out
        mock_save.assert_called_once()

    def test_cmd_swarm_tranche_review_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="review",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            lane_id="lane_a",
            tier="1",
            json=True,
        )
        fake_manifest = SimpleNamespace(
            manifest_id="pmf-tranche",
            lane=lambda _lane_id: SimpleNamespace(allowed_write_scope=["aragora/live/**"]),
        )
        fake_artifact = SimpleNamespace(
            lane_id="lane_a",
            status="completed",
            run_id="run-1",
            metadata={},
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheArtifactStore") as store_cls,
            patch("aragora.swarm.supervisor.SwarmSupervisor") as supervisor_cls,
            patch("aragora.swarm.tranche_review.review_lane") as mock_review,
        ):
            store_cls.return_value.load.return_value = fake_artifact
            store_cls.return_value.list.return_value = [fake_artifact]
            supervisor_cls.return_value.refresh_run.return_value.to_dict.return_value = {
                "run_id": "run-1",
                "status": "completed",
                "work_orders": [],
            }
            mock_review.return_value = {
                "status": "passed",
                "tier": 1,
                "findings": [],
                "retry_count": 0,
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-review"' in out
        assert '"status": "passed"' in out
        assert '"action": "review"' in out

    def test_cmd_swarm_tranche_review_raises_unexpected_refresh_errors(self):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="review",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            lane_id="lane_a",
            tier="1",
            json=True,
        )
        fake_manifest = SimpleNamespace(
            manifest_id="pmf-tranche",
            lane=lambda _lane_id: SimpleNamespace(allowed_write_scope=["aragora/live/**"]),
        )
        fake_artifact = SimpleNamespace(
            lane_id="lane_a",
            status="completed",
            run_id="run-1",
            metadata={},
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheArtifactStore") as store_cls,
            patch("aragora.swarm.supervisor.SwarmSupervisor") as supervisor_cls,
            patch("aragora.swarm.tranche_review.review_lane") as mock_review,
        ):
            store_cls.return_value.load.return_value = fake_artifact
            store_cls.return_value.list.return_value = [fake_artifact]
            supervisor = supervisor_cls.return_value
            supervisor.refresh_run.side_effect = TypeError("refresh exploded")
            supervisor.store.get_supervisor_run.return_value = {
                "run_id": "run-1",
                "status": "completed",
                "work_orders": [],
            }

            with pytest.raises(TypeError, match="refresh exploded"):
                cmd_swarm(args)

        mock_review.assert_not_called()

    def test_cmd_swarm_tranche_integrate_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="integrate",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            lane_id="lane_a",
            json=True,
        )
        fake_manifest = SimpleNamespace(manifest_id="pmf-tranche")
        fake_artifact = SimpleNamespace(
            lane_id="lane_a",
            status="review_passed",
            metadata={
                "branch": "feat-branch",
                "review": {"status": "passed"},
                "receipt_id": "receipt-123",
                "lease_id": "lease-123",
            },
        )
        fake_state = SimpleNamespace(save=lambda _path: None)
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheArtifactStore") as store_cls,
            patch("aragora.swarm.tranche_watch.load_tranche_run_state", return_value=fake_state),
            patch(
                "aragora.swarm.tranche_integrate.integrate_lane",
                new_callable=AsyncMock,
            ) as mock_integrate,
        ):
            store_cls.return_value.load.return_value = fake_artifact
            mock_integrate.return_value = {
                "lane_id": "lane_a",
                "recommendation": "merge",
                "executed": False,
                "checks": "checks_passed",
                "review_status": "passed",
                "publish_result": {
                    "published": True,
                    "action": "pr_created",
                    "branch": "feat-branch",
                    "pr_url": "https://github.com/org/repo/pull/42",
                    "detail": "Branch pushed and PR created against main.",
                },
                "cascade_report": {
                    "merged_lane_id": "lane_a",
                    "downstream": [
                        {
                            "lane_id": "lane_b",
                            "pr_url": "https://github.com/org/repo/pull/99",
                            "action": "retargeted",
                            "reason": "Retargeted downstream PR from stack-base to main.",
                        }
                    ],
                    "clean": True,
                    "needs_human": False,
                },
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-integrate"' in out
        assert '"recommendation": "merge"' in out
        assert '"action": "integrate"' in out
        assert '"publish_result"' in out
        assert '"cascade_report"' in out
        assert '"action": "retargeted"' in out
        mock_integrate.assert_awaited_once()

    def test_cmd_swarm_tranche_integrate_ignores_malformed_run_state(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="integrate",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            lane_id="lane_a",
            json=True,
        )
        fake_manifest = SimpleNamespace(manifest_id="pmf-tranche")
        fake_artifact = SimpleNamespace(
            lane_id="lane_a",
            status="review_passed",
            metadata={"branch": "feat-branch", "review": {"status": "passed"}},
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheArtifactStore") as store_cls,
            patch(
                "aragora.swarm.tranche_watch.load_tranche_run_state",
                side_effect=ValueError("Tranche run state must deserialize to an object."),
            ),
            patch(
                "aragora.swarm.tranche_integrate.integrate_lane",
                new_callable=AsyncMock,
            ) as mock_integrate,
        ):
            store_cls.return_value.load.return_value = fake_artifact
            mock_integrate.return_value = {"lane_id": "lane_a", "recommendation": "merge"}

            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-integrate"' in out
        assert '"lane_id": "lane_a"' in out
        mock_integrate.assert_awaited_once()
        assert mock_integrate.await_args.kwargs["run_state"] is None

    def test_cmd_swarm_tranche_watch_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="watch",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            driver=True,
            owner_session_id="sess-1",
            interval_seconds=3.0,
            max_ticks=2,
            json=True,
        )
        fake_manifest = SimpleNamespace(manifest_id="pmf-tranche")
        fake_state = SimpleNamespace(
            manifest_id="pmf-tranche",
            status="running",
            autonomy_mode="adaptive",
            lane_states={},
            to_dict=lambda: {
                "manifest_id": "pmf-tranche",
                "status": "running",
                "autonomy_mode": "adaptive",
                "lane_states": {},
            },
            save=lambda _path: None,
        )
        watched_state = SimpleNamespace(
            manifest_id="pmf-tranche",
            status="completed",
            autonomy_mode="adaptive",
            lane_states={},
            to_dict=lambda: {
                "manifest_id": "pmf-tranche",
                "status": "completed",
                "autonomy_mode": "adaptive",
                "lane_states": {},
            },
        )
        released_state = SimpleNamespace(
            manifest_id="pmf-tranche",
            status="completed",
            autonomy_mode="adaptive",
            lane_states={},
            to_dict=lambda: {
                "manifest_id": "pmf-tranche",
                "status": "completed",
                "autonomy_mode": "adaptive",
                "lane_states": {},
            },
            save=lambda _path: None,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche_watch.load_tranche_run_state", return_value=fake_state),
            patch(
                "aragora.swarm.tranche_watch.claim_driver", return_value=fake_state
            ) as mock_claim,
            patch("aragora.swarm.tranche_watch.release_driver", return_value=released_state),
            patch(
                "aragora.swarm.tranche_watch.watch_loop", new_callable=AsyncMock
            ) as mock_watch_loop,
        ):
            mock_watch_loop.return_value = watched_state
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-watch"' in out
        assert '"status": "completed"' in out
        assert '"action": "watch"' in out
        mock_claim.assert_called_once()
        mock_watch_loop.assert_awaited_once()
        assert mock_watch_loop.await_args.kwargs["driver_session_id"] == "sess-1"
        assert callable(mock_watch_loop.await_args.kwargs["run_fn"])

    def test_cmd_swarm_tranche_list_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="list",
            json=True,
        )
        with (
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch(
                "aragora.swarm.tranche_watch.list_tranche_states",
                return_value=[
                    {
                        "manifest_id": "pmf-tranche",
                        "status": "running",
                        "autonomy_mode": "adaptive",
                        "path": "/tmp/repo/.aragora/tranches/pmf-tranche/run_state.yaml",
                        "lane_states": {},
                        "updated_at": "2026-03-19T00:00:00+00:00",
                    }
                ],
            ),
        ):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-list"' in out
        assert '"manifest_id": "pmf-tranche"' in out
        assert '"action": "list"' in out

    def test_cmd_swarm_tranche_run_queue_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="run-queue",
            queue="/tmp/overnight-queue.yaml",
            max_parallel_lanes=2,
            json=True,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch(
                "aragora.swarm.tranche_queue.run_tranche_queue",
                new_callable=AsyncMock,
            ) as mock_run_queue,
        ):
            mock_run_queue.return_value = {
                "mode": "tranche-queue",
                "queue_id": "overnight",
                "status": "completed",
                "counts": {"completed": 2},
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-queue"' in out
        assert '"queue_id": "overnight"' in out
        assert '"action": "run-queue"' in out
        mock_run_queue.assert_awaited_once()
        assert mock_run_queue.await_args.kwargs["max_parallel_lanes"] == 2

    def test_cmd_swarm_tranche_status_text(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="status",
            queue="/tmp/overnight-queue.yaml",
            json=False,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche_queue.tranche_queue_status") as mock_status,
        ):
            mock_status.return_value = {
                "mode": "tranche-queue-status",
                "queue_id": "overnight",
                "status": "running",
                "current_item_id": "issue-1046",
                "items": [
                    {
                        "item_id": "issue-1046",
                        "status": "running",
                        "pr_url": "https://github.com/org/repo/pull/42",
                        "worker_branch": "codex/issue-1046",
                        "worker_branches": ["codex/issue-1046"],
                        "elapsed_seconds": 300.0,
                    }
                ],
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "queue_id=overnight status=running current_item_id=issue-1046" in out
        assert "item_id" in out
        assert "worker_branch" in out
        assert "https://github.com/org/repo/pull/42" in out
        assert "codex/issue-1046" in out
        assert "5m 0s" in out
        mock_status.assert_called_once_with(
            queue_path=Path("/tmp/overnight-queue.yaml").resolve(),
            repo_root=Path("/tmp/repo"),
        )

    def test_cmd_swarm_tranche_reconcile_queue_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="reconcile-queue",
            queue="/tmp/overnight-queue.yaml",
            json=True,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche_queue.reconcile_tranche_queue") as mock_reconcile,
        ):
            mock_reconcile.return_value = {
                "mode": "tranche-queue",
                "queue_id": "overnight",
                "status": "running",
                "counts": {"running": 1},
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-queue"' in out
        assert '"queue_id": "overnight"' in out
        assert '"action": "reconcile-queue"' in out
        mock_reconcile.assert_called_once()

    def test_cmd_swarm_tranche_compile_queue_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="compile-queue",
            sources="/tmp/overnight-sources.yaml",
            output="/tmp/overnight-queue.yaml",
            json=True,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche_queue.compile_tranche_queue") as mock_compile_queue,
        ):
            mock_compile_queue.return_value = {
                "mode": "tranche-queue-compile",
                "queue_id": "overnight",
                "item_count": 2,
                "proposal_count": 1,
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-queue-compile"' in out
        assert '"queue_id": "overnight"' in out
        assert '"action": "compile-queue"' in out
        mock_compile_queue.assert_called_once()

    def test_cmd_swarm_tranche_harvest_queue_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="harvest-queue",
            queue="/tmp/overnight-queue.yaml",
            execute_merge=True,
            allow_admin=True,
            json=True,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche_queue.harvest_tranche_queue") as mock_harvest_queue,
        ):
            mock_harvest_queue.return_value = {
                "mode": "tranche-queue-harvest",
                "queue_id": "overnight",
                "status": "completed",
                "pr_counts": {"merge_now": 1},
                "executed_merges": [],
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-queue-harvest"' in out
        assert '"queue_id": "overnight"' in out
        assert '"action": "harvest-queue"' in out
        mock_harvest_queue.assert_called_once_with(
            queue_path=Path("/tmp/overnight-queue.yaml").resolve(),
            repo_root=Path("/tmp/repo"),
            execute_merge=True,
            allow_admin=True,
        )

    def test_cmd_swarm_tranche_harvest_queue_dry_run_forces_non_mutating_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="harvest-queue",
            queue="/tmp/overnight-queue.yaml",
            dry_run=True,
            execute_merge=True,
            allow_admin=True,
            json=True,
        )
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche_queue.harvest_tranche_queue") as mock_harvest_queue,
        ):
            mock_harvest_queue.return_value = {
                "mode": "tranche-queue-harvest",
                "queue_id": "overnight",
                "status": "completed",
                "pr_counts": {"merge_now": 1},
                "executed_merges": [],
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"dry_run": true' in out
        assert '"requested_execute_merge": true' in out
        mock_harvest_queue.assert_called_once_with(
            queue_path=Path("/tmp/overnight-queue.yaml").resolve(),
            repo_root=Path("/tmp/repo"),
            execute_merge=False,
            allow_admin=True,
        )

    def test_cmd_swarm_tranche_prepare_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="prepare",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            lane_id="codex_a_live_gate",
            json=True,
        )
        fake_manifest = object()
        with (
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheExecutor") as executor_cls,
        ):
            executor_cls.return_value.prepare.return_value = {
                "mode": "tranche-prepare",
                "manifest_id": "pmf-tranche",
                "prepared_lanes": [{"lane_id": "codex_a_live_gate", "status": "prepared"}],
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-prepare"' in out
        assert '"lane_id": "codex_a_live_gate"' in out
        assert '"action": "prepare"' in out

    def test_cmd_swarm_tranche_run_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="tranche",
            swarm_goal="run",
            manifest="docs/examples/boss-lane-manifest-2026-03-19.yaml",
            lane_id="codex_a_live_gate",
            json=True,
        )
        fake_manifest = object()
        with (
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.swarm.tranche.load_tranche_manifest", return_value=fake_manifest),
            patch("aragora.swarm.tranche.TrancheExecutor") as executor_cls,
        ):
            executor_cls.return_value.run = AsyncMock(
                return_value={
                    "mode": "tranche-run",
                    "manifest_id": "pmf-tranche",
                    "results": [{"lane_id": "codex_a_live_gate", "status": "running"}],
                }
            )
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "tranche-run"' in out
        assert '"status": "running"' in out
        assert '"action": "run"' in out

    def test_cmd_swarm_runner_register_rejects_unknown_auth(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="register",
        )
        inspection = SimpleNamespace(
            to_dict=lambda: {
                "runner_id": "codex-runner-123",
                "runner_type": "codex",
                "auth_mode": "unknown",
                "availability": "available",
                "freshness_status": "unknown",
                "heartbeat_at": None,
                "stale_after_seconds": 3600,
                "owner_binding": {"user_id": None, "workspace_id": None},
                "capabilities": {
                    "supports_exec": True,
                    "supports_review": True,
                    "max_parallel_lanes": 2,
                },
                "next_action": "Set ARAGORA_USER_ID before registering.",
            }
        )
        registered = SimpleNamespace(
            to_dict=lambda: {
                "runner_id": "codex-runner-123",
                "runner_type": "codex",
                "auth_mode": "unknown",
                "availability": "available",
                "registered": False,
                "registry_path": "/tmp/swarm-runners.json",
                "freshness_status": "unknown",
                "heartbeat_at": None,
                "stale_after_seconds": 3600,
                "owner_binding": {"user_id": None, "workspace_id": None},
                "capabilities": {
                    "supports_exec": True,
                    "supports_review": True,
                    "max_parallel_lanes": 2,
                },
                "next_action": "Registration blocked: Codex auth mode is unknown.",
            }
        )

        with (
            patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            discover.return_value = [inspection]
            auth_ctx.return_value = object()
            registry_cls.return_value.register.return_value = registered
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "runner_id=codex-runner-123" in out
        assert "availability=available auth_mode=unknown" in out
        assert "owner=unbound workspace=none" in out
        assert "freshness=unknown heartbeat_at=none stale_after=3600" in out
        assert "registered_at=" not in out
        assert "next: Registration blocked: Codex auth mode is unknown." in out

    def test_cmd_swarm_runner_heartbeat_emits_freshness(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="heartbeat",
            json=True,
        )
        inspection = SimpleNamespace(
            to_dict=lambda: {
                "runner_id": "codex-runner-123",
                "runner_type": "codex",
                "auth_mode": "chatgpt_login",
                "availability": "available",
                "available": True,
                "freshness_status": "fresh",
                "heartbeat_at": "2026-03-09T12:05:00+00:00",
                "stale_after_seconds": 3600,
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "capabilities": {"supports_exec": True, "max_parallel_lanes": 2},
                "next_action": "Runner heartbeat refreshed.",
            }
        )
        heartbeated = SimpleNamespace(
            to_dict=lambda: {
                "runner_id": "codex-runner-123",
                "runner_type": "codex",
                "auth_mode": "chatgpt_login",
                "availability": "available",
                "available": True,
                "registered": True,
                "freshness_status": "fresh",
                "heartbeat_at": "2026-03-09T12:05:00+00:00",
                "stale_after_seconds": 3600,
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "capabilities": {"supports_exec": True, "max_parallel_lanes": 2},
                "next_action": "Runner heartbeat refreshed.",
            }
        )

        with (
            patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            discover.return_value = [inspection]
            auth_ctx.return_value = object()
            registry_cls.return_value.heartbeat.return_value = heartbeated
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"action": "heartbeat"' in out
        assert '"freshness_status": "fresh"' in out
        assert '"heartbeat_at": "2026-03-09T12:05:00+00:00"' in out

    def test_cmd_swarm_runner_report_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="report",
            runner_type="claude",
            json=True,
        )
        inspection = SimpleNamespace(
            to_dict=lambda: {
                "runner_id": "claude-runner-123",
                "runner_type": "claude",
                "auth_mode": "subscription",
                "availability": "available",
                "available": True,
                "freshness_status": "fresh",
                "heartbeat_at": "2026-03-09T12:05:00+00:00",
                "stale_after_seconds": 3600,
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "capabilities": {"supports_exec": True, "max_parallel_lanes": 2},
            }
        )
        routing = SimpleNamespace(
            to_dict=lambda: {
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "selected_runner_ids": ["claude-runner-123"],
                "selected_runners": [
                    {
                        "runner_id": "claude-runner-123",
                        "runner_type": "claude",
                        "freshness_status": "fresh",
                    }
                ],
                "blocked_reason": None,
                "next_action": "Route through the selected Claude runner set.",
            }
        )

        with (
            patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
            patch("aragora.swarm.runner_registry.refresh_discovered_runners") as refresh,
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            discover.return_value = [inspection]
            refresh.return_value = [inspection]
            auth_ctx.return_value = object()
            registry_cls.return_value.list_registrations.return_value = [
                {
                    "runner_id": "claude-runner-123",
                    "runner_type": "claude",
                    "cost_class": "subscription",
                    "freshness_status": "fresh",
                    "probe_status": "passed",
                    "active_lanes": 1,
                    "capabilities": {"max_parallel_lanes": 3, "active_lanes": 1},
                }
            ]
            registry_cls.return_value.resolve_boss_routing.return_value = routing
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"action": "report"' in out
        assert '"mode": "runner"' in out
        assert '"runner_type": "claude"' in out
        assert '"cost_class": "subscription"' in out
        assert '"selected_verified": 0' in out
        assert '"execution_verified": 1' in out
        assert '"discovered_runners": [' in out
        assert '"selected_runner_ids": [' in out

    def test_cmd_swarm_runner_probe_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="probe",
            runner_type="claude",
            probe_limit=1,
            json=True,
        )
        inspection = SimpleNamespace(
            runner_id="claude-runner-123",
            profile="max-02",
            to_dict=lambda: {
                "runner_id": "claude-runner-123",
                "runner_type": "claude",
                "profile": "max-02",
                "auth_mode": "subscription",
                "availability": "available",
            },
        )
        probe = SimpleNamespace(
            status="passed",
            to_runner_fields=lambda: {
                "probe_status": "passed",
                "probe_checked_at": "2026-03-09T12:05:00+00:00",
                "probe_detail": "Live prompt probe succeeded.",
                "probe_latency_seconds": 1.2,
                "probe_ttl_seconds": 3600,
            },
        )

        with (
            patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.probe_runner_execution", return_value=probe),
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            discover.return_value = [inspection]
            auth_ctx.return_value = object()
            registry_cls.return_value.resolve_boss_routing.return_value = SimpleNamespace(
                to_dict=lambda: {
                    "selected_runners": [],
                    "selected_runner_ids": [],
                    "blocked_reason": None,
                }
            )
            registry_cls.return_value.record_probe.return_value = {
                "runner_id": "claude-runner-123",
                "runner_type": "claude",
                "profile": "max-02",
                "probe_status": "passed",
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"action": "probe"' in out
        assert '"attempted": 1' in out
        assert '"passed": 1' in out
        assert '"probe_status": "passed"' in out

    def test_cmd_swarm_runner_probe_codex_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="probe",
            runner_type="codex",
            probe_limit=1,
            json=True,
        )
        inspection = SimpleNamespace(
            runner_id="codex-runner-456",
            profile="codex-mini",
            to_dict=lambda: {
                "runner_id": "codex-runner-456",
                "runner_type": "codex",
                "profile": "codex-mini",
                "auth_mode": "api_key",
                "availability": "available",
            },
        )
        probe = SimpleNamespace(
            status="passed",
            to_runner_fields=lambda: {
                "probe_status": "passed",
                "probe_checked_at": "2026-03-09T12:10:00+00:00",
                "probe_detail": "Live prompt probe succeeded.",
                "probe_latency_seconds": 0.8,
                "probe_ttl_seconds": 3600,
            },
        )

        with (
            patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.probe_runner_execution", return_value=probe),
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            discover.return_value = [inspection]
            auth_ctx.return_value = object()
            registry_cls.return_value.resolve_boss_routing.return_value = SimpleNamespace(
                to_dict=lambda: {
                    "selected_runners": [],
                    "selected_runner_ids": [],
                    "blocked_reason": None,
                }
            )
            registry_cls.return_value.record_probe.return_value = {
                "runner_id": "codex-runner-456",
                "runner_type": "codex",
                "profile": "codex-mini",
                "probe_status": "passed",
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"action": "probe"' in out
        assert '"attempted": 1' in out
        assert '"passed": 1' in out
        assert '"probe_status": "passed"' in out
        assert '"runner_type": "codex"' in out

    def test_cmd_swarm_runner_probe_gemini_cli_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="probe",
            runner_type="gemini-cli",
            probe_limit=1,
            json=True,
        )
        inspection = SimpleNamespace(
            runner_id="gemini-runner-789",
            profile="gemini-pro",
            to_dict=lambda: {
                "runner_id": "gemini-runner-789",
                "runner_type": "gemini-cli",
                "profile": "gemini-pro",
                "auth_mode": "oauth",
                "availability": "available",
            },
        )
        probe = SimpleNamespace(
            status="passed",
            to_runner_fields=lambda: {
                "probe_status": "passed",
                "probe_checked_at": "2026-03-09T12:15:00+00:00",
                "probe_detail": "Live prompt probe succeeded.",
                "probe_latency_seconds": 1.0,
                "probe_ttl_seconds": 3600,
            },
        )

        with (
            patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.probe_runner_execution", return_value=probe),
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            discover.return_value = [inspection]
            auth_ctx.return_value = object()
            registry_cls.return_value.resolve_boss_routing.return_value = SimpleNamespace(
                to_dict=lambda: {
                    "selected_runners": [],
                    "selected_runner_ids": [],
                    "blocked_reason": None,
                }
            )
            registry_cls.return_value.record_probe.return_value = {
                "runner_id": "gemini-runner-789",
                "runner_type": "gemini-cli",
                "profile": "gemini-pro",
                "probe_status": "passed",
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"action": "probe"' in out
        assert '"attempted": 1' in out
        assert '"passed": 1' in out
        assert '"probe_status": "passed"' in out
        assert '"runner_type": "gemini-cli"' in out

    def test_cmd_swarm_runner_maintain_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="runner",
            swarm_goal="maintain",
            runner_type="claude",
            probe_limit=1,
            json=True,
        )
        inspection = SimpleNamespace(
            runner_id="claude-runner-123",
            profile="max-02",
            to_dict=lambda: {
                "runner_id": "claude-runner-123",
                "runner_type": "claude",
                "profile": "max-02",
                "auth_mode": "subscription",
                "availability": "available",
            },
        )
        probe = SimpleNamespace(
            status="failed",
            to_runner_fields=lambda: {
                "probe_status": "failed",
                "probe_checked_at": "2026-03-09T12:05:00+00:00",
                "probe_detail": "Probe failed",
                "probe_latency_seconds": 2.4,
                "probe_ttl_seconds": 3600,
            },
        )
        routing_before = SimpleNamespace(
            to_dict=lambda: {
                "selected_runners": [{"runner_id": "claude-runner-123"}],
                "selected_runner_ids": ["claude-runner-123"],
                "blocked_reason": None,
            }
        )
        routing_after = SimpleNamespace(
            to_dict=lambda: {
                "selected_runners": [],
                "selected_runner_ids": [],
                "blocked_reason": "no_eligible_registered_runners",
            }
        )

        with (
            patch(
                "aragora.swarm.runner_registry.refresh_discovered_runners",
                return_value=[inspection],
            ),
            patch(
                "aragora.swarm.runner_registry.prioritized_probe_candidates",
                return_value=[inspection],
            ),
            patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
            patch("aragora.swarm.runner_registry.probe_runner_execution", return_value=probe),
            patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        ):
            auth_ctx.return_value = object()
            registry_cls.return_value.resolve_boss_routing.side_effect = [
                routing_before,
                routing_after,
            ]
            registry_cls.return_value.record_probe.return_value = {
                "runner_id": "claude-runner-123",
                "runner_type": "claude",
                "profile": "max-02",
                "probe_status": "failed",
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"action": "maintain"' in out
        assert '"attempted": 1' in out
        assert '"failed": 1' in out
        assert '"selected_before": 1' in out
        assert '"selected_after": 0' in out
        assert '"execution_verified_after": 0' in out
        assert '"heartbeat_readiness"' in out
        assert '"ready": false' in out
        assert '"blocked_reason": "no_execution_verified_runner"' in out

    def test_cmd_swarm_audit_issues_json(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="audit-issues",
            swarm_goal=None,
            boss_repo="synaptent/aragora",
            labels=["boss-ready"],
            boss_label_filter=None,
            boss_issue_number=None,
            boss_issue_list=None,
            audit_ref="origin/main",
            json=True,
        )
        issue = SimpleNamespace(
            number=1639,
            title="Add --json output flag to aragora quickstart CLI",
            body="Validation: pytest tests/cli/test_quickstart.py -x -q",
            labels=["boss-ready"],
            url="https://github.com/synaptent/aragora/issues/1639",
        )

        with (
            patch("aragora.swarm.boss_loop.GitHubIssueFeed") as feed_cls,
            patch(
                "aragora.cli.commands.swarm._open_audit_checkout",
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=Path("/tmp/audit-main")),
                    __exit__=MagicMock(return_value=False),
                ),
            ) as open_checkout,
            patch(
                "aragora.cli.commands.swarm._audit_issue_validation_contract",
                return_value={
                    "number": 1639,
                    "title": "Add --json output flag to aragora quickstart CLI",
                    "url": "https://github.com/synaptent/aragora/issues/1639",
                    "labels": ["boss-ready"],
                    "validation_contract": ["pytest tests/cli/test_quickstart.py -x -q"],
                    "commands": ["pytest tests/cli/test_quickstart.py -x -q"],
                    "probe_results": [
                        {
                            "command": "pytest tests/cli/test_quickstart.py -x -q",
                            "status": "failed",
                            "returncode": 1,
                        }
                    ],
                    "status": "validation_fails_now",
                    "next_action": "Validation still fails on the current branch.",
                },
            ) as audit_issue,
        ):
            feed_cls.return_value.fetch.return_value = [issue]
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert '"mode": "swarm-issue-audit"' in out
        assert '"action": "audit-issues"' in out
        assert '"audit_ref": "origin/main"' in out
        assert '"issue_count": 1' in out
        assert '"validation_fails_now": 1' in out
        open_checkout.assert_called_once()
        _, kwargs = open_checkout.call_args
        assert kwargs["git_ref"] == "origin/main"
        audit_issue.assert_called_once()
        _, kwargs = audit_issue.call_args
        assert kwargs["repo_root"] == Path("/tmp/audit-main")

    def test_classify_issue_validation_status_detects_cli_usage_failure(self):
        status, next_action = _classify_issue_validation_status(
            validation_contract=["aragora quickstart --json"],
            commands=["python3 -m aragora.cli.main quickstart --json"],
            probe_results=[
                {
                    "command": "python3 -m aragora.cli.main quickstart --json",
                    "status": "failed",
                    "returncode": 1,
                    "stderr": "usage: main.py ... error: unrecognized arguments: --json",
                }
            ],
        )
        assert status == "cli_usage_failure"
        assert "parser rejects this queued CLI command" in next_action

    def test_classify_issue_validation_status_detects_no_matching_tests_collected(self):
        status, next_action = _classify_issue_validation_status(
            validation_contract=["pytest tests/swarm/test_boss_loop.py -k refine -q"],
            commands=["pytest tests/swarm/test_boss_loop.py -k refine -q"],
            probe_results=[
                {
                    "command": "pytest tests/swarm/test_boss_loop.py -k refine -q",
                    "status": "failed",
                    "returncode": 5,
                    "stdout": "82 deselected in 0.44s",
                }
            ],
        )
        assert status == "no_matching_tests_collected"
        assert "collects no tests on the current branch" in next_action

    def test_classify_issue_validation_status_detects_unsafe_validation_contract(self):
        status, next_action = _classify_issue_validation_status(
            validation_contract=[
                'aragora quickstart --topic test --rounds 1 --json | python3 -c "import json"'
            ],
            commands=[
                "python3 -m aragora.cli.main quickstart --topic test --rounds 1 --json | "
                'python3 -c "import json"'
            ],
            probe_results=[
                {
                    "command": "python3 -m aragora.cli.main quickstart --topic test --rounds 1 --json | "
                    'python3 -c "import json"',
                    "status": "unsafe",
                    "detail": "shell operators are not allowed",
                }
            ],
        )
        assert status == "unsafe_validation_contract"
        assert "single direct command" in next_action

    def test_cmd_swarm_requires_goal_or_spec(self, capsys):
        args = argparse.Namespace(
            swarm_action_or_goal="run",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=False,
            budget_limit=5.0,
            require_approval=False,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )
        cmd_swarm(args)
        out = capsys.readouterr().out
        assert "provide a goal or --spec file" in out

    def test_cmd_swarm_dry_run_saves_spec(self, tmp_path: Path):
        output_spec = tmp_path / "generated-spec.yaml"
        fake_spec = _FakeSpec("id: generated\n")
        mock_commander = SimpleNamespace(dry_run=AsyncMock(return_value=fake_spec))

        args = argparse.Namespace(
            swarm_action_or_goal="ship swarm",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=True,
            budget_limit=7.0,
            require_approval=False,
            save_spec=str(output_spec),
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        mock_commander.dry_run.assert_awaited_once()
        assert output_spec.exists()
        assert output_spec.read_text() == "id: generated\n"

    def test_cmd_swarm_dry_run_skip_interrogation_builds_direct_spec(self, capsys):
        args = argparse.Namespace(
            swarm_action_or_goal="verify dry run",
            swarm_goal=None,
            spec=None,
            skip_interrogation=True,
            dry_run=True,
            budget_limit=11.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmCommander"):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "[DRY RUN] Skipping interrogation" in out
        assert '"raw_goal": "verify dry run"' in out

    def test_cmd_swarm_skip_interrogation_dispatches_when_goal_is_already_bounded(self):
        fake_run = MagicMock()
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock(return_value=fake_run))
        args = argparse.Namespace(
            swarm_action_or_goal="Only touch aragora/swarm/spec.py",
            swarm_goal=None,
            spec=None,
            skip_interrogation=True,
            dry_run=False,
            budget_limit=9.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        mock_commander.run_supervised_from_spec.assert_awaited_once()
        call = mock_commander.run_supervised_from_spec.await_args
        assert call.kwargs["max_concurrency"] == 8
        assert call.kwargs["dispatch"] is True
        assert call.kwargs["wait"] is True

    def test_cmd_swarm_skip_interrogation_fails_closed_for_vague_goal(self, capsys):
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock())
        args = argparse.Namespace(
            swarm_action_or_goal="make it better",
            swarm_goal=None,
            spec=None,
            skip_interrogation=True,
            dry_run=False,
            budget_limit=9.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "under-specified for dispatch" in out
        mock_commander.run_supervised_from_spec.assert_not_called()

    @patch("aragora.worktree.fleet.FleetCoordinationStore")
    @patch("aragora.worktree.fleet.build_fleet_rows")
    @patch("aragora.worktree.fleet.resolve_repo_root")
    def test_cmd_swarm_status_uses_supervisor(
        self, mock_resolve_root, mock_build_rows, mock_store_cls, capsys
    ):
        mock_resolve_root.return_value = Path("/tmp/repo")
        mock_build_rows.return_value = [
            {
                "session_id": "sess-a",
                "path": "/tmp/repo/.worktrees/a",
                "branch": "codex/docs-lane",
                "has_lock": True,
                "pid_alive": True,
                "agent": "codex",
                "last_activity": "2026-03-07T00:00:00+00:00",
            }
        ]
        store = MagicMock()
        store.list_claims.return_value = [
            {"session_id": "sess-a", "path": "aragora/swarm/reporter.py"}
        ]
        store.list_merge_queue.return_value = [
            {
                "id": "mq-1",
                "branch": "codex/docs-lane",
                "session_id": "sess-a",
                "status": "needs_human",
                "metadata": {"receipt_id": "rcpt-123"},
            }
        ]
        mock_store_cls.return_value = store
        args = argparse.Namespace(
            swarm_action_or_goal="status",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=False,
            budget_limit=9.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmSupervisor") as supervisor_cls:
            supervisor_cls.return_value.status_summary.return_value = {
                "runs": [
                    {
                        "run_id": "run-1",
                        "status": "active",
                        "target_branch": "main",
                        "goal": "dogfood",
                        "work_orders": [
                            {
                                "work_order_id": "docs-lane",
                                "title": "Write operator guide",
                                "status": "completed",
                                "branch": "codex/docs-lane",
                                "worktree_path": "/tmp/repo/.worktrees/a",
                                "target_agent": "codex",
                                "last_progress_at": "2026-03-07T00:00:00+00:00",
                            }
                        ],
                    }
                ],
                "counts": {
                    "runs": 1,
                    "queued_work_orders": 0,
                    "leased_work_orders": 0,
                    "completed_work_orders": 1,
                },
                "coordination": {"counts": {"active_leases": 1}},
            }
            cmd_swarm(args)

        mock_build_rows.assert_called_once_with(
            Path("/tmp/repo"),
            base_branch="main",
            tail=0,
            include_git_metrics=False,
        )
        out = capsys.readouterr().out
        assert "runs=1 queued=0 leased=0 completed=1" in out
        assert "integrator ready=0 review=0 blocked=1" in out
        assert "next: Write operator guide:" in out

    def test_cmd_swarm_reconcile_uses_reconciler(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="reconcile",
            run_id="run-123",
        )

        fake_run = _fake_supervisor_run()

        with patch("aragora.swarm.SwarmReconciler") as reconciler_cls:
            reconciler_cls.return_value.tick_run = AsyncMock(return_value=fake_run)
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "run_id=run-123" in out

    def test_cmd_swarm_spec_no_dispatch_preserves_explicit_work_orders(self, tmp_path: Path):
        spec_path = tmp_path / "swarm-spec.yaml"
        spec = SwarmSpec(
            raw_goal="Dogfood the supervised swarm",
            refined_goal="Dogfood the supervised swarm",
            work_orders=[
                {
                    "work_order_id": "docs-lane",
                    "title": "Add operator guide",
                    "file_scope": ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"],
                    "expected_tests": [],
                    "target_agent": "codex",
                    "reviewer_agent": "claude",
                }
            ],
        )
        spec_path.write_text(spec.to_yaml())
        mock_commander = SimpleNamespace(
            run_supervised_from_spec=AsyncMock(return_value=_fake_supervisor_run())
        )
        args = _swarm_args(spec=str(spec_path), no_dispatch=True)

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        mock_commander.run_supervised_from_spec.assert_awaited_once()
        call = mock_commander.run_supervised_from_spec.await_args
        passed_spec = call.args[0]
        assert passed_spec.work_orders[0]["work_order_id"] == "docs-lane"
        assert passed_spec.work_orders[0]["file_scope"] == ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"]
        assert call.kwargs["dispatch"] is False
        assert call.kwargs["wait"] is True

    def test_cmd_swarm_spec_dispatch_only_runs_fire_and_forget(
        self, tmp_path: Path, capsys
    ) -> None:
        spec_path = tmp_path / "swarm-spec.yaml"
        spec = SwarmSpec(
            raw_goal="Dogfood the supervised swarm",
            refined_goal="Dogfood the supervised swarm",
            work_orders=[
                {
                    "work_order_id": "tests-lane",
                    "title": "Add regressions",
                    "file_scope": ["tests/swarm/test_commander.py"],
                    "expected_tests": ["python -m pytest tests/swarm/test_commander.py -q"],
                    "target_agent": "claude",
                    "reviewer_agent": "codex",
                }
            ],
        )
        spec_path.write_text(spec.to_yaml())
        fake_run = _fake_supervisor_run(
            work_orders=[{"work_order_id": "tests-lane", "status": "dispatched"}]
        )
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock(return_value=fake_run))
        args = _swarm_args(spec=str(spec_path), dispatch_only=True, json=True)

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        call = mock_commander.run_supervised_from_spec.await_args
        assert call.kwargs["dispatch"] is True
        assert call.kwargs["wait"] is False
        out = capsys.readouterr().out
        assert '"run_id": "run-123"' in out
        assert '"status": "active"' in out

    def test_cmd_swarm_boss_mode_forces_supervised_defaults_and_prints_text(self, capsys):
        fake_run = _fake_supervisor_run(
            run_id="boss-run-1",
            status="needs_human",
            work_orders=[
                {
                    "work_order_id": "lane-a",
                    "title": "Lane A",
                    "status": "needs_human",
                    "branch": "codex/lane-a",
                    "worktree_path": "/tmp/repo/.worktrees/lane-a",
                    "target_agent": "codex",
                    "lease_id": "lease-a",
                    "receipt_id": "receipt-a",
                    "dispatch_error": "waiting for human choice",
                }
            ],
        )
        mock_commander = SimpleNamespace(run_supervised=AsyncMock(return_value=fake_run))
        args = _swarm_args(
            swarm_action_or_goal="boss",
            swarm_goal="Split vague operator request into supervised lanes",
            concurrency_cap=1,
        )

        with (
            patch("aragora.swarm.SwarmCommander", return_value=mock_commander),
            patch("aragora.cli.commands.swarm._resolve_boss_routing") as resolve_routing,
            patch("aragora.cli.commands.swarm._build_boss_payload") as build_payload,
        ):
            resolve_routing.return_value = {
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "selected_runner_ids": ["codex-runner-1"],
                "selected_runners": [{"runner_id": "codex-runner-1", "freshness_status": "fresh"}],
                "selection_basis": "registered=true",
                "blocked_reason": None,
                "rejected_runner_ids": [],
                "next_action": "Boss mode will route only through the selected registered Codex runner set.",
            }
            build_payload.return_value = {
                "mode": "boss",
                "run_id": "boss-run-1",
                "status": "needs_human",
                "goal": "Split vague operator request into supervised lanes",
                "target_branch": "main",
                "work_order_counts": {"needs_human": 1},
                "routing": {
                    "selected_runner_ids": ["codex-runner-1"],
                    "selected_runners": [
                        {"runner_id": "codex-runner-1", "freshness_status": "fresh"}
                    ],
                    "blocked_reason": None,
                    "rejected_runner_ids": [],
                    "next_action": "Boss mode will route only through the selected registered Codex runner set.",
                },
                "lanes": [
                    {
                        "work_order_id": "lane-a",
                        "status": "needs_human",
                        "branch": "codex/lane-a",
                        "worktree_path": "/tmp/repo/.worktrees/lane-a",
                        "receipt_id": "receipt-a",
                    }
                ],
                "integrator_next_actions": ["Review lane-a and decide whether to narrow scope."],
                "needs_human": [
                    {
                        "work_order_id": "lane-a",
                        "title": "Lane A",
                        "reasons": ["waiting for human choice"],
                    }
                ],
            }
            cmd_swarm(args)

        call = mock_commander.run_supervised.await_args
        assert call.args[0] == "Split vague operator request into supervised lanes"
        assert call.kwargs["max_concurrency"] == 4
        assert call.kwargs["dispatch"] is True
        assert call.kwargs["wait"] is True
        out = capsys.readouterr().out
        assert "run_id=boss-run-1" in out
        assert "work_orders=[needs_human=1]" in out
        assert "routing: selected_runners=codex-runner-1(fresh)" in out
        assert "next: Review lane-a and decide whether to narrow scope." in out
        assert "needs_human: Lane A -> waiting for human choice" in out

    def test_cmd_swarm_boss_mode_json_with_spec_emits_boss_payload(self, tmp_path: Path, capsys):
        spec_path = tmp_path / "swarm-spec.yaml"
        spec = SwarmSpec(
            raw_goal="Run boss mode from spec",
            refined_goal="Run boss mode from spec",
            work_orders=[
                {
                    "work_order_id": "lane-b",
                    "title": "Lane B",
                    "file_scope": ["aragora/swarm/reporter.py"],
                    "expected_tests": ["python -m pytest tests/swarm/test_commander.py -q"],
                    "target_agent": "claude",
                }
            ],
        )
        spec_path.write_text(spec.to_yaml())
        fake_run = _fake_supervisor_run(
            run_id="boss-run-2",
            status="active",
            work_orders=[
                {
                    "work_order_id": "lane-b",
                    "title": "Lane B",
                    "status": "leased",
                    "branch": "codex/lane-b",
                    "worktree_path": "/tmp/repo/.worktrees/lane-b",
                    "target_agent": "claude",
                }
            ],
        )
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock(return_value=fake_run))
        args = _swarm_args(
            swarm_action_or_goal="boss",
            spec=str(spec_path),
            json=True,
            concurrency_cap=2,
        )

        with (
            patch("aragora.swarm.SwarmCommander", return_value=mock_commander),
            patch("aragora.cli.commands.swarm._resolve_boss_routing") as resolve_routing,
            patch("aragora.cli.commands.swarm._build_boss_payload") as build_payload,
        ):
            resolve_routing.return_value = {
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "selected_runner_ids": ["codex-runner-1"],
                "selected_runners": [{"runner_id": "codex-runner-1", "freshness_status": "fresh"}],
                "selection_basis": "registered=true",
                "blocked_reason": None,
                "rejected_runner_ids": [],
                "next_action": "Boss mode will route only through the selected registered Codex runner set.",
            }
            build_payload.return_value = {
                "mode": "boss",
                "run_id": "boss-run-2",
                "status": "active",
                "goal": "Run boss mode from spec",
                "target_branch": "main",
                "work_order_counts": {"leased": 1},
                "routing": {
                    "selected_runner_ids": ["codex-runner-1"],
                    "selected_runners": [
                        {"runner_id": "codex-runner-1", "freshness_status": "fresh"}
                    ],
                    "blocked_reason": None,
                    "rejected_runner_ids": [],
                    "next_action": "Boss mode will route only through the selected registered Codex runner set.",
                },
                "lanes": [
                    {
                        "work_order_id": "lane-b",
                        "status": "leased",
                        "branch": "codex/lane-b",
                        "worktree_path": "/tmp/repo/.worktrees/lane-b",
                        "lease_id": "lease-b",
                        "receipt_id": None,
                        "next_action": "Wait for worker completion.",
                    }
                ],
                "integrator_next_actions": ["Wait for worker completion."],
                "needs_human": [],
                "coordination_counts": {"active_leases": 1},
                "integrator_summary": {"review_lanes": 0},
            }
            cmd_swarm(args)

        call = mock_commander.run_supervised_from_spec.await_args
        assert call.kwargs["max_concurrency"] == 4
        assert call.kwargs["dispatch"] is True
        assert call.kwargs["wait"] is True
        out = capsys.readouterr().out
        assert '"mode": "boss"' in out
        assert '"run_id": "boss-run-2"' in out
        assert '"integrator_next_actions": [' in out
        assert '"coordination_counts": {' in out
        assert '"selected_runner_ids": [' in out

    def test_cmd_swarm_boss_mode_blocks_when_no_eligible_runner(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="boss",
            swarm_goal="Split vague operator request into supervised lanes",
            json=True,
        )
        mock_commander = SimpleNamespace(run_supervised=AsyncMock())

        with (
            patch("aragora.swarm.SwarmCommander", return_value=mock_commander),
            patch("aragora.cli.commands.swarm._resolve_boss_routing") as resolve_routing,
        ):
            resolve_routing.return_value = {
                "owner_binding": {"user_id": None, "workspace_id": None},
                "selected_runner_ids": [],
                "selected_runners": [],
                "selection_basis": "registered=true",
                "blocked_reason": "missing_owner_context",
                "rejected_runner_ids": [],
                "next_action": "Set `ARAGORA_USER_ID` and `ARAGORA_WORKSPACE_ID` before running Boss mode.",
            }
            cmd_swarm(args)

        mock_commander.run_supervised.assert_not_called()
        out = capsys.readouterr().out
        assert '"status": "blocked"' in out
        assert '"blocked_reason": "missing_owner_context"' in out
        assert '"selected_runner_ids": []' in out

    def test_cmd_swarm_boss_mode_blocks_when_only_stale_runners_exist(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="boss",
            swarm_goal="Split vague operator request into supervised lanes",
            json=True,
        )
        mock_commander = SimpleNamespace(run_supervised=AsyncMock())

        with (
            patch("aragora.swarm.SwarmCommander", return_value=mock_commander),
            patch("aragora.cli.commands.swarm._resolve_boss_routing") as resolve_routing,
        ):
            resolve_routing.return_value = {
                "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                "selected_runner_ids": [],
                "selected_runners": [],
                "selection_basis": "registered=true freshness_status=fresh",
                "blocked_reason": "no_fresh_registered_runners",
                "rejected_runner_ids": ["codex-runner-stale"],
                "next_action": "Refresh the heartbeat for an available registered Codex runner.",
            }
            cmd_swarm(args)

        mock_commander.run_supervised.assert_not_called()
        out = capsys.readouterr().out
        assert '"blocked_reason": "no_fresh_registered_runners"' in out
        assert '"rejected_runner_ids": [' in out

    def test_cmd_swarm_integrator_view_text(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="integrator",
        )

        with (
            patch("aragora.worktree.fleet.resolve_repo_root") as resolve_repo_root,
            patch("aragora.cli.commands.swarm._load_integrator_view") as load_view,
        ):
            resolve_repo_root.return_value = Path("/tmp/repo")
            load_view.return_value = {
                "summary": {
                    "total_lanes": 1,
                    "ready_lanes": 1,
                    "blocked_lanes": 0,
                    "review_lanes": 0,
                    "stale_heartbeat_lanes": 0,
                    "superseded_lanes": 0,
                },
                "lanes": [
                    {
                        "lane_id": "lane-1",
                        "title": "Write operator guide",
                        "branch": "codex/docs-lane",
                        "status": "completed",
                        "merge_readiness": "ready",
                        "canonical_lane": True,
                        "receipt_id": "rcpt-1",
                        "lease_id": "lease-1",
                        "blockers": [],
                        "next_action": "Queue or validate this lane for merge.",
                    }
                ],
                "next_actions": ["Queue or validate this lane for merge."],
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "Swarm Integrator View (1 lanes)" in out
        assert "Write operator guide" in out
        assert "lane_id=lane-1" in out
        assert "receipt=rcpt-1 lease=lease-1" in out

    def test_cmd_swarm_integrator_merge_records_decision(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="integrator",
            swarm_goal="merge",
            lane_id="lane-1",
            rationale="Ready to merge",
            decided_by="human-integrator",
        )
        mock_store = MagicMock()
        mock_store.record_integration_decision.return_value = SimpleNamespace(
            decision="merge",
            decision_id="dec-1",
        )

        with (
            patch("aragora.worktree.fleet.resolve_repo_root") as resolve_repo_root,
            patch("aragora.cli.commands.swarm._load_integrator_view") as load_view,
            # The swarm module binds ``DevCoordinationStore`` once at import
            # time (see Tier B PR 4 optional-import restructure), so patching
            # the upstream symbol is no longer enough — we must patch the
            # local binding used by ``cmd_swarm``.
            patch("aragora.cli.commands.swarm.DevCoordinationStore", return_value=mock_store),
        ):
            resolve_repo_root.return_value = Path("/tmp/repo")
            load_view.return_value = {
                "lanes": [
                    {
                        "lane_id": "lane-1",
                        "receipt_id": "rcpt-1",
                        "lease_id": "lease-1",
                        "branch": "codex/docs-lane",
                    }
                ]
            }
            cmd_swarm(args)

        call = mock_store.record_integration_decision.call_args
        assert call.kwargs["receipt_id"] == "rcpt-1"
        assert call.kwargs["lease_id"] == "lease-1"
        assert call.kwargs["decided_by"] == "human-integrator"
        out = capsys.readouterr().out
        assert "decision_id=dec-1" in out
        assert "decision=merge" in out

    def test_cmd_swarm_integrator_supersede_updates_registry(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="integrator",
            swarm_goal="supersede",
            lane_id="lane-1",
            new_pr_url="https://github.com/synaptent/aragora/pull/9999",
            rationale="Replacement PR is canonical",
        )
        mock_entry = SimpleNamespace(status="active", superseded=[{"pr_url": "old"}])

        with (
            patch("aragora.worktree.fleet.resolve_repo_root") as resolve_repo_root,
            patch("aragora.cli.commands.swarm._load_integrator_view") as load_view,
            patch("aragora.swarm.pr_registry.PullRequestRegistry") as registry_cls,
        ):
            resolve_repo_root.return_value = Path("/tmp/repo")
            load_view.return_value = {
                "lanes": [
                    {
                        "lane_id": "lane-1",
                        "branch": "codex/docs-lane",
                    }
                ]
            }
            registry_cls.return_value.supersede.return_value = mock_entry
            cmd_swarm(args)

        registry_cls.return_value.supersede.assert_called_once_with(
            "codex/docs-lane",
            "https://github.com/synaptent/aragora/pull/9999",
            reason="Replacement PR is canonical",
        )
        out = capsys.readouterr().out
        assert "branch=codex/docs-lane" in out
        assert "superseded_count=1" in out

    def test_cmd_swarm_reconcile_watch_uses_watch_run(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="reconcile",
            run_id="run-123",
            watch=True,
            interval_seconds=1.5,
            max_ticks=4,
        )
        fake_run = _fake_supervisor_run(
            work_orders=[{"work_order_id": "tests-lane", "status": "completed"}]
        )

        with patch("aragora.swarm.SwarmReconciler") as reconciler_cls:
            reconciler = reconciler_cls.return_value
            reconciler.watch_run = AsyncMock(return_value=fake_run)
            reconciler.tick_run = AsyncMock()
            cmd_swarm(args)

        reconciler.watch_run.assert_awaited_once_with(
            "run-123",
            interval_seconds=1.5,
            max_ticks=4,
        )
        reconciler.tick_run.assert_not_called()
        out = capsys.readouterr().out
        assert "work_orders=1 [completed=1]" in out


def test_cmd_swarm_initiative_plan_json(tmp_path, capsys):
    args = _swarm_args(
        swarm_action_or_goal="initiative",
        swarm_goal="plan",
        swarm_campaign_target="Create an initiative registry",
        initiative_dir=str(tmp_path),
        feature_flag="initiative_registry",
        dependency=["decision-plan-core"],
        validation=["python3 -m pytest tests/swarm/test_initiative_store.py -q"],
        milestone=["Planning ready"],
        checkpoint=["Registry validated"],
        json=True,
    )
    initiative = InitiativeRecord(
        initiative_id="initiative-registry",
        title="Create an initiative registry",
        goal="Create an initiative registry",
        rationale="Create an initiative registry",
        feature_flag_name="initiative_registry",
        slices=[
            InitiativeSlice(
                slice_id="slice-1",
                title="Registry",
                description="Persist initiative artifacts locally.",
            )
        ],
    )

    with patch("aragora.swarm.initiative_planner.InitiativePlanner.plan", return_value=initiative):
        cmd_swarm(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "initiative-plan"
    assert payload["initiative"]["initiative_id"] == "initiative-registry"
    assert Path(payload["path"]).exists()


def test_cmd_swarm_initiative_show_and_list(tmp_path, capsys):
    store = InitiativeStore(state_dir=tmp_path)
    initiative = InitiativeRecord(
        initiative_id="initiative-registry",
        title="Create an initiative registry",
        goal="Create an initiative registry",
        rationale="Persist roadmap work locally.",
        feature_flag_name="initiative_registry",
        slices=[
            InitiativeSlice(
                slice_id="slice-1",
                title="Registry",
                description="Persist initiative artifacts locally.",
            )
        ],
    )
    store.save(initiative)

    show_args = _swarm_args(
        swarm_action_or_goal="initiative",
        swarm_goal="show",
        swarm_campaign_target="initiative-registry",
        initiative_dir=str(tmp_path),
        json=True,
    )
    cmd_swarm(show_args)
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["mode"] == "initiative-show"
    assert show_payload["initiative"]["feature_flag_name"] == "initiative_registry"

    list_args = _swarm_args(
        swarm_action_or_goal="initiative",
        swarm_goal="list",
        initiative_dir=str(tmp_path),
        json=True,
    )
    cmd_swarm(list_args)
    list_payload = json.loads(capsys.readouterr().out)
    assert list_payload["mode"] == "initiative-list"
    assert list_payload["count"] == 1
    assert list_payload["items"][0]["initiative_id"] == "initiative-registry"
