#!/usr/bin/env python3
"""Fail-closed external proof for a provider-neutral Aragora canary."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from aragora.config.secrets import SecretManager, SecretsConfig
from aragora.gauntlet.odr_signing import compute_key_id
from scripts.validate_provider_neutral_canary import (
    validate_image,
    validate_secrets_directory,
)


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Response: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrlLibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Response:
        request_headers = dict(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                _NoRedirectHandler(),
            )
            with opener.open(request, timeout=20) as resp:
                return Response(resp.status, dict(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, dict(exc.headers.items()), exc.read())


def _url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _json(response: Response) -> dict[str, Any]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("endpoint did not return a JSON object") from exc
    if not isinstance(value, dict):
        raise RuntimeError("endpoint did not return a JSON object")
    return value


def _load_auth_token(secrets_dir: str) -> str:
    manager = SecretManager(SecretsConfig(secrets_dir=secrets_dir))
    directory_fd = manager._open_secrets_directory()  # noqa: SLF001
    try:
        token = manager._read_protected_file(directory_fd, "canary-auth-token")  # noqa: SLF001
        bootstrap_token = manager._read_protected_file(  # noqa: SLF001
            directory_fd, "ARAGORA_API_TOKEN"
        )
    finally:
        os.close(directory_fd)
    if not token:
        raise RuntimeError("canary-auth-token is missing from mounted custody")
    if bootstrap_token and hmac.compare_digest(token, bootstrap_token):
        raise RuntimeError("canary-auth-token must differ from the server bootstrap token")
    if not token.startswith("ara_") and token.count(".") != 2:
        raise RuntimeError("canary-auth-token must be a user JWT or ara_ API key")
    return token


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _check_health(client: Transport, base_url: str) -> dict[str, Any]:
    liveness = client.request("GET", _url(base_url, "/healthz"))
    health = client.request("GET", _url(base_url, "/api/health"))
    health_payload = _json(health) if health.status == 200 else {}
    healthy = health_payload.get("status") in {"healthy", "ok"}
    return {
        "ok": liveness.status == 200 and health.status == 200 and healthy,
        "healthz_status": liveness.status,
        "api_health_status": health.status,
        "api_health_value": health_payload.get("status"),
    }


def _check_build(client: Transport, base_url: str, expected_sha: str) -> dict[str, Any]:
    path = "/health/build?" + urllib.parse.urlencode({"verify": expected_sha})
    response = client.request("GET", _url(base_url, path))
    payload = _json(response) if response.status == 200 else {}
    actual = str(payload.get("sha") or "")
    return {
        "ok": response.status == 200 and actual == expected_sha,
        "status": response.status,
        "expected_sha": expected_sha,
        "actual_sha": actual,
    }


def _check_signing_keys(client: Transport, base_url: str) -> tuple[dict[str, Any], Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    envelope_response = client.request("GET", _url(base_url, "/api/v2/receipts/signing-key"))
    pem_response = client.request("GET", _url(base_url, "/.well-known/aragora-odr-signing-key"))
    if envelope_response.status != 200 or pem_response.status != 200:
        return {
            "ok": False,
            "json_status": envelope_response.status,
            "pem_status": pem_response.status,
        }, None
    envelope = _json(envelope_response)
    pem = pem_response.body.decode("utf-8")
    public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(public_key, Ed25519PublicKey):
        raise RuntimeError("signing key endpoint did not return an Ed25519 public key")
    key_id = compute_key_id(public_key)
    envelope_pem = str(envelope.get("public_key_pem") or "")
    response_headers = {name.lower(): value for name, value in pem_response.headers.items()}
    header_key_id = response_headers.get("x-aragora-key-id", "")
    ok = (
        envelope.get("algorithm") == "Ed25519"
        and envelope.get("key_id") == key_id
        and header_key_id == key_id
        and envelope_pem == pem
    )
    return {
        "ok": ok,
        "json_status": envelope_response.status,
        "pem_status": pem_response.status,
        "key_id": key_id,
    }, public_key


def _verify_receipt(receipt_path: str, public_key: Any) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    try:
        from aragora_verify.verifier import verify
    except ModuleNotFoundError:
        package_src = Path(__file__).resolve().parents[1] / "aragora-verify" / "src"
        sys.path.insert(0, str(package_src))
        from aragora_verify.verifier import verify
    result = verify(receipt, public_key=public_key)
    signature = next((check for check in result.checks if check.name == "signature"), None)
    return {
        "ok": bool(result.ok and signature is not None and signature.status == "pass"),
        "receipt_id": receipt.get("receipt_id"),
        "signature_status": signature.status if signature is not None else "missing",
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


_WEBHOOK_CONFIGS_ENDPOINT = "/api/v1/webhook-configs"


def _webhook_metadata_matches(
    webhook: dict[str, Any],
    *,
    webhook_id: str,
    expected_url: str,
    expected_name: str,
) -> bool:
    return (
        webhook.get("id") == webhook_id
        and webhook.get("url") == expected_url
        and webhook.get("events") == ["canary_probe"]
        and webhook.get("name") == expected_name
    )


def _persistence_before(
    client: Transport, base_url: str, headers: dict[str, str], state_path: Path
) -> dict[str, Any]:
    marker = uuid.uuid4().hex
    callback_url = f"https://example.invalid/aragora-canary/{marker}"
    endpoint = _WEBHOOK_CONFIGS_ENDPOINT
    expected_name = f"canary-{marker}"
    response = client.request(
        "POST",
        _url(base_url, endpoint),
        headers=headers,
        payload={"url": callback_url, "events": ["canary_probe"], "name": expected_name},
    )

    payload = _json(response) if response.status == 201 else {}
    webhook_value = payload.get("webhook")
    webhook: dict[str, Any] = webhook_value if isinstance(webhook_value, dict) else {}
    webhook_id = str(webhook.get("id") or "")
    if not webhook_id:
        return {"ok": False, "create_status": response.status}
    create_matches = webhook.get("url") == callback_url
    read = client.request("GET", _url(base_url, f"{endpoint}/{webhook_id}"), headers=headers)
    read_payload = _json(read) if read.status == 200 else {}
    stored_value = read_payload.get("webhook")
    stored: dict[str, Any] = stored_value if isinstance(stored_value, dict) else {}
    ok = (
        read.status == 200
        and create_matches
        and _webhook_metadata_matches(
            stored,
            webhook_id=webhook_id,
            expected_url=callback_url,
            expected_name=expected_name,
        )
    )
    if ok:
        try:
            _write_state(
                state_path,
                {
                    "webhook_id": webhook_id,
                    "expected_url": callback_url,
                    "expected_events": ["canary_probe"],
                    "expected_name": expected_name,
                    "marker": marker,
                    "endpoint": endpoint,
                },
            )
        except Exception:
            client.request("DELETE", _url(base_url, f"{endpoint}/{webhook_id}"), headers=headers)
            raise
        return {"ok": True, "create_status": response.status, "read_status": read.status}
    cleanup = client.request("DELETE", _url(base_url, f"{endpoint}/{webhook_id}"), headers=headers)
    return {
        "ok": False,
        "create_status": response.status,
        "read_status": read.status,
        "cleanup_status": cleanup.status,
    }


def _persistence_after(
    client: Transport, base_url: str, headers: dict[str, str], state_path: Path
) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    webhook_id = str(state.get("webhook_id") or "")
    endpoint = str(state.get("endpoint") or "")
    if endpoint != _WEBHOOK_CONFIGS_ENDPOINT:
        raise RuntimeError("persistence state does not select the durable webhook endpoint")
    marker = str(state.get("marker") or "")
    expected_url = str(state.get("expected_url") or "")
    expected_name = str(state.get("expected_name") or "")
    read = client.request("GET", _url(base_url, f"{endpoint}/{webhook_id}"), headers=headers)
    read_payload = _json(read) if read.status == 200 else {}
    stored_value = read_payload.get("webhook")
    stored: dict[str, Any] = stored_value if isinstance(stored_value, dict) else {}
    state_matches = (
        state.get("expected_events") == ["canary_probe"] and expected_name == f"canary-{marker}"
    )
    persisted = (
        read.status == 200
        and state_matches
        and _webhook_metadata_matches(
            stored,
            webhook_id=webhook_id,
            expected_url=expected_url,
            expected_name=expected_name,
        )
    )
    deleted = client.request("DELETE", _url(base_url, f"{endpoint}/{webhook_id}"), headers=headers)
    return {
        "ok": persisted and deleted.status in {200, 204},
        "read_status": read.status,
        "delete_status": deleted.status,
    }


_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_WEBSOCKET_HEADER_BYTES = 8192


def _check_websocket(base_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname
    if not host:
        raise RuntimeError("canary URL has no hostname")
    port = parsed.port or 443
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    expected_accept = base64.b64encode(
        hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii"), usedforsecurity=False).digest()
    )
    request = (
        f"GET /ws HTTP/1.1\r\nHost: {parsed.netloc}\r\n"
        "Connection: Upgrade\r\nUpgrade: websocket\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        f"Origin: {base_url.rstrip('/')}\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection((host, port), timeout=10) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as secured:
            secured.sendall(request)
            response = bytearray()
            header_terminator = b"\r\n\r\n"
            while header_terminator not in response and len(response) < _MAX_WEBSOCKET_HEADER_BYTES:
                chunk = secured.recv(min(1024, _MAX_WEBSOCKET_HEADER_BYTES - len(response)))
                if not chunk:
                    break
                response.extend(chunk)

    header_block, terminator, _remainder = bytes(response).partition(header_terminator)
    header_lines = header_block.split(b"\r\n")
    status_line = header_lines[0] if header_lines else b""
    status_parts = status_line.split()
    status_ok = (
        len(status_parts) >= 2
        and status_parts[0].startswith(b"HTTP/")
        and status_parts[1] == b"101"
    )
    response_headers: dict[bytes, bytes] = {}
    for line in header_lines[1:]:
        name, separator, value = line.partition(b":")
        if separator:
            response_headers[name.strip().lower()] = value.strip()
    connection_tokens = {
        token.strip().lower() for token in response_headers.get(b"connection", b"").split(b",")
    }
    accept = response_headers.get(b"sec-websocket-accept", b"")
    ok = (
        bool(terminator)
        and status_ok
        and response_headers.get(b"upgrade", b"").lower() == b"websocket"
        and b"upgrade" in connection_tokens
        and hmac.compare_digest(accept, expected_accept)
    )
    return {
        "ok": ok,
        "status_line": status_line.decode("ascii", errors="replace")[:80],
        "url": f"wss://{parsed.netloc}/ws",
    }


def _failed_check(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error_type": type(exc).__name__}


def _validate_inputs(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        errors.append("base_url must be an HTTPS origin without a path")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        errors.append("expected_sha must be a full 40-character lowercase commit SHA")
    for name in ("expected_image_digest", "observed_image_digest"):
        if validate_image(str(getattr(args, name))):
            errors.append(f"{name} must be a non-placeholder immutable image digest reference")
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{3,200}", args.database_proof_id):
        errors.append("database_proof_id must be a non-secret snapshot/export identifier")
    return errors


def run_verification(args: argparse.Namespace, client: Transport | None = None) -> dict[str, Any]:
    input_errors = _validate_inputs(args)
    if input_errors:
        return {
            "ok": False,
            "phase": args.phase,
            "base_url": args.base_url,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "checks": {"inputs": {"ok": False, "errors": input_errors}},
        }
    transport = client or UrlLibTransport()
    checks: dict[str, dict[str, Any]] = {"inputs": {"ok": True}}
    runtime_uid = int(getattr(args, "runtime_uid", os.geteuid()))
    runtime_gid = int(getattr(args, "runtime_gid", os.getegid()))
    headers: dict[str, str] | None = None
    try:
        custody_errors, _present_names = validate_secrets_directory(
            args.secrets_dir,
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
        )
        if custody_errors:
            checks["custody"] = {
                "ok": False,
                "error_type": "CustodyValidationError",
                "errors": custody_errors,
            }
        else:
            token = _load_auth_token(args.secrets_dir)
            headers = _authorization(token)
            checks["custody"] = {"ok": True, "source": "mounted_file"}
    except Exception as exc:  # noqa: BLE001 - every failure must reach the artifact
        checks["custody"] = _failed_check(exc)

    try:
        checks["health"] = _check_health(transport, args.base_url)
    except Exception as exc:  # noqa: BLE001
        checks["health"] = _failed_check(exc)
    try:
        checks["build"] = _check_build(transport, args.base_url, args.expected_sha)
    except Exception as exc:  # noqa: BLE001
        checks["build"] = _failed_check(exc)
    try:
        signing, public_key = _check_signing_keys(transport, args.base_url)
        checks["signing_keys"] = signing
    except Exception as exc:  # noqa: BLE001
        public_key = None
        checks["signing_keys"] = _failed_check(exc)
    try:
        checks["receipt"] = (
            _verify_receipt(args.receipt_file, public_key)
            if public_key is not None
            else {"ok": False, "signature_status": "no-public-key"}
        )
    except Exception as exc:  # noqa: BLE001
        checks["receipt"] = _failed_check(exc)
    if headers is None:
        checks["persistence"] = {"ok": False, "error_type": "AuthUnavailable"}
    else:
        try:
            checks["persistence"] = (
                _persistence_before(transport, args.base_url, headers, Path(args.persistence_state))
                if args.phase == "before-restart"
                else _persistence_after(
                    transport, args.base_url, headers, Path(args.persistence_state)
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks["persistence"] = _failed_check(exc)
    try:
        checks["websocket"] = (
            _check_websocket(args.base_url) if client is None else {"ok": True, "mode": "test"}
        )
    except Exception as exc:  # noqa: BLE001
        checks["websocket"] = _failed_check(exc)

    identity_ok = (
        args.expected_image_digest == args.observed_image_digest
        and "@sha256:" in args.expected_image_digest
        and bool(args.database_proof_id.strip())
    )
    checks["identity"] = {
        "ok": identity_ok,
        "expected_image_digest": args.expected_image_digest,
        "observed_image_digest": args.observed_image_digest,
        "database_proof_id": args.database_proof_id,
    }
    return {
        "ok": all(bool(check.get("ok")) for check in checks.values()),
        "phase": args.phase,
        "base_url": args.base_url,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before-restart", "after-restart"), required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-image-digest", required=True)
    parser.add_argument("--observed-image-digest", required=True)
    parser.add_argument("--database-proof-id", required=True)
    parser.add_argument("--secrets-dir", required=True)
    parser.add_argument("--receipt-file", required=True)
    parser.add_argument("--persistence-state", required=True)
    parser.add_argument("--runtime-uid", type=int, default=1000)
    parser.add_argument("--runtime-gid", type=int, default=1000)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_verification(args)
    _write_state(Path(args.output), report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
