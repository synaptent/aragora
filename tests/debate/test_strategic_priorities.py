"""Tests for the 6 strategic priorities implementation.

P1: Close the self-improvement flywheel (presets + post-debate defaults)
P2: Default-enable Trickster + Gauntlet
P3: Wire MetaLearner into debate orchestration
P4: Multi-provider 'diverse' preset
P5: RLM integration in codebase context
P6: Calibration → blockchain reputation chain
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.post_debate_coordinator import (
    DEFAULT_POST_DEBATE_CONFIG,
    PostDebateConfig,
    PostDebateCoordinator,
)


# ===========================================================================
# P1: Close the self-improvement flywheel
# ===========================================================================


class TestFlywheelPresets:
    """Verify knowledge flywheel flags in presets."""

    def test_sme_preset_has_knowledge_injection(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("sme")
        assert preset.get("enable_knowledge_injection") is True

    def test_sme_preset_has_adaptive_consensus(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("sme")
        assert preset.get("enable_adaptive_consensus") is True

    def test_sme_preset_has_meta_learning(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("sme")
        assert preset.get("enable_meta_learning") is True

    def test_sme_preset_has_post_debate_config(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("sme")
        assert "post_debate_config" in preset
        config = preset["post_debate_config"]
        assert isinstance(config, PostDebateConfig)
        assert config.auto_explain is True
        assert config.auto_persist_receipt is True
        assert config.auto_gauntlet_validate is True
        assert config.auto_push_calibration is True

    def test_enterprise_preset_has_calibration_push(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("enterprise")
        config = preset["post_debate_config"]
        assert config.auto_push_calibration is True

    def test_research_preset_has_flywheel_flags(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("research")
        assert preset.get("enable_knowledge_injection") is True
        assert preset.get("enable_adaptive_consensus") is True
        assert preset.get("enable_meta_learning") is True

    def test_research_preset_has_post_debate_config(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("research")
        assert "post_debate_config" in preset
        config = preset["post_debate_config"]
        assert config.auto_gauntlet_validate is True

    def test_all_presets_load_without_key_error(self):
        """Every preset should load via get_preset without errors."""
        from aragora.debate.presets import get_preset, list_presets

        for name in list_presets():
            preset = get_preset(name)
            assert isinstance(preset, dict), f"Preset '{name}' is not a dict"
            assert len(preset) > 0, f"Preset '{name}' is empty"


# ===========================================================================
# P2: Default-enable Trickster + Gauntlet
# ===========================================================================


class TestDefaultGauntlet:
    """Gauntlet validation is now default-on in DEFAULT_POST_DEBATE_CONFIG."""

    def test_default_config_gauntlet_enabled(self):
        assert DEFAULT_POST_DEBATE_CONFIG.auto_gauntlet_validate is True

    def test_default_config_calibration_push_enabled(self):
        assert DEFAULT_POST_DEBATE_CONFIG.auto_push_calibration is True

    def test_trickster_default_on_in_protocol(self):
        from aragora.debate.protocol import DebateProtocol

        protocol = DebateProtocol()
        assert protocol.enable_trickster is True


# ===========================================================================
# P3: Wire MetaLearner into debate orchestration
# ===========================================================================


class TestMetaLearnerPresets:
    """MetaLearner is now enabled in sme preset."""

    def test_sme_enables_meta_learning(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("sme")
        assert preset.get("enable_meta_learning") is True

    def test_enterprise_enables_meta_learning(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("enterprise")
        assert preset.get("enable_meta_learning") is True


# ===========================================================================
# P4: Multi-provider 'diverse' preset
# ===========================================================================


class TestDiversePreset:
    """New 'diverse' preset for multi-provider heterogeneous consensus."""

    def test_diverse_preset_exists(self):
        from aragora.debate.presets import list_presets

        assert "diverse" in list_presets()

    def test_diverse_preset_provider_diversity(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("diverse")
        assert preset.get("min_provider_diversity") == 3
        assert preset.get("prefer_diverse_providers") is True

    def test_diverse_preset_has_flywheel(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("diverse")
        assert preset.get("enable_knowledge_injection") is True
        assert preset.get("enable_adaptive_consensus") is True
        assert preset.get("enable_meta_learning") is True

    def test_diverse_preset_has_post_debate_config(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("diverse")
        assert "post_debate_config" in preset
        config = preset["post_debate_config"]
        assert isinstance(config, PostDebateConfig)
        assert config.auto_gauntlet_validate is True
        assert config.auto_push_calibration is True

    def test_diverse_preset_has_correct_keys(self):
        from aragora.debate.presets import get_preset

        preset = get_preset("diverse")
        assert preset.get("min_provider_diversity") == 3
        assert preset.get("prefer_diverse_providers") is True
        assert preset.get("enable_receipt_generation") is True

    def test_arena_config_provider_diversity_defaults(self):
        from aragora.debate.arena_config import ArenaConfig

        config = ArenaConfig()
        assert config.min_provider_diversity == 1
        assert config.prefer_diverse_providers is False


# ===========================================================================
# P5: RLM integration in codebase context
# ===========================================================================


class TestCodebaseRLMIntegration:
    """RLM deep exploration in CodebaseContextProvider."""

    def test_config_enable_rlm_default_false(self):
        from aragora.debate.codebase_context import CodebaseContextConfig

        config = CodebaseContextConfig()
        assert config.enable_rlm is False

    def test_config_enable_rlm_settable(self):
        from aragora.debate.codebase_context import CodebaseContextConfig

        config = CodebaseContextConfig(enable_rlm=True)
        assert config.enable_rlm is True

    @pytest.mark.asyncio
    async def test_rlm_context_appended_when_enabled(self):
        from aragora.debate.codebase_context import (
            CodebaseContextConfig,
            CodebaseContextProvider,
        )

        config = CodebaseContextConfig(
            codebase_path="/tmp",
            enable_rlm=True,
        )
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(return_value="# Codebase map")

        mock_rlm = MagicMock()
        mock_rlm.query = AsyncMock(return_value="RLM found 5 relevant modules")

        with (
            patch("aragora.rlm.context_builder.NomicContextBuilder", return_value=mock_builder),
            patch("aragora.rlm.bridge.AragoraRLM", return_value=mock_rlm),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = await provider.build_context("Refactor error handling")

        assert "Codebase map" in result
        assert "RLM Deep Analysis" in result
        assert "RLM found 5 relevant modules" in result

    @pytest.mark.asyncio
    async def test_rlm_fallback_on_import_error(self):
        from aragora.debate.codebase_context import (
            CodebaseContextConfig,
            CodebaseContextProvider,
        )

        config = CodebaseContextConfig(
            codebase_path="/tmp",
            enable_rlm=True,
        )
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(return_value="# Standard context")

        with (
            patch("aragora.rlm.context_builder.NomicContextBuilder", return_value=mock_builder),
            patch.dict("sys.modules", {"aragora.rlm.bridge": None}),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = await provider.build_context("Test task")

        assert "Standard context" in result
        # RLM section should NOT appear since import failed
        assert "RLM Deep Analysis" not in result

    @pytest.mark.asyncio
    async def test_rlm_not_called_when_disabled(self):
        from aragora.debate.codebase_context import (
            CodebaseContextConfig,
            CodebaseContextProvider,
        )

        config = CodebaseContextConfig(
            codebase_path="/tmp",
            enable_rlm=False,  # Disabled
        )
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(return_value="# Context")

        with (
            patch("aragora.rlm.context_builder.NomicContextBuilder", return_value=mock_builder),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = await provider.build_context("Test task")

        assert "RLM Deep Analysis" not in result


# ===========================================================================
# P6: Calibration → blockchain reputation chain
# ===========================================================================


class TestCalibrationPushStep:
    """Tests for PostDebateCoordinator._step_push_calibration."""

    def test_config_has_calibration_fields(self):
        config = PostDebateConfig()
        assert hasattr(config, "auto_push_calibration")
        assert hasattr(config, "calibration_min_predictions")
        assert config.auto_push_calibration is False
        assert config.calibration_min_predictions == 5

    def test_push_calibration_with_calibrated_agents(self):
        config = PostDebateConfig(auto_push_calibration=True, calibration_min_predictions=3)
        coordinator = PostDebateCoordinator(config=config)

        # Mock agent with calibration tracker
        agent = MagicMock()
        agent.name = "claude"
        tracker = MagicMock()
        tracker.get_calibration.return_value = {
            "brier_score": 0.2,
            "prediction_count": 10,
        }
        agent.calibration_tracker = tracker

        mock_adapter = MagicMock()
        with patch(
            "aragora.knowledge.mound.adapters.erc8004_adapter.ERC8004Adapter",
            return_value=mock_adapter,
        ):
            result = coordinator._step_push_calibration("d1", [agent])

        assert result is True
        mock_adapter.push_reputation.assert_called_once()
        call_kwargs = mock_adapter.push_reputation.call_args
        # Brier 0.2 → reputation 80
        assert call_kwargs.kwargs.get("score") == 80 or call_kwargs[1].get("score") == 80

    def test_push_calibration_skips_insufficient_predictions(self):
        config = PostDebateConfig(auto_push_calibration=True, calibration_min_predictions=10)
        coordinator = PostDebateCoordinator(config=config)

        agent = MagicMock()
        agent.name = "novice"
        tracker = MagicMock()
        tracker.get_calibration.return_value = {
            "brier_score": 0.5,
            "prediction_count": 3,  # Less than min 10
        }
        agent.calibration_tracker = tracker

        mock_adapter = MagicMock()
        with patch(
            "aragora.knowledge.mound.adapters.erc8004_adapter.ERC8004Adapter",
            return_value=mock_adapter,
        ):
            result = coordinator._step_push_calibration("d1", [agent])

        assert result is False
        mock_adapter.push_reputation.assert_not_called()

    def test_push_calibration_skips_agents_without_tracker(self):
        config = PostDebateConfig(auto_push_calibration=True)
        coordinator = PostDebateCoordinator(config=config)

        agent = MagicMock(spec=["name"])  # No calibration_tracker attr
        agent.name = "uncalibrated"

        mock_adapter = MagicMock()
        with patch(
            "aragora.knowledge.mound.adapters.erc8004_adapter.ERC8004Adapter",
            return_value=mock_adapter,
        ):
            result = coordinator._step_push_calibration("d1", [agent])

        assert result is False

    def test_push_calibration_graceful_on_import_error(self):
        config = PostDebateConfig(auto_push_calibration=True)
        coordinator = PostDebateCoordinator(config=config)

        agent = MagicMock()
        agent.name = "claude"
        agent.calibration_tracker = MagicMock()
        agent.calibration_tracker.get_calibration.return_value = {
            "brier_score": 0.1,
            "prediction_count": 20,
        }

        with patch.dict("sys.modules", {"aragora.knowledge.mound.adapters.erc8004_adapter": None}):
            result = coordinator._step_push_calibration("d1", [agent])

        assert result is False

    def test_brier_to_reputation_conversion(self):
        """Verify Brier score → reputation mapping."""
        # Brier 0.0 (perfect) → 100
        # Brier 0.5 → 50
        # Brier 1.0 (worst) → 0
        config = PostDebateConfig(auto_push_calibration=True, calibration_min_predictions=1)
        coordinator = PostDebateCoordinator(config=config)

        scores = [(0.0, 100), (0.2, 80), (0.5, 50), (1.0, 0)]
        for brier, expected_rep in scores:
            agent = MagicMock()
            agent.name = f"agent_{brier}"
            tracker = MagicMock()
            tracker.get_calibration.return_value = {
                "brier_score": brier,
                "prediction_count": 10,
            }
            agent.calibration_tracker = tracker

            mock_adapter = MagicMock()
            with patch(
                "aragora.knowledge.mound.adapters.erc8004_adapter.ERC8004Adapter",
                return_value=mock_adapter,
            ):
                coordinator._step_push_calibration("d1", [agent])

            call_kwargs = mock_adapter.push_reputation.call_args
            actual_score = call_kwargs.kwargs.get("score", call_kwargs[1].get("score"))
            assert actual_score == expected_rep, (
                f"Brier {brier} → expected {expected_rep}, got {actual_score}"
            )


class TestERC8004PushReputation:
    """Tests for ERC8004Adapter.push_reputation method."""

    def test_push_reputation_returns_true(self):
        from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter

        adapter = ERC8004Adapter()
        # Mock _emit_event since it may not exist in all contexts
        adapter._emit_event = MagicMock()

        result = adapter.push_reputation(
            agent_id="claude",
            score=85,
            domain="calibration",
            metadata={"debate_id": "d123"},
        )
        assert result is True
        adapter._emit_event.assert_called_once()
        args = adapter._emit_event.call_args
        assert args[0][0] == "reputation_pushed"

    def test_push_reputation_local_only_without_signer(self):
        from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter

        adapter = ERC8004Adapter(signer=None)
        adapter._emit_event = MagicMock()

        result = adapter.push_reputation(
            agent_id="gpt4",
            score=72,
            domain="calibration",
        )
        assert result is True
        # Should emit event but not try on-chain
        event_data = adapter._emit_event.call_args[0][1]
        assert event_data["status"] == "recorded"


# ===========================================================================
# Integration: full pipeline test
# ===========================================================================


class TestFlywheelIntegration:
    """Integration test: full pipeline with all 6 priorities active."""

    def test_full_flywheel_protocol(self):
        """DebateProtocol.with_full_flywheel enables all flywheel features."""
        from aragora.debate.protocol import DebateProtocol

        protocol = DebateProtocol.with_full_flywheel()
        assert protocol.enable_adaptive_consensus is True
        assert protocol.enable_synthesis is True
        assert protocol.enable_knowledge_injection is True
        assert protocol.enable_trickster is True
        assert protocol.auto_create_plan is True

    def test_sme_preset_description_updated(self):
        from aragora.debate.presets import get_preset_info

        info = get_preset_info("sme")
        # Should mention flywheel or meta-learning
        assert "flywheel" in info["description"].lower() or "meta" in info["description"].lower()

    def test_diverse_preset_description(self):
        from aragora.debate.presets import get_preset_info

        info = get_preset_info("diverse")
        assert (
            "multi-provider" in info["description"].lower()
            or "diverse" in info["description"].lower()
        )
