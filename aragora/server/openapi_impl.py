"""
OpenAPI Schema Generator for Aragora API.

Generates OpenAPI 3.1 specification for all API endpoints.
Endpoints are organized by tag/category for clear documentation.

OpenAPI 3.1 uses JSON Schema 2020-12 which provides:
- Better nullable handling (type arrays instead of nullable: true)
- JSON Schema $ref compatibility
- Improved content negotiation

Usage:
    from aragora.server.openapi import generate_openapi_schema, save_openapi_schema

    # Get schema as dict
    schema = generate_openapi_schema()

    # Save to file
    path, count = save_openapi_schema("docs/api/openapi.json")
"""

import ast
import copy
import inspect
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any

# Import schemas and helpers from submodules
from aragora.server.auth_requirements import AuthLevel, get_requirement
from aragora.server.openapi.route_contract_overrides import ROUTE_CONTRACT_OVERRIDES
from aragora.server.openapi.schemas import COMMON_SCHEMAS

# Import all endpoint definitions from endpoints subpackage
from aragora.server.openapi.endpoints import (
    ALL_ENDPOINTS,
    WIRED_REGISTRATION_ENDPOINTS,
    WIRED_REGISTRATION_NO_V1_ALIASES,
)
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# API version
API_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Tag inference from URL path patterns
# ---------------------------------------------------------------------------
# Ordered list of (path_prefix, tag) rules. First match wins, so more
# specific prefixes (e.g. "bots/telegram") must come before generic ones
# (e.g. "bots").  The path is stripped of /api/, /api/v1/, /api/v2/ before
# matching.
# ---------------------------------------------------------------------------
TAG_INFERENCE_RULES: list[tuple[str, str]] = [
    # Bot platform-specific
    ("bots/telegram", "Bots - Telegram"),
    ("bots/discord", "Bots - Discord"),
    ("bots/whatsapp", "Bots - WhatsApp"),
    ("bots/google-chat", "Bots - Google Chat"),
    ("bots/zoom", "Bots - Zoom"),
    ("bots/teams", "Teams"),
    ("bots/email", "Email"),
    ("bots/slack", "Bots"),
    ("bots", "Bots"),
    # SME sub-features
    ("sme/teams", "Teams"),
    ("sme/slack", "Integrations"),
    ("sme/budgets", "Budgets"),
    ("sme/receipts", "Gauntlet"),
    ("sme/success", "SME"),
    ("sme", "SME"),
    # Workflow sub-features (before generic "workflow")
    ("workflow-templates", "Workflow Templates"),
    ("workflow-approvals", "Workflows"),
    ("workflow-executions", "Workflows"),
    ("workflows", "Workflows"),
    ("workflow", "Workflows"),
    # Core debate
    ("debates", "Debates"),
    ("debate", "Debates"),
    ("graph-debates", "Debates"),
    ("matrix-debates", "Debates"),
    ("deliberations", "Deliberations"),
    ("consensus", "Consensus"),
    ("decisions", "Decisions"),
    # Agents & rankings
    ("agents", "Agents"),
    ("agent-dashboard", "Agents"),
    ("agent", "Agents"),
    ("flips", "Insights"),
    ("leaderboard", "Agents"),
    ("rankings", "Agents"),
    ("selection", "Routing"),
    ("calibration", "Agents"),
    ("persona", "Agents"),
    ("training", "Agents"),
    ("ml", "Agents"),
    # Memory & knowledge
    ("memory", "Memory"),
    ("learning", "Learning"),
    ("meta-learning", "Learning"),
    ("knowledge_base", "Knowledge"),
    ("knowledge-mound", "Knowledge Mound"),
    ("knowledge", "Knowledge"),
    ("km", "Knowledge Mound"),
    ("evidence", "Knowledge"),
    ("belief", "Belief"),
    ("cross-pollination", "Cross-Pollination"),
    ("rlm", "Knowledge"),
    ("sharing", "Knowledge"),
    # Admin & control
    ("admin", "Admin"),
    ("control-plane", "Control Plane"),
    ("policies", "Control Plane"),
    ("compliance", "Admin"),
    ("rbac", "Admin"),
    ("tenancy", "Admin"),
    ("reconciliation", "Admin"),
    ("services", "Admin"),
    ("partner", "Admin"),
    ("autonomous", "Admin"),
    ("devops", "Admin"),
    ("computer-use", "Admin"),
    ("backups", "Admin"),
    ("dr", "Admin"),
    ("users", "Admin"),
    # Auth & security
    ("auth", "Authentication"),
    ("oauth", "OAuth"),
    ("mfa", "MFA"),
    ("security", "Security"),
    ("privacy", "Security"),
    ("retention", "Retention"),
    # Audit
    ("audit-trails", "Audit"),
    ("audit", "Audit"),
    # Email & inbox
    ("email", "Email"),
    ("inbox", "Inbox"),
    ("gmail", "Email"),
    ("outlook", "Email"),
    # Financial
    ("accounting", "Accounting"),
    ("expenses", "Accounting"),
    ("invoices", "Accounting"),
    ("payments", "Accounting"),
    ("billing", "Costs"),
    ("costs", "Costs"),
    ("budgets", "Budgets"),
    ("receipts", "Gauntlet"),
    # Analytics & monitoring
    ("decision-analytics", "Analytics"),
    ("analytics", "Analytics"),
    ("dashboard", "Analytics"),
    ("endpoint-analytics", "Analytics"),
    ("evaluation", "Analytics"),
    ("features", "Analytics"),
    ("feedback", "Analytics"),
    ("metrics", "Monitoring"),
    ("monitoring", "Monitoring"),
    ("alerts", "Monitoring"),
    ("incidents", "Monitoring"),
    ("notifications", "Monitoring"),
    ("oncall", "Monitoring"),
    # Codebase & devops
    ("codebase", "Codebase"),
    ("repository", "Codebase"),
    ("github", "GitHub"),
    ("dependency", "Codebase"),
    # Auditing & red team
    ("auditing", "Auditing"),
    ("probes", "Auditing"),
    ("redteam", "Auditing"),
    # Threat & security findings
    ("cve", "Threat Intel"),
    ("threat", "Threat Intel"),
    ("findings", "Gauntlet"),
    ("finding-workflow", "Gauntlet"),
    # Documents
    ("documents", "Documents"),
    ("upload", "Documents"),
    ("cloud", "Documents"),
    ("legal", "Documents"),
    ("canvas", "Documents"),
    ("gallery", "Documents"),
    # Integrations & connectors
    ("integrations", "Integrations"),
    ("connectors", "Integrations"),
    ("external_integrations", "Integrations"),
    ("a2a", "A2A Protocol"),
    ("webhooks", "Webhooks"),
    ("crm", "Integrations"),
    ("ecommerce", "Integrations"),
    ("verticals", "Integrations"),
    ("support", "Integrations"),
    ("channels", "Integrations"),
    # Teams
    ("teams", "Teams"),
    # Gauntlet
    ("gauntlet", "Gauntlet"),
    # Verification
    ("verification", "Verification"),
    # Explainability
    ("explainability", "Explainability"),
    ("explain", "Explainability"),
    ("uncertainty", "Explainability"),
    # Advanced features
    ("nomic", "Nomic"),
    ("genesis", "Genesis"),
    ("evolution", "Evolution"),
    ("laboratory", "Laboratory"),
    ("tournaments", "Tournaments"),
    ("replays", "Replays"),
    ("critiques", "Critiques"),
    ("introspection", "Introspection"),
    ("plugins", "Plugins"),
    ("marketplace", "Plugins"),
    ("skills", "Plugins"),
    ("breakpoints", "Checkpoints"),
    ("checkpoints", "Checkpoints"),
    # Classification
    ("classify", "Classification"),
    ("classification", "Classification"),
    # Media & social
    ("chat", "Bots"),
    ("voice", "Media"),
    ("speech", "Media"),
    ("podcast", "Media"),
    ("youtube", "Media"),
    ("advertising", "Advertising"),
    ("social", "Social"),
    # Queue
    ("queue", "Queue"),
    ("scheduler", "Queue"),
    ("orchestration", "Workflows"),
    # Misc
    ("pulse", "Pulse"),
    ("gastown", "Gas Town"),
    ("workspace", "Workspace"),
    ("workspaces", "Workspace"),
    ("relationships", "Relationships"),
    ("devices", "Devices"),
    # Belief & provenance
    ("belief-network", "Belief"),
    ("provenance", "Belief"),
    # Routing rules & domain routing
    ("routing-rules", "Routing"),
    ("routing", "Routing"),
    ("team-selection", "Routing"),
    # SLOs & status pages
    ("slos", "Monitoring"),
    ("status", "System"),
    ("diagnostics", "System"),
    ("debug", "System"),
    ("circuit-breakers", "Monitoring"),
    # Evaluation
    ("evaluate", "Analytics"),
    # Usage & quotas
    ("usage", "Costs"),
    ("quotas", "Admin"),
    # Reviews
    ("reviews", "Debates"),
    # Transcription & media
    ("transcribe", "Media"),
    ("transcription", "Media"),
    # Bindings & personas
    ("bindings", "Control Plane"),
    ("personas", "Agents"),
    ("moments", "Insights"),
    # Verification (alternate prefix)
    ("verify", "Verification"),
    # Templates
    ("templates", "Workflow Templates"),
    # System
    ("openapi", "System"),
    ("postman", "System"),
    ("platform", "System"),
    ("docs", "System"),
    ("redoc", "System"),
    ("health", "System"),
    ("ready", "System"),
    ("system", "System"),
    ("modes", "System"),
    ("config", "System"),
    ("settings", "System"),
    # History & matches
    ("history", "Insights"),
    ("matches", "Debates"),
    ("match", "Debates"),
    # Gateway & onboarding
    ("gateway", "Gateway"),
    ("onboarding", "Onboarding"),
    # Sessions
    ("sessions", "Sessions"),
    ("session", "Sessions"),
    # Import/export
    ("import", "Documents"),
    ("export", "Documents"),
    # Sponsors & organizations
    ("sponsors", "Partners"),
    ("organizations", "Admin"),
    ("organization", "Admin"),
]

