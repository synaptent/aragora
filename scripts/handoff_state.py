#!/usr/bin/env python3
"""Read-only handoff state classifier for Aragora automation outbox items."""

from __future__ import annotations

import dataclasses
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:  # Works both as ``python scripts/handoff_state.py`` and as ``scripts.handoff_state``.
    from scripts.github_cli_health import github_cli_env
except Exception:  # pragma: no cover - script-path fallback
    try:
        from github_cli_health import github_cli_env  # type: ignore[no-redef]
    except Exception:  # pragma: no cover - partially bootstrapped fallback

        def github_cli_env(
            base_env: Mapping[str, str] | None = None,
            *,
            prefer_app: bool = True,
        ) -> dict[str, str]:
            return dict(os.environ if base_env is None else base_env)


UTC = timezone.utc
SCHEMA_VERSION = "aragora-handoff-state/1.0"

DEFAULT_REPO_ROOT = Path(".")
DEFAULT_OUTBOX_DIR = Path(".aragora/automation-outbox")
DEFAULT_RECEIPT_DIR = Path(".aragora/automation-receipts")
DEFAULT_STATUS_CACHE = Path(".aragora/automation-github-status/latest.json")
DEFAULT_LANE_REGISTRY = Path(".aragora/agent-bridge/lanes.json")
DEFAULT_STEERING_ROOT = Path(".aragora/operator-steering")
DEFAULT_HEARTBEATS = Path(".aragora/agent-bridge/heartbeats.json")
DEFAULT_QUEUE_CAP_CACHE_MAX_AGE_SECONDS = 1800
DEFAULT_PR_BASE = "main"
URL_PATTERN = re.compile(r"https?://\S+")

TERMINAL_RECEIPT_STATUSES = {"published", "already_satisfied", "completed", "skipped"}
ACTIVE_LANE_STATUSES = {
    "acknowledged",
    "active",
    "blocked",
    "blocked_on_publication",
    "claimed",
    "pending",
    "queued",
    "running",
    "waiting_for_steering",
    "working",
}
BLOCKING_LANE_STATUSES = {
    "blocked",
    "blocked_on_publication",
    "waiting_for_steering",
}
PR_PUBLICATION_ACTIONS = {
    "open_pr",
    "open_pull_request",
    "open_or_update_pr",
    "open_or_update_pull_request",
    "push_branch_and_open_pr",
    "push_branch_and_open_pull_request",
    "push_branch_and_open_or_update_pr",
    "push_branch_and_open_or_update_pull_request",
}
PR_PUBLICATION_IDEMPOTENCY_PREFIXES = ("open-pr-", "update-pr-")
HEAD_FIELD_KEYS = (
    "desired_head_sha",
    "target_head_sha",
    "head_sha",
    "headRefOid",
    "head_ref_oid",
    "head",
    "commit",
)
BASE_FIELD_KEYS = (
    "base",
    "base_ref",
    "base_ref_name",
    "baseRefName",
    "target_base",
    "base_branch",
)
LOCAL_WORK_MARKER_KEYS = (
    "uncommitted_changes",
    "has_uncommitted_changes",
    "uncommitted",
    "unpushed_commits",
    "local_changes",
    "local_work",
    "dirty",
)
OWNER_WORK_MARKER_KEYS = (
    *LOCAL_WORK_MARKER_KEYS,
    "dirty_worktree",
    "branch_ahead",
    "branch_ahead_of_origin_main",
    "has_unique_commits",
    "unique_commits",
    "worktree_dirty",
)
LOCAL_WORK_FALSE_MARKER_VALUES = frozenset(
    (
        "0",
        "clean",
        "false",
        "no",
        "none",
        "verified-clean",
        "verified_clean",
    )
)
LOCAL_WORK_TRUE_MARKER_VALUES = frozenset(
    (
        "1",
        "ahead",
        "branch_ahead",
        "dirty",
        "local_work",
        "possible_unpushed_work",
        "true",
        "uncommitted",
        "uncommitted_changes",
        "unpushed",
        "unpushed_commits",
        "yes",
    )
)


class HandoffState(str, Enum):
    PUBLICATION_REQUESTED = "publication_requested"
    REPRESENTED_BY_EXACT_OPEN_PR = "represented_by_exact_open_pr"
    REPRESENTED_BY_EXACT_REMOTE_BRANCH = "represented_by_exact_remote_branch"
    BLOCKED_BY_OWNER = "blocked_by_owner"
    BLOCKED_BY_HUMAN = "blocked_by_human"
    BLOCKED_BY_POSSIBLE_UNPUSHED_WORK = "blocked_by_possible_unpushed_work"
    BLOCKED_BY_LIVE_QUEUE_CAP = "blocked_by_live_queue_cap"
    PRESERVED_NOT_ACTIONABLE = "preserved_not_actionable"
    UNKNOWN = "unknown"


@dataclass
class GitHubEvidence:
    mode: str
    error: str | None = None
    open_prs: list[dict[str, Any]] = field(default_factory=list)
    exact_open_pr: dict[str, Any] | None = None
    remote_ref: dict[str, Any] | None = None


@dataclass
class ReceiptEvidence:
    status: str | None = None
    reason: str | None = None
    has_pr_reference: bool = False
    has_issue_reference: bool = False
    issue_only_pr_receipt: bool = False
    path: str | None = None
    target_pr: int | None = None


@dataclass
class OwnerEvidence:
    available: bool = False
    matched: bool = False
    error: str | None = None
    lane_id: str | None = None
    owner_session: str | None = None
    source: str | None = None
    status: str | None = None
    owner_state: str | None = None
    owner_blocking_state: str | None = None
    owner_blocking_state_reason: str | None = None
    advisory_withheld: str | None = None
    stale_claim_available: bool | None = None
    payload: dict[str, Any] | None = None


@dataclass
class SteeringEvidence:
    pending_message_count: int = 0
    blocking_message_count: int = 0
    resolved_read_receipt_count: int = 0
    human_message_count: int = 0
    latest_message: dict[str, Any] | None = None
    latest_read_receipt: dict[str, Any] | None = None
    ack_protocol: str = "top_level_message_remains_pending"


@dataclass
class QueueCapEvidence:
    available: bool = False
    github_queue_available: bool | None = None
    degraded: bool | None = None
    degraded_reason: str | None = None
    open_pr_cap_reached: bool | None = None
    raw_open_pr_cap_reached: bool | None = None
    open_codex_pr_count: int | None = None
    max_open_prs: int | None = None
    generated_at: str | None = None
    cache_age_seconds: float | None = None
    cache_stale: bool | None = None
    cache_stale_threshold_seconds: int | None = None
    decision_source: str | None = None


@dataclass
class HandoffClassification:
    outbox_file: str
    idempotency_key: str | None
    branch: str | None
    desired_head_sha: str | None
    state: HandoffState
    reason: str
    evidence: dict[str, Any]
    next_mutation_candidate: str = "none"
    safe_to_mutate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "outbox_file": self.outbox_file,
            "idempotency_key": self.idempotency_key,
            "branch": self.branch,
            "desired_head_sha": self.desired_head_sha,
            "state": self.state.value,
            "reason": self.reason,
            "evidence": self.evidence,
            "next_mutation_candidate": self.next_mutation_candidate,
            "safe_to_mutate": self.safe_to_mutate,
        }


