"""
Security Debate Runner.

Runs multi-agent debates for remediation recommendations on critical
security findings. Relocated from aragora.events.security_events (P4a E7a)
because it is the domain-coupled half of that module: it imports
aragora.debate.orchestrator.Arena, aragora.debate.protocol, and
aragora.agents.api_agents.{anthropic,openai}.

The question builder lives in aragora.debate.security_question (a leaf shared
with the runner in aragora.debate.security_debate) and is re-exported here.

Self-registers trigger_security_debate as the callback that
aragora.events.security_events.SecurityEventEmitter invokes for its
auto-debate path (see register_security_debate_runner), so the domain-free
events module never imports aragora.debate or aragora.agents directly.
Registration is a plain module-level side effect, so any composition root
that imports this module first makes the runner available process-wide.

Three domain-side composition roots import this module explicitly rather
than relying solely on incidental transitive imports:
  - aragora.debate.orchestrator (Arena, for any Arena-backed process)
  - aragora.debate.event_subscribers.bootstrap_debate_event_subscribers
    (non-Arena consumers of the shared event-subscriber bootstrap, e.g.
    server startup, memory/knowledge extensions)
  - aragora.analysis.codebase.sast.scanner (SAST auto-scan findings, which
    can run in isolation from both of the above)

The latter two also call ensure_registered() explicitly rather than relying
on the bare-import side effect alone, since a plain import is a no-op once
this module is already cached in sys.modules -- see ensure_registered's
docstring.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from aragora.debate.security_question import build_security_debate_question
from aragora.events.security_events import (
    SecurityDebateRunner,
    SecurityEvent,
    _register_default_security_debate_runner,
    _store_security_debate_result,
)

logger = logging.getLogger(__name__)


async def trigger_security_debate(
    event: SecurityEvent,
    confidence_threshold: float = 0.7,
    agents: list[Any] | None = None,
    timeout_seconds: int = 300,
) -> str | None:
    """
    Trigger a multi-agent debate for security remediation.

    Args:
        event: Security event with findings
        confidence_threshold: Minimum consensus confidence
        agents: Optional list of agents (uses defaults if None)
        timeout_seconds: Maximum debate duration

    Returns:
        Debate ID if triggered, None if failed
    """
    try:
        from aragora.debate.security_debate import run_security_debate

        result = await run_security_debate(
            event=event,
            agents=agents,
            confidence_threshold=confidence_threshold,
            timeout_seconds=timeout_seconds,
            org_id=event.workspace_id or "default",
        )

        if (
            not getattr(result, "messages", [])
            and not getattr(result, "participants", [])
            and getattr(result, "rounds_used", 0) == 0
            and str(getattr(result, "final_answer", "")).startswith("No agents available")
        ):
            logger.warning("No agents available for security debate")
            event.debate_requested = False
            event.debate_id = None
            return None

        threshold_met = getattr(result, "metadata", {}).get("security_confidence_threshold_met")
        if threshold_met is not True:
            if threshold_met is not False:
                logger.warning(
                    "Security debate %s did not report confidence threshold status",
                    getattr(result, "debate_id", None),
                )
                event.debate_requested = False
                event.debate_id = None
                return None
            logger.warning(
                "Security debate %s completed below confidence threshold %.2f",
                getattr(result, "debate_id", None),
                confidence_threshold,
            )

        debate_id = (
            getattr(result, "debate_id", "")
            or getattr(result, "id", "")
            or f"security_debate_{uuid.uuid4().hex[:12]}"
        )
        event.debate_requested = True
        event.debate_id = debate_id

        logger.info(
            f"[Security] Debate {debate_id} completed: "
            f"consensus={result.consensus_reached}, confidence={result.confidence:.2f}"
        )

        # Store result for later retrieval
        await _store_security_debate_result(debate_id, event, result)

        return debate_id

    except ImportError as e:
        logger.warning("Canonical security debate runner not available: %s", e)
        event.debate_requested = False
        event.debate_id = None
        return None
    except (RuntimeError, ValueError, TypeError, OSError) as e:
        logger.exception("Failed to run security debate: %s", e)
        event.debate_requested = False
        event.debate_id = None
        return None


async def _get_security_debate_agents() -> list[Any]:
    """Compatibility shim for the canonical security debate agent selector."""
    from aragora.debate.security_debate import get_security_debate_agents

    return await get_security_debate_agents()


def ensure_registered() -> SecurityDebateRunner | None:
    """Idempotently (re-)register trigger_security_debate as the default runner.

    The bare module-level self-registration below only fires the first time
    this module is imported into a process: a plain `import
    aragora.debate.security_response` is a no-op if the module is already in
    sys.modules, so it will NOT re-run the registration side effect. A
    composition root that must guarantee registration even when this module
    may already be cached elsewhere (e.g. after an explicit
    register_security_debate_runner(None) clear, or a cold-start test that
    resets the registry to simulate a fresh process) should call this
    explicitly instead. Like the module-level self-registration, this never
    clobbers an explicit runner hook or an explicit None-clear (see
    _register_default_security_debate_runner).
    """
    return _register_default_security_debate_runner(trigger_security_debate)


ensure_registered()


__all__ = [
    "trigger_security_debate",
    "build_security_debate_question",
    "ensure_registered",
]
