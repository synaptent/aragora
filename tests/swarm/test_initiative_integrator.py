from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.swarm.campaign import (
    CampaignDependency,
    CampaignManifest,
    CampaignProject,
    CampaignProjectStatus,
    save_campaign_manifest,
)
from aragora.swarm.initiative_models import InitiativeRecord, InitiativeSlice
from aragora.swarm.initiative_integrator import InitiativeIntegrator
from aragora.swarm.initiative_store import InitiativeStore
from aragora.swarm.merge_arbiter import CheckSnapshotHeadMismatch, REQUIRED_CHECKS
from aragora.swarm.spec import SwarmSpec

HEAD_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
CHILD_HEAD_SHA = "cafebeefcafebeefcafebeefcafebeefcafebeef"


def _bounded_spec(goal: str) -> SwarmSpec:
    return SwarmSpec(
        raw_goal=goal,
        refined_goal=goal,
        acceptance_criteria=["pytest -q tests/swarm/test_initiative_integrator.py"],
        constraints=["do not widen scope"],
        file_scope_hints=["aragora/swarm/initiative_integrator.py"],
        budget_limit_usd=5.0,
    )


def _project(
    project_id: str,
    title: str,
    *,
    status: str = CampaignProjectStatus.PENDING.value,
    milestone: str | None = None,
    dependencies: list[str] | None = None,
    branch: str | None = None,
    pr_url: str | None = None,
    feature_flag: str | None = None,
    feature_flag_required: bool = False,
) -> CampaignProject:
    return CampaignProject(
        project_id=project_id,
        title=title,
        milestone=milestone,
        spec=_bounded_spec(title),
        file_scope_hints=["aragora/swarm/initiative_integrator.py"],
        acceptance_criteria=["pytest -q tests/swarm/test_initiative_integrator.py"],
        constraints=["stay in scope"],
        dependencies=[
            CampaignDependency(project_id=dependency_id, reason="depends_on")
            for dependency_id in (dependencies or [])
        ],
        branch=branch,
        pr_url=pr_url,
        feature_flag=feature_flag,
        feature_flag_required=feature_flag_required,
        status=status,
    )


def _manifest_path(tmp_path: Path, *projects: CampaignProject) -> Path:
    manifest_path = tmp_path / ".aragora" / "campaign_manifest.yaml"
    manifest = CampaignManifest(
        campaign_id="initiative-test",
        created_at="2026-04-07T00:00:00+00:00",
        source_kind="manual",
        source_ref="initiative.md",
        projects=list(projects),
    )
    save_campaign_manifest(manifest_path, manifest)
    return manifest_path


