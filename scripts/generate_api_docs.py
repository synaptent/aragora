#!/usr/bin/env python3
"""
Generate API documentation from handler classes.

Parses every handler module statically (ast, nothing imported, so the output does
not depend on installed extras) and lists only the (method, path) pairs that
docs/api/openapi.json serves; discovered endpoints without a spec operation are left out.

Usage:
    python scripts/generate_api_docs.py > docs/API_ENDPOINTS.md
    python scripts/generate_api_docs.py --output docs/API_ENDPOINTS.md
    python scripts/generate_api_docs.py --format json
"""

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = PROJECT_ROOT / "aragora" / "server" / "handlers"
SPEC_PATH = PROJECT_ROOT / "docs" / "api" / "openapi.json"
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


@dataclass
class Endpoint:
    """Represents an API endpoint."""

    path: str
    method: str = "GET"
    description: str = ""
    handler_class: str = ""
    handler_method: str = ""
    parameters: list[dict] = field(default_factory=list)
    response_example: str | None = None
    auth_required: bool = False


@dataclass
class EndpointGroup:
    """Group of related endpoints."""

    name: str
    description: str
    endpoints: list[Endpoint] = field(default_factory=list)


def discover_handler_modules(handlers_dir: Path = HANDLERS_DIR) -> list[Path]:
    """Discover every handler module file under ``handlers_dir``, in path order."""
    return sorted(
        path
        for path in handlers_dir.rglob("*.py")
        if not any(part.startswith("_") for part in path.relative_to(handlers_dir).parts)
        and path.stem not in ("base", "routing")
    )


def normalize_path(path: str) -> str:
    """Erase path-parameter names (``{id}``, ``:id``, ``<id>``) so handler and spec paths compare."""
    return re.sub(r"\{[^}]+\}|:\w+|<[^>]+>", "{}", path.rstrip("/") or "/")


def load_spec_operations(spec_path: Path) -> dict[str, dict[str, dict]]:
    """Map each normalized spec path to its operations keyed by upper-case method."""
    operations: dict[str, dict[str, dict]] = {}
    for path, item in json.loads(spec_path.read_text(encoding="utf-8"))["paths"].items():
        for method, operation in item.items():
            if method.upper() in HTTP_METHODS:
                operations.setdefault(normalize_path(path), {})[method.upper()] = operation
    return operations


def handler_classes(module: ast.Module) -> list[tuple[str, ast.ClassDef]]:
    """Return the module's ``*Handler`` classes by name, as ``inspect.getmembers`` orders them."""
    nodes = [n for n in module.body if isinstance(n, ast.ClassDef) and n.name.endswith("Handler")]
    return sorted(((node.name, node) for node in nodes), key=lambda pair: pair[0])


def extract_endpoints_from_module_docstring(module) -> list[tuple[str, str, str]]:
    """Extract endpoints from module docstring.

    Module docstrings follow the format:
        Endpoints:
        - GET /api/path - Description
        - POST /api/path/{param} - Description

    Returns:
        List of (method, path, description) tuples
    """
    docstring = ast.get_docstring(module, clean=False)
    if not docstring:
        return []

    endpoints = []
    match = re.search(r"Endpoints:\s*\n((?:\s*-?\s*[A-Z]+\s+/\S+.*\n?)+)", docstring)
    if not match:
        return []

    endpoint_block = match.group(1)
    for line in endpoint_block.strip().split("\n"):
        endpoint_match = re.match(r"^\s*-?\s*([A-Z]+)\s+(/\S+)\s*(?:-\s*(.*))?$", line)
        if endpoint_match:
            method = endpoint_match.group(1)
            path = endpoint_match.group(2)
            description = (endpoint_match.group(3) or "").strip()
            endpoints.append((method, path, description))

    return endpoints


def extract_routes_from_handler(handler_class: ast.ClassDef) -> list[str]:
    """Extract literal ROUTES and POST_ROUTES from a handler class; computed values are skipped."""
    routes: list[object] = []
    for stmt in handler_class.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        if {t.id for t in targets if isinstance(t, ast.Name)} & {"ROUTES", "POST_ROUTES"}:
            try:
                routes.extend(ast.literal_eval(stmt.value))
            except ValueError:
                continue
    return [route for route in dict.fromkeys(routes) if isinstance(route, str)]


