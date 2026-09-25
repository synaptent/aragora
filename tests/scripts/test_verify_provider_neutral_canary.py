from __future__ import annotations

import base64
import hashlib
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.verify_provider_neutral_canary as verifier
from aragora.gauntlet.odr_signing import (
    generate_signing_key,
    public_key_pem,
    sign_odr_receipt,
)
from scripts.verify_provider_neutral_canary import Response, _write_state, run_verification
from scripts.validate_provider_neutral_canary import _PROVIDER_FILES, _REQUIRED_FILES
from tests.gauntlet.test_odr_signing import _valid_odr

IMAGE = "ghcr.io/synaptent/aragora@sha256:" + "a" * 64
SHA = "b" * 40
TOKEN = "ara_private_canary_token_123456"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_provider_neutral_canary.py"


class FakeTransport:
    def __init__(self, pem: str, *, build_sha: str = SHA) -> None:
        from cryptography.hazmat.primitives import serialization

        public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
        from aragora.gauntlet.odr_signing import compute_key_id

        self.pem = pem
        self.key_id = compute_key_id(public_key)
        self.build_sha = build_sha
        self.webhook_id = "probe-123"
        self.callback_url = ""
        self.auth_headers: list[str] = []
        self.webhook_events: list[str] = []
        self.webhook_name = ""
        self.read_overrides: dict[str, object] = {}
        self.delete_calls = 0

    @staticmethod
    def _response(status: int, payload=None, headers=None) -> Response:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return Response(status, headers or {}, body)

    def request(self, method, url, *, headers=None, payload=None) -> Response:
        if headers and "Authorization" in headers:
            self.auth_headers.append(headers["Authorization"])
        path = url.split("?", 1)[0]
        if path.endswith("/healthz"):
            return self._response(200)
        if path.endswith("/api/health"):
            return self._response(200, {"status": "healthy"})
        if path.endswith("/health/build"):
            return self._response(200, {"sha": self.build_sha})
        if path.endswith("/api/v2/receipts/signing-key"):
            return self._response(
                200,
                {
                    "algorithm": "Ed25519",
                    "key_id": self.key_id,
                    "public_key_pem": self.pem,
                },
            )
        if path.endswith("/.well-known/aragora-odr-signing-key"):
            return Response(200, {"X-Aragora-Key-Id": self.key_id}, self.pem.encode("utf-8"))
        if method == "POST" and path.endswith("/api/v1/webhook-configs"):
            assert set(payload) == {"url", "events", "name"}
            assert payload["events"] == ["canary_probe"]
            assert payload["name"].startswith("canary-")
            self.callback_url = payload["url"]
            self.webhook_events = list(payload["events"])
            self.webhook_name = payload["name"]
            return self._response(
                201,
                {
                    "webhook": {
                        "id": self.webhook_id,
                        "url": self.callback_url,
                        "secret": "must-not-appear-in-report",
                    }
                },
            )
        if method == "GET" and path.endswith(f"/api/v1/webhook-configs/{self.webhook_id}"):
            webhook: dict[str, object] = {
                "id": self.webhook_id,
                "url": self.callback_url,
                "events": self.webhook_events,
                "name": self.webhook_name,
            }
            webhook.update(self.read_overrides)
            return self._response(200, {"webhook": webhook})
        if method == "DELETE" and path.endswith(f"/api/v1/webhook-configs/{self.webhook_id}"):
            self.delete_calls += 1
            return self._response(204)
        return self._response(404)


class PersistenceForbiddenTransport(FakeTransport):
    def request(self, method, url, *, headers=None, payload=None):
        if "/api/v1/webhook-configs" in url:
            raise AssertionError("persistence network method called without valid custody")
        return super().request(method, url, headers=headers, payload=payload)


