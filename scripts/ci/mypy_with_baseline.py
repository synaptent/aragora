#!/usr/bin/env python3
"""Run the pinned mypy toolchain through the committed debt baseline.

This helper is the authoritative full-repository typecheck gate. It fails
closed when the declared toolchain, baseline, mypy exit status, or diagnostic
shape is not trustworthy. Existing debt may pass through ``mypy-baseline``;
new errors and gate failures may not.
"""

from __future__ import annotations

import argparse
from importlib import metadata
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
BASELINE_PATH = REPO_ROOT / ".mypy-baseline"
DEFAULT_MYPY_ARGS: tuple[str, ...] = (
    "aragora/",
    "scripts/",
    "--config-file=pyproject.toml",
    "--ignore-missing-imports",
)
MYPY_DIAGNOSTIC_RE = re.compile(r"^.+?:\d+(?::\d+)?: error:", re.MULTILINE)
CONFIGURATION_ERROR = 2
TYPECHECK_DISTRIBUTIONS: tuple[str, ...] = ("mypy", "mypy-baseline", "pyjwt")


def _error(message: str) -> None:
    print(f"TYPECHECK-GATE-ERROR: {message}", file=sys.stderr)


def _requirement_name(requirement: str) -> str:
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement.strip())
    if match is None:
        raise ValueError(f"invalid requirement in dev dependencies: {requirement!r}")
    return match.group(1).lower().replace("_", "-").replace(".", "-")


def _load_typecheck_requirements(pyproject_path: Path) -> tuple[str, ...]:
    with pyproject_path.open("rb") as handle:
        document: dict[str, Any] = tomllib.load(handle)

    dev = document.get("project", {}).get("optional-dependencies", {}).get("dev")
    if not isinstance(dev, list) or not all(isinstance(item, str) for item in dev):
        raise ValueError("project.optional-dependencies.dev must be a list of requirements")

    selected: dict[str, list[str]] = {name: [] for name in TYPECHECK_DISTRIBUTIONS}
    for requirement in dev:
        name = _requirement_name(requirement)
        if name in selected:
            selected[name].append(requirement)

    for name, requirements in selected.items():
        if len(requirements) != 1:
            raise ValueError(
                f"expected exactly one {name!r} requirement in project.optional-dependencies.dev"
            )
    return tuple(selected[name][0] for name in TYPECHECK_DISTRIBUTIONS)


def _expected_exact_version(requirement: str, distribution: str) -> str:
    match = re.fullmatch(
        rf"{re.escape(distribution)}(?:\[[^\]]+\])?==([^,;\s]+)",
        requirement,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError(
            f"the CI {distribution} requirement must use one exact "
            f"'{distribution}[extras]==VERSION' pin"
        )
    return match.group(1)


def _installed_distribution_version(distribution: str) -> str:
    return metadata.version(distribution)


def _validate_toolchain(expected_versions: dict[str, str]) -> None:
    for distribution, expected in expected_versions.items():
        try:
            actual = _installed_distribution_version(distribution)
        except metadata.PackageNotFoundError as exc:
            raise ValueError(f"{distribution} is not installed") from exc
        if actual != expected:
            raise ValueError(
                f"installed {distribution} {actual!r} does not match pinned version {expected!r}"
            )


def _run_mypy(mypy_args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mypy", *mypy_args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def _run_baseline(mypy_output: str, *, sync: bool) -> int:
    command = [
        sys.executable,
        "-m",
        "mypy_baseline",
        "sync" if sync else "filter",
        "--baseline-path",
        str(BASELINE_PATH),
        "--no-colors",
    ]
    if sync:
        command.append("--sort-baseline")
    else:
        command.append("--allow-unsynced")
    command.extend(("--ignore-categories", "note"))
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        input=mypy_output,
        text=True,
        check=False,
    )
    return result.returncode


def _write_mypy_output(output: str) -> None:
    if not output:
        return
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the pinned mypy toolchain through mypy-baseline."
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Regenerate .mypy-baseline from the pinned full-repository check.",
    )
    parser.add_argument(
        "--print-install-requirements",
        action="store_true",
        help="Print the pyproject-declared mypy tool requirements for CI installation.",
    )
    parser.add_argument(
        "mypy_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to mypy; defaults to the authoritative full-repo targets.",
    )
    args = parser.parse_args(argv)

    try:
        requirements = _load_typecheck_requirements(PYPROJECT_PATH)
        expected_versions = {
            distribution: _expected_exact_version(requirement, distribution)
            for distribution, requirement in zip(TYPECHECK_DISTRIBUTIONS, requirements, strict=True)
        }
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        _error(str(exc))
        return CONFIGURATION_ERROR

    if args.print_install_requirements:
        print("\n".join(requirements))
        return 0

    try:
        _validate_toolchain(expected_versions)
    except ValueError as exc:
        _error(str(exc))
        return CONFIGURATION_ERROR

    if not BASELINE_PATH.is_file():
        _error(f"committed baseline is missing: {BASELINE_PATH}")
        return CONFIGURATION_ERROR

    raw_args = tuple(item for item in args.mypy_args if item != "--")
    result = _run_mypy(raw_args or DEFAULT_MYPY_ARGS)
    if result.returncode not in {0, 1}:
        _write_mypy_output(result.stdout)
        _error(f"mypy exited with unexpected status {result.returncode}")
        return result.returncode if result.returncode > 0 else CONFIGURATION_ERROR
    if result.returncode == 1 and MYPY_DIAGNOSTIC_RE.search(result.stdout) is None:
        _write_mypy_output(result.stdout)
        _error("mypy failed without any recognized file:line[:column]: error diagnostics")
        return 1

    return _run_baseline(result.stdout, sync=args.sync)


if __name__ == "__main__":
    sys.exit(main())
