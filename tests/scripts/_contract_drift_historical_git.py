from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PR_9320_HEAD_REF = "refs/pull/9320/head"
PR_9320_LOCAL_REF = "refs/cdg-historical-backfill/9320/head"
PR_9320_HEAD_SHA = "aba6b14c94eca3a9c825b1a303ea67684d5f8daa"
HISTORICAL_HEAD_FETCH_ENV = "ARAGORA_CDG_FETCH_HISTORICAL_HEAD"


def _historical_head_fetch_allowed() -> bool:
    # The historical head is squash-merged, so ordinary clones (including the
    # default actions/checkout) never carry it; fetching refs/pull/*/head is a
    # live-network step that must stay opt-in outside CI.
    if os.environ.get(HISTORICAL_HEAD_FETCH_ENV) == "1":
        return True
    return os.environ.get("GITHUB_ACTIONS") == "true"


def ensure_pr_9320_head(
    repo_root: Path,
    *,
    remote: str = "origin",
    expected_sha: str = PR_9320_HEAD_SHA,
) -> str:
    """Fetch and authenticate the historical PR head missing from ordinary clones.

    When the object is absent locally, the fetch of ``refs/pull/9320/head``
    runs only under ``ARAGORA_CDG_FETCH_HISTORICAL_HEAD=1`` or
    ``GITHUB_ACTIONS=true``; otherwise the calling test skips with a reason
    naming the opt-in instead of dialing the network.
    """
    probe = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{expected_sha}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        if not _historical_head_fetch_allowed():
            pytest.skip(
                f"historical head {expected_sha} is absent locally and fetching "
                f"{PR_9320_HEAD_REF} from {remote!r} needs the network; set "
                f"{HISTORICAL_HEAD_FETCH_ENV}=1 to opt in (CI opts in via GITHUB_ACTIONS=true)"
            )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "fetch",
                "--no-tags",
                "--force",
                remote,
                f"{PR_9320_HEAD_REF}:{PR_9320_LOCAL_REF}",
            ],
            check=True,
        )
        ref = PR_9320_LOCAL_REF
    else:
        ref = expected_sha
    resolved = subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        text=True,
    ).strip()
    if resolved != expected_sha:
        raise AssertionError(f"{PR_9320_HEAD_REF} resolved to {resolved}, expected {expected_sha}")
    return resolved
