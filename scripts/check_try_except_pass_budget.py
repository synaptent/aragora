#!/usr/bin/env python3
"""Committed-ceiling budget for blanket ``except ...: pass`` in ``tests/``.

ruff's S110 (try-except-pass) and S112 (try-except-continue) flag ``except:`` /
``except Exception:`` / ``except BaseException:`` handlers whose body is only
``pass`` / ``continue``.  In a test that shape makes every outcome pass,
including an ``AttributeError`` from asserting on a ``None`` result, so the test
proves nothing.  The fix is ``pytest.raises(<ExactError>, match=...)`` or a
concrete assertion on the returned value; in fixtures, narrow to the one
exception you actually intend to tolerate.

This checker mirrors ``scripts/check_sdk_parity.py``: measured debt is compared
against explicit committed ceilings in a budget file.  A file absent from the
budget has a ceiling of 0, so new files cannot introduce the pattern and
existing files cannot grow.  Ceilings only ever move down (``--tighten``
refuses to raise one).  A ``# noqa`` for S110/S112 inside ``tests/`` is a hard
failure regardless of budget, so the budget cannot be bypassed by suppression.

Usage:
    python scripts/check_try_except_pass_budget.py            # enforce; exit 1 on any exceed
    python scripts/check_try_except_pass_budget.py --json
    python scripts/check_try_except_pass_budget.py --tighten  # lower ceilings to measured debt
    python scripts/check_try_except_pass_budget.py --budget PATH --tests-root PATH

Exit codes: 0 within budget; 1 over budget (or ``--tighten`` refused); 2
infrastructure error (ruff unavailable, malformed or unwritable budget).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS_ROOT = REPO_ROOT / "tests"
DEFAULT_BUDGET = REPO_ROOT / "scripts" / "baselines" / "try_except_pass_budget.json"
RULES: tuple[str, ...] = ("S110", "S112")
BUDGET_SCHEMA = "check-try-except-pass-committed-budget-v1"
TOTAL_KEY = "committed_max_total"
PER_FILE_KEY = "committed_max_per_file"
NOQA_CODE = "NOQA-S11x"
# Built from parts so this file's own text never matches the scan.
_NOQA_RE = re.compile(r"#\s*no" + r"qa\b[^\n]*\bS11[02]\b")

FIX_GUIDANCE = (
    "Fix: assert the exact exception with `pytest.raises(<Error>, match=...)`, assert the "
    "returned value, or narrow a fixture's handler to the one exception it must tolerate. "
    "Do not add `# noqa`. After removing sites, run: "
    "python scripts/check_try_except_pass_budget.py --tighten"
)


class RuffUnavailableError(RuntimeError):
    """ruff could not be executed."""


@dataclass(frozen=True)
class Finding:
    path: str  # repo-root-relative, POSIX separators
    row: int
    code: str
    message: str


@dataclass(frozen=True)
class Budget:
    total: int
    per_file: dict[str, int]


@dataclass(frozen=True)
class BudgetLoadResult:
    budget: Budget | None = None
    error_kind: str | None = None  # "missing" | "malformed"
    error_detail: str | None = None
    raw_bytes: bytes | None = None


@dataclass
class Evaluation:
    ok: bool
    total_measured: int
    total_ceiling: int
    per_file_measured: dict[str, int]
    over_files: dict[str, tuple[int, int]]  # path -> (measured, ceiling)
    slack_files: dict[str, tuple[int, int]]  # path -> (measured, ceiling), measured < ceiling
    noqa_findings: list[Finding] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total_measured": self.total_measured,
            "total_ceiling": self.total_ceiling,
            "over_files": {
                k: {"measured": m, "ceiling": c} for k, (m, c) in self.over_files.items()
            },
            "slack_files": {
                k: {"measured": m, "ceiling": c} for k, (m, c) in self.slack_files.items()
            },
            "noqa_findings": [asdict(f) for f in self.noqa_findings],
            "findings": [asdict(f) for f in self.findings],
        }


# --------------------------------------------------------------------------- measure


def _ruff_command() -> list[str]:
    probe = [sys.executable, "-m", "ruff", "--version"]
    try:
        if subprocess.run(probe, capture_output=True, text=True, check=False).returncode == 0:
            return [sys.executable, "-m", "ruff"]
    except OSError:
        pass
    binary = shutil.which("ruff")
    if binary:
        return [binary]
    raise RuffUnavailableError(
        "ruff is not installed (neither `python -m ruff` nor a `ruff` binary)"
    )


def _relativize(path: Path, repo_root: Path, tests_root: Path) -> str:
    resolved = path.resolve()
    for base in (repo_root.resolve(), tests_root.resolve().parent):
        try:
            return resolved.relative_to(base).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def measure(tests_root: Path = DEFAULT_TESTS_ROOT, repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Run ruff S110/S112 over ``tests_root`` and return sorted findings."""
    cmd = _ruff_command() + [
        "check",
        str(tests_root),
        "--select",
        ",".join(RULES),
        "--output-format",
        "json",
        "--exit-zero",
        "--no-cache",
    ]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuffUnavailableError(
            f"ruff failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuffUnavailableError(f"ruff produced non-JSON output: {exc}") from exc
    findings = [
        Finding(
            path=_relativize(Path(item["filename"]), repo_root, tests_root),
            row=int(item["location"]["row"]),
            code=str(item["code"]),
            message=str(item.get("message", "")),
        )
        for item in data
    ]
    return sorted(findings, key=lambda f: (f.path, f.row))


def scan_noqa(tests_root: Path = DEFAULT_TESTS_ROOT, repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Find ``# noqa`` comments that suppress S110/S112 anywhere under ``tests_root``."""
    found: list[Finding] = []
    for path in sorted(tests_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for row, line in enumerate(text.splitlines(), start=1):
            if _NOQA_RE.search(line):
                found.append(
                    Finding(
                        path=_relativize(path, repo_root, tests_root),
                        row=row,
                        code=NOQA_CODE,
                        message="noqa suppression of S110/S112 is not allowed in tests/",
                    )
                )
    return found


# --------------------------------------------------------------------------- budget


def _as_ceiling(value: Any, key: str) -> int:
    # bool is an int subclass and must not slip through as a ceiling.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a nonnegative integer, got {value!r}")
    return value


def load_budget(path: Path = DEFAULT_BUDGET) -> BudgetLoadResult:
    if not path.exists():
        return BudgetLoadResult(error_kind="missing", error_detail=f"{path} does not exist")
    try:
        raw_bytes = path.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return BudgetLoadResult(error_kind="malformed", error_detail=str(exc))
    if not isinstance(data, dict):
        return BudgetLoadResult(error_kind="malformed", error_detail="budget must be a JSON object")
    if data.get("schema") != BUDGET_SCHEMA:
        return BudgetLoadResult(
            error_kind="malformed",
            error_detail=f"schema must be {BUDGET_SCHEMA!r}, got {data.get('schema')!r}",
            raw_bytes=raw_bytes,
        )
    try:
        total = _as_ceiling(data.get(TOTAL_KEY), TOTAL_KEY)
        per_file_raw = data.get(PER_FILE_KEY)
        if not isinstance(per_file_raw, dict):
            raise ValueError(f"{PER_FILE_KEY} must be a JSON object")
        per_file = {
            str(k): _as_ceiling(v, f"{PER_FILE_KEY}[{k!r}]") for k, v in per_file_raw.items()
        }
    except ValueError as exc:
        return BudgetLoadResult(error_kind="malformed", error_detail=str(exc), raw_bytes=raw_bytes)
    return BudgetLoadResult(budget=Budget(total=total, per_file=per_file), raw_bytes=raw_bytes)


def canonical_budget_bytes(total: int, per_file: dict[str, int]) -> bytes:
    payload = {
        "schema": BUDGET_SCHEMA,
        TOTAL_KEY: total,
        PER_FILE_KEY: {k: per_file[k] for k in sorted(per_file) if per_file[k] > 0},
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def evaluate(findings: list[Finding], noqa_findings: list[Finding], budget: Budget) -> Evaluation:
    measured = Counter(f.path for f in findings)
    over: dict[str, tuple[int, int]] = {}
    slack: dict[str, tuple[int, int]] = {}
    for path in sorted(set(measured) | set(budget.per_file)):
        m, c = measured.get(path, 0), budget.per_file.get(path, 0)
        if m > c:
            over[path] = (m, c)
        elif m < c:
            slack[path] = (m, c)
    total = sum(measured.values())
    ok = not over and total <= budget.total and not noqa_findings
    return Evaluation(
        ok=ok,
        total_measured=total,
        total_ceiling=budget.total,
        per_file_measured=dict(sorted(measured.items())),
        over_files=over,
        slack_files=slack,
        noqa_findings=list(noqa_findings),
        findings=list(findings),
    )


def format_text(ev: Evaluation, budget_path: Path) -> str:
    lines: list[str] = []
    n_files = len(ev.per_file_measured)
    if ev.ok:
        lines.append(
            f"PASS: try/except-pass budget: {ev.total_measured} site(s) in {n_files} file(s), "
            f"total ceiling {ev.total_ceiling} ({budget_path})"
        )
        if ev.slack_files or ev.total_measured < ev.total_ceiling:
            lines.append(
                f"  {len(ev.slack_files)} file(s) below ceiling; run --tighten to ratchet the budget down."
            )
        return "\n".join(lines)
    lines.append(
        f"FAIL: try/except-pass budget exceeded: {len(ev.over_files)} file(s) over ceiling, "
        f"total {ev.total_measured} vs ceiling {ev.total_ceiling} ({budget_path})"
    )
    by_path: dict[str, list[Finding]] = {}
    for f in ev.findings:
        by_path.setdefault(f.path, []).append(f)
    for path, (m, c) in ev.over_files.items():
        lines.append(f"  {path}: {m} > ceiling {c}")
        for f in by_path.get(path, []):
            lines.append(f"    {f.path}:{f.row}: {f.code} {f.message}")
    if ev.total_measured > ev.total_ceiling and not ev.over_files:
        lines.append(f"  total {ev.total_measured} exceeds committed total {ev.total_ceiling}")
    for f in ev.noqa_findings:
        lines.append(f"  {f.path}:{f.row}: {f.code} {f.message}")
    lines.append(FIX_GUIDANCE)
    return "\n".join(lines)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".try_except_pass_budget.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.chmod(tmp_name, 0o644)  # mkstemp defaults to 0600; keep the budget world-readable
        os.replace(tmp_name, str(path))
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def tighten(
    findings: list[Finding], noqa_findings: list[Finding], budget_path: Path
) -> tuple[int, str]:
    """Write measured debt as the committed ceilings.  Never raises a ceiling."""
    measured = Counter(f.path for f in findings)
    total = sum(measured.values())
    if noqa_findings:
        return (
            1,
            "FAIL: --tighten refuses while noqa suppressions of S110/S112 exist in tests/:\n"
            + "\n".join(f"  {f.path}:{f.row}" for f in noqa_findings),
        )
    loaded = load_budget(budget_path)
    if loaded.error_kind == "malformed":
        return (
            2,
            f"FAIL: refusing to overwrite malformed budget file ({budget_path}): {loaded.error_detail}",
        )
    if loaded.budget is not None:
        ev = evaluate(findings, [], loaded.budget)
        if ev.over_files or ev.total_measured > ev.total_ceiling:
            over = [f"{p} {m} > committed {c}" for p, (m, c) in ev.over_files.items()]
            if ev.total_measured > ev.total_ceiling:
                over.append(f"total {ev.total_measured} > committed {ev.total_ceiling}")
            return 1, "FAIL: --tighten refuses to raise committed ceilings: " + "; ".join(over)
    target = canonical_budget_bytes(total, dict(measured))
    if loaded.raw_bytes == target:
        return 0, f"Budget already tight: {total} site(s) in {len(measured)} file(s) (no write)"
    try:
        _atomic_write(budget_path, target)
    except OSError as exc:
        return 2, f"FAIL: cannot write budget file ({budget_path}): {exc}"
    return 0, (
        f"Tightened committed ceilings to measured debt: total<={total} across "
        f"{len(measured)} file(s) -> {budget_path}"
    )


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    parser.add_argument("--tests-root", type=Path, default=DEFAULT_TESTS_ROOT)
    parser.add_argument("--json", action="store_true", help="Emit the evaluation as JSON")
    parser.add_argument(
        "--tighten", action="store_true", help="Lower committed ceilings to measured debt"
    )
    args = parser.parse_args(argv)

    try:
        findings = measure(args.tests_root)
    except RuffUnavailableError as exc:
        print(f"FAIL: {exc}")
        return 2
    noqa_findings = scan_noqa(args.tests_root)

    if args.tighten:
        code, message = tighten(findings, noqa_findings, args.budget)
        print(message)
        return code

    loaded = load_budget(args.budget)
    if loaded.budget is None:
        print(
            f"FAIL: budget file {loaded.error_kind} ({args.budget}): {loaded.error_detail}. "
            "Create it with --tighten."
        )
        return 2
    ev = evaluate(findings, noqa_findings, loaded.budget)
    if args.json:
        print(json.dumps(ev.to_dict(), indent=2))
    else:
        print(format_text(ev, args.budget))
    return 0 if ev.ok else 1


if __name__ == "__main__":
    sys.exit(main())
