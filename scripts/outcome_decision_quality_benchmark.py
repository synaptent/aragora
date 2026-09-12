#!/usr/bin/env python3
"""Frozen outcome-backed decision-quality benchmark CLI.

The CLI deliberately separates validation, execution, scoring, and rendering.
It emits structured JSON for every terminal result and never exposes the
outcome sidecar to a runner process.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from aragora.evaluation.outcome_decision_quality import (  # noqa: E402
    BenchmarkBundle,
    CostLedger,
    execute_batch,
    load_benchmark_bundle,
    load_results,
    render_markdown,
    run_subprocess_runner,
    score_results,
)

DEFAULT_MANIFEST = PROJECT_ROOT / "docs/benchmarks/decision_quality/benchmark-manifest.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    validate = subparsers.add_parser("validate-corpus", help="validate frozen corpus contract")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    run = subparsers.add_parser("run", help="run one bounded split through a JSON runner")
    run.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run.add_argument("--split", choices=("development", "holdout"), required=True)
    run.add_argument("--repetition", type=int, default=1)
    run.add_argument("--implementation-sha", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--runner-command", required=True)
    run.add_argument("--runner-timeout", type=float, default=600.0)
    run.add_argument("--results", type=Path, required=True)
    run.add_argument("--cost-ledger", type=Path)
    run.add_argument("--holdout-lock", type=Path)
    run.add_argument("--max-cases", type=int)

    score = subparsers.add_parser("score", help="score one or more result ledgers")
    score.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    score.add_argument("--results", type=Path, nargs="+", required=True)
    score.add_argument("--implementation-sha", required=True)
    score.add_argument("--output", type=Path)

    render = subparsers.add_parser("render", help="render deterministic Markdown from a score")
    render.add_argument("--score", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    return parser


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return exit_code


def _load_bundle_or_error(manifest: Path) -> tuple[BenchmarkBundle | None, int | None]:
    bundle, report = load_benchmark_bundle(manifest)
    if bundle is None:
        return None, _emit({"operation": "validate-corpus", **report.to_dict()}, exit_code=2)
    return bundle, None


def _validate(args: argparse.Namespace) -> int:
    _, report = load_benchmark_bundle(args.manifest)
    return _emit(
        {"operation": "validate-corpus", **report.to_dict()}, exit_code=0 if report.ok else 2
    )


def _run(args: argparse.Namespace) -> int:
    bundle, error_code = _load_bundle_or_error(args.manifest)
    if error_code is not None:
        return error_code
    assert bundle is not None
    command = shlex.split(args.runner_command)
    if not command:
        return _emit(
            {"ok": False, "operation": "run", "error": "empty runner command"}, exit_code=2
        )
    budget = float(bundle.manifest["budget"]["paid_api_daily_usd"])
    cost_path = args.cost_ledger or args.results.parent / "costs.jsonl"
    ledger = CostLedger.load(cost_path, budget)
    runner = partial(run_subprocess_runner, command, timeout=args.runner_timeout)
    summary = execute_batch(
        bundle,
        runner,
        split=args.split,
        repetition=args.repetition,
        implementation_sha=args.implementation_sha,
        run_id=args.run_id,
        results_path=args.results,
        cost_ledger=ledger,
        max_cases=args.max_cases,
        holdout_lock_path=args.holdout_lock,
    )
    return _emit({"operation": "run", **summary}, exit_code=0 if summary["ok"] else 1)


def _score(args: argparse.Namespace) -> int:
    bundle, error_code = _load_bundle_or_error(args.manifest)
    if error_code is not None:
        return error_code
    assert bundle is not None
    results, errors = load_results(args.results)
    if errors:
        return _emit({"ok": False, "operation": "score", "errors": errors}, exit_code=2)
    score = score_results(bundle, results, implementation_sha=args.implementation_sha)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(score, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _emit({"ok": True, "operation": "score", "score": score})


def _render(args: argparse.Namespace) -> int:
    try:
        score = json.loads(args.score.read_text(encoding="utf-8"))
    except OSError as exc:
        return _emit({"ok": False, "operation": "render", "error": str(exc)}, exit_code=2)
    except UnicodeError as exc:
        return _emit({"ok": False, "operation": "render", "error": str(exc)}, exit_code=2)
    except json.JSONDecodeError as exc:
        return _emit({"ok": False, "operation": "render", "error": str(exc)}, exit_code=2)
    if not isinstance(score, dict):
        return _emit(
            {"ok": False, "operation": "render", "error": "score must be a JSON object"},
            exit_code=2,
        )
    markdown = render_markdown(score)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    return _emit(
        {
            "ok": True,
            "operation": "render",
            "output": str(args.output),
            "sha256": __import__("hashlib").sha256(markdown.encode("utf-8")).hexdigest(),
        }
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "validate-corpus":
            return _validate(args)
        if args.operation == "run":
            return _run(args)
        if args.operation == "score":
            return _score(args)
        if args.operation == "render":
            return _render(args)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _emit({"ok": False, "operation": args.operation, "error": str(exc)}, exit_code=2)
    return _emit(
        {"ok": False, "operation": args.operation, "error": "unknown operation"}, exit_code=2
    )


if __name__ == "__main__":
    raise SystemExit(main())
