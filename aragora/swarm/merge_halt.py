"""The main-red merge halt that every automated merge path must obey (#9216).

``.aragora/merge_executor.halt`` is armed when main is red (by
``scripts/pristine_main_health.py`` or ``scripts/merge_executor.py``) and stays
armed until a human deletes it. Only ``merge_executor.py`` used to read it, so
PRs #9115 and #9111 merged on 2026-07-11 while the marker was armed and
byte-identical before and after: nothing on the merging path opened the file.

Every merge-capable path calls :func:`evaluate_merge_halt` or
:func:`assert_merge_allowed` for the exact PR head it is about to merge.
``tests/swarm/test_merge_halt_guard.py`` keeps an inventory of those paths and
fails when a new merge path appears or an existing one stops calling the guard.

Everything fails closed. An armed halt, a marker that exists but cannot be read,
and a waiver that is missing, corrupt, expired, or for another PR or head all
block. The only way to merge while halted is a waiver at
``.aragora/merge_executor.waiver`` that names this PR and this full head SHA::

    {
      "pr": 9115,
      "head_sha": "<full 40-character head SHA>",
      "actor": "<operator login>",
      "scope": "single-pr",
      "reason": "<why this head may merge while main is red>",
      "expires_at": "2026-07-11T12:00:00+00:00"
    }

A force-push invalidates the waiver because the head no longer matches.

``merge_executor.py`` keeps its own existence-based check on its ``--halt-file``
and does not honour waivers, so a waived PR can still be refused there. That
asymmetry is deliberately fail-closed: the path that writes the marker stays the
strictest reader of it.

The markers resolve against the primary checkout, not a linked worktree's own
``.aragora`` directory, because main-health automation arms one repository-wide
halt and merges run from many worktrees.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _shared_checkout_root(repo_root: Path) -> Path:
    """Return the primary checkout root for a normal checkout or a linked worktree.

    Raises ``RuntimeError`` on malformed linked-worktree metadata so callers can
    fail closed instead of silently reading a worktree-local marker.
    """
    dot_git = repo_root / ".git"
    try:
        mode = os.stat(dot_git).st_mode
    except FileNotFoundError:
        return repo_root
    except OSError as exc:
        raise RuntimeError(f"could not inspect git metadata at {dot_git}: {exc}") from exc

    if stat.S_ISDIR(mode):
        return repo_root
    if not stat.S_ISREG(mode):
        raise RuntimeError(f"git metadata at {dot_git} is neither a file nor a directory")

    try:
        marker = dot_git.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if not marker.lower().startswith(prefix):
            raise ValueError("missing gitdir marker")
        git_dir = Path(marker[len(prefix) :].strip())
        if not git_dir.is_absolute():
            git_dir = (repo_root / git_dir).resolve()
        common_raw = (git_dir / "commondir").read_text(encoding="utf-8").strip()
        if not common_raw:
            raise ValueError("empty commondir")
        common_dir = Path(common_raw)
        if not common_dir.is_absolute():
            common_dir = (git_dir / common_dir).resolve()
        if not (common_dir / "objects").is_dir():
            raise ValueError(f"invalid common git directory {common_dir}")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"could not resolve shared git state from {dot_git}: {exc}") from exc
    return common_dir.parent


# Raising at import time would fail closed for merges but fail open for the
# writer: pristine_main_health.py imports DEFAULT_HALT_FILE at module level, so a
# raise would crash the lane that arms the halt. Degrade to the local checkout
# instead and record the error; evaluate_merge_halt() then refuses every merge
# that relies on the unresolved default location.
try:
    SHARED_REPO_ROOT = _shared_checkout_root(_REPO_ROOT)
    SHARED_ROOT_ERROR: str | None = None
except RuntimeError as _exc:
    SHARED_REPO_ROOT = _REPO_ROOT
    SHARED_ROOT_ERROR = str(_exc)

DEFAULT_HALT_FILE = SHARED_REPO_ROOT / ".aragora" / "merge_executor.halt"
DEFAULT_WAIVER_FILE = SHARED_REPO_ROOT / ".aragora" / "merge_executor.waiver"


class MergeHalted(RuntimeError):
    """Raised when a merge is attempted while the halt blocks it."""


@dataclass(frozen=True)
class HaltDecision:
    allowed: bool
    reason: str
    halt_reason: str | None = None
    waiver_actor: str | None = None


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(payload, error)``; only a missing file counts as absent.

    ``Path.exists()`` returns False on any ``OSError``, which would present an
    armed marker behind an unreadable directory as absent. ``os.stat`` lets only
    ``FileNotFoundError`` mean "no marker".
    """
    try:
        os.stat(path)
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"{path.name} could not be inspected ({exc})"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{path.name} exists but could not be read ({exc})"
    if not isinstance(data, dict):
        return None, f"{path.name} is not a JSON object"
    return data, None


