#!/usr/bin/env python3
"""Reject new or stale internal module edges in Boundary 2."""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = Path("scripts/ci/boundary_maps/receipts_verifier.json")
BASELINE_PATH = Path("scripts/baselines/boundary2_edges_baseline.json")
CHECKER_PATH = Path("scripts/ci/check_boundary_edges.py")
HOOK_PATH = Path(".pre-commit-config.yaml")


class PolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModuleRoot:
    path: Path
    package: str


@dataclass(frozen=True)
class Policy:
    roots: tuple[ModuleRoot, ...]
    sources: tuple[Path, ...]
    allowed: tuple[str, ...]
    hook_id: str
    hook_files: str


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError(f"{label} must be a JSON object")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise PolicyError(f"{label} must be a non-empty array")
    if any(not isinstance(item, str) or not item for item in value):
        raise PolicyError(f"{label} entries must be non-empty strings")
    items = tuple(value)
    if len(items) != len(set(items)):
        raise PolicyError(f"{label} contains duplicate entries")
    return items


def _path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{label} must be a non-empty path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise PolicyError(f"{label} must stay within the repository")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PolicyError(f"{label} escapes the repository") from exc
    return resolved


def _covered(pattern: re.Pattern[str], repo_root: Path, path: Path) -> bool:
    relative = path.relative_to(repo_root).as_posix()
    probe = f"{relative}/__boundary_probe__.py" if path.is_dir() else relative
    return pattern.fullmatch(probe) is not None