def _all_passing_checks() -> dict[str, str]:
    return dict.fromkeys(REQUIRED_CHECKS, "SUCCESS")


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "swarm_action_or_goal": "initiative",
        "swarm_goal": "status",
        "swarm_campaign_target": None,
        "spec": None,
        "skip_interrogation": False,
        "dry_run": False,
        "budget_limit": 50.0,
        "require_approval": False,
        "max_parallel": 20,
        "concurrency_cap": 8,
        "no_loop": False,
        "target_branch": "main",
        "managed_dir_pattern": ".worktrees/{agent}-auto",
        "json": True,
        "run_id": None,
        "refresh_scaling": False,
        "no_dispatch": False,
        "watch": False,
        "claude_runner_profiles": None,
        "runner_rotation_interval": 1800.0,
        "interval_seconds": 5.0,
        "max_ticks": None,
        "all_runs": False,
        "dispatch_only": False,
        "no_wait": False,
        "profile": "ceo",
        "from_obsidian": None,
        "obsidian_vault": None,
        "no_obsidian_receipts": False,
        "autonomy": "propose",
        "boss_repo": None,
        "manifest": "unused.yaml",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestInitiativeIntegrator:
    def test_status_reports_milestone_progress(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Root slice",
                status=CampaignProjectStatus.COMPLETED.value,
                milestone="M1",
            ),
            _project(
                "proj-002",
                "Follow-up slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                milestone="M1",
            ),
            _project(
                "proj-003",
                "Blocked slice",
                status=CampaignProjectStatus.BLOCKED.value,
                milestone="M2",
            ),
        )

        payload = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path).status(
            refresh=False
        )

        assert payload["total_slices"] == 3
        assert payload["completed_slices"] == 1
        assert payload["milestones_total"] == 2
        milestone_rows = {row["milestone"]: row for row in payload["milestones"]}
        assert milestone_rows["M1"]["total"] == 2
        assert milestone_rows["M1"]["completed"] == 1
        assert milestone_rows["M1"]["waiting_for_merge"] == 1
        assert milestone_rows["M2"]["blocked"] == 1

    @pytest.mark.asyncio
    async def test_run_does_not_retry_slice_with_published_pr(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Published slice",
                branch="codex/initiative-published",
                pr_url="https://github.com/synaptent/aragora/pull/1234",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)
        integrator.executor = MagicMock()
        integrator.executor.execute_once = AsyncMock(return_value={"stop_reason": "should_not_run"})
        with patch.object(
            integrator,
            "_resolve_project_pr_snapshot",
            return_value={
                "number": 91234,
                "url": "https://github.com/synaptent/aragora/pull/91234",
                "isDraft": False,
                "state": "OPEN",
                "headRefName": "codex/initiative-published",
                "mergeStateStatus": "CLEAN",
                "mergedAt": None,
            },
        ):
            payload = await integrator.run()

        assert payload["executed"] is False
        integrator.executor.execute_once.assert_not_called()
        assert payload["slices"][0]["status"] == CampaignProjectStatus.WAITING_FOR_MERGE.value
        assert payload["slices"][0]["execution_terminal"] is True

    def test_sync_terminals_completes_merged_pr_backed_slice(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Merged slice",
                pr_url="https://github.com/synaptent/aragora/pull/5001",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)

        with patch.object(
            integrator,
            "_resolve_project_pr_snapshot",
            return_value={
                "number": 5001,
                "url": "https://github.com/synaptent/aragora/pull/5001",
                "isDraft": False,
                "state": "MERGED",
                "headRefName": "codex/merged-slice",
                "mergeStateStatus": "MERGED",
                "mergedAt": "2026-04-07T00:00:00+00:00",
            },
        ):
            integrator.sync_terminals()

        payload = integrator.status(refresh=False)
        assert payload["slices"][0]["status"] == CampaignProjectStatus.COMPLETED.value

    def test_promote_prefers_dependency_root_even_when_manifest_unsorted(
        self, tmp_path: Path
    ) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-002",
                "Child slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                dependencies=["proj-001"],
                pr_url="https://github.com/synaptent/aragora/pull/2002",
            ),
            _project(
                "proj-001",
                "Parent slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                pr_url="https://github.com/synaptent/aragora/pull/2001",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)
        integrator.executor = MagicMock()
        integrator.executor.complete_project.return_value = {
            "project_id": "proj-001",
            "status": CampaignProjectStatus.COMPLETED.value,
        }

        def resolve_snapshot(project: CampaignProject) -> dict[str, object]:
            if project.project_id == "proj-001":
                return {
                    "number": 2001,
                    "url": "https://github.com/synaptent/aragora/pull/2001",
                    "isDraft": False,
                    "state": "OPEN",
                    "headRefName": "codex/parent",
                    "headRefOid": HEAD_SHA,
                    "mergeStateStatus": "CLEAN",
                    "mergedAt": None,
                }
            return {
                "number": 2002,
                "url": "https://github.com/synaptent/aragora/pull/2002",
                "isDraft": False,
                "state": "OPEN",
                "headRefName": "codex/child",
                "headRefOid": CHILD_HEAD_SHA,
                "mergeStateStatus": "CLEAN",
                "mergedAt": None,
            }

        with (
            patch.object(integrator, "_resolve_project_pr_snapshot", side_effect=resolve_snapshot),
            patch(
                "aragora.swarm.initiative_integrator._get_check_status",
                return_value=_all_passing_checks(),
            ) as check_status,
            patch(
                "aragora.swarm.initiative_integrator._merge_pr", return_value=(True, "merged")
            ) as merge_pr,
        ):
            payload = integrator.promote()

        assert payload["action"] == "merged"
        assert payload["project_id"] == "proj-001"
        check_status.assert_called_once_with(2001, integrator.repo, HEAD_SHA)
        merge_pr.assert_called_once_with(2001, integrator.repo, HEAD_SHA)

    def test_promote_blocks_merge_when_check_snapshot_head_changes(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Head drift slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                pr_url="https://github.com/synaptent/aragora/pull/2001",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)

        with (
            patch.object(
                integrator,
                "_resolve_project_pr_snapshot",
                return_value={
                    "number": 2001,
                    "url": "https://github.com/synaptent/aragora/pull/2001",
                    "isDraft": False,
                    "state": "OPEN",
                    "headRefName": "codex/head-drift",
                    "headRefOid": HEAD_SHA,
                    "mergeStateStatus": "CLEAN",
                    "mergedAt": None,
                },
            ),
            patch(
                "aragora.swarm.initiative_integrator._get_check_status",
                side_effect=CheckSnapshotHeadMismatch(
                    f"check snapshot head changed: expected {HEAD_SHA}, got {CHILD_HEAD_SHA}"
                ),
            ) as check_status,
            patch("aragora.swarm.initiative_integrator._merge_pr") as merge_pr,
        ):
            payload = integrator.promote()

        assert payload["action"] == "blocked"
        assert "check snapshot head changed" in payload["reason"]
        check_status.assert_called_once_with(2001, integrator.repo, HEAD_SHA)
        merge_pr.assert_not_called()

    def test_dry_run_blocks_would_merge_without_valid_head(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Dry-run missing head slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                pr_url="https://github.com/synaptent/aragora/pull/2001",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)

        with (
            patch.object(integrator, "sync_terminals"),
            patch.object(
                integrator,
                "_slice_status",
                return_value={
                    "next_action": "merge",
                    "promotion_blockers": [],
                    "pr_number": 2001,
                    "pr_url": "https://github.com/synaptent/aragora/pull/2001",
                    "head_sha": None,
                },
            ),
            patch("aragora.swarm.initiative_integrator._merge_pr") as merge_pr,
        ):
            payload = integrator.promote(project_id="proj-001", dry_run=True)

        assert payload["action"] == "blocked"
        assert "valid full head SHA" in payload["reason"]
        merge_pr.assert_not_called()

    @pytest.mark.parametrize("head_sha", [None, "", "deadbeef", "D" * 40])
    def test_promote_blocks_merge_without_valid_snapshot_head(
        self, tmp_path: Path, head_sha: object
    ) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Missing head slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                pr_url="https://github.com/synaptent/aragora/pull/2001",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)

        with (
            patch.object(
                integrator,
                "_resolve_project_pr_snapshot",
                return_value={
                    "number": 2001,
                    "url": "https://github.com/synaptent/aragora/pull/2001",
                    "isDraft": False,
                    "state": "OPEN",
                    "headRefName": "codex/missing-head",
                    "headRefOid": head_sha,
                    "mergeStateStatus": "CLEAN",
                    "mergedAt": None,
                },
            ),
            patch(
                "aragora.swarm.initiative_integrator._get_check_status",
                return_value=_all_passing_checks(),
            ),
            patch("aragora.swarm.initiative_integrator._merge_pr") as merge_pr,
        ):
            payload = integrator.promote()

        assert payload["action"] == "blocked"
        assert "valid full head SHA" in payload["reason"]
        merge_pr.assert_not_called()

    def test_promote_promotes_draft_slice_when_dependency_clear(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Draft slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                pr_url="https://github.com/synaptent/aragora/pull/3001",
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)

        with (
            patch.object(
                integrator,
                "_resolve_project_pr_snapshot",
                return_value={
                    "number": 3001,
                    "url": "https://github.com/synaptent/aragora/pull/3001",
                    "isDraft": True,
                    "state": "OPEN",
                    "headRefName": "codex/draft-slice",
                    "headRefOid": HEAD_SHA,
                    "mergeStateStatus": "CLEAN",
                    "mergedAt": None,
                },
            ),
            patch(
                "aragora.swarm.initiative_integrator._get_check_status",
                return_value=_all_passing_checks(),
            ),
            patch(
                "aragora.swarm.initiative_integrator._promote_draft", return_value=True
            ) as promote_draft,
        ):
            payload = integrator.promote()

        assert payload["action"] == "promoted_draft"
        assert payload["project_id"] == "proj-001"
        promote_draft.assert_called_once_with(3001, integrator.repo)

    def test_promote_blocks_merge_when_feature_flag_is_required(self, tmp_path: Path) -> None:
        manifest_path = _manifest_path(
            tmp_path,
            _project(
                "proj-001",
                "Flagged slice",
                status=CampaignProjectStatus.WAITING_FOR_MERGE.value,
                pr_url="https://github.com/synaptent/aragora/pull/4001",
                feature_flag_required=True,
            ),
        )
        integrator = InitiativeIntegrator(manifest_path=manifest_path, repo_root=tmp_path)

        with (
            patch.object(
                integrator,
                "_resolve_project_pr_snapshot",
                return_value={
                    "number": 4001,
                    "url": "https://github.com/synaptent/aragora/pull/4001",
                    "isDraft": False,
                    "state": "OPEN",
                    "headRefName": "codex/flagged-slice",
                    "headRefOid": HEAD_SHA,
                    "mergeStateStatus": "CLEAN",
                    "mergedAt": None,
                },
            ),
            patch(
                "aragora.swarm.initiative_integrator._get_check_status",
                return_value=_all_passing_checks(),
            ),
        ):
            payload = integrator.promote()

        assert payload["action"] == "blocked"
        assert "feature flag required" in payload["reason"]


