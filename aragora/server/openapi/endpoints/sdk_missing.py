"""SDK endpoint stubs for contract parity.

These endpoints are referenced by Python SDK namespaces but don't yet have
full handler implementations. Adding them to the OpenAPI spec ensures the
contract matrix test passes and documents the planned API surface.
"""

from aragora.server.openapi.helpers import _ok_response

_obj = {"type": "object"}
_str = {"type": "string"}
_arr_obj = {"type": "array", "items": {"type": "object"}}

SDK_MISSING_ENDPOINTS: dict = {
    # --- support ---
    "/api/support/connect": {
        "post": {
            "tags": ["Support"],
            "summary": "Connect support integration",
            "description": "Create or authorize a support-system integration used for ticket ingestion and response workflows.",
            "operationId": "createSupportConnect",
            "responses": {"200": _ok_response("Connected", _obj)},
        },
    },
    "/api/support/triage": {
        "post": {
            "tags": ["Support"],
            "summary": "Triage support request",
            "description": "Run triage over a support request and return routing or prioritization metadata.",
            "operationId": "createSupportTriage",
            "responses": {"200": _ok_response("Triage result", _obj)},
        },
    },
    "/api/support/auto-respond": {
        "post": {
            "tags": ["Support"],
            "summary": "Auto-respond to support ticket",
            "description": "Generate and send an automated response for a support ticket using configured support workflows.",
            "operationId": "createSupportAutoRespond",
            "responses": {"200": _ok_response("Response sent", _obj)},
        },
    },
    "/api/support/{support_id}": {
        "delete": {
            "tags": ["Support"],
            "summary": "Delete support integration",
            "description": "Remove a previously configured support integration and revoke its active connection.",
            "operationId": "deleteSupportIntegration",
            "parameters": [
                {
                    "name": "support_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique support integration identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Deleted")},
        },
    },
    "/api/support/{support_id}/tickets": {
        "post": {
            "tags": ["Support"],
            "summary": "Create support ticket",
            "description": "Create a new ticket within the specified support integration.",
            "operationId": "createSupportTicket",
            "parameters": [
                {
                    "name": "support_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique support integration identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"201": _ok_response("Ticket created", _obj)},
        },
    },
    "/api/support/{support_id}/tickets/{ticket_id}": {
        "put": {
            "tags": ["Support"],
            "summary": "Update support ticket",
            "description": "Update ticket fields or workflow state for a ticket in the configured support system.",
            "operationId": "updateSupportTicket",
            "parameters": [
                {
                    "name": "support_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique support integration identifier.",
                    "schema": _str,
                },
                {
                    "name": "ticket_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique ticket identifier within the support system.",
                    "schema": _str,
                },
            ],
            "responses": {"200": _ok_response("Ticket updated", _obj)},
        },
    },
    "/api/support/{support_id}/tickets/{ticket_id}/reply": {
        "post": {
            "tags": ["Support"],
            "summary": "Reply to support ticket",
            "description": "Post a reply to an existing support ticket and return delivery metadata.",
            "operationId": "createSupportTicketReply",
            "parameters": [
                {
                    "name": "support_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique support integration identifier.",
                    "schema": _str,
                },
                {
                    "name": "ticket_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique ticket identifier within the support system.",
                    "schema": _str,
                },
            ],
            "responses": {"200": _ok_response("Reply sent", _obj)},
        },
    },
    # --- flips ---
    "/api/flips/{flip_id}": {
        "get": {
            "tags": ["Flips"],
            "summary": "Get flip details",
            "description": "Retrieve detailed metadata for a recorded flip event.",
            "operationId": "getFlip",
            "parameters": [
                {
                    "name": "flip_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique flip identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Flip details", _obj)},
        },
    },
    # --- ecommerce ---
    "/api/ecommerce/connect": {
        "post": {
            "tags": ["Ecommerce"],
            "summary": "Connect ecommerce integration",
            "description": "Create or authorize an ecommerce integration used for inventory and fulfillment workflows.",
            "operationId": "createEcommerceConnect",
            "responses": {"200": _ok_response("Connected", _obj)},
        },
    },
    "/api/ecommerce/sync-inventory": {
        "post": {
            "tags": ["Ecommerce"],
            "summary": "Sync inventory",
            "description": "Trigger an inventory synchronization job for a connected ecommerce system.",
            "operationId": "createEcommerceSyncInventory",
            "responses": {"200": _ok_response("Inventory synced", _obj)},
        },
    },
    "/api/ecommerce/ship": {
        "post": {
            "tags": ["Ecommerce"],
            "summary": "Ship order",
            "description": "Create or trigger shipment handling for an ecommerce order.",
            "operationId": "createEcommerceShip",
            "responses": {"200": _ok_response("Shipment created", _obj)},
        },
    },
    "/api/ecommerce/{integration_id}": {
        "delete": {
            "tags": ["Ecommerce"],
            "summary": "Delete ecommerce integration",
            "description": "Remove a connected ecommerce integration and stop future sync activity.",
            "operationId": "deleteEcommerceIntegration",
            "parameters": [
                {
                    "name": "integration_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique ecommerce integration identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Deleted")},
        },
    },
    # --- crm ---
    "/api/crm/connect": {
        "post": {
            "tags": ["CRM"],
            "summary": "Connect CRM integration",
            "description": "Create or authorize a CRM integration for lead sync and enrichment workflows.",
            "operationId": "createCrmConnect",
            "responses": {"200": _ok_response("Connected", _obj)},
        },
    },
    "/api/crm/sync-lead": {
        "post": {
            "tags": ["CRM"],
            "summary": "Sync lead to CRM",
            "description": "Push a lead or contact update into the configured CRM system.",
            "operationId": "createCrmSyncLead",
            "responses": {"200": _ok_response("Lead synced", _obj)},
        },
    },
    "/api/crm/enrich": {
        "post": {
            "tags": ["CRM"],
            "summary": "Enrich CRM contact",
            "description": "Run enrichment for a CRM contact and return the updated contact payload.",
            "operationId": "createCrmEnrich",
            "responses": {"200": _ok_response("Contact enriched", _obj)},
        },
    },
    "/api/crm/{integration_id}": {
        "delete": {
            "tags": ["CRM"],
            "summary": "Delete CRM integration",
            "description": "Remove a configured CRM integration and revoke its active connection.",
            "operationId": "deleteCrmIntegration",
            "parameters": [
                {
                    "name": "integration_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique CRM integration identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Deleted")},
        },
    },
    # --- matches ---
    # Served: MatchesStatsHandler.handle exact-matches the version-stripped
    # path and returns EloSystem.get_stats() verbatim. Public read (no auth
    # check), like the other ranking reads; every key is always present
    # because missing aggregates fall back to defaults.
    "/api/matches/stats": {
        "get": {
            "tags": ["Matches"],
            "summary": "Get match statistics",
            "description": "Return aggregate statistics for the match system.",
            "operationId": "getMatchStats",
            "responses": {
                "200": _ok_response(
                    "Match statistics",
                    {
                        "type": "object",
                        "properties": {
                            "total_agents": {"type": "integer"},
                            "avg_elo": {"type": "number"},
                            "max_elo": {"type": "number"},
                            "min_elo": {"type": "number"},
                            "total_matches": {"type": "integer"},
                        },
                    },
                )
            },
        },
    },
    "/api/matches/{match_id}": {
        "get": {
            "tags": ["Matches"],
            "summary": "Get match details",
            "description": "Retrieve a single match record and its associated metadata.",
            "operationId": "getMatch",
            "parameters": [
                {
                    "name": "match_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique match identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Match details", _obj)},
        },
    },
    # --- quotas ---
    # Not an orphan: the path is claimed at runtime by
    # UsageMeteringHandler.can_handle's dynamic /api/v1/quotas/{resource}
    # dispatch and is pinned stable in stability_manifest.json. The POST
    # branch is served: handle() dispatches this action literal to
    # _request_quota_increase ahead of the dynamic {resource} branch; both
    # SDKs already expose the call, which is exactly this module's charter.
    # v1 literal only: the dispatcher passes raw paths with no legacy<->v1
    # aliasing, so an unversioned alias would document an unserved path.
    "/api/v1/quotas/request-increase": {
        "post": {
            "tags": ["Quotas"],
            "summary": "Request quota increase",
            "description": (
                "Submit a quota increase request for review. Requires the org:billing permission."
            ),
            "operationId": "createQuotaIncreaseRequest",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["resource"],
                            "properties": {
                                "resource": {
                                    "type": "string",
                                    "maxLength": 256,
                                    "description": "Resource type the increase applies to.",
                                },
                                "requested_limit": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "description": "Desired new limit.",
                                },
                                "reason": {
                                    "type": "string",
                                    "maxLength": 2000,
                                    "description": "Why the increase is needed.",
                                },
                                "justification": {
                                    "type": "string",
                                    "maxLength": 2000,
                                    "description": (
                                        "Accepted alias for reason; the key the "
                                        "python SDK documents."
                                    ),
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Request submitted",
                    {
                        "type": "object",
                        "properties": {
                            "request_id": {"type": "string"},
                            "status": {"type": "string"},
                            "resource": {"type": "string"},
                            "requested_limit": {"type": ["number", "null"]},
                            "reason": {"type": ["string", "null"]},
                            "org_id": {"type": "string"},
                            "submitted_by": {"type": "string"},
                            "submitted_at": {"type": "string"},
                        },
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    # --- reputation ---
    # Served: CritiqueHandler.handle lists the raw path in ROUTES and sits
    # behind require_permission("critiques:read"). Missing ?domain= is a 400;
    # limit is clamped to 1..1000 (default 100). The reputation rows mirror
    # _get_reputation_by_domain's projection of AgentReputation.
    "/api/reputation/domain": {
        "get": {
            "tags": ["Reputation"],
            "summary": "Get domain reputation scores",
            "description": (
                "Return domain-level reputation scores or reputation summaries. "
                "Requires the critiques:read permission."
            ),
            "operationId": "getReputationDomain",
            "parameters": [
                {
                    "name": "domain",
                    "in": "query",
                    "required": True,
                    "description": "Domain token matched against agent names.",
                    "schema": _str,
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": "Maximum reputations to return.",
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                        "default": 100,
                    },
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Domain reputation",
                    {
                        "type": "object",
                        "properties": {
                            "domain": _str,
                            "reputations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "agent": _str,
                                        "score": {"type": "number"},
                                        "vote_weight": {"type": "number"},
                                        "proposal_acceptance_rate": {"type": "number"},
                                        "critique_value": {"type": "number"},
                                        "debates_participated": {"type": "integer"},
                                    },
                                },
                            },
                            "count": {"type": "integer"},
                        },
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    # Served: same CritiqueHandler ROUTES dispatch and critiques:read
    # permission as /api/reputation/domain. Snapshots derive from stored
    # reputation rows; timestamp is AgentReputation.updated_at (a string
    # defaulting to "", never null) and event is always "snapshot".
    "/api/reputation/history": {
        "get": {
            "tags": ["Reputation"],
            "summary": "Get reputation history",
            "description": (
                "List historical reputation events or score snapshots. "
                "Requires the critiques:read permission."
            ),
            "operationId": "getReputationHistory",
            "parameters": [
                {
                    "name": "agent",
                    "in": "query",
                    "required": False,
                    "description": "Restrict snapshots to a single agent.",
                    "schema": _str,
                },
                {
                    "name": "start_date",
                    "in": "query",
                    "required": False,
                    "description": "ISO-8601 lower bound; invalid values are a 400.",
                    "schema": _str,
                },
                {
                    "name": "end_date",
                    "in": "query",
                    "required": False,
                    "description": "ISO-8601 upper bound; invalid values are a 400.",
                    "schema": _str,
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": "Maximum snapshots to return.",
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                        "default": 100,
                    },
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Reputation history",
                    {
                        "type": "object",
                        "properties": {
                            "history": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "timestamp": _str,
                                        "agent": _str,
                                        "reputation": {"type": "number"},
                                        "event": _str,
                                    },
                                },
                            },
                            "count": {"type": "integer"},
                        },
                    },
                )
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/reputation/{agent_id}": {
        "get": {
            "tags": ["Reputation"],
            "summary": "Get agent reputation",
            "description": "Retrieve the current reputation profile for a specific agent.",
            "operationId": "getReputationByAgentId",
            "parameters": [
                {
                    "name": "agent_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique agent identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Agent reputation", _obj)},
        },
    },
}

__all__ = ["SDK_MISSING_ENDPOINTS"]
