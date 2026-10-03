"""Bounded Claude text generation through the explicit VibeProxy policy."""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass

from aragora.agents.transports.vibeproxy import (
    ModelTransportPolicy,
    TransportMode,
    VibeProxyConfigurationError,
    VibeProxyTimeoutError,
    VibeProxyUnavailableError,
)

DEFAULT_CLAUDE_MODEL = "claude-opus-5"
VIBEPROXY_HARNESS = "local VibeProxy Anthropic Messages transport"
VIBEPROXY_TIMEOUT_ENV = "ARAGORA_COLLECT_EVIDENCE_VIBEPROXY_TIMEOUT_SECONDS"
DEFAULT_VIBEPROXY_TIMEOUT_SECONDS = 120.0
# Cap on the catalog /models discovery leg so it and the message leg SHARE the
# attempt budget instead of each drawing the full amount (which let one attempt
# run up to ~2x the intended timeout).
_DISCOVERY_CAP_SECONDS = 6.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaudeVibeProxyAttempt:
    """Result of the optional VibeProxy leg before a direct Claude fallback."""

    attempted: bool
    required: bool
    ok: bool
    text: str = ""
    response_model: str | None = None
    error: str = ""
    harness: str = ""
    timeout_seconds: float = 0.0
    # Wall-clock the proxy leg actually consumed. The caller subtracts THIS
    # (not the allotted ``timeout_seconds``) from the reviewer budget so a
    # fast proxy failure does not shrink the direct fallback's deadline.
    elapsed_seconds: float = 0.0


def _attempt_timeout(reviewer_timeout: float, mode: TransportMode) -> float:
    # A malformed timeout env is a timeout-tuning typo, not a transport-intent
    # signal: degrade to the default like every sibling timeout env
    # (quorum_evidence._timeout_seconds) rather than raising a config error that
    # would escalate prefer -> required and suppress all fallbacks.
    raw = os.environ.get(VIBEPROXY_TIMEOUT_ENV, "").strip()
    configured = DEFAULT_VIBEPROXY_TIMEOUT_SECONDS
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            parsed = DEFAULT_VIBEPROXY_TIMEOUT_SECONDS
        configured = (
            parsed if math.isfinite(parsed) and parsed > 0 else (DEFAULT_VIBEPROXY_TIMEOUT_SECONDS)
        )

    # Prefer mode must leave time for the direct reviewer path. Required mode
    # can consume the full reviewer budget because fallback is prohibited.
    budget = reviewer_timeout if mode is TransportMode.REQUIRED else reviewer_timeout / 2
    return min(configured, budget)


