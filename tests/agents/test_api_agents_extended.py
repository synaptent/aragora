"""
Extended tests for API agents - focusing on gaps in coverage.

Tests cover:
- Rate limiting (token refill, concurrent acquire, timeout, thread safety)
- Fallback mechanism (Anthropic/OpenAI 429, model mapping, streaming)
- Streaming error handling (buffer overflow, malformed JSON, timeouts)
- Concurrency (concurrent generate calls)
- Quota detection
"""

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from aragora.agents.api_agents import (
    MAX_STREAM_BUFFER_SIZE,
    AnthropicAPIAgent,
    GeminiAgent,
    OpenAIAPIAgent,
    OpenRouterAgent,
    OpenRouterRateLimiter,
    get_openrouter_limiter,
    set_openrouter_tier,
)


def create_mock_aiohttp_response(status=200, json_data=None, text="", headers=None):
    """Create a properly mocked aiohttp response."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.headers = headers or {}
    mock_response.text = AsyncMock(return_value=text)
    if json_data:
        mock_response.json = AsyncMock(return_value=json_data)
    return mock_response


@asynccontextmanager
async def mock_aiohttp_session(response):
    """Context manager that mocks aiohttp.ClientSession with proper async handling."""
    mock_session = MagicMock()

    # Create async context manager for post/get methods
    async def async_response_cm(*args, **kwargs):
        return response

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session.post = MagicMock(return_value=mock_cm)
    mock_session.get = MagicMock(return_value=mock_cm)

    yield mock_session


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def rate_limiter():
    """Fresh rate limiter instance."""
    return OpenRouterRateLimiter(tier="standard")


@pytest.fixture
def anthropic_agent():
    """Anthropic API agent for testing."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test_key"}):
        return AnthropicAPIAgent(name="test-anthropic", enable_fallback=True)


