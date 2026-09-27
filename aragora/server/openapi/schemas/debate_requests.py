"""
Debate Request Schema Definitions.

Typed request/response schemas for all debate interaction, intervention,
cost estimation, and WebSocket reconnection endpoints.

These complement the core debate schemas in debate.py with full request
body specifications for external API consumption.
"""

from typing import Any

DEBATE_REQUEST_SCHEMAS: dict[str, Any] = {
    # =========================================================================
    # Debate Interaction Request Schemas
    # =========================================================================
    "DebateJoinRequest": {
        "type": "object",
        "description": "Request to join an active debate as a participant or observer",
        "properties": {
            "role": {
                "type": "string",
                "description": "Role in the debate",
                "enum": ["observer", "participant", "moderator"],
                "default": "observer",
            },
            "display_name": {
                "type": "string",
                "description": "Display name shown to other participants",
                "maxLength": 100,
            },
        },
        "example": {"role": "observer", "display_name": "Alice"},
    },
    "DebateVoteRequest": {
        "type": "object",
        "description": "Submit a vote on the current debate position or agent response",
        "properties": {
            "position": {
                "type": "string",
                "description": "The position being voted on",
                "minLength": 1,
                "maxLength": 500,
            },
            "intensity": {
                "type": "integer",
                "description": "Vote intensity/conviction (1=weak, 10=strong)",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
            },
            "reasoning": {
                "type": "string",
                "description": "Optional reasoning for the vote",
                "maxLength": 2000,
            },
        },
        "required": ["position"],
        "example": {
            "position": "for",
            "intensity": 8,
            "reasoning": "The evidence strongly supports this approach.",
        },
    },
    "DebateSuggestionRequest": {
        "type": "object",
        "description": "Submit a suggestion or argument to inject into the debate",
        "properties": {
            "content": {
                "type": "string",
                "description": "The suggestion or argument text",
                "minLength": 1,
                "maxLength": 5000,
            },
            "type": {
                "type": "string",
                "description": "Type of suggestion",
                "enum": ["argument", "question", "evidence", "follow_up"],
                "default": "argument",
            },
            "target_agent": {
                "type": "string",
                "description": "Optional: direct the suggestion at a specific agent",
            },
        },
        "required": ["content"],
        "example": {
            "content": "Consider the impact on legacy system compatibility.",
            "type": "argument",
        },
    },
    "DebateUpdateRequest": {
        "type": "object",
        "description": "Update a debate's configuration (before or during execution)",
        "properties": {
            "rounds": {
                "type": "integer",
                "description": "Update max rounds",
                "minimum": 1,
                "maximum": 12,
            },
            "consensus": {
                "type": "string",
                "description": "Change consensus strategy",
                "enum": [
                    "majority",
                    "unanimous",
                    "supermajority",
                    "weighted",
                    "hybrid",
                    "judge",
                    "none",
                ],
            },
            "context": {
                "type": "string",
                "description": "Append additional context",
                "maxLength": 10000,
            },
            "metadata": {
                "type": "object",
                "description": "Update metadata (merged with existing)",
            },
        },
        "example": {
            "rounds": 12,
            "context": "New constraint: budget is limited to $50k.",
        },
    },
    "DebateForkRequest": {
        "type": "object",
        "description": "Fork a debate from a specific round to explore alternatives",
        "properties": {
            "branch_point": {
                "type": "integer",
                "description": "Round number to branch from (1-indexed)",
                "minimum": 1,
            },
            "new_premise": {
                "type": "string",
                "description": "New premise or constraint for the forked branch",
                "maxLength": 2000,
            },
        },
        "required": ["branch_point"],
        "example": {
            "branch_point": 3,
            "new_premise": "What if we had unlimited budget?",
        },
    },
    "DebateBroadcastRequest": {
        "type": "object",
        "description": "Generate an audio or video broadcast of a debate",
        "properties": {
            "format": {
                "type": "string",
                "description": "Output format for the broadcast",
                "enum": ["audio", "video"],
                "default": "audio",
            },
            "voices": {
                "type": "object",
                "description": "Voice mapping (agent_name -> voice_id)",
                "additionalProperties": {"type": "string"},
            },
            "language": {
                "type": "string",
                "description": "Language code for TTS",
                "default": "en-US",
            },
        },
        "example": {
            "format": "audio",
            "voices": {"claude": "alloy", "gpt-4": "echo"},
        },
    },
    "DebateCloneRequest": {
        "type": "object",
        "description": "Clone an existing debate with fresh state",
        "properties": {
            "preserveAgents": {
                "type": "boolean",
                "description": "Keep the same agent lineup",
                "default": True,
            },
            "preserveContext": {
                "type": "boolean",
                "description": "Keep the original context and documents",
                "default": True,
            },
        },
        "example": {"preserveAgents": True, "preserveContext": False},
    },
    "DebateFollowupRequest": {
        "type": "object",
        "description": "Create a follow-up debate from a crux or open question",
        "properties": {
            "cruxId": {
                "type": "string",
                "description": "ID of the crux claim to follow up on",
            },
            "context": {
                "type": "string",
                "description": "Additional context for the follow-up",
                "maxLength": 5000,
            },
        },
        "example": {
            "cruxId": "crux_001",
            "context": "The original debate was inconclusive on scalability.",
        },
    },
    "DebateEvidenceRequest": {
        "type": "object",
        "description": "Add evidence to support or counter a debate position",
        "properties": {
            "evidence": {
                "type": "string",
                "description": "The evidence text or URL",
                "minLength": 1,
                "maxLength": 10000,
            },
            "source": {
                "type": "string",
                "description": "Source attribution",
                "maxLength": 500,
            },
            "metadata": {
                "type": "object",
                "description": "Additional metadata about the evidence",
            },
        },
        "required": ["evidence"],
        "example": {
            "evidence": "According to the 2025 State of DevOps Report...",
            "source": "https://example.com/devops-report-2025",
        },
    },
    "DebateVerifyClaimRequest": {
        "type": "object",
        "description": "Verify a specific claim from the debate",
        "properties": {
            "claim_id": {
                "type": "string",
                "description": "ID of the claim to verify",
            },
            "evidence": {
                "type": "string",
                "description": "Optional evidence to check the claim against",
                "maxLength": 5000,
            },
        },
        "required": ["claim_id"],
        "example": {
            "claim_id": "claim_42",
            "evidence": "Counter-evidence text here.",
        },
    },
    "DebateUserInputRequest": {
        "type": "object",
        "description": "Add user input to an active debate",
        "properties": {
            "input": {
                "type": "string",
                "description": "The user's input text",
                "minLength": 1,
                "maxLength": 5000,
            },
            "type": {
                "type": "string",
                "description": "Type of user input",
                "enum": ["suggestion", "vote", "question", "context"],
                "default": "suggestion",
            },
        },
        "required": ["input"],
        "example": {
            "input": "What about the maintenance costs?",
            "type": "question",
        },
    },
    "DebateCounterfactualRequest": {
        "type": "object",
        "description": "Create a counterfactual scenario for what-if analysis",
        "properties": {
            "condition": {
                "type": "string",
                "description": "The hypothetical condition to analyze",
                "maxLength": 2000,
            },
            "variables": {
                "type": "object",
                "description": "Variables to adjust in the scenario",
                "additionalProperties": True,
            },
        },
        "required": ["condition"],
        "example": {
            "condition": "What if the team size was doubled?",
            "variables": {"team_size": 20},
        },
    },
    "DebateMessageRequest": {
        "type": "object",
        "description": "Add a message to a debate thread",
        "properties": {
            "content": {
                "type": "string",
                "description": "Message content",
                "minLength": 1,
                "maxLength": 5000,
            },
            "role": {
                "type": "string",
                "description": "Message role",
                "enum": ["user", "system"],
                "default": "user",
            },
        },
        "required": ["content"],
        "example": {
            "content": "Please also consider regulatory constraints.",
            "role": "user",
        },
    },
    "DebateBatchRequest": {
        "type": "object",
        "description": "Submit multiple debates for batch processing",
        "properties": {
            "requests": {
                "type": "array",
                "description": "Array of debate creation requests",
                "items": {
                    "$ref": "#/components/schemas/DebateCreateRequest",
                },
                "minItems": 1,
                "maxItems": 50,
            },
        },
        "required": ["requests"],
        "example": {
            "requests": [
                {"task": "Should we use TypeScript?", "rounds": 5},
                {"task": "Is GraphQL better than REST?", "rounds": 5},
            ],
        },
    },
    # =========================================================================
    # Intervention Request Schemas
    # =========================================================================
    "DebateInjectArgumentRequest": {
        "type": "object",
        "description": "Inject an argument or follow-up into an active debate",
        "properties": {
            "content": {
                "type": "string",
                "description": "The argument or question to inject",
                "minLength": 1,
                "maxLength": 5000,
            },
            "type": {
                "type": "string",
                "description": "Type of injection",
                "enum": ["argument", "follow_up"],
                "default": "argument",
            },
            "source": {
                "type": "string",
                "description": "Source identifier",
                "default": "user",
            },
            "user_id": {
                "type": "string",
                "description": "User ID for attribution",
            },
        },
        "required": ["content"],
        "example": {
            "content": "Have you considered developer experience?",
            "type": "argument",
        },
    },
    "DebateUpdateWeightsRequest": {
        "type": "object",
        "description": "Update an agent's influence weight in the debate",
        "properties": {
            "agent": {
                "type": "string",
                "description": "Agent name or ID",
                "minLength": 1,
            },
            "weight": {
                "type": "number",
                "description": "Influence weight (0.0=muted, 1.0=normal, 2.0=double)",
                "minimum": 0.0,
                "maximum": 2.0,
                "default": 1.0,
            },
            "user_id": {
                "type": "string",
                "description": "User ID for audit trail",
            },
        },
        "required": ["agent", "weight"],
        "example": {"agent": "claude", "weight": 1.5},
    },
    "DebateUpdateThresholdRequest": {
        "type": "object",
        "description": "Update the consensus threshold for a debate",
        "properties": {
            "threshold": {
                "type": "number",
                "description": "Consensus threshold (0.5=majority, 0.75=strong, 1.0=unanimous)",
                "minimum": 0.5,
                "maximum": 1.0,
            },
            "user_id": {
                "type": "string",
                "description": "User ID for audit trail",
            },
        },
        "required": ["threshold"],
        "example": {"threshold": 0.8},
    },
    # =========================================================================
    # Cost Estimation Schemas
    # =========================================================================
    "DebateCostEstimateRequest": {
        "type": "object",
        "description": "Parameters for estimating debate cost before execution",
        "properties": {
            "num_agents": {
                "type": "integer",
                "description": "Number of agents to participate",
                "minimum": 1,
                "maximum": 8,
                "default": 3,
            },
            "num_rounds": {
                "type": "integer",
                "description": "Number of debate rounds",
                "minimum": 1,
                "maximum": 12,
                "default": 9,
            },
            "model_types": {
                "type": "array",
                "description": "Model types to use",
                "items": {"type": "string"},
                "example": ["claude-opus-5", "gpt-4o", "gemini-pro"],
            },
        },
        "example": {
            "num_agents": 3,
            "num_rounds": 9,
            "model_types": ["claude-opus-5", "gpt-4o", "gemini-pro"],
        },
    },
    "DebateCostEstimateResponse": {
        "type": "object",
        "description": "Estimated cost breakdown for a debate",
        "properties": {
            "total_estimated_cost_usd": {
                "type": "number",
                "description": "Total estimated cost in USD",
            },
            "breakdown_by_model": {
                "type": "array",
                "description": "Cost breakdown per model",
                "items": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "provider": {"type": "string"},
                        "estimated_input_tokens": {"type": "integer"},
                        "estimated_output_tokens": {"type": "integer"},
                        "input_cost_usd": {"type": "number"},
                        "output_cost_usd": {"type": "number"},
                        "subtotal_usd": {"type": "number"},
                    },
                },
            },
            "assumptions": {
                "type": "object",
                "description": "Assumptions used for the estimate",
                "properties": {
                    "avg_input_tokens_per_round": {"type": "integer"},
                    "avg_output_tokens_per_round": {"type": "integer"},
                    "includes_system_prompt": {"type": "boolean"},
                },
            },
            "num_agents": {"type": "integer"},
            "num_rounds": {"type": "integer"},
        },
        "required": ["total_estimated_cost_usd", "breakdown_by_model"],
    },
    # =========================================================================
    # WebSocket Reconnection Schemas
    # =========================================================================
    "WebSocketResumeToken": {
        "type": "object",
        "description": "Token for resuming a WebSocket connection after disconnect",
        "properties": {
            "resume_token": {
                "type": "string",
                "description": "Opaque token encoding the last received event position",
            },
            "debate_id": {
                "type": "string",
                "description": "Debate this token belongs to",
            },
            "last_seq": {
                "type": "integer",
                "description": "Sequence number of last received event",
            },
            "expires_at": {
                "type": "string",
                "format": "date-time",
                "description": "When this resume token expires",
            },
        },
        "required": ["resume_token", "debate_id", "last_seq"],
    },
}


__all__ = ["DEBATE_REQUEST_SCHEMAS"]
