#!/usr/bin/env python3
"""
Generate OpenAPI 3.1.0 spec for Aragora.

Three-tier strategy:
  1. Canonical registry  -- import aragora.server.openapi.generate_openapi_schema()
  2. Runtime decorator    -- import handler modules, read _endpoint_registry
  3. AST fallback         -- parse handler .py files for @api_endpoint(...) calls

By default the script tries the canonical registry first, merges in any
decorator-registered endpoints that are not already in the canonical spec,
and finally falls back to AST parsing when imports fail (e.g. missing deps).

Usage:
    python scripts/generate_openapi.py
    python scripts/generate_openapi.py --output docs/api/openapi.yaml --format yaml
    python scripts/generate_openapi.py --ast-only          # skip runtime imports
    python scripts/generate_openapi.py --legacy-handlers    # old handler introspection
    python scripts/generate_openapi.py --stdout --format json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = PROJECT_ROOT / "aragora" / "server" / "handlers"

# Ensure project root is on sys.path for imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _get_version() -> str:
    """Read package version from aragora/__version__.py without importing."""
    version_file = PROJECT_ROOT / "aragora" / "__version__.py"
    try:
        tree = ast.parse(version_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__version__":
                        if isinstance(node.value, ast.JoinedStr):
                            # f-string -- fall through to exec
                            break
                        if isinstance(node.value, ast.Constant):
                            return str(node.value.value)
        # Fallback: exec the file in a sandbox
        ns: dict[str, Any] = {}
        exec(compile(version_file.read_text(), version_file, "exec"), ns)  # noqa: S102
        return str(ns.get("__version__", "0.0.0"))
    except Exception:
        return "0.0.0"


API_VERSION = _get_version()


# ============================================================================
# AST-based @api_endpoint extractor
# ============================================================================


def _eval_literal(node: ast.expr) -> Any:
    """Safely evaluate an AST node to a Python literal.

    Handles constants, lists, dicts, and unary operators (e.g., True/False).
    Returns None for anything that cannot be statically resolved.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        items = [_eval_literal(elt) for elt in node.elts]
        if any(v is _UNRESOLVABLE for v in items):
            return _UNRESOLVABLE
        return items
    if isinstance(node, ast.Tuple):
        items = [_eval_literal(elt) for elt in node.elts]
        if any(v is _UNRESOLVABLE for v in items):
            return _UNRESOLVABLE
        return tuple(items)
    if isinstance(node, ast.Dict):
        keys = [_eval_literal(k) if k is not None else None for k in node.keys]
        values = [_eval_literal(v) for v in node.values]
        if any(v is _UNRESOLVABLE for v in keys) or any(v is _UNRESOLVABLE for v in values):
            return _UNRESOLVABLE
        return dict(zip(keys, values))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = _eval_literal(node.operand)
        if operand is not _UNRESOLVABLE:
            return -operand
    if isinstance(node, ast.Name):
        # True / False / None are ast.Constant in 3.8+, but be safe
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        if node.id == "None":
            return None
    return _UNRESOLVABLE


# Sentinel for values that cannot be resolved statically
_UNRESOLVABLE = object()


def _extract_decorator_kwargs(call_node: ast.Call) -> dict[str, Any]:
    """Extract keyword arguments from an @api_endpoint(...) call node."""
    kwargs: dict[str, Any] = {}
    for kw in call_node.keywords:
        if kw.arg is None:
            continue  # **kwargs -- skip
        value = _eval_literal(kw.value)
        if value is not _UNRESOLVABLE:
            kwargs[kw.arg] = value
    return kwargs


def _is_api_endpoint_decorator(node: ast.expr) -> ast.Call | None:
    """Return the Call node if this is an @api_endpoint(...) decorator."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "api_endpoint":
        return node
    if isinstance(func, ast.Attribute) and func.attr == "api_endpoint":
        return node
    return None


def _ast_extract_endpoints_from_file(filepath: Path) -> list[dict[str, Any]]:
    """Parse a single Python file and extract @api_endpoint metadata via AST."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    endpoints: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        # Look for decorated functions and methods
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = _is_api_endpoint_decorator(decorator)
            if call is None:
                continue
            kwargs = _extract_decorator_kwargs(call)
            path = kwargs.get("path")
            if not path or not isinstance(path, str):
                continue
            method = kwargs.get("method", "GET")
            if not isinstance(method, str):
                continue
            summary = kwargs.get("summary", "")
            if not isinstance(summary, str):
                summary = ""
            tags = kwargs.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            description = kwargs.get("description", "")
            if not isinstance(description, str):
                description = ""
            parameters = kwargs.get("parameters")
            if not isinstance(parameters, list):
                parameters = []
            request_body = kwargs.get("request_body")
            if not isinstance(request_body, dict):
                request_body = None
            responses = kwargs.get("responses")
            if not isinstance(responses, dict):
                responses = {}
            auth_required = kwargs.get("auth_required", True)
            deprecated = kwargs.get("deprecated", False)
            operation_id = kwargs.get("operation_id")
            if not isinstance(operation_id, str):
                operation_id = node.name

            # Use a cleaned docstring fallback so AST output matches runtime imports.
            if not description:
                description = ast.get_docstring(node, clean=True) or ""

            if not summary:
                summary = node.name.replace("_", " ").title()

            endpoints.append(
                {
                    "path": path,
                    "method": method.upper(),
                    "summary": summary,
                    "tags": tags,
                    "description": description,
                    "parameters": parameters,
                    "request_body": request_body,
                    "responses": responses,
                    "auth_required": bool(auth_required),
                    "deprecated": bool(deprecated),
                    "operation_id": operation_id,
                    "source_file": str(filepath.relative_to(PROJECT_ROOT)),
                }
            )

    return endpoints