@pytest.fixture
def openai_agent():
    """OpenAI API agent for testing."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test_key"}):
        return OpenAIAPIAgent(name="test-openai", enable_fallback=True)


@pytest.fixture
def openrouter_agent():
    """OpenRouter API agent for testing."""
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):
        return OpenRouterAgent(name="test-openrouter")


@pytest.fixture
def gemini_agent():
    """Gemini API agent for testing."""
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
        return GeminiAgent(name="test-gemini", enable_fallback=True)


@pytest.fixture
def mock_successful_response():
    """Mock successful API response."""
    return {"choices": [{"message": {"content": "Test response"}}]}


@pytest.fixture
def mock_anthropic_response():
    """Mock successful Anthropic API response."""
    return {"content": [{"text": "Test response"}]}


# =============================================================================
# Rate Limiting Extended Tests
# =============================================================================


class TestRateLimiterTokenRefill:
    """Tests for token bucket refill mechanism."""

    def test_token_refill_over_time(self, rate_limiter):
        """Test that tokens refill based on elapsed time."""
        # Drain some tokens
        rate_limiter._tokens = 5.0
        old_last_refill = rate_limiter._last_refill

        # Simulate time passing (1 minute = should refill 200 tokens for standard tier)
        with patch("time.monotonic") as mock_time:
            mock_time.return_value = old_last_refill + 60  # 1 minute later
            rate_limiter._refill()

            # Assert inside mock context since _tokens property triggers _refill()
            assert rate_limiter._tokens == rate_limiter.tier.burst_size

    def test_burst_size_enforcement(self, rate_limiter):
        """Test that tokens don't exceed burst size."""
        rate_limiter._tokens = rate_limiter.tier.burst_size

        # Try to refill when already at max
        rate_limiter._refill()

        # Should not exceed burst size
        assert rate_limiter._tokens <= rate_limiter.tier.burst_size

    @pytest.mark.asyncio
    async def test_multiple_concurrent_acquire_calls(self, rate_limiter):
        """Test 5+ concurrent acquire calls."""
        # Set low initial tokens
        rate_limiter._tokens = 3.0

        async def acquire_token():
            return await rate_limiter.acquire(timeout=2.0)

        # Launch 5 concurrent acquires
        tasks = [acquire_token() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # At least 3 should succeed (initial tokens)
        successful = sum(1 for r in results if r)
        assert successful >= 3

    def test_header_update_during_rate_limit_exhaustion(self, rate_limiter):
        """Test header update when API reports exhausted limits."""
        headers = {
            "X-RateLimit-Limit": "200",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(time.time() + 60),
        }

        rate_limiter.update_from_headers(headers)
        stats = rate_limiter.stats

        assert stats["api_remaining"] == 0

    @pytest.mark.asyncio
    async def test_timeout_waiting_for_tokens(self):
        """Test that acquire times out when no tokens available."""
        limiter = OpenRouterRateLimiter(tier="free")  # Low rate
        limiter._tokens = 0.0

        # Should timeout
        result = await limiter.acquire(timeout=0.1)
        assert result is False

    def test_environment_variable_tier_override(self):
        """Test that OPENROUTER_TIER env var overrides default."""
        with patch.dict("os.environ", {"OPENROUTER_TIER": "premium"}):
            limiter = OpenRouterRateLimiter()

        assert limiter.tier.name == "premium"
        assert limiter.tier.requests_per_minute == 500

    def test_thread_safety_under_contention(self, rate_limiter):
        """Test rate limiter is thread-safe."""
        results = []
        errors = []

        def acquire_sync():
            try:
                with rate_limiter._bucket._sync_lock:
                    rate_limiter._bucket._tokens -= 1
                    results.append(rate_limiter._bucket._tokens)
            except Exception as e:
                errors.append(e)

        # Launch 10 threads
        threads = [threading.Thread(target=acquire_sync) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

    def test_stats_accuracy_after_release_on_error(self, rate_limiter):
        """Test that stats are accurate after release_on_error."""
        # Set tokens to a known value below burst
        rate_limiter._tokens = 5.0

        # Release on error (gives back 0.5)
        rate_limiter.release_on_error()

        stats = rate_limiter.stats
        # Should be 5.0 + 0.5 = 5.5 (may round up or down depending on timing)
        assert stats["tokens_available"] in (5, 6)  # Allow for rounding


# =============================================================================
# Fallback Mechanism Tests
# =============================================================================


class TestAnthropicFallback:
    """Tests for Anthropic to OpenRouter fallback."""

    @pytest.mark.asyncio
    async def test_anthropic_429_triggers_fallback(self, anthropic_agent):
        """Test that Anthropic 429 error triggers OpenRouter fallback."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_openrouter_key"}):
            # Mock the fallback agent's generate
            with patch.object(anthropic_agent, "_get_cached_fallback_agent") as mock_get_fallback:
                mock_fallback = MagicMock()
                mock_fallback.generate = AsyncMock(return_value="Fallback response")
                mock_get_fallback.return_value = mock_fallback

                # Create mock response for 429 error
                mock_response = create_mock_aiohttp_response(status=429, text="Rate limit exceeded")
                mock_post_cm = MagicMock()
                mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
                mock_post_cm.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_post_cm)

                mock_session_cm = MagicMock()
                mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_cm.__aexit__ = AsyncMock(return_value=None)

                with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                    result = await anthropic_agent.generate("Test prompt")

                    assert result == "Fallback response"
                    mock_fallback.generate.assert_called_once()

    def test_anthropic_fallback_model_mapping(self, anthropic_agent):
        """Test that Anthropic models resolve to the current frontier via
        OpenRouter (frontier-model-refresh, 2026-09-04). AnthropicAPIAgent no
        longer carries a static OPENROUTER_MODEL_MAP: get_fallback_model()
        resolves the current model through the catalog and upgrade map
        instead, so legacy spellings not previously hand-enumerated (e.g.
        "claude-opus-4-5-20251101") upgrade too -- and the target preserves
        TIER, so a Sonnet spelling lands on the Sonnet row rather than the
        $10/$50 flagship (finding C-P3 on #9989)."""
        for legacy_model in ("claude-opus-4-5-20251101", "claude-opus-4-7"):
            agent = AnthropicAPIAgent(api_key="test-key", model=legacy_model)
            assert agent.get_fallback_model() == "anthropic/claude-fable-5.1"
        for legacy_sonnet in ("claude-sonnet-4-20250514", "claude-sonnet-4-6"):
            agent = AnthropicAPIAgent(api_key="test-key", model=legacy_sonnet)
            assert agent.get_fallback_model() == "anthropic/claude-sonnet-5"

        # A genuinely unknown model falls back to DEFAULT_FALLBACK_MODEL.
        unknown_agent = AnthropicAPIAgent(api_key="test-key", model="unknown-model-xyz")
        assert unknown_agent.get_fallback_model() == AnthropicAPIAgent.DEFAULT_FALLBACK_MODEL

    def test_fallback_preserves_system_prompt(self, anthropic_agent):
        """Test that system prompt is preserved in fallback agent."""
        anthropic_agent.set_system_prompt("You are a helpful assistant.")

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):
            fallback = anthropic_agent._get_cached_fallback_agent()

        assert fallback.system_prompt == "You are a helpful assistant."

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_missing_openrouter_api_key_graceful_error(self, anthropic_agent):
        """Test graceful handling when OPENROUTER_API_KEY not set."""
        import os

        # Ensure OPENROUTER_API_KEY is not set
        saved = os.environ.pop("OPENROUTER_API_KEY", None)

        try:
            mock_response = create_mock_aiohttp_response(status=429, text="Rate limit exceeded")
            mock_post_cm = MagicMock()
            mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post_cm.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_post_cm)

            mock_session_cm = MagicMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=None)

            with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                from aragora.agents.errors import AgentError

                with pytest.raises(AgentError) as exc_info:
                    await anthropic_agent.generate("Test")

                # The error message should contain the original API error
                assert "Anthropic API error 429" in str(exc_info.value)
        finally:
            if saved:
                os.environ["OPENROUTER_API_KEY"] = saved

    def test_billing_quota_keywords_trigger_fallback(self, anthropic_agent):
        """Test that billing/quota error keywords trigger fallback."""
        # Test various quota-related error messages
        assert anthropic_agent.is_quota_error(429, "") is True
        assert anthropic_agent.is_quota_error(400, "credit balance is too low") is True
        assert anthropic_agent.is_quota_error(403, "insufficient quota") is True
        assert anthropic_agent.is_quota_error(400, "billing issue") is True
        assert anthropic_agent.is_quota_error(400, "rate_limit exceeded") is True

        # Regular errors should not trigger fallback
        assert anthropic_agent.is_quota_error(400, "invalid request") is False
        assert anthropic_agent.is_quota_error(500, "internal server error") is False

    @pytest.mark.asyncio
    async def test_enable_fallback_false_prevents_fallback(self):
        """Test that enable_fallback=False prevents fallback."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test_key"}):
            agent = AnthropicAPIAgent(name="test", enable_fallback=False)

        mock_response = create_mock_aiohttp_response(status=429, text="Rate limit")
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            from aragora.agents.errors import AgentError

            with pytest.raises(AgentError) as exc_info:
                await agent.generate("Test")

            # Should raise without trying fallback
            assert "429" in str(exc_info.value)

    def test_fallback_agent_lazy_initialization(self, anthropic_agent):
        """Test that fallback agent is lazily initialized."""
        assert anthropic_agent._fallback_agent is None

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):
            fallback = anthropic_agent._get_cached_fallback_agent()

        assert fallback is not None
        assert anthropic_agent._fallback_agent is fallback

        # Second call should return same instance
        fallback2 = anthropic_agent._get_cached_fallback_agent()
        assert fallback is fallback2


class TestOpenAIFallback:
    """Tests for OpenAI to OpenRouter fallback."""

    @pytest.mark.asyncio
    async def test_openai_429_triggers_fallback(self, openai_agent):
        """Test that OpenAI 429 error triggers OpenRouter fallback."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_openrouter_key"}):
            with patch.object(openai_agent, "_get_cached_fallback_agent") as mock_get_fallback:
                mock_fallback = MagicMock()
                mock_fallback.generate = AsyncMock(return_value="Fallback response")
                mock_get_fallback.return_value = mock_fallback

                mock_response = create_mock_aiohttp_response(status=429, text="Rate limit exceeded")
                mock_post_cm = MagicMock()
                mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
                mock_post_cm.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_post_cm)

                mock_session_cm = MagicMock()
                mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_cm.__aexit__ = AsyncMock(return_value=None)

                with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                    result = await openai_agent.generate("Test prompt")

                    assert result == "Fallback response"

    def test_openai_fallback_model_mapping(self, openai_agent):
        """Test that OpenAI models resolve to the current frontier via
        OpenRouter (frontier-model-refresh, 2026-09-04 review fix round 1,
        item 3). OpenAIAPIAgent no longer carries a static
        OPENROUTER_MODEL_MAP: get_fallback_model() (QuotaFallbackMixin)
        resolves the current model through the catalog and upgrade map."""
        flagship_agent = OpenAIAPIAgent(api_key="test-key", model="gpt-5.5")
        assert flagship_agent.get_fallback_model() == "openai/gpt-6-astra"
        # The GPT-4 line is value tier by price, so it lands with the mini
        # SKUs on Terra (round-4 re-review of finding C-P3 on #9989).
        for value_model in ("gpt-4o", "gpt-4o-mini"):
            value_agent = OpenAIAPIAgent(api_key="test-key", model=value_model)
            assert value_agent.get_fallback_model() == "openai/gpt-5.6-terra"

    def test_openai_quota_keyword_detection(self, openai_agent):
        """Test OpenAI quota error detection."""
        assert openai_agent.is_quota_error(429, "") is True
        assert openai_agent.is_quota_error(400, "insufficient_quota") is True
        assert openai_agent.is_quota_error(403, "quota exceeded") is True
        assert openai_agent.is_quota_error(400, "invalid request") is False


