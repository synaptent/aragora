"""Debate endpoint definitions."""

from aragora.server.openapi.helpers import _ok_response, STANDARD_ERRORS

HYBRID_DEBATE_SCHEMA = {
    "type": "object",
    "properties": {
        "debate_id": {"type": "string"},
        "task": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["pending", "running", "completed", "failed"],
        },
        "consensus_reached": {"type": "boolean"},
        "confidence": {"type": "number"},
        "final_answer": {"type": ["string", "null"]},
        "external_agent": {"type": "string"},
        "verification_agents": {"type": "array", "items": {"type": "string"}},
        "consensus_threshold": {"type": "number"},
        "max_rounds": {"type": "integer"},
        "domain": {"type": "string"},
        "config": {"type": "object", "additionalProperties": True},
        "rounds": {"type": "integer"},
        "started_at": {"type": "string", "format": "date-time"},
        "completed_at": {"type": ["string", "null"], "format": "date-time"},
    },
    "required": ["debate_id", "task", "status", "started_at"],
    "additionalProperties": True,
}

HYBRID_DEBATE_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "debates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "debate_id": {"type": "string"},
                    "task": {"type": "string"},
                    "status": {"type": "string"},
                    "consensus_reached": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "started_at": {"type": "string", "format": "date-time"},
                },
                "required": ["debate_id", "task", "status"],
                "additionalProperties": True,
            },
        },
        "total": {"type": "integer"},
    },
    "required": ["debates", "total"],
}

HYBRID_DEBATE_CREATE_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "minLength": 1, "maxLength": 5000},
        "external_agent": {"type": "string", "minLength": 1},
        "verification_agents": {"type": "array", "items": {"type": "string"}},
        "consensus_threshold": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.7,
        },
        "max_rounds": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
        "domain": {"type": "string", "default": "general"},
        "config": {"type": "object", "additionalProperties": True},
    },
    "required": ["task", "external_agent"],
    "additionalProperties": True,
}

