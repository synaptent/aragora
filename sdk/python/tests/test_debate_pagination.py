"""Debate pagination contracts from CrudOperationsMixin._list_debates envelopes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora_sdk.exceptions import AragoraError, ConnectionError
from aragora_sdk.namespaces.debates import AsyncDebatesAPI, DebatesAPI
from aragora_sdk.pagination import AsyncPaginator, SyncPaginator

pytestmark = pytest.mark.asyncio


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def client_api(request: Any) -> tuple[Any, Any]:
    client = MagicMock()
    if request.param:
        client.request = AsyncMock()
        return client, AsyncDebatesAPI(client)
    return client, DebatesAPI(client)


async def pull(paginator: Any) -> dict[str, Any]:
    return await paginator.__anext__() if isinstance(paginator, AsyncPaginator) else next(paginator)


async def collect(paginator: Any) -> list[dict[str, Any]]:
    if isinstance(paginator, AsyncPaginator):
        return [item async for item in paginator]
    return list(paginator)


async def test_server_envelope_preserves_items_metadata_and_filters(client_api: Any) -> None:
    client, api = client_api
    items = [{"id": "a", "status": "failed", "agent_failures": [{"phase": "vote"}]}, {"id": "b"}]
    client.request.side_effect = [
        {"debates": items, "count": 2, "total": 3, "has_more": True, "offset": 0, "limit": 2},
        {
            "debates": [{"id": "c"}],
            "count": 1,
            "total": 3,
            "has_more": False,
            "offset": 2,
            "limit": 2,
        },
    ]
    paginator = api.list_all(status="completed", page_size=2)
    assert await collect(paginator) == [*items, {"id": "c"}]
    assert paginator.total == 3
    assert [c.kwargs["params"] for c in client.request.call_args_list] == [
        {"status": "completed", "limit": 2, "offset": 0},
        {"status": "completed", "limit": 2, "offset": 2},
    ]
    assert all(c.args == ("GET", "/api/v1/debates") for c in client.request.call_args_list)
    assert await collect(paginator) == []
    assert client.request.call_count == 2


async def test_server_clamped_short_page_does_not_lose_remainder(client_api: Any) -> None:
    client, api = client_api
    # DebatesHandler clamps limit to 100 even when the caller asks for 200.
    first = [{"id": str(i)} for i in range(100)]
    client.request.side_effect = [
        {"debates": first, "total": 101, "has_more": True, "limit": 100, "offset": 0},
        {"debates": [{"id": "100"}], "total": 101, "has_more": False, "limit": 100, "offset": 100},
    ]
    assert len(await collect(api.list_all(page_size=200))) == 101
    assert [c.kwargs["params"]["offset"] for c in client.request.call_args_list] == [0, 100]


async def test_total_without_has_more_retains_short_page_remainder(client_api: Any) -> None:
    client, api = client_api
    client.request.side_effect = [
        {"debates": [{"id": "a"}], "total": 2},
        {"debates": [{"id": "b"}], "total": 2},
    ]
    assert await collect(api.list_all(page_size=20)) == [{"id": "a"}, {"id": "b"}]
    assert client.request.call_count == 2


@pytest.mark.parametrize(
    "page",
    [
        {"debates": [], "total": 0, "has_more": False},
        {"debates": []},
    ],
)
async def test_genuine_empty_page_terminates(client_api: Any, page: Any) -> None:
    client, api = client_api
    client.request.return_value = page
    assert await collect(api.list_all()) == []
    assert client.request.call_count == 1


@pytest.mark.parametrize(
    "page",
    [
        {"debates": [{"id": "a"}], "total": 1},
        {"debates": [{"id": "a"}], "has_more": False},
        {"debates": [{"id": "a"}]},
    ],
)
async def test_legacy_metadata_is_optional(client_api: Any, page: Any) -> None:
    client, api = client_api
    client.request.return_value = page
    assert await collect(api.list_all()) == [{"id": "a"}]
    assert client.request.call_count == 1


@pytest.mark.parametrize(
    "page",
    [
        None,
        "private-payload",
        [],
        {},
        {"items": []},
        {"data": []},
        {"debates": None},
        {"debates": "private-payload"},
        {"debates": {"id": "a"}},
        {"debates": [None]},
        {"debates": ["private-payload"]},
        {"debates": [], "total": "2"},
        {"debates": [], "total": True},
        {"debates": [], "total": -1},
        {"debates": [], "has_more": "false"},
        {"debates": [], "has_more": True},
    ],
)
async def test_invalid_envelope_is_typed_failure_not_empty_success(
    client_api: Any, page: Any
) -> None:
    client, api = client_api
    client.request.return_value = page
    with pytest.raises(AragoraError) as error:
        await collect(api.list_all())
    assert "private-payload" not in str(error.value)
    assert error.value.response_body is None
    assert client.request.call_count == 1


async def test_later_bad_page_preserves_already_delivered_work(client_api: Any) -> None:
    client, api = client_api
    client.request.side_effect = [
        {"debates": [{"id": "a"}], "has_more": True},
        {"items": [{"id": "wrong-envelope"}]},
    ]
    paginator = api.list_all(page_size=1)
    assert await pull(paginator) == {"id": "a"}
    with pytest.raises(AragoraError):
        await pull(paginator)


async def test_transport_error_identity_is_preserved(client_api: Any) -> None:
    client, api = client_api
    failure = ConnectionError("offline")
    client.request.side_effect = failure
    with pytest.raises(ConnectionError) as error:
        await collect(api.list_all())
    assert error.value is failure


@pytest.mark.parametrize("page_size", [0, -1, True, 1.5])
async def test_invalid_page_size_fails_before_request(client_api: Any, page_size: Any) -> None:
    client, api = client_api
    with pytest.raises(AragoraError):
        api.list_all(page_size=page_size)
    client.request.assert_not_called()


@pytest.mark.parametrize(
    "response", [[{"id": "a"}], {"items": [{"id": "a"}]}, {"data": [{"id": "a"}]}]
)
async def test_generic_paginator_compatibility(client_api: Any, response: Any) -> None:
    client, api = client_api
    client.request.return_value = response
    paginator = (AsyncPaginator if isinstance(api, AsyncDebatesAPI) else SyncPaginator)(
        client, "/items"
    )
    assert await collect(paginator) == [{"id": "a"}]