# Non-API paths that need tag inference (e.g. /healthz, /readyz, /audio)
_ROOT_PATH_TAGS: dict[str, str] = {
    "/healthz": "System",
    "/readyz": "System",
    "/readyz/dependencies": "System",
    "/status": "System",
    "/audio": "Media",
}


def _infer_tag_for_path(path: str) -> str:
    """Infer an appropriate OpenAPI tag from the URL path.

    Strips version prefixes and matches the remaining path against
    known prefix rules.  Returns ``"Undocumented"`` only when no rule
    matches.
    """
    # Check root paths first (non-/api/ paths)
    root_tag = _ROOT_PATH_TAGS.get(path)
    if root_tag:
        return root_tag

    stripped = re.sub(r"^/api/(v\d+/)?", "", path)
    stripped = re.sub(r"\{[^}]+\}", "", stripped).strip("/")

    # Handle file-like paths (e.g. openapi.json, postman.json)
    stripped = re.sub(r"\.\w+$", "", stripped)

    for prefix, tag in TAG_INFERENCE_RULES:
        if stripped == prefix or stripped.startswith(prefix + "/"):
            return tag
    return "Undocumented"


def _add_v1_aliases(paths: dict[str, Any]) -> dict[str, Any]:
    """Add /api/v1 aliases for non-versioned /api endpoints."""
    aliased: dict[str, Any] = {}
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    # Track existing normalized v1 paths to avoid operationId collisions when
    # only path parameter names differ (e.g. {id} vs {debate_id}).
    existing_v1_templates = {
        _normalize_template(path) for path in paths if path.startswith("/api/v1/")
    }
    for path, spec in paths.items():
        if path in aliased and (path.startswith("/api/v1/") or path.startswith("/api/v2/")):
            # Merge explicit v1/v2 spec into existing auto-generated alias
            # so methods from non-versioned paths are preserved.
            explicit = copy.deepcopy(spec)
            for method, operation in explicit.items():
                if method.lower() in methods:
                    aliased[path][method] = operation
                elif method not in aliased[path]:
                    aliased[path][method] = operation
        else:
            aliased[path] = copy.deepcopy(spec)
        if not path.startswith("/api/"):
            continue
        if path.startswith("/api/v1/") or path.startswith("/api/v2/"):
            continue
        if path in WIRED_REGISTRATION_NO_V1_ALIASES:
            continue
        v1_path = path.replace("/api/", "/api/v1/", 1)
        if v1_path not in aliased:
            alias_spec = copy.deepcopy(spec)
            if _normalize_template(v1_path) in existing_v1_templates:
                for method, operation in alias_spec.items():
                    if method.lower() in methods and isinstance(operation, dict):
                        operation.pop("operationId", None)
            aliased[v1_path] = alias_spec
        else:
            # Merge methods from non-versioned path into existing v1 path
            alias_spec = copy.deepcopy(spec)
            for method, operation in alias_spec.items():
                if method.lower() in methods and method not in aliased[v1_path]:
                    if isinstance(operation, dict):
                        operation.pop("operationId", None)
                    aliased[v1_path][method] = operation
    return aliased


def _mark_legacy_paths_deprecated(paths: dict[str, Any]) -> dict[str, Any]:
    """Mark non-versioned /api endpoints as deprecated."""
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    for path, spec in paths.items():
        if not path.startswith("/api/"):
            continue
        if path.startswith("/api/v1/") or path.startswith("/api/v2/"):
            continue
        for method, operation in spec.items():
            if method.lower() in methods and isinstance(operation, dict):
                operation.setdefault(
                    "deprecated",
                    True,
                )
                if not operation.get("x-preserve-legacy-operation-id"):
                    operation.pop("operationId", None)
    return paths


def _extract_route_path(route: Any) -> str:
    """Normalize handler route metadata into a path-like string."""
    if isinstance(route, tuple):
        for candidate in reversed(route):
            if hasattr(candidate, "pattern"):
                return str(candidate.pattern)
            if isinstance(candidate, str) and candidate.startswith("/"):
                return candidate
        for candidate in route:
            if isinstance(candidate, str):
                return candidate
        return ""
    if hasattr(route, "pattern"):
        return str(route.pattern)
    if isinstance(route, str):
        return route
    return ""


def _normalize_route(route: Any) -> str:
    # Strip HTTP method prefix if present (e.g. "POST /api/v1/..." -> "/api/v1/...")
    raw_route = _extract_route_path(route)
    if not raw_route:
        return ""
    parts = raw_route.split(" ", 1)
    path = parts[-1] if len(parts) > 1 and parts[0].isupper() else raw_route
    return path.rstrip("*").rstrip("/")


def _extract_route_method(route: Any) -> str | None:
    raw_route = _extract_route_path(route)
    if not raw_route:
        return None
    parts = raw_route.split(" ", 1)
    if len(parts) != 2 or not parts[0].isupper():
        return None
    method = parts[0].lower()
    if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
        return None
    return method


def _extract_path_params(path: str) -> list[str]:
    """Extract path parameter names from a path template.

    Args:
        path: URL path with {param} placeholders

    Returns:
        List of parameter names found in the path
    """
    return re.findall(r"\{([^}]+)\}", path)


