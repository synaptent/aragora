#!/usr/bin/env python3
"""Generate boss-ready GitHub issues by scanning the codebase.

Scans for improvement opportunities (missing tests, silent exceptions,
broad exception handlers, TODOs, etc.), formats them as boss-ready issues,
validates through the pre-dispatch gate, deduplicates against open issues,
and creates them on GitHub.

Usage:
    python scripts/generate_boss_issues.py --dry-run            # Preview
    python scripts/generate_boss_issues.py --max-issues 10      # Create 10
    python scripts/generate_boss_issues.py --categories test_coverage silent_exception
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.swarm.decomposition_bridge import DecompositionBridge  # noqa: E402
from aragora.swarm.issue_scanner import BossIssueCandidate, scan_all  # noqa: E402
from aragora.swarm.issue_upgrader import upgrade_issue_heuristic  # noqa: E402
from aragora.swarm.pr_value import (  # noqa: E402
    CLASS_MAINTENANCE,
    read_backpressure_withheld_classes,
)
from aragora.swarm.proof_first_queue import classify_proof_first_queue_issue  # noqa: E402
from aragora.swarm.roadmap_priority import load_roadmap_priority_policy  # noqa: E402

_GENERIC_PARENT_PHRASES: tuple[str, ...] = (
    "read the module and identify all public functions",
    "create a test file with broad coverage",
    "covering all public api surface",
    "while preserving existing behavior and keeping the work reviewable",
    "supporting tests",
    "think about it",
)
_OPEN_ISSUE_PAGE_SIZE = 100
_OPEN_ISSUE_MAX_PAGES = 10
_OPEN_PR_PAGE_SIZE = 100
_OPEN_PR_MAX_PAGES = 10
_OPEN_PR_FILES_PAGE_SIZE = 100
_OPEN_PR_FILES_MAX_PAGES = 10
DEFAULT_BACKPRESSURE_SIGNAL_FILE = REPO_ROOT / ".aragora" / "backpressure.json"
_UPGRADEABLE_CATEGORIES = frozenset(
    {"test_coverage", "broad_exception", "silent_exception", "type_annotation"}
)


@dataclass(slots=True)
class DecompositionTelemetry:
    """Aggregate telemetry for one generator run."""

    parents_seen: int = 0
    parents_eligible: int = 0
    parents_preserved: int = 0
    parents_replaced: int = 0
    children_emitted: int = 0
    children_rejected: int = 0
    sanitizer_rejections: int = 0


class _AdmissionError(RuntimeError):
    """A required queue observation is unavailable or incomplete."""

    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage}: {reason}")


def _github_json(stage: str, endpoint: str, *fields: str) -> object:
    command = ["gh", "api", "--method", "GET", endpoint]
    for field in fields:
        command.extend(["-f", field])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise _AdmissionError(stage, f"{type(exc).__name__}: {exc}") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:200]
        raise _AdmissionError(stage, f"gh failed rc={result.returncode} stderr={stderr!r}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _AdmissionError(stage, f"invalid JSON: {exc}") from exc


def _github_pages(endpoint: str, *, stage: str, page_size: int, max_pages: int) -> Iterator[dict]:
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, max_pages + 1):
        page_stage = f"{stage} page {page}"
        payload = _github_json(page_stage, f"{endpoint}{separator}per_page={page_size}&page={page}")
        if not isinstance(payload, list) or len(payload) > page_size:
            raise _AdmissionError(page_stage, "expected a bounded list of records")
        for record in payload:
            if not isinstance(record, dict):
                raise _AdmissionError(page_stage, "expected an object record")
            yield record
        if len(payload) < page_size:
            return
    raise _AdmissionError(stage, f"pagination exceeded configured cap ({max_pages} pages)")


def _valid_count(value: object) -> bool:
    return type(value) is int and value >= 0


def format_boss_ready_body(candidate: BossIssueCandidate) -> str:
    """Format a candidate into the proven boss-ready issue body.

    For supported categories, use the issue upgrader to generate concrete,
    module-aware issue bodies instead of the generic template.
    """
    if candidate.category in _UPGRADEABLE_CATEGORIES:
        upgraded = upgrade_issue_heuristic(
            candidate.title,
            f"## Task\n\n{candidate.description}\n\n### File Scope\n"
            + "\n".join(f"- `{f}`" for f in candidate.file_scope),
            repo_root=REPO_ROOT,
            category=candidate.category,
            validation_command=candidate.validation_command,
            acceptance_criteria=list(candidate.acceptance_criteria),
            new_files=list(candidate.new_files),
        )
        if upgraded:
            body = upgraded.upgraded_body
            body += f"\n\n<!-- fingerprint:{candidate.fingerprint} -->"
            return body

    parts: list[str] = []

    # Task section
    parts.append(f"## Task\n\n{candidate.description}")

    # File scope
    scope_lines: list[str] = []
    for f in candidate.file_scope:
        scope_lines.append(f"- `{f}`")
    for f in candidate.new_files:
        scope_lines.append(f"- `{f}` (create)")
    if scope_lines:
        parts.append("### File Scope\n" + "\n".join(scope_lines))

    # Validation
    if candidate.validation_command:
        parts.append(f"### Validation\n```bash\n{candidate.validation_command}\n```")

    # Acceptance criteria
    if candidate.acceptance_criteria:
        criteria = "\n".join(f"- {c}" for c in candidate.acceptance_criteria)
        parts.append(f"### Acceptance Criteria\n{criteria}")

    # Constraints
    parts.append(
        "### Constraints\n"
        "- Single-file change preferred\n"
        "- Under 100 lines of new/changed code\n"
        f"- Estimated complexity: {candidate.estimated_complexity}"
    )

    # Fingerprint for exact dedup across runs
    parts.append(f"<!-- fingerprint:{candidate.fingerprint} -->")

    return "\n\n".join(parts)


def fetch_existing_boss_issues(repo: str) -> list[dict]:
    """Fetch open generated issues from GitHub, regardless of current labels."""
    issues: list[dict] = []
    for issue in _github_pages(
        f"repos/{repo}/issues?state=open",
        stage="open issues",
        page_size=_OPEN_ISSUE_PAGE_SIZE,
        max_pages=_OPEN_ISSUE_MAX_PAGES,
    ):
        number = issue.get("number")
        if (
            not _valid_count(number)
            or number == 0
            or not isinstance(issue.get("title"), str)
            or "body" not in issue
            or (issue["body"] is not None and not isinstance(issue["body"], str))
        ):
            raise _AdmissionError("open issues", "malformed issue number/title/body")
        # The REST issues endpoint also includes PRs; they are checked separately.
        if "pull_request" in issue:
            if not isinstance(issue["pull_request"], dict):
                raise _AdmissionError("open issues", "malformed pull_request marker")
            continue
        if "<!-- fingerprint:" in (issue["body"] or ""):
            issues.append(issue)
    return issues


def fetch_open_pr_files(repo: str) -> set[str]:
    """Fetch file paths changed in open PRs."""
    files: set[str] = set()
    for pr in _github_pages(
        f"repos/{repo}/pulls?state=open",
        stage="open PRs",
        page_size=_OPEN_PR_PAGE_SIZE,
        max_pages=_OPEN_PR_MAX_PAGES,
    ):
        number = pr.get("number")
        if not _valid_count(number) or number == 0:
            raise _AdmissionError("open PRs", "malformed PR number")
        stage = f"open PR #{number} files"
        for item in _github_pages(
            f"repos/{repo}/pulls/{number}/files",
            stage=stage,
            page_size=_OPEN_PR_FILES_PAGE_SIZE,
            max_pages=_OPEN_PR_FILES_MAX_PAGES,
        ):
            path = item.get("filename")
            if not isinstance(path, str) or not path.strip():
                raise _AdmissionError(stage, "malformed filename")
            files.add(path)
    return files


def _normalize_tokens(text: str) -> set[str]:
    """Normalize title into tokens for similarity comparison."""
    text = text.lower()
    # Remove common prefixes
    for prefix in [
        "add unit tests for",
        "narrow broad except exception in",
        "replace silent exception",
        "address todo/fixme",
    ]:
        text = text.replace(prefix, "")
    return {t for t in text.split() if len(t) > 2}


def is_duplicate(
    candidate: BossIssueCandidate,
    existing: list[dict],
) -> bool:
    """Check if candidate duplicates an existing issue."""
    candidate_tokens = _normalize_tokens(candidate.title)
    candidate_files = set(candidate.file_scope + candidate.new_files)

    for issue in existing:
        # Fingerprint match (exact)
        if candidate.fingerprint in (issue.get("body") or ""):
            return True

        # Title similarity (Jaccard > 0.6)
        existing_tokens = _normalize_tokens(issue.get("title", ""))
        if candidate_tokens and existing_tokens:
            intersection = candidate_tokens & existing_tokens
            union = candidate_tokens | existing_tokens
            if union and len(intersection) / len(union) > 0.6:
                return True

        # File scope overlap
        existing_body = issue.get("body", "") or ""
        for f in candidate_files:
            if f in existing_body:
                return True

    return False


def conflicts_with_pr(
    candidate: BossIssueCandidate,
    pr_files: set[str],
) -> bool:
    """Check if candidate's file scope overlaps with open PRs."""
    for f in candidate.file_scope:
        if f in pr_files:
            return True
    return False


