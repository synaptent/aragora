"""Run with an isolated wheel consumer's Python: python -I <this file>."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import httpx
import pytest

import aragora_sdk as sdk
import aragora_sdk.client as client_module

SDK_ROOT = Path(__file__).resolve().parents[1]
REQUESTS = [
    ("POST", "/api/v1/debates"),
    ("POST", "/api/v1/code-review/review"),
    ("GET", "/api/v2/receipts/example"),
]


def installed_origin() -> dict[str, str]:
    """Fail closed on editable/check-out imports, including late module replacement."""
    assert sys.prefix != sys.base_prefix, "Use a dedicated wheel consumer virtualenv"
    distribution = importlib.metadata.distribution("aragora-sdk")
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info", {}).get("editable"), "Editable installs are not acceptance"
    hashes = {}
    for module in (sdk, client_module, sys.modules["aragora_sdk.exceptions"]):
        assert module.__file__ is not None
        origin = Path(module.__file__).resolve()
        origin.relative_to(Path(sys.prefix).resolve())
        assert origin == Path(str(distribution.locate_file("aragora_sdk/" + origin.name))).resolve()
        hashes[str(origin)] = hashlib.sha256(origin.read_bytes()).hexdigest()
    return hashes


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("method,path", REQUESTS)
async def test_loopback_consumers(async_mode: bool, method: str, path: str) -> None:
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received.append((self.command, self.path))
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        if async_mode:
            async with sdk.AragoraAsyncClient(base_url=url, max_retries=1) as client:
                assert await client.request(method, path) == {"ok": True}
        else:
            with sdk.AragoraClient(base_url=url, max_retries=1) as client:
                assert client.request(method, path) == {"ok": True}
        assert client._client.is_closed
        assert received == [(method, path)]
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.mark.parametrize("scenario", ["rate_limit", "timeout", "connection"])
def test_documented_handlers(scenario: str, capsys: pytest.CaptureFixture[str]) -> None:
    snippets = re.findall(
        r"```python\n(.*?)```", (SDK_ROOT / "REQUEST_LIFECYCLE.md").read_text(), re.S
    )
    assert len(snippets) == 2
    received = []

    def handle(request: httpx.Request) -> httpx.Response:
        received.append(request)
        if scenario != "rate_limit":
            failure = httpx.ReadTimeout if scenario == "timeout" else httpx.ConnectError
            raise failure("private fixture", request=request)
        return httpx.Response(
            429,
            headers={"Retry-After": "0"},
            json={
                "error": "Slow down",
                "code": "RATE_LIMITED",
                "trace_id": "trace-429",
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handle))
    with patch("aragora_sdk.client.httpx.Client", return_value=http):
        exec(
            compile(snippets[0 if scenario == "rate_limit" else 1], "REQUEST_LIFECYCLE.md", "exec"),
            {},
        )
    assert (
        capsys.readouterr().out.strip()
        == {
            "rate_limit": "429 RATE_LIMITED trace-429 0",
            "timeout": "TimeoutError Request timed out",
            "connection": "ConnectionError Connection failed",
        }[scenario]
    )
    assert len(received) == 1
    assert http.is_closed


class AcceptanceGuard:
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        installed_origin()
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        assert reporter is not None
        if (
            not session.testscollected
            or len(reporter.stats.get("passed", [])) != session.testscollected
            or any(
                reporter.stats.get(key) for key in ("deselected", "skipped", "xfailed", "xpassed")
            )
        ):
            session.exitstatus = 1


@pytest.mark.parametrize("mode", ["complete", "deselected", "collect-only", "empty"])
def test_acceptance_requires_full_execution(mode: str) -> None:
    stats = {"passed": [object()]} if mode in ("complete", "deselected") else {}
    if mode == "deselected":
        stats["deselected"] = [object()]
    reporter = SimpleNamespace(stats=stats)
    session = SimpleNamespace(
        testscollected=0 if mode == "empty" else 1,
        exitstatus=0,
        config=SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda _: reporter)),
    )
    AcceptanceGuard().pytest_sessionfinish(cast(pytest.Session, session))
    assert session.exitstatus == (0 if mode == "complete" else 1)


@pytest.mark.parametrize(
    "options",
    [
        "-o python_functions=test_loopback_consumers",
        "-o python_functions=test_acceptance_requires_full_execution",
        "-k test_loopback_consumers",
        "--collect-only",
    ],
    ids=["collection", "guard-only", "selection", "collect-only"],
)
def test_entrypoint_rejects_pytest_options(options: str) -> None:
    result = subprocess.run(
        [sys.executable, "-I", str(Path(__file__).resolve())],
        env={**os.environ, "PYTEST_ADDOPTS": options},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "PYTEST_ADDOPTS must be unset" in result.stderr


if __name__ == "__main__":
    if os.environ.get("PYTEST_ADDOPTS"):
        raise SystemExit("PYTEST_ADDOPTS must be unset for installed acceptance")
    print(json.dumps({"installed": installed_origin()}, sort_keys=True), flush=True)
    # Copy only tests, never conftest.py (which inserts the source checkout).
    # -I plus an empty pytest configuration prevents PYTHONPATH/repo config leakage.
    with tempfile.TemporaryDirectory(prefix="aragora-wheel-acceptance-") as scratch:
        targets = [str(Path(__file__).resolve())]
        for name in ("test_request_lifecycle.py", "test_transport_lifecycle.py"):
            targets.append(str(shutil.copyfile(SDK_ROOT / "tests" / name, Path(scratch) / name)))
        config = Path(scratch) / "pytest.ini"
        config.write_text("[pytest]\nasyncio_mode = auto\n")
        raise SystemExit(
            pytest.main(
                [
                    "-q",
                    "--noconftest",
                    "--import-mode=importlib",
                    "-c",
                    str(config),
                    *targets,
                ],
                plugins=[AcceptanceGuard()],
            )
        )