def _ensure_path_parameters(paths: dict[str, Any]) -> dict[str, Any]:
    """Ensure all path parameters are defined in operations.

    For each path with {param} placeholders, verifies that the operation
    has corresponding parameter definitions. Adds missing parameters
    with sensible defaults.

    Args:
        paths: OpenAPI paths dictionary

    Returns:
        Updated paths dictionary with all path parameters defined
    """
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for path, path_spec in paths.items():
        path_params = _extract_path_params(path)
        if not path_params:
            continue

        # Handle duplicate parameter names in path (e.g., /api/{param}/foo/{param})
        # by making them unique: param, param_2, etc.
        seen_params: dict[str, int] = {}
        unique_params: list[str] = []
        for param in path_params:
            if param in seen_params:
                seen_params[param] += 1
                unique_params.append(f"{param}_{seen_params[param]}")
            else:
                seen_params[param] = 1
                unique_params.append(param)

        for method, operation in path_spec.items():
            if method.lower() not in methods:
                continue
            if not isinstance(operation, dict):
                continue

            # Get existing parameters
            existing_params = operation.get("parameters", [])
            existing_path_params = [
                p for p in existing_params if isinstance(p, dict) and p.get("in") == "path"
            ]
            non_path_params = [
                p for p in existing_params if not (isinstance(p, dict) and p.get("in") == "path")
            ]

            normalized_path_params: list[dict[str, Any]] = []
            for index, param_name in enumerate(unique_params):
                if index < len(existing_path_params):
                    param_def = dict(existing_path_params[index])
                    param_def["name"] = param_name
                    param_def["in"] = "path"
                    param_def["required"] = True
                else:
                    # Infer schema type from parameter name
                    base_name = param_name.split("_")[0] if "_" in param_name else param_name
                    if base_name.endswith("_id") or base_name == "id":
                        schema_type = "string"
                    elif base_name in ("page", "limit", "offset", "count", "token_id"):
                        schema_type = "integer"
                    else:
                        schema_type = "string"

                    param_def = {
                        "name": param_name,
                        "in": "path",
                        "required": True,
                        "schema": {"type": schema_type},
                        "description": f"Path parameter: {param_name}",
                    }
                normalized_path_params.append(param_def)

            operation["parameters"] = normalized_path_params + non_path_params

    return paths


def _pattern_prefix(pattern: str) -> str:
    cleaned = pattern.lstrip("^")
    escaped = False
    for idx, ch in enumerate(cleaned):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in ".^$*+?{}[]()|":
            return cleaned[:idx].rstrip("/")
    return cleaned.rstrip("/")


def _collect_handler_paths() -> set[str]:
    from aragora.server.handlers import ALL_HANDLERS

    handled_paths: set[str] = set()
    handler_classes: list[Any] = (
        list(ALL_HANDLERS) if isinstance(ALL_HANDLERS, (list, tuple, set)) else []  # type: ignore[arg-type]
    )
    for handler_cls in handler_classes:
        for attr_name in ("ROUTES", "ROUTE_PREFIXES"):
            routes: Any = getattr(handler_cls, attr_name, None)
            if routes is not None:
                for route in routes:
                    normalized = _normalize_route(route)
                    if normalized:
                        handled_paths.add(normalized)
        patterns = getattr(handler_cls, "ROUTE_PATTERNS", None)
        if patterns:
            for pattern in patterns:
                # Handle (compiled_regex, name) tuples
                pat = (
                    pattern[0].pattern
                    if isinstance(pattern, tuple)
                    else (pattern.pattern if hasattr(pattern, "pattern") else pattern)
                )
                prefix = _pattern_prefix(pat)
                if prefix:
                    handled_paths.add(prefix)
    return handled_paths


def _is_path_handled(
    spec_path: str,
    base_path: str,
    legacy_path: str,
    legacy_base: str,
    handled_paths: set[str],
    handled_legacy_paths: set[str],
) -> bool:
    for handled in handled_paths:
        if spec_path.startswith(handled) or handled.startswith(base_path):
            return True
    for handled in handled_legacy_paths:
        if legacy_path.startswith(handled) or handled.startswith(legacy_base):
            return True
    return False


def _is_autogenerated_operation(operation: Any) -> bool:
    return isinstance(operation, dict) and operation.get("x-autogenerated") is True


def _is_fully_autogenerated_spec(spec: dict[str, Any]) -> bool:
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    saw_operation = False
    for method, operation in spec.items():
        if method.lower() not in methods or not isinstance(operation, dict):
            continue
        saw_operation = True
        if not _is_autogenerated_operation(operation):
            return False
    return saw_operation


def _is_source_backed_registration(path: str, spec: dict[str, Any]) -> bool:
    return path in WIRED_REGISTRATION_ENDPOINTS and any(
        isinstance(operation, dict) and operation.get("x-wired-registration") is True
        for operation in spec.values()
    )


def _filter_unhandled_paths(paths: dict[str, Any]) -> dict[str, Any]:
    try:
        handled_paths = _collect_handler_paths()
    except (ImportError, ValueError, RuntimeError, AttributeError) as exc:
        logger.warning("Failed to collect handler paths for OpenAPI filtering: %s", exc)
        return paths
    handled_legacy_paths = {strip_version_prefix(path) for path in handled_paths}
    filtered: dict[str, Any] = {}
    for spec_path, spec in paths.items():
        if _is_source_backed_registration(spec_path, spec):
            filtered[spec_path] = spec
            continue
        # Keep hand-authored contract entries even when handler discovery lags.
        # The filter is meant to suppress unbacked autogenerated placeholders.
        if not _is_fully_autogenerated_spec(spec):
            filtered[spec_path] = spec
            continue
        normalized = re.sub(r"\{[^}]+\}", "*", spec_path)
        base_path = normalized.split("*")[0].rstrip("/")
        legacy_path = strip_version_prefix(spec_path)
        legacy_base = re.sub(r"\{[^}]+\}", "*", legacy_path).split("*")[0].rstrip("/")
        has_curated_operation = any(
            isinstance(operation, dict) and not _is_autogenerated_operation(operation)
            for operation in spec.values()
        )
        if (
            _is_path_handled(
                spec_path,
                base_path,
                legacy_path,
                legacy_base,
                handled_paths,
                handled_legacy_paths,
            )
            or has_curated_operation
        ):
            filtered[spec_path] = spec
    return filtered


