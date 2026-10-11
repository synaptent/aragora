"""Pin the campaign receipt-helper split.

The pure helpers that derive decision-receipt fields from a campaign project and its
swarm run live in ``aragora.swarm.campaign_receipts``. ``aragora.swarm.campaign``
re-exports the same function objects, so existing imports from the campaign module and
the executor's receipt emission keep using one implementation per name.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from aragora.swarm import campaign, campaign_receipts
from aragora.swarm.campaign_models import CampaignProject
from aragora.swarm.worker_launcher import MAX_WORKER_LOG_TAIL_CHARS

MOVED_NAMES = """
    _derive_phase _failure_classification_from_outcome _receipt_final_status
    _receipt_review_verdict _duration_seconds_from_run _changed_files_from_run
    _tests_from_acceptance_criteria _ordered_unique _worker_branches_from_run
    _worker_commits_from_run _worker_branch_from_run _worker_commit_from_run
    _truncate_receipt_text _receipt_debug_value _receipt_verification_results
    _receipt_merge_gate _work_order_snapshot_for_receipt _work_order_snapshots_from_run
    _planner_metadata_from_run _verification_missing_reason_from_run
""".split()


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_helper_is_defined_in_receipts_and_reexported_by_campaign(name: str) -> None:
    func = getattr(campaign_receipts, name)
    assert func.__module__ == "aragora.swarm.campaign_receipts"
    assert getattr(campaign, name) is func


def test_receipts_module_does_not_import_the_campaign_facade() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(campaign_receipts))):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "aragora.swarm.campaign" not in imported
    assert not hasattr(campaign_receipts, "CampaignExecutor")


def test_worker_fields_come_from_project_and_work_orders_in_order() -> None:
    project = CampaignProject(
        project_id="p1",
        title="Split receipts",
        branch="feature/p1",
        commit_shas=["aaa", " "],
    )
    run = {
        "work_orders": [
            "not-a-dict",
            {"branch": "feature/p1", "commit_shas": ["bbb"], "head_sha": "ccc"},
            {"branch": "feature/p1-retry", "head_sha": "aaa"},
        ]
    }
    assert campaign._worker_branches_from_run(project, run) == ["feature/p1", "feature/p1-retry"]
    assert campaign._worker_commits_from_run(project, run) == ["aaa", "bbb", "ccc"]
    assert campaign._worker_branch_from_run(project, None) == "feature/p1"
    assert campaign._worker_commit_from_run(project, run) == "ccc"


def test_receipt_text_is_truncated_to_the_worker_log_tail_limit() -> None:
    text = "x" * MAX_WORKER_LOG_TAIL_CHARS + "tail"
    assert campaign._truncate_receipt_text(text) == "x" * MAX_WORKER_LOG_TAIL_CHARS
    assert campaign._truncate_receipt_text(text, tail=True).endswith("tail")
    assert campaign._receipt_debug_value({"k": [text, 3, None]}) == {
        "k": ["x" * MAX_WORKER_LOG_TAIL_CHARS, 3, None]
    }
