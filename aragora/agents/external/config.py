"""Configuration for external agent framework adapters.

Provides dataclasses for configuring external agent adapters with
circuit breaker settings, security controls, and resource limits.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkspaceType(str, Enum):
    """Workspace isolation mode for external agent execution."""

    LOCAL = "local"  # Local filesystem (dev only)
    DOCKER = "docker"  # Docker container per session
    KUBERNETES = "kubernetes"  # K8s pod per tenant


class ApprovalMode(str, Enum):
    """How high-risk operations are handled."""

    AUTO = "auto"  # Automatic based on policy
    MANUAL = "manual"  # Always require human approval
    DENY = "deny"  # Never allow (block at gate)


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Circuit breaker configuration for external agent operations."""

    failure_threshold: int = 5
    success_threshold: int = 3
    cooldown_seconds: float = 60.0
    half_open_max_requests: int = 2


@dataclass
class ToolConfig:
    """Configuration for a single external agent tool.

    Controls whether a tool is enabled, its risk level, and how
    it's handled by the security layer.
    """

    enabled: bool = True
    permission_key: str = ""
    risk_level: str = "low"  # low, medium, high
    approval_mode: ApprovalMode = ApprovalMode.AUTO
    timeout_seconds: float = 300.0
    max_retries: int = 2
    allowed_paths: list[str] = field(default_factory=list)  # For file tools
    blocked_patterns: list[str] = field(default_factory=list)  # Regex patterns


@dataclass
class WorkspaceConfig:
    """Workspace isolation configuration for external agents."""

    type: WorkspaceType = WorkspaceType.DOCKER
    base_image: str = "python:3.11-slim"
    memory_limit_mb: int = 2048
    cpu_limit: float = 1.0
    timeout_seconds: float = 3600.0  # 1 hour max session
    network_enabled: bool = True
    mount_secrets: bool = False  # Never mount secrets directly
    cleanup_on_exit: bool = True
    base_path: str = field(
        default_factory=lambda: os.path.join(tempfile.gettempdir(), "aragora-workspaces")
    )


@dataclass
class ExternalAgentConfig:
    """Base configuration for external agent adapters.

    This is the base config class that all adapter-specific configs
    should inherit from. Provides common settings for circuit breakers,
    security, and resource limits.
    """

    # Adapter identification
    adapter_name: str = "base"

    # Connection settings
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 3600.0
    max_concurrent_tasks: int = 5
    retry_attempts: int = 3
    retry_delay_seconds: float = 5.0

    # Circuit breaker settings
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    # Security settings
    allowed_tools: set[str] = field(default_factory=set)
    blocked_tools: set[str] = field(default_factory=set)
    max_file_size_mb: int = 100
    allowed_domains: set[str] = field(default_factory=set)

    # Resource limits
    max_tokens_per_task: int = 100000
    max_cost_per_task_usd: float = 10.0

    # Audit settings
    log_all_outputs: bool = True
    redact_secrets: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "adapter_name": self.adapter_name,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "retry_attempts": self.retry_attempts,
            "circuit_breaker": {
                "failure_threshold": self.circuit_breaker.failure_threshold,
                "success_threshold": self.circuit_breaker.success_threshold,
                "cooldown_seconds": self.circuit_breaker.cooldown_seconds,
            },
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "max_tokens_per_task": self.max_tokens_per_task,
            "max_cost_per_task_usd": self.max_cost_per_task_usd,
            "redact_secrets": self.redact_secrets,
        }


@dataclass
class OpenHandsConfig(ExternalAgentConfig):
    """OpenHands-specific configuration.

    Configures the OpenHands adapter with settings for the OpenHands
    server, LLM, workspace, and tool permissions.
    """

    adapter_name: str = "openhands"
    base_url: str = field(
        default_factory=lambda: os.getenv("OPENHANDS_URL", "http://localhost:3000")
    )

    # LLM settings
    model: str = "claude-sonnet-4-6"
    api_key_secret_name: str = "ANTHROPIC_API_KEY"  # noqa: S105 -- env var name
    temperature: float = 0.0
    max_tokens: int = 4096

    # Workspace settings
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    sandbox_type: str = "docker"  # docker, e2b, local

    # OpenHands-specific tool configs
    tools: dict[str, ToolConfig] = field(
        default_factory=lambda: {
            "TerminalTool": ToolConfig(
                permission_key="external_agents:tool:shell_execute",
                risk_level="high",
                approval_mode=ApprovalMode.AUTO,
                timeout_seconds=60.0,
                blocked_patterns=[
                    r"rm\s+-rf\s+/",
                    r"sudo\s+",
                    r"curl.*\|.*sh",
                ],
            ),
            "FileEditorTool": ToolConfig(
                permission_key="external_agents:tool:file_write",
                risk_level="high",
                approval_mode=ApprovalMode.AUTO,
                allowed_paths=["./workspace/", tempfile.gettempdir() + "/"],
                blocked_patterns=[r"\.env$", r"credentials", r"\.key$"],
            ),
            "BrowserTool": ToolConfig(
                permission_key="external_agents:tool:browser_use",
                risk_level="high",
                approval_mode=ApprovalMode.MANUAL,
                timeout_seconds=120.0,
            ),
            "TaskTrackerTool": ToolConfig(
                permission_key="external_agents:execute",
                risk_level="low",
                approval_mode=ApprovalMode.AUTO,
            ),
        }
    )


@dataclass
class AutoGPTConfig(ExternalAgentConfig):
    """AutoGPT-specific configuration (placeholder)."""

    adapter_name: str = "autogpt"
    base_url: str = field(default_factory=lambda: os.getenv("AUTOGPT_URL", "http://localhost:8000"))
    agent_id: str | None = None


@dataclass
class CrewAIConfig(ExternalAgentConfig):
    """CrewAI-specific configuration (placeholder)."""

    adapter_name: str = "crewai"
    crew_config_path: str | None = None
    verbose: bool = False


def get_config_for_adapter(adapter_name: str) -> ExternalAgentConfig:
    """Factory function to get adapter configuration.

    Creates a default configuration instance for the specified adapter.
    Configuration can be customized after creation or loaded from
    environment variables.

    Args:
        adapter_name: Name of the adapter ('openhands', 'autogpt', 'crewai')

    Returns:
        Configuration instance for the adapter

    Raises:
        ValueError: If adapter_name is not recognized
    """
    configs = {
        "openhands": OpenHandsConfig,
        "autogpt": AutoGPTConfig,
        "crewai": CrewAIConfig,
    }

    config_cls = configs.get(adapter_name.lower())
    if config_cls is None:
        valid = ", ".join(sorted(configs.keys()))
        raise ValueError(f"Unknown adapter: {adapter_name}. Valid: {valid}")

    return config_cls()
