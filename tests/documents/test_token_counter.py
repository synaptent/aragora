"""
Tests for token counting service.
"""

import pytest

from aragora.documents.chunking.token_counter import (
    TokenCounter,
    get_token_counter,
    count_tokens,
)


class TestTokenCounter:
    """Tests for TokenCounter class."""

    @pytest.fixture
    def counter(self):
        """Create a token counter instance."""
        return TokenCounter()

    def test_count_empty_string(self, counter):
        """Test counting empty string returns 0."""
        assert counter.count("") == 0
        # Whitespace-only may return small non-zero due to approximation
        assert counter.count("   ") <= 1

    def test_count_basic_text(self, counter):
        """Test counting basic text."""
        tokens = counter.count("Hello, world!")
        assert tokens > 0
        assert tokens < 10  # Should be a few tokens

    def test_count_longer_text(self, counter):
        """Test counting longer text scales appropriately."""
        short = counter.count("Hello")
        long = counter.count("Hello " * 100)
        assert long > short * 50  # Roughly proportional

    def test_count_with_model(self, counter):
        """Test counting with specific model."""
        text = "The quick brown fox jumps over the lazy dog."

        gpt4_tokens = counter.count(text, model="gpt-4")
        claude_tokens = counter.count(text, model="claude-3-opus")

        # Both should return reasonable counts
        assert gpt4_tokens > 0
        assert claude_tokens > 0

    def test_count_messages(self, counter):
        """Test counting chat messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        tokens = counter.count_messages(messages)
        assert tokens > 0

        # Should include overhead
        content_tokens = counter.count("Hello") + counter.count("Hi there!")
        assert tokens > content_tokens  # Has formatting overhead

    def test_estimate_chunks(self, counter):
        """Test chunk estimation."""
        # 1000 tokens of text should split into ~2 chunks of 512
        text = "word " * 250  # ~250 tokens

        chunks = counter.estimate_chunks(text, chunk_size=512, overlap=50)
        assert chunks >= 1

        # More text should require more chunks
        long_text = "word " * 2000  # ~2000 tokens
        long_chunks = counter.estimate_chunks(long_text, chunk_size=512, overlap=50)
        assert long_chunks > chunks

    def test_fits_context(self, counter):
        """Test context window checking."""
        short_text = "Hello"
        long_text = "word " * 10000  # Very long

        # Short text should fit in any model
        assert counter.fits_context(short_text, "gpt-4") is True

        # Long text might not fit in small models
        fits_gpt4 = counter.fits_context(long_text, "gpt-4", max_tokens=8192)
        fits_gemini = counter.fits_context(long_text, "gemini-3-pro", max_tokens=1000000)

        # Gemini with 1M tokens should fit more
        if not fits_gpt4:
            assert fits_gemini is True

    def test_truncate_to_tokens(self, counter):
        """Test text truncation."""
        text = "Hello world this is a test sentence."

        # Truncate to very small number
        truncated = counter.truncate_to_tokens(text, max_tokens=3)
        assert len(truncated) < len(text)
        assert truncated.endswith("...")

        # Truncate to large number should return original
        not_truncated = counter.truncate_to_tokens(text, max_tokens=1000)
        assert not_truncated == text

    def test_default_model(self, counter):
        """Test default model is used when not specified."""
        tokens1 = counter.count("Test text")
        tokens2 = counter.count("Test text", model=counter.default_model)
        assert tokens1 == tokens2


class TestGlobalTokenCounter:
    """Tests for global token counter functions."""

    def test_get_token_counter(self):
        """Test getting global counter."""
        counter1 = get_token_counter()
        counter2 = get_token_counter()
        assert counter1 is counter2  # Same instance

    def test_count_tokens_function(self):
        """Test convenience function."""
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_count_tokens_with_model(self):
        """Test convenience function with model."""
        tokens = count_tokens("Test", model="claude-3-opus")
        assert tokens > 0


class TestTiktokenIntegration:
    """Tests for tiktoken integration (if available)."""

    def test_tiktoken_accurate_count(self):
        """Test tiktoken provides accurate counts."""
        counter = TokenCounter()

        # Known token counts for GPT-4
        text = "Hello, world!"
        tokens = counter.count(text, model="gpt-4")

        # tiktoken should give consistent results
        tokens2 = counter.count(text, model="gpt-4")
        assert tokens == tokens2

    def test_tiktoken_different_encodings(self):
        """Test different encodings produce different counts."""
        counter = TokenCounter()

        text = "Hello, world! This is a test."

        gpt4_tokens = counter.count(text, model="gpt-4")
        gpt4o_tokens = counter.count(text, model="gpt-4o")

        # Different models may have different token counts
        # Both should be reasonable
        assert gpt4_tokens > 0
        assert gpt4o_tokens > 0


class TestApproximateCounter:
    """Tests for approximate token counting (fallback)."""

    def test_approximation_reasonable(self):
        """Test approximation gives reasonable results."""
        counter = TokenCounter()

        # Test with a model that uses approximation
        text = "The quick brown fox jumps over the lazy dog."

        # Claude uses approximation (not tiktoken)
        tokens = counter.count(text, model="claude-3-opus")

        # Should be roughly 10-15 tokens for this sentence
        assert 5 < tokens < 25

    def test_approximation_scales(self):
        """Test approximation scales with text length."""
        counter = TokenCounter()

        short = counter.count("Hello", model="claude-3")
        medium = counter.count("Hello " * 10, model="claude-3")
        long = counter.count("Hello " * 100, model="claude-3")

        assert short < medium < long


class TestDefaultModelIsLiveWithoutAnUpgrade:
    """``TokenCounter``'s default must name an active catalog row directly.

    "gpt-4" is an UPGRADES key, so the counter's default depended on the
    upgrade map to reach a live model, and it selected ``cl100k_base`` when
    every current OpenAI model tokenizes with ``o200k_base`` -- counts were
    measured against the wrong tokenizer (2026-09-05 merge-gate addendum on
    #9989).
    """

    def test_default_model_is_an_active_catalog_row(self):
        from aragora.models.catalog import spec_or_none
        from aragora.models.upgrade_map import UPGRADES

        model = TokenCounter().default_model
        assert model not in UPGRADES
        spec = spec_or_none(model)
        assert spec is not None and not spec.retired

    def test_default_model_selects_the_current_openai_encoding(self):
        from aragora.documents.chunking.token_counter import MODEL_ENCODINGS

        model = TokenCounter().default_model
        assert MODEL_ENCODINGS[model] == "o200k_base"

    def test_module_level_count_tokens_shares_the_default(self):
        from aragora.config.model_pins import GPT6_ASTRA_DIRECT

        assert TokenCounter().default_model == GPT6_ASTRA_DIRECT
        assert count_tokens("hello world") == TokenCounter().count("hello world")
