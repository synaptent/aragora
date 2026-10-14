from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.cli.commands.swarm import (
    _render_tranche_queue_harvest_table,
    _render_tranche_queue_status,
)
from aragora.swarm.tranche_queue import (
    QUEUE_ITEM_PHASE_APPROVED,
    QUEUE_ITEM_PHASE_EXPLORED,
    QUEUE_ITEM_PHASE_PLANNED,
    QUEUE_ITEM_PHASE_QUEUED,
    QUEUE_WORK_CLASS_BOUNDED_FEATURE,
    QUEUE_WORK_CLASS_HARVEST,
    QUEUE_WORK_CLASS_INITIATIVE_MANUAL,
    QUEUE_STATUS_PENDING,
    QUEUE_ITEM_STATUS_COMPLETED,
    QUEUE_ITEM_STATUS_NEEDS_HUMAN,
    QUEUE_ITEM_STATUS_PENDING,
    QUEUE_ITEM_STATUS_RUNNING,
    QUEUE_ITEM_STATUS_STOPPED,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_RUNNING,
    QUEUE_STATUS_STOPPED,
    TrancheQueueExecutor,
    TrancheQueueItem,
    TrancheQueueItemRunState,
    TrancheQueueManifest,
    TrancheQueueRunState,
    compile_tranche_queue,
    explore_tranche_queue,
    harvest_tranche_queue,
    _queue_merge_policy,
    _resolve_queue_autonomy_mode,
    plan_tranche_queue,
    queue_state_path_for_queue,
    reconcile_tranche_queue,
    tranche_queue_status,
)
from aragora.swarm.tranche import TrancheArtifactStore, TrancheLaneArtifact
from aragora.swarm.tranche_state import (
    LANE_STATUS_NEEDS_HUMAN,
    TRANCHE_STATUS_NEEDS_HUMAN,
    LaneRunState,
    TrancheRunState,
)


def _write_queue(queue_path: Path) -> TrancheQueueManifest:
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [
                {"id": "issue-1046", "kind": "issue", "source": "1046", "merge_class": "manual"},
                {
                    "id": "intake-docs",
                    "kind": "intake",
                    "source": "bundles/docs.yaml",
                    "merge_class": "manual",
                },
                {"id": "issue-1047", "kind": "issue", "source": "1047", "merge_class": "manual"},
            ],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")
    return manifest


def test_compile_queue_writes_execute_doc_source_as_intake_bundle(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.yaml"
    doc_path = tmp_path / "roadmap.md"
    output_path = tmp_path / "overnight.yaml"
    doc_path.write_text("# Roadmap\n\nShip tranche queue.\n", encoding="utf-8")
    sources_path.write_text(
        """
queue_id: overnight
sources:
  - id: roadmap-doc
    kind: doc
    mode: execute
    path: roadmap.md
    objective: Ship the roadmap tranche work.
    merge_class: manual
""".strip(),
        encoding="utf-8",
    )

    payload = compile_tranche_queue(
        sources_path=sources_path,
        output_path=output_path,
        repo_root=tmp_path,
    )

    assert payload["item_count"] == 1
    assert payload["proposal_count"] == 0
    manifest = TrancheQueueManifest.load(output_path)
    assert manifest.items[0].kind == "intake"
    assert manifest.items[0].max_lanes == 1
    bundle_path = (output_path.parent / manifest.items[0].source).resolve()
    assert bundle_path.exists()
    bundle = bundle_path.read_text(encoding="utf-8")
    assert "Ship the roadmap tranche work." in bundle
    assert "merge_policy: manual" in bundle


def test_compile_queue_classifies_unbounded_execute_doc_source_as_initiative_manual(
    tmp_path: Path,
) -> None:
    sources_path = tmp_path / "sources.yaml"
    output_path = tmp_path / "overnight.yaml"
    doc_path = tmp_path / "roadmap.md"
    doc_path.write_text("# Roadmap\n\nShip tranche queue.\n", encoding="utf-8")
    sources_path.write_text(
        """
queue_id: overnight
sources:
  - id: roadmap-doc
    kind: doc
    mode: execute
    path: roadmap.md
    objective: Ship the roadmap tranche work.
    merge_class: manual
""".strip(),
        encoding="utf-8",
    )

    payload = compile_tranche_queue(
        sources_path=sources_path,
        output_path=output_path,
        repo_root=tmp_path,
    )

    assert payload["item_count"] == 1
    manifest = TrancheQueueManifest.load(output_path)
    assert manifest.items[0].work_class == QUEUE_WORK_CLASS_INITIATIVE_MANUAL


def test_harvest_queue_executes_merge_for_merge_now_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [
                {
                    "id": "issue-1046",
                    "kind": "issue",
                    "source": "1046",
                    "merge_class": "manual",
                }
            ],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    state = TrancheQueueRunState(queue_id="overnight", status=QUEUE_STATUS_PENDING)
    state.ensure_manifest(manifest)
    item_state = state.item_states["issue-1046"]
    item_state.status = QUEUE_ITEM_STATUS_NEEDS_HUMAN
    item_state.pr_urls = ["https://github.com/org/repo/pull/42"]
    state.save(queue_state_path_for_queue(queue_path))

    class _FakeSnapshot:
        disposition = "merge_now"
        required_checks_green = True
        head_branch = "codex/example-branch"
        head_sha = "a" * 40

        def to_dict(self) -> dict[str, object]:
            return {
                "pr_url": "https://github.com/org/repo/pull/42",
                "state": "OPEN",
                "draft": False,
                "head_branch": self.head_branch,
                "base_branch": "main",
                "review_decision": "APPROVED",
                "merge_state_status": "CLEAN",
                "merge_commit_sha": None,
                "required_checks": [],
                "advisory_checks": [],
                "required_checks_green": True,
                "required_checks_known": True,
                "required_checks_source": "ruleset",
                "disposition": "merge_now",
                "blocker_detail": None,
            }

    class _FakeMergeResult:
        merged = True
        action = "merge"
        used_admin = False

        def to_dict(self) -> dict[str, object]:
            return {
                "merged": True,
                "action": "merge",
                "used_admin": False,
                "detail": "merged",
            }

    class _FakeGitHubControl:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root

        def fetch_gate_snapshot(self, pr_ref: str) -> _FakeSnapshot:
            assert pr_ref == "https://github.com/org/repo/pull/42"
            return _FakeSnapshot()

        def merge_pr(
            self,
            pr_ref: str,
            *,
            required_checks_green: bool,
            allow_admin: bool,
            head_sha: str | None,
        ) -> _FakeMergeResult:
            assert pr_ref == "https://github.com/org/repo/pull/42"
            assert required_checks_green is True
            assert allow_admin is True
            assert head_sha == "a" * 40  # the snapshot's head, pinned
            return _FakeMergeResult()

    monkeypatch.setattr("aragora.swarm.tranche_queue.GitHubControl", _FakeGitHubControl)

    payload = harvest_tranche_queue(
        queue_path=queue_path,
        repo_root=tmp_path,
        execute_merge=True,
        allow_admin=True,
    )

    assert payload["mode"] == "tranche-queue-harvest"
    assert payload["queue_id"] == "overnight"
    assert payload["pr_counts"] == {"merged": 1}
    assert payload["executed_merges"] == [
        {
            "item_id": "issue-1046",
            "pr_url": "https://github.com/org/repo/pull/42",
            "branch": "codex/example-branch",
            "action": "merge",
            "used_admin": False,
        }
    ]
    assert payload["summary"] == {
        "total_items": 1,
        "prs_created": 1,
        "completed": 1,
        "needs_human": 0,
        "failed": 0,
    }
    assert payload["items"][0]["prs"][0]["snapshot_disposition"] == "merge_now"
    assert payload["items"][0]["prs"][0]["disposition"] == "merged"
    assert payload["items"][0]["summary_outcome"] == "merged"


def test_harvest_queue_summary_counts_needs_human_and_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)

    state = TrancheQueueRunState(queue_id="overnight", status=QUEUE_STATUS_COMPLETED)
    state.ensure_manifest(manifest)
    merged_item = state.item_states["issue-1046"]
    merged_item.status = QUEUE_ITEM_STATUS_COMPLETED
    merged_item.pr_urls = ["https://github.com/org/repo/pull/42"]
    needs_human_item = state.item_states["intake-docs"]
    needs_human_item.status = QUEUE_ITEM_STATUS_NEEDS_HUMAN
    failed_item = state.item_states["issue-1047"]
    failed_item.status = QUEUE_ITEM_STATUS_STOPPED
    failed_item.pr_urls = ["https://github.com/org/repo/pull/99"]
    state.save(queue_state_path_for_queue(queue_path))

    class _FakeSnapshot:
        def __init__(self, pr_url: str, *, disposition: str) -> None:
            self.pr_url = pr_url
            self.disposition = disposition
            self.required_checks_green = True
            self.head_branch = "codex/example-branch"

        def to_dict(self) -> dict[str, object]:
            return {
                "pr_url": self.pr_url,
                "state": "MERGED" if self.disposition == "merged" else "OPEN",
                "draft": False,
                "head_branch": self.head_branch,
                "base_branch": "main",
                "review_decision": "APPROVED",
                "merge_state_status": "CLEAN",
                "merge_commit_sha": "abc123" if self.disposition == "merged" else None,
                "required_checks": [],
                "advisory_checks": [],
                "required_checks_green": True,
                "required_checks_known": True,
                "required_checks_source": "ruleset",
                "disposition": self.disposition,
                "blocker_detail": None,
            }

    class _FakeGitHubControl:
        def __init__(self, *, repo_root: Path) -> None:
            self.repo_root = repo_root

        def fetch_gate_snapshot(self, pr_ref: str) -> _FakeSnapshot:
            if pr_ref == "https://github.com/org/repo/pull/42":
                return _FakeSnapshot(pr_ref, disposition="merged")
            raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr("aragora.swarm.tranche_queue.GitHubControl", _FakeGitHubControl)

    payload = harvest_tranche_queue(
        queue_path=queue_path,
        repo_root=tmp_path,
    )

    assert payload["pr_counts"] == {"merged": 1, "error": 1}
    assert payload["summary"] == {
        "total_items": 3,
        "prs_created": 2,
        "completed": 1,
        "needs_human": 1,
        "failed": 1,
    }
    assert [item["summary_outcome"] for item in payload["items"]] == [
        "merged",
        "needs_human",
        "failed",
    ]


