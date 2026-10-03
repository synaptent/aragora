"""Focused tests for the bounded Claude consult helper."""

from __future__ import annotations

import importlib.util
import io
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.agents import claude_profile_pool


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "consult_claude.py"
SPEC = importlib.util.spec_from_file_location("consult_claude_under_test", SCRIPT)
assert SPEC and SPEC.loader
consult_claude = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(consult_claude)


@pytest.fixture(autouse=True)
def _default_direct_transport(monkeypatch):
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "direct")


def test_build_cli_command_disables_mcp() -> None:
    with consult_claude._claude_empty_mcp_config_file() as mcp_config_path:
        command, _used_profile = consult_claude._build_cli_command(
            "claude-fable-5", mcp_config_path
        )

        assert "--strict-mcp-config" in command
        assert "--mcp-config" in command
        assert command[command.index("--mcp-config") + 1] == str(mcp_config_path)
        assert json.loads(mcp_config_path.read_text(encoding="utf-8")) == {"mcpServers": {}}
        assert "--model" in command
        assert command[command.index("--model") + 1] == "claude-fable-5"


def test_build_cli_command_routes_profile_pool_through_script_repo_root(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_build_claude_command(base_cmd, *, repo_root=None, index=None):
        captured["base_cmd"] = base_cmd
        captured["repo_root"] = repo_root
        captured["index"] = index
        return list(base_cmd), False

    monkeypatch.setattr(claude_profile_pool, "build_claude_command", fake_build_claude_command)

    with consult_claude._claude_empty_mcp_config_file() as mcp_config_path:
        command, used_profile = consult_claude._build_cli_command("claude-fable-5", mcp_config_path)

    assert command == captured["base_cmd"]
    assert used_profile is False
    assert captured["repo_root"] == consult_claude._REPO_ROOT
    assert captured["index"] is None


def test_run_cli_uses_stdin_prompt_timeout_and_redacts_stderr(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePopen:
        returncode = 1
        pid = 12345

        def __init__(self, command, *, stdin, stdout, stderr, text, start_new_session):
            mcp_config_path = Path(command[command.index("--mcp-config") + 1])
            captured.update(
                {
                    "command": command,
                    "stdin": stdin,
                    "stdout": stdout,
                    "stderr": stderr,
                    "text": text,
                    "start_new_session": start_new_session,
                    "mcp_exists_during_run": mcp_config_path.exists(),
                    "mcp_json": json.loads(mcp_config_path.read_text(encoding="utf-8")),
                }
            )

        def communicate(self, input, timeout):
            captured["input"] = input
            captured["timeout"] = timeout
            return "", "Using profile home: /secret/profile\nCommand: claude --print\ntoken=secret"

    monkeypatch.setattr(consult_claude.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(consult_claude.subprocess, "Popen", FakePopen)

    result = consult_claude._run_cli("live prompt", "claude-fable-5", 12.5)

    assert result["ok"] is False
    assert result["error"] == "claude CLI failed, rc=1, empty=True"
    assert "secret" not in json.dumps(result)
    assert "profile" not in json.dumps(result).lower()
    assert captured["input"] == "live prompt"
    assert captured["timeout"] == 12.5
    assert captured["stderr"] == subprocess.DEVNULL
    assert captured["mcp_exists_during_run"] is True
    assert captured["mcp_json"] == {"mcpServers": {}}
    assert captured["start_new_session"] is True
    assert "--print" in captured["command"]
    assert "-p" not in captured["command"]
    assert "-" not in captured["command"]


def test_run_cli_does_not_treat_nonzero_stdout_as_success(monkeypatch) -> None:
    class FakePopen:
        returncode = 1
        pid = 54321

        def __init__(self, *args, **kwargs):
            assert kwargs["start_new_session"] is True

        def communicate(self, input, timeout):
            assert input == "live prompt"
            assert timeout == 12.5
            return "usable advice\n", "auth warning with token=secret"

    monkeypatch.setattr(consult_claude.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(consult_claude.subprocess, "Popen", FakePopen)

    result = consult_claude._run_cli("live prompt", "claude-fable-5", 12.5)

    assert result["ok"] is False
    assert "text" not in result
    assert result["error"] == "claude CLI failed, rc=1, empty=False"
    assert "secret" not in json.dumps(result)


def test_run_cli_classifies_rate_limit_without_exposing_raw_output(monkeypatch) -> None:
    class FakePopen:
        returncode = 1
        pid = 54321

        def __init__(self, *args, **kwargs):
            assert kwargs["stderr"] == subprocess.DEVNULL

        def communicate(self, input, timeout):
            assert input == "live prompt"
            assert timeout == 12.5
            return "You've hit your session limit - resets 3am (America/Chicago)\n", ""

    monkeypatch.setattr(consult_claude.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(consult_claude.subprocess, "Popen", FakePopen)

    result = consult_claude._run_cli("live prompt", "claude-fable-5", 12.5)

    assert result == {
        "ok": False,
        "backend": "cli",
        "elapsed_s": result["elapsed_s"],
        "rate_limited": True,
        "failure_kind": "rate_limited",
        "error": "claude CLI rate limited, rc=1",
    }
    serialized = json.dumps(result)
    assert "3am" not in serialized
    assert "America/Chicago" not in serialized


def test_classify_cli_failure_does_not_treat_generic_limit_as_rate_limit() -> None:
    result = consult_claude._classify_cli_failure("recursion limit reached")

    assert result == {"failure_kind": "cli_error"}


def test_consult_default_is_cli_only(monkeypatch) -> None:
    cli_models: list[str] = []
    monkeypatch.delenv("ARAGORA_MODEL_TRANSPORT", raising=False)

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {"ok": False, "backend": "cli", "error": f"{model} unavailable"}

    def fake_api(*_args, **_kwargs) -> dict:
        raise AssertionError("API fallback must be explicit")

    def fake_openrouter(*_args, **_kwargs) -> dict:
        raise AssertionError("OpenRouter fallback must be explicit")

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_api", fake_api)
    monkeypatch.setattr(consult_claude, "_run_openrouter_api", fake_openrouter)

    result = consult_claude.consult("question")

    assert result["ok"] is False
    assert cli_models == [consult_claude.DEFAULT_MODEL, consult_claude.FALLBACK_MODEL]
    assert [attempt["backend"] for attempt in result["attempts"]] == ["cli", "cli"]


def test_consult_uses_vibeproxy_before_cli(monkeypatch) -> None:
    policy = SimpleNamespace(mode=consult_claude.TransportMode.PREFER)
    monkeypatch.setattr(consult_claude.ModelTransportPolicy, "from_env", lambda **_kwargs: policy)
    monkeypatch.setattr(
        consult_claude,
        "_run_vibeproxy",
        lambda *_args, **_kwargs: {
            "ok": True,
            "backend": "vibeproxy",
            "text": "fable answer",
            "elapsed_s": 0.1,
        },
    )
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    result = consult_claude.consult("question")

    assert result["ok"] is True
    assert result["backend"] == "vibeproxy"
    assert result["model"] == consult_claude.DEFAULT_MODEL


def test_run_vibeproxy_preserves_catalog_timeout_classification() -> None:
    class TimeoutPolicy:
        client = object()

        def resolve(self, *_args, **_kwargs):
            raise consult_claude.VibeProxyTimeoutError("catalog timed out")

    result = consult_claude._run_vibeproxy(
        "question",
        consult_claude.DEFAULT_MODEL,
        10,
        None,
        TimeoutPolicy(),  # type: ignore[arg-type]
    )

    assert result == {
        "ok": False,
        "backend": "vibeproxy",
        "timed_out": True,
        "error": "catalog timed out",
    }


def test_run_vibeproxy_marks_executed_failure_as_backend_failed() -> None:
    class FailedPolicy:
        client = object()

        def resolve(self, *_args, **_kwargs):
            raise consult_claude.VibeProxyUnavailableError("invalid response")

    result = consult_claude._run_vibeproxy(
        "question",
        consult_claude.DEFAULT_MODEL,
        10,
        None,
        FailedPolicy(),  # type: ignore[arg-type]
    )

    assert result["timed_out"] is False
    assert result["failure_kind"] == "backend_failed"


def test_run_vibeproxy_sanitizes_unexpected_client_failure() -> None:
    class BrokenClient:
        def anthropic_message(self, **_kwargs):
            raise RuntimeError("sensitive proxy detail")

    class BrokenPolicy:
        client = BrokenClient()

        def resolve(self, *_args, **_kwargs):
            return SimpleNamespace(transport="vibeproxy", resolved_model="claude-fable-5")

    result = consult_claude._run_vibeproxy(
        "question",
        consult_claude.DEFAULT_MODEL,
        10,
        None,
        BrokenPolicy(),  # type: ignore[arg-type]
    )

    assert result == {
        "ok": False,
        "backend": "vibeproxy",
        "timed_out": False,
        "failure_kind": "backend_failed",
        "error": "VibeProxy attempt failed: RuntimeError",
    }


def test_consult_prefer_falls_back_to_cli(monkeypatch) -> None:
    policy = SimpleNamespace(mode=consult_claude.TransportMode.PREFER)
    monkeypatch.setattr(consult_claude.ModelTransportPolicy, "from_env", lambda **_kwargs: policy)
    monkeypatch.setattr(
        consult_claude,
        "_run_vibeproxy",
        lambda *_args, **_kwargs: {
            "ok": False,
            "backend": "vibeproxy",
            "error": "proxy unavailable",
        },
    )
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: {
            "ok": True,
            "backend": "cli",
            "text": "cli answer",
            "elapsed_s": 0.1,
        },
    )

    result = consult_claude.consult("question")

    assert result["ok"] is True
    assert [attempt["backend"] for attempt in result["attempts"]] == [
        "vibeproxy",
        "vibeproxy",
        "cli",
    ]


def test_consult_prefer_fails_closed_after_proxy_configuration_error(monkeypatch) -> None:
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-prefer")
    monkeypatch.setattr(
        consult_claude.ModelTransportPolicy,
        "from_env",
        lambda **_kwargs: (_ for _ in ()).throw(
            consult_claude.VibeProxyConfigurationError("invalid proxy configuration")
        ),
    )
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    result = consult_claude.consult("question")

    assert result["ok"] is False
    assert result["usage_error"] is True
    assert [attempt["backend"] for attempt in result["attempts"]] == ["vibeproxy"]
    assert result["attempts"][0]["error"] == "invalid proxy configuration"


def test_consult_required_fails_closed_on_proxy_configuration_error(monkeypatch) -> None:
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-required")
    monkeypatch.setattr(
        consult_claude.ModelTransportPolicy,
        "from_env",
        lambda **_kwargs: (_ for _ in ()).throw(
            consult_claude.VibeProxyConfigurationError("invalid proxy configuration")
        ),
    )
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    result = consult_claude.consult("question")

    assert result["ok"] is False
    assert result["usage_error"] is True
    assert [attempt["backend"] for attempt in result["attempts"]] == ["vibeproxy"]
    assert result["error"] == "invalid proxy configuration"


def test_consult_rejects_empty_model_with_clean_failure_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    result = consult_claude.consult("question", model="", fallback_model="")

    assert result == {
        "ok": False,
        "model": "",
        "timed_out": False,
        "budget_exhausted": False,
        "rate_limited": False,
        "usage_error": True,
        "attempts": [],
        "error": "model must be a non-empty string",
    }


def test_consult_required_does_not_fall_back_to_cli(monkeypatch) -> None:
    policy = SimpleNamespace(mode=consult_claude.TransportMode.REQUIRED)
    monkeypatch.setattr(consult_claude.ModelTransportPolicy, "from_env", lambda **_kwargs: policy)
    monkeypatch.setattr(
        consult_claude,
        "_run_vibeproxy",
        lambda *_args, **_kwargs: {
            "ok": False,
            "backend": "vibeproxy",
            "error": "proxy unavailable",
        },
    )
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    result = consult_claude.consult("question")

    assert result["ok"] is False
    assert [attempt["backend"] for attempt in result["attempts"]] == ["vibeproxy", "vibeproxy"]


def test_consult_required_budget_excludes_unreachable_fallbacks(monkeypatch) -> None:
    policy = SimpleNamespace(mode=consult_claude.TransportMode.REQUIRED)
    timeouts: list[float] = []
    monotonic_values = iter([0.0, 0.0, 10.0])
    monkeypatch.setattr(consult_claude.ModelTransportPolicy, "from_env", lambda **_kwargs: policy)
    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: next(monotonic_values))

    def fail_proxy(_prompt, _model, timeout, _system, _policy):
        timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "vibeproxy",
            "timed_out": True,
            "error": "timeout",
        }

    monkeypatch.setattr(consult_claude, "_run_vibeproxy", fail_proxy)

    result = consult_claude.consult(
        "question",
        timeout=10,
        api_fallback=True,
        openrouter_fallback=True,
    )

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert timeouts == [10, 10]
    assert [attempt["backend"] for attempt in result["attempts"]] == [
        "vibeproxy",
        "vibeproxy",
    ]


def test_consult_api_fallback_skips_cli_only_model(monkeypatch) -> None:
    cli_models: list[str] = []
    api_models: list[str] = []

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {"ok": False, "backend": "cli", "error": f"{model} unavailable"}

    def fake_api(_prompt: str, model: str, _timeout: float, *, system: str | None = None) -> dict:
        del system
        api_models.append(model)
        if model == consult_claude.FALLBACK_MODEL:
            return {"ok": True, "backend": "api", "text": "fallback answer", "elapsed_s": 0.1}
        return {"ok": False, "backend": "api", "error": f"{model} unavailable"}

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_api", fake_api)

    result = consult_claude.consult("question", api_fallback=True)

    assert result["ok"] is True
    assert result["model"] == consult_claude.FALLBACK_MODEL
    assert cli_models == [consult_claude.DEFAULT_MODEL, consult_claude.FALLBACK_MODEL]
    assert api_models == [consult_claude.FALLBACK_MODEL]


def test_consult_openrouter_fallback_is_explicit(monkeypatch) -> None:
    cli_models: list[str] = []
    openrouter_models: list[str] = []
    openrouter_prompts: list[str] = []
    openrouter_systems: list[str | None] = []

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {"ok": False, "backend": "cli", "error": f"{model} unavailable"}

    def fake_openrouter(
        prompt: str,
        model: str,
        _timeout: float,
        system: str | None,
    ) -> dict:
        openrouter_prompts.append(prompt)
        openrouter_systems.append(system)
        openrouter_models.append(model)
        return {
            "ok": True,
            "backend": "openrouter",
            "text": "openrouter answer",
            "elapsed_s": 0.1,
        }

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_openrouter_api", fake_openrouter)

    result = consult_claude.consult(
        "question",
        system="system instructions",
        openrouter_fallback=True,
        openrouter_model="anthropic/claude-test",
    )

    assert result["ok"] is True
    assert result["model"] == "anthropic/claude-test"
    assert result["backend"] == "openrouter"
    assert cli_models == [consult_claude.DEFAULT_MODEL, consult_claude.FALLBACK_MODEL]
    assert openrouter_models == ["anthropic/claude-test"]
    assert openrouter_prompts == ["question"]
    assert openrouter_systems == ["system instructions"]


def test_run_openrouter_api_redacts_http_error_body(monkeypatch) -> None:
    class RaisingUrlopen:
        def __call__(self, *_args, **_kwargs):
            raise consult_claude.urllib.error.HTTPError(
                url=consult_claude.OPENROUTER_API_URL,
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=io.BytesIO(b"profile=/secret/path token=secret prompt text"),
            )

    monkeypatch.setattr(consult_claude, "_resolve_openrouter_api_key", lambda: "test-key")
    monkeypatch.setattr(consult_claude.urllib.request, "urlopen", RaisingUrlopen())

    result = consult_claude._run_openrouter_api(
        "secret prompt",
        "anthropic/claude-test",
        1.0,
        None,
    )

    assert result["ok"] is False
    assert result["error"] == "API OpenRouter HTTP 429: response body redacted"
    assert "secret" not in json.dumps(result)
    assert "profile" not in json.dumps(result).lower()


def test_run_api_redacts_http_error_body(monkeypatch) -> None:
    class RaisingUrlopen:
        def __call__(self, *_args, **_kwargs):
            raise consult_claude.urllib.error.HTTPError(
                url=consult_claude.ANTHROPIC_API_URL,
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=io.BytesIO(b"profile=/secret/path token=secret prompt text"),
            )

    monkeypatch.setattr(consult_claude, "_resolve_api_key", lambda: "test-key")
    monkeypatch.setattr(consult_claude.urllib.request, "urlopen", RaisingUrlopen())

    result = consult_claude._run_api("secret prompt", "claude-fable-5", 1.0, None)

    assert result["ok"] is False
    assert result["error"] == "API HTTP 429: response body redacted"
    assert "secret" not in json.dumps(result)
    assert "profile" not in json.dumps(result).lower()


def test_run_api_redacts_invalid_response_body(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self):
            self._returned = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _amt=None) -> bytes:
            if self._returned:
                return b""
            self._returned = True
            return b"\xff\xfe not utf-8"

    monkeypatch.setattr(consult_claude, "_resolve_api_key", lambda: "test-key")
    monkeypatch.setattr(
        consult_claude.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = consult_claude._run_api("secret prompt", "claude-fable-5", 1.0, None)

    assert result["ok"] is False
    assert result["error"] == "API response parse failed: response body redacted"
    assert "secret" not in json.dumps(result)


def test_run_api_caps_oversized_response_body(monkeypatch) -> None:
    payload = b'{"content":[{"type":"text","text":"secret response"}]}' + (b" " * 128)
    read_amounts: list[int | None] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, amt=None) -> bytes:
            read_amounts.append(amt)
            if amt is None or amt < 0:
                return payload
            return payload[:amt]

        read1 = read

    monkeypatch.setattr(consult_claude, "MAX_API_RESPONSE_BYTES", 8, raising=False)
    monkeypatch.setattr(consult_claude, "_resolve_api_key", lambda: "test-key")
    monkeypatch.setattr(
        consult_claude.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = consult_claude._run_api("secret prompt", "claude-opus-4-8", 1.0, None)

    assert read_amounts == [9]
    assert result["ok"] is False
    assert result["error"] == "API response exceeds maximum size: response body redacted"
    assert "secret" not in json.dumps(result)


def test_run_api_times_out_slow_streaming_response(monkeypatch) -> None:
    clock = {"now": 0.0}
    read_amounts: list[int | None] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, amt=None) -> bytes:
            read_amounts.append(amt)
            clock["now"] += 0.6
            return b" "

    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(consult_claude, "_resolve_api_key", lambda: "test-key")
    monkeypatch.setattr(
        consult_claude.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = consult_claude._run_api("secret prompt", "claude-opus-4-8", 1.0, None)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["error"] == "API request failed: TimeoutError"
    assert read_amounts == [
        1,
        1,
    ]
    assert "secret" not in json.dumps(result)


def test_run_api_read1_uses_remaining_socket_timeout(monkeypatch) -> None:
    clock = {"now": 0.0}
    read_amounts: list[int] = []
    socket_timeouts: list[float] = []

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            socket_timeouts.append(timeout)

    class FakeRaw:
        _sock = FakeSocket()

    class FakeFp:
        raw = FakeRaw()

    class FakeResponse:
        fp = FakeFp()

        def __init__(self):
            self._chunks = [
                b'{"content":[{"type":"text","text":"bounded answer"}]}',
                b"",
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read1(self, amount: int) -> bytes:
            read_amounts.append(amount)
            chunk = self._chunks.pop(0)
            clock["now"] += 0.25
            return chunk

    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(consult_claude, "_resolve_api_key", lambda: "test-key")
    monkeypatch.setattr(
        consult_claude.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = consult_claude._run_api("secret prompt", "claude-opus-4-8", 1.0, None)

    assert result["ok"] is True
    assert result["text"] == "bounded answer"
    assert read_amounts == [
        consult_claude.API_RESPONSE_READ_CHUNK_BYTES,
        consult_claude.API_RESPONSE_READ_CHUNK_BYTES,
    ]
    assert socket_timeouts == [1.0, 0.75]


def test_run_api_read1_timeout_after_single_socket_read(monkeypatch) -> None:
    clock = {"now": 0.0}
    socket_timeouts: list[float] = []

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            socket_timeouts.append(timeout)

    class FakeRaw:
        _sock = FakeSocket()

    class FakeFp:
        raw = FakeRaw()

    class FakeResponse:
        fp = FakeFp()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read1(self, _amount: int) -> bytes:
            clock["now"] += 1.0
            return b" "

    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(consult_claude, "_resolve_api_key", lambda: "test-key")
    monkeypatch.setattr(
        consult_claude.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = consult_claude._run_api("secret prompt", "claude-opus-4-8", 1.0, None)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["error"] == "API request failed: TimeoutError"
    assert socket_timeouts == [1.0]


def test_consult_enforces_overall_timeout_before_fallbacks(monkeypatch) -> None:
    cli_models: list[str] = []
    monotonic_values = iter([0.0, 0.0, 10.0, 10.0])

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {"ok": False, "backend": "cli", "timed_out": True, "error": "timeout"}

    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)

    result = consult_claude.consult(
        "question",
        timeout=10,
        overall_timeout=10,
        api_fallback=True,
    )

    assert result["ok"] is False
    assert result["timed_out"] is False
    assert result["budget_exhausted"] is True
    assert cli_models == [consult_claude.DEFAULT_MODEL]
    assert [attempt["backend"] for attempt in result["attempts"]] == [
        "cli",
        "cli",
        "api",
    ]
    assert result["attempts"][0]["timed_out"] is True
    assert all(attempt.get("budget_exhausted") for attempt in result["attempts"][1:])
    assert "overall consult timeout exhausted before attempt" in result["error"]


def test_consult_default_budget_allows_fallback_after_primary_timeout(monkeypatch) -> None:
    cli_models: list[str] = []
    cli_timeouts: list[float] = []
    monotonic_values = iter([0.0, 0.0, 10.0])

    def fake_cli(_prompt: str, model: str, timeout: float) -> dict:
        cli_models.append(model)
        cli_timeouts.append(timeout)
        if model == consult_claude.DEFAULT_MODEL:
            return {"ok": False, "backend": "cli", "timed_out": True, "error": "timeout"}
        return {"ok": True, "backend": "cli", "text": "fallback cli answer", "elapsed_s": 0.1}

    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)

    result = consult_claude.consult("question", timeout=10)

    assert result["ok"] is True
    assert result["model"] == consult_claude.FALLBACK_MODEL
    assert cli_models == [consult_claude.DEFAULT_MODEL, consult_claude.FALLBACK_MODEL]
    assert cli_timeouts == [10, 10]


def test_consult_reports_timeout_only_when_all_attempts_timeout(monkeypatch) -> None:
    attempt_timeouts: list[float] = []
    monotonic_values = iter([0.0, 0.0, 10.0])

    def fake_cli(_prompt: str, model: str, timeout: float) -> dict:
        attempt_timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "cli",
            "timed_out": True,
            "error": f"{model} timed out",
        }

    def fake_api(_prompt: str, model: str, timeout: float, *, system: str | None = None) -> dict:
        del system
        attempt_timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "api",
            "timed_out": True,
            "error": f"{model} timed out",
        }

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_api", fake_api)
    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: next(monotonic_values))

    result = consult_claude.consult("question")

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert [attempt["model"] for attempt in result["attempts"]] == [
        consult_claude.DEFAULT_MODEL,
        consult_claude.FALLBACK_MODEL,
    ]
    assert attempt_timeouts == [600, 600]


