from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
from typing import Any, Iterator, cast

import pytest

from aragora.agents.transports import vibeproxy
from scripts import check_vibeproxy


@dataclass
class _Reply:
    body: bytes
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    initial_delay: float = 0.0
    chunks: tuple[bytes, ...] = ()
    chunk_delay: float = 0.0


@dataclass
class _ProxyState:
    replies: dict[str, _Reply]
    requests: list[tuple[str, str]] = field(default_factory=list)


@contextmanager
def _proxy(replies: dict[str, _Reply]) -> Iterator[tuple[str, _ProxyState]]:
    state = _ProxyState(replies)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            state.requests.append(("GET", self.path))
            reply = state.replies.get(self.path, _Reply(b'{"error":"not found"}', status=404))
            if reply.initial_delay:
                time.sleep(reply.initial_delay)
            body = b"".join(reply.chunks) if reply.chunks else reply.body
            self.send_response(reply.status)
            for name, value in reply.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if reply.chunks:
                    for index, chunk in enumerate(reply.chunks):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if index + 1 < len(reply.chunks):
                            time.sleep(reply.chunk_delay)
                else:
                    self.wfile.write(reply.body)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self) -> None:  # noqa: N802
            state.requests.append(("POST", self.path))
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = cast(tuple[str, int], server.server_address)
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _run_json(
    capsys: pytest.CaptureFixture[str],
    base_url: str,
    *extra: str,
) -> tuple[int, dict[str, Any], str]:
    code = check_vibeproxy.main(["--json", "--base-url", base_url, *extra])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.out + captured.err


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> Iterator[None]:
    vibeproxy._CATALOG_CACHE.clear()
    yield
    vibeproxy._CATALOG_CACHE.clear()


