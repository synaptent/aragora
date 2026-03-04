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
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nDebate timed out after {timeout_seconds}s"
    ended = time.monotonic()

    quality = _extract_quality(stdout)
    classified = classify_stderr_signals(stderr)
    return {
        "duration_seconds": round(ended - started, 2),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "quality": quality,
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
        and (run["quality"]["practicality"] or 0) >= 6.0
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