def test_unavailable_proxy_does_not_mask_cli_timeouts(monkeypatch) -> None:
    policy = SimpleNamespace(mode=consult_claude.TransportMode.PREFER)
    monkeypatch.setattr(consult_claude.ModelTransportPolicy, "from_env", lambda **_kwargs: policy)
    monkeypatch.setattr(
        consult_claude,
        "_run_vibeproxy",
        lambda *_args, **_kwargs: {
            "ok": False,
            "backend": "vibeproxy",
            "timed_out": False,
            "failure_kind": "transport_unavailable",
            "error": "proxy unavailable",
        },
    )
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda _prompt, model, _timeout: {
            "ok": False,
            "backend": "cli",
            "timed_out": True,
            "error": f"{model} timed out",
        },
    )

    result = consult_claude.consult("question")

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert [attempt["backend"] for attempt in result["attempts"]] == [
        "vibeproxy",
        "vibeproxy",
        "cli",
        "cli",
    ]


def test_consult_explicit_api_fallback_has_budget_for_supported_models(monkeypatch) -> None:
    attempt_timeouts: list[float] = []
    monotonic_values = iter([0.0, 0.0, 10.0, 20.0])

    def fake_cli(_prompt: str, model: str, timeout: float) -> dict:
        attempt_timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "cli",
            "timed_out": True,
            "error": f"{model} timed out",
        }

    def fake_api(_prompt: str, model: str, timeout: float, *, system: str | None = None) -> dict:
        del model, system
        attempt_timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "api",
            "timed_out": True,
            "error": "api timed out",
        }

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_api", fake_api)
    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: next(monotonic_values))

    result = consult_claude.consult("question", timeout=10, api_fallback=True)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert [attempt["model"] for attempt in result["attempts"]] == [
        consult_claude.DEFAULT_MODEL,
        consult_claude.FALLBACK_MODEL,
        consult_claude.FALLBACK_MODEL,
    ]
    assert attempt_timeouts == [10, 10, 10]