def run_claude_vibeproxy(
    prompt: str,
    *,
    reviewer_timeout: float,
    model: str = DEFAULT_CLAUDE_MODEL,
    policy: ModelTransportPolicy | None = None,
) -> ClaudeVibeProxyAttempt:
    """Run one exact-model Claude attempt when VibeProxy is explicitly selected.

    Direct mode returns ``attempted=False`` without touching the proxy. In prefer
    mode an unavailable proxy (or a malformed transport/timeout env) returns a
    non-required failure — or degrades to direct — so the caller keeps its
    existing direct path; only genuine ``vibeproxy-required`` fails closed.
    """

    start = time.monotonic()

    def _elapsed() -> float:
        return time.monotonic() - start

    # Kept as two statements (not ``policy or from_env()``) so the assignment
    # value is a direct ModelTransportPolicy call the inference-site allowlist
    # gate recognizes as a transport-policy receiver (see the manifest entry for
    # this site in scripts/inference_site_allowlist.json).
    resolved_policy = policy
    if resolved_policy is None:
        try:
            resolved_policy = ModelTransportPolicy.from_env()
        except VibeProxyConfigurationError as exc:
            # A malformed ARAGORA_MODEL_TRANSPORT (or base URL / model map)
            # leaves the mode unknown. Fail closed ONLY when the operator
            # explicitly asked for required; otherwise degrade to direct so a
            # typo does not silently drop the Claude leg with all fallbacks off.
            raw_mode = os.environ.get("ARAGORA_MODEL_TRANSPORT", "").strip().lower()
            if raw_mode == TransportMode.REQUIRED.value:
                return ClaudeVibeProxyAttempt(
                    attempted=True,
                    required=True,
                    ok=False,
                    error=f"VibeProxy configuration error: {exc}",
                    elapsed_seconds=_elapsed(),
                )
            return ClaudeVibeProxyAttempt(
                attempted=False, required=False, ok=False, elapsed_seconds=_elapsed()
            )

    if resolved_policy.mode is TransportMode.DIRECT:
        return ClaudeVibeProxyAttempt(
            attempted=False, required=False, ok=False, elapsed_seconds=_elapsed()
        )

    required = resolved_policy.mode is TransportMode.REQUIRED
    timeout = 0.0
    try:
        timeout = _attempt_timeout(reviewer_timeout, resolved_policy.mode)
        # Discovery and the message leg SHARE the attempt budget: bound discovery
        # to a small cap and charge the message leg the remainder, so the two
        # legs sum to at most ``timeout`` instead of each drawing the full amount.
        discovery_timeout = min(timeout, _DISCOVERY_CAP_SECONDS)
        route = resolved_policy.resolve(
            "anthropic", model, capabilities=("chat",), timeout=discovery_timeout
        )
        if route.transport != "vibeproxy" or resolved_policy.client is None:
            return ClaudeVibeProxyAttempt(
                attempted=True,
                required=required,
                ok=False,
                error=route.fallback_reason or "VibeProxy route unavailable",
                timeout_seconds=timeout,
                elapsed_seconds=_elapsed(),
            )
        message_timeout = max(1.0, timeout - discovery_timeout)
        text = resolved_policy.client.anthropic_message(
            model=route.resolved_model,
            prompt=prompt,
            timeout=message_timeout,
        )
    except VibeProxyTimeoutError as exc:
        return ClaudeVibeProxyAttempt(
            attempted=True,
            required=required,
            ok=False,
            error=str(exc),
            timeout_seconds=timeout,
            elapsed_seconds=_elapsed(),
        )
    except VibeProxyConfigurationError as exc:
        # Reachable only in prefer/required mode (the policy already resolved).
        # Honor the resolved mode instead of forcing required.
        return ClaudeVibeProxyAttempt(
            attempted=True,
            required=required,
            ok=False,
            error=str(exc),
            timeout_seconds=timeout,
            elapsed_seconds=_elapsed(),
        )
    except VibeProxyUnavailableError as exc:
        return ClaudeVibeProxyAttempt(
            attempted=True,
            required=required,
            ok=False,
            error=str(exc),
            timeout_seconds=timeout,
            elapsed_seconds=_elapsed(),
        )
    except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        # The production client translates transport and response failures into
        # the typed exceptions above. Contain plausible injected policy/client
        # faults without turning this boundary into a blanket exception sink.
        # Log only the type because messages can contain credentials or bodies.
        logger.warning("Unexpected VibeProxy failure: %s", type(exc).__name__)
        return ClaudeVibeProxyAttempt(
            attempted=True,
            required=required,
            ok=False,
            error=f"Unexpected VibeProxy failure: {type(exc).__name__}",
            timeout_seconds=timeout,
            elapsed_seconds=_elapsed(),
        )
    return ClaudeVibeProxyAttempt(
        attempted=True,
        required=required,
        ok=True,
        text=text,
        # VibeProxyClient.anthropic_message() returns only after verifying that
        # the response body's model exactly matches the routed model.
        response_model=route.resolved_model,
        harness=f"{VIBEPROXY_HARNESS} (model: {route.resolved_model})",
        timeout_seconds=timeout,
        elapsed_seconds=_elapsed(),
    )


__all__ = [
    "ClaudeVibeProxyAttempt",
    "DEFAULT_CLAUDE_MODEL",
    "VIBEPROXY_HARNESS",
    "VIBEPROXY_TIMEOUT_ENV",
    "run_claude_vibeproxy",
]
