from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from aragora.swarm.campaign import CampaignProject, CampaignReviewer, _changed_files_from_run
from aragora.swarm.tranche import (
    TrancheLaneArtifact,
    TrancheManifest,
    _lane_budget_limit_usd,
    _lane_review_model,
    _lane_source_urls,
    _lane_spec_from_manifest,
    _lane_target_agent,
    _lane_title,
    _manifest_base_branch,
)


def select_review_tier(
    *,
    write_scope: list[str],
    diff_lines: int,
    verification_passed: bool,
    risk_tolerance: str | None,
) -> int:
    override = str(risk_tolerance or "").strip().lower()
    if override == "high":
        return 3
    if override == "medium":
        return 2
    if override == "low":
        return 1

    tier = 1
    scope_count = len([item for item in write_scope if str(item).strip()])
    if scope_count >= 2:
        tier = 2
    if scope_count > 3:
        tier = 3

    if diff_lines > 50:
        tier = max(tier, 2)
    if diff_lines > 300:
        tier = 3

    if not verification_passed:
        tier = 3
    return tier


async def review_lane(
    *,
    manifest: TrancheManifest,
    lane_id: str,
    artifact: TrancheLaneArtifact,
    run_dict: dict[str, Any],
    reviewer: Any | None = None,
    reviewers: list[Any] | None = None,
    tier: int = 1,
    dispatch_fn: Any | None = None,
    max_retries: int = 2,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    repo = (repo_root or Path.cwd()).resolve()
    if tier == 2:
        return await _tier_2_review(
            manifest=manifest,
            lane_id=lane_id,
            artifact=artifact,
            run_dict=run_dict,
            reviewers=reviewers,
            repo_root=repo,
        )
    if tier == 3:
        return await _tier_3_review(
            manifest=manifest,
            lane_id=lane_id,
            artifact=artifact,
            run_dict=run_dict,
            reviewer=reviewer,
            dispatch_fn=dispatch_fn,
            max_retries=max_retries,
            repo_root=repo,
        )
    return await _tier_1_review(
        manifest=manifest,
        lane_id=lane_id,
        artifact=artifact,
        run_dict=run_dict,
        reviewer=reviewer,
        repo_root=repo,
        tier=1,
    )


def _adapt_lane_to_campaign_project(
    manifest: TrancheManifest,
    lane_id: str,
    artifact: TrancheLaneArtifact,
) -> CampaignProject:
    lane = manifest.lane(lane_id)
    spec = _lane_spec_from_manifest(manifest, lane)
    return CampaignProject(
        project_id=lane.lane_id,
        title=_lane_title(lane),
        source_refs=list(_lane_source_urls(lane)),
        spec=spec,
        file_scope_hints=list(spec.file_scope_hints),
        acceptance_criteria=list(spec.acceptance_criteria),
        constraints=list(spec.constraints),
        run_id=artifact.run_id,
    )


async def _tier_1_review(
    *,
    manifest: TrancheManifest,
    lane_id: str,
    artifact: TrancheLaneArtifact,
    run_dict: dict[str, Any],
    reviewer: Any | None,
    repo_root: Path,
    tier: int,
) -> dict[str, Any]:
    lane = manifest.lane(lane_id)
    project = _adapt_lane_to_campaign_project(manifest, lane_id, artifact)
    reviewer_obj = reviewer or CampaignReviewer()
    worker_model = _lane_target_agent(lane, fallback="codex")
    review_model = _lane_review_model(lane, target_agent=worker_model)
    changed_files = _changed_files_from_run(run_dict)
    gate = await reviewer_obj.review(
        project=project,
        worker_model=worker_model,
        review_model=review_model,
        enforce_cross_model_review=bool(lane.metadata.get("enforce_cross_model_review", True)),
        run_dict=dict(run_dict),
        budget_context={"project_estimated_cost_usd": _lane_budget_limit_usd(lane)},
        repo_root=repo_root,
        target_branch=_manifest_base_branch(manifest, fallback="main"),
    )
    return {
        "status": gate.status,
        "tier": tier,
        "findings": list(gate.findings),
        "changed_files": changed_files,
        "review": gate.to_dict(),
        "retry_count": 0,
    }


async def _tier_2_review(
    *,
    manifest: TrancheManifest,
    lane_id: str,
    artifact: TrancheLaneArtifact,
    run_dict: dict[str, Any],
    reviewers: list[Any] | None,
    repo_root: Path,
) -> dict[str, Any]:
    reviewer_objs = [item for item in (reviewers or []) if item is not None]
    if len(reviewer_objs) < 2:
        reviewer_objs = reviewer_objs + [CampaignReviewer() for _ in range(2 - len(reviewer_objs))]
    results: list[dict[str, Any]] = []
    for reviewer_obj in reviewer_objs[:2]:
        results.append(
            await _tier_1_review(
                manifest=manifest,
                lane_id=lane_id,
                artifact=artifact,
                run_dict=run_dict,
                reviewer=reviewer_obj,
                repo_root=repo_root,
                tier=2,
            )
        )
    statuses = [str(item["status"]).strip().lower() for item in results]
    if all(status == "passed" for status in statuses):
        status = "passed"
    elif any(status == "blocked_nonreviewable" for status in statuses):
        status = "blocked_nonreviewable"
    elif any(status == "changes_requested" for status in statuses):
        status = "changes_requested"
    else:
        status = statuses[0] if statuses else "blocked_nonreviewable"
    findings: list[str] = []
    changed_files: list[str] = []
    for item in results:
        findings.extend(str(f).strip() for f in item.get("findings", []) if str(f).strip())
        changed_files.extend(
            str(path).strip() for path in item.get("changed_files", []) if str(path).strip()
        )
    return {
        "status": status,
        "tier": 2,
        "findings": list(dict.fromkeys(findings)),
        "changed_files": list(dict.fromkeys(changed_files)),
        "reviews": [item.get("review", {}) for item in results],
        "retry_count": 0,
    }


async def _tier_3_review(
    *,
    manifest: TrancheManifest,
    lane_id: str,
    artifact: TrancheLaneArtifact,
    run_dict: dict[str, Any],
    reviewer: Any | None,
    dispatch_fn: Any | None,
    max_retries: int,
    repo_root: Path,
) -> dict[str, Any]:
    lane = manifest.lane(lane_id)
    retry_count = 0
    current_run = dict(run_dict)
    accumulated_findings: list[str] = []
    while True:
        first_pass = await _tier_1_review(
            manifest=manifest,
            lane_id=lane_id,
            artifact=artifact,
            run_dict=current_run,
            reviewer=reviewer,
            repo_root=repo_root,
            tier=3,
        )
        accumulated_findings = list(
            dict.fromkeys(
                accumulated_findings
                + [
                    str(item).strip()
                    for item in first_pass.get("findings", [])
                    if str(item).strip()
                ]
            )
        )
        if first_pass["status"] == "passed":
            first_pass["findings"] = list(accumulated_findings)
            first_pass["retry_count"] = retry_count
            return first_pass
        if retry_count >= max(0, int(max_retries)):
            return {
                "status": "needs_human",
                "tier": 3,
                "findings": list(accumulated_findings),
                "changed_files": _changed_files_from_run(current_run),
                "retry_count": retry_count,
            }
        retry_count += 1
        retry_spec = _retry_spec_from_findings(
            manifest=manifest,
            lane_id=lane_id,
            findings=list(accumulated_findings),
        )
        dispatch = dispatch_fn or _default_dispatch
        result = await dispatch(
            retry_spec,
            target_branch=_manifest_base_branch(manifest, fallback="main"),
            budget_limit_usd=_lane_budget_limit_usd(lane),
            repo_path=repo_root,
            default_target_agent=_lane_target_agent(lane, fallback="codex"),
            default_reviewer_agent=_lane_review_model(
                lane,
                target_agent=_lane_target_agent(lane, fallback="codex"),
            ),
        )
        next_run = result.get("run") if isinstance(result.get("run"), dict) else {}
        if str(result.get("status", "")).strip().lower() != "completed" or not next_run:
            return {
                "status": "needs_human",
                "tier": 3,
                "findings": list(accumulated_findings),
                "changed_files": _changed_files_from_run(current_run),
                "retry_count": retry_count,
            }
        current_run = dict(next_run)


def run_verification_passed(run_dict: dict[str, Any], *, has_verification_commands: bool) -> bool:
    work_orders = [item for item in run_dict.get("work_orders", []) if isinstance(item, dict)]
    verification_results = [
        entry
        for item in work_orders
        for entry in item.get("verification_results", [])
        if isinstance(entry, dict)
    ]
    if verification_results:
        return all(bool(entry.get("passed", False)) for entry in verification_results)
    exit_codes = [
        item.get("exit_code") for item in work_orders if item.get("exit_code") is not None
    ]
    if exit_codes:
        return all(int(cast(Any, code)) == 0 for code in exit_codes)
    return not has_verification_commands


def _retry_spec_from_findings(
    *,
    manifest: TrancheManifest,
    lane_id: str,
    findings: list[str],
) -> Any:
    lane = manifest.lane(lane_id)
    spec = _lane_spec_from_manifest(manifest, lane)
    extra_constraints = [
        f"Address review finding: {item}" for item in findings if str(item).strip()
    ]
    spec.constraints = list(dict.fromkeys(list(spec.constraints) + extra_constraints))
    return spec


async def _default_dispatch(spec: Any, **kwargs: Any) -> dict[str, Any]:
    from aragora.swarm.boss_loop import dispatch_bounded_spec

    return await dispatch_bounded_spec(spec, **kwargs)
