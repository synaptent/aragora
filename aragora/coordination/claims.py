"""Advisory file claim protocol for multi-agent coordination.

Agents claim file paths before editing.  Claims are **advisory** — they warn
about overlap but never block.  This gives agents enough information to avoid
conflicts without introducing locks or deadlocks.

Usage::

    from aragora.coordination.claims import ClaimManager

    mgr = ClaimManager(repo_path=Path("."))
    result = mgr.claim(["aragora/server/auth.py"], session_id="claude-abc1", intent="OIDC refactor")
    # result.status == "granted" or "contested"
    mgr.release("claude-abc1")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_COORD_DIR = ".aragora_coordination"
_CLAIMS_DIR = "claims"


class ClaimStatus(str, Enum):
    """Result of a claim attempt."""

    GRANTED = "granted"
    CONTESTED = "contested"


@dataclass
class FileClaim:
    """A single file claim by an agent session."""

    claim_id: str
    session_id: str
    paths: list[str]
    intent: str
    claimed_at: float
    ttl_minutes: int = 30
    released: bool = False

    @property
    def expires_at(self) -> float:
        return self.claimed_at + (self.ttl_minutes * 60)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_active(self) -> bool:
        return not self.released and not self.is_expired

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["expires_at"] = self.expires_at
        return d

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> FileClaim:
        return cls(
            claim_id=str(data.get("claim_id", "")),
            session_id=str(data.get("session_id", "")),
            paths=list(data.get("paths", [])),  # type: ignore[arg-type]
            intent=str(data.get("intent", "")),
            claimed_at=float(data.get("claimed_at", 0)),
            ttl_minutes=int(data.get("ttl_minutes", 30)),
            released=bool(data.get("released", False)),
        )


@dataclass
class ClaimResult:
    """Result of a claim attempt."""

    status: ClaimStatus
    claim: FileClaim
    contested_by: list[FileClaim] = field(default_factory=list)
    contested_paths: list[str] = field(default_factory=list)


class ClaimManager:
    """File-backed advisory claim manager.

    Claims are stored as JSON files in ``.aragora_coordination/claims/``.
    Supports glob patterns (e.g. ``sdk/**``) and exact paths.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        *,
        default_ttl_minutes: int = 30,
    ):
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self._claims_dir = self.repo_path / _COORD_DIR / _CLAIMS_DIR
        self._default_ttl = default_ttl_minutes

    def _ensure_dir(self) -> Path:
        self._claims_dir.mkdir(parents=True, exist_ok=True)
        return self._claims_dir

    def _load_active_claims(self) -> list[FileClaim]:
        """Load all non-expired, non-released claims."""
        if not self._claims_dir.exists():
            return []

        claims: list[FileClaim] = []
        for path in self._claims_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                c = FileClaim.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

            if c.is_active:
                claims.append(c)
            elif c.is_expired:
                # Auto-clean expired claims
                path.unlink(missing_ok=True)

        return claims

    @staticmethod
    def _paths_overlap(claimed: list[str], requested: list[str]) -> list[str]:
        """Find overlapping paths between two claim sets.

        Supports both exact matches and glob patterns.
        """
        overlaps: list[str] = []
        for req in requested:
            for existing in claimed:
                if req == existing:
                    overlaps.append(req)
                elif fnmatch(req, existing) or fnmatch(existing, req):
                    overlaps.append(req)
        return list(dict.fromkeys(overlaps))  # dedupe preserving order

    def claim(
        self,
        paths: list[str],
        session_id: str,
        *,
        intent: str = "",
        ttl_minutes: int | None = None,
    ) -> ClaimResult:
        """Attempt to claim file paths.

        Args:
            paths: File paths or glob patterns to claim.
            session_id: ID of the claiming session.
            intent: Human-readable description of what the agent plans to do.
            ttl_minutes: Override default TTL for this claim.

        Returns:
            ClaimResult with status and any contested claims.
        """
        active = self._load_active_claims()

        # Find contests (other sessions claiming overlapping paths)
        contested_by: list[FileClaim] = []
        contested_paths: list[str] = []
        for existing in active:
            if existing.session_id == session_id:
                continue
            overlap = self._paths_overlap(existing.paths, paths)
            if overlap:
                contested_by.append(existing)
                contested_paths.extend(overlap)

        contested_paths = list(dict.fromkeys(contested_paths))

        # Create the claim regardless (advisory — never block)
        now = time.time()
        new_claim = FileClaim(
            claim_id=str(uuid4())[:12],
            session_id=session_id,
            paths=paths,
            intent=intent,
            claimed_at=now,
            ttl_minutes=ttl_minutes or self._default_ttl,
        )

        d = self._ensure_dir()
        claim_path = d / f"{new_claim.claim_id}.json"
        claim_path.write_text(
            json.dumps(new_claim.to_dict(), default=str),
            encoding="utf-8",
        )

        status = ClaimStatus.CONTESTED if contested_by else ClaimStatus.GRANTED

        if contested_by:
            logger.warning(
                "claim_contested session=%s paths=%s contested_by=%s",
                session_id,
                contested_paths,
                [c.session_id for c in contested_by],
            )
        else:
            logger.debug("claim_granted session=%s paths=%s", session_id, paths)

        return ClaimResult(
            status=status,
            claim=new_claim,
            contested_by=contested_by,
            contested_paths=contested_paths,
        )

    def release(self, session_id: str) -> int:
        """Release all claims held by a session. Returns count released."""
        if not self._claims_dir.exists():
            return 0

        released = 0
        for path in self._claims_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("session_id") == session_id:
                    path.unlink(missing_ok=True)
                    released += 1
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        if released:
            logger.info("claims_released session=%s count=%d", session_id, released)
        return released

    def check(self, paths: list[str]) -> list[FileClaim]:
        """Check which active claims overlap with the given paths."""
        active = self._load_active_claims()
        holders: list[FileClaim] = []
        for c in active:
            if self._paths_overlap(c.paths, paths):
                holders.append(c)
        return holders

    def list_all(self) -> list[FileClaim]:
        """List all active (non-expired, non-released) claims."""
        return self._load_active_claims()


__all__ = [
    "ClaimManager",
    "ClaimResult",
    "ClaimStatus",
    "FileClaim",
]
