#!/usr/bin/env python3
"""Regenerate docs/METRICS.md from ground truth.

Single source of truth for all public numeric claims about Aragora.
Every metric has an explicit, reproducible command so a cold auditor can
verify it by running the same command.

Usage:
    python scripts/regenerate_metrics.py              # rewrite docs/METRICS.md
    python scripts/regenerate_metrics.py --check      # fail if drift > 0.5%
    python scripts/regenerate_metrics.py --json       # emit JSON only
    python scripts/regenerate_metrics.py snapshot --ref HEAD --output metrics.json

Drift threshold is intentionally tight: claim-drift is a thesis-commitment
violation (Commitment 4: respect the limits). A drifted metric should
trigger a PR rather than a silent mismatch.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import repository_metrics
except ModuleNotFoundError:  # Direct execution puts scripts/ on sys.path.
    import repository_metrics  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
METRICS_DOC = REPO_ROOT / "docs" / "METRICS.md"
DRIFT_THRESHOLD = 0.005  # 0.5%


@dataclass
class Metric:
    key: str
    label: str
    value: int | str
    command: str
    source: str
    notes: str = ""


@dataclass
class MetricsSnapshot:
    generated_at: str
    git_sha: str
    metrics: list[Metric] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "git_sha": self.git_sha,
            "metrics": [
                {
                    "key": m.key,
                    "label": m.label,
                    "value": m.value,
                    "command": m.command,
                    "source": m.source,
                    "notes": m.notes,
                }
                for m in self.metrics
            ],
        }


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    """Run a shell command and return stdout (stripped)."""
    result = subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _tracked_files(*pathspecs: str) -> list[Path]:
    """Return git-tracked files matching pathspecs as repo-relative paths."""
    result = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed for {pathspecs!r}\n{result.stderr}")
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _count_line_matches(paths: list[Path], pattern: str) -> int:
    """Count matching lines across tracked paths."""
    regex = re.compile(pattern)
    count = 0
    for rel_path in paths:
        path = REPO_ROOT / rel_path
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                count += sum(1 for line in f if regex.search(line))
        except OSError:
            pass
    return count


def _count_file_lines(paths: list[Path]) -> int:
    """Sum line counts across tracked paths that exist."""
    total = 0
    for rel_path in paths:
        path = REPO_ROOT / rel_path
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                total += sum(1 for _ in f)
        except OSError:
            pass
    return total


def gather_metrics() -> MetricsSnapshot:
    git_sha = _run(["git", "rev-parse", "--short", "HEAD"]) or "unknown"
    generated_at = datetime.now(timezone.utc).isoformat()

    metrics: list[Metric] = []

    # ----- Python surface -----
    aragora_files = _tracked_files("aragora")
    aragora_py_files = [
        p for p in aragora_files if p.suffix == ".py" and "__pycache__" not in p.parts
    ]
    py_files = len(aragora_py_files)
    metrics.append(
        Metric(
            key="python_files",
            label="Python files under aragora/",
            value=py_files,
            command="git ls-files aragora | grep -E '\\.py$' | wc -l",
            source="aragora/",
        )
    )

    # LOC via git-tracked Python-native counting (avoids xargs/wc batching risks:
    # xargs may split args into multiple `wc` invocations producing
    # multiple 'total' lines where only the last is kept; filenames
    # with spaces break shell splitting, and ignored local files can
    # otherwise pollute canonical docs).
    loc = _count_file_lines(aragora_py_files)
    metrics.append(
        Metric(
            key="python_loc",
            label="Python lines of code under aragora/",
            value=loc,
            command=(
                'python3 -c "from pathlib import Path; import subprocess; '
                "files = subprocess.check_output(['git', 'ls-files', 'aragora'], "
                "text=True).splitlines(); "
                "print(sum(sum(1 for _ in Path(p).open(encoding='utf-8', "
                "errors='replace')) for p in files if p.endswith('.py')))\""
            ),
            source="aragora/",
            notes="Uses git-tracked files + direct line count to avoid xargs/wc batching and ignored-file pollution.",
        )
    )

    # Top-level modules
    top_modules = len({p.parts[1] for p in aragora_files if len(p.parts) > 2})
    metrics.append(
        Metric(
            key="top_level_modules",
            label="Top-level modules under aragora/",
            value=top_modules,
            command="git ls-files aragora | awk -F/ 'NF>2 {print $2}' | sort -u | wc -l",
            source="aragora/",
        )
    )

    # ----- Tests -----
    tests_files = _tracked_files("tests")
    test_py_files = [p for p in tests_files if p.suffix == ".py" and p.name.startswith("test_")]
    test_files = len(test_py_files)
    metrics.append(
        Metric(
            key="test_files",
            label="Test files (test_*.py under tests/)",
            value=test_files,
            command="git ls-files tests | grep -E '(^|/)test_[^/]*\\.py$' | wc -l",
            source="tests/",
        )
    )

    # All test functions (class-nested + module-level)
    test_fns = _count_line_matches(tests_files, r"^\s*(async )?def test_")
    metrics.append(
        Metric(
            key="test_functions",
            label="Test functions (class + module level)",
            value=test_fns,
            command="git grep -E '^[[:space:]]*(async )?def test_' -- tests | wc -l",
            source="tests/",
            notes="Counts both module-level and class-nested test methods.",
        )
    )

    # Parametrize decorators (effective cases are a multiple of these)
    parametrize_count = _count_line_matches(tests_files, r"@pytest\.mark\.parametrize")
    metrics.append(
        Metric(
            key="parametrize_decorators",
            label="@pytest.mark.parametrize decorators",
            value=parametrize_count,
            command="git grep -E '@pytest\\.mark\\.parametrize' -- tests | wc -l",
            source="tests/",
            notes="Each decorator expands into N test cases during collection.",
        )
    )

    # ----- CLI -----
    cli_prefix_depth = len(Path("aragora/cli/commands").parts)
    cli_command_modules = len(
        [
            p
            for p in aragora_files
            if p.parent == Path("aragora/cli/commands")
            and len(p.parts) == cli_prefix_depth + 1
            and p.suffix == ".py"
            and not p.name.startswith("__")
        ]
    )
    metrics.append(
        Metric(
            key="cli_command_modules",
            label="CLI top-level command modules",
            value=cli_command_modules,
            command="git ls-files aragora/cli/commands | grep -E '/[^/]*\\.py$' | grep -v '/__' | wc -l",
            source="aragora/cli/commands/",
        )
    )

    # ----- OpenAPI -----
    openapi_path = REPO_ROOT / "docs" / "api" / "openapi.json"
    if openapi_path.exists():
        try:
            spec = json.loads(openapi_path.read_text())
            paths = spec.get("paths", {})
            http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}
            op_count = sum(1 for p in paths.values() for m in p if m.lower() in http_methods)
            metrics.append(
                Metric(
                    key="openapi_paths",
                    label="OpenAPI paths",
                    value=len(paths),
                    command="python -c \"import json; print(len(json.load(open('docs/api/openapi.json'))['paths']))\"",
                    source="docs/api/openapi.json",
                )
            )
            metrics.append(
                Metric(
                    key="openapi_operations",
                    label="OpenAPI operations (HTTP verbs)",
                    value=op_count,
                    command="python -c \"import json; spec=json.load(open('docs/api/openapi.json')); print(sum(1 for p in spec['paths'].values() for m in p if m.lower() in {'get','post','put','delete','patch','head','options'}))\"",
                    source="docs/api/openapi.json",
                )
            )
        except (OSError, json.JSONDecodeError) as e:
            metrics.append(
                Metric(
                    key="openapi_paths",
                    label="OpenAPI paths",
                    value=f"error: {type(e).__name__}",
                    command="python -c \"import json; print(len(json.load(open('docs/api/openapi.json'))['paths']))\"",
                    source="docs/api/openapi.json",
                )
            )

    # ----- RBAC -----
    permission_calls = _count_line_matches(aragora_py_files, r"@require_permission\(")
    metrics.append(
        Metric(
            key="rbac_permission_calls",
            label="@require_permission decorator calls",
            value=permission_calls,
            # The pathspec must stay restricted to .py files: the generator
            # counts decorator calls, and non-.py hits (README/YAML prose
            # mentions) would inflate a reproduction over all tracked files.
            command="git grep -E '@require_permission\\(' -- 'aragora/*.py' | wc -l",
            source="aragora/",
        )
    )

    permission_pattern = re.compile(r"@require_permission\((['\"])([^'\"]+)['\"]\)")
    unique_permission_values: set[str] = set()
    for rel_path in aragora_py_files:
        try:
            text = (REPO_ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        unique_permission_values.update(
            match.group(2) for match in permission_pattern.finditer(text)
        )
    unique_permissions = len(unique_permission_values)
    metrics.append(
        Metric(
            key="rbac_unique_permissions",
            label="Unique permission strings",
            value=unique_permissions,
            command='git grep -h -o -E "@require_permission\\([\'\\"][^\'\\"]+[\'\\"]\\)" -- aragora | sed -E "s/.*[\'\\"]([^\'\\"]+)[\'\\"].*/\\1/" | sort -u | wc -l',
            source="aragora/",
        )
    )

    # ----- SDK -----
    py_sdk_prefix = Path("sdk/python/aragora_sdk")
    py_sdk_modules = len(
        [
            p
            for p in _tracked_files(str(py_sdk_prefix))
            if p.suffix == ".py"
            and not p.name.startswith("__")
            and len(p.relative_to(py_sdk_prefix).parts) <= 2
        ]
    )
    metrics.append(
        Metric(
            key="python_sdk_modules",
            label="Python SDK modules",
            value=py_sdk_modules,
            command="git ls-files sdk/python/aragora_sdk | grep -E '\\.py$' | grep -v '/__' | awk -F/ 'NF<=5' | wc -l",
            source="sdk/python/",
        )
    )

    ts_sdk_prefix = Path("sdk/typescript/src")
    ts_sdk_modules = len(
        [
            p
            for p in _tracked_files(str(ts_sdk_prefix))
            if p.suffix == ".ts" and len(p.relative_to(ts_sdk_prefix).parts) <= 2
        ]
    )
    metrics.append(
        Metric(
            key="typescript_sdk_modules",
            label="TypeScript SDK modules",
            value=ts_sdk_modules,
            command="git ls-files sdk/typescript/src | grep -E '\\.ts$' | awk -F/ 'NF<=5' | wc -l",
            source="sdk/typescript/",
        )
    )

    # ----- Agent registry -----
    settings_path = REPO_ROOT / "aragora" / "config" / "settings.py"
    if settings_path.exists():
        text = settings_path.read_text()
        match = re.search(
            r"ALLOWED_AGENT_TYPES[^=]*=\s*frozenset\s*\(\s*(?:\{|\[)([^}\]]+)",
            text,
            re.DOTALL,
        )
        if match:
            allowed_count = len(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))
            metrics.append(
                Metric(
                    key="allowed_agent_types",
                    label="Allowlisted agent types",
                    value=allowed_count,
                    command="grep -A 50 'ALLOWED_AGENT_TYPES' aragora/config/settings.py | grep -oE \"'[a-z-]+'\" | sort -u | wc -l",
                    source="aragora/config/settings.py",
                )
            )

    # ----- Adapter factory -----
    adapter_factory = REPO_ROOT / "aragora" / "knowledge" / "mound" / "adapters" / "factory.py"
    if adapter_factory.exists():
        # Adapters are enumerated as tuples like ("./<name>_adapter", "<Class>", {...})
        # Count unique ".<name>_adapter" module references.
        adapter_count = len(re.findall(r'"\.[a-z_]+_adapter"', adapter_factory.read_text()))
        metrics.append(
            Metric(
                key="knowledge_mound_adapter_specs",
                label="Knowledge Mound adapter specs",
                value=adapter_count,
                command="git grep -E '\"\\.[a-z_]+_adapter\"' -- aragora/knowledge/mound/adapters/factory.py | wc -l",
                source="aragora/knowledge/mound/adapters/factory.py",
                notes="Counts adapter module entries in the factory spec tuple list.",
            )
        )

    adapter_dir = Path("aragora/knowledge/mound/adapters")
    if (REPO_ROOT / adapter_dir).exists():
        adapter_files = len(
            [p for p in aragora_files if p.parent == adapter_dir and p.name.endswith("_adapter.py")]
        )
        metrics.append(
            Metric(
                key="knowledge_mound_adapter_files",
                label="Knowledge Mound adapter files",
                value=adapter_files,
                command="git ls-files aragora/knowledge/mound/adapters | grep -E '/[^/]+_adapter\\.py$' | wc -l",
                source="aragora/knowledge/mound/adapters/",
            )
        )

    # ----- Docs -----
    doc_files = len([p for p in _tracked_files("docs") if p.suffix == ".md"])
    metrics.append(
        Metric(
            key="doc_files",
            label="Markdown files under docs/",
            value=doc_files,
            command="git ls-files docs | grep -E '\\.md$' | wc -l",
            source="docs/",
        )
    )

    # ----- CI workflows -----
    workflows = len([p for p in _tracked_files(".github/workflows") if p.suffix == ".yml"])
    metrics.append(
        Metric(
            key="ci_workflows",
            label="GitHub Actions workflows",
            value=workflows,
            command="git ls-files .github/workflows | grep -E '\\.yml$' | wc -l",
            source=".github/workflows/",
        )
    )

    # ----- Mypy baseline -----
    mypy_baseline = REPO_ROOT / ".mypy-baseline"
    if mypy_baseline.exists():
        mypy_errors = sum(1 for _ in mypy_baseline.open())
        metrics.append(
            Metric(
                key="mypy_baseline_errors",
                label="Mypy baseline errors (grandfathered)",
                value=mypy_errors,
                command="wc -l .mypy-baseline",
                source=".mypy-baseline",
            )
        )

    return MetricsSnapshot(
        generated_at=generated_at,
        git_sha=git_sha,
        metrics=metrics,
    )


def render_markdown(snapshot: MetricsSnapshot) -> str:
    lines: list[str] = []
    lines.append("# Aragora Canonical Metrics")
    lines.append("")
    lines.append(
        "> **This doc is auto-generated.** Do not edit by hand — edits will be "
        "overwritten by the next run of `scripts/regenerate_metrics.py`. "
        "If a number here disagrees with another doc, this doc wins. "
        "Every metric below is reproducible by running the command in its row."
    )
    lines.append("")
    lines.append(
        "> **No timestamp or git SHA is embedded in this doc by design.** "
        "Embedding either would cause two branches that both regenerated "
        "the doc to always conflict on merge, turning an honesty mechanism "
        "into a merge-conflict factory. The authoritative timestamp and SHA "
        "for any regeneration are available via `--json`."
    )
    lines.append("")
    lines.append("- **Regenerate:** `python scripts/regenerate_metrics.py`")
    lines.append("- **Verify (drift check):** `python scripts/regenerate_metrics.py --check`")
    lines.append("- **Timestamped JSON snapshot:** `python scripts/regenerate_metrics.py --json`")
    lines.append("")
    lines.append("## Canonical numbers")
    lines.append("")
    lines.append("| Metric | Value | Source | Command |")
    lines.append("|---|---|---|---|")
    for m in snapshot.metrics:
        cmd = m.command.replace("|", "\\|")
        source = m.source.replace("|", "\\|")
        lines.append(f"| {m.label} | `{m.value}` | `{source}` | `{cmd}` |")
    lines.append("")

    # Notes section
    noted = [m for m in snapshot.metrics if m.notes]
    if noted:
        lines.append("## Notes on counting methodology")
        lines.append("")
        for m in noted:
            lines.append(f"- **{m.label}:** {m.notes}")
        lines.append("")

    lines.append("## Why this doc exists")
    lines.append("")
    lines.append(
        "Aragora's thesis (Commitment 4: respect the limits) requires that "
        "the product not claim capability it does not have. The same "
        "discipline applies to numeric claims. Before this doc existed, "
        "different docs cited different numbers for the same metric "
        "(e.g. test-count claims ranged from 129K to 210K+ depending on "
        "regex used). This doc is the single source of truth."
    )
    lines.append("")
    lines.append(
        "All other docs that cite a metric should link here rather than "
        "hard-code the number, or explicitly snapshot the number with a "
        "date so staleness is visible."
    )
    lines.append("")
    lines.append("## Drift threshold")
    lines.append("")
    lines.append(
        "The `--check` mode fails if any metric moved by more than 0.5% from "
        "the committed doc. This threshold is a trade-off: lower values "
        "(e.g. 0.1%) would trigger on small absolute moves in small-denominator "
        "metrics (e.g. adapter count changing by one), forcing doc churn on "
        "normal development. Higher values (e.g. 5%) would let meaningful "
        "drift accumulate silently. 0.5% was picked as the default; it is a "
        "constant in `scripts/regenerate_metrics.py` (`DRIFT_THRESHOLD`) and "
        "can be tuned if specific metrics prove too noisy."
    )
    lines.append("")
    lines.append(
        "New metrics (present in the script but not in the committed doc) "
        "are reported as `NEW:` in the check output and force a refresh "
        "regardless of threshold."
    )
    lines.append("")
    lines.append("## Related automation")
    lines.append("")
    lines.append(
        "- `.github/workflows/metrics-drift.yml` runs this script on every PR "
        "that touches counted surfaces (`aragora/`, `tests/`, `sdk/`, "
        "`docs/api/openapi.json`, `.mypy-baseline`), and on a weekly Monday "
        "schedule. It invokes `--check` and fails the job if drift exceeds "
        "the threshold. On PR runs the check also snapshots the metrics at "
        "the merge commit's mainline parent (`--base-json`/`--base-doc`) so "
        "drift that pre-exists on `main` is reported as `INHERITED:` and "
        "does not fail the PR — only drift the PR itself introduces blocks. "
        "The weekly scheduled run stays strict and polices accumulated "
        "main-side staleness. The job does **not** auto-open a refresh PR; "
        "it fails loud and a human or follow-up automation decides whether "
        "to regenerate."
    )
    lines.append(
        "- `tests/scripts/test_regenerate_metrics.py` holds external "
        "invariants (e.g. test count > 100K, python file count > 1K) so the "
        "bootstrap is not fully self-referential: even if the committed "
        "doc were wrong, the invariant tests would catch a gross break."
    )
    lines.append(
        "- `scripts/reconcile_status.py` cross-references feature claims "
        "across CAPABILITY_MATRIX, GA_CHECKLIST, STATUS, ROADMAP."
    )
    lines.append(
        "- `scripts/validate_openapi_routes.py` verifies OpenAPI paths "
        "against actual handler implementations."
    )
    lines.append("")
    return "\n".join(lines)


def parse_current_metrics(doc_path: Path) -> dict[str, int | str]:
    """Extract metric values from an existing METRICS.md for drift comparison."""
    if not doc_path.exists():
        return {}
    text = doc_path.read_text()
    # Rows look like: | <label> | `<value>` | `<source>` | `<command>` |
    pattern = re.compile(r"^\|\s*([^|]+?)\s*\|\s*`([^`]*)`\s*\|", re.MULTILINE)
    result: dict[str, int | str] = {}
    for label, value in pattern.findall(text):
        label = label.strip()
        raw = value.strip()
        try:
            result[label] = int(raw)
        except ValueError:
            result[label] = raw
    return result


def load_base_snapshot(path: Path) -> dict[str, int | str]:
    """Load a --json snapshot (metric key -> value) for base attribution."""
    data = json.loads(path.read_text())
    return {m["key"]: m["value"] for m in data["metrics"]}


def _drift_is_inherited(
    metric: Metric,
    doc_value: int | str,
    base_live: dict[str, int | str],
    base_doc: dict[str, int | str],
) -> bool:
    """Return True when a doc-vs-truth drift is fully inherited from the base ref.

    Attribution model (PR runs): the check executes on the synthetic merge
    commit, so ``metric.value`` includes everything already merged to main
    since docs/METRICS.md was last refreshed. The PR is only accountable for
    the delta *it* introduces:

        pr_code_delta = value(merge commit) - value(base)
        pr_doc_delta  = doc(merge commit)   - doc(base)

    If the PR's unaccounted residual ``|pr_code_delta - pr_doc_delta|`` is
    within DRIFT_THRESHOLD, the remaining drift pre-exists on the base branch
    and must not block this PR (the weekly scheduled run polices it).
    """
    base_value = base_live.get(metric.key)
    base_doc_value = base_doc.get(metric.label)
    if base_value is None or base_doc_value is None:
        return False
    if (
        isinstance(metric.value, int)
        and isinstance(doc_value, int)
        and isinstance(base_value, int)
        and isinstance(base_doc_value, int)
    ):
        pr_code_delta = metric.value - base_value
        pr_doc_delta = doc_value - base_doc_value
        residual = abs(pr_code_delta - pr_doc_delta) / max(abs(doc_value), 1)
        return residual <= DRIFT_THRESHOLD
    # String-valued metrics: inherited only if the PR changed neither the
    # live value nor the documented value relative to the base.
    return str(metric.value) == str(base_value) and str(doc_value) == str(base_doc_value)


def check_drift(
    snapshot: MetricsSnapshot,
    base_live: dict[str, int | str] | None = None,
    base_doc: dict[str, int | str] | None = None,
) -> tuple[bool, list[str]]:
    """Compare snapshot against the committed doc.

    Returns (drifted, messages). Messages prefixed with ``INHERITED:`` are
    informational (drift pre-existing on the base ref, when base attribution
    data is supplied) and do not set ``drifted``.
    """
    current = parse_current_metrics(METRICS_DOC)
    attribute = base_live is not None and base_doc is not None
    blocking = 0
    drifts: list[str] = []

    def _record(message: str, metric: Metric, doc_value: int | str) -> None:
        nonlocal blocking
        if attribute and _drift_is_inherited(metric, doc_value, base_live or {}, base_doc or {}):
            drifts.append(f"INHERITED: {message}")
        else:
            blocking += 1
            drifts.append(message)

    for m in snapshot.metrics:
        prev = current.get(m.label)
        if prev is None:
            # A metric missing from the doc means the counter set itself
            # changed; that always requires a refresh (never attributed).
            blocking += 1
            drifts.append(f"NEW: {m.label} = {m.value}")
            continue
        if isinstance(prev, int) and isinstance(m.value, int):
            if prev == 0:
                delta_pct = 1.0 if m.value != 0 else 0.0
            else:
                delta_pct = abs(m.value - prev) / prev
            if delta_pct > DRIFT_THRESHOLD:
                _record(
                    f"DRIFT: {m.label} {prev} -> {m.value} ({delta_pct * 100:.1f}%)",
                    m,
                    prev,
                )
        else:
            if str(prev) != str(m.value):
                _record(f"CHANGED: {m.label} {prev!r} -> {m.value!r}", m, prev)
    return (blocking > 0), drifts


def _write_repository_snapshot(ref: str, output: Path) -> int:
    try:
        snapshot = repository_metrics.collect_ref_snapshot(REPO_ROOT, ref)
        payload = snapshot.as_dict()
    except (OSError, RuntimeError, ValueError) as exc:
        payload = {
            "schema_version": repository_metrics.SCHEMA_VERSION,
            "collector_version": repository_metrics.COLLECTOR_VERSION,
            "catalog_digest": "",
            "git_sha": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "partial",
            "errors": [{"collector": "snapshot", "detail": str(exc)}],
            "metrics": [],
        }

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"Could not write snapshot to {output}: {exc}", file=sys.stderr)
        return 2

    return 2 if payload["errors"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any metric drifted more than 0.5%% from current doc.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON snapshot to stdout instead of writing docs/METRICS.md.",
    )
    parser.add_argument(
        "--base-json",
        type=Path,
        help=(
            "With --check: --json snapshot taken at the PR base ref. Drift "
            "fully explained by the base (pre-existing on main) is reported "
            "as INHERITED and does not fail the check."
        ),
    )
    parser.add_argument(
        "--base-doc",
        type=Path,
        help="With --check: docs/METRICS.md as committed at the PR base ref.",
    )
    subparsers = parser.add_subparsers(dest="command")
    snapshot_parser = subparsers.add_parser(
        "snapshot", help="Write an exact, SHA-bound repository snapshot."
    )
    snapshot_parser.add_argument("--ref", required=True, help="Git ref to collect.")
    snapshot_parser.add_argument("--output", required=True, type=Path, help="Output JSON path.")
    args = parser.parse_args(argv)

    if args.command == "snapshot":
        if args.check or args.json:
            parser.error("snapshot cannot be combined with --check or --json")
        return _write_repository_snapshot(args.ref, args.output)

    if (args.base_json or args.base_doc) and not args.check:
        parser.error("--base-json/--base-doc are only valid with --check")

    snapshot = gather_metrics()

    if args.json:
        print(json.dumps(snapshot.as_dict(), indent=2))
        return 0

    if args.check:
        base_live: dict[str, int | str] | None = None
        base_doc_values: dict[str, int | str] | None = None
        if args.base_json or args.base_doc:
            if not (args.base_json and args.base_doc):
                parser.error("--base-json and --base-doc must be provided together")
            try:
                base_live = load_base_snapshot(args.base_json)
                base_doc_values = parse_current_metrics(args.base_doc)
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                print(
                    f"WARNING: could not load base attribution data ({exc}); "
                    "falling back to strict check.",
                    file=sys.stderr,
                )
                base_live = None
                base_doc_values = None
        if base_live is not None and base_doc_values is not None:
            drifted, drifts = check_drift(snapshot, base_live=base_live, base_doc=base_doc_values)
        else:
            drifted, drifts = check_drift(snapshot)
        inherited = [d for d in drifts if d.startswith("INHERITED:")]
        blocking = [d for d in drifts if not d.startswith("INHERITED:")]
        if inherited:
            print("Inherited drift (pre-existing on base branch; not blocking):")
            for d in inherited:
                print(f"  {d}")
            print()
        if drifted:
            print("Metrics drifted:")
            for d in blocking:
                print(f"  {d}")
            print()
            print(
                "Run `python scripts/regenerate_metrics.py` to refresh "
                "docs/METRICS.md and commit the result."
            )
            return 1
        print("No drift beyond 0.5% threshold.")
        return 0

    # Regenerate the doc
    markdown = render_markdown(snapshot)
    METRICS_DOC.parent.mkdir(parents=True, exist_ok=True)
    METRICS_DOC.write_text(markdown)
    print(f"Wrote {METRICS_DOC} with {len(snapshot.metrics)} metrics.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
