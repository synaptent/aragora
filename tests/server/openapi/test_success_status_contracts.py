from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from jsonschema import Draft202012Validator

from aragora.server.handlers.admin.credits import CreditsAdminHandler
from aragora.server.handlers.features.integrations import IntegrationsHandler
from aragora.server.openapi import generate_openapi_schema
from aragora.storage.integration_memory import InMemoryIntegrationStore


ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = ROOT / "docs/api/openapi.json"
GENERATED_OPENAPI_PATH = ROOT / "docs/api/openapi_generated.json"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_spec(spec_path: Path) -> dict[str, Any]:
    return json.loads(spec_path.read_text(), object_pairs_hook=_reject_duplicate_keys)


def _documented_success_statuses(spec_path: Path, path: str, method: str) -> set[int]:
    spec = _load_spec(spec_path)
    responses = spec["paths"][path][method]["responses"]
    return {int(status) for status in responses if status.isdigit() and 200 <= int(status) < 300}


@pytest.mark.asyncio
async def test_credit_issue_success_statuses_match_runtime_handler() -> None:
    transaction = SimpleNamespace(to_dict=lambda: {"id": "credit-1"})
    manager = SimpleNamespace(issue_credit=AsyncMock(return_value=transaction))
    runtime_method = inspect.unwrap(CreditsAdminHandler.issue_credit)

    with patch(
        "aragora.server.handlers.admin.credits.get_credit_manager",
        return_value=manager,
    ):
        result = await runtime_method(
            CreditsAdminHandler(),
            "org-1",
            {
                "amount_cents": 100,
                "description": "Contract status probe",
            },
            "admin-1",
        )

    runtime_statuses = {result.status_code}
    assert runtime_statuses == {201}
    for path in (
        "/api/admin/credits/{org_id}/issue",
        "/api/v1/admin/credits/{org_id}/issue",
    ):
        assert _documented_success_statuses(OPENAPI_PATH, path, "post") == runtime_statuses


@pytest.mark.asyncio
async def test_integration_put_success_statuses_match_create_and_update_runtime() -> None:
    store = InMemoryIntegrationStore()
    handler = IntegrationsHandler(server_context={})

    with patch(
        "aragora.server.handlers.features.integrations.get_integration_store",
        return_value=store,
    ):
        created = await handler.configure_integration("email", {}, user_id="user-1")
        updated = await handler.configure_integration(
            "email",
            {"enabled": False},
            user_id="user-1",
        )

    runtime_results = (created, updated)
    runtime_statuses = {result.status_code for result in runtime_results}
    assert runtime_statuses == {200, 201}
    for path in (
        "/api/integrations/{type}",
        "/api/v1/integrations/{type}",
    ):
        assert _documented_success_statuses(OPENAPI_PATH, path, "put") == runtime_statuses

    generated_runtime_schema = generate_openapi_schema()
    generated_responses = generated_runtime_schema["paths"]["/api/v1/integrations/{type}"]["put"][
        "responses"
    ]
    assert {
        int(status)
        for status in generated_responses
        if status.isdigit() and 200 <= int(status) < 300
    } == runtime_statuses

    assert (
        _documented_success_statuses(
            GENERATED_OPENAPI_PATH,
            "/api/v1/integrations/{type}",
            "put",
        )
        == runtime_statuses
    )

    for spec in (
        _load_spec(GENERATED_OPENAPI_PATH),
        generated_runtime_schema,
    ):
        responses = spec["paths"]["/api/v1/integrations/{type}"]["put"]["responses"]
        for result in runtime_results:
            payload = json.loads(result.body)
            schema = responses[str(result.status_code)]["content"]["application/json"]["schema"]
            Draft202012Validator(schema).validate(payload)
            integration = payload["integration"]
            assert integration["type"] == "email"
            assert integration["enabled"] is (result.status_code == 201)
