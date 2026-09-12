"""Deterministic protocol/containment tests; no provider calls or credentials."""

import json
import http.client
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scripts import prepare_claude_code_vibeproxy_review as runner


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()

    def git(*args):
        return (
            subprocess.check_output(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    *args,
                ],
                cwd=repo,
            )
            .decode()
            .strip()
        )

    git("init", "-q")
    (repo / "pricing.py").write_text("old = 1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (repo / "pricing.py").write_text("from policy import MAX\n" + "value = 1\n" * 1001)
    (repo / "policy.py").write_text("MAX = 25\n")
    git("add", ".")
    git("commit", "-qm", "head")
    return runner.Checkout(repo, base, git("rev-parse", "HEAD"))


def sse(tool=None, model=runner.DEFAULT_CLAUDE_MODEL, stop=None):
    frames = [{"type": "message_start", "message": {"model": model}}]
    if tool:
        frames += [
            {"type": "content_block_start", "index": 0, "content_block": tool},
            {"type": "content_block_stop", "index": 0},
        ]
    frames += [
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop or ("tool_use" if tool else "end_turn")},
        },
        {"type": "message_stop"},
    ]
    return "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames).encode()


def read(audit, path="pricing.py", offset=1, limit=200):
    ident = str(len(audit.calls))
    audit.response(
        sse(
            {
                "type": "tool_use",
                "id": ident,
                "name": "Read",
                "input": {"file_path": path, "offset": offset, "limit": limit},
            }
        )
    )
    lines = audit.source.files[path].splitlines()
    content = "\n".join(
        f"{i + 1}\t{lines[i]}" for i in range(offset - 1, min(len(lines), offset - 1 + limit))
    )
    results = dict(audit.results, **{ident: content})
    blocks = [
        {"type": "tool_result", "tool_use_id": key, "content": value}
        for key, value in results.items()
    ]
    return {
        "model": runner.DEFAULT_CLAUDE_MODEL,
        "stream": True,
        "tools": [{"name": "Read"}],
        "messages": [{"role": "user", "content": blocks}],
    }


def test_large_cross_file_complete_and_preflight_only(source, tmp_path):
    audit = runner.Audit(source, tmp_path / "frozen")
    for path in source.changed:
        for offset in range(1, len(source.files[path].splitlines()) + 1, 200):
            audit.request(read(audit, path, offset))
    audit.response(sse())
    assert audit.finished and audit.complete() and len(audit.covered["pricing.py"]) == 1002
    out = tmp_path / "report"
    result = runner.prepare(source.repo, source.base, source.head, out, Path("absent"), False)
    assert result["status"] == "preflight_only" and result["would_count"] is False
    assert not result["single_shot_preflight"]["single_shot_complete"]
    assert result["single_shot_preflight"]["limits"]["lines_per_file"] == 400


@pytest.mark.parametrize(
    "fault", ["missing", "bytes", "reordered", "error", "model", "tools", "duplicate"]
)
def test_bad_read_never_completes(source, tmp_path, fault):
    audit = runner.Audit(source, tmp_path / "frozen")
    body = read(audit)
    block = body["messages"][0]["content"][0]
    if fault == "missing":
        body["messages"] = []
    elif fault in ("bytes", "reordered"):
        block["content"] = (
            "1\tforged" if fault == "bytes" else "\n".join(reversed(block["content"].splitlines()))
        )
    elif fault == "error":
        block["is_error"] = True
    elif fault == "model":
        body["model"] = "substitute"
    elif fault == "tools":
        body["tools"] = [{"name": "Bash"}]
    else:
        body["messages"][0]["content"].append(block)
    with pytest.raises(ValueError):
        audit.request(body)
    assert not audit.complete()


@pytest.mark.parametrize(
    "fault", ["model", "truncated", "max_tokens", "incomplete", "escape", "untracked", "symlink"]
)
def test_response_fail_closed(source, tmp_path, fault):
    audit = runner.Audit(source, tmp_path / "frozen")
    with pytest.raises((ValueError, KeyError)):
        if fault in ("escape", "untracked", "symlink"):
            if fault == "symlink":
                audit.root.mkdir()
                (audit.root / "pricing.py").symlink_to(source.repo / "pricing.py")
            read(
                audit,
                path="../secret"
                if fault == "escape"
                else "absent"
                if fault == "untracked"
                else "pricing.py",
            )
        else:
            payload = (
                sse(model="wrong")
                if fault == "model"
                else sse(stop="max_tokens")
                if fault == "max_tokens"
                else sse()
            )
            audit.response(payload[:-15] if fault == "truncated" else payload)
    assert not audit.finished


def test_dirty_head_and_gateway_credentials_fail_closed(source, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-inherit")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "must-not-inherit")
    env = runner.environment(tmp_path, 12345, "ephemeral")
    assert env["ANTHROPIC_API_KEY"] == "ephemeral" and "CLAUDE_CODE_OAUTH_TOKEN" not in env
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "direct")
    result = runner.prepare(
        source.repo, source.base, source.head, tmp_path / "blocked", Path("absent"), True
    )
    assert result["error"] == "gateway_required_mode_only" and result["would_count"] is False
    (source.repo / "pricing.py").write_text("dirty")
    with pytest.raises(ValueError, match="dirty_checkout"):
        source.check()
    source.head = source.base
    with pytest.raises(ValueError, match="head_drift"):
        source.check()


