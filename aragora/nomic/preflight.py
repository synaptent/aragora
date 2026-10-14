"""
Preflight Health Check - Pre-cycle validation for nomic loop.

Validates system readiness before starting a nomic cycle:
- Provider availability (API keys, endpoints)
- Circuit breaker states
- Resource availability
- Agent health

Inspired by nomic loop debate consensus on wasted effort prevention.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a preflight check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    """Result of a single preflight check."""

    name: str
    status: CheckStatus
    message: str
    latency_ms: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class PreflightResult:
    """Overall preflight check result."""

    passed: bool
    checks: dict[str, CheckResult] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    recommended_agents: list[str] = field(default_factory=list)
    skipped_agents: list[str] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": {
                k: {"status": v.status.value, "message": v.message, "latency_ms": v.latency_ms}
                for k, v in self.checks.items()
            },
            "warnings": self.warnings,
            "blocking_issues": self.blocking_issues,
            "recommended_agents": self.recommended_agents,
            "skipped_agents": self.skipped_agents,
            "total_duration_ms": self.total_duration_ms,
        }


class PreflightHealthCheck:
    """
    Pre-cycle health validation system.

    Runs lightweight checks before starting a nomic cycle to:
    - Validate API keys are present
    - Check provider availability with minimal API calls
    - Verify circuit breakers are not all open
    - Recommend which agents to use

    Usage:
        preflight = PreflightHealthCheck()
        result = await preflight.run(timeout=10.0)

        if not result.passed:
            print("Preflight failed:", result.blocking_issues)
        else:
            print("Recommended agents:", result.recommended_agents)
    """

    # Provider configurations: (env_var, provider_name, model_hint)
    PROVIDER_CHECKS = [
        ("ANTHROPIC_API_KEY", "anthropic", "claude"),
        ("OPENAI_API_KEY", "openai", "gpt-4"),
        ("GEMINI_API_KEY", "gemini", "gemini"),
        ("OPENROUTER_API_KEY", "openrouter", "openrouter"),
        ("XAI_API_KEY", "xai", "grok"),
    ]

    # Agent to provider mapping
    AGENT_PROVIDERS = {
        "claude-visionary": "anthropic",
        "codex-engineer": "openai",
        "gemini-visionary": "gemini",
        "grok-lateral-thinker": "xai",
        "deepseek-v4-pro": "openrouter",
    }

    def __init__(self, min_required_agents: int = 2):
        """
        Initialize preflight check.

        Args:
            min_required_agents: Minimum agents needed to proceed
        """
        self.min_required_agents = min_required_agents

    async def run(self, timeout: float = 10.0) -> PreflightResult:
        """
        Run all preflight checks.

        Args:
            timeout: Maximum time for all checks (seconds)

        Returns:
            PreflightResult with pass/fail status and details
        """
        start_time = time.time()
        result = PreflightResult(passed=True)

        try:
            # Run checks in parallel
            checks = await asyncio.wait_for(
                asyncio.gather(
                    self._check_api_keys(),
                    self._check_circuit_breakers(),
                    self._check_providers_light(),
                    return_exceptions=True,
                ),
                timeout=timeout,
            )

            # Process results
            for check in checks:
                if isinstance(check, Exception):
                    result.blocking_issues.append(f"Check error: {check}")
                elif isinstance(check, CheckResult):
                    result.checks[check.name] = check
                    if check.status == CheckStatus.FAILED:
                        result.blocking_issues.append(check.message)
                    elif check.status == CheckStatus.WARNING:
                        result.warnings.append(check.message)
                elif isinstance(check, list):
                    # Multiple check results
                    for c in check:
                        if isinstance(c, CheckResult):
                            result.checks[c.name] = c
                            if c.status == CheckStatus.FAILED:
                                result.blocking_issues.append(c.message)
                            elif c.status == CheckStatus.WARNING:
                                result.warnings.append(c.message)

            # Determine available agents
            for agent_name, provider in self.AGENT_PROVIDERS.items():
                # Check which providers have keys
                provider_env = next((e for e, p, _ in self.PROVIDER_CHECKS if p == provider), None)
                if provider_env and os.environ.get(provider_env):
                    # Check if circuit breaker is closed
                    if not self._is_circuit_open(agent_name):
                        result.recommended_agents.append(agent_name)
                    else:
                        result.skipped_agents.append(agent_name)
                else:
                    result.skipped_agents.append(agent_name)

            # Check minimum agents
            if len(result.recommended_agents) < self.min_required_agents:
                result.blocking_issues.append(
                    f"Only {len(result.recommended_agents)} agents available, "
                    f"minimum {self.min_required_agents} required"
                )

            # Set overall pass/fail
            result.passed = len(result.blocking_issues) == 0

        except asyncio.TimeoutError:
            result.passed = False
            result.blocking_issues.append(f"Preflight checks timed out after {timeout}s")

        result.total_duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "preflight_complete passed=%s agents=%s duration=%.0fms",
            result.passed,
            len(result.recommended_agents),
            result.total_duration_ms,
        )

        return result

    async def _check_api_keys(self) -> CheckResult:
        """Check that at least one API key is available."""
        start = time.time()
        available = []

        for env_var, provider, _ in self.PROVIDER_CHECKS:
            if os.environ.get(env_var):
                available.append(provider)

        latency = (time.time() - start) * 1000

        if not available:
            return CheckResult(
                name="api_keys",
                status=CheckStatus.FAILED,
                message="No API keys found. Set at least one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY",
                latency_ms=latency,
            )

        if len(available) == 1:
            return CheckResult(
                name="api_keys",
                status=CheckStatus.WARNING,
                message=f"Only one provider available: {available[0]}",
                latency_ms=latency,
                details={"available": available},
            )

        return CheckResult(
            name="api_keys",
            status=CheckStatus.PASSED,
            message=f"{len(available)} API keys found: {', '.join(available)}",
            latency_ms=latency,
            details={"available": available},
        )

    async def _check_circuit_breakers(self) -> CheckResult:
        """Check circuit breaker states."""
        start = time.time()

        try:
            from aragora.resilience import get_circuit_breaker_status

            status = get_circuit_breaker_status()
            open_count = sum(1 for s in status.values() if s.get("status") == "open")
            total = len(status) if status else 0

            latency = (time.time() - start) * 1000

            if total == 0:
                return CheckResult(
                    name="circuit_breakers",
                    status=CheckStatus.PASSED,
                    message="No circuit breakers registered (fresh start)",
                    latency_ms=latency,
                )

            if open_count == total:
                return CheckResult(
                    name="circuit_breakers",
                    status=CheckStatus.FAILED,
                    message=f"All {total} circuit breakers are open",
                    latency_ms=latency,
                    details=status,
                )

            if open_count > 0:
                return CheckResult(
                    name="circuit_breakers",
                    status=CheckStatus.WARNING,
                    message=f"{open_count}/{total} circuit breakers open",
                    latency_ms=latency,
                    details=status,
                )

            return CheckResult(
                name="circuit_breakers",
                status=CheckStatus.PASSED,
                message=f"All {total} circuit breakers closed",
                latency_ms=latency,
            )

        except ImportError:
            return CheckResult(
                name="circuit_breakers",
                status=CheckStatus.SKIPPED,
                message="Circuit breaker module not available",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _check_providers_light(self) -> list[CheckResult]:
        """
        Light provider checks (no API calls, just basic validation).

        For actual API availability, use _check_providers_live() which
        makes minimal API calls.
        """
        results = []

        for env_var, provider, model in self.PROVIDER_CHECKS:
            if os.environ.get(env_var):
                # Just verify the key looks valid (basic format check)
                key = os.environ.get(env_var, "")
                if len(key) < 10:
                    results.append(
                        CheckResult(
                            name=f"provider_{provider}",
                            status=CheckStatus.WARNING,
                            message=f"{provider} API key looks too short",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            name=f"provider_{provider}",
                            status=CheckStatus.PASSED,
                            message=f"{provider} API key configured",
                        )
                    )

        return results

    async def _check_providers_live(self, timeout: float = 5.0) -> list[CheckResult]:
        """
        Live provider checks with actual API calls.

        Makes minimal API requests to verify connectivity.
        Use sparingly to avoid rate limits.
        """
        results = []
        tasks = []

        for env_var, provider, model in self.PROVIDER_CHECKS:
            if os.environ.get(env_var):
                tasks.append(self._probe_provider(provider, model, timeout))

        if tasks:
            probe_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in probe_results:
                if isinstance(result, CheckResult):
                    results.append(result)

        return results

    async def _probe_provider(
        self,
        provider: str,
        model: str,
        timeout: float,
    ) -> CheckResult:
        """Probe a single provider with minimal request."""
        start = time.time()

        try:
            # Minimal probe based on provider
            if provider == "anthropic":
                import anthropic

                client = anthropic.AsyncAnthropic()
                # Just check auth by making a minimal request
                await asyncio.wait_for(
                    client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=1,
                        messages=[{"role": "user", "content": "ping"}],
                    ),
                    timeout=timeout,
                )

            elif provider == "openai":
                from openai import AsyncOpenAI

                openai_client = AsyncOpenAI()
                await asyncio.wait_for(
                    openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        max_tokens=1,
                        messages=[{"role": "user", "content": "ping"}],
                    ),
                    timeout=timeout,
                )

            latency = (time.time() - start) * 1000
            return CheckResult(
                name=f"provider_{provider}_live",
                status=CheckStatus.PASSED,
                message=f"{provider} responding ({latency:.0f}ms)",
                latency_ms=latency,
            )

        except asyncio.TimeoutError:
            return CheckResult(
                name=f"provider_{provider}_live",
                status=CheckStatus.WARNING,
                message=f"{provider} timed out after {timeout}s",
                latency_ms=(time.time() - start) * 1000,
            )
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            return CheckResult(
                name=f"provider_{provider}_live",
                status=CheckStatus.FAILED,
                message=f"{provider} error: {type(e).__name__}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _get_available_api_keys(self) -> list[str]:
        """Get list of available provider names based on API keys."""
        available = []
        for env_var, provider, _ in self.PROVIDER_CHECKS:
            if os.environ.get(env_var):
                available.append(provider)
        return available

    def _is_circuit_open(self, agent_name: str) -> bool:
        """Check if circuit breaker is open for an agent."""
        try:
            from aragora.resilience import get_circuit_breaker_status

            status = get_circuit_breaker_status()
            agent_status = status.get(agent_name, {})
            return agent_status.get("status") == "open"
        except ImportError:
            return False


async def run_preflight(
    timeout: float = 10.0,
    min_agents: int = 2,
    emit_to_immune: bool = True,
) -> PreflightResult:
    """
    Convenience function to run preflight checks.

    Args:
        timeout: Check timeout in seconds
        min_agents: Minimum required agents
        emit_to_immune: Whether to emit health events

    Returns:
        PreflightResult with status and recommendations
    """
    check = PreflightHealthCheck(min_required_agents=min_agents)
    result = await check.run(timeout=timeout)

    if emit_to_immune:
        try:
            from aragora.debate.immune_system import get_immune_system

            immune = get_immune_system()
            immune.system_event(
                event_type="preflight_complete",
                message=f"Preflight {'passed' if result.passed else 'failed'}",
                details=result.to_dict(),
                audience_message=(
                    f"System ready with {len(result.recommended_agents)} agents!"
                    if result.passed
                    else f"System issues detected: {', '.join(result.blocking_issues)}"
                ),
            )
        except ImportError:
            pass

    return result
