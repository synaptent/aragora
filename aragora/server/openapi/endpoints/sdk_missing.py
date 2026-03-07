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
    # --- verification (additional) ---
    "/api/verification/proofs": {
        "get": {
            "tags": ["Verification"],
            "summary": "List verification proofs",
            "description": "Return stored verification proofs and associated metadata for prior verification runs.",
            "operationId": "listVerificationProofs",
            "responses": {"200": _ok_response("Proofs list", _arr_obj)},
        },
    },
    "/api/verification/validate": {
        "post": {
            "tags": ["Verification"],
            "summary": "Validate claims",
            "description": "Validate supplied claims or evidence and return a verification result payload.",
            "operationId": "createVerificationValidate",
            "responses": {"200": _ok_response("Validation result", _obj)},
        },
    },
    # --- calibration ---
    "/api/calibration/curve": {
        "get": {
            "tags": ["Calibration"],
            "summary": "Get calibration curve",
            "description": "Fetch calibration-curve data used to evaluate model or agent confidence quality.",
            "operationId": "getCalibrationCurve",
            "responses": {"200": _ok_response("Calibration curve data", _obj)},
        },
    },
    "/api/calibration/history": {
        "get": {
            "tags": ["Calibration"],
            "summary": "Get calibration history",
            "description": "List historical calibration measurements and snapshots for supported agents or systems.",
            "operationId": "getCalibrationHistory",
            "responses": {"200": _ok_response("Calibration history", _arr_obj)},
        },
    },
    # --- services ---
    "/api/services/{service_id}/health": {
        "get": {
            "tags": ["Services"],
            "summary": "Get service health",
            "description": "Return health information for an external or internal service registered with Aragora.",
            "operationId": "getServiceHealth",
            "parameters": [
                {
                    "name": "service_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique service identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Service health", _obj)},
        },
    },
    "/api/services/{service_id}/metrics": {
        "get": {
            "tags": ["Services"],
            "summary": "Get service metrics",
            "description": "Return operational metrics for a registered service.",
            "operationId": "getServiceMetrics",
            "parameters": [
                {
                    "name": "service_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique service identifier.",
                    "schema": _str,
                }
            ],
            "responses": {"200": _ok_response("Service metrics", _obj)},
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
    "/api/matches/stats": {
        "get": {
            "tags": ["Matches"],
            "summary": "Get match statistics",
            "description": "Return aggregate statistics for the match system.",
            "operationId": "getMatchStats",
            "responses": {"200": _ok_response("Match statistics", _obj)},
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
    "/api/quotas/request-increase": {
        "post": {
            "tags": ["Quotas"],
            "summary": "Request quota increase",
            "description": "Submit a quota increase request for review.",
            "operationId": "createQuotaIncreaseRequest",
            "responses": {"200": _ok_response("Request submitted", _obj)},
        },
    },
    # --- reputation ---
    "/api/reputation/domain": {
        "get": {
            "tags": ["Reputation"],
            "summary": "Get domain reputation scores",
            "description": "Return domain-level reputation scores or reputation summaries.",
            "operationId": "getReputationDomain",
            "responses": {"200": _ok_response("Domain reputation", _obj)},
        },
    },
    "/api/reputation/history": {
        "get": {
            "tags": ["Reputation"],
            "summary": "Get reputation history",
            "description": "List historical reputation events or score snapshots.",
            "operationId": "getReputationHistory",
            "responses": {"200": _ok_response("Reputation history", _arr_obj)},
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
