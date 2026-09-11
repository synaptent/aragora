from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from aragora.evaluation.outcome_backed_conditions import (
    ARAGORA_TEAM,
    CLAUDE_SINGLE,
    GEMINI_SINGLE,
    OPENAI_SINGLE,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, canonical_json_sha256
from aragora.evaluation.outcome_backed_packets import PACKET_SET_SCHEMA, SOURCE_PACKET_SCHEMA
from aragora.evaluation.outcome_backed_prompt import (
    PROMPT_SCHEMA,
    OutcomeBackedPromptError,
    render_outcome_backed_prompt,
)


def _packet(*, source_content: str = "Evidence available before the cutoff.") -> dict[str, object]:
    content_sha256 = hashlib.sha256(source_content.encode()).hexdigest()
    packet: dict[str, object] = {
        "schema_version": SOURCE_PACKET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "case": {
            "case_id": "se-dev-example",
            "domain": "software_engineering",
            "split": "development",
            "title": "Example decision",
            "decision_prompt": "Choose the safer migration plan.",
            "forecast_question": "What is the probability option A is outcome-aligned?",
            "forecast_option_id": "option-a",
            "options": [
                {"option_id": "option-a", "label": "A", "description": "Migrate now."},
                {"option_id": "option-b", "label": "B", "description": "Defer migration."},
            ],
            "information_cutoff": "2025-01-02T00:00:00Z",
        },
        "sources": [
            {
                "source_id": "source-1",
                "title": "Frozen source",
                "url": "https://www.sec.gov/source",
                "published_at": "2025-01-01T00:00:00Z",
                "content_sha256": content_sha256,
                "media_type": "text/plain; charset=utf-8",
                "content_encoding": "utf-8",
                "content": source_content,
            }
        ],
    }
    packet["packet_sha256"] = canonical_json_sha256(packet)
    return packet


def _packet_set(packet: dict[str, object]) -> dict[str, object]:
    assert isinstance(packet["case"], dict)
    case_id = str(packet["case"]["case_id"])
    entries = [
        {
            "case_id": case_id if index == 0 else f"zz-dev-{index:02d}",
            "packet_sha256": packet["packet_sha256"] if index == 0 else f"{index:064x}",
        }
        for index in range(16)
    ]
    manifest: dict[str, object] = {
        "schema_version": PACKET_SET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "split": "development",
        "packet_count": 16,
        "source_count": 16,
        "packets": sorted(entries, key=lambda item: str(item["case_id"])),
    }
    manifest["packet_set_sha256"] = canonical_json_sha256(manifest)
    return manifest


def test_rendering_is_byte_deterministic_and_self_hashing() -> None:
    packet = _packet()
    packet_set = _packet_set(packet)

    first = render_outcome_backed_prompt(packet, packet_set=packet_set, condition_id=CLAUDE_SINGLE)
    reordered = dict(reversed(list(packet.items())))
    second = render_outcome_backed_prompt(
        reordered,
        packet_set=dict(reversed(list(packet_set.items()))),
        condition_id=CLAUDE_SINGLE,
    )

    assert first == second
    assert first.prompt_text.endswith("\n")
    assert first.prompt_sha256 == hashlib.sha256(first.prompt_text.encode()).hexdigest()
    assert first.to_dict()["schema_version"] == PROMPT_SCHEMA


def test_non_ascii_packet_embedding_matches_digest_canonicalization() -> None:
    packet = _packet(
        source_content="The claimant was \u201cliable\u201d \u2014 exposure was \u20ac2m."
    )
    rendered = render_outcome_backed_prompt(
        packet,
        packet_set=_packet_set(packet),
        condition_id=CLAUDE_SINGLE,
    )

    embedded = rendered.task_content.split("SOURCE PACKET (canonical JSON)\n", 1)[1].split(
        "\nRESPONSE CONTRACT", 1
    )[0]
    assert embedded == json.dumps(
        packet,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert "\u201cliable\u201d \u2014 exposure was \u20ac2m" in embedded
    unhashed = json.loads(embedded)
    claimed_hash = unhashed.pop("packet_sha256")
    assert canonical_json_sha256(unhashed) == claimed_hash


def test_prompt_digest_changes_with_valid_packet_hash_change() -> None:
    first_packet = _packet()
    second_packet = _packet(source_content="Different frozen pre-cutoff evidence.")
    first = render_outcome_backed_prompt(
        first_packet,
        packet_set=_packet_set(first_packet),
        condition_id=OPENAI_SINGLE,
    )
    second = render_outcome_backed_prompt(
        second_packet,
        packet_set=_packet_set(second_packet),
        condition_id=OPENAI_SINGLE,
    )

    assert first.packet_sha256 != second.packet_sha256
    assert first.prompt_sha256 != second.prompt_sha256
    assert first.packet_sha256 in first.prompt_text
    assert second.packet_sha256 in second.prompt_text
    assert first.packet_set_sha256 in first.prompt_text


def test_unknown_condition_is_rejected() -> None:
    packet = _packet()
    with pytest.raises(OutcomeBackedPromptError, match="unknown frozen condition ID"):
        render_outcome_backed_prompt(
            packet, packet_set=_packet_set(packet), condition_id="other-single"
        )


@pytest.mark.parametrize(
    ("path", "key"),
    [
        (("case",), "correct_option_id"),
        (("sources", 0), "resolution_summary"),
        (("case",), "cruxes"),
    ],
)
def test_outcome_bearing_keys_are_rejected(path: tuple[str | int, ...], key: str) -> None:
    packet = _packet()
    target: object = packet
    for part in path:
        assert isinstance(target, dict | list)
        target = target[part]  # type: ignore[index]
    assert isinstance(target, dict)
    target[key] = "hidden answer"
    packet["packet_sha256"] = canonical_json_sha256(
        {name: value for name, value in packet.items() if name != "packet_sha256"}
    )

    with pytest.raises(OutcomeBackedPromptError, match="outcome-bearing key"):
        render_outcome_backed_prompt(
            packet, packet_set=_packet_set(packet), condition_id=GEMINI_SINGLE
        )


@pytest.mark.parametrize(
    "key",
    [
        "correctOptionId",
        "correct-option-id",
        "CORRECT OPTION ID",
        "outcomeSidecar",
        "resolvedAt",
    ],
)
def test_outcome_bearing_key_variants_are_rejected(key: str) -> None:
    packet = _packet()
    assert isinstance(packet["case"], dict)
    packet["case"][key] = "hidden answer"
    packet["packet_sha256"] = canonical_json_sha256(
        {name: value for name, value in packet.items() if name != "packet_sha256"}
    )

    with pytest.raises(OutcomeBackedPromptError, match="outcome-bearing key"):
        render_outcome_backed_prompt(
            packet, packet_set=_packet_set(packet), condition_id=GEMINI_SINGLE
        )


def test_team_has_exactly_one_adversarial_round_and_synthesis() -> None:
    packet = _packet()
    packet_set = _packet_set(packet)
    team = render_outcome_backed_prompt(packet, packet_set=packet_set, condition_id=ARAGORA_TEAM)
    single = render_outcome_backed_prompt(packet, packet_set=packet_set, condition_id=CLAUDE_SINGLE)

    assert team.task_content == single.task_content
    assert team.prompt_text.count("Adversarial phase") == 1
    assert team.prompt_text.count("Synthesis phase") == 1
    assert "Do not run another critique or revision round" in team.prompt_text
    assert "TEAM PROTOCOL" not in single.prompt_text


def test_single_conditions_differ_only_in_identity_binding() -> None:
    packet = _packet()
    rendered = [
        render_outcome_backed_prompt(
            packet, packet_set=_packet_set(packet), condition_id=condition_id
        )
        for condition_id in (CLAUDE_SINGLE, OPENAI_SINGLE, GEMINI_SINGLE)
    ]

    assert len({item.identity_binding for item in rendered}) == 3
    assert len({item.task_content for item in rendered}) == 1
    assert all("TEAM PROTOCOL" not in item.prompt_text for item in rendered)


def test_prompt_contract_requires_two_actions_sources_and_valid_packet_hash() -> None:
    one_action = _packet()
    assert isinstance(one_action["case"], dict)
    one_action["case"]["options"] = one_action["case"]["options"][:1]
    one_action["packet_sha256"] = canonical_json_sha256(
        {name: value for name, value in one_action.items() if name != "packet_sha256"}
    )
    with pytest.raises(OutcomeBackedPromptError, match="exactly two actions"):
        render_outcome_backed_prompt(
            one_action, packet_set=_packet_set(one_action), condition_id=CLAUDE_SINGLE
        )

    no_sources = _packet()
    no_sources["sources"] = []
    no_sources["packet_sha256"] = canonical_json_sha256(
        {name: value for name, value in no_sources.items() if name != "packet_sha256"}
    )
    with pytest.raises(OutcomeBackedPromptError, match="at least one source"):
        render_outcome_backed_prompt(
            no_sources, packet_set=_packet_set(no_sources), condition_id=CLAUDE_SINGLE
        )

    tampered = deepcopy(_packet())
    assert isinstance(tampered["case"], dict)
    tampered["case"]["title"] = "Tampered without rehash"
    with pytest.raises(OutcomeBackedPromptError, match="packet hash mismatch"):
        render_outcome_backed_prompt(
            tampered, packet_set=_packet_set(_packet()), condition_id=CLAUDE_SINGLE
        )


def test_packet_must_belong_to_a_complete_hash_verified_packet_set() -> None:
    packet = _packet()
    packet_set = _packet_set(packet)
    assert isinstance(packet_set["packets"], list)
    assert isinstance(packet_set["packets"][0], dict)
    packet_set["packets"][0]["packet_sha256"] = "f" * 64
    packet_set["packet_set_sha256"] = canonical_json_sha256(
        {name: value for name, value in packet_set.items() if name != "packet_set_sha256"}
    )

    with pytest.raises(OutcomeBackedPromptError, match="not bound to the packet-set"):
        render_outcome_backed_prompt(packet, packet_set=packet_set, condition_id=CLAUDE_SINGLE)

    incomplete = _packet_set(packet)
    assert isinstance(incomplete["packets"], list)
    incomplete["packets"] = incomplete["packets"][:-1]
    incomplete["packet_count"] = 15
    incomplete["packet_set_sha256"] = canonical_json_sha256(
        {name: value for name, value in incomplete.items() if name != "packet_set_sha256"}
    )
    with pytest.raises(OutcomeBackedPromptError, match="must contain 16 development packets"):
        render_outcome_backed_prompt(packet, packet_set=incomplete, condition_id=CLAUDE_SINGLE)


def test_response_contract_requires_cruxes_forecast_confidence_and_source_ids() -> None:
    packet = _packet()
    rendered = render_outcome_backed_prompt(
        packet, packet_set=_packet_set(packet), condition_id=OPENAI_SINGLE
    )

    assert '"probability_forecast"' in rendered.task_content
    assert '"confidence"' in rendered.task_content
    assert '"cruxes"' in rendered.task_content
    assert '"falsifiable_claims"' in rendered.task_content
    assert '"source_ids"' in rendered.task_content
    packet_json = json.dumps(_packet(), sort_keys=True, separators=(",", ":"))
    assert packet_json in rendered.task_content
