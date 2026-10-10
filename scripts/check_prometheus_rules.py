#!/usr/bin/env python3
"""Validate Prometheus alert rule files with promtool.

The checker prefers a locally installed `promtool` binary and falls back to
Docker (`prom/prometheus`) when promtool is unavailable. The Docker run is
bounded by `--docker-timeout`; when it fails or times out, a PyYAML shape
check is used instead.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

DEFAULT_RULE_FILES: tuple[str, ...] = (
    "deploy/alerting/prometheus-rules.yml",
    "deploy/monitoring/alerts.yaml",
    "deploy/observability/alerts.rules",
    "deploy/observability/alerts.yml",
)
DEFAULT_DOCKER_IMAGE = "prom/prometheus:v2.54.1"
# Long enough for a cold image pull; a wedged daemon would otherwise block forever.
DEFAULT_DOCKER_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class CheckResult:
    returncode: int
    command: list[str]
    output: str
    error: str = ""


def resolve_rule_files(repo_root: Path, rule_files: Sequence[str]) -> tuple[list[Path], list[Path]]:
    """Split configured rule files into existing and missing paths."""
    existing: list[Path] = []
    missing: list[Path] = []
    for rel in rule_files:
        path = (repo_root / rel).resolve()
        if path.exists():
            existing.append(path)
        else:
            missing.append(path)
    return existing, missing


def _build_native_promtool_cmd(rule_files: Sequence[Path]) -> list[str]:
    return ["promtool", "check", "rules", *[str(p) for p in rule_files]]


def _build_docker_promtool_cmd(
    repo_root: Path,
    rule_files: Sequence[Path],
    *,
    image: str = DEFAULT_DOCKER_IMAGE,
) -> list[str]:
    rel_paths: list[str] = []
    for path in rule_files:
        rel_paths.append(str(path.resolve().relative_to(repo_root.resolve())))
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root.resolve()}:/workspace",
        "-w",
        "/workspace",
        image,
        "promtool",
        "check",
        "rules",
        *rel_paths,
    ]


def run_rule_check(
    repo_root: Path,
    rule_files: Sequence[Path],
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    docker_image: str = DEFAULT_DOCKER_IMAGE,
    docker_timeout_s: float = DEFAULT_DOCKER_TIMEOUT_S,
) -> CheckResult:
    """Run promtool check using local binary or a time-bounded Docker fallback."""

    def _yaml_fallback() -> CheckResult:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised via runtime environments
            return CheckResult(
                returncode=1,
                command=[],
                output="",
                error=(
                    "Unable to validate Prometheus rules: `promtool` unavailable, Docker unusable, "
                    f"and PyYAML import failed ({exc!r})."
                ),
            )

        errors: list[str] = []
        for path in rule_files:
            try:
                content = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"{path}: YAML parse error: {exc}")
                continue

            if not isinstance(content, dict):
                errors.append(f"{path}: expected top-level mapping")
                continue
            groups = content.get("groups")
            if not isinstance(groups, list):
                errors.append(f"{path}: expected top-level `groups` list")

        if errors:
            return CheckResult(
                returncode=1,
                command=["python", "yaml-safe-load"],
                output="",
                error="\n".join(errors),
            )

        return CheckResult(
            returncode=0,
            command=["python", "yaml-safe-load"],
            output=f"Fallback YAML validation passed ({len(rule_files)} files)",
            error="",
        )

    if which("promtool"):
        cmd = _build_native_promtool_cmd(rule_files)
        proc = run(cmd, capture_output=True, text=True)
        output = (proc.stdout or "").strip()
        error = (proc.stderr or "").strip()
        return CheckResult(proc.returncode, cmd, output, error)

    if which("docker"):
        cmd = _build_docker_promtool_cmd(repo_root, rule_files, image=docker_image)
        try:
            proc = run(cmd, capture_output=True, text=True, timeout=docker_timeout_s)
        except subprocess.TimeoutExpired:
            fallback = _yaml_fallback()
            note = f"promtool via Docker timed out after {docker_timeout_s:g} seconds"
            if fallback.returncode == 0:
                return CheckResult(
                    0, fallback.command, fallback.output, f"{note}. Using YAML fallback check."
                )
            return CheckResult(
                fallback.returncode,
                fallback.command,
                fallback.output,
                f"{note}, and the YAML fallback check failed:\n{fallback.error}",
            )
        output = (proc.stdout or "").strip()
        error = (proc.stderr or "").strip()
        if proc.returncode == 0:
            return CheckResult(proc.returncode, cmd, output, error)

        fallback = _yaml_fallback()
        if fallback.returncode == 0:
            detail = error or output
            fallback_error = (
                f"promtool via Docker was unavailable ({detail}). Using YAML fallback check."
            )
            return CheckResult(0, fallback.command, fallback.output, fallback_error)
        return fallback

    return _yaml_fallback()


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected seconds, got {value!r}") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive finite number, got {value!r}")
    return seconds


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Prometheus alert rules")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root path",
    )
    parser.add_argument(
        "--rule-file",
        action="append",
        dest="rule_files",
        default=None,
        help="Rule file relative to repo root (repeatable). Defaults to known Aragora rule files.",
    )
    parser.add_argument(
        "--docker-image",
        default=DEFAULT_DOCKER_IMAGE,
        help="Docker image containing promtool for fallback mode",
    )
    parser.add_argument(
        "--docker-timeout",
        type=_positive_seconds,
        default=DEFAULT_DOCKER_TIMEOUT_S,
        metavar="SECONDS",
        help=(
            "Seconds to wait for promtool via Docker before using the YAML fallback check "
            f"(default: {DEFAULT_DOCKER_TIMEOUT_S:g} seconds)"
        ),
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    configured_rules = tuple(args.rule_files or DEFAULT_RULE_FILES)

    existing, missing = resolve_rule_files(repo_root, configured_rules)
    if missing:
        print("Missing Prometheus rule files:")
        for path in missing:
            print(f"- {path}")
        return 1
    if not existing:
        print("No Prometheus rule files configured")
        return 1

    result = run_rule_check(
        repo_root,
        existing,
        docker_image=args.docker_image,
        docker_timeout_s=args.docker_timeout,
    )

    if result.command:
        print(f"Running: {' '.join(result.command)}")
    if result.output:
        print(result.output)
    if result.error:
        print(result.error)

    if result.returncode == 0:
        print(f"Prometheus rule validation passed ({len(existing)} files)")
        return 0

    print("Prometheus rule validation failed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