def extract_docstring_info(docstring: str) -> tuple[str, list[dict]]:
    """Extract description and parameters from docstring.

    Returns:
        Tuple of (description, list of parameter dicts)
    """
    if not docstring:
        return "", []

    lines = docstring.strip().split("\n")
    description_lines = []
    parameters = []

    in_params = False
    in_returns = False
    current_param = None

    for line in lines:
        line = line.strip()

        if line.lower().startswith("args:") or line.lower().startswith("parameters:"):
            in_params = True
            in_returns = False
            continue
        elif line.lower().startswith("returns:"):
            in_params = False
            in_returns = True
            continue
        elif line.lower().startswith("raises:"):
            in_params = False
            in_returns = False
            continue

        if in_params:
            # Match parameter definitions like "param_name: description" or "param_name (type): description"
            param_match = re.match(r"^(\w+)\s*(?:\(([^)]+)\))?\s*:\s*(.+)?$", line)
            if param_match:
                current_param = {
                    "name": param_match.group(1),
                    "type": param_match.group(2) or "string",
                    "description": param_match.group(3) or "",
                }
                parameters.append(current_param)
            elif current_param and line:
                # Continuation of previous parameter description
                current_param["description"] += " " + line
        elif not in_returns:
            description_lines.append(line)

    description = " ".join(description_lines).strip()
    # Clean up description - take first sentence or first 200 chars
    if description:
        first_sentence = description.split(".")[0]
        description = first_sentence[:200] + ("..." if len(first_sentence) > 200 else "")

    return description, parameters