def test_consult_explicit_openrouter_fallback_has_budget(monkeypatch) -> None:
    attempt_timeouts: list[float] = []
    monotonic_values = iter([0.0, 0.0, 10.0, 20.0])

    def fake_cli(_prompt: str, model: str, timeout: float) -> dict:
        attempt_timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "cli",
            "timed_out": True,
            "error": f"{model} timed out",
        }

    def fake_openrouter(
        _prompt: str,
        model: str,
        timeout: float,
        system: str | None,
    ) -> dict:
        del model, system
        attempt_timeouts.append(timeout)
        return {
            "ok": False,
            "backend": "openrouter",
            "timed_out": True,
            "error": "openrouter timed out",
        }

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_openrouter_api", fake_openrouter)
    monkeypatch.setattr(consult_claude.time, "monotonic", lambda: next(monotonic_values))

    result = consult_claude.consult("question", timeout=10, openrouter_fallback=True)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert [attempt["backend"] for attempt in result["attempts"]] == [
        "cli",
        "cli",
        "openrouter",
    ]
    assert attempt_timeouts == [10, 10, 10]


def test_run_cli_timeout_kills_process_group(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakePopen:
        returncode = None
        pid = 6789

        def __init__(self, *args, **kwargs):
            calls.append(("popen", kwargs["start_new_session"]))

        def communicate(self, input, timeout):
            calls.append(("communicate", timeout))
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=timeout)

        def wait(self, timeout):
            calls.append(("wait", timeout))

    monkeypatch.setattr(consult_claude.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(consult_claude.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(consult_claude.os, "killpg", lambda pid, sig: calls.append(("killpg", pid)))

    result = consult_claude._run_cli("question", "claude-fable-5", 1.5)

    assert result["timed_out"] is True
    assert ("popen", True) in calls
    assert ("killpg", 6789) in calls
    assert ("wait", 5) in calls


def test_run_cli_kills_process_group_after_communicate_errors(monkeypatch) -> None:
    for exc in [OSError("boom"), UnicodeError("boom"), ValueError("boom")]:
        calls: list[tuple[str, object]] = []

        class FakePopen:
            returncode = None
            pid = 2468

            def __init__(self, *args, **kwargs):
                calls.append(("popen", kwargs["start_new_session"]))

            def communicate(self, input, timeout):
                calls.append(("communicate", timeout))
                raise exc

            def wait(self, timeout):
                calls.append(("wait", timeout))

        monkeypatch.setattr(consult_claude.shutil, "which", lambda name: "/usr/bin/claude")
        monkeypatch.setattr(consult_claude.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(
            consult_claude.os,
            "killpg",
            lambda pid, sig: calls.append(("killpg", pid)),
        )

        result = consult_claude._run_cli("question", "claude-fable-5", 1.5)

        assert result["ok"] is False
        assert result["error"] == f"claude CLI launch failed: {type(exc).__name__}"
        assert ("popen", True) in calls
        assert ("killpg", 2468) in calls
        assert ("wait", 5) in calls


def test_consult_tries_fallback_cli_after_primary_timeout(monkeypatch) -> None:
    cli_models: list[str] = []

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        if model == consult_claude.DEFAULT_MODEL:
            return {"ok": False, "backend": "cli", "timed_out": True, "error": "timeout"}
        return {"ok": True, "backend": "cli", "text": "fallback cli answer", "elapsed_s": 0.1}

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)

    result = consult_claude.consult("question", api_fallback=False)

    assert result["ok"] is True
    assert result["model"] == consult_claude.FALLBACK_MODEL
    assert cli_models == [consult_claude.DEFAULT_MODEL, consult_claude.FALLBACK_MODEL]


def test_consult_skips_redundant_cli_fallback_after_subscription_rate_limit(
    monkeypatch,
) -> None:
    cli_models: list[str] = []

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {
            "ok": False,
            "backend": "cli",
            "rate_limited": True,
            "failure_kind": "rate_limited",
            "error": "claude CLI rate limited, rc=1",
        }

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)

    result = consult_claude.consult("question", api_fallback=False)

    assert result["ok"] is False
    assert result["rate_limited"] is True
    assert result["model"] == consult_claude.DEFAULT_MODEL
    assert cli_models == [consult_claude.DEFAULT_MODEL]


def test_consult_rate_limit_still_allows_explicit_openrouter_fallback(monkeypatch) -> None:
    cli_models: list[str] = []

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {
            "ok": False,
            "backend": "cli",
            "rate_limited": True,
            "failure_kind": "rate_limited",
            "error": "claude CLI rate limited, rc=1",
        }

    def fake_openrouter(
        _prompt: str,
        model: str,
        _timeout: float,
        *,
        system: str | None = None,
    ) -> dict:
        assert model == "anthropic/claude-test"
        assert system is None
        return {"ok": True, "backend": "openrouter", "text": "fallback answer"}

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)
    monkeypatch.setattr(consult_claude, "_run_openrouter_api", fake_openrouter)

    result = consult_claude.consult(
        "question",
        openrouter_fallback=True,
        openrouter_model="anthropic/claude-test",
    )

    assert result["ok"] is True
    assert result["backend"] == "openrouter"
    assert cli_models == [consult_claude.DEFAULT_MODEL]


