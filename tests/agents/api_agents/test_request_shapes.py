"""Request-shape hardening: catalog-driven Anthropic/OpenAI payload flags.

Task 7 (frontier-model-refresh, 2026-09-04): request shapes must be derived
from ``aragora.models.catalog`` flags (``supports_sampling_params``,
``thinking_default_on``, ``forced_tool_choice_allowed``, ``max_tokens_param``,
``reasoning_effort_default``) instead of hand-maintained per-provider
conditionals, so a new frontier row is enough to correct the wire shape.
"""

from __future__ import annotations

import json
import socket
import urllib.request

import pytest

from aragora.models import compat


def test_flags_come_from_catalog() -> None:
    assert compat.rejects_sampling_params("gpt-6-astra") is True
    assert compat.rejects_sampling_params("claude-fable-5-1") is True
    assert compat.rejects_sampling_params("gemini-3.8-flash") is False
    assert compat.rejects_sampling_params("claude-newfamily-9") is False  # unknown -> conservative
    assert compat.thinks_by_default("claude-fable-5-1") is True
    assert compat.allows_forced_tool_choice("claude-fable-5-1") is False
    assert compat.max_tokens_param("gpt-6-astra") == "max_completion_tokens"
    assert compat.max_tokens_param("gemini-3.8-flash") == "max_tokens"
    assert compat.reasoning_effort_default("gpt-6-astra") == "high"


def test_anthropic_payload_for_fable_51() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(
        name="a", model="claude-fable-5-1", temperature=0.2, top_p=0.9, api_key="test-key"
    )
    payload = agent._build_payload("hello", max_tokens=32000)
    assert "temperature" not in payload and "top_p" not in payload
    assert "thinking" not in payload or payload["thinking"] == {"type": "adaptive"}
    assert payload["max_tokens"] == 32000
    assert payload.get("tool_choice", {"type": "auto"}).get("type") in ("auto", "none")


def test_anthropic_payload_default_max_tokens_non_streaming() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    payload = agent._build_payload("hello")
    # min(catalog max_output_tokens=128_000, 16_000) for non-streaming.
    assert payload["max_tokens"] == 16000


def test_anthropic_payload_default_max_tokens_streaming() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    payload = agent._build_payload("hello", stream=True)
    # min(catalog max_output_tokens=128_000, 64_000) for streaming.
    assert payload["max_tokens"] == 64000


def test_anthropic_stream_max_tokens_setting_lowers_the_streamed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``generate_stream`` takes no caller max_tokens, so the streamed default
    IS the per-call output ceiling. ``ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS`` is
    the operator's knob for it (finding C-P3 on #9989)."""
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.config.settings import get_settings

    monkeypatch.setenv("ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS", "8000")
    get_settings.cache_clear()
    try:
        agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
        assert agent._build_payload("hello", stream=True)["max_tokens"] == 8000
        # Non-streaming keeps its own 16k default -- the knob is stream-only.
        assert agent._build_payload("hello")["max_tokens"] == 16_000
    finally:
        get_settings.cache_clear()


def test_anthropic_stream_max_tokens_setting_still_capped_by_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuring more output than the model can emit changes nothing."""
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.config.settings import get_settings

    monkeypatch.setenv("ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS", "900000")
    get_settings.cache_clear()
    try:
        agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
        assert agent._build_payload("hello", stream=True)["max_tokens"] == 128_000
    finally:
        get_settings.cache_clear()


def test_anthropic_stream_max_tokens_setting_does_not_override_an_explicit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is a DEFAULT, not a policy ceiling: a caller that names a value
    still gets it (capped only by the catalog)."""
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.config.settings import get_settings

    monkeypatch.setenv("ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS", "8000")
    get_settings.cache_clear()
    try:
        agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
        payload = agent._build_payload("hello", max_tokens=32_000, stream=True)
        assert payload["max_tokens"] == 32_000
    finally:
        get_settings.cache_clear()


