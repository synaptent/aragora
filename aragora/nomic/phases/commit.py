"""
Commit phase for nomic loop.

Phase 5: Commit changes if verified
- Human approval check (if required)
- Git add and commit
- Commit hash tracking
- Structured commit gate with audit trail
"""

import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from collections.abc import Callable

logger = logging.getLogger(__name__)

from . import CommitResult

if TYPE_CHECKING:
    from aragora.nomic.gates import CommitGate


def _is_auto_commit_enabled() -> bool:
    """Read auto-commit flag at runtime (supports test monkeypatching)."""
    return os.environ.get("NOMIC_AUTO_COMMIT", "0") == "1"


class CommitPhase:
    """
    Handles committing verified changes to git.

    Supports human approval workflow and auto-commit mode.
    """

    def __init__(
        self,
        aragora_path: Path,
        require_human_approval: bool = True,
        auto_commit: bool = False,
        cycle_count: int = 0,
        log_fn: Callable[[str], None] | None = None,
        stream_emit_fn: Callable[..., None] | None = None,
        commit_gate: Optional["CommitGate"] = None,
        cycle_outcome: Any | None = None,
    ):
        """
        Initialize the commit phase.

        Args:
            aragora_path: Path to the aragora project root
            require_human_approval: Whether to require human approval for commits
            auto_commit: Whether to auto-commit without prompting
            cycle_count: Current cycle number
            log_fn: Function to log messages
            stream_emit_fn: Function to emit streaming events
            commit_gate: Optional CommitGate for structured approval with audit trail
            cycle_outcome: Optional NomicCycleOutcome to persist to KM after commit
        """
        self.aragora_path = aragora_path
        self.require_human_approval = require_human_approval
        self.auto_commit = auto_commit
        self.cycle_count = cycle_count
        self._log = log_fn or print
        self._stream_emit = stream_emit_fn or (lambda *args: None)
        self._commit_gate = commit_gate
        self._cycle_outcome = cycle_outcome

    async def execute(self, improvement: str) -> CommitResult:
        """
        Execute the commit phase.

        Args:
            improvement: Description of the improvement being committed

        Returns:
            CommitResult with commit status and hash
        """
        phase_start = datetime.now()
        self._log("\n" + "=" * 70)
        self._log("PHASE 5: COMMIT")
        self._log("=" * 70)
        self._stream_emit("on_phase_start", "commit", self.cycle_count, {})

        # === SAFETY: Commit approval gate ===
        gate_decision = None
        gate_approved = False
        if self._commit_gate:
            try:
                from aragora.nomic.gates import ApprovalRequired, ApprovalStatus

                gate_context = {
                    "files_changed": [],
                    "improvement_summary": improvement[:200],
                }
                commit_info = improvement[:500]

                gate_decision = await self._commit_gate.require_approval(commit_info, gate_context)

                if gate_decision.status == ApprovalStatus.APPROVED:
                    gate_approved = True
                    self._log(f"  [gate] Commit approved by {gate_decision.approver}")
                elif gate_decision.status == ApprovalStatus.SKIPPED:
                    self._log("  [gate] Commit gate skipped (disabled)")

            except ApprovalRequired as e:
                self._log(f"  [gate] Commit approval denied: {e}")
                phase_duration = (datetime.now() - phase_start).total_seconds()
                self._stream_emit(
                    "on_phase_end",
                    "commit",
                    self.cycle_count,
                    False,
                    phase_duration,
                    {"reason": "gate_declined", "gate": "commit"},
                )
                return CommitResult(
                    success=False,
                    data={
                        "reason": "gate_declined",
                        "message": "Commit gate declined",
                        "gate": "commit",
                    },
                    duration_seconds=phase_duration,
                    commit_hash=None,
                    committed=False,
                )
            except (RuntimeError, ValueError, OSError) as gate_error:
                self._log(f"  [gate] Gate check error: {gate_error}, falling back to legacy")
                # Fall through to legacy approval

        # Legacy approval check if gate not used/failed/skipped
        if not gate_approved and self.require_human_approval and not self.auto_commit:
            approval = self._get_approval()
            if not approval:
                phase_duration = (datetime.now() - phase_start).total_seconds()
                self._stream_emit(
                    "on_phase_end",
                    "commit",
                    self.cycle_count,
                    False,
                    phase_duration,
                    {"reason": "human_declined"},
                )
                return CommitResult(
                    success=False,
                    data={"reason": "Human declined"},
                    duration_seconds=phase_duration,
                    commit_hash=None,
                    committed=False,
                )

        summary = improvement.replace("\n", " ")

        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],  # noqa: S607 -- fixed command
                cwd=self.aragora_path,
                check=True,
            )

            # Commit
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [  # noqa: S607 -- fixed command
                    "git",
                    "commit",
                    "-m",
                    f"feat(nomic): {summary}\n\n🤖 Auto-generated by aragora nomic loop",
                ],
                cwd=self.aragora_path,
                capture_output=True,
                text=True,
            )

            committed = result.returncode == 0
            commit_hash = None

            if committed:
                self._log(f"  Committed: {summary}")
                # Get commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 -- fixed command
                    cwd=self.aragora_path,
                    capture_output=True,
                    text=True,
                )
                commit_hash = "unknown"
                if hash_result.returncode == 0:
                    hash_candidate = hash_result.stdout.strip()
                    if self._looks_like_short_hash(hash_candidate):
                        commit_hash = hash_candidate
                    else:
                        # Retry once for compatibility with mixed/mock subprocess flows.
                        retry_hash_result = subprocess.run(
                            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 -- fixed command
                            cwd=self.aragora_path,
                            capture_output=True,
                            text=True,
                        )
                        if retry_hash_result.returncode == 0:
                            retry_candidate = retry_hash_result.stdout.strip()
                            if self._looks_like_short_hash(retry_candidate):
                                commit_hash = retry_candidate
                            elif hash_candidate:
                                commit_hash = hash_candidate
                        elif hash_candidate:
                            commit_hash = hash_candidate

                # Get files changed count
                stat_result = subprocess.run(
                    ["git", "diff", "--stat", "HEAD~1..HEAD"],  # noqa: S607 -- fixed command
                    cwd=self.aragora_path,
                    capture_output=True,
                    text=True,
                )
                files_changed = len(
                    [line for line in stat_result.stdout.split("\n") if "|" in line]
                )
                self._stream_emit("on_commit", commit_hash, summary, files_changed)

                # Persist cycle outcome to Knowledge Mound for cross-cycle learning
                if self._cycle_outcome:
                    await self._persist_to_km(commit_hash)
            else:
                self._log(f"  Commit failed: {result.stderr}")

            phase_duration = (datetime.now() - phase_start).total_seconds()
            self._stream_emit(
                "on_phase_end", "commit", self.cycle_count, committed, phase_duration, {}
            )

            return CommitResult(
                success=committed,
                data={"message": summary},
                duration_seconds=phase_duration,
                commit_hash=commit_hash,
                committed=committed,
            )

        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Commit phase error: %s", e)
            phase_duration = (datetime.now() - phase_start).total_seconds()
            error_desc = f"Commit failed: {type(e).__name__}"
            self._stream_emit(
                "on_phase_end",
                "commit",
                self.cycle_count,
                False,
                phase_duration,
                {"error": error_desc},
            )
            self._stream_emit("on_error", "commit", error_desc, True)
            return CommitResult(
                success=False,
                error=error_desc,
                data={},
                duration_seconds=phase_duration,
                commit_hash=None,
                committed=False,
            )

    def _get_approval(self) -> bool:
        """Get human approval for commit."""
        self._log("\nChanges ready for review:")
        subprocess.run(["git", "diff", "--stat"], cwd=self.aragora_path)  # noqa: S607 -- fixed command

        # Check if auto-commit is enabled or running non-interactively
        if _is_auto_commit_enabled():
            self._log("\n[commit] Auto-committing (NOMIC_AUTO_COMMIT=1)")
            return True
        elif not sys.stdin.isatty():
            self._log("\n[commit] Non-interactive mode detected, auto-commit disabled")
            self._log("[commit] Set NOMIC_AUTO_COMMIT=1 to allow unattended commits")
            return False
        else:
            # Interactive mode: prompt for approval
            response = input("\nCommit these changes? [y/N]: ")
            return response.lower() == "y"

    @staticmethod
    def _looks_like_short_hash(value: str) -> bool:
        """Check whether a value looks like a short commit-ish identifier."""
        if not isinstance(value, str):
            return False
        # Accept alphanumeric short IDs to stay compatible with mocked git outputs
        # used in tests and lightweight local wrappers.
        return bool(re.fullmatch(r"[0-9A-Za-z]{3,40}", value))

    async def _persist_to_km(self, commit_hash: str | None) -> None:
        """Persist cycle outcome to Knowledge Mound for cross-cycle learning."""
        if self._cycle_outcome is None:
            return
        try:
            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                get_nomic_cycle_adapter,
            )
            from datetime import timezone

            # Enrich outcome with commit hash
            self._cycle_outcome.metadata["commit_hash"] = commit_hash
            if not getattr(self._cycle_outcome, "completed_at", None):
                self._cycle_outcome.completed_at = datetime.now(timezone.utc)

            adapter = get_nomic_cycle_adapter()
            result = await adapter.ingest_cycle_outcome(self._cycle_outcome)
            self._log(f"  [km] Persisted cycle outcome: {result.items_ingested} items")
            self._stream_emit("on_km_persist", result.items_ingested, result.cycle_id)
        except ImportError:
            self._log("  [km] KM adapter not available, skipping persistence")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("KM persistence failed: %s", e)
            self._log(f"  [km] Persistence failed (non-fatal): {type(e).__name__}")

    def _get_changed_files(self) -> list[str]:
        """Get list of changed files."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],  # noqa: S607 -- fixed command
                cwd=self.aragora_path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        except (OSError, subprocess.SubprocessError) as e:
            self._log(f"  [git] Failed to get changed files: {e}")
        return []


__all__ = ["CommitPhase"]
