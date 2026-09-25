"""Exercise the real file loader through the public key handlers."""

import json
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization

from aragora.gauntlet.odr_signing import compute_key_id, public_key_pem
from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast
from aragora.server.handlers.receipts import ReceiptsHandler
from tests.gauntlet.odr_test_keys import odr_test_key


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "missing", "garbage", "empty", "unset"])
async def test_key_routes_and_readiness_are_independent(tmp_path, monkeypatch, mode):
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_FILE", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_SECRET", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    path = tmp_path / "key.pem"
    key = odr_test_key()
    if mode == "valid":
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    elif mode == "garbage":
        path.write_text("not a key")
    if path.is_file():
        path.chmod(0o600)
    if mode != "unset":
        monkeypatch.setenv("ARAGORA_ODR_SIGNING_KEY_FILE", "" if mode == "empty" else str(path))
    handler = ReceiptsHandler({})
    handler._signing_key_cache = None
    expected = 200 if mode == "valid" else 404
    pem = await handler.handle("GET", "/.well-known/aragora-odr-signing-key")
    envelope = await handler.handle("GET", "/api/v2/receipts/signing-key")
    assert pem.status_code == envelope.status_code == expected
    assert b"PRIVATE" not in pem.body + envelope.body
    if mode == "valid":
        assert pem.body == public_key_pem(key).encode()
        assert pem.headers["X-Aragora-Key-Id"] == compute_key_id(key.public_key())
        assert json.loads(envelope.body)["algorithm"] == "Ed25519"
    ready_handler = MagicMock()
    ready_handler.can_handle.return_value = True
    with (
        patch("aragora.server.handlers.admin.health._get_cached_health", return_value=None),
        patch("aragora.server.handlers.admin.health._set_cached_health"),
        patch("aragora.server.degraded_mode.is_degraded", return_value=False),
    ):
        ready = readiness_probe_fast(ready_handler)
    assert ready.status_code == 200
    assert json.loads(ready.body)["status"] == "ready"