def ast_scan_handlers(handlers_dir: Path | None = None) -> list[dict[str, Any]]:
    """Scan all handler .py files under handlers_dir using AST parsing.

    Returns a flat list of endpoint metadata dicts.
    """
    root = handlers_dir or HANDLERS_DIR
    if not root.is_dir():
        print(f"Warning: handlers directory not found: {root}", file=sys.stderr)
        return []

    all_endpoints: list[dict[str, Any]] = []
    for py_file in sorted(root.rglob("*.py")):
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue
        endpoints = _ast_extract_endpoints_from_file(py_file)
        all_endpoints.extend(endpoints)

    return all_endpoints


# ============================================================================
# Runtime decorator introspection
# ============================================================================


def _runtime_collect_decorator_endpoints() -> list[dict[str, Any]]:
    """Import handler modules and collect endpoints from the global registry."""
    try:
        from aragora.server.handlers.openapi_decorator import get_registered_endpoints

        # Force-import handler modules to trigger decorator registration
        _force_import_handlers()

        endpoints = get_registered_endpoints()
        result: list[dict[str, Any]] = []
        for ep in endpoints:
            result.append(
                {
                    "path": ep.path,
                    "method": ep.method,
                    "summary": ep.summary,
                    "tags": ep.tags,
                    "description": ep.description,
                    "parameters": ep.parameters,
                    "request_body": ep.request_body,
                    "responses": ep.responses,
                    "auth_required": bool(ep.security),
                    "deprecated": ep.deprecated,
                    "operation_id": ep.operation_id,
                    "source": "runtime_decorator",
                }
            )
        return result
    except Exception as exc:
        print(f"Warning: runtime decorator collection failed: {exc}", file=sys.stderr)
        return []


def _force_import_handlers() -> None:
    """Best-effort import of handler modules to trigger decorator registration."""
    import importlib

    if not HANDLERS_DIR.is_dir():
        return
    for py_file in sorted(HANDLERS_DIR.rglob("*.py")):
        if py_file.name.startswith("__"):
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        module_name = str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
        try:
            importlib.import_module(module_name)
        except Exception:
            pass  # Best-effort; AST fallback covers failures


# ============================================================================
# Endpoint list -> OpenAPI paths conversion
# ============================================================================


def _extract_path_params(path: str) -> list[dict[str, Any]]:
    """Extract {param} placeholders from a path and return parameter defs."""
    params: list[dict[str, Any]] = []
    for match in re.finditer(r"\{(\w+)\}", path):
        name = match.group(1)
        params.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": f"Path parameter: {name}",
            }
        )
    return params


def endpoints_to_openapi_paths(
    endpoints: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Convert a flat list of endpoint dicts to an OpenAPI paths dict."""
    paths: dict[str, dict[str, Any]] = {}

    for ep in endpoints:
        path = ep["path"]
        method = ep["method"].lower()

        if path not in paths:
            paths[path] = {}
        if method in paths[path]:
            continue  # First-seen wins (canonical > runtime > AST)

        operation: dict[str, Any] = {
            "summary": ep.get("summary", ""),
            "tags": ep.get("tags", []),
        }

        description = ep.get("description", "")
        if description:
            operation["description"] = description

        op_id = ep.get("operation_id")
        if op_id:
            operation["operationId"] = op_id

        # Parameters: merge explicit + auto-detected path params
        explicit_params = ep.get("parameters", [])
        auto_path_params = _extract_path_params(path)
        explicit_names = {p.get("name") for p in explicit_params if isinstance(p, dict)}
        merged_params = list(explicit_params)
        for auto_p in auto_path_params:
            if auto_p["name"] not in explicit_names:
                merged_params.append(auto_p)
        if merged_params:
            operation["parameters"] = merged_params

        # Request body
        req_body = ep.get("request_body")
        if req_body and isinstance(req_body, dict):
            operation["requestBody"] = req_body
        elif method in ("post", "put", "patch") and not req_body:
            operation["requestBody"] = {
                "content": {"application/json": {"schema": {"type": "object"}}},
            }

        # Responses
        responses = ep.get("responses", {})
        if responses and isinstance(responses, dict):
            operation["responses"] = responses
        else:
            operation["responses"] = {
                "200": {
                    "description": "Success",
                    "content": {
                        "application/json": {"schema": {"type": "object"}},
                    },
                },
            }

        # Security
        if ep.get("auth_required", True):
            operation["security"] = [{"bearerAuth": []}]

        if ep.get("deprecated", False):
            operation["deprecated"] = True

        paths[path][method] = operation

    return paths


# ============================================================================
# Full schema assembly
# ============================================================================


def _collect_tags(paths: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Aggregate unique tags from all operations, return sorted tag objects."""
    tag_set: set[str] = set()
    for path_spec in paths.values():
        for method_spec in path_spec.values():
            if isinstance(method_spec, dict):
                for tag in method_spec.get("tags", []):
                    tag_set.add(tag)
    return [{"name": t, "description": f"{t} operations"} for t in sorted(tag_set)]


def build_openapi_schema(
    paths: dict[str, dict[str, Any]],
    *,
    version: str | None = None,
) -> dict[str, Any]:
    """Assemble the complete OpenAPI 3.1.0 document."""
    sorted_paths = dict(sorted(paths.items()))
    tags = _collect_tags(sorted_paths)

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Aragora API",
            "description": (
                "Control plane for multi-agent vetted decisionmaking across "
                "organizational knowledge and channels. Orchestrates 15+ AI "
                "models to debate your organization's knowledge and deliver "
                "defensible decisions with full audit trails."
            ),
            "version": version or API_VERSION,
            "contact": {"name": "Aragora Team"},
            "license": {"name": "MIT", "identifier": "MIT"},
        },
        "servers": [
            {"url": "http://localhost:8080", "description": "Development server"},
            {"url": "https://api.aragora.ai", "description": "Production server"},
        ],
        "tags": tags,
        "paths": sorted_paths,
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"},
                        "code": {"type": "string"},
                        "trace_id": {"type": "string"},
                    },
                    "required": ["error"],
                },
            },
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "API token authentication. Set via ARAGORA_API_TOKEN environment variable."
                    ),
                },
            },
        },
    }


