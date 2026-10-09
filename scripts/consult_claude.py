#!/usr/bin/env python3
"""Bounded advisory consult of a specific Claude model (default: Claude Fable 5).

Gives any agent (Codex conductor, Droid, Claude Code, humans) a reliable way to
ask a named Claude model for read-only advice with hard per-attempt and overall
timeouts. The known failure mode this fixes: ad-hoc ``timeout 120 claude -p
"..."`` calls hang or time out with no output and no diagnostics.

Backends, in order:

1. Local VibeProxy — used only when ``ARAGORA_MODEL_TRANSPORT`` is explicitly
   set to ``vibeproxy-prefer`` or ``vibeproxy-required``. Loopback alone does
   not authenticate the process receiving a prompt, so direct mode is the
   default.
2. ``claude`` CLI (subscription auth) — routed through the authenticated
   ``claude_profile.sh`` pool when available, with ``--model`` forwarded and a
   hard subprocess timeout.
3. Anthropic Messages API — used only with explicit ``--api-fallback`` opt-in
   after CLI attempts fail. The key comes from ``ANTHROPIC_API_KEY`` or the
   aragora secrets manager; if neither is present the attempt is recorded as a
   normal failed backend attempt.
4. OpenRouter Chat Completions API — used only with explicit
   ``--openrouter-fallback`` opt-in after CLI/API attempts fail. This is useful
   when the Claude subscription CLI is quota-exhausted but an OpenRouter key is
   available. The key comes from ``OPENROUTER_API_KEY`` or the aragora secrets
   manager.

Output is the raw model text on stdout, or a JSON envelope with ``--json``.
Exit codes: 0 ok, 2 all backends timed out, 3 no prompt, 4 all backends failed
or budget exhausted, 64 usage/config error.

Examples::

    python scripts/consult_claude.py "Which PR should I settle next?"
    python scripts/consult_claude.py --prompt-file /tmp/question.md --json
    echo "$QUESTION" | python scripts/consult_claude.py --timeout 300 --overall-timeout 1200
    python scripts/consult_claude.py --api-fallback --prompt-file /tmp/question.md
    python scripts/consult_claude.py --openrouter-fallback --prompt-file /tmp/question.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aragora.agents.transports.vibeproxy import (  # noqa: E402
    ModelTransportPolicy,
    TransportMode,
    VibeProxyConfigurationError,
    VibeProxyTimeoutError,
    VibeProxyUnavailableError,
)
from aragora.config.model_pins import (  # noqa: E402
    FABLE_51_DIRECT,
    FABLE_51_VIA_OPENROUTER,
    OPUS_5_DIRECT,
)

DEFAULT_MODEL = FABLE_51_DIRECT
FALLBACK_MODEL = OPUS_5_DIRECT
DEFAULT_TIMEOUT_SECONDS = 600
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = os.environ.get(
    "ARAGORA_CONSULT_OPENROUTER_MODEL",
    os.environ.get("OPENROUTER_FABLE_MODEL", FABLE_51_VIA_OPENROUTER),
)
API_MAX_TOKENS = 8192
MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
# Model ids the direct Messages API is known NOT to serve, so the API
# backend skips them rather than burning an attempt on a certain refusal.
# The CLI backend still runs them -- that is the whole point of the set.
#
# claude-fable-5-1 was removed on 2026-09-05 (merge-gate ruling on finding
# C-P3 of #9989): the Claude API reference lists claude-fable-5-1 as a
# direct Messages API model, and this same PR makes it the default direct-API
# model on every other surface, so keeping it here contradicted the rest of
# the branch. claude-fable-5 stays: it has been observed refusing on this
# path and nothing in the API reference or this branch re-verifies it.
API_UNSUPPORTED_MODELS = {"claude-fable-5"}
MAX_PROMPT_BYTES = 512 * 1024
API_RESPONSE_READ_CHUNK_BYTES = 64 * 1024
_CLI_RATE_LIMIT_MARKERS = (
    "you've hit your session limit",
    "you have hit your session limit",
    "rate limit exceeded",
    "usage limit reached",
    "hit your usage limit",
)

EXIT_OK = 0
EXIT_TIMEOUT = 2
EXIT_NO_PROMPT = 3
EXIT_ALL_FAILED = 4
EXIT_USAGE = 64


def _safe_cli_error(*, returncode: int | None = None, empty: bool | None = None) -> str:
    """Public CLI failure string safe for JSON logs and durable artifacts."""

    parts = ["claude CLI failed"]
    if returncode is not None:
        parts.append(f"rc={returncode}")
    if empty is not None:
        parts.append(f"empty={empty}")
    return ", ".join(parts)


def _classify_cli_failure(text: str) -> dict[str, bool | str]:
    """Classify known CLI failures without returning raw model or account output."""

    lowered = text.lower()
    if any(marker in lowered for marker in _CLI_RATE_LIMIT_MARKERS):
        return {
            "rate_limited": True,
            "failure_kind": "rate_limited",
        }
    return {"failure_kind": "cli_error"}


def _safe_api_error(message: str) -> str:
    """Public API failure string safe for JSON logs and durable artifacts."""

    return f"API {message}"


def _validate_timeout(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


@contextmanager
def _claude_empty_mcp_config_file():
    """Write an empty Claude MCP config to avoid wedged local server handshakes."""

    fd, path_text = tempfile.mkstemp(prefix="aragora-consult-claude-mcp-", suffix=".json")
    path = Path(path_text)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"mcpServers": {}}, handle)
            handle.write("\n")
        yield path
    finally:
        path.unlink(missing_ok=True)


def _build_cli_command(model: str, mcp_config_path: Path) -> tuple[list[str], bool]:
    """Return the claude CLI command, profile-pool wrapped when possible."""
    base = [
        "claude",
        "--print",
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_config_path),
        "--model",
        model,
    ]
    try:
        from aragora.agents.claude_profile_pool import build_claude_command

        return build_claude_command(base, repo_root=_REPO_ROOT)
    except Exception:
        return base, False


def _strip_preamble(text: str) -> str:
    try:
        from aragora.agents.claude_profile_pool import strip_profile_preamble

        return strip_profile_preamble(text)
    except Exception:
        return text.strip()


def _run_cli(prompt: str, model: str, timeout: float) -> dict:
    """One bounded claude CLI attempt. Never raises; returns a result dict."""
    if shutil.which("claude") is None:
        return {"ok": False, "backend": "cli", "error": "claude CLI not on PATH"}
    started = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    try:
        with _claude_empty_mcp_config_file() as mcp_config_path:
            command, used_profile = _build_cli_command(model, mcp_config_path)
            backend = "cli"
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            stdout, _stderr = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        if proc is not None:
            _kill_process_group(proc)
        return {
            "ok": False,
            "backend": locals().get("backend", "cli"),
            "timed_out": True,
            "elapsed_s": round(time.monotonic() - started, 1),
            "error": f"claude CLI exceeded {timeout:.0f}s timeout",
        }
    except (OSError, UnicodeError, ValueError) as exc:
        if proc is not None:
            _kill_process_group(proc)
        return {
            "ok": False,
            "backend": locals().get("backend", "cli"),
            "error": f"claude CLI launch failed: {type(exc).__name__}",
        }
    elapsed = round(time.monotonic() - started, 1)
    text = _strip_preamble(stdout) if used_profile else stdout.strip()
    if proc.returncode != 0:
        classification = _classify_cli_failure(text)
        error = _safe_cli_error(returncode=proc.returncode, empty=not text)
        if classification.get("rate_limited"):
            error = f"claude CLI rate limited, rc={proc.returncode}"
        return {
            "ok": False,
            "backend": backend,
            "elapsed_s": elapsed,
            **classification,
            "error": error,
        }
    if text:
        return {"ok": True, "backend": backend, "elapsed_s": elapsed, "text": text}
    return {
        "ok": False,
        "backend": backend,
        "elapsed_s": elapsed,
        "error": _safe_cli_error(empty=True),
    }


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    """Best-effort cleanup for spawned Claude and any nested child process."""

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            proc.kill()
        except OSError:
            return
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _resolve_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        from aragora.config.secrets import get_secret

        return get_secret("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _resolve_openrouter_api_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        from aragora.config.secrets import get_secret

        return get_secret("OPENROUTER_API_KEY")
    except Exception:
        return None


def _response_socket(response):
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    for candidate in (
        getattr(raw, "_sock", None),
        getattr(raw, "sock", None),
        getattr(fp, "_sock", None),
        getattr(response, "_sock", None),
    ):
        if hasattr(candidate, "settimeout"):
            return candidate
    return None


def _set_response_timeout(response, timeout: float) -> None:
    sock = _response_socket(response)
    if sock is not None:
        sock.settimeout(max(0.001, timeout))


def _read_api_response_chunk(response, amount: int) -> bytes:
    read1 = getattr(response, "read1", None)
    if callable(read1):
        return read1(amount)
    return response.read(min(amount, 1))


def _read_api_response_with_deadline(response, *, deadline: float) -> bytes:
    """Read a bounded API body without letting slow streams exceed the wall clock."""

    chunks: list[bytes] = []
    total = 0
    limit = MAX_API_RESPONSE_BYTES + 1
    while total < limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("API response read exceeded timeout")
        amount = min(API_RESPONSE_READ_CHUNK_BYTES, limit - total)
        _set_response_timeout(response, remaining)
        chunk = _read_api_response_chunk(response, amount)
        if time.monotonic() >= deadline:
            raise TimeoutError("API response read exceeded timeout")
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _run_api(prompt: str, model: str, timeout: float, system: str | None) -> dict:
    """One bounded Anthropic Messages API attempt. Never raises."""
    key = _resolve_api_key()
    if not key:
        return {"ok": False, "backend": "api", "error": "no ANTHROPIC_API_KEY available"}
    payload: dict = {
        "model": model,
        "max_tokens": API_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    started = time.monotonic()
    deadline = started + timeout
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _read_api_response_with_deadline(response, deadline=deadline)
            if len(raw) > MAX_API_RESPONSE_BYTES:
                return {
                    "ok": False,
                    "backend": "api",
                    "error": _safe_api_error(
                        "response exceeds maximum size: response body redacted"
                    ),
                }
            body = json.loads(raw.decode())
            if not isinstance(body, dict):
                raise ValueError("API response JSON is not an object")
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "backend": "api",
            "error": _safe_api_error(f"HTTP {exc.code}: response body redacted"),
        }
    except (json.JSONDecodeError, UnicodeError, ValueError):
        return {
            "ok": False,
            "backend": "api",
            "error": _safe_api_error("response parse failed: response body redacted"),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        timed_out = "timed out" in str(exc).lower() or isinstance(exc, TimeoutError)
        return {
            "ok": False,
            "backend": "api",
            "timed_out": timed_out,
            "error": _safe_api_error(f"request failed: {type(exc).__name__}"),
        }
    elapsed = round(time.monotonic() - started, 1)
    content = body.get("content", [])
    if not isinstance(content, list):
        content = []
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        return {
            "ok": False,
            "backend": "api",
            "elapsed_s": elapsed,
            "error": "API returned no text",
        }
    return {"ok": True, "backend": "api", "elapsed_s": elapsed, "text": text}


def _run_vibeproxy(
    prompt: str,
    model: str,
    timeout: float,
    system: str | None,
    policy: ModelTransportPolicy,
) -> dict:
    """One bounded VibeProxy Claude attempt. Never exposes local credentials."""

    started = time.monotonic()
    try:
        route = policy.resolve("anthropic", model, capabilities=("chat",))
        if route.transport != "vibeproxy" or policy.client is None:
            return {
                "ok": False,
                "backend": "vibeproxy",
                "timed_out": False,
                "failure_kind": "transport_unavailable",
                "error": route.fallback_reason or "VibeProxy route unavailable",
            }
        text = policy.client.anthropic_message(
            model=route.resolved_model,
            prompt=prompt,
            timeout=timeout,
            system=system,
            max_tokens=API_MAX_TOKENS,
        )
    except VibeProxyTimeoutError as exc:
        return {
            "ok": False,
            "backend": "vibeproxy",
            "timed_out": True,
            "error": str(exc),
        }
    except VibeProxyConfigurationError as exc:
        return {
            "ok": False,
            "backend": "vibeproxy",
            "timed_out": False,
            "failure_kind": "configuration_error",
            "error": str(exc),
        }
    except VibeProxyUnavailableError as exc:
        return {
            "ok": False,
            "backend": "vibeproxy",
            "timed_out": False,
            "failure_kind": "backend_failed",
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "backend": "vibeproxy",
            "timed_out": False,
            "failure_kind": "backend_failed",
            "error": f"VibeProxy attempt failed: {type(exc).__name__}",
        }
    return {
        "ok": True,
        "backend": "vibeproxy",
        "elapsed_s": round(time.monotonic() - started, 1),
        "text": text,
    }


def _run_openrouter_api(prompt: str, model: str, timeout: float, system: str | None) -> dict:
    """One bounded OpenRouter Chat Completions attempt. Never raises."""
    key = _resolve_openrouter_api_key()
    if not key:
        return {
            "ok": False,
            "backend": "openrouter",
            "error": "no OPENROUTER_API_KEY available",
        }
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "max_tokens": API_MAX_TOKENS,
        "messages": messages,
    }
    request = urllib.request.Request(
        OPENROUTER_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
            "http-referer": "https://github.com/synaptent/aragora",
            "x-title": "Aragora bounded consult",
        },
    )
    started = time.monotonic()
    deadline = started + timeout
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _read_api_response_with_deadline(response, deadline=deadline)
            if len(raw) > MAX_API_RESPONSE_BYTES:
                return {
                    "ok": False,
                    "backend": "openrouter",
                    "error": _safe_api_error(
                        "OpenRouter response exceeds maximum size: response body redacted"
                    ),
                }
            body = json.loads(raw.decode())
            if not isinstance(body, dict):
                raise ValueError("OpenRouter response JSON is not an object")
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "backend": "openrouter",
            "error": _safe_api_error(f"OpenRouter HTTP {exc.code}: response body redacted"),
        }
    except (json.JSONDecodeError, UnicodeError, ValueError):
        return {
            "ok": False,
            "backend": "openrouter",
            "error": _safe_api_error("OpenRouter response parse failed: response body redacted"),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        timed_out = "timed out" in str(exc).lower() or isinstance(exc, TimeoutError)
        return {
            "ok": False,
            "backend": "openrouter",
            "timed_out": timed_out,
            "error": _safe_api_error(f"OpenRouter request failed: {type(exc).__name__}"),
        }
    elapsed = round(time.monotonic() - started, 1)
    choices = body.get("choices", [])
    if not isinstance(choices, list):
        choices = []
    text_parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            text_parts.extend(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
    text = "".join(text_parts).strip()
    if not text:
        return {
            "ok": False,
            "backend": "openrouter",
            "elapsed_s": elapsed,
            "error": "OpenRouter returned no text",
        }
    return {"ok": True, "backend": "openrouter", "elapsed_s": elapsed, "text": text}


def _remaining_timeout(started: float, overall_timeout: float, per_attempt_timeout: float) -> float:
    remaining = overall_timeout - (time.monotonic() - started)
    return max(0.0, min(per_attempt_timeout, remaining))


def _append_budget_exhausted(attempts: list[dict], *, model: str, backend: str) -> None:
    attempts.append(
        {
            "model": model,
            "ok": False,
            "backend": backend,
            "budget_exhausted": True,
            "error": "overall consult timeout exhausted before attempt",
        }
    )


def _api_models(model: str, fallback_model: str | None) -> list[str]:
    models: list[str] = []
    for candidate in (model, fallback_model):
        if candidate and candidate not in API_UNSUPPORTED_MODELS and candidate not in models:
            models.append(candidate)
    return models


def _planned_attempt_count(
    *,
    model: str,
    fallback_model: str | None,
    api_fallback: bool,
    openrouter_fallback: bool,
    vibeproxy_attempts: int = 0,
) -> int:
    cli_attempts = 1 + int(bool(fallback_model and fallback_model != model))
    api_attempts = len(_api_models(model, fallback_model)) if api_fallback else 0
    openrouter_attempts = int(openrouter_fallback)
    return vibeproxy_attempts + cli_attempts + api_attempts + openrouter_attempts


def _default_overall_timeout(
    *,
    timeout: float,
    model: str,
    fallback_model: str | None,
    api_fallback: bool,
    openrouter_fallback: bool,
    vibeproxy_attempts: int = 0,
) -> float:
    return timeout * _planned_attempt_count(
        model=model,
        fallback_model=fallback_model,
        api_fallback=api_fallback,
        openrouter_fallback=openrouter_fallback,
        vibeproxy_attempts=vibeproxy_attempts,
    )


def _configuration_failure(model: str, error: str, attempts: list[dict] | None = None) -> dict:
    return {
        "ok": False,
        "model": model,
        "timed_out": False,
        "budget_exhausted": False,
        "rate_limited": False,
        "usage_error": True,
        "attempts": list(attempts or []),
        "error": error,
    }


def _attempts_timed_out(attempts: list[dict]) -> bool:
    """Ignore unavailable transport preflights when classifying execution timeout."""

    executed = [
        attempt for attempt in attempts if attempt.get("failure_kind") != "transport_unavailable"
    ]
    return bool(executed) and all(bool(attempt.get("timed_out")) for attempt in executed)


def consult(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    overall_timeout: float | None = None,
    fallback_model: str | None = FALLBACK_MODEL,
    system: str | None = None,
    api_fallback: bool = False,
    openrouter_fallback: bool = False,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
) -> dict:
    """Run the consult across backends and return the first success.

    ``timeout`` is the per-attempt ceiling. ``overall_timeout`` is the total
    consult budget shared by every CLI/API attempt. When omitted, the default
    budget is derived from the enabled attempt plan so each documented fallback
    path can still run after a full-timeout primary attempt.
    """
    _validate_timeout(timeout, "timeout")
    if overall_timeout is not None:
        _validate_timeout(overall_timeout, "overall_timeout")
    if not isinstance(model, str) or not model.strip():
        return _configuration_failure(str(model or ""), "model must be a non-empty string")
    model = model.strip()
    if fallback_model is not None:
        if not isinstance(fallback_model, str):
            return _configuration_failure(model, "fallback_model must be a string or null")
        fallback_model = fallback_model.strip() or None
    cli_prompt = _compose_prompt(prompt, system)
    attempts: list[dict] = []
    started = time.monotonic()
    try:
        vibeproxy_policy = ModelTransportPolicy.from_env(default_mode=TransportMode.DIRECT)
    except VibeProxyConfigurationError as exc:
        attempts.append(
            {
                "model": model,
                "ok": False,
                "backend": "vibeproxy",
                "timed_out": False,
                "failure_kind": "configuration_error",
                "error": str(exc),
            }
        )
        return _configuration_failure(model, str(exc), attempts)
    vibeproxy_models = list(
        dict.fromkeys(candidate for candidate in (model, fallback_model) if candidate)
    )
    vibeproxy_attempts = (
        len(vibeproxy_models) if vibeproxy_policy.mode is not TransportMode.DIRECT else 0
    )
    if overall_timeout is None:
        if vibeproxy_policy.mode is TransportMode.REQUIRED:
            overall_timeout = timeout * vibeproxy_attempts
        else:
            overall_timeout = _default_overall_timeout(
                timeout=timeout,
                model=model,
                fallback_model=fallback_model,
                api_fallback=api_fallback,
                openrouter_fallback=openrouter_fallback,
                vibeproxy_attempts=vibeproxy_attempts,
            )

    if vibeproxy_policy.mode is not TransportMode.DIRECT:
        for vibeproxy_model in vibeproxy_models:
            attempt_timeout = _remaining_timeout(started, overall_timeout, timeout)
            if attempt_timeout <= 0:
                _append_budget_exhausted(attempts, model=vibeproxy_model, backend="vibeproxy")
                continue
            result = _run_vibeproxy(
                prompt,
                vibeproxy_model,
                attempt_timeout,
                system,
                vibeproxy_policy,
            )
            attempts.append({"model": vibeproxy_model, **result})
            if result.get("ok"):
                return {**result, "model": vibeproxy_model, "attempts": attempts}
        if vibeproxy_policy.mode is TransportMode.REQUIRED:
            return {
                "ok": False,
                "model": str(attempts[-1].get("model", model)) if attempts else model,
                "timed_out": _attempts_timed_out(attempts),
                "budget_exhausted": any(a.get("budget_exhausted") for a in attempts),
                "rate_limited": False,
                "attempts": attempts,
                "error": "; ".join(str(a.get("error")) for a in attempts),
            }

    attempt_timeout = _remaining_timeout(started, overall_timeout, timeout)
    if attempt_timeout <= 0:
        _append_budget_exhausted(attempts, model=model, backend="cli")
    else:
        result = _run_cli(cli_prompt, model, attempt_timeout)
        attempts.append({"model": model, **result})
        if result.get("ok"):
            return {**result, "model": model, "attempts": attempts}
    cli_rate_limited = bool(attempts and attempts[-1].get("rate_limited"))
    if fallback_model and fallback_model != model and not cli_rate_limited:
        attempt_timeout = _remaining_timeout(started, overall_timeout, timeout)
        if attempt_timeout <= 0:
            _append_budget_exhausted(attempts, model=fallback_model, backend="cli")
        else:
            result = _run_cli(cli_prompt, fallback_model, attempt_timeout)
            attempts.append({"model": fallback_model, **result})
            if result.get("ok"):
                return {**result, "model": fallback_model, "attempts": attempts}
    if api_fallback:
        for api_model in _api_models(model, fallback_model):
            if any(
                attempt.get("backend") == "api" and attempt.get("model") == api_model
                for attempt in attempts
            ):
                continue
            attempt_timeout = _remaining_timeout(started, overall_timeout, timeout)
            if attempt_timeout <= 0:
                _append_budget_exhausted(attempts, model=api_model, backend="api")
                continue
            result = _run_api(prompt, api_model, attempt_timeout, system=system)
            attempts.append({"model": api_model, **result})
            if result.get("ok"):
                return {**result, "model": api_model, "attempts": attempts}
    if openrouter_fallback:
        attempt_timeout = _remaining_timeout(started, overall_timeout, timeout)
        if attempt_timeout <= 0:
            _append_budget_exhausted(attempts, model=openrouter_model, backend="openrouter")
        else:
            result = _run_openrouter_api(prompt, openrouter_model, attempt_timeout, system=system)
            attempts.append({"model": openrouter_model, **result})
            if result.get("ok"):
                return {**result, "model": openrouter_model, "attempts": attempts}
    timed_out = _attempts_timed_out(attempts)
    budget_exhausted = any(a.get("budget_exhausted") for a in attempts)
    rate_limited = any(a.get("rate_limited") for a in attempts)
    return {
        "ok": False,
        "model": str(attempts[-1].get("model", model)) if attempts else model,
        "timed_out": timed_out,
        "budget_exhausted": budget_exhausted,
        "rate_limited": rate_limited,
        "attempts": attempts,
        "error": "; ".join(str(a.get("error")) for a in attempts),
    }


def _prompt_too_large_error() -> str:
    return f"prompt exceeds maximum size ({MAX_PROMPT_BYTES} bytes)"


def _validate_prompt_bytes(prompt: str) -> None:
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError(_prompt_too_large_error())


def _compose_prompt(prompt: str, system: str | None) -> str:
    if system:
        prompt = f"{system}\n\n---\n\n{prompt}"
    _validate_prompt_bytes(prompt)
    return prompt


def _read_prompt_file(path_text: str) -> str:
    path = Path(path_text)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("prompt file must be a regular file")
    if info.st_size > MAX_PROMPT_BYTES:
        raise ValueError(_prompt_too_large_error())
    with path.open("rb") as handle:
        data = handle.read(MAX_PROMPT_BYTES + 1)
    if len(data) > MAX_PROMPT_BYTES:
        raise ValueError(_prompt_too_large_error())
    return data.decode("utf-8")


def _read_stdin_prompt() -> str:
    stream = sys.stdin
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        data = buffer.read(MAX_PROMPT_BYTES + 1)
        if len(data) > MAX_PROMPT_BYTES:
            raise ValueError(_prompt_too_large_error())
        return data.decode("utf-8")
    prompt = stream.read(MAX_PROMPT_BYTES + 1)
    _validate_prompt_bytes(prompt)
    return prompt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prompt", nargs="?", help="Question text (or use --prompt-file / stdin)")
    parser.add_argument("--prompt-file", help="Read the question from a file")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"Model id (default {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--fallback-model",
        default=FALLBACK_MODEL,
        help=f"Second CLI attempt if the primary model errors (default {FALLBACK_MODEL}; '' disables)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Hard per-attempt timeout in seconds (default {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--overall-timeout",
        type=float,
        default=None,
        help=(
            "Hard total consult timeout in seconds "
            "(default: --timeout multiplied by enabled backend attempts)"
        ),
    )
    parser.add_argument("--system", help="Optional system-style preamble prepended to the prompt")
    parser.set_defaults(api_fallback=False)
    api_fallback_group = parser.add_mutually_exclusive_group()
    api_fallback_group.add_argument(
        "--api-fallback",
        dest="api_fallback",
        action="store_true",
        help=("Opt in to Anthropic API fallback when CLI attempts fail (may use paid API credits)"),
    )
    api_fallback_group.add_argument(
        "--no-api-fallback",
        dest="api_fallback",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(openrouter_fallback=False)
    openrouter_fallback_group = parser.add_mutually_exclusive_group()
    openrouter_fallback_group.add_argument(
        "--openrouter-fallback",
        dest="openrouter_fallback",
        action="store_true",
        help=(
            "Opt in to OpenRouter fallback when CLI/API attempts fail "
            "(requires OPENROUTER_API_KEY and may use paid API credits)"
        ),
    )
    openrouter_fallback_group.add_argument(
        "--no-openrouter-fallback",
        dest="openrouter_fallback",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--openrouter-model",
        default=DEFAULT_OPENROUTER_MODEL,
        help=(
            f"OpenRouter model id for --openrouter-fallback (default: {DEFAULT_OPENROUTER_MODEL})"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON result envelope")
    args = parser.parse_args(argv)

    try:
        _validate_timeout(args.timeout, "--timeout")
        if args.overall_timeout is not None:
            _validate_timeout(args.overall_timeout, "--overall-timeout")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.prompt_file:
        try:
            prompt = _read_prompt_file(args.prompt_file)
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"error: cannot read --prompt-file: {exc}", file=sys.stderr)
            return EXIT_NO_PROMPT
    elif args.prompt:
        prompt = args.prompt
    elif not sys.stdin.isatty():
        try:
            prompt = _read_stdin_prompt()
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"error: cannot read stdin prompt: {exc}", file=sys.stderr)
            return EXIT_NO_PROMPT
    else:
        parser.print_usage(sys.stderr)
        print("error: no prompt given (arg, --prompt-file, or stdin)", file=sys.stderr)
        return EXIT_NO_PROMPT
    prompt = prompt.strip()
    if not prompt:
        print("error: prompt is empty", file=sys.stderr)
        return EXIT_NO_PROMPT
    try:
        _validate_prompt_bytes(prompt)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_PROMPT

    try:
        result = consult(
            prompt,
            model=args.model,
            timeout=args.timeout,
            overall_timeout=args.overall_timeout,
            fallback_model=args.fallback_model or None,
            system=args.system,
            api_fallback=args.api_fallback,
            openrouter_fallback=args.openrouter_fallback,
            openrouter_model=args.openrouter_model,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_PROMPT
    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("ok"):
        print(result["text"])
    else:
        print(f"consult failed: {result.get('error')}", file=sys.stderr)
    if result.get("ok"):
        return EXIT_OK
    if result.get("usage_error"):
        return EXIT_USAGE
    return EXIT_TIMEOUT if result.get("timed_out") else EXIT_ALL_FAILED


if __name__ == "__main__":
    sys.exit(main())
