"""Compatibility re-export of :mod:`aragora.types.skills`.

The skill types moved to the foundation layer so the debate engine can use them
without importing ``aragora.skills``. Every name below is the identical object.
"""

from __future__ import annotations

from aragora.types.skills import (
    CapabilityLevel,
    Skill,
    SkillCapability,
    SkillContext,
    SkillManifest,
    SkillResult,
    SkillStatus,
    SyncSkill,
)

__all__ = [
    "CapabilityLevel",
    "Skill",
    "SkillCapability",
    "SkillContext",
    "SkillManifest",
    "SkillResult",
    "SkillStatus",
    "SyncSkill",
]
