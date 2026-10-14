#!/usr/bin/env python3
"""Publish structured automation handoffs as GitHub issues.

Local Codex automations can verify bounded work while running in contexts where
GitHub writes are unreliable. This bridge runs from a normal shell, reads the
structured handoffs those automations leave in memory or in the local automation
outbox, deduplicates against existing GitHub issues, and creates the missing
issue records with ``gh``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.github_cli_health import check_github_cli_health

UTC = timezone.utc
DEFAULT_CODEX_HOME = Path.home() / ".codex"
DEFAULT_REPO = "synaptent/aragora"
DEFAULT_LABELS = ("boss-ready",)
DEFAULT_LIMIT = 2
DEFAULT_MAX_OPEN_ISSUES = 12
DEFAULT_COMMAND_TIMEOUT_SECONDS = 45
MAX_ISSUE_BODY_CHARS = 60_000
DEFAULT_OUTBOX_DIR = Path(".aragora/automation-outbox")
DEFAULT_RECEIPT_DIR = Path(".aragora/automation-receipts")
DEFAULT_BASE_REF = "origin/main"
TERMINAL_RECEIPT_STATUSES = {"published", "already_satisfied", "completed", "skipped"}
PR_OPEN_REQUEST_CANONICAL_ACTION = "open_pr"
PR_OPEN_REQUEST_ACTIONS = {
    "open_pr",
    "open_pull_request",
    "open_or_update_pr",
    "open_or_update_pull_request",
    "push_branch_and_open_pr",
    "push_branch_and_open_pull_request",
    "push_branch_and_open_or_update_pr",
    "push_branch_and_open_or_update_pull_request",
}
REQUIRED_OUTBOX_KEYS = (
    "task",
    "requires_github",
    "requested_action",
    "repo",
    "local_evidence",
    "validation",
    "idempotency_key",
    "created_at",
)
DEFAULT_AUTOMATION_IDS = (
    "founder-review",
    "founder-triage",
    "engineering-automation-2",
    "aragora-overnight-steward",
)
REQUIRED_LABELS = (
    "Handoff Source",
    "Priority",
    "Task Title",
    "Why Now",
    "Repo Evidence",
    "Acceptance Criteria",
    "Validation",
    "Expiration Hours",
)
OPTIONAL_LABELS = ("Backup Task",)
ALL_LABELS = REQUIRED_LABELS + OPTIONAL_LABELS
BLOCK_TIMESTAMP_KEY = "__block_timestamp"
BLOCK_POSITION_KEY = "__block_position"
BLOCK_TIMESTAMP_PATTERN = re.compile(
    r"(?m)(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
PR_REFERENCE_PATTERN = re.compile(r"(?i)\b(?:PR|pull request)\s*#(\d+)\b")
PR_SLUG_REFERENCE_PATTERN = re.compile(r"(?i)(?:^|[\\/_-])pr[-_]?(\d{3,})(?:\b|[\\/_-])")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

try:
    from aragora.swarm.github_app_auth import gh_subprocess_run, github_cli_env
except Exception:  # pragma: no cover - fallback for partially bootstrapped script contexts

    def github_cli_env(
        base_env: Mapping[str, str] | None = None,
        *,
        prefer_app: bool = True,
    ) -> dict[str, str]:
        return dict(os.environ if base_env is None else base_env)

    def gh_subprocess_run(
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: float = 30.0,
        prefer_app: bool = True,
        write_op: bool = False,
        env: Mapping[str, str] | None = None,
        max_retries: int = 3,
        base_backoff: float = 5.0,
        max_backoff: float = 600.0,
        sleep: Callable[[float], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del prefer_app, write_op, max_retries, base_backoff, max_backoff, sleep
        return subprocess.run(
            ["gh", *list(args)],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(os.environ if env is None else env),
            check=False,
        )


def _mute_stdout_after_broken_pipe() -> None:
    """Avoid interpreter-shutdown tracebacks after downstream pipes close."""
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, sys.stdout.fileno())
        finally:
            os.close(devnull_fd)
    except (AttributeError, OSError, ValueError):
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass


def _emit_stdout(text: str) -> bool:
    try:
        sys.stdout.write(f"{text}\n")
        sys.stdout.flush()
    except BrokenPipeError:
        _mute_stdout_after_broken_pipe()
        return False
    return True


@dataclass(frozen=True)
class Handoff:
    source_file: str
    task_title: str
    priority: str
    body: str
    labels: dict[str, str]
    expires_at: str | None
    idempotency_key: str | None = None
    source_kind: str = "memory"
    branch: str | None = None
    desired_head: str | None = None


@dataclass(frozen=True)
class PublishDecision:
    task_title: str
    source_file: str
    eligible: bool
    reason: str
    branch: str | None = None
    desired_head: str | None = None
    existing_issue_url: str | None = None
    existing_pr_url: str | None = None
    created_issue_url: str | None = None


def _decision_for_handoff(
    handoff: Handoff,
    *,
    eligible: bool,
    reason: str,
    existing_issue_url: str | None = None,
    existing_pr_url: str | None = None,
    created_issue_url: str | None = None,
) -> PublishDecision:
    return PublishDecision(
        task_title=handoff.task_title,
        source_file=handoff.source_file,
        eligible=eligible,
        reason=reason,
        branch=handoff.branch,
        desired_head=handoff.desired_head,
        existing_issue_url=existing_issue_url,
        existing_pr_url=existing_pr_url,
        created_issue_url=created_issue_url,
    )


def summarize_decisions(decisions: Sequence[PublishDecision]) -> dict[str, Any]:
    reason_counts = Counter(item.reason for item in decisions)
    eligible_count = sum(1 for item in decisions if item.eligible)
    return {
        "total": len(decisions),
        "eligible_count": eligible_count,
        "ineligible_count": len(decisions) - eligible_count,
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def summary_only_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return compact publisher status for recurring automation logs."""

    compact = dict(payload)
    decisions = compact.pop("decisions", None)
    if isinstance(decisions, Sequence) and not isinstance(decisions, (str, bytes, bytearray)):
        decision_count = len(decisions)
        compact["decision_count"] = decision_count
        handoff_count = compact.get("handoff_count")
        if isinstance(handoff_count, int):
            omitted_count = max(handoff_count - decision_count, 0)
            compact["decision_omitted_count"] = omitted_count
            compact["decisions_truncated"] = omitted_count > 0
        compact["decisions_omitted"] = True
    compact["details_omitted"] = True
    return compact