def test_anthropic_stream_cap_falls_back_to_64k_when_settings_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stub or unimportable config must not silently shrink every streamed
    answer -- the shipped default stands."""
    import builtins

    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    real_import = builtins.__import__

    def _blow_up(name: str, *args: object, **kwargs: object) -> object:
        if name == "aragora.config":
            raise ImportError("simulated config import failure")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blow_up)
    assert agent._stream_max_tokens_cap() == 64_000


def test_anthropic_payload_caller_value_capped_at_catalog_max() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    payload = agent._build_payload("hello", max_tokens=999_000)
    assert payload["max_tokens"] == 128_000


def test_anthropic_payload_unknown_model_keeps_4096_default() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-newfamily-9", api_key="test-key")
    payload = agent._build_payload("hello")
    assert payload["max_tokens"] == 4096


def test_anthropic_refusal_fallback_payload_and_headers() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    payload = agent._build_payload("hello")
    assert payload.get("fallbacks") == "default"
    headers = agent._request_headers()
    assert "server-side-fallback-2026-07-01" in headers.get("anthropic-beta", "")


def test_anthropic_refusal_fallback_disabled_by_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    monkeypatch.setenv("ARAGORA_ANTHROPIC_REFUSAL_FALLBACK", "false")
    from aragora.config.settings import get_settings

    get_settings.cache_clear()
    try:
        agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
        payload = agent._build_payload("hello")
        assert "fallbacks" not in payload
        headers = agent._request_headers()
        assert "server-side-fallback-2026-07-01" not in headers.get("anthropic-beta", "")
    finally:
        get_settings.cache_clear()


def test_anthropic_refusal_fallback_beta_pairing_rule() -> None:
    """The payload form and the beta header must stay paired.

    2026-09-05 merge-gate ruling on finding C-P3 of #9989: the refusal
    fallback beta has two request shapes and mixing them is a 400 --
    the SCALAR ``"fallbacks": "default"`` pairs with the 2026-07-01 beta,
    the ARRAY ``"fallbacks": [{"model": ...}]`` with the 2026-06-01 beta.
    Aragora ships the scalar form only, so the payload must never carry the
    array form with the 07-01 header, and the header must never be the
    06-01 one while the payload is scalar.
    """
    from aragora.agents.api_agents import anthropic as anthropic_mod
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    array_beta = "server-side-fallback-2026-06-01"
    assert anthropic_mod._REFUSAL_FALLBACK_BETA == "server-side-fallback-2026-07-01"
    assert anthropic_mod._REFUSAL_FALLBACK_PAYLOAD_VALUE == "default"

    for model in sorted(anthropic_mod._REFUSAL_FALLBACK_MODEL_IDS):
        agent = AnthropicAPIAgent(name="a", model=model, api_key="test-key")
        for stream in (False, True):
            payload = agent._build_payload("hello", stream=stream)
            fallbacks = payload["fallbacks"]
            # Scalar form, never the array form.
            assert isinstance(fallbacks, str), f"{model}: array form sent with the 07-01 header"
            assert not isinstance(fallbacks, (list, tuple))
            assert fallbacks == "default"
        for use_web_search in (False, True):
            beta = agent._request_headers(use_web_search=use_web_search)["anthropic-beta"]
            betas = {v.strip() for v in beta.split(",")}
            assert "server-side-fallback-2026-07-01" in betas
            # The array-form beta must never accompany the scalar payload.
            assert array_beta not in betas, f"{model}: 06-01 beta sent with the scalar form"


def test_anthropic_refusal_fallback_only_on_the_official_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BYOK/LiteLLM/VibeProxy gateway gets neither the beta nor the body field.

    The ``server-side-fallback-*`` beta header and the ``"fallbacks"`` body
    field are an api.anthropic.com request extension. Sending them to a
    third-party gateway that does not implement it can fail the whole
    request (findings O-P3 and C-P3 on #9989).
    """
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8318")
    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    assert agent.base_url == "http://localhost:8318/v1"
    payload = agent._build_payload("hello")
    assert "fallbacks" not in payload
    assert "server-side-fallback-2026-07-01" not in agent._request_headers().get(
        "anthropic-beta", ""
    )
    # The model itself still qualifies -- only the endpoint disqualifies it.
    assert agent._supports_refusal_fallback() is True
    assert agent._refusal_fallback_enabled() is False