def _operation_from_api_metadata(attr_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    summary = metadata.get("summary") or attr_name.replace("_", " ").title()
    path = metadata.get("path")
    tags = metadata.get("tags")
    if isinstance(tags, list):
        tags = [tag for tag in tags if isinstance(tag, str) and tag]
    else:
        tags = []
    if not tags and isinstance(path, str) and path.startswith("/"):
        tags = [_infer_tag_for_path(path)]

    operation: dict[str, Any] = {
        "summary": summary,
        "tags": tags,
        "operationId": metadata.get("operation_id") or attr_name,
        "responses": {
            "200": {
                "description": "Success",
                "content": {
                    "application/json": {
                        "schema": {"type": "object"},
                    }
                },
            }
        },
    }

    description = metadata.get("description")
    if isinstance(description, str) and description:
        operation["description"] = description

    if metadata.get("auth_required", True):
        operation["security"] = [{"bearerAuth": []}]

    return operation


def _collect_api_metadata_paths() -> dict[str, dict[str, Any]]:
    from aragora.server.handlers import ALL_HANDLERS

    valid_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    paths: dict[str, dict[str, Any]] = {}
    handler_classes: list[Any] = (
        list(ALL_HANDLERS) if isinstance(ALL_HANDLERS, (list, tuple, set)) else []  # type: ignore[arg-type]
    )

    for handler_cls in handler_classes:
        for attr_name, attr_value in vars(handler_cls).items():
            target = attr_value
            if isinstance(attr_value, (staticmethod, classmethod)):
                target = attr_value.__func__
            metadata = getattr(target, "_api_metadata", None)
            if not isinstance(metadata, dict):
                continue
            path = metadata.get("path")
            method = metadata.get("method", "GET")
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            if not isinstance(method, str):
                continue
            method_key = method.lower()
            if method_key not in valid_methods:
                continue
            paths.setdefault(path, {}).setdefault(
                method_key,
                _operation_from_api_metadata(attr_name, metadata),
            )

    return paths


def _apply_handler_api_metadata(paths: dict[str, Any]) -> dict[str, Any]:
    try:
        metadata_paths = _collect_api_metadata_paths()
    except (ImportError, ValueError, RuntimeError, AttributeError) as exc:
        logger.warning("Failed to collect handler API metadata for OpenAPI: %s", exc)
        return paths

    for path, methods in metadata_paths.items():
        if not path.startswith("/api/v1/decision-analytics/"):
            continue
        path_spec = paths.setdefault(path, {})
        for method, operation in methods.items():
            current = path_spec.get(method)
            if current is None or _is_autogenerated_operation(current):
                path_spec[method] = copy.deepcopy(operation)
    return paths


def _apply_auth_manifest(paths: dict[str, Any]) -> dict[str, Any]:
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    for path, path_spec in paths.items():
        if not isinstance(path_spec, dict):
            continue
        for method, operation in path_spec.items():
            method_key = method.lower()
            if method_key not in methods or not isinstance(operation, dict):
                continue
            requirement = get_requirement(path, method_key)
            if requirement is None:
                continue
            if requirement.level == AuthLevel.PUBLIC:
                operation.pop("security", None)
                continue
            if "security" not in operation:
                operation["security"] = [{scheme: [] for scheme in requirement.openapi_security}]
    return paths


def _apply_route_contract_overrides(paths: dict[str, Any]) -> dict[str, Any]:
    for path, method_overrides in ROUTE_CONTRACT_OVERRIDES.items():
        path_spec = paths.get(path)
        if not isinstance(path_spec, dict):
            continue
        for method, override in method_overrides.items():
            operation = path_spec.get(method)
            if not isinstance(operation, dict):
                continue
            operation.update(copy.deepcopy(override))
            operation.pop("x-autogenerated", None)
    return paths


def _drop_decision_analytics_legacy_placeholders(paths: dict[str, Any]) -> dict[str, Any]:
    """Remove legacy decision-analytics placeholders when versioned metadata exists."""
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    versioned_operations: set[tuple[str, str]] = set()

    for path, spec in paths.items():
        if not (path.startswith("/api/v1/") or path.startswith("/api/v2/")):
            continue
        if not isinstance(spec, dict):
            continue
        legacy_path = strip_version_prefix(path)
        for method, operation in spec.items():
            method_key = method.lower()
            if method_key in methods and isinstance(operation, dict):
                if not _is_autogenerated_operation(operation):
                    versioned_operations.add((legacy_path, method_key))

    filtered: dict[str, Any] = {}
    for path, spec in paths.items():
        if (
            path.startswith("/api/")
            and not path.startswith(("/api/v1/", "/api/v2/"))
            and path.startswith("/api/decision-analytics/")
            and isinstance(spec, dict)
            and _is_fully_autogenerated_spec(spec)
        ):
            legacy_path = strip_version_prefix(path)
            operation_methods = [
                method.lower()
                for method in spec
                if method.lower() in methods and isinstance(spec.get(method), dict)
            ]
            if operation_methods and all(
                (legacy_path, method) in versioned_operations for method in operation_methods
            ):
                continue
        filtered[path] = spec

    return filtered


def _drop_orchestration_v1_status_placeholder(paths: dict[str, Any]) -> dict[str, Any]:
    """Drop the stray v1 orchestration status placeholder when the real dynamic path exists."""
    placeholder_path = "/api/v1/orchestration/status"
    dynamic_path = "/api/v1/orchestration/status/{request_id}"
    placeholder_spec = paths.get(placeholder_path)
    dynamic_spec = paths.get(dynamic_path)
    if not isinstance(placeholder_spec, dict) or not isinstance(dynamic_spec, dict):
        return paths

    placeholder_post = placeholder_spec.get("post")
    dynamic_get = dynamic_spec.get("get")
    if not _is_autogenerated_operation(placeholder_post):
        return paths
    if not (isinstance(dynamic_get, dict) and not _is_autogenerated_operation(dynamic_get)):
        return paths

    paths.pop(placeholder_path, None)
    return paths


#: Autogenerated placeholder paths whose operations are not actually served by the
#: default dispatcher. They exist only because ``_autogenerate_missing_paths`` expands
#: bare handler ROUTES prefixes into standalone spec entries. Dropping them keeps the
#: published contract truthful; genuinely served sub-paths keep their own entries.
_UNSERVED_BARE_PLACEHOLDER_PATHS = (
    "/api/review-queue",
    "/api/v1/review-queue",
    "/api/slos",
    "/api/v1/slos",
    "/api/v1/chat/knowledge/channel",
    "/api/v1/debates/public",
    "/api/v1/knowledge/mound/graph",
    "/api/v1/memory",
    "/api/v1/memory/tier",
    "/api/v1/shared",
)


def _drop_unserved_bare_placeholders(paths: dict[str, Any]) -> dict[str, Any]:
    """Drop autogenerated bare-route placeholders that no dispatcher actually serves."""
    for placeholder_path in _UNSERVED_BARE_PLACEHOLDER_PATHS:
        spec = paths.get(placeholder_path)
        if isinstance(spec, dict) and _is_fully_autogenerated_spec(spec):
            paths.pop(placeholder_path, None)
    return paths


def _normalize_template(path: str) -> str:
    normalized = re.sub(r"\{[^}]+\}", "*", path)
    normalized = normalized.replace("/*", "/*").rstrip("/")
    return normalized


def _normalize_legacy_template(path: str) -> str:
    """Normalize a path with version prefix stripped."""
    return _normalize_template(strip_version_prefix(path))


def _route_to_template(route: str) -> str:
    cleaned = route.rstrip("/")
    cleaned = cleaned.rstrip("*").rstrip("/")
    # Replace each * with a unique {param}, {param_2}, {param_3}, etc.
    count = 0
    parts = cleaned.split("*")
    result_parts = [parts[0]]
    for part in parts[1:]:
        count += 1
        param_name = "param" if count == 1 else f"param_{count}"
        result_parts.append(f"{{{param_name}}}")
        result_parts.append(part)
    return "".join(result_parts)


def _align_legacy_paths_with_versioned(paths: dict[str, Any]) -> dict[str, Any]:
    """Ensure legacy /api paths mirror method sets from versioned paths."""
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

    versioned_methods: dict[str, tuple[tuple[int, int], set[str], dict[str, Any]]] = {}
    for path, spec in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        key = _normalize_legacy_template(path)
        method_set = {method for method in spec if method.lower() in methods}
        has_autogen = any(
            isinstance(operation, dict) and operation.get("x-autogenerated") is True
            for operation in spec.values()
        )
        score = (
            0 if has_autogen else 1,
            -path.count("{param}"),
        )
        current = versioned_methods.get(key)
        if current is None or score > current[0]:
            versioned_methods[key] = (score, method_set, spec)

    for path, spec in list(paths.items()):
        if not path.startswith("/api/"):
            continue
        if path.startswith("/api/v1/") or path.startswith("/api/v2/"):
            continue
        key = _normalize_legacy_template(path)
        versioned_entry = versioned_methods.get(key)
        if not versioned_entry:
            continue
        _, v1_methods, versioned_spec = versioned_entry
        legacy_methods = {method for method in spec if method.lower() in methods}
        if legacy_methods == v1_methods:
            continue

        updated: dict[str, Any] = {
            key: value for key, value in spec.items() if key.lower() not in methods
        }
        for method in sorted(v1_methods):
            operation = spec.get(method)
            if isinstance(operation, dict):
                updated[method] = operation
                continue
            versioned_operation = versioned_spec.get(method)
            if isinstance(versioned_operation, dict):
                updated[method] = copy.deepcopy(versioned_operation)
            else:
                updated[method] = {
                    "summary": "Autogenerated placeholder (spec pending)",
                    "tags": [_infer_tag_for_path(path)],
                    "responses": {"200": {"description": "OK"}},
                    "x-autogenerated": True,
                    "x-method-inferred": False,
                }
        paths[path] = updated

    return paths


def _infer_methods(handler_cls: type) -> tuple[list[str], bool]:
    methods = set()
    for method in ("get", "post", "put", "patch", "delete", "head"):
        if f"handle_{method}" in handler_cls.__dict__:
            methods.add(method)
    if methods:
        return sorted(methods), True
    if "handle" not in handler_cls.__dict__:
        return ["get"], False
    try:
        handle_method = getattr(handler_cls, "handle", None)
        if handle_method is None:
            return ["get"], False
        source = inspect.getsource(handle_method)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name):
                if node.left.id != "method":
                    continue
                if not node.comparators:
                    continue
                comp = node.comparators[0]
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    methods.add(comp.value.lower())
                elif isinstance(comp, (ast.Tuple, ast.List)):
                    for elt in comp.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            methods.add(elt.value.lower())
            if isinstance(node, ast.Compare) and node.ops:
                if isinstance(node.ops[0], (ast.In, ast.NotIn)):
                    if isinstance(node.left, ast.Name) and node.left.id == "method":
                        if node.comparators:
                            comp = node.comparators[0]
                            if isinstance(comp, (ast.Tuple, ast.List)):
                                for elt in comp.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        methods.add(elt.value.lower())
    except (OSError, TypeError, SyntaxError):
        pass
    if methods:
        return sorted(methods), True
    return ["get"], False