class NarrowGitHubClient:
    """Narrow REST-only GitHub reader.

    This intentionally uses exact branch/ref endpoints and never calls GraphQL
    or mutating gh commands.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        github_repo: str,
        disabled: bool = False,
        timeout_seconds: int = 20,
    ) -> None:
        self.repo_root = repo_root
        self.github_repo = github_repo
        self.disabled = disabled
        self.timeout_seconds = timeout_seconds
        self._pr_cache: dict[str, tuple[list[dict[str, Any]] | None, str | None]] = {}
        self._pr_number_cache: dict[int, tuple[dict[str, Any] | None, str | None]] = {}
        self._ref_cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}

    @property
    def mode(self) -> str:
        if self.disabled:
            return "disabled"
        return "ready"

    def open_prs_for_branch(self, branch: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        if self.disabled:
            return None, "github disabled"
        if branch in self._pr_cache:
            return self._pr_cache[branch]
        result: tuple[list[dict[str, Any]] | None, str | None]
        owner, repo_error = _github_repo_owner(self.github_repo)
        if repo_error is not None:
            result = (None, repo_error)
            self._pr_cache[branch] = result
            return result
        head = f"{owner}:{quote(branch, safe='')}"
        per_page = 100
        items: list[dict[str, Any]] = []
        max_pages = 20
        for page in range(1, max_pages + 1):
            endpoint = (
                f"repos/{self.github_repo}/pulls?state=open&head={head}"
                f"&per_page={per_page}&page={page}"
            )
            payload, error = self._api(endpoint)
            if error is not None:
                result = (None, error)
                break
            if not isinstance(payload, list):
                result = (None, "open PR REST response was not a list")
                break
            items.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < per_page:
                result = (items, None)
                break
        else:
            result = (
                None,
                f"open PR REST page cap reached after {max_pages} pages for exact branch",
            )
        self._pr_cache[branch] = result
        return result

    def open_pr_by_number(self, pr_number: int) -> tuple[dict[str, Any] | None, str | None]:
        if self.disabled:
            return None, "github disabled"
        if pr_number in self._pr_number_cache:
            return self._pr_number_cache[pr_number]
        result: tuple[dict[str, Any] | None, str | None]
        _, repo_error = _github_repo_owner(self.github_repo)
        if repo_error is not None:
            result = (None, repo_error)
            self._pr_number_cache[pr_number] = result
            return result
        payload, error = self._api(f"repos/{self.github_repo}/pulls/{pr_number}")
        if error is not None and _github_not_found_error(error):
            result = (None, None)
        elif error is not None:
            result = (None, error)
        elif not isinstance(payload, dict):
            result = (None, "target PR REST response was not a mapping")
        else:
            result = (payload, None)
        self._pr_number_cache[pr_number] = result
        return result

    def remote_ref(self, branch: str) -> tuple[dict[str, Any] | None, str | None]:
        if self.disabled:
            return None, "github disabled"
        if branch in self._ref_cache:
            return self._ref_cache[branch]
        result: tuple[dict[str, Any] | None, str | None]
        _, repo_error = _github_repo_owner(self.github_repo)
        if repo_error is not None:
            result = (None, repo_error)
            self._ref_cache[branch] = result
            return result
        endpoint = f"repos/{self.github_repo}/git/ref/heads/{quote(branch, safe='/')}"
        payload, error = self._api(endpoint)
        if error is not None and _github_not_found_error(error):
            result = (None, None)
        elif error is not None:
            result = (None, error)
        elif not isinstance(payload, dict):
            result = (None, "ref REST response was not a mapping")
        else:
            result = (payload, None)
        self._ref_cache[branch] = result
        return result

    def _api(self, endpoint: str) -> tuple[Any | None, str | None]:
        try:
            proc = subprocess.run(
                ["gh", "api", endpoint],
                cwd=self.repo_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                env=github_cli_env(os.environ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"gh api failed ({exc.__class__.__name__})"
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            message = detail[0] if detail else ""
            prefix = "github_not_found: " if _gh_stderr_is_not_found(message) else ""
            return None, f"{prefix}gh api exited {proc.returncode}: {message}"
        try:
            return json.loads(proc.stdout), None
        except json.JSONDecodeError:
            return None, "gh api returned unparseable JSON"


class OwnerProbe:
    """Read-only owner/liveness probe via the existing supported helper."""

    def __init__(self, *, repo_root: Path, state_root: Path, timeout_seconds: int = 20) -> None:
        self.repo_root = repo_root
        self.state_root = _as_aragora_root(state_root)
        self.timeout_seconds = timeout_seconds
        self._cache: dict[str, OwnerEvidence] = {}

    def probe(self, branch: str) -> OwnerEvidence:
        if branch in self._cache:
            return self._cache[branch]
        registry = self.state_root / "agent-bridge" / "lanes.json"
        steering_root = self.state_root / "operator-steering"
        heartbeat_path = self.state_root / "agent-bridge" / "heartbeats.json"
        script = self.repo_root / "scripts" / "identify_lane_owner.py"
        cmd = [
            sys.executable,
            str(script),
            "--branch",
            branch,
            "--liveness",
            "--json",
            "--registry-path",
            str(registry),
            "--steering-inbox-root",
            str(steering_root),
            "--heartbeat-path",
            str(heartbeat_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.repo_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = OwnerEvidence(
                available=False, error=f"owner probe failed ({exc.__class__.__name__})"
            )
            self._cache[branch] = result
            return result
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip().splitlines()
            text = message[0] if message else f"identify_lane_owner exited {proc.returncode}"
            no_match = _owner_probe_no_match(text)
            result = OwnerEvidence(
                available=no_match,
                matched=False,
                error=text,
            )
            self._cache[branch] = result
            return result
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result = OwnerEvidence(available=False, error="owner probe returned unparseable JSON")
            self._cache[branch] = result
            return result
        if not isinstance(payload, dict):
            result = OwnerEvidence(available=False, error="owner probe returned non-mapping JSON")
            self._cache[branch] = result
            return result
        result = owner_evidence_from_payload(payload)
        self._cache[branch] = result
        return result


class LaneRegistryOwnerProbe:
    """Fast read-only owner probe from the shared lane registry.

    This is intentionally less deep than identify_lane_owner.py --liveness, but
    it is enough to keep whole-outbox classification bounded and deterministic.
    Focused runs can still opt into the supported liveness helper.
    """

    def __init__(self, *, state_root: Path) -> None:
        self.state_root = _as_aragora_root(state_root)
        self.records = _load_lane_records(self.state_root / "agent-bridge" / "lanes.json")

    def probe(self, branch: str) -> OwnerEvidence:
        candidates = [row for row in self.records if str(row.get("branch") or "") == branch]
        if not candidates:
            return OwnerEvidence(
                available=True,
                matched=False,
                error="no lane matched",
                source="lane_registry",
            )
        row = _best_lane_record(candidates)
        status = str(row.get("status") or "").strip().lower()
        blocking_state = str(row.get("owner_blocking_state") or "").strip() or None
        if blocking_state is None and status in BLOCKING_LANE_STATUSES:
            blocking_state = "unknown_owner"
        elif blocking_state is None and status in ACTIVE_LANE_STATUSES:
            blocking_state = "unknown_owner"
        evidence = owner_evidence_from_payload(row)
        evidence.source = evidence.source or "lane_registry"
        evidence.status = status or evidence.status
        evidence.owner_blocking_state = evidence.owner_blocking_state or blocking_state
        evidence.owner_blocking_state_reason = evidence.owner_blocking_state_reason or (
            _lane_registry_blocking_reason(status, blocking_state) if blocking_state else None
        )
        evidence.advisory_withheld = evidence.advisory_withheld or _possible_unpushed_marker(row)
        return evidence


def owner_evidence_from_payload(payload: Mapping[str, Any]) -> OwnerEvidence:
    advisory = payload.get("stale_claim_advisory")
    available = None
    if isinstance(advisory, Mapping):
        available = bool(advisory.get("available"))
    owner_session = _first_text(payload, "owner_session", "session", "to_session")
    lane_id = _first_text(payload, "lane_id", "lane")
    return OwnerEvidence(
        available=True,
        matched=True,
        lane_id=lane_id,
        owner_session=owner_session,
        source=_first_text(payload, "source"),
        status=_first_text(payload, "status", "lane_status"),
        owner_state=_first_text(payload, "owner_state", "assessed"),
        owner_blocking_state=_first_text(payload, "owner_blocking_state"),
        owner_blocking_state_reason=_first_text(payload, "owner_blocking_state_reason"),
        advisory_withheld=_first_text(payload, "advisory_withheld")
        or _possible_unpushed_marker(payload, marker_keys=OWNER_WORK_MARKER_KEYS),
        stale_claim_available=available,
        payload=_owner_payload_summary(payload),
    )


def _possible_unpushed_marker(
    payload: Mapping[str, Any],
    *,
    marker_keys: Sequence[str] = LOCAL_WORK_MARKER_KEYS,
) -> str | None:
    if _first_text(payload, "advisory_withheld") == "possible_unpushed_work":
        return "possible_unpushed_work"
    for key in (
        "owner_blocking_state_reason",
        "withheld_reason",
        "cleanup_state",
        "decision",
    ):
        value = str(payload.get(key) or "").strip().lower()
        if value == "possible_unpushed_work" or "possible unpushed work" in value:
            return "possible_unpushed_work"
    for key in marker_keys:
        marker = payload.get(key)
        if marker is True:
            return "possible_unpushed_work"
        if isinstance(marker, int) and marker > 0:
            return "possible_unpushed_work"
        if isinstance(marker, str):
            string_marker = _local_work_string_marker(marker)
            if string_marker is True:
                return "possible_unpushed_work"
        if (
            isinstance(marker, Sequence)
            and not isinstance(marker, (str, bytes, bytearray))
            and marker
        ):
            return "possible_unpushed_work"
    for key in ("stale_claim_advisory", "owner_liveness", "cleanup_safety"):
        section = payload.get(key)
        if isinstance(section, Mapping) and _possible_unpushed_marker(
            section, marker_keys=marker_keys
        ):
            return "possible_unpushed_work"
    advisory = payload.get("stale_claim_advisory")
    if isinstance(advisory, Mapping) and advisory.get("available") is True:
        return None
    return None


def _local_work_string_marker(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized:
        return False
    if normalized in LOCAL_WORK_FALSE_MARKER_VALUES:
        return False
    if normalized in LOCAL_WORK_TRUE_MARKER_VALUES:
        return True
    # Unknown non-empty markers fail closed: producer-specific sentinels must be
    # explicitly allowlisted before they can prove absence of local work.
    return True


def _owner_payload_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep classifier evidence useful without exposing local session internals."""

    summary: dict[str, Any] = {}
    for key in (
        "lane_id",
        "branch",
        "status",
        "owner_state",
        "owner_blocking_state",
        "owner_blocking_state_reason",
        "advisory_withheld",
        "updated_at",
        "last_heartbeat_at",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            summary[key] = value
    advisory = payload.get("stale_claim_advisory")
    if isinstance(advisory, Mapping):
        compact = {
            key: advisory.get(key)
            for key in ("available", "protocol", "reason")
            if advisory.get(key) not in (None, "")
        }
        if compact:
            summary["stale_claim_advisory"] = compact
    return summary


def classify_handoffs(
    *,
    repo_root: Path,
    state_root: Path | None = None,
    github_repo: str | None = None,
    outbox_file: str | Path | None = None,
    no_github: bool = False,
    owner_timeout_seconds: int = 20,
    github_timeout_seconds: int = 20,
    with_liveness_helper: bool = False,
    queue_cache_max_age_seconds: int = DEFAULT_QUEUE_CAP_CACHE_MAX_AGE_SECONDS,
    github_client: Any | None = None,
    owner_probe: Any | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    state_root = resolve_state_root(repo_root=repo_root, state_root=state_root)
    github_repo = github_repo or _github_repo_from_origin(repo_root)
    outbox_dir = _state_path(state_root, DEFAULT_OUTBOX_DIR)
    receipt_dir = _state_path(state_root, DEFAULT_RECEIPT_DIR)
    status_cache_path = _state_path(state_root, DEFAULT_STATUS_CACHE)

    queue_cap = load_queue_cap_evidence(
        status_cache_path,
        max_age_seconds=queue_cache_max_age_seconds,
    )
    receipts = load_terminal_receipts(receipt_dir)
    outbox_files = _selected_outbox_files(outbox_dir, outbox_file)
    steering_rows = _steering_message_rows(_state_path(state_root, DEFAULT_STEERING_ROOT))
    gh = github_client or NarrowGitHubClient(
        repo_root=repo_root,
        github_repo=github_repo or "",
        disabled=no_github or github_repo is None,
        timeout_seconds=github_timeout_seconds,
    )
    if owner_probe is not None:
        owner = owner_probe
    elif with_liveness_helper:
        owner = OwnerProbe(
            repo_root=repo_root,
            state_root=state_root,
            timeout_seconds=owner_timeout_seconds,
        )
    else:
        owner = LaneRegistryOwnerProbe(state_root=state_root)

    items: list[HandoffClassification] = []
    github_errors: list[str] = []
    for path in outbox_files:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            items.append(
                HandoffClassification(
                    outbox_file=path.name,
                    idempotency_key=path.stem,
                    branch=None,
                    desired_head_sha=None,
                    state=HandoffState.UNKNOWN,
                    reason="outbox file is missing or unparseable",
                    evidence={},
                )
            )
            continue
        item = classify_handoff_item(
            path=path,
            payload=payload,
            receipt=receipts.get(str(payload.get("idempotency_key") or path.stem).strip()),
            queue_cap=queue_cap,
            github_client=gh,
            owner_probe=owner,
            state_root=state_root,
            steering_rows=steering_rows,
        )
        gh_error = item.evidence.get("github", {}).get("error")
        if isinstance(gh_error, str) and gh_error:
            github_errors.append(gh_error)
        items.append(item)

    counts = Counter(item.state.value for item in items)
    github_mode = (
        "disabled" if getattr(gh, "disabled", False) else ("partial" if github_errors else "ready")
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "repo": str(repo_root),
        "state_root": str(state_root),
        "github_repo": github_repo,
        "outbox_dir": str(outbox_dir),
        "receipt_dir": str(receipt_dir),
        "outbox_count": len(items),
        "counts": dict(sorted(counts.items())),
        "github": {
            "mode": github_mode,
            "error": github_errors[0] if github_errors else None,
            "item_error_count": len(github_errors),
            "partial_degradation": bool(github_errors) and not getattr(gh, "disabled", False),
        },
        "queue_cap": dataclasses.asdict(queue_cap),
        "items": [item.to_dict() for item in items],
    }
    return payload


def classify_handoff_item(
    *,
    path: Path,
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    queue_cap: QueueCapEvidence,
    github_client: Any,
    owner_probe: Any,
    state_root: Path,
    steering_rows: Sequence[Mapping[str, Any]] | None = None,
) -> HandoffClassification:
    idem = str(payload.get("idempotency_key") or path.stem).strip() or path.stem
    branch = branch_from_payload(payload)
    desired_head = desired_head_from_payload(payload)
    desired_base = desired_base_from_payload(payload)
    receipt_evidence = receipt_evidence_from_payload(receipt, payload)

    evidence: dict[str, Any] = {
        "receipt": dataclasses.asdict(receipt_evidence),
        "queue_cap": dataclasses.asdict(queue_cap),
    }
    local_conflict_reason = local_evidence_conflict_reason(payload)
    if local_conflict_reason is not None:
        evidence["local_evidence"] = {
            "record_count": len(_local_evidence_mappings(payload.get("local_evidence"))),
            "conflict": local_conflict_reason,
        }
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch or None,
            desired_head_sha=desired_head or None,
            state=HandoffState.UNKNOWN,
            reason=local_conflict_reason,
            evidence=evidence,
        )
    if not branch:
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=None,
            desired_head_sha=desired_head or None,
            state=HandoffState.UNKNOWN,
            reason="outbox payload has no branch",
            evidence=evidence,
        )

    github = github_evidence_for_branch(
        github_client,
        branch,
        desired_head,
        desired_base,
        target_pr=receipt_evidence.target_pr,
    )
    evidence["github"] = dataclasses.asdict(github)
    owner = owner_probe.probe(branch) if branch else OwnerEvidence()
    local_work_marker = _payload_possible_unpushed_marker(payload)
    if local_work_marker and owner.advisory_withheld is None:
        owner = dataclasses.replace(owner, advisory_withheld=local_work_marker)
    evidence["owner"] = dataclasses.asdict(owner)
    steering = steering_evidence_for_branch(
        state_root=state_root,
        branch=branch,
        owner_session=owner.owner_session,
        lane_id=owner.lane_id,
        message_rows=steering_rows,
    )
    evidence["steering"] = dataclasses.asdict(steering)
    if not desired_head and github.open_prs:
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=None,
            state=HandoffState.UNKNOWN,
            reason="branch has open PR(s) but handoff has no desired head to verify",
            evidence=evidence,
        )

    if github.exact_open_pr is not None:
        number = github.exact_open_pr.get("number")
        if _possible_unpushed(owner):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.BLOCKED_BY_POSSIBLE_UNPUSHED_WORK,
                reason=f"branch has exact-head open PR #{number} but possible unpushed work exists",
                evidence=evidence,
                next_mutation_candidate="owner_preservation_request",
            )
        if _human_blocked(owner, steering):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.BLOCKED_BY_HUMAN,
                reason=f"branch has exact-head open PR #{number} but human gate remains",
                evidence=evidence,
                next_mutation_candidate="human_gate",
            )
        if _owner_blocked(owner, steering):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.BLOCKED_BY_OWNER,
                reason=f"branch has exact-head open PR #{number} but owner gate remains",
                evidence=evidence,
                next_mutation_candidate="owner_followup",
            )
        if github.exact_open_pr.get("draft") is True:
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.REPRESENTED_BY_EXACT_OPEN_PR,
                reason=f"branch has exact-head draft open PR #{number}",
                evidence=evidence,
            )
        if github.mode != "ready":
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.REPRESENTED_BY_EXACT_OPEN_PR,
                reason=f"branch has exact-head open PR #{number} but GitHub PR evidence is degraded",
                evidence=evidence,
            )
        mutation_guard = _exact_open_pr_mutation_guard(
            github.exact_open_pr,
            desired_head,
            owner,
        )
        if mutation_guard:
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.REPRESENTED_BY_EXACT_OPEN_PR,
                reason=f"branch has exact-head open PR #{number} but {mutation_guard}",
                evidence=evidence,
            )
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.REPRESENTED_BY_EXACT_OPEN_PR,
            reason=f"branch has exact-head open PR #{number}",
            evidence=evidence,
            next_mutation_candidate="write_representation_receipt_then_archive",
            safe_to_mutate=True,
        )

    remote_exact_head = _remote_ref_matches(github.remote_ref, desired_head)
    remote_mutation_guard = _remote_ref_mutation_guard(github.remote_ref, desired_head, owner)
    if remote_exact_head and _possible_unpushed(owner):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.BLOCKED_BY_POSSIBLE_UNPUSHED_WORK,
            reason="desired head is preserved by exact remote branch but possible unpushed work exists",
            evidence=evidence,
            next_mutation_candidate="owner_preservation_request",
        )

    if remote_exact_head:
        if _human_blocked(owner, steering):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.BLOCKED_BY_HUMAN,
                reason="desired head is preserved by exact remote branch but human gate remains",
                evidence=evidence,
                next_mutation_candidate="human_gate",
            )
        if _owner_blocked(owner, steering):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.BLOCKED_BY_OWNER,
                reason="desired head is preserved by exact remote branch but owner gate remains",
                evidence=evidence,
                next_mutation_candidate="owner_followup",
            )
        if github.mode in {"degraded", "disabled"}:
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.UNKNOWN,
                reason="GitHub PR evidence is unavailable; cannot prove absence of exact open PR",
                evidence=evidence,
            )
        if github.open_prs:
            if is_pr_publication_request(payload):
                if queue_cap.open_pr_cap_reached:
                    return HandoffClassification(
                        outbox_file=path.name,
                        idempotency_key=idem,
                        branch=branch,
                        desired_head_sha=desired_head or None,
                        state=HandoffState.BLOCKED_BY_LIVE_QUEUE_CAP,
                        reason="remote branch is exact but existing open PR is not exact and open PR cap is reached",
                        evidence=evidence,
                        next_mutation_candidate="queue_drain",
                    )
                if _queue_cap_uncertain_for_publication(queue_cap):
                    return HandoffClassification(
                        outbox_file=path.name,
                        idempotency_key=idem,
                        branch=branch,
                        desired_head_sha=desired_head or None,
                        state=HandoffState.UNKNOWN,
                        reason=(
                            "remote branch is exact but queue-cap evidence is stale or unavailable; "
                            "cannot prove publication is safe"
                        ),
                        evidence=evidence,
                    )
                return HandoffClassification(
                    outbox_file=path.name,
                    idempotency_key=idem,
                    branch=branch,
                    desired_head_sha=desired_head or None,
                    state=HandoffState.PUBLICATION_REQUESTED,
                    reason="remote branch is exact but existing open PR head does not match desired head",
                    evidence=evidence,
                    next_mutation_candidate="publish_or_represent_pr",
                )
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.UNKNOWN,
                reason=(
                    "remote branch is exact but existing open PR head does not match desired head; "
                    "manual reconciliation is required before treating the branch as preserved"
                ),
                evidence=evidence,
            )
        if queue_cap.open_pr_cap_reached and is_pr_publication_request(payload):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.BLOCKED_BY_LIVE_QUEUE_CAP,
                reason="remote branch is exact but live cache reports open PR cap reached",
                evidence=evidence,
                next_mutation_candidate="queue_drain",
            )
        if _queue_cap_uncertain_for_publication(queue_cap) and is_pr_publication_request(payload):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.UNKNOWN,
                reason=(
                    "remote branch is exact but queue-cap evidence is stale or unavailable; "
                    "cannot prove publication is safe"
                ),
                evidence=evidence,
            )
        if is_pr_publication_request(payload):
            return HandoffClassification(
                outbox_file=path.name,
                idempotency_key=idem,
                branch=branch,
                desired_head_sha=desired_head or None,
                state=HandoffState.PUBLICATION_REQUESTED,
                reason="remote branch is exact but PR publication remains requested",
                evidence=evidence,
                next_mutation_candidate="publish_or_represent_pr",
            )
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.REPRESENTED_BY_EXACT_REMOTE_BRANCH,
            reason=(
                f"desired head is preserved by exact remote branch but {remote_mutation_guard}"
                if remote_mutation_guard
                else "desired head is preserved by exact remote branch"
            ),
            evidence=evidence,
            next_mutation_candidate=(
                "none" if remote_mutation_guard else "represent_or_publish_remote_branch"
            ),
            safe_to_mutate=remote_mutation_guard is None
            and not (
                _possible_unpushed(owner)
                or _human_blocked(owner, steering)
                or _owner_blocked(owner, steering)
            ),
        )

    if _terminal_receipt_satisfied(receipt_evidence):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.UNKNOWN,
            reason="terminal receipt exists but live PR/ref representation is not proven",
            evidence=evidence,
        )

    if _possible_unpushed(owner):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.BLOCKED_BY_POSSIBLE_UNPUSHED_WORK,
            reason="owner liveness withholds advisory because possible unpushed work exists",
            evidence=evidence,
            next_mutation_candidate="owner_preservation_request",
        )

    if _human_blocked(owner, steering):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.BLOCKED_BY_HUMAN,
            reason="handoff is gated by a human owner or human-directed steering",
            evidence=evidence,
            next_mutation_candidate="human_gate",
        )

    if not remote_exact_head and _owner_blocked(owner, steering):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.BLOCKED_BY_OWNER,
            reason="handoff has an owner/lane blocker and no exact representation proof",
            evidence=evidence,
            next_mutation_candidate="owner_followup",
        )

    if queue_cap.open_pr_cap_reached and is_pr_publication_request(payload):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.BLOCKED_BY_LIVE_QUEUE_CAP,
            reason="publication requested but live cache reports open PR cap reached",
            evidence=evidence,
            next_mutation_candidate="queue_drain",
        )

    if _queue_cap_uncertain_for_publication(queue_cap) and is_pr_publication_request(payload):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.UNKNOWN,
            reason="publication requested but queue-cap evidence is stale or unavailable",
            evidence=evidence,
        )

    if github.mode in {"degraded", "disabled"} and is_pr_publication_request(payload):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.UNKNOWN,
            reason="GitHub evidence is unavailable; cannot prove absence of exact open PR/ref",
            evidence=evidence,
        )

    if receipt_evidence.issue_only_pr_receipt:
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.PUBLICATION_REQUESTED,
            reason="PR-intended handoff has issue-only receipt; PR representation still requested",
            evidence=evidence,
            next_mutation_candidate="publish_or_represent_pr",
        )

    if is_pr_publication_request(payload):
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.PUBLICATION_REQUESTED,
            reason="PR publication remains requested and no stronger representation/blocker matched",
            evidence=evidence,
            next_mutation_candidate="publish_or_represent_pr",
        )

    if github.remote_ref is not None:
        return HandoffClassification(
            outbox_file=path.name,
            idempotency_key=idem,
            branch=branch,
            desired_head_sha=desired_head or None,
            state=HandoffState.PRESERVED_NOT_ACTIONABLE,
            reason="remote branch exists but exact desired-head representation is not proven",
            evidence=evidence,
        )

    return HandoffClassification(
        outbox_file=path.name,
        idempotency_key=idem,
        branch=branch,
        desired_head_sha=desired_head or None,
        state=HandoffState.UNKNOWN,
        reason="no representation, owner, cap, or publication state could be proven",
        evidence=evidence,
    )


