"""
Skills System Base Types.

Inspired by ClawdBot's skills architecture, this module provides the foundational
types and interfaces for pluggable skill capabilities in Aragora. They live in the
foundation layer so the debate engine can use them without importing
``aragora.skills``; ``aragora.skills`` and ``aragora.skills.base`` re-export them.

A Skill is a modular, self-contained capability that can:
- Be dynamically loaded and registered
- Declare its capabilities and requirements via a manifest
- Execute operations with typed inputs and outputs
- Integrate with the debate system and RBAC

Key concepts:
- SkillManifest: Declarative skill metadata and requirements
- Skill: Abstract base class for skill implementations
- SkillResult: Typed result container with status and metadata
- SkillContext: Execution context with permissions and state
- SkillCapability: Enumeration of capability types

Usage:
    from aragora.skills import Skill, SkillManifest, SkillResult

    class WebSearchSkill(Skill):
        @property
        def manifest(self) -> SkillManifest:
            return SkillManifest(
                name="web_search",
                version="1.0.0",
                capabilities=[SkillCapability.EXTERNAL_API],
                input_schema={"query": {"type": "string"}},
            )

        async def execute(self, input_data: dict, context: SkillContext) -> SkillResult:
            query = input_data["query"]
            results = await self._search(query)
            return SkillResult.success(results)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar, Generic
import uuid

logger = logging.getLogger(__name__)


class SkillCapability(str, Enum):
    """Capabilities a skill can declare."""

    # Data access capabilities
    READ_LOCAL = "read_local"  # Read local files
    WRITE_LOCAL = "write_local"  # Write local files
    READ_DATABASE = "read_database"  # Query databases
    WRITE_DATABASE = "write_database"  # Modify databases

    # External capabilities
    EXTERNAL_API = "external_api"  # Call external APIs
    WEB_SEARCH = "web_search"  # Search the web
    WEB_FETCH = "web_fetch"  # Fetch web pages

    # Execution capabilities
    CODE_EXECUTION = "code_execution"  # Execute code
    SHELL_EXECUTION = "shell_execution"  # Run shell commands

    # AI capabilities
    LLM_INFERENCE = "llm_inference"  # Call LLM APIs
    EMBEDDING = "embedding"  # Generate embeddings

    # Debate-specific capabilities
    DEBATE_CONTEXT = "debate_context"  # Access debate context
    EVIDENCE_COLLECTION = "evidence_collection"  # Collect evidence
    KNOWLEDGE_QUERY = "knowledge_query"  # Query knowledge mound

    # System capabilities
    SYSTEM_INFO = "system_info"  # Access system information
    NETWORK = "network"  # Network operations


class CapabilityLevel(str, Enum):
    """Coarse capability level for quick tool filtering."""

    READ = "read"  # Only reads data, no side effects
    WRITE = "write"  # Modifies data (files, databases)
    EXEC = "exec"  # Executes code or shell commands

    @classmethod
    def from_capabilities(cls, caps: list["SkillCapability"]) -> "CapabilityLevel":
        """Derive the highest capability level from a list of capabilities."""
        exec_caps = {SkillCapability.CODE_EXECUTION, SkillCapability.SHELL_EXECUTION}
        write_caps = {SkillCapability.WRITE_LOCAL, SkillCapability.WRITE_DATABASE}
        if exec_caps & set(caps):
            return cls.EXEC
        if write_caps & set(caps):
            return cls.WRITE
        return cls.READ


class SkillStatus(str, Enum):
    """Status of a skill execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"  # Partially successful
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PERMISSION_DENIED = "permission_denied"
    INVALID_INPUT = "invalid_input"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass
class SkillManifest:
    """
    Declarative manifest describing a skill's metadata and requirements.

    The manifest is used for:
    - Skill discovery and registration
    - Permission checking before execution
    - Input validation
    - Tool schema generation for LLM function calling
    """

    name: str
    version: str
    capabilities: list[SkillCapability]
    input_schema: dict[str, Any]  # JSON Schema for input validation

    # Optional metadata
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)

    # Requirements
    required_permissions: list[str] = field(default_factory=list)
    required_env_vars: list[str] = field(default_factory=list)
    required_packages: list[str] = field(default_factory=list)

    # Execution constraints
    max_execution_time_seconds: float = 60.0
    max_retries: int = 3

    @property
    def capability_level(self) -> CapabilityLevel:
        """Coarse capability level derived from declared capabilities."""
        return CapabilityLevel.from_capabilities(self.capabilities)

    rate_limit_per_minute: int | None = None

    # Debate integration
    debate_compatible: bool = True  # Can be used during debates
    requires_debate_context: bool = False  # Needs active debate context

    # Output schema (optional, for structured outputs)
    output_schema: dict[str, Any] | None = None

    def to_function_schema(self) -> dict[str, Any]:
        """
        Convert manifest to LLM function calling schema.

        Returns a schema compatible with OpenAI/Anthropic function calling.
        """
        return {
            "name": self.name,
            "description": self.description or f"Skill: {self.name}",
            "parameters": {
                "type": "object",
                "properties": self.input_schema,
                "required": [
                    k
                    for k, v in self.input_schema.items()
                    if isinstance(v, dict) and v.get("required", False)
                ],
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize manifest to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": [c.value for c in self.capabilities],
            "input_schema": self.input_schema,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "required_permissions": self.required_permissions,
            "required_env_vars": self.required_env_vars,
            "required_packages": self.required_packages,
            "max_execution_time_seconds": self.max_execution_time_seconds,
            "max_retries": self.max_retries,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "debate_compatible": self.debate_compatible,
            "requires_debate_context": self.requires_debate_context,
            "output_schema": self.output_schema,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillManifest:
        """Deserialize manifest from dictionary."""
        capabilities = [
            SkillCapability(c) if isinstance(c, str) else c for c in data.get("capabilities", [])
        ]
        return cls(
            name=data["name"],
            version=data["version"],
            capabilities=capabilities,
            input_schema=data.get("input_schema", {}),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            required_permissions=data.get("required_permissions", []),
            required_env_vars=data.get("required_env_vars", []),
            required_packages=data.get("required_packages", []),
            max_execution_time_seconds=data.get("max_execution_time_seconds", 60.0),
            max_retries=data.get("max_retries", 3),
            rate_limit_per_minute=data.get("rate_limit_per_minute"),
            debate_compatible=data.get("debate_compatible", True),
            requires_debate_context=data.get("requires_debate_context", False),
            output_schema=data.get("output_schema"),
        )


T = TypeVar("T")


@dataclass
class SkillResult(Generic[T]):
    """
    Result of a skill execution.

    Contains the result data, status, timing information, and metadata.
    Supports generic typing for strongly-typed results.
    """

    status: SkillStatus
    data: T | None = None
    error_message: str | None = None
    error_code: str | None = None

    # Timing
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # Usage tracking
    tokens_used: int | None = None
    cost_estimate: float | None = None

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.status == SkillStatus.SUCCESS

    @property
    def duration_seconds(self) -> float | None:
        """Get execution duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @classmethod
    def create_success(cls, data: T, **metadata: Any) -> SkillResult[T]:
        """Create a successful result."""
        return cls(
            status=SkillStatus.SUCCESS,
            data=data,
            completed_at=datetime.now(timezone.utc),
            metadata=metadata,
        )

    @classmethod
    def create_failure(
        cls,
        error_message: str,
        error_code: str | None = None,
        status: SkillStatus = SkillStatus.FAILURE,
        **metadata: Any,
    ) -> SkillResult[T]:
        """Create a failure result."""
        return cls(
            status=status,
            error_message=error_message,
            error_code=error_code,
            completed_at=datetime.now(timezone.utc),
            metadata=metadata,
        )

    @classmethod
    def create_timeout(cls, timeout_seconds: float) -> SkillResult[T]:
        """Create a timeout result."""
        return cls(
            status=SkillStatus.TIMEOUT,
            error_message=f"Execution timed out after {timeout_seconds}s",
            completed_at=datetime.now(timezone.utc),
        )

    @classmethod
    def create_permission_denied(cls, permission: str) -> SkillResult[T]:
        """Create a permission denied result."""
        return cls(
            status=SkillStatus.PERMISSION_DENIED,
            error_message=f"Missing required permission: {permission}",
            error_code="permission_denied",
            completed_at=datetime.now(timezone.utc),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return {
            "status": self.status.value,
            "data": self.data,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "execution_id": self.execution_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
            "warnings": self.warnings,
            "tokens_used": self.tokens_used,
            "cost_estimate": self.cost_estimate,
        }


@dataclass
class SkillContext:
    """
    Execution context for skill invocation.

    Provides access to:
    - User/tenant information for RBAC
    - Debate context (if applicable)
    - Configuration and environment
    - Previous execution results (for chaining)
    """

    # Identity
    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None

    # Permissions
    permissions: list[str] = field(default_factory=list)

    # Debate context (if invoked during debate)
    debate_id: str | None = None
    debate_context: dict[str, Any] | None = None
    agent_name: str | None = None

    # Environment
    environment: str = "development"  # development, staging, production
    config: dict[str, Any] = field(default_factory=dict)

    # Previous results (for skill chaining)
    previous_results: dict[str, SkillResult] = field(default_factory=dict)

    # Request metadata
    request_id: str | None = None
    correlation_id: str | None = None

    def has_permission(self, permission: str) -> bool:
        """Check if context has a specific permission."""
        return permission in self.permissions

    def has_all_permissions(self, permissions: list[str]) -> bool:
        """Check if context has all specified permissions."""
        return all(p in self.permissions for p in permissions)

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)


class Skill(ABC):
    """
    Abstract base class for skills.

    Skills are modular capabilities that can be:
    - Registered with the SkillRegistry
    - Invoked with typed inputs
    - Used during debates for evidence collection, etc.
    - Exposed as LLM tools for function calling
    """

    @property
    @abstractmethod
    def manifest(self) -> SkillManifest:
        """Return the skill's manifest."""
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """
        Execute the skill.

        Args:
            input_data: Input parameters matching the manifest's input_schema
            context: Execution context with permissions and state

        Returns:
            SkillResult with execution outcome
        """
        raise NotImplementedError

    async def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate input against the manifest's input schema.

        Returns:
            Tuple of (is_valid, error_message)
        """
        schema = self.manifest.input_schema
        if not schema:
            return True, None

        # Basic validation (can be extended with jsonschema)
        for key, spec in schema.items():
            if isinstance(spec, dict) and spec.get("required", False):
                if key not in input_data:
                    return False, f"Missing required field: {key}"

            if key in input_data:
                expected_type = spec.get("type") if isinstance(spec, dict) else None
                if expected_type:
                    value = input_data[key]
                    if expected_type == "string" and not isinstance(value, str):
                        return False, f"Field {key} must be a string"
                    elif expected_type == "number" and not isinstance(value, (int, float)):
                        return False, f"Field {key} must be a number"
                    elif expected_type == "boolean" and not isinstance(value, bool):
                        return False, f"Field {key} must be a boolean"
                    elif expected_type == "array" and not isinstance(value, list):
                        return False, f"Field {key} must be an array"
                    elif expected_type == "object" and not isinstance(value, dict):
                        return False, f"Field {key} must be an object"

        return True, None

    async def check_permissions(self, context: SkillContext) -> tuple[bool, str | None]:
        """
        Check if context has required permissions.

        Returns:
            Tuple of (has_permission, missing_permission)
        """
        for permission in self.manifest.required_permissions:
            if not context.has_permission(permission):
                return False, permission
        return True, None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.manifest.name})"


class SyncSkill(Skill):
    """
    Base class for synchronous skills.

    Wraps a synchronous execute method in an async interface.
    """

    @abstractmethod
    def execute_sync(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Synchronous execution method."""
        raise NotImplementedError

    async def execute(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Wrap sync execution in async."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self.execute_sync,
            input_data,
            context,
        )


__all__ = [
    "CapabilityLevel",
    "Skill",
    "SkillCapability",
    "SkillContext",
    "SkillManifest",
    "SkillResult",
    "SkillStatus",
    "SyncSkill",
]