def _gh_write_op(args: list[str]) -> bool:
    return len(args) >= 2 and (args[0], args[1]) in {
        ("issue", "create"),
        ("issue", "edit"),
        ("issue", "comment"),
    }


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = github_cli_env(os.environ) if args and args[0] == "gh" else None
    if args and args[0] == "gh":
        return gh_subprocess_run(
            args[1:],
            timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            prefer_app=True,
            write_op=_gh_write_op(args[1:]),
            env=dict(os.environ if env is None else env),
            max_retries=0,
        )
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = (
            stderr
            or f"command timed out after {DEFAULT_COMMAND_TIMEOUT_SECONDS}s: {' '.join(args)}"
        )
        return subprocess.CompletedProcess(args=args, returncode=124, stdout=stdout, stderr=message)


def _codex_home(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env_value = os.environ.get("CODEX_HOME")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_CODEX_HOME


def _repo_root(path: Path) -> Path:
    proc = _run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "not a git repository")
    return Path(proc.stdout.strip()).resolve()


def _repo_relative(root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return root / path


def _same_git_origin(left: Path, right: Path) -> bool:
    left_proc = _run(["git", "config", "--get", "remote.origin.url"], cwd=left)
    right_proc = _run(["git", "config", "--get", "remote.origin.url"], cwd=right)
    if left_proc.returncode != 0 or right_proc.returncode != 0:
        return False
    return bool(left_proc.stdout.strip()) and left_proc.stdout.strip() == right_proc.stdout.strip()


def _automation_state_root(root: Path) -> Path:
    """Return the checkout whose shared .aragora state should back handoff publishing."""

    if (root / ".aragora").is_dir():
        return root

    configured = os.environ.get("ARAGORA_AUTOMATION_STATE_ROOT")
    candidates: list[tuple[Path, bool]] = []
    if configured:
        candidates.append((Path(configured).expanduser(), True))
    candidates.append((Path.home() / "Development" / "aragora", False))

    for candidate, explicit in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if not (resolved / ".aragora").is_dir():
            continue
        if explicit or _same_git_origin(root, resolved):
            return resolved
    return root


def _automation_state_path(root: Path, path: Path | None, default_relative: Path) -> Path:
    if path is not None:
        return _repo_relative(root, path)
    return _automation_state_root(root) / default_relative


def _automation_state_default_path(state_root: Path, default_relative: Path) -> Path:
    expanded = state_root.expanduser()
    if default_relative.parts[:1] == (".aragora",) and expanded.name == ".aragora":
        return expanded.joinpath(*default_relative.parts[1:])
    return expanded / default_relative


def _memory_files(codex_home: Path, automation_ids: set[str] | None = None) -> list[Path]:
    automations = codex_home / "automations"
    if not automations.exists():
        return []
    if automation_ids is None:
        return sorted(automations.glob("*/memory.md"))
    return sorted(
        path
        for automation_id in automation_ids
        if (path := automations / automation_id / "memory.md").exists()
    )


def _outbox_files(outbox_dir: Path) -> list[Path]:
    if not outbox_dir.exists():
        return []
    return sorted(path for path in outbox_dir.glob("*.json") if path.is_file())


def _source_mtime(source_file: str | Path) -> float:
    try:
        return Path(source_file).stat().st_mtime
    except OSError:
        return 0.0


def _receipt_path(receipt_dir: Path, idempotency_key: str) -> Path:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "-", idempotency_key).strip("-")
    if not safe_key:
        safe_key = "handoff"
    return receipt_dir / f"{safe_key}.json"


def _terminal_receipt_exists(receipt_dir: Path, idempotency_key: str) -> bool:
    path = _receipt_path(receipt_dir, idempotency_key)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("status") or "") in TERMINAL_RECEIPT_STATUSES


def _terminal_receipt_keys(receipt_dir: Path) -> set[str]:
    return set(_terminal_receipts_by_key(receipt_dir))


def _terminal_receipts_by_key(receipt_dir: Path) -> dict[str, list[dict[str, Any]]]:
    receipts: dict[str, list[dict[str, Any]]] = {}
    if not receipt_dir.exists():
        return receipts
    for receipt_file in sorted(receipt_dir.glob("*.json")):
        try:
            payload = json.loads(receipt_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "") not in TERMINAL_RECEIPT_STATUSES:
            continue
        idempotency_key = str(payload.get("idempotency_key") or receipt_file.stem).strip()
        if idempotency_key:
            receipts.setdefault(idempotency_key, []).append(payload)
    return receipts


def _write_receipt(
    receipt_dir: Path,
    handoff: Handoff,
    decision: PublishDecision,
    *,
    repo: str,
) -> None:
    if handoff.source_kind != "outbox" or not handoff.idempotency_key:
        return
    terminal_reasons = {"published", "existing_issue", "existing_pr", "target_open_pr"}
    if decision.reason not in terminal_reasons:
        return
    status = "published" if decision.reason == "published" else "already_satisfied"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "idempotency_key": handoff.idempotency_key,
        "task": handoff.task_title,
        "source_file": handoff.source_file,
        "repo": repo,
        "status": status,
        "reason": decision.reason,
        "created_issue_url": decision.created_issue_url,
        "existing_issue_url": decision.existing_issue_url,
        "existing_pr_url": decision.existing_pr_url,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    _receipt_path(receipt_dir, handoff.idempotency_key).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _label_matches(text: str) -> list[re.Match[str]]:
    label_pattern = "|".join(re.escape(label) for label in ALL_LABELS)
    return list(re.finditer(rf"(?m)^({label_pattern}):\s*", text))


