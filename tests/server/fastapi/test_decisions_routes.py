from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app


@pytest.fixture
def decision_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client(fastapi_context_builder, decision_service: AsyncMock) -> TestClient:
    app = create_app()
    app.state.context = fastapi_context_builder(decision_service=decision_service)
    return TestClient(app, raise_server_exceptions=False)


def test_start_decision_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v2/decisions", json={"task": "Ship it?"})

    assert response.status_code == 401


def test_list_decisions_forwards_filters(
    client: TestClient,
    decision_service: AsyncMock,
    fastapi_bearer,
) -> None:
    decision_service.list_debates.return_value = []

    response = client.get(
        "/api/v2/decisions?status=completed&limit=7", headers=fastapi_bearer("user-1", "org-1")
    )

    assert response.status_code == 200
    assert response.json() == []
    kwargs = decision_service.list_debates.await_args.kwargs
    assert kwargs["limit"] == 7
    assert kwargs["status"].value == "completed"
    assert kwargs["org_id"] == "org-1"


def test_list_decisions_rejects_malformed_status(client: TestClient, fastapi_bearer) -> None:
    response = client.get(
        "/api/v2/decisions?status=not-a-state", headers=fastapi_bearer("user-1", "org-1")
    )

    assert response.status_code == 400
    assert "Invalid status" in response.json()["detail"]


def test_get_decision_returns_404_when_missing(
    client: TestClient,
    decision_service: AsyncMock,
    fastapi_bearer,
) -> None:
    decision_service.get_debate.return_value = None

    response = client.get(
        "/api/v2/decisions/missing-debate", headers=fastapi_bearer("user-1", "org-1")
    )

    assert response.status_code == 404
    assert response.json() == {"error": "Decision not found", "code": "not_found"}


def test_list_decisions_drops_other_orgs_even_if_the_service_returns_them(
    client: TestClient,
    decision_service: AsyncMock,
    fastapi_bearer,
) -> None:
    def _state(decision_id: str, metadata: dict) -> SimpleNamespace:
        return SimpleNamespace(
            id=decision_id,
            task="t",
            status=SimpleNamespace(value="running"),
            progress=0.0,
            current_round=0,
            total_rounds=3,
            agents=[],
            result=None,
            error=None,
            created_at=None,
            updated_at=None,
            completed_at=None,
            metadata=metadata,
        )

    decision_service.list_debates.return_value = [
        _state("mine", {"org_id": "org-1"}),
        _state("theirs", {"org_id": "org-2"}),
        _state("unowned", {}),
    ]

    response = client.get("/api/v2/decisions", headers=fastapi_bearer("user-1", "org-1"))

    assert response.status_code == 200
    assert [d["id"] for d in response.json()] == ["mine"]