def validate_body(body: str) -> tuple[bool, str]:
    """Validate issue body through sanitation check."""
    try:
        from aragora.swarm.boss_validation import assess_issue_body_sanitation

        ok, reason = assess_issue_body_sanitation(body)
        return ok, reason or ""
    except ImportError:
        # If boss_validation not importable, do basic checks
        if len(body.strip()) < 50:
            return False, "body_too_short"
        if "## Task" not in body:
            return False, "missing_task_section"
        return True, ""


def is_low_quality_parent(candidate: BossIssueCandidate, body: str) -> bool:
    """Return True only for generic parent issues worth decomposing.

    The bridge should operate on broad or templated parent issues, not on
    already-bounded single-file work orders produced by the scanner.
    """
    total_scope = len(candidate.file_scope) + len(candidate.new_files)
    normalized_body = " ".join(body.lower().split())

    if total_scope == 0:
        return True
    if total_scope > 2:
        return True
    if not candidate.validation_command:
        return True
    if candidate.estimated_complexity not in {"small", "medium"}:
        return True
    return any(phrase in normalized_body for phrase in _GENERIC_PARENT_PHRASES)


def _print_decomposition_telemetry(telemetry: DecompositionTelemetry) -> None:
    print(
        "  Decomposition telemetry:"
        f" seen={telemetry.parents_seen}"
        f" eligible={telemetry.parents_eligible}"
        f" preserved={telemetry.parents_preserved}"
        f" replaced={telemetry.parents_replaced}"
        f" children={telemetry.children_emitted}"
        f" rejected={telemetry.children_rejected}"
        f" sanitizer={telemetry.sanitizer_rejections}"
    )