# ============================================================================
# Legacy handler introspection (preserved for --legacy-handlers flag)
# ============================================================================


def _legacy_generate_openapi_schema() -> dict[str, Any]:
    """Generate spec via old handler ROUTES introspection (backward compat)."""
    import inspect

    handlers: list[tuple[str, Any]] = []
    try:
        import aragora.server.handlers as handlers_module

        all_exports = getattr(handlers_module, "__all__", dir(handlers_module))
        for name in all_exports:
            if name.endswith("Handler") and name != "BaseHandler":
                try:
                    cls = getattr(handlers_module, name, None)
                    if cls is not None and hasattr(cls, "ROUTES"):
                        handlers.append((name, cls))
                except Exception:
                    pass
    except ImportError:
        pass

    paths: dict[str, Any] = {}
    tags: dict[str, str] = {}

    tag_map = {
        "System": "System",
        "Debates": "Debates",
        "Agents": "Agents",
        "Pulse": "Pulse",
        "Analytics": "Analytics",
        "Consensus": "Consensus",
        "Memory": "Memory",
        "Gauntlet": "Gauntlet",
    }

    for handler_name, handler_cls in handlers:
        tag_key = handler_name.replace("Handler", "")
        tag = tag_map.get(tag_key, tag_key)
        handler_doc = inspect.getdoc(handler_cls)
        if handler_doc and tag not in tags:
            tags[tag] = handler_doc.split("\n")[0]

        handler_routes = getattr(handler_cls, "ROUTES", [])
        if isinstance(handler_routes, dict):
            handler_routes = list(handler_routes.keys())

        for route in handler_routes:
            if route not in paths:
                paths[route] = {}
            paths[route]["get"] = {
                "summary": f"GET {route}",
                "tags": [tag],
                "responses": {"200": {"description": "Success"}},
            }

    sorted_paths = dict(sorted(paths.items()))
    tag_list = [{"name": t, "description": d or f"{t} operations"} for t, d in sorted(tags.items())]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Aragora API",
            "description": "Auto-generated from handler ROUTES (legacy mode).",
            "version": API_VERSION,
            "contact": {"name": "Aragora Team"},
            "license": {"name": "MIT"},
        },
        "servers": [{"url": "http://localhost:8080", "description": "Development server"}],
        "tags": tag_list,
        "paths": sorted_paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API token authentication",
                },
            },
        },
    }


# ============================================================================
# Main generation pipeline
# ============================================================================