def github_evidence_for_branch(
    github_client: Any,
    branch: str,
    desired_head: str,
    desired_base: str = "",
    target_pr: int | None = None,
) -> GitHubEvidence:
    open_prs, pr_error = github_client.open_prs_for_branch(branch)
    ref, ref_error = github_client.remote_ref(branch)
    exact_open_pr = None
    open_pr_items = open_prs or []
    if desired_head:
        for item in open_pr_items:
            compact = _compact_open_pr(item)
            head_ref = str(compact.get("head") or "")
            head_sha = str(compact.get("head_sha") or "")
            base_ref = str(compact.get("base") or DEFAULT_PR_BASE)
            if (
                head_ref == branch
                and heads_match(desired_head, head_sha)
                and _base_matches(
                    desired_base,
                    base_ref,
                    actual_is_live=True,
                )
            ):
                exact_open_pr = {**compact, "base": base_ref or None}
                break
    target_pr_error = None
    if exact_open_pr is None and target_pr is not None:
        target_payload, target_pr_error = _open_pr_by_number(github_client, target_pr)
        if target_payload is not None:
            exact_open_pr = _exact_open_pr_from_payload(
                target_payload,
                desired_head=desired_head,
                desired_base=desired_base,
                expected_branch=branch,
            )
    remote_ref = None
    if ref is not None:
        obj = ref.get("object") if isinstance(ref.get("object"), Mapping) else {}
        remote_ref = {
            "ref": ref.get("ref"),
            "sha": obj.get("sha") or ref.get("sha"),
        }
    errors = "; ".join(error for error in (pr_error, target_pr_error, ref_error) if error)
    if getattr(github_client, "disabled", False):
        mode = "disabled"
    elif errors:
        mode = "degraded"
    else:
        mode = "ready"
    return GitHubEvidence(
        mode=mode,
        error=errors or None,
        open_prs=[_compact_open_pr(item) for item in open_pr_items],
        exact_open_pr=exact_open_pr,
        remote_ref=remote_ref,
    )


