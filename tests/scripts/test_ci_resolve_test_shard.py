"""Verify CI test shards partition tests/{handlers,debate,server} cleanly.

The shard resolver in scripts/ci_resolve_test_shard.py drives the
test-fast matrix in .github/workflows/test.yml. If sub-shards overlap
or miss files we either run tests twice (wasted CI minutes) or skip
them entirely (silent regressions). Both are bad, so guard with this
test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci_resolve_test_shard.py"

spec = importlib.util.spec_from_file_location("ci_resolve_test_shard", SCRIPT_PATH)
assert spec and spec.loader
shard_mod = importlib.util.module_from_spec(spec)
sys.modules["ci_resolve_test_shard"] = shard_mod
spec.loader.exec_module(shard_mod)


def _expand_to_files(paths: list[str]) -> set[str]:
    """Recursively expand any directory entries in ``paths`` to test_*.py files.

    Tokens starting with ``--`` (e.g. ``--ignore=tests/server/handlers``) are
    interpreted as pytest options, not test paths, and the operand is removed
    from the resulting set so we model what pytest will actually collect.
    """
    include: set[str] = set()
    excludes: set[str] = set()
    for raw in paths:
        if raw.startswith("--ignore="):
            excludes.add(raw.split("=", 1)[1])
            continue
        if raw.startswith("--"):
            continue
        path = REPO_ROOT / raw
        if path.is_file():
            include.add(str(path.relative_to(REPO_ROOT)))
        elif path.is_dir():
            for f in path.rglob("test_*.py"):
                if "__pycache__" in f.parts:
                    continue
                include.add(str(f.relative_to(REPO_ROOT)))
    for ex in excludes:
        ex_path = REPO_ROOT / ex
        include = {f for f in include if not Path(f).is_relative_to(ex_path.relative_to(REPO_ROOT))}
    return include


def _all_tests_under(rel_root: str) -> set[str]:
    root = REPO_ROOT / rel_root
    return {
        str(p.relative_to(REPO_ROOT))
        for p in root.rglob("test_*.py")
        if "__pycache__" not in p.parts
    }


def _assert_partition(
    expected_total_root: str,
    shard_names: list[str],
) -> None:
    expected = _all_tests_under(expected_total_root)
    expanded_per_shard = {name: _expand_to_files(shard_mod.SHARDS[name]()) for name in shard_names}
    union: set[str] = set().union(*expanded_per_shard.values())

    missing = expected - union
    extras = union - expected
    overlaps: set[str] = set()
    items = list(expanded_per_shard.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            overlaps |= items[i][1] & items[j][1]

    assert not missing, (
        f"shards miss {len(missing)} files under {expected_total_root}: {sorted(missing)[:10]}"
    )
    assert not extras, f"shards include unexpected files: {sorted(extras)[:10]}"
    assert not overlaps, f"shards overlap on {len(overlaps)} files: {sorted(overlaps)[:10]}"


def test_handlers_partition_is_complete_and_disjoint() -> None:
    _assert_partition(
        "tests/handlers",
        ["handlers-features", "handlers-amk-no-features", "handlers-lz"],
    )


def test_server_handlers_partition_is_complete_and_disjoint() -> None:
    _assert_partition(
        "tests/server/handlers",
        ["server-handlers-am", "server-handlers-nz"],
    )


def test_debate_partition_is_complete_and_disjoint() -> None:
    _assert_partition(
        "tests/debate",
        ["debate-phases", "debate-1", "debate-2", "debate-3"],
    )


def test_debate_boundaries_are_sorted_and_each_range_nonempty() -> None:
    """Boundary tuple stays sorted, and no debate shard silently degenerates."""
    bounds = shard_mod._DEBATE_FILE_BOUNDARIES
    assert list(bounds) == sorted(bounds)
    for name in ["debate-phases", "debate-1", "debate-2", "debate-3"]:
        assert shard_mod.SHARDS[name](), f"shard {name} resolved to no paths"


def test_debate_subdirs_run_only_in_phases_shard() -> None:
    """Subdirectory tests belong to debate-phases; ranges cover only top-level files."""
    subdir_tests = {f for f in _all_tests_under("tests/debate") if len(Path(f).parts) > 3}
    assert subdir_tests <= _expand_to_files(shard_mod.shard_debate_phases())
    for fn in (shard_mod.shard_debate_1, shard_mod.shard_debate_2, shard_mod.shard_debate_3):
        assert subdir_tests.isdisjoint(_expand_to_files(fn()))


def test_resolver_emits_relative_paths() -> None:
    """All resolver outputs are repo-relative paths that exist or are pytest options."""
    for name, fn in shard_mod.SHARDS.items():
        for token in fn():
            if token.startswith("--"):
                continue
            assert (REPO_ROOT / token).exists(), f"shard {name} resolved nonexistent path: {token}"
