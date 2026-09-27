"""
Agent-related handler imports and registry entries.

This module contains imports and registry entries for:
- Core agent handlers (AgentsHandler, PersonaHandler, etc.)
- Calibration and training handlers
- Agent configuration and external agents
- A2A (Agent-to-Agent) handlers
"""

from __future__ import annotations

from .core import _safe_import

# =============================================================================
# Agent Handler Imports
# =============================================================================

# Core agent handlers
AgentsHandler = _safe_import("aragora.server.handlers", "AgentsHandler")
PersonaHandler = _safe_import("aragora.server.handlers", "PersonaHandler")
CalibrationHandler = _safe_import("aragora.server.handlers", "CalibrationHandler")

# Training handler
TrainingHandler = _safe_import("aragora.server.handlers", "TrainingHandler")

# A2A (Agent-to-Agent) handler
A2AHandler = _safe_import("aragora.server.handlers", "A2AHandler")

# Agent config handler
AgentConfigHandler = _safe_import("aragora.server.handlers.agents.config", "AgentConfigHandler")

# External agents and gateway
ExternalAgentsHandler = _safe_import(
    "aragora.server.handlers.agents.external_agents", "ExternalAgentsHandler"
)

# Gateway agent handlers
GatewayAgentsHandler = _safe_import(
    "aragora.server.handlers.gateway.gateway_agents_handler", "GatewayAgentsHandler"
)

# Selection handler (agent selection)
SelectionHandler = _safe_import("aragora.server.handlers.agents.selection", "SelectionHandler")

# Agent recommendations and feedback
AgentRecommendationHandler = _safe_import(
    "aragora.server.handlers.agents.recommendations", "AgentRecommendationHandler"
)
FeedbackHandler = _safe_import("aragora.server.handlers.agents.feedback", "FeedbackHandler")

# Match statistics (ELO aggregate stats)
MatchesStatsHandler = _safe_import(
    "aragora.server.handlers.agents.matches_stats", "MatchesStatsHandler"
)

# =============================================================================
# Agent Handler Registry Entries
# =============================================================================

AGENT_HANDLER_REGISTRY: list[tuple[str, object]] = [
    ("_agents_handler", AgentsHandler),
    ("_persona_handler", PersonaHandler),
    ("_calibration_handler", CalibrationHandler),
    ("_training_handler", TrainingHandler),
    ("_a2a_handler", A2AHandler),
    ("_agent_config_handler", AgentConfigHandler),
    ("_external_agents_handler", ExternalAgentsHandler),
    ("_gateway_agents_handler", GatewayAgentsHandler),
    ("_selection_handler", SelectionHandler),
    # Agent recommendations and feedback
    ("_agent_recommendation_handler", AgentRecommendationHandler),
    ("_feedback_handler", FeedbackHandler),
    # Match statistics
    ("_matches_stats_handler", MatchesStatsHandler),
]

__all__ = [
    # Agent handlers
    "AgentsHandler",
    "PersonaHandler",
    "CalibrationHandler",
    "TrainingHandler",
    "A2AHandler",
    "AgentConfigHandler",
    "ExternalAgentsHandler",
    "GatewayAgentsHandler",
    "SelectionHandler",
    "MatchesStatsHandler",
    # Registry
    "AGENT_HANDLER_REGISTRY",
]
