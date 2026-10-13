"""Tests for OpenAPI schema generator."""

import json
import pytest

from aragora.server.openapi import (
    API_VERSION,
    COMMON_SCHEMAS,
    ALL_ENDPOINTS,
    generate_openapi_schema,
    get_openapi_json,
    get_openapi_yaml,
    handle_openapi_request,
)


class TestOpenAPISchema:
    """Tests for OpenAPI schema generation."""

    def test_api_version_format(self):
        """API version follows semver format."""
        parts = API_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_common_schemas_defined(self):
        """Common schemas are defined."""
        assert "Error" in COMMON_SCHEMAS
        assert "Agent" in COMMON_SCHEMAS
        assert "Debate" in COMMON_SCHEMAS
        assert "Message" in COMMON_SCHEMAS
        assert "HealthCheck" in COMMON_SCHEMAS
        assert "PaginatedResponse" in COMMON_SCHEMAS

    def test_error_schema_structure(self):
        """Error schema has required fields."""
        error = COMMON_SCHEMAS["Error"]
        assert error["type"] == "object"
        assert "error" in error["properties"]
        assert "error" in error["required"]

    def test_agent_schema_structure(self):
        """Agent schema has expected fields."""
        agent = COMMON_SCHEMAS["Agent"]
        assert agent["type"] == "object"
        props = agent["properties"]
        assert "name" in props
        assert "elo" in props
        assert "matches" in props

    def test_debate_schema_structure(self):
        """Debate schema has expected fields."""
        debate = COMMON_SCHEMAS["Debate"]
        assert debate["type"] == "object"
        props = debate["properties"]
        assert "id" in props
        assert "topic" in props
        assert "status" in props
        # Note: messages are in separate Message schema, not embedded in Debate

    def test_message_schema_structure(self):
        """Message schema has expected fields."""
        message = COMMON_SCHEMAS["Message"]
        assert message["type"] == "object"
        props = message["properties"]
        assert "role" in props
        assert "content" in props
        assert "agent" in props

    def test_health_check_schema_structure(self):
        """HealthCheck schema has expected fields."""
        health = COMMON_SCHEMAS["HealthCheck"]
        assert health["type"] == "object"
        props = health["properties"]
        assert "status" in props
        assert "version" in props
        assert "timestamp" in props


class TestEndpoints:
    """Tests for endpoint definitions."""

    def test_health_endpoint_defined(self):
        """Health endpoint is defined."""
        assert "/api/health" in ALL_ENDPOINTS
        assert "get" in ALL_ENDPOINTS["/api/health"]

    def test_agents_endpoint_defined(self):
        """Agents endpoint is defined."""
        assert "/api/agents" in ALL_ENDPOINTS
        endpoint = ALL_ENDPOINTS["/api/agents"]
        assert "get" in endpoint
        assert endpoint["get"]["tags"] == ["Agents"]

    def test_debates_endpoint_defined(self):
        """Debates endpoint is defined."""
        assert "/api/debates" in ALL_ENDPOINTS
        assert "/api/debates/{id}" in ALL_ENDPOINTS
        assert "/api/debates/{id}/messages" in ALL_ENDPOINTS

    def test_leaderboard_endpoint_defined(self):
        """Leaderboard endpoint is defined."""
        assert "/api/leaderboard" in ALL_ENDPOINTS
        endpoint = ALL_ENDPOINTS["/api/leaderboard"]
        assert "limit" in str(endpoint)

    def test_analytics_endpoints_defined(self):
        """Analytics endpoints are defined."""
        assert "/api/analytics/disagreements" in ALL_ENDPOINTS
        assert "/api/analytics/role-rotation" in ALL_ENDPOINTS
        assert "/api/analytics/early-stops" in ALL_ENDPOINTS

    def test_pulse_endpoints_defined(self):
        """Pulse endpoints are defined."""
        assert "/api/pulse/trending" in ALL_ENDPOINTS
        assert "/api/pulse/suggest" in ALL_ENDPOINTS

    def test_metrics_endpoints_defined(self):
        """Metrics endpoints are defined."""
        assert "/api/metrics" in ALL_ENDPOINTS
        assert "/metrics" in ALL_ENDPOINTS  # Prometheus format at /metrics

    def test_endpoint_has_tags(self):
        """All endpoints have tags."""
        for path, methods in ALL_ENDPOINTS.items():
            for method, spec in methods.items():
                assert "tags" in spec, f"{path} {method} missing tags"

    def test_endpoint_has_summary(self):
        """All endpoints have summary."""
        for path, methods in ALL_ENDPOINTS.items():
            for method, spec in methods.items():
                assert "summary" in spec, f"{path} {method} missing summary"

    def test_endpoint_has_responses(self):
        """All endpoints have responses."""
        for path, methods in ALL_ENDPOINTS.items():
            for method, spec in methods.items():
                assert "responses" in spec, f"{path} {method} missing responses"


