"""
YAML Agent Configuration Loader.

Adapted from claude-flow (MIT License)
Pattern: Dynamic agent specialization via YAML configuration files
Original: https://github.com/ruvnet/claude-flow

Aragora adaptations:
- Integration with AgentRegistry for agent creation
- Support for expertise domains and fallback chains
- Hook registration for pre/post task automation
- Hot-reload capability for development

Usage:
    loader = AgentConfigLoader()
    configs = loader.load_directory(Path("agents/configs"))
    agent = loader.create_agent(configs["security-auditor"])
"""

from __future__ import annotations

__all__ = [
    "AgentConfig",
    "AgentConfigLoader",
    "ConfigValidationError",
    "load_agent_configs",
]

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

_yaml: Any = None
try:
    import yaml

    _yaml = yaml
except ImportError:
    logger.debug("PyYAML not installed, YAML config loading will be unavailable")

if TYPE_CHECKING:
    from aragora.core import Agent


class ConfigValidationError(Exception):
    """Raised when agent configuration validation fails."""

    def __init__(self, config_path: str, errors: list[str]):
        self.config_path = config_path
        self.errors = errors
        super().__init__(f"Invalid config '{config_path}': {'; '.join(errors)}")


@dataclass
class AgentConfig:
    """
    Configuration for a YAML-defined agent.

    Supports all agent parameters that can be specified in YAML config files.
    """

    # Required fields
    name: str
    model_type: str  # Maps to AgentRegistry type: "anthropic-api", "openai-api", etc.

    # Model configuration
    model: str | None = None  # Specific model override (e.g., "claude-3-5-sonnet")
    temperature: float = 0.7
    max_tokens: int = 4096

    # Role and behavior
    role: str = "proposer"  # "proposer", "critic", "synthesizer", "judge"
    stance: str = "neutral"  # "affirmative", "negative", "neutral"
    system_prompt: str = ""

    # Expertise and capabilities
    expertise_domains: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

    # Priority and fallback
    priority: str = "normal"  # "low", "normal", "high", "critical"
    fallback_chain: list[str] = field(default_factory=list)  # Agent types to try on failure

    # Memory and access
    memory_access: str = "read"  # "none", "read", "write", "full"
    timeout_seconds: int = 300

    # Hooks (pre/post task automation)
    hooks: dict[str, str] = field(default_factory=dict)

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)

    # Source tracking
    config_path: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        errors = self._validate()
        if errors:
            raise ConfigValidationError(self.config_path or self.name, errors)

    def _validate(self) -> list[str]:
        """Validate configuration values."""
        errors = []

        if not self.name:
            errors.append("name is required")
        if not self.model_type:
            errors.append("model_type is required")

        valid_roles = {"proposer", "critic", "synthesizer", "judge"}
        if self.role not in valid_roles:
            errors.append(f"role must be one of {valid_roles}, got '{self.role}'")

        valid_stances = {"affirmative", "negative", "neutral"}
        if self.stance not in valid_stances:
            errors.append(f"stance must be one of {valid_stances}, got '{self.stance}'")

        valid_priorities = {"low", "normal", "high", "critical"}
        if self.priority not in valid_priorities:
            errors.append(f"priority must be one of {valid_priorities}, got '{self.priority}'")

        valid_memory = {"none", "read", "write", "full"}
        if self.memory_access not in valid_memory:
            errors.append(
                f"memory_access must be one of {valid_memory}, got '{self.memory_access}'"
            )

        if self.temperature < 0.0 or self.temperature > 2.0:
            errors.append(f"temperature must be 0.0-2.0, got {self.temperature}")

        if self.max_tokens < 1:
            errors.append(f"max_tokens must be positive, got {self.max_tokens}")

        if self.timeout_seconds < 1:
            errors.append(f"timeout_seconds must be positive, got {self.timeout_seconds}")

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {
            "name": self.name,
            "model_type": self.model_type,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "role": self.role,
            "stance": self.stance,
            "system_prompt": self.system_prompt,
            "expertise_domains": list(self.expertise_domains),
            "capabilities": list(self.capabilities),
            "priority": self.priority,
            "fallback_chain": list(self.fallback_chain),
            "memory_access": self.memory_access,
            "timeout_seconds": self.timeout_seconds,
            "hooks": dict(self.hooks),
            "description": self.description,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: str | None = None) -> AgentConfig:
        """Create configuration from dictionary."""
        return cls(
            name=data.get("name", ""),
            model_type=data.get("model_type", ""),
            model=data.get("model"),
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=int(data.get("max_tokens", 4096)),
            role=data.get("role", "proposer"),
            stance=data.get("stance", "neutral"),
            system_prompt=data.get("system_prompt", ""),
            expertise_domains=data.get("expertise_domains", []),
            capabilities=data.get("capabilities", []),
            priority=data.get("priority", "normal"),
            fallback_chain=data.get("fallback_chain", []),
            memory_access=data.get("memory_access", "read"),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            hooks=data.get("hooks", {}),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            config_path=config_path,
        )


