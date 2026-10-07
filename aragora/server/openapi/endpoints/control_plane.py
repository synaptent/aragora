"""Control plane endpoint definitions."""

from aragora.server.openapi.helpers import _ok_response, STANDARD_ERRORS, AUTH_REQUIREMENTS

CONTROL_PLANE_ENDPOINTS = {
    "/api/control-plane/agents": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "List control plane agents",
            "operationId": "listControlPlaneAgents",
            "description": "List registered agents. Supports filtering by capability.",
            "parameters": [
                {
                    "name": "capability",
                    "in": "query",
                    "description": "Filter agents by capability",
                    "schema": {"type": "string"},
                },
                {
                    "name": "available",
                    "in": "query",
                    "description": "Only show available agents (default: true)",
                    "schema": {"type": "boolean", "default": True},
                },
            ],
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response("Agent list", "ControlPlaneAgentList"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "post": {
            "tags": ["Control Plane"],
            "summary": "Register agent",
            "operationId": "createControlPlaneAgents",
            "description": "Register an agent with capabilities and model metadata.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["agent_id", "capabilities"],
                            "properties": {
                                "agent_id": {"type": "string"},
                                "capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "model": {"type": "string"},
                                "provider": {"type": "string"},
                                "metadata": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _ok_response("Agent registered", "ControlPlaneAgent"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/control-plane/agents/{agent_id}": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Get agent",
            "operationId": "getControlPlaneAgent",
            "description": "Get a specific agent by ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "agent_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Agent details", "ControlPlaneAgent"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Control Plane"],
            "summary": "Unregister agent",
            "operationId": "deleteControlPlaneAgent",
            "description": "Unregister an agent by ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "agent_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Agent unregistered",
                    {
                        "agent_id": {"type": "string"},
                        "unregistered": {"type": "boolean"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/control-plane/agents/{agent_id}/heartbeat": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Send heartbeat",
            "operationId": "createControlPlaneAgentsHeartbeat",
            "description": "Update agent heartbeat and status.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "agent_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Heartbeat accepted",
                    {
                        "agent_id": {"type": "string"},
                        "accepted": {"type": "boolean"},
                        "next_heartbeat_ms": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/tasks": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Submit task",
            "operationId": "createControlPlaneTasks",
            "description": "Submit a task to the control plane scheduler.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["task_type"],
                            "properties": {
                                "task_type": {"type": "string"},
                                "payload": {"type": "object"},
                                "required_capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": ["low", "normal", "high", "urgent"],
                                },
                                "timeout_seconds": {"type": "number"},
                                "metadata": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _ok_response("Task submitted", "ControlPlaneTaskCreated"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/tasks/{task_id}": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Get task",
            "operationId": "getControlPlaneTask",
            "description": "Get task status and metadata by ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "task_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Task details", "ControlPlaneTask"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/tasks/{task_id}/complete": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Complete task",
            "operationId": "createControlPlaneTasksComplete",
            "description": "Mark a task as completed.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "task_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "result": {"type": "object"},
                                "agent_id": {"type": "string"},
                                "latency_ms": {"type": "number"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Task completed",
                    {
                        "task_id": {"type": "string"},
                        "completed": {"type": "boolean"},
                        "completed_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/tasks/{task_id}/fail": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Fail task",
            "operationId": "createControlPlaneTasksFail",
            "description": "Mark a task as failed.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "task_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "error": {"type": "string"},
                                "agent_id": {"type": "string"},
                                "result": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Task failed",
                    {
                        "task_id": {"type": "string"},
                        "failed": {"type": "boolean"},
                        "failed_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/tasks/{task_id}/cancel": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Cancel task",
            "operationId": "createControlPlaneTasksCancel",
            "description": "Cancel a task by ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "task_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Task cancelled",
                    {
                        "task_id": {"type": "string"},
                        "cancelled": {"type": "boolean"},
                        "cancelled_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/tasks/claim": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Claim task",
            "operationId": "createControlPlaneTasksClaim",
            "description": "Claim the next available task for an agent.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["agent_id"],
                            "properties": {
                                "agent_id": {"type": "string"},
                                "capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "block_ms": {"type": "integer", "default": 5000},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response("Task claim result", "ControlPlaneTaskClaimResponse"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/queue": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Queue snapshot",
            "operationId": "listControlPlaneQueue",
            "description": "Get pending and running tasks for dashboard queue.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 50},
                }
            ],
            "responses": {
                "200": _ok_response("Queue snapshot", "ControlPlaneQueue"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/metrics": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Control plane metrics",
            "operationId": "listControlPlaneMetrics",
            "description": "Get dashboard metrics derived from scheduler and registry stats.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response("Metrics snapshot", "ControlPlaneMetrics"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/stats": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Control plane stats",
            "operationId": "listControlPlaneStats",
            "description": "Get scheduler and registry stats.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response("Control plane stats", "ControlPlaneStats"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/health": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "System health",
            "operationId": "listControlPlaneHealth",
            "description": "Get system health with agent health summaries.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response("System health", "ControlPlaneHealth"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/health/{agent_id}": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Agent health",
            "operationId": "getControlPlaneHealth",
            "description": "Get health status for a specific agent.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "agent_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Agent health",
                    {
                        "agent_id": {"type": "string"},
                        "healthy": {"type": "boolean"},
                        "status": {"type": "string"},
                        "last_heartbeat": {"type": "string", "format": "date-time"},
                        "latency_ms": {"type": "number"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/deliberations": {
        "post": {
            "tags": ["Control Plane"],
            "summary": "Run vetted decisionmaking session",
            "operationId": "createControlPlaneDeliberations",
            "description": "Run or queue a vetted decisionmaking session (async when async=true).",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/DeliberationRequest"}
                    }
                },
            },
            "responses": {
                "200": _ok_response("Decisionmaking completed", "DeliberationSyncResponse"),
                "202": _ok_response("Decisionmaking queued", "DeliberationQueuedResponse"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/control-plane/deliberations/{request_id}": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Get vetted decisionmaking result",
            "operationId": "getControlPlaneDeliberation",
            "description": "Fetch a stored vetted decisionmaking record by request ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "request_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Decisionmaking record", "DeliberationRecord"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    # -------------------------------------------------------------------------
    # Policies
    # -------------------------------------------------------------------------
    "/api/v1/policies/{policy_id}": {
        "get": {
            "tags": ["Control Plane", "Policies"],
            "summary": "Get policy by ID",
            "operationId": "getPolicy",
            "description": "Retrieve a specific governance policy by its unique identifier.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "policy_id",
                    "in": "path",
                    "required": True,
                    "description": "Policy ID",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Policy details", "Policy"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "put": {
            "tags": ["Control Plane", "Policies"],
            "summary": "Update policy",
            "operationId": "updatePolicy",
            "description": "Update an existing governance policy. Validates for conflicts with other active policies.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "policy_id",
                    "in": "path",
                    "required": True,
                    "description": "Policy ID",
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Policy name"},
                                "description": {
                                    "type": "string",
                                    "description": "Policy description",
                                },
                                "rules": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                    "description": "Policy rules",
                                },
                                "enabled": {
                                    "type": "boolean",
                                    "description": "Whether the policy is active",
                                },
                                "priority": {
                                    "type": "integer",
                                    "description": "Policy evaluation priority (lower = higher priority)",
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response("Policy updated", "Policy"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "409": {
                    "description": "Policy conflict detected with existing policies",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"},
                        },
                    },
                },
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Control Plane", "Policies"],
            "summary": "Delete policy",
            "operationId": "deletePolicy",
            "description": "Delete a governance policy by ID. Active policies must be disabled before deletion.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "policy_id",
                    "in": "path",
                    "required": True,
                    "description": "Policy ID",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Policy deleted",
                    {
                        "policy_id": {"type": "string"},
                        "deleted": {"type": "boolean"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "409": {
                    "description": "Cannot delete an active policy - disable it first",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"},
                        },
                    },
                },
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/control-plane/deliberations/{request_id}/status": {
        "get": {
            "tags": ["Control Plane"],
            "summary": "Get vetted decisionmaking status",
            "operationId": "getControlPlaneDeliberationsStatu",
            "description": "Check vetted decisionmaking status for polling.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "request_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Decisionmaking status", "DeliberationStatus"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/coordination/active-work": {
        "get": {
            "tags": ["Coordination"],
            "summary": "Get active agent work snapshot",
            "operationId": "getCoordinationActiveWork",
            "description": (
                "Return a compact, agent-readable snapshot over existing fleet claims, "
                "developer leases, merge queue entries, worktree sessions, and active "
                "agent bridge runs."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "base",
                    "in": "query",
                    "required": False,
                    "description": "Base branch for worktree status.",
                    "schema": {"type": "string", "default": "main"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Active work snapshot",
                    {
                        "type": "object",
                        "required": [
                            "schema_version",
                            "repo_root",
                            "base_branch",
                            "generated_at",
                            "active_owners",
                            "claimed_paths",
                            "avoid_paths",
                            "worktrees",
                            "fleet_claims",
                            "active_leases",
                            "merge_queue",
                            "bridge_runs",
                            "counts",
                            "source_errors",
                        ],
                        "properties": {
                            "schema_version": {"type": "integer", "enum": [1]},
                            "repo_root": {"type": "string"},
                            "base_branch": {"type": "string"},
                            "generated_at": {"type": "string", "format": "date-time"},
                            "active_owners": {"type": "array", "items": {"type": "object"}},
                            "claimed_paths": {"type": "array", "items": {"type": "string"}},
                            "avoid_paths": {"type": "array", "items": {"type": "string"}},
                            "avoid_path_hints": {"type": "array", "items": {"type": "object"}},
                            "worktrees": {"type": "array", "items": {"type": "object"}},
                            "fleet_claims": {"type": "array", "items": {"type": "object"}},
                            "active_leases": {"type": "array", "items": {"type": "object"}},
                            "merge_queue": {"type": "array", "items": {"type": "object"}},
                            "bridge_runs": {"type": "array", "items": {"type": "object"}},
                            "counts": {"type": "object", "additionalProperties": True},
                            "source_errors": {"type": "array", "items": {"type": "object"}},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
}
