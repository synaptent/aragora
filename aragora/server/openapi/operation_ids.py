"""Deterministic OpenAPI operation ID generation."""

from __future__ import annotations

import re
from typing import Any


def path_to_camel_case(path: str) -> str:
    """Convert an API path to the canonical operation ID path component."""
    path = re.sub(r"^/api(/v\d+)?/", "", path)
    path = re.sub(
        r"\{([^}]+)\}", lambda match: "By" + match.group(1).title().replace("_", ""), path
    )

    parts = re.split(r"[/_-]", path)
    result: list[str] = []
    for index, part in enumerate(parts):
        if not part:
            continue
        if index == 0 or result:
            result.append(part.title())
        else:
            result.append(part)
    return "".join(result)


def generate_operation_id(method: str, path: str) -> str:
    """Generate the canonical base operation ID for a method and path."""
    method = method.lower()
    verb = {
        "get": "get",
        "post": "create",
        "put": "update",
        "patch": "patch",
        "delete": "delete",
        "head": "head",
        "options": "options",
    }.get(method, method)

    if method == "get" and not re.search(r"\{[^}]+\}$", path):
        if not path.endswith("/health") and not path.endswith("/metrics"):
            verb = "list"
    if method == "get" and re.search(r"\{[^}]+\}$", path):
        verb = "get"

    path_part = path_to_camel_case(path)
    operation_id = verb + path_part if path_part else verb + "Root"
    return operation_id[0].lower() + operation_id[1:]


def add_operation_ids_to_paths(
    paths: dict[str, Any],
) -> tuple[int, int, int]:
    """Add or deduplicate operation IDs in path iteration order.

    Returns ``(added_count, existing_count, updated_count)``.
    """
    added = 0
    existing = 0
    updated = 0
    seen_ids: set[str] = set()

    for path, methods in paths.items():
        for method, details in methods.items():
            if not isinstance(details, dict):
                continue
            if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options"):
                continue

            base_id = details.get("operationId") or generate_operation_id(method, path)
            operation_id = base_id
            counter = 1
            while operation_id in seen_ids:
                operation_id = f"{base_id}{counter}"
                counter += 1

            if "operationId" in details:
                if operation_id != details["operationId"]:
                    details["operationId"] = operation_id
                    updated += 1
                else:
                    existing += 1
            else:
                details["operationId"] = operation_id
                added += 1

            seen_ids.add(operation_id)

    return added, existing, updated


def add_operation_ids(spec: dict[str, Any]) -> tuple[dict[str, Any], int, int, int]:
    """Add or deduplicate operation IDs for every operation in a spec."""
    added, existing, updated = add_operation_ids_to_paths(spec.get("paths", {}))
    return spec, added, existing, updated
