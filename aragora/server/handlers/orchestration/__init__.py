"""
Unified Orchestration Handler for Aragora Control Plane.

This package provides the primary API for multi-agent vetted decisionmaking
across organizational knowledge and channels.

All public names are re-exported here for backward compatibility.
"""

from aragora.server.handlers.orchestration.handler import (  # noqa: F401
    OrchestrationHandler,
    handler,
    _orchestration_requests,
    _orchestration_results,
)
from aragora.server.http_utils import run_async as run_async
from aragora.server.handlers.orchestration.models import (
    KnowledgeContextSource,
    OrchestrationRequest,
    OrchestrationResult,
    OutputChannel,
    OutputFormat,
    TeamStrategy,
)
from aragora.server.handlers.orchestration.protocols import (
    ConfluenceConnectorProtocol,
    EmailSenderProtocol,
    GitHubConnectorProtocol,
    JiraConnectorProtocol,
    KnowledgeMoundProtocol,
    RecommendAgentsFunc,
)
from aragora.server.handlers.orchestration.templates import (
    DeliberationTemplate,
    TEMPLATES,
)
from aragora.server.handlers.orchestration.validation import (
    MAX_SOURCE_ID_LENGTH,
    PERM_CHANNEL_DISCORD,
    PERM_CHANNEL_EMAIL,
    PERM_CHANNEL_SLACK,
    PERM_CHANNEL_TEAMS,
    PERM_CHANNEL_TELEGRAM,
    PERM_CHANNEL_WEBHOOK,
    PERM_KNOWLEDGE_CONFLUENCE,
    PERM_KNOWLEDGE_DOCUMENT,
    PERM_KNOWLEDGE_GITHUB,
    PERM_KNOWLEDGE_JIRA,
    PERM_KNOWLEDGE_SLACK,
    PERM_ORCH_ADMIN,
    PERM_ORCH_CHANNELS_WRITE,
    PERM_ORCH_DELIBERATE,
    PERM_ORCH_KNOWLEDGE_READ,
    SAFE_SOURCE_ID_PATTERN,
    SourceIdValidationError,
    safe_source_id,
    validate_channel_id,
)

__all__ = [
    # Handler
    "OrchestrationHandler",
    "handler",
    # Request/Response types
    "OrchestrationRequest",
    "OrchestrationResult",
    "KnowledgeContextSource",
    "OutputChannel",
    "DeliberationTemplate",
    "TeamStrategy",
    "OutputFormat",
    "TEMPLATES",
    # RBAC Permission Constants
    "PERM_ORCH_DELIBERATE",
    "PERM_ORCH_KNOWLEDGE_READ",
    "PERM_ORCH_CHANNELS_WRITE",
    "PERM_ORCH_ADMIN",
    "PERM_KNOWLEDGE_SLACK",
    "PERM_KNOWLEDGE_CONFLUENCE",
    "PERM_KNOWLEDGE_GITHUB",
    "PERM_KNOWLEDGE_JIRA",
    "PERM_KNOWLEDGE_DOCUMENT",
    "PERM_CHANNEL_SLACK",
    "PERM_CHANNEL_TEAMS",
    "PERM_CHANNEL_DISCORD",
    "PERM_CHANNEL_TELEGRAM",
    "PERM_CHANNEL_EMAIL",
    "PERM_CHANNEL_WEBHOOK",
    # Security Validation
    "safe_source_id",
    "validate_channel_id",
    "SourceIdValidationError",
    "SAFE_SOURCE_ID_PATTERN",
    "MAX_SOURCE_ID_LENGTH",
    # Protocols
    "ConfluenceConnectorProtocol",
    "GitHubConnectorProtocol",
    "JiraConnectorProtocol",
    "EmailSenderProtocol",
    "KnowledgeMoundProtocol",
    "RecommendAgentsFunc",
]