def generate_schema(
    *,
    ast_only: bool = False,
    legacy_handlers: bool = False,
    include_runtime: bool = True,
) -> dict[str, Any]:
    """Run the multi-tier generation pipeline and return the OpenAPI schema."""
    if legacy_handlers:
        print("Generating OpenAPI spec from handler ROUTES (legacy)...", file=sys.stderr)
        schema = _legacy_generate_openapi_schema()
        schema["paths"] = _filter_internal_paths(schema["paths"])
        return schema

    if ast_only:
        print("Generating OpenAPI spec via AST parsing only...", file=sys.stderr)
        endpoints = ast_scan_handlers()
        paths = _filter_internal_paths(endpoints_to_openapi_paths(endpoints))
        return build_openapi_schema(paths)

    # --- Tier 1: canonical registry ---
    canonical_paths: dict[str, dict[str, Any]] = {}
    canonical_ok = False
    try:
        from aragora.server.openapi import generate_openapi_schema as canonical_generate

        canonical_schema = canonical_generate()
        canonical_paths = canonical_schema.get("paths", {})
        canonical_ok = True
        print(
            f"Tier 1 (canonical registry): {_count_operations(canonical_paths)} operations",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"Tier 1 (canonical registry) failed: {exc}", file=sys.stderr)

    # --- Tier 2: runtime decorator registry ---
    runtime_endpoints: list[dict[str, Any]] = []
    if include_runtime and not ast_only:
        runtime_endpoints = _runtime_collect_decorator_endpoints()
        print(
            f"Tier 2 (runtime decorators): {len(runtime_endpoints)} endpoints",
            file=sys.stderr,
        )

    # --- Tier 3: AST fallback ---
    ast_endpoints = ast_scan_handlers()
    print(
        f"Tier 3 (AST parsing): {len(ast_endpoints)} @api_endpoint calls found",
        file=sys.stderr,
    )

    # --- Merge ---
    # Start with canonical as the base, then layer on decorator and AST endpoints
    # for paths/methods not already present. Autogenerated placeholders are
    # intentionally weaker than decorator metadata, even when they came from the
    # canonical route list.
    merged_paths = dict(canonical_paths)  # shallow copy of top level

    # Merge runtime decorator endpoints
    if runtime_endpoints:
        decorator_paths = endpoints_to_openapi_paths(runtime_endpoints)
        _merge_paths_prefer_metadata(merged_paths, decorator_paths)

    # Merge AST endpoints (lowest priority)
    if ast_endpoints:
        ast_paths = endpoints_to_openapi_paths(ast_endpoints)
        _merge_paths_prefer_metadata(merged_paths, ast_paths)

    # --- Tier 4: handler ROUTES supplement ---
    # Handlers registered in HANDLER_REGISTRY serve every path in their ROUTES
    # (and method-specific *_ROUTES) even when no canonical/decorator entry
    # documents it. Emit explicit autogenerated placeholders for those so the
    # published contract covers everything the server actually routes.
    if include_runtime:
        supplement = _collect_handler_routes_supplement(merged_paths)
        if supplement:
            print(
                f"Tier 4 (handler ROUTES supplement): {len(supplement)} paths",
                file=sys.stderr,
            )
            _merge_supplement(merged_paths, supplement)

    # Deduplicate paths that differ only by parameter names (e.g.
    # /api/v1/agent/{name}/introspect vs /api/v1/agent/{param}/introspect).
    # Keep the path with descriptive parameter names over generic {param}.
    merged_paths = _deduplicate_ambiguous_paths(merged_paths)

    # Apply the internal-route policy to the FINAL merged path set, not just
    # the Tier-4 supplement. Tier-1 (canonical registry), Tier-2 (decorators)
    # and Tier-3 (AST) all surface internal families (control-plane, SME,
    # emergency admin, ...) that must never publish into the public spec —
    # and the route-coverage gate excludes internal prefixes from both sides
    # of its comparison, so a leak here would be permanently invisible to it.
    merged_paths = _filter_internal_paths(merged_paths)

    if canonical_ok:
        # Rebuild using canonical schema structure but with merged paths
        canonical_schema["paths"] = dict(sorted(merged_paths.items()))
        # Ensure tags reflect any new additions
        existing_tag_names = {t["name"] for t in canonical_schema.get("tags", [])}
        for tag_obj in _collect_tags(merged_paths):
            if tag_obj["name"] not in existing_tag_names:
                canonical_schema.setdefault("tags", []).append(tag_obj)
                existing_tag_names.add(tag_obj["name"])
        return canonical_schema
    else:
        return build_openapi_schema(merged_paths)


def _is_autogenerated_operation(operation: Any) -> bool:
    return isinstance(operation, dict) and operation.get("x-autogenerated") is True


def _merge_paths_prefer_metadata(
    merged_paths: dict[str, dict[str, Any]],
    incoming_paths: dict[str, dict[str, Any]],
) -> None:
    """Merge incoming paths, replacing selected placeholders with metadata."""
    replace_autogenerated_prefixes = ("/api/v1/decision-analytics/",)
    for path, methods in incoming_paths.items():
        if path not in merged_paths:
            merged_paths[path] = methods
            continue

        can_replace_autogenerated = path.startswith(replace_autogenerated_prefixes)
        for method, spec in methods.items():
            current = merged_paths[path].get(method)
            if (
                isinstance(current, dict)
                and current.get("x-wired-registration") is True
                and not _is_autogenerated_operation(spec)
            ):
                metadata = {key: spec[key] for key in ("summary", "description") if spec.get(key)}
                current.update(metadata)
                legacy_path = path.replace("/api/v1/", "/api/", 1)
                legacy = merged_paths.get(legacy_path, {}).get(method)
                if isinstance(legacy, dict) and legacy.get("x-wired-registration") is True:
                    legacy.update(metadata)
                continue
            if current is None or (
                can_replace_autogenerated and not _is_autogenerated_operation(spec)
            ):
                merged_paths[path][method] = spec


# ============================================================================
# Tier 4: handler ROUTES supplement
# ============================================================================

# Trailing path segments that imply an action endpoint (POST) when the HTTP
# method is not declared via *_ROUTES.
_ACTION_SEGMENTS = frozenset(
    {
        "execute",
        "run",
        "trigger",
        "classify",
        "enforce",
        "validate",
        "improve",
        "drill",
        "query",
        "dedup",
        "connect",
        "disconnect",
        "callback",
        "webhook",
        "mailgun",
        "import",
        "merge",
        "approve",
        "reject",
        "restore",
        "sync",
        "retry",
        "cancel",
    }
)

_ROUTE_METHOD_PREFIXES = ("GET ", "POST ", "PUT ", "PATCH ", "DELETE ", "HEAD ", "OPTIONS ")


