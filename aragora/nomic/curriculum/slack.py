"""
Slack Preservation - Intentionally leaving room for user authorship.

Inspired by the conversation insight:
"Systems that fill every gap with predicted-optimal action may be
helpful in the short term and corrosive to agency over time."

The SOAR curriculum system generates stepping stones toward goals.
But if it always generates the optimal next step, it removes the
space where the user could have surprised themselves.

This module:
- Leaves gaps intentionally in curricula
- Introduces "explore randomly" as a valid stepping stone
- Treats user deviation from curriculum as signal, not failure
- Preserves slack for intermittent agency

Key insight:
"Agency is intermittent, not continuous. Most of the time you're
executing inherited heuristics. But occasionally, attention collapses
the state space, reflection suspends default policy, you select which
gradient to treat as binding. That needs room to happen."

Usage:
    from aragora.nomic.curriculum.slack import SlackPreserver

    # Wrap curriculum generation with slack preservation
    preserver = SlackPreserver(slack_ratio=0.2)

    curriculum = await generate_curriculum(target_task="Build API")
    curriculum = preserver.inject_slack(curriculum)

    # Now curriculum has intentional gaps
    for stone in curriculum.stepping_stones:
        if stone.is_slack_stone:
            # This is an opportunity for user authorship
            pass
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SlackType(str, Enum):
    """Types of slack that can be injected into curricula."""

    EXPLORE = "explore"  # Do something unexpected
    REFLECT = "reflect"  # Step back and consider
    DEVIATE = "deviate"  # Intentionally go off-script
    RANDOM = "random"  # Pure randomness within bounds
    USER_CHOICE = "user_choice"  # User defines this step
    NEGATIVE_SPACE = "negative_space"  # Do nothing, observe


class DeviationSignal(str, Enum):
    """What a user's deviation from curriculum might signal."""

    INSIGHT = "insight"  # User sees something system didn't
    RESTLESSNESS = "restlessness"  # User is bored/constrained
    DISCOVERY = "discovery"  # User found a better path
    REJECTION = "rejection"  # User rejects the curriculum's values
    EXPLORATION = "exploration"  # User is curious about alternatives
    FATIGUE = "fatigue"  # User needs a break from structure


@dataclass
class SlackStone:
    """A stepping stone that preserves slack for user authorship.

    Unlike regular stepping stones that specify what to do,
    slack stones create space for the user to surprise themselves.
    """

    id: str
    slack_type: SlackType
    prompt: str  # Invitation, not instruction
    why_slack_here: str  # Why this gap matters
    minimum_time: float | None = None  # Don't rush through
    suggestions: list[str] = field(default_factory=list)  # Optional, not prescriptive
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_slack_stone(self) -> bool:
        return True


@dataclass
class DeviationRecord:
    """Record of when a user deviated from curriculum."""

    curriculum_id: str
    expected_stone_id: str
    what_user_did: str
    signal_interpretation: DeviationSignal | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    user_explanation: str = ""
    was_productive: bool | None = None  # Determined later


@dataclass
class SlackConfig:
    """Configuration for slack preservation."""

    # How much of curriculum should be slack
    slack_ratio: float = 0.2  # 20% slack stones

    # Where to inject slack
    inject_at_start: bool = True  # Room to find footing
    inject_at_end: bool = True  # Room for reflection
    inject_after_difficulty_jumps: bool = True  # Room to process

    # What kinds of slack to include
    allowed_slack_types: list[SlackType] = field(
        default_factory=lambda: [
            SlackType.EXPLORE,
            SlackType.REFLECT,
            SlackType.USER_CHOICE,
        ]
    )

    # Deviation handling
    celebrate_productive_deviations: bool = True
    track_deviation_patterns: bool = True