def _open_pr_by_number(
    github_client: Any,
    target_pr: int,
) -> tuple[dict[str, Any] | None, str | None]:
    lookup = getattr(github_client, "open_pr_by_number", None)
    if lookup is None:
        return None, "github client cannot lookup target PR by number"
    payload, error = lookup(target_pr)
    if payload is not None and not isinstance(payload, dict):
        return None, "target PR lookup response was not a mapping"
    return payload, error


def _exact_open_pr_from_payload(
    item: Mapping[str, Any],
    *,
    desired_head: str,
    desired_base: str,
    expected_branch: str | None = None,
) -> dict[str, Any] | None:
    if str(item.get("state") or "").strip().lower() != "open":
        return None
    if not desired_head:
        return None
    raw_head = item.get("head")
    raw_base = item.get("base")
    head = raw_head if isinstance(raw_head, Mapping) else {}
    base = raw_base if isinstance(raw_base, Mapping) else {}
    head_ref = str(head.get("ref") or item.get("head_ref") or item.get("headRefName") or "").strip()
    if expected_branch and head_ref != expected_branch:
        return None
    head_sha = str(head.get("sha") or item.get("head_sha") or item.get("headRefOid") or "")
    base_ref = str(
        base.get("ref") or item.get("base_ref") or item.get("baseRefName") or DEFAULT_PR_BASE
    )
    if not heads_match(desired_head, head_sha) or not _base_matches(
        desired_base,
        base_ref,
        actual_is_live=True,
    ):
        return None
    return {**_compact_open_pr(item), "base": base_ref or None}


