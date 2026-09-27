"""Milestone-aware initiative integration on top of campaign manifests.

The initiative layer reuses the campaign executor as the slice execution
contract and adds:

- milestone progress reporting
- terminal handling for published PR slices
- dependency-aware draft promotion / merge ordering
- feature-flag-required merge gating
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aragora.swarm.campaign import (
    CampaignExecutor,
    CampaignManifest,
    CampaignProject,
    CampaignProjectStatus,
    load_campaign_manifest,
    locked_manifest_path,
    save_campaign_manifest,
)
from aragora.swarm.merge_arbiter import (
    REQUIRED_CHECKS,
    ArbiterOperationalError,
    CheckSnapshotHeadMismatch,
    _classify_required_checks,
    _get_check_status,
    _is_full_head_sha,
    _merge_pr,
    _promote_draft,
    _run_gh,
)
from aragora.swarm.pr_registry import PullRequestRegistry

logger = logging.getLogger(__name__)

DEFAULT_INITIATIVE_MANIFEST = ".aragora/campaign_manifest.yaml"
_RUNNABLE_PROJECT_STATUSES = frozenset(
    {
        CampaignProjectStatus.PENDING.value,
        CampaignProjectStatus.READY.value,
        CampaignProjectStatus.NEEDS_REVISION.value,
        CampaignProjectStatus.ACTIVE.value,
        CampaignProjectStatus.DELIVERED.value,
    }
)


def _project_milestone(project: CampaignProject) -> str:
    return str(project.milestone or "").strip() or "default"


def _project_pr_reference(project: CampaignProject) -> str | None:
    for candidate in (project.pr_url, project.adopted_pr):
        text = str(candidate or "").strip()
        if text:
            return text
    return None


def _parse_pr_number(reference: object) -> int | None:
    text = str(reference or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    marker = "/pull/"
    if marker in text:
        tail = text.split(marker, 1)[1].split("/", 1)[0].strip()
        if tail.isdigit():
            return int(tail)
    return None


def _gh_json(args: list[str], *, timeout: float = 30.0) -> Any:
    result = _run_gh(args, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout or "null")


def _get_pr_snapshot(
    pr_reference: object,
    *,
    repo: str,
) -> dict[str, Any] | None:
    pr_number = _parse_pr_number(pr_reference)
    ref = str(pr_number or pr_reference or "").strip()
    if not ref:
        return None
    try:
        payload = _gh_json(
            [
                "pr",
                "view",
                ref,
                "--repo",
                repo,
                "--json",
                "number,url,isDraft,state,headRefName,headRefOid,mergeStateStatus,mergedAt",
            ]
        )
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _find_open_pr_for_branch(branch: str, *, repo: str) -> dict[str, Any] | None:
    normalized = str(branch or "").strip()
    if not normalized:
        return None
    try:
        payload = _gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--head",
                normalized,
                "--json",
                "number,url,isDraft,state,headRefName,headRefOid,mergeStateStatus,mergedAt",
                "--limit",
                "10",
            ]
        )
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    return first if isinstance(first, dict) else None


def _is_pr_merged(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("mergedAt"):
        return True
    return str(snapshot.get("state", "")).strip().upper() == "MERGED"


def _is_pr_open(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if _is_pr_merged(snapshot):
        return False
    return str(snapshot.get("state", "")).strip().upper() in {"OPEN", "DRAFT", ""}


def _dependency_blockers(
    manifest: CampaignManifest,
    project: CampaignProject,
) -> list[str]:
    status_map = {item.project_id: item.status for item in manifest.projects}
    blockers: list[str] = []
    for dependency in project.dependencies:
        dep_status = status_map.get(dependency.project_id)
        if dep_status != CampaignProjectStatus.COMPLETED.value:
            blockers.append(dependency.project_id)
    return blockers


def _ordered_projects(manifest: CampaignManifest) -> list[CampaignProject]:
    projects = list(manifest.projects)
    if len(projects) < 2:
        return projects

    project_map = {project.project_id: project for project in projects}
    order = {project.project_id: index for index, project in enumerate(projects)}
    indegree = {project.project_id: 0 for project in projects}
    dependents: dict[str, list[str]] = {project.project_id: [] for project in projects}

    for project in projects:
        seen_dependencies: set[str] = set()
        for dependency in project.dependencies:
            dep_id = dependency.project_id
            if (
                dep_id == project.project_id
                or dep_id not in project_map
                or dep_id in seen_dependencies
            ):
                continue
            indegree[project.project_id] += 1
            dependents[dep_id].append(project.project_id)
            seen_dependencies.add(dep_id)

    ready = sorted(
        [project_id for project_id, degree in indegree.items() if degree == 0],
        key=order.__getitem__,
    )
    ordered_ids: list[str] = []
    while ready:
        project_id = ready.pop(0)
        ordered_ids.append(project_id)
        for dependent_id in sorted(dependents.get(project_id, []), key=order.__getitem__):
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                ready.append(dependent_id)
                ready.sort(key=order.__getitem__)

    if len(ordered_ids) < len(projects):
        remaining = sorted(
            [project.project_id for project in projects if project.project_id not in ordered_ids],
            key=order.__getitem__,
        )
        ordered_ids.extend(remaining)

    return [project_map[project_id] for project_id in ordered_ids]


class InitiativeIntegrator:
    """Milestone-aware integration and promotion for campaign-backed slices."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        repo_root: Path | None = None,
        target_branch: str = "main",
        repo: str = "synaptent/aragora",
        executor: CampaignExecutor | None = None,
        registry: PullRequestRegistry | None = None,
    ) -> None:
        self.manifest_path = manifest_path.resolve()
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.target_branch = target_branch
        self.repo = repo
        self.executor = executor or CampaignExecutor(
            manifest_path=self.manifest_path,
            repo_root=self.repo_root,
            target_branch=self.target_branch,
        )
        self.registry = registry or PullRequestRegistry(state_dir=self.repo_root / ".aragora")

    async def run(self) -> dict[str, Any]:
        self.sync_terminals()
        manifest = load_campaign_manifest(self.manifest_path)
        should_execute = any(
            project.status in _RUNNABLE_PROJECT_STATUSES for project in manifest.projects
        )
        if should_execute:
            campaign_payload = await self.executor.execute_once()
        else:
            campaign_payload = {
                "stop_reason": "promotion_pending",
                "dispatched_projects": [],
                "merge_ready_projects": [],
            }
        payload = self.status(refresh=True)
        payload.update(
            {
                "mode": "initiative-run",
                "executed": should_execute,
                "campaign": campaign_payload,
            }
        )
        return payload

    def status(self, *, refresh: bool = True) -> dict[str, Any]:
        if refresh:
            self.sync_terminals()
        manifest = load_campaign_manifest(self.manifest_path)
        slice_rows = [
            self._slice_status(manifest, project) for project in _ordered_projects(manifest)
        ]
        milestones: dict[str, dict[str, Any]] = {}
        for row in slice_rows:
            milestone = str(row["milestone"])
            bucket = milestones.setdefault(
                milestone,
                {
                    "milestone": milestone,
                    "total": 0,
                    "completed": 0,
                    "waiting_for_pr": 0,
                    "waiting_for_merge": 0,
                    "blocked": 0,
                    "promotable": 0,
                },
            )
            bucket["total"] += 1
            status = str(row["status"])
            if status == CampaignProjectStatus.COMPLETED.value:
                bucket["completed"] += 1
            if status == CampaignProjectStatus.WAITING_FOR_PR.value:
                bucket["waiting_for_pr"] += 1
            if status == CampaignProjectStatus.WAITING_FOR_MERGE.value:
                bucket["waiting_for_merge"] += 1
            if status in {
                CampaignProjectStatus.BLOCKED.value,
                CampaignProjectStatus.FAILED.value,
                CampaignProjectStatus.STALLED.value,
                CampaignProjectStatus.SKIPPED.value,
            }:
                bucket["blocked"] += 1
            if row["next_action"] in {"promote_draft", "merge"}:
                bucket["promotable"] += 1
        milestone_rows = list(milestones.values())
        total = len(slice_rows)
        completed = sum(
            1 for row in slice_rows if row["status"] == CampaignProjectStatus.COMPLETED.value
        )
        return {
            "mode": "initiative-status",
            "initiative_id": manifest.campaign_id,
            "manifest_path": str(self.manifest_path),
            "target_branch": self.target_branch,
            "repo": self.repo,
            "total_slices": total,
            "completed_slices": completed,
            "milestones_complete": sum(
                1 for row in milestone_rows if row["completed"] == row["total"]
            ),
            "milestones_total": len(milestone_rows),
            "milestones": milestone_rows,
            "slices": slice_rows,
        }

    def promote(
        self,
        *,
        project_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self.sync_terminals()
        manifest = load_campaign_manifest(self.manifest_path)
        projects = _ordered_projects(manifest)
        target: CampaignProject | None = None
        row: dict[str, Any] | None = None
        if project_id:
            target = manifest.project_map().get(project_id)
            if target is None:
                raise KeyError(f"Unknown project_id: {project_id}")
            row = self._slice_status(manifest, target)
        else:
            waiting_rows: list[tuple[CampaignProject, dict[str, Any]]] = []
            for candidate in projects:
                if candidate.status not in {
                    CampaignProjectStatus.WAITING_FOR_PR.value,
                    CampaignProjectStatus.WAITING_FOR_MERGE.value,
                }:
                    continue
                candidate_row = self._slice_status(manifest, candidate)
                waiting_rows.append((candidate, candidate_row))
                if candidate_row.get("next_action"):
                    target = candidate
                    row = candidate_row
                    break
            if target is None and waiting_rows:
                target, row = waiting_rows[0]

        if target is None:
            payload = self.status(refresh=False)
            payload.update(
                {
                    "mode": "initiative-promote",
                    "action": "noop",
                    "reason": "no waiting initiative slices",
                }
            )
            return payload

        if row is None:
            raise RuntimeError("initiative promote selected a slice without computed status")
        next_action = str(row.get("next_action") or "").strip()
        blockers = list(row.get("promotion_blockers", []) or [])
        if not next_action:
            return {
                "mode": "initiative-promote",
                "initiative_id": manifest.campaign_id,
                "project_id": target.project_id,
                "action": "blocked",
                "reason": blockers[0] if blockers else "slice is not promotable",
                "promotion_blockers": blockers,
            }

        pr_number = _parse_pr_number(row.get("pr_number") or row.get("pr_url"))
        if pr_number is None:
            return {
                "mode": "initiative-promote",
                "initiative_id": manifest.campaign_id,
                "project_id": target.project_id,
                "action": "blocked",
                "reason": "unable to resolve PR number for slice",
                "promotion_blockers": ["unable to resolve PR number for slice"],
            }

        if next_action == "promote_draft":
            if dry_run:
                return {
                    "mode": "initiative-promote",
                    "initiative_id": manifest.campaign_id,
                    "project_id": target.project_id,
                    "action": "would_promote_draft",
                    "pr_number": pr_number,
                    "pr_url": row.get("pr_url"),
                }
            promoted = _promote_draft(pr_number, self.repo)
            return {
                "mode": "initiative-promote",
                "initiative_id": manifest.campaign_id,
                "project_id": target.project_id,
                "action": "promoted_draft" if promoted else "blocked",
                "pr_number": pr_number,
                "pr_url": row.get("pr_url"),
                "reason": "" if promoted else "failed to promote draft PR",
            }

        if next_action == "merge":
            head_sha = str(row.get("head_sha") or "")
            if not _is_full_head_sha(head_sha):
                return {
                    "mode": "initiative-promote",
                    "initiative_id": manifest.campaign_id,
                    "project_id": target.project_id,
                    "action": "blocked",
                    "pr_number": pr_number,
                    "pr_url": row.get("pr_url"),
                    "reason": "PR snapshot missing valid full head SHA",
                }
            if dry_run:
                return {
                    "mode": "initiative-promote",
                    "initiative_id": manifest.campaign_id,
                    "project_id": target.project_id,
                    "action": "would_merge",
                    "pr_number": pr_number,
                    "pr_url": row.get("pr_url"),
                    "head_sha": head_sha,
                }
            merged, reason = _merge_pr(
                pr_number,
                self.repo,
                head_sha,
            )
            if not merged:
                return {
                    "mode": "initiative-promote",
                    "initiative_id": manifest.campaign_id,
                    "project_id": target.project_id,
                    "action": "blocked",
                    "pr_number": pr_number,
                    "pr_url": row.get("pr_url"),
                    "reason": reason,
                }
            completion = self.executor.complete_project(
                target.project_id,
                pr_url=str(row.get("pr_url") or "") or None,
            )
            return {
                "mode": "initiative-promote",
                "initiative_id": manifest.campaign_id,
                "project_id": target.project_id,
                "action": "merged",
                "pr_number": pr_number,
                "pr_url": row.get("pr_url"),
                "completion": completion,
            }

        return {
            "mode": "initiative-promote",
            "initiative_id": manifest.campaign_id,
            "project_id": target.project_id,
            "action": "blocked",
            "reason": f"unsupported promotion action: {next_action}",
        }

    def sync_terminals(self) -> None:
        merged_projects: list[tuple[str, str | None]] = []
        changed = False
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            for project in manifest.projects:
                snapshot = self._resolve_project_pr_snapshot(project)
                pr_ref = _project_pr_reference(project)
                if _is_pr_merged(snapshot):
                    merged_pr = str((snapshot or {}).get("url") or pr_ref or "").strip() or None
                    if merged_pr and project.pr_url != merged_pr:
                        project.pr_url = merged_pr
                        changed = True
                    if project.status == CampaignProjectStatus.COMPLETED.value:
                        continue
                    if project.status != CampaignProjectStatus.WAITING_FOR_MERGE.value:
                        project.status = CampaignProjectStatus.WAITING_FOR_MERGE.value
                        changed = True
                    merged_projects.append((project.project_id, merged_pr))
                    continue

                if _is_pr_open(snapshot) or pr_ref:
                    desired_pr = (
                        str((snapshot or {}).get("url") or pr_ref or "").strip() or project.pr_url
                    )
                    desired_branch = (
                        str((snapshot or {}).get("headRefName") or project.branch or "").strip()
                        or project.branch
                    )
                    if desired_pr and project.pr_url != desired_pr:
                        project.pr_url = desired_pr
                        changed = True
                    if desired_branch and project.branch != desired_branch:
                        project.branch = desired_branch
                        changed = True
                    if project.status != CampaignProjectStatus.WAITING_FOR_MERGE.value:
                        project.status = CampaignProjectStatus.WAITING_FOR_MERGE.value
                        changed = True
                    continue

                if project.branch and project.status in _RUNNABLE_PROJECT_STATUSES:
                    project.status = CampaignProjectStatus.WAITING_FOR_PR.value
                    changed = True

            if changed:
                save_campaign_manifest(self.manifest_path, manifest)

        for project_id, pr_url in merged_projects:
            try:
                self.executor.complete_project(project_id, pr_url=pr_url)
            except ValueError:
                logger.debug("initiative sync skipped completion for %s", project_id, exc_info=True)

    def _resolve_project_pr_snapshot(self, project: CampaignProject) -> dict[str, Any] | None:
        project_pr = _project_pr_reference(project)
        if project_pr:
            snapshot = _get_pr_snapshot(project_pr, repo=self.repo)
            if snapshot is not None:
                return snapshot
            fallback_number = _parse_pr_number(project_pr)
            return {
                "number": fallback_number,
                "url": project_pr,
                "isDraft": None,
                "state": "UNKNOWN",
                "headRefName": project.branch,
                "headRefOid": None,
                "mergeStateStatus": "",
                "mergedAt": None,
            }

        branch = str(project.branch or "").strip()
        if branch:
            registry_entry = self.registry.get(branch)
            if isinstance(registry_entry, dict):
                registry_pr = str(registry_entry.get("pr_url") or "").strip()
                if registry_pr:
                    snapshot = _get_pr_snapshot(registry_pr, repo=self.repo)
                    if snapshot is not None:
                        return snapshot
                    return {
                        "number": _parse_pr_number(registry_pr),
                        "url": registry_pr,
                        "isDraft": None,
                        "state": "UNKNOWN",
                        "headRefName": branch,
                        "headRefOid": None,
                        "mergeStateStatus": "",
                        "mergedAt": None,
                    }
            return _find_open_pr_for_branch(branch, repo=self.repo)
        return None

    def _slice_status(
        self,
        manifest: CampaignManifest,
        project: CampaignProject,
    ) -> dict[str, Any]:
        snapshot = self._resolve_project_pr_snapshot(project)
        pr_number = _parse_pr_number((snapshot or {}).get("number") or (snapshot or {}).get("url"))
        head_sha = (snapshot or {}).get("headRefOid")
        check_snapshot_error: str | None = None
        try:
            checks = (
                _get_check_status(pr_number, self.repo, str(head_sha))
                if pr_number is not None and _is_full_head_sha(head_sha)
                else {}
            )
        except CheckSnapshotHeadMismatch as exc:
            checks = {}
            check_snapshot_error = str(exc)
        except ArbiterOperationalError:
            # Status reporting degrades to "checks unknown" on gh faults; only
            # the arbiter poll loop feeds these faults to its circuit breaker.
            checks = {}
        missing_checks, failing_checks = _classify_required_checks(checks)
        dependency_blockers = _dependency_blockers(manifest, project)
        promotion_blockers: list[str] = []
        next_action: str | None = None

        if project.status == CampaignProjectStatus.WAITING_FOR_PR.value and not snapshot:
            promotion_blockers.append("published PR not found for branch deliverable")
        elif project.status == CampaignProjectStatus.WAITING_FOR_MERGE.value:
            if check_snapshot_error:
                promotion_blockers.append(check_snapshot_error)
            if snapshot is not None and not _is_full_head_sha(head_sha):
                promotion_blockers.append("PR snapshot missing valid full head SHA")
            if dependency_blockers:
                promotion_blockers.append(
                    "dependencies not merged: " + ", ".join(dependency_blockers)
                )
            if missing_checks:
                promotion_blockers.append("missing checks: " + ", ".join(missing_checks))
            if failing_checks:
                promotion_blockers.append("failing checks: " + ", ".join(failing_checks))
            if snapshot is None:
                promotion_blockers.append("PR snapshot unavailable")
            elif bool(snapshot.get("isDraft")):
                if not promotion_blockers:
                    next_action = "promote_draft"
            else:
                if project.feature_flag_required and not project.feature_flag:
                    promotion_blockers.append("feature flag required before merge")
                if not promotion_blockers and not _is_pr_merged(snapshot):
                    next_action = "merge"

        return {
            "project_id": project.project_id,
            "title": project.title,
            "milestone": _project_milestone(project),
            "status": project.status,
            "branch": project.branch,
            "pr_url": (snapshot or {}).get("url") or _project_pr_reference(project),
            "pr_number": pr_number,
            "head_sha": head_sha if _is_full_head_sha(head_sha) else None,
            "pr_draft": bool(snapshot.get("isDraft")) if isinstance(snapshot, dict) else None,
            "pr_state": str((snapshot or {}).get("state") or "").strip() or None,
            "dependencies": [dep.project_id for dep in project.dependencies],
            "dependency_blockers": dependency_blockers,
            "feature_flag": project.feature_flag,
            "feature_flag_required": project.feature_flag_required,
            "execution_terminal": bool(_project_pr_reference(project) or _is_pr_open(snapshot)),
            "required_checks": list(REQUIRED_CHECKS),
            "missing_checks": missing_checks,
            "failing_checks": failing_checks,
            "next_action": next_action,
            "promotion_blockers": promotion_blockers,
        }


__all__ = [
    "DEFAULT_INITIATIVE_MANIFEST",
    "InitiativeIntegrator",
]
