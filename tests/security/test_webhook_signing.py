"""Regression tests for the shared webhook HMAC signing surface."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("payload", "secret", "expected"),
    [
        (
            "",
            "",
            "sha256=b613679a0814d9ec772f95d778c35fc5ff1697c493715653c6c712144292c5ad",
        ),
        (
            "payload",
            "secret",
            "sha256=b82fcb791acec57859b989b430a826488ce2e479fdf92326bd0a2e8375a42ba4",
        ),
        (
            '{"event":"debate_end","message":"café ☕"}',
            "sëcret-🔐",
            "sha256=f8f58ceadd5694429203e199c2a1ee5132dc175bd47f05a31f3a811368c23223",
        ),
    ],
)
def test_signature_output_is_byte_identical(payload: str, secret: str, expected: str) -> None:
    """The downshift must preserve the handler's exact historical output."""
    from aragora.security.webhook_signing import generate_signature

    assert generate_signature(payload, secret) == expected


def test_legacy_handler_signature_warns_and_delegates() -> None:
    """The old server surface remains usable and points callers to the new home."""
    from aragora.security.webhook_signing import generate_signature as canonical
    from aragora.server.handlers.webhook_management import generate_signature as legacy

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        actual = legacy("payload", "secret")

    assert actual == canonical("payload", "secret")
    messages = [
        str(item.message) for item in captured if issubclass(item.category, DeprecationWarning)
    ]
    assert any(
        "aragora.server.handlers.webhooks.generate_signature" in message
        and "aragora.security.webhook_signing.generate_signature" in message
        for message in messages
    )


def test_events_verifier_reuses_canonical_signer() -> None:
    """Webhook verification and delivery share one signing implementation."""
    from aragora.events.webhook_verify import generate_signature as event_signer
    from aragora.security.webhook_signing import generate_signature as canonical

    assert event_signer is canonical


@pytest.mark.parametrize(
    "module_name",
    ["aragora.events.dispatcher", "aragora.events.async_dispatcher"],
)
def test_event_dispatchers_do_not_import_server_signer(module_name: str) -> None:
    """Infrastructure dispatchers must not reach up into the server layer."""
    module = __import__(module_name, fromlist=["__file__"])
    module_file = module.__file__
    assert module_file is not None
    source = Path(module_file).read_text(encoding="utf-8")

    assert "from aragora.server.handlers.webhooks import generate_signature" not in source
    assert "from aragora.security.webhook_signing import generate_signature" in source


def test_retry_queue_does_not_import_server_signer() -> None:
    """The webhook retry queue signs through the security layer, not the server layer."""
    module = __import__("aragora.webhooks.retry_queue", fromlist=["__file__"])
    module_file = module.__file__
    assert module_file is not None
    source = Path(module_file).read_text(encoding="utf-8")

    assert "from aragora.server.handlers.webhook_management import" not in source
    assert "from aragora.server.handlers.webhooks import" not in source
    assert "from aragora.security.webhook_signing import" in source
