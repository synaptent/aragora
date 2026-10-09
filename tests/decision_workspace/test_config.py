"""Workspace settings: offered agents and intake limits fail closed."""

from __future__ import annotations

from aragora.decision_workspace.config import (
    DEFAULT_MAX_DOCUMENTS,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_PASTED_CHARS,
    ENV_AGENTS,
    agent_options,
    workspace_limits,
)

MISSION_AGENTS = (
    "openai-api|gpt-5.5,openai-api|claude-haiku-4-5-20251001,openai-api|gemini-3-flash,grok"
)


def test_offered_agents_are_exactly_the_configured_entries_in_order():
    options = agent_options({ENV_AGENTS: MISSION_AGENTS})
    assert options.configured
    assert options.error is None
    assert options.specs == (
        "openai-api|gpt-5.5",
        "openai-api|claude-haiku-4-5-20251001",
        "openai-api|gemini-3-flash",
        "grok",
    )
    assert options.agents[0].to_dict() == {
        "spec": "openai-api|gpt-5.5",
        "provider": "openai-api",
        "model": "gpt-5.5",
    }
    assert options.agents[3].to_dict() == {"spec": "grok", "provider": "grok", "model": None}


def test_entries_are_trimmed_and_blank_or_repeated_entries_dropped():
    options = agent_options({ENV_AGENTS: " grok , ,openai-api|gpt-5.5,grok,, "})
    assert options.specs == ("grok", "openai-api|gpt-5.5")


def test_empty_or_unset_configuration_offers_nothing_and_names_the_variable():
    for env in ({}, {ENV_AGENTS: ""}, {ENV_AGENTS: " , ,"}):
        options = agent_options(env)
        assert not options.configured
        assert options.agents == ()
        assert options.error is not None
        assert ENV_AGENTS in options.error


def test_one_invalid_entry_disables_the_whole_list():
    options = agent_options({ENV_AGENTS: "grok,not-a-real-provider|x"})
    assert not options.configured
    assert options.agents == ()
    assert "not-a-real-provider|x" in (options.error or "")
    assert ENV_AGENTS in (options.error or "")


def test_limits_default_to_the_architecture_values():
    limits = workspace_limits({})
    assert limits.max_documents == DEFAULT_MAX_DOCUMENTS == 10
    assert limits.max_file_bytes == DEFAULT_MAX_FILE_BYTES == 1048576
    assert limits.max_pasted_chars == DEFAULT_MAX_PASTED_CHARS == 204800


def test_limits_read_positive_integers():
    limits = workspace_limits(
        {
            "ARAGORA_WORKSPACE_MAX_DOCUMENTS": "3",
            "ARAGORA_WORKSPACE_MAX_FILE_BYTES": " 2048 ",
            "ARAGORA_WORKSPACE_MAX_PASTED_CHARS": "100",
        }
    )
    assert (limits.max_documents, limits.max_file_bytes, limits.max_pasted_chars) == (3, 2048, 100)


def test_unreadable_limits_fall_back_to_the_default_not_to_unlimited():
    for bad in ("abc", "0", "-5", "1.5"):
        limits = workspace_limits(
            {
                "ARAGORA_WORKSPACE_MAX_DOCUMENTS": bad,
                "ARAGORA_WORKSPACE_MAX_FILE_BYTES": bad,
                "ARAGORA_WORKSPACE_MAX_PASTED_CHARS": bad,
            }
        )
        assert limits.max_documents == DEFAULT_MAX_DOCUMENTS
        assert limits.max_file_bytes == DEFAULT_MAX_FILE_BYTES
        assert limits.max_pasted_chars == DEFAULT_MAX_PASTED_CHARS
