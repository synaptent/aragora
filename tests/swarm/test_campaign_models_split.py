"""Pin the campaign data-model split.

The campaign enums, dataclasses and the small value helpers they use live in
``aragora.swarm.campaign_models``. ``aragora.swarm.campaign`` re-exports the same
objects, so existing imports from the campaign module and the lazy ``aragora.swarm``
exports keep resolving to one class per name.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import aragora.swarm as swarm_package
from aragora.swarm import campaign, campaign_models

MOVED_NAMES = """
    _optional_text _coerce_boolish _canonical_planner_strategy _canonical_review_model
    CampaignProjectStatus CampaignRunOutcome CampaignStopReason CampaignReviewStatus
    CampaignDependency CampaignReviewGate CampaignExecutionState CampaignProject
    CampaignManifest
""".split()


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_name_is_defined_in_models_and_reexported_by_campaign(name: str) -> None:
    obj = getattr(campaign_models, name)
    assert obj.__module__ == "aragora.swarm.campaign_models"
    assert getattr(campaign, name) is obj


def test_models_module_does_not_import_the_campaign_facade() -> None:
    imported = {
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(campaign_models)))
        if isinstance(node, ast.ImportFrom)
    }
    assert "aragora.swarm.campaign" not in imported
    assert not hasattr(campaign_models, "CampaignExecutor")


def test_lazy_package_exports_resolve_to_the_models_classes() -> None:
    for name in ("CampaignManifest", "CampaignProject", "CampaignRunOutcome"):
        assert getattr(swarm_package, name) is getattr(campaign_models, name)


def test_manifest_round_trips_through_the_campaign_module() -> None:
    manifest = campaign.CampaignManifest.from_dict(
        {
            "campaign_id": "camp-1",
            "created_at": "2026-10-10T00:00:00+00:00",
            "source_kind": "goal",
            "source_ref": "split campaign models",
            "worker_model": "codex",
            "review_model": "codex",
            "planner_strategy": "MODEL",
            "experiment_id": " null ",
            "execution_state": {"last_run_at": "2026-10-10T01:00:00+00:00"},
        }
    )
    assert manifest.review_model == "claude"
    assert manifest.planner_strategy == "model"
    assert manifest.experiment_id is None
    again = campaign.CampaignManifest.from_text(manifest.to_yaml())
    assert again.to_dict() == manifest.to_dict()
    assert isinstance(again.execution_state, campaign.CampaignExecutionState)
