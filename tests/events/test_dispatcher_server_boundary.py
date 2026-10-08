"""Regression tests for the events dispatcher server-boundary inversion."""

from __future__ import annotations

import ast
import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.events.dispatcher import (
    DeliveryResult,
    WebhookDispatcher,
    register_webhook_store_provider,
)
from aragora.events.types import StreamEvent, StreamEventType


@pytest.fixture(autouse=True)
def _reset_webhook_store_provider():
    """Keep the process-wide provider registry isolated across tests."""
    register_webhook_store_provider(None)
    yield
    register_webhook_store_provider(None)


def test_dispatch_event_without_registered_provider_is_noop(caplog):
    """Library-only events usage must not require the server composition root."""
    dispatcher = WebhookDispatcher(max_workers=1)
    submit = MagicMock()
    dispatcher._executor.submit = submit

    try:
        with (
            patch("aragora.events.dispatcher.get_event_rate_limiter", return_value=None),
            caplog.at_level(logging.WARNING, logger="aragora.events.dispatcher"),
        ):
            dispatcher.dispatch_event("debates.created", {"debate_id": "d-1"})
    finally:
        dispatcher.shutdown(wait=False)

    submit.assert_not_called()
    assert not [
        record
        for record in caplog.records
        if "webhook store provider" in record.getMessage().lower()
    ]


def test_registered_provider_failure_emits_rate_limited_warning(caplog):
    """A broken registered provider warns once per throttle window."""
    dispatcher = WebhookDispatcher(max_workers=1)
    provider = MagicMock(side_effect=sqlite3.OperationalError("store unavailable"))
    register_webhook_store_provider(provider)

    try:
        with (
            patch("aragora.events.dispatcher.get_event_rate_limiter", return_value=None),
            patch("aragora.events.dispatcher.time.monotonic", side_effect=[100.0, 101.0]),
            caplog.at_level(logging.WARNING, logger="aragora.events.dispatcher"),
        ):
            dispatcher.dispatch_event("debates.created", {"debate_id": "d-1"})
            dispatcher.dispatch_event("debates.created", {"debate_id": "d-2"})
    finally:
        dispatcher.shutdown(wait=False)

    assert provider.call_count == 2
    warnings = [
        record
        for record in caplog.records
        if "webhook store provider failed" in record.getMessage().lower()
    ]
    assert len(warnings) == 1


def test_registered_provider_programming_error_propagates():
    """Unexpected provider bugs must not be hidden as storage outages."""
    dispatcher = WebhookDispatcher(max_workers=1)
    register_webhook_store_provider(
        MagicMock(side_effect=AssertionError("provider invariant failed"))
    )

    try:
        with (
            patch("aragora.events.dispatcher.get_event_rate_limiter", return_value=None),
            pytest.raises(AssertionError, match="provider invariant failed"),
        ):
            dispatcher.dispatch_event("debates.created", {"debate_id": "d-1"})
    finally:
        dispatcher.shutdown(wait=False)


def test_dispatch_event_looks_up_webhooks_through_registered_provider():
    """Dispatch lookup resolves the store exclusively through the events registry."""
    dispatcher = WebhookDispatcher(max_workers=1)
    store = MagicMock()
    store.get_for_event.return_value = []
    provider = MagicMock(return_value=store)
    register_webhook_store_provider(provider)

    try:
        with patch("aragora.events.dispatcher.get_event_rate_limiter", return_value=None):
            dispatcher.dispatch_event("debates.created", {"debate_id": "d-1"})
    finally:
        dispatcher.shutdown(wait=False)

    provider.assert_called_once_with()
    store.get_for_event.assert_called_once_with("debates.created")


def test_delivery_result_is_recorded_on_lookup_store():
    """The store used for lookup must receive the matching delivery result."""
    dispatcher = WebhookDispatcher(max_workers=1)
    webhook = MagicMock(id="wh-1", url="https://example.com/hook")
    store = MagicMock()
    store.get_for_event.return_value = [webhook]
    register_webhook_store_provider(lambda: store)
    dispatcher._executor.submit = MagicMock(side_effect=lambda callback, *args: callback(*args))

    result = DeliveryResult(
        success=False,
        status_code=503,
        error="unavailable",
        retry_count=2,
        duration_ms=25.0,
    )

    try:
        with (
            patch("aragora.events.dispatcher.get_event_rate_limiter", return_value=None),
            patch(
                "aragora.events.dispatcher.dispatch_webhook_with_retry",
                return_value=result,
            ),
        ):
            dispatcher.dispatch_event("debates.created", {"debate_id": "d-1"})
    finally:
        dispatcher.shutdown(wait=False)

    store.record_delivery.assert_called_once_with(
        webhook_id="wh-1",
        status_code=503,
        success=False,
    )


def test_subscribe_to_stream_uses_events_side_emitter_contract():
    """Emitter subscription dispatches events and remains inert after shutdown."""
    dispatcher = WebhookDispatcher(max_workers=1)
    emitter = MagicMock()
    dispatcher.dispatch_event = MagicMock()

    dispatcher.subscribe_to_stream(emitter)

    callback = emitter.subscribe.call_args.args[0]
    event = StreamEvent(
        type=StreamEventType.DEBATE_END,
        data={"debate_id": "d-1"},
    )
    callback(event)
    dispatcher.dispatch_event.assert_called_once_with("debate_end", event.to_dict())

    dispatcher.shutdown(wait=False)
    callback(event)
    dispatcher.dispatch_event.assert_called_once()


def test_dispatcher_has_no_server_emitter_or_webhook_handler_imports():
    """The lower-layer dispatcher must not import either server-owned surface."""
    dispatcher_path = Path(__file__).parents[2] / "aragora" / "events" / "dispatcher.py"
    tree = ast.parse(dispatcher_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "aragora.server.stream.emitter" not in imported_modules
    assert "aragora.server.handlers.webhooks" not in imported_modules
