"""Run controlled dogfood benchmark loops and emit a summary JSON report.

Reuses the exact command payload from a prior dogfood analysis report so roster,
task prompt, and context remain fixed, while allowing timeout/runs overrides.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from aragora.debate.runtime_blockers import classify_stderr_signals


QUALITY_LINE_RE = re.compile(
    r"\[quality\]\s+verdict=(?P<verdict>[a-z_]+)\s+"
    r"score=(?P<score>[0-9]+(?:\.[0-9]+)?)\s+"
    r"practicality=(?P<practicality>[0-9]+(?:\.[0-9]+)?)\s+"
    r"loops=(?P<loops>[0-9]+)\s+upgraded=(?P<upgraded>True|False)"
)
EXECUTION_PATH_RE = re.compile(r"Execution path:\s*(?P<path>[a-z0-9_-]+)", re.IGNORECASE)
LIVE_STAGES_RE = re.compile(r"Live stages completed:\s*(?P<count>\d+)", re.IGNORECASE)
PROVIDER_CALLS_RE = re.compile(r"Provider calls detected:\s*(?P<flag>True|False)", re.IGNORECASE)
QUALITY_GATE_RE = re.compile(r"\[QUALITY GATE\]\s+(?P<verdict>PASS|FAIL)", re.IGNORECASE)
TOP_TRACK_RE = re.compile(r"^\s*1\.\s+\[(?P<track>[a-z_]+)\]", re.IGNORECASE | re.MULTILINE)
TRACK_LINE_RE = re.compile(r"^\s*\d+\.\s+\[(?P<track>[a-z_]+)\]", re.IGNORECASE | re.MULTILINE)


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _load_base_command(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    command = payload.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError(f"Expected non-empty 'command' list in {path}")
    if not all(isinstance(part, str) for part in command):
        raise ValueError(f"Command list in {path} must contain only strings")
    return command


def _override_timeout(command: list[str], timeout_seconds: int) -> list[str]:
    cmd = list(command)
    if "--timeout" in cmd:
        idx = cmd.index("--timeout")
        if idx + 1 >= len(cmd):
            raise ValueError("Malformed command: --timeout flag has no value")
        cmd[idx + 1] = str(timeout_seconds)
        return cmd

    # Only append --timeout when command targets `aragora ... ask`.
    # Other subcommands (for example `pipeline self-improve`) may not
    # accept a timeout flag.
    subcommand = None
    if "aragora.cli.main" in cmd:
        module_idx = cmd.index("aragora.cli.main")
        if module_idx + 1 < len(cmd):
            subcommand = cmd[module_idx + 1]
    elif "aragora" in cmd:
        cli_idx = cmd.index("aragora")
        if cli_idx + 1 < len(cmd):
            subcommand = cmd[cli_idx + 1]

    if subcommand == "ask":
        cmd.extend(["--timeout", str(timeout_seconds)])
    return cmd


def _extract_quality(stdout: str) -> dict[str, Any]:
    match = QUALITY_LINE_RE.search(stdout)
    if not match:
        return {
            "present": False,
            "verdict": None,
            "score": None,
            "practicality": None,
            "loops": None,
            "upgraded": None,
        }
    return {
        "present": True,
        "verdict": match.group("verdict"),
        "score": float(match.group("score")),
        "practicality": float(match.group("practicality")),
        "loops": int(match.group("loops")),
        "upgraded": match.group("upgraded") == "True",
    }


def _extract_pipeline_checks(stdout: str) -> dict[str, Any]:
    execution_match = EXECUTION_PATH_RE.search(stdout or "")
    live_stage_match = LIVE_STAGES_RE.search(stdout or "")
    provider_match = PROVIDER_CALLS_RE.search(stdout or "")
    quality_gate_match = QUALITY_GATE_RE.search(stdout or "")
    top_track_match = TOP_TRACK_RE.search(stdout or "")
    track_lines = [m.group("track").lower() for m in TRACK_LINE_RE.finditer(stdout or "")]

    execution_path = execution_match.group("path").lower() if execution_match else None
    live_stages = int(live_stage_match.group("count")) if live_stage_match else None
    provider_calls_detected = None
    if provider_match:
        provider_calls_detected = provider_match.group("flag").lower() == "true"

    quality_gate_verdict = (
        quality_gate_match.group("verdict").lower() if quality_gate_match else None
    )
    top_track = top_track_match.group("track").lower() if top_track_match else None
    has_cross_track_duplicates = len(track_lines) != len(set(track_lines)) if track_lines else None
    top_track_in_allowed_set = (
        top_track in {"core", "security", "self_hosted"} if top_track is not None else None
    )

    checks = {
        "execution_path_live": execution_path == "live" if execution_path is not None else None,
        "quality_gate_pass": quality_gate_verdict == "pass"
        if quality_gate_verdict is not None
        else None,
        "top_track_is_infra_or_security": top_track_in_allowed_set,
        "no_cross_track_clones": (
            (not has_cross_track_duplicates) if has_cross_track_duplicates is not None else None
        ),
    }
    checks_present = any(value is not None for value in checks.values())
    hard_checks_pass = checks_present and all(
        value is True for value in checks.values() if value is not None
    )

    return {
        "present": checks_present,
        "execution_path": execution_path,
        "live_stages_completed": live_stages,
        "provider_calls_detected": provider_calls_detected,
        "quality_gate_verdict": quality_gate_verdict,
        "top_track": top_track,
        "track_lines": track_lines,
        "checks": checks,
        "hard_checks_pass": hard_checks_pass,
    }


def _excerpt(text: str, max_chars: int = 4000) -> str:
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def _run_once(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(  # noqa: S603
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds + 30,  # small guard for process teardown
        )
        exit_code = int(proc.returncode)
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
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
    ended = time.monotonic()

    quality = _extract_quality(stdout)
    pipeline_checks = _extract_pipeline_checks(stdout)
    classified = classify_stderr_signals(stderr)
    return {
        "duration_seconds": round(ended - started, 2),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "quality": quality,
        "pipeline_checks": pipeline_checks,
        "runtime_blockers": classified["runtime_blockers"],
        "warning_signals": classified["warning_signals"],
        "warning_only": classified["warning_only"],
        "stdout_excerpt": _excerpt(stdout),
        "stderr_excerpt": _excerpt(stderr),
    }


def _safe_mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def _safe_median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _safe_min(values: list[float]) -> float | None:
    return round(min(values), 3) if values else None


def _safe_max(values: list[float]) -> float | None:
    return round(max(values), 3) if values else None


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(runs)
    non_timeout = [run for run in runs if not run["timed_out"]]
    successful = [run for run in runs if run["exit_code"] == 0 and not run["timed_out"]]
    quality_present = [run for run in successful if run["quality"]["present"]]
    passed = [
        run
        for run in quality_present
        if run["quality"]["verdict"] == "good"
        and (run["quality"]["score"] or 0) >= 9.0
        and (run["quality"]["practicality"] or 0) >= 5.0
    ]
    pipeline_present = [run for run in runs if run.get("pipeline_checks", {}).get("present")]
    pipeline_hard_pass = [
        run for run in pipeline_present if run.get("pipeline_checks", {}).get("hard_checks_pass")
    ]

    durations = [float(run["duration_seconds"]) for run in runs]
    loops = [
        float(run["quality"]["loops"])
        for run in quality_present
        if run["quality"]["loops"] is not None
    ]
    scores = [
        float(run["quality"]["score"])
        for run in quality_present
        if run["quality"]["score"] is not None
    ]
    practical = [
        float(run["quality"]["practicality"])
        for run in quality_present
        if run["quality"]["practicality"] is not None
    ]

    blocker_counts: dict[str, int] = {}
    for run in runs:
        for blocker in run.get("runtime_blockers") or []:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    check_keys = [
        "execution_path_live",
        "quality_gate_pass",
        "top_track_is_infra_or_security",
        "no_cross_track_clones",
    ]
    check_pass_rates: dict[str, float | None] = {}
    for key in check_keys:
        values = [
            run.get("pipeline_checks", {}).get("checks", {}).get(key) for run in pipeline_present
        ]
        bool_values = [bool(v) for v in values if v is not None]
        if not bool_values:
            check_pass_rates[key] = None
        else:
            check_pass_rates[key] = round(sum(bool_values) / len(bool_values), 4)

    return {
        "total_runs": total,
        "non_timeout_runs": len(non_timeout),
        "successful_runs": len(successful),
        "quality_present_runs": len(quality_present),
        "passed_quality_and_practicality_runs": len(passed),
        "pass_rate": round(len(passed) / total, 4) if total else 0.0,
        "duration_seconds": {
            "mean": _safe_mean(durations),
            "median": _safe_median(durations),
            "min": _safe_min(durations),
            "max": _safe_max(durations),
        },
        "quality_score_10": {
            "mean": _safe_mean(scores),
            "median": _safe_median(scores),
            "min": _safe_min(scores),
            "max": _safe_max(scores),
        },
        "practicality_score_10": {
            "mean": _safe_mean(practical),
            "median": _safe_median(practical),
            "min": _safe_min(practical),
            "max": _safe_max(practical),
        },
        "loops_used": {
            "mean": _safe_mean(loops),
            "median": _safe_median(loops),
            "min": _safe_min(loops),
            "max": _safe_max(loops),
        },
        "pipeline_hard_checks": {
            "present_runs": len(pipeline_present),
            "hard_check_pass_runs": len(pipeline_hard_pass),
            "hard_check_pass_rate": (
                round(len(pipeline_hard_pass) / len(pipeline_present), 4)
                if pipeline_present
                else None
            ),
            "check_pass_rates": check_pass_rates,
        },
        "runtime_blockers": blocker_counts,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-report",
        default="docs/plans/dogfood_timeout3600_single_run_analysis.json",
        help="Path to a prior dogfood analysis JSON containing a 'command' list.",
    )
    parser.add_argument(
        "--runs", type=int, default=3, help="Number of benchmark runs (default: 3)."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Fixed timeout (seconds) applied to every run (default: 3600).",
    )
    parser.add_argument(
        "--output",
        default="docs/plans/dogfood_benchmark_2026-03-01.json",
        help="Output report JSON path.",
    )
    parser.add_argument(
        "--enforce-pipeline-hard-checks",
        action="store_true",
        help=(
            "Fail non-zero when pipeline hard checks are present and any run fails them "
            "(execution_path/live, quality gate pass, top-track class, clone check)."
        ),
    )
    parser.add_argument(
        "--require-pipeline-hard-checks-presence",
        action="store_true",
        help=(
            "When enforcing hard checks, also fail if no run emitted pipeline hard-check signals."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    base_report = Path(args.base_report)
    if not base_report.is_file():
        raise SystemExit(f"Base report not found: {base_report}")

    command = _override_timeout(_load_base_command(base_report), args.timeout)
    runs: list[dict[str, Any]] = []

    print(
        f"[dogfood-benchmark] base_report={base_report} runs={args.runs} timeout={args.timeout}s",
        flush=True,
    )
    for idx in range(1, args.runs + 1):
        print(f"[dogfood-benchmark] run {idx}/{args.runs} starting", flush=True)
        result = _run_once(command, args.timeout)
        runs.append(result)
        q = result["quality"]
        print(
            "[dogfood-benchmark] run {idx} done "
            "exit={exit_code} duration={duration}s verdict={verdict} score={score} practicality={practicality}".format(
                idx=idx,
                exit_code=result["exit_code"],
                duration=result["duration_seconds"],
                verdict=q.get("verdict"),
                score=q.get("score"),
                practicality=q.get("practicality"),
            ),
            flush=True,
        )

    payload = {
        "generated_at": _utc_now(),
        "base_report": str(base_report),
        "command": command,
        "strict_timeout_seconds": args.timeout,
        "runs": runs,
        "summary": _summarize(runs),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[dogfood-benchmark] report={out_path}", flush=True)
    print(f"[dogfood-benchmark] summary={json.dumps(payload['summary'], indent=2)}", flush=True)
    if args.enforce_pipeline_hard_checks:
        checks = payload["summary"].get("pipeline_hard_checks", {})
        present_runs = int(checks.get("present_runs") or 0)
        pass_runs = int(checks.get("hard_check_pass_runs") or 0)
        if args.require_pipeline_hard_checks_presence and present_runs == 0:
            print(
                "[dogfood-benchmark] enforce-pipeline-hard-checks failed: no pipeline checks present",
                flush=True,
            )
            return 1
        if present_runs > 0 and pass_runs < present_runs:
            print(
                "[dogfood-benchmark] enforce-pipeline-hard-checks failed: "
                f"{pass_runs}/{present_runs} runs passed",
                flush=True,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
