"""KM checkpoint restore is documented as not implemented (501) wherever it is described.

The handler tests pin the served statuses. These tests pin the OpenAPI entry, every
generated API document, the stability manifest and both SDKs to the same 501, and
the create entry to the 507 that the global checkpoint ceiling answers.
"""

from __future__ import annotations

import ast
import functools
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from aragora.server.openapi.endpoints.checkpoints import CHECKPOINT_ENDPOINTS

ROOT = Path(__file__).resolve().parents[3]
RESTORE = "/api/km/checkpoints/{checkpoint_name}/restore"
COLLECTION = "/api/km/checkpoints"
DOCUMENTS = ["openapi.json", "openapi.yaml", "openapi_generated.json", "openapi_generated.yaml"]


@functools.cache
def _document(name: str) -> dict[str, Any]:
    text = (ROOT / "docs" / "api" / name).read_text()
    if name.endswith(".json"):
        return json.loads(text)
    return yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def _error_code(response: dict[str, Any]) -> list[str]:
    schema = response["content"]["application/json"]["schema"]
    return schema["properties"]["error"]["properties"]["code"]["enum"]


def _assert_restore_not_implemented(operation: dict[str, Any]) -> None:
    responses = operation["responses"]
    assert _error_code(responses["501"]) == ["not_implemented"]
    assert "not implemented" in operation["description"].lower()
    for code, response in responses.items():
        if str(code).startswith("2"):
            assert "content" not in response, f"{code} documents a success payload"
    assert operation.get("x-aragora-stability") != "stable"


def _assert_create_documents_the_ceiling(operation: dict[str, Any]) -> None:
    assert _error_code(operation["responses"]["507"]) == ["checkpoint_storage_full"]


def test_endpoint_definitions() -> None:
    _assert_restore_not_implemented(CHECKPOINT_ENDPOINTS[RESTORE]["post"])
    _assert_create_documents_the_ceiling(CHECKPOINT_ENDPOINTS[COLLECTION]["post"])


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
@pytest.mark.parametrize("name", DOCUMENTS)
def test_generated_documents(name: str, prefix: str) -> None:
    paths = _document(name)["paths"]
    _assert_restore_not_implemented(paths[RESTORE.replace("/api", prefix, 1)]["post"])
    _assert_create_documents_the_ceiling(paths[COLLECTION.replace("/api", prefix, 1)]["post"])


def test_stability_manifest_does_not_declare_restore_stable() -> None:
    manifest = json.loads((ROOT / "aragora/server/openapi/stability_manifest.json").read_text())
    restore = "POST /api/v1/km/checkpoints/{param}/restore"
    assert restore not in manifest["stable"] + manifest.get("beta", [])


def test_python_sdk_restore_documents_the_501() -> None:
    source = (ROOT / "sdk/python/aragora_sdk/namespaces/checkpoints.py").read_text()
    docstrings = [
        ast.get_docstring(node) or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "restore_km"
    ]
    assert len(docstrings) == 2  # sync and async clients
    for doc in docstrings:
        assert "501" in doc and "ServerError" in doc, doc


def test_typescript_sdk_restore_documents_the_501() -> None:
    source = (ROOT / "sdk/typescript/src/namespaces/checkpoints.ts").read_text()
    match = re.search(
        r"/\*\*((?:(?!\*/).)*)\*/\s*async restoreKM\(name: string\): Promise<([^>]*)>",
        source,
        re.S,
    )
    assert match is not None
    assert "501" in match.group(1)
    assert match.group(2) == "never"
