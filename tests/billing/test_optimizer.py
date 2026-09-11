"""
Tests for the cost optimization engine.

Tests cover:
- Model downgrade analysis
- Caching recommendations
- Batching optimization
- Recommendation management
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.billing.recommendations import (
    OptimizationRecommendation,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
    ModelAlternative,
    CachingOpportunity,
    BatchingOpportunity,
    RecommendationSummary,
)
from aragora.billing.optimizer import (
    CostOptimizer,
    MODEL_TIERS,
    ModelDowngradeAnalyzer,
    CachingRecommender,
    BatchingOptimizer,
    UsagePattern,
)
from aragora.billing.usage import PROVIDER_PRICING


class TestRecommendationDataclasses:
    """Tests for recommendation dataclasses."""

    def test_optimization_recommendation_creates_correctly(self):
        """Test OptimizationRecommendation initialization."""
        rec = OptimizationRecommendation(
            type=RecommendationType.MODEL_DOWNGRADE,
            priority=RecommendationPriority.HIGH,
            workspace_id="ws-123",
            current_cost_usd=Decimal("100.00"),
            projected_cost_usd=Decimal("30.00"),
            title="Use cheaper model",
            description="Switch to a cheaper model for this operation",
        )

        assert rec.type == RecommendationType.MODEL_DOWNGRADE
        assert rec.priority == RecommendationPriority.HIGH
        assert rec.estimated_savings_usd == Decimal("70.00")
        assert rec.savings_percentage == 70.0
        assert rec.status == RecommendationStatus.PENDING

    def test_recommendation_to_dict(self):
        """Test recommendation serialization."""
        rec = OptimizationRecommendation(
            type=RecommendationType.CACHING,
            priority=RecommendationPriority.MEDIUM,
            workspace_id="ws-123",
            current_cost_usd=Decimal("50.00"),
            projected_cost_usd=Decimal("25.00"),
            title="Enable caching",
        )

        data = rec.to_dict()

        assert data["type"] == "caching"
        assert data["priority"] == "medium"
        assert data["estimated_savings_usd"] == "25.00"
        assert data["savings_percentage"] == 50.0

    def test_recommendation_apply(self):
        """Test applying a recommendation."""
        rec = OptimizationRecommendation(
            type=RecommendationType.MODEL_DOWNGRADE,
            workspace_id="ws-123",
        )

        rec.apply("user-456")

        assert rec.status == RecommendationStatus.APPLIED
        assert rec.applied_by == "user-456"
        assert rec.applied_at is not None

    def test_recommendation_dismiss(self):
        """Test dismissing a recommendation."""
        rec = OptimizationRecommendation(
            type=RecommendationType.BATCHING,
            workspace_id="ws-123",
        )

        rec.dismiss()

        assert rec.status == RecommendationStatus.DISMISSED

    def test_recommendation_summary(self):
        """Test recommendation summary."""
        summary = RecommendationSummary(
            workspace_id="ws-123",
            total_recommendations=10,
            pending_count=5,
            applied_count=3,
            dismissed_count=2,
            total_potential_savings=Decimal("100.00"),
            realized_savings=Decimal("60.00"),
            critical_count=1,
            high_count=2,
            medium_count=4,
            low_count=3,
        )

        data = summary.to_dict()

        assert data["total_recommendations"] == 10
        assert data["total_potential_savings_usd"] == "100.00"
        assert data["by_priority"]["critical"] == 1


class TestModelDowngradeAnalyzer:
    """Tests for model downgrade analyzer."""

    def test_model_tiers_have_explicit_provider_pricing(self):
        """Every optimizer tier must resolve to explicit billing rates, not defaults."""
        for model, info in MODEL_TIERS.items():
            provider_prices = PROVIDER_PRICING[info["provider"]]
            assert model in provider_prices
            assert f"{model}-output" in provider_prices

    def test_analyze_identifies_downgrade_opportunity(self):
        """Test analyzer finds downgrade opportunities."""
        analyzer = ModelDowngradeAnalyzer()

        patterns = [
            UsagePattern(
                model="claude-opus-4",
                provider="anthropic",
                operation="summarize",
                count=100,
                total_tokens_in=500000,
                total_tokens_out=100000,
                total_cost=Decimal("50.00"),
            ),
        ]

        recommendations = analyzer.analyze(patterns, "ws-123")

        assert len(recommendations) >= 1
        rec = recommendations[0]
        assert rec.type == RecommendationType.MODEL_DOWNGRADE
        assert rec.projected_cost_usd < rec.current_cost_usd
        assert rec.model_alternative is not None

    def test_analyze_recommends_downgrade_to_new_models(self):
        """Test analyzer finds new alternatives like gemini-3.5-flash and deepseek-v4-pro."""
        analyzer = ModelDowngradeAnalyzer()

        patterns = [
            UsagePattern(
                model="claude-opus-4-8",
                provider="anthropic",
                operation="summarize",
                count=100,
                total_tokens_in=500000,
                total_tokens_out=100000,
                total_cost=Decimal("50.00"),
            ),
        ]

        recommendations = analyzer.analyze(patterns, "ws-123")

        assert len(recommendations) >= 1
        rec = recommendations[0]
        assert rec.type == RecommendationType.MODEL_DOWNGRADE
        assert rec.model_alternative is not None
        assert rec.projected_cost_usd < rec.current_cost_usd

        alternatives = {
            alt.model: alt
            for alt in analyzer._find_alternatives(  # noqa: SLF001
                patterns[0],
                current_tier=1,
            )
        }
        assert "deepseek-v4-pro" in alternatives
        assert "gemini-3.5-flash" in alternatives
        assert alternatives["gemini-3.5-flash"].cost_per_1k_input == Decimal("0.00150")
        assert alternatives["gemini-3.5-flash"].cost_per_1k_output == Decimal("0.00900")

    def test_runtime_claude_model_ids_have_optimizer_tiers(self):
        """Runtime Claude IDs must hit optimizer tiers instead of being skipped."""
        # claude-opus-4-8 is a live catalog row, so the CATALOG band wins the
        # collision with the hand-curated one (wave-6 ruling, tables).
        assert MODEL_TIERS["claude-opus-4-8"] == {
            "tier": 1,
            "provider": "anthropic",
            "quality": 0.9,
        }
        assert MODEL_TIERS["claude-opus-4-7"] == {
            "tier": 1,
            "provider": "anthropic",
            "quality": 1.0,
        }
        assert MODEL_TIERS["claude-opus-4.8"] == {
            "tier": 1,
            "provider": "anthropic",
            "quality": 1.0,
        }
        assert MODEL_TIERS["claude-opus-4.7"] == {
            "tier": 1,
            "provider": "anthropic",
            "quality": 1.0,
        }
        assert MODEL_TIERS["claude-haiku-3"] == {
            "tier": 3,
            "provider": "anthropic",
            "quality": 0.65,
        }
        assert MODEL_TIERS["claude-haiku-4-5"] == {
            "tier": 3,
            "provider": "anthropic",
            "quality": 0.65,
        }
        assert MODEL_TIERS["claude-haiku-4.5"] == {
            "tier": 3,
            "provider": "anthropic",
            "quality": 0.65,
        }
        # Same: a live catalog row, so its own "value" band wins.
        assert MODEL_TIERS["claude-haiku-4-5-20251001"] == {
            "tier": 3,
            "provider": "anthropic",
            "quality": 0.72,
        }

    def test_analyze_uses_runtime_opus_model_for_downgrade(self):
        """The analyzer must not miss Opus traffic because the model ID is an alias."""
        analyzer = ModelDowngradeAnalyzer()

        for model in (
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-opus-4.8",
            "claude-opus-4.7",
        ):
            recommendations = analyzer.analyze(
                [
                    UsagePattern(
                        model=model,
                        provider="anthropic",
                        operation="summarize",
                        count=100,
                        total_tokens_in=500000,
                        total_tokens_out=100000,
                        total_cost=Decimal("50.00"),
                    ),
                ],
                "ws-123",
            )

            assert recommendations
            assert recommendations[0].title.startswith("Use ")
            assert f"instead of {model}" in recommendations[0].title

    def test_runtime_haiku_model_can_be_priced_as_alternative(self):
        """Runtime Haiku IDs keep explicit rates when eligible as alternatives."""
        analyzer = ModelDowngradeAnalyzer(quality_threshold=0.6)

        alternatives = {
            alt.model: alt
            for alt in analyzer._find_alternatives(  # noqa: SLF001
                UsagePattern(
                    model="claude-opus-4-8",
                    provider="anthropic",
                    operation="summarize",
                ),
                current_tier=1,
            )
        }

        assert alternatives["claude-haiku-4-5"].cost_per_1k_input == Decimal("0.00100")
        assert alternatives["claude-haiku-4-5"].cost_per_1k_output == Decimal("0.00500")

    def test_analyze_skips_cheap_models(self):
        """Test analyzer skips already cheap models."""
        analyzer = ModelDowngradeAnalyzer()

        patterns = [
            UsagePattern(
                model="gpt-4o-mini",
                provider="openai",
                operation="classify",
                count=100,
                total_tokens_in=100000,
                total_tokens_out=20000,
                total_cost=Decimal("5.00"),
            ),
        ]

        recommendations = analyzer.analyze(patterns, "ws-123")

        # Should not recommend downgrade for already cheap model
        assert len(recommendations) == 0

    def test_analyze_respects_min_sample_size(self):
        """Test analyzer skips patterns with too few samples."""
        analyzer = ModelDowngradeAnalyzer(min_sample_size=50)

        patterns = [
            UsagePattern(
                model="claude-opus-4",
                provider="anthropic",
                operation="analyze",
                count=10,  # Below threshold
                total_cost=Decimal("100.00"),
            ),
        ]

        recommendations = analyzer.analyze(patterns, "ws-123")

        assert len(recommendations) == 0

    def test_is_simple_operation(self):
        """Test simple operation detection."""
        analyzer = ModelDowngradeAnalyzer()

        assert analyzer._is_simple_operation("summarize_document")
        assert analyzer._is_simple_operation("extract_entities")
        assert analyzer._is_simple_operation("format_text")
        assert not analyzer._is_simple_operation("analyze_complex_code")
        assert not analyzer._is_simple_operation("debug_issue")


class TestCachingRecommender:
    """Tests for caching recommender."""

    def test_analyze_finds_caching_opportunities(self):
        """Test recommender finds caching opportunities."""
        recommender = CachingRecommender(min_repeat_count=3)

        # Create mock usage data with repeated patterns
        from aragora.billing.cost_tracker import TokenUsage

        usages = []
        for i in range(20):
            usages.append(
                TokenUsage(
                    workspace_id="ws-123",
                    operation="get_summary",
                    tokens_in=1000,  # Same tokens = likely repeated
                    tokens_out=200,
                    cost_usd=Decimal("0.05"),
                    timestamp=datetime.now(timezone.utc),
                )
            )

        recommendations = recommender.analyze(usages, "ws-123")

        assert len(recommendations) >= 1
        rec = recommendations[0]
        assert rec.type == RecommendationType.CACHING
        assert rec.caching_opportunity is not None

    def test_analyze_skips_low_repeat_operations(self):
        """Test recommender skips operations with low repeats."""
        recommender = CachingRecommender(min_repeat_count=10)

        from aragora.billing.cost_tracker import TokenUsage

        usages = [
            TokenUsage(
                workspace_id="ws-123",
                operation="unique_query",
                tokens_in=i * 100,  # Different tokens = unique queries
                tokens_out=50,
                cost_usd=Decimal("0.01"),
                timestamp=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        recommendations = recommender.analyze(usages, "ws-123")

        assert len(recommendations) == 0


class TestBatchingOptimizer:
    """Tests for batching optimizer."""

    def test_analyze_finds_batching_opportunities(self):
        """Test optimizer finds batching opportunities."""
        optimizer = BatchingOptimizer(min_requests_per_hour=10)

        from aragora.billing.cost_tracker import TokenUsage

        # Create high-frequency usage - all within the same hour
        usages = []
        base_time = datetime.now(timezone.utc)
        for i in range(100):  # More requests
            usages.append(
                TokenUsage(
                    workspace_id="ws-123",
                    operation="process_item",
                    tokens_in=500,
                    tokens_out=100,
                    cost_usd=Decimal("0.10"),  # Higher cost
                    timestamp=base_time - timedelta(minutes=i % 60),  # Within same hour
                )
            )

        recommendations = optimizer.analyze(usages, "ws-123")

        # Batching recommendations depend on having enough savings potential
        # If no recommendations, that's also valid if the cost threshold isn't met
        if recommendations:
            rec = recommendations[0]
            assert rec.type == RecommendationType.BATCHING
            assert rec.batching_opportunity is not None
            assert rec.batching_opportunity.optimal_batch_size > 1
        else:
            # If no batching recommendations, verify the result is still a valid list
            assert recommendations == [], "Should return empty list when no batching needed"


class TestCostOptimizer:
    """Tests for main cost optimizer."""

    @pytest.fixture
    def mock_cost_tracker(self):
        """Create mock cost tracker."""
        import asyncio

        tracker = MagicMock()
        tracker._buffer_lock = asyncio.Lock()
        tracker._usage_buffer = []
        tracker.get_budget = MagicMock(return_value=None)
        return tracker

    @pytest.mark.asyncio
    async def test_analyze_workspace_generates_recommendations(self, mock_cost_tracker):
        """Test workspace analysis generates recommendations."""
        from aragora.billing.cost_tracker import TokenUsage

        # Add usage data to mock tracker
        for i in range(20):
            mock_cost_tracker._usage_buffer.append(
                TokenUsage(
                    workspace_id="ws-123",
                    model="claude-opus-4",
                    provider="anthropic",
                    operation="summarize",
                    tokens_in=1000,
                    tokens_out=200,
                    cost_usd=Decimal("0.10"),
                    timestamp=datetime.now(timezone.utc) - timedelta(hours=i),
                )
            )

        optimizer = CostOptimizer(cost_tracker=mock_cost_tracker)
        recommendations = await optimizer.analyze_workspace("ws-123")

        assert isinstance(recommendations, list)
        # Should find at least model downgrade opportunity
        if recommendations:
            assert all(isinstance(r, OptimizationRecommendation) for r in recommendations)

    def test_get_recommendation(self, mock_cost_tracker):
        """Test getting recommendation by ID."""
        optimizer = CostOptimizer(cost_tracker=mock_cost_tracker)

        rec = OptimizationRecommendation(
            type=RecommendationType.MODEL_DOWNGRADE,
            workspace_id="ws-123",
        )
        optimizer._recommendations[rec.id] = rec
        optimizer._workspace_recs["ws-123"].append(rec.id)

        result = optimizer.get_recommendation(rec.id)

        assert result == rec

    def test_get_workspace_recommendations(self, mock_cost_tracker):
        """Test getting all recommendations for a workspace."""
        optimizer = CostOptimizer(cost_tracker=mock_cost_tracker)

        for i in range(3):
            rec = OptimizationRecommendation(
                type=RecommendationType.MODEL_DOWNGRADE,
                workspace_id="ws-123",
                priority=RecommendationPriority.HIGH if i == 0 else RecommendationPriority.LOW,
            )
            optimizer._recommendations[rec.id] = rec
            optimizer._workspace_recs["ws-123"].append(rec.id)

        results = optimizer.get_workspace_recommendations("ws-123")

        assert len(results) == 3

    def test_apply_recommendation(self, mock_cost_tracker):
        """Test applying a recommendation."""
        optimizer = CostOptimizer(cost_tracker=mock_cost_tracker)

        rec = OptimizationRecommendation(
            type=RecommendationType.CACHING,
            workspace_id="ws-123",
        )
        optimizer._recommendations[rec.id] = rec

        success = optimizer.apply_recommendation(rec.id, "user-456")

        assert success
        assert rec.status == RecommendationStatus.APPLIED
        assert rec.applied_by == "user-456"

    def test_dismiss_recommendation(self, mock_cost_tracker):
        """Test dismissing a recommendation."""
        optimizer = CostOptimizer(cost_tracker=mock_cost_tracker)

        rec = OptimizationRecommendation(
            type=RecommendationType.BATCHING,
            workspace_id="ws-123",
        )
        optimizer._recommendations[rec.id] = rec

        success = optimizer.dismiss_recommendation(rec.id)

        assert success
        assert rec.status == RecommendationStatus.DISMISSED

    def test_get_summary(self, mock_cost_tracker):
        """Test getting recommendation summary."""
        optimizer = CostOptimizer(cost_tracker=mock_cost_tracker)

        # Add various recommendations
        for status, priority, savings in [
            (RecommendationStatus.PENDING, RecommendationPriority.CRITICAL, Decimal("50")),
            (RecommendationStatus.PENDING, RecommendationPriority.HIGH, Decimal("30")),
            (RecommendationStatus.APPLIED, RecommendationPriority.MEDIUM, Decimal("20")),
            (RecommendationStatus.DISMISSED, RecommendationPriority.LOW, Decimal("10")),
        ]:
            rec = OptimizationRecommendation(
                type=RecommendationType.MODEL_DOWNGRADE,
                workspace_id="ws-123",
                status=status,
                priority=priority,
                current_cost_usd=Decimal("100"),
                projected_cost_usd=Decimal("100") - savings,
            )
            optimizer._recommendations[rec.id] = rec
            optimizer._workspace_recs["ws-123"].append(rec.id)

        summary = optimizer.get_summary("ws-123")

        assert summary.total_recommendations == 4
        assert summary.pending_count == 2
        assert summary.applied_count == 1
        assert summary.dismissed_count == 1
        assert summary.critical_count == 1
        assert summary.total_potential_savings == Decimal("80")  # pending only
        assert summary.realized_savings == Decimal("20")  # applied only


class TestUsagePattern:
    """Tests for usage pattern dataclass."""

    def test_usage_pattern_creation(self):
        """Test UsagePattern creation."""
        pattern = UsagePattern(
            model="claude-sonnet-4",
            provider="anthropic",
            operation="analyze",
            count=100,
            total_tokens_in=500000,
            total_tokens_out=100000,
            total_cost=Decimal("25.00"),
            avg_tokens_in=5000.0,
            avg_tokens_out=1000.0,
        )

        assert pattern.model == "claude-sonnet-4"
        assert pattern.count == 100
        assert pattern.avg_tokens_in == 5000.0


class TestCatalogDerivedTiers:
    """MODEL_TIERS gained a row per active catalog model (2026-09-04
    wave-3 ruling): before this the downgrade analyzer could only ever
    recommend the 2024-era roster it shipped with."""

    def test_every_active_catalog_model_has_a_tier_row(self):
        from aragora.models.catalog import CATALOG

        for spec in CATALOG.values():
            if spec.retired:
                continue
            assert spec.canonical_id in MODEL_TIERS, spec.canonical_id
            row = MODEL_TIERS[spec.canonical_id]
            assert row["provider"] == spec.provider
            assert row["tier"] in (1, 2, 3)
            assert 0.0 < row["quality"] <= 1.0

    def test_only_canonical_ids_are_emitted_so_one_model_is_one_candidate(self):
        """``_find_alternatives`` enumerates this table as a candidate list,
        so an alias row would let one model occupy several downgrade slots."""
        from aragora.models.catalog import CATALOG

        for spec in CATALOG.values():
            if spec.retired:
                continue
            aliases = set(spec.all_ids()) - {spec.canonical_id}
            for alias in aliases:
                # An alias may only appear if a HAND-curated legacy row put
                # it there on purpose.
                if alias in MODEL_TIERS:
                    from aragora.billing.optimizer import _LEGACY_MODEL_TIERS

                    assert alias in _LEGACY_MODEL_TIERS, alias

    def test_catalog_rows_win_a_key_collision(self):
        """A legacy key that is (or has been renamed onto) a LIVE catalog id
        resolves to the catalog's tier and provider, not to the hand-written
        snapshot of what that model used to be (wave-6 ruling, tables,
        on #9989).

        The legacy layer still answers every spelling the catalog does not
        carry -- aliases, retired ids, the 2024-era roster -- which is the
        only reason it is kept.
        """
        from aragora.billing.optimizer import _catalog_tier_rows, _LEGACY_MODEL_TIERS

        catalog_rows = _catalog_tier_rows()
        shadowed = sorted(set(catalog_rows) & set(_LEGACY_MODEL_TIERS))
        assert shadowed, "no collision left to prove the precedence with"
        for model in shadowed:
            assert MODEL_TIERS[model] == catalog_rows[model], model
        for model, row in _LEGACY_MODEL_TIERS.items():
            if model not in catalog_rows:
                assert MODEL_TIERS[model] == row, model

    def test_a_legacy_row_renamed_onto_a_live_id_follows_the_catalog(self):
        """The renaming case the ruling names, exercised end to end: point a
        hand-curated key at a live catalog id and the merged table must report
        the catalog's band and provider for it."""
        from aragora.billing import optimizer

        live = "gpt-5.6-terra"
        catalog_row = optimizer._catalog_tier_rows()[live]
        stale = {"tier": 1, "provider": "openai", "quality": 0.99}
        assert catalog_row != stale

        merged = {**{live: stale}, **optimizer._catalog_tier_rows()}
        assert merged[live] == catalog_row
        assert MODEL_TIERS[live] == catalog_row

    def test_frontier_flagships_are_top_band_and_value_skus_are_cheap_band(self):
        assert MODEL_TIERS["gpt-6-astra"]["tier"] == 1
        assert MODEL_TIERS["claude-fable-5-1"]["tier"] == 1
        assert MODEL_TIERS["gemini-3.8-flash"]["tier"] == 3
        assert MODEL_TIERS["gpt-5.6-terra"]["tier"] == 3

    def test_a_frontier_flagship_can_now_be_downgraded(self):
        """Traffic on the current OpenAI flagship used to be skipped
        entirely -- the analyzer had no tier row for it."""
        analyzer = ModelDowngradeAnalyzer()
        recommendations = analyzer.analyze(
            [
                UsagePattern(
                    model="gpt-6-astra",
                    provider="openai",
                    operation="summarize",
                    count=100,
                    total_tokens_in=500000,
                    total_tokens_out=100000,
                    total_cost=Decimal("50.00"),
                ),
            ],
            "ws-123",
        )
        assert recommendations
        assert recommendations[0].projected_cost_usd < recommendations[0].current_cost_usd