def _load_internal_route_prefixes() -> tuple[str, ...]:
    """Load the internal-route policy, failing CLOSED when it is unusable.

    Without the policy, internal route families (control-plane, SME,
    emergency admin, ...) would silently publish into the public spec.

    Policy prefixes are exact family roots, version-scoped: comparison keys
    normalize unversioned ``/api/`` to ``/api/v1/``, so a ``/api/v1/...``
    prefix also covers the unversioned alias — but NOT other versions or
    non-``/api/`` forms. E.g. ``/api/v1/sso/`` is internal while the
    browser-facing ``/auth/sso/*`` flow and the SDK's ``/api/v2/sso/*``
    aliases stay public by design. Every entry must be ``/api/``-rooted;
    anything else is a policy error (fail closed, never silently ignored).
    """
    prefixes_file = PROJECT_ROOT / "scripts" / "baselines" / "internal_route_prefixes.json"
    try:
        data = json.loads(prefixes_file.read_text())
        prefixes_raw = data.get("prefixes")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise SystemExit(
            f"Error: cannot load internal route policy {prefixes_file}: {exc}. "
            "Refusing to generate without it — internal route families would "
            "be published into the public spec."
        ) from exc
    if not isinstance(prefixes_raw, list):
        raise SystemExit(
            f"Error: internal route policy {prefixes_file} must contain a 'prefixes' list."
        )
    invalid = [p for p in prefixes_raw if not (isinstance(p, str) and p.startswith("/api/"))]
    if invalid:
        raise SystemExit(
            f"Error: internal route policy {prefixes_file} has non-'/api/' prefixes: "
            f"{invalid}. Comparison keys are '/api/'-rooted, so these entries could "
            "never match and would silently fail to exclude anything."
        )
    internal_prefixes: tuple[str, ...] = tuple(prefixes_raw)
    if not internal_prefixes:
        raise SystemExit(
            f"Error: internal route policy {prefixes_file} contains no valid '/api/' prefixes."
        )
    return internal_prefixes


def _is_internal_route(comparison_key: str, internal_prefixes: tuple[str, ...]) -> bool:
    """Whether a normalized comparison key falls in an internal route family.

    Matching semantics deliberately mirror validate_openapi_routes.py
    (exact family root, or under it with the slash intact) so the generator
    excludes exactly the set the route-coverage gate excludes.
    """
    for prefix in internal_prefixes:
        base = prefix.rstrip("/")
        if comparison_key == base or comparison_key.startswith(base + "/"):
            return True
    return False


