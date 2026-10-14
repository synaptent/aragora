#!/usr/bin/env python3
"""
Repo hygiene guard.

Fails if tracked files include runtime artifacts (DBs, node_modules, build outputs).
Optionally checks the working tree for untracked artifacts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


TRACKED_PATTERNS = [
    # Directories
    "/node_modules/",
    "/dist/",
    "/output/",
    "/htmlcov/",
    "/.nomic/",
    "/.pytest_cache/",
    "/.mypy_cache/",
    "/.ruff_cache/",
]

TRACKED_SUFFIXES = (
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
    ".log",
)


def _get_data_dir(repo_root: Path) -> Path:
    env_dir = os.environ.get("ARAGORA_DATA_DIR") or os.environ.get("ARAGORA_NOMIC_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    for candidate in (repo_root / ".nomic", repo_root / "data"):
        if candidate.exists():
            return candidate.resolve()
    return (repo_root / ".nomic").resolve()


def _is_under(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_status_untracked() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:].strip()
        if status in {"??", "A ", "AM", " M"}:
            paths.append(path)
    return paths


def _matches(path: str) -> bool:
    if any(segment in path for segment in TRACKED_PATTERNS):
        return True
    return path.endswith(TRACKED_SUFFIXES)


def _report(heading: str, paths: list[str]) -> None:
    print(heading)
    for path in sorted(paths):
        print(f"  - {path}")


_HARDCODED_PATH_PATTERNS = [
    'Path(".nomic/',
    'Path(".nomic")',
    "Path('.nomic/",
    "Path('.nomic')",
    '".nomic/',
    "'.nomic/",
]

# Files that legitimately reference .nomic (configs, docs, tests, migrations)
_HARDCODED_PATH_ALLOWLIST = {
    "aragora/config/data_dir.py",
    "aragora/config/legacy.py",
    "aragora/config/settings.py",
    "aragora/persistence/db_config.py",
    "aragora/migrations/sqlite_to_postgres.py",
    "scripts/guard_repo_clean.py",
    "scripts/migrate_runtime_dbs.py",
    "scripts/migrate_databases.py",
    "scripts/migrate_sqlite_to_postgres.py",
    "scripts/seed_demo.py",
    "scripts/epic_strategic_debate.py",
    "scripts/generate_epic_debate_receipt.py",
    "scripts/strategic_debate.py",
    "scripts/run_fractal_debate.py",
    "scripts/replay_cli.py",
    "scripts/gastown_migrate_state.py",
    "scripts/nomic_eval.py",
    "scripts/nomic/safety/constitution.py",
    # Environment variable defaults (not runtime path construction)
    "aragora/mcp/impl_config.py",
    "scripts/nomic/config.py",
    "scripts/nomic_loop.py",
    # Docstrings/string literals (not path construction)
    "aragora/broadcast/pipeline.py",
    "aragora/policy/engine.py",
    "aragora/replay/storage.py",
}


def _scan_hardcoded_paths(repo_root: Path) -> list[str]:
    """Scan Python source for hardcoded .nomic/ paths (lint check)."""
    violations: list[str] = []
    aragora_dir = repo_root / "aragora"
    scripts_dir = repo_root / "scripts"
    for search_dir in (aragora_dir, scripts_dir):
        if not search_dir.is_dir():
            continue
        for py_file in search_dir.rglob("*.py"):
            rel = str(py_file.relative_to(repo_root))
            if rel in _HARDCODED_PATH_ALLOWLIST:
                continue
            if "/tests/" in rel or rel.startswith("tests/"):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                if any(pat in line for pat in _HARDCODED_PATH_PATTERNS):
                    # Skip comments
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    violations.append(f"{rel}:{i}: {stripped.strip()}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard repo against runtime artifacts.")
    parser.add_argument(
        "--check",
        dest="check_working_tree",
        action="store_true",
        help="Alias for --check-working-tree.",
    )
    parser.add_argument(
        "--check-working-tree",
        dest="check_working_tree",
        action="store_true",
        help="Also fail if untracked working-tree artifacts are present.",
    )
    parser.add_argument(
        "--scan-paths",
        action="store_true",
        help="Scan source for hardcoded .nomic/ paths (lint check).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    data_dir = _get_data_dir(repo_root)

    tracked = [path for path in _git_ls_files() if _matches(path)]
    if tracked:
        _report("Tracked runtime artifacts detected:", tracked)
        print("Remove these files from git and keep runtime data under ARAGORA_DATA_DIR.")
        return 1

    if args.check_working_tree:
        untracked = [path for path in _git_status_untracked() if _matches(path)]
        # Ignore artifacts under ARAGORA_DATA_DIR
        untracked = [path for path in untracked if not _is_under(repo_root / path, data_dir)]
        if untracked:
            _report("Untracked runtime artifacts detected:", untracked)
            print("Move runtime data under ARAGORA_DATA_DIR or delete these artifacts.")
            return 1

    if args.scan_paths:
        violations = _scan_hardcoded_paths(repo_root)
        if violations:
            _report("Hardcoded .nomic/ paths found (use get_nomic_dir()):", violations)
            return 1

    print("Repo hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
