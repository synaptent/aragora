"""Tests for epistemic question-persona modes (#8815)."""

from __future__ import annotations

from aragora.modes.base import ModeRegistry
from aragora.modes.tool_groups import ToolGroup


def test_question_personas_register_with_read_debate_permissions() -> None:
    ModeRegistry.clear()
    from aragora.modes.builtin import register_all_builtins

    register_all_builtins()

    for name in ("outsider", "falsifier", "deleter", "assumption_surfacer"):
        mode = ModeRegistry.get(name)
        assert mode is not None
        assert ToolGroup.READ in mode.tool_groups
        assert ToolGroup.BROWSER in mode.tool_groups
        assert ToolGroup.DEBATE in mode.tool_groups
        assert ToolGroup.EDIT not in mode.tool_groups
        assert ToolGroup.COMMAND not in mode.tool_groups


def test_question_personas_have_distinct_nonduplicative_prompts() -> None:
    ModeRegistry.clear()
    from aragora.modes.builtin import register_all_builtins

    register_all_builtins()
    prompts = {
        name: ModeRegistry.get(name).get_system_prompt()
        for name in ("outsider", "falsifier", "deleter", "assumption_surfacer")
    }

    assert "outside" in prompts["outsider"].lower()
    assert "falsif" in prompts["falsifier"].lower()
    assert "remove" in prompts["deleter"].lower()
    assert "assumption" in prompts["assumption_surfacer"].lower()
    assert len(set(prompts.values())) == 4
