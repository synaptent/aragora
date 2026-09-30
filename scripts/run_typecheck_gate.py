#!/usr/bin/env python3
"""Plan the phase-1 typecheck gate for changed Aragora Python files."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

PlanMode = Literal["skip", "changed", "full"]

FORCE_FULL_EXACT_PATHS = {
    "pyproject.toml",
    ".github/workflows/lint.yml",
    "scripts/run_typecheck_gate.py",
    "scripts/test_tiers.sh",
    "scripts/ci/mypy_with_baseline.py",
    "scripts/ci/check_tool_baseline.py",
    "scripts/ci/tool_baseline_parsers.py",
    "scripts/baselines/root-mypy-full.json",
}
FORCE_FULL_PREFIXES = (".github/actions/pr-scope-classifier/",)


class ChangedFilesError(RuntimeError):
    """Raised when changed files cannot be computed truthfully from git refs."""


def _git_stdout(*, repo_root: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _is_no_merge_base_failure(details: str) -> bool:
    lowered = details.lower()
    return "no merge base" in lowered or "no merge-base" in lowered


def _run_git_fetch(*, repo_root: Path, args: list[str]) -> bool:
    proc = subprocess.run(
        ["git", "fetch", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _history_recovery_fetches(*, base: str) -> list[list[str]]:
    base_branch = base.removeprefix("origin/")
    fetches = [["--no-tags", "--deepen=128", "origin", base_branch]]
    head_branch = os.environ.get("GITHUB_HEAD_REF")
    if head_branch:
        fetches.append(["--no-tags", "--deepen=128", "origin", head_branch])
    fetches.append(["--no-tags", "--deepen=512", "origin", base_branch])
    if head_branch:
        fetches.append(["--no-tags", "--deepen=512", "origin", head_branch])
    return fetches


def _diff_changed_files(*, repo_root: Path, diff_spec: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", diff_spec],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _recover_changed_files_from_shallow_history(
    *, repo_root: Path, base: str, diff_spec: str
) -> list[str] | None:
    if os.environ.get("GITHUB_EVENT_NAME") not in {"pull_request", "pull_request_target"}:
        return None
    for fetch_args in _history_recovery_fetches(base=base):
        if not _run_git_fetch(repo_root=repo_root, args=fetch_args):
            continue
        try:
            return _diff_changed_files(repo_root=repo_root, diff_spec=diff_spec)
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "").strip()
            if exc.returncode != 128 or not _is_no_merge_base_failure(details):
                raise
    return None


def _diff_head_for_changed_files(*, repo_root: Path, base: str, head_ref: str) -> str:
    if os.environ.get("GITHUB_EVENT_NAME") not in {"pull_request", "pull_request_target"}:
        return head_ref
    try:
        base_tip = _git_stdout(repo_root=repo_root, args=["rev-parse", base])
        first_parent = _git_stdout(repo_root=repo_root, args=["rev-parse", f"{head_ref}^1"])
        second_parent = _git_stdout(repo_root=repo_root, args=["rev-parse", f"{head_ref}^2"])
    except subprocess.CalledProcessError:
        return head_ref
    if first_parent and second_parent and first_parent != base_tip:
        return second_parent
    return head_ref


@dataclass(frozen=True)
class TypecheckPlan:
    mode: PlanMode
    targets: list[str]
    changed_files: list[str]
    reasons: list[str]

    @property
    def summary(self) -> str:
        if self.mode == "changed":
            return f"Run mypy on {len(self.targets)} touched aragora Python file(s)."
        if self.mode == "full":
            return "Run the full typecheck tier due to config or structural changes."
        return "Skip typecheck: no touched aragora Python files require the phase-1 gate."


def _normalize_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        value = raw.strip().replace("\\", "/")
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _is_requirement_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("requirements") and name.endswith(".txt")


def _forces_full_typecheck(path: str) -> bool:
    if path in FORCE_FULL_EXACT_PATHS or _is_requirement_file(path):
        return True
    return any(path.startswith(prefix) for prefix in FORCE_FULL_PREFIXES)


def _is_aragora_python_target(path: str) -> bool:
    return path.startswith("aragora/") and path.endswith(".py")


def build_typecheck_plan(*, repo_root: Path, changed_files: list[str]) -> TypecheckPlan:
    normalized = _normalize_paths(changed_files)
    reasons: list[str] = []

    force_full_paths = [path for path in normalized if _forces_full_typecheck(path)]
    if force_full_paths:
        reasons.extend(f"force_full:{path}" for path in force_full_paths)
        return TypecheckPlan(
            mode="full",
            targets=[],
            changed_files=normalized,
            reasons=reasons,
        )

    deleted_targets = [
        path
        for path in normalized
        if _is_aragora_python_target(path) and not (repo_root / path).exists()
    ]
    if deleted_targets:
        reasons.extend(f"deleted_target:{path}" for path in deleted_targets)
        return TypecheckPlan(
            mode="full",
            targets=[],
            changed_files=normalized,
            reasons=reasons,
        )

    targets = [
        path
        for path in normalized
        if _is_aragora_python_target(path) and (repo_root / path).exists()
    ]
    if targets:
        reasons.extend(f"target:{path}" for path in targets)
        return TypecheckPlan(
            mode="changed",
            targets=targets,
            changed_files=normalized,
            reasons=reasons,
        )

    reasons.append("no_aragora_python_targets")
    return TypecheckPlan(
        mode="skip",
        targets=[],
        changed_files=normalized,
        reasons=reasons,
    )


def get_changed_files(*, repo_root: Path, base_ref: str, head_ref: str = "HEAD") -> list[str]:
    base = base_ref if base_ref.startswith("origin/") else f"origin/{base_ref}"
    diff_head = _diff_head_for_changed_files(repo_root=repo_root, base=base, head_ref=head_ref)
    diff_spec = f"{base}...{diff_head}"
    try:
        return _diff_changed_files(repo_root=repo_root, diff_spec=diff_spec)
    except subprocess.CalledProcessError as exc:
        if exc.returncode != 128:
            raise
        details = (exc.stderr or exc.stdout or "").strip()
        if _is_no_merge_base_failure(details):
            recovered = _recover_changed_files_from_shallow_history(
                repo_root=repo_root,
                base=base,
                diff_spec=diff_spec,
            )
            if recovered is not None:
                return recovered
        message = (
            f"Unable to compute changed files with merge-base diff {diff_spec}. "
            f"Refusing to fall back to {base}..{head_ref} because stale or shallow "
            "PR merge refs can include unrelated mainline files in the phase-1 "
            "typecheck gate. A bounded history-deepening retry did not recover a "
            "truthful merge base. Regenerate the PR merge ref, fetch sufficient "
            "history, or pass explicit changed files with --files from the PR API "
            "or workflow changed-file output."
        )
        if details:
            message = f"{message} Git reported: {details}"
        raise ChangedFilesError(message) from exc


def write_github_outputs(*, plan: TypecheckPlan, output_path: Path) -> None:
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(f"mode={plan.mode}\n")
        handle.write(f"target_count={len(plan.targets)}\n")
        handle.write(f"summary={plan.summary}\n")
        handle.write("reasons<<EOF\n")
        handle.write("\n".join(plan.reasons))
        handle.write("\nEOF\n")


def write_targets_file(*, plan: TypecheckPlan, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(plan.targets)
    output_path.write_text(f"{payload}\n" if payload else "", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan the truthful phase-1 typecheck gate for changed Aragora Python files.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current working directory).",
    )
    parser.add_argument(
        "--base-ref",
        help="Base git ref for diff planning (example: main). Required unless --files is supplied.",
    )
    parser.add_argument(
        "--head-ref",
        default="HEAD",
        help="Head git ref for diff planning (default: HEAD).",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        help="Explicit changed files to classify instead of querying git.",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional GitHub Actions output file to append plan metadata to.",
    )
    parser.add_argument(
        "--targets-file",
        type=Path,
        help="Optional file path for newline-delimited mypy targets.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the computed plan as JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()

    if args.files is not None:
        changed_files = list(args.files)
    else:
        if not args.base_ref:
            raise SystemExit("--base-ref is required unless --files is provided.")
        try:
            changed_files = get_changed_files(
                repo_root=repo_root,
                base_ref=args.base_ref,
                head_ref=args.head_ref,
            )
        except ChangedFilesError as exc:
            raise SystemExit(str(exc)) from exc

    plan = build_typecheck_plan(repo_root=repo_root, changed_files=changed_files)

    if args.github_output is not None:
        write_github_outputs(plan=plan, output_path=args.github_output)
    if args.targets_file is not None:
        write_targets_file(plan=plan, output_path=args.targets_file)

    if args.json:
        print(json.dumps(asdict(plan), indent=2, sort_keys=True))
    else:
        print(plan.summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
