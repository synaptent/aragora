"""Pipeline endpoint definitions for the Idea-to-Execution canvas pipeline."""

from aragora.server.openapi.helpers import STANDARD_ERRORS, AUTH_REQUIREMENTS

_ID_PARAM = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Pipeline ID",
}

_DEBATE_ID_PARAM = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Debate ID",
}

_AGENT_ID_PARAM = {
    "name": "agent_id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Agent assignment ID",
}

_STAGE_PARAM = {
    "name": "stage",
    "in": "path",
    "required": True,
    "schema": {
        "type": "string",
        "enum": ["ideas", "principles", "goals", "actions", "orchestration"],
    },
    "description": "Pipeline stage name",
}

_GRAPH_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string"},
                                "summary": {"type": "string"},
                                "content": {"type": "string"},
                            },
                        },
                    },
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_id": {"type": "string"},
                                "target_id": {"type": "string"},
                                "relation": {"type": "string"},
                            },
                        },
                    },
                },
            }
        }
    },
}


def _json_response(description: str) -> dict:
    """Inline 200 response with generic JSON object body."""
    return {
        "description": description,
        "content": {"application/json": {"schema": {"type": "object"}}},
    }


def _transition_request_body(*, include_pipeline_id: bool) -> dict:
    """Request body for approve/reject transition endpoints."""
    required = ["from_stage", "to_stage"]
    properties = {
        "from_stage": {"type": "string"},
        "to_stage": {"type": "string"},
        "approved": {
            "type": "boolean",
            "description": "Defaults to true when omitted; set to false to reject.",
        },
        "comment": {"type": "string"},
    }
    if include_pipeline_id:
        required.insert(0, "pipeline_id")
        properties["pipeline_id"] = {"type": "string"}

    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": required,
                    "properties": properties,
                }
            }
        },
    }