class TestSDKReferencedEndpointRegistrations:
    """Live, SDK-referenced, stability-manifest-pinned endpoints must be registered.

    GET proofs is served at runtime via handlers/verification/verification.py
    ROUTES dispatch; the quotas path is claimed by
    UsageMeteringHandler.can_handle, and its POST branch is served by
    handle()'s dedicated request-increase action-literal dispatch.
    Both were invisible to the generator, so any aggregate-spec sync dropped
    them and regressed verify_sdk_contracts --strict.
    """

    def test_verification_proofs_get_defined(self):
        """GET /api/v1/verification/proofs is registered with its served method."""
        assert "/api/v1/verification/proofs" in ALL_ENDPOINTS
        endpoint = ALL_ENDPOINTS["/api/v1/verification/proofs"]
        assert "get" in endpoint
        assert endpoint["get"]["tags"] == ["Verification"]
        assert endpoint["get"]["operationId"] == "listVerificationProofs"

    def test_verification_proofs_get_documents_runtime_contract(self):
        """The proofs GET documents the runtime envelope, params, and auth.

        _get_proofs returns an object envelope (proofs/filters/limit/total),
        accepts debate_id/proof_type/limit query params, and sits behind
        require_permission — not a bare array on an unauthenticated route.
        Its degraded z3-unavailable envelope (proofs/available/hint) is
        documented via optional available/hint properties.
        """
        op = ALL_ENDPOINTS["/api/v1/verification/proofs"]["get"]
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert schema["properties"]["proofs"]["type"] == "array"
        assert {"filters", "limit", "total"} <= set(schema["properties"])
        # Degraded envelope (z3 unavailable): {proofs, available, hint} only.
        assert schema["properties"]["available"]["type"] == "boolean"
        assert schema["properties"]["hint"]["type"] == "string"
        param_names = {p["name"] for p in op["parameters"]}
        assert param_names == {"debate_id", "proof_type", "limit"}
        assert op["security"] == [{"bearerAuth": []}]

    def test_quotas_request_increase_post_defined(self):
        """POST /api/v1/quotas/request-increase is registered."""
        assert "/api/v1/quotas/request-increase" in ALL_ENDPOINTS
        endpoint = ALL_ENDPOINTS["/api/v1/quotas/request-increase"]
        assert "post" in endpoint
        assert endpoint["post"]["tags"] == ["Quotas"]
        assert endpoint["post"]["operationId"] == "createQuotaIncreaseRequest"

    def test_quotas_request_increase_post_documents_runtime_contract(self):
        """The quotas POST documents the served contract runtime-true.

        _request_quota_increase (handlers/usage_metering.py) sits behind
        require_permission("org:billing"), reads a JSON body with required
        resource plus optional requested_limit/reason (justification accepted
        as the python SDK's documented alias), and returns the submission
        receipt echoing the request plus org/submitter/timestamp metadata.
        """
        op = ALL_ENDPOINTS["/api/v1/quotas/request-increase"]["post"]
        assert op["security"] == [{"bearerAuth": []}]
        body = op["requestBody"]
        assert body["required"] is True
        schema = body["content"]["application/json"]["schema"]
        assert schema["required"] == ["resource"]
        assert {"resource", "requested_limit", "reason", "justification"} <= set(
            schema["properties"]
        )
        receipt = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert {
            "request_id",
            "status",
            "resource",
            "requested_limit",
            "reason",
            "org_id",
            "submitted_by",
            "submitted_at",
        } <= set(receipt["properties"])

    def test_generated_schema_emits_pinned_operations(self):
        """Generator emits the stability-pinned v1 operations."""
        schema = generate_openapi_schema()
        paths = schema["paths"]
        assert "get" in paths["/api/v1/verification/proofs"]
        assert "post" in paths["/api/v1/quotas/request-increase"]

    def test_v1_proofs_get_replaces_inferred_post_placeholder(self):
        """The real GET registration displaces the wrong-method autogen POST."""
        schema = generate_openapi_schema()
        entry = schema["paths"]["/api/v1/verification/proofs"]
        assert "post" not in entry
        assert entry["get"].get("x-method-inferred") is not True
        assert entry["get"]["operationId"] == "listVerificationProofs"

    def test_no_unserved_legacy_aliases_emitted(self):
        """No unversioned aliases: the dispatcher passes raw paths with no
        legacy<->v1 aliasing and the handlers claim only the v1 literals, so a
        legacy alias would be a spec-orphan (validate_openapi_routes)."""
        schema = generate_openapi_schema()
        assert "/api/verification/proofs" not in schema["paths"]
        assert "/api/quotas/request-increase" not in schema["paths"]


