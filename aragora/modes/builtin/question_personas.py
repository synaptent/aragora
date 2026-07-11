"""Question-persona modes composed from epistemic question batteries."""

from __future__ import annotations

from dataclasses import dataclass, field

from aragora.epistemic.question_batteries import QuestionBattery, get_question_battery
from aragora.modes.base import Mode
from aragora.modes.tool_groups import ToolGroup


def _debate_read_tools() -> ToolGroup:
    return ToolGroup.READ | ToolGroup.BROWSER | ToolGroup.DEBATE


@dataclass
class QuestionPersonaMode(Mode):
    """Read/debate-only mode that emphasizes one epistemic question stance."""

    battery_name: str = ""
    tool_groups: ToolGroup = field(default_factory=_debate_read_tools)
    file_patterns: list[str] = field(default_factory=list)
    system_prompt_additions: str = ""

    @property
    def battery(self) -> QuestionBattery:
        return get_question_battery(self.battery_name)

    def get_system_prompt(self) -> str:
        battery = self.battery
        return f"""## {battery.persona_role} Question Persona

You are operating as the {battery.persona_role}. This is a read/debate-oriented
questioning stance that composes with epistemic_hygiene, redteam, and prober
flows without adding write authority.

### Primary Question
{battery.question}

### Why It Matters
{battery.why_it_matters}

### Operating Guidance
{battery.persona_prompt}

Ask concise decision-changing questions. Do not duplicate generic epistemic
hygiene sections unless they help answer the primary question.
"""


@dataclass
class OutsiderMode(QuestionPersonaMode):
    name: str = "outsider"
    description: str = "Ask what an outside audience would need to trust the decision"
    battery_name: str = "outsider"


@dataclass
class FalsifierMode(QuestionPersonaMode):
    name: str = "falsifier"
    description: str = "Ask what observable evidence would make the decision wrong"
    battery_name: str = "falsifier"


@dataclass
class DeleterMode(QuestionPersonaMode):
    name: str = "deleter"
    description: str = "Ask whether stopping, removing, or narrowing is better"
    battery_name: str = "deleter"


@dataclass
class AssumptionSurfacerMode(QuestionPersonaMode):
    name: str = "assumption_surfacer"
    description: str = "Ask which assumptions are load-bearing"
    battery_name: str = "assumption_surfacer"
