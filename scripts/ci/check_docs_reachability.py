#!/usr/bin/env python3
"""Curated docs reachability checker (standard library only, read-only).

Breadth-first search over relative Markdown links in git-tracked Markdown,
starting from the seeds README.md and docs/README.md. Traversal follows links
into any tracked Markdown page except docs/archive/, then reports which
curated candidate pages were reached and which are orphans.

Curated candidates (--scope curated): tracked docs/*.md plus Markdown anywhere
under docs/getting-started, docs/guides, docs/reference, docs/architecture,
docs/operations, docs/governance and docs/strategy. docs/archive/ is neither
traversed nor reported. Untracked files are ignored.

whole_tree_orphan_count (informational, never gated) counts every tracked
non-archive docs/**/*.md page that the traversal did not reach.

Exit codes: 0 no curated orphans; 1 curated orphans found; 2 usage or tool error.

Usage:
  python3 scripts/ci/check_docs_reachability.py --scope curated
  python3 scripts/ci/check_docs_reachability.py --scope curated --json
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

SCHEMA_VERSION = 1
SCOPE = "curated"
SEEDS = ("README.md", "docs/README.md")
CURATED_DIRS = frozenset(
    {
        "getting-started",
        "guides",
        "reference",
        "architecture",
        "operations",
        "governance",
        "strategy",
    }
)
ARCHIVE_PREFIX = "docs/archive/"

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
# A fence may open after a list marker ("- ```"); it then also ends where that list item ends.
FENCE_OPEN_RE = re.compile(r"^\s*(?:(?:[-+*]|\d{1,9}[.)])\s+)?(`{3,}|~{3,})(.*)$")
INLINE_CODE_RE = re.compile(r"(`+).*?\1")
INLINE_LINK_RE = re.compile(
    r"(?<!!)\[(?:[^\[\]]|\[[^\[\]]*\])*\]"
    r"\(\s*(<[^>\n]*>|[^\s()]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
REF_DEF_RE = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*(<[^>\n]*>|\S+)")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


class ToolError(Exception):
    """The checker could not inspect the repository."""


@dataclass(frozen=True)
class Report:
    reachable: tuple[str, ...]
    orphans: tuple[str, ...]
    whole_tree_orphan_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "scope": SCOPE,
            "seeds": list(SEEDS),
            "candidate_count": len(self.reachable) + len(self.orphans),
            "reachable_count": len(self.reachable),
            "reachable": list(self.reachable),
            "orphans": list(self.orphans),
            "orphan_count": len(self.orphans),
            "whole_tree_orphan_count": self.whole_tree_orphan_count,
        }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git(root: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError(f"git {args[0]} failed in {root}: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise ToolError(f"git {args[0]} failed in {root}: {stderr}")
    return proc.stdout


def tracked_markdown(root: Path) -> set[str]:
    """Repo-relative paths of Markdown files in the git index."""
    paths: set[str] = set()
    for raw in git(root, "ls-files", "-z").split(b"\0"):
        try:
            path = raw.decode("utf-8")
        except UnicodeDecodeError:
            shown = raw.decode("utf-8", errors="backslashreplace")
            raise ToolError(
                f"tracked path is not valid UTF-8: {shown} (rename it or remove it from the index)"
            ) from None
        if path.endswith(".md"):
            paths.add(path)
    return paths


def require_toplevel(root: Path) -> None:
    """A root below the worktree top-level would silently report no candidates."""
    toplevel = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel").rstrip(b"\n")))
    if not toplevel.samefile(root):
        raise ToolError(f"--root {root} is not the git worktree top-level; use --root {toplevel}")


def prose_lines(text: str) -> list[str]:
    """Lines outside fenced code blocks, with inline code spans removed."""
    lines: list[str] = []
    fence: str | None = None
    item_indent = 0
    for line in text.splitlines():
        if fence and item_indent and line.strip() and len(line) - len(line.lstrip()) < item_indent:
            fence = None
        match = (FENCE_OPEN_RE if fence is None else FENCE_RE).match(line)
        if fence is None:
            # A backtick fence's info string cannot contain backticks (CommonMark).
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                fence = match.group(1)
                item_indent = match.start(1) if line[: match.start(1)].strip() else 0
                continue
            lines.append(INLINE_CODE_RE.sub("", line))
        elif (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= len(fence)
            and not match.group(2).strip()
        ):
            fence = None
    return lines


def link_targets(text: str) -> list[str]:
    """Raw inline-link and reference-definition targets, in document order."""
    targets: list[str] = []
    for line in prose_lines(text):
        targets.extend(match.group(1) for match in INLINE_LINK_RE.finditer(line))
        definition = REF_DEF_RE.match(line)
        if definition and not definition.group(1).startswith("^"):
            targets.append(definition.group(2))
    return targets


def resolve_target(source: str, raw: str, pages: set[str]) -> str | None:
    """Map a link target in ``source`` to a traversable page, if any."""
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith(("#", "//")) or SCHEME_RE.match(target):
        return None
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(source), path)
    normalized = posixpath.normpath(joined)
    if normalized == ".." or normalized.startswith("../"):
        return None
    for candidate in (normalized, posixpath.join(normalized, "README.md")):
        candidate = posixpath.normpath(candidate)
        if candidate in pages:
            return candidate
    return None


def is_curated(path: str) -> bool:
    parts = path.split("/")
    if parts[0] != "docs" or len(parts) < 2:
        return False
    return len(parts) == 2 or parts[1] in CURATED_DIRS


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def analyze(root: Path) -> Report:
    pages = {p for p in tracked_markdown(root) if not p.startswith(ARCHIVE_PREFIX)}
    require_toplevel(root)
    for seed in SEEDS:
        if seed not in pages:
            print(f"check_docs_reachability: warning: seed {seed} is not tracked", file=sys.stderr)
    reached = {seed for seed in SEEDS if seed in pages}
    queue = deque(sorted(reached))
    while queue:
        source = queue.popleft()
        for raw in link_targets(read_text(root / source)):
            target = resolve_target(source, raw, pages)
            if target is not None and target not in reached:
                reached.add(target)
                queue.append(target)
    candidates = sorted(p for p in pages if is_curated(p))
    unreached_docs = [p for p in pages if p.startswith("docs/") and p not in reached]
    return Report(
        reachable=tuple(p for p in candidates if p in reached),
        orphans=tuple(p for p in candidates if p not in reached),
        whole_tree_orphan_count=len(unreached_docs),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_docs_reachability.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scope",
        choices=(SCOPE,),
        default=SCOPE,
        help="candidate set to gate (only 'curated' is defined; default: curated)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the schema v1 JSON report on stdout"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root(),
        help="git worktree top-level to inspect; anything else is a tool error (exit 2) "
        "(default: the checkout containing this script)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = analyze(args.root.resolve())
    except ToolError as exc:
        print(f"check_docs_reachability: error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(
            f"check_docs_reachability: scope={SCOPE} seeds={', '.join(SEEDS)} "
            f"candidates={len(report.reachable) + len(report.orphans)} "
            f"reachable={len(report.reachable)} orphans={len(report.orphans)}"
        )
        for orphan in report.orphans:
            print(f"  orphan: {orphan}")
        print(f"whole-tree orphans (informational): {report.whole_tree_orphan_count}")
    return 1 if report.orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