def test_main_json_surfaces_safe_rate_limit_classification(monkeypatch, capsys) -> None:
    def fake_consult(*_args, **_kwargs) -> dict:
        return {
            "ok": False,
            "model": consult_claude.DEFAULT_MODEL,
            "timed_out": False,
            "budget_exhausted": False,
            "rate_limited": True,
            "attempts": [
                {
                    "model": consult_claude.DEFAULT_MODEL,
                    "ok": False,
                    "backend": "cli",
                    "rate_limited": True,
                    "failure_kind": "rate_limited",
                    "error": "claude CLI rate limited, rc=1",
                }
            ],
            "error": "claude CLI rate limited, rc=1",
        }

    monkeypatch.setattr(consult_claude, "consult", fake_consult)

    rc = consult_claude.main(["--json", "question"])

    assert rc == consult_claude.EXIT_ALL_FAILED
    payload = json.loads(capsys.readouterr().out)
    assert payload["rate_limited"] is True
    assert payload["attempts"][0]["failure_kind"] == "rate_limited"


def test_consult_failure_reports_last_attempted_model(monkeypatch) -> None:
    cli_models: list[str] = []

    def fake_cli(_prompt: str, model: str, _timeout: float) -> dict:
        cli_models.append(model)
        return {"ok": False, "backend": "cli", "error": f"{model} unavailable"}

    monkeypatch.setattr(consult_claude, "_run_cli", fake_cli)

    result = consult_claude.consult("question", api_fallback=False)

    assert result["ok"] is False
    assert result["model"] == consult_claude.FALLBACK_MODEL
    assert cli_models == [consult_claude.DEFAULT_MODEL, consult_claude.FALLBACK_MODEL]

    cli_models.clear()

    result = consult_claude.consult(
        "question",
        fallback_model=None,
        api_fallback=False,
    )

    assert result["ok"] is False
    assert result["model"] == consult_claude.DEFAULT_MODEL
    assert cli_models == [consult_claude.DEFAULT_MODEL]


