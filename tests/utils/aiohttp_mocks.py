"""Mock builders for ``aiohttp.ClientSession`` and its responses.

Gotcha this module exists to prevent
==================================

A hand-rolled aiohttp mock usually assigns a bare ``AsyncMock()`` (no
``return_value``) to ``__aexit__`` on both the session and the
``session.post(...)`` context manager.  That swallows exceptions:

``AsyncMock()`` with no ``return_value`` resolves to a fresh ``MagicMock`` when
awaited, and a ``MagicMock`` is truthy.  Under the ``async with`` protocol a
truthy ``__aexit__`` return means "I handled the exception", so every
exception raised inside the mocked ``async with session.post(...)`` block is
silently discarded and the surrounding call returns ``None``.  A test written
as ``with pytest.raises(AgentAPIError)`` then reports ``DID NOT RAISE`` even
though the ``raise`` executed, and a test that merely asserts on the result
passes for the wrong reason.

The real ``aiohttp`` context managers return ``None`` from ``__aexit__``, so
the builders here pin ``__aexit__`` to ``AsyncMock(return_value=False)``.  Use
them instead of copy-pasting the shape above.

Usage::

    from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response

    response = make_mock_response(status=500, text="Server Error")
    session = make_mock_client_session(response)
    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(AgentAPIError):
            await agent.generate("prompt")

Pass a list of responses to serve them in order across successive calls, or
override a verb after construction for connection-level failures::

    session = make_mock_client_session([first_response, second_response])
    session.post = MagicMock(side_effect=aiohttp.ClientConnectorError(...))
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from unittest.mock import AsyncMock, MagicMock

HTTP_VERBS: tuple[str, ...] = ("get", "post", "put", "patch", "delete", "head", "request")


def make_async_context_manager(value: Any) -> MagicMock:
    """Return a ``MagicMock`` usable as ``async with cm as value``.

    ``__aexit__`` is pinned falsy so exceptions raised inside the block
    propagate exactly as they would through a real aiohttp context manager.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def make_mock_response(
    *,
    status: int = 200,
    json_data: Any = None,
    text: str = "",
    headers: Mapping[str, str] | None = None,
    content: Any = None,
) -> MagicMock:
    """Build a mock ``aiohttp.ClientResponse``.

    ``json()`` and ``text()`` are awaitable.  ``content`` (for streaming tests)
    is attached verbatim when given.  The response is itself an async context
    manager so it works both as ``session.post(...)`` return value and when a
    test awaits ``__aenter__`` directly.
    """
    response = MagicMock()
    response.status = status
    response.headers = dict(headers or {})
    response.json = AsyncMock(return_value={} if json_data is None else json_data)
    response.text = AsyncMock(return_value=text)
    response.read = AsyncMock(return_value=text.encode("utf-8"))
    if content is not None:
        response.content = content
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


def make_mock_client_session(
    response: Any = None,
    *,
    verbs: Iterable[str] = HTTP_VERBS,
) -> MagicMock:
    """Build a mock ``aiohttp.ClientSession``.

    Args:
        response: A single mock response served for every call, or a sequence
            of responses served in order (one per call, across all verbs).
            ``None`` serves a bare ``make_mock_response()``.
        verbs: HTTP method names to wire up (default: all common verbs).

    Every configured verb returns an async context manager whose
    ``__aenter__`` yields the response and whose ``__aexit__`` is falsy, so
    exceptions raised inside ``async with session.post(...) as resp:`` reach
    the caller.  The session is also an async context manager yielding itself,
    and exposes an awaitable ``close()``.
    """
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.close = AsyncMock(return_value=None)
    session.closed = False

    if response is None:
        response = make_mock_response()

    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        shared_side_effect = [make_async_context_manager(r) for r in response]
        # One shared iterator so ordering holds across verbs.
        iterator = iter(shared_side_effect)
        for verb in verbs:
            setattr(session, verb, MagicMock(side_effect=lambda *a, **k: next(iterator)))
    else:
        for verb in verbs:
            setattr(
                session,
                verb,
                MagicMock(return_value=make_async_context_manager(response)),
            )
    return session


__all__ = [
    "HTTP_VERBS",
    "make_async_context_manager",
    "make_mock_client_session",
    "make_mock_response",
]