def test_render_harvest_queue_summary_table_prints_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _render_tranche_queue_harvest_table(
        {
            "queue_id": "overnight",
            "status": "completed",
            "summary": {
                "total_items": 3,
                "prs_created": 2,
                "completed": 1,
                "needs_human": 1,
                "failed": 1,
            },
        }
    )

    output = capsys.readouterr().out
    assert "Tranche Queue Harvest (overnight)" in output
    assert "status=completed" in output

    metrics: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        label, value = parts
        if label in {"total items", "PRs created", "completed", "needs_human", "failed"}:
            metrics[label] = value

    assert metrics == {
        "total items": "3",
        "PRs created": "2",
        "completed": "1",
        "needs_human": "1",
        "failed": "1",
    }


def test_render_tranche_queue_status_prints_terminal_truth(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _render_tranche_queue_status(
        {
            "queue_id": "overnight",
            "status": "stopped",
            "current_item_id": "intake-docs",
            "elapsed_seconds": 95.0,
            "stop_reason": "driver_stopped",
            "counts": {"completed": 1, "needs_human": 1, "pending": 1},
            "terminal_counts": {"completed": 1, "needs_human": 1},
            "current_item": {
                "item_id": "intake-docs",
                "status": "needs_human",
                "next_action": "stop_and_replan",
                "blocking_question": "What should be fixed before this lane is rerun?",
                "pr_urls": ["https://example.test/pr/42"],
            },
            "items": [],
        }
    )

    output = capsys.readouterr().out
    assert "queue_id=overnight status=stopped current_item_id=intake-docs elapsed=1m 35s" in output
    assert "stop_reason=driver_stopped" in output
    assert "counts=completed=1, needs_human=1, pending=1" in output
    assert "terminal_counts=completed=1, needs_human=1" in output
    assert (
        "current_item next_action=stop_and_replan status=needs_human pr_urls=https://example.test/pr/42"
        in output
    )
    assert "current_item_blocker=What should be fixed before this lane is rerun?" in output


def test_tranche_queue_status_reads_pr_url_branch_and_elapsed(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    manifest_path = tmp_path / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-test\n", encoding="utf-8")

    started_at = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    finished_at = started_at + timedelta(minutes=5)
    state = TrancheQueueRunState(
        queue_id=manifest.queue_id,
        status=QUEUE_STATUS_RUNNING,
        started_at=started_at,
        updated_at=finished_at,
    )
    state.ensure_manifest(manifest)
    state.updated_at = finished_at
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
        manifest_id="tranche-test",
        manifest_path=str(manifest_path),
        pr_urls=["https://github.com/org/repo/pull/42"],
        started_at=started_at,
        updated_at=finished_at,
        finished_at=finished_at,
    )
    state.save(queue_state_path_for_queue(queue_path))

    TrancheRunState(
        manifest_id="tranche-test",
        status="completed",
        autonomy_mode="adaptive",
        lane_states={
            "lane-a": LaneRunState(
                lane_id="lane-a",
                status="completed",
                pr_url="https://github.com/org/repo/pull/42",
            )
        },
    ).save(manifest_path.with_name("run_state.yaml"))
    TrancheArtifactStore(repo_root=tmp_path).save(
        "tranche-test",
        TrancheLaneArtifact(
            lane_id="lane-a",
            source_ref="issue-1046",
            status="completed",
            metadata={"branch": "codex/issue-1046"},
        ),
    )

    payload = tranche_queue_status(queue_path=queue_path, repo_root=tmp_path)

    assert payload["mode"] == "tranche-queue-status"
    assert payload["status"] == QUEUE_STATUS_RUNNING
    assert payload["counts"] == {
        "completed": 1,
        "pending": 2,
    }
    assert payload["terminal_counts"] == {"completed": 1}
    assert payload["elapsed_seconds"] == 300.0
    assert payload["current_item"] is None
    issue = next(item for item in payload["items"] if item["item_id"] == "issue-1046")
    assert issue["phase"] == QUEUE_ITEM_PHASE_EXPLORED
    assert issue["next_action"] is None
    assert issue["pr_url"] == "https://github.com/org/repo/pull/42"
    assert issue["worker_branch"] == "codex/issue-1046"
    assert issue["worker_branches"] == ["codex/issue-1046"]
    assert issue["elapsed_seconds"] == 300.0


@pytest.mark.asyncio
async def test_explore_queue_persists_normalize_and_inspect_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [{"id": "intake-docs", "kind": "intake", "source": "bundles/docs.yaml"}],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    tranche_dir = tmp_path / ".aragora" / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    intake_path = tranche_dir / "intake_bundle.yaml"
    intake_path.write_text("objective: test\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    inspection_path = tranche_dir / "inspection.yaml"
    inspection_path.write_text("preflight_status: ready\n", encoding="utf-8")

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: {
            "manifest_id": "tranche-a",
            "intake_path": str(intake_path),
            "normalized_bundle_path": str(normalized_path),
            "manifest_path": str(manifest_path),
            "inspection_path": str(inspection_path),
            "tranche_dir": str(tranche_dir),
            "submission_status": "awaiting_confirmation",
            "inspection_status": "ready",
            "recommended_action": "design-review",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheQueueExecutor._bundle_for_item",
        lambda self, item, effective_autonomy_mode: {"objective": "test"},
    )

    async def fail_design_review(**kwargs):
        raise AssertionError("explore-queue should not run design review")

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fail_design_review)

    payload = await explore_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    item = payload["items"][0]
    assert payload["mode"] == "tranche-queue-explore"
    assert item["status"] == QUEUE_ITEM_STATUS_PENDING
    assert item["phase"] == QUEUE_ITEM_PHASE_EXPLORED
    assert item["next_action"] == "plan-queue"
    assert item["manifest_path"] == str(manifest_path)
    assert item["normalized_bundle_path"] == str(normalized_path)
    assert item["inspection_path"] == str(inspection_path)
    assert item["inspection_status"] == "ready"

    state = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
    persisted = state.item_states["intake-docs"]
    assert persisted.phase == QUEUE_ITEM_PHASE_EXPLORED
    assert persisted.manifest_path == str(manifest_path)
    assert persisted.normalized_bundle_path == str(normalized_path)
    assert persisted.inspection_path == str(inspection_path)


@pytest.mark.asyncio
async def test_plan_queue_marks_item_approved_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [{"id": "intake-docs", "kind": "intake", "source": "bundles/docs.yaml"}],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    tranche_dir = tmp_path / ".aragora" / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    intake_path = tranche_dir / "intake_bundle.yaml"
    intake_path.write_text("objective: test\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    inspection_path = tranche_dir / "inspection.yaml"
    inspection_path.write_text("preflight_status: ready\n", encoding="utf-8")

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: {
            "manifest_id": "tranche-a",
            "intake_path": str(intake_path),
            "normalized_bundle_path": str(normalized_path),
            "manifest_path": str(manifest_path),
            "inspection_path": str(inspection_path),
            "tranche_dir": str(tranche_dir),
            "submission_status": "awaiting_confirmation",
            "inspection_status": "ready",
            "recommended_action": "design-review",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheQueueExecutor._bundle_for_item",
        lambda self, item, effective_autonomy_mode: {"objective": "test"},
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.save_design_review",
        lambda *args, **kwargs: None,
    )

    async def fake_design_review(*, manifest, normalized_bundle, inspection):
        return {"recommendation": "approved", "record": {"recommendation": "approved"}}

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fake_design_review)

    payload = await plan_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    item = payload["items"][0]
    assert payload["mode"] == "tranche-queue-plan"
    assert item["status"] == QUEUE_ITEM_STATUS_PENDING
    assert item["phase"] == QUEUE_ITEM_PHASE_APPROVED
    assert item["next_action"] == "run-queue"
    assert item["design_review_recommendation"] == "approved"

    state = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
    persisted = state.item_states["intake-docs"]
    assert persisted.phase == QUEUE_ITEM_PHASE_APPROVED
    assert persisted.design_review_recommendation == "approved"


@pytest.mark.asyncio
async def test_plan_queue_blocks_initiative_manual_item_before_unattended_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [
                {
                    "id": "initiative-docs",
                    "kind": "intake",
                    "source": "bundles/docs.yaml",
                    "work_class": "initiative_manual",
                }
            ],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    tranche_dir = tmp_path / ".aragora" / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    intake_path = tranche_dir / "intake_bundle.yaml"
    intake_path.write_text("objective: test\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    inspection_path = tranche_dir / "inspection.yaml"
    inspection_path.write_text("preflight_status: ready\n", encoding="utf-8")

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: {
            "manifest_id": "tranche-a",
            "intake_path": str(intake_path),
            "normalized_bundle_path": str(normalized_path),
            "manifest_path": str(manifest_path),
            "inspection_path": str(inspection_path),
            "tranche_dir": str(tranche_dir),
            "submission_status": "awaiting_confirmation",
            "inspection_status": "ready",
            "recommended_action": "design-review",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheQueueExecutor._bundle_for_item",
        lambda self, item, effective_autonomy_mode: {"objective": "test"},
    )

    async def fail_design_review(**kwargs):
        raise AssertionError("initiative/manual items should stop before unattended design review")

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fail_design_review)

    payload = await plan_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    item = payload["items"][0]
    assert item["work_class"] == QUEUE_WORK_CLASS_INITIATIVE_MANUAL
    assert item["status"] == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert item["phase"] == QUEUE_ITEM_PHASE_EXPLORED
    assert item["blocked_reason"] == "initiative_manual_requires_operator_split"
    assert item["next_action"] == "plan-queue"
    assert item["admission"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_plan_queue_blocks_item_missing_verification_commands_after_design_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [{"id": "intake-docs", "kind": "intake", "source": "bundles/docs.yaml"}],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    tranche_dir = tmp_path / ".aragora" / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    intake_path = tranche_dir / "intake_bundle.yaml"
    intake_path.write_text("objective: test\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    inspection_path = tranche_dir / "inspection.yaml"
    inspection_path.write_text("preflight_status: ready\n", encoding="utf-8")

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: {
            "manifest_id": "tranche-a",
            "intake_path": str(intake_path),
            "normalized_bundle_path": str(normalized_path),
            "manifest_path": str(manifest_path),
            "inspection_path": str(inspection_path),
            "tranche_dir": str(tranche_dir),
            "submission_status": "awaiting_confirmation",
            "inspection_status": "ready",
            "recommended_action": "design-review",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheQueueExecutor._bundle_for_item",
        lambda self, item, effective_autonomy_mode: {"objective": "test"},
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.save_design_review",
        lambda *args, **kwargs: None,
    )

    async def fake_design_review(*, manifest, normalized_bundle, inspection):
        return {"recommendation": "approved", "record": {"recommendation": "approved"}}

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fake_design_review)

    payload = await plan_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    item = payload["items"][0]
    assert item["work_class"] == QUEUE_WORK_CLASS_BOUNDED_FEATURE
    assert item["status"] == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert item["phase"] == QUEUE_ITEM_PHASE_PLANNED
    assert item["blocked_reason"] == "queue_item_missing_verification_commands"
    assert item["next_action"] == "plan-queue"
    assert item["admission"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_run_queue_does_not_dispatch_planned_but_unapproved_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [{"id": "intake-docs", "kind": "intake", "source": "bundle.yaml"}],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    tranche_dir = tmp_path / ".aragora" / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    state = TrancheQueueRunState(queue_id=manifest.queue_id)
    state.ensure_manifest(manifest)
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_PENDING,
        phase=QUEUE_ITEM_PHASE_PLANNED,
        manifest_id="tranche-a",
        manifest_path=str(manifest_path),
        design_review_recommendation="awaiting_confirmation",
    )
    state.save(queue_state_path_for_queue(queue_path))

    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )

    async def fail_drive_manifest(**kwargs):
        raise AssertionError("run-queue must not dispatch unapproved items")

    monkeypatch.setattr(executor, "_drive_manifest", fail_drive_manifest)

    payload = await executor.run()

    assert payload["status"] == QUEUE_STATUS_COMPLETED
    assert payload["counts"] == {"needs_human": 1}
    item = payload["items"][0]
    assert item["status"] == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert item["phase"] == QUEUE_ITEM_PHASE_PLANNED
    assert item["next_action"] == "plan-queue"


def test_tranche_queue_status_surfaces_blocked_replan_next_action(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [{"id": "intake-docs", "kind": "intake", "source": "bundle.yaml"}],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")

    state = TrancheQueueRunState(queue_id=manifest.queue_id, status=QUEUE_STATUS_PENDING)
    state.ensure_manifest(manifest)
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_NEEDS_HUMAN,
        phase=QUEUE_ITEM_PHASE_EXPLORED,
        manifest_path=str(tmp_path / "tranche.yaml"),
        recommended_action="stop_and_replan",
        inspection_status="blocked",
    )
    state.save(queue_state_path_for_queue(queue_path))

    payload = tranche_queue_status(queue_path=queue_path, repo_root=tmp_path)

    item = payload["items"][0]
    assert item["status"] == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert item["phase"] == QUEUE_ITEM_PHASE_EXPLORED
    assert item["next_action"] == "stop_and_replan"


@pytest.mark.asyncio
async def test_process_item_resumes_legacy_approved_manifest_without_resubmitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = TrancheQueueManifest.from_dict(
        {
            "queue_id": "overnight",
            "items": [{"id": "intake-docs", "kind": "intake", "source": "bundle.yaml"}],
        }
    )
    queue_path.write_text(manifest.to_yaml(), encoding="utf-8")
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = manifest.items[0]
    tranche_dir = tmp_path / ".aragora" / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
""".strip()
        + "\n",
        encoding="utf-8",
    )

    item_state = TrancheQueueItemRunState(
        item_id=item.item_id,
        manifest_id="tranche-a",
        manifest_path=str(manifest_path),
        normalized_bundle_path=str(normalized_path),
        phase=QUEUE_ITEM_PHASE_APPROVED,
        design_review_recommendation="approved",
    )

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: pytest.fail("approved legacy manifest should not resubmit"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )

    async def fail_design_review(**kwargs):
        raise AssertionError("approved legacy manifest should not rerun design review")

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fail_design_review)

    async def fake_drive_manifest(*, item, item_state, manifest_path, tranche_manifest, deadline):
        item_state.status = QUEUE_ITEM_STATUS_COMPLETED
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_drive_manifest", fake_drive_manifest)

    result = await executor._process_item(
        manifest=manifest,
        item=item,
        item_state=item_state,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    assert result is None
    assert item_state.status == QUEUE_ITEM_STATUS_COMPLETED
    assert item_state.phase == QUEUE_ITEM_PHASE_APPROVED


def test_compile_queue_records_proposal_for_synthesize_doc_source(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.yaml"
    output_path = tmp_path / "overnight.yaml"
    sources_path.write_text(
        """
queue_id: overnight
sources:
  - id: goals-doc
    kind: doc
    mode: synthesize
    path: goals.md
    merge_class: manual
""".strip(),
        encoding="utf-8",
    )

    payload = compile_tranche_queue(
        sources_path=sources_path,
        output_path=output_path,
        repo_root=tmp_path,
    )

    assert payload["item_count"] == 0
    assert payload["proposal_count"] == 1
    assert payload["status"] == "needs_human"
    assert payload["wrote_queue"] is False
    assert payload["proposals"][0]["status"] == "needs_human"
    assert "not executable yet" in payload["proposals"][0]["reason"]
    assert payload["detail"] == "All sources produced proposals. Review proposals before running."
    assert output_path.exists() is False


def test_compile_queue_records_proposal_for_missing_execute_doc_source(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.yaml"
    output_path = tmp_path / "overnight.yaml"
    sources_path.write_text(
        """
queue_id: overnight
sources:
  - id: missing-doc
    kind: doc
    mode: execute
    path: does-not-exist.md
    objective: Ship the missing doc work.
    merge_class: manual
""".strip(),
        encoding="utf-8",
    )

    payload = compile_tranche_queue(
        sources_path=sources_path,
        output_path=output_path,
        repo_root=tmp_path,
    )

    assert payload["item_count"] == 0
    assert payload["proposal_count"] == 1
    assert payload["status"] == "needs_human"
    assert payload["wrote_queue"] is False
    assert payload["proposals"][0]["reason"] == "Execute doc source path was not found."
    assert payload["detail"] == "All sources produced proposals. Review proposals before running."
    assert output_path.exists() is False


def test_compile_queue_propagates_verification_commands_to_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification commands from sources must flow through to compiled queue items."""
    sources_path = tmp_path / "sources.yaml"
    output_path = tmp_path / "overnight.yaml"
    sources_path.write_text(
        """
queue_id: overnight
sources:
  - id: test-issue
    kind: issue
    mode: execute
    url: https://github.com/org/repo/issues/42
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
    merge_class: manual
""".strip(),
        encoding="utf-8",
    )

    payload = compile_tranche_queue(
        sources_path=sources_path,
        output_path=output_path,
        repo_root=tmp_path,
    )

    assert payload["item_count"] == 1
    manifest = TrancheQueueManifest.load(output_path)
    item = manifest.items[0]
    assert item.verification_commands == ["python3 -m pytest tests/cli/test_setup.py -q"]


def test_compile_queue_expands_issue_query_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources_path = tmp_path / "sources.yaml"
    output_path = tmp_path / "overnight.yaml"
    sources_path.write_text(
        """
queue_id: overnight
sources:
  - id: autonomy-query
    kind: issue_query
    mode: execute
    query: "label:autonomy sort:created-asc"
    repo: synaptent/aragora
    limit: 2
""".strip(),
        encoding="utf-8",
    )

    def fake_run(cmd, text, capture_output, timeout, check):
        assert cmd[:3] == ["gh", "issue", "list"]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "number": 1046,
                        "title": "A",
                        "url": "https://github.com/org/repo/issues/1046",
                    },
                    {
                        "number": 1047,
                        "title": "B",
                        "url": "https://github.com/org/repo/issues/1047",
                    },
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("aragora.swarm.tranche_queue.subprocess.run", fake_run)

    payload = compile_tranche_queue(
        sources_path=sources_path,
        output_path=output_path,
        repo_root=tmp_path,
    )

    assert payload["item_count"] == 2
    manifest = TrancheQueueManifest.load(output_path)
    assert [item.kind for item in manifest.items] == ["issue", "issue"]
    assert all(item.work_class == QUEUE_WORK_CLASS_HARVEST for item in manifest.items)
    assert all(item.max_lanes == 1 for item in manifest.items)
    assert manifest.items[0].source == "https://github.com/org/repo/issues/1046"
    assert manifest.items[1].source == "https://github.com/org/repo/issues/1047"


