"""Verification and auditing endpoint definitions."""

from aragora.server.openapi.helpers import _ok_response

VERIFICATION_ENDPOINTS = {
    "/api/verification/status": {
        "get": {
            "tags": ["Verification"],
            "summary": "Verification status",
            "operationId": "listVerificationStatus",
            "description": "Get the current status of verification services and backend availability.",
            "responses": {
                "200": _ok_response(
                    "Verification status",
                    {
                        "available": {"type": "boolean"},
                        "backends": {"type": "array", "items": {"type": "string"}},
                        "z3_version": {"type": "string"},
                    },
                )
            },
        },
    },
    "/api/verification/formal-verify": {
        "post": {
            "tags": ["Verification"],
            "summary": "Formal verification",
            "operationId": "createVerificationFormalVerify",
            "description": "Run formal verification on claims",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "claims": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                    "description": "Claims to formally verify",
                                },
                                "backend": {
                                    "type": "string",
                                    "enum": ["z3", "lean"],
                                    "description": "Verification backend to use",
                                },
                            },
                            "required": ["claims"],
                        }
                    }
                }
            },
            "responses": {
                "200": _ok_response(
                    "Verification result",
                    {
                        "verified": {"type": "boolean"},
                        "proofs": {"type": "array", "items": {"type": "object"}},
                        "counterexamples": {"type": "array", "items": {"type": "object"}},
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    # Registered under the v1 literal only: the runtime dispatcher passes raw
    # request paths to can_handle with no legacy<->v1 aliasing, and
    # VerificationHandler.ROUTES claims only the /api/v1/ form, so an
    # unversioned alias here would document an unserved path.
    "/api/v1/verification/proofs": {
        "get": {
            "tags": ["Verification"],
            "summary": "List verification proofs",
            "operationId": "listVerificationProofs",
            "description": "Return stored verification proofs and associated metadata for prior verification runs.",
            "parameters": [
                {
                    "name": "debate_id",
                    "in": "query",
                    "required": False,
                    "description": "Filter proofs by debate identifier.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "proof_type",
                    "in": "query",
                    "required": False,
                    "description": "Filter proofs by proof type.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": "Maximum number of proofs to return.",
                    "schema": {"type": "integer", "default": 20},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Proofs list",
                    {
                        "type": "object",
                        "properties": {
                            "proofs": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                            "filters": {"type": "object"},
                            "limit": {"type": "integer"},
                            "total": {"type": "integer"},
                            "available": {
                                "type": "boolean",
                                "description": (
                                    "False when the formal-verification backend "
                                    "(z3) is unavailable; that degraded envelope "
                                    "returns only proofs/available/hint."
                                ),
                            },
                            "hint": {
                                "type": "string",
                                "description": (
                                    "Remediation hint, present only in the "
                                    "degraded (z3-unavailable) envelope."
                                ),
                            },
                        },
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/debates/capability-probe": {
        "post": {
            "tags": ["Auditing"],
            "summary": "Run capability probe",
            "operationId": "createDebatesCapabilityProbe",
            "description": "Run a capability probe to test agent abilities and identify potential limitations.",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "agent_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Agents to probe",
                                },
                                "probe_type": {
                                    "type": "string",
                                    "enum": ["reasoning", "knowledge", "creativity", "full"],
                                    "description": "Type of capability probe",
                                },
                            },
                        }
                    }
                }
            },
            "responses": {
                "200": _ok_response(
                    "Probe results",
                    {
                        "probe_id": {"type": "string"},
                        "results": {"type": "array", "items": {"type": "object"}},
                        "limitations": {"type": "array", "items": {"type": "string"}},
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/debates/deep-audit": {
        "post": {
            "tags": ["Auditing"],
            "summary": "Deep audit",
            "operationId": "createDebatesDeepAudit",
            "description": "Run a comprehensive deep audit on debate results to identify quality issues.",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debate_id": {"type": "string", "description": "Debate to audit"},
                                "depth": {
                                    "type": "string",
                                    "enum": ["shallow", "medium", "deep"],
                                    "description": "Audit depth level",
                                },
                                "focus_areas": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Areas to focus on",
                                },
                            },
                            "required": ["debate_id"],
                        }
                    }
                }
            },
            "responses": {
                "200": _ok_response(
                    "Audit results",
                    {
                        "audit_id": {"type": "string"},
                        "issues": {"type": "array", "items": {"type": "object"}},
                        "severity_counts": {"type": "object"},
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/probes/capability": {
        "post": {
            "tags": ["Auditing"],
            "summary": "Capability probe",
            "operationId": "createProbesCapability",
            "description": "Execute a capability probe to assess agent performance across various dimensions.",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "agent_id": {"type": "string", "description": "Agent to probe"},
                                "capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Specific capabilities to test",
                                },
                            },
                        }
                    }
                }
            },
            "responses": {
                "200": _ok_response(
                    "Probe results",
                    {
                        "probe_id": {"type": "string", "description": "Probe execution ID"},
                        "agent_id": {"type": "string", "description": "Probed agent ID"},
                        "capabilities": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Assessed capability results",
                        },
                        "overall_score": {
                            "type": "number",
                            "description": "Overall capability score",
                        },
                    },
                ),
            },
            "security": [{"bearerAuth": []}],
        },
    },
}