def _args(tmp_path: Path, receipt_path: Path, phase: str) -> argparse.Namespace:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    secret_dir.chmod(0o700)
    for name in _REQUIRED_FILES:
        value = "managed-test-value"
        if name == "canary-auth-token":
            value = TOKEN
        elif name == "ARAGORA_API_TOKEN":
            value = "different-bootstrap-value"
        path = secret_dir / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
    provider_path = secret_dir / sorted(_PROVIDER_FILES)[0]
    provider_path.write_text("managed-provider-value", encoding="utf-8")
    provider_path.chmod(0o600)
    return argparse.Namespace(
        phase=phase,
        base_url="https://canary.example.invalid",
        expected_sha=SHA,
        expected_image_digest=IMAGE,
        observed_image_digest=IMAGE,
        database_proof_id="snapshot-proof-123",
        secrets_dir=str(secret_dir),
        receipt_file=str(receipt_path),
        persistence_state=str(tmp_path / "persistence.json"),
        output=str(tmp_path / f"{phase}.json"),
        runtime_uid=os.geteuid(),
        runtime_gid=os.getegid(),
    )


def _receipt(tmp_path: Path):
    key = generate_signing_key()
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(sign_odr_receipt(_valid_odr(), key)), encoding="utf-8")
    return key, receipt_path


def test_direct_help_entrypoint_from_repo_root() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = ""

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--phase" in result.stdout
    assert "--persistence-state" in result.stdout


def _mock_websocket_exchange(monkeypatch, nonce: bytes, response_chunks: list[bytes]):
    class FakeSocket:
        def __init__(self, chunks: list[bytes]) -> None:
            self.chunks = list(chunks)
            self.sent = b""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def sendall(self, request: bytes) -> None:
            self.sent = request

        def recv(self, size: int) -> bytes:
            if not self.chunks:
                return b""
            chunk = self.chunks.pop(0)
            result = chunk[:size]
            if len(chunk) > size:
                self.chunks.insert(0, chunk[size:])
            return result

    raw = FakeSocket([])
    secured = FakeSocket(response_chunks)

    class FakeTLSContext:
        def wrap_socket(self, sock, *, server_hostname):
            assert sock is raw
            assert server_hostname == "canary.example.invalid"
            return secured

    monkeypatch.setattr(verifier.os, "urandom", lambda size: nonce)
    monkeypatch.setattr(
        verifier.socket,
        "create_connection",
        lambda address, timeout: raw,
    )
    monkeypatch.setattr(verifier.ssl, "create_default_context", FakeTLSContext)
    result = verifier._check_websocket("https://canary.example.invalid")
    return result, secured.sent


def test_websocket_validates_complete_rfc6455_handshake(monkeypatch) -> None:
    nonce = b"0123456789abcdef"
    key = base64.b64encode(nonce).decode("ascii")
    accept = base64.b64encode(
        hashlib.sha1(
            (key + verifier._WEBSOCKET_GUID).encode("ascii"), usedforsecurity=False
        ).digest()
    )
    response = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"uPgRaDe: WebSocket\r\n"
        b"cOnNeCtIoN: keep-alive, UpGrAdE\r\n"
        b"sEc-WeBsOcKeT-aCcEpT: " + accept + b"\r\n\r\nignored-body"
    )

    result, request = _mock_websocket_exchange(
        monkeypatch, nonce, [response[:25], response[25:71], response[71:]]
    )

    assert result == {
        "ok": True,
        "status_line": "HTTP/1.1 101 Switching Protocols",
        "url": "wss://canary.example.invalid/ws",
    }
    assert b"Origin: https://canary.example.invalid\r\n" in request


def test_websocket_rejects_forged_101_accept(monkeypatch) -> None:
    response = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: upgrade\r\n"
        b"Sec-WebSocket-Accept: AAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\n\r\n"
    )

    result, _request = _mock_websocket_exchange(monkeypatch, b"0123456789abcdef", [response])

    assert result["ok"] is False


