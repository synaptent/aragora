#!/usr/bin/env python3
"""Journey measurement harness for the agent-facing surface work (READ-ONLY).

An agent operating this repository pays a real, countable price to find out what
is true: every command it runs returns bytes it must read into context. That
price has never been measured, so claims about agent ergonomics here have always
been assertions. This harness makes them evidence.

A *journey* is a named, ordered list of shell commands representing one thing an
agent actually has to do (orient from cold, resume an interrupted task, decide a
risky action, re-check a quiet system). Running a journey records, per call, the
tokens the agent would have to read back, the wall time, and the exit code, then
scores the totals against fixed pass/fail budgets.

Inputs:

1. A journey definition file (JSON), default ``scripts/agent_surface/journeys.json``.
   Shape::

       {"journeys": {"<name>": {"question": str,
                                "budget": str,
                                "calls": [{"label": str, "cmd": str}, ...]}}}

2. Nothing else. The harness never writes to the repo, never calls a mutating
   command on the caller's behalf, and never touches the network itself -- though
   a journey's own commands may (e.g. ``gh``), which is the point: that cost is
   what we are measuring.

Output: one JSON object on stdout::

    {journey, question, calls[{label, cmd, exit_code, out_tokens, err_tokens,
     out_bytes, wall_ms, truncated}], totals{calls, tokens, wall_ms},
     budget{name, limit_calls, limit_tokens, verdict, margin}, tokenizer,
     measured_at}

Exit codes (so a wrapper or CI lane can branch on ``$?``):

- 0 -- journey ran and met its budget
- 3 -- journey ran and BLEW its budget (a result, not an error)
- 1 -- harness failure (bad journey file, unknown journey name)

Token accounting: counts are produced with ``tiktoken`` ``cl100k_base``, which is
a *proxy* for Claude's tokenizer, not the same tokenizer. Empirically it runs
within roughly 10-15% on English prose and structured output, which is far
inside the margins these budgets care about (a 4k budget versus a 40k reality).
Where an exact figure matters, ``--exact`` re-counts via the Anthropic count
API; it degrades back to the proxy, loudly, when no credential is available.
Every emitted record names the tokenizer actually used, so no number in this
repo is ever ambiguous about its provenance.

Safety model (mirrors ``backlog_gate.py``): read-only with respect to the repo
and to GitHub. Journey commands are executed as written, so journey files are
trusted input -- keep them to read-only probes. Stdlib plus ``tiktoken``.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_JOURNEYS = Path(__file__).with_name("journeys.json")

# Hard budgets from the v3 design constraints. These are pass/fail, not targets.
# A journey names which budget applies to it; "none" opts out of scoring while
# still recording measurements.
BUDGETS: dict[str, dict[str, Any]] = {
    "cold_orientation": {
        "limit_calls": 1,
        "limit_tokens": 4_000,
        "means": "cold agent reaches its first safe action",
    },
    "quiet_recheck": {
        "limit_calls": 1,
        "limit_tokens": 200,
        "means": "re-check when nothing meaningful has changed",
    },
    "full_situation": {
        "limit_calls": 3,
        "limit_tokens": 12_000,
        "means": "full situation reconstructible",
    },
    "none": {"limit_calls": None, "limit_tokens": None, "means": "unscored"},
}

# Output past this is truncated before counting. A single command that returns
# more than this has already lost -- the exact figure past the cliff is noise,
# and holding megabytes in memory to count it helps nobody.
MAX_CAPTURE_BYTES = 4 * 1024 * 1024


@dataclass
class CallRecord:
    label: str
    cmd: str
    exit_code: int
    out_tokens: int
    err_tokens: int
    out_bytes: int
    wall_ms: int
    truncated: bool = False
    error: str | None = None


@dataclass
class JourneyResult:
    journey: str
    question: str
    budget: str
    calls: list[CallRecord] = field(default_factory=list)
    tokenizer: str = ""
    measured_at: str = ""

    @property
    def total_tokens(self) -> int:
        # An agent pays for stderr too: it lands in the tool result either way.
        return sum(c.out_tokens + c.err_tokens for c in self.calls)

    @property
    def total_wall_ms(self) -> int:
        return sum(c.wall_ms for c in self.calls)


class TokenCounter:
    """Counts tokens, and is honest about which tokenizer produced the count."""

    def __init__(self, exact: bool = False) -> None:
        self.name = "unavailable"
        self._encoder: Any = None
        self._client: Any = None

        try:
            import tiktoken

            self._encoder = tiktoken.get_encoding("cl100k_base")
            self.name = "tiktoken/cl100k_base (proxy)"
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the run
            print(
                f"warning: tiktoken unavailable ({exc}); falling back to chars/4", file=sys.stderr
            )
            self.name = "chars/4 (crude fallback)"

        if exact:
            self._try_enable_exact()

    def _try_enable_exact(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "warning: --exact requested but ANTHROPIC_API_KEY is unset; "
                "keeping proxy tokenizer",
                file=sys.stderr,
            )
            return
        try:
            import anthropic

            self._client = anthropic.Anthropic()
            self.name = "anthropic/count_tokens (exact)"
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the run
            print(f"warning: exact counting unavailable ({exc}); keeping proxy", file=sys.stderr)

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._client is not None:
            try:
                resp = self._client.messages.count_tokens(
                    model="claude-fable-5",
                    messages=[{"role": "user", "content": text}],
                )
                return int(resp.input_tokens)
            except Exception as exc:  # noqa: BLE001 - degrade to proxy per-call
                print(f"warning: exact count failed ({exc}); proxy for this call", file=sys.stderr)
        if self._encoder is not None:
            return len(self._encoder.encode(text, disallowed_special=()))
        return (len(text) + 3) // 4


def run_call(label: str, cmd: str, counter: TokenCounter, cwd: Path, timeout: int) -> CallRecord:
    """Run one probe and record what an agent would have paid to read it."""
    started = time.monotonic()
    truncated = False
    error: str | None = None
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, code = "", f"TIMEOUT after {timeout}s", 124
        error = "timeout"
    except Exception as exc:  # noqa: BLE001 - a broken probe is data, not a crash
        stdout, stderr, code = "", str(exc), 1
        error = "spawn_failed"

    wall_ms = int((time.monotonic() - started) * 1000)

    if len(stdout) > MAX_CAPTURE_BYTES:
        stdout = stdout[:MAX_CAPTURE_BYTES]
        truncated = True

    return CallRecord(
        label=label,
        cmd=cmd,
        exit_code=code,
        out_tokens=counter.count(stdout),
        err_tokens=counter.count(stderr),
        out_bytes=len(stdout.encode("utf-8", errors="replace")),
        wall_ms=wall_ms,
        truncated=truncated,
        error=error,
    )


def score(result: JourneyResult) -> dict[str, Any]:
    spec = BUDGETS.get(result.budget, BUDGETS["none"])
    limit_calls = spec["limit_calls"]
    limit_tokens = spec["limit_tokens"]

    if limit_calls is None:
        return {
            "name": result.budget,
            "means": spec["means"],
            "limit_calls": None,
            "limit_tokens": None,
            "actual_calls": len(result.calls),
            "actual_tokens": result.total_tokens,
            "verdict": "UNSCORED",
        }

    over_calls = len(result.calls) > limit_calls
    over_tokens = result.total_tokens > limit_tokens
    verdict = "FAIL" if (over_calls or over_tokens) else "PASS"

    return {
        "name": result.budget,
        "means": spec["means"],
        "limit_calls": limit_calls,
        "limit_tokens": limit_tokens,
        "actual_calls": len(result.calls),
        "actual_tokens": result.total_tokens,
        "verdict": verdict,
        "over_calls_by": max(0, len(result.calls) - limit_calls),
        "over_tokens_by": max(0, result.total_tokens - limit_tokens),
        "overshoot_x": (round(result.total_tokens / limit_tokens, 1) if limit_tokens else None),
    }


def render_human(result: JourneyResult, budget: dict[str, Any]) -> str:
    lines = [
        f"journey: {result.journey}",
        f"question: {result.question}",
        f"tokenizer: {result.tokenizer}",
        "",
        f"{'call':<34} {'exit':>4} {'tokens':>9} {'ms':>7}",
        f"{'-' * 34} {'-' * 4} {'-' * 9} {'-' * 7}",
    ]
    for c in result.calls:
        flag = " *" if c.truncated else ""
        lines.append(
            f"{c.label[:34]:<34} {c.exit_code:>4} "
            f"{c.out_tokens + c.err_tokens:>9,} {c.wall_ms:>7,}{flag}"
        )
    lines += [
        f"{'-' * 34} {'-' * 4} {'-' * 9} {'-' * 7}",
        f"{'TOTAL':<34} {'':>4} {result.total_tokens:>9,} {result.total_wall_ms:>7,}",
        "",
    ]
    if budget["verdict"] == "UNSCORED":
        lines.append(
            f"budget: unscored ({len(result.calls)} calls, {result.total_tokens:,} tokens)"
        )
    else:
        lines.append(
            f"budget [{budget['name']}] {budget['means']}: "
            f"{budget['actual_calls']}/{budget['limit_calls']} calls, "
            f"{budget['actual_tokens']:,}/{budget['limit_tokens']:,} tokens "
            f"-> {budget['verdict']}"
        )
        if budget["verdict"] == "FAIL" and budget.get("overshoot_x"):
            lines.append(f"  overshoot: {budget['overshoot_x']}x the token budget")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("journey", help="journey name, or 'all', or 'list'")
    ap.add_argument("--file", type=Path, default=DEFAULT_JOURNEYS)
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--timeout", type=int, default=180, help="per-call seconds")
    ap.add_argument("--exact", action="store_true", help="count via Anthropic API")
    ap.add_argument("--json", action="store_true", help="JSON only, no table")
    args = ap.parse_args()

    try:
        spec = json.loads(args.file.read_text())
    except Exception as exc:  # noqa: BLE001 - surface the real cause and stop
        print(f"error: cannot read journey file {args.file}: {exc}", file=sys.stderr)
        return 1

    journeys = spec.get("journeys", {})
    if args.journey == "list":
        for name, j in journeys.items():
            print(f"{name:<24} [{j.get('budget', 'none')}] {j.get('question', '')}")
        return 0

    names = list(journeys) if args.journey == "all" else [args.journey]
    unknown = [n for n in names if n not in journeys]
    if unknown:
        print(f"error: unknown journey(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(journeys) or '(none)'}", file=sys.stderr)
        return 1

    counter = TokenCounter(exact=args.exact)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    payloads: list[dict[str, Any]] = []
    any_fail = False

    for name in names:
        j = journeys[name]
        result = JourneyResult(
            journey=name,
            question=j.get("question", ""),
            budget=j.get("budget", "none"),
            tokenizer=counter.name,
            measured_at=stamp,
        )
        for call in j.get("calls", []):
            result.calls.append(
                run_call(call["label"], call["cmd"], counter, args.repo, args.timeout)
            )

        budget = score(result)
        any_fail = any_fail or budget["verdict"] == "FAIL"

        payload = asdict(result)
        payload["totals"] = {
            "calls": len(result.calls),
            "tokens": result.total_tokens,
            "wall_ms": result.total_wall_ms,
        }
        payload["budget"] = budget
        payloads.append(payload)

        if not args.json:
            print(render_human(result, budget))
            print()

    if args.json:
        print(json.dumps({"results": payloads}, indent=2))

    return 3 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
