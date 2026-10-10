"""Pin the campaign planner split.

``CampaignPlanner`` and its source-parsing helpers live in
``aragora.swarm.campaign_planner``; the manifest bookkeeping helpers shared by the
planner, reviewer and executor live in ``aragora.swarm.campaign_state``.
``aragora.swarm.campaign`` re-exports the same objects, so existing imports and
``patch("aragora.swarm.campaign.CampaignPlanner....")`` targets keep resolving to one
implementation per name.
"""

from __future__ import annotations

import ast
import inspect
from types import ModuleType

import pytest

from aragora.swarm import campaign, campaign_planner, campaign_state, tranche_submit
from aragora.swarm.campaign_models import CampaignManifest, CampaignProject

PLANNER_NAMES = """
    CampaignPlanner _complexity_cost _success_criteria_to_list _normalized_scope
    _parse_source_items _gh_json
""".split()

STATE_NAMES = """
    _now_iso _project_estimated_cost _campaign_budget_snapshot _refresh_execution_state
    _extract_first_json_object _extract_json_list
""".split()


def _imported_modules(module: ModuleType) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


@pytest.mark.parametrize(
    ("module", "name"),
    [(campaign_planner, name) for name in PLANNER_NAMES]
    + [(campaign_state, name) for name in STATE_NAMES],
)
def test_moved_name_is_defined_in_its_module_and_reexported_by_campaign(
    module: ModuleType, name: str
) -> None:
    obj = getattr(module, name)
    assert obj.__module__ == module.__name__
    assert getattr(campaign, name) is obj


def test_budget_epsilon_is_shared_with_the_campaign_facade() -> None:
    assert campaign._BUDGET_EPSILON is campaign_state._BUDGET_EPSILON


def test_split_modules_do_not_import_the_campaign_facade() -> None:
    assert "aragora.swarm.campaign" not in _imported_modules(campaign_planner)
    assert "aragora.swarm.campaign" not in _imported_modules(campaign_state)
    assert "aragora.swarm.campaign_planner" not in _imported_modules(campaign_state)
    assert not hasattr(campaign_planner, "CampaignExecutor")
    assert not hasattr(campaign_state, "CampaignPlanner")


def test_facade_consumers_get_the_moved_planner_class() -> None:
    assert tranche_submit.CampaignPlanner is campaign_planner.CampaignPlanner


def test_source_items_split_on_bullets_and_headings() -> None:
    text = "- first item\n* second item\n\n# Heading\nbody line\n\n1. numbered"
    assert campaign._parse_source_items(text) == [
        "first item",
        "second item",
        "Heading\nbody line",
        "numbered",
    ]


def test_model_findings_are_extracted_from_noisy_json() -> None:
    text = 'noise {"findings": ["keep", "  ", 3]} trailing'
    assert campaign._extract_json_list(text) == ["keep", "3"]
    assert campaign._extract_first_json_object("[1, 2]") == {}


def test_refresh_execution_state_reserves_active_project_cost() -> None:
    manifest = CampaignManifest(
        campaign_id="c1",
        created_at="2026-01-01T00:00:00+00:00",
        source_kind="source_file",
        source_ref="plan.md",
        budget_limit_usd=10.0,
        projects=[
            CampaignProject(project_id="p1", title="a", status="active", estimated_cost_usd=2.5),
            CampaignProject(project_id="p2", title="b", status="ready", estimated_cost_usd=1.0),
            CampaignProject(project_id="p3", title="c", status="completed", estimated_cost_usd=4.0),
        ],
    )
    campaign._refresh_execution_state(manifest)
    state = manifest.execution_state
    assert state.ready_queue == ["p2"]
    assert state.active_projects == ["p1"]
    assert state.completed_projects == ["p3"]
    assert state.reserved_cost_usd == 2.5
    snapshot = campaign._campaign_budget_snapshot(manifest)
    assert snapshot["available_budget_usd"] == 7.5
    assert snapshot["budget_exhausted"] is False