def _compact_open_pr(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_head = item.get("head")
    raw_base = item.get("base")
    head = raw_head if isinstance(raw_head, Mapping) else {}
    base = raw_base if isinstance(raw_base, Mapping) else {}
    head_ref = str(head.get("ref") or item.get("head_ref") or item.get("headRefName") or "").strip()
    head_sha = str(head.get("sha") or item.get("head_sha") or item.get("headRefOid") or "").strip()
    base_ref = str(base.get("ref") or item.get("base_ref") or item.get("baseRefName") or "").strip()
    return {
        "number": item.get("number"),
        "state": item.get("state"),
        "draft": item.get("draft"),
        "head": head_ref or None,
        "head_sha": head_sha or None,
        "base": base_ref or None,
        "html_url": item.get("html_url") or item.get("url"),
    }


def load_terminal_receipts(receipt_dir: Path) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    receipt_order: dict[str, float] = {}
    if not receipt_dir.exists():
        return receipts
    for path in sorted(receipt_dir.glob("*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status not in TERMINAL_RECEIPT_STATUSES:
            continue
        key = str(payload.get("idempotency_key") or path.stem).strip()
        if key:
            payload = dict(payload)
            payload["__receipt_path"] = str(path)
            order = _receipt_sort_timestamp(payload, path)
            if key not in receipts or order >= receipt_order.get(key, 0.0):
                receipts[key] = payload
                receipt_order[key] = order
    return receipts


def load_queue_cap_evidence(
    path: Path,
    *,
    max_age_seconds: int = DEFAULT_QUEUE_CAP_CACHE_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> QueueCapEvidence:
    payload = _load_json(path)
    if isinstance(payload, list):
        payload = next((item for item in reversed(payload) if isinstance(item, dict)), None)
    if not isinstance(payload, dict):
        return QueueCapEvidence(available=False)
    raw_github_queue = payload.get("github_queue")
    raw_limits = payload.get("limits")
    github_queue = raw_github_queue if isinstance(raw_github_queue, Mapping) else {}
    limits = raw_limits if isinstance(raw_limits, Mapping) else {}
    raw_pressure = github_queue.get("pressure")
    pressure = raw_pressure if isinstance(raw_pressure, Mapping) else {}
    generated_at = str(payload.get("generated_at") or "") or None
    generated_dt = _parse_datetime(generated_at)
    cache_age_seconds = None
    cache_stale = None
    decision_source = "fresh_cache"
    if generated_dt is None:
        cache_stale = True
        decision_source = "cache_missing_or_invalid_generated_at"
    else:
        current = now or datetime.now(UTC)
        cache_age_seconds = max(0.0, (current - generated_dt).total_seconds())
        cache_stale = cache_age_seconds > max_age_seconds
        if cache_stale:
            decision_source = "expired_cache"
    raw_cap = _bool_or_none(pressure.get("open_pr_cap_reached"))
    queue_available = _bool_or_none(github_queue.get("available"))
    degraded = _bool_or_none(github_queue.get("degraded"))
    if not cache_stale and queue_available is False:
        decision_source = "github_queue_unavailable"
    elif not cache_stale and degraded:
        decision_source = "fresh_degraded_cache_rest_fallback"
    effective_cap = (
        raw_cap if raw_cap is True else None if cache_stale or queue_available is False else raw_cap
    )
    return QueueCapEvidence(
        available=True,
        github_queue_available=queue_available,
        degraded=degraded,
        degraded_reason=str(github_queue.get("degraded_reason") or "") or None,
        open_pr_cap_reached=effective_cap,
        raw_open_pr_cap_reached=raw_cap,
        open_codex_pr_count=_int_or_none(github_queue.get("open_codex_pr_count")),
        max_open_prs=_int_or_none(limits.get("max_open_prs")),
        generated_at=generated_at,
        cache_age_seconds=cache_age_seconds,
        cache_stale=cache_stale,
        cache_stale_threshold_seconds=max_age_seconds,
        decision_source=decision_source,
    )


def _receipt_sort_timestamp(receipt: Mapping[str, Any], path: Path) -> float:
    for key in (
        "generated_at",
        "created_at",
        "updated_at",
        "published_at",
        "completed_at",
        "receipt_at",
        "read_at_utc",
    ):
        parsed = _parse_datetime(str(receipt.get(key) or "") or None)
        if parsed is not None:
            return parsed.timestamp()
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def receipt_evidence_from_payload(
    receipt: Mapping[str, Any] | None,
    outbox_payload: Mapping[str, Any],
) -> ReceiptEvidence:
    if receipt is None:
        return ReceiptEvidence(target_pr=target_pr_number_from_receipt(outbox_payload))
    status = str(receipt.get("status") or "").strip().lower() or None
    reason = str(receipt.get("reason") or "").strip().lower() or None
    has_pr = receipt_has_pr_reference(receipt)
    has_issue = receipt_has_issue_reference(receipt)
    issue_only = (
        is_pr_publication_request(outbox_payload)
        and status in {"already_satisfied", "published"}
        and not has_pr
        and (reason in {"published", "existing_issue", "created_issue"} or has_issue)
    )
    return ReceiptEvidence(
        status=status,
        reason=reason,
        has_pr_reference=has_pr,
        has_issue_reference=has_issue,
        issue_only_pr_receipt=issue_only,
        path=str(receipt.get("__receipt_path") or "") or None,
        target_pr=target_pr_number_from_receipt(receipt)
        or target_pr_number_from_receipt(outbox_payload),
    )


def steering_evidence_for_branch(
    *,
    state_root: Path,
    branch: str,
    owner_session: str | None,
    lane_id: str | None,
    message_rows: Sequence[Mapping[str, Any]] | None = None,
) -> SteeringEvidence:
    root = _state_path(state_root, DEFAULT_STEERING_ROOT)
    rows = list(message_rows) if message_rows is not None else _steering_message_rows(root)
    if not rows:
        return SteeringEvidence()
    matches: list[dict[str, Any]] = []
    for row in rows:
        path = Path(str(row.get("path") or ""))
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        to_session = str(payload.get("to_session") or "")
        lane_hint = str(payload.get("lane_id_hint") or "")
        branch_conflict = _steering_mentions_other_branch(payload, branch)
        if branch_conflict:
            continue
        branch_match = bool(branch and _steering_branch_matches(payload, branch))
        lane_match = bool(lane_id and _lane_hint_matches(lane_hint, lane_id))
        if owner_session and to_session == owner_session:
            if not (branch_match or lane_match):
                continue
            pass
        elif lane_match:
            pass
        elif branch_match:
            pass
        else:
            continue
        receipt = row.get("latest_read_receipt")
        human_detected = _looks_human(payload)
        matches.append(
            {
                "path": str(path),
                "to_session": to_session or None,
                "lane_id_hint": lane_hint or None,
                "priority": str(payload.get("priority") or "").lower() or None,
                "human_detected": human_detected,
                "subject_present": bool(str(payload.get("subject") or "").strip()),
                "body_present": bool(str(payload.get("body") or "").strip()),
                "sent_at_utc": payload.get("sent_at_utc"),
                "from": payload.get("from"),
                "latest_read_receipt": receipt,
            }
        )
    blocking = [m for m in matches if m.get("priority") == "blocking"]
    human = [m for m in matches if m.get("human_detected")]
    latest = sorted(matches, key=lambda m: str(m.get("sent_at_utc") or ""))[-1] if matches else None
    receipts = [
        receipt
        for receipt in (m.get("latest_read_receipt") for m in matches)
        if isinstance(receipt, dict)
    ]
    resolved_receipts = [
        receipt
        for receipt in receipts
        if str(receipt.get("outcome") or "").strip().lower()
        in {"obeyed", "stale", "superseded", "completed"}
    ]
    latest_receipt = (
        sorted(receipts, key=lambda r: str(r.get("read_at_utc") or ""))[-1] if receipts else None
    )
    return SteeringEvidence(
        pending_message_count=len(matches),
        blocking_message_count=len(blocking),
        resolved_read_receipt_count=len(resolved_receipts),
        human_message_count=len(human),
        latest_message=latest,
        latest_read_receipt=latest_receipt,
    )


def _steering_message_rows(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                "path": str(path),
                "payload": payload,
                "latest_read_receipt": latest_read_receipt_for_message(path),
            }
        )
    return rows


def branch_from_payload(payload: Mapping[str, Any]) -> str:
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        branch = str(local_evidence.get("branch") or "").strip()
        if branch:
            return branch
    branch = str(payload.get("branch") or "").strip()
    if branch:
        return branch
    requested_action = _mapping_from_action(payload.get("requested_action"))
    if requested_action is not None:
        return str(requested_action.get("branch") or "").strip()
    return ""


def desired_head_from_payload(payload: Mapping[str, Any]) -> str:
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        for key in HEAD_FIELD_KEYS:
            head = str(local_evidence.get(key) or "").strip()
            if head:
                return head
    for key in HEAD_FIELD_KEYS:
        head = str(payload.get(key) or "").strip()
        if head:
            return head
    requested_action = _mapping_from_action(payload.get("requested_action"))
    if requested_action is not None:
        for key in HEAD_FIELD_KEYS:
            head = str(requested_action.get(key) or "").strip()
            if head:
                return head
    return ""


def desired_base_from_payload(payload: Mapping[str, Any]) -> str:
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        for key in BASE_FIELD_KEYS:
            base = str(local_evidence.get(key) or "").strip()
            if base:
                return base
    for key in BASE_FIELD_KEYS:
        base = str(payload.get(key) or "").strip()
        if base:
            return base
    requested_action = _mapping_from_action(payload.get("requested_action"))
    if requested_action is not None:
        for key in BASE_FIELD_KEYS:
            base = str(requested_action.get(key) or "").strip()
            if base:
                return base
    if is_pr_publication_request(payload):
        return DEFAULT_PR_BASE
    return ""


def local_evidence_conflict_reason(payload: Mapping[str, Any]) -> str | None:
    records = _local_evidence_mappings(payload.get("local_evidence"))
    top_branch = _first_text(payload, "branch")
    top_head = _first_text(payload, *HEAD_FIELD_KEYS)
    top_base = _first_text(payload, *BASE_FIELD_KEYS)
    requested_action = _mapping_from_action(payload.get("requested_action")) or {}
    action_branch = _first_text(requested_action, "branch")
    action_head = _first_text(requested_action, *HEAD_FIELD_KEYS)
    action_base = _first_text(requested_action, *BASE_FIELD_KEYS)
    if top_branch and action_branch and top_branch != action_branch:
        return "top-level branch conflicts with requested_action branch"
    if top_head and action_head and not heads_match(top_head, action_head):
        return "top-level desired head conflicts with requested_action desired head"
    if top_base and action_base and not _base_matches(top_base, action_base):
        return "top-level base conflicts with requested_action base"
    if not records:
        return None
    for record in records:
        record_branch = _first_text(record, "branch")
        record_head = _first_text(record, *HEAD_FIELD_KEYS)
        record_base = _first_text(record, *BASE_FIELD_KEYS)
        if top_branch and record_branch and top_branch != record_branch:
            return "local_evidence branch conflicts with top-level branch"
        if action_branch and record_branch and action_branch != record_branch:
            return "local_evidence branch conflicts with requested_action branch"
        if top_head and record_head and not heads_match(top_head, record_head):
            return "local_evidence head conflicts with top-level desired head"
        if action_head and record_head and not heads_match(action_head, record_head):
            return "local_evidence head conflicts with requested_action desired head"
        if top_base and record_base and not _base_matches(top_base, record_base):
            return "local_evidence base conflicts with top-level base"
        if action_base and record_base and not _base_matches(action_base, record_base):
            return "local_evidence base conflicts with requested_action base"
    if len(records) <= 1:
        return None
    branches = {
        str(record.get("branch") or "").strip()
        for record in records
        if str(record.get("branch") or "").strip()
    }
    head_values: list[str] = []
    for record in records:
        value = _first_text(record, *HEAD_FIELD_KEYS)
        if value:
            head_values.append(value)
    bases = {
        _normalize_base_ref(value)
        for record in records
        if (value := _first_text(record, *BASE_FIELD_KEYS))
    }
    if len(branches) > 1 or _head_values_conflict(head_values) or len(bases) > 1:
        return "multiple local_evidence records disagree on branch, head, or base"
    return None


def is_pr_publication_request(payload: Mapping[str, Any]) -> bool:
    action = requested_action_type(payload)
    idempotency_key = str(payload.get("idempotency_key") or "")
    return action in PR_PUBLICATION_ACTIONS or idempotency_key.startswith(
        PR_PUBLICATION_IDEMPOTENCY_PREFIXES
    )


def requested_action_type(payload: Mapping[str, Any]) -> str:
    requested_action = payload.get("requested_action")
    mapping = _mapping_from_action(requested_action)
    if mapping is not None:
        return str(mapping.get("type") or mapping.get("action") or "").strip().lower()
    if isinstance(requested_action, str):
        return requested_action.strip().lower()
    return ""


def receipt_has_pr_reference(receipt: Mapping[str, Any]) -> bool:
    for key in (
        "created_pr_url",
        "existing_pr_url",
        "pr_url",
        "pull_request_url",
        "created_pull_request_url",
        "existing_pull_request_url",
    ):
        if str(receipt.get(key) or "").strip():
            return True
    return False


def receipt_has_issue_reference(receipt: Mapping[str, Any]) -> bool:
    for key in ("created_issue_url", "existing_issue_url", "issue_url"):
        if str(receipt.get(key) or "").strip():
            return True
    return False


TARGET_PR_NUMBER_KEYS = ("target_pr", "target_open_pr", "pr_number", "pull_request_number")
TARGET_PR_URL_KEYS = (
    "created_pr_url",
    "existing_pr_url",
    "pr_url",
    "pull_request_url",
    "created_pull_request_url",
    "existing_pull_request_url",
)


def target_pr_number_from_receipt(receipt: Mapping[str, Any]) -> int | None:
    number = _target_pr_number_from_mapping(receipt)
    if number is not None:
        return number
    requested_action = _mapping_from_action(receipt.get("requested_action"))
    if requested_action is not None:
        return _target_pr_number_from_mapping(requested_action)
    return None


def _target_pr_number_from_mapping(mapping: Mapping[str, Any]) -> int | None:
    for key in TARGET_PR_NUMBER_KEYS:
        number = _pr_number_from_value(mapping.get(key))
        if number is not None:
            return number
    for key in TARGET_PR_URL_KEYS:
        number = _pr_number_from_value(mapping.get(key))
        if number is not None:
            return number
    return None


def heads_match(expected: str, actual: str) -> bool:
    expected_value = str(expected or "").strip().lower()
    actual_value = str(actual or "").strip().lower()
    if not _sha_prefix_is_usable(expected_value) or not _sha_prefix_is_usable(actual_value):
        return False
    if _full_sha_or_none(expected_value) and _full_sha_or_none(actual_value):
        return expected_value == actual_value
    return expected_value.startswith(actual_value) or actual_value.startswith(expected_value)


def _head_values_conflict(values: Sequence[str]) -> bool:
    normalized = [str(value or "").strip().lower() for value in values if str(value or "").strip()]
    full_values = {_full_sha_or_none(value) for value in normalized}
    full_values.discard(None)
    if len(full_values) > 1:
        return True
    # A full SHA and its usable prefix describe the same head; only unrelated
    # representatives should make multiple local-evidence records conflict.
    representatives: list[str] = []
    for value in normalized:
        if not any(heads_match(value, existing) for existing in representatives):
            representatives.append(value)
    return len(representatives) > 1


def full_heads_match(expected: str, actual: str) -> bool:
    expected_value = str(expected or "").strip().lower()
    actual_value = str(actual or "").strip().lower()
    return bool(
        _full_sha_or_none(expected_value)
        and _full_sha_or_none(actual_value)
        and expected_value == actual_value
    )


def _full_sha_or_none(value: str) -> str | None:
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _sha_prefix_is_usable(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", value))


def _remote_ref_matches(remote_ref: Mapping[str, Any] | None, desired_head: str) -> bool:
    if not remote_ref or not desired_head:
        return False
    return heads_match(desired_head, str(remote_ref.get("sha") or ""))


def _remote_ref_mutation_guard(
    remote_ref: Mapping[str, Any] | None,
    desired_head: str,
    owner: OwnerEvidence,
) -> str | None:
    if not full_heads_match(desired_head, str((remote_ref or {}).get("sha") or "")):
        return "full desired-head SHA does not exactly match the remote branch head"
    return _owner_probe_mutation_guard(owner)


def _exact_open_pr_mutation_guard(
    exact_open_pr: Mapping[str, Any] | None,
    desired_head: str,
    owner: OwnerEvidence,
) -> str | None:
    if not full_heads_match(desired_head, str((exact_open_pr or {}).get("head_sha") or "")):
        return "full desired-head SHA does not exactly match the PR head"
    return _owner_probe_mutation_guard(owner)


def _owner_probe_mutation_guard(owner: OwnerEvidence) -> str | None:
    if str(owner.source or "") == "lane_registry":
        return "owner liveness helper was not used for mutation-grade safety"
    return None


def _base_matches(desired_base: str, actual_base: str, *, actual_is_live: bool = False) -> bool:
    expected = _normalize_base_ref(desired_base)
    if not expected:
        if actual_is_live:
            return _normalize_base_ref(actual_base) == DEFAULT_PR_BASE
        return True
    actual = str(actual_base or "").strip()
    if not actual:
        return False
    if actual_is_live:
        return expected == actual
    return expected == _normalize_base_ref(actual)


def _normalize_base_ref(value: str) -> str:
    base = str(value or "").strip()
    for prefix in ("refs/remotes/origin/", "refs/heads/", "origin/", "remotes/origin/"):
        if base.startswith(prefix):
            return base[len(prefix) :]
    return base


def _possible_unpushed(owner: OwnerEvidence) -> bool:
    value = str(owner.advisory_withheld or "").strip().lower()
    return value == "possible_unpushed_work"


def _payload_possible_unpushed_marker(payload: Mapping[str, Any]) -> str | None:
    if _possible_unpushed_marker(payload):
        return "possible_unpushed_work"
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        if _possible_unpushed_marker(local_evidence):
            return "possible_unpushed_work"
    return None


def _owner_probe_no_match(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return "no lane matched" in normalized or "no matching lane" in normalized


def _human_blocked(owner: OwnerEvidence, steering: SteeringEvidence) -> bool:
    tokens = [
        owner.owner_session,
        owner.lane_id,
        owner.source,
        owner.status,
        owner.owner_blocking_state,
    ]
    if any(_contains_human_token(str(token or "")) for token in tokens):
        return True
    return steering.human_message_count > 0


def _owner_blocked(owner: OwnerEvidence, steering: SteeringEvidence) -> bool:
    if owner.available is False:
        return True
    if steering.blocking_message_count > 0:
        return True
    blocking = str(owner.owner_blocking_state or "").strip().lower()
    if blocking in {"live_owner", "stale_owner", "unknown_owner", "stale_terminal_owner"}:
        return True
    return False


def _queue_cap_uncertain_for_publication(queue_cap: QueueCapEvidence) -> bool:
    if queue_cap.available is not True:
        return True
    if queue_cap.open_pr_cap_reached is None:
        return True
    return queue_cap.cache_stale is True or queue_cap.github_queue_available is False


def _terminal_receipt_satisfied(receipt: ReceiptEvidence) -> bool:
    if receipt.status not in TERMINAL_RECEIPT_STATUSES or receipt.issue_only_pr_receipt:
        return False
    return receipt.has_pr_reference or receipt.target_pr is not None


def _looks_human(mapping: Mapping[str, Any]) -> bool:
    # Do not inspect the filesystem path: all steering messages live under
    # ".aragora/operator-steering", which would make every matched message look
    # human/operator-gated.
    fields = (
        "subject",
        "body",
        "to_session",
        "lane_id_hint",
    )
    text = " ".join(str(mapping.get(field) or "") for field in fields).lower()
    if _contains_human_token(text):
        return True
    operator_phrases = (
        "operator approval",
        "operator authorization",
        "operator decision",
        "operator settlement",
        "operator must",
        "ask operator",
    )
    return any(phrase in text for phrase in operator_phrases)


def _contains_human_token(value: str) -> bool:
    return re.search(r"(?<!non-)\bhuman\b", value.lower()) is not None


def _lane_hint_matches(lane_hint: str, lane_id: str) -> bool:
    normalized_lane = lane_id.strip()
    if not normalized_lane:
        return False
    hints = [part.strip() for part in re.split(r"[,;\s]+", lane_hint) if part.strip()]
    return normalized_lane in hints


def _steering_branch_matches(payload: Mapping[str, Any], branch: str) -> bool:
    exact_keys = (
        "branch",
        "head_branch",
        "target_branch",
        "source_branch",
        "base_branch",
    )
    text_keys = (
        "subject",
        "body",
        "summary",
        "requested_next_action",
    )
    for key in exact_keys:
        if str(payload.get(key) or "").strip() == branch:
            return True
    for key in text_keys:
        if _text_contains_exact_branch(str(payload.get(key) or ""), branch):
            return True
    for key in ("branches", "branch_names"):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if any(str(item) == branch for item in value):
                return True
    for key in ("metadata", "context", "evidence"):
        value = payload.get(key)
        if not isinstance(value, Mapping):
            continue
        for nested_key in exact_keys:
            if str(value.get(nested_key) or "").strip() == branch:
                return True
        for nested_key in text_keys:
            if _text_contains_exact_branch(str(value.get(nested_key) or ""), branch):
                return True
    return False


def _steering_mentions_other_branch(payload: Mapping[str, Any], branch: str) -> bool:
    tokens = _steering_branch_tokens(payload)
    return bool(tokens and branch not in tokens)


def _steering_branch_tokens(payload: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    exact_keys = (
        "branch",
        "head_branch",
        "target_branch",
        "source_branch",
        "base_branch",
    )
    text_keys = (
        "subject",
        "body",
        "summary",
        "requested_next_action",
    )
    for key in exact_keys:
        value = str(payload.get(key) or "").strip()
        if value:
            tokens.add(value)
    for key in ("branches", "branch_names"):
        names = payload.get(key)
        if isinstance(names, Sequence) and not isinstance(names, (str, bytes, bytearray)):
            tokens.update(str(item).strip() for item in names if str(item).strip())
    for key in text_keys:
        tokens.update(_branch_tokens_from_text(str(payload.get(key) or "")))
    for key in ("metadata", "context", "evidence"):
        section = payload.get(key)
        if not isinstance(section, Mapping):
            continue
        for nested_key in exact_keys:
            nested = str(section.get(nested_key) or "").strip()
            if nested:
                tokens.add(nested)
        for nested_key in text_keys:
            tokens.update(_branch_tokens_from_text(str(section.get(nested_key) or "")))
    return tokens


def _branch_tokens_from_text(text: str) -> set[str]:
    text = URL_PATTERN.sub("", text)
    return {
        token.rstrip(".,;:!?)]}'\"")
        for token in re.findall(r"\b[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+", text)
    }


def _text_contains_exact_branch(text: str, branch: str) -> bool:
    candidate = str(branch or "").strip()
    if not candidate:
        return False
    if text.strip() == candidate:
        return True
    return candidate in _branch_tokens_from_text(text)


def latest_read_receipt_for_message(message_path: Path) -> dict[str, Any] | None:
    receipt_dir = message_path.parent / "_read_receipts"
    if not receipt_dir.is_dir():
        return None
    receipts: list[dict[str, Any]] = []
    data = _load_json(message_path)
    if not isinstance(data, dict):
        data = {}
    message_sha = str(data.get("message_sha256") or "")
    for receipt_path in sorted(receipt_dir.glob("*.json")):
        payload = _load_json(receipt_path)
        if not isinstance(payload, dict):
            continue
        if str(payload.get("message_filename") or "") != message_path.name:
            continue
        receipt_sha = str(payload.get("message_sha256") or "")
        if message_sha and receipt_sha and receipt_sha != message_sha:
            continue
        receipts.append(
            {
                "path": str(receipt_path),
                "read_at_utc": payload.get("read_at_utc"),
                "read_by_session": payload.get("read_by_session"),
                "outcome": payload.get("outcome"),
                "outcome_note": payload.get("outcome_note"),
            }
        )
    if not receipts:
        return None
    return sorted(receipts, key=lambda r: str(r.get("read_at_utc") or ""))[-1]


def _selected_outbox_files(outbox_dir: Path, outbox_file: str | Path | None) -> list[Path]:
    outbox_root = outbox_dir.resolve()
    if outbox_file is None:
        if not outbox_dir.exists():
            return []
        return sorted(p for p in outbox_dir.iterdir() if p.is_file() and p.suffix == ".json")
    value = Path(outbox_file).expanduser()
    path = (value if value.is_absolute() else outbox_dir / value).resolve()
    try:
        path.relative_to(outbox_root)
    except ValueError:
        raise ValueError(f"outbox file must be inside {outbox_root}: {value}") from None
    if not path.is_file():
        raise FileNotFoundError(f"outbox file does not exist: {path}")
    return [path]


def _load_lane_records(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, Mapping):
        records = payload.get("lanes") or payload.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


def _lane_registry_blocking_reason(status: str, blocking_state: str | None) -> str | None:
    if blocking_state == "live_owner":
        return "lane registry status is active/blocking; use focused liveness before mutation"
    if blocking_state == "stale_terminal_owner":
        return "lane registry status is terminal but needs focused liveness proof"
    if blocking_state == "unknown_owner":
        return "lane registry matched an owner without enough liveness proof"
    return f"lane registry owner_blocking_state={blocking_state}" if blocking_state else None


def _best_lane_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    active = [
        row
        for row in records
        if str(row.get("status") or "").strip().lower() in ACTIVE_LANE_STATUSES
    ]
    candidates = active or records
    return sorted(candidates, key=lambda row: str(row.get("updated_at") or ""), reverse=True)[0]


def _gh_stderr_is_not_found(message: str) -> bool:
    text = str(message or "").strip().lower()
    return "http 404" in text or "not found" in text or "status code 404" in text


def _github_not_found_error(error: str) -> bool:
    return str(error or "").startswith("github_not_found:")


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _mapping_from_action(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = None
    if isinstance(parsed, Mapping):
        return parsed
    return None


def _local_evidence_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _state_path(state_root: Path, default_relative: Path) -> Path:
    state_root = _as_aragora_root(state_root)
    if default_relative.parts[:1] == (".aragora",):
        return state_root.joinpath(*default_relative.parts[1:])
    return state_root / default_relative


def resolve_state_root(*, repo_root: Path, state_root: Path | None = None) -> Path:
    if state_root is not None:
        return _as_aragora_root(state_root)
    env_root = os.environ.get("ARAGORA_AUTOMATION_STATE_ROOT")
    if env_root:
        return _as_aragora_root(Path(env_root))
    common_root = _git_common_worktree_root(repo_root)
    if common_root is not None and (common_root / ".aragora").exists():
        return common_root / ".aragora"
    return _as_aragora_root(repo_root)


def _as_aragora_root(path: Path) -> Path:
    expanded = path.expanduser().resolve()
    if expanded.name == ".aragora":
        return expanded
    return expanded / ".aragora"


def _git_common_worktree_root(repo_root: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = (repo_root / common).resolve()
    if common.name == ".git":
        return common.parent
    return None


def _github_repo_from_origin(repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    if not value:
        return None
    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")
    elif "github.com/" in value:
        value = value.split("github.com/", 1)[1]
    value = value.removesuffix(".git").strip("/")
    parts = value.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return None


def _github_repo_owner(github_repo: str) -> tuple[str, str | None]:
    parts = [part for part in str(github_repo or "").strip().split("/") if part]
    if len(parts) != 2:
        return "", "github repo must be in owner/name form"
    return parts[0], None


def _first_text(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(mapping.get(key) or "").strip()
        if value:
            return value
    return None


def _pr_number_from_value(value: Any) -> int | None:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return None
    if text.isdigit():
        return int(text)
    marker = "/pull/"
    if marker not in text:
        return None
    candidate = text.rsplit(marker, 1)[1].split("/", 1)[0]
    return int(candidate) if candidate.isdigit() else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def compact_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version"),
        "generated_at": payload.get("generated_at"),
        "repo": payload.get("repo"),
        "state_root": payload.get("state_root"),
        "github_repo": payload.get("github_repo"),
        "outbox_count": payload.get("outbox_count"),
        "counts": payload.get("counts", {}),
        "github": payload.get("github", {}),
        "queue_cap": payload.get("queue_cap", {}),
    }


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