def discover_endpoints(
    handlers_dir: Path = HANDLERS_DIR, spec_path: Path = SPEC_PATH
) -> tuple[list[EndpointGroup], int]:
    """Discover endpoints from handler sources; return the groups and the count omitted.

    Only (method, path) pairs the spec serves are kept: a docstring endpoint or a
    ROUTES path without a spec operation is counted as omitted instead of guessed.
    """
    operations = load_spec_operations(spec_path)
    groups = []
    omitted = 0

    for py_file in discover_handler_modules(handlers_dir):
        module = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

        # First try to extract endpoints from module docstring
        module_endpoints = extract_endpoints_from_module_docstring(module)

        # Get module description from first paragraph before "Endpoints:"
        module_doc = ast.get_docstring(module, clean=False) or ""
        module_desc = ""
        if module_doc:
            desc_match = re.match(r"^(.+?)(?=\n\s*Endpoints:|$)", module_doc, re.DOTALL)
            if desc_match:
                module_desc = desc_match.group(1).strip().split("\n")[0]

        # Find handler classes in the module
        handler_class_name = None

        for name, obj in handler_classes(module):
            if extract_routes_from_handler(obj):
                handler_class_name = name
                break

        # If we have module docstring endpoints, use those (preferred)
        if module_endpoints:
            group_name = py_file.stem.title().replace("_", " ")
            group = EndpointGroup(name=group_name, description=module_desc)

            for method, path, description in module_endpoints:
                operation = operations.get(normalize_path(path), {}).get(method)
                if operation is None:
                    omitted += 1
                    continue
                auth_required = bool(operation.get("security"))
                endpoint = Endpoint(
                    path=path,
                    method=method,
                    description=description,
                    handler_class=handler_class_name or "",
                    handler_method="",
                    parameters=[],
                    auth_required=auth_required,
                )
                group.endpoints.append(endpoint)

            if group.endpoints:
                groups.append(group)
            continue

        # Fall back to ROUTES attribute
        for name, obj in handler_classes(module):
            if extract_routes_from_handler(obj):
                group_name = name.replace("Handler", "")
                group_desc = ast.get_docstring(obj, clean=False) or f"{group_name} endpoints"

                # Extract first line of docstring as description
                if group_desc:
                    group_desc = group_desc.strip().split("\n")[0]

                group = EndpointGroup(name=group_name, description=group_desc)

                routes = extract_routes_from_handler(obj)
                served = {route: operations.get(normalize_path(route), {}) for route in routes}
                omitted += sum(not methods for methods in served.values())
                method_docs = {
                    f.name: ast.get_docstring(f, clean=False) or ""
                    for f in obj.body
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                pairs = [(r, m) for r in routes for m in sorted(served[r], key=HTTP_METHODS.index)]

                for route, method in pairs:
                    # Try to find the corresponding handler method
                    handler_method = None
                    method_doc = ""
                    params: list[dict] = []

                    # Look for method that handles this route
                    for attr_name, attr_doc in sorted(method_docs.items()):
                        if attr_name.startswith("_") and not attr_name.startswith("__"):
                            # Check if method handles this route
                            if route in attr_doc or route.split("/")[-1] in attr_name:
                                handler_method = attr_name
                                method_doc, params = extract_docstring_info(attr_doc)
                                break

                    auth_required = bool(served[route][method].get("security"))
                    endpoint = Endpoint(
                        path=route,
                        method=method,
                        description=method_doc or f"{method} {route}",
                        handler_class=name,
                        handler_method=handler_method or "",
                        parameters=params,
                        auth_required=auth_required,
                    )
                    group.endpoints.append(endpoint)

                if group.endpoints:
                    groups.append(group)

    return groups, omitted


def generate_markdown(groups: list[EndpointGroup]) -> str:
    """Generate markdown documentation from endpoint groups."""
    lines = [
        "# Aragora API Documentation",
        "",
        "This document describes the HTTP API endpoints provided by the Aragora server.",
        "",
        "## Table of Contents",
        "",
    ]

    # Generate TOC
    for group in groups:
        anchor = group.name.lower().replace(" ", "-")
        lines.append(f"- [{group.name}](#{anchor})")

    lines.extend(["", "---", ""])

    # Generate endpoint documentation
    for group in groups:
        lines.extend(
            [
                f"## {group.name}",
                "",
                group.description,
                "",
            ]
        )

        for endpoint in group.endpoints:
            method_badge = f"`{endpoint.method}`"
            auth_badge = " 🔒" if endpoint.auth_required else ""

            lines.extend(
                [
                    f"### {method_badge} `{endpoint.path}`{auth_badge}",
                    "",
                    endpoint.description or "No description available.",
                    "",
                ]
            )

            if endpoint.parameters:
                lines.append("**Parameters:**")
                lines.append("")
                lines.append("| Name | Type | Description |")
                lines.append("|------|------|-------------|")
                for param in endpoint.parameters:
                    lines.append(
                        f"| `{param['name']}` | {param['type']} | {param['description']} |"
                    )
                lines.append("")

            if endpoint.response_example:
                lines.extend(
                    [
                        "**Response Example:**",
                        "",
                        "```json",
                        endpoint.response_example,
                        "```",
                        "",
                    ]
                )

        lines.append("---")
        lines.append("")

    # Add footer
    lines.extend(
        [
            "## Authentication",
            "",
            "Endpoints marked with 🔒 require authentication.",
            "",
            "Include an `Authorization` header with your API token:",
            "",
            "```",
            "Authorization: Bearer <your-api-token>",
            "```",
            "",
            "Set `ARAGORA_API_TOKEN` environment variable to configure the token.",
            "",
            "---",
            "",
            "*Generated automatically by `scripts/generate_api_docs.py`*",
        ]
    )

    return "\n".join(lines) + "\n"


def generate_json(groups: list[EndpointGroup]) -> str:
    """Generate JSON documentation from endpoint groups."""
    data: dict[str, Any] = {"title": "Aragora API", "version": "1.0.0", "groups": []}

    for group in groups:
        group_data: dict[str, Any] = {
            "name": group.name,
            "description": group.description,
            "endpoints": [],
        }

        for endpoint in group.endpoints:
            endpoint_data = {
                "path": endpoint.path,
                "method": endpoint.method,
                "description": endpoint.description,
                "auth_required": endpoint.auth_required,
                "parameters": endpoint.parameters,
            }
            group_data["endpoints"].append(endpoint_data)

        data["groups"].append(group_data)

    return json.dumps(data, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Generate API documentation from handler classes")
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args()

    print("Discovering endpoints...", file=sys.stderr)
    groups, omitted = discover_endpoints()

    total_endpoints = sum(len(g.endpoints) for g in groups)
    print(f"Found {total_endpoints} endpoints in {len(groups)} groups", file=sys.stderr)
    print(f"Omitted {omitted} discovered endpoints with no spec operation", file=sys.stderr)

    if args.format == "json":
        output = generate_json(groups)
    else:
        output = generate_markdown(groups)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Documentation written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
