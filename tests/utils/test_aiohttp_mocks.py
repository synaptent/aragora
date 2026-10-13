"""Tests for ``tests.utils.aiohttp_mocks`` and a guard against the bare
``__aexit__`` AsyncMock shape that silently swallows exceptions.

See the module docstring of ``tests/utils/aiohttp_mocks.py`` for the gotcha.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.utils.aiohttp_mocks import (
    make_async_context_manager,
    make_mock_client_session,
    make_mock_response,
)

TESTS_ROOT = Path(__file__).resolve().parents[1]


class _Boom(RuntimeError):
    pass


class TestMakeAsyncContextManager:
    @pytest.mark.asyncio
    async def test_aenter_yields_value(self):
        cm = make_async_context_manager("payload")
        async with cm as value:
            assert value == "payload"

    @pytest.mark.asyncio
    async def test_exception_inside_block_propagates(self):
        cm = make_async_context_manager("payload")
        with pytest.raises(_Boom):
            async with cm:
                raise _Boom("inside")
        cm.__aexit__.assert_awaited_once()


class TestMakeMockResponse:
    @pytest.mark.asyncio
    async def test_defaults(self):
        response = make_mock_response()
        assert response.status == 200
        assert await response.json() == {}
        assert await response.text() == ""
        assert response.headers == {}

    @pytest.mark.asyncio
    async def test_configured_fields(self):
        response = make_mock_response(
            status=429,
            json_data={"error": "rate"},
            text='{"error": "rate"}',
            headers={"Retry-After": "30"},
        )
        assert response.status == 429
        assert await response.json() == {"error": "rate"}
        assert await response.text() == '{"error": "rate"}'
        assert await response.read() == b'{"error": "rate"}'
        assert response.headers["Retry-After"] == "30"

    @pytest.mark.asyncio
    async def test_response_is_async_context_manager_that_propagates(self):
        response = make_mock_response(status=500)
        with pytest.raises(_Boom):
            async with response as resp:
                assert resp is response
                raise _Boom("inside response cm")


class TestMakeMockClientSession:
    @pytest.mark.asyncio
    async def test_post_yields_response(self):
        response = make_mock_response(json_data={"ok": True})
        session = make_mock_client_session(response)
        async with session as s:
            assert s is session
            async with s.post("https://example.invalid", json={}) as resp:
                assert resp is response
                assert await resp.json() == {"ok": True}
        session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_inside_post_block_propagates(self):
        """The regression this module guards: a raise inside the mocked
        ``async with session.post(...)`` must reach the caller."""
        session = make_mock_client_session(make_mock_response(status=500))
        with pytest.raises(_Boom, match="from handler"):
            async with session as s:
                async with s.post("https://example.invalid") as resp:
                    if resp.status != 200:
                        raise _Boom("from handler")

    @pytest.mark.asyncio
    async def test_exception_propagates_through_patched_client_session(self):
        import aiohttp

        session = make_mock_client_session(make_mock_response(status=503))
        with patch("aiohttp.ClientSession", return_value=session):
            with pytest.raises(_Boom):
                async with aiohttp.ClientSession() as s:
                    async with s.get("https://example.invalid") as resp:
                        raise _Boom(f"status {resp.status}")

    @pytest.mark.asyncio
    async def test_sequence_of_responses_served_in_order(self):
        first = make_mock_response(status=429)
        second = make_mock_response(status=200, json_data={"n": 2})
        session = make_mock_client_session([first, second])
        async with session.post("u") as r1:
            assert r1 is first
        async with session.get("u") as r2:
            assert r2 is second

    @pytest.mark.asyncio
    async def test_default_response_and_close(self):
        session = make_mock_client_session()
        async with session.get("u") as resp:
            assert resp.status == 200
        await session.close()
        session.close.assert_awaited_once()
        assert session.closed is False


class TestNoBareAsyncMockAexitInSuite:
    """Guard: nobody re-introduces a bare ``AsyncMock()`` (no ``return_value``)
    as ``__aexit__``.  Use ``make_mock_client_session`` /
    ``make_async_context_manager`` or write ``AsyncMock(return_value=False)``.
    """

    # Built from parts so this file does not itself match.
    _BARE = re.compile(r"__aexit__\s*=\s*AsyncMock\(\s*\)")

    def test_no_bare_async_mock_aexit(self):
        offenders: list[str] = []
        for path in sorted(TESTS_ROOT.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if self._BARE.search(line):
                    offenders.append(f"{path.relative_to(TESTS_ROOT.parent)}:{lineno}")
        assert not offenders, (
            "A bare AsyncMock() (no return_value) assigned to __aexit__ swallows exceptions "
            "raised inside the "
            "mocked `async with` block (truthy return suppresses them). Pin it with "
            "`AsyncMock(return_value=False)` or use tests.utils.aiohttp_mocks. "
            "Offenders:\n  " + "\n  ".join(offenders)
        )
