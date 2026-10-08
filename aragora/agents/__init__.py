"""
Agent implementations for various AI models.

The package used to eagerly import nearly every agent subsystem at module import
time. That made lightweight imports like ``aragora.agents.base`` or
``aragora.agents.demo_agent`` drag in ranking, storage, billing, and external
credential initialization. Keep package import cheap and resolve exports lazily.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)

_OPTIONAL_MODULE_EXPORTS = {
    "aragora.agents.api_agents": {
        "AnthropicAPIAgent",
        "DeepSeekAgent",
        "DeepSeekReasonerAgent",
        "DeepSeekV3Agent",
        "GeminiAgent",
        "GrokAgent",
        "LlamaAgent",
        "LMStudioAgent",
        "MistralAgent",
        "OllamaAgent",
        "OpenAIAPIAgent",
        "OpenRouterAgent",
    },
}

_EXPORT_MAP = {
    "AirlockConfig": ("aragora.agents.airlock", "AirlockConfig"),
    "AirlockMetrics": ("aragora.agents.airlock", "AirlockMetrics"),
    "AirlockProxy": ("aragora.agents.airlock", "AirlockProxy"),
    "wrap_agent": ("aragora.agents.airlock", "wrap_agent"),
    "wrap_agents": ("aragora.agents.airlock", "wrap_agents"),
    "AgentConfig": ("aragora.agents.config_loader", "AgentConfig"),
    "AgentConfigLoader": ("aragora.agents.config_loader", "AgentConfigLoader"),
    "ConfigValidationError": ("aragora.agents.config_loader", "ConfigValidationError"),
    "load_agent_configs": ("aragora.agents.config_loader", "load_agent_configs"),
    "AnthropicAPIAgent": ("aragora.agents.api_agents", "AnthropicAPIAgent"),
    "DeepSeekAgent": ("aragora.agents.api_agents", "DeepSeekAgent"),
    "DeepSeekReasonerAgent": ("aragora.agents.api_agents", "DeepSeekReasonerAgent"),
    "DeepSeekV3Agent": ("aragora.agents.api_agents", "DeepSeekV3Agent"),
    "GeminiAgent": ("aragora.agents.api_agents", "GeminiAgent"),
    "GrokAgent": ("aragora.agents.api_agents", "GrokAgent"),
    "LlamaAgent": ("aragora.agents.api_agents", "LlamaAgent"),
    "LMStudioAgent": ("aragora.agents.api_agents", "LMStudioAgent"),
    "MistralAgent": ("aragora.agents.api_agents", "MistralAgent"),
    "OllamaAgent": ("aragora.agents.api_agents", "OllamaAgent"),
    "OpenAIAPIAgent": ("aragora.agents.api_agents", "OpenAIAPIAgent"),
    "OpenRouterAgent": ("aragora.agents.api_agents", "OpenRouterAgent"),
    "create_agent": ("aragora.agents.base", "create_agent"),
    "list_available_agents": ("aragora.agents.base", "list_available_agents"),
    "CalibrationBucket": ("aragora.agents.calibration", "CalibrationBucket"),
    "CalibrationSummary": ("aragora.agents.calibration", "CalibrationSummary"),
    "CalibrationTracker": ("aragora.agents.calibration", "CalibrationTracker"),
    "ClaudeAgent": ("aragora.agents.cli_agents", "ClaudeAgent"),
    "CodexAgent": ("aragora.agents.cli_agents", "CodexAgent"),
    "DeepseekCLIAgent": ("aragora.agents.cli_agents", "DeepseekCLIAgent"),
    "GeminiCLIAgent": ("aragora.agents.cli_agents", "GeminiCLIAgent"),
    "GrokCLIAgent": ("aragora.agents.cli_agents", "GrokCLIAgent"),
    "KiloCodeAgent": ("aragora.agents.cli_agents", "KiloCodeAgent"),
    "OpenAIAgent": ("aragora.agents.cli_agents", "OpenAIAgent"),
    "QwenCLIAgent": ("aragora.agents.cli_agents", "QwenCLIAgent"),
    "DemoAgent": ("aragora.agents.demo_agent", "DemoAgent"),
    "QUOTA_ERROR_KEYWORDS": ("aragora.agents.fallback", "QUOTA_ERROR_KEYWORDS"),
    "AgentFallbackChain": ("aragora.agents.fallback", "AgentFallbackChain"),
    "AllProvidersExhaustedError": ("aragora.agents.fallback", "AllProvidersExhaustedError"),
    "FallbackMetrics": ("aragora.agents.fallback", "FallbackMetrics"),
    "QuotaFallbackMixin": ("aragora.agents.fallback", "QuotaFallbackMixin"),
    "EmergentTrait": ("aragora.agents.laboratory", "EmergentTrait"),
    "PersonaExperiment": ("aragora.agents.laboratory", "PersonaExperiment"),
    "PersonaLaboratory": ("aragora.agents.laboratory", "PersonaLaboratory"),
    "TraitTransfer": ("aragora.agents.laboratory", "TraitTransfer"),
    "LocalLLMDetector": ("aragora.agents.local_llm_detector", "LocalLLMDetector"),
    "LocalLLMServer": ("aragora.agents.local_llm_detector", "LocalLLMServer"),
    "LocalLLMStatus": ("aragora.agents.local_llm_detector", "LocalLLMStatus"),
    "detect_local_llms": ("aragora.agents.local_llm_detector", "detect_local_llms"),
    "detect_local_llms_sync": ("aragora.agents.local_llm_detector", "detect_local_llms_sync"),
    "AgentMetric": ("aragora.agents.performance_monitor", "AgentMetric"),
    "AgentPerformanceMonitor": ("aragora.agents.performance_monitor", "AgentPerformanceMonitor"),
    "AgentStats": ("aragora.agents.performance_monitor", "AgentStats"),
    "EXPERTISE_DOMAINS": ("aragora.agents.personas", "EXPERTISE_DOMAINS"),
    "PERSONALITY_TRAITS": ("aragora.agents.personas", "PERSONALITY_TRAITS"),
    "Persona": ("aragora.agents.personas", "Persona"),
    "PersonaManager": ("aragora.agents.personas", "PersonaManager"),
    "AgentRegistry": ("aragora.agents.registry", "AgentRegistry"),
    "register_all_agents": ("aragora.agents.registry", "register_all_agents"),
    "AgentTelemetry": ("aragora.agents.telemetry", "AgentTelemetry"),
    "TelemetryContext": ("aragora.agents.telemetry", "TelemetryContext"),
    "get_telemetry_stats": ("aragora.agents.telemetry", "get_telemetry_stats"),
    "register_telemetry_collector": ("aragora.agents.telemetry", "register_telemetry_collector"),
    "reset_telemetry": ("aragora.agents.telemetry", "reset_telemetry"),
    "setup_default_collectors": ("aragora.agents.telemetry", "setup_default_collectors"),
    "unregister_telemetry_collector": (
        "aragora.agents.telemetry",
        "unregister_telemetry_collector",
    ),
    "with_telemetry": ("aragora.agents.telemetry", "with_telemetry"),
    "PowerSamplingMixin": ("aragora.agents.power_sampling_mixin", "PowerSamplingMixin"),
    "SDPOLearner": ("aragora.agents.learning", "SDPOLearner"),
    "SDPOConfig": ("aragora.agents.learning", "SDPOConfig"),
    "SDPOCalibrationBridge": ("aragora.agents.learning", "SDPOCalibrationBridge"),
    "SDPOCalibrationConfig": ("aragora.agents.learning", "SDPOCalibrationConfig"),
    "integrate_sdpo_with_calibration": (
        "aragora.agents.learning",
        "integrate_sdpo_with_calibration",
    ),
    "SchedulerProtocol": ("aragora.agents.scheduler_protocol", "SchedulerProtocol"),
    "SchedulerType": ("aragora.agents.scheduler_protocol", "SchedulerType"),
    "TaskInfo": ("aragora.agents.scheduler_protocol", "TaskInfo"),
    "LocalSchedulerAdapter": ("aragora.agents.scheduler_protocol", "LocalSchedulerAdapter"),
    "DistributedSchedulerAdapter": (
        "aragora.agents.scheduler_protocol",
        "DistributedSchedulerAdapter",
    ),
    "get_scheduler": ("aragora.agents.scheduler_protocol", "get_scheduler"),
    "reset_scheduler": ("aragora.agents.scheduler_protocol", "reset_scheduler"),
    "SenderReputationAgent": ("aragora.agents.email_agents", "SenderReputationAgent"),
    "ContentUrgencyAgent": ("aragora.agents.email_agents", "ContentUrgencyAgent"),
    "ContextRelevanceAgent": ("aragora.agents.email_agents", "ContextRelevanceAgent"),
    "BillingCriticalityAgent": ("aragora.agents.email_agents", "BillingCriticalityAgent"),
    "TimelineAgent": ("aragora.agents.email_agents", "TimelineAgent"),
    "get_email_agent_team": ("aragora.agents.email_agents", "get_email_agent_team"),
    "CredentialStatus": ("aragora.agents.credential_validator", "CredentialStatus"),
    "filter_available_agents": ("aragora.agents.credential_validator", "filter_available_agents"),
    "get_agent_credential_status": (
        "aragora.agents.credential_validator",
        "get_agent_credential_status",
    ),
    "get_available_agent_types": (
        "aragora.agents.credential_validator",
        "get_available_agent_types",
    ),
    "get_credential_status": ("aragora.agents.credential_validator", "get_credential_status"),
    "get_missing_credentials_summary": (
        "aragora.agents.credential_validator",
        "get_missing_credentials_summary",
    ),
    "log_credential_status": ("aragora.agents.credential_validator", "log_credential_status"),
    "validate_agent_credentials": (
        "aragora.agents.credential_validator",
        "validate_agent_credentials",
    ),
}

__all__ = sorted(set(_EXPORT_MAP) | {"get_agents_by_names"})


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORT_MAP[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    try:
        module = importlib.import_module(module_name)
    except ImportError:
        if attr_name not in _OPTIONAL_MODULE_EXPORTS.get(module_name, set()):
            raise
        value = None
        globals()[name] = value
        return value

    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def get_agents_by_names(names: list[str]) -> list:
    """Get agent instances for the supplied registered type names."""
    from aragora.agents.base import AgentType, create_agent
    from aragora.agents.registry import AgentRegistry, register_all_agents

    register_all_agents()

    agents = []
    for name in names:
        try:
            if AgentRegistry.is_registered(name):
                agents.append(create_agent(cast(AgentType, name)))
        except ImportError:
            pass
        except (RuntimeError, ValueError) as exc:
            logger.debug("agent_create_failed name=%s: %s", name, exc)
    return agents