def _timestamp_before(text: str, position: int) -> str | None:
    """Return the closest preceding full ISO timestamp for a memory handoff block."""

    matches = list(BLOCK_TIMESTAMP_PATTERN.finditer(text[:position]))
    if not matches:
        return None
    return matches[-1].group(1)


def _parse_block_datetime(values: dict[str, str]) -> datetime | None:
    raw_timestamp = values.get(BLOCK_TIMESTAMP_KEY)
    if not raw_timestamp:
        return None
    normalized = raw_timestamp.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_blocks(text: str) -> list[dict[str, str]]:
    matches = _label_matches(text)
    blocks: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        if match.group(1) != "Handoff Source":
            continue

        block_matches = [match]
        next_index = index + 1
        while next_index < len(matches) and matches[next_index].group(1) != "Handoff Source":
            block_matches.append(matches[next_index])
            next_index += 1

        values: dict[str, str] = {}
        for item_index, item in enumerate(block_matches):
            next_start = (
                block_matches[item_index + 1].start()
                if item_index + 1 < len(block_matches)
                else len(text)
            )
            values[item.group(1)] = text[item.end() : next_start].strip()

        if all(label in values and values[label] for label in REQUIRED_LABELS):
            values[BLOCK_TIMESTAMP_KEY] = _timestamp_before(text, match.start()) or ""
            values[BLOCK_POSITION_KEY] = str(match.start())
            blocks.append(values)
    return blocks


def _expiration(values: dict[str, str], source_file: Path) -> str | None:
    raw_hours = values.get("Expiration Hours", "").strip()
    try:
        hours = float(raw_hours)
    except ValueError:
        return None
    if hours <= 0:
        return None
    reference_time = _parse_block_datetime(values) or datetime.fromtimestamp(
        source_file.stat().st_mtime, tz=UTC
    )
    expires_at = reference_time + timedelta(hours=hours)
    return expires_at.isoformat()


def _is_expired(expires_at: str | None, *, now: datetime) -> bool:
    if not expires_at:
        return False
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) < now


def _format_body(values: dict[str, str], source_file: Path) -> str:
    lines: list[str] = []
    for label in ALL_LABELS:
        value = values.get(label)
        if value:
            lines.append(f"{label}: {value}")
            lines.append("")
    lines.append("---")
    lines.append(f"Published from automation memory: `{source_file}`")
    return "\n".join(lines).strip()


def _format_json_block(value: Any) -> str:
    if value is None or value == "":
        return "NONE"
    if isinstance(value, str):
        return value.strip() or "NONE"
    return json.dumps(value, indent=2, sort_keys=True)


def _format_outbox_body(payload: dict[str, Any], source_file: Path) -> str:
    fields = [
        ("Task", payload.get("task")),
        ("Requested Action", payload.get("requested_action")),
        ("Requires GitHub", payload.get("requires_github")),
        ("Repo", payload.get("repo")),
        ("Created At", payload.get("created_at")),
        ("Idempotency Key", payload.get("idempotency_key")),
        ("Local Evidence", payload.get("local_evidence")),
        ("Validation", payload.get("validation")),
    ]
    lines: list[str] = []
    for label, value in fields:
        formatted = _format_json_block(value)
        lines.append(f"{label}:")
        if "\n" in formatted or formatted.startswith("{") or formatted.startswith("["):
            lines.append("```json" if formatted.startswith(("{", "[")) else "```")
            lines.append(formatted)
            lines.append("```")
        else:
            lines.append(formatted)
        lines.append("")
    lines.append("---")
    lines.append(f"Published from automation outbox: `{source_file}`")
    return "\n".join(lines).strip()


def _has_required_outbox_contract(payload: dict[str, Any]) -> bool:
    for key in REQUIRED_OUTBOX_KEYS:
        if key not in payload:
            return False
        value = payload[key]
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
    return True


def _local_evidence_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _outbox_evidence_value(payload: dict[str, Any], key: str) -> str:
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        value = str(local_evidence.get(key) or "").strip()
        if value:
            return value
    requested_action = _structured_action(payload.get("requested_action"))
    if requested_action is not None:
        value = str(requested_action.get(key) or "").strip()
        if value:
            return value
    return str(payload.get(key) or "").strip()


def _structured_action(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    return None
            except (SyntaxError, ValueError):
                return None
            if isinstance(parsed, Mapping):
                return parsed
    return None


def _normalized_requested_action(value: Any) -> str:
    structured = _structured_action(value)
    if structured is not None:
        action = str(
            structured.get("type")
            or structured.get("action")
            or structured.get("requested_action")
            or ""
        )
    elif isinstance(value, str):
        text = value.strip()
        action = text
    else:
        action = str(value or "")

    normalized = action.strip().lower().replace("-", "_")
    if normalized in PR_OPEN_REQUEST_ACTIONS:
        return PR_OPEN_REQUEST_CANONICAL_ACTION
    return normalized


def _is_pr_open_request(payload: dict[str, Any]) -> bool:
    return (
        _normalized_requested_action(payload.get("requested_action"))
        == PR_OPEN_REQUEST_CANONICAL_ACTION
    )


def _outbox_branch_fingerprint(payload: dict[str, Any]) -> str | None:
    requested_action = _normalized_requested_action(payload.get("requested_action"))
    repo = str(payload.get("repo") or "").strip()
    branch = _outbox_evidence_value(payload, "branch")
    if not requested_action or not repo or not branch:
        return None
    return "\0".join((requested_action, repo, branch))


def _outbox_desired_head(payload: dict[str, Any]) -> str | None:
    for key in ("desired_head_sha", "head_sha", "head", "commit"):
        value = _outbox_evidence_value(payload, key)
        if value and re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
            return value
    return None


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    proc = _run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=repo_root)
    return proc.returncode == 0


