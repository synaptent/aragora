#!/usr/bin/env python3
"""Reproducible repository metrics collection and policy comparison."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "docs" / "status" / "metrics" / "catalog.toml"
SCHEMA_VERSION = 1
COLLECTOR_VERSION = "1"
KINDS = {"inventory", "contract", "ratchet", "claim"}
DISPLAYS = {"lower_bound", "exact", "link_only"}
COMPARISONS = {"report_only", "delegated", "non_increasing", "exact_claim"}
POLICIES = {
    "none",
    "validate_openapi_routes",
    "sdk_parity",
    "agent_registry_sync",
    "mypy_baseline_ratchet",
    "catalog_claim",
}


class CatalogError(ValueError):
    """Raised when the metric catalog is malformed or unsupported."""


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    unit: str
    source: str
    collector: str
    kind: str
    display: str
    display_value: str
    comparison: str
    policy: str
    reproduction: str


@dataclass(frozen=True)
class RepositoryView:
    root: Path
    tracked_paths: tuple[PurePosixPath, ...]

    def paths(self, prefix: str = "", suffix: str = "") -> list[PurePosixPath]:
        return [
            path
            for path in self.tracked_paths
            if (not prefix or path.as_posix() == prefix or path.as_posix().startswith(prefix + "/"))
            and (not suffix or path.as_posix().endswith(suffix))
        ]

    def read_text(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8", errors="replace")


@dataclass
class RepositorySnapshot:
    git_sha: str
    generated_at: str
    catalog_digest: str
    metrics: list[dict[str, object]]
    errors: list[dict[str, str]]

    @property
    def status(self) -> str:
        return "complete" if not self.errors else "partial"

    @property
    def values(self) -> dict[str, object]:
        return {str(metric["key"]): metric.get("value") for metric in self.metrics}

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "collector_version": COLLECTOR_VERSION,
            "catalog_digest": self.catalog_digest,
            "git_sha": self.git_sha,
            "generated_at": self.generated_at,
            "status": self.status,
            "errors": self.errors,
            "metrics": self.metrics,
        }


Collector = Callable[[RepositoryView], dict[str, object]]


def count_python_modules(paths: Iterable[PurePosixPath]) -> int:
    return sum(
        1
        for path in paths
        if path.suffix == ".py"
        and "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.parts)
    )


def count_test_definitions(texts: Iterable[str]) -> int:
    pattern = re.compile(r"^\s*(?:async )?def test_", re.MULTILINE)
    return sum(len(pattern.findall(text)) for text in texts)


def count_adapter_files(paths: Iterable[PurePosixPath]) -> int:
    return sum(1 for path in paths if path.name.endswith("_adapter.py"))


def parse_project_version(text: str) -> str:
    project = tomllib.loads(text).get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("project.version is missing from pyproject.toml")
    return version


def _python_surface(view: RepositoryView) -> dict[str, object]:
    files = view.paths("aragora")
    python = [path for path in files if path.suffix == ".py" and "__pycache__" not in path.parts]
    loc = sum(len(view.read_text(path.as_posix()).splitlines()) for path in python)
    modules = {path.parts[1] for path in files if len(path.parts) > 2}
    return {"python_files": len(python), "python_loc": loc, "top_level_modules": len(modules)}


def _test_surface(view: RepositoryView) -> dict[str, object]:
    files = view.paths("tests")
    test_files = [path for path in files if path.suffix == ".py" and path.name.startswith("test_")]
    parametrize = re.compile(r"@pytest\.mark\.parametrize")
    texts = [view.read_text(path.as_posix()) for path in files]
    return {
        "test_files": len(test_files),
        "test_functions": count_test_definitions(texts),
        "parametrize_decorators": sum(len(parametrize.findall(text)) for text in texts),
    }


def _cli_surface(view: RepositoryView) -> dict[str, object]:
    prefix = PurePosixPath("aragora/cli/commands")
    count = sum(
        1
        for path in view.paths(prefix.as_posix(), ".py")
        if path.parent == prefix and not path.name.startswith("__")
    )
    return {"cli_command_modules": count}


def _openapi_surface(view: RepositoryView) -> dict[str, object]:
    path = "docs/api/openapi.json"
    if PurePosixPath(path) not in view.tracked_paths:
        return {"openapi_paths": 0, "openapi_operations": 0}
    spec = json.loads(view.read_text(path))
    paths = spec.get("paths", {})
    methods = {"get", "post", "put", "delete", "patch", "head", "options"}
    operations = sum(1 for value in paths.values() for method in value if method.lower() in methods)
    return {"openapi_paths": len(paths), "openapi_operations": operations}


def _rbac_surface(view: RepositoryView) -> dict[str, object]:
    texts = [view.read_text(path.as_posix()) for path in view.paths("aragora", ".py")]
    permission = re.compile(r"@require_permission\((['\"])([^'\"]+)['\"]\)")
    calls = sum(text.count("@require_permission(") for text in texts)
    unique = {match.group(2) for text in texts for match in permission.finditer(text)}
    return {"rbac_permission_calls": calls, "rbac_unique_permissions": len(unique)}


def _sdk_surface(view: RepositoryView) -> dict[str, object]:
    py_prefix = PurePosixPath("sdk/python/aragora_sdk")
    ts_prefix = PurePosixPath("sdk/typescript/src")
    py_count = sum(
        1
        for path in view.paths(py_prefix.as_posix(), ".py")
        if not path.name.startswith("__") and len(path.relative_to(py_prefix).parts) <= 2
    )
    ts_count = sum(
        1
        for path in view.paths(ts_prefix.as_posix(), ".ts")
        if len(path.relative_to(ts_prefix).parts) <= 2
    )
    return {"python_sdk_modules": py_count, "typescript_sdk_modules": ts_count}


def _agent_registry(view: RepositoryView) -> dict[str, object]:
    path = "aragora/config/settings.py"
    if PurePosixPath(path) not in view.tracked_paths:
        return {"allowed_agent_types": 0}
    match = re.search(
        r"ALLOWED_AGENT_TYPES[^=]*=\s*frozenset\s*\(\s*(?:\{|\[)([^}\]]+)",
        view.read_text(path),
        re.DOTALL,
    )
    return {
        "allowed_agent_types": len(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))
        if match
        else 0
    }


def _adapter_surface(view: RepositoryView) -> dict[str, object]:
    factory = "aragora/knowledge/mound/adapters/factory.py"
    specs = 0
    if PurePosixPath(factory) in view.tracked_paths:
        specs = len(re.findall(r'"\.[a-z_]+_adapter"', view.read_text(factory)))
    directory = PurePosixPath("aragora/knowledge/mound/adapters")
    files = count_adapter_files(
        path for path in view.paths(directory.as_posix(), "_adapter.py") if path.parent == directory
    )
    return {"knowledge_mound_adapter_specs": specs, "knowledge_mound_adapter_files": files}


def _docs_surface(view: RepositoryView) -> dict[str, object]:
    return {"doc_files": len(view.paths("docs", ".md"))}


def _workflow_surface(view: RepositoryView) -> dict[str, object]:
    directory = PurePosixPath(".github/workflows")
    workflows = [
        path
        for path in view.paths(directory.as_posix())
        if path.parent == directory and path.suffix in {".yml", ".yaml"}
    ]
    return {"ci_workflows": len(workflows)}


def _mypy_debt(view: RepositoryView) -> dict[str, object]:
    path = PurePosixPath(".mypy-baseline")
    value = len(view.read_text(path.as_posix()).splitlines()) if path in view.tracked_paths else 0
    return {"mypy_baseline_errors": value}


def _project_claims(view: RepositoryView) -> dict[str, object]:
    path = "pyproject.toml"
    if PurePosixPath(path) not in view.tracked_paths:
        raise ValueError("pyproject.toml is missing from the ref")
    return {"project_version": parse_project_version(view.read_text(path))}


COLLECTOR_REGISTRY: dict[str, Collector] = {
    "python_surface": _python_surface,
    "test_surface": _test_surface,
    "cli_surface": _cli_surface,
    "openapi_surface": _openapi_surface,
    "rbac_surface": _rbac_surface,
    "sdk_surface": _sdk_surface,
    "agent_registry": _agent_registry,
    "adapter_surface": _adapter_surface,
    "docs_surface": _docs_surface,
    "workflow_surface": _workflow_surface,
    "mypy_debt": _mypy_debt,
    "project_claims": _project_claims,
}


def load_catalog(path: Path = CATALOG_PATH) -> tuple[list[MetricDefinition], str]:
    raw_bytes = path.read_bytes()
    raw = tomllib.loads(raw_bytes.decode("utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"unsupported catalog schema_version: {raw.get('schema_version')!r}")
    entries = raw.get("metrics")
    if not isinstance(entries, list) or not entries:
        raise CatalogError("catalog must contain at least one [[metrics]] entry")
    required = {field.name for field in MetricDefinition.__dataclass_fields__.values()}
    definitions: list[MetricDefinition] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise CatalogError(f"metrics[{index}] must be a table")
        missing = sorted(required - entry.keys())
        if missing:
            raise CatalogError(f"metrics[{index}] missing fields: {', '.join(missing)}")
        values = {key: entry[key] for key in required}
        if not all(isinstance(value, str) for value in values.values()):
            raise CatalogError(f"metrics[{index}] fields must all be strings")
        definition = MetricDefinition(**values)
        if definition.key in seen:
            raise CatalogError(f"duplicate metric key: {definition.key}")
        if definition.collector not in COLLECTOR_REGISTRY:
            raise CatalogError(
                f"unsupported collector for {definition.key}: {definition.collector}"
            )
        if definition.kind not in KINDS or definition.display not in DISPLAYS:
            raise CatalogError(f"unsupported kind/display for {definition.key}")
        if definition.comparison not in COMPARISONS or definition.policy not in POLICIES:
            raise CatalogError(f"unsupported comparison/policy for {definition.key}")
        if definition.display in {"lower_bound", "exact"} and not definition.display_value:
            raise CatalogError(f"{definition.key} requires display_value")
        if definition.display == "lower_bound":
            try:
                int(definition.display_value)
            except ValueError as exc:
                raise CatalogError(f"{definition.key} lower bound must be an integer") from exc
        seen.add(definition.key)
        definitions.append(definition)
    return sorted(definitions, key=lambda item: item.key), hashlib.sha256(raw_bytes).hexdigest()


def _run_git(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def _extract_archive(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe git archive member: {member.name}")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise RuntimeError(f"could not read git archive member: {member.name}")
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def _collect_view(
    view: RepositoryView,
    git_sha: str,
    definitions: list[MetricDefinition],
    digest: str,
    generated_at: str | None = None,
) -> RepositorySnapshot:
    grouped: dict[str, list[MetricDefinition]] = {}
    for definition in definitions:
        grouped.setdefault(definition.collector, []).append(definition)
    values: dict[str, object] = {}
    errors: list[dict[str, str]] = []
    for collector_name in sorted(grouped):
        try:
            collected = COLLECTOR_REGISTRY[collector_name](view)
            for definition in grouped[collector_name]:
                if definition.key not in collected:
                    raise ValueError(f"collector omitted {definition.key}")
                values[definition.key] = collected[definition.key]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"collector": collector_name, "detail": str(exc)})
    metrics = [
        {**asdict(definition), "value": values.get(definition.key)} for definition in definitions
    ]
    return RepositorySnapshot(
        git_sha=git_sha,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        catalog_digest=digest,
        metrics=metrics,
        errors=errors,
    )


def collect_ref_snapshot(
    repo_root: Path,
    ref: str,
    catalog_path: Path = CATALOG_PATH,
    generated_at: str | None = None,
) -> RepositorySnapshot:
    definitions, digest = load_catalog(catalog_path)
    sha = _run_git(repo_root, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    tracked = tuple(
        PurePosixPath(path.decode("utf-8"))
        for path in _run_git(repo_root, "ls-tree", "-r", "--name-only", "-z", sha).split(b"\0")
        if path
    )
    with tempfile.TemporaryDirectory(prefix="repository-metrics-") as temp:
        temp_path = Path(temp)
        archive = temp_path / "ref.tar"
        _run_git(repo_root, "archive", "--format=tar", f"--output={archive}", sha)
        root = temp_path / "tree"
        root.mkdir()
        _extract_archive(archive, root)
        return _collect_view(RepositoryView(root, tracked), sha, definitions, digest, generated_at)


def compare_snapshots(
    base: RepositorySnapshot,
    head: RepositorySnapshot,
    definitions: list[MetricDefinition],
) -> dict[str, object]:
    changes: list[dict[str, object]] = []
    violations = 0
    delegated = 0
    reports = 0
    for definition in definitions:
        before = base.values.get(definition.key)
        after = head.values.get(definition.key)
        delta = after - before if isinstance(before, int) and isinstance(after, int) else None
        result = "pass"
        detail = ""
        if definition.comparison == "delegated":
            result, detail = "delegated", f"authority: {definition.policy}"
            delegated += 1
        elif definition.comparison == "report_only":
            result, detail = "report", "informational inventory movement"
            reports += 1
        elif definition.comparison == "non_increasing" and (
            not isinstance(before, int) or not isinstance(after, int) or after > before
        ):
            result, detail = "violation", "ratchet increased or was not numeric"
        if definition.display == "lower_bound":
            try:
                bound = int(definition.display_value)
            except ValueError:
                result, detail = "error", "lower-bound display_value is not an integer"
            else:
                if not isinstance(after, int) or after < bound:
                    result, detail = "violation", f"public lower bound {bound} is false"
        elif definition.display == "exact" and str(after) != definition.display_value:
            result, detail = "violation", "exact public claim does not match the observed value"
        if result in {"violation", "error"}:
            violations += 1
        changes.append(
            {
                "key": definition.key,
                "kind": definition.kind,
                "base": before,
                "head": after,
                "delta": delta,
                "comparison": definition.comparison,
                "policy": definition.policy,
                "result": result,
                "detail": detail,
            }
        )
    collection_errors = [*base.errors, *head.errors]
    return {
        "schema_version": SCHEMA_VERSION,
        "base_sha": base.git_sha,
        "head_sha": head.git_sha,
        "status": "error" if collection_errors else ("violation" if violations else "pass"),
        "errors": collection_errors,
        "summary": {
            "metrics": len(changes),
            "violations": violations,
            "delegated": delegated,
            "inventory_reports": reports,
        },
        "metrics": changes,
    }


def render_summary(comparison: dict[str, object]) -> str:
    summary = comparison["summary"]
    assert isinstance(summary, dict)
    lines = [
        "# Repository Metrics",
        "",
        f"Base: `{comparison['base_sha']}`",
        f"Head: `{comparison['head_sha']}`",
        f"Status: **{comparison['status']}**",
        "",
        "| Metric | Kind | Base | Head | Delta | Result | Authority |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    metrics = comparison["metrics"]
    assert isinstance(metrics, list)
    for metric in metrics:
        assert isinstance(metric, dict)
        lines.append(
            f"| {metric['key']} | {metric['kind']} | {metric['base']} | {metric['head']} | "
            f"{metric['delta']} | {metric['result']} | {metric['policy']} |"
        )
    lines.extend(
        [
            "",
            f"Violations: {summary['violations']}; delegated: {summary['delegated']}; "
            f"inventory reports: {summary['inventory_reports']}.",
            "",
        ]
    )
    return "\n".join(lines)


def render_contract(definitions: list[MetricDefinition]) -> str:
    lines = [
        "# Repository Metrics Contract",
        "",
        "Exact observations are SHA-bound artifacts. This contract defines how each metric is collected, displayed, and governed.",
        "",
        "| Metric | Public display | Kind | Source | Policy authority | Reproduce |",
        "|---|---|---|---|---|---|",
    ]
    for definition in definitions:
        if definition.display == "lower_bound":
            display = f"{int(definition.display_value):,}+"
        elif definition.display == "exact":
            display = definition.display_value
        else:
            display = "Exact snapshot only"
        fields = [
            definition.label,
            display,
            definition.kind,
            f"`{definition.source}`",
            definition.policy,
            f"`{definition.reproduction.replace('|', chr(92) + '|')}`",
        ]
        lines.append("| " + " | ".join(fields) + " |")
    lines.append("")
    return "\n".join(lines)


def exit_code(comparison: dict[str, object]) -> int:
    if comparison.get("errors"):
        return 2
    summary = comparison.get("summary", {})
    return 1 if isinstance(summary, dict) and summary.get("violations") else 0