class TestInitiativeCli:
    def test_swarm_parser_accepts_initiative_status(self) -> None:
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "initiative",
                "status",
                "--manifest",
                ".aragora/campaign_manifest.yaml",
            ]
        )

        assert args.swarm_action_or_goal == "initiative"
        assert args.swarm_goal == "status"

    def test_cmd_swarm_initiative_status_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from aragora.cli.commands.swarm import cmd_swarm

        manifest_path = _manifest_path(tmp_path, _project("proj-001", "CLI slice"))
        args = _args(manifest=str(manifest_path))

        with patch("aragora.swarm.initiative_integrator.InitiativeIntegrator") as integrator_cls:
            integrator_cls.return_value.status.return_value = {
                "mode": "initiative-status",
                "initiative_id": "initiative-1",
                "total_slices": 1,
                "completed_slices": 0,
                "milestones_complete": 0,
                "milestones_total": 1,
                "milestones": [],
                "slices": [],
            }
            cmd_swarm(args)

        parsed = json.loads(capsys.readouterr().out)
        assert parsed["mode"] == "initiative-status"
        assert parsed["initiative_id"] == "initiative-1"

    def test_cmd_swarm_initiative_status_resolves_manifest_from_store(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from aragora.cli.commands.swarm import cmd_swarm

        store = InitiativeStore(repo_root=tmp_path)
        initiative = InitiativeRecord(
            initiative_id="initiative-from-store",
            title="Store-backed initiative",
            goal="Run status without a pre-supplied manifest path.",
            rationale="CLI should resolve initiative ids through the JSON store.",
            slices=[
                InitiativeSlice(
                    slice_id="slice-1",
                    title="Bridge",
                    description="Create the initiative manifest bridge.",
                    file_scope=["aragora/swarm/initiative_campaign_bridge.py"],
                    validations=["pytest -q tests/swarm/test_initiative_campaign_bridge.py"],
                )
            ],
        )
        store.save(initiative)
        args = _args(
            swarm_goal="status",
            swarm_campaign_target=initiative.initiative_id,
            manifest=None,
            initiative_dir=str(store.state_dir),
        )

        with (
            patch("aragora.worktree.fleet.resolve_repo_root", return_value=tmp_path),
            patch("aragora.swarm.initiative_integrator.InitiativeIntegrator") as integrator_cls,
        ):
            integrator_cls.return_value.status.return_value = {
                "mode": "initiative-status",
                "initiative_id": initiative.initiative_id,
                "total_slices": 1,
                "completed_slices": 0,
                "milestones_complete": 0,
                "milestones_total": 0,
                "milestones": [],
                "slices": [],
            }
            cmd_swarm(args)

        manifest_path = store.campaign_manifest_path_for(initiative.initiative_id)
        assert manifest_path.exists()
        assert integrator_cls.call_args.kwargs["manifest_path"] == manifest_path
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["initiative_id"] == initiative.initiative_id

    def test_cmd_swarm_initiative_promote_keeps_manifest_target_as_project_id(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from aragora.cli.commands.swarm import cmd_swarm

        manifest_path = _manifest_path(tmp_path, _project("proj-001", "CLI slice"))
        args = _args(
            swarm_goal="promote",
            swarm_campaign_target="proj-001",
            manifest=str(manifest_path),
            dry_run=True,
        )

        with patch("aragora.swarm.initiative_integrator.InitiativeIntegrator") as integrator_cls:
            integrator_cls.return_value.promote.return_value = {
                "mode": "initiative-promote",
                "project_id": "proj-001",
                "decision": "dry_run",
            }
            cmd_swarm(args)

        assert integrator_cls.return_value.promote.call_args.kwargs["project_id"] == "proj-001"
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["project_id"] == "proj-001"