def _git_patch_equivalent(repo_root: Path, base: str, candidate: str) -> bool:
    diff_proc = _run(["git", "diff", "--quiet", f"{base}...{candidate}"], cwd=repo_root)
    if diff_proc.returncode == 0:
        return True
    if diff_proc.returncode != 1:
        return False

    proc = _run(["git", "cherry", base, candidate], cwd=repo_root)
    if proc.returncode != 0:
        return False
    statuses = [line[:1] for line in proc.stdout.splitlines() if line.strip()]
    return bool(statuses) and all(status == "-" for status in statuses)


def _outbox_branch_already_merged(repo_root: Path, payload: dict[str, Any]) -> bool:
    if not _is_pr_open_request(payload):
        return False

    base_ref = _outbox_evidence_value(payload, "base") or DEFAULT_BASE_REF
    if not base_ref:
        return False

    candidates = [
        _outbox_evidence_value(payload, "head"),
        _outbox_evidence_value(payload, "head_sha"),
        _outbox_evidence_value(payload, "commit"),
        _outbox_evidence_value(payload, "branch"),
    ]
    for candidate in dict.fromkeys(item for item in candidates if item):
        if _git_is_ancestor(repo_root, candidate, base_ref):
            return True
    return False


def _outbox_branch_patch_equivalent(repo_root: Path, payload: dict[str, Any]) -> bool:
    if not _is_pr_open_request(payload):
        return False

    base_ref = _outbox_evidence_value(payload, "base") or DEFAULT_BASE_REF
    if not base_ref:
        return False

    candidates = [
        _outbox_evidence_value(payload, "branch"),
        _outbox_evidence_value(payload, "head"),
        _outbox_evidence_value(payload, "head_sha"),
        _outbox_evidence_value(payload, "commit"),
    ]
    for candidate in dict.fromkeys(item for item in candidates if item):
        if _git_patch_equivalent(repo_root, base_ref, candidate):
            return True
    return False


def _remote_tracking_head(repo_root: Path, branch: str | None) -> str | None:
    if not branch:
        return None
    proc = _run(["git", "rev-parse", "--verify", f"origin/{branch}"], cwd=repo_root)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value if re.fullmatch(r"[0-9a-fA-F]{7,40}", value) else None


def _branch_tip(repo_root: Path, branch: str | None) -> str | None:
    if not branch:
        return None

    refs = [branch] if branch.startswith("origin/") else [f"origin/{branch}", branch]
    for ref in dict.fromkeys(refs):
        proc = _run(["git", "rev-parse", "--verify", ref], cwd=repo_root)
        if proc.returncode != 0:
            continue
        value = proc.stdout.strip()
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
            return value
    return None


def _stale_outbox_head(repo_root: Path, handoff: Handoff) -> str | None:
    if handoff.source_kind != "outbox" or not handoff.branch or not handoff.desired_head:
        return None
    branch_tip = _branch_tip(repo_root, handoff.branch)
    if not branch_tip or _head_matches(handoff.desired_head, branch_tip):
        return None
    return branch_tip


def _local_handoff_blocker(repo_root: Path, handoff: Handoff) -> PublishDecision | None:
    if _stale_outbox_head(repo_root, handoff):
        return _decision_for_handoff(
            handoff,
            eligible=False,
            reason="stale_outbox_head",
        )
    return None


def _receipt_satisfies_outbox(
    repo_root: Path,
    payload: dict[str, Any],
    receipt_payload: dict[str, Any],
) -> bool:
    reason = str(receipt_payload.get("reason") or "").strip().lower()
    if _is_pr_open_request(payload):
        created_issue_url = str(receipt_payload.get("created_issue_url") or "").strip()
        existing_issue_url = str(receipt_payload.get("existing_issue_url") or "").strip()
        if reason in {"published", "existing_issue"} or created_issue_url or existing_issue_url:
            return False

    desired_head = _outbox_desired_head(payload)
    if reason != "target_open_pr" or not desired_head:
        return True
    remote_head = _remote_tracking_head(repo_root, _outbox_evidence_value(payload, "branch"))
    if not remote_head:
        return False
    return _head_matches(desired_head, remote_head)


