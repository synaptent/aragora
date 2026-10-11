"""
OpenClaw Migration Utilities.

Provides tools for gradual migration between OpenClaw and Aragora:
- Migration modes (OpenClaw-only, Aragora-only, prefer-Aragora, parallel)
- Batch skill import from directories
- Skill export to SKILL.md format
- Migration context for routing decisions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from aragora.skills.base import Skill

from .skill_converter import OpenClawBridgeSkill, OpenClawSkillConverter
from .skill_parser import OpenClawSkillParser, ParsedOpenClawSkill

logger = logging.getLogger(__name__)


class MigrationMode(str, Enum):
    """Migration mode for skill routing."""

    OPENCLAW_ONLY = "openclaw_only"  # All skills run via OpenClaw
    ARAGORA_ONLY = "aragora_only"  # All skills run natively in Aragora
    PREFER_ARAGORA = "prefer_aragora"  # Use Aragora native if available, fallback to OpenClaw
    PARALLEL = "parallel"  # Run both and compare results


@dataclass
class MigrationState:
    """Tracks migration state for a set of skills."""

    mode: MigrationMode = MigrationMode.PREFER_ARAGORA
    imported_skills: dict[str, OpenClawBridgeSkill] = field(default_factory=dict)
    native_overrides: dict[str, Skill] = field(default_factory=dict)
    migration_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_skills(self) -> int:
        return len(self.imported_skills)

    @property
    def migrated_count(self) -> int:
        return len(self.native_overrides)

    @property
    def migration_percentage(self) -> float:
        if not self.imported_skills:
            return 100.0
        return (self.migrated_count / self.total_skills) * 100.0


class MigrationContext:
    """
    Routes skill invocations based on migration state.

    In PREFER_ARAGORA mode, checks for a native Aragora skill first
    and falls back to the OpenClaw bridge skill if none exists.
    """

    def __init__(self, state: MigrationState | None = None):
        self._state = state or MigrationState()

    @property
    def state(self) -> MigrationState:
        return self._state

    def resolve_skill(self, skill_name: str) -> Skill | None:
        """
        Resolve which skill implementation to use.

        Args:
            skill_name: Name of the skill to resolve.

        Returns:
            The appropriate Skill instance, or None if not found.
        """
        mode = self._state.mode

        if mode == MigrationMode.ARAGORA_ONLY:
            return self._state.native_overrides.get(skill_name)

        if mode == MigrationMode.OPENCLAW_ONLY:
            return self._state.imported_skills.get(skill_name)

        if mode == MigrationMode.PREFER_ARAGORA:
            native = self._state.native_overrides.get(skill_name)
            if native:
                return native
            return self._state.imported_skills.get(skill_name)

        if mode == MigrationMode.PARALLEL:
            # In parallel mode, prefer native for execution but both are available
            return self._state.native_overrides.get(
                skill_name,
                self._state.imported_skills.get(skill_name),
            )

        return None

    def register_native(self, skill_name: str, skill: Skill) -> None:
        """
        Register a native Aragora skill as a replacement.

        Args:
            skill_name: Name to register under (should match OpenClaw skill name).
            skill: The native Aragora Skill instance.
        """
        self._state.native_overrides[skill_name] = skill
        self._state.migration_log.append(
            {
                "action": "register_native",
                "skill_name": skill_name,
                "skill_type": type(skill).__name__,
            }
        )
        logger.info(
            "Registered native override for '%s' (%.0f%% migrated)",
            skill_name,
            self._state.migration_percentage,
        )

    def import_skill(self, parsed: ParsedOpenClawSkill) -> OpenClawBridgeSkill:
        """
        Import a parsed OpenClaw skill.

        Args:
            parsed: Parsed SKILL.md data.

        Returns:
            The converted bridge skill.
        """
        bridge = OpenClawSkillConverter.convert(parsed)
        name = parsed.name or bridge.manifest.name
        self._state.imported_skills[name] = bridge
        self._state.migration_log.append(
            {
                "action": "import",
                "skill_name": name,
                "requires": parsed.requires,
            }
        )
        return bridge


def import_openclaw_skills(
    directory: str | Path,
    context: MigrationContext | None = None,
) -> list[OpenClawBridgeSkill]:
    """
    Batch import OpenClaw skills from a directory.

    Args:
        directory: Path to search for SKILL.md files.
        context: Optional migration context to register imported skills.

    Returns:
        List of converted bridge skills.
    """
    parsed_skills = OpenClawSkillParser.parse_directory(directory)
    results: list[OpenClawBridgeSkill] = []

    for parsed in parsed_skills:
        if context:
            bridge = context.import_skill(parsed)
        else:
            bridge = OpenClawSkillConverter.convert(parsed)
        results.append(bridge)

    logger.info("Imported %s OpenClaw skills from %s", len(results), directory)
    return results


def export_to_openclaw(skill: Skill, output_dir: str | Path) -> Path:
    """
    Export an Aragora skill to OpenClaw SKILL.md format.

    Args:
        skill: The Aragora Skill to export.
        output_dir: Directory to write the SKILL.md file.

    Returns:
        Path to the created SKILL.md file.
    """
    output = Path(output_dir)
    skill_dir = output / skill.manifest.name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_md = OpenClawSkillConverter.to_skill_md(skill)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(skill_md, encoding="utf-8")

    logger.info("Exported skill '%s' to %s", skill.manifest.name, skill_file)
    return skill_file