def test_json_success_is_sanitized_and_never_requests_inference(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "vp-secret-do-not-print"
    monkeypatch.setenv("ARAGORA_VIBEPROXY_API_KEY", secret)
    catalog = _Reply(json.dumps({"data": [{"id": "zeta-model"}, {"id": "alpha-model"}]}).encode())
    metadata = _Reply(
        json.dumps(
            {
                "endpoints": [
                    "POST /v1/chat/completions",
                    "GET /v1/models",
                    "GET https://not-a-route.example/secret",
                ]
            }
        ).encode(),
        headers={"X-CPA-Version": "1.8.237"},
    )
    with _proxy({"/v1/models": catalog, "/": metadata}) as (base_url, state):
        code, result, rendered = _run_json(capsys, base_url)

    assert code == 0
    assert result["schema_version"] == 1
    assert result["ok"] is True
    assert result["endpoint"] == {"url": base_url + "/v1", "loopback": True}
    assert result["version"] == {
        "value": "1.8.237",
        "source": "http_header:x-cpa-version",
    }
    assert result["protocols"] == {
        "advertised": ["GET /v1/models", "POST /v1/chat/completions"],
        "advertised_redacted_count": 0,
        "verified_no_inference": ["GET /v1/models"],
        "aragora_implemented_not_probed": [
            "POST /v1/chat/completions",
            "POST /v1/messages",
            "POST /v1/responses",
        ],
        "metadata_status": "verified",
    }
    assert result["model_inventory"] == {
        "count": 2,
        "models": ["alpha-model", "zeta-model"],
        "redacted_count": 0,
    }
    assert result["catalog_freshness"]["scope"] == "process_local"
    assert result["catalog_freshness"]["source"] == "live"
    assert result["catalog_freshness"]["fresh"] is True
    assert result["error"] is None
    assert state.requests == [("GET", "/v1/models"), ("GET", "/")]
    assert secret not in rendered


def test_server_echoed_credential_and_control_characters_are_redacted(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "LEAK-ME-SENTINEL"
    injected = "safe-model\nforged-terminal-line"
    monkeypatch.setenv("ARAGORA_VIBEPROXY_API_KEY", secret)
    catalog_data = {"data": [{"id": "ordinary-model"}, {"id": secret}, {"id": injected}]}
    catalog = _Reply(json.dumps(catalog_data).encode())
    metadata_data = {"endpoints": ["GET /v1/models", f"POST /v1/{secret}"]}
    metadata = _Reply(
        json.dumps(metadata_data).encode(),
        headers={"X-CPA-Version": secret},
    )
    with _proxy({"/v1/models": catalog, "/": metadata}) as (base_url, _):
        json_code, result, json_rendered = _run_json(capsys, base_url)
        human_code = check_vibeproxy.main(["--base-url", base_url])
        human = capsys.readouterr()

    rendered = json_rendered + human.out + human.err
    assert json_code == human_code == 0
    assert result["model_inventory"]["count"] == 3
    assert result["model_inventory"]["models"] == ["ordinary-model"]
    assert result["model_inventory"]["redacted_count"] == 2
    assert result["protocols"]["advertised"] == ["GET /v1/models"]
    assert result["protocols"]["advertised_redacted_count"] == 1
    assert result["version"] == {"value": None, "source": "redacted"}
    assert secret not in rendered
    assert "forged-terminal-line" not in rendered


def test_human_output_is_concise(capsys: pytest.CaptureFixture[str]) -> None:
    catalog = _Reply(b'{"data":[{"id":"model-a"}]}')
    metadata = _Reply(b'{"endpoints":[]}')
    with _proxy({"/v1/models": catalog, "/": metadata}) as (base_url, _state):
        code = check_vibeproxy.main(["--base-url", base_url])
    captured = capsys.readouterr()

    assert code == 0
    assert "VibeProxy: ready" in captured.out
    assert "models=1" in captured.out
    assert "verified_no_inference=GET /v1/models" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("reply", "category"),
    [
        (_Reply(b"not-json"), "malformed_response"),
        (_Reply(b'{"data":"not-a-list"}'), "malformed_response"),
        (_Reply(b'{"data":[]}'), "malformed_response"),
    ],
)
def test_malformed_catalog_has_stable_failure_envelope(
    capsys: pytest.CaptureFixture[str], reply: _Reply, category: str
) -> None:
    with _proxy({"/v1/models": reply}) as (base_url, state):
        code, result, _rendered = _run_json(capsys, base_url)

    assert code == 1
    assert result["ok"] is False
    assert result["error"]["category"] == category
    assert result["model_inventory"] == {
        "count": 0,
        "models": [],
        "redacted_count": 0,
    }
    assert result["latency_ms"]["catalog"] is not None
    assert state.requests == [("GET", "/v1/models")]


def test_unavailable_endpoint_returns_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with socket.socket() as port_probe:
        port_probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port_probe.bind(("127.0.0.1", 0))
        host, port = port_probe.getsockname()
    code, result, _rendered = _run_json(capsys, f"http://{host}:{port}", "--timeout-seconds", "0.2")

    assert code == 1
    assert result["error"]["category"] == "unavailable"


def test_catalog_slow_drip_obeys_wall_clock_deadline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reply = _Reply(
        b"",
        chunks=(b'{"data":[', b'{"id":"slow"}', b"]}"),
        chunk_delay=0.12,
    )
    with _proxy({"/v1/models": reply}) as (base_url, state):
        started = time.monotonic()
        code, result, _rendered = _run_json(capsys, base_url, "--timeout-seconds", "0.18")
        elapsed = time.monotonic() - started

    assert code == 1
    assert result["error"]["category"] == "timeout"
    assert elapsed < 0.5
    assert state.requests == [("GET", "/v1/models")]


def test_catalog_and_metadata_share_one_total_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = _Reply(b'{"data":[{"id":"model-a"}]}', initial_delay=0.2)
    metadata = _Reply(
        b"",
        chunks=(b'{"end', b'points"', b":[]}"),
        chunk_delay=0.1,
    )
    with _proxy({"/v1/models": catalog, "/": metadata}) as (base_url, state):
        started = time.monotonic()
        code, result, _rendered = _run_json(capsys, base_url, "--timeout-seconds", "0.35")
        elapsed = time.monotonic() - started

    assert code == 0
    assert result["ok"] is True
    assert result["protocols"]["metadata_status"] == "timeout"
    assert result["protocols"]["verified_no_inference"] == ["GET /v1/models"]
    assert elapsed < 0.55
    assert state.requests == [("GET", "/v1/models"), ("GET", "/")]


def test_redirect_is_denied_without_following_location_or_leaking_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "location-secret"
    redirect = _Reply(
        b"",
        status=302,
        headers={"Location": f"/v1/messages?token={secret}"},
    )
    with _proxy({"/v1/models": redirect}) as (base_url, state):
        code, result, rendered = _run_json(capsys, base_url)

    assert code == 1
    assert result["error"]["category"] == "redirect_denied"
    assert state.requests == [("GET", "/v1/models")]
    assert secret not in rendered


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8317",
        "http://user:password@127.0.0.1:8318",
        "http://127.0.0.1:8318?token=query-secret",
        "http://192.0.2.1:8318",
        "http://[::1",
    ],
)
def test_unsafe_endpoint_is_rejected_without_echoing_input(
    capsys: pytest.CaptureFixture[str], url: str
) -> None:
    code, result, rendered = _run_json(capsys, url)

    assert code == 1
    assert result["error"]["category"] == "configuration"
    assert result["endpoint"] == {"url": None, "loopback": None}
    assert "password" not in rendered
    assert "query-secret" not in rendered


def test_http_error_body_and_api_key_are_redacted(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "api-and-body-secret"
    monkeypatch.setenv("ARAGORA_VIBEPROXY_API_KEY", secret)
    with _proxy({"/v1/models": _Reply(secret.encode(), status=500)}) as (
        base_url,
        state,
    ):
        code, result, rendered = _run_json(capsys, base_url)

    assert code == 1
    assert result["error"] == {
        "category": "unavailable",
        "message": "VibeProxy HTTP 500",
    }
    assert secret not in rendered
    assert state.requests == [("GET", "/v1/models")]


def test_oversized_catalog_is_rejected_through_transport_limit(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vibeproxy, "MAX_RESPONSE_BYTES", 32)
    with _proxy({"/v1/models": _Reply(b'{"data":[' + b" " * 64 + b"]}")}) as (
        base_url,
        _state,
    ):
        code, result, _rendered = _run_json(capsys, base_url)

    assert code == 1
    assert result["error"]["category"] == "malformed_response"
