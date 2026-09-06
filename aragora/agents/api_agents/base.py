"""
Base class for API-based agents.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aragora.agents.base import CritiqueMixin
from aragora.core import Agent, Message
from aragora.core_types import AgentRole
from aragora.resilience import BaseCircuitBreaker, get_v2_circuit_breaker as get_circuit_breaker

if TYPE_CHECKING:
    from aragora.debate.complexity_governor import AdaptiveComplexityGovernor

logger = logging.getLogger(__name__)


class APIAgent(CritiqueMixin, Agent):
    """Base class for API-based agents.

    Includes circuit breaker protection for graceful failure handling.
    Supports dependency injection of circuit breaker for better testability.
    Supports persona-based generation parameters for diversity.
    """

    def __init__(
        self,
        name: str,
        model: str,
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        base_url: str | None = None,
        circuit_breaker: BaseCircuitBreaker | None = None,
        enable_circuit_breaker: bool = True,
        # Circuit breaker configuration (allows per-agent tuning)
        # Default threshold=5 provides faster failure detection for improved resilience
        # Default cooldown=60s balances recovery time with service availability
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 60.0,
        # Generation parameters (can be set from Persona)
        temperature: float | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        # Adaptive timeout configuration
        enable_adaptive_timeout: bool = True,
    ) -> None:
        super().__init__(name, model, role)
        self._base_timeout = timeout  # Store base timeout
        self.timeout = timeout  # Current effective timeout
        self.api_key = api_key
        self.base_url = base_url
        self.agent_type = "api"  # Default for API agents
        self.enable_circuit_breaker = enable_circuit_breaker
        self.enable_adaptive_timeout = enable_adaptive_timeout
        self._complexity_governor: AdaptiveComplexityGovernor | None = None

        # Generation parameters (from persona or explicit)
        self.temperature = temperature  # None means use provider default
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty

        # Use provided circuit breaker, global registry, or disable
        # Global registry ensures consistent state across agent instances
        self._circuit_breaker: BaseCircuitBreaker | None
        if circuit_breaker is not None:
            self._circuit_breaker = circuit_breaker
        elif enable_circuit_breaker:
            # Use global registry with agent name for shared state
            self._circuit_breaker = get_circuit_breaker(
                f"agent_{name}",
                failure_threshold=circuit_breaker_threshold,
                cooldown_seconds=circuit_breaker_cooldown,
            )
        else:
            self._circuit_breaker = None

        # Token usage tracking for billing
        self._last_tokens_in: int = 0
        self._last_tokens_out: int = 0
        self._total_tokens_in: int = 0
        self._total_tokens_out: int = 0

    def set_generation_params(
        self,
        temperature: float | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
    ) -> None:
        """Set generation parameters, typically from a Persona."""
        if temperature is not None:
            self.temperature = temperature
        if top_p is not None:
            self.top_p = top_p
        if frequency_penalty is not None:
            self.frequency_penalty = frequency_penalty

    def get_generation_params(self) -> dict[str, float]:
        """Get generation parameters as a dict (excludes None values)."""
        params = {}
        if self.temperature is not None:
            params["temperature"] = self.temperature
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            params["frequency_penalty"] = self.frequency_penalty
        return params

    @property
    def circuit_breaker(self) -> BaseCircuitBreaker | None:
        """Get the circuit breaker for this agent."""
        return self._circuit_breaker

    def is_circuit_open(self) -> bool:
        """Check if the circuit breaker is open (blocking requests)."""
        if self._circuit_breaker is None:
            return False
        return not self._circuit_breaker.can_proceed()

    def _record_token_usage(self, tokens_in: int, tokens_out: int) -> None:
        """Record token usage from an API call.

        Called by subclasses after successful API calls to track usage.

        Args:
            tokens_in: Input/prompt tokens used
            tokens_out: Output/completion tokens used
        """
        self._last_tokens_in = tokens_in
        self._last_tokens_out = tokens_out
        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out
        self._record_budget_spend(tokens_in, tokens_out)

    @property
    def billing_model(self) -> str:
        """Model id this call's token usage should be PRICED against.

        Normally ``self.model``. When the provider answered with a different
        model -- Anthropic's server-side refusal fallback, on by default for
        Fable 5.1 / Opus 5 -- the tokens were produced by, and billed by the
        provider at, the SERVED model's rate. Pricing them at the requested
        model's rate mis-states the spend in both directions depending on
        which is dearer (finding C-P3 on #9989); today a Fable request
        answered by Opus 4.8 is over-charged 2x.

        Subclasses that can observe the served model expose it as
        ``last_served_model`` (set only when it genuinely DIFFERS from the
        requested model, per the catalog). Anything else -- an agent that
        cannot tell, or a call the server answered without naming a model --
        falls back to ``self.model``, so the estimate is never worse than
        before this existed.
        """
        served = getattr(self, "last_served_model", None)
        return served if isinstance(served, str) and served else self.model

    def _record_budget_spend(self, tokens_in: int, tokens_out: int) -> None:
        """Debit this call's estimated USD cost against the monthly budget guard.

        Best-effort and default-OFF: a no-op unless ``ARAGORA_MONTHLY_BUDGET_USD``
        is set, and it never raises (metering must not break a call). Unknown
        providers fall back to OpenRouter pricing in ``calculate_token_cost``,
        which is conservative (it will not under-count cheap providers).
        Priced against :attr:`billing_model`, so a call a server-side fallback
        answered is debited at the model that actually produced the tokens.
        """
        try:
            from aragora.billing import budget_guard

            if not budget_guard.is_enabled():
                return
            from aragora.billing.usage import calculate_token_cost

            provider = getattr(self, "provider", None) or self.agent_type or "openrouter"
            cost = calculate_token_cost(str(provider), self.billing_model, tokens_in, tokens_out)
            budget_guard.record_spend(float(cost))
        except Exception:  # noqa: BLE001 - budget metering must never crash the agent
            logger.debug("budget_guard spend recording skipped", exc_info=True)

    def _enforce_budget_precall(self, estimated_usd: float = 0.0) -> None:
        """Fail-closed monthly-cap check before a metered API call.

        No-op unless ``ARAGORA_MONTHLY_BUDGET_USD`` is set. When the cap is
        reached it raises ``budget_guard.BudgetExceededError`` *before* the call,
        so spend cannot run away (the anti-$40k guard). Callers (agent
        ``generate``) invoke this at the top of a metered call.
        """
        from aragora.billing import budget_guard

        budget_guard.assert_within_budget(estimated_usd, label=self.name)

    def _estimate_budget_cost_from_text_usd(
        self,
        prompt_text: str,
        max_output_tokens: int,
    ) -> float:
        """Conservative spend estimate for streaming paths without usage metadata."""
        try:
            from aragora.billing.usage import calculate_token_cost

            provider = getattr(self, "provider", None) or self.agent_type or "openrouter"
            estimated_input_tokens = (len(prompt_text) + 3) // 4 if prompt_text else 0
            return float(
                calculate_token_cost(
                    str(provider),
                    self.model,
                    estimated_input_tokens,
                    max(0, int(max_output_tokens)),
                )
            )
        except Exception:  # noqa: BLE001 - budget estimation must not crash generation
            logger.debug("budget_guard text estimate skipped", exc_info=True)
            return 0.0

    @property
    def last_tokens_in(self) -> int:
        """Get input tokens from last API call."""
        return self._last_tokens_in

    @property
    def last_tokens_out(self) -> int:
        """Get output tokens from last API call."""
        return self._last_tokens_out

    @property
    def total_tokens_in(self) -> int:
        """Get total input tokens across all API calls."""
        return self._total_tokens_in

    @property
    def total_tokens_out(self) -> int:
        """Get total output tokens across all API calls."""
        return self._total_tokens_out

    def get_token_usage(self) -> dict[str, int]:
        """Get token usage summary for billing.

        Returns:
            Dict with tokens_in, tokens_out, total_tokens_in, total_tokens_out
        """
        return {
            "tokens_in": self._last_tokens_in,
            "tokens_out": self._last_tokens_out,
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
        }

    def reset_token_usage(self) -> None:
        """Reset token usage counters (e.g., at start of new debate)."""
        self._last_tokens_in = 0
        self._last_tokens_out = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0

    # =========================================================================
    # Adaptive Timeout Support
    # =========================================================================

    def set_complexity_governor(self, governor: AdaptiveComplexityGovernor | None) -> None:
        """Set the complexity governor for adaptive timeout management.

        When set, the agent will use the governor to determine timeouts
        based on task complexity and system stress levels.

        Args:
            governor: The AdaptiveComplexityGovernor instance, or None to disable
        """
        self._complexity_governor = governor
        if governor:
            logger.debug(
                "adaptive_timeout_enabled agent=%s complexity=%s",
                self.name,
                governor.task_complexity.value,
            )

    def get_effective_timeout(self) -> float:
        """Get the effective timeout for this agent.

        If adaptive timeout is enabled and a complexity governor is set,
        returns a timeout scaled by task complexity and system stress.
        Otherwise returns the base timeout.

        Returns:
            Timeout in seconds
        """
        if not self.enable_adaptive_timeout or self._complexity_governor is None:
            return float(self._base_timeout)

        # Get agent-specific constraints from governor
        constraints = self._complexity_governor.get_agent_constraints(self.name)
        adaptive_timeout = constraints.get("timeout_seconds", self._base_timeout)

        # Also consider complexity-scaled timeout
        scaled_timeout = self._complexity_governor.get_scaled_timeout(float(self._base_timeout))

        # Use the more conservative (lower) of the two
        effective = min(adaptive_timeout, scaled_timeout)

        # Update self.timeout for compatibility with existing code
        self.timeout = int(effective)

        logger.debug(
            f"adaptive_timeout_calc agent={self.name} "
            f"base={self._base_timeout} adaptive={adaptive_timeout:.0f} "
            f"scaled={scaled_timeout:.0f} effective={effective:.0f}"
        )

        return effective

    def record_response_to_governor(
        self,
        latency_ms: float,
        success: bool,
        response_tokens: int = 0,
    ) -> None:
        """Record a response to the complexity governor for metrics tracking.

        This feeds back performance data to the governor so it can adjust
        timeouts and constraints for future requests.

        Args:
            latency_ms: Response latency in milliseconds
            success: Whether the response was successful
            response_tokens: Number of tokens in response
        """
        if self._complexity_governor is None:
            return

        if success:
            self._complexity_governor.record_agent_response(
                self.name, latency_ms, success, response_tokens
            )
        else:
            # Timeouts are recorded separately
            if latency_ms >= self._base_timeout * 1000:
                self._complexity_governor.record_agent_timeout(self.name, self._base_timeout)
            else:
                self._complexity_governor.record_agent_response(
                    self.name, latency_ms, success, response_tokens
                )

    @property
    def base_timeout(self) -> int:
        """Get the base timeout (before adaptive adjustments)."""
        return self._base_timeout

    @base_timeout.setter
    def base_timeout(self, value: int) -> None:
        """Set the base timeout."""
        self._base_timeout = value
        self.timeout = value  # Also update current timeout

    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = False,
        sanitize_fn: object | None = None,
    ) -> str:
        """Build context from previous messages.

        Delegates to CritiqueMixin. API agents typically don't truncate.

        Args:
            context: List of previous messages
            truncate: Whether to truncate (default False for API agents)
            sanitize_fn: Optional sanitization function (unused by API agents)
        """
        # API agents typically don't need truncation, but respect the parameter
        return CritiqueMixin._build_context_prompt(self, context, truncate=truncate)

    # _parse_critique is inherited from CritiqueMixin


__all__ = ["APIAgent"]
