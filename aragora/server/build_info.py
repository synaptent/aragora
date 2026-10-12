"""
Build information for deploy verification.

Provides the current build SHA, build time, and deploy version.
These values are embedded at build time via environment variables
or computed at startup as a fallback.

Environment variables (set in CI/CD):
- ARAGORA_BUILD_SHA: Git commit SHA at build time
- ARAGORA_BUILD_TIME: ISO 8601 timestamp of the build
- ARAGORA_DEPLOY_VERSION: Semantic version or tag name
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)

# These are set at build time via environment variables in CI/CD.
# At runtime they are read once and cached.
_BUILD_SHA = os.environ.get("ARAGORA_BUILD_SHA", "")
_BUILD_TIME = os.environ.get("ARAGORA_BUILD_TIME", "")
_DEPLOY_VERSION = os.environ.get("ARAGORA_DEPLOY_VERSION", "")


def _git_sha_fallback() -> str:
    """Try to get git SHA from the local repo as a fallback."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # fixed command
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "unknown"


@lru_cache(maxsize=1)
def get_build_info() -> dict[str, str]:
    """Return build information.

    Values are resolved once and cached for the lifetime of the process.
    Priority: environment variable > git fallback > "unknown".
    """
    sha = _BUILD_SHA or _git_sha_fallback()
    build_time = _BUILD_TIME or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    version = _DEPLOY_VERSION or "dev"

    return {
        "sha": sha,
        "build_time": build_time,
        "version": version,
        "sha_short": sha[:8] if sha and sha != "unknown" else "unknown",
    }


def verify_sha(expected_sha: str) -> dict[str, object]:
    """Verify the running build matches an expected SHA.

    Returns a dict with match status and details.
    """
    info = get_build_info()
    current = info["sha"]
    # Support both full and short SHA comparison
    matches = (
        current != "unknown"
        and expected_sha != ""
        and (current.startswith(expected_sha) or expected_sha.startswith(current))
    )
    return {
        "matches": matches,
        "expected": expected_sha,
        "current": current,
        "current_short": info["sha_short"],
    }
