"""
Vertical Configuration Schema.

Defines configuration dataclasses for vertical specialists,
including tool configurations and compliance settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import yaml


class ComplianceLevel(str, Enum):
    """Compliance strictness levels."""

    ADVISORY = "advisory"  # Suggestions only
    WARNING = "warning"  # Warn on violations
    ENFORCED = "enforced"  # Block on violations


@dataclass
class ToolConfig:
    """Configuration for a domain tool."""

    name: str
    description: str
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    requires_auth: bool = False
    connector_type: str | None = None  # e.g., "github", "pubmed"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "parameters": self.parameters,
            "requires_auth": self.requires_auth,
            "connector_type": self.connector_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolConfig:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            parameters=data.get("parameters", {}),
            requires_auth=data.get("requires_auth", False),
            connector_type=data.get("connector_type"),
        )


@dataclass
class ComplianceConfig:
    """Configuration for compliance checking."""

    framework: str  # e.g., "OWASP", "HIPAA", "SOX"
    version: str = "latest"
    level: ComplianceLevel = ComplianceLevel.WARNING
    rules: list[str] = field(default_factory=list)  # Specific rules to check
    exemptions: list[str] = field(default_factory=list)  # Rules to skip

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "framework": self.framework,
            "version": self.version,
            "level": self.level.value,
            "rules": self.rules,
            "exemptions": self.exemptions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComplianceConfig:
        """Create from dictionary."""
        return cls(
            framework=data["framework"],
            version=data.get("version", "latest"),
            level=ComplianceLevel(data.get("level", "warning")),
            rules=data.get("rules", []),
            exemptions=data.get("exemptions", []),
        )


@dataclass
class ModelConfig:
    """Configuration for specialist models."""

    # Primary model (API-based)
    primary_model: str = "claude-opus-5"
    primary_provider: str = "anthropic"

    # Specialist model (optional, HuggingFace)
    specialist_model: str | None = None
    specialist_quantization: str | None = None  # "8bit", "4bit"

    # Fine-tuning
    finetuned_adapter: str | None = None  # LoRA adapter path

    # Generation parameters
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 4096

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "primary_model": self.primary_model,
            "primary_provider": self.primary_provider,
            "specialist_model": self.specialist_model,
            "specialist_quantization": self.specialist_quantization,
            "finetuned_adapter": self.finetuned_adapter,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
        """Create from dictionary."""
        return cls(
            primary_model=data.get("primary_model", "claude-opus-5"),
            primary_provider=data.get("primary_provider", "anthropic"),
            specialist_model=data.get("specialist_model"),
            specialist_quantization=data.get("specialist_quantization"),
            finetuned_adapter=data.get("finetuned_adapter"),
            temperature=data.get("temperature", 0.7),
            top_p=data.get("top_p", 0.9),
            max_tokens=data.get("max_tokens", 4096),
        )


@dataclass
class VerticalConfig:
    """
    Complete configuration for a vertical specialist.

    Defines the domain, tools, compliance requirements, and model settings
    for a specialized AI agent.
    """

    # Identity
    vertical_id: str
    display_name: str
    description: str

    # Domain
    domain_keywords: list[str] = field(default_factory=list)
    expertise_areas: list[str] = field(default_factory=list)

    # System prompt template (Jinja2)
    system_prompt_template: str = ""

    # Tools
    tools: list[ToolConfig] = field(default_factory=list)

    # Compliance
    compliance_frameworks: list[ComplianceConfig] = field(default_factory=list)

    # Model
    model_config: ModelConfig = field(default_factory=ModelConfig)

    # Metadata
    version: str = "1.0.0"
    author: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "vertical_id": self.vertical_id,
            "display_name": self.display_name,
            "description": self.description,
            "domain_keywords": self.domain_keywords,
            "expertise_areas": self.expertise_areas,
            "system_prompt_template": self.system_prompt_template,
            "tools": [t.to_dict() for t in self.tools],
            "compliance_frameworks": [c.to_dict() for c in self.compliance_frameworks],
            "model_config": self.model_config.to_dict(),
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerticalConfig:
        """Create from dictionary."""
        return cls(
            vertical_id=data["vertical_id"],
            display_name=data["display_name"],
            description=data.get("description", ""),
            domain_keywords=data.get("domain_keywords", []),
            expertise_areas=data.get("expertise_areas", []),
            system_prompt_template=data.get("system_prompt_template", ""),
            tools=[ToolConfig.from_dict(t) for t in data.get("tools", [])],
            compliance_frameworks=[
                ComplianceConfig.from_dict(c) for c in data.get("compliance_frameworks", [])
            ],
            model_config=ModelConfig.from_dict(data.get("model_config", {})),
            version=data.get("version", "1.0.0"),
            author=data.get("author"),
            tags=data.get("tags", []),
        )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> VerticalConfig:
        """Load configuration from YAML file."""
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def to_yaml(self, yaml_path: str) -> None:
        """Save configuration to YAML file."""
        with open(yaml_path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)

    def get_enabled_tools(self) -> list[ToolConfig]:
        """Get list of enabled tools."""
        return [t for t in self.tools if t.enabled]

    def get_compliance_frameworks(
        self,
        level: ComplianceLevel | None = None,
    ) -> list[ComplianceConfig]:
        """Get compliance frameworks, optionally filtered by level."""
        if level is None:
            return self.compliance_frameworks
        return [c for c in self.compliance_frameworks if c.level == level]
