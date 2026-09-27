#!/usr/bin/env python3
"""Guard required-check-priority keep-lists against drift."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Violation:
    path: str
    message: str


@dataclass(frozen=True)
class _YamlMappingLine:
    indent: int
    key: str
    value: str


@dataclass(frozen=True)
class _MainPushTrigger:
    targets_main: bool
    path_filtered: bool


WORKFLOW_PATH = Path(".github/workflows/required-check-priority.yml")

UNSTABLE_MODULE_PATH = Path("aragora/cli/commands/review_queue_unstable.py")

# Named `run:` steps allowed to execute BEFORE the first allowlisted verifier
# step in a job covered by the UNSTABLE cancellation exception. The receipt
# treats pre-verifier steps as setup that may already have run, so any new
# substantive pre-verifier step must be reviewed here before it can hide
# behind a cancelled advisory run.
UNSTABLE_SETUP_RUN_STEPS = {
    "Verify checkout integrity",
    "Install Python dependencies",
    "Install dependencies",
    "Runner fingerprint",
    "Install TypeScript SDK dependencies",
}

# The receipt exempts GitHub-injected wrap-up steps (post-hooks/teardown) from
# its skipped-tail rule, so authored steps must never reuse those names.
_INJECTED_WRAPUP_NAME_RE = re.compile(r"^(Post |Stop containers|Complete job$|Set up job$)")

REQUIRED_KEEP_WORKFLOW_PATHS = {
    ".github/workflows/aragora-merge-quorum.yml",
    ".github/workflows/aragora-review-gate.yml",
    ".github/workflows/autopilot-worktree-e2e.yml",
    ".github/workflows/core-suites.yml",
    ".github/workflows/lint.yml",
    ".github/workflows/sdk-parity.yml",
    ".github/workflows/sdk-generate.yml",
    ".github/workflows/sdk-test.yml",
    ".github/workflows/test.yml",
    ".github/workflows/openapi.yml",
    ".github/workflows/pr-admission-controller.yml",
    ".github/workflows/quality-smoke.yml",
    ".github/workflows/required-check-priority.yml",
    ".github/workflows/release-readiness.yml",
    ".github/workflows/security-gate.yml",
    ".github/workflows/self-hosted-shadow.yml",
    ".github/workflows/smoke.yml",
    ".github/workflows/smoke-offline.yml",
}

REQUIRED_KEEP_WORKFLOW_NAMES = {
    "Aragora Merge Quorum",
    "Aragora Code Review",
    "Autopilot Worktree E2E",
    "Core Suites (Decision Integrity)",
    "Generate SDK Types",
    "Offline Golden Path",
    "Required Check Priority",
    "Lint",
    "PR Admission Controller",
    "Quality Pipeline Smoke",
    "Release Readiness Gate",
    "Security Gate",
    "Self-Hosted Shadow CI",
    "SDK Parity Check",
    "SDK Tests",
    "Smoke Tests",
    "Tests",
    "OpenAPI Spec",
}

REQUIRED_CONTEXT_TO_WORKFLOW_PATH = {
    "lint": ".github/workflows/lint.yml",
    "typecheck": ".github/workflows/lint.yml",
    "sdk-parity": ".github/workflows/sdk-parity.yml",
    "Generate & Validate": ".github/workflows/openapi.yml",
    "TypeScript SDK Type Check": ".github/workflows/sdk-test.yml",
}

# The cancellation sweep must only ever cancel QUEUED runs. Cancelling an
# in_progress run frees no queue capacity (the run already holds a runner)
# and leaves a red "cancelled" conclusion on advisory checks that the
# cancelled-run guardian deliberately does not rerun, forcing manual reruns
# before merge settlement. See PR run 29520862671 (2026-07-15), which
# cancelled in-flight advisory runs on PR #9346 seconds after creation.
_QUEUED_ONLY_STATUS_FILTER_RE = re.compile(
    r"if\s*\(\s*run\.status\s*!==\s*(['\"])queued\1\s*\)\s*continue;"
)

# Cancelling a workflow run on the live PR head leaves a cancelled check in
# GitHub's status rollup and can poison mergeStateStatus into UNSTABLE (#9034).
# The worker must resolve the live PR head on every sweep, reject stale event
# heads, and confirm freshness again immediately before cancellation.
_LIVE_HEAD_FETCH_RE = re.compile(
    r"github\.rest\.pulls\.get\s*\(\s*\{.*?pull_number\s*:\s*pr\.number",
    flags=re.DOTALL,
)
_PER_SWEEP_LIVE_HEAD_REFRESH_RE = re.compile(
    r"for\s*\(\s*let\s+pass\s*=.*?pass\s*<=\s*sweeps.*?\)\s*\{.*?"
    r"const\s+liveHeadSha\s*=\s*await\s+getLiveHeadSha\(\)\s*;",
    flags=re.DOTALL,
)
_STALE_EVENT_HEAD_GUARD_RE = re.compile(
    r"if\s*\(\s*!liveHeadSha\s*\|\|\s*liveHeadSha\s*!==\s*headSha\s*\)"
)
_CURRENT_HEAD_SKIP_RE = re.compile(r"if\s*\(\s*run\.head_sha\s*===\s*liveHeadSha\s*\)\s*continue;")
_PRE_CANCEL_HEAD_REFRESH_RE = re.compile(
    r"const\s+confirmedLiveHeadSha\s*=\s*await\s+getLiveHeadSha\(\)\s*;.*?"
    r"confirmedLiveHeadSha\s*!==\s*headSha.*?github\.rest\.actions\.cancelWorkflowRun",
    flags=re.DOTALL,
)
# The branch-name run listing can match an unrelated PR sharing the branch
# name (forks, common automation names); cancellation must be scoped to runs
# provably from this PR's own source repo, and to this PR when GitHub
# attributes the run to PRs at all.
_SAME_SOURCE_REPO_GUARD_RE = re.compile(
    r"if\s*\(\s*!runHeadRepo\s*\|\|\s*!prHeadRepo\s*\|\|\s*runHeadRepo\s*!==\s*prHeadRepo\s*\)\s*"
    r"continue;"
)
_PR_ATTRIBUTION_GUARD_RE = re.compile(
    r"runPrNumbers\.length\s*>\s*0\s*&&\s*!runPrNumbers\.includes\(pr\.number\)"
)


def _extract_js_set_items(workflow_text: str, set_name: str) -> list[str] | None:
    pattern = r"const\s+" + re.escape(set_name) + r"\s*=\s*new Set\(\[(?P<body>.*?)\]\);"
    match = re.search(pattern, workflow_text, flags=re.DOTALL)
    if not match:
        return None
    body = match.group("body")
    return re.findall(r"""["']([^"']+)["']""", body)


def _parse_yaml_mapping_line(line: str) -> _YamlMappingLine | None:
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    match = re.match(
        r"^(?P<indent>\s*)(?P<key>['\"]?[A-Za-z0-9_-]+['\"]?)\s*:\s*(?P<value>.*)$",
        line,
    )
    if not match:
        return None
    return _YamlMappingLine(
        indent=len(match.group("indent")),
        key=match.group("key").strip("\"'"),
        value=_strip_yaml_comment(match.group("value")).strip(),
    )


def _strip_yaml_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or value[index - 1].isspace())
        ):
            return value[:index].rstrip()
    return value.rstrip()


def _flow_curly_balance(value: str) -> int:
    balance = 0
    in_single = False
    in_double = False
    for char in value:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "{":
                balance += 1
            elif char == "}":
                balance -= 1
    return balance


def _complete_flow_mapping_value(
    value: str,
    lines: list[str],
    index: int,
) -> str:
    if not value.strip().startswith("{"):
        return value

    parts = [value]
    balance = _flow_curly_balance(value)
    for child in lines[index + 1 :]:
        if balance <= 0:
            break
        child_value = _strip_yaml_comment(child.strip())
        if not child_value:
            continue
        parts.append(child_value)
        balance += _flow_curly_balance(child_value)
    return " ".join(parts)


def _nested_yaml_block(lines: list[str], index: int, parent_indent: int) -> list[str]:
    block: list[str] = []
    for line in lines[index + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            block.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= parent_indent:
            break
        block.append(line)
    return block


def _inline_yaml_value_mentions(value: str, expected: str) -> bool:
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_./-]){re.escape(expected)}(?![A-Za-z0-9_./-])",
            value,
        )
    )


def _flow_mapping_value(value: str, key: str) -> str | None:
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None

    for item in _split_flow_items(stripped[1:-1]):
        colon_index = _top_level_colon_index(item)
        if colon_index is None:
            continue
        item_key = item[:colon_index].strip().strip("\"'")
        if item_key == key:
            return item[colon_index + 1 :].strip()
    return None


def _split_flow_items(value: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth_curly = 0
    depth_square = 0
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "{":
                depth_curly += 1
            elif char == "}":
                depth_curly = max(depth_curly - 1, 0)
            elif char == "[":
                depth_square += 1
            elif char == "]":
                depth_square = max(depth_square - 1, 0)
            elif char == "," and depth_curly == 0 and depth_square == 0:
                items.append(value[start:index].strip())
                start = index + 1
    trailing = value[start:].strip()
    if trailing:
        items.append(trailing)
    return items


def _top_level_colon_index(value: str) -> int | None:
    depth_curly = 0
    depth_square = 0
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "{":
                depth_curly += 1
            elif char == "}":
                depth_curly = max(depth_curly - 1, 0)
            elif char == "[":
                depth_square += 1
            elif char == "]":
                depth_square = max(depth_square - 1, 0)
            elif char == ":" and depth_curly == 0 and depth_square == 0:
                return index
    return None


def _flow_push_targets_main(value: str) -> bool:
    branches = _flow_mapping_value(value, "branches")
    if branches is not None:
        return _inline_yaml_value_mentions(branches, "main")

    branches_ignore = _flow_mapping_value(value, "branches-ignore")
    if branches_ignore is not None and _inline_yaml_value_mentions(
        branches_ignore,
        "main",
    ):
        return False

    return True


def _flow_push_has_path_filter(value: str) -> bool:
    return (
        _flow_mapping_value(value, "paths") is not None
        or _flow_mapping_value(
            value,
            "paths-ignore",
        )
        is not None
    )


def _block_value_for_key(lines: list[str], key: str) -> list[str] | None:
    for index, line in enumerate(lines):
        parsed = _parse_yaml_mapping_line(line)
        if parsed is None or parsed.key != key:
            continue

        values = [parsed.value]
        for child in lines[index + 1 :]:
            child_parsed = _parse_yaml_mapping_line(child)
            if child_parsed is not None and child_parsed.indent <= parsed.indent:
                break
            child_value = _strip_yaml_comment(child.strip())
            if child_value:
                values.append(child_value)
        return values
    return None


def _push_block_targets_main(push_block: list[str]) -> bool:
    branch_values = _block_value_for_key(push_block, "branches")
    if branch_values is not None:
        return _inline_yaml_value_mentions("\n".join(branch_values), "main")

    ignored_branch_values = _block_value_for_key(push_block, "branches-ignore")
    if ignored_branch_values is not None and _inline_yaml_value_mentions(
        "\n".join(ignored_branch_values),
        "main",
    ):
        return False

    return True


def _push_block_has_path_filter(push_block: list[str]) -> bool:
    for line in push_block:
        parsed = _parse_yaml_mapping_line(line)
        if parsed is not None and parsed.key in {"paths", "paths-ignore"}:
            return True
    return False


def _main_push_trigger(workflow_text: str) -> _MainPushTrigger:
    lines = workflow_text.splitlines()
    for index, line in enumerate(lines):
        parsed = _parse_yaml_mapping_line(line)
        if parsed is None or parsed.key != "on" or parsed.indent != 0:
            continue

        if parsed.value:
            on_value = _complete_flow_mapping_value(parsed.value, lines, index)
            inline_push = _flow_mapping_value(on_value, "push")
            if inline_push is None:
                if _inline_yaml_value_mentions(on_value, "push"):
                    return _MainPushTrigger(targets_main=True, path_filtered=False)
            else:
                if not _flow_push_targets_main(inline_push):
                    return _MainPushTrigger(targets_main=False, path_filtered=False)
                return _MainPushTrigger(
                    targets_main=True,
                    path_filtered=_flow_push_has_path_filter(inline_push),
                )

        on_block = _nested_yaml_block(lines, index, parsed.indent)
        for on_index, on_line in enumerate(on_block):
            on_parsed = _parse_yaml_mapping_line(on_line)
            if on_parsed is None or on_parsed.key != "push":
                continue

            if on_parsed.value:
                push_value = _complete_flow_mapping_value(
                    on_parsed.value,
                    on_block,
                    on_index,
                )
                if not _flow_push_targets_main(push_value):
                    return _MainPushTrigger(targets_main=False, path_filtered=False)
                return _MainPushTrigger(
                    targets_main=True,
                    path_filtered=_flow_push_has_path_filter(push_value),
                )

            push_block = _nested_yaml_block(on_block, on_index, on_parsed.indent)
            if not _push_block_targets_main(push_block):
                return _MainPushTrigger(targets_main=False, path_filtered=False)
            return _MainPushTrigger(
                targets_main=True,
                path_filtered=_push_block_has_path_filter(push_block),
            )

    return _MainPushTrigger(targets_main=False, path_filtered=False)


def find_required_check_priority_violations(
    workflow_text: str,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    violations: list[str] = []

    path_items = _extract_js_set_items(workflow_text, "alwaysKeepWorkflowPaths")
    if path_items is None:
        return ["missing `alwaysKeepWorkflowPaths` set definition"]

    name_items = _extract_js_set_items(workflow_text, "alwaysKeepWorkflowNames")
    if name_items is None:
        return ["missing `alwaysKeepWorkflowNames` set definition"]

    if len(path_items) != len(set(path_items)):
        violations.append("duplicate entries found in alwaysKeepWorkflowPaths")
    if len(name_items) != len(set(name_items)):
        violations.append("duplicate entries found in alwaysKeepWorkflowNames")

    path_set = set(path_items)
    missing_required_paths = sorted(REQUIRED_KEEP_WORKFLOW_PATHS - path_set)
    for path in missing_required_paths:
        violations.append(f"missing required keep workflow path: {path}")

    for context, mapped_path in sorted(REQUIRED_CONTEXT_TO_WORKFLOW_PATH.items()):
        if mapped_path not in path_set:
            violations.append(
                f"required context `{context}` maps to workflow path not in keep-list: {mapped_path}"
            )

    name_set = set(name_items)
    missing_required_names = sorted(REQUIRED_KEEP_WORKFLOW_NAMES - name_set)
    for name in missing_required_names:
        violations.append(f"missing required keep workflow name: {name}")

    if not _QUEUED_ONLY_STATUS_FILTER_RE.search(workflow_text):
        violations.append(
            "cancellation sweep is not restricted to queued runs: expected "
            "`if (run.status !== 'queued') continue;` (in_progress runs must "
            "never be cancelled)"
        )

    if not _LIVE_HEAD_FETCH_RE.search(workflow_text):
        violations.append("cancellation sweep does not resolve the live PR head with `pulls.get`")

    if not _PER_SWEEP_LIVE_HEAD_REFRESH_RE.search(workflow_text):
        violations.append(
            "cancellation sweep does not refresh the live PR head at the start of every sweep"
        )

    if not _STALE_EVENT_HEAD_GUARD_RE.search(workflow_text):
        violations.append(
            "cancellation sweep does not stop when its event head is stale: expected "
            "`if (!liveHeadSha || liveHeadSha !== headSha)`"
        )

    if not _CURRENT_HEAD_SKIP_RE.search(workflow_text):
        violations.append(
            "cancellation sweep does not skip the current PR head: expected "
            "`if (run.head_sha === liveHeadSha) continue;` (only superseded-head "
            "runs may be cancelled)"
        )

    if not _PRE_CANCEL_HEAD_REFRESH_RE.search(workflow_text):
        violations.append(
            "cancellation sweep does not refresh the live PR head immediately before cancellation"
        )

    if not _SAME_SOURCE_REPO_GUARD_RE.search(workflow_text):
        violations.append(
            "cancellation sweep does not verify the run's source repo matches this PR's "
            "head repo (branch names collide across forks/PRs)"
        )

    if not _PR_ATTRIBUTION_GUARD_RE.search(workflow_text):
        violations.append(
            "cancellation sweep does not verify PR attribution: expected "
            "`runPrNumbers.length > 0 && !runPrNumbers.includes(pr.number)`"
        )

    if repo_root is not None:
        mapped_workflows: dict[str, str] = {}
        for rel in sorted(path_set):
            wf_path = (repo_root / rel).resolve()
            if not wf_path.exists():
                violations.append(f"keep workflow path does not exist: {rel}")
        for context, rel in sorted(REQUIRED_CONTEXT_TO_WORKFLOW_PATH.items()):
            wf_path = (repo_root / rel).resolve()
            if not wf_path.exists():
                continue
            text = wf_path.read_text(encoding="utf-8")
            mapped_workflows[rel] = text
            if context not in text:
                violations.append(
                    f"required context marker `{context}` not found in mapped workflow: {rel}"
                )
        for context, rel in sorted(REQUIRED_CONTEXT_TO_WORKFLOW_PATH.items()):
            mapped_text = mapped_workflows.get(rel)
            if mapped_text is None:
                continue
            main_push = _main_push_trigger(mapped_text)
            if main_push.targets_main and main_push.path_filtered:
                violations.append(
                    f"required context `{context}` maps to path-filtered main push workflow: {rel}"
                )

    return violations


@dataclass(frozen=True)
class _WorkflowStep:
    name: str | None
    has_run: bool


def _load_unstable_receipt_policy(
    repo_root: Path,
) -> tuple[dict[tuple[str, str], tuple[str, ...]], dict[str, str]] | None:
    """Extract the UNSTABLE-receipt allowlists from the module source via ast,
    so the policy check shares a single source of truth without importing the
    aragora package."""
    module_file = repo_root / UNSTABLE_MODULE_PATH
    if not module_file.exists():
        return None
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    verifiers: dict[tuple[str, str], tuple[str, ...]] | None = None
    workflow_paths: dict[str, str] | None = None
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        if value is None:
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "UNSTABLE_CANCELLED_CONTEXT_VERIFIERS":
                verifiers = ast.literal_eval(value)
            elif target.id == "UNSTABLE_ALLOWLISTED_WORKFLOW_PATHS":
                workflow_paths = ast.literal_eval(value)
    if verifiers is None or workflow_paths is None:
        return None
    return verifiers, workflow_paths


def _workflow_job_blocks(workflow_text: str) -> dict[str, list[str]]:
    lines = workflow_text.splitlines()
    blocks: dict[str, list[str]] = {}
    for index, line in enumerate(lines):
        parsed = _parse_yaml_mapping_line(line)
        if parsed is None or parsed.key != "jobs" or parsed.indent != 0:
            continue
        jobs_block = _nested_yaml_block(lines, index, parsed.indent)
        job_indent: int | None = None
        for job_index, job_line in enumerate(jobs_block):
            job_parsed = _parse_yaml_mapping_line(job_line)
            if job_parsed is None:
                continue
            if job_indent is None:
                job_indent = job_parsed.indent
            if job_parsed.indent != job_indent:
                continue
            blocks[job_parsed.key] = _nested_yaml_block(jobs_block, job_index, job_parsed.indent)
        break
    return blocks


def _job_display_name(job_id: str, job_block: list[str]) -> str:
    field_indent: int | None = None
    for line in job_block:
        parsed = _parse_yaml_mapping_line(line)
        if parsed is None:
            continue
        if field_indent is None:
            field_indent = parsed.indent
        if parsed.indent == field_indent and parsed.key == "name" and parsed.value:
            return parsed.value.strip("\"'")
    return job_id


def _job_steps(job_block: list[str]) -> list[_WorkflowStep]:
    steps: list[_WorkflowStep] = []
    steps_indent: int | None = None
    dash_indent: int | None = None
    current_name: str | None = None
    current_has_run = False
    current_open = False

    def _close() -> None:
        nonlocal current_open, current_name, current_has_run
        if current_open:
            steps.append(_WorkflowStep(name=current_name, has_run=current_has_run))
        current_open = False
        current_name = None
        current_has_run = False

    for line in job_block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if steps_indent is None:
            parsed = _parse_yaml_mapping_line(line)
            if parsed is not None and parsed.key == "steps" and not parsed.value:
                steps_indent = parsed.indent
            continue
        if indent <= steps_indent:
            break
        if stripped.startswith("- ") or stripped == "-":
            _close()
            current_open = True
            dash_indent = indent
            stripped = stripped[1:].lstrip()
            if not stripped:
                continue
            indent = dash_indent + 2
        elif dash_indent is None or indent != dash_indent + 2:
            # Deeper lines belong to multiline values (run: | scripts, with:
            # blocks); only fields at the step's own indent are step keys.
            continue
        match = re.match(r"^(name|run|uses)\s*:\s*(.*)$", stripped)
        if not match or not current_open:
            continue
        key = match.group(1)
        value = _strip_yaml_comment(match.group(2)).strip()
        if key == "name" and current_name is None:
            current_name = value.strip("\"'")
        elif key == "run":
            current_has_run = True
    _close()
    return steps


def _unstable_receipt_violations(repo_root: Path) -> list[str]:
    policy = _load_unstable_receipt_policy(repo_root)
    if policy is None:
        return [
            f"could not extract UNSTABLE receipt allowlists from {UNSTABLE_MODULE_PATH}",
        ]
    verifiers, workflow_paths = policy
    violations: list[str] = []
    for (workflow_name, job_name), verifier_names in sorted(verifiers.items()):
        rel = workflow_paths.get(workflow_name)
        if not rel:
            violations.append(
                f"UNSTABLE allowlist workflow `{workflow_name}` has no path in "
                "UNSTABLE_ALLOWLISTED_WORKFLOW_PATHS"
            )
            continue
        wf_file = repo_root / rel
        if not wf_file.exists():
            violations.append(f"UNSTABLE allowlist workflow path does not exist: {rel}")
            continue
        job_blocks = _workflow_job_blocks(wf_file.read_text(encoding="utf-8"))
        job_block: list[str] | None = None
        for job_id, block in job_blocks.items():
            if _job_display_name(job_id, block) == job_name or job_id == job_name:
                job_block = block
                break
        if job_block is None:
            violations.append(f"UNSTABLE allowlist job `{job_name}` not found in {rel}")
            continue
        steps = _job_steps(job_block)
        step_names = [step.name for step in steps]
        for verifier in verifier_names:
            if verifier not in step_names:
                violations.append(
                    f"UNSTABLE verifier step `{verifier}` missing from job `{job_name}` in {rel}"
                )
        verifier_indexes = [
            index for index, step in enumerate(steps) if step.name in set(verifier_names)
        ]
        if not verifier_indexes:
            continue
        first_verifier = min(verifier_indexes)
        for step in steps[:first_verifier]:
            if step.has_run and (step.name or "") not in UNSTABLE_SETUP_RUN_STEPS:
                violations.append(
                    f"job `{job_name}` in {rel} runs unreviewed pre-verifier step "
                    f"`{step.name or '(unnamed)'}`; add it to the verifier allowlist or "
                    "UNSTABLE_SETUP_RUN_STEPS"
                )
        for step in steps:
            if step.name and _INJECTED_WRAPUP_NAME_RE.match(step.name):
                violations.append(
                    f"job `{job_name}` in {rel} authors step `{step.name}`, which collides "
                    "with GitHub-injected wrap-up names exempted by the UNSTABLE receipt"
                )
    return violations


def check_repo(repo_root: Path) -> list[Violation]:
    workflow_file = repo_root / WORKFLOW_PATH
    if not workflow_file.exists():
        return [Violation(path=str(WORKFLOW_PATH), message="missing workflow file")]

    text = workflow_file.read_text(encoding="utf-8")
    violations = [
        Violation(path=str(WORKFLOW_PATH), message=message)
        for message in find_required_check_priority_violations(text, repo_root=repo_root)
    ]
    violations.extend(
        Violation(path=str(UNSTABLE_MODULE_PATH), message=message)
        for message in _unstable_receipt_violations(repo_root)
    )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce required-check-priority workflow keep-list policy."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to check",
    )
    args = parser.parse_args()

    violations = check_repo(Path(args.repo_root).resolve())
    if not violations:
        print("Required check priority policy check passed")
        return 0

    print("Required check priority policy violations detected:")
    for v in violations:
        print(f"- {v.path}: {v.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