DEBATE_ENDPOINTS = {
    "/api/debates": {
        "get": {
            "tags": ["Debates"],
            "summary": "List debates",
            "description": """Get list of all debates for the authenticated user.

**Rate Limit:** 60 requests per minute (free), 300/min (pro), 1000/min (enterprise)

**Pagination:** Use `limit` and `offset` for pagination. Maximum 100 items per request.

**Filtering:** Results are filtered to debates owned by or shared with the authenticated user.""",
            "operationId": "listDebates",
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Maximum number of debates to return",
                    "schema": {"type": "integer", "default": 20, "maximum": 100, "minimum": 1},
                    "example": 20,
                },
                {
                    "name": "offset",
                    "in": "query",
                    "description": "Number of debates to skip",
                    "schema": {"type": "integer", "default": 0, "minimum": 0},
                    "example": 0,
                },
                {
                    "name": "status",
                    "in": "query",
                    "description": "Filter by debate status",
                    "schema": {
                        "type": ["string", "null"],
                        "enum": ["running", "completed", "failed", "paused"],
                    },
                },
                {
                    "name": "since",
                    "in": "query",
                    "description": "Filter debates created after this timestamp",
                    "schema": {"type": "string", "format": "date-time"},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "List of debates",
                    {
                        "debates": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Debate"},
                        },
                        "count": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "429": STANDARD_ERRORS["429"],
            },
            "security": [{"bearerAuth": []}],
        },
        "post": {
            "tags": ["Debates"],
            "summary": "Create a new debate",
            "description": """Start a new multi-agent debate on a given topic.

**Rate Limit:** 10 debates per day (free), 100/day (pro), unlimited (enterprise)

**Concurrent Limit:** 1 concurrent debate (free), 5 (pro), 20 (enterprise)

**Authentication:** Required. The debate will be owned by the authenticated user.

**WebSocket:** After creation, connect to the returned `websocket_url` to stream real-time debate progress.""",
            "operationId": "createDebate",
            "security": [{"bearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/DebateCreateRequest"},
                        "examples": {
                            "simple": {
                                "summary": "Simple debate",
                                "value": {
                                    "task": "Should we use TypeScript for our next project?",
                                    "rounds": 9,
                                },
                            },
                            "with_agents": {
                                "summary": "Debate with specific agents",
                                "value": {
                                    "task": "Is GraphQL better than REST for mobile apps?",
                                    "agents": ["claude", "gpt-4", "gemini"],
                                    "rounds": 9,
                                    "consensus": "judge",
                                },
                            },
                            "with_context": {
                                "summary": "Debate with context",
                                "value": {
                                    "task": "Should we migrate to Kubernetes?",
                                    "context": "We have 50 microservices and 10 engineers.",
                                    "rounds": 5,
                                    "consensus": "weighted",
                                },
                            },
                        },
                    }
                },
            },
            "responses": {
                "200": _ok_response("Debate created successfully", "DebateCreateResponse"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "402": STANDARD_ERRORS["402"],
                "429": STANDARD_ERRORS["429"],
            },
        },
    },
    "/api/debate": {
        "post": {
            "tags": ["Debates"],
            "summary": "Create a new debate (deprecated)",
            "description": "Deprecated. Use POST /api/debates instead.",
            "operationId": "createDebateDeprecated",
            "deprecated": True,
            "security": [{"bearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/DebateCreateRequest"}
                    }
                },
            },
            "responses": {
                "200": _ok_response("Debate created successfully", "DebateCreateResponse"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
            },
        },
    },
    "/api/debates/{id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate by ID",
            "operationId": "getDebateById",
            "description": "Retrieve full details for a specific debate by its unique identifier.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response("Debate details", "Debate"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/debates/slug/{slug}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate by slug",
            "operationId": "getDebateBySlug",
            "description": "Retrieve full details for a specific debate by its URL-friendly slug.",
            "parameters": [
                {"name": "slug", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response("Debate details", "Debate"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/debates/{id}/messages": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate messages",
            "operationId": "getDebateMessages",
            "description": "Get paginated message history for a debate",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 50, "maximum": 200},
                },
                {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
            ],
            "responses": {
                "200": _ok_response(
                    "Paginated messages",
                    {
                        "messages": {"type": "array", "items": {"type": "object"}},
                        "total": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/convergence": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get convergence status",
            "operationId": "getDebateConvergence",
            "description": "Check if debate has reached semantic convergence",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Convergence status",
                    {
                        "converged": {"type": "boolean"},
                        "similarity_score": {"type": "number"},
                        "rounds_since_convergence": {"type": "integer"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/citations": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get evidence citations",
            "operationId": "getDebateCitations",
            "description": "Get grounded verdict with evidence citations",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Citations and grounding score",
                    {
                        "citations": {"type": "array", "items": {"type": "object"}},
                        "grounding_score": {"type": "number"},
                        "verdict": {"type": "string"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/evidence": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate evidence",
            "operationId": "getDebateEvidence",
            "description": "Get all evidence and sources cited during the debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Evidence data",
                    {
                        "evidence": {"type": "array", "items": {"type": "object"}},
                        "sources": {"type": "array", "items": {"type": "string"}},
                        "total": {"type": "integer"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/impasse": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get impasse status",
            "operationId": "getDebateImpasse",
            "description": "Check if debate reached an impasse",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Impasse status",
                    {
                        "impasse": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "rounds_at_impasse": {"type": "integer"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/meta-critique": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get meta-critique",
            "operationId": "getDebateMetaCritique",
            "description": "Get meta-level critique analyzing the debate's reasoning quality.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Meta-critique data",
                    {
                        "quality_score": {"type": "number"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "weaknesses": {"type": "array", "items": {"type": "string"}},
                        "suggestions": {"type": "array", "items": {"type": "string"}},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/graph/stats": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate graph stats",
            "operationId": "getDebateGraphStats",
            "description": "Get graph statistics showing argument structure and relationships.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Graph statistics",
                    {
                        "node_count": {"type": "integer"},
                        "edge_count": {"type": "integer"},
                        "depth": {"type": "integer"},
                        "clusters": {"type": "integer"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/fork": {
        "post": {
            "tags": ["Debates"],
            "summary": "Fork debate",
            "operationId": "forkDebate",
            "description": "Create a counterfactual branch from a specific round",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "branch_point": {
                                    "type": "integer",
                                    "description": "Round to branch from",
                                },
                                "new_premise": {
                                    "type": "string",
                                    "description": "New premise for fork",
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _ok_response(
                    "Forked debate created",
                    {
                        "fork_id": {"type": "string"},
                        "parent_id": {"type": "string"},
                        "branch_point": {"type": "integer"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
            },
        },
    },
    "/api/debates/{id}/export/{format}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Export debate",
            "operationId": "exportDebate",
            "description": "Export debate content in the specified format for sharing or archiving.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                {
                    "name": "format",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "enum": ["json", "markdown", "html", "pdf"]},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Exported debate",
                    {
                        "content": {"type": "string"},
                        "format": {"type": "string"},
                        "filename": {"type": "string"},
                    },
                )
            },
        },
    },
    "/api/debates/{id}/broadcast": {
        "post": {
            "tags": ["Debates"],
            "summary": "Generate debate broadcast",
            "operationId": "createDebateBroadcast",
            "description": "Generate audio/video broadcast of debate",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "format": {"type": "string", "enum": ["audio", "video"]},
                                "voices": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "202": _ok_response(
                    "Broadcast generation started",
                    {
                        "job_id": {"type": "string"},
                        "status": {"type": "string"},
                        "estimated_duration_seconds": {"type": "integer"},
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/debates/{id}/publish/twitter": {
        "post": {
            "tags": ["Social"],
            "summary": "Publish to Twitter",
            "operationId": "publishDebateToTwitter",
            "description": "Publish debate summary and key points to Twitter/X.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Published to Twitter",
                    {
                        "tweet_id": {"type": "string"},
                        "url": {"type": "string"},
                        "success": {"type": "boolean"},
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/debates/{id}/publish/youtube": {
        "post": {
            "tags": ["Social"],
            "summary": "Publish to YouTube",
            "operationId": "publishDebateToYouTube",
            "description": "Publish debate video/audio to YouTube.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Published to YouTube",
                    {
                        "video_id": {"type": "string"},
                        "url": {"type": "string"},
                        "success": {"type": "boolean"},
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/debates/{id}/red-team": {
        "get": {
            "tags": ["Auditing"],
            "summary": "Get red team results",
            "operationId": "getDebateRedTeamResults",
            "description": "Get adversarial analysis results from red team review.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Red team results",
                    {
                        "vulnerabilities": {"type": "array", "items": {"type": "object"}},
                        "risk_score": {"type": "number"},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                    },
                )
            },
        },
    },
    "/api/v1/graph-debates/{debate_id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get graph debate details",
            "operationId": "getGraphDebateById",
            "description": "Retrieve details for a graph-structured debate by its unique identifier.",
            "parameters": [
                {
                    "name": "debate_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Graph debate details",
                    {
                        "id": {"type": "string"},
                        "nodes": {"type": "array", "items": {"type": "object"}},
                        "edges": {"type": "array", "items": {"type": "object"}},
                        "status": {"type": "string"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/matrix-debates/{debate_id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get matrix debate details",
            "operationId": "getMatrixDebateById",
            "description": "Retrieve details for a matrix-structured debate by its unique identifier.",
            "parameters": [
                {
                    "name": "debate_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Matrix debate details",
                    {
                        "id": {"type": "string"},
                        "rows": {"type": "array", "items": {"type": "object"}},
                        "columns": {"type": "array", "items": {"type": "object"}},
                        "status": {"type": "string"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/search": {
        "get": {
            "tags": ["Debates"],
            "summary": "Cross-debate search",
            "operationId": "searchDebates",
            "description": "Search across all debates for matching content and arguments.",
            "parameters": [
                {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
            ],
            "responses": {
                "200": _ok_response(
                    "Search results",
                    {
                        "results": {"type": "array", "items": {"type": "object"}},
                        "total": {"type": "integer"},
                        "query": {"type": "string"},
                    },
                )
            },
        },
    },
    "/api/dashboard/debates": {
        "get": {
            "tags": ["Debates"],
            "summary": "Dashboard debates",
            "operationId": "getDashboardDebates",
            "description": "Get debates formatted for dashboard display",
            "parameters": [
                {"name": "domain", "in": "query", "schema": {"type": "string"}},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}},
                {"name": "hours", "in": "query", "schema": {"type": "integer", "default": 24}},
            ],
            "responses": {
                "200": _ok_response(
                    "Dashboard data",
                    {
                        "debates": {"type": "array", "items": {"type": "object"}},
                        "stats": {"type": "object"},
                        "period_hours": {"type": "integer"},
                    },
                )
            },
        },
    },
    # ===========================================================================
    # v1 API Endpoints (SDK Compatibility)
    # ===========================================================================
    "/api/v1/debates": {
        "get": {
            "tags": ["Debates"],
            "summary": "List debates",
            "description": """Get a paginated list of debates for the authenticated user.

**Rate Limit:** 60 requests per minute (free), 300/min (pro), 1000/min (enterprise)

**Pagination:** Use `limit` and `offset` query parameters. Maximum 100 items per page.

**Filtering:** Filter by `status` (running, completed, failed, paused) and
`since` (ISO 8601 timestamp) to narrow results.""",
            "operationId": "listDebatesV1",
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Maximum number of debates to return (1-100)",
                    "schema": {"type": "integer", "default": 20, "maximum": 100, "minimum": 1},
                    "example": 20,
                },
                {
                    "name": "offset",
                    "in": "query",
                    "description": "Number of debates to skip for pagination",
                    "schema": {"type": "integer", "default": 0, "minimum": 0},
                    "example": 0,
                },
                {
                    "name": "status",
                    "in": "query",
                    "description": "Filter by debate status",
                    "schema": {
                        "type": "string",
                        "enum": ["running", "completed", "failed", "paused"],
                    },
                },
                {
                    "name": "since",
                    "in": "query",
                    "description": "Return only debates created after this ISO 8601 timestamp",
                    "schema": {"type": "string", "format": "date-time"},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Paginated list of debates",
                    {
                        "type": "object",
                        "properties": {
                            "debates": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Debate"},
                            },
                            "count": {
                                "type": "integer",
                                "description": "Total number of debates matching filters",
                            },
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "429": STANDARD_ERRORS["429"],
            },
            "security": [{"bearerAuth": []}],
        },
        "post": {
            "tags": ["Debates"],
            "summary": "Create a new debate",
            "description": """Start a new multi-agent debate on a given topic.

**How it works:** Aragora selects the best agents for your topic (or uses your
explicit list), runs adversarial rounds where agents propose, critique, and revise
positions, then detects consensus and generates an audit-ready decision receipt.

**Rate Limit:** 10 debates per day (free), 100/day (pro), unlimited (enterprise)

**Concurrent Limit:** 1 concurrent debate (free), 5 (pro), 20 (enterprise)

**WebSocket:** After creation, connect to the returned `websocket_url` to stream
real-time debate progress (proposals, critiques, votes, consensus events).""",
            "operationId": "createDebateV1",
            "security": [{"bearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/DebateCreateRequest"},
                        "examples": {
                            "simple": {
                                "summary": "Simple debate with default agents",
                                "value": {
                                    "task": "Should we use TypeScript for our next project?",
                                    "rounds": 9,
                                },
                            },
                            "with_agents": {
                                "summary": "Debate with specific agents",
                                "value": {
                                    "task": "Is GraphQL better than REST for mobile apps?",
                                    "agents": ["claude", "gpt-4o", "gemini"],
                                    "rounds": 9,
                                    "consensus": "judge",
                                },
                            },
                            "with_context": {
                                "summary": "Debate with organizational context",
                                "value": {
                                    "task": "Should we migrate to Kubernetes?",
                                    "context": "We run 50 microservices with a team of 10 engineers. Current infrastructure is on AWS ECS.",
                                    "rounds": 5,
                                    "consensus": "weighted",
                                },
                            },
                        },
                    }
                },
            },
            "responses": {
                "200": _ok_response("Debate created successfully", "DebateCreateResponse"),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "402": STANDARD_ERRORS["402"],
                "429": STANDARD_ERRORS["429"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/debates/active": {
        "get": {
            "tags": ["Debates"],
            "summary": "List active debates",
            "description": (
                "Return debates that are currently running or paused in the live server state. "
                "This endpoint backs the live debate readiness UI."
            ),
            "operationId": "listActiveDebatesV1",
            "responses": {
                "200": _ok_response(
                    "Active debates returned",
                    {
                        "type": "object",
                        "properties": {
                            "debates": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "topic": {"type": "string"},
                                        "status": {
                                            "type": "string",
                                            "enum": ["running", "paused"],
                                        },
                                        "started_at": {
                                            "type": "string",
                                            "format": "date-time",
                                        },
                                        "agents": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "round": {"type": "integer"},
                                        "total_rounds": {"type": "integer"},
                                        "elapsed_seconds": {"type": "number"},
                                    },
                                    "additionalProperties": True,
                                },
                            },
                        },
                        "required": ["debates"],
                    },
                ),
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/debates/hybrid": {
        "get": {
            "tags": ["Debates"],
            "summary": "List hybrid debates",
            "operationId": "listHybridDebatesV1",
            "description": "List hybrid debates with optional status and limit filters.",
            "parameters": [
                {
                    "name": "status",
                    "in": "query",
                    "description": "Filter by hybrid debate status.",
                    "schema": {
                        "type": "string",
                        "enum": ["pending", "running", "completed", "failed"],
                    },
                },
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Maximum number of hybrid debates to return.",
                    "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
            ],
            "responses": {
                "200": _ok_response("Hybrid debates", HYBRID_DEBATE_LIST_SCHEMA),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "429": STANDARD_ERRORS["429"],
                "500": STANDARD_ERRORS["500"],
            },
            "security": [{"bearerAuth": []}],
        },
        "post": {
            "tags": ["Debates"],
            "summary": "Create hybrid debate",
            "operationId": "createHybridDebateV1",
            "description": "Start a hybrid debate using an external agent and internal verification agents.",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": HYBRID_DEBATE_CREATE_REQUEST_SCHEMA}},
            },
            "responses": {
                "201": _ok_response("Hybrid debate created", HYBRID_DEBATE_SCHEMA),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "429": STANDARD_ERRORS["429"],
                "500": STANDARD_ERRORS["500"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/v1/debates/hybrid/{id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get hybrid debate",
            "operationId": "getHybridDebateV1",
            "description": "Retrieve full details for a specific hybrid debate by ID.",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Hybrid debate identifier.",
                    "example": "hybrid_abc123def456",
                }
            ],
            "responses": {
                "200": _ok_response("Hybrid debate details", HYBRID_DEBATE_SCHEMA),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/v1/debates/{id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate by ID",
            "operationId": "getDebateByIdV1",
            "description": """Retrieve full details for a specific debate by its unique identifier.

**Response includes:**
- Debate metadata (task, status, created_at, duration)
- Agent participation summary
- Round-by-round proposals and critiques
- Consensus information and confidence score
- Receipt ID (if generated)
- WebSocket URL for live streaming (if still running)""",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Unique debate identifier",
                    "example": "deb_abc123xyz",
                }
            ],
            "responses": {
                "200": _ok_response("Debate details", "Debate"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Debates"],
            "summary": "Delete debate",
            "operationId": "deleteDebateV1",
            "description": "Permanently delete a debate and all associated data.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response("Delete result", {"success": {"type": "boolean"}}),
                "404": STANDARD_ERRORS["404"],
            },
            "security": [{"bearerAuth": []}],
        },
        "patch": {
            "tags": ["Debates"],
            "summary": "Update debate metadata",
            "operationId": "patchDebateV1",
            "description": (
                "Update debate metadata. Supported fields: title, tags, "
                "status (active, paused, concluded, archived), and custom "
                "metadata. Use status='archived' for soft-delete."
            ),
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "tags": {"type": "array", "items": {"type": "string"}},
                                "status": {
                                    "type": "string",
                                    "enum": ["active", "paused", "concluded", "archived"],
                                },
                                "metadata": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                # _patch_debate returns an update envelope, not the full
                # Debate resource (see debates/crud.py).
                "200": _ok_response(
                    "Update result with the updated debate summary",
                    {
                        "success": {"type": "boolean"},
                        "debate_id": {"type": "string"},
                        "updated_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "debate": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "status": {"type": "string"},
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/v1/debates/{id}/consensus": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get consensus information",
            "operationId": "getDebateConsensusV1",
            "description": "Get consensus status and conclusion for a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Consensus data",
                    {
                        "reached": {"type": "boolean"},
                        "conclusion": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                        "dissent": {"type": "array", "items": {"type": "string"}},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/explainability": {
        "get": {
            "tags": ["Explainability"],
            "summary": "Get explainability data",
            "operationId": "getDebateExplainabilityV1",
            "description": "Get explainability data for a debate decision.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Explainability data",
                    {
                        "debate_id": {"type": "string"},
                        "narrative": {"type": "string"},
                        "factors": {"type": "array", "items": {"type": "object"}},
                        "confidence": {"type": "number"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/explainability/factors": {
        "get": {
            "tags": ["Explainability"],
            "summary": "Get factor decomposition",
            "operationId": "getDebateExplainabilityFactorsV1",
            "description": "Get factor decomposition for a debate decision.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Factors",
                    {
                        "factors": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "weight": {"type": "number"},
                                    "description": {"type": "string"},
                                    "evidence": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/explainability/narrative": {
        "get": {
            "tags": ["Explainability"],
            "summary": "Get narrative explanation",
            "operationId": "getDebateExplainabilityNarrativeV1",
            "description": "Get natural language narrative explanation.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Narrative",
                    {
                        "text": {"type": "string"},
                        "key_points": {"type": "array", "items": {"type": "string"}},
                        "audience_level": {"type": "string"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/explainability/provenance": {
        "get": {
            "tags": ["Explainability"],
            "summary": "Get provenance chain",
            "operationId": "getDebateExplainabilityProvenanceV1",
            "description": "Get provenance chain for debate claims.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Provenance",
                    {
                        "claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "sources": {"type": "array", "items": {"type": "string"}},
                                    "confidence": {"type": "number"},
                                    "agent": {"type": "string"},
                                },
                            },
                        },
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/explainability/counterfactual": {
        "get": {
            "tags": ["Explainability"],
            "summary": "Get counterfactual analysis",
            "operationId": "getDebateExplainabilityCounterfactualV1",
            "description": "Get counterfactual analysis for a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Counterfactual scenarios",
                    {
                        "scenarios": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "condition": {"type": "string"},
                                    "outcome": {"type": "string"},
                                    "probability": {"type": "number"},
                                },
                            },
                        },
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
        "post": {
            "tags": ["Explainability"],
            "summary": "Create counterfactual scenario",
            "operationId": "createDebateCounterfactualV1",
            "description": "Create a counterfactual scenario for analysis.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {"schema": {"type": "object", "additionalProperties": True}}
                },
            },
            "responses": {
                "200": _ok_response(
                    "Counterfactual result",
                    {
                        "predicted_outcome": {"type": "string"},
                        "confidence": {"type": "number"},
                        "impact_analysis": {"type": "array", "items": {"type": "object"}},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/rhetorical": {
        "get": {
            "tags": ["Auditing"],
            "summary": "Get rhetorical analysis",
            "operationId": "getDebateRhetoricalV1",
            "description": "Get rhetorical pattern observations for a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Rhetorical analysis",
                    {
                        "debate_id": {"type": "string"},
                        "observations": {"type": "array", "items": {"type": "object"}},
                        "summary": {"type": "object"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/trickster": {
        "get": {
            "tags": ["Auditing"],
            "summary": "Get trickster status",
            "operationId": "getDebateTricksterV1",
            "description": "Get hollow consensus detection status from Trickster.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Trickster status",
                    {
                        "debate_id": {"type": "string"},
                        "hollow_consensus_detected": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "indicators": {"type": "array", "items": {"type": "object"}},
                        "recommendation": {"type": ["string", "null"]},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debate/{id}/meta-critique": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get meta-critique",
            "operationId": "getDebateMetaCritiqueV1",
            "description": "Get meta-level critique analyzing the debate's reasoning quality.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Meta-critique",
                    {
                        "debate_id": {"type": "string"},
                        "quality_score": {"type": "number"},
                        "critique": {"type": "string"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "weaknesses": {"type": "array", "items": {"type": "string"}},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                        "agent_performance": {"type": "array", "items": {"type": "object"}},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/archive": {
        "post": {
            "tags": ["Debates"],
            "summary": "Archive debate",
            "operationId": "archiveDebateV1",
            "description": "Archive a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response("Archive result", {"success": {"type": "boolean"}}),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/clone": {
        "post": {
            "tags": ["Debates"],
            "summary": "Clone debate",
            "operationId": "cloneDebateV1",
            "description": "Clone a debate with fresh state.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "preserveAgents": {"type": "boolean"},
                                "preserveContext": {"type": "boolean"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response("Clone result", {"debate_id": {"type": "string"}}),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/evidence": {
        "post": {
            "tags": ["Debates"],
            "summary": "Add evidence",
            "operationId": "addDebateEvidenceV1",
            "description": "Add evidence to a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "evidence": {"type": "string"},
                                "source": {"type": "string"},
                                "metadata": {"type": "object"},
                            },
                            "required": ["evidence"],
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Evidence added",
                    {"evidence_id": {"type": "string"}, "success": {"type": "boolean"}},
                ),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/messages": {
        "post": {
            "tags": ["Debates"],
            "summary": "Add message",
            "operationId": "addDebateMessageV1",
            "description": "Add a message to a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "role": {"type": "string"},
                            },
                            "required": ["content"],
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response("Message", "Message"),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/pause": {
        "post": {
            "tags": ["Debates"],
            "summary": "Pause debate",
            "operationId": "pauseDebateV1",
            "description": "Pause a running debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Pause result",
                    {"success": {"type": "boolean"}, "status": {"type": "string"}},
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/resume": {
        "post": {
            "tags": ["Debates"],
            "summary": "Resume debate",
            "operationId": "resumeDebateV1",
            "description": "Resume a paused debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Resume result",
                    {"success": {"type": "boolean"}, "status": {"type": "string"}},
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/start": {
        "post": {
            "tags": ["Debates"],
            "summary": "Start debate",
            "operationId": "startDebateV1",
            "description": "Start a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Start result",
                    {"success": {"type": "boolean"}, "status": {"type": "string"}},
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/stop": {
        "post": {
            "tags": ["Debates"],
            "summary": "Stop debate",
            "operationId": "stopDebateV1",
            "description": "Stop a running debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Stop result",
                    {"success": {"type": "boolean"}, "status": {"type": "string"}},
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/user-input": {
        "post": {
            "tags": ["Debates"],
            "summary": "Add user input",
            "operationId": "addDebateUserInputV1",
            "description": "Add user input to a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": ["suggestion", "vote", "question", "context"],
                                },
                            },
                            "required": ["input"],
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "User input added",
                    {"input_id": {"type": "string"}, "success": {"type": "boolean"}},
                ),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/verify": {
        "post": {
            "tags": ["Debates"],
            "summary": "Verify claim",
            "operationId": "verifyDebateClaimV1",
            "description": "Verify a specific claim from the debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "claim_id": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                            "required": ["claim_id"],
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Verification result",
                    {
                        "claim_id": {"type": "string"},
                        "verified": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                        "counter_evidence": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/cancel": {
        "post": {
            "tags": ["Debates"],
            "summary": "Cancel debate",
            "operationId": "cancelDebateV1",
            "description": "Cancel a running debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Cancel result",
                    {"success": {"type": "boolean"}, "status": {"type": "string"}},
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/followup": {
        "post": {
            "tags": ["Debates"],
            "summary": "Create follow-up debate",
            "operationId": "createDebateFollowupV1",
            "description": "Create a follow-up debate from an existing one.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "cruxId": {"type": "string"},
                                "context": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response("Follow-up created", {"debate_id": {"type": "string"}}),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/verification-report": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get verification report",
            "operationId": "getDebateVerificationReportV1",
            "description": "Get the verification report for debate conclusions.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Verification report",
                    {
                        "debate_id": {"type": "string"},
                        "verified": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "claims_verified": {"type": "integer"},
                        "claims_total": {"type": "integer"},
                        "verification_details": {"type": "array", "items": {"type": "object"}},
                        "bonuses": {"type": "array", "items": {"type": "object"}},
                        "generated_at": {"type": "string"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/batch": {
        "get": {
            "tags": ["Debates"],
            "summary": "List batch requests",
            "operationId": "listDebateBatchesV1",
            "description": "List submitted debate batches, optionally filtered by status.",
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer", "default": 50, "maximum": 100},
                    "description": "Maximum batches to return.",
                },
                {
                    "name": "status",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Filter by batch status (pending, processing, completed, ...).",
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Batch list",
                    {
                        "batches": {"type": "array", "items": {"type": "object"}},
                        "count": {"type": "integer"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
            },
        },
        "post": {
            "tags": ["Debates"],
            "summary": "Submit batch debates",
            "operationId": "submitDebateBatchV1",
            "description": "Submit multiple debates for batch processing.",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "requests": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/DebateCreateRequest"},
                                },
                            },
                            "required": ["requests"],
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Batch submitted",
                    {
                        "batch_id": {"type": "string"},
                        "jobs": {"type": "array", "items": {"type": "object"}},
                        "total_jobs": {"type": "integer"},
                        "submitted_at": {"type": "string"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
            },
        },
    },
    "/api/v1/debates/batch/{id}/status": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get batch status",
            "operationId": "getDebateBatchStatusV1",
            "description": "Get the status of a batch job.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Batch status",
                    {
                        "batch_id": {"type": "string"},
                        "status": {"type": "string"},
                        "total_jobs": {"type": "integer"},
                        "completed_jobs": {"type": "integer"},
                        "failed_jobs": {"type": "integer"},
                        "jobs": {"type": "array", "items": {"type": "object"}},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/queue/status": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get queue status",
            "operationId": "getDebateQueueStatusV1",
            "description": "Get the current queue status.",
            "responses": {
                "200": _ok_response(
                    "Queue status",
                    {
                        "pending_count": {"type": "integer"},
                        "running_count": {"type": "integer"},
                        "completed_today": {"type": "integer"},
                        "average_wait_time_ms": {"type": "integer"},
                        "estimated_completion_time": {"type": ["string", "null"]},
                    },
                ),
            },
        },
    },
    "/api/v1/debates/graph/{id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get debate graph",
            "operationId": "getDebateGraphV1",
            "description": "Get the argument graph for a debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Debate graph",
                    {
                        "nodes": {"type": "array", "items": {"type": "object"}},
                        "edges": {"type": "array", "items": {"type": "object"}},
                        "metadata": {"type": "object"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/matrix/{id}": {
        "get": {
            "tags": ["Debates"],
            "summary": "Get matrix comparison",
            "operationId": "getDebateMatrixV1",
            "description": "Get matrix comparison for a multi-scenario debate.",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": _ok_response(
                    "Matrix comparison",
                    {
                        "debate_id": {"type": "string"},
                        "scenarios": {"type": "array", "items": {"type": "object"}},
                        "comparison_matrix": {"type": "array", "items": {"type": "array"}},
                        "dominant_scenario": {"type": ["string", "null"]},
                        "sensitivity_analysis": {"type": ["object", "null"]},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    # =========================================================================
    # Debate Diagnostics (SME Self-Service Debugging)
    # =========================================================================
    "/api/v1/debates/{id}/diagnostics": {
        "get": {
            "tags": ["Debates", "Diagnostics"],
            "summary": "Get debate diagnostics",
            "operationId": "getDebateDiagnosticsV1",
            "description": """Get a diagnostic report for a debate.

**Purpose:** SME self-service debugging. Helps users understand why a debate
failed, timed out, or produced unexpected results without reading server logs.

**Response includes:**
- Overall debate status and wall-clock duration
- Per-agent participation report (rounds, proposals, critiques, errors)
- Consensus information (reached, method, confidence score)
- Whether a decision receipt was generated
- Actionable suggestions for resolving issues (e.g. missing API keys, too few rounds)""",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "The debate ID to diagnose",
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Diagnostic report",
                    {
                        "type": "object",
                        "properties": {
                            "debate_id": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["running", "completed", "failed", "paused", "unknown"],
                            },
                            "duration_seconds": {
                                "type": "number",
                                "description": "Wall-clock duration of the debate in seconds",
                            },
                            "agents": {
                                "type": "array",
                                "description": "Per-agent diagnostic information",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "provider": {
                                            "type": "string",
                                            "description": "Inferred AI provider (anthropic, openai, google, etc.)",
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["active", "failed", "timeout", "inactive"],
                                        },
                                        "rounds_participated": {"type": "integer"},
                                        "proposals": {"type": "integer"},
                                        "critiques": {"type": "integer"},
                                        "error": {
                                            "type": ["string", "null"],
                                            "description": "Error message if agent failed",
                                        },
                                    },
                                },
                            },
                            "consensus": {
                                "type": "object",
                                "properties": {
                                    "reached": {"type": "boolean"},
                                    "method": {
                                        "type": "string",
                                        "description": "Consensus method used (majority, weighted, judge, unanimous)",
                                    },
                                    "confidence": {
                                        "type": "number",
                                        "description": "Consensus confidence score (0.0 - 1.0)",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                },
                            },
                            "receipt_generated": {
                                "type": "boolean",
                                "description": "Whether a decision receipt was generated for this debate",
                            },
                            "suggestions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Actionable suggestions for resolving issues",
                            },
                        },
                        "required": [
                            "debate_id",
                            "status",
                            "duration_seconds",
                            "agents",
                            "consensus",
                            "receipt_generated",
                            "suggestions",
                        ],
                        "example": {
                            "debate_id": "deb_abc123",
                            "status": "failed",
                            "duration_seconds": 45.2,
                            "agents": [
                                {
                                    "name": "claude",
                                    "provider": "anthropic",
                                    "status": "active",
                                    "rounds_participated": 3,
                                    "proposals": 3,
                                    "critiques": 2,
                                    "error": None,
                                },
                                {
                                    "name": "gpt-4o",
                                    "provider": "openai",
                                    "status": "failed",
                                    "rounds_participated": 0,
                                    "proposals": 0,
                                    "critiques": 0,
                                    "error": "API key invalid or expired",
                                },
                            ],
                            "consensus": {
                                "reached": False,
                                "method": "majority",
                                "confidence": 0.0,
                            },
                            "receipt_generated": False,
                            "suggestions": [
                                "Agent gpt-4o did not participate - verify OPENAI_API_KEY is set and valid",
                                "No consensus reached after 3 rounds - consider increasing round count or reducing agent count",
                                "Consider adding OPENROUTER_API_KEY as fallback for failed providers",
                            ],
                        },
                    },
                ),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
}