def _filter_internal_paths(paths: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Drop internal route families from a final spec path set.

    Applied to the merged output of every tier (canonical registry, runtime
    decorators, AST scan, handler ROUTES supplement) immediately before the
    spec is built: internal routes must be excluded from the public spec no
    matter which tier surfaced them. The route-coverage gate excludes these
    prefixes from both sides of its comparison, so it can never flag a leak
    itself — this filter is the single enforcement point.
    """
    internal_prefixes = _load_internal_route_prefixes()
    filtered = {
        path: methods
        for path, methods in paths.items()
        if not _is_internal_route(_normalize_for_comparison(path), internal_prefixes)
    }
    dropped = len(paths) - len(filtered)
    if dropped:
        print(
            f"Internal-route policy: excluded {dropped} internal path(s) from the public spec",
            file=sys.stderr,
        )
    return filtered


def _normalize_for_comparison(route: str) -> str:
    """Collapse a route to a version-normalized, param-generic comparison key.

    Mirrors scripts/validate_openapi_routes.py normalize_route so that the
    supplement adds exactly the paths the route-coverage gate reports missing.
    """
    route = route.rstrip("/")
    if route.startswith("/api/") and not route.startswith("/api/v"):
        route = route.replace("/api/", "/api/v1/", 1)
    route = re.sub(r"/\*(/|$)", r"/{param}\1", route)
    return re.sub(r"/\{[^}]+\}", "/{param}", route)


def _wildcard_param_name(prev_segment: str, used: set[str]) -> str:
    """Derive a descriptive path-parameter name from the preceding segment."""
    base = re.sub(r"[^a-zA-Z0-9]+", "_", prev_segment).strip("_").lower() or "item"
    if base.endswith("s") and not base.endswith("ss") and len(base) > 3:
        base = base[:-1]
    name = f"{base}_id"
    counter = 2
    while name in used:
        name = f"{base}_id{counter}"
        counter += 1
    used.add(name)
    return name


def _route_to_spec_path(route: str) -> str:
    """Convert a handler ROUTES entry to a publishable OpenAPI path."""
    for prefix in _ROUTE_METHOD_PREFIXES:
        if route.startswith(prefix):
            route = route[len(prefix) :]
            break
    route = route.rstrip("/")
    # Dispatch strips version prefixes (see handler_registry/core.py), so the
    # canonical published form of an unversioned /api/ route is /api/v1/.
    if route.startswith("/api/") and not route.startswith("/api/v"):
        route = route.replace("/api/", "/api/v1/", 1)

    segments = route.split("/")
    used_names: set[str] = set()
    for i, seg in enumerate(segments):
        if seg == "*":
            prev = segments[i - 1] if i > 0 else "item"
            segments[i] = "{" + _wildcard_param_name(prev, used_names) + "}"
    return "/".join(segments)


_HANDLER_VERB_METHODS = (
    ("handle", "get"),
    ("handle_get", "get"),
    ("handle_post", "post"),
    ("handle_put", "put"),
    ("handle_patch", "patch"),
    ("handle_delete", "delete"),
)


def _implemented_handler_verbs(handler_class: Any) -> list[str]:
    """Derive the HTTP verb set a handler actually implements.

    The dispatch layer (handler_registry) tries the method-specific handler
    first (POST -> handle_post(), DELETE -> handle_delete(), ...) and falls
    through to the generic handle() when it returns None, while GET goes
    straight to handle(). So overridden handle_* methods are definitive verb
    evidence, and an overridden handle() adds GET. No-op defaults inherited
    from the shared base handler do not count as implementations. Returns an
    empty list when nothing can be derived (the caller falls back to the
    path-segment heuristic).

    Note: a handler that overrides ONLY generic handle() may still serve any
    verb through the dispatch fall-through (dispatcher-style handlers branch
    on the request method inside handle()), so callers must not treat a bare
    ["get"] result as proof the route is GET-only.
    """
    base_funcs: dict[str, Any] = {}
    try:
        from aragora.server.handlers.base import BaseHandler

        for attr, _verb in _HANDLER_VERB_METHODS:
            base = getattr(BaseHandler, attr, None)
            if base is not None:
                base_funcs[attr] = getattr(base, "__func__", base)
    except Exception:  # noqa: BLE001 - fall back to presence-based detection
        pass

    verbs: list[str] = []
    for attr, verb in _HANDLER_VERB_METHODS:
        try:
            method = getattr(handler_class, attr, None)
        except Exception:  # noqa: BLE001 - exotic descriptors; skip attribute
            continue
        if not callable(method):
            continue
        func = getattr(method, "__func__", method)
        if attr in base_funcs and func is base_funcs[attr]:
            continue  # inherited no-op default, not an implementation
        if verb not in verbs:
            verbs.append(verb)
    return verbs


def _explicit_route_verbs(handler_class: Any) -> dict[str, set[str]]:
    """Verb map declared by a handler's ``routes()`` method, keyed by path.

    Some dispatch-based handlers (e.g. SSOHandler) declare their served verbs
    only via ``routes()`` returning ``(METHOD, path, handler_name)`` tuples —
    their static ROUTES list is method-less, so verb inference alone would
    document POST operations as GET. ``routes()`` is invoked on a bare
    instance (``object.__new__``) so handler ``__init__`` side effects can't
    fire during spec generation; any failure degrades to verb inference.
    Keys are normalized comparison keys (see _normalize_for_comparison).
    """
    routes_fn = getattr(handler_class, "routes", None)
    if not callable(routes_fn):
        return {}
    try:
        declared = routes_fn(object.__new__(handler_class))
    except Exception:  # noqa: BLE001 - optional protocol; fall back to inference
        return {}
    if not isinstance(declared, (list, tuple)):
        return {}
    out: dict[str, set[str]] = {}
    for item in declared:
        if not (isinstance(item, (list, tuple)) and len(item) >= 2):
            continue
        method, path = item[0], item[1]
        if not (isinstance(method, str) and isinstance(path, str) and path.startswith("/")):
            continue
        key = _normalize_for_comparison(_route_to_spec_path(path))
        out.setdefault(key, set()).add(method.strip().lower())
    return out


def _merge_supplement(
    merged_paths: dict[str, dict[str, Any]], supplement: dict[str, dict[str, Any]]
) -> None:
    """Merge supplement operations method-wise into the spec paths.

    A path-level setdefault dropped every supplement whose path already
    existed (review P2 on #9360) — documented operations are never
    overwritten, and missing-method supplements land beside them.
    """
    for path, methods in supplement.items():
        target = merged_paths.setdefault(path, {})
        for op_method, operation in methods.items():
            target.setdefault(op_method, operation)


def _collect_handler_routes_supplement(
    existing_paths: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build placeholder path items for handler routes absent from the spec.

    Reads ROUTES / *_ROUTES from every handler in HANDLER_REGISTRY (the same
    sources the route-coverage gate validates), skips internal route families,
    and returns autogenerated operations for any route whose normalized form
    is not already covered by ``existing_paths``.
    """
    try:
        from aragora.server.handler_registry import HANDLER_REGISTRY
    except Exception as exc:
        print(f"Warning: handler ROUTES supplement skipped: {exc}", file=sys.stderr)
        return {}

    # Fail CLOSED on the internal-route policy: without it, internal route
    # families (control-plane, SME, emergency admin, ...) would silently
    # publish into the public spec.
    internal_prefixes = _load_internal_route_prefixes()

    covered = {_normalize_for_comparison(p) for p in existing_paths}
    # Method-level spec coverage: a path documented for GET must still accept
    # supplements for its OTHER declared methods (review P2 on #9360 — the
    # path-level skip silently swallowed POST_ROUTES on GET-documented paths).
    covered_methods: dict[str, set[str]] = {}
    # comparison key -> exact spec path string, so covered-path supplements
    # merge into the existing path item instead of minting a {param} twin.
    spec_path_by_key: dict[str, str] = {}
    for existing_path, path_item in existing_paths.items():
        key = _normalize_for_comparison(existing_path)
        spec_path_by_key.setdefault(key, existing_path)
        if isinstance(path_item, dict):
            covered_methods.setdefault(key, set()).update(
                m.lower() for m in path_item if isinstance(m, str)
            )
    supplement: dict[str, dict[str, Any]] = {}
    # Maps comparison key -> supplement path, so a route declared with several
    # methods (e.g. "GET /x" and "POST /x") merges into one path item.
    supplement_keys: dict[str, str] = {}

    method_attrs = (
        ("ROUTES", None),
        ("GET_ROUTES", "get"),
        ("POST_ROUTES", "post"),
        ("PUT_ROUTES", "put"),
        ("PATCH_ROUTES", "patch"),
        ("DELETE_ROUTES", "delete"),
    )

    for _attr_name, handler_ref in HANDLER_REGISTRY:
        handler_class = handler_ref
        resolve = getattr(handler_ref, "resolve", None)
        if callable(resolve):
            try:
                handler_class = resolve()
            except Exception:  # noqa: BLE001 - unresolvable handlers have no routes
                continue
        if handler_class is None:
            continue

        doc = (getattr(handler_class, "__doc__", None) or "").strip()
        doc_summary = doc.split("\n")[0].strip() if doc else ""
        tag = getattr(handler_class, "__name__", "Handler").removesuffix("Handler") or "Handler"

        # First pass: collect supplement-eligible entries for this handler so
        # verb attribution can be bounded by how many generic (method-unknown)
        # paths the handler declares.
        entries: list[tuple[str | None, str, str]] = []
        # Count generic routes across EVERYTHING the handler declares — not
        # just the uncovered entries that land in the supplement. The class
        # verb set is the union across all of the handler's generic routes,
        # so it is only attributable when the handler declares exactly one
        # generic route in total. Counting only uncovered routes would apply
        # the union to a lone leftover path (e.g. EmailWebhookHandler's
        # POST-only mailgun webhook picking up GET from the covered /status
        # route's handle()).
        total_generic_declared = 0
        # Explicit routes() declarations are per-path verb evidence and beat
        # every inference tier (review P2 on #9360: SSOHandler's POST
        # login/callback/logout documented as GET-only). Expanded here in the
        # first pass so per-method coverage applies: a path documented for
        # GET still gets its declared POST supplemented.
        explicit_verbs = _explicit_route_verbs(handler_class)
        for attr, declared_method in method_attrs:
            routes = getattr(handler_class, attr, None)
            if not isinstance(routes, (list, tuple)):
                continue
            for raw_route in routes:
                route = (
                    raw_route[1]
                    if isinstance(raw_route, tuple) and len(raw_route) > 1
                    else raw_route
                )
                if not isinstance(route, str) or not route.startswith("/"):
                    continue

                method = declared_method
                if method is None:
                    for prefix in _ROUTE_METHOD_PREFIXES:
                        if route.startswith(prefix):
                            method = prefix.strip().lower()
                            break

                spec_path = _route_to_spec_path(route)
                comparison_key = _normalize_for_comparison(spec_path)

                if method is None:
                    # Count every method-less static entry — including ones
                    # resolved via routes() below — so class-level verb
                    # derivation stays gated to single-generic-path handlers
                    # and can't over-attribute a routes()-covered sibling's
                    # verbs to the remaining generic path.
                    total_generic_declared += 1

                if method is None and comparison_key in explicit_verbs:
                    # routes() declared this path's verb set explicitly:
                    # expand to method-declared entries, per-method covered.
                    for verb in sorted(explicit_verbs[comparison_key]):
                        if verb in covered_methods.get(comparison_key, set()):
                            continue
                        if _is_internal_route(comparison_key, internal_prefixes):
                            continue
                        entries.append((verb, spec_path, comparison_key))
                    continue

                if method is None:
                    # Generic ROUTES on an already-covered path: the served
                    # verb set is unknowable, so never re-derive ops for it.
                    if comparison_key in covered and comparison_key not in supplement_keys:
                        continue
                elif method in covered_methods.get(comparison_key, set()):
                    # This exact operation is already documented in the spec.
                    continue
                if _is_internal_route(comparison_key, internal_prefixes):
                    continue
                entries.append((method, spec_path, comparison_key))

        # Class-level verb derivation (handle -> GET, handle_post -> POST,
        # ...) is only unambiguous when the handler declares exactly ONE
        # generic path: with several paths, the class verb set is the union
        # across all of them and would advertise nonexistent operations
        # (e.g. SandboxHandler serves POST /execute but only GET /pool/status).
        # A bare ["get"] result is also skipped: it means only generic
        # handle() is overridden, and dispatcher-style handlers serve any
        # verb through it.
        derived_verbs: list[str] = []
        if total_generic_declared == 1:
            derived_verbs = _implemented_handler_verbs(handler_class)
            if derived_verbs == ["get"]:
                derived_verbs = []

        for method, spec_path, comparison_key in entries:
            method_inferred = method is None
            if method is not None:
                methods = [method]
            elif derived_verbs:
                methods = derived_verbs
            else:
                # Fallback: infer a single verb from the last segment.
                last_segment = spec_path.rsplit("/", 1)[-1]
                methods = ["post" if last_segment in _ACTION_SEGMENTS else "get"]

            covered.add(comparison_key)
            target_path = supplement_keys.setdefault(
                comparison_key, spec_path_by_key.get(comparison_key, spec_path)
            )
            for op_method in methods:
                # The operation publishes under target_path (which may be an
                # existing spec path whose template uses different parameter
                # names, e.g. {param}), so its summary and declared path
                # parameters MUST be derived from target_path — deriving them
                # from spec_path produced operations whose parameter names
                # didn't match their path template (invalid OpenAPI).
                operation: dict[str, Any] = {
                    "summary": f"{op_method.upper()} {target_path}",
                    "description": (
                        (doc_summary + " " if doc_summary else "")
                        + "Auto-generated from handler ROUTES; detailed contract pending."
                    ),
                    "tags": [tag],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {"schema": {"type": "object"}},
                            },
                        },
                    },
                    "security": [{"bearerAuth": []}],
                    "x-autogenerated": True,
                    "x-method-inferred": method_inferred,
                    "x-aragora-stability": "experimental",
                }
                params = _extract_path_params(target_path)
                if params:
                    operation["parameters"] = params
                if op_method in ("post", "put", "patch"):
                    operation["requestBody"] = {
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                supplement.setdefault(target_path, {}).setdefault(op_method, operation)

    return supplement


def _deduplicate_ambiguous_paths(paths: dict[str, Any]) -> dict[str, Any]:
    """Remove paths that differ only in parameter names.

    When two paths normalize to the same template (e.g.
    /api/v1/agent/{name}/introspect vs /api/v1/agent/{param}/introspect),
    keep the one with descriptive parameter names over generic {param},
    and prefer non-autogenerated specs.
    """
    norm_re = re.compile(r"\{[^}]+\}")

    def _norm(p: str) -> str:
        return norm_re.sub("*", p).rstrip("/")

    groups: dict[str, list[str]] = {}
    for path in paths:
        groups.setdefault(_norm(path), []).append(path)

    result: dict[str, Any] = {}
    for group in groups.values():
        if len(group) == 1:
            result[group[0]] = paths[group[0]]
            continue

        # Pick best: prefer non-autogenerated, then named params, then versioned
        def _score(p: str) -> tuple[int, int, int]:
            spec = paths[p]
            has_auto = any(
                isinstance(op, dict) and op.get("x-autogenerated") is True for op in spec.values()
            )
            return (
                0 if has_auto else 1,
                -p.count("{param}"),
                1 if "/api/v1/" in p or "/api/v2/" in p else 0,
            )

        best = max(group, key=_score)
        result[best] = paths[best]

    removed = len(paths) - len(result)
    if removed:
        print(
            f"Deduplicated {removed} ambiguous path(s) ({len(result)} paths remain)",
            file=sys.stderr,
        )
    return result


def _count_operations(paths: dict[str, dict[str, Any]]) -> int:
    """Count total HTTP method operations across all paths."""
    return sum(len(methods) for methods in paths.values())


# ============================================================================
# Output helpers
# ============================================================================


def save_schema(schema: dict[str, Any], output_path: str, fmt: str = "json") -> int:
    """Save schema to file. Returns endpoint count."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "yaml":
        try:
            import yaml

            content = yaml.dump(schema, default_flow_style=False, sort_keys=False, width=120)
        except ImportError:
            print(
                "Warning: PyYAML not installed, falling back to JSON output",
                file=sys.stderr,
            )
            fmt = "json"
            content = json.dumps(schema, indent=2)
    else:
        content = json.dumps(schema, indent=2)

    path.write_text(content + "\n")

    endpoint_count = _count_operations(schema.get("paths", {}))
    return endpoint_count


def print_summary(schema: dict[str, Any]) -> None:
    """Print a human-readable summary of the generated spec."""
    paths = schema.get("paths", {})
    total_paths = len(paths)
    method_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()

    for path_spec in paths.values():
        for method, op in path_spec.items():
            method_upper = method.upper()
            method_counter[method_upper] += 1
            if isinstance(op, dict):
                for tag in op.get("tags", []):
                    tag_counter[tag] += 1

    total_ops = sum(method_counter.values())

    print("\n--- OpenAPI Generation Summary ---", file=sys.stderr)
    print(f"OpenAPI version : {schema.get('openapi', '?')}", file=sys.stderr)
    print(f"API version     : {schema.get('info', {}).get('version', '?')}", file=sys.stderr)
    print(f"Total paths     : {total_paths}", file=sys.stderr)
    print(f"Total operations: {total_ops}", file=sys.stderr)

    print("\nBy HTTP method:", file=sys.stderr)
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        count = method_counter.get(method, 0)
        if count:
            print(f"  {method:8s} {count}", file=sys.stderr)

    print(f"\nBy tag ({len(tag_counter)} tags):", file=sys.stderr)
    for tag, count in tag_counter.most_common(25):
        print(f"  {tag:30s} {count}", file=sys.stderr)
    if len(tag_counter) > 25:
        remaining = sum(c for _, c in tag_counter.most_common()[25:])
        print(f"  {'... (remaining)':30s} {remaining}", file=sys.stderr)

    print("--- End Summary ---\n", file=sys.stderr)


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate OpenAPI 3.1.0 spec for Aragora (multi-tier pipeline)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="docs/api/openapi.yaml",
        help="Output file path (default: docs/api/openapi.yaml)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "yaml"],
        default=None,
        help="Output format (auto-detected from --output extension if not set)",
    )
    parser.add_argument(
        "--ast-only",
        action="store_true",
        help="Use only AST parsing (no runtime imports)",
    )
    parser.add_argument(
        "--legacy-handlers",
        action="store_true",
        help="Use legacy handler ROUTES introspection",
    )
    parser.add_argument(
        "--no-runtime",
        action="store_true",
        help="Skip runtime decorator import (tiers 1 + 3 only)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print spec to stdout instead of file",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress summary output",
    )
    args = parser.parse_args()

    # Auto-detect format from output extension
    fmt = args.format
    if fmt is None:
        if args.output.endswith(".yaml") or args.output.endswith(".yml"):
            fmt = "yaml"
        else:
            fmt = "json"

    schema = generate_schema(
        ast_only=args.ast_only,
        legacy_handlers=args.legacy_handlers,
        include_runtime=not args.no_runtime,
    )

    if not args.quiet:
        print_summary(schema)

    if args.stdout:
        if fmt == "yaml":
            try:
                import yaml

                print(yaml.dump(schema, default_flow_style=False, sort_keys=False, width=120))
            except ImportError:
                print(json.dumps(schema, indent=2))
        else:
            print(json.dumps(schema, indent=2))
    else:
        endpoint_count = save_schema(schema, args.output, fmt)
        print(f"Output: {args.output} ({endpoint_count} operations)", file=sys.stderr)


if __name__ == "__main__":
    main()
