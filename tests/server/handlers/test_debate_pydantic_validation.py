"""
Tests for Pydantic v2 input validation on debate endpoints (Epic #292, T3).

Tests confirm:
- Valid payloads pass validation
- Invalid payloads return 422 (or similar error) from validate_debate_request
- Field constraints are enforced (question length, rounds bounds, agents list size)
- The DebateRequest model is importable and correctly structured
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestDebateRequestModel:
    """Unit tests for the DebateRequest Pydantic model."""

    def test_import_debate_request(self):
        """DebateRequest can be imported."""
        from aragora.server.validation.pydantic_models import DebateRequest

        assert DebateRequest is not None

    def test_valid_minimal_request(self):
        """A request with just a long-enough question is valid."""
        from aragora.server.validation.pydantic_models import DebateRequest

        req = DebateRequest(question="Should we adopt microservices architecture?")
        assert req.question == "Should we adopt microservices architecture?"
        assert req.rounds == 3  # default
        assert req.agents == []  # default

    def test_valid_full_request(self):
        """A request with all fields set is valid."""
        from aragora.server.validation.pydantic_models import DebateRequest

        req = DebateRequest(
            question="What is the best approach for distributed caching?",
            rounds=5,
            agents=["claude", "gpt"],
        )
        assert req.rounds == 5
        assert req.agents == ["claude", "gpt"]

    def test_question_too_short_raises(self):
        """Question shorter than 10 chars raises ValidationError."""
        from aragora.server.validation.pydantic_models import DebateRequest

        with pytest.raises(ValidationError):
            DebateRequest(question="Short")

    def test_blank_question_raises(self):
        """Blank/whitespace question raises ValidationError."""
        from aragora.server.validation.pydantic_models import DebateRequest

        with pytest.raises(ValidationError):
            DebateRequest(question="          ")

    def test_question_too_long_raises(self):
        """Question longer than 2000 chars raises ValidationError."""
        from aragora.server.validation.pydantic_models import DebateRequest

        with pytest.raises(ValidationError):
            DebateRequest(question="x" * 2001)

    def test_rounds_below_minimum_raises(self):
        """rounds < 1 raises ValidationError."""
        from aragora.server.validation.pydantic_models import DebateRequest

        with pytest.raises(ValidationError):
            DebateRequest(
                question="Should we use microservices instead of monoliths?",
                rounds=0,
            )

    def test_rounds_above_maximum_raises(self):
        """rounds > 10 raises ValidationError."""
        from aragora.server.validation.pydantic_models import DebateRequest

        with pytest.raises(ValidationError):
            DebateRequest(
                question="Should we use microservices instead of monoliths?",
                rounds=11,
            )

    def test_agents_list_too_long_raises(self):
        """agents list with more than 10 entries raises ValidationError."""
        from aragora.server.validation.pydantic_models import DebateRequest

        with pytest.raises(ValidationError):
            DebateRequest(
                question="Should we use microservices instead of monoliths?",
                agents=[f"agent_{i}" for i in range(11)],
            )

    def test_question_stripped_of_whitespace(self):
        """Leading/trailing whitespace is stripped from question."""
        from aragora.server.validation.pydantic_models import DebateRequest

        req = DebateRequest(question="  What is the best deployment strategy?  ")
        assert req.question == "What is the best deployment strategy?"

    def test_agents_parsed_from_comma_string(self):
        """agents can be provided as a comma-separated string."""
        from aragora.server.validation.pydantic_models import DebateRequest

        req = DebateRequest(
            question="Should we use microservices instead of monoliths?",
            agents="claude, gpt, gemini",  # type: ignore[arg-type]
        )
        assert req.agents == ["claude", "gpt", "gemini"]

    def test_to_handler_dict_contains_question(self):
        """to_handler_dict() returns a dict containing the question."""
        from aragora.server.validation.pydantic_models import DebateRequest

        req = DebateRequest(question="What is the best deployment strategy?")
        d = req.to_handler_dict()
        assert "question" in d
        assert d["question"] == "What is the best deployment strategy?"

    def test_to_handler_dict_contains_rounds(self):
        """to_handler_dict() contains rounds."""
        from aragora.server.validation.pydantic_models import DebateRequest

        req = DebateRequest(question="What is the best deployment strategy?", rounds=7)
        d = req.to_handler_dict()
        assert d["rounds"] == 7


class TestValidateDebateRequest:
    """Tests for the validate_debate_request helper function."""

    def test_valid_payload_returns_model(self):
        """Valid body returns (DebateRequest, None)."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        req, err = validate_debate_request(
            {"question": "Should we adopt microservices architecture?"}
        )
        assert req is not None
        assert err is None

    def test_invalid_payload_returns_error_string(self):
        """Invalid body returns (None, error_message) with non-empty message."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        req, err = validate_debate_request({"question": "Short"})
        assert req is None
        assert err is not None
        assert len(err) > 0

    def test_blank_question_returns_error(self):
        """Blank question returns error message, not an exception."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        req, err = validate_debate_request({"question": "   "})
        assert req is None
        assert err is not None

    def test_rounds_out_of_range_returns_error(self):
        """rounds=0 returns error string."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        req, err = validate_debate_request(
            {
                "question": "Should we adopt microservices architecture?",
                "rounds": 0,
            }
        )
        assert req is None
        assert err is not None

    def test_error_is_human_readable(self):
        """Error message for invalid payload is human-readable text."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        _, err = validate_debate_request({"question": "Too short"})
        # Should mention the field or constraint
        assert err is not None
        assert isinstance(err, str)
        assert len(err.strip()) > 10

    def test_missing_question_returns_error(self):
        """Missing question field returns error (question is required)."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        req, err = validate_debate_request({"rounds": 3})
        assert req is None
        assert err is not None


class TestDebateCreateEndpointPydanticIntegration:
    """Tests that confirm the create endpoint wires in Pydantic validation.

    These tests call validate_debate_request directly (as the handler does)
    to confirm the 422 path is reachable. Full handler integration tests are
    in test_debates_handler.py.
    """

    def test_pydantic_validates_before_spam_check(self):
        """Pydantic validation rejects payload before spam check runs."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        # Too short — Pydantic should reject
        req, err = validate_debate_request({"question": "Hi"})
        assert req is None
        assert err is not None

    def test_pydantic_accepts_valid_debate_payload(self):
        """A realistic debate payload passes Pydantic validation."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        payload = {
            "question": "Should small teams adopt trunk-based development?",
            "rounds": 3,
            "agents": ["claude", "gpt"],
            "auto_select": False,
        }
        req, err = validate_debate_request(payload)
        assert req is not None
        assert err is None

    def test_validation_returns_422_compatible_error(self):
        """Error from validate_debate_request is a string suitable for a 422 response."""
        from aragora.server.validation.pydantic_models import validate_debate_request

        _, err = validate_debate_request({"question": "Short"})
        # Error string should be non-empty and not a traceback
        assert err is not None
        assert "\n" not in err or len(err.splitlines()) <= 3