class TestSdkMissingRuntimeTrueBackfill:
    """Runtime-true pins for the served sdk_missing.py charter entries.

    Census follow-up to the quotas enrichment: of the 21 remaining charter
    operations, exactly three are reachable through _try_modular_handler
    (route-index/can_handle match into a handler method that serves the
    documented path). These pins bind their spec entries to the handler
    truth so a spec edit that drifts from the served contract fails here
    before verify_sdk_contracts or sdk-parity see it.
    """

    def test_matches_stats_get_documents_runtime_contract(self):
        """GET /api/matches/stats documents the served public stats shape.

        MatchesStatsHandler.handle serves the exact version-stripped path with
        no auth check (a public ranking read like the leaderboard), returning
        EloSystem.get_stats(): total_agents/avg_elo/max_elo/min_elo/
        total_matches, all always present (missing aggregates default).
        """
        op = ALL_ENDPOINTS["/api/matches/stats"]["get"]
        assert "security" not in op
        assert "requestBody" not in op
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {
            "total_agents",
            "avg_elo",
            "max_elo",
            "min_elo",
            "total_matches",
        }
        assert schema["properties"]["total_agents"]["type"] == "integer"
        assert schema["properties"]["avg_elo"]["type"] == "number"
        assert schema["properties"]["total_matches"]["type"] == "integer"

    def test_reputation_history_get_documents_runtime_contract(self):
        """GET /api/reputation/history documents the served snapshot timeline.

        CritiqueHandler.handle sits behind require_permission("critiques:read"),
        accepts agent/start_date/end_date filters plus a 1..1000-clamped limit,
        and returns {history: [{timestamp, agent, reputation, event}], count}.
        timestamp is AgentReputation.updated_at (str, default ""), never null.
        """
        op = ALL_ENDPOINTS["/api/reputation/history"]["get"]
        assert op["security"] == [{"bearerAuth": []}]
        params = {p["name"]: p for p in op["parameters"]}
        assert set(params) == {"agent", "start_date", "end_date", "limit"}
        assert all(p["in"] == "query" for p in params.values())
        assert not any(p.get("required") for p in params.values())
        assert params["limit"]["schema"]["type"] == "integer"
        assert params["limit"]["schema"]["maximum"] == 1000
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {"history", "count"}
        item = schema["properties"]["history"]["items"]
        assert set(item["properties"]) == {"timestamp", "agent", "reputation", "event"}
        assert item["properties"]["timestamp"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"

    def test_reputation_domain_get_documents_runtime_contract(self):
        """GET /api/reputation/domain documents the served domain filter.

        CritiqueHandler.handle (require_permission("critiques:read")) 400s
        without ?domain= and returns {domain, reputations: [...], count} with
        the six per-agent reputation fields _get_reputation_by_domain emits.
        """
        op = ALL_ENDPOINTS["/api/reputation/domain"]["get"]
        assert op["security"] == [{"bearerAuth": []}]
        params = {p["name"]: p for p in op["parameters"]}
        assert set(params) == {"domain", "limit"}
        assert params["domain"]["required"] is True
        assert params["domain"]["in"] == "query"
        assert not params["limit"].get("required")
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert set(schema["properties"]) == {"domain", "reputations", "count"}
        item = schema["properties"]["reputations"]["items"]
        assert set(item["properties"]) == {
            "agent",
            "score",
            "vote_weight",
            "proposal_acceptance_rate",
            "critique_value",
            "debates_participated",
        }
        assert item["properties"]["debates_participated"]["type"] == "integer"


class TestGenerateOpenAPISchema:
    """Tests for schema generation function."""

    def test_returns_dict(self):
        """Returns a dictionary."""
        schema = generate_openapi_schema()
        assert isinstance(schema, dict)

    def test_openapi_version(self):
        """Has correct OpenAPI version."""
        schema = generate_openapi_schema()
        assert schema["openapi"] == "3.1.0"

    def test_info_section(self):
        """Has info section with required fields."""
        schema = generate_openapi_schema()
        info = schema["info"]
        assert info["title"] == "Aragora API"
        assert info["version"] == API_VERSION
        assert "description" in info

    def test_servers_section(self):
        """Has servers section."""
        schema = generate_openapi_schema()
        servers = schema["servers"]
        assert len(servers) >= 1
        assert "url" in servers[0]
        assert "description" in servers[0]

    def test_tags_section(self):
        """Has tags section."""
        schema = generate_openapi_schema()
        tags = schema["tags"]
        tag_names = [t["name"] for t in tags]
        assert "System" in tag_names
        assert "Agents" in tag_names
        assert "Debates" in tag_names

    def test_paths_section(self):
        """Has paths section with endpoints."""
        schema = generate_openapi_schema()
        assert "paths" in schema
        assert len(schema["paths"]) > 0

    def test_components_section(self):
        """Has components section with schemas."""
        schema = generate_openapi_schema()
        assert "components" in schema
        assert "schemas" in schema["components"]
        assert len(schema["components"]["schemas"]) > 0

    def test_security_schemes(self):
        """Has security schemes defined."""
        schema = generate_openapi_schema()
        security = schema["components"]["securitySchemes"]
        assert "bearerAuth" in security
        assert security["bearerAuth"]["type"] == "http"
        assert security["bearerAuth"]["scheme"] == "bearer"


class TestGetOpenAPIJson:
    """Tests for JSON output."""

    def test_returns_string(self):
        """Returns a JSON string."""
        result = get_openapi_json()
        assert isinstance(result, str)

    def test_valid_json(self):
        """Returns valid JSON."""
        result = get_openapi_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_json_has_openapi_key(self):
        """JSON has openapi key."""
        result = get_openapi_json()
        parsed = json.loads(result)
        assert "openapi" in parsed


class TestGetOpenAPIYaml:
    """Tests for YAML output."""

    def test_returns_string(self):
        """Returns a string."""
        result = get_openapi_yaml()
        assert isinstance(result, str)

    def test_contains_openapi_key(self):
        """Output contains openapi key."""
        result = get_openapi_yaml()
        assert "openapi" in result

    def test_yaml_format_if_available(self):
        """Uses YAML format if PyYAML available."""
        try:
            import yaml

            result = get_openapi_yaml()
            # YAML format uses colons without quotes
            assert "openapi:" in result
        except ImportError:
            # Falls back to JSON
            result = get_openapi_yaml()
            assert '"openapi"' in result


class TestHandleOpenAPIRequest:
    """Tests for request handler."""

    def test_default_json_format(self):
        """Default format is JSON."""
        content, content_type = handle_openapi_request()
        assert content_type == "application/json"
        assert '"openapi"' in content

    def test_explicit_json_format(self):
        """JSON format when requested."""
        content, content_type = handle_openapi_request(format="json")
        assert content_type == "application/json"

    def test_yaml_format(self):
        """YAML format when requested."""
        content, content_type = handle_openapi_request(format="yaml")
        assert content_type == "application/yaml"
        assert "openapi" in content

    def test_content_is_string(self):
        """Content is always a string."""
        for fmt in ["json", "yaml"]:
            content, _ = handle_openapi_request(format=fmt)
            assert isinstance(content, str)


class TestSchemaValidation:
    """Tests for schema validation."""

    def test_all_refs_valid(self):
        """All $ref references point to existing schemas."""
        schema = generate_openapi_schema()
        schemas = schema["components"]["schemas"]

        def check_refs(obj, path=""):
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref = obj["$ref"]
                    # Extract schema name from #/components/schemas/SchemaName
                    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                        schema_name = ref.split("/")[-1]
                        assert schema_name in schemas, f"Invalid $ref at {path}: {ref}"
                for k, v in obj.items():
                    check_refs(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_refs(item, f"{path}[{i}]")

        check_refs(schema["paths"])

    def test_path_parameters_match(self):
        """Path parameters in URL match parameter definitions."""
        schema = generate_openapi_schema()

        for path, methods in schema["paths"].items():
            # Extract path params from URL
            import re

            url_params = set(re.findall(r"\{(\w+)\}", path))

            for method, spec in methods.items():
                if url_params:
                    params = spec.get("parameters", [])
                    defined_path_params = {p["name"] for p in params if p.get("in") == "path"}
                    assert url_params == defined_path_params, (
                        f"{path} {method}: URL params {url_params} != defined {defined_path_params}"
                    )

    def test_response_codes_valid(self):
        """Response codes are valid HTTP codes."""
        schema = generate_openapi_schema()
        for path, methods in schema["paths"].items():
            for method, spec in methods.items():
                for code in spec["responses"].keys():
                    assert code.isdigit() and 100 <= int(code) <= 599, (
                        f"{path} {method}: invalid response code {code}"
                    )
