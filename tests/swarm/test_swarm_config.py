"""Tests for aragora.swarm.config — public API coverage."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from aragora.swarm.config import (
    AutonomyLevel,
    InterrogatorConfig,
    SwarmCommanderConfig,
    USER_PROFILE_PROMPTS,
    UserProfile,
    merge_configs,
)


# ---------------------------------------------------------------------------
# UserProfile enum
# ---------------------------------------------------------------------------


class TestUserProfile:
    """Tests for the UserProfile enum."""

    def test_all_members_are_strings(self):
        for member in UserProfile:
            assert isinstance(member.value, str)

    def test_expected_members_exist(self):
        assert UserProfile.CEO.value == "ceo"
        assert UserProfile.CTO.value == "cto"
        assert UserProfile.DEVELOPER.value == "developer"
        assert UserProfile.POWER_USER.value == "power_user"

    def test_inherits_str(self):
        # UserProfile(str, Enum) means each member IS a str
        assert UserProfile.CEO == "ceo"

    def test_construction_from_string(self):
        assert UserProfile("developer") is UserProfile.DEVELOPER

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            UserProfile("unknown_profile")


# ---------------------------------------------------------------------------
# AutonomyLevel enum
# ---------------------------------------------------------------------------


class TestAutonomyLevel:
    """Tests for the AutonomyLevel enum."""

    def test_all_members_are_strings(self):
        for member in AutonomyLevel:
            assert isinstance(member.value, str)

    def test_expected_members_exist(self):
        assert AutonomyLevel.FULL_AUTO.value == "full_auto"
        assert AutonomyLevel.PROPOSE_APPROVE.value == "propose"
        assert AutonomyLevel.HUMAN_GUIDED.value == "guided"
        assert AutonomyLevel.METRICS_DRIVEN.value == "metrics"

    def test_inherits_str(self):
        assert AutonomyLevel.FULL_AUTO == "full_auto"

    def test_construction_from_string(self):
        assert AutonomyLevel("guided") is AutonomyLevel.HUMAN_GUIDED

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            AutonomyLevel("not_a_level")


# ---------------------------------------------------------------------------
# USER_PROFILE_PROMPTS constant
# ---------------------------------------------------------------------------


class TestUserProfilePrompts:
    """Tests for the USER_PROFILE_PROMPTS mapping."""

    def test_all_profiles_have_prompts(self):
        for profile in UserProfile:
            assert profile in USER_PROFILE_PROMPTS
            assert isinstance(USER_PROFILE_PROMPTS[profile], str)
            assert len(USER_PROFILE_PROMPTS[profile]) > 0

    def test_all_prompts_contain_spec_ready(self):
        for profile, prompt in USER_PROFILE_PROMPTS.items():
            assert "SPEC_READY" in prompt, f"SPEC_READY missing from {profile} prompt"

    def test_prompts_are_distinct(self):
        prompt_texts = list(USER_PROFILE_PROMPTS.values())
        assert len(prompt_texts) == len(set(prompt_texts))

    def test_prompts_mention_aragora(self):
        for profile, prompt in USER_PROFILE_PROMPTS.items():
            assert "Aragora" in prompt, f"Aragora missing from {profile} prompt"


# ---------------------------------------------------------------------------
# InterrogatorConfig
# ---------------------------------------------------------------------------


class TestInterrogatorConfigDefaults:
    """Tests for InterrogatorConfig default values."""

    def test_default_max_turns(self):
        cfg = InterrogatorConfig()
        assert cfg.max_turns == 8

    def test_default_model(self):
        cfg = InterrogatorConfig()
        assert cfg.model == "claude-opus-5"

    def test_default_fallback_flag(self):
        cfg = InterrogatorConfig()
        assert cfg.fallback_to_fixed_questions is True

    def test_default_user_profile(self):
        cfg = InterrogatorConfig()
        assert cfg.user_profile is UserProfile.CEO

    def test_default_system_prompt_set_from_profile(self):
        cfg = InterrogatorConfig()
        assert cfg.system_prompt == USER_PROFILE_PROMPTS[UserProfile.CEO]

    def test_explicit_system_prompt_is_preserved(self):
        cfg = InterrogatorConfig(system_prompt="Custom prompt")
        assert cfg.system_prompt == "Custom prompt"

    def test_empty_system_prompt_falls_back_to_profile(self):
        cfg = InterrogatorConfig(system_prompt="")
        assert cfg.system_prompt == USER_PROFILE_PROMPTS[UserProfile.CEO]


class TestInterrogatorConfigProfiles:
    """Tests for profile-driven prompt selection."""

    @pytest.mark.parametrize("profile", list(UserProfile))
    def test_profile_sets_correct_system_prompt(self, profile: UserProfile):
        cfg = InterrogatorConfig(user_profile=profile)
        assert cfg.system_prompt == USER_PROFILE_PROMPTS[profile]

    def test_profile_as_string_is_coerced(self):
        cfg = InterrogatorConfig(user_profile="developer")
        assert cfg.user_profile is UserProfile.DEVELOPER
        assert cfg.system_prompt == USER_PROFILE_PROMPTS[UserProfile.DEVELOPER]

    def test_profile_enum_member_is_accepted(self):
        cfg = InterrogatorConfig(user_profile=UserProfile.CTO)
        assert cfg.user_profile is UserProfile.CTO


class TestInterrogatorConfigMerge:
    """Tests for InterrogatorConfig.merge and with_overrides."""

    def test_merge_returns_new_instance(self):
        cfg = InterrogatorConfig()
        new_cfg = cfg.merge({"max_turns": 12})
        assert new_cfg is not cfg

    def test_merge_applies_override(self):
        cfg = InterrogatorConfig()
        new_cfg = cfg.merge({"max_turns": 12})
        assert new_cfg.max_turns == 12
        # Original untouched
        assert cfg.max_turns == 8

    def test_merge_preserves_non_overridden_fields(self):
        cfg = InterrogatorConfig(user_profile=UserProfile.CTO)
        new_cfg = cfg.merge({"max_turns": 4})
        assert new_cfg.user_profile is UserProfile.CTO
        assert new_cfg.model == cfg.model

    def test_merge_empty_dict_is_no_op(self):
        cfg = InterrogatorConfig()
        new_cfg = cfg.merge({})
        assert new_cfg.max_turns == cfg.max_turns
        assert new_cfg.model == cfg.model
        assert new_cfg.user_profile == cfg.user_profile

    def test_merge_multiple_fields(self):
        cfg = InterrogatorConfig()
        new_cfg = cfg.merge({"max_turns": 3, "model": "gpt-4o"})
        assert new_cfg.max_turns == 3
        assert new_cfg.model == "gpt-4o"

    def test_merge_custom_system_prompt(self):
        cfg = InterrogatorConfig()
        new_cfg = cfg.merge({"system_prompt": "Be terse."})
        assert new_cfg.system_prompt == "Be terse."

    def test_with_overrides_equivalent_to_merge(self):
        cfg = InterrogatorConfig()
        via_merge = cfg.merge({"max_turns": 5})
        via_overrides = cfg.with_overrides(max_turns=5)
        assert via_merge.max_turns == via_overrides.max_turns
        assert via_merge.model == via_overrides.model

    def test_merge_profile_string_coerced(self):
        cfg = InterrogatorConfig()
        new_cfg = cfg.merge({"user_profile": "developer"})
        assert new_cfg.user_profile is UserProfile.DEVELOPER


# ---------------------------------------------------------------------------
# SwarmCommanderConfig
# ---------------------------------------------------------------------------


class TestSwarmCommanderConfigDefaults:
    """Tests for SwarmCommanderConfig default values."""

    def test_has_default_interrogator(self):
        cfg = SwarmCommanderConfig()
        assert isinstance(cfg.interrogator, InterrogatorConfig)

    def test_default_budget_limit(self):
        cfg = SwarmCommanderConfig()
        assert cfg.budget_limit_usd == 50.0

    def test_default_require_approval(self):
        cfg = SwarmCommanderConfig()
        assert cfg.require_approval is False

    def test_default_use_worktree_isolation(self):
        cfg = SwarmCommanderConfig()
        assert cfg.use_worktree_isolation is True

    def test_default_enable_meta_planning(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_meta_planning is True

    def test_default_enable_gauntlet_validation(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_gauntlet_validation is True

    def test_default_enable_mode_enforcement(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_mode_enforcement is True

    def test_default_generate_receipts(self):
        cfg = SwarmCommanderConfig()
        assert cfg.generate_receipts is True

    def test_default_spectate_stream(self):
        cfg = SwarmCommanderConfig()
        assert cfg.spectate_stream is True

    def test_default_max_parallel_tasks(self):
        cfg = SwarmCommanderConfig()
        assert cfg.max_parallel_tasks == 20

    def test_default_max_cycles(self):
        cfg = SwarmCommanderConfig()
        assert cfg.max_cycles == 5

    def test_default_max_subtasks(self):
        cfg = SwarmCommanderConfig()
        assert cfg.max_subtasks == 15

    def test_default_max_parallel_branches(self):
        cfg = SwarmCommanderConfig()
        assert cfg.max_parallel_branches == 16

    def test_default_iterative_mode(self):
        cfg = SwarmCommanderConfig()
        assert cfg.iterative_mode is True

    def test_default_user_profile(self):
        cfg = SwarmCommanderConfig()
        assert cfg.user_profile is UserProfile.CEO

    def test_default_enable_research_pipeline(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_research_pipeline is True

    def test_default_obsidian_vault_path_is_none(self):
        cfg = SwarmCommanderConfig()
        assert cfg.obsidian_vault_path is None

    def test_default_obsidian_write_receipts(self):
        cfg = SwarmCommanderConfig()
        assert cfg.obsidian_write_receipts is True

    def test_default_enable_epistemic_scoring(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_epistemic_scoring is True

    def test_default_enable_calibration(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_calibration is True

    def test_default_enable_hollow_consensus_detection(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_hollow_consensus_detection is True

    def test_default_autonomy_level(self):
        cfg = SwarmCommanderConfig()
        assert cfg.autonomy_level is AutonomyLevel.PROPOSE_APPROVE

    def test_default_enable_cross_cycle_learning(self):
        cfg = SwarmCommanderConfig()
        assert cfg.enable_cross_cycle_learning is True

    def test_budget_limit_can_be_none(self):
        cfg = SwarmCommanderConfig(budget_limit_usd=None)
        assert cfg.budget_limit_usd is None

    def test_obsidian_vault_path_can_be_set(self):
        cfg = SwarmCommanderConfig(obsidian_vault_path="/home/user/vault")
        assert cfg.obsidian_vault_path == "/home/user/vault"


class TestSwarmCommanderConfigPostInit:
    """Tests for SwarmCommanderConfig.__post_init__ coercion and sync logic."""

    def test_user_profile_string_is_coerced(self):
        cfg = SwarmCommanderConfig(user_profile="developer")
        assert cfg.user_profile is UserProfile.DEVELOPER

    def test_autonomy_level_string_is_coerced(self):
        cfg = SwarmCommanderConfig(autonomy_level="full_auto")
        assert cfg.autonomy_level is AutonomyLevel.FULL_AUTO

    def test_interrogator_profile_synced_to_commander_profile(self):
        """When user_profile differs from interrogator default, interrogator is synced."""
        cfg = SwarmCommanderConfig(user_profile=UserProfile.DEVELOPER)
        assert cfg.interrogator.user_profile is UserProfile.DEVELOPER

    def test_interrogator_prompt_not_changed_when_default_prompt_already_set(self):
        # The default InterrogatorConfig.__post_init__ fills system_prompt with the
        # CEO prompt before SwarmCommanderConfig.__post_init__ runs, so
        # has_custom_prompt is True and the prompt is NOT overwritten during sync.
        cfg = SwarmCommanderConfig(user_profile=UserProfile.DEVELOPER)
        # Only the profile attribute is synced; the already-set prompt stays as-is.
        assert cfg.interrogator.user_profile is UserProfile.DEVELOPER
        assert cfg.interrogator.system_prompt == USER_PROFILE_PROMPTS[UserProfile.CEO]

    def test_interrogator_prompt_updated_when_blank_prompt_passed(self):
        # Explicitly passing system_prompt="" causes __post_init__ to set the CEO
        # prompt immediately; when the commander later syncs to DEVELOPER the
        # has_custom_prompt check is True (same situation), so the prompt stays CEO.
        # To get a fresh prompt for DEVELOPER, construct the interrogator with
        # user_profile=DEVELOPER so its own __post_init__ picks the right prompt.
        interrogator = InterrogatorConfig(user_profile=UserProfile.DEVELOPER, system_prompt="")
        cfg = SwarmCommanderConfig(user_profile=UserProfile.DEVELOPER, interrogator=interrogator)
        assert cfg.interrogator.system_prompt == USER_PROFILE_PROMPTS[UserProfile.DEVELOPER]

    def test_custom_interrogator_prompt_preserved_during_profile_sync(self):
        """A pre-set custom prompt on the interrogator must survive profile sync."""
        interrogator = InterrogatorConfig(system_prompt="My custom prompt")
        cfg = SwarmCommanderConfig(
            user_profile=UserProfile.CTO,
            interrogator=interrogator,
        )
        # The sync path sees has_custom_prompt=True and must not overwrite it.
        assert cfg.interrogator.system_prompt == "My custom prompt"

    def test_matching_profiles_no_sync_needed(self):
        """When profiles already match, no extra sync is needed."""
        cfg = SwarmCommanderConfig(user_profile=UserProfile.CEO)
        assert cfg.interrogator.user_profile is UserProfile.CEO

    def test_interrogator_profile_as_string_coerced(self):
        interrogator = InterrogatorConfig(user_profile="cto")
        cfg = SwarmCommanderConfig(interrogator=interrogator)
        # Commander defaults to CEO; interrogator is CTO → gets synced to CEO
        assert cfg.interrogator.user_profile is UserProfile.CEO

    def test_explicit_interrogator_profile_matching_commander_no_sync(self):
        interrogator = InterrogatorConfig(user_profile=UserProfile.DEVELOPER)
        cfg = SwarmCommanderConfig(
            user_profile=UserProfile.DEVELOPER,
            interrogator=interrogator,
        )
        assert cfg.interrogator.user_profile is UserProfile.DEVELOPER


class TestSwarmCommanderConfigMerge:
    """Tests for SwarmCommanderConfig.merge and with_overrides."""

    def test_merge_returns_new_instance(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"max_cycles": 10})
        assert new_cfg is not cfg

    def test_merge_scalar_override(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"max_cycles": 10})
        assert new_cfg.max_cycles == 10
        assert cfg.max_cycles == 5  # Original unchanged

    def test_merge_preserves_non_overridden_fields(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"max_cycles": 10})
        assert new_cfg.budget_limit_usd == cfg.budget_limit_usd
        assert new_cfg.user_profile == cfg.user_profile

    def test_merge_empty_dict_is_no_op(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({})
        for f in fields(cfg):
            assert getattr(new_cfg, f.name) == getattr(cfg, f.name)

    def test_merge_with_interrogator_dict(self):
        """Nested dict overrides for interrogator are merged recursively."""
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"interrogator": {"max_turns": 20}})
        assert new_cfg.interrogator.max_turns == 20
        assert new_cfg.interrogator.model == cfg.interrogator.model

    def test_merge_with_interrogator_instance(self):
        """Passing an InterrogatorConfig instance replaces the nested config."""
        custom_interrogator = InterrogatorConfig(max_turns=3)
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"interrogator": custom_interrogator})
        assert new_cfg.interrogator is custom_interrogator

    def test_merge_interrogator_dict_preserves_other_interrogator_fields(self):
        cfg = SwarmCommanderConfig(interrogator=InterrogatorConfig(max_turns=6, model="gpt-4o"))
        new_cfg = cfg.merge({"interrogator": {"max_turns": 12}})
        assert new_cfg.interrogator.max_turns == 12
        assert new_cfg.interrogator.model == "gpt-4o"

    def test_merge_budget_none(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"budget_limit_usd": None})
        assert new_cfg.budget_limit_usd is None

    def test_merge_boolean_flip(self):
        cfg = SwarmCommanderConfig()
        assert cfg.require_approval is False
        new_cfg = cfg.merge({"require_approval": True})
        assert new_cfg.require_approval is True

    def test_with_overrides_equivalent_to_merge(self):
        cfg = SwarmCommanderConfig()
        via_merge = cfg.merge({"max_subtasks": 7})
        via_overrides = cfg.with_overrides(max_subtasks=7)
        assert via_merge.max_subtasks == via_overrides.max_subtasks

    def test_merge_user_profile_string_coerced(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"user_profile": "cto"})
        assert new_cfg.user_profile is UserProfile.CTO

    def test_merge_autonomy_level_string_coerced(self):
        cfg = SwarmCommanderConfig()
        new_cfg = cfg.merge({"autonomy_level": "full_auto"})
        assert new_cfg.autonomy_level is AutonomyLevel.FULL_AUTO

    def test_merge_mutates_source_dict_by_popping_interrogator(self):
        """merge() calls overrides.pop('interrogator') directly, so the key is
        removed from the caller's dict — document this as known behavior."""
        cfg = SwarmCommanderConfig()
        overrides: dict[str, Any] = {"interrogator": {"max_turns": 5}, "max_cycles": 2}
        _ = cfg.merge(overrides)
        # merge() pops 'interrogator' in-place; the key is gone after the call.
        assert "interrogator" not in overrides
        # Non-interrogator keys are left in place.
        assert "max_cycles" in overrides


