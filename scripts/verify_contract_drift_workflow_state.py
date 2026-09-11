#!/usr/bin/env python3
"""Read-only verifier for the live Contract Drift Governance workflow state."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml

DEFAULT_REPOSITORY = "synaptent/aragora"
CANONICAL_WORKFLOW_ID = 233974988
CANONICAL_WORKFLOW_PATH = ".github/workflows/contract-drift-governance.yml"
CANONICAL_WORKFLOW_NAME = "Contract Drift Governance"
EXPECTED_PR_DELTA_APP_ID = 15368
LIVE_CHECK_NAMES = (
    "contract-drift-pr-delta",
    "contract-drift-main-receipt",
    "contract-drift-program-trajectory",
)
# The finalizer dispatch runs as its own `actions: write` job so the receipt
# job stays read-only. It is not a live check: it only ever executes on a
# historical-backfill dispatch and must appear skipped on routine main runs.
HISTORICAL_DISPATCH_JOB_NAME = "contract-drift-historical-backfill-dispatch"
EXPECTED_WORKFLOW_JOB_NAMES = frozenset(LIVE_CHECK_NAMES) | {HISTORICAL_DISPATCH_JOB_NAME}
PRE_CUTOVER_REQUIRED_CHECKS = (
    ("lint", 15368),
    ("typecheck", 15368),
    ("sdk-parity", 15368),
    ("Generate & Validate", 15368),
    ("TypeScript SDK Type Check", 15368),
    ("aragora-merge-quorum", 15368),
)
EXPECTED_PROTECTION_STRICT = False
MAX_PAGES = 10_000
HISTORY_SHARD_LIMIT = 1000
HISTORY_SHARD_TARGET = 900
HISTORY_START_DATE = date(2026, 2, 13)
MAX_ARTIFACT_ZIP_BYTES = 20 * 1024 * 1024
MAX_ARTIFACT_PAYLOAD_BYTES = 10 * 1024 * 1024


class VerificationError(ValueError):
    """The authenticated state did not satisfy the fail-closed contract."""


class ApiReader(Protocol):
    def get_json(self, endpoint: str) -> dict[str, Any]: ...

    def get_bytes(self, endpoint: str, *, max_bytes: int | None = None) -> bytes: ...


class GhApiReader:
    """Authenticated read-only GitHub transport backed by ``gh api``."""

    def __init__(self, *, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds

    def _run(self, endpoint: str, *, accept: str) -> bytes:
        try:
            proc = subprocess.run(
                ["gh", "api", "--method", "GET", "-H", f"Accept: {accept}", endpoint],
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise VerificationError(f"authenticated GitHub GET timed out: {endpoint}") from exc
        if proc.returncode != 0:
            error = proc.stderr.decode("utf-8", errors="replace").strip()
            raise VerificationError(f"authenticated GitHub GET failed for {endpoint}: {error}")
        return proc.stdout

    def get_json(self, endpoint: str) -> dict[str, Any]:
        raw = self._run(endpoint, accept="application/vnd.github+json")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationError(f"GitHub response is malformed for {endpoint}: {exc}") from exc
        if not isinstance(payload, dict):
            raise VerificationError(f"GitHub response is not an object: {endpoint}")
        return payload

    def get_bytes(self, endpoint: str, *, max_bytes: int | None = None) -> bytes:
        accept = (
            "application/vnd.github.raw+json"
            if "/contents/" in urlparse(endpoint).path
            else "application/vnd.github+json"
        )
        raw = self._run(endpoint, accept=accept)
        if max_bytes is not None and len(raw) > max_bytes:
            raise VerificationError(f"authenticated GitHub response is too large: {endpoint}")
        return raw


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise VerificationError(f"{label} is malformed")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{label} is malformed")
    return value


def _with_page(endpoint: str, page: int) -> str:
    parsed = urlparse(endpoint)
    query = [
        (key, value) for key, value in parse_qsl(parsed.query) if key not in {"page", "per_page"}
    ]
    query.extend((("per_page", "100"), ("page", str(page))))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _paginate_collection(
    reader: ApiReader,
    endpoint: str,
    *,
    collection_key: str,
    identity: Callable[[dict[str, Any]], Any],
    label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    endpoints: list[str] = []
    reported_total: int | None = None
    page = 1
    while True:
        page_endpoint = _with_page(endpoint, page)
        endpoints.append(page_endpoint)
        payload = reader.get_json(page_endpoint)
        page_records = payload.get(collection_key)
        if not isinstance(page_records, list) or not all(
            isinstance(record, dict) for record in page_records
        ):
            raise VerificationError(f"{label} page is malformed: {page_endpoint}")
        if "total_count" not in payload:
            raise VerificationError(f"{label} total_count is missing")
        page_total = _require_int(payload["total_count"], f"{label} total_count")
        if reported_total is None:
            reported_total = page_total
        elif page_total != reported_total:
            raise VerificationError(f"{label} total_count moved between pages")
        existing = {identity(record) for record in records}
        page_identities = [identity(record) for record in page_records]
        if any(value is None for value in page_identities):
            raise VerificationError(f"{label} record identity is missing")
        if len(page_identities) != len(set(page_identities)) or existing.intersection(
            page_identities
        ):
            raise VerificationError(f"{label} pagination returned duplicate identities")
        records.extend(page_records)
        if len(page_records) < 100:
            break
        page += 1
        if page > MAX_PAGES:
            raise VerificationError(f"{label} pagination did not terminate")

    identities = [identity(record) for record in records]
    if any(value is None for value in identities):
        raise VerificationError(f"{label} record identity is missing")
    if len(identities) != len(set(identities)):
        raise VerificationError(f"{label} pagination returned duplicate identities")
    if reported_total != len(records):
        raise VerificationError(
            f"{label} records do not reconcile to total_count ({len(records)} != {reported_total})"
        )
    return records, endpoints


def attempt_numbers(run: Mapping[str, Any]) -> list[int]:
    attempt = run.get("run_attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("run_attempt is malformed")
    return list(range(1, attempt + 1))


def validate_attempt_jobs(endpoint: str, jobs: list[dict], *, attempt: int) -> None:
    if f"/attempts/{attempt}/jobs" not in endpoint:
        raise ValueError("jobs endpoint is not attempt-specific")
    for job in jobs:
        if job.get("run_attempt") != attempt:
            raise ValueError("job record is not attempt-specific")
        check_url = str(job.get("check_url") or job.get("check_run_url") or "")
        if not check_url:
            raise ValueError("job check URL is missing")


def _workflow_job_names(source: bytes) -> set[str]:
    try:
        doc = yaml.load(source.decode("utf-8"), Loader=yaml.BaseLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise VerificationError(f"workflow source is malformed: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        raise VerificationError("workflow source lacks jobs")
    return {
        str(job.get("name", job_id)) for job_id, job in doc["jobs"].items() if isinstance(job, dict)
    }


def _canonical_workflow(
    reader: ApiReader,
    *,
    repo: str,
    canonical_workflow_id: int,
) -> tuple[dict[str, Any], list[str]]:
    workflows, endpoints = _paginate_collection(
        reader,
        f"repos/{repo}/actions/workflows",
        collection_key="workflows",
        identity=lambda workflow: workflow.get("id"),
        label="workflow discovery",
    )
    candidates: list[dict[str, Any]] = []
    for workflow in workflows:
        path = workflow.get("path")
        if not isinstance(path, str) or not path.startswith(".github/workflows/"):
            continue
        name = str(workflow.get("name") or "")
        if path == CANONICAL_WORKFLOW_PATH or name == CANONICAL_WORKFLOW_NAME:
            candidates.append(workflow)
    if len(candidates) != 1:
        raise VerificationError(
            "exactly one registered workflow may emit the live check names "
            f"(found {len(candidates)})"
        )
    workflow = candidates[0]
    workflow_id = _require_int(workflow.get("id"), "canonical workflow ID", minimum=1)
    if workflow_id != canonical_workflow_id:
        raise VerificationError(
            f"canonical workflow ID moved ({workflow_id} != {canonical_workflow_id})"
        )
    if workflow.get("path") != CANONICAL_WORKFLOW_PATH:
        raise VerificationError("canonical workflow path moved")
    if workflow.get("name") != CANONICAL_WORKFLOW_NAME:
        raise VerificationError("canonical workflow name moved")
    if workflow.get("state") != "active":
        raise VerificationError("canonical workflow must be active")
    source = reader.get_bytes(f"repos/{repo}/contents/{CANONICAL_WORKFLOW_PATH}?ref=main")
    if _workflow_job_names(source) != EXPECTED_WORKFLOW_JOB_NAMES:
        raise VerificationError("canonical workflow does not expose the exact three live checks")
    return workflow, endpoints


def _main_sha(reader: ApiReader, repo: str) -> str:
    payload = reader.get_json(f"repos/{repo}/git/ref/heads/main")
    obj = payload.get("object")
    if not isinstance(obj, dict):
        raise VerificationError("main ref object is malformed")
    sha = _require_string(obj.get("sha"), "main SHA")
    if len(sha) != 40:
        raise VerificationError("main SHA is not full length")
    return sha


def _workflow_runs(
    reader: ApiReader, *, repo: str, workflow_id: int
) -> tuple[list[dict[str, Any]], list[str]]:
    endpoint = f"repos/{repo}/actions/workflows/{workflow_id}/runs"
    first = reader.get_json(_with_page(endpoint, 1))
    total = _require_int(first.get("total_count"), "workflow-run total_count")
    if total <= HISTORY_SHARD_LIMIT:
        return _paginate_collection(
            reader,
            endpoint,
            collection_key="workflow_runs",
            identity=lambda run: run.get("id"),
            label="workflow-run discovery",
        )
    return _workflow_runs_by_date(
        reader,
        repo=repo,
        workflow_id=workflow_id,
        reported_total=total,
    )


def _day_runs(
    reader: ApiReader, *, repo: str, workflow_id: int, day: date
) -> tuple[list[dict[str, Any]], list[str]]:
    day_text = day.isoformat()
    endpoint = (
        f"repos/{repo}/actions/workflows/{workflow_id}/runs?"
        f"created={day_text}T00:00:00Z..{day_text}T23:59:59Z"
    )
    records, endpoints = _paginate_collection(
        reader,
        endpoint,
        collection_key="workflow_runs",
        identity=lambda run: run.get("id"),
        label=f"workflow-run date shard {day_text}",
    )
    if len(records) >= HISTORY_SHARD_LIMIT:
        raise VerificationError(
            f"single-day workflow history reaches the 1000-result cap: {day_text}"
        )
    return records, endpoints


def _workflow_runs_by_date(
    reader: ApiReader, *, repo: str, workflow_id: int, reported_total: int
) -> tuple[list[dict[str, Any]], list[str]]:
    today = datetime.now(timezone.utc).date()
    daily: list[tuple[date, list[dict[str, Any]]]] = []
    query_endpoints: list[str] = []
    day = HISTORY_START_DATE
    while day <= today:
        day_records, day_endpoints = _day_runs(reader, repo=repo, workflow_id=workflow_id, day=day)
        daily.append((day, day_records))
        query_endpoints.extend(day_endpoints)
        day += timedelta(days=1)

    records: list[dict[str, Any]] = []
    shards: list[str] = []
    shard: list[tuple[date, list[dict[str, Any]]]] = []
    shard_count = 0
    for day, day_records in daily:
        if shard and shard_count + len(day_records) > HISTORY_SHARD_TARGET:
            shards.append(f"created={shard[0][0].isoformat()}..{shard[-1][0].isoformat()}")
            records.extend(run for _, runs in shard for run in runs)
            shard, shard_count = [], 0
        shard.append((day, day_records))
        shard_count += len(day_records)
    if shard:
        shards.append(f"created={shard[0][0].isoformat()}..{shard[-1][0].isoformat()}")
        records.extend(run for _, runs in shard for run in runs)

    ids = [_require_int(run.get("id"), "workflow-run ID", minimum=1) for run in records]
    if len(ids) != len(set(ids)):
        raise VerificationError("date-sharded workflow history returned duplicate identities")
    if len(records) != reported_total:
        raise VerificationError(
            "date-sharded workflow history does not reconcile to the unfiltered total_count"
        )
    return records, [*shards, *query_endpoints]


def _run_key(run: Mapping[str, Any]) -> tuple[str, int, int]:
    return (
        _require_string(run.get("run_started_at"), "run_started_at"),
        _require_int(run.get("id"), "run ID", minimum=1),
        attempt_numbers(run)[-1],
    )


def _selected_main_run(
    runs: Iterable[dict[str, Any]],
    *,
    workflow_id: int,
    main_sha: str,
    is_historical_backfill: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    eligible = [
        run
        for run in runs
        if run.get("workflow_id") == workflow_id
        and run.get("path") == CANONICAL_WORKFLOW_PATH
        and run.get("head_branch") == "main"
        and run.get("head_sha") == main_sha
        and run.get("event") in {"push", "schedule", "workflow_dispatch"}
        and not is_historical_backfill(run)
    ]
    if not eligible:
        raise VerificationError("no canonical main workflow execution matches current main")
    return max(eligible, key=_run_key)


def _check_summary(
    reader: ApiReader,
    *,
    repo: str,
    endpoint: str,
    job: Mapping[str, Any],
    run: Mapping[str, Any],
    attempt: int,
) -> dict[str, Any]:
    if job.get("run_attempt") != attempt:
        raise VerificationError("job record is not attempt-specific")
    check_url = _require_string(job.get("check_run_url"), "attempt-specific check URL")
    parsed_check_url = urlparse(check_url)
    if parsed_check_url.scheme != "https" or parsed_check_url.netloc != "api.github.com":
        raise VerificationError("attempt check URL is not an authenticated GitHub API URL")
    expected_prefix = f"/repos/{repo}/check-runs/"
    if not parsed_check_url.path.startswith(expected_prefix):
        raise VerificationError("attempt check URL is bound to another repository")
    check = reader.get_json(check_url)
    if check.get("id") is None or check.get("name") != job.get("name"):
        raise VerificationError("attempt job/check identity mismatch")
    if check.get("head_sha") != run.get("head_sha"):
        raise VerificationError("attempt check is bound to another SHA")
    app = check.get("app")
    app_id = app.get("id") if isinstance(app, dict) else None
    if app_id != EXPECTED_PR_DELTA_APP_ID:
        raise VerificationError("attempt check is not authenticated by the GitHub Actions app")
    details_url = _require_string(check.get("details_url"), "attempt check details URL")
    if f"/runs/{run['id']}/" not in details_url:
        raise VerificationError("attempt check details URL is bound to another run")
    return {
        "job_id": _require_int(job.get("id"), "job ID", minimum=1),
        "check_run_id": _require_int(check.get("id"), "check-run ID", minimum=1),
        "app_id": app_id,
        "status": check.get("status"),
        "conclusion": check.get("conclusion"),
        "check_url": check_url,
        "details_url": details_url,
        "jobs_endpoint": endpoint,
    }


def _attempts(reader: ApiReader, *, repo: str, run: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    run_id = _require_int(run.get("id"), "run ID", minimum=1)
    for attempt in attempt_numbers(run):
        endpoint = f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
        jobs, _ = _paginate_collection(
            reader,
            endpoint,
            collection_key="jobs",
            identity=lambda job: job.get("id"),
            label=f"attempt {attempt} jobs",
        )
        try:
            validate_attempt_jobs(endpoint, jobs, attempt=attempt)
        except ValueError as exc:
            raise VerificationError(str(exc)) from exc
        names = [job.get("name") for job in jobs]
        if len(names) != len(set(names)):
            raise VerificationError("attempt jobs contain duplicate names")
        if set(names) != EXPECTED_WORKFLOW_JOB_NAMES:
            raise VerificationError("attempt jobs do not expose the exact three live checks")
        summaries = {
            str(job["name"]): _check_summary(
                reader,
                repo=repo,
                endpoint=endpoint,
                job=job,
                run=run,
                attempt=attempt,
            )
            for job in jobs
        }
        checks = {name: summaries[name] for name in LIVE_CHECK_NAMES}
        dispatch = summaries[HISTORICAL_DISPATCH_JOB_NAME]
        # Selected runs are push/schedule/dispatch executions on main; the
        # historical-backfill path never produces a routine receipt, so the
        # write-scoped dispatch job must have been skipped, never executed.
        if dispatch.get("status") != "completed" or dispatch.get("conclusion") != "skipped":
            raise VerificationError(
                "historical-backfill dispatch job did not skip on the selected main execution"
            )
        auxiliary_jobs = {HISTORICAL_DISPATCH_JOB_NAME: str(dispatch.get("conclusion"))}
        result.append(
            {
                "attempt": attempt,
                "jobs_endpoint": endpoint,
                "checks": checks,
                "auxiliary_jobs": auxiliary_jobs,
            }
        )
    return result


def _artifact_payload(raw_zip: bytes, *, expected_name: str) -> tuple[bytes, dict[str, Any]]:
    if len(raw_zip) > MAX_ARTIFACT_ZIP_BYTES:
        raise VerificationError("run artifact zip exceeds the verifier size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if names != [expected_name]:
                raise VerificationError(
                    "run artifact zip does not contain exactly the expected file"
                )
            info = archive.getinfo(names[0])
            if info.file_size > MAX_ARTIFACT_PAYLOAD_BYTES:
                raise VerificationError("run artifact payload exceeds the verifier size limit")
            raw_payload = archive.read(names[0])
    except (zipfile.BadZipFile, KeyError) as exc:
        raise VerificationError(f"run artifact zip is malformed: {exc}") from exc
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"run artifact payload is malformed: {exc}") from exc
    if not isinstance(payload, dict):
        raise VerificationError("run artifact payload is not an object")
    return raw_payload, payload


def _payload_source_sha(payload: Mapping[str, Any]) -> str | None:
    direct = payload.get("source_sha")
    if isinstance(direct, str):
        return direct
    program = payload.get("program")
    if isinstance(program, dict) and isinstance(program.get("source_sha"), str):
        return str(program["source_sha"])
    return None


def _artifacts(reader: ApiReader, *, repo: str, run: Mapping[str, Any]) -> list[dict[str, Any]]:
    run_id = _require_int(run.get("id"), "run ID", minimum=1)
    artifacts, _ = _paginate_collection(
        reader,
        f"repos/{repo}/actions/runs/{run_id}/artifacts",
        collection_key="artifacts",
        identity=lambda artifact: artifact.get("id"),
        label="run artifacts",
    )
    head_sha = _require_string(run.get("head_sha"), "run head SHA")
    expected = {
        f"contract-drift-main-receipt-{head_sha}": "contract-drift-main-receipt.json",
        f"contract-drift-program-trajectory-{head_sha}": ("contract-drift-program-trajectory.json"),
    }
    selected = [artifact for artifact in artifacts if artifact.get("name") in expected]
    if {artifact.get("name") for artifact in selected} != set(expected):
        raise VerificationError("run-level receipt/trajectory artifacts are incomplete")
    summaries: list[dict[str, Any]] = []
    for artifact in selected:
        if artifact.get("expired") is not False:
            raise VerificationError("run artifact is expired")
        workflow_run = artifact.get("workflow_run")
        if (
            not isinstance(workflow_run, dict)
            or workflow_run.get("id") != run_id
            or workflow_run.get("head_sha") != head_sha
        ):
            raise VerificationError("run artifact is bound to another run or SHA")
        artifact_id = _require_int(artifact.get("id"), "artifact ID", minimum=1)
        name = str(artifact["name"])
        raw_payload, payload = _artifact_payload(
            reader.get_bytes(
                f"repos/{repo}/actions/artifacts/{artifact_id}/zip",
                max_bytes=MAX_ARTIFACT_ZIP_BYTES,
            ),
            expected_name=expected[name],
        )
        if _payload_source_sha(payload) != head_sha:
            raise VerificationError("artifact payload is bound to another source SHA")
        payload_status = payload.get("status")
        expected_status = "pass" if name.startswith("contract-drift-main-receipt-") else "fail"
        if payload_status != expected_status:
            raise VerificationError("artifact payload status contradicts its live check")
        summaries.append(
            {
                "id": artifact_id,
                "name": name,
                "size_in_bytes": _require_int(
                    artifact.get("size_in_bytes"), "artifact size", minimum=1
                ),
                "payload_sha256": hashlib.sha256(raw_payload).hexdigest(),
                "payload_status": payload_status,
            }
        )
    return sorted(summaries, key=lambda item: item["id"])


def _branch_protection(reader: ApiReader, repo: str) -> dict[str, Any]:
    payload = reader.get_json(f"repos/{repo}/branches/main/protection/required_status_checks")
    if not isinstance(payload.get("strict"), bool):
        raise VerificationError("branch-protection strict is malformed")
    if payload["strict"] is not EXPECTED_PROTECTION_STRICT:
        raise VerificationError("branch-protection strict moved")
    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, list) or not all(isinstance(item, dict) for item in raw_checks):
        raise VerificationError("branch-protection checks are malformed")
    checks = [
        (
            _require_string(item.get("context"), "required-check context"),
            _require_int(item.get("app_id"), "required-check app_id", minimum=1),
        )
        for item in raw_checks
    ]
    if len(checks) != len(set(checks)):
        raise VerificationError("branch-protection check tuples are duplicated")
    expected_before = set(PRE_CUTOVER_REQUIRED_CHECKS)
    actual = set(checks)
    expected_after = expected_before | {("contract-drift-pr-delta", EXPECTED_PR_DELTA_APP_ID)}
    if actual != expected_before and actual != expected_after:
        raise VerificationError("branch protection does not match a valid cutover state")
    phase = "after" if actual == expected_after else "before"
    return {"strict": payload["strict"], "checks": sorted(checks), "cutover_phase": phase}


@dataclass(frozen=True)
class _Snapshot:
    main_sha: str
    run: dict[str, Any]

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "run_started_at": self.run["run_started_at"],
            "run_id": self.run["id"],
            "run_attempt": self.run["run_attempt"],
        }


def _is_historical_backfill_dispatch(reader: ApiReader, *, repo: str, run: dict[str, Any]) -> bool:
    # Run listings never expose dispatch inputs, so the historical-backfill
    # input is recovered from the attempt topology: program-trajectory is the
    # one job whose `if` is false exactly on a historical-backfill dispatch.
    if run.get("event") != "workflow_dispatch":
        return False
    run_id = _require_int(run.get("id"), "run ID", minimum=1)
    attempt = attempt_numbers(run)[-1]
    endpoint = f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
    jobs, _ = _paginate_collection(
        reader,
        endpoint,
        collection_key="jobs",
        identity=lambda job: job.get("id"),
        label=f"attempt {attempt} jobs",
    )
    trajectory = [job for job in jobs if job.get("name") == "contract-drift-program-trajectory"]
    if len(trajectory) != 1:
        raise VerificationError("dispatch execution does not expose the program-trajectory job")
    summary = _check_summary(
        reader, repo=repo, endpoint=endpoint, job=trajectory[0], run=run, attempt=attempt
    )
    return summary.get("conclusion") == "skipped"


def _snapshot(reader: ApiReader, *, repo: str, workflow_id: int) -> tuple[_Snapshot, list[str]]:
    main_sha = _main_sha(reader, repo)
    runs, endpoints = _workflow_runs(reader, repo=repo, workflow_id=workflow_id)
    run = _selected_main_run(
        runs,
        workflow_id=workflow_id,
        main_sha=main_sha,
        is_historical_backfill=lambda candidate: _is_historical_backfill_dispatch(
            reader, repo=repo, run=candidate
        ),
    )
    source = reader.get_bytes(
        f"repos/{repo}/contents/{CANONICAL_WORKFLOW_PATH}?ref={run['head_sha']}"
    )
    if _workflow_job_names(source) != EXPECTED_WORKFLOW_JOB_NAMES:
        raise VerificationError("selected run workflow source does not expose exact live checks")
    return _Snapshot(main_sha=main_sha, run=run), endpoints


def _same_snapshot(left: _Snapshot, right: _Snapshot) -> bool:
    fields = ("id", "run_attempt", "run_started_at", "status", "conclusion", "head_sha")
    return left.main_sha == right.main_sha and all(
        left.run.get(field) == right.run.get(field) for field in fields
    )


def verify_workflow_state(
    reader: ApiReader,
    *,
    repo: str = DEFAULT_REPOSITORY,
    canonical_workflow_id: int = CANONICAL_WORKFLOW_ID,
) -> dict[str, Any]:
    """Verify complete live topology/history/protection state without mutations."""
    workflow, workflow_pages = _canonical_workflow(
        reader,
        repo=repo,
        canonical_workflow_id=canonical_workflow_id,
    )
    before, run_pages = _snapshot(reader, repo=repo, workflow_id=canonical_workflow_id)
    attempts = _attempts(reader, repo=repo, run=before.run)
    artifacts = _artifacts(reader, repo=repo, run=before.run)
    protection = _branch_protection(reader, repo)
    selected_attempt = attempts[-1]
    checks = selected_attempt["checks"]
    receipt = checks["contract-drift-main-receipt"]
    trajectory = checks["contract-drift-program-trajectory"]
    pr_delta = checks["contract-drift-pr-delta"]
    if before.run.get("status") != "completed":
        raise VerificationError("selected workflow execution is not completed")
    if receipt.get("status") != "completed" or receipt.get("conclusion") != "success":
        raise VerificationError("main-receipt check is not a completed success")
    if trajectory.get("status") != "completed" or trajectory.get("conclusion") not in {
        "failure",
        "timed_out",
    }:
        raise VerificationError("program-trajectory check is not truthfully red")
    if pr_delta.get("conclusion") != "skipped":
        raise VerificationError("push execution did not skip the PR-delta check")
    after, _ = _snapshot(reader, repo=repo, workflow_id=canonical_workflow_id)
    if not _same_snapshot(before, after):
        raise VerificationError(
            "current main or newest workflow execution moved during verification"
        )

    return {
        "repository": repo,
        "workflow": {key: workflow[key] for key in ("id", "name", "path", "state")},
        "workflow_pages": workflow_pages,
        "main_sha": before.main_sha,
        "selection": {
            "identity": before.identity,
            "status": before.run.get("status"),
            "conclusion": before.run.get("conclusion"),
            "attempts": attempts,
            "selected_attempt": selected_attempt,
            "artifacts": artifacts,
            "run_pages": run_pages,
        },
        "branch_protection": protection,
        "stable_requery": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify live Contract Drift Governance workflow state read-only."
    )
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--workflow-id", type=int, default=CANONICAL_WORKFLOW_ID)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_workflow_state(
            GhApiReader(timeout_seconds=args.timeout_seconds),
            repo=args.repo,
            canonical_workflow_id=args.workflow_id,
        )
    except VerificationError as exc:
        print(f"contract drift workflow verification failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"contract drift workflow verification failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        identity = result["selection"]["identity"]
        print(
            "verified "
            f"{result['workflow']['path']} id={result['workflow']['id']} "
            f"main={result['main_sha']} run={identity['run_id']} "
            f"attempt={identity['run_attempt']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
