#!/usr/bin/env python3
"""Run paired control vs focused dogfood benchmark debates.

This script standardizes the A/B benchmark profile used in dogfood runs:
- fixed OpenRouter heterogeneous panel
- deterministic section contract and scoring via scripts/dogfood_score.py
- paired control/focused execution with aggregate median decision
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_AGENTS = ",".join(
    [
        "openrouter|anthropic/claude-sonnet-4||proposer",
        "openrouter|openai/gpt-4o||critic",
        "openrouter|google/gemini-2.0-flash-001||synthesizer",
    ]
)

DEFAULT_SECTIONS = ",".join(
    [
        "Ranked High-Level Tasks",
        "Suggested Subtasks",
        "Owner module / file paths",
        "Test Plan",
        "Rollback Plan",
        "Gate Criteria",
    ]
)

DEFAULT_CONTROL_TASK = (
    "Generate an execution-ready self-improvement plan for Aragora dogfood quality. "
    "Do not recreate existing components when existing modules already cover a capability. "
    "Use concrete repository paths where applicable."
)

DEFAULT_FOCUSED_TASK = (
    "Generate an execution-ready self-improvement plan for Aragora dogfood quality. "
    "Strict requirements: "
    "1) Use exactly these six H2 sections in this order: Ranked High-Level Tasks; "
    "Suggested Subtasks; Owner module / file paths; Test Plan; Rollback Plan; Gate Criteria. "
    "2) Before proposing any change, identify existing repo modules that already implement "
    "adjacent capability; prefer MODIFY/EXTEND over CREATE. "
    "3) For Owner module / file paths, include only concrete repository paths; for truly new "
    "files, append [NEW] and one-line necessity justification. "
    "4) Gate criteria must include explicit numeric thresholds and time windows. "
    "5) Rollback plan must include explicit trigger -> action mapping. "
    "6) Avoid duplicate-create proposals for existing capabilities; target "
    "duplicate_existing_create_ratio <= 0.25."
)

DEFAULT_INTEGRATION_VAGUE_TASK = (
    "Please describe the relationship between the completed dogfood stress test, "
    "the ideas-to-execution pipeline, the self-improvement pipeline, the heterogeneous "
    "agent codebase assessment/coding-change pipeline, and the self bug-fixing pipeline. "
    "Can all of these be more tightly integrated? This is intentionally vague and poorly "
    "specified; treat it as a dogfooding prompt and produce an execution-ready integration plan."
)

DEFAULT_INTEGRATION_FOCUSED_TASK = (
    "Use the same vague integration task below and produce an execution-ready plan.\n\n"
    f"Task: {DEFAULT_INTEGRATION_VAGUE_TASK}\n\n"
    "Strict requirements:\n"
    "1) Use exactly these six H2 sections in this order: Ranked High-Level Tasks; Suggested "
    "Subtasks; Owner module / file paths; Test Plan; Rollback Plan; Gate Criteria.\n"
    "2) Do not clone the same objective across all tracks; assign each goal to a fitting track.\n"
    "3) For this prompt class, ensure the top goal track is core, security, or self_hosted.\n"
    "4) Gate Criteria must include explicit numeric thresholds and time windows.\n"
    "5) Include rollback trigger -> action mappings.\n"
    "6) Prefer modify/extend existing modules over creating duplicates."
)


@dataclass
class RunStatus:
    label: str
    exit_code: int
    duration_seconds: float
    final_answer_present: bool
    timeout_report_exists: bool
    stdout: str
    stderr: str
    timeout: str
    codebase_context: str
    focused_profile: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "final_answer_present": self.final_answer_present,
            "timeout_report_exists": self.timeout_report_exists,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timeout": self.timeout,
            "codebase_context": self.codebase_context,
            "focused_profile": self.focused_profile,
        }


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _load_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env_path = repo_root / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in env:
                env[key] = value
    return env


def _run_command(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> tuple[int, str, str, float, bool]:
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds + 45,
            check=False,
        )
        elapsed = round(time.monotonic() - started, 3)
        return int(proc.returncode), proc.stdout, proc.stderr, elapsed, False
    except subprocess.TimeoutExpired as exc:
        elapsed = round(time.monotonic() - started, 3)
        stdout_raw = exc.stdout or ""
        stderr_raw = exc.stderr or ""
        if isinstance(stdout_raw, bytes):
            stdout = stdout_raw.decode("utf-8", errors="replace")
        else:
            stdout = stdout_raw
        if isinstance(stderr_raw, bytes):
            stderr = stderr_raw.decode("utf-8", errors="replace")
        else:
            stderr = stderr_raw
        stderr = stderr + f"\nDebate timed out after {timeout_seconds}s"
        return 124, stdout, stderr, elapsed, True


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _truncate_text(value: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return value[:max_chars] + f"\n\n...[truncated {omitted} chars]..."


def _run_variant(
    *,
    pair_dir: Path,
    label: str,
    task: str,
    focused: bool,
    timeout_seconds: int,
    repo_root: Path,
    env: dict[str, str],
    args: argparse.Namespace,
) -> RunStatus:
    stdout_path = pair_dir / f"pair_{pair_dir.name}_{label}_stdout.txt"
    stderr_path = pair_dir / f"pair_{pair_dir.name}_{label}_stderr.txt"
    timeout_path = pair_dir / f"pair_{pair_dir.name}_{label}_timeout.json"
    status_path = pair_dir / f"pair_{pair_dir.name}_{label}_status.json"
    context_out = pair_dir / f"pair_{pair_dir.name}_{label}_codebase_context.md"

    cmd = [
        "python3",
        "-m",
        "aragora.cli.main",
        "ask",
        task,
        "--local",
        "--mode",
        "orchestrator",
        "--agents",
        args.agents,
        "--rounds",
        "1",
        "--consensus",
        "majority",
        "--timeout",
        str(timeout_seconds),
        "--no-context-init-rlm",
        "--codebase-context",
        "--codebase-context-path",
        str(repo_root),
        "--codebase-context-timeout",
        str(args.codebase_context_timeout_seconds),
        "--codebase-context-out",
        str(context_out),
    ]

    if focused:
        cmd.extend(
            [
                "--required-sections",
                DEFAULT_SECTIONS,
                "--output-contract-file",
                str(args.contract_file),
                "--quality-upgrade-max-loops",
                str(args.focused_quality_upgrade_max_loops),
                "--quality-concretize-max-rounds",
                str(args.focused_quality_concretize_max_rounds),
                "--quality-extra-assessment-rounds",
                str(args.focused_quality_extra_assessment_rounds),
                "--quality-min-score",
                str(args.focused_quality_min_score),
                "--quality-practical-min-score",
                str(args.focused_quality_practical_min_score),
                "--grounding-fail-closed",
                "--grounding-min-verified-paths",
                str(args.focused_grounding_min_verified_paths),
            ]
        )
    else:
        cmd.extend(
            [
                "--no-upgrade-to-good",
                "--quality-concretize-max-rounds",
                "0",
                "--quality-extra-assessment-rounds",
                "0",
            ]
        )

    exit_code, stdout, stderr, duration_seconds, timed_out = _run_command(
        cmd,
        cwd=repo_root,
        env=env,
        timeout_seconds=timeout_seconds,
    )

    stdout_path.write_text(
        _truncate_text(stdout, max_chars=args.max_artifact_chars),
        encoding="utf-8",
    )
    stderr_path.write_text(
        _truncate_text(stderr, max_chars=args.max_artifact_chars),
        encoding="utf-8",
    )

    if timed_out:
        _write_json(
            timeout_path,
            {
                "status": "timeout",
                "timeout_seconds": timeout_seconds,
                "elapsed_seconds": duration_seconds,
                "label": label,
            },
        )

    status = RunStatus(
        label=label,
        exit_code=exit_code,
        duration_seconds=duration_seconds,
        final_answer_present="FINAL ANSWER:" in stdout,
        timeout_report_exists=timed_out,
        stdout=str(stdout_path),
        stderr=str(stderr_path),
        timeout=str(timeout_path),
        codebase_context=str(context_out),
        focused_profile=focused,
    )
    _write_json(status_path, status.to_dict())
    return status


def _score_pair(
    *,
    pair_dir: Path,
    control: RunStatus,
    focused: RunStatus,
    repo_root: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    summary_json = pair_dir / f"pair_{pair_dir.name}_summary.json"
    summary_md = pair_dir / f"pair_{pair_dir.name}_summary.md"
    cmd = [
        "python3",
        "scripts/dogfood_score.py",
        "--baseline-stdout",
        control.stdout,
        "--enhanced-stdout",
        focused.stdout,
        "--repo-root",
        str(repo_root),
        "--output-json",
        str(summary_json),
        "--output-md",
        str(summary_md),
    ]
    if control.timeout_report_exists:
        cmd.extend(["--baseline-timeout-report", control.timeout])
    if focused.timeout_report_exists:
        cmd.extend(["--enhanced-timeout-report", focused.timeout])

    proc = subprocess.run(  # noqa: S603
        cmd,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"dogfood_score failed ({proc.returncode}): {proc.stderr}")

    return json.loads(summary_json.read_text(encoding="utf-8"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt-profile",
        choices=["default", "integration_vague"],
        default="default",
        help="Prompt fixture profile used for control/focused tasks.",
    )
    parser.add_argument(
        "--pairs",
        type=int,
        default=5,
        help="Number of control/focused pairs to run (default: 5).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=960,
        help="Debate timeout per run (default: 960).",
    )
    parser.add_argument(
        "--promotion-threshold-delta",
        type=float,
        default=0.05,
        help="Median enhanced-baseline composite delta required to promote focused profile.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root path (default: current working directory).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/tmp/dogfood_ab_pairs"),
        help="Output artifact root directory (default: /tmp/dogfood_ab_pairs).",
    )
    parser.add_argument(
        "--agents",
        default=DEFAULT_AGENTS,
        help="Agent roster spec for aragora ask.",
    )
    parser.add_argument(
        "--control-task",
        default=DEFAULT_CONTROL_TASK,
        help="Task prompt for control runs.",
    )
    parser.add_argument(
        "--focused-task",
        default=DEFAULT_FOCUSED_TASK,
        help="Task prompt for focused runs.",
    )
    parser.add_argument(
        "--contract-file",
        type=Path,
        default=Path("docs/plans/dogfood_output_contract_v2.json"),
        help="Output contract file used in focused runs.",
    )
    parser.add_argument(
        "--codebase-context-timeout-seconds",
        type=int,
        default=120,
        help="Timeout for engineered codebase context generation.",
    )
    parser.add_argument(
        "--focused-quality-upgrade-max-loops",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--focused-quality-concretize-max-rounds",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--focused-quality-extra-assessment-rounds",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--focused-quality-min-score",
        type=float,
        default=9.0,
    )
    parser.add_argument(
        "--focused-quality-practical-min-score",
        type=float,
        default=5.5,
    )
    parser.add_argument(
        "--focused-grounding-min-verified-paths",
        type=float,
        default=0.1,
    )
    parser.add_argument(
        "--max-artifact-chars",
        type=int,
        default=2_000_000,
        help="Maximum chars saved per stdout/stderr artifact file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    env = _load_env(repo_root)

    if args.prompt_profile == "integration_vague":
        args.control_task = DEFAULT_INTEGRATION_VAGUE_TASK
        args.focused_task = DEFAULT_INTEGRATION_FOCUSED_TASK

    if not args.contract_file.is_file():
        raise SystemExit(f"Contract file not found: {args.contract_file}")

    pair_records: list[dict[str, Any]] = []
    baseline_scores: list[float] = []
    enhanced_scores: list[float] = []
    timeout_rates: list[float] = []

    print(
        f"[dogfood-ab] pairs={args.pairs} timeout={args.timeout_seconds}s output={output_root}",
        flush=True,
    )

    for idx in range(1, args.pairs + 1):
        pair_dir = output_root / str(idx)
        pair_dir.mkdir(parents=True, exist_ok=True)
        print(f"[dogfood-ab] pair {idx}/{args.pairs}: control", flush=True)
        control = _run_variant(
            pair_dir=pair_dir,
            label="control",
            task=args.control_task,
            focused=False,
            timeout_seconds=args.timeout_seconds,
            repo_root=repo_root,
            env=env,
            args=args,
        )
        print(
            f"[dogfood-ab] control exit={control.exit_code} "
            f"duration={control.duration_seconds}s final={control.final_answer_present}",
            flush=True,
        )

        print(f"[dogfood-ab] pair {idx}/{args.pairs}: focused", flush=True)
        focused = _run_variant(
            pair_dir=pair_dir,
            label="focused",
            task=args.focused_task,
            focused=True,
            timeout_seconds=args.timeout_seconds,
            repo_root=repo_root,
            env=env,
            args=args,
        )
        print(
            f"[dogfood-ab] focused exit={focused.exit_code} "
            f"duration={focused.duration_seconds}s final={focused.final_answer_present}",
            flush=True,
        )

        score = _score_pair(
            pair_dir=pair_dir,
            control=control,
            focused=focused,
            repo_root=repo_root,
            env=env,
        )
        summary = score.get("summary", {})
        baseline = float(summary.get("composite_scores", {}).get("baseline", 0.0))
        enhanced = float(summary.get("composite_scores", {}).get("enhanced", 0.0))
        timeout_rate = float(summary.get("timeout_rate", 0.0))
        baseline_scores.append(baseline)
        enhanced_scores.append(enhanced)
        timeout_rates.append(timeout_rate)
        print(
            f"[dogfood-ab] pair {idx} winner={summary.get('winner')} "
            f"scores={summary.get('composite_scores')} timeout_rate={timeout_rate}",
            flush=True,
        )

        record = {
            "pair": idx,
            "control": control.to_dict(),
            "focused": focused.to_dict(),
            "score": score,
        }
        pair_records.append(record)
        _write_json(pair_dir / f"pair_{idx}_record.json", record)

    baseline_median = round(statistics.median(baseline_scores), 4) if baseline_scores else 0.0
    enhanced_median = round(statistics.median(enhanced_scores), 4) if enhanced_scores else 0.0
    promotion_delta = round(enhanced_median - baseline_median, 4)
    promote_focused = promotion_delta >= float(args.promotion_threshold_delta)

    aggregate = {
        "generated_at": _utc_now(),
        "pairs": args.pairs,
        "timeout_seconds": args.timeout_seconds,
        "median_composite": {
            "baseline": baseline_median,
            "enhanced": enhanced_median,
        },
        "mean_timeout_rate": round(statistics.mean(timeout_rates), 4) if timeout_rates else 0.0,
        "per_pair_winner": [r["score"]["summary"]["winner"] for r in pair_records],
        "artifacts_root": str(output_root),
        "promotion_threshold_delta": float(args.promotion_threshold_delta),
        "promotion_delta": promotion_delta,
        "promote_focused": promote_focused,
        "prompt_profile": args.prompt_profile,
    }
    _write_json(output_root / "aggregate_summary.json", aggregate)

    step_report = {
        "experiment": "dogfood_ab_pairs",
        "generated_at": _utc_now(),
        "aggregate": aggregate,
        "pairs": pair_records,
    }
    _write_json(output_root / "step_report.json", step_report)
    print(f"[dogfood-ab] aggregate={json.dumps(aggregate, indent=2)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