# ---------------------------------------------------------------------------
# merge_configs helper
# ---------------------------------------------------------------------------


class TestMergeConfigs:
    """Tests for the module-level merge_configs() helper."""

    def test_no_layers_returns_equivalent_config(self):
        base = SwarmCommanderConfig()
        result = merge_configs(base)
        assert result.max_cycles == base.max_cycles
        assert result.budget_limit_usd == base.budget_limit_usd

    def test_single_layer_applied(self):
        base = SwarmCommanderConfig()
        result = merge_configs(base, {"max_cycles": 99})
        assert result.max_cycles == 99

    def test_multiple_layers_applied_left_to_right(self):
        base = SwarmCommanderConfig()
        result = merge_configs(
            base,
            {"max_cycles": 3},
            {"max_cycles": 7},
        )
        # Last layer wins
        assert result.max_cycles == 7

    def test_layers_can_target_different_fields(self):
        base = SwarmCommanderConfig()
        result = merge_configs(
            base,
            {"max_cycles": 3},
            {"budget_limit_usd": 100.0},
        )
        assert result.max_cycles == 3
        assert result.budget_limit_usd == 100.0

    def test_base_not_mutated(self):
        base = SwarmCommanderConfig()
        original_max_cycles = base.max_cycles
        _ = merge_configs(base, {"max_cycles": 99})
        assert base.max_cycles == original_max_cycles

    def test_layers_are_not_mutated(self):
        base = SwarmCommanderConfig()
        layer: dict[str, Any] = {"interrogator": {"max_turns": 5}}
        _ = merge_configs(base, layer)
        # Layer still has 'interrogator' key intact
        assert "interrogator" in layer

    def test_interrogator_dict_merged_through_layers(self):
        base = SwarmCommanderConfig()
        result = merge_configs(base, {"interrogator": {"max_turns": 15}})
        assert result.interrogator.max_turns == 15

    def test_empty_layers_are_no_ops(self):
        base = SwarmCommanderConfig(max_cycles=2)
        result = merge_configs(base, {}, {}, {})
        assert result.max_cycles == 2

    def test_returns_swarm_commander_config(self):
        base = SwarmCommanderConfig()
        result = merge_configs(base, {"max_cycles": 1})
        assert isinstance(result, SwarmCommanderConfig)
