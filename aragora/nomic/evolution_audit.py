"""
Evolution Audit — tracks agent prompt and configuration modifications.

Logs every change made to agent prompts or configurations during Nomic Loop
autonomous self-improvement cycles to an append-only JSONL file for audit
and rollback purposes.

Storage: <base_path>/.aragora_beads/evolution_audit.jsonl
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LOG_FILENAME = "evolution_audit.jsonl"


class EvolutionAudit:
    """Append-only audit log for agent prompt and configuration modifications.

    Each modification is stored as a single JSON object on its own line
    (JSONL format) in `.aragora_beads/evolution_audit.jsonl` relative to
    the given base path.

    Usage::

        audit = EvolutionAudit(base_path=Path("."))
        await audit.log_modification(
            agent="claude",
            field="system_prompt",
            before="old prompt",
            after="new prompt",
            reason="Nomic cycle #5 improvement",
        )

        history = await audit.get_history(agent="claude")
    """

    def __init__(
        self,
        base_path: Path | None = None,
        filename: str = _DEFAULT_LOG_FILENAME,
    ) -> None:
        self._base_path = Path(base_path) if base_path is not None else Path.cwd()
        self._filename = filename

    @property
    def _log_path(self) -> Path:
        """Absolute path to the JSONL audit log file."""
        return self._base_path / ".aragora_beads" / self._filename

    async def log_modification(
        self,
        agent: str,
        field: str,
        before: str,
        after: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append a single modification record to the audit log.

        Args:
            agent: Name of the agent whose prompt/config was modified.
            field: The field that was changed (e.g. "system_prompt", "instructions").
            before: Previous value.
            after: New value.
            reason: Human-readable explanation for the modification.
            extra: Optional additional metadata to include in the record.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "field": field,
            "before": before,
            "after": after,
            "reason": reason,
        }
        if extra:
            entry["extra"] = extra  # namespace under dedicated key to preserve required fields

        log_path = self._log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("EvolutionAudit: failed to write entry: %s", exc)

    async def get_history(
        self,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read the audit log and return modification records.

        Args:
            agent: If provided, only return entries for this agent name.

        Returns:
            List of dicts, one per modification, in chronological order.
            Returns empty list if the log file does not exist.
        """
        log_path = self._log_path
        if not log_path.exists():
            return []

        results: list[dict[str, Any]] = []
        try:
            with open(log_path, encoding="utf-8") as fh:
                for line_number, raw_line in enumerate(fh, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "EvolutionAudit: skipping malformed line %d: %s",
                            line_number,
                            exc,
                        )
                        continue

                    if agent is None or entry.get("agent") == agent:
                        results.append(entry)
        except OSError as exc:
            logger.warning("EvolutionAudit: failed to read log: %s", exc)

        return results
