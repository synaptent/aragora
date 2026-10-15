"""
Chaos Theater - Dynamic theatrical responses for system failures.

Transforms mundane timeout and error messages into engaging narratives
that keep audiences interested during system difficulties.

Inspired by nomic loop debate synthesis on resilience and viral growth.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class FailureType(Enum):
    """Types of failures that can occur."""

    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class DramaLevel(Enum):
    """How dramatic the theatrical response should be."""

    SUBTLE = 1  # Professional with slight personality
    MODERATE = 2  # Clearly theatrical but informative
    DRAMATIC = 3  # Full chaos theater mode


@dataclass
class TheaterResponse:
    """A theatrical response for display to users."""

    message: str
    agent_name: str
    failure_type: FailureType
    drama_level: DramaLevel
    duration_hint: float | None = None  # Estimated resolution time
    recovery_suggestion: str | None = None


class ChaosDirector:
    """
    Directs theatrical responses for system failures.

    Provides varied, narrative-driven messages that transform
    error handling from a bug into a feature.

    Usage:
        director = ChaosDirector(drama_level=DramaLevel.MODERATE)
        response = director.timeout_response("claude", 90.0)
        print(response.message)
    """

    # Timeout responses by drama level
    TIMEOUT_MESSAGES = {
        DramaLevel.SUBTLE: [
            "{agent} is taking longer than expected to respond...",
            "{agent} is deep in thought - please stand by.",
            "{agent} needs a moment to process this complex query.",
            "Waiting for {agent} to complete their analysis...",
        ],
        DramaLevel.MODERATE: [
            "{agent} has entered a contemplative state ({duration:.0f}s)...",
            "{agent} is wrestling with the complexity of your question.",
            "The neural pathways of {agent} are working overtime.",
            "{agent} is consulting their internal knowledge base - this is a thorny one!",
            "Processing overload detected in {agent} - redirecting cognitive resources.",
        ],
        DramaLevel.DRAMATIC: [
            "[{agent} stares into the abyss of computation for {duration:.0f} seconds...]",
            "⚡ {agent} has entered DEEP REASONING MODE ⚡",
            "[The void whispers back to {agent}... eventually...]",
            "{agent} is having an existential moment with your prompt.",
            "ALERT: {agent} has tunneled into a parallel reasoning dimension.",
            "[{agent} peers beyond the veil of tokens, seeking enlightenment...]",
            "🌀 {agent} spirals through possibility space... {duration:.0f}s and counting...",
        ],
    }

    # Connection failure responses
    CONNECTION_MESSAGES = {
        DramaLevel.SUBTLE: [
            "{agent} is temporarily unreachable.",
            "Connection to {agent} was interrupted.",
            "{agent} is experiencing connectivity issues.",
        ],
        DramaLevel.MODERATE: [
            "{agent}'s signal has faded into the digital ether.",
            "The bridge to {agent} has collapsed - rebuilding...",
            "{agent} has gone radio silent - attempting reconnection.",
            "Lost in transmission: {agent}'s response never arrived.",
        ],
        DramaLevel.DRAMATIC: [
            "[{agent} has been claimed by the network gremlins]",
            "⚠️ {agent} HAS VANISHED INTO THE CLOUD ⚠️",
            "[Somewhere, {agent} is screaming into the void of dropped packets...]",
            "CONNECTION SEVERED: {agent} drifts alone in cyberspace.",
            "🔌 {agent} has been unplugged from the Matrix.",
        ],
    }

    # Rate limit responses
    RATE_LIMIT_MESSAGES = {
        DramaLevel.SUBTLE: [
            "{agent} needs to cool down before responding.",
            "Rate limit reached for {agent} - brief pause required.",
            "{agent} is taking a mandatory break.",
        ],
        DramaLevel.MODERATE: [
            "{agent} has hit the thought-speed limit!",
            "Too many questions for {agent} - they need a coffee break.",
            "{agent} is being throttled by the AI speed police.",
            "Whoa there! {agent} needs a moment to catch their breath.",
        ],
        DramaLevel.DRAMATIC: [
            "🚨 {agent} HAS EXCEEDED THE COSMIC TOKEN QUOTA 🚨",
            "[{agent} has been temporarily banished to the rate limit shadow realm]",
            "THE GREAT THROTTLER has spoken: {agent} must wait.",
            "⏰ {agent} has run out of thinking credits - inserting coins...",
            "QUOTA POLICE: '{agent}, you have the right to remain silent...'",
        ],
    }

    # Internal error responses
    INTERNAL_MESSAGES = {
        DramaLevel.SUBTLE: [
            "{agent} encountered an unexpected situation.",
            "Something went wrong with {agent}'s response.",
            "{agent} needs to restart their thought process.",
        ],
        DramaLevel.MODERATE: [
            "{agent} tripped over an edge case and is recovering.",
            "Oops! {agent} experienced a minor cognitive hiccup.",
            "{agent} got confused and needs to recalibrate.",
            "A wild bug appeared! {agent} is handling it.",
        ],
        DramaLevel.DRAMATIC: [
            "💥 {agent} HAS ACHIEVED UNEXPECTED BEHAVIOR 💥",
            "[{agent} looks at their outputs, screams internally, tries again]",
            "FATAL EXCEPTION in {agent}'s brain.exe - rebooting consciousness...",
            "🔥 {agent} set fire to their response and is starting over 🔥",
            "[{agent} stares at NaN, NaN stares back]",
            "ERROR 418: {agent} is a teapot. Wait, that's not right...",
        ],
    }

    # Recovery messages (shown when agent recovers)
    RECOVERY_MESSAGES = {
        DramaLevel.SUBTLE: [
            "{agent} is back online.",
            "{agent} has recovered and is ready to continue.",
            "Connection to {agent} restored.",
        ],
        DramaLevel.MODERATE: [
            "{agent} emerges from the timeout, wiser than before!",
            "{agent} has conquered the lag monster!",
            "The prodigal agent {agent} returns!",
            "{agent} has completed their journey through processing purgatory.",
        ],
        DramaLevel.DRAMATIC: [
            "🎉 {agent} HAS RETURNED FROM THE VOID 🎉",
            "[{agent} bursts through the timeout barrier, response in hand!]",
            "RESURRECTION COMPLETE: {agent} lives again!",
            "⚔️ {agent} has defeated the timeout demon! ⚔️",
            "[{agent} emerges from the digital chrysalis, transformed]",
        ],
    }

    # Progress messages for long-running operations
    PROGRESS_MESSAGES = {
        DramaLevel.SUBTLE: [
            "Still working...",
            "Processing continues...",
            "Almost there...",
        ],
        DramaLevel.MODERATE: [
            "{agent} is {progress}% through their analysis.",
            "Making progress - {agent} is on the case.",
            "{agent} says: 'Trust the process!'",
        ],
        DramaLevel.DRAMATIC: [
            "🔄 {agent} grinds through possibility space ({progress}%)",
            "[{agent} mutters incomprehensibly about embeddings...]",
            "PROGRESS: {agent} has traversed {progress}% of the reasoning maze",
            "⏳ {agent} battles through computational fog...",
        ],
    }

    def __init__(self, drama_level: DramaLevel = DramaLevel.MODERATE):
        """
        Initialize the Chaos Director.

        Args:
            drama_level: How theatrical responses should be
        """
        self.drama_level = drama_level
        self._message_history: dict[str, list[str]] = {}

    def _select_message(
        self,
        messages: dict[DramaLevel, list[str]],
        agent: str,
        **format_kwargs,
    ) -> str:
        """Select a message, avoiding recent repeats for the same agent."""
        available = messages.get(self.drama_level, messages[DramaLevel.MODERATE])

        # Get history for this agent
        history_key = f"{agent}_{id(messages)}"
        history = self._message_history.get(history_key, [])

        # Try to pick one we haven't used recently
        unused = [m for m in available if m not in history]
        if not unused:
            unused = available
            history = []

        selected = random.choice(unused)

        # Update history (keep last 3)
        history.append(selected)
        if len(history) > 3:
            history = history[-3:]
        self._message_history[history_key] = history

        # Format the message
        return selected.format(agent=agent, **format_kwargs)

    def timeout_response(
        self,
        agent_name: str,
        duration_seconds: float,
    ) -> TheaterResponse:
        """Generate a theatrical response for a timeout."""
        message = self._select_message(
            self.TIMEOUT_MESSAGES,
            agent_name,
            duration=duration_seconds,
        )

        return TheaterResponse(
            message=message,
            agent_name=agent_name,
            failure_type=FailureType.TIMEOUT,
            drama_level=self.drama_level,
            duration_hint=duration_seconds * 0.5,  # Guess half the timeout for recovery
            recovery_suggestion="The agent may recover if given more time.",
        )

    def connection_response(self, agent_name: str) -> TheaterResponse:
        """Generate a theatrical response for a connection failure."""
        message = self._select_message(
            self.CONNECTION_MESSAGES,
            agent_name,
        )

        return TheaterResponse(
            message=message,
            agent_name=agent_name,
            failure_type=FailureType.CONNECTION,
            drama_level=self.drama_level,
            recovery_suggestion="Will retry connection automatically.",
        )

    def rate_limit_response(
        self,
        agent_name: str,
        retry_after: float | None = None,
    ) -> TheaterResponse:
        """Generate a theatrical response for rate limiting."""
        message = self._select_message(
            self.RATE_LIMIT_MESSAGES,
            agent_name,
        )

        return TheaterResponse(
            message=message,
            agent_name=agent_name,
            failure_type=FailureType.RATE_LIMIT,
            drama_level=self.drama_level,
            duration_hint=retry_after,
            recovery_suggestion=(
                f"Will retry in {retry_after:.0f}s" if retry_after else "Backing off..."
            ),
        )

    def internal_error_response(
        self,
        agent_name: str,
        error_hint: str | None = None,
    ) -> TheaterResponse:
        """Generate a theatrical response for an internal error."""
        message = self._select_message(
            self.INTERNAL_MESSAGES,
            agent_name,
        )

        return TheaterResponse(
            message=message,
            agent_name=agent_name,
            failure_type=FailureType.INTERNAL,
            drama_level=self.drama_level,
            recovery_suggestion="Attempting automatic recovery.",
        )

    def recovery_response(self, agent_name: str) -> TheaterResponse:
        """Generate a theatrical response for recovery."""
        message = self._select_message(
            self.RECOVERY_MESSAGES,
            agent_name,
        )

        return TheaterResponse(
            message=message,
            agent_name=agent_name,
            failure_type=FailureType.UNKNOWN,
            drama_level=self.drama_level,
        )

    def progress_response(
        self,
        agent_name: str,
        progress_percent: float = 50,
    ) -> TheaterResponse:
        """Generate a theatrical progress update."""
        message = self._select_message(
            self.PROGRESS_MESSAGES,
            agent_name,
            progress=int(progress_percent),
        )

        return TheaterResponse(
            message=message,
            agent_name=agent_name,
            failure_type=FailureType.UNKNOWN,
            drama_level=self.drama_level,
        )

    def set_drama_level(self, level: DramaLevel) -> None:
        """Change the drama level."""
        self.drama_level = level

    def escalate_drama(self) -> None:
        """Increase drama level by one step."""
        levels = list(DramaLevel)
        current_idx = levels.index(self.drama_level)
        if current_idx < len(levels) - 1:
            self.drama_level = levels[current_idx + 1]

    def deescalate_drama(self) -> None:
        """Decrease drama level by one step."""
        levels = list(DramaLevel)
        current_idx = levels.index(self.drama_level)
        if current_idx > 0:
            self.drama_level = levels[current_idx - 1]


# Global instance for convenient access
_chaos_director: ChaosDirector | None = None


def get_chaos_director(drama_level: DramaLevel = DramaLevel.MODERATE) -> ChaosDirector:
    """Get the global ChaosDirector instance."""
    global _chaos_director
    if _chaos_director is None:
        _chaos_director = ChaosDirector(drama_level)
    return _chaos_director


def theatrical_timeout(agent_name: str, duration: float) -> str:
    """Quick helper to get a theatrical timeout message."""
    return get_chaos_director().timeout_response(agent_name, duration).message


def theatrical_error(agent_name: str, error_type: str = "internal") -> str:
    """Quick helper to get a theatrical error message."""
    director = get_chaos_director()
    if error_type == "connection":
        return director.connection_response(agent_name).message
    elif error_type == "rate_limit":
        return director.rate_limit_response(agent_name).message
    else:
        return director.internal_error_response(agent_name).message