# Prompts for different slack types
SLACK_PROMPTS = {
    SlackType.EXPLORE: [
        "Before the next step, explore something that caught your attention.",
        "What aspect of this problem interests you that we haven't touched?",
        "Take a detour. Follow your curiosity, not the plan.",
    ],
    SlackType.REFLECT: [
        "Pause and notice what you've learned so far.",
        "What assumptions have we been making? Are they right?",
        "Before moving on: is this still the right goal?",
    ],
    SlackType.DEVIATE: [
        "Try the opposite of what seems obvious.",
        "What would someone who disagrees with our approach do here?",
        "Break one of the constraints we've been respecting.",
    ],
    SlackType.RANDOM: [
        "Pick any of the following randomly, then explain why it turned out to be interesting (or not).",
        "Roll the dice on this decision. See what happens.",
    ],
    SlackType.USER_CHOICE: [
        "What do you want to do here? You define this step.",
        "This space is yours. The curriculum has no opinion.",
        "Design your own stepping stone for this moment.",
    ],
    SlackType.NEGATIVE_SPACE: [
        "Do nothing with this step. Just observe.",
        "Wait. Let the situation develop without intervention.",
        "Sometimes the best action is no action. This is that moment.",
    ],
}


class SlackPreserver:
    """Preserves slack in curricula for user authorship.

    Example:
        preserver = SlackPreserver(config=SlackConfig(slack_ratio=0.25))

        # Inject slack into an existing curriculum
        curriculum = await generate_curriculum(...)
        curriculum = preserver.inject_slack(curriculum)

        # Track when users deviate
        if user_did_something_different:
            deviation = preserver.record_deviation(
                curriculum_id=curriculum.id,
                expected_stone_id="stone_5",
                what_user_did="Refactored the auth module instead",
            )
            interpretation = preserver.interpret_deviation(deviation)
    """

    def __init__(self, config: SlackConfig | None = None):
        """Initialize the preserver.

        Args:
            config: Configuration for slack preservation
        """
        self.config = config or SlackConfig()
        self._deviations: list[DeviationRecord] = []
        self._slack_stone_counter = 0

    def inject_slack(
        self,
        curriculum: Any,  # Curriculum type from soar_curriculum
    ) -> Any:
        """Inject slack stones into a curriculum.

        Args:
            curriculum: The curriculum to modify

        Returns:
            Modified curriculum with slack stones
        """
        if not hasattr(curriculum, "stepping_stones"):
            return curriculum

        stones = list(curriculum.stepping_stones)
        if not stones:
            return curriculum

        # Calculate how many slack stones to add
        target_slack_count = max(1, int(len(stones) * self.config.slack_ratio))

        # Determine injection points
        injection_points = self._determine_injection_points(stones)

        # Limit to target count
        if len(injection_points) > target_slack_count:
            injection_points = random.sample(injection_points, target_slack_count)

        # Sort in reverse to avoid index shifting issues
        injection_points.sort(reverse=True)

        # Inject slack stones
        for idx, slack_type in injection_points:
            slack_stone = self._create_slack_stone(slack_type, stones, idx)
            stones.insert(idx, slack_stone)

        # Replace curriculum stones
        curriculum.stepping_stones = stones

        return curriculum

    def _determine_injection_points(
        self,
        stones: list,
    ) -> list[tuple[int, SlackType]]:
        """Determine where to inject slack stones.

        Args:
            stones: Current stepping stones

        Returns:
            List of (index, slack_type) tuples
        """
        points = []

        # At start
        if self.config.inject_at_start:
            points.append((0, SlackType.REFLECT))

        # At end
        if self.config.inject_at_end:
            points.append((len(stones), SlackType.REFLECT))

        # After difficulty jumps
        if self.config.inject_after_difficulty_jumps:
            for i in range(1, len(stones)):
                prev_diff = getattr(stones[i - 1], "difficulty", 0.5)
                curr_diff = getattr(stones[i], "difficulty", 0.5)

                if curr_diff - prev_diff > 0.2:
                    # Significant difficulty jump - add exploration space
                    slack_type = random.choice([SlackType.EXPLORE, SlackType.USER_CHOICE])
                    points.append((i, slack_type))

        # Random additional slack
        remaining_allowed = self.config.allowed_slack_types
        if remaining_allowed:
            # Add some random slack points
            for i in range(1, len(stones) - 1):
                if random.random() < 0.1:  # 10% chance per position
                    slack_type = random.choice(remaining_allowed)
                    points.append((i, slack_type))

        return points

    def _create_slack_stone(
        self,
        slack_type: SlackType,
        stones: list,
        position: int,
    ) -> SlackStone:
        """Create a slack stone.

        Args:
            slack_type: Type of slack to create
            stones: Current stone list for context
            position: Where this will be inserted

        Returns:
            Created SlackStone
        """
        self._slack_stone_counter += 1

        # Select prompt based on type
        prompt = random.choice(SLACK_PROMPTS.get(slack_type, ["Take a moment."]))

        # Generate contextual "why"
        if position == 0:
            why = "Space to find your footing before diving in."
        elif position >= len(stones):
            why = "Space to reflect on what you've learned."
        else:
            why = "A gap for your own authorship in this process."

        # Optional suggestions (not prescriptive)
        suggestions = []
        if slack_type == SlackType.EXPLORE:
            suggestions = [
                "Look at something tangentially related",
                "Talk to someone about the problem",
                "Draw or diagram your current understanding",
            ]
        elif slack_type == SlackType.USER_CHOICE:
            suggestions = [
                "You could continue the planned curriculum",
                "You could take a completely different approach",
                "You could do nothing and see what questions arise",
            ]

        return SlackStone(
            id=f"slack_{self._slack_stone_counter}",
            slack_type=slack_type,
            prompt=prompt,
            why_slack_here=why,
            minimum_time=60.0 if slack_type == SlackType.REFLECT else None,
            suggestions=suggestions,
        )

    def record_deviation(
        self,
        curriculum_id: str,
        expected_stone_id: str,
        what_user_did: str,
        user_explanation: str = "",
    ) -> DeviationRecord:
        """Record when a user deviates from curriculum.

        Deviation is not failure - it's signal.

        Args:
            curriculum_id: ID of the curriculum
            expected_stone_id: What stone was expected
            what_user_did: What the user actually did
            user_explanation: Optional user-provided explanation

        Returns:
            DeviationRecord
        """
        record = DeviationRecord(
            curriculum_id=curriculum_id,
            expected_stone_id=expected_stone_id,
            what_user_did=what_user_did,
            user_explanation=user_explanation,
        )

        self._deviations.append(record)
        return record

    def interpret_deviation(
        self,
        deviation: DeviationRecord,
    ) -> DeviationSignal:
        """Interpret what a deviation might signal.

        This is heuristic - the user's explanation matters more.

        Args:
            deviation: The deviation to interpret

        Returns:
            Best-guess DeviationSignal
        """
        what = deviation.what_user_did.lower()
        explanation = deviation.user_explanation.lower()

        # Look for signals in what they did
        if any(word in what for word in ["refactor", "improve", "fix", "optimize"]):
            return DeviationSignal.INSIGHT

        if any(word in what for word in ["explore", "try", "experiment", "test"]):
            return DeviationSignal.EXPLORATION

        if any(word in what for word in ["break", "stop", "pause", "rest"]):
            return DeviationSignal.FATIGUE

        if any(word in what for word in ["different", "other", "alternative", "new"]):
            return DeviationSignal.DISCOVERY

        # Check explanation
        if explanation:
            if "better" in explanation or "found" in explanation:
                return DeviationSignal.DISCOVERY
            if "bored" in explanation or "stuck" in explanation:
                return DeviationSignal.RESTLESSNESS
            if "wrong" in explanation or "disagree" in explanation:
                return DeviationSignal.REJECTION

        # Default to exploration - most charitable interpretation
        return DeviationSignal.EXPLORATION

    def get_deviation_summary(
        self,
        curriculum_id: str | None = None,
    ) -> dict[str, Any]:
        """Get summary of deviations.

        Args:
            curriculum_id: Optional filter by curriculum

        Returns:
            Summary of deviation patterns
        """
        deviations = self._deviations
        if curriculum_id:
            deviations = [d for d in deviations if d.curriculum_id == curriculum_id]

        if not deviations:
            return {"total": 0, "interpretation": "No deviations recorded"}

        # Count by signal type
        signal_counts: dict[str, int] = {}
        for d in deviations:
            signal = d.signal_interpretation or self.interpret_deviation(d)
            signal_counts[signal.value] = signal_counts.get(signal.value, 0) + 1

        # Calculate productivity rate
        productivity_known = [d for d in deviations if d.was_productive is not None]
        if productivity_known:
            productive_rate = sum(1 for d in productivity_known if d.was_productive) / len(
                productivity_known
            )
        else:
            productive_rate = None

        return {
            "total": len(deviations),
            "by_signal": signal_counts,
            "productive_rate": productive_rate,
            "interpretation": self._interpret_deviation_pattern(signal_counts),
        }

    def _interpret_deviation_pattern(
        self,
        signal_counts: dict[str, int],
    ) -> str:
        """Interpret overall deviation pattern."""
        if not signal_counts:
            return "No pattern - insufficient deviations"

        dominant = max(signal_counts.items(), key=lambda x: x[1])

        interpretations = {
            "insight": "User is finding things the curriculum missed. Consider incorporating their discoveries.",
            "exploration": "User is curious beyond the curriculum. This is healthy agency.",
            "discovery": "User is finding better paths. The curriculum may be suboptimal.",
            "restlessness": "User may feel constrained. Consider adding more slack.",
            "rejection": "User may disagree with curriculum direction. Check value alignment.",
            "fatigue": "User may need rest or smaller steps. Adjust pace.",
        }

        return interpretations.get(
            dominant[0], "Mixed signals - user's agency is active and varied."
        )

    def celebrate_deviation(
        self,
        deviation: DeviationRecord,
    ) -> str:
        """Generate celebration message for productive deviation.

        Deviation that leads somewhere good should be celebrated,
        not merely tolerated.

        Args:
            deviation: The deviation to celebrate

        Returns:
            Celebration message
        """
        signal = deviation.signal_interpretation or self.interpret_deviation(deviation)

        celebrations = {
            DeviationSignal.INSIGHT: "Great catch! You saw something the curriculum missed.",
            DeviationSignal.DISCOVERY: "You found a better path. That's exactly what slack is for.",
            DeviationSignal.EXPLORATION: "Curiosity rewarded. The detour taught us something.",
            DeviationSignal.RESTLESSNESS: "Your instinct to break free was right. The structure was too tight.",
            DeviationSignal.REJECTION: "You held to your values when the curriculum didn't. That matters.",
            DeviationSignal.FATIGUE: "Knowing when to pause is wisdom, not weakness.",
        }

        return celebrations.get(signal, "Your deviation was valuable. The plan isn't always right.")


def create_pure_slack_curriculum(
    task_description: str,
    duration_hours: float = 2.0,
    slack_types: list[SlackType] | None = None,
) -> list[SlackStone]:
    """Create a curriculum made entirely of slack.

    Sometimes the best curriculum is no curriculum - just
    structured space for exploration.

    Args:
        task_description: What the user is working on
        duration_hours: Approximate duration
        slack_types: Which types of slack to include

    Returns:
        List of SlackStones (a pure-slack curriculum)
    """
    types = slack_types or [
        SlackType.EXPLORE,
        SlackType.REFLECT,
        SlackType.USER_CHOICE,
        SlackType.NEGATIVE_SPACE,
    ]

    # Estimate stone count based on duration (one per ~30 min)
    stone_count = max(2, int(duration_hours * 2))

    stones = []
    for i in range(stone_count):
        slack_type = types[i % len(types)]
        prompt = random.choice(SLACK_PROMPTS[slack_type])

        stone = SlackStone(
            id=f"pure_slack_{i + 1}",
            slack_type=slack_type,
            prompt=prompt,
            why_slack_here=f"This is space for you to work on: {task_description[:50]}...",
            minimum_time=30 * 60,  # 30 minutes minimum
        )
        stones.append(stone)

    return stones