def _terminal_outbox_fingerprints(
    repo_root: Path,
    outbox_dir: Path,
    terminal_receipts: dict[str, list[dict[str, Any]]],
) -> set[str]:
    if not terminal_receipts:
        return set()
    fingerprints: set[str] = set()
    for source_file in _outbox_files(outbox_dir):
        try:
            payload = json.loads(source_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not _has_required_outbox_contract(payload):
            continue
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        receipt_payloads = terminal_receipts.get(idempotency_key, [])
        if not any(
            _receipt_satisfies_outbox(repo_root, payload, receipt_payload)
            for receipt_payload in receipt_payloads
        ):
            continue
        fingerprint = _outbox_branch_fingerprint(payload)
        if fingerprint:
            fingerprints.add(fingerprint)
    return fingerprints


def _latest_block(parsed_blocks: list[dict[str, str]]) -> dict[str, str]:
    def key(values: dict[str, str]) -> tuple[datetime, int]:
        block_time = _parse_block_datetime(values) or datetime.min.replace(tzinfo=UTC)
        try:
            position = int(values.get(BLOCK_POSITION_KEY, "0"))
        except ValueError:
            position = 0
        return (block_time, position)

    return max(parsed_blocks, key=key)


def load_handoffs(
    codex_home: Path,
    *,
    automation_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[Handoff]:
    current_time = now or datetime.now(UTC)
    handoffs: list[Handoff] = []
    for memory_file in _memory_files(codex_home, automation_ids):
        try:
            text = memory_file.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed_blocks = _parse_blocks(text)
        if not parsed_blocks:
            continue
        values = _latest_block(parsed_blocks)
        priority = values["Priority"].strip()
        task_title = values["Task Title"].strip()
        expires_at = _expiration(values, memory_file)
        if priority.upper() == "NONE" or task_title.upper() == "NONE":
            continue
        if _is_expired(expires_at, now=current_time):
            continue
        handoffs.append(
            Handoff(
                source_file=str(memory_file),
                task_title=task_title,
                priority=priority,
                body=_format_body(values, memory_file),
                labels=values,
                expires_at=expires_at,
            )
        )

    return sorted(
        handoffs,
        key=lambda item: (_source_mtime(item.source_file), item.priority),
        reverse=True,
    )


def load_outbox_handoffs(
    repo_root: Path,
    *,
    outbox_dir: Path | None = None,
    receipt_dir: Path | None = None,
    now: datetime | None = None,
    max_handoffs: int | None = None,
) -> list[Handoff]:
    handoffs, _skip_reasons = _load_outbox_handoffs_with_skip_reasons(
        repo_root,
        outbox_dir=outbox_dir,
        receipt_dir=receipt_dir,
        now=now,
        max_handoffs=max_handoffs,
    )
    return handoffs


def _load_outbox_handoffs_with_skip_reasons(
    repo_root: Path,
    *,
    outbox_dir: Path | None = None,
    receipt_dir: Path | None = None,
    now: datetime | None = None,
    max_handoffs: int | None = None,
) -> tuple[list[Handoff], Counter[str]]:
    outbox_root = _automation_state_path(repo_root, outbox_dir, DEFAULT_OUTBOX_DIR).resolve()
    receipt_root = _automation_state_path(repo_root, receipt_dir, DEFAULT_RECEIPT_DIR).resolve()
    current_time = now or datetime.now(UTC)
    terminal_receipts = _terminal_receipts_by_key(receipt_root)
    terminal_fingerprints = (
        set()
        if max_handoffs is not None
        else _terminal_outbox_fingerprints(
            repo_root,
            outbox_root,
            terminal_receipts,
        )
    )
    handoffs_by_identity: dict[tuple[str, str], Handoff] = {}
    skipped_reasons: Counter[str] = Counter()
    source_files = _outbox_files(outbox_root)
    if max_handoffs is not None:
        source_files = sorted(source_files, key=_source_mtime, reverse=True)
    for index, source_file in enumerate(source_files):
        if max_handoffs is not None and len(handoffs_by_identity) >= max_handoffs:
            skipped_reasons["preview_limit"] += len(source_files) - index
            break
        try:
            payload = json.loads(source_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped_reasons["invalid_json"] += 1
            continue
        if not isinstance(payload, dict):
            skipped_reasons["invalid_payload"] += 1
            continue
        if not _has_required_outbox_contract(payload):
            skipped_reasons["missing_required_contract"] += 1
            continue
        task_title = str(payload.get("task") or payload.get("title") or "").strip()
        requested_action = _normalized_requested_action(payload.get("requested_action"))
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        requires_github = payload.get("requires_github", True)
        if isinstance(requires_github, str):
            requires_github = requires_github.strip().lower() not in {"0", "false", "no"}
        if requires_github is False:
            skipped_reasons["requires_github_false"] += 1
            continue
        if not task_title or not requested_action or not idempotency_key:
            skipped_reasons["missing_identity"] += 1
            continue
        expires_at = str(payload.get("expires_at") or "").strip() or None
        if _is_expired(expires_at, now=current_time):
            skipped_reasons["expired"] += 1
            continue
        branch_fingerprint = _outbox_branch_fingerprint(payload)
        receipt_payloads = terminal_receipts.get(idempotency_key, [])
        if any(
            _receipt_satisfies_outbox(repo_root, payload, receipt_payload)
            for receipt_payload in receipt_payloads
        ):
            skipped_reasons["terminal_receipt"] += 1
            continue
        if branch_fingerprint and branch_fingerprint in terminal_fingerprints:
            skipped_reasons["terminal_branch_receipt"] += 1
            continue
        if _outbox_branch_already_merged(repo_root, payload):
            skipped_reasons["already_merged"] += 1
            continue
        if _outbox_branch_patch_equivalent(repo_root, payload):
            skipped_reasons["patch_equivalent"] += 1
            continue
        handoff = Handoff(
            source_file=str(source_file),
            task_title=task_title,
            priority=str(payload.get("priority") or "MEDIUM").strip() or "MEDIUM",
            body=_format_outbox_body(payload, source_file),
            labels={key: _format_json_block(value) for key, value in payload.items()},
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            source_kind="outbox",
            branch=_outbox_evidence_value(payload, "branch") or None,
            desired_head=_outbox_desired_head(payload),
        )
        identity = (
            ("branch", branch_fingerprint)
            if branch_fingerprint
            else ("idempotency", idempotency_key)
        )
        existing = handoffs_by_identity.get(identity)
        if existing is None or (
            _source_mtime(handoff.source_file),
            handoff.source_file,
        ) > (
            _source_mtime(existing.source_file),
            existing.source_file,
        ):
            if existing is not None:
                skipped_reasons["duplicate_identity"] += 1
            handoffs_by_identity[identity] = handoff
        else:
            skipped_reasons["duplicate_identity"] += 1
    handoffs = sorted(
        handoffs_by_identity.values(),
        key=lambda item: (_source_mtime(item.source_file), item.priority),
        reverse=True,
    )
    return handoffs, skipped_reasons


def _ensure_gh_auth(repo_root: Path) -> None:
    health = check_github_cli_health(repo_root)
    if not health.ready:
        raise RuntimeError(health.error or health.mode)


def _title_tokens(title: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", title.lower())
        if len(token) >= 3 and token not in STOPWORDS
    }


def _looks_duplicate(candidate: str, existing: str) -> bool:
    candidate_tokens = _title_tokens(candidate)
    existing_tokens = _title_tokens(existing)
    if not candidate_tokens or not existing_tokens:
        return candidate.strip().lower() == existing.strip().lower()
    candidate_handlers = {token for token in candidate_tokens if token.endswith("handler")}
    existing_handlers = {token for token in existing_tokens if token.endswith("handler")}
    if (
        candidate_handlers
        and existing_handlers
        and candidate_handlers.isdisjoint(existing_handlers)
    ):
        return False
    overlap = candidate_tokens & existing_tokens
    return len(overlap) >= min(3, len(candidate_tokens))


def _existing_issue(repo_root: Path, repo: str, title: str) -> dict[str, Any] | None:
    proc = _run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--search",
            title,
            "--json",
            "number,title,url,state",
            "--limit",
            "50",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "failed to list issues")
    payload = json.loads(proc.stdout or "[]")
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        existing_title = str(item.get("title") or "")
        if _looks_duplicate(title, existing_title):
            return item
    return None


def _existing_pr(repo_root: Path, repo: str, title: str) -> dict[str, Any] | None:
    proc = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--search",
            title,
            "--json",
            "number,title,url,state,headRefName,headRefOid",
            "--limit",
            "50",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "failed to list PRs")
    payload = json.loads(proc.stdout or "[]")
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        existing_title = str(item.get("title") or "")
        if _looks_duplicate(title, existing_title):
            return item
    return None


def _referenced_pr_numbers(handoff: Handoff) -> list[int]:
    seen: set[int] = set()
    numbers: list[int] = []
    text = f"{handoff.task_title}\n{handoff.body}"
    matches = list(PR_REFERENCE_PATTERN.finditer(text)) + list(
        PR_SLUG_REFERENCE_PATTERN.finditer(text)
    )
    for match in matches:
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if number in seen:
            continue
        seen.add(number)
        numbers.append(number)
    return numbers


def _pr_by_number(repo_root: Path, repo: str, number: int) -> dict[str, Any] | None:
    proc = _run(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,title,url,state,headRefName,headRefOid",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").lower()
        if "could not resolve to a pull request" in stderr or "not found" in stderr:
            return None
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "failed to view PR")
    payload = json.loads(proc.stdout or "{}")
    return payload if isinstance(payload, dict) else None


