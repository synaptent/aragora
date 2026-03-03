"""
OpenAPI Endpoint Definitions.

Each submodule contains endpoint specifications for a specific domain.
Endpoints can also be registered using the @api_endpoint decorator.
"""

from aragora.server.openapi.endpoints.system import SYSTEM_ENDPOINTS
from aragora.server.openapi.endpoints.agents import AGENT_ENDPOINTS
from aragora.server.openapi.endpoints.debates import DEBATE_ENDPOINTS
from aragora.server.openapi.endpoints.analytics import ANALYTICS_ENDPOINTS
from aragora.server.openapi.endpoints.consensus import CONSENSUS_ENDPOINTS
from aragora.server.openapi.endpoints.relationships import RELATIONSHIP_ENDPOINTS
from aragora.server.openapi.endpoints.memory import MEMORY_ENDPOINTS
from aragora.server.openapi.endpoints.belief import BELIEF_ENDPOINTS
from aragora.server.openapi.endpoints.pulse import PULSE_ENDPOINTS
from aragora.server.openapi.endpoints.metrics import METRICS_ENDPOINTS
from aragora.server.openapi.endpoints.verification import VERIFICATION_ENDPOINTS
from aragora.server.openapi.endpoints.documents import DOCUMENT_ENDPOINTS
from aragora.server.openapi.endpoints.plugins import PLUGIN_ENDPOINTS
from aragora.server.openapi.endpoints.additional import ADDITIONAL_ENDPOINTS
from aragora.server.openapi.endpoints.oauth import OAUTH_ENDPOINTS
from aragora.server.openapi.endpoints.workspace import WORKSPACE_ENDPOINTS
from aragora.server.openapi.endpoints.workflows import WORKFLOW_ENDPOINTS
from aragora.server.openapi.endpoints.cross_pollination import CROSS_POLLINATION_ENDPOINTS
from aragora.server.openapi.endpoints.gauntlet import GAUNTLET_ENDPOINTS
from aragora.server.openapi.endpoints.patterns import PATTERN_ENDPOINTS
from aragora.server.openapi.endpoints.checkpoints import CHECKPOINT_ENDPOINTS
from aragora.server.openapi.endpoints.explainability import EXPLAINABILITY_ENDPOINTS
from aragora.server.openapi.endpoints.workflow_templates import WORKFLOW_TEMPLATES_ENDPOINTS
from aragora.server.openapi.endpoints.control_plane import CONTROL_PLANE_ENDPOINTS
from aragora.server.openapi.endpoints.decisions import DECISION_ENDPOINTS
from aragora.server.openapi.endpoints.codebase_security import CODEBASE_SECURITY_ENDPOINTS
from aragora.server.openapi.endpoints.codebase_metrics import CODEBASE_METRICS_ENDPOINTS
from aragora.server.openapi.endpoints.codebase_intelligence import (
    CODEBASE_INTELLIGENCE_ENDPOINTS,
)
from aragora.server.openapi.endpoints.codebase_quick_scan import (
    CODEBASE_QUICK_SCAN_ENDPOINTS,
)
from aragora.server.openapi.endpoints.github import GITHUB_ENDPOINTS
from aragora.server.openapi.endpoints.costs import COSTS_ENDPOINTS
from aragora.server.openapi.endpoints.shared_inbox import INBOX_ENDPOINTS
from aragora.server.openapi.endpoints.gmail import GMAIL_ENDPOINTS
from aragora.server.openapi.endpoints.outlook import OUTLOOK_ENDPOINTS
from aragora.server.openapi.endpoints.knowledge_chat import KNOWLEDGE_CHAT_ENDPOINTS
from aragora.server.openapi.endpoints.knowledge_base import KNOWLEDGE_BASE_ENDPOINTS
from aragora.server.openapi.endpoints.knowledge_mound import KNOWLEDGE_MOUND_ENDPOINTS
from aragora.server.openapi.endpoints.audit_sessions import AUDIT_SESSIONS_ENDPOINTS
from aragora.server.openapi.endpoints.accounting import ACCOUNTING_ENDPOINTS
from aragora.server.openapi.endpoints.threat_intel import THREAT_INTEL_ENDPOINTS
from aragora.server.openapi.endpoints.budgets import BUDGET_ENDPOINTS
from aragora.server.openapi.endpoints.teams import TEAMS_ENDPOINTS
from aragora.server.openapi.endpoints.webhooks import WEBHOOK_ENDPOINTS
from aragora.server.openapi.endpoints.integrations import INTEGRATION_ENDPOINTS
from aragora.server.openapi.endpoints.nomic import NOMIC_ENDPOINTS
from aragora.server.openapi.endpoints.deliberations import DELIBERATIONS_ENDPOINTS
from aragora.server.openapi.endpoints.auth import AUTH_ENDPOINTS
from aragora.server.openapi.endpoints.admin import ADMIN_ENDPOINTS
from aragora.server.openapi.endpoints.a2a import A2A_ENDPOINTS
from aragora.server.openapi.endpoints.admin_security import ADMIN_SECURITY_ENDPOINTS
from aragora.server.openapi.endpoints.advertising import ADVERTISING_ENDPOINTS
from aragora.server.openapi.endpoints.bots import BOTS_ENDPOINTS
from aragora.server.openapi.endpoints.queue import QUEUE_ENDPOINTS
from aragora.server.openapi.endpoints.devices import DEVICES_ENDPOINTS
from aragora.server.openapi.endpoints.onboarding import ONBOARDING_ENDPOINTS
from aragora.server.openapi.endpoints.computer_use import COMPUTER_USE_ENDPOINTS
from aragora.server.openapi.endpoints.gateway import GATEWAY_ENDPOINTS
from aragora.server.openapi.endpoints.openclaw import OPENCLAW_ENDPOINTS
from aragora.server.openapi.endpoints.sdk_missing import SDK_MISSING_ENDPOINTS
from aragora.server.openapi.endpoints.debate_hardening import DEBATE_HARDENING_ENDPOINTS
from aragora.server.openapi.endpoints.reconciliation import RECONCILIATION_ENDPOINTS
from aragora.server.openapi.endpoints.response_schemas import RESPONSE_SCHEMA_ENDPOINTS
from aragora.server.openapi.endpoints.pipeline import PIPELINE_ENDPOINTS
from aragora.server.openapi.endpoints.playbooks import PLAYBOOK_ENDPOINTS
from aragora.server.openapi.endpoints.marketplace import MARKETPLACE_ENDPOINTS
from aragora.server.openapi.endpoints.orchestration import ORCHESTRATION_ENDPOINTS