class AgentConfigLoader:
    """
    Loads and manages YAML agent configurations.

    Supports:
    - Loading individual YAML files
    - Loading all configs from a directory
    - Creating agents from configs
    - Hot-reload for development
    """

    def __init__(self, registry: Any | None = None):
        """
        Initialize the config loader.

        Args:
            registry: Optional AgentRegistry instance (uses default if not provided)
        """
        self._configs: dict[str, AgentConfig] = {}
        self._registry = registry
        self._config_paths: dict[str, Path] = {}

    def load_yaml(self, path: str | Path) -> AgentConfig:
        """
        Load a single YAML configuration file.

        Args:
            path: Path to the YAML file

        Returns:
            AgentConfig instance

        Raises:
            ConfigValidationError: If configuration is invalid
            FileNotFoundError: If file doesn't exist
            ImportError: If PyYAML is not installed
        """
        if _yaml is None:
            raise ImportError(
                "PyYAML is required for YAML config loading. Install with: pip install pyyaml"
            )

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        logger.debug("Loading agent config from %s", path)

        with open(path) as f:
            data = _yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ConfigValidationError(str(path), ["YAML must contain a mapping"])

        config = AgentConfig.from_dict(data, str(path))
        self._configs[config.name] = config
        self._config_paths[config.name] = path

        logger.info("Loaded agent config: %s (%s)", config.name, config.model_type)
        return config

    def load_directory(self, directory: str | Path) -> dict[str, AgentConfig]:
        """
        Load all YAML configurations from a directory.

        Args:
            directory: Path to directory containing YAML files

        Returns:
            Dictionary mapping agent names to their configurations
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning("Config directory not found: %s", directory)
            return {}

        configs: dict[str, AgentConfig] = {}

        for yaml_file in directory.glob("*.yaml"):
            try:
                config = self.load_yaml(yaml_file)
                configs[config.name] = config
            except (ConfigValidationError, ValueError, OSError, TypeError) as e:
                logger.error("Failed to load config %s: %s", yaml_file, e)
                continue

        for yml_file in directory.glob("*.yml"):
            try:
                config = self.load_yaml(yml_file)
                configs[config.name] = config
            except (ConfigValidationError, ValueError, OSError, TypeError) as e:
                logger.error("Failed to load config %s: %s", yml_file, e)
                continue

        logger.info("Loaded %s agent configs from %s", len(configs), directory)
        return configs

    def reload_config(self, name: str) -> AgentConfig | None:
        """
        Reload a specific configuration from disk.

        Args:
            name: Name of the agent configuration

        Returns:
            Updated AgentConfig or None if not found
        """
        if name not in self._config_paths:
            logger.warning("No config path recorded for %s", name)
            return None

        path = self._config_paths[name]
        if not path.exists():
            logger.warning("Config file no longer exists: %s", path)
            del self._config_paths[name]
            if name in self._configs:
                del self._configs[name]
            return None

        return self.load_yaml(path)

    def reload_all(self) -> dict[str, AgentConfig]:
        """
        Reload all configurations from their original paths.

        Returns:
            Updated dictionary of configurations
        """
        reloaded: dict[str, AgentConfig] = {}
        for name in list(self._config_paths.keys()):
            config = self.reload_config(name)
            if config:
                reloaded[name] = config
        return reloaded

    def get_config(self, name: str) -> AgentConfig | None:
        """Get a loaded configuration by name."""
        return self._configs.get(name)

    def list_configs(self) -> list[str]:
        """List all loaded configuration names."""
        return list(self._configs.keys())

    def create_agent(self, config: str | AgentConfig) -> Agent:
        """
        Create an agent from a configuration.

        Args:
            config: AgentConfig instance or name of loaded config

        Returns:
            Agent instance created via AgentRegistry

        Raises:
            ValueError: If config not found or registry unavailable
        """
        if isinstance(config, str):
            if config not in self._configs:
                raise ValueError(f"Config not loaded: {config}")
            config = self._configs[config]

        # Get or import registry
        registry = self._registry
        if registry is None:
            from aragora.agents.registry import AgentRegistry, register_all_agents

            register_all_agents()
            registry = AgentRegistry

        # Create agent via registry
        agent = registry.create(
            model_type=config.model_type,
            name=config.name,
            role=config.role,
            model=config.model,
        )

        # Apply additional configuration
        if config.system_prompt:
            agent.set_system_prompt(config.system_prompt)

        if hasattr(agent, "stance"):
            agent.stance = config.stance

        # Store config reference for later access. Some registry-created agents do
        # not predefine ``_config``, but they still need access to YAML fallback
        # metadata at runtime.
        setattr(agent, "_config", config)

        logger.debug("Created agent from config: %s", config.name)
        return agent

    def create_agents(self, configs: list[str | AgentConfig] | None = None) -> list[Agent]:
        """
        Create multiple agents from configurations.

        Args:
            configs: List of config names or AgentConfig instances.
                    If None, creates agents for all loaded configs.

        Returns:
            List of created agents
        """
        if configs is None:
            configs = list(self._configs.values())

        agents = []
        for config in configs:
            try:
                agent = self.create_agent(config)
                agents.append(agent)
            except (ValueError, TypeError, RuntimeError, KeyError) as e:
                logger.error("Failed to create agent from config: %s", e)

        return agents

    def get_by_expertise(self, domain: str) -> list[AgentConfig]:
        """
        Find configurations with a specific expertise domain.

        Args:
            domain: Expertise domain to search for

        Returns:
            List of matching configurations
        """
        return [c for c in self._configs.values() if domain in c.expertise_domains]

    def get_by_capability(self, capability: str) -> list[AgentConfig]:
        """
        Find configurations with a specific capability.

        Args:
            capability: Capability to search for

        Returns:
            List of matching configurations
        """
        return [c for c in self._configs.values() if capability in c.capabilities]

    def get_by_tag(self, tag: str) -> list[AgentConfig]:
        """
        Find configurations with a specific tag.

        Args:
            tag: Tag to search for

        Returns:
            List of matching configurations
        """
        return [c for c in self._configs.values() if tag in c.tags]

    def get_by_priority(self, priority: str) -> list[AgentConfig]:
        """
        Find configurations with a specific priority level.

        Args:
            priority: Priority level ("low", "normal", "high", "critical")

        Returns:
            List of matching configurations
        """
        return [c for c in self._configs.values() if c.priority == priority]


def load_agent_configs(
    config_dir: str | Path | None = None,
) -> dict[str, AgentConfig]:
    """
    Convenience function to load agent configurations.

    Args:
        config_dir: Directory containing YAML configs.
                   Defaults to 'aragora/agents/configs'

    Returns:
        Dictionary mapping agent names to configurations
    """
    if config_dir is None:
        # Default to configs directory relative to this file
        config_dir = Path(__file__).parent / "configs"

    loader = AgentConfigLoader()
    return loader.load_directory(config_dir)