def test_timeout_kills_owned_process_group(tmp_path):
    relay = SimpleNamespace(error="", out=tmp_path, token="ephemeral")
    command = [
        sys.executable,
        "-c",
        'import os,time,json; print(json.dumps({"pid":os.getpid()}),flush=True); time.sleep(60)',
    ]
    started = time.monotonic()
    with pytest.raises(ValueError, match="hard_timeout"):
        runner.supervise(command, "", {}, tmp_path, started + 0.4, relay)
    assert time.monotonic() - started < 4
    pid = json.loads((tmp_path / "cli-trace.jsonl").read_text())["pid"]
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


def test_unavailable_gateway_is_terminal_without_fallback(source, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "tempting-direct-key")
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{unavailable.getsockname()[1]}"
        audit = runner.Audit(source, tmp_path / "frozen")
        relay = runner.Relay(audit, tmp_path, endpoint, "local-only", time.monotonic() + 3)
        worker = threading.Thread(target=relay.loop)
        worker.start()
        client = http.client.HTTPConnection("127.0.0.1", relay.server_port, timeout=6)
        try:
            body = {
                "model": runner.DEFAULT_CLAUDE_MODEL,
                "stream": True,
                "tools": [{"name": "Read"}],
                "messages": [],
            }
            client.request("POST", "/v1/messages", json.dumps(body), {"x-api-key": relay.token})
            response = client.getresponse()
            assert response.status == 502
            response.read()
            assert relay.error in {"ConnectionRefusedError", "TimeoutError"}
            assert len(relay.rows) == 1
            assert not audit.finished and "response_sha256" not in relay.rows[0]
        finally:
            client.close()
            relay.stopping.set()
            worker.join(timeout=3)
            relay.server_close()
        assert not worker.is_alive()


def test_relay_shutdown_interrupts_stalled_upstream(source, tmp_path):
    with socket.socket() as stalled:
        stalled.bind(("127.0.0.1", 0))
        stalled.listen(1)
        stalled.settimeout(3)
        relay = runner.Relay(
            runner.Audit(source, tmp_path / "frozen"),
            tmp_path,
            f"http://127.0.0.1:{stalled.getsockname()[1]}",
            "local-only",
            time.monotonic() + 60,
        )
        worker = threading.Thread(target=relay.loop)
        worker.start()
        client = http.client.HTTPConnection("127.0.0.1", relay.server_port, timeout=3)
        try:
            body = {
                "model": runner.DEFAULT_CLAUDE_MODEL,
                "stream": True,
                "tools": [{"name": "Read"}],
                "messages": [],
            }
            client.request("POST", "/v1/messages", json.dumps(body), {"x-api-key": relay.token})
            upstream, _address = stalled.accept()
            with upstream:
                assert upstream.recv(4096)
                started = time.monotonic()
                relay.stop()
                worker.join(timeout=2)
                assert not worker.is_alive()
                assert time.monotonic() - started < 2
                assert relay.error and not relay.audit.finished
        finally:
            client.close()
            relay.stop()
            worker.join(timeout=2)
            relay.server_close()


@pytest.mark.skipif(sys.platform != "darwin", reason="Execution refuses non-macOS containment")
def test_real_os_write_and_network_denial(tmp_path):
    home, frozen = tmp_path / "home", tmp_path / "frozen"
    home.mkdir()
    frozen.mkdir()
    profile = tmp_path / "policy.sb"
    profile.write_text(runner.sandbox(home, frozen, Path("/bin/cat"), 12345))
    prefix = ["/usr/bin/sandbox-exec", "-f", str(profile)]
    env = runner.environment(home, 12345, "ephemeral")
    write = subprocess.run(
        prefix + ["/usr/bin/touch", str(frozen / "bad")], env=env, capture_output=True
    )
    assert write.returncode != 0 and not (frozen / "bad").exists()
    connect = subprocess.run(
        prefix + ["/usr/bin/nc", "-vz", "-w", "1", "192.0.2.1", "443"],
        env=env,
        capture_output=True,
        timeout=3,
    )
    assert connect.returncode != 0 and b"Operation not permitted" in connect.stderr


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_symlink_and_submodule_blobs_rejected(source, mode):
    source.tree["pricing.py"] = (mode, "blob", "0" * 40)
    with pytest.raises(ValueError, match="unsupported_file_mode"):
        source.load("pricing.py")


@pytest.mark.parametrize("subtype", ["api_retry", "compact_boundary"])
def test_retry_or_compaction_terminates_promptly(tmp_path, subtype):
    relay = SimpleNamespace(error="", out=tmp_path, token="ephemeral")
    code = f"import time; print({json.dumps({'subtype': subtype})!r},flush=True); time.sleep(60)"
    started = time.monotonic()
    with pytest.raises(ValueError, match="retry_or_compaction"):
        runner.supervise([sys.executable, "-c", code], "", {}, tmp_path, started + 5, relay)
    assert time.monotonic() - started < 3