import logging
from typing import Any

logger = logging.getLogger(__name__)


# Import decorator-based endpoints registry
def _get_decorator_endpoints() -> dict[str, Any]:
    """Get endpoints registered via @api_endpoint decorator.

    Returns empty dict if decorator module not available or no endpoints registered.
    """
    try:
        from aragora.server.handlers.openapi_decorator import get_registered_endpoints_dict

        return get_registered_endpoints_dict()
    except ImportError:
        return {}
    except (AttributeError, RuntimeError, ValueError) as exc:
        logger.warning("Failed to load decorator endpoints: %s", exc)
        return {}


# Combined endpoints dictionary
ALL_ENDPOINTS = {
    **SYSTEM_ENDPOINTS,
    **AGENT_ENDPOINTS,
    **DEBATE_ENDPOINTS,
    **ANALYTICS_ENDPOINTS,
    **CONSENSUS_ENDPOINTS,
    **RELATIONSHIP_ENDPOINTS,
    **MEMORY_ENDPOINTS,
    **BELIEF_ENDPOINTS,
    **PULSE_ENDPOINTS,
    **METRICS_ENDPOINTS,
    **VERIFICATION_ENDPOINTS,
    **DOCUMENT_ENDPOINTS,
    **PLUGIN_ENDPOINTS,
    **ADDITIONAL_ENDPOINTS,
    **OAUTH_ENDPOINTS,
    **WORKSPACE_ENDPOINTS,
    **WORKFLOW_ENDPOINTS,
    **CROSS_POLLINATION_ENDPOINTS,
    **GAUNTLET_ENDPOINTS,
    **PATTERN_ENDPOINTS,
    **CHECKPOINT_ENDPOINTS,
    **EXPLAINABILITY_ENDPOINTS,
    **WORKFLOW_TEMPLATES_ENDPOINTS,
    **CONTROL_PLANE_ENDPOINTS,
    **DECISION_ENDPOINTS,
    **CODEBASE_SECURITY_ENDPOINTS,
    **CODEBASE_METRICS_ENDPOINTS,
    **CODEBASE_INTELLIGENCE_ENDPOINTS,
    **CODEBASE_QUICK_SCAN_ENDPOINTS,
    **GITHUB_ENDPOINTS,
    **COSTS_ENDPOINTS,
    **INBOX_ENDPOINTS,
    **GMAIL_ENDPOINTS,
    **OUTLOOK_ENDPOINTS,
    **KNOWLEDGE_CHAT_ENDPOINTS,
    **KNOWLEDGE_BASE_ENDPOINTS,
    **KNOWLEDGE_MOUND_ENDPOINTS,
    **AUDIT_SESSIONS_ENDPOINTS,
    **ACCOUNTING_ENDPOINTS,
    **THREAT_INTEL_ENDPOINTS,
    **BUDGET_ENDPOINTS,
    **TEAMS_ENDPOINTS,
    **WEBHOOK_ENDPOINTS,
    **INTEGRATION_ENDPOINTS,
    **NOMIC_ENDPOINTS,
    **DELIBERATIONS_ENDPOINTS,
    **AUTH_ENDPOINTS,
    **ADMIN_ENDPOINTS,
    **A2A_ENDPOINTS,
    **ADMIN_SECURITY_ENDPOINTS,
    **ADVERTISING_ENDPOINTS,
    **BOTS_ENDPOINTS,
    **QUEUE_ENDPOINTS,
    **DEVICES_ENDPOINTS,
    **ONBOARDING_ENDPOINTS,
    **COMPUTER_USE_ENDPOINTS,
    **GATEWAY_ENDPOINTS,
    **OPENCLAW_ENDPOINTS,
    **SDK_MISSING_ENDPOINTS,
    **DEBATE_HARDENING_ENDPOINTS,
    **RECONCILIATION_ENDPOINTS,
    **RESPONSE_SCHEMA_ENDPOINTS,
    **PIPELINE_ENDPOINTS,
    **PLAYBOOK_ENDPOINTS,
    **MARKETPLACE_ENDPOINTS,
    **ORCHESTRATION_ENDPOINTS,
}

