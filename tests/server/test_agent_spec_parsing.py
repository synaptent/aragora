"""Tests for agent spec parsing in question_classifier.py.

Verifies that agent specs are in valid pipe format (provider|model|persona|role)
and can be parsed correctly by debate_factory.
"""

import pytest

from aragora.server.question_classifier import (
    PERSONA_TO_AGENT,
    QuestionClassification,
    QuestionClassifier,
    classify_and_assign_agents_sync,
)


class TestPersonaToAgentMapping:
    """Tests for PERSONA_TO_AGENT mapping format."""

    def test_all_mappings_are_simple_agent_types(self):
        """All persona mappings should be simple agent types without colons.

        This ensures get_agent_string() produces 2-part specs that
        debate_factory.parse_agent_specs() can correctly parse.
        """
        for persona, agent_type in PERSONA_TO_AGENT.items():
            assert ":" not in agent_type, (
                f"PERSONA_TO_AGENT['{persona}'] = '{agent_type}' contains a colon. "
                f"Use the registered agent type instead (e.g., 'qwen' not 'openrouter:qwen/model')."
            )

    def test_openrouter_personas_use_registered_types(self):
        """OpenRouter personas should use registered agent types."""
        # "yi" was removed with the YiAgent registration (frontier-model-
        # refresh, 2026-09-04): 01-ai/yi-large is gone from OpenRouter.
        openrouter_personas = ["qwen", "qwen-max", "deepseek", "deepseek-r1", "kimi"]

        for persona in openrouter_personas:
            agent_type = PERSONA_TO_AGENT.get(persona)
            assert agent_type is not None, f"Missing mapping for {persona}"
            # Should be a simple registered type, not "openrouter:model/path"
            assert not agent_type.startswith("openrouter:"), (
                f"'{persona}' maps to '{agent_type}'. "
                f"Should use registered type '{persona}' instead."
            )


class TestGetAgentString:
    """Tests for QuestionClassifier.get_agent_string()."""

    def test_always_produces_pipe_format_specs(self):
        """Agent specs should be in pipe format: provider|model|persona|role."""
        classifier = QuestionClassifier()
        classification = QuestionClassification(
            category="technical",
            complexity="moderate",
            recommended_personas=["qwen", "deepseek", "claude", "codex"],
        )

        result = classifier.get_agent_string(classification)

        for spec in result.split(","):
            parts = spec.split("|")
            assert len(parts) == 4, (
                f"Spec '{spec}' should have exactly 4 parts (provider|model|persona|role), "
                f"but has {len(parts)} parts"
            )
            provider, model, persona, role = parts
            assert provider, f"Provider should not be empty in spec '{spec}'"
            assert role in (
                "proposer",
                "critic",
                "synthesizer",
                "judge",
            ), f"Role '{role}' should be a valid debate role"

    def test_openrouter_specs_are_valid(self):
        """OpenRouter agent specs should be valid pipe format."""
        classifier = QuestionClassifier()
        classification = QuestionClassification(
            category="technical",
            complexity="complex",
            recommended_personas=["qwen", "deepseek", "kimi"],
        )

        result = classifier.get_agent_string(classification)

        # Should produce specs like "qwen||qwen|proposer,deepseek||deepseek|critic"
        for spec in result.split(","):
            parts = spec.split("|")
            assert len(parts) == 4, f"Spec '{spec}' should be pipe format with 4 parts"
            provider, model, persona, role = parts
            # Provider should not contain slashes (model paths)
            assert "/" not in provider, (
                f"Provider '{provider}' in spec '{spec}' contains '/'. "
                f"Model path should not be in the provider."
            )

    def test_mixed_personas_produce_valid_specs(self):
        """Mix of OpenRouter and direct API personas should all be pipe format."""
        classifier = QuestionClassifier()
        classification = QuestionClassification(
            category="scientific",
            complexity="complex",
            recommended_personas=["claude", "qwen", "gemini", "deepseek", "grok"],
        )

        result = classifier.get_agent_string(classification)

        specs = result.split(",")
        assert len(specs) >= 2, "Should have at least 2 agents"

        for spec in specs:
            parts = spec.split("|")
            assert len(parts) == 4, f"Spec '{spec}' should be pipe format with 4 parts"

    def test_avoids_duplicate_agent_types(self):
        """Should avoid duplicate agent types for diversity."""
        classifier = QuestionClassifier()
        # Create classification with personas that map to the same agent type
        classification = QuestionClassification(
            category="ethical",
            complexity="complex",
            recommended_personas=["philosopher", "existentialist", "humanist", "claude"],
        )

        result = classifier.get_agent_string(classification)
        specs = result.split(",")
        # Pipe format: provider|model|persona|role - get providers
        agent_types = [spec.split("|")[0] for spec in specs]

        # anthropic-api should not appear more than twice
        # (we allow up to 2 before filtering kicks in)
        anthropic_count = agent_types.count("anthropic-api")
        assert anthropic_count <= 2, (
            f"anthropic-api appears {anthropic_count} times, "
            f"diversity filter should limit duplicates"
        )


class TestClassifyAndAssignAgents:
    """Integration tests for classify_and_assign_agents()."""

    def test_simple_classification_produces_valid_specs(self):
        """Simple (non-LLM) classification should produce valid pipe format specs."""
        agent_string, classification = classify_and_assign_agents_sync(
            "What is the best database for high-throughput writes?",
        )

        assert classification.category in [
            "technical",
            "scientific",
            "general",
            "ethical",
            "financial",
            "healthcare",
            "legal",
            "security",
            "political",
        ]

        for spec in agent_string.split(","):
            parts = spec.split("|")
            assert len(parts) == 4, f"Spec '{spec}' should be pipe format with 4 parts"

    def test_compliance_question_produces_valid_specs(self):
        """Compliance question should produce valid agent specs."""
        agent_string, classification = classify_and_assign_agents_sync(
            "How do we ensure HIPAA compliance for patient data?",
        )

        for spec in agent_string.split(","):
            parts = spec.split("|")
            assert len(parts) == 4, f"Spec '{spec}' should be pipe format with 4 parts"


class TestDebateFactoryCompatibility:
    """Tests ensuring compatibility with debate_factory.parse_agent_specs()."""

    def test_specs_parseable_by_debate_factory(self):
        """Generated specs should be parseable by DebateConfig.parse_agent_specs()."""
        from aragora.server.debate_factory import AgentSpec, DebateConfig

        classifier = QuestionClassifier()
        classification = QuestionClassification(
            category="technical",
            complexity="moderate",
            recommended_personas=["qwen", "deepseek", "claude"],
        )

        agent_string = classifier.get_agent_string(classification)

        # Create DebateConfig and parse (disable auto_trim to test parsing, not credentials)
        config = DebateConfig(
            question="Test question",
            agents_str=agent_string,
            auto_trim_unavailable=False,
        )

        specs = config.parse_agent_specs()

        assert len(specs) >= 2, "Should have at least 2 agent specs"
        for spec in specs:
            assert isinstance(spec, AgentSpec)
            assert spec.provider, f"Provider should not be empty: {spec}"
            # Role should be a valid debate role, not a model path
            assert spec.role in (
                "proposer",
                "critic",
                "synthesizer",
                "judge",
            ), f"Role '{spec.role}' should be a valid debate role"
            assert "/" not in (spec.role or ""), (
                f"Role '{spec.role}' contains '/', suggesting a model path leaked into role"
            )