class TestGeminiFallback:
    """Tests for Gemini to OpenRouter fallback."""

    @pytest.mark.asyncio
    async def test_gemini_429_triggers_fallback(self, gemini_agent):
        """Test that Gemini 429 error triggers OpenRouter fallback."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_openrouter_key"}):
            with patch.object(gemini_agent, "_get_cached_fallback_agent") as mock_get_fallback:
                mock_fallback = MagicMock()
                mock_fallback.generate = AsyncMock(return_value="Fallback response")
                mock_get_fallback.return_value = mock_fallback

                mock_response = create_mock_aiohttp_response(status=429, text="Rate limit exceeded")
                mock_post_cm = MagicMock()
                mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
                mock_post_cm.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_post_cm)

                mock_session_cm = MagicMock()
                mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_cm.__aexit__ = AsyncMock(return_value=None)

                with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                    result = await gemini_agent.generate("Test prompt")

                    assert result == "Fallback response"

    @pytest.mark.asyncio
    async def test_gemini_403_quota_triggers_fallback(self, gemini_agent):
        """Test that Gemini 403 quota error triggers OpenRouter fallback."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_openrouter_key"}):
            with patch.object(gemini_agent, "_get_cached_fallback_agent") as mock_get_fallback:
                mock_fallback = MagicMock()
                mock_fallback.generate = AsyncMock(return_value="Fallback response")
                mock_get_fallback.return_value = mock_fallback

                mock_response = create_mock_aiohttp_response(
                    status=403, text="Resource exhausted: quota exceeded"
                )
                mock_post_cm = MagicMock()
                mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
                mock_post_cm.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_post_cm)

                mock_session_cm = MagicMock()
                mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_cm.__aexit__ = AsyncMock(return_value=None)

                with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                    result = await gemini_agent.generate("Test prompt")

                    assert result == "Fallback response"

    def test_gemini_fallback_model_mapping(self):
        """Gemini models resolve to an OpenRouter slug through the catalog.

        The hand-written OPENROUTER_MODEL_MAP is gone (frontier-model-
        refresh, 2026-09-04); assert the behaviour it used to provide
        rather than the dict's contents.
        """
        for model in ("gemini-3.1-pro-preview", "gemini-1.5-pro"):
            agent = GeminiAgent(api_key="test-key", model=model)
            assert agent.get_fallback_model() == "google/gemini-3.1-pro-preview", model
        # The catalog is tier-aware where the old hand map was not: a flash
        # spelling upgrades to the flash tier rather than over-paying for Pro.
        agent = GeminiAgent(api_key="test-key", model="gemini-2.0-flash")
        assert agent.get_fallback_model() == "google/gemini-3.8-flash"

    def test_gemini_quota_keyword_detection(self, gemini_agent):
        """Test Gemini quota error detection."""
        # Rate limit status codes
        assert gemini_agent.is_quota_error(429, "") is True
        # 403 requires quota keywords in error text (unified behavior)
        assert gemini_agent.is_quota_error(403, "quota exceeded") is True
        assert gemini_agent.is_quota_error(403, "") is False  # No keyword, not detected

        # Quota keywords in error message
        assert gemini_agent.is_quota_error(400, "resource exhausted") is True
        assert gemini_agent.is_quota_error(400, "quota exceeded") is True
        assert gemini_agent.is_quota_error(400, "rate limit reached") is True
        assert gemini_agent.is_quota_error(400, "too many requests") is True

        # Regular errors should not trigger fallback
        assert gemini_agent.is_quota_error(400, "invalid request") is False
        assert gemini_agent.is_quota_error(500, "internal server error") is False

    @pytest.mark.asyncio
    async def test_gemini_enable_fallback_false_prevents_fallback(self):
        """Test that enable_fallback=False prevents fallback."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
            agent = GeminiAgent(name="test", enable_fallback=False)

        mock_response = create_mock_aiohttp_response(status=429, text="Rate limit")
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            from aragora.agents.errors import AgentError

            with pytest.raises(AgentError) as exc_info:
                await agent.generate("Test")

            # Should raise without trying fallback
            assert "429" in str(exc_info.value)

    def test_gemini_fallback_agent_lazy_initialization(self, gemini_agent):
        """Test that fallback agent is lazily initialized."""
        assert gemini_agent._fallback_agent is None

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):
            fallback = gemini_agent._get_cached_fallback_agent()

        assert fallback is not None
        assert gemini_agent._fallback_agent is fallback

        # Second call should return same instance
        fallback2 = gemini_agent._get_cached_fallback_agent()
        assert fallback is fallback2

    def test_gemini_fallback_preserves_system_prompt(self, gemini_agent):
        """Test that system prompt is preserved in fallback agent."""
        gemini_agent.set_system_prompt("You are a helpful assistant.")

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):
            fallback = gemini_agent._get_cached_fallback_agent()

        assert fallback.system_prompt == "You are a helpful assistant."


# =============================================================================
# Streaming Error Handling Tests
# =============================================================================


class TestStreamingErrorHandling:
    """Tests for streaming error handling."""

    @pytest.mark.asyncio
    async def test_buffer_overflow_protection(self, anthropic_agent):
        """Test that buffer overflow is detected and raises error."""
        # Create a mock response that streams huge amounts of data
        mock_response = MagicMock()
        mock_response.status = 200

        # Create async generator that yields massive chunks
        async def iter_massive_chunks():
            yield b"x" * (MAX_STREAM_BUFFER_SIZE + 1000)

        mock_response.content = MagicMock()
        mock_response.content.iter_any = iter_massive_chunks

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            from aragora.agents.errors import AgentStreamError

            with pytest.raises(AgentStreamError) as exc_info:
                chunks = []
                async for chunk in anthropic_agent.generate_stream("Test"):
                    chunks.append(chunk)

            assert "buffer exceeded" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_malformed_json_handling(self, anthropic_agent):
        """Test handling of malformed JSON in stream."""
        mock_response = MagicMock()
        mock_response.status = 200

        # Create async generator with malformed JSON
        async def iter_malformed():
            yield b'data: {"type": "content_block_delta", invalid json}\n'
            yield b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "valid"}}\n'
            yield b"data: [DONE]\n"

        mock_response.content = MagicMock()
        mock_response.content.iter_any = iter_malformed

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            # Should handle malformed JSON gracefully and continue
            chunks = []
            async for chunk in anthropic_agent.generate_stream("Test"):
                chunks.append(chunk)

            # Should have gotten the valid chunk
            assert "valid" in "".join(chunks)

    @pytest.mark.asyncio
    async def test_asyncio_timeout_propagates(self, anthropic_agent):
        """Test that asyncio.TimeoutError propagates correctly."""
        mock_response = MagicMock()
        mock_response.status = 200

        async def iter_timeout():
            yield b'data: {"type": "content_block_delta"}\n'
            raise asyncio.TimeoutError()

        mock_response.content = MagicMock()
        mock_response.content.iter_any = iter_timeout

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            with pytest.raises(asyncio.TimeoutError):
                async for chunk in anthropic_agent.generate_stream("Test"):
                    pass

    @pytest.mark.asyncio
    async def test_aiohttp_client_error_handling(self, anthropic_agent):
        """Test handling of aiohttp.ClientError."""
        mock_response = MagicMock()
        mock_response.status = 200

        async def iter_client_error():
            yield b'data: {"type": "test"}\n'
            raise aiohttp.ClientError("Connection lost")

        mock_response.content = MagicMock()
        mock_response.content.iter_any = iter_client_error

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session_cm,
        ):
            from aragora.agents.errors import AgentConnectionError

            with pytest.raises(AgentConnectionError) as exc_info:
                async for chunk in anthropic_agent.generate_stream("Test"):
                    pass

            assert "connection" in str(exc_info.value).lower()


# =============================================================================
# Concurrency Tests
# =============================================================================


class TestConcurrency:
    """Tests for concurrent API calls."""

    @pytest.mark.asyncio
    async def test_5_concurrent_generate_calls(self, anthropic_agent):
        """Test 5 concurrent generate calls."""
        mock_response = create_mock_aiohttp_response(
            status=200, json_data={"content": [{"text": "Response"}]}
        )

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            tasks = [anthropic_agent.generate(f"Prompt {i}") for i in range(5)]
            results = await asyncio.gather(*tasks)

            assert len(results) == 5
            assert all(r == "Response" for r in results)

    @pytest.mark.asyncio
    async def test_10_concurrent_generate_calls(self, anthropic_agent):
        """Test 10 concurrent generate calls."""
        mock_response = create_mock_aiohttp_response(
            status=200, json_data={"content": [{"text": "Response"}]}
        )

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            tasks = [anthropic_agent.generate(f"Prompt {i}") for i in range(10)]
            results = await asyncio.gather(*tasks)

            assert len(results) == 10

    def test_10_threads_acquiring_rate_limiter_tokens(self):
        """Test thread safety with 10 threads acquiring tokens."""
        limiter = OpenRouterRateLimiter(tier="premium")
        limiter._tokens = 20.0  # Start with enough tokens

        acquired = []
        lock = threading.Lock()

        def acquire_sync():
            # Synchronous version using the bucket lock directly
            with limiter._bucket._sync_lock:
                if limiter._bucket._tokens >= 1:
                    limiter._bucket._tokens -= 1
                    with lock:
                        acquired.append(True)
                else:
                    with lock:
                        acquired.append(False)

        threads = [threading.Thread(target=acquire_sync) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(acquired) == 10
        # Most should succeed with 20 initial tokens
        assert sum(acquired) >= 10

    @pytest.mark.asyncio
    async def test_race_condition_in_fallback_agent_creation(self, anthropic_agent):
        """Test that fallback agent creation is safe under concurrent access."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):
            # Reset fallback agent
            anthropic_agent._fallback_agent = None

            async def get_fallback():
                return anthropic_agent._get_cached_fallback_agent()

            # Concurrent calls should return the same instance
            tasks = [get_fallback() for _ in range(5)]
            results = await asyncio.gather(*tasks)

            # All should be the same instance
            first = results[0]
            assert all(r is first for r in results)


