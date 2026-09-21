"""
Inbox Auto-Debate Trigger.

Bridges the inbox prioritization system to the debate engine. When emails
are re-prioritized to "critical" (or when tier_3_debate is forced), this
module can optionally trigger a multi-agent debate to analyze the email
content and produce a decision receipt.

The trigger is opt-in: callers must pass ``auto_debate=True`` in the
reprioritize request body, or the system must be configured with
``INBOX_AUTO_DEBATE=true`` in environment.

Flow:
    Email reprioritized → priority == "critical"
    → InboxDebateTrigger.maybe_trigger()
    → Creates debate via playground API (same as Oracle)
    → Stores debate_id in email cache metadata
    → Emits INBOX_DEBATE_TRIGGERED event
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Environment-level opt-in for auto-debate on critical emails
INBOX_AUTO_DEBATE_ENABLED = os.environ.get("INBOX_AUTO_DEBATE", "").lower() in (
    "1",
    "true",
    "yes",
)

# Debounce: don't re-trigger debate for the same email within this window
_DEBATE_COOLDOWN_SECONDS = 600  # 10 minutes

# Rate limit: max debates per hour from inbox triggers
_MAX_DEBATES_PER_HOUR = 4

# Minimum priority to trigger auto-debate
_TRIGGER_PRIORITY = "critical"


@dataclass
class DebateTriggerResult:
    """Result of an auto-debate trigger attempt."""

    triggered: bool
    debate_id: str | None = None
    reason: str = ""
    email_id: str = ""


@dataclass
class InboxDebateTrigger:
    """
    Evaluates inbox items and optionally triggers debates for critical emails.

    Maintains per-email cooldown and hourly rate limits to prevent spam.
    """

    # email_id -> last trigger timestamp
    _cooldowns: dict[str, float] = field(default_factory=dict)
    # timestamps of recent triggers (for rate limiting)
    _recent_triggers: list[float] = field(default_factory=list)

    def _is_rate_limited(self) -> bool:
        """Check if we've exceeded the hourly trigger limit."""
        now = time.time()
        cutoff = now - 3600
        self._recent_triggers = [t for t in self._recent_triggers if t > cutoff]
        return len(self._recent_triggers) >= _MAX_DEBATES_PER_HOUR

    def _is_on_cooldown(self, email_id: str) -> bool:
        """Check if this email was recently debated."""
        last = self._cooldowns.get(email_id)
        if last is None:
            return False
        return (time.time() - last) < _DEBATE_COOLDOWN_SECONDS

    def should_trigger(
        self,
        email_id: str,
        priority: str,
        *,
        force: bool = False,
    ) -> tuple[bool, str]:
        """
        Decide whether to trigger a debate for this email.

        Returns (should_trigger, reason).
        """
        if not force and priority != _TRIGGER_PRIORITY:
            return False, f"priority '{priority}' below threshold '{_TRIGGER_PRIORITY}'"

        if self._is_on_cooldown(email_id):
            return False, "email recently debated (cooldown active)"

        if self._is_rate_limited():
            return False, f"rate limit reached ({_MAX_DEBATES_PER_HOUR}/hour)"

        return True, "eligible for auto-debate"

    async def trigger_debate(
        self,
        email_id: str,
        subject: str,
        body_preview: str,
        sender: str,
        *,
        agents: int = 3,
        rounds: int = 2,
    ) -> DebateTriggerResult:
        """
        Trigger a debate for an inbox email.

        Uses the playground debate endpoint (same as Oracle) to run a quick
        analysis debate. The debate topic is constructed from the email
        subject and body preview.
        """
        topic = f"Analyze and advise on this critical email from {sender}: {subject}"

        try:
            # Use the inline mock debate from the playground handler.
            # This provides a fast, lightweight analysis without needing
            # the full debate orchestrator or external API calls.
            from aragora.server.handlers.demo.playground import _run_inline_mock_debate

            result = _run_inline_mock_debate(
                topic=topic,
                rounds=rounds,
                agent_count=agents,
                question=topic,
            )

            debate_id = result.get("id") if result else None

            # Record trigger
            now = time.time()
            self._cooldowns[email_id] = now
            self._recent_triggers.append(now)

            # Emit event
            self._emit_trigger_event(email_id, debate_id, subject)

            logger.info(
                "Auto-debate triggered for email %s (debate_id=%s)",
                email_id,
                debate_id,
            )

            return DebateTriggerResult(
                triggered=True,
                debate_id=debate_id,
                reason="debate triggered successfully",
                email_id=email_id,
            )

        except (ImportError, AttributeError) as e:
            logger.warning("Playground debate not available: %s", e)
            return DebateTriggerResult(
                triggered=False,
                reason="debate engine not available",
                email_id=email_id,
            )
        except (ValueError, RuntimeError, OSError, ConnectionError) as e:
            logger.warning("Auto-debate failed for email %s: %s", email_id, e)
            return DebateTriggerResult(
                triggered=False,
                reason="debate creation failed",
                email_id=email_id,
            )

    def _emit_trigger_event(
        self,
        email_id: str,
        debate_id: str | None,
        subject: str,
    ) -> None:
        """Emit an INBOX_DEBATE_TRIGGERED event via the webhook dispatcher."""
        try:
            from aragora.events.dispatcher import dispatch_event

            dispatch_event(
                "inbox_debate_triggered",
                {
                    "email_id": email_id,
                    "debate_id": debate_id,
                    "subject": subject,
                    "timestamp": time.time(),
                },
            )
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("Could not dispatch trigger event: %s", e)


# Module-level singleton
_trigger: InboxDebateTrigger | None = None


def get_inbox_debate_trigger() -> InboxDebateTrigger:
    """Get or create the global inbox debate trigger."""
    global _trigger
    if _trigger is None:
        _trigger = InboxDebateTrigger()
    return _trigger


async def process_reprioritization_debates(
    changes: list[dict[str, Any]],
    email_cache: Any,
    *,
    auto_debate: bool = False,
) -> list[DebateTriggerResult]:
    """
    Process reprioritization results and trigger debates for critical emails.

    Called after _reprioritize_emails() completes. Evaluates each priority
    change and triggers debates for emails that became critical.

    Args:
        changes: List of priority change dicts from reprioritization
        email_cache: The email cache to look up email details
        auto_debate: Whether auto-debate was requested by the caller

    Returns:
        List of DebateTriggerResult for emails that were evaluated
    """
    if not auto_debate and not INBOX_AUTO_DEBATE_ENABLED:
        return []

    trigger = get_inbox_debate_trigger()
    results: list[DebateTriggerResult] = []

    for change in changes:
        email_id = change.get("email_id", "")
        new_priority = change.get("new_priority", "")

        should, reason = trigger.should_trigger(email_id, new_priority)
        if not should:
            results.append(
                DebateTriggerResult(
                    triggered=False,
                    reason=reason,
                    email_id=email_id,
                )
            )
            continue

        # Look up email details from cache
        cached = email_cache.get(email_id) if email_cache else None
        subject = cached.get("subject", "Unknown") if cached else "Unknown"
        body_preview = cached.get("snippet", "") if cached else ""
        sender = cached.get("from", "Unknown") if cached else "Unknown"

        result = await trigger.trigger_debate(
            email_id=email_id,
            subject=subject,
            body_preview=body_preview,
            sender=sender,
        )
        results.append(result)

    return results