_HTTP_VERBS_UPPER = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})

# Last path segments that read state; evidence-free routes ending in one of
# these guess GET rather than a mutating verb from the handler's union.
_READ_SEGMENTS = frozenset(
    {
        "status",
        "results",
        "history",
        "stats",
        "statistics",
        "stream",
        "health",
        "summary",
        "progress",
        "analytics",
        "metrics",
    }
)


def _dispatch_verbs_by_route(handler_cls: type) -> dict[str, set[str]]:
    """Attribute verbs to routes by scanning the handler's dispatch methods.

    A verb counts for a route only when the route path appears as a string
    literal in that verb's ``handle_<verb>`` source (or in a same-class helper
    the method calls, one level deep). Trailing-slash literals are prefix
    idioms (``path.startswith("/api/x/")``) and never attribute the bare
    route. The generic ``handle`` method is the GET path in the handler
    convention, so its literals count as GET evidence — unless it dispatches
    on a ``method`` value, in which case only conditions testing both the
    route and the method attribute (exactly the verbs they test). This
    recovers genuinely served operations on handlers whose class-wide verb
    union is too ambiguous to fan out.
    """

    def _method_source(name: str) -> str | None:
        fn = handler_cls.__dict__.get(name)
        if fn is None:
            return None
        try:
            return inspect.getsource(fn)
        except (OSError, TypeError):
            return None

    def _parse(source: str) -> ast.AST | None:
        try:
            return ast.parse(textwrap.dedent(source))
        except SyntaxError:
            return None

    def _path_constants(node: ast.AST) -> set[str]:
        # Any route-shaped literal in the verb's dispatch source counts:
        # equality comparisons, membership tests, dispatch-table keys, and
        # @api_endpoint(path=...) declarations all appear as constants.
        # Trailing-slash literals are startswith() prefixes and are excluded
        # (they only prove sub-routes are served, not the bare route).
        return {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.startswith("/")
            and not child.value.endswith("/")
        }

    verbs_by_path: dict[str, set[str]] = {}

    def _add(path: str, verb: str) -> None:
        # Key by the version-stripped form: dispatch code frequently
        # normalizes /api/v1/... to /api/... before comparing.
        key = re.sub(r"^/api/v\d+/", "/api/", path)
        verbs_by_path.setdefault(key, set()).add(verb)

    def _paths_with_helpers(source: str) -> set[str]:
        tree = _parse(source)
        paths = _path_constants(tree) if tree is not None else set()
        for helper in set(re.findall(r"self\.(_\w+)\(", source)):
            helper_source = _method_source(helper)
            if helper_source:
                helper_tree = _parse(helper_source)
                if helper_tree is not None:
                    paths |= _path_constants(helper_tree)
        return paths

    for verb in ("get", "post", "put", "patch", "delete", "head"):
        source = _method_source(f"handle_{verb}")
        if source is None:
            continue
        for path in _paths_with_helpers(source):
            _add(path, verb)

    generic_source = _method_source("handle")
    if generic_source is not None:
        tree = _parse(generic_source)
        if tree is not None:
            compares_method = any(
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name)
                and node.left.id == "method"
                for node in ast.walk(tree)
            )
            if not compares_method:
                for path in _paths_with_helpers(generic_source):
                    _add(path, "get")
            else:
                for node in ast.walk(tree):
                    if not isinstance(node, ast.If):
                        continue
                    test_paths = _path_constants(node.test)
                    test_verbs = {
                        child.value
                        for child in ast.walk(node.test)
                        if isinstance(child, ast.Constant)
                        and isinstance(child.value, str)
                        and child.value in _HTTP_VERBS_UPPER
                    }
                    if test_paths and test_verbs:
                        for path in test_paths:
                            for test_verb in test_verbs:
                                _add(path, test_verb.lower())
    return verbs_by_path


def _collect_route_map_methods(handler_cls: type) -> dict[str, tuple[list[str], bool]]:
    route_map = getattr(handler_cls, "_ROUTE_MAP", None)
    if not isinstance(route_map, dict):
        return {}

    valid_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    methods_by_route: dict[str, set[str]] = {}
    for key in route_map:
        if not isinstance(key, str) or " " not in key:
            continue
        method, _ = key.split(" ", 1)
        method = method.lower()
        if method not in valid_methods:
            continue

        normalized_route = _normalize_route(key)
        if not normalized_route:
            continue
        template = _route_to_template(normalized_route)
        if template and template.startswith("/"):
            methods_by_route.setdefault(template, set()).add(method)

    return {route: (sorted(methods), True) for route, methods in methods_by_route.items()}


def _collect_declared_route_methods(routes: Any) -> dict[str, tuple[list[str], bool]]:
    methods_by_route: dict[str, set[str]] = {}
    valid_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    if isinstance(routes, dict):
        for route, declared_methods in routes.items():
            if not isinstance(declared_methods, (list, tuple, set)):
                continue
            normalized_route = _normalize_route(route)
            if not normalized_route:
                continue
            template = _route_to_template(normalized_route)
            if not template or not template.startswith("/"):
                continue
            for method in declared_methods:
                if isinstance(method, str):
                    normalized_method = method.lower()
                    if normalized_method in valid_methods:
                        methods_by_route.setdefault(template, set()).add(normalized_method)
    elif isinstance(routes, (list, tuple, set)):
        for route in routes:
            method = _extract_route_method(route)
            if method is None:
                continue
            normalized_route = _normalize_route(route)
            if not normalized_route:
                continue
            template = _route_to_template(normalized_route)
            if template and template.startswith("/"):
                methods_by_route.setdefault(template, set()).add(method)
    else:
        return {}

    return {route: (sorted(methods), False) for route, methods in methods_by_route.items()}


def _merge_route_methods(
    *method_maps: dict[str, tuple[list[str], bool]],
) -> dict[str, tuple[list[str], bool]]:
    merged: dict[str, tuple[list[str], bool]] = {}
    for method_map in method_maps:
        for route, (methods, inferred) in method_map.items():
            current = merged.get(route)
            if current is None:
                merged[route] = (list(methods), inferred)
                continue
            merged_methods = sorted(set(current[0]) | set(methods))
            merged[route] = (merged_methods, current[1] and inferred)
    return merged