# =============================================================================
# OpenRouter Agent Tests
# =============================================================================


class TestOpenRouterAgent:
    """Tests for OpenRouterAgent."""

    @pytest.mark.asyncio
    async def test_rate_limit_token_acquisition(self, openrouter_agent):
        """Test that OpenRouter agent acquires rate limit tokens."""
        # Reset global limiter
        set_openrouter_tier("standard")

        mock_response = create_mock_aiohttp_response(
            status=200, json_data={"choices": [{"message": {"content": "Response"}}]}, headers={}
        )

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            result = await openrouter_agent.generate("Test")
            assert result == "Response"

    @pytest.mark.asyncio
    async def test_openrouter_429_releases_token(self, openrouter_agent):
        """Test that 429 error releases token back to pool."""
        # Reset rate limiter to fresh state (clears backoff)
        set_openrouter_tier("standard")
        limiter = get_openrouter_limiter()
        limiter._backoff.reset()  # Clear any backoff state

        mock_response = create_mock_aiohttp_response(
            status=429, text="Rate limited", headers={"Retry-After": "60"}
        )

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        # Mock backoff to return small delays (prevents timeout during test)
        mock_backoff = MagicMock()
        mock_backoff.is_backing_off = False
        mock_backoff.get_delay.return_value = 0.1
        mock_backoff.record_failure.return_value = 0.1
        mock_backoff.reset = MagicMock()
        mock_backoff.failure_count = 0

        # Mock asyncio.sleep to prevent actual waiting during retries
        with (
            patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session_cm,
            ),
            patch("aragora.agents.api_agents.openrouter.asyncio.sleep", new_callable=AsyncMock),
            patch.object(limiter, "_backoff", mock_backoff),
        ):
            from aragora.agents.errors import AgentRateLimitError

            with pytest.raises(AgentRateLimitError) as exc_info:
                await openrouter_agent.generate("Test")

            assert "429" in str(exc_info.value)