def load_policy(repo_root: Path, map_path: Path) -> Policy:
    root = repo_root.resolve()
    data = _json_object(map_path, "boundary map")
    if data.get("schema_version") != 1:
        raise PolicyError("boundary map schema_version must be 1")
    boundary = data.get("boundary")
    if not isinstance(boundary, dict) or boundary.get("id") != 2:
        raise PolicyError("boundary map must identify Boundary 2")
    if boundary.get("name") != "receipts+verifier" or not boundary.get("provenance"):
        raise PolicyError("boundary name or provenance is invalid")

    raw_roots = data.get("module_roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        raise PolicyError("module_roots must be a non-empty array")
    roots: list[ModuleRoot] = []
    for index, raw in enumerate(raw_roots):
        if not isinstance(raw, dict):
            raise PolicyError(f"module_roots[{index}] must be an object")
        package = raw.get("package")
        if not isinstance(package, str) or not package.isidentifier():
            raise PolicyError(f"module_roots[{index}].package must be an identifier")
        roots.append(
            ModuleRoot(_path(root, raw.get("path"), f"module_roots[{index}].path"), package)
        )
    if len({item.path for item in roots}) != len(roots) or len(
        {item.package for item in roots}
    ) != len(roots):
        raise PolicyError("module_roots contains duplicate paths or packages")

    sources = tuple(
        _path(root, value, f"sources[{index}]")
        for index, value in enumerate(_strings(data.get("sources"), "sources"))
    )
    allowed = _strings(data.get("allowed_internal_prefixes"), "allowed_internal_prefixes")
    if any(not item.startswith("aragora.") for item in allowed):
        raise PolicyError("allowed_internal_prefixes entries must start with aragora.")

    hook = data.get("hook")
    if not isinstance(hook, dict) or not isinstance(hook.get("id"), str):
        raise PolicyError("hook.id must be a string")
    hook_files = hook.get("files")
    if not isinstance(hook_files, str) or not hook_files:
        raise PolicyError("hook.files must be a non-empty regex")
    try:
        pattern = re.compile(hook_files)
    except re.error as exc:
        raise PolicyError(f"hook.files is invalid: {exc}") from exc

    for item in [*(entry.path for entry in roots), *sources]:
        if not item.exists():
            raise PolicyError(f"mapped path does not exist: {item.relative_to(root)}")
        if not any(item.is_relative_to(entry.path) for entry in roots):
            raise PolicyError(f"source is outside module_roots: {item.relative_to(root)}")
        if not _covered(pattern, root, item):
            raise PolicyError(f"hook.files does not cover {item.relative_to(root)}")
    for relative in (HOOK_PATH, MAP_PATH, BASELINE_PATH, CHECKER_PATH):
        if not pattern.fullmatch(relative.as_posix()):
            raise PolicyError(f"hook.files does not cover {relative}")
    return Policy(tuple(roots), sources, allowed, hook["id"], hook_files)


def _python_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix != ".py":
            raise PolicyError(f"mapped source is not Python: {path}")
        return [path]
    return sorted(item for item in path.rglob("*.py") if "__pycache__" not in item.parts)


def _module(path: Path, policy: Policy) -> tuple[str, bool]:
    matches = [root for root in policy.roots if path.is_relative_to(root.path)]
    if not matches:
        raise PolicyError(f"source has no module root: {path}")
    root = max(matches, key=lambda item: len(item.path.parts))
    relative = path.relative_to(root.path)
    parts = [root.package, *relative.with_suffix("").parts]
    is_package = path.name == "__init__.py"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _known_modules(policy: Policy) -> set[str]:
    known: set[str] = set()
    for root in policy.roots:
        for path in _python_files(root.path):
            name, _ = _module(path, policy)
            parts = name.split(".")
            known.update(".".join(parts[:index]) for index in range(1, len(parts) + 1))
    return known


def _relative_base(module: str, is_package: bool, node: ast.ImportFrom) -> str:
    package = module.split(".") if is_package else module.split(".")[:-1]
    keep = len(package) - (node.level - 1)
    if keep < 1:
        raise PolicyError(f"relative import escapes package in {module}")
    parts = package[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _targets(tree: ast.AST, module: str, is_package: bool, known: set[str]) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _relative_base(module, is_package, node) if node.level else node.module
            if not base:
                raise PolicyError(f"empty import target in {module}")
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                targets.add(candidate if alias.name != "*" and candidate in known else base)
    return targets


def _allowed(target: str, prefixes: tuple[str, ...]) -> bool:
    return any(target == prefix or target.startswith(f"{prefix}.") for prefix in prefixes)


def scan(repo_root: Path, policy: Policy) -> set[str]:
    violations: set[str] = set()
    known = _known_modules(policy)
    seen: set[Path] = set()
    for source in policy.sources:
        for path in _python_files(source):
            if path in seen:
                continue
            seen.add(path)
            module, is_package = _module(path, policy)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                raise PolicyError(f"cannot parse {path.relative_to(repo_root)}: {exc}") from exc
            for target in _targets(tree, module, is_package, known):
                if module == "aragora_verify" or module.startswith("aragora_verify."):
                    if target == "aragora" or target.startswith("aragora."):
                        violations.add(f"offline {module} -> {target}")
                elif (target == "aragora" or target.startswith("aragora.")) and not _allowed(
                    target, policy.allowed
                ):
                    violations.add(f"import {module} -> {target}")
    return violations


def _hook_values(path: Path, hook_id: str) -> dict[str, str]:
    values: dict[str, str] = {}
    matches = 0
    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:"):
            active = stripped.split(":", 1)[1].strip() == hook_id
            matches += int(active)
            continue
        if active and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in {"entry", "language", "pass_filenames", "files", "stages"}:
                values[key] = value.strip().strip("'\"")
    if matches != 1:
        raise PolicyError(f"expected exactly one {hook_id!r} hook, found {matches}")
    return values


def validate_hook(repo_root: Path, policy: Policy) -> None:
    hook_path = repo_root / HOOK_PATH
    try:
        text = hook_path.read_text(encoding="utf-8")
        values = _hook_values(hook_path, policy.hook_id)
    except OSError as exc:
        raise PolicyError(f"cannot read {HOOK_PATH}: {exc}") from exc
    expected = {
        "entry": "python3 scripts/ci/check_boundary_edges.py",
        "language": "system",
        "pass_filenames": "false",
        "files": policy.hook_files,
        "stages": "[pre-commit, pre-push]",
    }
    if values != expected:
        raise PolicyError(f"{policy.hook_id} hook drift: expected {expected}, found {values}")
    install = "pre-commit install --hook-type pre-commit --hook-type pre-push"
    if install not in "\n".join(text.splitlines()[:10]):
        raise PolicyError("documented default hook installation omits pre-commit or pre-push")


def load_baseline(path: Path) -> set[str]:
    data = _json_object(path, "boundary baseline")
    if data.get("schema_version") != 1 or data.get("boundary") != {
        "id": 2,
        "name": "receipts+verifier",
    }:
        raise PolicyError("boundary baseline identity is invalid")
    if data.get("map") != MAP_PATH.as_posix():
        raise PolicyError("boundary baseline map path is invalid")
    frozen_ref = data.get("frozen_from_ref")
    if not isinstance(frozen_ref, str) or not re.fullmatch(r"[0-9a-f]{40}", frozen_ref):
        raise PolicyError("frozen_from_ref must be an informational 40-character SHA")
    raw_items = data.get("violations")
    if not isinstance(raw_items, list) or any(
        not isinstance(item, str) or not item for item in raw_items
    ):
        raise PolicyError("baseline violations must be a string array")
    items = tuple(raw_items)
    if len(items) != len(set(items)):
        raise PolicyError("baseline violations contains duplicate entries")
    if list(items) != sorted(items):
        raise PolicyError("baseline violations must be sorted")
    return set(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--map", type=Path, default=MAP_PATH)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--print-current", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    map_path = args.map if args.map.is_absolute() else root / args.map
    baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline
    try:
        policy = load_policy(root, map_path)
        validate_hook(root, policy)
        current = scan(root, policy)
        if args.print_current:
            print(
                json.dumps(sorted(current), indent=2) if args.json else "\n".join(sorted(current))
            )
            return 0
        baseline = load_baseline(baseline_path)
    except PolicyError as exc:
        print(f"ERROR: {exc}")
        return 2

    new = current - baseline
    stale = baseline - current
    result = {"ok": not new and not stale, "new": sorted(new), "stale": sorted(stale)}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for item in sorted(new):
            print(f"NEW: {item}")
        for item in sorted(stale):
            print(f"STALE: {item}")
        if result["ok"]:
            print(f"Boundary 2 module-edge policy passed ({len(baseline)} baseline edges)")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