PIPELINE_ENDPOINTS: dict[str, dict] = {
    "/api/v1/canvas/pipeline": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get latest pipeline or list pipelines",
            "operationId": "listOrLatestPipeline",
            "description": (
                "Return the latest canvas pipeline by default. Pass `list=true` to return "
                "pipeline summaries instead."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "list",
                    "in": "query",
                    "schema": {"type": "boolean"},
                    "description": "Return pipeline summaries instead of the latest pipeline.",
                },
                {
                    "name": "status",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": "Optional status filter when list mode is enabled.",
                },
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 100},
                    "description": "Maximum number of pipeline summaries to return in list mode.",
                },
            ],
            "responses": {
                "200": _json_response("Latest pipeline payload or pipeline list"),
            },
        },
    },
    "/api/v1/canvas/pipeline/from-ideas": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Create pipeline from ideas",
            "operationId": "createPipelineFromIdeas",
            "description": "Create a full 4-stage pipeline from a list of raw idea strings.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["ideas"],
                            "properties": {
                                "ideas": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of idea strings",
                                }
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Pipeline result"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/from-debate": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Create pipeline from debate",
            "operationId": "createPipelineFromDebate",
            "description": "Create a pipeline from an ArgumentCartographer debate graph (nodes + edges).",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _GRAPH_BODY,
            "responses": {
                "200": _json_response("Pipeline result"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/from-braindump": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Create pipeline from brain dump",
            "operationId": "createPipelineFromBrainDump",
            "description": (
                "Parse unstructured text into ideas and immediately create a pipeline from "
                "the extracted ideas."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string"},
                                "context": {"type": "string"},
                                "auto_advance": {"type": "boolean"},
                                "use_unified_orchestrator": {"type": "boolean"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _json_response("Pipeline created from a parsed brain dump"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/from-template": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Create pipeline from template",
            "operationId": "createPipelineFromTemplate",
            "description": "Create a pipeline from a named template.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["template_id"],
                            "properties": {
                                "template_id": {"type": "string"},
                                "parameters": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Pipeline result"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/demo": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Create demo pipeline",
            "operationId": "createDemoPipeline",
            "description": "Create a pre-populated demo pipeline with all stages completed.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "ideas": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                }
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _json_response("Demo pipeline created"),
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/advance": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Advance pipeline stage",
            "operationId": "advancePipelineStage",
            "description": "Advance a pipeline to the next stage (e.g. ideas -> goals).",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["pipeline_id", "target_stage"],
                            "properties": {
                                "pipeline_id": {"type": "string"},
                                "target_stage": {
                                    "type": "string",
                                    "enum": ["ideas", "goals", "actions", "orchestration"],
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Advance result"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/approve-transition": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Approve stage transition by body",
            "operationId": "approvePipelineTransitionByBody",
            "description": (
                "Approve or reject a pending stage transition when the pipeline ID is sent "
                "in the request body."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _transition_request_body(include_pipeline_id=True),
            "responses": {
                "200": _json_response("Transition result"),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/run": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Run async pipeline",
            "operationId": "runPipeline",
            "description": "Start an asynchronous pipeline execution from ideas through all stages.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["ideas"],
                            "properties": {
                                "ideas": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "202": {
                    "description": "Pipeline started",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "pipeline_id": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/extract-goals": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Extract goals from ideas",
            "operationId": "extractGoals",
            "description": "Use AI to extract structured goals from an ideas canvas.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _GRAPH_BODY,
            "responses": {
                "200": _json_response("Extracted goals"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/extract-principles": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Extract principles from ideas canvas",
            "operationId": "extractPipelinePrinciples",
            "description": "Extract principles and themes from an ideas canvas.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["ideas_canvas"],
                            "properties": {
                                "ideas_canvas": {"type": "object"},
                                "themes": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Principles canvas"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/auto-run": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Auto-run pipeline from freeform text",
            "operationId": "autoRunPipeline",
            "description": (
                "Start an asynchronous pipeline from freeform text and return a pipeline "
                "identifier immediately."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string"},
                                "automation_level": {
                                    "type": "string",
                                    "enum": ["full", "guided", "manual"],
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Auto-run pipeline start status"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/from-system-metrics": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Create pipeline from system metrics",
            "operationId": "createPipelineFromSystemMetrics",
            "description": "Auto-generate a pipeline from system health analysis.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {"type": "object"},
                    }
                },
            },
            "responses": {
                "200": _json_response("Pipeline created from system metrics"),
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/convert/debate": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Convert debate to ideas canvas",
            "operationId": "convertDebateToCanvas",
            "description": "Convert a debate graph into an ideas-stage canvas.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _GRAPH_BODY,
            "responses": {
                "200": _json_response("Ideas canvas"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/convert/workflow": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Convert workflow to actions canvas",
            "operationId": "convertWorkflowToCanvas",
            "description": "Convert a workflow definition into an actions-stage canvas.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"type": "object"},
                    }
                },
            },
            "responses": {
                "200": _json_response("Actions canvas"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/templates": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "List pipeline templates",
            "operationId": "listPipelineTemplates",
            "description": "List available pipeline templates.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _json_response("Template list"),
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline",
            "operationId": "getPipeline",
            "description": "Get a pipeline result by ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Pipeline result"),
                "404": STANDARD_ERRORS["404"],
            },
        },
        "put": {
            "tags": ["Pipeline"],
            "summary": "Save pipeline canvas state",
            "operationId": "savePipeline",
            "description": "Save the current canvas state for a pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"type": "object"}},
                },
            },
            "responses": {
                "200": _json_response("Saved"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/status": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline stage status",
            "operationId": "getPipelineStatus",
            "description": "Get per-stage completion status for a pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Stage status"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/stage/{stage}": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline stage canvas",
            "operationId": "getPipelineStage",
            "description": "Get the canvas data for a specific pipeline stage.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM, _STAGE_PARAM],
            "responses": {
                "200": _json_response("Stage canvas"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/graph": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline React Flow graph",
            "operationId": "getPipelineGraph",
            "description": "Get the React Flow compatible graph JSON for a pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                _ID_PARAM,
                {
                    "name": "stage",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": "Filter to a specific stage",
                },
            ],
            "responses": {
                "200": _json_response("React Flow graph"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/receipt": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline decision receipt",
            "operationId": "getPipelineReceipt",
            "description": "Get the cryptographic decision receipt for a completed pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Decision receipt"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/approve-transition": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Approve stage transition",
            "operationId": "approvePipelineTransition",
            "description": "Approve or reject a pending stage transition.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "requestBody": _transition_request_body(include_pipeline_id=False),
            "responses": {
                "200": _json_response("Transition result"),
                "404": STANDARD_ERRORS["404"],
                "400": STANDARD_ERRORS["400"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/execute": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Execute completed pipeline",
            "operationId": "executeCanvasPipeline",
            "description": (
                "Queue execution for a completed pipeline or return a dry-run summary of the "
                "planned work."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "dry_run": {"type": "boolean"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Dry-run execution summary"),
                "202": _json_response("Pipeline execution queued"),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/intelligence": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline intelligence rollup",
            "operationId": "getPipelineIntelligence",
            "description": (
                "Return beliefs, explanations, and precedents for nodes in the pipeline."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Pipeline intelligence"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/beliefs": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline beliefs",
            "operationId": "getPipelineBeliefs",
            "description": "Return belief-network-style confidence data for pipeline nodes.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Pipeline beliefs"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/explanations": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline explanations",
            "operationId": "getPipelineExplanations",
            "description": "Return explainability factors for pipeline nodes.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Pipeline explanations"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/precedents": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "Get pipeline precedents",
            "operationId": "getPipelinePrecedents",
            "description": "Return similar goals or precedents linked to the pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Pipeline precedents"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/canvas/pipeline/{id}/self-improve": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Feed pipeline into self-improvement",
            "operationId": "selfImprovePipeline",
            "description": (
                "Trigger the self-improvement system using a pipeline as the source task "
                "definition."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "budget_limit": {"type": "number"},
                                "require_approval": {"type": "boolean"},
                                "dry_run": {"type": "boolean"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Self-improvement preview"),
                "201": _json_response("Self-improvement run started"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/v1/debates/{id}/to-pipeline": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Convert debate to pipeline",
            "operationId": "convertDebateToPipeline",
            "description": (
                "Load a completed debate's argument graph and create a pipeline from it."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_DEBATE_ID_PARAM],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "use_universal": {"type": "boolean"},
                                "auto_advance": {"type": "boolean"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _json_response("Pipeline created from debate"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/pipeline/{id}/agents": {
        "get": {
            "tags": ["Pipeline"],
            "summary": "List pipeline agents",
            "operationId": "listPipelineAgents",
            "description": "Return current agent assignments and statuses for a pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM],
            "responses": {
                "200": _json_response("Pipeline agent assignments"),
            },
        },
    },
    "/api/v1/pipeline/{id}/agents/{agent_id}/approve": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Approve pipeline agent",
            "operationId": "approvePipelineAgent",
            "description": "Approve an assigned agent task for a pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM, _AGENT_ID_PARAM],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "notes": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Agent approval recorded"),
            },
        },
    },
    "/api/v1/pipeline/{id}/agents/{agent_id}/reject": {
        "post": {
            "tags": ["Pipeline"],
            "summary": "Reject pipeline agent",
            "operationId": "rejectPipelineAgent",
            "description": "Reject an assigned agent task for a pipeline.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_ID_PARAM, _AGENT_ID_PARAM],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["feedback"],
                            "properties": {
                                "feedback": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _json_response("Agent rejection recorded"),
                "400": STANDARD_ERRORS["400"],
            },
        },
    },
}

# Body-addressed routes that look up an existing pipeline by ``pipeline_id``.
_BODY_ID_ROUTES = frozenset(
    {"/api/v1/canvas/pipeline/advance", "/api/v1/canvas/pipeline/approve-transition"}
)

# Every pipeline route needs a signed-in user with an organization, and another
# org's pipeline answers exactly like a missing one.
for _path, _operations in PIPELINE_ENDPOINTS.items():
    for _operation in _operations.values():
        _responses = _operation["responses"]
        _responses.setdefault("401", STANDARD_ERRORS["401"])
        _responses.setdefault("403", STANDARD_ERRORS["403"])
        if "{id}" in _path or _path in _BODY_ID_ROUTES:
            _responses.setdefault("404", STANDARD_ERRORS["404"])
