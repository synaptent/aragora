from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, cast

from aragora.swarm.campaign import CampaignPlanner
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.tranche import (
    GhReferenceClient,
    TrancheInspector,
    TranchePlanner,
    parse_github_reference_url,
)
from aragora.swarm.tranche_state import (
    LANE_STATUS_PENDING,
    TRANCHE_STATUS_PLANNED,
    LaneRunState,
    TrancheRunState,
)


def classify_source_ref(url: str) -> dict[str, Any]:
    value = str(url).strip()
    try:
        target = parse_github_reference_url(value)
    except ValueError:
        return {
            "url": value,
            "kind": "context",
            "gated": False,
        }
    return {
        "url": value,
        "kind": "github",
        "gated": True,
        "github_kind": target.kind,
        "owner": target.owner,
        "repo": target.repo,
        "repo_full_name": f"{target.owner}/{target.repo}",
        "number": target.number,
    }


def enrich_github_refs(
    refs: list[dict[str, Any]],
    client: GhReferenceClient,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        item = dict(ref)
        if item.get("kind") != "github":
            enriched.append(item)
            continue
        repo = str(item.get("repo_full_name", "")).strip()
        number = int(item.get("number", 0) or 0)
        github_kind = str(item.get("github_kind", "")).strip()
        payload = (
            client.get_pr(repo, number)
            if github_kind == "pull_request"
            else client.get_issue(repo, number)
        )
        observed_state = _observed_reference_state(github_kind, payload)
        item.update(
            {
                "observed_state": observed_state,
                "status": _reference_status(observed_state),
                "stale": observed_state in {"closed", "merged"},
                "title": str(payload.get("title", "")).strip(),
                "labels": [
                    str(label.get("name", "")).strip()
                    for label in payload.get("labels", [])
                    if isinstance(label, dict) and str(label.get("name", "")).strip()
                ],
                "closed_at": payload.get("closedAt"),
                "merged_at": payload.get("mergedAt"),
            }
        )
        enriched.append(item)
    return enriched


def determine_decomposition_action(bundle: dict[str, Any]) -> str:
    lanes = _candidate_lanes(bundle)
    if not lanes:
        return "full_decomposition"
    for lane in lanes:
        if not _optional_text(lane.get("prompt")) or not _optional_text(lane.get("owner_role")):
            return "augment"
    for lane in lanes:
        if not _string_list(lane.get("allowed_write_scope")):
            return "inference_only"
        if not _string_list(lane.get("verification_commands")):
            return "inference_only"
    return "none"


def normalize_lanes(
    bundle: dict[str, Any],
    planner: Any | None,
) -> list[dict[str, Any]]:
    action = determine_decomposition_action(bundle)
    if action == "full_decomposition":
        lanes = _planner_lanes(bundle, planner, action=action)
    elif action == "augment":
        lanes = _planner_lanes(bundle, planner, action=action)
    else:
        lanes = _candidate_lanes(bundle)
    normalized: list[dict[str, Any]] = []
    for index, lane in enumerate(lanes, start=1):
        normalized.append(_normalize_lane(lane, index=index))
    max_lanes = _resolve_max_lanes(bundle.get("max_lanes"))
    if len(normalized) > max_lanes:
        normalized = _limit_normalized_lanes(normalized, max_lanes=max_lanes)
    return normalized


def submit_intake_bundle(
    bundle: dict[str, Any],
    *,
    repo_root: str | Path,
    autonomy_mode: str | None = None,
    planner: CampaignPlanner | None = None,
    reference_client: GhReferenceClient | None = None,
    skip_github_resolution: bool = False,
) -> dict[str, Any]:
    objective = _optional_text(bundle.get("objective"))
    if not objective:
        raise ValueError("submit bundle requires objective")
    repo_path = Path(repo_root).resolve()
    manifest_id = (
        _optional_text(bundle.get("manifest_id"))
        or _optional_text(bundle.get("bundle_id"))
        or f"tranche-{_slugify(objective)[:24] or 'intake'}-{uuid.uuid4().hex[:8]}"
    )
    mode = (
        _optional_text(autonomy_mode) or _optional_text(bundle.get("autonomy_mode")) or "adaptive"
    )
    client = reference_client or GhReferenceClient()

    raw_bundle = _copy_bundle(bundle)
    raw_bundle.setdefault("manifest_id", manifest_id)
    raw_bundle.setdefault("autonomy_mode", mode)

    normalized_bundle = _build_normalized_bundle(
        raw_bundle,
        manifest_id=manifest_id,
        repo_root=repo_path,
        planner=planner,
        reference_client=client,
        skip_github_resolution=skip_github_resolution,
    )
    tranche_dir = repo_path / ".aragora" / "tranches" / manifest_id
    intake_path = tranche_dir / "intake_bundle.yaml"
    normalized_path = tranche_dir / "normalized_bundle.yaml"
    manifest_path = tranche_dir / "tranche.yaml"
    inspection_path = tranche_dir / "inspection.yaml"
    run_state_path = tranche_dir / "run_state.yaml"
    _write_yaml_like(intake_path, raw_bundle)
    _write_yaml_like(normalized_path, normalized_bundle)

    tranche_planner = TranchePlanner(repo_root=repo_path)
    manifest, manifest_path = tranche_planner.plan_from_prompt_bundle(
        normalized_path,
        output_path=manifest_path,
    )
    inspector = TrancheInspector(
        repo_root=repo_path,
        reference_client=cast(
            Any,
            _StaticOpenReferenceClient() if skip_github_resolution else client,
        ),
    )
    inspection = inspector.inspect(manifest)
    _write_yaml_like(inspection_path, dict(inspection))
    inspection_status = str(inspection.get("preflight_status", "blocked")).strip() or "blocked"
    submission_status, recommended_action = _submission_decision(
        manifest,
        inspection=inspection,
        autonomy_mode=mode,
    )
    state = TrancheRunState(
        manifest_id=manifest.manifest_id,
        status=TRANCHE_STATUS_PLANNED,
        autonomy_mode=mode,
        lane_states={
            lane.lane_id: LaneRunState(lane_id=lane.lane_id, status=LANE_STATUS_PENDING)
            for lane in manifest.lanes
        },
    )
    state.save(run_state_path)
    return {
        "manifest_id": manifest.manifest_id,
        "intake_path": str(intake_path),
        "normalized_bundle_path": str(normalized_path),
        "manifest_path": str(manifest_path),
        "inspection_path": str(inspection_path),
        "run_state_path": str(run_state_path),
        "inspection_status": inspection_status,
        "submission_status": submission_status,
        "recommended_action": recommended_action,
        "tranche_dir": str(tranche_dir),
    }


def _observed_reference_state(kind: str, payload: dict[str, Any]) -> str:
    state = str(payload.get("state", "")).strip().lower()
    if kind == "pull_request" and str(payload.get("mergedAt", "")).strip():
        return "merged"
    return state or "unknown"


def _reference_status(observed_state: str) -> str:
    return "actionable" if observed_state == "open" else "stale"


def _candidate_lanes(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    raw_lanes = bundle.get("candidate_lanes")
    if not isinstance(raw_lanes, list):
        return []
    return [dict(item) for item in raw_lanes if isinstance(item, dict)]


def _resolve_max_lanes(value: Any) -> int:
    return max(1, int(value or 1))


def _limit_normalized_lanes(
    lanes: list[dict[str, Any]],
    *,
    max_lanes: int,
) -> list[dict[str, Any]]:
    if len(lanes) <= max_lanes:
        return [dict(lane) for lane in lanes]
    retained = [dict(lane) for lane in lanes[:max_lanes]]
    retained_ids = {
        _optional_text(lane.get("lane_id")) or ""
        for lane in retained
        if _optional_text(lane.get("lane_id"))
    }
    for lane in retained:
        lane["dependencies"] = [
            dep for dep in _string_list(lane.get("dependencies")) if dep in retained_ids
        ]
    return retained


def _planner_lanes(
    bundle: dict[str, Any], planner: Any | None, *, action: str
) -> list[dict[str, Any]]:
    if planner is None:
        raise ValueError(f"planner is required for {action}")
    if action == "augment" and hasattr(planner, "augment_lanes"):
        lanes = planner.augment_lanes(bundle)
    elif hasattr(planner, "decompose_bundle"):
        lanes = planner.decompose_bundle(bundle)
    elif hasattr(planner, "plan_lanes"):
        lanes = planner.plan_lanes(bundle)
    elif hasattr(planner, "plan_from_items"):
        objective = _optional_text(bundle.get("objective")) or "Tranche intake bundle"
        items = _planner_items(bundle, action=action, objective=objective)
        manifest = planner.plan_from_items(
            items,
            source_kind="intake_bundle",
            source_ref=_optional_text(bundle.get("manifest_id")) or objective,
        )
        lanes = [
            _campaign_project_to_lane(project, planner=planner) for project in manifest.projects
        ]
    elif callable(planner):
        lanes = planner(bundle)
    else:
        raise ValueError(f"planner is required for {action}")
    if not isinstance(lanes, list):
        raise ValueError("planner must return a list of lane objects")
    planned = [dict(item) for item in lanes if isinstance(item, dict)]
    if planned:
        return planned
    objective = _optional_text(bundle.get("objective")) or "Complete the tranche objective."
    return [_fallback_lane_from_objective(objective)]


def _normalize_lane(lane: dict[str, Any], *, index: int) -> dict[str, Any]:
    title = _optional_text(lane.get("title")) or f"Lane {index}"
    prompt = _optional_text(lane.get("prompt"))
    owner_role = _optional_text(lane.get("owner_role"))
    if not prompt:
        raise ValueError("normalized lane requires prompt")
    if not owner_role:
        raise ValueError("normalized lane requires owner_role")
    scope = _string_list(lane.get("allowed_write_scope")) or _infer_scope_from_lane(lane)
    normalized = {
        "lane_id": _optional_text(lane.get("lane_id")) or _slugify(title) or f"lane-{index:02d}",
        "title": title,
        "prompt": prompt,
        "owner_role": owner_role,
        "source_refs": _string_list(lane.get("source_refs")),
        "target_agent": _optional_text(lane.get("target_agent")),
        "review_model": _optional_text(lane.get("review_model")),
        "allowed_write_scope": scope,
        "dependencies": _string_list(lane.get("dependencies")),
        "acceptance_criteria": _string_list(lane.get("acceptance_criteria")),
        "constraints": _string_list(lane.get("constraints")),
        "verification_commands": _string_list(lane.get("verification_commands")),
        "stop_conditions": _string_list(lane.get("stop_conditions")),
        "expected_receipts_artifacts": _string_list(lane.get("expected_receipts_artifacts")),
    }
    extras = {
        key: value
        for key, value in lane.items()
        if key
        not in {
            "lane_id",
            "title",
            "prompt",
            "owner_role",
            "source_refs",
            "target_agent",
            "review_model",
            "allowed_write_scope",
            "dependencies",
            "acceptance_criteria",
            "constraints",
            "verification_commands",
            "stop_conditions",
            "expected_receipts_artifacts",
            "file_scope_hints",
        }
    }
    normalized.update(extras)
    return normalized


def _build_normalized_bundle(
    bundle: dict[str, Any],
    *,
    manifest_id: str,
    repo_root: Path,
    planner: CampaignPlanner | None,
    reference_client: GhReferenceClient,
    skip_github_resolution: bool,
) -> dict[str, Any]:
    source_refs = _collect_source_refs(bundle)
    classified = [
        classify_source_ref(entry["url"]) | {"meaning": entry["meaning"]} for entry in source_refs
    ]
    enriched = (
        classified if skip_github_resolution else enrich_github_refs(classified, reference_client)
    )
    planner_obj = planner or CampaignPlanner(repo_root=repo_root, planner_strategy="heuristic")
    lanes = normalize_lanes(bundle, planner=planner_obj)
    return {
        "manifest_id": manifest_id,
        "bundle_id": manifest_id,
        "objective": _optional_text(bundle.get("objective")) or "",
        "repo": _normalized_repo(bundle.get("repo"), repo_root=repo_root),
        "shared_constraints": _normalized_shared_constraints(bundle),
        "references": {"source_refs": _source_ref_map(enriched)},
        "lanes": lanes,
        "terminal_outcomes": dict(bundle.get("terminal_outcomes") or {}),
        "execution_contract": summarize_execution_contract({"lanes": lanes}),
    }


def _infer_scope_from_lane(lane: dict[str, Any]) -> list[str]:
    hints = _string_list(lane.get("file_scope_hints"))
    if not hints:
        text = " ".join(
            item
            for item in (
                _optional_text(lane.get("title")),
                _optional_text(lane.get("prompt")),
            )
            if item
        )
        hints = SwarmSpec.infer_file_scope_hints(text)
    return _normalize_scope_hints(hints)


def _normalize_scope_hints(hints: list[str]) -> list[str]:
    normalized: list[str] = []
    for hint in hints:
        value = str(hint).strip().removeprefix("./").rstrip("/")
        if not value:
            continue
        if "*" in value:
            normalized.append(value)
            continue
        if "/" in value and "." not in value.rsplit("/", 1)[-1]:
            normalized.append(f"{value}/**")
            continue
        normalized.append(value)
    return list(dict.fromkeys(normalized))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _copy_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(bundle))


def _collect_source_refs(bundle: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in (
        bundle.get("source_refs", []) if isinstance(bundle.get("source_refs"), list) else []
    ):
        if isinstance(item, dict):
            url = _optional_text(item.get("url"))
            if url:
                refs.append({"url": url, "meaning": _optional_text(item.get("meaning")) or ""})
        else:
            url = _optional_text(item)
            if url:
                refs.append({"url": url, "meaning": ""})
    for lane in _candidate_lanes(bundle):
        for url in _string_list(lane.get("source_refs")):
            refs.append(
                {
                    "url": url,
                    "meaning": f"Source ref for lane {_optional_text(lane.get('lane_id')) or _optional_text(lane.get('title')) or 'lane'}",
                }
            )
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in refs:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def _source_ref_map(refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for index, ref in enumerate(refs, start=1):
        if ref.get("kind") != "github":
            continue
        github_kind = str(ref.get("github_kind", "")).strip()
        number = int(ref.get("number", 0) or 0)
        prefix = "pr" if github_kind == "pull_request" else "issue"
        ref_id = f"{prefix}_{number}" if number else f"{prefix}_{index}"
        state = str(ref.get("observed_state", "")).strip() or (
            "open" if str(ref.get("status", "")).strip() == "actionable" else ""
        )
        mapped[ref_id] = {
            "kind": github_kind,
            "url": str(ref.get("url", "")).strip(),
            "state": state,
            "meaning": str(ref.get("meaning", "")).strip(),
        }
    return mapped


def _normalized_repo(repo_value: Any, *, repo_root: Path) -> dict[str, Any]:
    repo = dict(repo_value) if isinstance(repo_value, dict) else {}
    repo.setdefault("root", str(repo_root))
    repo.setdefault("base_ref", "origin/main")
    repo.setdefault("name", repo_root.name)
    return repo


def _normalized_shared_constraints(bundle: dict[str, Any]) -> dict[str, Any]:
    shared = dict(bundle.get("shared_constraints") or {})
    constraints = _string_list(bundle.get("constraints"))
    if constraints:
        shared.setdefault("constraints", constraints)
    acceptance = _string_list(bundle.get("acceptance_signals"))
    if acceptance:
        shared.setdefault("acceptance_signals", acceptance)
    return shared


def _planner_items(bundle: dict[str, Any], *, action: str, objective: str) -> list[str]:
    if action == "full_decomposition":
        return [objective]
    items: list[str] = []
    for lane in _candidate_lanes(bundle):
        text = _optional_text(lane.get("prompt")) or _optional_text(lane.get("title"))
        if text:
            items.append(text)
    return items or [objective]


def campaign_projects_to_candidate_lanes(
    projects: list[Any],
    *,
    planner: Any,
) -> list[dict[str, Any]]:
    return [_campaign_project_to_lane(project, planner=planner) for project in projects]


def _campaign_project_to_lane(project: Any, *, planner: Any) -> dict[str, Any]:
    source_refs = [
        value
        for value in getattr(project, "source_refs", [])
        if isinstance(value, str) and "://" in value
    ]
    spec = getattr(project, "spec", None)
    prompt = _optional_text(getattr(spec, "raw_goal", None)) or _optional_text(
        getattr(project, "title", None)
    )
    return {
        "lane_id": _optional_text(getattr(project, "project_id", None))
        or _slugify(prompt or "lane"),
        "title": _optional_text(getattr(project, "title", None)) or prompt or "Generated lane",
        "prompt": prompt or "Complete the tranche lane.",
        "owner_role": "implementation_engineer",
        "source_refs": source_refs,
        "target_agent": _optional_text(getattr(planner, "worker_model", None)) or "codex",
        "review_model": _optional_text(getattr(planner, "review_model", None)) or "claude",
        "allowed_write_scope": _normalize_scope_hints(
            list(getattr(project, "file_scope_hints", []) or [])
        ),
        "dependencies": [
            str(getattr(dep, "project_id", "")).strip()
            for dep in getattr(project, "dependencies", [])
            if str(getattr(dep, "project_id", "")).strip()
        ],
        "acceptance_criteria": _string_list(getattr(project, "acceptance_criteria", [])),
        "constraints": _string_list(getattr(project, "constraints", [])),
        "verification_commands": [],
    }


def _fallback_lane_from_objective(objective: str) -> dict[str, Any]:
    return {
        "lane_id": _slugify(objective) or "lane-01",
        "title": objective,
        "prompt": objective,
        "owner_role": "implementation_engineer",
        "allowed_write_scope": _normalize_scope_hints(SwarmSpec.infer_file_scope_hints(objective)),
        "verification_commands": [],
    }


def _submission_decision(
    manifest: Any,
    *,
    inspection: dict[str, Any],
    autonomy_mode: str,
) -> tuple[str, str]:
    inspection_status = str(inspection.get("preflight_status", "blocked")).strip() or "blocked"
    if inspection_status != "ok":
        recommended = inspection.get("recommended_action")
        if isinstance(recommended, dict):
            return "blocked", str(
                recommended.get("kind", "stop_and_replan")
            ).strip() or "stop_and_replan"
        return "blocked", "stop_and_replan"
    has_writable_lanes = any(
        bool(lane.allowed_write_scope) for lane in getattr(manifest, "lanes", [])
    )
    mode = str(autonomy_mode).strip() or "adaptive"
    if mode == "fire_and_forget":
        return "ready_to_prepare", "prepare"
    if mode in {"checkpoint", "spectator"}:
        return "awaiting_confirmation", "design-review" if has_writable_lanes else "prepare"
    return "awaiting_confirmation", "design-review" if has_writable_lanes else "prepare"


def summarize_execution_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    raw_lanes = bundle.get("lanes")
    if not isinstance(raw_lanes, list):
        raw_lanes = bundle.get("candidate_lanes")
    lanes = (
        [dict(item) for item in raw_lanes if isinstance(item, dict)]
        if isinstance(raw_lanes, list)
        else []
    )
    missing_scope_lanes: list[str] = []
    unbounded_scope_lanes: list[str] = []
    missing_verification_lanes: list[str] = []
    lane_summaries: list[dict[str, Any]] = []
    for index, lane in enumerate(lanes, start=1):
        lane_id = _optional_text(lane.get("lane_id")) or f"lane-{index:02d}"
        scope = _string_list(lane.get("allowed_write_scope"))
        verification_commands = _string_list(lane.get("verification_commands"))
        if not scope:
            missing_scope_lanes.append(lane_id)
        elif not all(_scope_is_bounded(entry) for entry in scope):
            unbounded_scope_lanes.append(lane_id)
        if not verification_commands:
            missing_verification_lanes.append(lane_id)
        lane_summaries.append(
            {
                "lane_id": lane_id,
                "has_bounded_scope": bool(scope) and lane_id not in unbounded_scope_lanes,
                "has_verification_commands": bool(verification_commands),
            }
        )
    ready = bool(lanes) and not (
        missing_scope_lanes or unbounded_scope_lanes or missing_verification_lanes
    )
    return {
        "ready": ready,
        "lane_count": len(lanes),
        "lanes": lane_summaries,
        "missing_scope_lanes": missing_scope_lanes,
        "unbounded_scope_lanes": unbounded_scope_lanes,
        "missing_verification_lanes": missing_verification_lanes,
    }


def _scope_is_bounded(value: str) -> bool:
    normalized = str(value or "").strip().removeprefix("./").rstrip("/")
    if not normalized:
        return False
    if normalized in {".", "*", "**"}:
        return False
    if normalized.endswith("/**"):
        return bool(normalized[:-3])
    return True


def _write_yaml_like(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    except ImportError:
        text = json.dumps(payload, indent=2, sort_keys=False)
    path.write_text(text, encoding="utf-8")


class _StaticOpenReferenceClient:
    def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        return {
            "number": number,
            "state": "OPEN",
            "title": f"Issue {number}",
            "url": f"https://github.com/{repo}/issues/{number}",
            "labels": [],
            "closedAt": None,
        }

    def get_pr(self, repo: str, number: int) -> dict[str, Any]:
        return {
            "number": number,
            "state": "OPEN",
            "mergedAt": None,
            "title": f"PR {number}",
            "url": f"https://github.com/{repo}/pull/{number}",
            "labels": [],
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviewDecision": "",
            "headRefName": "",
            "baseRefName": "main",
        }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return slug
