"""
Aragora Pagination Helpers

Provides auto-paginating iterators for list endpoints, allowing users to
iterate through all results without manually handling pagination.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

from .exceptions import AragoraError

if TYPE_CHECKING:
    from .client import AragoraAsyncClient, AragoraClient


def _named_page(
    response: Any, items_key: str, offset: int, page_size: int
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """Validate an opted-in endpoint envelope before changing iterator state."""
    if not isinstance(response, dict) or not isinstance(response.get(items_key), list):
        raise AragoraError("Invalid pagination response: expected named item list")
    items = response[items_key]
    if any(not isinstance(item, dict) for item in items):
        raise AragoraError("Invalid pagination response: expected object items")
    total = response.get("total")
    if total is not None and (type(total) is not int or total < 0):
        raise AragoraError("Invalid pagination response: expected non-negative total")
    next_offset = offset + len(items)
    if total is not None and (next_offset > total or (not items and next_offset < total)):
        raise AragoraError("Invalid pagination response: inconsistent total")
    if "has_more" in response:
        has_more = response["has_more"]
        if not isinstance(has_more, bool) or (has_more and not items):
            raise AragoraError("Invalid pagination response: inconsistent has_more")
        if total is not None and has_more != (next_offset < total):
            raise AragoraError("Invalid pagination response: inconsistent has_more")
        # Servers may clamp the requested limit; a short page can still continue.
        exhausted = not has_more
    elif total is not None:
        exhausted = next_offset >= total
    else:
        exhausted = len(items) < page_size
    return items, total, exhausted


class SyncPaginator(Iterator[dict[str, Any]]):
    """Auto-paginating synchronous iterator for list endpoints.

    Automatically fetches additional pages as needed while iterating.

    Example::

        for debate in client.debates.list_all(status="active"):
            print(debate["id"])
    """

    def __init__(
        self,
        client: AragoraClient,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = 20,
        *,
        items_key: str | None = None,
    ) -> None:
        """Initialize the paginator.

        Args:
            client: The AragoraClient instance to use for requests.
            path: The API endpoint path.
            params: Additional query parameters to include in requests.
            page_size: Number of items to fetch per page.
            items_key: Opt into a named object-list envelope with validated metadata.
                Omit to retain the generic items/data/raw-list response formats.
        """
        if items_key is not None and (type(page_size) is not int or page_size <= 0):
            raise AragoraError("Pagination page_size must be a positive integer")
        self._items_key = items_key
        self._client = client
        self._path = path
        self._params = params or {}
        self._page_size = page_size
        self._offset = 0
        self._buffer: list[dict[str, Any]] = []
        self._exhausted = False
        self._total: int | None = None

    def __iter__(self) -> SyncPaginator:
        return self

    def __next__(self) -> dict[str, Any]:
        if not self._buffer:
            if self._exhausted:
                raise StopIteration
            self._fetch_page()
        if not self._buffer:
            raise StopIteration
        return self._buffer.pop(0)

    def _fetch_page(self) -> None:
        """Fetch the next page of results."""
        params = {
            **self._params,
            "limit": self._page_size,
            "offset": self._offset,
        }
        response = self._client.request("GET", self._path, params=params)

        if self._items_key is not None:
            page, total, exhausted = _named_page(
                response, self._items_key, self._offset, self._page_size
            )
            self._buffer.extend(page)
            self._offset += len(page)
            self._total = total
            self._exhausted = exhausted
            return

        # Handle different response formats
        if isinstance(response, dict):
            raw_items = response.get("items", response.get("data", []))
            items: list[dict[str, Any]] = raw_items if raw_items is not None else []
            self._total = response.get("total")
        else:
            items = response if isinstance(response, list) else []

        if items:
            self._buffer.extend(items)
            self._offset += len(items)

            # Check if we've exhausted all results
            if len(items) < self._page_size:
                self._exhausted = True
            elif self._total is not None and self._offset >= self._total:
                self._exhausted = True
        else:
            self._exhausted = True

    @property
    def total(self) -> int | None:
        """Return the total number of items, if known from the API response."""
        return self._total


class AsyncPaginator(AsyncIterator[dict[str, Any]]):
    """Auto-paginating asynchronous iterator for list endpoints.

    Automatically fetches additional pages as needed while iterating.

    Example::

        async for debate in client.debates.list_all(status="active"):
            print(debate["id"])
    """

    def __init__(
        self,
        client: AragoraAsyncClient,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = 20,
        *,
        items_key: str | None = None,
    ) -> None:
        """Initialize the paginator.

        Args:
            client: The AragoraAsyncClient instance to use for requests.
            path: The API endpoint path.
            params: Additional query parameters to include in requests.
            page_size: Number of items to fetch per page.
            items_key: Opt into a named object-list envelope with validated metadata.
                Omit to retain the generic items/data/raw-list response formats.
        """
        if items_key is not None and (type(page_size) is not int or page_size <= 0):
            raise AragoraError("Pagination page_size must be a positive integer")
        self._items_key = items_key
        self._client = client
        self._path = path
        self._params = params or {}
        self._page_size = page_size
        self._offset = 0
        self._buffer: list[dict[str, Any]] = []
        self._exhausted = False
        self._total: int | None = None

    def __aiter__(self) -> AsyncPaginator:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._buffer:
            if self._exhausted:
                raise StopAsyncIteration
            await self._fetch_page()
        if not self._buffer:
            raise StopAsyncIteration
        return self._buffer.pop(0)

    async def _fetch_page(self) -> None:
        """Fetch the next page of results."""
        params = {
            **self._params,
            "limit": self._page_size,
            "offset": self._offset,
        }
        response = await self._client.request("GET", self._path, params=params)

        if self._items_key is not None:
            page, total, exhausted = _named_page(
                response, self._items_key, self._offset, self._page_size
            )
            self._buffer.extend(page)
            self._offset += len(page)
            self._total = total
            self._exhausted = exhausted
            return

        # Handle different response formats
        if isinstance(response, dict):
            raw_items = response.get("items", response.get("data", []))
            items: list[dict[str, Any]] = raw_items if raw_items is not None else []
            self._total = response.get("total")
        else:
            items = response if isinstance(response, list) else []

        if items:
            self._buffer.extend(items)
            self._offset += len(items)

            # Check if we've exhausted all results
            if len(items) < self._page_size:
                self._exhausted = True
            elif self._total is not None and self._offset >= self._total:
                self._exhausted = True
        else:
            self._exhausted = True

    @property
    def total(self) -> int | None:
        """Return the total number of items, if known from the API response."""
        return self._total
