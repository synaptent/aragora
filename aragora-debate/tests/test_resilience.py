"""Offline resilience tests, including every provider's actual SDK call site."""

import asyncio
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora_debate import _resilience as resilience
from aragora_debate.agents import ClaudeAgent, GeminiAgent, MistralAgent, OpenAIAgent


@pytest.mark.asyncio
async def test_timeout_coroutine_and_control():
    cancelled = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.set()

    with pytest.raises(TimeoutError):
        await resilience.with_timeout(0.01)(slow())
    assert cancelled.is_set()
    assert await resilience.with_timeout(1)(asyncio.sleep(0.001, result="ok")) == "ok"


@pytest.mark.asyncio
async def test_timeout_sync_callable_runs_off_event_loop():
    release = threading.Event()
    thread_ids = []

    def slow():
        thread_ids.append(threading.get_ident())
        release.wait(2)

    try:
        with pytest.raises(TimeoutError):
            await resilience.with_timeout(0.05)(slow)
        assert thread_ids and thread_ids != [threading.get_ident()]
    finally:
        release.set()
    assert await resilience.with_timeout(1)(lambda: 42) == 42


@pytest.mark.asyncio
async def test_retry_exhausts_with_exponential_backoff_and_last_error(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(resilience.asyncio, "sleep", sleep)
    errors = [ValueError(str(i)) for i in range(3)]
    call = MagicMock(side_effect=errors)
    with pytest.raises(ValueError) as caught:
        await resilience.retry(3, backoff=0.25, exceptions=(ValueError,))(call)()
    assert caught.value is errors[-1]
    assert call.call_count == 3
    assert [c.args for c in sleep.await_args_list] == [(0.25,), (0.5,)]


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_retry_returns_success_and_preserves_arguments(asynchronous):
    call = (AsyncMock if asynchronous else MagicMock)(side_effect=[ValueError(), "ok"])
    assert await resilience.retry(3, backoff=0)(call)("arg", option=1) == "ok"
    assert call.call_count == 2
    call.assert_called_with("arg", option=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TypeError(), asyncio.CancelledError()])
async def test_retry_does_not_retry_other_errors_or_cancellation(error):
    call = AsyncMock(side_effect=error)
    with pytest.raises(type(error)):
        await resilience.retry(3, backoff=0, exceptions=(ValueError,))(call)()
    assert call.call_count == 1


@pytest.mark.asyncio
async def test_circuit_breaker_open_reject_half_open_and_close():
    now = [10.0]
    breaker = resilience.CircuitBreaker(2, 5, clock=lambda: now[0])
    call = MagicMock(side_effect=[ValueError(), ValueError(), "ok", "again"])
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call(call)
    assert breaker.state == "open"
    with pytest.raises(resilience.CircuitOpenError):
        await breaker.call(call)
    assert call.call_count == 2
    now[0] += 5
    assert breaker.state == "half-open"
    assert await breaker.call(call) == "ok"
    assert breaker.state == "closed"
    assert await breaker.call(call) == "again"


@pytest.mark.asyncio
async def test_circuit_breaker_success_resets_failures_and_failed_probe_reopens():
    now = [0.0]
    breaker = resilience.CircuitBreaker(2, 5, clock=lambda: now[0])
    fail = MagicMock(side_effect=ValueError())
    with pytest.raises(ValueError):
        await breaker.call(fail)
    await breaker.call(lambda: "ok")
    with pytest.raises(ValueError):
        await breaker.call(fail)
    assert breaker.state == "closed"
    with pytest.raises(ValueError):
        await breaker.call(fail)
    now[0] = 5
    with pytest.raises(ValueError):
        await breaker.call(fail)
    assert breaker.state == "open"
    now[0] = 9
    with pytest.raises(resilience.CircuitOpenError):
        await breaker.call(fail)


@pytest.mark.asyncio
async def test_circuit_breaker_only_one_half_open_probe_and_cancellation_releases_it():
    now = [0.0]
    breaker = resilience.CircuitBreaker(1, 1, clock=lambda: now[0])
    with pytest.raises(ValueError):
        await breaker.call(MagicMock(side_effect=ValueError()))
    now[0] = 1
    started = asyncio.Event()

    async def probe():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(breaker.call(probe))
    await started.wait()
    with pytest.raises(resilience.CircuitOpenError):
        await breaker.call(lambda: "blocked")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await breaker.call(lambda: "ok") == "ok"
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_late_success_cannot_close_newly_open_circuit():
    breaker = resilience.CircuitBreaker(1, 10)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_success():
        started.set()
        await release.wait()
        return "late"

    task = asyncio.create_task(breaker.call(slow_success))
    await started.wait()
    with pytest.raises(ValueError):
        await breaker.call(MagicMock(side_effect=ValueError()))
    release.set()
    assert await task == "late"
    assert breaker.state == "open"


