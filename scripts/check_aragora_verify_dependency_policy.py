#!/usr/bin/env python3
"""Fail when aragora-verify declares dependencies outside its adopted policy."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "aragora-verify" / "pyproject.toml"
DEPENDENCY_POLICY = {
    "build-system.requires": frozenset({"hatchling"}),
    "project.dependencies": frozenset({"cryptography"}),
    "project.optional-dependencies.schema": frozenset({"jsonschema"}),
    "project.optional-dependencies.dev": frozenset({"pytest"}),
}


def _table(value: object, label: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(f"{label} must be a TOML table")
    return {}


def _requirement_names(value: object, label: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list):
        errors.append(f"{label} must be a TOML array")
        return set()

    names: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            errors.append(f"{label} contains a non-string requirement")
            continue
        try:
            names.add(canonicalize_name(Requirement(raw).name))
        except InvalidRequirement as exc:
            errors.append(f"{label} contains invalid PEP 508 requirement {raw!r}: {exc}")
    return names


def check_manifest(path: Path) -> list[str]:
    """Return policy violations for an aragora-verify pyproject manifest."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return [f"cannot parse {path}: {exc}"]

    errors: list[str] = []
    build_system = _table(document.get("build-system"), "build-system", errors)
    project = _table(document.get("project"), "project", errors)
    optional = _table(project.get("optional-dependencies"), "project.optional-dependencies", errors)
    declared: dict[str, object] = {
        "build-system.requires": build_system.get("requires"),
        "project.dependencies": project.get("dependencies"),
    }
    declared.update(
        {
            f"project.optional-dependencies.{group}": requirements
            for group, requirements in optional.items()
        }
    )

    for label in sorted(set(DEPENDENCY_POLICY) | set(declared)):
        actual = _requirement_names(declared.get(label), label, errors)
        expected = DEPENDENCY_POLICY.get(label, frozenset())
        for name in sorted(actual - expected):
            errors.append(f"{label} declares unadopted dependency {name!r}")
        for name in sorted(expected - actual):
            errors.append(f"{label} is missing adopted dependency {name!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    errors = check_manifest(args.pyproject)
    if not errors:
        print("aragora-verify dependency policy passed")
        return 0

    print("aragora-verify dependency policy violations:")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
