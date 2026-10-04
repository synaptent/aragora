#!/usr/bin/env python3
"""Serialize concurrent PRs that touch a Tier-4 merge-authority surface.

Problem this solves
--------------------
When many open PRs edit the same Tier-4 file (``scripts/settle_tier4_pr.py``
is the worst offender), every one of them must run the full human-settlement
dance *and* re-conflicts the others on merge. The fleet ends up generating the
very settlement toil the gate exists to prevent — a six-way pile-up where each
landing forces a rebase of all the rest.

The merge-train fixes the *class*: it treats each Tier-4 contention surface as
a single-lane track. At most ``cap`` open PRs (default 1) may touch a given
surface at once; the rest are *queued* in a deterministic order behind the
head-of-train. A pre-open check (``--check``) refuses to add an (N+1)th PR to a
full lane, and ``--status`` shows the current train per surface so the operator
can land them head-first, rebasing each on the prior.

Design
------
The core (``evaluate_merge_train`` / ``build_train`` / ``serialized_paths_for``)
is pure: it takes an explicit list of open PRs and a candidate's changed files
and returns a decision. All GitHub I/O lives at the edges (``fetch_open_prs``)
and is App-token-routed via ``scripts/gh_app_env.py`` so the check never burns
the operator PAT's GraphQL budget. This keeps the module import-clean (stdlib
only) and unit-testable without a live ``gh``.

The serialized-surface list mirrors ``review_queue.TIER_4_PREFIXES`` — the
canonical Tier-4 classifier. It is vendored here (not imported) to keep this
module dependency-light; ``tests/scripts/test_tier4_merge_train.py`` carries a
drift guard that fails if the two ever diverge.

Usage
-----
    # Would opening this PR overflow a Tier-4 lane?
    python3 scripts/tier4_merge_train.py --check --changed-files scripts/settle_tier4_pr.py
    python3 scripts/tier4_merge_train.py --check --base origin/main --head HEAD --repo synaptent/aragora

    # Show the current train (which PR is head, which are queued) per surface.
    python3 scripts/tier4_merge_train.py --status --repo synaptent/aragora --json

Exit codes: 0 = allowed (lane has room), 2 = queued (lane full), 1 = usage/error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "synaptent/aragora"
DEFAULT_CAP = 1
GH_TIMEOUT_SECONDS = 30

# Mirror of ``aragora.cli.commands.review_queue.TIER_4_PREFIXES`` — the canonical
# Tier-4 (human-preapproval / merge-authority) classifier. Vendored to keep this
# module stdlib-only; the drift guard in the focused test fails if it diverges.
CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION = 1
CONTRACT_DRIFT_AUTHORITY_TIER = 4
CONTRACT_DRIFT_AUTHORITY_CANONICAL_SOURCE = (
    "aragora.cli.commands.review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES"
)
CONTRACT_DRIFT_AUTHORITY_PREFIXES: tuple[str, ...] = (
    "scripts/check_contract_drift_ratchet.py",
    "scripts/generate_contract_drift_inventory.py",
    "scripts/baselines/contract_drift_inventory.json",
    "scripts/sdk_path_normalize.py",
    "scripts/baselines/internal_route_prefixes.json",
    "scripts/baselines/contract_drift_program.json",
    "scripts/check_sdk_parity.py",
    "scripts/validate_openapi_routes.py",
)
SERIALIZED_TIER4_PREFIXES: tuple[str, ...] = (
    ".github/workflows/",
    "deploy/",
    "docker/",
    "k8s/",
    *CONTRACT_DRIFT_AUTHORITY_PREFIXES,
    "aragora/cli/commands/review_queue.py",
    "aragora/cli/parser.py",
    "aragora/swarm/quorum_evidence.py",
    "scripts/settle_tier4_pr.py",
    "scripts/settle_one_pr.py",
    "scripts/merge_codex_automation_prs.py",
)

ALLOW = "allow"
QUEUE = "queue"


def matches_serialized_path(path: str) -> str | None:
    """Return the serialized Tier-4 prefix ``path`` falls under, or ``None``.

    A directory prefix (``.github/workflows/``) matches any file beneath it; an
    exact file entry matches only that file.
    """
    candidate = str(path or "").strip()
    if not candidate:
        return None
    for prefix in SERIALIZED_TIER4_PREFIXES:
        if prefix.endswith("/"):
            if candidate.startswith(prefix):
                return prefix
        elif candidate == prefix:
            return prefix
    return None


def serialized_paths_for(files: Iterable[str]) -> set[str]:
    """The set of serialized Tier-4 surfaces touched by ``files``."""
    touched: set[str] = set()
    for path in files:
        prefix = matches_serialized_path(path)
        if prefix is not None:
            touched.add(prefix)
    return touched


def _pr_sort_key(pr: dict[str, Any]) -> tuple[str, int]:
    """Deterministic train order: oldest PR first, ties broken by number.

    ``createdAt`` is an ISO-8601 string which sorts lexicographically; a missing
    value sorts first (treated as oldest) so it still yields a stable order.
    """
    created = str(pr.get("createdAt") or pr.get("created_at") or "")
    raw_number = pr.get("number")
    try:
        number = int(raw_number) if raw_number is not None else 0
    except (TypeError, ValueError):
        number = 0
    return (created, number)


def _pr_number(pr: dict[str, Any]) -> int | None:
    raw_number = pr.get("number")
    if raw_number is None:
        return None
    try:
        return int(raw_number)
    except (TypeError, ValueError):
        return None


def _pr_files(pr: dict[str, Any]) -> list[str]:
    raw = pr.get("files")
    files: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                name = entry.get("path") or entry.get("filename")
                if name:
                    files.append(str(name))
            elif isinstance(entry, str):
                files.append(entry)
    return files


def build_train(
    open_prs: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Per serialized surface, the ordered list of open PRs occupying it.

    The first element of each list is the head-of-train (should land next); the
    rest are queued behind it.
    """
    lanes: dict[str, list[dict[str, Any]]] = {}
    for pr in sorted(open_prs, key=_pr_sort_key):
        for prefix in serialized_paths_for(_pr_files(pr)):
            lanes.setdefault(prefix, []).append(
                {
                    "number": _pr_number(pr),
                    "title": str(pr.get("title") or "").strip(),
                    "createdAt": str(pr.get("createdAt") or pr.get("created_at") or ""),
                }
            )
    return lanes