def maybe_decompose_candidates_with_telemetry(
    candidates: list[BossIssueCandidate],
    *,
    enabled: bool,
    max_children_per_parent: int,
    repo_root: Path,
) -> tuple[list[BossIssueCandidate], DecompositionTelemetry]:
    """Optionally replace low-quality parents with bounded child candidates."""
    telemetry = DecompositionTelemetry(parents_seen=len(candidates))
    if not enabled or not candidates:
        telemetry.parents_preserved = len(candidates)
        return list(candidates), telemetry

    bridge = DecompositionBridge(repo_root)
    expanded: list[BossIssueCandidate] = []
    for candidate in candidates:
        parent_body = format_boss_ready_body(candidate)
        if not is_low_quality_parent(candidate, parent_body):
            expanded.append(candidate)
            telemetry.parents_preserved += 1
            continue

        telemetry.parents_eligible += 1
        outcome = bridge.decompose_issue_sync_with_stats(
            candidate.title,
            parent_body,
            max_children=max_children_per_parent,
        )
        telemetry.children_rejected += outcome.stats.rejected_candidates
        telemetry.sanitizer_rejections += outcome.stats.sanitizer_rejections

        if len(outcome.children) >= 2:
            expanded.extend(outcome.children)
            telemetry.parents_replaced += 1
            telemetry.children_emitted += len(outcome.children)
        else:
            expanded.append(candidate)
            telemetry.parents_preserved += 1

    return expanded, telemetry


def maybe_decompose_candidates(
    candidates: list[BossIssueCandidate],
    *,
    enabled: bool,
    max_children_per_parent: int,
    repo_root: Path,
) -> list[BossIssueCandidate]:
    expanded, _ = maybe_decompose_candidates_with_telemetry(
        candidates,
        enabled=enabled,
        max_children_per_parent=max_children_per_parent,
        repo_root=repo_root,
    )
    return expanded