def _waiver_applies(
    waiver: dict[str, Any], *, pr: int, head_sha: str, now: dt.datetime
) -> tuple[bool, str]:
    """Return ``(True, actor)`` for an exact-head waiver, else ``(False, why)``."""
    waiver_pr = waiver.get("pr")
    if isinstance(waiver_pr, bool) or not isinstance(waiver_pr, int):
        return False, f"waiver pr must be an integer, got {waiver_pr!r}"
    fields: dict[str, str] = {}
    for key in ("head_sha", "actor", "scope", "reason", "expires_at"):
        value = waiver.get(key)
        if not isinstance(value, str):
            return False, f"waiver {key} must be a string, got {value!r}"
        fields[key] = value.strip()
    waiver_head = fields["head_sha"].lower()
    actor = fields["actor"]
    scope = fields["scope"]
    reason = fields["reason"]
    expires_raw = fields["expires_at"]

    if not actor:
        return False, "waiver has an empty actor"
    if not reason:
        return False, "waiver has an empty reason"
    if scope != "single-pr":
        return False, f"waiver scope must be 'single-pr', got {scope!r}"
    if waiver_pr != pr:
        return False, f"waiver is for PR #{waiver_pr}, not #{pr}"

    # Both sides must be full SHAs: two equal abbreviations would otherwise let
    # one waiver cover every commit sharing that prefix.
    head = str(head_sha or "").strip().lower()
    for label, value in (("waiver", waiver_head), ("merge", head)):
        if not _FULL_SHA_RE.fullmatch(value):
            return False, f"{label} head {value[:12] or '(empty)'!r} is not a full 40-char SHA"
    if waiver_head != head:
        return False, f"waiver head {waiver_head[:12]} != merge head {head[:12]}"

    try:
        expires = dt.datetime.fromisoformat(expires_raw)
    except ValueError:
        return False, f"waiver expires_at is not ISO-8601 ({expires_raw!r})"
    if expires.tzinfo is None:
        return False, "waiver expires_at must include an explicit timezone"
    if expires <= now:
        return False, f"waiver expired at {expires.isoformat()}"

    return True, actor


def evaluate_merge_halt(
    pr: int,
    head_sha: str,
    *,
    halt_file: Path | None = None,
    waiver_file: Path | None = None,
    now: dt.datetime | None = None,
) -> HaltDecision:
    """Decide whether ``pr`` may merge at exactly ``head_sha`` right now."""
    # Without the shared checkout the default marker path points into this
    # worktree, and an armed halt could sit where we are not looking.
    if halt_file is None and SHARED_ROOT_ERROR is not None:
        return HaltDecision(
            False,
            "cannot resolve the shared checkout, so the halt marker location is unknown; "
            f"failing closed ({SHARED_ROOT_ERROR})",
        )
    halt_path = halt_file or DEFAULT_HALT_FILE
    waiver_path = waiver_file or DEFAULT_WAIVER_FILE
    moment = now or dt.datetime.now(dt.timezone.utc)

    halt, halt_error = _read_json(halt_path)
    if halt_error:
        return HaltDecision(False, f"halt marker unreadable, failing closed: {halt_error}")
    if halt is None:
        return HaltDecision(True, "no halt marker present")

    halt_reason = str(halt.get("reason") or "unknown")
    waiver, waiver_error = _read_json(waiver_path)
    if waiver_error:
        return HaltDecision(
            False, f"halt armed ({halt_reason}); {waiver_error}", halt_reason=halt_reason
        )
    if waiver is None:
        return HaltDecision(
            False, f"halt armed ({halt_reason}) and no waiver present", halt_reason=halt_reason
        )

    applies, detail = _waiver_applies(waiver, pr=pr, head_sha=head_sha, now=moment)
    if not applies:
        return HaltDecision(False, f"halt armed ({halt_reason}); {detail}", halt_reason=halt_reason)
    return HaltDecision(
        True,
        f"halt armed ({halt_reason}) but waived for PR #{pr} at {head_sha[:12]} by {detail}",
        halt_reason=halt_reason,
        waiver_actor=detail,
    )


def assert_merge_allowed(
    pr: int,
    head_sha: str,
    *,
    halt_file: Path | None = None,
    waiver_file: Path | None = None,
    now: dt.datetime | None = None,
) -> HaltDecision:
    """Raise :class:`MergeHalted` unless ``pr`` may merge at ``head_sha``."""
    decision = evaluate_merge_halt(
        pr, head_sha, halt_file=halt_file, waiver_file=waiver_file, now=now
    )
    if not decision.allowed:
        raise MergeHalted(f"refusing to merge PR #{pr}: {decision.reason}")
    return decision