def test_main_rejects_non_positive_timeout(capsys) -> None:
    rc = consult_claude.main(["--timeout", "0", "question"])

    assert rc == consult_claude.EXIT_USAGE
    assert "positive finite" in capsys.readouterr().err


def test_main_rejects_non_positive_overall_timeout(capsys) -> None:
    rc = consult_claude.main(["--overall-timeout", "0", "question"])

    assert rc == consult_claude.EXIT_USAGE
    assert "positive finite" in capsys.readouterr().err


def test_main_rejects_invalid_transport_as_usage_error(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "required")
    monkeypatch.setattr(
        consult_claude,
        "_run_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    rc = consult_claude.main(["--json", "question"])

    assert rc == consult_claude.EXIT_USAGE
    result = json.loads(capsys.readouterr().out)
    assert result["usage_error"] is True
    assert result["error"] == "invalid ARAGORA_MODEL_TRANSPORT: required"


def test_consult_rejects_non_positive_timeout_for_programmatic_callers() -> None:
    try:
        consult_claude.consult("question", timeout=0)
    except ValueError as exc:
        assert "timeout must be a positive finite number" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_consult_rejects_non_positive_overall_timeout_for_programmatic_callers() -> None:
    try:
        consult_claude.consult("question", overall_timeout=0)
    except ValueError as exc:
        assert "overall_timeout must be a positive finite number" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_consult_rejects_oversized_prompt_for_programmatic_callers(monkeypatch) -> None:
    monkeypatch.setattr(consult_claude, "MAX_PROMPT_BYTES", 8)

    def fail_cli(*_args, **_kwargs):
        raise AssertionError("oversized prompt must be rejected before CLI")

    monkeypatch.setattr(consult_claude, "_run_cli", fail_cli)

    try:
        consult_claude.consult("x" * 9)
    except ValueError as exc:
        assert "prompt exceeds maximum size" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_consult_rejects_oversized_system_prompt_for_programmatic_callers(monkeypatch) -> None:
    monkeypatch.setattr(consult_claude, "MAX_PROMPT_BYTES", 10)

    def fail_cli(*_args, **_kwargs):
        raise AssertionError("oversized prompt must be rejected before CLI")

    monkeypatch.setattr(consult_claude, "_run_cli", fail_cli)

    try:
        consult_claude.consult("abc", system="system")
    except ValueError as exc:
        assert "prompt exceeds maximum size" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_main_reports_missing_prompt_file(capsys, tmp_path) -> None:
    missing = tmp_path / "missing.md"

    rc = consult_claude.main(["--prompt-file", str(missing)])

    assert rc == consult_claude.EXIT_NO_PROMPT
    assert "cannot read --prompt-file" in capsys.readouterr().err


def test_main_rejects_non_regular_prompt_file_before_read(capsys, tmp_path) -> None:
    rc = consult_claude.main(["--prompt-file", str(tmp_path)])

    assert rc == consult_claude.EXIT_NO_PROMPT
    assert "prompt file must be a regular file" in capsys.readouterr().err


def test_prompt_file_read_is_capped_after_stat(monkeypatch) -> None:
    read_amounts: list[int] = []

    class FakeHandle:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, amount: int) -> bytes:
            read_amounts.append(amount)
            return b"x" * amount

    class FakePath:
        def __init__(self, path_text: str):
            self.path_text = path_text

        def stat(self):
            return SimpleNamespace(st_size=0, st_mode=stat.S_IFREG | 0o644)

        def open(self, mode: str):
            assert mode == "rb"
            return FakeHandle()

    monkeypatch.setattr(consult_claude, "MAX_PROMPT_BYTES", 8)
    monkeypatch.setattr(consult_claude, "Path", FakePath)

    try:
        consult_claude._read_prompt_file("growing-prompt.md")
    except ValueError as exc:
        assert "prompt exceeds maximum size" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert read_amounts == [9]


