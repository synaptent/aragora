"""Campaign manifest bookkeeping shared by the planner, reviewer and executor.

Timestamps, the budget snapshot, the execution-state refresh and JSON extraction from
model responses. ``aragora.swarm.campaign`` re-exports every name here, so importing
from either module yields the same objects.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from aragora.swarm.campaign_models import (
    CampaignManifest,
    CampaignProject,
    CampaignProjectStatus,
)

UTC = timezone.utc
_BUDGET_EPSILON = 1e-9


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _project_estimated_cost(project: CampaignProject) -> float:
    return max(0.0, float(project.estimated_cost_usd or 0.0))


def _campaign_budget_snapshot(manifest: CampaignManifest) -> dict[str, float | bool]:
    spent = max(0.0, float(manifest.execution_state.total_cost_usd or 0.0))
    reserved = sum(
        _project_estimated_cost(project)
        for project in manifest.projects
        if project.status == CampaignProjectStatus.ACTIVE.value
    )
    limit = max(0.0, float(manifest.budget_limit_usd or 0.0))
    committed = spent + reserved
    available = max(0.0, limit - committed)
    return {
        "budget_limit_usd": round(limit, 4),
        "spent_cost_usd": round(spent, 4),
        "reserved_cost_usd": round(reserved, 4),
        "committed_cost_usd": round(committed, 4),
        "available_budget_usd": round(available, 4),
        "budget_exhausted": bool(available <= _BUDGET_EPSILON),
    }


def _refresh_execution_state(manifest: CampaignManifest) -> None:
    manifest.execution_state.ready_queue = [
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.READY.value
    ]
    manifest.execution_state.active_projects = [
        project.project_id
        for project in manifest.projects
        if project.status
        in {
            CampaignProjectStatus.ACTIVE.value,
            CampaignProjectStatus.WAITING_FOR_PR.value,
            CampaignProjectStatus.WAITING_FOR_MERGE.value,
        }
    ]
    manifest.execution_state.completed_projects = [
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.COMPLETED.value
    ]
    manifest.execution_state.failed_projects = [
        project.project_id
        for project in manifest.projects
        if project.status
        in {
            CampaignProjectStatus.FAILED.value,
            CampaignProjectStatus.STALLED.value,
            CampaignProjectStatus.BLOCKED.value,
        }
    ]
    manifest.execution_state.skipped_projects = [
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.SKIPPED.value
    ]
    manifest.execution_state.reserved_cost_usd = float(
        _campaign_budget_snapshot(manifest)["reserved_cost_usd"]
    )


def _extract_first_json_object(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _extract_json_list(text: str) -> list[str]:
    payload = _extract_first_json_object(text)
    findings = payload.get("findings")
    if isinstance(findings, list):
        return [str(item) for item in findings if str(item).strip()]
    return []
