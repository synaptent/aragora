"""Tests for ``tests.utils.async_helpers.close_coroutine_then``."""

from __future__ import annotations

import asyncio
import warnings
from unittest.mock import MagicMock, patch

import pytest

from tests.utils.async_helpers import close_coroutine_then


async def _work() -> str:
    return "ran"


def test_returns_result_and_closes_coroutine():
    coro = _work()
    side_effect = close_coroutine_then("stubbed")
    assert side_effect(coro) == "stubbed"
    # A closed coroutine cannot be resumed.
    with pytest.raises(RuntimeError, match="cannot reuse already awaited coroutine"):
        asyncio.run(coro)


def test_raises_after_closing_coroutine():
    coro = _work()
    side_effect = close_coroutine_then(raise_=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        side_effect(coro)
    with pytest.raises(RuntimeError, match="cannot reuse already awaited coroutine"):
        asyncio.run(coro)


def test_non_coroutine_argument_is_left_alone():
    sentinel = object()
    assert close_coroutine_then(7)(sentinel) == 7


def test_patched_runner_emits_no_never_awaited_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with patch("asyncio.run", side_effect=close_coroutine_then(MagicMock())):
            asyncio.run(_work())
        import gc

        gc.collect()
    assert not [w for w in caught if "never awaited" in str(w.message)]