@pytest.mark.skipif(sys.platform != "darwin", reason="Execution refuses non-macOS containment")
def test_prepared_artifact_end_to_end_with_fake_cli_and_gateway(source, tmp_path, monkeypatch):
    chunks = [
        (path, offset)
        for path in source.changed
        for offset in range(1, len(source.files[path].splitlines()) + 1, runner.READ_LINES)
    ]
    received = []

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.headers["x-api-key"] == "gateway-only-secret"
            assert body["model"] == runner.DEFAULT_CLAUDE_MODEL
            index = len(received)
            received.append(body)
            tool = None
            if index < len(chunks):
                path, offset = chunks[index]
                tool = {
                    "type": "tool_use",
                    "id": str(index),
                    "name": "Read",
                    "input": {"file_path": path, "offset": offset, "limit": runner.READ_LINES},
                }
            payload = sse(tool)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    gateway = HTTPServer(("127.0.0.1", 0), Gateway)
    gateway_thread = threading.Thread(target=gateway.serve_forever)
    gateway_thread.start()
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-required")
    monkeypatch.setenv("ARAGORA_VIBEPROXY_BASE_URL", f"http://127.0.0.1:{gateway.server_port}")
    monkeypatch.setenv("ARAGORA_VIBEPROXY_API_KEY", "gateway-only-secret")
    monkeypatch.delenv("ARAGORA_VIBEPROXY_MODEL_MAP", raising=False)
    check_output = subprocess.check_output

    def version_or_git(command, **kwargs):
        if command[-1] == "--version":
            return f"{runner.CLI_VERSION} (Claude Code)\n".encode()
        return check_output(command, **kwargs)

    monkeypatch.setattr(runner.subprocess, "check_output", version_or_git)

    def fake_cli(command, prompt, env, cwd, deadline, relay):
        assert "--tools" in command and "Read" in command
        assert "gateway-only-secret" not in env.values()
        assert env["ANTHROPIC_API_KEY"] == relay.token
        assert source.head in prompt
        blocks = []
        for index in range(len(chunks) + 1):
            client = http.client.HTTPConnection("127.0.0.1", relay.server_port, timeout=5)
            try:
                body = {
                    "model": runner.DEFAULT_CLAUDE_MODEL,
                    "stream": True,
                    "tools": [{"name": "Read"}],
                    "messages": [{"role": "user", "content": blocks}],
                }
                client.request("POST", "/v1/messages", json.dumps(body), {"x-api-key": relay.token})
                response = client.getresponse()
                payload = response.read()
                assert response.status == 200, (payload, relay.error)
            finally:
                client.close()
            if index < len(chunks):
                path, offset = chunks[index]
                lines = (cwd / path).read_text().splitlines()
                content = "\n".join(
                    f"{i + 1}\t{lines[i]}"
                    for i in range(offset - 1, min(len(lines), offset - 1 + runner.READ_LINES))
                )
                blocks.append(
                    {"type": "tool_result", "tool_use_id": str(index), "content": content}
                )
        trace = b"\n".join(
            json.dumps(event).encode()
            for event in [
                {
                    "type": "system",
                    "subtype": "init",
                    "tools": ["Read"],
                    "model": runner.DEFAULT_CLAUDE_MODEL,
                    "apiKeySource": "ANTHROPIC_API_KEY",
                },
                {"type": "result", "is_error": False, "result": "Synthetic test only."},
            ]
        )
        (relay.out / "cli-trace.jsonl").write_bytes(trace)
        return trace, 0

    monkeypatch.setattr(runner, "supervise", fake_cli)
    output = tmp_path / "prepared"
    try:
        result = runner.prepare(
            source.repo, source.base, source.head, output, Path("/bin/cat"), True
        )
    finally:
        gateway.shutdown()
        gateway.server_close()
        gateway_thread.join(timeout=3)
    assert result["status"] == "prepared_non_countable", result
    assert result["would_count"] is False and result["non_countable"] is True
    assert result["coverage_complete"] and len(result["coverage"]["pricing.py"]) == 1002
    assert result["provenance"]["upstream_attestation"] == "UNMEASURED"
    assert result["provenance"]["fallback_allowed"] is False
    assert result["response_models"] == [runner.DEFAULT_CLAUDE_MODEL] * len(received)
    for index, row in enumerate(result["wire_requests"], 1):
        assert row["request_sha256"] == runner.digest(
            (output / f"request-{index}.json").read_bytes()
        )
        assert row["response_sha256"] == runner.digest(
            (output / f"response-{index}.sse").read_bytes()
        )
    assert json.loads((output / "diagnostic.json").read_text()) == result
    assert not any(
        b"gateway-only-secret" in p.read_bytes() for p in output.iterdir() if p.is_file()
    )
    source.check()
