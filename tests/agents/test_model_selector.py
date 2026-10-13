"""
Tests for the SpecialistModelSelector and related classes.

Tests cover:
- ModelCapability enum
- ModelProfile dataclass and methods
- SpecialistModelSelector model selection logic
- MODEL_PROFILES definitions
- Cost and latency optimization
- Model comparison functionality
"""

import pytest

from aragora.agents.model_selector import (
    MODEL_PROFILES,
    VERTICAL_CAPABILITIES,
    ModelCapability,
    ModelProfile,
    ModelSelection,
    SpecialistModelSelector,
)
from aragora.agents.vertical_personas import Vertical


class TestModelProfiles:
    """Tests for MODEL_PROFILES dictionary."""

    def test_model_profiles_exist(self):
        """Verify major models are defined in MODEL_PROFILES."""
        assert "claude" in MODEL_PROFILES
        assert "gpt4" in MODEL_PROFILES
        assert "gemini" in MODEL_PROFILES

    def test_model_profiles_include_all_major_providers(self):
        """Verify all major providers are represented."""
        providers = {p.provider for p in MODEL_PROFILES.values()}
        assert "anthropic" in providers
        assert "openai" in providers
        assert "google" in providers
        assert "mistral" in providers
        assert "deepseek" in providers
        assert "xai" in providers

    def test_claude_profile_has_expected_properties(self):
        """Verify Claude profile has correct properties."""
        claude = MODEL_PROFILES["claude"]
        assert claude.model_id == "claude-sonnet-4-6"
        assert claude.display_name == "Claude Sonnet 4.6"
        assert claude.provider == "anthropic"
        assert claude.max_context_tokens == 200000
        assert claude.supports_vision is True

    def test_kimi_profile_tracks_k3_runtime_metadata(self):
        kimi = MODEL_PROFILES["kimi"]

        assert kimi.model_id == "kimi-k3"
        assert kimi.display_name == "Kimi K3"
        assert kimi.provider == "moonshot"
        assert kimi.max_context_tokens == 1_048_576
        assert kimi.max_output_tokens == 32_768
        assert (kimi.cost_input_per_1k, kimi.cost_output_per_1k) == (0.003, 0.015)
        assert kimi.supports_vision is True

    def test_qwen_profile_tracks_qwen38_max_runtime_metadata(self):
        qwen = MODEL_PROFILES["qwen"]

        assert qwen.model_id == "qwen3.8-max"
        assert qwen.display_name == "Qwen 3.8 Max"
        assert qwen.provider == "alibaba"
        assert qwen.max_context_tokens == 1_000_000
        assert qwen.max_output_tokens == 131_072
        assert (qwen.cost_input_per_1k, qwen.cost_output_per_1k) == (0.002, 0.006)

    def test_all_profiles_have_required_fields(self):
        """Verify all profiles have required fields populated."""
        for name, profile in MODEL_PROFILES.items():
            assert profile.model_id, f"{name} missing model_id"
            assert profile.display_name, f"{name} missing display_name"
            assert profile.provider, f"{name} missing provider"
            assert profile.max_context_tokens > 0, f"{name} has invalid context"
            assert profile.cost_input_per_1k >= 0, f"{name} has invalid input cost"
            assert profile.cost_output_per_1k >= 0, f"{name} has invalid output cost"

    def test_all_profiles_have_capabilities(self):
        """Verify all profiles have capability scores defined."""
        for name, profile in MODEL_PROFILES.items():
            assert len(profile.capabilities) > 0, f"{name} has no capabilities"
            for cap, score in profile.capabilities.items():
                assert 0.0 <= score <= 1.0, f"{name} has invalid {cap} score: {score}"


class TestModelCapabilityEnum:
    """Tests for ModelCapability enum."""

    def test_model_capability_enum_has_all_types(self):
        """All capability types should be defined."""
        expected_capabilities = [
            "REASONING",
            "CODING",
            "LEGAL",
            "MEDICAL",
            "FINANCIAL",
            "CREATIVE",
            "MATH",
            "MULTILINGUAL",
            "LONG_CONTEXT",
            "INSTRUCTION_FOLLOWING",
            "FACTUAL_ACCURACY",
        ]
        actual_capabilities = [cap.name for cap in ModelCapability]
        for expected in expected_capabilities:
            assert expected in actual_capabilities, f"Missing capability: {expected}"

    def test_model_capability_enum_values(self):
        """Verify enum values are lowercase strings."""
        for cap in ModelCapability:
            assert cap.value == cap.name.lower()

    def test_model_capability_enum_count(self):
        """Verify the expected number of capabilities."""
        assert len(ModelCapability) == 11