def _collect_autogenerated_paths() -> dict[str, tuple[list[str], bool]]:
    from aragora.server.handlers import ALL_HANDLERS

    paths: dict[str, tuple[list[str], bool]] = {}
    handler_classes: list[Any] = (
        list(ALL_HANDLERS) if isinstance(ALL_HANDLERS, (list, tuple, set)) else []  # type: ignore[arg-type]
    )
    for handler_cls in handler_classes:
        handler_methods, inferred = _infer_methods(handler_cls)
        route_map_methods = _collect_route_map_methods(handler_cls)
        normalized_route_map_templates = {
            _normalize_template(template) for template in route_map_methods
        }
        explicit_route_methods = _merge_route_methods(
            _collect_declared_route_methods(getattr(handler_cls, "ROUTES", None)),
            route_map_methods,
            _collect_declared_route_methods(getattr(handler_cls, "DYNAMIC_ROUTES", None)),
        )
        route_templates: list[str] = []
        for attr_name in ("ROUTES", "DYNAMIC_ROUTES", "ROUTE_PREFIXES"):
            routes: Any = getattr(handler_cls, attr_name, None)
            if not routes:
                continue
            routes_list: list[Any] = list(routes)
            for route in routes_list:
                normalized_route = _normalize_route(route)
                if not normalized_route:
                    continue
                if attr_name == "ROUTE_PREFIXES":
                    template = normalized_route.rstrip("/")
                    if not template:
                        continue
                    template = f"{template}/{{param}}"
                    if _normalize_template(template) in normalized_route_map_templates:
                        continue
                else:
                    template = _route_to_template(normalized_route)
                if template and template.startswith("/"):
                    route_templates.append(template)
        pattern_templates: list[str] = []
        patterns = getattr(handler_cls, "ROUTE_PATTERNS", None)
        if patterns:
            for pattern in patterns:
                # Handle (compiled_regex, name) tuples
                pat = (
                    pattern[0].pattern
                    if isinstance(pattern, tuple)
                    else (pattern.pattern if hasattr(pattern, "pattern") else pattern)
                )
                prefix = _pattern_prefix(pat)
                if prefix:
                    pattern_templates.append(f"{prefix}/{{param}}")
        # The class verb set is the union across every route the handler
        # dispatches, so it is only attributable when exactly one route lacks
        # explicit per-route methods (or when the set holds a single verb —
        # the only verb the handler can serve anywhere). Applying a multi-verb
        # union more broadly advertises phantom operations (e.g. DELETE on
        # every route of a handler that only deletes under one prefix). For
        # ambiguous routes, per-verb dispatch analysis recovers the verbs
        # whose handle_<verb> actually references the route; routes with no
        # dispatch evidence get a single conservative verb chosen inside the
        # union, since a verb outside it is a guaranteed phantom.
        explicit_by_norm = {
            _normalize_template(template): methods
            for template, methods in explicit_route_methods.items()
        }
        generic_templates = {
            template
            for template in route_templates + pattern_templates
            if _normalize_template(template) not in explicit_by_norm
        }
        # NOTE: a single-verb handle_<verb> set alongside a generic handle()
        # is still fanned out (the GET side of such handlers stays
        # under-documented) — narrowing that idiom reshuffles hundreds of
        # operations and is deferred; see PR #9365 review round 3.
        ambiguous = len(generic_templates) > 1 and len(handler_methods) > 1
        if ambiguous:
            dispatch_verbs = _dispatch_verbs_by_route(handler_cls)
            if "get" in handler_methods:
                fallback: tuple[list[str], bool] = (["get"], True)
            elif "post" in handler_methods:
                fallback = (["post"], True)
            else:
                fallback = (handler_methods[:1], True)
        else:
            dispatch_verbs = {}
            fallback = (handler_methods, inferred)

        def _methods_for(template: str) -> tuple[list[str], bool]:
            explicit = explicit_by_norm.get(_normalize_template(template))
            if explicit is not None:
                return explicit
            key = re.sub(r"^/api/v\d+/", "/api/", template).rstrip("/") or template
            dispatched = dispatch_verbs.get(key)
            if dispatched:
                return (sorted(dispatched), True)
            # Evidence-free routes with a read-shaped last segment guess GET
            # (a mutating verb on a status/read sub-route is a phantom write);
            # only applies when the handler has a GET path to serve them.
            if (
                ambiguous
                and ("get" in handler_methods or "handle" in handler_cls.__dict__)
                and key.rsplit("/", 1)[-1] in _READ_SEGMENTS
            ):
                return (["get"], True)
            return fallback

        for template in route_templates:
            paths.setdefault(template, _methods_for(template))
        for template in pattern_templates:
            paths.setdefault(template, _methods_for(template))
        for template, methods in explicit_route_methods.items():
            paths.setdefault(template, methods)
    return paths


def _autogenerate_missing_paths(paths: dict[str, Any]) -> dict[str, Any]:
    existing_norm = {_normalize_template(path) for path in paths}
    try:
        auto_paths = _collect_autogenerated_paths()
    except (ImportError, ValueError, RuntimeError, AttributeError) as exc:
        logger.warning("Failed to autogenerate OpenAPI paths: %s", exc)
        return paths
    for template, (methods, inferred) in auto_paths.items():
        normalized = _normalize_template(template)
        if normalized in existing_norm:
            continue
        tag = _infer_tag_for_path(template)
        spec: dict[str, Any] = {}
        for method in methods:
            # Generate a basic response schema based on method type
            if method == "get":
                response_schema = {
                    "type": "object",
                    "properties": {
                        "data": {"type": "object", "description": "Response data"},
                        "success": {"type": "boolean"},
                    },
                }
            elif method == "post":
                response_schema = {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Created resource ID"},
                        "success": {"type": "boolean"},
                    },
                }
            elif method == "delete":
                response_schema = {
                    "type": "object",
                    "properties": {
                        "deleted": {"type": "boolean"},
                    },
                }
            else:
                response_schema = {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                    },
                }
            spec[method] = {
                "summary": "Autogenerated placeholder (spec pending)",
                "tags": [tag],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {
                            "application/json": {
                                "schema": response_schema,
                            }
                        },
                    }
                },
                "x-autogenerated": True,
                "x-method-inferred": inferred,
            }
        paths[template] = spec
    return paths


def _apply_stability_markers(paths: dict[str, Any]) -> dict[str, Any]:
    from aragora.server.openapi.stability import resolve_stability

    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    for path, spec in paths.items():
        if not isinstance(spec, dict):
            continue
        for method, operation in spec.items():
            if method.lower() not in methods or not isinstance(operation, dict):
                continue
            operation["x-aragora-stability"] = resolve_stability(method, path, operation)
    return paths


def _describe_missing_tag(tag: str) -> str:
    """Provide a fallback description for used tags missing from the static catalog."""
    normalized = tag.replace("_", " ").strip()
    if normalized.startswith("Bots - "):
        return f"{normalized} endpoints"
    return f"{normalized} operations"