@pytest.mark.asyncio
async def test_retry_never_retries_open_circuit_or_cancelled_default_call(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(resilience.asyncio, "sleep", sleep)
    for error in (resilience.CircuitOpenError(), asyncio.CancelledError()):
        call = AsyncMock(side_effect=error)
        with pytest.raises(type(error)):
            await resilience.retry(3)(call)()
        assert call.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", "invalid", "0", "-1", "nan", "inf"])
async def test_resilience_environment_defaults_and_invalid_fallbacks(monkeypatch, value):
    for key in (
        "ARAGORA_DEBATE_TIMEOUT_S",
        "ARAGORA_DEBATE_RETRY_ATTEMPTS",
        "ARAGORA_DEBATE_BREAKER_FAIL_MAX",
    ):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    wait = AsyncMock(return_value="ok")
    monkeypatch.setattr(resilience.asyncio, "wait_for", wait)
    # Close the captured coroutine rather than leave it unawaited in this stub.
    assert await resilience.with_timeout()(lambda: "ok") == "ok"
    wait.call_args.args[0].close()
    assert wait.call_args.kwargs["timeout"] == 30
    call = MagicMock(side_effect=ValueError())
    with pytest.raises(ValueError):
        await resilience.retry(backoff=0)(call)()
    assert call.call_count == 3
    assert resilience.CircuitBreaker().fail_max == 5


@pytest.mark.parametrize(
    "factory",
    [
        lambda: resilience.with_timeout(0),
        lambda: resilience.with_timeout(float("nan")),
        lambda: resilience.retry(0),
        lambda: resilience.retry(2, backoff=-1),
        lambda: resilience.CircuitBreaker(0),
        lambda: resilience.CircuitBreaker(1, reset_timeout=0),
    ],
)
def test_resilience_invalid_explicit_settings_raise(factory):
    with pytest.raises(ValueError):
        factory()


@pytest.fixture(params=[ClaudeAgent, OpenAIAgent, MistralAgent, GeminiAgent])
def sdk_agent(request, monkeypatch):
    module = MagicMock()
    client = MagicMock()
    for constructor in (module.Anthropic, module.OpenAI, module.Mistral, module.Client):
        constructor.return_value = client
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setitem(sys.modules, "mistralai", module)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=module))
    monkeypatch.setitem(sys.modules, "google.genai", module)
    monkeypatch.setenv("ARAGORA_DEBATE_RETRY_ATTEMPTS", "3")
    monkeypatch.setenv("ARAGORA_DEBATE_BREAKER_FAIL_MAX", "2")
    agent = request.param("test", api_key="SECRET-ALPHA-123")
    calls = {
        ClaudeAgent: client.messages.create,
        OpenAIAgent: client.chat.completions.create,
        MistralAgent: client.chat.complete,
        GeminiAgent: client.models.generate_content,
    }
    call = calls[request.param]
    text = '{"choice": "test", "issues": [], "severity": 1, "confidence": 0.9}'
    call.return_value = SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        text=text,
    )
    return agent, call


async def _run_agent(agent, method):
    if method == "generate":
        return await agent.generate("topic")
    if method == "critique":
        return await agent.critique("proposal", "topic")
    return await agent.vote({"test": "proposal"}, "topic")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate", "critique", "vote"])
async def test_agent_sdk_timeout(sdk_agent, monkeypatch, method):
    agent, call = sdk_agent
    monkeypatch.setenv("ARAGORA_DEBATE_TIMEOUT_S", "0.1")
    monkeypatch.setenv("ARAGORA_DEBATE_RETRY_ATTEMPTS", "1")
    release = threading.Event()
    call.side_effect = lambda **kwargs: release.wait(2)
    try:
        with pytest.raises(TimeoutError):
            await _run_agent(agent, method)
        assert call.call_count == 1
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate", "critique", "vote"])
async def test_agent_sdk_retry_and_breaker_rejection(sdk_agent, monkeypatch, method):
    agent, call = sdk_agent
    monkeypatch.setattr(resilience.asyncio, "sleep", AsyncMock())
    call.side_effect = [ValueError(), call.return_value]
    assert await _run_agent(agent, method) is not None
    assert call.call_count == 2
    call.reset_mock()
    call.side_effect = ValueError()
    with pytest.raises(resilience.CircuitOpenError):
        await _run_agent(agent, method)
    assert call.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate", "critique", "vote"])
async def test_agent_sdk_exhausts_configured_retry_attempts(sdk_agent, monkeypatch, method):
    agent, call = sdk_agent
    monkeypatch.setenv("ARAGORA_DEBATE_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(resilience.asyncio, "sleep", AsyncMock())
    errors = [ValueError("first"), ValueError("last")]
    call.side_effect = errors
    with pytest.raises(ValueError) as caught:
        await _run_agent(agent, method)
    assert caught.value is errors[-1]
    assert call.call_count == 2
    with pytest.raises(resilience.CircuitOpenError):
        await _run_agent(agent, method)
    assert call.call_count == 2