class TestModelProfile:
    """Tests for ModelProfile dataclass."""

    @pytest.fixture
    def sample_profile(self):
        """Create a sample profile for testing."""
        return ModelProfile(
            model_id="test-model",
            display_name="Test Model",
            provider="test-provider",
            capabilities={
                ModelCapability.REASONING: 0.9,
                ModelCapability.CODING: 0.85,
                ModelCapability.LEGAL: 0.7,
            },
            max_context_tokens=100000,
            max_output_tokens=4096,
            cost_input_per_1k=0.01,
            cost_output_per_1k=0.03,
            avg_latency_ms=500.0,
            reliability_score=0.95,
        )

    def test_get_capability_score(self, sample_profile):
        """Test score retrieval for a profile."""
        assert sample_profile.get_capability_score(ModelCapability.REASONING) == 0.9
        assert sample_profile.get_capability_score(ModelCapability.CODING) == 0.85
        assert sample_profile.get_capability_score(ModelCapability.LEGAL) == 0.7

    def test_get_capability_score_missing(self, sample_profile):
        """Test score retrieval for undefined capability returns default."""
        # MEDICAL is not defined in the sample profile
        score = sample_profile.get_capability_score(ModelCapability.MEDICAL)
        assert score == 0.5  # Default value

    def test_get_total_score_with_weights(self, sample_profile):
        """Test weighted score calculation."""
        weights = {
            ModelCapability.REASONING: 0.5,
            ModelCapability.CODING: 0.3,
            ModelCapability.LEGAL: 0.2,
        }
        # Expected: (0.9*0.5 + 0.85*0.3 + 0.7*0.2) / (0.5+0.3+0.2)
        # = (0.45 + 0.255 + 0.14) / 1.0 = 0.845
        score = sample_profile.get_total_score(weights)
        assert abs(score - 0.845) < 0.001

    def test_get_total_score_empty_weights(self, sample_profile):
        """Test weighted score with empty weights returns default."""
        score = sample_profile.get_total_score({})
        assert score == 0.5  # Default when no weights

    def test_get_total_score_with_missing_capabilities(self, sample_profile):
        """Test weighted score calculation with capabilities not in profile."""
        weights = {
            ModelCapability.REASONING: 0.5,
            ModelCapability.MEDICAL: 0.5,  # Not in sample profile
        }
        # MEDICAL defaults to 0.5
        # Expected: (0.9*0.5 + 0.5*0.5) / 1.0 = 0.7
        score = sample_profile.get_total_score(weights)
        assert abs(score - 0.7) < 0.001

    def test_estimate_cost(self, sample_profile):
        """Test cost estimation for tokens."""
        # 1000 input tokens at 0.01 per 1K = 0.01
        # 500 output tokens at 0.03 per 1K = 0.015
        # Total = 0.025
        cost = sample_profile.estimate_cost(input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.025) < 0.0001

    def test_estimate_cost_zero_tokens(self, sample_profile):
        """Test cost estimation with zero tokens."""
        cost = sample_profile.estimate_cost(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_estimate_cost_large_request(self, sample_profile):
        """Test cost estimation for large token counts."""
        # 100K input tokens at 0.01 per 1K = 1.0
        # 10K output tokens at 0.03 per 1K = 0.3
        # Total = 1.3
        cost = sample_profile.estimate_cost(input_tokens=100000, output_tokens=10000)
        assert abs(cost - 1.3) < 0.0001

    def test_default_values(self):
        """Test default values for ModelProfile."""
        profile = ModelProfile(
            model_id="minimal",
            display_name="Minimal Model",
            provider="test",
        )
        assert profile.max_context_tokens == 128000
        assert profile.max_output_tokens == 4096
        assert profile.cost_input_per_1k == 0.003
        assert profile.cost_output_per_1k == 0.015
        assert profile.avg_latency_ms == 1000.0
        assert profile.reliability_score == 0.95
        assert profile.is_fine_tunable is False
        assert profile.supports_function_calling is True
        assert profile.supports_vision is False
        assert profile.supports_streaming is True


class TestSpecialistModelSelector:
    """Tests for SpecialistModelSelector class."""

    @pytest.fixture
    def selector(self):
        """Create a selector with default profiles."""
        return SpecialistModelSelector()

    @pytest.fixture
    def custom_selector(self):
        """Create a selector with custom profiles for controlled testing."""
        custom_profiles = {
            "fast-model": ModelProfile(
                model_id="fast-1",
                display_name="Fast Model",
                provider="test",
                capabilities={
                    ModelCapability.CODING: 0.8,
                    ModelCapability.REASONING: 0.7,
                    ModelCapability.LEGAL: 0.6,
                },
                max_context_tokens=50000,
                cost_input_per_1k=0.001,
                cost_output_per_1k=0.002,
                avg_latency_ms=200,
                reliability_score=0.95,
            ),
            "smart-model": ModelProfile(
                model_id="smart-1",
                display_name="Smart Model",
                provider="test",
                capabilities={
                    ModelCapability.CODING: 0.95,
                    ModelCapability.REASONING: 0.95,
                    ModelCapability.LEGAL: 0.9,
                },
                max_context_tokens=200000,
                cost_input_per_1k=0.01,
                cost_output_per_1k=0.03,
                avg_latency_ms=1000,
                reliability_score=0.98,
            ),
            "cheap-model": ModelProfile(
                model_id="cheap-1",
                display_name="Cheap Model",
                provider="test",
                capabilities={
                    ModelCapability.CODING: 0.7,
                    ModelCapability.REASONING: 0.65,
                    ModelCapability.LEGAL: 0.5,
                },
                max_context_tokens=100000,
                cost_input_per_1k=0.0001,
                cost_output_per_1k=0.0002,
                avg_latency_ms=400,
                reliability_score=0.90,
            ),
        }
        return SpecialistModelSelector(model_profiles=custom_profiles)

    def test_select_model_for_coding_task(self, selector):
        """Test selection with CODING capability."""
        selection = selector.select_model(
            vertical=Vertical.SOFTWARE,
            task_type="code_review",
            required_capabilities=[ModelCapability.CODING],
        )

        assert isinstance(selection, ModelSelection)
        assert selection.model_id in MODEL_PROFILES
        # The selected model should have good coding capability
        profile = MODEL_PROFILES[selection.model_id]
        assert profile.get_capability_score(ModelCapability.CODING) >= 0.8

    def test_select_model_for_legal_task(self, selector):
        """Test selection with LEGAL capability."""
        selection = selector.select_model(
            vertical=Vertical.LEGAL,
            task_type="contract_review",
            required_capabilities=[ModelCapability.LEGAL],
        )

        assert isinstance(selection, ModelSelection)
        assert selection.model_id in MODEL_PROFILES
        # Selection should have good legal capability
        profile = MODEL_PROFILES[selection.model_id]
        assert profile.get_capability_score(ModelCapability.LEGAL) >= 0.7

    def test_select_model_with_context_constraint(self, custom_selector):
        """Test context length filtering."""
        # Request context that only smart-model can handle
        selection = custom_selector.select_model(
            context_length=150000,  # Only smart-model has 200K
        )

        assert selection.model_id == "smart-model"

    def test_select_model_filters_insufficient_context(self, custom_selector):
        """Test that models with insufficient context are filtered out."""
        # fast-model has only 50K context
        selection = custom_selector.select_model(
            context_length=60000,
        )

        # fast-model should be excluded
        assert selection.model_id != "fast-model"

    def test_select_model_cost_sensitive(self, custom_selector):
        """Test cost sensitivity adjustment."""
        # Without cost sensitivity
        selection_normal = custom_selector.select_model(
            vertical=Vertical.SOFTWARE,
            cost_sensitive=False,
        )

        # With cost sensitivity
        selection_cost = custom_selector.select_model(
            vertical=Vertical.SOFTWARE,
            cost_sensitive=True,
        )

        # Cost-sensitive selection should favor cheaper model
        normal_profile = custom_selector._profiles[selection_normal.model_id]
        cost_profile = custom_selector._profiles[selection_cost.model_id]

        normal_cost = (normal_profile.cost_input_per_1k + normal_profile.cost_output_per_1k) / 2
        cost_cost = (cost_profile.cost_input_per_1k + cost_profile.cost_output_per_1k) / 2

        # The cost-sensitive selection should have equal or lower cost
        assert cost_cost <= normal_cost

    def test_select_model_latency_sensitive(self, custom_selector):
        """Test latency sensitivity adjustment."""
        # Without latency sensitivity
        selection_normal = custom_selector.select_model(
            vertical=Vertical.SOFTWARE,
            latency_sensitive=False,
        )

        # With latency sensitivity
        selection_latency = custom_selector.select_model(
            vertical=Vertical.SOFTWARE,
            latency_sensitive=True,
        )

        # Latency-sensitive selection should favor faster model
        normal_profile = custom_selector._profiles[selection_normal.model_id]
        latency_profile = custom_selector._profiles[selection_latency.model_id]

        # The latency-sensitive selection should have equal or lower latency
        assert latency_profile.avg_latency_ms <= normal_profile.avg_latency_ms

    def test_select_model_excluded_models(self, custom_selector):
        """Test that excluded models are not selected."""
        selection = custom_selector.select_model(
            excluded_models=["smart-model", "fast-model"],
        )

        assert selection.model_id == "cheap-model"

    def test_select_model_returns_selection_object(self, selector):
        """Test that select_model returns a proper ModelSelection object."""
        selection = selector.select_model()

        assert isinstance(selection, ModelSelection)
        assert isinstance(selection.model_id, str)
        assert isinstance(selection.profile, ModelProfile)
        assert isinstance(selection.score, float)
        assert isinstance(selection.reasoning, str)
        assert isinstance(selection.alternatives, list)
        assert isinstance(selection.estimated_cost, float)
        assert isinstance(selection.estimated_latency_ms, (int, float))

    def test_select_model_includes_alternatives(self, selector):
        """Test that selection includes alternative models."""
        selection = selector.select_model()

        # Should have up to 3 alternatives
        assert len(selection.alternatives) <= 3
        for alt_id, alt_score in selection.alternatives:
            assert isinstance(alt_id, str)
            assert isinstance(alt_score, float)
            # Alternative scores should be less than or equal to selected
            assert alt_score <= selection.score

    def test_get_cheapest_capable(self, custom_selector):
        """Test finding the most cost-effective model."""
        cheapest = custom_selector.get_cheapest_capable(
            min_capability_score=0.7,
            capability=ModelCapability.CODING,
        )

        assert cheapest == "cheap-model"

    def test_get_cheapest_capable_high_threshold(self, custom_selector):
        """Test cheapest capable with high threshold."""
        cheapest = custom_selector.get_cheapest_capable(
            min_capability_score=0.9,
            capability=ModelCapability.CODING,
        )

        # Only smart-model has CODING >= 0.9
        assert cheapest == "smart-model"

    def test_get_cheapest_capable_no_match(self, custom_selector):
        """Test cheapest capable when no model qualifies."""
        cheapest = custom_selector.get_cheapest_capable(
            min_capability_score=0.99,
            capability=ModelCapability.CODING,
        )

        assert cheapest is None

    def test_get_fastest_capable(self, custom_selector):
        """Test finding the lowest latency model."""
        fastest = custom_selector.get_fastest_capable(
            min_capability_score=0.7,
            capability=ModelCapability.CODING,
        )

        # fast-model has lowest latency (200ms) and CODING=0.8 >= 0.7
        assert fastest == "fast-model"

    def test_get_fastest_capable_high_threshold(self, custom_selector):
        """Test fastest capable with high threshold."""
        fastest = custom_selector.get_fastest_capable(
            min_capability_score=0.9,
            capability=ModelCapability.CODING,
        )

        # Only smart-model has CODING >= 0.9
        assert fastest == "smart-model"

    def test_get_fastest_capable_no_match(self, custom_selector):
        """Test fastest capable when no model qualifies."""
        fastest = custom_selector.get_fastest_capable(
            min_capability_score=0.99,
            capability=ModelCapability.CODING,
        )

        assert fastest is None

    def test_compare_models(self, selector):
        """Test model comparison output."""
        comparison = selector.compare_models(
            model_ids=["claude", "gpt4", "gemini"],
            vertical=Vertical.SOFTWARE,
        )

        assert "claude" in comparison
        assert "gpt4" in comparison
        assert "gemini" in comparison

        # Check structure of comparison data
        for model_id, data in comparison.items():
            assert "display_name" in data
            assert "provider" in data
            assert "total_score" in data
            assert "capabilities" in data
            assert "max_context" in data
            assert "cost_per_1k_avg" in data
            assert "avg_latency_ms" in data
            assert "reliability" in data

    def test_compare_models_includes_all_capabilities(self, selector):
        """Test that comparison includes all capability scores."""
        comparison = selector.compare_models(["claude"], vertical=Vertical.GENERAL)

        capabilities = comparison["claude"]["capabilities"]
        for cap in ModelCapability:
            assert cap.value in capabilities
            assert isinstance(capabilities[cap.value], float)

    def test_compare_models_unknown_model(self, selector):
        """Test that unknown models are skipped in comparison."""
        comparison = selector.compare_models(
            model_ids=["claude", "unknown_model", "gpt4"],
        )

        assert "claude" in comparison
        assert "gpt4" in comparison
        assert "unknown_model" not in comparison

    def test_fallback_to_default(self):
        """Test fallback when no candidates match."""
        # Create selector with limited profiles
        limited_profiles = {
            "small-model": ModelProfile(
                model_id="small",
                display_name="Small",
                provider="test",
                capabilities={ModelCapability.REASONING: 0.5},
                max_context_tokens=1000,  # Very small
            ),
        }
        selector = SpecialistModelSelector(model_profiles=limited_profiles)

        # Request context larger than any model supports
        selection = selector.select_model(context_length=10000)

        # Should fall back to available model
        assert selection is not None
        assert selection.model_id == "small-model"

    def test_fallback_with_all_excluded(self, custom_selector):
        """Test fallback when all models are excluded."""
        selection = custom_selector.select_model(
            excluded_models=["fast-model", "smart-model", "cheap-model"],
        )

        # Should still return something (fallback)
        assert selection is not None

    def test_selection_reasoning_includes_vertical(self, selector):
        """Test that reasoning includes vertical information."""
        selection = selector.select_model(
            vertical=Vertical.LEGAL,
            task_type="contract_analysis",
        )

        assert "legal" in selection.reasoning.lower()

    def test_selection_reasoning_includes_modifiers(self, selector):
        """Test that reasoning includes cost/latency modifiers."""
        selection = selector.select_model(
            cost_sensitive=True,
            latency_sensitive=True,
        )

        assert "cost" in selection.reasoning.lower()
        assert "latency" in selection.reasoning.lower()


class TestVerticalCapabilities:
    """Tests for VERTICAL_CAPABILITIES mapping."""

    def test_vertical_capabilities_defined(self):
        """Test that vertical capabilities are defined for major verticals."""
        assert Vertical.SOFTWARE in VERTICAL_CAPABILITIES
        assert Vertical.LEGAL in VERTICAL_CAPABILITIES
        assert Vertical.HEALTHCARE in VERTICAL_CAPABILITIES
        assert Vertical.ACCOUNTING in VERTICAL_CAPABILITIES
        assert Vertical.ACADEMIC in VERTICAL_CAPABILITIES
        assert Vertical.GENERAL in VERTICAL_CAPABILITIES

    def test_vertical_capabilities_weights_are_positive(self):
        """Test that all capability weights are positive."""
        for vertical, weights in VERTICAL_CAPABILITIES.items():
            for cap, weight in weights.items():
                assert weight > 0, f"{vertical} has non-positive weight for {cap}"
                assert weight <= 1.0, f"{vertical} has weight > 1.0 for {cap}"

    def test_software_vertical_emphasizes_coding(self):
        """Test that SOFTWARE vertical emphasizes coding capability."""
        weights = VERTICAL_CAPABILITIES[Vertical.SOFTWARE]
        assert ModelCapability.CODING in weights
        # Coding should be the highest or among the highest
        assert weights[ModelCapability.CODING] == max(weights.values())

    def test_legal_vertical_emphasizes_legal(self):
        """Test that LEGAL vertical emphasizes legal capability."""
        weights = VERTICAL_CAPABILITIES[Vertical.LEGAL]
        assert ModelCapability.LEGAL in weights
        # Legal should be the highest
        assert weights[ModelCapability.LEGAL] == max(weights.values())

    def test_healthcare_vertical_emphasizes_medical(self):
        """Test that HEALTHCARE vertical emphasizes medical capability."""
        weights = VERTICAL_CAPABILITIES[Vertical.HEALTHCARE]
        assert ModelCapability.MEDICAL in weights
        # Medical should be the highest
        assert weights[ModelCapability.MEDICAL] == max(weights.values())


class TestModelSelectionEdgeCases:
    """Tests for edge cases in model selection."""

    def test_empty_available_models(self):
        """Test handling of empty available models list."""
        selector = SpecialistModelSelector(available_models=[])
        selection = selector.select_model()

        # Should return a fallback - when available_models is empty,
        # the selector falls back to MODEL_PROFILES keys
        assert selection is not None
        assert selection.model_id in MODEL_PROFILES

    def test_available_models_subset(self):
        """Test selection with subset of available models."""
        selector = SpecialistModelSelector(available_models=["claude", "gpt4"])

        selection = selector.select_model()
        assert selection.model_id in ["claude", "gpt4"]

        # Alternatives should only include available models
        for alt_id, _ in selection.alternatives:
            assert alt_id in ["claude", "gpt4"]

    def test_multiple_required_capabilities(self):
        """Test selection with multiple required capabilities."""
        selector = SpecialistModelSelector()

        selection = selector.select_model(
            required_capabilities=[
                ModelCapability.CODING,
                ModelCapability.REASONING,
                ModelCapability.LONG_CONTEXT,
            ],
        )

        profile = MODEL_PROFILES[selection.model_id]
        # Selected model should be strong in all required capabilities
        assert profile.get_capability_score(ModelCapability.CODING) >= 0.7
        assert profile.get_capability_score(ModelCapability.REASONING) >= 0.7

    def test_cost_and_latency_sensitive_together(self):
        """Test selection with both cost and latency sensitivity."""
        selector = SpecialistModelSelector()

        selection = selector.select_model(
            cost_sensitive=True,
            latency_sensitive=True,
        )

        # Should return a model that balances both
        assert selection is not None
        profile = MODEL_PROFILES[selection.model_id]
        # Typically Haiku or similar efficient models
        assert profile.avg_latency_ms <= 1500


class TestModelProfileCapabilities:
    """Tests for model profile capability scores."""

    @pytest.mark.parametrize(
        "model_id",
        ["claude", "gpt4", "gemini", "mistral", "deepseek"],
    )
    def test_model_has_reasoning_capability(self, model_id):
        """Test that major models have reasoning capability defined."""
        profile = MODEL_PROFILES[model_id]
        score = profile.get_capability_score(ModelCapability.REASONING)
        assert score >= 0.7, f"{model_id} should have strong reasoning"

    @pytest.mark.parametrize(
        "model_id",
        ["claude", "gpt4", "deepseek"],
    )
    def test_coding_focused_models(self, model_id):
        """Test that coding-focused models have high coding scores."""
        profile = MODEL_PROFILES[model_id]
        score = profile.get_capability_score(ModelCapability.CODING)
        assert score >= 0.85, f"{model_id} should have excellent coding capability"

    @pytest.mark.parametrize(
        "model_id,expected_provider",
        [
            ("claude", "anthropic"),
            ("gpt4", "openai"),
            ("gemini", "google"),
            ("mistral", "mistral"),
            ("deepseek", "deepseek"),
            ("grok", "xai"),
        ],
    )
    def test_model_provider_mapping(self, model_id, expected_provider):
        """Test that models are mapped to correct providers."""
        profile = MODEL_PROFILES[model_id]
        assert profile.provider == expected_provider


class TestModelSelectionIntegration:
    """Integration tests for the model selector."""

    def test_full_selection_workflow(self):
        """Test a complete selection workflow."""
        selector = SpecialistModelSelector()

        # Simulate selecting for a legal document review
        selection = selector.select_model(
            vertical=Vertical.LEGAL,
            task_type="contract_review",
            context_length=100000,
            cost_sensitive=False,
            latency_sensitive=False,
            required_capabilities=[ModelCapability.LEGAL, ModelCapability.LONG_CONTEXT],
        )

        # Verify complete selection
        assert selection.model_id
        assert selection.profile
        assert selection.score > 0
        assert selection.reasoning
        assert selection.estimated_cost > 0
        assert selection.estimated_latency_ms > 0

    def test_selection_consistency(self):
        """Test that selection is deterministic for same inputs."""
        selector = SpecialistModelSelector()

        selection1 = selector.select_model(
            vertical=Vertical.SOFTWARE,
            task_type="code_review",
        )

        selection2 = selector.select_model(
            vertical=Vertical.SOFTWARE,
            task_type="code_review",
        )

        assert selection1.model_id == selection2.model_id
        assert selection1.score == selection2.score