def test_anthropic_refusal_fallback_on_official_endpoint_spelled_without_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate compares the RESOLVED url, so a /v1-less spelling of the
    official endpoint still counts as official and keeps the fallback."""
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    payload = agent._build_payload("hello")
    assert payload.get("fallbacks") == "default"
    assert "server-side-fallback-2026-07-01" in agent._request_headers()["anthropic-beta"]


def test_is_official_anthropic_endpoint_branches() -> None:
    from aragora.agents.api_agents.anthropic import _is_official_anthropic_endpoint

    assert _is_official_anthropic_endpoint(None) is True
    assert _is_official_anthropic_endpoint("") is True
    assert _is_official_anthropic_endpoint("https://api.anthropic.com/v1") is True
    assert _is_official_anthropic_endpoint("https://api.anthropic.com/v1/") is True
    assert _is_official_anthropic_endpoint("https://api.anthropic.com") is True
    assert _is_official_anthropic_endpoint("http://localhost:8318") is False
    assert _is_official_anthropic_endpoint("https://litellm.internal/v1") is False
    assert _is_official_anthropic_endpoint("https://api.anthropic.com.evil.test/v1") is False


def test_anthropic_refusal_fallback_not_applied_to_other_models() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agent = AnthropicAPIAgent(name="a", model="claude-opus-4-8", api_key="test-key")
    payload = agent._build_payload("hello")
    assert "fallbacks" not in payload


def test_anthropic_stop_reason_refusal_raises_structured_error() -> None:
    import asyncio

    from unittest.mock import patch

    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.agents.errors.exceptions import AgentAPIError
    from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")

    # The helpers pin __aexit__ falsy; a bare AsyncMock there would tell the
    # `async with` protocol to suppress the raise and return None instead.
    mock_response = make_mock_response(
        status=200,
        json_data={
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {"category": "cyber"},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
    )
    mock_session = make_mock_client_session(mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(AgentAPIError) as excinfo:
            asyncio.run(agent.generate("hello"))

    assert getattr(excinfo.value, "reason", None) == "refusal"
    assert getattr(excinfo.value, "category", None) == "cyber"


def test_anthropic_refusal_records_exactly_one_breaker_failure() -> None:
    """A refusal must cost the breaker one failure, not two.

    The refusal branch records the failure itself. If the raised error were
    ``recoverable=True`` (the default for a ``status_code=None``
    ``AgentAPIError``), ``@handle_agent_errors`` would not short-circuit on
    ``if not e.recoverable: raise`` and would fall through to its own
    ``circuit_breaker.record_failure()`` — so a couple of cyber-classifier
    refusals could trip the breaker and take the primary Anthropic path out
    of service, which is exactly what the refusal fallback exists to survive.
    """
    import asyncio

    from unittest.mock import patch

    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.agents.errors.exceptions import AgentAPIError
    from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    breaker = agent._circuit_breaker
    assert breaker is not None
    before = breaker.failures

    mock_response = make_mock_response(
        status=200,
        json_data={
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {"category": "cyber"},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
    )
    mock_session = make_mock_client_session(mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(AgentAPIError) as excinfo:
            asyncio.run(agent.generate("hello"))

    assert excinfo.value.recoverable is False, "a refusal is terminal, never retryable"
    assert breaker.failures - before == 1


def test_sse_parser_captures_message_delta_stop_info() -> None:
    """Parser unit test: a "message_delta" event populates stop_reason/
    stop_details on the parser object while text-chunk extraction is
    unaffected (message_delta itself yields no content)."""
    import asyncio

    from aragora.agents.api_agents.common import create_anthropic_sse_parser
    from tests.agents.api_agents.conftest import MockStreamResponse

    chunks = [
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"Hi"}}\n\n',
        b'event: message_delta\ndata: {"type":"message_delta","delta":'
        b'{"stop_reason":"refusal","stop_sequence":null},"stop_details":'
        b'{"category":"cyber"},"usage":{"output_tokens":1}}\n\n',
    ]
    mock_response = MockStreamResponse(status=200, chunks=chunks)

    async def _consume() -> tuple[object, list[str]]:
        parser = create_anthropic_sse_parser()
        collected = [c async for c in parser.parse_stream(mock_response.content, "test")]
        return parser, collected

    parser, collected = asyncio.run(_consume())

    assert collected == ["Hi"], "message_delta must not itself yield content"
    assert parser.stop_reason == "refusal"
    assert parser.stop_details == {"category": "cyber"}


def test_anthropic_stream_refusal_raises_after_yielding_partial_text() -> None:
    """A streamed refusal (stop_reason on a message_delta event, not a
    single JSON body) must raise the same structured AgentAPIError generate()
    raises, after any text already streamed."""
    import asyncio
    from unittest.mock import patch

    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.agents.errors.exceptions import AgentAPIError
    from tests.agents.api_agents.conftest import MockStreamResponse
    from tests.utils.aiohttp_mocks import make_mock_client_session

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    agent.enable_web_search = False

    chunks = [
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"Hello"}}\n\n',
        b'event: message_delta\ndata: {"type":"message_delta","delta":'
        b'{"stop_reason":"refusal","stop_sequence":null},"stop_details":'
        b'{"category":"cyber"},"usage":{"output_tokens":1}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    mock_response = MockStreamResponse(status=200, chunks=chunks)

    yielded: list[str] = []

    async def _consume() -> None:
        async for chunk in agent.generate_stream("hello"):
            yielded.append(chunk)

    mock_session = make_mock_client_session(mock_response)

    with patch(
        "aragora.agents.api_agents.anthropic.create_client_session",
        return_value=mock_session,
    ):
        with pytest.raises(AgentAPIError) as excinfo:
            asyncio.run(_consume())

    assert yielded == ["Hello"], "text streamed before the refusal must stay yielded"
    assert excinfo.value.reason == "refusal"
    assert excinfo.value.category == "cyber"


def test_anthropic_stream_end_turn_yields_full_text_without_error() -> None:
    """A normal (non-refusal) stream must not raise and must yield all text."""
    import asyncio
    from unittest.mock import patch

    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from tests.agents.api_agents.conftest import MockStreamResponse
    from tests.utils.aiohttp_mocks import make_mock_client_session

    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", api_key="test-key")
    agent.enable_web_search = False

    chunks = [
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"Hello"}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":" world"}}\n\n',
        b'event: message_delta\ndata: {"type":"message_delta","delta":'
        b'{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":2}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    mock_response = MockStreamResponse(status=200, chunks=chunks)

    yielded: list[str] = []

    async def _consume() -> None:
        async for chunk in agent.generate_stream("hello"):
            yielded.append(chunk)

    mock_session = make_mock_client_session(mock_response)

    with patch(
        "aragora.agents.api_agents.anthropic.create_client_session",
        return_value=mock_session,
    ):
        asyncio.run(_consume())

    assert "".join(yielded) == "Hello world"


def test_openai_payload_for_astra() -> None:
    from aragora.agents.api_agents.openai import OpenAIAPIAgent

    agent = OpenAIAPIAgent(name="o", model="gpt-6-astra", temperature=0.3, api_key="test-key")
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert "max_completion_tokens" in payload and "max_tokens" not in payload
    assert "temperature" not in payload
    assert payload["reasoning_effort"] == "high"


def test_openai_payload_default_max_tokens_is_reasoning_safe() -> None:
    """A reasoning model with no explicit cap must not inherit the flat 4096.

    On OpenAI reasoning models the reasoning tokens are billed and capped
    inside ``max_completion_tokens``; at ``reasoning_effort: "high"`` a 4096
    total budget routinely returns ``finish_reason: "length"`` with empty
    ``content``. Mirrors the Anthropic builder's ``_resolve_max_tokens``.
    """
    from aragora.agents.api_agents.openai import OpenAIAPIAgent
    from aragora.models.catalog import spec_or_none

    agent = OpenAIAPIAgent(name="o", model="gpt-6-astra", api_key="test-key")
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert payload["max_completion_tokens"] >= 16_000
    spec = spec_or_none("gpt-6-astra")
    assert spec is not None
    assert payload["max_completion_tokens"] == min(spec.max_output_tokens, 16_000)


def test_openai_payload_explicit_max_tokens_respected() -> None:
    """An explicit caller cap wins over the reasoning-safe default."""
    from aragora.agents.api_agents.openai import OpenAIAPIAgent

    agent = OpenAIAPIAgent(name="o", model="gpt-6-astra", api_key="test-key")
    agent.max_tokens = 2048
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert payload["max_completion_tokens"] == 2048


def test_openai_payload_uncataloged_reasoning_model_gets_flat_floor() -> None:
    """No catalog row + reasoning_effort being sent -> the flat 16k floor."""
    from aragora.agents.api_agents.openai import OpenAIAPIAgent
    from aragora.models.catalog import spec_or_none

    agent = OpenAIAPIAgent(
        name="o", model="brand-new-reasoner", reasoning_effort="high", api_key="test-key"
    )
    assert spec_or_none("brand-new-reasoner") is None
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert payload["max_tokens"] == 16_000


def test_openai_payload_for_non_reasoning_model_unchanged() -> None:
    from aragora.agents.api_agents.openai import OpenAIAPIAgent

    agent = OpenAIAPIAgent(
        name="o", model="some-openai-compatible-model", temperature=0.3, api_key="test-key"
    )
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert (
        payload["max_tokens"] == 4096
        and payload["temperature"] == 0.3
        and "reasoning_effort" not in payload
    )


def test_openai_reasoning_effort_override() -> None:
    from aragora.agents.api_agents.openai import OpenAIAPIAgent

    agent = OpenAIAPIAgent(
        name="o", model="gpt-6-astra", reasoning_effort="xhigh", api_key="test-key"
    )
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert payload["reasoning_effort"] == "xhigh"


# ---------------------------------------------------------------------------
# Keyless smoke test through VibeProxy (skipped automatically when the proxy
# is absent, e.g. in CI).
# ---------------------------------------------------------------------------


def _proxy_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 8318), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _proxy_up(), reason="VibeProxy not running on 127.0.0.1:8318")
@pytest.mark.parametrize(
    "model,url,body",
    [
        (
            "gpt-6-astra",
            "http://127.0.0.1:8318/v1/chat/completions",
            {
                "model": "gpt-6-astra",
                "messages": [{"role": "user", "content": "Reply: ok"}],
                "max_completion_tokens": 16,
                "reasoning_effort": "low",
            },
        ),
        (
            "claude-fable-5-1",
            "http://127.0.0.1:8318/v1/messages",
            {
                "model": "claude-fable-5-1",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Reply: ok"}],
            },
        ),
    ],
)
def test_live_shape_accepted_by_proxy(model: str, url: str, body: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer local",
            "x-api-key": "local",
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.status == 200