def test_main_rejects_oversized_prompt_file_before_consult(monkeypatch, capsys, tmp_path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("x" * 9, encoding="utf-8")
    monkeypatch.setattr(consult_claude, "MAX_PROMPT_BYTES", 8)

    def fail_consult(*_args, **_kwargs):
        raise AssertionError("oversized prompt must be rejected before consult")

    monkeypatch.setattr(consult_claude, "consult", fail_consult)

    rc = consult_claude.main(["--prompt-file", str(prompt_file), "--api-fallback"])

    assert rc == consult_claude.EXIT_NO_PROMPT
    assert "prompt exceeds maximum size" in capsys.readouterr().err


def test_main_rejects_oversized_prompt_after_system_before_backend(monkeypatch, capsys) -> None:
    monkeypatch.setattr(consult_claude, "MAX_PROMPT_BYTES", 10)

    def fail_cli(*_args, **_kwargs):
        raise AssertionError("oversized prompt must be rejected before CLI")

    monkeypatch.setattr(consult_claude, "_run_cli", fail_cli)

    rc = consult_claude.main(["--system", "system", "abc"])

    assert rc == consult_claude.EXIT_NO_PROMPT
    assert "prompt exceeds maximum size" in capsys.readouterr().err


def test_main_rejects_oversized_stdin_before_consult(monkeypatch, capsys) -> None:
    monkeypatch.setattr(consult_claude, "MAX_PROMPT_BYTES", 8)
    monkeypatch.setattr(consult_claude.sys, "stdin", io.StringIO("x" * 9))

    def fail_consult(*_args, **_kwargs):
        raise AssertionError("oversized prompt must be rejected before consult")

    monkeypatch.setattr(consult_claude, "consult", fail_consult)

    rc = consult_claude.main(["--json"])

    assert rc == consult_claude.EXIT_NO_PROMPT
    assert "prompt exceeds maximum size" in capsys.readouterr().err