def create_github_issue(
    repo: str,
    title: str,
    body: str,
    label: str,
    *,
    extra_labels: list[str] | None = None,
) -> bool:
    """Create a GitHub issue and return success.

    ``extra_labels`` lets callers pass additional labels (e.g. ``autonomous``)
    so issues meet the boss-loop dispatch contract that requires both
    ``boss-ready`` and ``autonomous`` labels (#5997 followup).
    """
    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
        "--label",
        label,
    ]
    for extra in extra_labels or []:
        extra = extra.strip()
        if extra and extra != label:
            cmd.extend(["--label", extra])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def select_with_substrate_cap(
    filtered: list[tuple[BossIssueCandidate, str]],
    max_issues: int,
    substrate_cap: float,
) -> tuple[list[tuple[BossIssueCandidate, str]], int]:
    """Trim candidates to ``max_issues``, capping the substrate-surface share.

    Order-preserving single pass: product-surface candidates are never
    skipped by the cap; substrate-surface candidates are admitted only up to
    ``int(max_issues * substrate_cap)``. Returns (selected, substrate_skipped)
    so callers can report skips instead of truncating silently.
    """
    if substrate_cap >= 1.0:
        return filtered[:max_issues], 0
    substrate_budget = int(max_issues * max(0.0, substrate_cap))
    selected: list[tuple[BossIssueCandidate, str]] = []
    substrate_taken = 0
    substrate_skipped = 0
    for item in filtered:
        if len(selected) >= max_issues:
            break
        if getattr(item[0], "surface", "substrate") == "substrate":
            if substrate_taken >= substrate_budget:
                substrate_skipped += 1
                continue
            substrate_taken += 1
        selected.append(item)
    return selected, substrate_skipped


def apply_net_closure_floor(
    max_issues: int,
    created_7d: int,
    closed_7d: int,
    floor: float,
) -> tuple[int, str]:
    """Throttle issue-creation appetite by the trailing closed:created ratio.

    Pure function (FOCUS.md Sprint 4 goal 3 / plan v2 Phase 0.3; audit basis
    215 created : 0 closed). When the trailing-window ``closed:created`` ratio
    is at or above ``floor``, the full ``max_issues`` allowance applies. Below
    the floor the allowance scales linearly with the ratio:
    ``allowed = min(max_issues, int(max_issues * ratio / floor))`` — at
    ratio == floor you get full allowance, at zero closures you get zero new
    issues. ``floor <= 0`` disables the throttle; ``created_7d == 0`` means
    there is nothing to throttle against. Returns (allowed_count, reason) —
    the reason always states the numbers so skips are reported, never silent.
    """
    if floor <= 0:
        return max_issues, (
            f"Closure floor disabled (floor={floor:g}): created_7d={created_7d} "
            f"closed_7d={closed_7d} allowed={max_issues}"
        )
    if created_7d <= 0:
        return max_issues, (
            f"Closure floor {floor:g}: nothing to throttle against "
            f"(created_7d={created_7d} closed_7d={closed_7d}) allowed={max_issues}"
        )
    ratio = closed_7d / max(1, created_7d)
    if ratio >= floor:
        return max_issues, (
            f"Closure floor {floor:g} met (ratio={ratio:.3f}): "
            f"created_7d={created_7d} closed_7d={closed_7d} allowed={max_issues}"
        )
    allowed = min(max_issues, int(max_issues * ratio / floor))
    return allowed, (
        f"Closure floor {floor:g} NOT met (ratio={ratio:.3f}): "
        f"created_7d={created_7d} closed_7d={closed_7d} -> throttled "
        f"allowed={allowed} of max_issues={max_issues}"
    )


def _search_issue_total(repo: str, qualifier: str) -> int:
    """Return a verified count, rejecting failed or incomplete searches."""
    query = f"repo:{repo} type:issue {qualifier}"
    stage = f"closure counts ({qualifier})"
    payload = _github_json(stage, "search/issues", f"q={query}", "per_page=1")
    if not isinstance(payload, dict) or not _valid_count(payload.get("total_count")):
        raise _AdmissionError(stage, "missing or invalid total_count")
    if payload.get("incomplete_results") is not False:
        raise _AdmissionError(stage, "search completeness unverified (incomplete_results)")
    return payload["total_count"]


