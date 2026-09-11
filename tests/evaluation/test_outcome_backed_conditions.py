from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from aragora.evaluation.outcome_backed_conditions import (
    ARAGORA_TEAM,
    CLAUDE_SINGLE,
    CONDITION_ROSTER_SCHEMA,
    FROZEN_CONDITION_ROSTER,
    GEMINI_SINGLE,
    OPENAI_SINGLE,
    ConditionRosterError,
    ConditionSpec,
    preflight_condition_roster,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, canonical_json_sha256


MODULE_PATH = Path("aragora/evaluation/outcome_backed_conditions.py")


def _replace_condition(condition_id: str, replacement: ConditionSpec) -> tuple[ConditionSpec, ...]:
    return tuple(
        replacement if condition.condition_id == condition_id else condition
        for condition in FROZEN_CONDITION_ROSTER
    )


def test_frozen_roster_preflight_is_stable_and_content_bound() -> None:
    first = preflight_condition_roster()
    second = preflight_condition_roster()

    assert first == second
    assert [condition.condition_id for condition in first.conditions] == [
        CLAUDE_SINGLE,
        OPENAI_SINGLE,
        GEMINI_SINGLE,
        ARAGORA_TEAM,
    ]
    assert [member.family for member in first.conditions[-1].members] == [
        "claude",
        "openai",
        "gemini",
    ]
    assert {member.transport for member in first.conditions[-1].members} == {"vibeproxy-required"}
    assert {member.protocol for member in first.conditions[-1].members} == {"openai-chat"}
    assert [member.catalog_owner for member in first.conditions[-1].members] == [
        "anthropic",
        "openai",
        "antigravity",
    ]
    assert first.conditions[2].members[0].requested_model == "gemini-3.1-pro-low"
    assert all(
        member.requested_model == member.expected_resolved_model
        for member in first.conditions[-1].members
    )
    payload = first.to_dict()
    digest = payload.pop("roster_sha256")
    assert payload["schema_version"] == CONDITION_ROSTER_SCHEMA
    assert payload["benchmark_id"] == BENCHMARK_ID
    assert digest == canonical_json_sha256(payload)


@pytest.mark.parametrize("remove_index", range(4))
def test_preflight_rejects_every_missing_condition(remove_index: int) -> None:
    roster = FROZEN_CONDITION_ROSTER[:remove_index] + FROZEN_CONDITION_ROSTER[remove_index + 1 :]

    with pytest.raises(ConditionRosterError, match="missing="):
        preflight_condition_roster(roster)


def test_preflight_rejects_unknown_and_duplicate_conditions() -> None:
    unknown = replace(FROZEN_CONDITION_ROSTER[0], condition_id="other-single")
    with pytest.raises(ConditionRosterError, match="unknown="):
        preflight_condition_roster(_replace_condition(CLAUDE_SINGLE, unknown))

    with pytest.raises(ConditionRosterError, match="duplicate condition IDs"):
        preflight_condition_roster(FROZEN_CONDITION_ROSTER[:-1] + (FROZEN_CONDITION_ROSTER[0],))


def test_preflight_rejects_condition_reordering() -> None:
    roster = (FROZEN_CONDITION_ROSTER[1], FROZEN_CONDITION_ROSTER[0]) + FROZEN_CONDITION_ROSTER[2:]

    with pytest.raises(ConditionRosterError, match="condition order"):
        preflight_condition_roster(roster)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_model", "claude-opus-latest"),
        ("expected_resolved_model", "claude-opus-4-8"),
        ("transport", "direct-api"),
        ("protocol", "anthropic-messages"),
        ("catalog_owner", "other"),
        ("identity_attestation", "command-line-only"),
        ("allow_fallback", True),
    ],
)
def test_preflight_rejects_alias_substitution_transport_and_fallback(
    field: str, value: object
) -> None:
    condition = FROZEN_CONDITION_ROSTER[0]
    changed_member = replace(condition.members[0], **{field: value})
    changed = replace(condition, members=(changed_member,))

    with pytest.raises(ConditionRosterError, match="exact frozen"):
        preflight_condition_roster(_replace_condition(CLAUDE_SINGLE, changed))


def test_preflight_rejects_unknown_or_duplicate_team_family() -> None:
    team = FROZEN_CONDITION_ROSTER[-1]
    unknown = replace(team.members[-1], family="other")
    with pytest.raises(ConditionRosterError, match="ordered families"):
        preflight_condition_roster(
            _replace_condition(ARAGORA_TEAM, replace(team, members=team.members[:-1] + (unknown,)))
        )

    duplicate = replace(team, members=(team.members[0], team.members[1], team.members[0]))
    with pytest.raises(ConditionRosterError, match="duplicate model family"):
        preflight_condition_roster(_replace_condition(ARAGORA_TEAM, duplicate))


def test_condition_module_has_no_provider_or_client_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    assert imports.isdisjoint({"anthropic", "google", "openai", "httpx", "requests"})
