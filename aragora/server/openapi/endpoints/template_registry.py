"""Template registry endpoint definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from aragora.server.openapi.helpers import _ok_response, STANDARD_ERRORS

__all__ = [
    "TEMPLATE_REGISTRY_ENDPOINTS",
    "get_registry_listing_schema",
    "get_registry_listing_required_fields",
    "get_registry_listing_property_names",
    "get_registry_listing_field_types",
    "build_sample_listing",
    "validate_listing",
]

_REGISTRY_LISTING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "category": {"type": "string"},
        "author_id": {"type": "string"},
        "version": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string"},
        "is_verified": {"type": "boolean"},
        "is_builtin": {"type": "boolean"},
        "install_count": {"type": "integer"},
        "rating_average": {"type": "number"},
        "rating_count": {"type": "integer"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "approved_by": {"type": ["string", "null"]},
    },
    "required": [
        "id",
        "name",
        "description",
        "category",
        "author_id",
        "version",
        "tags",
        "status",
        "is_verified",
        "is_builtin",
        "install_count",
        "rating_average",
        "rating_count",
        "created_at",
        "updated_at",
        "approved_by",
    ],
}


def get_registry_listing_schema() -> dict[str, Any]:
    """Return a copy of the registry listing schema for validation and testing."""
    return deepcopy(_REGISTRY_LISTING_SCHEMA)


def get_registry_listing_required_fields() -> list[str]:
    """Return the list of required fields for a registry listing."""
    return list(_REGISTRY_LISTING_SCHEMA["required"])


def get_registry_listing_property_names() -> list[str]:
    """Return all property names defined in the registry listing schema."""
    return sorted(_REGISTRY_LISTING_SCHEMA["properties"].keys())


def get_registry_listing_field_types() -> dict[str, Any]:
    """Return a mapping of field name to its JSON Schema type descriptor."""
    return {
        name: deepcopy(spec.get("type", "string"))
        for name, spec in _REGISTRY_LISTING_SCHEMA["properties"].items()
    }


def validate_listing(data: dict[str, Any]) -> list[str]:
    """Validate *data* against the registry listing schema, returning error messages.

    Returns an empty list when the listing is valid.  Checks required fields,
    disallowed extra keys, and basic JSON-Schema type conformance so that tests
    can assert validity without pulling in a full jsonschema dependency.
    """
    _JS_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
    }
    errors: list[str] = []
    props = _REGISTRY_LISTING_SCHEMA["properties"]

    for field in _REGISTRY_LISTING_SCHEMA["required"]:
        if field not in data:
            errors.append(f"missing required field: {field}")

    if _REGISTRY_LISTING_SCHEMA.get("additionalProperties") is False:
        extra = set(data) - set(props)
        if extra:
            errors.append(f"unexpected fields: {sorted(extra)}")

    for field, value in data.items():
        if field not in props:
            continue
        spec_type = props[field].get("type")
        if spec_type is None:
            continue
        if value is None:
            if isinstance(spec_type, list) and "null" in spec_type:
                continue
            errors.append(f"field '{field}' is null but not nullable")
            continue
        expected_types = spec_type if isinstance(spec_type, list) else [spec_type]
        py_types = tuple(
            t
            for st in expected_types
            if st != "null"
            for t in (
                (_JS_TYPE_MAP.get(st, ()),)
                if not isinstance(_JS_TYPE_MAP.get(st, ()), tuple)
                else (_JS_TYPE_MAP.get(st, ()),)
            )
        )
        # Flatten the tuple of python types
        flat: list[type] = []
        for entry in py_types:
            if isinstance(entry, tuple):
                flat.extend(entry)
            else:
                flat.append(entry)
        if flat and not isinstance(value, tuple(flat)):
            errors.append(f"field '{field}' expected {expected_types}, got {type(value).__name__}")

    return errors


def build_sample_listing(**overrides: Any) -> dict[str, Any]:
    """Build a sample registry listing dict suitable for schema validation tests."""
    sample: dict[str, Any] = {
        "id": "tpl_sample_001",
        "name": "Sample Template",
        "description": "A sample template for testing.",
        "category": "general",
        "author_id": "user_test",
        "version": "1.0.0",
        "tags": ["test", "sample"],
        "status": "published",
        "is_verified": False,
        "is_builtin": False,
        "install_count": 0,
        "rating_average": 0.0,
        "rating_count": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "approved_by": None,
    }
    sample.update(overrides)
    return sample


TEMPLATE_REGISTRY_ENDPOINTS: dict[str, Any] = {
    "/api/v1/templates/registry/{listing_id}": {
        "get": {
            "tags": ["Templates"],
            "summary": "Get template registry listing",
            "operationId": "getTemplateRegistryListing",
            "description": "Retrieve a single public template registry listing by its identifier.",
            "parameters": [
                {
                    "name": "listing_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique template registry listing identifier.",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Template registry listing", _REGISTRY_LISTING_SCHEMA),
                "404": STANDARD_ERRORS["404"],
            },
        }
    }
}