def _complete_tag_catalog(
    paths: dict[str, Any], base_tags: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Ensure every used operation tag is present in the schema tag catalog."""
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    catalog = list(base_tags)
    defined = {tag["name"] for tag in catalog if "name" in tag}

    for path_spec in paths.values():
        if not isinstance(path_spec, dict):
            continue
        for method, operation in path_spec.items():
            if method.lower() not in methods or not isinstance(operation, dict):
                continue
            for tag in operation.get("tags", []):
                if not isinstance(tag, str) or not tag or tag in defined:
                    continue
                catalog.append({"name": tag, "description": _describe_missing_tag(tag)})
                defined.add(tag)
    return catalog


def _fix_duplicate_path_params(paths: dict[str, Any]) -> dict[str, Any]:
    """Rename duplicate {param} placeholders in path templates to be unique.

    OpenAPI requires that each path parameter placeholder be unique within a
    path template.  For example, ``/api/{param}/claims/{param}/support`` is
    invalid; this function rewrites it to
    ``/api/{param}/claims/{param_2}/support`` and updates the corresponding
    parameter definitions in all operations.
    """
    fixed: dict[str, Any] = {}
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    for path, spec in paths.items():
        params = re.findall(r"\{([^}]+)\}", path)
        if len(params) == len(set(params)):
            # No duplicates
            fixed[path] = spec
            continue

        # Build a mapping: occurrence index -> new unique name
        seen: dict[str, int] = {}
        new_path = path
        rename_map: dict[str, str] = {}  # old_placeholder -> new_placeholder
        for param in params:
            count = seen.get(param, 0) + 1
            seen[param] = count
            if count > 1:
                new_name = f"{param}_{count}"
                # Replace only the Nth occurrence of {param} in the path
                old_placeholder = f"{{{param}}}"
                new_placeholder = f"{{{new_name}}}"
                # Find and replace the correct occurrence
                idx = -1
                for _ in range(count):
                    idx = new_path.index(old_placeholder, idx + 1)
                new_path = new_path[:idx] + new_placeholder + new_path[idx + len(old_placeholder) :]
                rename_map[f"param_{count}" if param == "param" else new_name] = new_name

        # Update parameter definitions in operations
        new_spec = copy.deepcopy(spec)
        for method_key, operation in new_spec.items():
            if method_key.lower() not in methods or not isinstance(operation, dict):
                continue
            op_params = operation.get("parameters", [])
            # Update any param definitions that reference renamed parameters
            for p in op_params:
                if isinstance(p, dict) and p.get("in") == "path":
                    old_name = p.get("name", "")
                    # Check if this old name needs renaming
                    if old_name in seen and seen[old_name] > 1:
                        # Already handled by _ensure_path_parameters later
                        pass

        fixed[new_path] = new_spec

    return fixed


def _deduplicate_ambiguous_paths(paths: dict[str, Any]) -> dict[str, Any]:
    """Remove paths that differ only in parameter names, keeping the canonical one.

    When two paths normalize to the same template (e.g. /api/v1/agent/{name}/introspect
    and /api/v1/agent/{param}/introspect), keep the one with descriptive parameter names
    (not {param}) and drop the autogenerated duplicate.
    """
    # Group paths by their normalized form
    groups: dict[str, list[str]] = {}
    for path in paths:
        norm = _normalize_template(path)
        groups.setdefault(norm, []).append(path)

    result: dict[str, Any] = {}
    for norm, group in groups.items():
        if len(group) == 1:
            result[group[0]] = paths[group[0]]
            continue

        # Pick the best path: prefer non-autogenerated, then named params over {param}
        def _score(p: str) -> tuple[int, int, int]:
            spec = paths[p]
            # Prefer paths where operations are NOT autogenerated
            has_autogen = any(
                isinstance(op, dict) and op.get("x-autogenerated") is True for op in spec.values()
            )
            # Prefer descriptive parameter names over generic {param}
            param_count = p.count("{param}")
            # Prefer versioned paths (/api/v1/) over legacy (/api/)
            is_versioned = 1 if "/api/v1/" in p or "/api/v2/" in p else 0
            return (0 if has_autogen else 1, -param_count, is_versioned)

        best = max(group, key=_score)
        result[best] = paths[best]

    return result


def generate_openapi_schema() -> dict[str, Any]:
    """Generate complete OpenAPI 3.1 schema."""
    paths = _mark_legacy_paths_deprecated(_add_v1_aliases(ALL_ENDPOINTS))
    paths = _filter_unhandled_paths(paths)
    paths = _autogenerate_missing_paths(paths)
    paths = _apply_handler_api_metadata(paths)
    paths = _apply_auth_manifest(paths)
    paths = _apply_route_contract_overrides(paths)
    paths = _align_legacy_paths_with_versioned(paths)
    paths = _mark_legacy_paths_deprecated(_add_v1_aliases(paths))
    paths = _drop_decision_analytics_legacy_placeholders(paths)
    paths = _drop_orchestration_v1_status_placeholder(paths)
    paths = _drop_unserved_bare_placeholders(paths)
    paths = _deduplicate_ambiguous_paths(paths)
    paths = _fix_duplicate_path_params(paths)  # Fix duplicate {param} in path templates
    paths = _ensure_path_parameters(paths)  # Auto-inject missing path parameters
    paths = _apply_stability_markers(paths)
    tags = _complete_tag_catalog(
        paths,
        [
            {"name": "System", "description": "Health checks and system status"},
            {"name": "Admin", "description": "Administrative controls and governance"},
            {"name": "Authentication", "description": "Authentication and session management"},
            {"name": "MFA", "description": "Multi-factor authentication flows"},
            {"name": "Security", "description": "Security configuration and encryption"},
            {"name": "Agents", "description": "Agent management, profiles, and rankings"},
            {"name": "A2A Protocol", "description": "Agent-to-agent protocol endpoints"},
            {"name": "Debates", "description": "Debate operations, history, and export"},
            {"name": "Deliberations", "description": "Deliberation workflows and outcomes"},
            {"name": "Analytics", "description": "Analysis and aggregated statistics"},
            {"name": "Insights", "description": "Position flips, moments, and patterns"},
            {"name": "Consensus", "description": "Consensus memory and settled questions"},
            {"name": "Relationships", "description": "Agent relationship tracking"},
            {"name": "Memory", "description": "Continuum memory management"},
            {"name": "Belief", "description": "Belief networks and claim analysis"},
            {"name": "Pulse", "description": "Trending topics and suggestions"},
            {"name": "Monitoring", "description": "Metrics and observability"},
            {"name": "Verification", "description": "Formal verification and proofs"},
            {"name": "Auditing", "description": "Capability probes and red teaming"},
            {"name": "Documents", "description": "Document upload and export"},
            {"name": "Codebase", "description": "Codebase security scans and metrics"},
            {"name": "GitHub", "description": "GitHub PR review automation"},
            {"name": "Inbox", "description": "Shared inbox and routing rules"},
            {"name": "Email", "description": "Email ingestion and operations"},
            {"name": "Costs", "description": "Cost visibility and budgeting"},
            {"name": "Budgets", "description": "Budget management, limits, and enforcement"},
            {"name": "Teams", "description": "Microsoft Teams bot and integration endpoints"},
            {"name": "Bots", "description": "Bot integrations and channels"},
            {"name": "Bots - Discord", "description": "Discord bot endpoints"},
            {"name": "Bots - Google Chat", "description": "Google Chat bot endpoints"},
            {"name": "Bots - Telegram", "description": "Telegram bot endpoints"},
            {"name": "Bots - WhatsApp", "description": "WhatsApp bot endpoints"},
            {"name": "Bots - Zoom", "description": "Zoom bot endpoints"},
            {
                "name": "Pipeline",
                "description": "Idea-to-execution pipeline (Ideas, Goals, Actions, Orchestration)",
            },
            {"name": "Alexa", "description": "Alexa voice assistant endpoints"},
            {"name": "Google Home", "description": "Google Home voice assistant endpoints"},
            {"name": "Accounting", "description": "Accounting and ERP integrations"},
            {"name": "Advertising", "description": "Advertising operations"},
            {"name": "Devices", "description": "Device management"},
            {"name": "Integrations", "description": "Third-party integrations"},
            {"name": "Media", "description": "Audio/video and podcast"},
            {"name": "Social", "description": "Social media publishing"},
            {"name": "Control Plane", "description": "Agent orchestration and task routing"},
            {"name": "Decisions", "description": "Unified decision routing results"},
            {"name": "Plugins", "description": "Plugin management and execution"},
            {"name": "Laboratory", "description": "Emergent trait analysis"},
            {"name": "Tournaments", "description": "Tournament management"},
            {"name": "Genesis", "description": "Agent genesis and lineage"},
            {"name": "Evolution", "description": "Agent evolution tracking"},
            {"name": "Replays", "description": "Debate replay management"},
            {"name": "Learning", "description": "Meta-learning statistics"},
            {"name": "Critiques", "description": "Critique patterns and reputation"},
            {"name": "Routing", "description": "Agent selection and team routing"},
            {"name": "Introspection", "description": "Agent self-awareness queries"},
            {"name": "Workflows", "description": "Workflow management and execution"},
            {"name": "Classification", "description": "Question and content classification"},
            {"name": "Retention", "description": "Data retention policies"},
            {"name": "OAuth", "description": "OAuth authentication flows"},
            {"name": "Audit", "description": "Audit logging and compliance"},
            {"name": "Queue", "description": "Queue and async job management"},
            {"name": "Webhooks", "description": "Webhook management and delivery"},
            {"name": "Nomic", "description": "Nomic loop monitoring and control"},
            {"name": "Gas Town", "description": "Gas Town governance endpoints"},
            {"name": "Knowledge", "description": "Knowledge operations and retrieval"},
            {"name": "Workspace", "description": "Workspace management"},
            {"name": "Workflow Templates", "description": "Pre-built workflow templates"},
            {"name": "Patterns", "description": "Workflow pattern management"},
            {"name": "Gauntlet", "description": "Decision receipts and risk heatmaps"},
            {"name": "Explainability", "description": "Decision explanations and provenance"},
            {"name": "Cross-Pollination", "description": "Cross-debate knowledge sharing"},
            {"name": "Knowledge Mound", "description": "Knowledge extraction and retrieval"},
            {"name": "Checkpoints", "description": "Debate checkpoint management"},
            {"name": "Threat Intel", "description": "Threat intelligence lookups"},
            {"name": "SME", "description": "SME workspace, success, and integration management"},
            {"name": "Undocumented", "description": "Autogenerated placeholders pending full spec"},
            {"name": "Agent", "description": "Individual agent configuration and profiles"},
            {"name": "Audio", "description": "Audio processing and podcast generation"},
            {"name": "Backups", "description": "Backup management and disaster recovery"},
            {"name": "Compliance", "description": "Compliance monitoring and reporting"},
            {"name": "Computer Use", "description": "Computer use and browser automation"},
            {"name": "Connectors", "description": "Platform connectors and data sources"},
            {"name": "Gateway", "description": "Secure gateway and proxy endpoints"},
            {"name": "Keys", "description": "API key management"},
            {"name": "Leaderboard", "description": "Agent leaderboard and rankings"},
            {"name": "ML", "description": "Machine learning model management"},
            {"name": "Notifications", "description": "Notification delivery and preferences"},
            {"name": "Onboarding", "description": "User onboarding flows"},
            {"name": "Payments", "description": "Payment processing and subscriptions"},
            {"name": "Personas", "description": "Agent persona management"},
            {"name": "Policies", "description": "Policy management and enforcement"},
            {"name": "Privacy", "description": "Privacy controls and data protection"},
            {"name": "Probes", "description": "Agent capability probes"},
            {"name": "RLM", "description": "Recursive language model context"},
            {"name": "Reviews", "description": "Code and content reviews"},
            {"name": "SCIM", "description": "SCIM 2.0 provisioning endpoints"},
            {"name": "Skills", "description": "Skill registry and marketplace"},
            {"name": "Training", "description": "Agent training and fine-tuning"},
            {"name": "Transcription", "description": "Audio transcription services"},
            {"name": "Uncertainty", "description": "Uncertainty quantification"},
            {"name": "Users", "description": "User management and profiles"},
            {"name": "Verticals", "description": "Industry vertical configurations"},
            {"name": "Wizard", "description": "Setup wizard flows"},
            {"name": "API Keys", "description": "API key lifecycle management"},
            {"name": "Analysis", "description": "Data analysis and reporting"},
            {"name": "Batch", "description": "Batch processing operations"},
            {"name": "Bindings", "description": "Resource bindings and links"},
            {"name": "Blockchain", "description": "Blockchain and ERC-8004 endpoints"},
            {"name": "Categorization", "description": "Content categorization"},
            {"name": "Chat", "description": "Chat messaging and conversations"},
            {"name": "Config", "description": "Configuration management"},
            {"name": "Context", "description": "Context management and injection"},
            {"name": "Dashboard", "description": "Dashboard views and widgets"},
            {"name": "Evidence", "description": "Evidence collection and management"},
            {"name": "Export", "description": "Data export operations"},
            {"name": "Feedback", "description": "Feedback collection and processing"},
            {"name": "Fork", "description": "Debate forking and branching"},
            {"name": "Gmail", "description": "Gmail integration endpoints"},
            {"name": "Graph Debates", "description": "Graph-based debate orchestration"},
            {"name": "Health", "description": "Health and readiness checks"},
            {"name": "Knowledge Base", "description": "Knowledge base management"},
            {"name": "Matrix Debates", "description": "Matrix debate orchestration"},
            {"name": "Password", "description": "Password management"},
            {"name": "Prioritization", "description": "Task and item prioritization"},
            {"name": "Receipts", "description": "Decision receipt management"},
            {"name": "Reputation", "description": "Agent reputation tracking"},
            {"name": "Search", "description": "Search across resources"},
            {"name": "Sessions", "description": "Session management"},
            {"name": "Sync", "description": "Data synchronization"},
            {"name": "Validation", "description": "Input validation endpoints"},
            {"name": "VIP", "description": "VIP tier features"},
            {"name": "Workspaces", "description": "Workspace management and settings"},
        ],
    )
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Aragora API",
            "description": "Control plane for multi-agent vetted decisionmaking across org knowledge and channels. "
            "Orchestrate 15+ AI models to debate your organization's knowledge and deliver "
            "defensible decisions with full audit trails.",
            "version": API_VERSION,
            "contact": {"name": "Aragora Team"},
            "license": {"name": "MIT"},
        },
        "servers": [
            {"url": "http://localhost:8080", "description": "Development server"},
            {"url": "https://api.aragora.ai", "description": "Production server"},
        ],
        "tags": tags,
        "paths": paths,
        "components": {
            "schemas": COMMON_SCHEMAS,
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API token authentication. Set via ARAGORA_API_TOKEN environment variable.",
                },
            },
        },
        "security": [],  # Global security is optional, per-endpoint security defined above
    }


def get_openapi_json() -> str:
    """Get OpenAPI schema as JSON string."""
    return json.dumps(generate_openapi_schema(), indent=2)


def get_openapi_yaml() -> str:
    """Get OpenAPI schema as YAML string."""
    try:
        import yaml

        result: str = yaml.dump(
            generate_openapi_schema(), default_flow_style=False, sort_keys=False
        )
        return result
    except ImportError:
        # Fallback to JSON if PyYAML not installed
        return get_openapi_json()


def handle_openapi_request(format: str = "json") -> tuple[str, str]:
    """Handle request for OpenAPI spec.

    Returns:
        Tuple of (content, content_type)
    """
    if format == "yaml":
        return get_openapi_yaml(), "application/yaml"
    return get_openapi_json(), "application/json"


def save_openapi_schema(output_path: str = "docs/api/openapi.json") -> tuple[str, int]:
    """Save complete OpenAPI schema to file.

    Returns:
        Tuple of (file_path, endpoint_count)
    """
    schema = generate_openapi_schema()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w") as f:
        json.dump(schema, f, indent=2)

    endpoint_count = sum(len(methods) for methods in schema["paths"].values())
    return str(output.absolute()), endpoint_count


def get_endpoint_count() -> int:
    """Get total number of documented endpoints."""
    schema = generate_openapi_schema()
    return sum(len(methods) for methods in schema["paths"].values())


# =============================================================================
# Postman Collection Export (moved to postman_generator.py)
# =============================================================================

# Re-export for backwards compatibility
from aragora.server.postman_generator import (  # noqa: F401
    generate_postman_collection,
    get_postman_json,
    handle_postman_request,
    save_postman_collection,
)
