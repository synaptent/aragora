"""
Resource Tracking for Workflow Execution.

Extracted from engine_v2.py to enable composition-based resource tracking.
Any workflow executor can use ResourceTracker to add resource management
without requiring inheritance.

Usage:
    from aragora.workflow.resource_tracker import ResourceTracker, ResourceLimits

    # Create tracker with limits
    tracker = ResourceTracker(
        limits=ResourceLimits(max_tokens=100000, max_cost_usd=5.0)
    )

    # Track usage during execution
    tracker.start()
    cost = tracker.add_tokens("step1", "claude", input_tokens=500, output_tokens=200)
    tracker.add_api_call()

    # Check limits
    if tracker.check_limits():
        print("Within limits")
    else:
        print(f"Limit exceeded: {tracker.limit_exceeded_type}")

    # Get metrics
    print(tracker.get_metrics())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.models.pricing_mirror import per_1k_rows


# Model pricing, USD per 1K tokens.
#
# The hand-written rows below are HISTORICAL and stay exactly as they were:
# a workflow record or a test that names ``gpt-4o`` must keep pricing at
# gpt-4o's rate, and the family labels ("claude", "gemini", "grok", ...) are
# what ``ResourceTracker.add_tokens`` actually receives as ``agent_type``.
# What they did NOT have was a row for any CURRENT frontier model, so every
# live call fell through to the ``default`` estimate (2026-09-04 controller
# ruling, wave 3). ``per_1k_rows()`` adds one row per spelling of every
# active catalog row; the catalog wins a key collision because it is the
# more recently verified rate (the same convention the five phase-2 pricing
# tables use).
_LEGACY_MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-opus-4": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4": {"input": 0.003, "output": 0.015},
    "claude": {"input": 0.003, "output": 0.015},  # Default to sonnet
    # OpenAI
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "o1": {"input": 0.015, "output": 0.06},
    "o1-mini": {"input": 0.003, "output": 0.012},
    "o3-mini": {"input": 0.003, "output": 0.012},
    # Google
    "gemini-3.1-pro-preview": {"input": 0.002, "output": 0.012},
    "gemini-pro": {"input": 0.00025, "output": 0.0005},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    "gemini": {"input": 0.00025, "output": 0.0005},
    # Mistral
    "mistral-large": {"input": 0.004, "output": 0.012},
    "mistral-medium": {"input": 0.0027, "output": 0.0081},
    "mistral": {"input": 0.004, "output": 0.012},
    "codestral": {"input": 0.001, "output": 0.003},
    # xAI
    "grok": {"input": 0.005, "output": 0.015},
    "grok-2": {"input": 0.005, "output": 0.015},
    # DeepSeek
    "deepseek": {"input": 0.00174, "output": 0.00348},
    "deepseek-v4-pro": {"input": 0.00174, "output": 0.00348},
    "deepseek-v3": {"input": 0.00014, "output": 0.00028},
    # Others
    "llama": {"input": 0.0002, "output": 0.0002},
    "qwen": {"input": 0.0003, "output": 0.0003},
    # Default fallback
    "default": {"input": 0.003, "output": 0.015},
}

MODEL_PRICING: dict[str, dict[str, float]] = {**_LEGACY_MODEL_PRICING, **per_1k_rows()}


class ResourceExhaustedError(Exception):
    """Raised when resource limits are exceeded."""

    pass


class ResourceType(Enum):
    """Types of resources tracked."""

    TOKENS = "tokens"
    COST = "cost"
    TIME = "time"
    API_CALLS = "api_calls"


@dataclass
class ResourceLimits:
    """Resource limits for workflow execution."""

    max_tokens: int = 100000
    max_cost_usd: float = 10.0
    timeout_seconds: float = 600.0
    max_api_calls: int = 100
    max_parallel_agents: int = 5
    max_retries_per_step: int = 3

    # Warning thresholds (percentage of limit)
    warning_threshold: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "timeout_seconds": self.timeout_seconds,
            "max_api_calls": self.max_api_calls,
            "max_parallel_agents": self.max_parallel_agents,
            "max_retries_per_step": self.max_retries_per_step,
            "warning_threshold": self.warning_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceLimits:
        """Create from dictionary."""
        return cls(
            max_tokens=data.get("max_tokens", 100000),
            max_cost_usd=data.get("max_cost_usd", 10.0),
            timeout_seconds=data.get("timeout_seconds", 600.0),
            max_api_calls=data.get("max_api_calls", 100),
            max_parallel_agents=data.get("max_parallel_agents", 5),
            max_retries_per_step=data.get("max_retries_per_step", 3),
            warning_threshold=data.get("warning_threshold", 0.8),
        )


@dataclass
class ResourceUsage:
    """Tracks resource usage during workflow execution."""

    tokens_used: int = 0
    cost_usd: float = 0.0
    time_elapsed_seconds: float = 0.0
    api_calls: int = 0

    # Per-step tracking
    step_tokens: dict[str, int] = field(default_factory=dict)
    step_costs: dict[str, float] = field(default_factory=dict)
    step_durations: dict[str, float] = field(default_factory=dict)

    # Per-agent tracking
    agent_tokens: dict[str, int] = field(default_factory=dict)
    agent_costs: dict[str, float] = field(default_factory=dict)

    def add_tokens(
        self,
        step_id: str,
        agent_type: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """
        Add token usage and calculate cost.

        Args:
            step_id: Step that used the tokens
            agent_type: Type of agent/model (e.g., "claude", "gpt-4")
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens

        Returns:
            Cost in USD for this token usage
        """
        total_tokens = input_tokens + output_tokens
        self.tokens_used += total_tokens
        self.step_tokens[step_id] = self.step_tokens.get(step_id, 0) + total_tokens
        self.agent_tokens[agent_type] = self.agent_tokens.get(agent_type, 0) + total_tokens

        # Calculate cost
        pricing = MODEL_PRICING.get(agent_type.lower(), MODEL_PRICING["default"])
        cost = (input_tokens / 1000) * pricing["input"] + (output_tokens / 1000) * pricing["output"]
        self.cost_usd += cost
        self.step_costs[step_id] = self.step_costs.get(step_id, 0.0) + cost
        self.agent_costs[agent_type] = self.agent_costs.get(agent_type, 0.0) + cost

        return cost

    def add_api_call(self) -> None:
        """Record an API call."""
        self.api_calls += 1

    def add_step_duration(self, step_id: str, duration_seconds: float) -> None:
        """Record step duration."""
        self.step_durations[step_id] = duration_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "time_elapsed_seconds": self.time_elapsed_seconds,
            "api_calls": self.api_calls,
            "step_tokens": self.step_tokens,
            "step_costs": self.step_costs,
            "step_durations": self.step_durations,
            "agent_tokens": self.agent_tokens,
            "agent_costs": self.agent_costs,
        }

    def reset(self) -> None:
        """Reset all usage counters."""
        self.tokens_used = 0
        self.cost_usd = 0.0
        self.time_elapsed_seconds = 0.0
        self.api_calls = 0
        self.step_tokens.clear()
        self.step_costs.clear()
        self.step_durations.clear()
        self.agent_tokens.clear()
        self.agent_costs.clear()


class ResourceTracker:
    """
    Composable resource tracking for workflow execution.

    Can be used standalone or injected into any workflow executor
    to add resource tracking and limit enforcement.

    Example:
        tracker = ResourceTracker(ResourceLimits(max_cost_usd=5.0))
        tracker.start()

        # During execution
        tracker.add_tokens("step1", "claude", 500, 200)

        # Check if still within limits
        if not tracker.check_limits():
            raise ResourceExhaustedError(tracker.get_limit_message())
    """

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        on_warning: Callable[[ResourceType, float], None] | None = None,
    ):
        """
        Initialize the resource tracker.

        Args:
            limits: Resource limits to enforce (uses defaults if None)
            on_warning: Callback when approaching limits (receives type, percentage)
        """
        self._limits = limits or ResourceLimits()
        self._usage = ResourceUsage()
        self._start_time: float | None = None
        self._on_warning = on_warning
        self._warnings_issued: set[tuple[ResourceType, int]] = set()

    @property
    def limits(self) -> ResourceLimits:
        """Get current resource limits."""
        return self._limits

    @property
    def usage(self) -> ResourceUsage:
        """Get current resource usage."""
        return self._usage

    def set_limits(self, limits: ResourceLimits) -> None:
        """Update resource limits."""
        self._limits = limits

    def start(self) -> None:
        """Start tracking (resets usage and starts timer)."""
        self._usage.reset()
        self._start_time = time.time()
        self._warnings_issued.clear()

    def stop(self) -> None:
        """Stop tracking and finalize elapsed time."""
        if self._start_time:
            self._usage.time_elapsed_seconds = time.time() - self._start_time

    def add_tokens(
        self,
        step_id: str,
        agent_type: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """
        Add token usage and return cost.

        Also checks warning thresholds and emits warnings if needed.
        """
        cost = self._usage.add_tokens(step_id, agent_type, input_tokens, output_tokens)
        self._check_warnings()
        return cost

    def add_api_call(self) -> None:
        """Record an API call."""
        self._usage.add_api_call()
        self._check_warnings()

    def add_step_duration(self, step_id: str, duration_seconds: float) -> None:
        """Record step duration."""
        self._usage.add_step_duration(step_id, duration_seconds)

    def update_elapsed_time(self) -> float:
        """Update and return elapsed time."""
        if self._start_time:
            self._usage.time_elapsed_seconds = time.time() - self._start_time
        return self._usage.time_elapsed_seconds

    def _check_warnings(self) -> None:
        """Check and emit warnings for approaching limits."""
        if not self._on_warning:
            return

        # Token warning
        token_pct = self._usage.tokens_used / self._limits.max_tokens
        self._emit_warning_if_threshold(ResourceType.TOKENS, token_pct)

        # Cost warning
        cost_pct = self._usage.cost_usd / self._limits.max_cost_usd
        self._emit_warning_if_threshold(ResourceType.COST, cost_pct)

        # API calls warning
        api_pct = self._usage.api_calls / self._limits.max_api_calls
        self._emit_warning_if_threshold(ResourceType.API_CALLS, api_pct)

        # Time warning
        if self._start_time:
            elapsed = time.time() - self._start_time
            time_pct = elapsed / self._limits.timeout_seconds
            self._emit_warning_if_threshold(ResourceType.TIME, time_pct)

    def _emit_warning_if_threshold(self, resource_type: ResourceType, percentage: float) -> None:
        """Emit warning if threshold crossed and not already warned."""
        threshold_pct = int(self._limits.warning_threshold * 100)
        key = (resource_type, threshold_pct)

        if percentage >= self._limits.warning_threshold and key not in self._warnings_issued:
            self._warnings_issued.add(key)
            if self._on_warning:
                self._on_warning(resource_type, percentage)

    def check_limits(self) -> bool:
        """
        Check if all resource limits are within bounds.

        Returns:
            True if within limits, False if any limit exceeded
        """
        if self._usage.tokens_used >= self._limits.max_tokens:
            return False
        if self._usage.cost_usd >= self._limits.max_cost_usd:
            return False
        if self._usage.api_calls >= self._limits.max_api_calls:
            return False
        if self._start_time:
            elapsed = time.time() - self._start_time
            if elapsed >= self._limits.timeout_seconds:
                return False
        return True

    def check_limits_or_raise(self) -> None:
        """Check limits and raise ResourceExhaustedError if exceeded."""
        if self._usage.tokens_used >= self._limits.max_tokens:
            raise ResourceExhaustedError(
                f"Token limit exceeded: {self._usage.tokens_used} >= {self._limits.max_tokens}"
            )

        if self._usage.cost_usd >= self._limits.max_cost_usd:
            raise ResourceExhaustedError(
                f"Cost limit exceeded: ${self._usage.cost_usd:.4f} >= ${self._limits.max_cost_usd}"
            )

        if self._usage.api_calls >= self._limits.max_api_calls:
            raise ResourceExhaustedError(
                f"API call limit exceeded: {self._usage.api_calls} >= {self._limits.max_api_calls}"
            )

        if self._start_time:
            elapsed = time.time() - self._start_time
            if elapsed >= self._limits.timeout_seconds:
                raise ResourceExhaustedError(
                    f"Time limit exceeded: {elapsed:.1f}s >= {self._limits.timeout_seconds}s"
                )

    @property
    def limit_exceeded_type(self) -> ResourceType | None:
        """Get the type of limit that was exceeded, if any."""
        if self._usage.tokens_used >= self._limits.max_tokens:
            return ResourceType.TOKENS
        if self._usage.cost_usd >= self._limits.max_cost_usd:
            return ResourceType.COST
        if self._usage.api_calls >= self._limits.max_api_calls:
            return ResourceType.API_CALLS
        if self._start_time:
            elapsed = time.time() - self._start_time
            if elapsed >= self._limits.timeout_seconds:
                return ResourceType.TIME
        return None

    def get_limit_message(self) -> str | None:
        """Get a human-readable message about the exceeded limit."""
        limit_type = self.limit_exceeded_type
        if limit_type == ResourceType.TOKENS:
            return f"Token limit exceeded: {self._usage.tokens_used}/{self._limits.max_tokens}"
        if limit_type == ResourceType.COST:
            return f"Cost limit exceeded: ${self._usage.cost_usd:.4f}/${self._limits.max_cost_usd}"
        if limit_type == ResourceType.API_CALLS:
            return f"API call limit exceeded: {self._usage.api_calls}/{self._limits.max_api_calls}"
        if limit_type == ResourceType.TIME:
            elapsed = self._usage.time_elapsed_seconds
            return f"Time limit exceeded: {elapsed:.1f}s/{self._limits.timeout_seconds}s"
        return None

    def get_metrics(self) -> dict[str, Any]:
        """Get comprehensive metrics."""
        self.update_elapsed_time()
        return {
            "usage": self._usage.to_dict(),
            "limits": self._limits.to_dict(),
            "within_limits": self.check_limits(),
            "limit_exceeded_type": (
                self.limit_exceeded_type.value if self.limit_exceeded_type else None
            ),
        }

    def estimate_cost(
        self,
        agent_type: str,
        estimated_tokens: int = 1000,
    ) -> float:
        """
        Estimate cost for a single operation.

        Args:
            agent_type: Type of agent/model
            estimated_tokens: Estimated total tokens (split 50/50 input/output)

        Returns:
            Estimated cost in USD
        """
        pricing = MODEL_PRICING.get(agent_type.lower(), MODEL_PRICING["default"])
        input_tokens = estimated_tokens // 2
        output_tokens = estimated_tokens - input_tokens
        return (input_tokens / 1000) * pricing["input"] + (output_tokens / 1000) * pricing["output"]


__all__ = [
    "ResourceTracker",
    "ResourceLimits",
    "ResourceUsage",
    "ResourceType",
    "ResourceExhaustedError",
    "MODEL_PRICING",
]
