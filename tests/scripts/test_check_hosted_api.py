"""scripts/check_hosted_api.sh against a local stub server (no network)."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_hosted_api.sh"
PUBKEY = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAstub\n-----END PUBLIC KEY-----\n"

pytestmark = pytest.mark.skipif(shutil.which("curl") is None, reason="curl not available")


def _stub(healthy: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401 - silence the test output
            pass

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - http.server API
            if self.path == "/readyz":
                self._json(200, {"status": "ready"})
            elif self.path == "/health/build":
                sha = "272a7ef2f672bce4d7c79bdeb916053e95840bc5" if healthy else "unknown"
                self._json(200, {"sha": sha, "version": "2.11.0" if healthy else "dev"})
            elif self.path == "/.well-known/aragora-odr-signing-key" and healthy:
                body = PUBKEY.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/ws" and self.headers.get("Sec-WebSocket-Protocol") == "aragora-v1":
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Protocol", "aragora-v1")
                self.end_headers()
                self.close_connection = True
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if self.path == "/api/v2/receipts/verify" and healthy:
                self._json(200, {"verified": False, "key_id": "ed25519-stub"})
            else:
                self._json(401, {"error": "auth_required"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run(server, *extra: str) -> subprocess.CompletedProcess[str]:
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return subprocess.run(
        ["bash", str(SCRIPT), base, *extra],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "CHECK_HOSTED_API_TIMEOUT": "5",
        },
    )


def test_healthy_deployment_passes_every_check(tmp_path):
    key = tmp_path / "pub.pem"
    key.write_text(PUBKEY)
    server = _stub(healthy=True)
    try:
        result = _run(
            server, "--pubkey", str(key), "--expect-sha", "272a7ef2", "--expect-version", "2.11.0"
        )
    finally:
        server.shutdown()
    assert result.returncode == 0, result.stdout + result.stderr
    for check in ("readyz", "build", "signing-key", "verify", "websocket"):
        assert f"PASS {check}" in result.stdout


def test_unsigned_old_build_fails_the_identity_and_key_checks():
    server = _stub(healthy=False)
    try:
        result = _run(server)
    finally:
        server.shutdown()
    assert result.returncode == 1
    assert "PASS readyz" in result.stdout
    assert "FAIL build" in result.stdout
    assert "FAIL signing-key" in result.stdout
    assert "FAIL verify" in result.stdout


def test_mismatched_public_key_fails(tmp_path):
    key = tmp_path / "other.pem"
    key.write_text(PUBKEY.replace("stub", "other"))
    server = _stub(healthy=True)
    try:
        result = _run(server, "--pubkey", str(key))
    finally:
        server.shutdown()
    assert result.returncode == 1
    assert "FAIL signing-key" in result.stdout