def _open_pr_by_branch(repo_root: Path, repo: str, branch: str | None) -> dict[str, Any] | None:
    if not branch:
        return None
    proc = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--head",
            branch,
            "--json",
            "number,title,url,state,headRefName,headRefOid",
            "--limit",
            "1",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or "failed to list PRs by branch"
        )
    payload = json.loads(proc.stdout or "[]")
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    return first if isinstance(first, dict) else None


def _head_matches(desired: str, actual: str) -> bool:
    desired_value = desired.strip().lower()
    actual_value = actual.strip().lower()
    if len(desired_value) < 7 or len(actual_value) < 7:
        return False
    return actual_value.startswith(desired_value) or desired_value.startswith(actual_value)


def _pr_head_satisfies_handoff(handoff: Handoff, pr: Mapping[str, Any]) -> bool:
    if handoff.source_kind != "outbox" or not handoff.desired_head:
        return True
    actual_head = str(pr.get("headRefOid") or "").strip()
    return bool(actual_head) and _head_matches(handoff.desired_head, actual_head)


def _target_open_pr(repo_root: Path, repo: str, handoff: Handoff) -> dict[str, Any] | None:
    branch_pr = _open_pr_by_branch(repo_root, repo, handoff.branch)
    if branch_pr and _pr_head_satisfies_handoff(handoff, branch_pr):
        return branch_pr
    for number in _referenced_pr_numbers(handoff):
        pr = _pr_by_number(repo_root, repo, number)
        if (
            isinstance(pr, dict)
            and str(pr.get("state") or "").upper() == "OPEN"
            and _pr_head_satisfies_handoff(handoff, pr)
        ):
            return pr
    return None


def _referenced_pr(repo_root: Path, repo: str, handoff: Handoff) -> dict[str, Any] | None:
    for number in _referenced_pr_numbers(handoff):
        pr = _pr_by_number(repo_root, repo, number)
        if isinstance(pr, dict):
            return pr
    return None


def _open_boss_ready_count(repo_root: Path, repo: str, labels: list[str]) -> int:
    args = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--json",
        "number",
        "--limit",
        "200",
    ]
    for label in labels:
        args.extend(["--label", label])
    proc = _run(args, cwd=repo_root)
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or "failed to count open issues"
        )
    payload = json.loads(proc.stdout or "[]")
    return len(payload) if isinstance(payload, list) else 0


def _create_issue(
    repo_root: Path,
    repo: str,
    handoff: Handoff,
    *,
    labels: list[str],
) -> str:
    args = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        handoff.task_title,
        "--body",
        _fit_issue_body(handoff.body),
    ]
    for label in labels:
        args.extend(["--label", label])
    proc = _run(args, cwd=repo_root)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh issue create failed")
    url = str(proc.stdout or "").strip().splitlines()[-1].strip()
    _add_issue_labels(repo_root, repo, url, labels)
    return url


def _fit_issue_body(body: str) -> str:
    if len(body) <= MAX_ISSUE_BODY_CHARS:
        return body
    suffix = (
        "\n\n---\n"
        "Automation publisher truncated this issue body because it exceeded "
        "GitHub's size limit. See the source automation memory path above for full evidence."
    )
    return body[: MAX_ISSUE_BODY_CHARS - len(suffix)].rstrip() + suffix


def _issue_number_from_url(url: str) -> str | None:
    match = re.search(r"/issues/(\d+)(?:$|[/?#])", url)
    return match.group(1) if match else None


