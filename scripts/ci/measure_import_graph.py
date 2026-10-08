#!/usr/bin/env python3
"""Measure the aragora import graph and ratchet its mutual-cycle count.

Emits three machine-parsable integers used by the codebase-health baseline
(epic #8257):

  * ``mutual_import_cycles`` -- number of unordered pairs of aragora modules
    that directly import each other (a mutual 2-cycle). This is the macro-
    coupling number P4b drives down and the ``--check`` ratchet protects.
  * ``server_imported_by``   -- number of distinct top-level ``aragora.<pkg>``
    packages OUTSIDE ``aragora.server`` that import any module in the
    ``aragora.server`` subtree. The "delivery layer used as a shared library"
    metric (target <=5).
  * ``handlers_flat_root``   -- number of ``*.py`` files directly in
    ``aragora/server/handlers/`` (cross-checks exactly with
    ``ls aragora/server/handlers/*.py | wc -l``).

Two deliberate measurement choices
----------------------------------
1. **TYPE_CHECKING-guarded imports are EXCLUDED**
   (``grimp.build_graph(..., exclude_type_checking_imports=True)``). Imports
   under an ``if TYPE_CHECKING:`` guard are type-only: they never execute, so
   they cannot create a real runtime circular import. Counting them would
   conflate type annotations with runtime coupling and would perversely reward
   deleting type hints. With them excluded the package has 140 mutual cycles
   (representing 140 cycles across 4,154 modules currently, drifting from
   the audit-time 139 cycles across 4,152 modules); including them inflates
   the count to 183. We pin the honest (excluded) value (140).

2. **The checkout root is forced onto ``sys.path[0]`` before building the
   graph.** Otherwise grimp resolves the SDK namespace package
   ``sdk/python/aragora`` (2 modules) instead of the real ``aragora`` package
   (~4,154 modules, or 4,152 at audit-time). Verified on PR #8311 (see mission library/environment.md).

Usage
-----
    python3 scripts/ci/measure_import_graph.py            # JSON: the 3 metrics
    python3 scripts/ci/measure_import_graph.py --json     # (same; explicit)
    python3 scripts/ci/measure_import_graph.py --check    # cycles ratchet
    python3 scripts/ci/measure_import_graph.py --list-cycles  # JSON: the mutual pairs
    python3 scripts/ci/measure_import_graph.py --freeze --adopt   # write baseline
    python3 scripts/ci/measure_import_graph.py --freeze   # shrink-only re-freeze

Exit codes
----------
    0 -- measurement succeeded, or ``--check`` found no cycle growth.
    1 -- ``--check`` detected cycle growth above the recorded baseline
         (fail-on-growth; a single new mutual cycle trips it).
    2 -- a usage/environment error (grimp missing, baseline missing, or a
         shrink-only violation on --freeze).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# NOTE: the literal "import_cycles_baseline" below is greppable on purpose
# (it wires --check/--freeze to the recorded baseline file).
CYCLES_BASELINE_PATH = REPO_ROOT / "scripts" / "baselines" / "import_cycles_baseline.json"
ROOT_PACKAGE = "aragora"
SERVER_PACKAGE = "aragora.server"
HANDLERS_DIR = REPO_ROOT / "aragora" / "server" / "handlers"


class MeasureError(RuntimeError):
    """Raised for usage/environment errors that map to exit code 2."""


# --- Graph construction -----------------------------------------------------


def _force_repo_root_on_syspath() -> None:
    """Put the checkout root at ``sys.path[0]`` so grimp resolves the real
    ``aragora`` package (~4,154 modules), not the SDK namespace package."""
    root = str(REPO_ROOT)
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)


def build_aragora_graph(exclude_type_checking: bool = True):
    """Build the grimp import graph for the ``aragora`` package.

    Caching is disabled (``cache_dir=None``) so the measurement always reflects
    the current tree and never writes a ``.grimp_cache`` artifact into the repo.
    """
    _force_repo_root_on_syspath()
    try:
        import grimp
    except ImportError as exc:  # pragma: no cover - exercised via validator install path
        raise MeasureError(
            "grimp not installed; run: python3 -m pip install grimp import-linter"
        ) from exc
    return grimp.build_graph(
        ROOT_PACKAGE,
        exclude_type_checking_imports=exclude_type_checking,
        cache_dir=None,
    )


# --- Pure metric functions --------------------------------------------------


def list_mutual_cycles(graph) -> list[list[str]]:
    """Sorted unordered pairs ``[a, b]`` (``a < b``) of modules that directly
    import each other."""
    edges: set[tuple[str, str]] = set()
    for module in graph.modules:
        for imported in graph.find_modules_directly_imported_by(module):
            if module != imported:
                edges.add((module, imported))
    pairs = {tuple(sorted((a, b))) for (a, b) in edges if (b, a) in edges}
    return [list(pair) for pair in sorted(pairs)]


def count_mutual_cycles(graph) -> int:
    """Unordered pairs of modules that directly import each other."""
    return len(list_mutual_cycles(graph))


def count_server_imported_by(graph, server_package: str = SERVER_PACKAGE) -> int:
    """Distinct top-level ``aragora.<pkg>`` packages outside the server subtree
    that directly import any module in the server subtree."""
    prefix = server_package + "."
    subtree = {m for m in graph.modules if m == server_package or m.startswith(prefix)}
    importer_tops: set[str] = set()
    for server_module in subtree:
        for importer in graph.find_modules_that_directly_import(server_module):
            if importer == server_package or importer.startswith(prefix):
                continue  # internal to the server subtree
            parts = importer.split(".")
            importer_tops.add(parts[1] if len(parts) >= 2 else importer)
    return len(importer_tops)


def count_handlers_flat_root(handlers_dir: Path = HANDLERS_DIR) -> int:
    """Count ``*.py`` files directly in ``handlers_dir`` (non-recursive),
    matching ``ls <dir>/*.py | wc -l`` exactly."""
    return sum(1 for _ in handlers_dir.glob("*.py"))


def evaluate_cycle_growth(current: int, baseline: int) -> bool:
    """Return True if ``current`` exceeds the recorded ``baseline`` (growth)."""
    return current > baseline


def measure_all(exclude_type_checking: bool = True) -> dict[str, object]:
    graph = build_aragora_graph(exclude_type_checking)
    return {
        "mutual_import_cycles": count_mutual_cycles(graph),
        "server_imported_by": count_server_imported_by(graph),
        "handlers_flat_root": count_handlers_flat_root(),
        "exclude_type_checking_imports": exclude_type_checking,
        "total_modules": len(graph.modules),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# --- Cycle ratchet baseline I/O --------------------------------------------


def load_cycle_baseline(path: Path = CYCLES_BASELINE_PATH) -> int:
    if not path.exists():
        raise MeasureError(
            f"cycles baseline not found: {path}. Create it with "
            "'python3 scripts/ci/measure_import_graph.py --freeze --adopt'."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("value")
    if not isinstance(value, int):
        raise MeasureError(f"malformed cycles baseline (expected int '.value'): {path}")
    return value


def write_cycle_baseline(path: Path, value: int) -> None:
    payload = {
        "_comment": (
            "Shrink-only baseline for mutual import cycles measured by "
            "scripts/ci/measure_import_graph.py with TYPE_CHECKING-guarded "
            "imports excluded. 'measure_import_graph.py --check' fails on ANY "
            "growth above this value (a single new mutual cycle trips it); this "
            "value may only shrink as cycles are removed (then re-freeze)."
        ),
        "metric": "mutual_import_cycles",
        "exclude_type_checking_imports": True,
        "value": value,
        "frozen_from_ref": _git_head(),
        "frozen_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _git_head() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        usage="%(prog)s [options]",
        description=(
            "Measure the aragora import graph (mutual cycles, server imported-by, "
            "handlers flat-root) with TYPE_CHECKING imports excluded, and ratchet "
            "the mutual-cycle count against scripts/baselines/import_cycles_baseline.json."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Cycle ratchet: re-measure mutual cycles and exit non-zero if the "
            "count grew above the recorded baseline (fail-on-growth)."
        ),
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help=(
            "Write the current mutual-cycle count to the baseline. Refuses to "
            "RAISE an existing baseline unless --adopt is given (shrink-only)."
        ),
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="With --freeze, permit the baseline value to grow (initial adoption only).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=CYCLES_BASELINE_PATH,
        help=(
            "Path to import_cycles_baseline.json "
            "(default: scripts/baselines/import_cycles_baseline.json)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON summary (the default output is already JSON).",
    )
    parser.add_argument(
        "--list-cycles",
        action="store_true",
        help=(
            "Print the mutual import cycles themselves as JSON "
            "({'cycles': [[a, b], ...]}, sorted pairs) instead of the counts."
        ),
    )
    return parser


def _run_list_cycles() -> int:
    cycles = list_mutual_cycles(build_aragora_graph())
    print(json.dumps({"cycles": cycles, "exclude_type_checking_imports": True}, indent=2))
    return 0


def _run_check(args: argparse.Namespace) -> int:
    baseline = load_cycle_baseline(args.baseline)
    current = count_mutual_cycles(build_aragora_graph())
    grew = evaluate_cycle_growth(current, baseline)
    if args.json:
        print(
            json.dumps(
                {
                    "metric": "mutual_import_cycles",
                    "baseline": baseline,
                    "current": current,
                    "ok": not grew,
                },
                indent=2,
            )
        )
    elif grew:
        print(
            f"FAIL: mutual import cycles grew {baseline} -> {current} "
            f"(+{current - baseline}). Remove the new mutual import(s); the cycle "
            "ratchet is shrink-only."
        )
    else:
        print(f"OK: mutual import cycles {current} <= baseline {baseline}.")
    return 1 if grew else 0


def _run_freeze(args: argparse.Namespace) -> int:
    current = count_mutual_cycles(build_aragora_graph())
    if args.baseline.exists() and not args.adopt:
        existing = load_cycle_baseline(args.baseline)
        if current > existing:
            raise MeasureError(
                f"--freeze would RAISE the cycles baseline {existing} -> {current} "
                "(shrink-only). Remove the new cycle(s), or pass --adopt for an "
                "intentional re-adoption."
            )
    write_cycle_baseline(args.baseline, current)
    print(f"Froze mutual import cycles baseline = {current} -> {args.baseline}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.freeze:
            return _run_freeze(args)
        if args.check:
            return _run_check(args)
        if args.list_cycles:
            return _run_list_cycles()
        print(json.dumps(measure_all(), indent=2))
    except MeasureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