def test_queue_item_defaults_to_single_lane() -> None:
    item = TrancheQueueItem.from_dict(
        {
            "id": "issue-1046",
            "kind": "issue",
            "source": "https://github.com/org/repo/issues/1046",
            "merge_class": "manual",
        }
    )

    assert item.max_lanes == 1
    assert item.work_class == QUEUE_WORK_CLASS_HARVEST


def test_legacy_approved_queue_state_without_phase_loads_as_execution_ready() -> None:
    item_state = TrancheQueueItemRunState.from_dict(
        {
            "item_id": "intake-docs",
            "manifest_path": "/tmp/tranche.yaml",
            "design_review_recommendation": "approved",
        }
    )

    assert item_state.phase == QUEUE_ITEM_PHASE_APPROVED


def test_low_risk_queue_item_keeps_fire_and_forget_and_sets_auto_merge_policy(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    queue_path.write_text(
        "queue_id: overnight\nitems:\n- id: one\n  kind: intake\n  source: bundle.yaml\n"
    )
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(
        "objective: test\ncandidate_lanes:\n- lane_id: lane-a\n  owner_role: critical_path_engineer\n",
        encoding="utf-8",
    )
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = TrancheQueueItem(
        item_id="one",
        kind="intake",
        source="bundle.yaml",
        merge_class="low_risk",
        autonomy_mode="fire_and_forget",
    )

    effective_autonomy, downgraded = _resolve_queue_autonomy_mode(
        item.autonomy_mode,
        merge_class=item.merge_class,
    )
    bundle = executor._bundle_from_intake_item(item, effective_autonomy_mode=effective_autonomy)

    assert effective_autonomy == "fire_and_forget"
    assert downgraded is False
    assert bundle["autonomy_mode"] == "fire_and_forget"
    assert bundle["candidate_lanes"][0]["merge_policy"] == "auto"


def test_manual_queue_item_downgrades_fire_and_forget_and_keeps_manual_policy(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    queue_path.write_text(
        "queue_id: overnight\nitems:\n- id: one\n  kind: intake\n  source: bundle.yaml\n"
    )
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(
        "objective: test\ncandidate_lanes:\n- lane_id: lane-a\n  owner_role: critical_path_engineer\n",
        encoding="utf-8",
    )
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = TrancheQueueItem(
        item_id="one",
        kind="intake",
        source="bundle.yaml",
        merge_class="manual",
        autonomy_mode="fire_and_forget",
    )

    effective_autonomy, downgraded = _resolve_queue_autonomy_mode(
        item.autonomy_mode,
        merge_class=item.merge_class,
    )
    bundle = executor._bundle_from_intake_item(item, effective_autonomy_mode=effective_autonomy)

    assert effective_autonomy == "adaptive"
    assert downgraded is True
    assert bundle["autonomy_mode"] == "adaptive"
    assert bundle["candidate_lanes"][0]["merge_policy"] == _queue_merge_policy(merge_class="manual")


def test_issue_queue_item_collapses_multi_lane_planner_output_to_single_fallback_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    queue_path.write_text(
        "queue_id: overnight\nitems:\n- id: issue-one\n  kind: issue\n  source: https://github.com/org/repo/issues/1046\n",
        encoding="utf-8",
    )
    executor = TrancheQueueExecutor(
        queue_path=queue_path,
        repo_root=tmp_path,
        worker_model="claude",
        review_model="claude",
        enforce_cross_model_review=False,
    )
    item = TrancheQueueItem(
        item_id="issue-one",
        kind="issue",
        source="https://github.com/org/repo/issues/1046",
        merge_class="manual",
        max_lanes=1,
        objective_override="Implement one CLI-only slice.",
        allowed_write_scope=["aragora/cli/**", "tests/cli/**"],
        autonomy_mode="adaptive",
    )

    class _FakePlanner:
        def plan_from_items(self, items, source_kind, source_ref):
            assert source_kind == "queue_issue"
            assert source_ref == "https://github.com/org/repo/issues/1046"
            return SimpleNamespace(projects=["proj-1", "proj-2"])

    monkeypatch.setattr(executor, "_planner", lambda: _FakePlanner())
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue._fetch_issue_payload",
        lambda source: {
            "number": 1046,
            "title": "Close the product loop",
            "body": "CLI-first bounded issue body.",
            "url": "https://github.com/org/repo/issues/1046",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.campaign_projects_to_candidate_lanes",
        lambda projects, planner: [
            {
                "lane_id": "proj-001",
                "title": "First planner lane",
                "prompt": "planner lane 1",
                "owner_role": "implementation_engineer",
                "allowed_write_scope": ["aragora/cli/**"],
                "dependencies": [],
                "target_agent": None,
                "review_model": None,
            },
            {
                "lane_id": "proj-002",
                "title": "Second planner lane",
                "prompt": "planner lane 2",
                "owner_role": "implementation_engineer",
                "allowed_write_scope": ["aragora/cli/**"],
                "dependencies": [],
                "target_agent": None,
                "review_model": None,
            },
        ],
    )

    bundle = executor._bundle_from_issue_item(item, effective_autonomy_mode="adaptive")

    assert bundle["autonomy_mode"] == "adaptive"
    assert len(bundle["candidate_lanes"]) == 1
    lane = bundle["candidate_lanes"][0]
    assert lane["lane_id"] == "issue-one"
    assert lane["merge_policy"] == "manual"
    assert lane["queue_item_id"] == "issue-one"
    assert lane["allowed_write_scope"] == ["aragora/cli/**", "tests/cli/**"]
    assert lane["target_agent"] == "claude"
    assert lane["review_model"] == "claude"
    assert lane["use_managed_session_script"] is False
    assert "Source issue context" in lane["prompt"]


def test_intake_queue_item_limits_candidate_lanes_to_max_lanes(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    queue_path.write_text(
        "queue_id: overnight\nitems:\n- id: intake\n  kind: intake\n  source: bundle.yaml\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(
        """
objective: test
candidate_lanes:
  - lane_id: lane-a
    title: Lane A
    prompt: Implement lane A
    owner_role: implementation_engineer
  - lane_id: lane-b
    title: Lane B
    prompt: Implement lane B
    owner_role: implementation_engineer
    dependencies:
      - lane-a
""".strip(),
        encoding="utf-8",
    )
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = TrancheQueueItem(
        item_id="intake",
        kind="intake",
        source="bundle.yaml",
        merge_class="manual",
        max_lanes=1,
    )

    bundle = executor._bundle_from_intake_item(item, effective_autonomy_mode="adaptive")

    assert bundle["max_lanes"] == 1
    assert len(bundle["candidate_lanes"]) == 1
    assert bundle["candidate_lanes"][0]["lane_id"] == "lane-a"


def test_queue_runner_keeps_safe_single_lane_default_even_when_item_allows_two(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    queue_path.write_text(
        "queue_id: overnight\nitems:\n- id: intake\n  kind: intake\n  source: bundle.yaml\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(
        """
objective: test
candidate_lanes:
  - lane_id: lane-a
    title: Lane A
    prompt: Implement lane A
    owner_role: implementation_engineer
  - lane_id: lane-b
    title: Lane B
    prompt: Implement lane B
    owner_role: implementation_engineer
""".strip(),
        encoding="utf-8",
    )
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = TrancheQueueItem(
        item_id="intake",
        kind="intake",
        source="bundle.yaml",
        merge_class="manual",
        max_lanes=2,
    )

    bundle = executor._bundle_for_item(item, effective_autonomy_mode="adaptive")

    assert bundle["max_lanes"] == 1
    assert [lane["lane_id"] for lane in bundle["candidate_lanes"]] == ["lane-a"]


def test_queue_runner_allows_two_lanes_when_parallel_cap_is_enabled(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    queue_path.write_text(
        "queue_id: overnight\nitems:\n- id: intake\n  kind: intake\n  source: bundle.yaml\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(
        """
objective: test
candidate_lanes:
  - lane_id: lane-a
    title: Lane A
    prompt: Implement lane A
    owner_role: implementation_engineer
  - lane_id: lane-b
    title: Lane B
    prompt: Implement lane B
    owner_role: implementation_engineer
""".strip(),
        encoding="utf-8",
    )
    executor = TrancheQueueExecutor(
        queue_path=queue_path,
        repo_root=tmp_path,
        max_parallel_lanes=2,
    )
    item = TrancheQueueItem(
        item_id="intake",
        kind="intake",
        source="bundle.yaml",
        merge_class="manual",
        max_lanes=2,
    )

    bundle = executor._bundle_for_item(item, effective_autonomy_mode="adaptive")

    assert bundle["max_lanes"] == 2
    assert [lane["lane_id"] for lane in bundle["candidate_lanes"]] == ["lane-a", "lane-b"]


@pytest.mark.asyncio
async def test_run_queue_processes_items_sequentially_and_continues_after_needs_human(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)

    seen: list[str] = []

    async def fake_process_item(*, manifest, item, item_state, deadline):
        seen.append(item.item_id)
        if item.item_id == "issue-1046":
            item_state.status = QUEUE_ITEM_STATUS_COMPLETED
        elif item.item_id == "intake-docs":
            item_state.status = QUEUE_ITEM_STATUS_NEEDS_HUMAN
            item_state.findings.append("Missing source material.")
        else:
            item_state.status = QUEUE_ITEM_STATUS_COMPLETED
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_process_item", fake_process_item)

    result = await executor.run()

    assert seen == ["issue-1046", "intake-docs", "issue-1047"]
    assert result["status"] == QUEUE_STATUS_COMPLETED
    assert result["counts"] == {"completed": 2, "needs_human": 1}

    state = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
    assert state.item_states["issue-1046"].status == QUEUE_ITEM_STATUS_COMPLETED
    assert state.item_states["intake-docs"].status == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert state.item_states["issue-1047"].status == QUEUE_ITEM_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_run_queue_process_item_exception_marks_item_needs_human_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)

    seen: list[str] = []

    async def fake_process_item(*, manifest, item, item_state, deadline):
        seen.append(item.item_id)
        if item.item_id == "issue-1046":
            raise FileNotFoundError("missing tranche dir")
        item_state.status = QUEUE_ITEM_STATUS_COMPLETED
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_process_item", fake_process_item)

    result = await executor.run()

    assert seen == ["issue-1046", "intake-docs", "issue-1047"]
    assert result["status"] == QUEUE_STATUS_COMPLETED
    assert result["counts"] == {"completed": 2, "needs_human": 1}

    state = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
    crashed = state.item_states["issue-1046"]
    assert crashed.status == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert crashed.stop_reason == "processing_error"
    assert crashed.findings == ["Queue item processing failed. Check logs for detail."]
    assert crashed.result["processing_error"] == {"error_type": "FileNotFoundError"}


@pytest.mark.asyncio
async def test_run_queue_resumes_from_existing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    state_path = queue_state_path_for_queue(queue_path)
    state = TrancheQueueRunState(queue_id=manifest.queue_id)
    state.ensure_manifest(manifest)
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
    )
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_PENDING,
    )
    state.item_states["issue-1047"] = TrancheQueueItemRunState(
        item_id="issue-1047",
        status=QUEUE_ITEM_STATUS_PENDING,
    )
    state.save(state_path)

    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    seen: list[str] = []

    async def fake_process_item(*, manifest, item, item_state, deadline):
        seen.append(item.item_id)
        item_state.status = QUEUE_ITEM_STATUS_COMPLETED
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_process_item", fake_process_item)

    result = await executor.run()

    assert seen == ["intake-docs", "issue-1047"]
    assert result["status"] == QUEUE_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_process_item_persists_manifest_path_before_drive_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = manifest.items[0]
    item_state = TrancheQueueItemRunState(item_id=item.item_id)

    queue_state = TrancheQueueRunState(queue_id=manifest.queue_id, status="running")
    queue_state.ensure_manifest(manifest)
    queue_state.current_item_id = item.item_id
    queue_state.save(queue_state_path_for_queue(queue_path))

    tranche_dir = tmp_path / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        executor,
        "_bundle_for_item",
        lambda item, effective_autonomy_mode: {"objective": "test"},
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: {
            "manifest_id": "tranche-a",
            "manifest_path": str(manifest_path),
            "tranche_dir": str(tranche_dir),
            "submission_status": "submitted",
            "inspection_status": "ready",
            "recommended_action": "run",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )

    async def fake_design_review(*, manifest, normalized_bundle, inspection):
        return {"recommendation": "approved", "record": {"recommendation": "approved"}}

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fake_design_review)
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.save_design_review", lambda *args, **kwargs: None
    )

    async def fake_drive_manifest(*, item, item_state, manifest_path, tranche_manifest, deadline):
        state = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
        persisted = state.item_states[item.item_id]
        assert persisted.status == "running"
        assert persisted.manifest_id == "tranche-a"
        assert persisted.manifest_path == str(manifest_path)
        assert state.current_item_id == item.item_id
        item_state.status = QUEUE_ITEM_STATUS_COMPLETED
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_drive_manifest", fake_drive_manifest)

    result = await executor._process_item(
        manifest=manifest,
        item=item,
        item_state=item_state,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    assert result is None
    assert item_state.status == QUEUE_ITEM_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_process_item_records_design_review_blocker_when_confirmation_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    item = manifest.items[0]
    item_state = TrancheQueueItemRunState(item_id=item.item_id)

    tranche_dir = tmp_path / "tranches" / "tranche-a"
    tranche_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tranche_dir / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-a\n", encoding="utf-8")
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    normalized_path.write_text(
        """
lanes:
  - lane_id: lane-a
    allowed_write_scope:
      - aragora/cli/**
    verification_commands:
      - python3 -m pytest tests/cli/test_setup.py -q
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        executor,
        "_bundle_for_item",
        lambda item, effective_autonomy_mode: {"objective": "test"},
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.submit_intake_bundle",
        lambda *args, **kwargs: {
            "manifest_id": "tranche-a",
            "manifest_path": str(manifest_path),
            "tranche_dir": str(tranche_dir),
            "submission_status": "submitted",
            "inspection_status": "ready",
            "recommended_action": "design-review",
        },
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_manifest",
        lambda path: SimpleNamespace(manifest_id="tranche-a"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.TrancheInspector",
        lambda repo_root: SimpleNamespace(
            inspect=lambda tranche_manifest: {"preflight_status": "ready"}
        ),
    )

    async def fake_design_review(*, manifest, normalized_bundle, inspection):
        return {
            "recommendation": "awaiting_confirmation",
            "unresolved_assumptions": ["Confirm operator approval sequencing."],
            "record": {
                "manifest_id": "tranche-a",
                "status": "awaiting_confirmation",
                "recommendation": "awaiting_confirmation",
                "unresolved_assumptions": ["Confirm operator approval sequencing."],
            },
        }

    monkeypatch.setattr("aragora.swarm.tranche_queue.run_design_review", fake_design_review)
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.save_design_review", lambda *args, **kwargs: None
    )

    result = await executor._process_item(
        manifest=manifest,
        item=item,
        item_state=item_state,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    assert result is None
    assert item_state.status == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert item_state.stop_reason == "awaiting_confirmation"
    assert item_state.blocked_reason == "design_review_awaiting_confirmation"
    assert (
        item_state.blocking_question
        == "Can you confirm this design assumption before rerunning the lane: Confirm operator approval sequencing?"
    )
    assert item_state.result["blocker"]["reason"] == "design_review_awaiting_confirmation"
    assert "awaiting_confirmation" in item_state.result["design_review"]["recommendation"]


@pytest.mark.asyncio
async def test_run_queue_needs_human_does_not_count_toward_consecutive_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    _write_queue(queue_path)
    executor = TrancheQueueExecutor(
        queue_path=queue_path,
        repo_root=tmp_path,
        max_consecutive_failures=2,
    )
    seen: list[str] = []

    async def fake_process_item(*, manifest, item, item_state, deadline):
        seen.append(item.item_id)
        item_state.status = QUEUE_ITEM_STATUS_NEEDS_HUMAN
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_process_item", fake_process_item)

    result = await executor.run()

    assert seen == ["issue-1046", "intake-docs", "issue-1047"]
    assert result["status"] == QUEUE_STATUS_COMPLETED
    assert result["counts"]["needs_human"] == 3
    assert result["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_run_queue_stops_after_configured_consecutive_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    _write_queue(queue_path)
    executor = TrancheQueueExecutor(
        queue_path=queue_path,
        repo_root=tmp_path,
        max_consecutive_failures=2,
    )
    seen: list[str] = []

    async def fake_process_item(*, manifest, item, item_state, deadline):
        seen.append(item.item_id)
        item_state.status = "stopped"
        item_state.finished_at = item_state.updated_at = item_state.started_at
        return None

    monkeypatch.setattr(executor, "_process_item", fake_process_item)

    result = await executor.run()

    assert seen == ["issue-1046", "intake-docs"]
    assert result["status"] == QUEUE_STATUS_STOPPED
    assert result["stop_reason"] == "max_consecutive_failures"
    assert result["counts"]["stopped"] == 2
    assert result["counts"]["pending"] == 1


def test_reconcile_queue_reports_truthful_counts(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    state = TrancheQueueRunState(queue_id=manifest.queue_id, status="running")
    state.ensure_manifest(manifest)
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
    )
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_NEEDS_HUMAN,
        findings=["Missing source material."],
    )
    state.item_states["issue-1047"] = TrancheQueueItemRunState(
        item_id="issue-1047",
        status=QUEUE_ITEM_STATUS_PENDING,
    )
    state.save(queue_state_path_for_queue(queue_path))

    payload = reconcile_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    assert payload["status"] == QUEUE_STATUS_STOPPED
    assert payload["stop_reason"] == "driver_stopped"
    assert payload["current_item_id"] is None
    assert payload["counts"] == {"completed": 1, "needs_human": 1, "pending": 1}
    assert payload["terminal_counts"] == {"completed": 1, "needs_human": 1}
    assert payload["items"][1]["findings"] == ["Missing source material."]


def test_tranche_queue_status_surfaces_current_item_truth(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    started_at = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    updated_at = started_at + timedelta(minutes=2)
    state = TrancheQueueRunState(
        queue_id=manifest.queue_id,
        status=QUEUE_STATUS_STOPPED,
        current_item_id="intake-docs",
        stop_reason="driver_stopped",
        started_at=started_at,
        updated_at=updated_at,
    )
    state.ensure_manifest(manifest)
    state.updated_at = updated_at
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
    )
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_NEEDS_HUMAN,
        phase=QUEUE_ITEM_PHASE_EXPLORED,
        stop_reason="preflight_blocked",
        blocked_reason="stop_and_replan",
        blocking_question="Which prerequisite should be fixed before rerunning this item?",
        pr_urls=["https://example.test/pr/9"],
        started_at=started_at,
        updated_at=updated_at,
    )
    state.item_states["issue-1047"] = TrancheQueueItemRunState(
        item_id="issue-1047",
        status=QUEUE_ITEM_STATUS_STOPPED,
        stop_reason="processing_error",
    )
    state.save(queue_state_path_for_queue(queue_path))

    payload = tranche_queue_status(queue_path=queue_path, repo_root=tmp_path)

    assert payload["stop_reason"] == "driver_stopped"
    assert payload["elapsed_seconds"] == 120.0
    assert payload["terminal_counts"] == {
        "completed": 1,
        "needs_human": 1,
        "stopped": 1,
    }
    current = payload["current_item"]
    assert current is not None
    assert current["item_id"] == "intake-docs"
    assert current["status"] == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert (
        current["blocking_question"]
        == "Which prerequisite should be fixed before rerunning this item?"
    )
    assert current["pr_urls"] == ["https://example.test/pr/9"]
    assert current["elapsed_seconds"] == 120.0


def test_tranche_queue_status_nulls_stale_current_item_payload(tmp_path: Path) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    state = TrancheQueueRunState(
        queue_id=manifest.queue_id,
        status=QUEUE_STATUS_STOPPED,
        current_item_id="missing",
        stop_reason="driver_stopped",
    )
    state.ensure_manifest(manifest)
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
    )
    state.save(queue_state_path_for_queue(queue_path))

    payload = tranche_queue_status(queue_path=queue_path, repo_root=tmp_path)

    assert payload["current_item_id"] == "missing"
    assert payload["current_item"] is None


def test_reconcile_queue_terminalizes_stale_running_item_and_stops_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    manifest_path = tmp_path / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-test\n", encoding="utf-8")
    state = TrancheQueueRunState(
        queue_id=manifest.queue_id,
        status=QUEUE_STATUS_RUNNING,
        current_item_id="intake-docs",
    )
    state.ensure_manifest(manifest)
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
    )
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_RUNNING,
        manifest_path=str(manifest_path),
        tranche_status="running",
    )
    state.item_states["issue-1047"] = TrancheQueueItemRunState(
        item_id="issue-1047",
        status=QUEUE_ITEM_STATUS_PENDING,
    )
    state.save(queue_state_path_for_queue(queue_path))

    class _FakeTrancheState:
        def __init__(self, status: str, *, pr_url: str | None = None) -> None:
            self.status = status
            lane = SimpleNamespace(pr_url=pr_url)
            self.lane_states = {"lane-a": lane}

        def to_dict(self) -> dict[str, object]:
            return {
                "status": self.status,
                "lane_states": {
                    lane_id: {"pr_url": lane_state.pr_url}
                    for lane_id, lane_state in self.lane_states.items()
                },
            }

        def save(self, path: str | Path) -> None:
            Path(path).write_text("status: completed\n", encoding="utf-8")

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_run_state",
        lambda _: _FakeTrancheState("running"),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.refresh_tranche_state",
        lambda current, **kwargs: _FakeTrancheState(
            "completed", pr_url="https://example.test/pr/1"
        ),
    )

    payload = reconcile_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    assert payload["status"] == QUEUE_STATUS_STOPPED
    assert payload["stop_reason"] == "driver_stopped"
    assert payload["current_item_id"] is None
    assert payload["counts"] == {"completed": 2, "pending": 1}
    intake = next(item for item in payload["items"] if item["item_id"] == "intake-docs")
    assert intake["status"] == QUEUE_ITEM_STATUS_COMPLETED
    assert intake["tranche_status"] == "completed"
    assert intake["pr_urls"] == ["https://example.test/pr/1"]

    repaired = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
    assert repaired.status == QUEUE_STATUS_STOPPED
    assert repaired.stop_reason == "driver_stopped"
    assert repaired.current_item_id is None
    assert repaired.item_states["intake-docs"].status == QUEUE_ITEM_STATUS_COMPLETED


def test_reconcile_queue_surfaces_blocker_context_from_tranche_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    manifest_path = tmp_path / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-test\n", encoding="utf-8")
    state = TrancheQueueRunState(
        queue_id=manifest.queue_id,
        status=QUEUE_STATUS_RUNNING,
        current_item_id="intake-docs",
    )
    state.ensure_manifest(manifest)
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_RUNNING,
        manifest_path=str(manifest_path),
        tranche_status="running",
    )
    state.save(queue_state_path_for_queue(queue_path))

    refreshed = TrancheRunState(
        manifest_id="tranche-test",
        status=TRANCHE_STATUS_NEEDS_HUMAN,
        autonomy_mode="adaptive",
        lane_states={
            "lane-a": LaneRunState(
                lane_id="lane-a",
                status=LANE_STATUS_NEEDS_HUMAN,
            )
        },
    )
    artifact = TrancheLaneArtifact(
        lane_id="lane-a",
        source_ref="issue-1046",
        status="needs_human",
        blocked_reason="required_checks_pending",
        blocking_question=(
            "Which pending required check should complete before this lane is merged or rerun?"
        ),
    )
    from aragora.swarm.tranche import TrancheArtifactStore

    TrancheArtifactStore(repo_root=tmp_path).save("tranche-test", artifact)

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_run_state",
        lambda _: refreshed,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.refresh_tranche_state",
        lambda current, **kwargs: refreshed,
    )

    payload = reconcile_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    assert payload["status"] == QUEUE_STATUS_STOPPED
    intake = next(item for item in payload["items"] if item["item_id"] == "intake-docs")
    assert intake["status"] == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert intake["blocked_reason"] == "required_checks_pending"
    assert (
        intake["blocking_question"]
        == "Which pending required check should complete before this lane is merged or rerun?"
    )
    assert intake["blocking_lane_id"] == "lane-a"

    repaired = TrancheQueueRunState.load(queue_state_path_for_queue(queue_path), manifest=manifest)
    assert repaired.item_states["intake-docs"].blocked_reason == "required_checks_pending"
    assert repaired.item_states["intake-docs"].blocking_lane_id == "lane-a"


def test_harvest_queue_preserves_needs_human_truth(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    manifest = _write_queue(queue_path)
    started_at = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    updated_at = started_at + timedelta(minutes=3)
    state = TrancheQueueRunState(
        queue_id=manifest.queue_id,
        status=QUEUE_STATUS_STOPPED,
        stop_reason="driver_stopped",
        current_item_id="intake-docs",
        started_at=started_at,
        updated_at=updated_at,
    )
    state.ensure_manifest(manifest)
    state.updated_at = updated_at
    state.item_states["issue-1046"] = TrancheQueueItemRunState(
        item_id="issue-1046",
        status=QUEUE_ITEM_STATUS_COMPLETED,
    )
    state.item_states["intake-docs"] = TrancheQueueItemRunState(
        item_id="intake-docs",
        status=QUEUE_ITEM_STATUS_NEEDS_HUMAN,
        phase=QUEUE_ITEM_PHASE_PLANNED,
        stop_reason="awaiting_confirmation",
        blocked_reason="design_review_awaiting_confirmation",
        blocking_question="Can you confirm the design assumption before rerunning the lane?",
        started_at=started_at,
        updated_at=updated_at,
    )
    state.item_states["issue-1047"] = TrancheQueueItemRunState(
        item_id="issue-1047",
        status=QUEUE_ITEM_STATUS_STOPPED,
        stop_reason="processing_error",
    )
    state.save(queue_state_path_for_queue(queue_path))

    payload = harvest_tranche_queue(queue_path=queue_path, repo_root=tmp_path)

    assert payload["status"] == QUEUE_STATUS_STOPPED
    assert payload["stop_reason"] == "driver_stopped"
    assert payload["current_item_id"] == "intake-docs"
    assert payload["terminal_counts"] == {
        "completed": 1,
        "needs_human": 1,
        "stopped": 1,
    }
    assert payload["elapsed_seconds"] == 180.0
    current = payload["current_item"]
    assert current is not None
    assert current["item_id"] == "intake-docs"
    intake = next(item for item in payload["items"] if item["item_id"] == "intake-docs")
    assert intake["summary_outcome"] == "needs_human"
    assert intake["stop_reason"] == "awaiting_confirmation"
    assert intake["blocked_reason"] == "design_review_awaiting_confirmation"
    assert (
        intake["blocking_question"]
        == "Can you confirm the design assumption before rerunning the lane?"
    )
    assert intake["pr_url"] is None
    assert intake["pr_urls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("systemic_reason", "expected_stop_reason"),
    [
        ("reviewer_routing_unavailable", "reviewer_routing_unavailable"),
        ("controller_publication_unavailable", "controller_publication_unavailable"),
        ("time_limit_exceeded", "time_limit_exceeded"),
    ],
)
async def test_run_queue_stops_on_systemic_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    systemic_reason: str,
    expected_stop_reason: str,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)

    async def fake_process_item(*, manifest, item, item_state, deadline):
        item_state.status = "stopped"
        item_state.finished_at = item_state.updated_at = item_state.started_at
        item_state.stop_reason = systemic_reason
        return systemic_reason

    monkeypatch.setattr(executor, "_process_item", fake_process_item)

    result = await executor.run()

    assert result["status"] == QUEUE_STATUS_STOPPED
    assert result["stop_reason"] == expected_stop_reason
    assert result["counts"] == {"stopped": 1, "pending": 2}


@pytest.mark.asyncio
async def test_drive_manifest_publishes_terminal_deliverable_without_recorded_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    manifest_path = tmp_path / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-test\n", encoding="utf-8")
    item = TrancheQueueItem(
        item_id="issue-1046",
        kind="issue",
        source="1046",
        merge_class="manual",
    )
    item_state = TrancheQueueItemRunState(
        item_id=item.item_id,
        status=QUEUE_ITEM_STATUS_RUNNING,
        effective_autonomy_mode="adaptive",
    )
    current = TrancheRunState(
        manifest_id="tranche-test",
        status=TRANCHE_STATUS_NEEDS_HUMAN,
        autonomy_mode="adaptive",
        lane_states={
            "lane-a": LaneRunState(
                lane_id="lane-a",
                status=LANE_STATUS_NEEDS_HUMAN,
                run_id="run-123",
            )
        },
    )
    artifact = TrancheLaneArtifact(
        lane_id="lane-a",
        source_ref="issue-1046",
        status="completed",
        run_id="run-123",
        metadata={
            "deliverable": {
                "branch": "codex/swarm-lane-a",
                "commit_shas": ["abc123"],
            }
        },
    )

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_run_state",
        lambda _: current,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.claim_driver",
        lambda state, **kwargs: state,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.release_driver",
        lambda state, **kwargs: state,
    )

    async def fake_watch_loop(state, **kwargs):
        return state

    monkeypatch.setattr("aragora.swarm.tranche_queue.watch_loop", fake_watch_loop)
    monkeypatch.setattr(
        TrancheQueueExecutor,
        "_load_artifact_for_lane",
        staticmethod(lambda *args, **kwargs: artifact),
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.DevCoordinationStore",
        lambda repo_root: object(),
    )

    async def fake_integrate_lane(**kwargs):
        return {
            "pr_url": "https://example.test/pr/42",
            "publish_result": {"action": "pr_created"},
            "recommendation": "needs_human",
            "executed": False,
        }

    monkeypatch.setattr("aragora.swarm.tranche_queue.integrate_lane", fake_integrate_lane)

    tranche_manifest = SimpleNamespace(manifest_id="tranche-test")
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)

    result = await executor._drive_manifest(
        item=item,
        item_state=item_state,
        manifest_path=manifest_path,
        tranche_manifest=tranche_manifest,
        deadline=deadline,
    )

    assert result is None
    assert item_state.status == QUEUE_ITEM_STATUS_NEEDS_HUMAN
    assert item_state.pr_urls == ["https://example.test/pr/42"]
    assert current.lane_states["lane-a"].pr_url == "https://example.test/pr/42"
    assert any(
        event.get("type") == "integrate" and event.get("pr_url") == "https://example.test/pr/42"
        for event in item_state.events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_parallel_lanes", "expected_all_ready"),
    [
        (1, False),
        (2, True),
    ],
)
async def test_drive_manifest_dispatches_all_ready_lanes_only_when_parallel_cap_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_parallel_lanes: int,
    expected_all_ready: bool,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    _write_queue(queue_path)
    executor = TrancheQueueExecutor(
        queue_path=queue_path,
        repo_root=tmp_path,
        max_parallel_lanes=max_parallel_lanes,
    )
    manifest_path = tmp_path / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-test\n", encoding="utf-8")
    item = TrancheQueueItem(
        item_id="issue-1046",
        kind="issue",
        source="1046",
        merge_class="manual",
        max_lanes=2,
    )
    item_state = TrancheQueueItemRunState(
        item_id=item.item_id,
        status=QUEUE_ITEM_STATUS_RUNNING,
        effective_autonomy_mode="adaptive",
    )
    current = TrancheRunState(
        manifest_id="tranche-test",
        status="planned",
        autonomy_mode="adaptive",
        lane_states={
            "lane-a": LaneRunState(lane_id="lane-a", status="pending"),
            "lane-b": LaneRunState(lane_id="lane-b", status="pending"),
        },
    )
    seen: dict[str, object] = {}

    class _FakeExecutor:
        def __init__(self, *, repo_root):
            self.repo_root = repo_root

        async def run(self, manifest, **kwargs):
            seen["all_ready"] = kwargs.get("all_ready")
            return {"mode": "tranche-run", "results": []}

    async def fake_watch_loop(state, *, run_fn, manifest, **kwargs):
        await run_fn(manifest=manifest)
        state.status = TRANCHE_STATUS_NEEDS_HUMAN
        return state

    async def fake_publish_terminal_lane_deliverables(**kwargs):
        return None

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_run_state",
        lambda _: current,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.claim_driver",
        lambda state, **kwargs: state,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.release_driver",
        lambda state, **kwargs: state,
    )
    monkeypatch.setattr("aragora.swarm.tranche_queue.TrancheExecutor", _FakeExecutor)
    monkeypatch.setattr("aragora.swarm.tranche_queue.watch_loop", fake_watch_loop)
    monkeypatch.setattr(executor, "_github_client", lambda: object())
    monkeypatch.setattr(executor, "_registry_client", lambda: object())
    monkeypatch.setattr(
        executor,
        "_publish_terminal_lane_deliverables",
        fake_publish_terminal_lane_deliverables,
    )

    await executor._drive_manifest(
        item=item,
        item_state=item_state,
        manifest_path=manifest_path,
        tranche_manifest=SimpleNamespace(manifest_id="tranche-test"),
        deadline=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    assert seen["all_ready"] is expected_all_ready


@pytest.mark.asyncio
async def test_drive_manifest_stops_on_unexpected_refresh_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_path = tmp_path / "overnight.yaml"
    _write_queue(queue_path)
    executor = TrancheQueueExecutor(queue_path=queue_path, repo_root=tmp_path)
    manifest_path = tmp_path / "tranche.yaml"
    manifest_path.write_text("manifest_id: tranche-test\n", encoding="utf-8")
    item = TrancheQueueItem(
        item_id="issue-1046",
        kind="issue",
        source="1046",
        merge_class="manual",
        max_lanes=1,
    )
    item_state = TrancheQueueItemRunState(
        item_id=item.item_id,
        status=QUEUE_ITEM_STATUS_RUNNING,
        effective_autonomy_mode="adaptive",
    )
    current = TrancheRunState(
        manifest_id="tranche-test",
        status="running",
        autonomy_mode="adaptive",
        lane_states={"lane-a": LaneRunState(lane_id="lane-a", status="running")},
    )
    artifact = TrancheLaneArtifact(
        lane_id="lane-a",
        source_ref="issue-1046",
        status="completed",
        run_id="run-1",
        metadata={},
    )

    class _FakeSupervisor:
        def __init__(self) -> None:
            self.store = SimpleNamespace(
                get_supervisor_run=lambda _run_id: {
                    "run_id": "run-1",
                    "status": "completed",
                    "work_orders": [],
                }
            )

        def refresh_run(self, run_id: str):
            raise TypeError(f"refresh exploded for {run_id}")

    async def fake_watch_loop(state, *, review_fn, manifest, **kwargs):
        await review_fn(manifest=manifest, lane_id="lane-a", artifact=artifact)
        return state

    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.load_tranche_run_state",
        lambda _: current,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.claim_driver",
        lambda state, **kwargs: state,
    )
    monkeypatch.setattr(
        "aragora.swarm.tranche_queue.release_driver",
        lambda state, **kwargs: state,
    )
    monkeypatch.setattr("aragora.swarm.tranche_queue.watch_loop", fake_watch_loop)
    monkeypatch.setattr(executor, "_github_client", lambda: object())
    monkeypatch.setattr(executor, "_registry_client", lambda: object())
    executor._supervisor = _FakeSupervisor()

    result = await executor._drive_manifest(
        item=item,
        item_state=item_state,
        manifest_path=manifest_path,
        tranche_manifest=SimpleNamespace(
            manifest_id="tranche-test",
            lane=lambda _lane_id: SimpleNamespace(allowed_write_scope=["aragora/swarm/**"]),
        ),
        deadline=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    assert result == "watch_failure"
    assert item_state.status == QUEUE_ITEM_STATUS_STOPPED
    assert item_state.stop_reason == "watch_failure"
    assert item_state.result["watch_error"] == {"error_type": "TypeError"}