# Deep merge decorator endpoints: manual specs take precedence over decorator
# specs when both define the same path+method (manual specs are richer).
_decorator_eps = _get_decorator_endpoints()
for path, methods in _decorator_eps.items():
    if path in ALL_ENDPOINTS:
        # Decorator fills gaps; manual specs preserved for existing methods
        ALL_ENDPOINTS[path] = {**methods, **ALL_ENDPOINTS[path]}
    else:
        ALL_ENDPOINTS[path] = methods

__all__ = [
    "SYSTEM_ENDPOINTS",
    "AGENT_ENDPOINTS",
    "DEBATE_ENDPOINTS",
    "ANALYTICS_ENDPOINTS",
    "CONSENSUS_ENDPOINTS",
    "RELATIONSHIP_ENDPOINTS",
    "MEMORY_ENDPOINTS",
    "BELIEF_ENDPOINTS",
    "PULSE_ENDPOINTS",
    "METRICS_ENDPOINTS",
    "VERIFICATION_ENDPOINTS",
    "DOCUMENT_ENDPOINTS",
    "PLUGIN_ENDPOINTS",
    "ADDITIONAL_ENDPOINTS",
    "OAUTH_ENDPOINTS",
    "WORKSPACE_ENDPOINTS",
    "WORKFLOW_ENDPOINTS",
    "CROSS_POLLINATION_ENDPOINTS",
    "GAUNTLET_ENDPOINTS",
    "PATTERN_ENDPOINTS",
    "CHECKPOINT_ENDPOINTS",
    "EXPLAINABILITY_ENDPOINTS",
    "WORKFLOW_TEMPLATES_ENDPOINTS",
    "CONTROL_PLANE_ENDPOINTS",
    "DECISION_ENDPOINTS",
    "CODEBASE_SECURITY_ENDPOINTS",
    "CODEBASE_METRICS_ENDPOINTS",
    "CODEBASE_INTELLIGENCE_ENDPOINTS",
    "CODEBASE_QUICK_SCAN_ENDPOINTS",
    "GITHUB_ENDPOINTS",
    "COSTS_ENDPOINTS",
    "INBOX_ENDPOINTS",
    "GMAIL_ENDPOINTS",
    "OUTLOOK_ENDPOINTS",
    "KNOWLEDGE_CHAT_ENDPOINTS",
    "KNOWLEDGE_BASE_ENDPOINTS",
    "KNOWLEDGE_MOUND_ENDPOINTS",
    "AUDIT_SESSIONS_ENDPOINTS",
    "ACCOUNTING_ENDPOINTS",
    "THREAT_INTEL_ENDPOINTS",
    "BUDGET_ENDPOINTS",
    "TEAMS_ENDPOINTS",
    "WEBHOOK_ENDPOINTS",
    "INTEGRATION_ENDPOINTS",
    "NOMIC_ENDPOINTS",
    "DELIBERATIONS_ENDPOINTS",
    "AUTH_ENDPOINTS",
    "ADMIN_ENDPOINTS",
    "A2A_ENDPOINTS",
    "ADMIN_SECURITY_ENDPOINTS",
    "ADVERTISING_ENDPOINTS",
    "BOTS_ENDPOINTS",
    "QUEUE_ENDPOINTS",
    "DEVICES_ENDPOINTS",
    "ONBOARDING_ENDPOINTS",
    "COMPUTER_USE_ENDPOINTS",
    "GATEWAY_ENDPOINTS",
    "OPENCLAW_ENDPOINTS",
    "SDK_MISSING_ENDPOINTS",
    "DEBATE_HARDENING_ENDPOINTS",
    "RECONCILIATION_ENDPOINTS",
    "RESPONSE_SCHEMA_ENDPOINTS",
    "PIPELINE_ENDPOINTS",
    "PLAYBOOK_ENDPOINTS",
    "MARKETPLACE_ENDPOINTS",
    "ORCHESTRATION_ENDPOINTS",
    "ALL_ENDPOINTS",
]