def test_before_and_after_restart_proof(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    transport = FakeTransport(public_key_pem(key))
    before_args = _args(tmp_path, receipt_path, "before-restart")

    before = run_verification(before_args, transport)

    assert before["ok"] is True
    state_path = Path(before_args.persistence_state)
    assert state_path.stat().st_mode & 0o777 == 0o600
    after_args = _args(tmp_path, receipt_path, "after-restart")
    after_args.persistence_state = str(state_path)
    after = run_verification(after_args, transport)
    assert after["ok"] is True
    assert transport.auth_headers
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["expected_url"] == transport.callback_url
    assert state["expected_events"] == ["canary_probe"]
    assert state["expected_name"] == f"canary-{state['marker']}"
    assert state["webhook_id"] == transport.webhook_id
    assert state["endpoint"] == "/api/v1/webhook-configs"
    assert TOKEN not in json.dumps(before)
    assert "must-not-appear-in-report" not in json.dumps(before)


def test_non_exact_build_sha_fails_closed(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    transport = FakeTransport(public_key_pem(key), build_sha=SHA + "-unexpected-suffix")

    report = run_verification(_args(tmp_path, receipt_path, "before-restart"), transport)

    assert report["ok"] is False
    assert report["checks"]["build"]["ok"] is False


@pytest.mark.parametrize(
    ("field", "mismatched_value"),
    [
        ("events", ["canary_probe", "debate_end"]),
        ("name", "forged-canary-name"),
    ],
)
def test_before_restart_metadata_mismatch_fails_and_cleans_up(
    tmp_path: Path, field: str, mismatched_value: object
) -> None:
    key, receipt_path = _receipt(tmp_path)
    transport = FakeTransport(public_key_pem(key))
    transport.read_overrides[field] = mismatched_value
    args = _args(tmp_path, receipt_path, "before-restart")

    report = run_verification(args, transport)

    assert report["ok"] is False
    assert report["checks"]["persistence"] == {
        "ok": False,
        "create_status": 201,
        "read_status": 200,
        "cleanup_status": 204,
    }
    assert transport.delete_calls == 1
    assert not Path(args.persistence_state).exists()


@pytest.mark.parametrize(
    ("field", "mismatched_value"),
    [
        ("events", []),
        ("name", "forged-canary-name"),
    ],
)
def test_after_restart_metadata_mismatch_fails_but_deletes(
    tmp_path: Path, field: str, mismatched_value: object
) -> None:
    key, receipt_path = _receipt(tmp_path)
    transport = FakeTransport(public_key_pem(key))
    before_args = _args(tmp_path, receipt_path, "before-restart")
    assert run_verification(before_args, transport)["ok"] is True
    transport.read_overrides[field] = mismatched_value
    transport.delete_calls = 0
    after_args = _args(tmp_path, receipt_path, "after-restart")
    after_args.persistence_state = before_args.persistence_state

    report = run_verification(after_args, transport)

    assert report["ok"] is False
    assert report["checks"]["persistence"] == {
        "ok": False,
        "read_status": 200,
        "delete_status": 204,
    }
    assert transport.delete_calls == 1


def test_image_or_database_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    transport = FakeTransport(public_key_pem(key))
    args = _args(tmp_path, receipt_path, "before-restart")
    args.observed_image_digest = "ghcr.io/synaptent/aragora@sha256:" + "d" * 64

    report = run_verification(args, transport)

    assert report["ok"] is False
    assert report["checks"]["identity"]["ok"] is False


def test_signing_key_endpoint_mismatch_fails_closed(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    transport = FakeTransport(public_key_pem(key))
    transport.key_id = "ed25519-wrong"

    report = run_verification(_args(tmp_path, receipt_path, "before-restart"), transport)

    assert report["ok"] is False
    assert report["checks"]["signing_keys"]["ok"] is False


def test_missing_token_is_recorded_in_failed_artifact(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    (Path(args.secrets_dir) / "canary-auth-token").unlink()

    report = run_verification(args, FakeTransport(public_key_pem(key)))

    assert report["ok"] is False
    assert report["checks"]["custody"]["ok"] is False
    assert report["checks"]["custody"]["error_type"] == "CustodyValidationError"


def test_auth_failure_skips_persistence_network(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    (Path(args.secrets_dir) / "canary-auth-token").unlink()

    report = run_verification(args, PersistenceForbiddenTransport(public_key_pem(key)))

    assert report["ok"] is False
    assert report["checks"]["persistence"] == {
        "ok": False,
        "error_type": "AuthUnavailable",
    }


def test_missing_database_custody_file_blocks_auth_and_persistence(
    tmp_path: Path, monkeypatch
) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    (Path(args.secrets_dir) / "DATABASE_URL").unlink()
    monkeypatch.setattr(
        verifier,
        "_load_auth_token",
        lambda _path: (_ for _ in ()).throw(AssertionError("auth must not be loaded")),
    )

    transport = PersistenceForbiddenTransport(public_key_pem(key))
    report = run_verification(args, transport)

    assert report["checks"]["custody"]["error_type"] == "CustodyValidationError"
    assert report["checks"]["custody"]["errors"] == ["missing required custody file: DATABASE_URL"]
    assert report["checks"]["persistence"]["error_type"] == "AuthUnavailable"
    assert not transport.auth_headers
    assert "managed-test-value" not in json.dumps(report)


def test_missing_provider_custody_file_blocks_persistence(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    for name in _PROVIDER_FILES:
        provider_path = Path(args.secrets_dir) / name
        if provider_path.exists():
            provider_path.unlink()

    transport = PersistenceForbiddenTransport(public_key_pem(key))
    report = run_verification(args, transport)

    assert report["checks"]["custody"]["error_type"] == "CustodyValidationError"
    assert report["checks"]["custody"]["errors"] == [
        "at least one managed AI provider key file is required"
    ]
    assert report["checks"]["persistence"]["error_type"] == "AuthUnavailable"
    assert not transport.auth_headers
    assert "managed-provider-value" not in json.dumps(report)


def test_custody_ownership_mismatch_blocks_persistence(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    args.runtime_uid = os.geteuid() + 1
    args.runtime_gid = os.getegid() + 1

    transport = PersistenceForbiddenTransport(public_key_pem(key))
    report = run_verification(args, transport)

    custody = report["checks"]["custody"]
    assert custody["error_type"] == "CustodyValidationError"
    assert custody["errors"] == ["custody directory ownership does not match runtime UID/GID"]
    assert report["checks"]["persistence"]["error_type"] == "AuthUnavailable"
    assert not transport.auth_headers


def test_transport_exception_is_recorded_without_secret_text(tmp_path: Path) -> None:
    _, receipt_path = _receipt(tmp_path)

    class BrokenTransport:
        def request(self, *args, **kwargs):
            raise OSError(f"network failed with {TOKEN}")

    report = run_verification(_args(tmp_path, receipt_path, "before-restart"), BrokenTransport())

    assert report["ok"] is False
    serialized = json.dumps(report)
    assert "OSError" in serialized
    assert TOKEN not in serialized


def test_http_origin_is_rejected_before_token_use(tmp_path: Path) -> None:
    _, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    args.base_url = "http://canary.example.invalid"

    class UnusedTransport:
        def request(self, *args, **kwargs):
            raise AssertionError("invalid HTTP origin reached the network")

    report = run_verification(args, UnusedTransport())

    assert report["ok"] is False
    assert report["checks"]["inputs"]["ok"] is False


def test_report_file_is_owner_only(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    _write_state(output, {"ok": False})
    assert output.stat().st_mode & 0o777 == 0o600


def test_invalid_auth_token_is_recorded(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    token_path = Path(args.secrets_dir) / "canary-auth-token"
    token_path.write_text("server-bootstrap-token", encoding="utf-8")
    token_path.chmod(0o600)

    report = run_verification(args, FakeTransport(public_key_pem(key)))

    assert report["ok"] is False
    assert report["checks"]["custody"]["error_type"] == "RuntimeError"


def test_bootstrap_token_reuse_is_rejected(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "before-restart")
    bootstrap_path = Path(args.secrets_dir) / "ARAGORA_API_TOKEN"
    bootstrap_path.write_text(TOKEN, encoding="utf-8")
    bootstrap_path.chmod(0o600)

    report = run_verification(args, FakeTransport(public_key_pem(key)))

    assert report["ok"] is False
    assert report["checks"]["custody"]["error_type"] == "RuntimeError"


def test_webhook_auth_rejection_is_recorded(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)

    class RejectingTransport(FakeTransport):
        def request(self, method, url, *, headers=None, payload=None):
            if method == "POST" and url.endswith("/api/v1/webhook-configs"):
                assert headers == {"Authorization": f"Bearer {TOKEN}"}
                return self._response(401, {"error": "Authentication required"})
            return super().request(method, url, headers=headers, payload=payload)

    report = run_verification(
        _args(tmp_path, receipt_path, "before-restart"),
        RejectingTransport(public_key_pem(key)),
    )

    assert report["ok"] is False
    assert report["checks"]["persistence"]["create_status"] == 401


def test_failed_read_reports_cleanup_status(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)

    class ReadFailTransport(FakeTransport):
        def request(self, method, url, *, headers=None, payload=None):
            if method == "GET" and "/api/v1/webhook-configs/" in url:
                return self._response(500)
            return super().request(method, url, headers=headers, payload=payload)

    report = run_verification(
        _args(tmp_path, receipt_path, "before-restart"),
        ReadFailTransport(public_key_pem(key)),
    )

    assert report["ok"] is False
    persistence = report["checks"]["persistence"]
    assert persistence["read_status"] == 500
    assert persistence["cleanup_status"] == 204


def test_state_write_failure_cleans_up_created_webhook(tmp_path: Path, monkeypatch) -> None:
    key, receipt_path = _receipt(tmp_path)

    class CleanupTrackingTransport(FakeTransport):
        deleted = False

        def request(self, method, url, *, headers=None, payload=None):
            if method == "DELETE":
                self.deleted = True
            return super().request(method, url, headers=headers, payload=payload)

    transport = CleanupTrackingTransport(public_key_pem(key))
    monkeypatch.setattr(
        verifier,
        "_write_state",
        lambda *args: (_ for _ in ()).throw(OSError("state unavailable")),
    )

    report = run_verification(_args(tmp_path, receipt_path, "before-restart"), transport)

    assert report["ok"] is False
    assert report["checks"]["persistence"]["error_type"] == "OSError"
    assert transport.deleted is True


def test_after_restart_delete_failure_is_recorded(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)

    class DeleteFailTransport(FakeTransport):
        fail_delete = False

        def request(self, method, url, *, headers=None, payload=None):
            if self.fail_delete and method == "DELETE":
                return self._response(500)
            return super().request(method, url, headers=headers, payload=payload)

    transport = DeleteFailTransport(public_key_pem(key))
    before_args = _args(tmp_path, receipt_path, "before-restart")
    assert run_verification(before_args, transport)["ok"] is True
    transport.fail_delete = True
    after_args = _args(tmp_path, receipt_path, "after-restart")
    after_args.persistence_state = before_args.persistence_state

    report = run_verification(after_args, transport)

    assert report["ok"] is False
    assert report["checks"]["persistence"]["delete_status"] == 500


def test_corrupt_after_restart_state_is_recorded(tmp_path: Path) -> None:
    key, receipt_path = _receipt(tmp_path)
    args = _args(tmp_path, receipt_path, "after-restart")
    Path(args.persistence_state).write_text("not json", encoding="utf-8")

    report = run_verification(args, FakeTransport(public_key_pem(key)))

    assert report["ok"] is False
    assert report["checks"]["persistence"]["error_type"] == "JSONDecodeError"