def fetch_closure_counts_7d(repo: str) -> tuple[int, int]:
    """Fetch complete (created_7d, closed_7d) counts or block admission."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    created = _search_issue_total(repo, f"created:>={since}")
    closed = _search_issue_total(repo, f"closed:>={since}")
    return created, closed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate boss-ready GitHub issues by scanning the codebase"
    )
    parser.add_argument("--repo", default="synaptent/aragora", help="GitHub repo")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    parser.add_argument("--max-issues", type=int, default=20, help="Max issues to create")
    parser.add_argument(
        "--substrate-cap",
        type=float,
        default=0.3,
        help=(
            "Maximum fraction of created issues whose surface is loop/meta "
            "substrate (scripts/, swarm, nomic, workflows). Product-surface "
            "candidates are never skipped by this cap. 1.0 disables the cap. "
            "FOCUS.md Sprint 3 goal 2."
        ),
    )
    parser.add_argument(
        "--closure-floor",
        type=float,
        default=0.25,
        help=(
            "Minimum trailing-7d closed:created issue ratio for the full "
            "--max-issues allowance. Below the floor the allowance scales "
            "linearly with the ratio (zero closures -> zero new issues). "
            "0 disables. FOCUS.md Sprint 4 goal 3."
        ),
    )
    parser.add_argument(
        "--backpressure-signal-file",
        default=str(DEFAULT_BACKPRESSURE_SIGNAL_FILE),
        help=(
            "Read explicit admission.withhold_classes from this backpressure signal. "
            "When maintenance is withheld, substrate candidate generation is disabled. "
            "Missing or legacy files without admission are advisory-only."
        ),
    )
    parser.add_argument(
        "--created-7d",
        type=int,
        default=None,
        help="Override the trailing-7d created-issue count (skips the gh fetch; testing)",
    )
    parser.add_argument(
        "--closed-7d",
        type=int,
        default=None,
        help="Override the trailing-7d closed-issue count (skips the gh fetch; testing)",
    )
    parser.add_argument("--categories", nargs="*", help="Filter to specific categories")
    parser.add_argument("--label", default="boss-ready", help="Primary label for created issues")
    parser.add_argument(
        "--extra-labels",
        default="autonomous",
        help=(
            "Comma-separated additional labels appended to each created issue. "
            "Default 'autonomous' satisfies the boss-loop dispatch contract that "
            "requires both 'boss-ready' and 'autonomous'. Pass empty string to disable."
        ),
    )
    parser.add_argument(
        "--min-success-rate",
        type=float,
        default=0.3,
        help="Drop candidate categories below this historical success rate",
    )
    parser.add_argument(
        "--decompose-low-quality",
        action="store_true",
        help="Use the decomposition bridge to replace vague parent issues with bounded child issues",
    )
    parser.add_argument(
        "--max-children-per-parent",
        type=int,
        default=5,
        help="Maximum child issues to emit for one decomposed parent",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    repo_root = REPO_ROOT

    # 1. Scan
    print(f"Scanning {repo_root}...")
    candidates = scan_all(
        repo_root,
        categories=args.categories,
        min_success_rate=args.min_success_rate,
    )
    candidates, decomposition_telemetry = maybe_decompose_candidates_with_telemetry(
        candidates,
        enabled=args.decompose_low_quality,
        max_children_per_parent=args.max_children_per_parent,
        repo_root=repo_root,
    )
    if args.decompose_low_quality:
        _print_decomposition_telemetry(decomposition_telemetry)
    print(
        f"  Found {len(candidates)} candidates across {len(set(c.category for c in candidates))} categories"
    )

    if args.verbose:
        by_cat: dict[str, int] = {}
        for c in candidates:
            by_cat[c.category] = by_cat.get(c.category, 0) + 1
        for cat, count in sorted(by_cat.items()):
            print(f"    {cat}: {count}")

    # 2. Deduplicate against existing issues (always fetch, even in dry-run)
    print("Fetching existing boss-ready issues...")
    try:
        existing = fetch_existing_boss_issues(args.repo)
        print(f"  {len(existing)} existing issues")

        # 3. Check PR conflicts (always fetch, even in dry-run)
        print("Fetching open PR files...")
        pr_files = fetch_open_pr_files(args.repo)
    except _AdmissionError as exc:
        print(f"BLOCKED: {exc}; 0 issues created")
        return 1
    print(f"  {len(pr_files)} files in open PRs")

    # 4. Filter
    filtered: list[tuple[BossIssueCandidate, str]] = []
    skipped_dup = 0
    skipped_pr = 0
    skipped_val = 0
    skipped_priority = 0
    priority_policy = load_roadmap_priority_policy(repo_root)

    for candidate in candidates:
        if len(filtered) >= args.max_issues * 2:
            break

        if is_duplicate(candidate, existing):
            skipped_dup += 1
            if args.verbose:
                print(f"  SKIP (duplicate): {candidate.title}")
            continue

        if conflicts_with_pr(candidate, pr_files):
            skipped_pr += 1
            if args.verbose:
                print(f"  SKIP (PR conflict): {candidate.title}")
            continue

        body = format_boss_ready_body(candidate)
        if args.label == "boss-ready":
            decision = classify_proof_first_queue_issue(
                candidate.title,
                body,
                repo_root=repo_root,
                roadmap_policy=priority_policy,
            )
            if not decision.allowed:
                skipped_priority += 1
                if args.verbose:
                    detail = (
                        ", ".join(decision.blocked_codes or decision.roadmap_codes) or decision.lane
                    )
                    print(f"  SKIP (canonical priority): {candidate.title} [{detail}]")
                continue
        ok, reason = validate_body(body)
        if not ok:
            skipped_val += 1
            if args.verbose:
                print(f"  SKIP (validation: {reason}): {candidate.title}")
            continue

        filtered.append((candidate, body))

    print(f"\nFiltered to {len(filtered)} valid candidates")
    print(
        "  Skipped: "
        f"{skipped_dup} duplicates, "
        f"{skipped_pr} PR conflicts, "
        f"{skipped_priority} canonical priority blocks, "
        f"{skipped_val} validation failures"
    )

    # 5. Trim to max, capping the substrate-surface share (Sprint 3 goal 2)
    effective_substrate_cap = args.substrate_cap
    withheld_classes = read_backpressure_withheld_classes(args.backpressure_signal_file)
    if CLASS_MAINTENANCE in withheld_classes:
        effective_substrate_cap = 0.0
        print("  Backpressure admission withheld maintenance: substrate candidate cap forced to 0%")
    to_create, substrate_skipped = select_with_substrate_cap(
        filtered, args.max_issues, effective_substrate_cap
    )
    if substrate_skipped:
        print(
            f"  Substrate cap {effective_substrate_cap:.0%}: skipped "
            f"{substrate_skipped} substrate-surface candidates "
            f"(substrate_skipped={substrate_skipped})"
        )

    # 5b. Net-closure floor (Sprint 4 goal 3): throttle total appetite when
    # the trailing-7d closed:created ratio falls below the floor.
    created_7d = args.created_7d
    closed_7d = args.closed_7d
    try:
        if args.closure_floor > 0:
            if created_7d is None or closed_7d is None:
                counts = fetch_closure_counts_7d(args.repo)
                if counts is None:
                    raise _AdmissionError("closure counts", "7d issue counts unavailable")
                if created_7d is None:
                    created_7d = counts[0]
                if closed_7d is None:
                    closed_7d = counts[1]
            if not _valid_count(created_7d) or not _valid_count(closed_7d):
                raise _AdmissionError("closure counts", "counts must be non-negative integers")
    except _AdmissionError as exc:
        print(f"BLOCKED: {exc}; 0 issues created")
        return 1
    allowed, closure_reason = apply_net_closure_floor(
        args.max_issues, created_7d or 0, closed_7d or 0, args.closure_floor
    )
    print(f"  {closure_reason}")
    if allowed < len(to_create):
        # Re-apply the substrate cap at the throttled budget so the
        # cap's composition is preserved while the total shrinks.
        to_create, _ = select_with_substrate_cap(to_create, allowed, effective_substrate_cap)

    # 6. Create or dry-run
    if args.dry_run:
        print(f"\n{'=' * 60}")
        print(f"DRY RUN — would create {len(to_create)} issues:")
        print(f"{'=' * 60}")
        for i, (candidate, body) in enumerate(to_create, 1):
            print(f"\n--- Issue {i}/{len(to_create)} ---")
            print(f"TITLE: {candidate.title}")
            print(f"CATEGORY: {candidate.category}")
            print(f"SUCCESS RATE: {candidate.expected_success_rate:.0%}")
            print(f"FILES: {', '.join(candidate.file_scope + candidate.new_files)}")
            print(f"FINGERPRINT: {candidate.fingerprint}")
            if args.verbose:
                print(f"\nBODY:\n{body}")
    else:
        created = 0
        failed = 0
        for i, (candidate, body) in enumerate(to_create, 1):
            print(f"  [{i}/{len(to_create)}] Creating: {candidate.title}...", end=" ")
            extra_labels = [
                label.strip() for label in (args.extra_labels or "").split(",") if label.strip()
            ]
            if create_github_issue(
                args.repo,
                candidate.title,
                body,
                args.label,
                extra_labels=extra_labels,
            ):
                print("OK")
                created += 1
            else:
                print("FAILED")
                failed += 1
            time.sleep(1)  # Rate limit safety

        print(f"\nDone: {created} created, {failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