def _add_issue_labels(repo_root: Path, repo: str, issue_url: str, labels: list[str]) -> None:
    if not labels:
        return
    number = _issue_number_from_url(issue_url)
    if not number:
        return
    proc = _run(
        ["gh", "issue", "edit", number, "--repo", repo, "--add-label", ",".join(labels)],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        return


def decide_handoffs(
    handoffs: list[Handoff],
    *,
    repo_root: Path,
    repo: str,
    labels: list[str],
    max_open_issues: int,
) -> list[PublishDecision]:
    open_issue_count = _open_boss_ready_count(repo_root, repo, labels)
    decisions: list[PublishDecision] = []
    for handoff in handoffs:
        local_blocker = _local_handoff_blocker(repo_root, handoff)
        if local_blocker is not None:
            decisions.append(local_blocker)
            continue
        target_pr = _target_open_pr(repo_root, repo, handoff)
        if target_pr:
            decisions.append(
                _decision_for_handoff(
                    handoff,
                    eligible=False,
                    reason="target_open_pr",
                    existing_pr_url=str(target_pr.get("url") or ""),
                )
            )
            continue
        existing = _existing_issue(repo_root, repo, handoff.task_title)
        if existing:
            decisions.append(
                _decision_for_handoff(
                    handoff,
                    eligible=False,
                    reason="existing_issue",
                    existing_issue_url=str(existing.get("url") or ""),
                )
            )
            continue
        referenced_pr = _referenced_pr(repo_root, repo, handoff)
        if referenced_pr and _pr_head_satisfies_handoff(handoff, referenced_pr):
            decisions.append(
                _decision_for_handoff(
                    handoff,
                    eligible=False,
                    reason="existing_pr",
                    existing_pr_url=str(referenced_pr.get("url") or ""),
                )
            )
            continue
        existing_pr = _existing_pr(repo_root, repo, handoff.task_title)
        if existing_pr and _pr_head_satisfies_handoff(handoff, existing_pr):
            decisions.append(
                _decision_for_handoff(
                    handoff,
                    eligible=False,
                    reason="existing_pr",
                    existing_pr_url=str(existing_pr.get("url") or ""),
                )
            )
            continue
        if open_issue_count >= max_open_issues:
            decisions.append(
                _decision_for_handoff(
                    handoff,
                    eligible=False,
                    reason="open_issue_cap",
                )
            )
            continue
        decisions.append(
            _decision_for_handoff(
                handoff,
                eligible=True,
                reason="eligible",
            )
        )
    return decisions


def publish_handoffs(
    handoffs: list[Handoff],
    decisions: list[PublishDecision],
    *,
    repo_root: Path,
    repo: str,
    labels: list[str],
    limit: int,
    receipt_dir: Path | None = None,
) -> list[PublishDecision]:
    by_key = {(item.task_title, item.source_file): item for item in handoffs}
    published: list[PublishDecision] = []
    count = 0
    for decision in decisions:
        if not decision.eligible:
            published.append(decision)
            continue
        handoff = by_key[(decision.task_title, decision.source_file)]
        if count >= limit:
            published.append(
                _decision_for_handoff(
                    handoff,
                    eligible=False,
                    reason="publish_limit",
                )
            )
            continue
        url = _create_issue(repo_root, repo, handoff, labels=labels)
        count += 1
        published_decision = _decision_for_handoff(
            handoff,
            eligible=False,
            reason="published",
            created_issue_url=url,
        )
        if receipt_dir is not None:
            _write_receipt(receipt_dir, handoff, published_decision, repo=repo)
        published.append(published_decision)
    return published


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish structured automation memory handoffs as GitHub issues.",
        allow_abbrev=False,
    )
    parser.add_argument("--repo", default=".", help="Path inside the target repository")
    parser.add_argument(
        "--github-repo",
        default=DEFAULT_REPO,
        help="GitHub repository slug for gh issue operations",
    )
    parser.add_argument(
        "--codex-home",
        default=None,
        help="Codex home containing automations; defaults to $CODEX_HOME or ~/.codex",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Maximum number of issues to create in one apply run",
    )
    parser.add_argument(
        "--max-open-issues",
        type=int,
        default=DEFAULT_MAX_OPEN_ISSUES,
        help="Maximum open issues with the selected labels before publishing pauses",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=list(DEFAULT_LABELS),
        help="Issue label to add; may be passed multiple times",
    )
    parser.add_argument(
        "--automation-id",
        action="append",
        dest="automation_ids",
        default=[],
        help=(
            "Automation memory id to scan. Defaults to scout/support automations: "
            + ", ".join(DEFAULT_AUTOMATION_IDS)
        ),
    )
    parser.add_argument(
        "--state-root",
        default=None,
        help=(
            "Shared automation state root used to derive default outbox/receipt dirs. "
            "Accepts either a repo root containing .aragora or the .aragora directory "
            "itself. Explicit --outbox-dir/--receipt-dir override it."
        ),
    )
    parser.add_argument(
        "--outbox-dir",
        default=None,
        help=(
            "Directory containing JSON automation outbox handoffs. Defaults to "
            ".aragora/automation-outbox under the shared automation state root."
        ),
    )
    parser.add_argument(
        "--receipt-dir",
        default=None,
        help=(
            "Directory for JSON automation publish receipts. Defaults to "
            ".aragora/automation-receipts under the shared automation state root."
        ),
    )
    parser.add_argument(
        "--no-outbox",
        action="store_true",
        help="Disable loading JSON automation outbox handoffs.",
    )
    parser.add_argument("--apply", action="store_true", help="Create eligible GitHub issues")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview eligible handoffs without writing; this is the default mode",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="With --json, omit per-handoff decisions and print compact counts only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    repo_root = _repo_root(Path(args.repo))
    codex_home = _codex_home(args.codex_home)
    state_root = Path(args.state_root).expanduser() if args.state_root else None
    outbox_arg = Path(args.outbox_dir).expanduser() if args.outbox_dir else None
    receipt_arg = Path(args.receipt_dir).expanduser() if args.receipt_dir else None
    if state_root is not None:
        if outbox_arg is None:
            outbox_arg = _automation_state_default_path(state_root, DEFAULT_OUTBOX_DIR)
        if receipt_arg is None:
            receipt_arg = _automation_state_default_path(state_root, DEFAULT_RECEIPT_DIR)
    outbox_dir = _automation_state_path(
        repo_root,
        outbox_arg,
        DEFAULT_OUTBOX_DIR,
    ).resolve()
    receipt_dir = _automation_state_path(
        repo_root,
        receipt_arg,
        DEFAULT_RECEIPT_DIR,
    ).resolve()
    labels = list(dict.fromkeys(args.labels))
    automation_ids = set(args.automation_ids or DEFAULT_AUTOMATION_IDS)
    memory_handoffs = load_handoffs(codex_home, automation_ids=automation_ids)
    outbox_preview_limit = None
    if args.no_outbox:
        outbox_handoffs: list[Handoff] = []
        outbox_skipped_reason_counts: Counter[str] = Counter()
    else:
        outbox_preview_limit = max(args.limit, 0) if args.summary_only and not args.apply else None
        if outbox_preview_limit is None:
            outbox_handoffs, outbox_skipped_reason_counts = _load_outbox_handoffs_with_skip_reasons(
                repo_root,
                outbox_dir=outbox_dir,
                receipt_dir=receipt_dir,
            )
        else:
            outbox_handoffs, outbox_skipped_reason_counts = _load_outbox_handoffs_with_skip_reasons(
                repo_root,
                outbox_dir=outbox_dir,
                receipt_dir=receipt_dir,
                max_handoffs=outbox_preview_limit,
            )
    outbox_file_count = 0 if args.no_outbox else len(_outbox_files(outbox_dir))
    outbox_skipped_count = sum(outbox_skipped_reason_counts.values())
    if outbox_skipped_count == 0:
        outbox_skipped_count = max(outbox_file_count - len(outbox_handoffs), 0)
    outbox_skipped_reason_counts_payload = dict(sorted(outbox_skipped_reason_counts.items()))
    handoffs = sorted(
        memory_handoffs + outbox_handoffs,
        key=lambda item: (_source_mtime(item.source_file), item.priority),
        reverse=True,
    )
    github_health = check_github_cli_health(repo_root)
    if not github_health.ready:
        decision_handoffs = handoffs[: max(args.limit, 0)]
        decisions = [
            _local_handoff_blocker(repo_root, handoff)
            or _decision_for_handoff(
                handoff,
                eligible=False,
                reason="github_unavailable",
            )
            for handoff in decision_handoffs
        ]
        payload = {
            "repo": str(repo_root),
            "codex_home": str(codex_home),
            "github_repo": args.github_repo,
            "labels": labels,
            "automation_ids": sorted(automation_ids),
            "outbox_dir": str(outbox_dir),
            "receipt_dir": str(receipt_dir),
            "memory_handoff_count": len(memory_handoffs),
            "outbox_file_count": outbox_file_count,
            "outbox_handoff_count": len(outbox_handoffs),
            "outbox_skipped_count": outbox_skipped_count,
            "outbox_skipped_reason_counts": outbox_skipped_reason_counts_payload,
            "outbox_preview_limited": outbox_preview_limit is not None,
            "outbox_preview_limit": outbox_preview_limit,
            "handoff_count": len(handoffs),
            "github_health": github_health.to_dict(),
            "decisions": [asdict(item) for item in decisions],
            "decision_summary": summarize_decisions(decisions),
        }
        if args.json:
            output_payload = summary_only_payload(payload) if args.summary_only else payload
            emitted = _emit_stdout(json.dumps(output_payload, indent=2))
        else:
            if handoffs:
                emitted = _emit_stdout(
                    f"github_unavailable: {github_health.mode} {github_health.error}".strip()
                )
            else:
                emitted = _emit_stdout(
                    f"noop: no handoffs to publish; github_unavailable={github_health.mode}"
                )
        if not emitted:
            return 0
        return 1 if handoffs else 0

    decision_handoffs = (
        handoffs[: max(args.limit, 0)] if args.summary_only and not args.apply else handoffs
    )
    decisions = decide_handoffs(
        decision_handoffs,
        repo_root=repo_root,
        repo=args.github_repo,
        labels=labels,
        max_open_issues=args.max_open_issues,
    )
    results = (
        publish_handoffs(
            handoffs,
            decisions,
            repo_root=repo_root,
            repo=args.github_repo,
            labels=labels,
            limit=args.limit,
            receipt_dir=receipt_dir,
        )
        if args.apply
        else decisions
    )
    by_key = {(item.task_title, item.source_file): item for item in handoffs}
    if args.apply:
        for item in results:
            handoff = by_key.get((item.task_title, item.source_file))
            if handoff is not None:
                _write_receipt(receipt_dir, handoff, item, repo=args.github_repo)

    payload = {
        "repo": str(repo_root),
        "codex_home": str(codex_home),
        "github_repo": args.github_repo,
        "labels": labels,
        "automation_ids": sorted(automation_ids),
        "outbox_dir": str(outbox_dir),
        "receipt_dir": str(receipt_dir),
        "memory_handoff_count": len(memory_handoffs),
        "outbox_file_count": outbox_file_count,
        "outbox_handoff_count": len(outbox_handoffs),
        "outbox_skipped_count": outbox_skipped_count,
        "outbox_skipped_reason_counts": outbox_skipped_reason_counts_payload,
        "outbox_preview_limited": outbox_preview_limit is not None,
        "outbox_preview_limit": outbox_preview_limit,
        "handoff_count": len(handoffs),
        "github_health": github_health.to_dict(),
        "decisions": [asdict(item) for item in results],
        "decision_summary": summarize_decisions(results),
    }
    if args.json:
        output_payload = summary_only_payload(payload) if args.summary_only else payload
        if not _emit_stdout(json.dumps(output_payload, indent=2)):
            return 0
    else:
        for item in results:
            marker = (
                "issue"
                if item.reason == "published"
                else "skip"
                if not item.eligible
                else "publish"
            )
            target = item.created_issue_url or item.existing_issue_url or item.existing_pr_url or ""
            if not _emit_stdout(f"{marker}: {item.task_title} [{item.reason}] {target}".strip()):
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
