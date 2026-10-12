"""Tracked symlinks must point at paths that exist inside the repository.

GitHub stages an action repository (``uses: synaptent/aragora@<ref>``) by
unpacking its tarball, and the job's "Set up job" step fails when a tracked
symlink's target is missing. The root ``k8s`` link pointed at the deleted
``deploy/k8s`` and broke the published Action for every outside repository.
Targets are read from the git index, not the working tree, so an untracked
local directory cannot hide a dangling link.
"""

from __future__ import annotations

import posixpath
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYMLINK_MODE = "120000"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def tracked_symlinks() -> dict[str, str]:
    """Map each tracked symlink path to its target, as recorded in the index."""
    links: dict[str, str] = {}
    for entry in _git("ls-files", "-s", "-z").split("\0"):
        meta, _, path = entry.partition("\t")
        fields = meta.split(" ")
        if fields[0] == SYMLINK_MODE:
            links[path] = _git("cat-file", "blob", fields[1])
    return links


def symlink_problems(links: dict[str, str], tracked: set[str]) -> list[str]:
    problems: list[str] = []
    for path, target in sorted(links.items()):
        if posixpath.isabs(target):
            problems.append(f"{path} -> {target}: absolute target")
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        if resolved == ".." or resolved.startswith("../"):
            problems.append(f"{path} -> {target}: resolves outside the repository")
        elif resolved not in tracked and not any(f.startswith(resolved + "/") for f in tracked):
            problems.append(f"{path} -> {target}: target {resolved} is not tracked")
    return problems


def test_every_tracked_symlink_resolves_inside_the_repository() -> None:
    tracked = set(_git("ls-files", "-z").split("\0")) - {""}
    assert symlink_problems(tracked_symlinks(), tracked) == []


@pytest.mark.parametrize(
    ("link", "target", "problem"),
    [
        ("k8s", "deploy/kubernetes", None),
        ("k8s", "deploy/kubernetes/monitoring/alerts.yaml", None),
        ("docs/k8s", "../deploy/kubernetes", None),
        ("k8s", "deploy/k8s", "is not tracked"),
        ("k8s", "../outside", "resolves outside the repository"),
        ("docs/k8s", "../../outside", "resolves outside the repository"),
        ("k8s", "/etc/hosts", "absolute target"),
    ],
)
def test_symlink_problems_flags_missing_and_escaping_targets(
    link: str, target: str, problem: str | None
) -> None:
    tracked = {"deploy/kubernetes/monitoring/alerts.yaml"}
    problems = symlink_problems({link: target}, tracked)
    if problem is None:
        assert problems == []
    else:
        assert len(problems) == 1 and problem in problems[0]