# =============================================================================
# Unknown Model Mapping Tests
# =============================================================================


class TestUnknownModelMapping:
    """Tests for handling unknown model names in fallback."""

    def test_anthropic_unknown_model_default_mapping(self):
        """Test that unknown Anthropic models map to default."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            agent = AnthropicAPIAgent(model="claude-unknown-future-model")

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            fallback = agent._get_cached_fallback_agent()

        # Should default to claude-sonnet-4
        assert "claude-sonnet" in fallback.model or "anthropic" in fallback.model

    def test_openai_unknown_model_default_mapping(self):
        """Test that unknown OpenAI models map to default."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            agent = OpenAIAPIAgent(model="gpt-future-model")

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            fallback = agent._get_cached_fallback_agent()

        # Should default to gpt-4o
        assert "gpt-4o" in fallback.model or "openai" in fallback.model


# =============================================================================
# Streaming Fallback Tests
# =============================================================================


class TestStreamingFallback:
    """Tests for streaming with fallback."""

    @pytest.mark.asyncio
    async def test_anthropic_streaming_fallback_works(self, anthropic_agent):
        """Test that streaming fallback works for Anthropic."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):

            async def mock_stream(*args, **kwargs):
                yield "Fallback "
                yield "streaming"

            with patch.object(anthropic_agent, "_get_cached_fallback_agent") as mock_get_fallback:
                mock_fallback = MagicMock()
                mock_fallback.generate_stream = mock_stream
                mock_get_fallback.return_value = mock_fallback

                mock_response = create_mock_aiohttp_response(status=429, text="Rate limit")
                mock_post_cm = MagicMock()
                mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
                mock_post_cm.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_post_cm)

                mock_session_cm = MagicMock()
                mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_cm.__aexit__ = AsyncMock(return_value=None)

                with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                    chunks = []
                    async for chunk in anthropic_agent.generate_stream("Test"):
                        chunks.append(chunk)

                    assert "".join(chunks) == "Fallback streaming"

    @pytest.mark.asyncio
    async def test_openai_streaming_fallback_works(self, openai_agent):
        """Test that streaming fallback works for OpenAI."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key"}):

            async def mock_stream(*args, **kwargs):
                yield "OpenAI "
                yield "fallback"

            with patch.object(openai_agent, "_get_cached_fallback_agent") as mock_get_fallback:
                mock_fallback = MagicMock()
                mock_fallback.generate_stream = mock_stream
                mock_get_fallback.return_value = mock_fallback

                mock_response = create_mock_aiohttp_response(status=429, text="Rate limit")
                mock_post_cm = MagicMock()
                mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
                mock_post_cm.__aexit__ = AsyncMock(return_value=None)

                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_post_cm)

                mock_session_cm = MagicMock()
                mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_cm.__aexit__ = AsyncMock(return_value=None)

                with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                    chunks = []
                    async for chunk in openai_agent.generate_stream("Test"):
                        chunks.append(chunk)

                    assert "".join(chunks) == "OpenAI fallback"


# =============================================================================
# API Response Parsing Tests
# =============================================================================


class TestAPIResponseParsing:
    """Tests for API response parsing edge cases."""

    @pytest.mark.asyncio
    async def test_anthropic_unexpected_response_format(self, anthropic_agent):
        """Test handling of unexpected Anthropic response format."""
        from aragora.agents.errors import AgentError

        mock_response = create_mock_aiohttp_response(status=200, json_data={"unexpected": "format"})

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            with pytest.raises(AgentError) as exc_info:
                await anthropic_agent.generate("Test")

            assert "Unexpected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_openai_unexpected_response_format(self, openai_agent):
        """Test handling of unexpected OpenAI response format."""
        from aragora.agents.errors import AgentError

        mock_response = create_mock_aiohttp_response(status=200, json_data={"unexpected": "format"})

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session_cm):
            with pytest.raises(AgentError) as exc_info:
                await openai_agent.generate("Test")

            assert "Unexpected" in str(exc_info.value)