def evaluate_merge_train(
    candidate_files: Iterable[str],
    open_prs: Sequence[dict[str, Any]],
    *,
    cap: int = DEFAULT_CAP,
    candidate_pr: int | None = None,
) -> dict[str, Any]:
    """Decide whether a candidate PR may occupy the Tier-4 lanes it touches.

    ``cap`` is the max number of *other* open PRs allowed on a surface before a
    new one must queue. The candidate itself is excluded from the count (so
    re-evaluating an already-open PR does not block on itself).
    """
    cap = max(1, int(cap))
    candidate_surfaces = sorted(serialized_paths_for(candidate_files))
    train = build_train(open_prs)

    contended: dict[str, Any] = {}
    blocking: set[int] = set()
    for prefix in candidate_surfaces:
        occupants = [
            entry
            for entry in train.get(prefix, [])
            if entry["number"] is not None and entry["number"] != candidate_pr
        ]
        lane_full = len(occupants) >= cap
        if lane_full:
            for entry in occupants:
                blocking.add(int(entry["number"]))
        contended[prefix] = {
            "open_pr_numbers": [entry["number"] for entry in occupants],
            "head_pr": occupants[0]["number"] if occupants else None,
            "lane_full": lane_full,
        }

    decision = QUEUE if blocking else ALLOW
    if not candidate_surfaces:
        reason = "candidate touches no serialized Tier-4 surface"
    elif decision == ALLOW:
        reason = "all touched Tier-4 lanes have room within cap"
    else:
        joined = ", ".join(str(n) for n in sorted(blocking))
        reason = (
            f"Tier-4 lane already occupied by open PR(s) {joined}; queue behind the "
            "head-of-train and rebase on it once it lands"
        )

    return {
        "decision": decision,
        "ok": decision == ALLOW,
        "cap": cap,
        "candidate_pr": candidate_pr,
        "candidate_surfaces": candidate_surfaces,
        "contended_surfaces": contended,
        "blocking_prs": sorted(blocking),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# GitHub I/O shell (App-token-routed, injectable for tests)
# ---------------------------------------------------------------------------


def _app_token_env() -> dict[str, str]:
    """Best-effort App-installation token env for read-only gh calls.

    Mirrors the shell wrappers: mint via ``scripts/gh_app_env.py --print-token``
    so the lane check never spends the operator PAT's GraphQL budget. Returns an
    empty dict (degrade to ambient gh auth) when the App config is absent.
    """
    try:
        result = subprocess.run(  # noqa: S603 - controlled gh_app_env invocation
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "gh_app_env.py"),
                "--print-token",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    token = (result.stdout or "").strip()
    if not token:
        return {}
    return {
        "GH_TOKEN": token,
        "GITHUB_TOKEN": token,
        "ARAGORA_GITHUB_AUTH_SOURCE": "github_app_installation",
    }


def fetch_open_prs(repo: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """List open PRs with their changed files via App-token-routed ``gh``."""
    import os

    env = {**os.environ, **_app_token_env()}
    result = subprocess.run(  # noqa: S603 - controlled gh invocation
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,createdAt,files",
        ],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {(result.stderr or '').strip()}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse gh pr list output: {exc}") from None
    return payload if isinstance(payload, list) else []


def _changed_files_from_git(base: str, head: str) -> list[str]:
    result = subprocess.run(  # noqa: S603 - controlled git invocation
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {(result.stderr or '').strip()}")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _load_open_prs_arg(value: str) -> list[dict[str, Any]]:
    text = sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8")
    payload = json.loads(text or "[]")
    return payload if isinstance(payload, list) else []


def _split_csv(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def _resolve_candidate_files(args: argparse.Namespace) -> list[str]:
    if args.changed_files:
        return _split_csv(args.changed_files)
    return _changed_files_from_git(args.base, args.head)


def _resolve_open_prs(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.open_prs_json:
        return _load_open_prs_arg(args.open_prs_json)
    return fetch_open_prs(args.repo)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="evaluate whether a candidate may occupy its lanes"
    )
    parser.add_argument(
        "--status", action="store_true", help="print the current train per serialized surface"
    )
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument(
        "--cap", type=int, default=DEFAULT_CAP, help="max concurrent open PRs per surface"
    )
    parser.add_argument(
        "--candidate-pr", type=int, default=None, help="exclude this PR from the lane count"
    )
    parser.add_argument(
        "--changed-files",
        action="append",
        default=[],
        help="comma-separated candidate paths; repeatable. Omit to diff --base..--head.",
    )
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--open-prs-json",
        default=None,
        help="path to a JSON list of open PRs (or '-' for stdin); omit to fetch live",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None, *, fetcher: Callable[..., Any] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.status == args.check:  # both or neither
        print("error: pass exactly one of --check or --status", file=sys.stderr)
        return 1

    try:
        open_prs = _resolve_open_prs(args)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: could not resolve open PRs: {exc}", file=sys.stderr)
        return 1

    if args.status:
        train = build_train(open_prs)
        if args.json:
            _emit({"cap": max(1, args.cap), "train": train}, as_json=True)
        else:
            if not train:
                print("merge-train: no open PR occupies any serialized Tier-4 surface")
            for prefix, lane in sorted(train.items()):
                print(f"merge-train: {prefix} (cap={max(1, args.cap)})")
                for position, entry in enumerate(lane):
                    marker = "HEAD" if position == 0 else f"queued #{position}"
                    print(f"  [{marker}] PR #{entry['number']} {entry['title']}")
        return 0

    try:
        candidate_files = _resolve_candidate_files(args)
    except (RuntimeError, OSError) as exc:
        print(f"error: could not resolve candidate files: {exc}", file=sys.stderr)
        return 1

    result = evaluate_merge_train(
        candidate_files,
        open_prs,
        cap=args.cap,
        candidate_pr=args.candidate_pr,
    )
    if args.json:
        _emit(result, as_json=True)
    elif result["decision"] == ALLOW:
        print(f"merge-train: allow — {result['reason']}")
    else:
        print(f"merge-train: queue — {result['reason']}", file=sys.stderr)
        for prefix in result["candidate_surfaces"]:
            lane = result["contended_surfaces"].get(prefix, {})
            if lane.get("lane_full"):
                print(f"  {prefix}: head-of-train PR #{lane.get('head_pr')}", file=sys.stderr)
    return 0 if result["ok"] else 2


CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES: tuple[str, ...] = (
    ".github/actions/pr-scope-classifier/action.yml",
    ".github/actions/setup-python-safe/action.yml",
    "aragora/__init__.py",
    "aragora/__main__.py",
    "aragora/__version__.py",
    "aragora/cli/__init__.py",
    "aragora/cli/_mission_parser.py",
    "aragora/cli/api_keys.py",
    "aragora/cli/commands/__init__.py",
    "aragora/cli/commands/review_queue_comment_verdicts.py",
    "aragora/cli/commands/review_queue_parsers.py",
    "aragora/cli/commands/review_queue_render.py",
    "aragora/cli/commands/review_queue_rest_fallback.py",
    "aragora/cli/commands/review_queue_transport.py",
    "aragora/cli/commands/review_queue_unstable.py",
    "aragora/cli/doctor.py",
    "aragora/cli/main.py",
    "aragora/compliance/__init__.py",
    "aragora/compliance/artifact_generator.py",
    "aragora/compliance/data_classification.py",
    "aragora/compliance/eu_ai_act.py",
    "aragora/compliance/framework.py",
    "aragora/compliance/monitor.py",
    "aragora/compliance/phi_detectors.py",
    "aragora/config/__init__.py",
    "aragora/config/distributed.py",
    "aragora/config/env_helpers.py",
    "aragora/config/feature_flags.py",
    "aragora/config/provider_readiness.py",
    "aragora/config/secrets.py",
    "aragora/config/settings.py",
    "aragora/config/stability.py",
    "aragora/config/timeouts.py",
    "aragora/config/validator.py",
    "aragora/connectors/__init__.py",
    "aragora/connectors/exceptions.py",
    "aragora/exceptions.py",
    "aragora/modes/__init__.py",
    "aragora/modes/base.py",
    "aragora/modes/builtin/__init__.py",
    "aragora/modes/builtin/architect.py",
    "aragora/modes/builtin/coder.py",
    "aragora/modes/builtin/debugger.py",
    "aragora/modes/builtin/epistemic_hygiene.py",
    "aragora/modes/builtin/orchestrator.py",
    "aragora/modes/builtin/reviewer.py",
    "aragora/modes/custom.py",
    "aragora/modes/handoff.py",
    "aragora/modes/tool_groups.py",
    "aragora/server/__init__.py",
    "aragora/server/startup/__init__.py",
    "aragora/server/startup/background.py",
    "aragora/server/startup/billing.py",
    "aragora/server/startup/control_plane.py",
    "aragora/server/startup/database.py",
    "aragora/server/startup/dr_drilling.py",
    "aragora/server/startup/event_subscribers.py",
    "aragora/server/startup/health_check.py",
    "aragora/server/startup/knowledge_mound.py",
    "aragora/server/startup/observability.py",
    "aragora/server/startup/parallel.py",
    "aragora/server/startup/redis.py",
    "aragora/server/startup/security.py",
    "aragora/server/startup/validation.py",
    "aragora/server/startup/validation_runner.py",
    "aragora/server/startup/workers.py",
    "aragora/swarm/__init__.py",
    "aragora/swarm/github_app_auth.py",
    "aragora/swarm/merge_quorum_io.py",
    "aragora/swarm/merge_quorum_reconcile.py",
    "scripts/__init__.py",
    "scripts/add_openapi_descriptions.py",
    "scripts/add_openapi_operation_ids.py",
    "scripts/add_openapi_param_descriptions.py",
    "scripts/audit_openapi_docs.py",
    "scripts/audit_test_skips.py",
    "scripts/build_contract_drift_historical_backfill.py",
    "scripts/capability_gap_report.py",
    "scripts/check_capability_matrix_sync.py",
    "scripts/check_cross_sdk_parity.py",
    "scripts/check_pentest_findings.py",
    "scripts/check_portability.py",
    "scripts/check_sdk_namespace_parity.py",
    "scripts/check_test_dependencies.py",
    "scripts/check_version_alignment.py",
    "scripts/ci_install_project.sh",
    "scripts/classification_scan.py",
    "scripts/contract_drift_report.py",
    "scripts/export_openapi.py",
    "scripts/generate_api_docs.py",
    "scripts/generate_capability_matrix.py",
    "scripts/generate_contract_drift_backlog.py",
    "scripts/generate_contract_drift_issue_plan.py",
    "scripts/generate_openapi.py",
    "scripts/generate_python_sdk_types.py",
    "scripts/generate_sdk_types.py",
    "scripts/gh_app_env.py",
    "scripts/guard_repo_clean.py",
    "scripts/openapi_release_envelope.py",
    "scripts/pre_release_check.py",
    "scripts/reconcile_status_docs.py",
    "scripts/run_pip_audit_gate.py",
    "scripts/smoke_test.py",
    "scripts/tier4_merge_train.py",
    "scripts/verify_sdk_contracts.py",
)
_AUTHORITY_DEPENDENCY_INSERTION_INDEX = SERIALIZED_TIER4_PREFIXES.index(
    "aragora/cli/commands/review_queue.py"
)
SERIALIZED_TIER4_PREFIXES = (
    SERIALIZED_TIER4_PREFIXES[:_AUTHORITY_DEPENDENCY_INSERTION_INDEX]
    + CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    + SERIALIZED_TIER4_PREFIXES[_AUTHORITY_DEPENDENCY_INSERTION_INDEX:]
)


if __name__ == "__main__":
    raise SystemExit(main())
