"""Deterministic, outcome-blind prompts for the outcome-backed benchmark."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from aragora.evaluation.outcome_backed_conditions import (
    ARAGORA_TEAM,
    CLAUDE_SINGLE,
    FROZEN_CONDITION_ROSTER,
    GEMINI_SINGLE,
    OPENAI_SINGLE,
    ConditionSpec,
    preflight_condition_roster,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, canonical_json_sha256
from aragora.evaluation.outcome_backed_packets import PACKET_SET_SCHEMA, SOURCE_PACKET_SCHEMA


PROMPT_SCHEMA = "outcome-backed-prompt/1.0"

_FROZEN_CONDITION_IDS = (CLAUDE_SINGLE, OPENAI_SINGLE, GEMINI_SINGLE, ARAGORA_TEAM)
_OUTCOME_BEARING_KEYS = frozenset(
    {
        "answer_key",
        "authoritative_sources",
        "correct_option_id",
        "cruxes",
        "outcome",
        "outcome_sidecar",
        "outcomes",
        "resolution",
        "resolution_summary",
        "resolved_at",
    }
)
_NORMALIZED_OUTCOME_BEARING_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", key.casefold()) for key in _OUTCOME_BEARING_KEYS
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OutcomeBackedPromptError(ValueError):
    """Raised when a benchmark prompt cannot be rendered fail-closed."""


@dataclass(frozen=True)
class RenderedOutcomeBackedPrompt:
    """Exact prompt bytes plus the bindings needed to verify them later."""

    condition_id: str
    packet_sha256: str
    packet_set_sha256: str
    roster_sha256: str
    identity_binding: str
    task_content: str
    prompt_text: str
    prompt_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": PROMPT_SCHEMA,
            "condition_id": self.condition_id,
            "packet_sha256": self.packet_sha256,
            "packet_set_sha256": self.packet_set_sha256,
            "roster_sha256": self.roster_sha256,
            "identity_binding": self.identity_binding,
            "task_content": self.task_content,
            "prompt_text": self.prompt_text,
            "prompt_sha256": self.prompt_sha256,
        }


def _reject_outcome_keys(value: object, *, path: str = "packet") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise OutcomeBackedPromptError(f"{path} contains a non-string key")
            normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized_key in _NORMALIZED_OUTCOME_BEARING_KEYS:
                raise OutcomeBackedPromptError(f"outcome-bearing key {key!r} found at {path}")
            _reject_outcome_keys(child, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            _reject_outcome_keys(child, path=f"{path}[{index}]")


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutcomeBackedPromptError(f"{field} must be a non-empty string")
    return value


def _canonical_json_text(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _validate_packet(
    packet: Mapping[str, object],
) -> tuple[str, str, tuple[str, str], str, tuple[str, ...]]:
    _reject_outcome_keys(packet)
    expected_keys = {
        "schema_version",
        "benchmark_id",
        "case",
        "sources",
        "packet_sha256",
    }
    if set(packet) != expected_keys:
        raise OutcomeBackedPromptError("source packet has unexpected or missing fields")
    if packet.get("schema_version") != SOURCE_PACKET_SCHEMA:
        raise OutcomeBackedPromptError("source packet schema mismatch")
    if packet.get("benchmark_id") != BENCHMARK_ID:
        raise OutcomeBackedPromptError("source packet benchmark mismatch")

    claimed_hash = packet.get("packet_sha256")
    if not isinstance(claimed_hash, str) or not _SHA256_RE.fullmatch(claimed_hash):
        raise OutcomeBackedPromptError("source packet has an invalid packet_sha256")
    unhashed = dict(packet)
    unhashed.pop("packet_sha256")
    if canonical_json_sha256(unhashed) != claimed_hash:
        raise OutcomeBackedPromptError("source packet hash mismatch")

    case = packet.get("case")
    if not isinstance(case, Mapping):
        raise OutcomeBackedPromptError("source packet case must be an object")
    case_id = _required_text(case.get("case_id"), "case.case_id")
    split = _required_text(case.get("split"), "case.split")
    if split not in {"development", "holdout"}:
        raise OutcomeBackedPromptError(f"case {case_id} has an unsupported split")
    options = case.get("options")
    if not isinstance(options, list) or len(options) != 2:
        raise OutcomeBackedPromptError(f"case {case_id} must contain exactly two actions")
    option_ids: list[str] = []
    for index, option in enumerate(options):
        if not isinstance(option, Mapping):
            raise OutcomeBackedPromptError(f"case.options[{index}] must be an object")
        option_ids.append(
            _required_text(option.get("option_id"), f"case.options[{index}].option_id")
        )
    if len(set(option_ids)) != 2:
        raise OutcomeBackedPromptError(f"case {case_id} action IDs must be unique")
    forecast_option_id = _required_text(case.get("forecast_option_id"), "case.forecast_option_id")
    if forecast_option_id not in option_ids:
        raise OutcomeBackedPromptError(
            "case.forecast_option_id must identify one of the two actions"
        )

    sources = packet.get("sources")
    if not isinstance(sources, list) or not sources:
        raise OutcomeBackedPromptError(f"case {case_id} must contain at least one source")
    source_ids: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            raise OutcomeBackedPromptError(f"packet.sources[{index}] must be an object")
        source_ids.append(
            _required_text(source.get("source_id"), f"packet.sources[{index}].source_id")
        )
    if len(set(source_ids)) != len(source_ids):
        raise OutcomeBackedPromptError(f"case {case_id} source IDs must be unique")
    return case_id, split, (option_ids[0], option_ids[1]), forecast_option_id, tuple(source_ids)


def _validate_packet_set(
    packet_set: Mapping[str, object],
    *,
    case_id: str,
    split: str,
    packet_sha256: str,
) -> str:
    _reject_outcome_keys(packet_set, path="packet_set")
    expected_keys = {
        "schema_version",
        "benchmark_id",
        "split",
        "packet_count",
        "source_count",
        "packets",
        "packet_set_sha256",
    }
    if set(packet_set) != expected_keys:
        raise OutcomeBackedPromptError("packet-set manifest has unexpected or missing fields")
    if packet_set.get("schema_version") != PACKET_SET_SCHEMA:
        raise OutcomeBackedPromptError("packet-set manifest schema mismatch")
    if packet_set.get("benchmark_id") != BENCHMARK_ID:
        raise OutcomeBackedPromptError("packet-set manifest benchmark mismatch")
    if packet_set.get("split") != split:
        raise OutcomeBackedPromptError("packet and packet-set split mismatch")

    expected_count = 16 if split == "development" else 8
    entries = packet_set.get("packets")
    if packet_set.get("packet_count") != expected_count or not isinstance(entries, list):
        raise OutcomeBackedPromptError(
            f"packet-set manifest must contain {expected_count} {split} packets"
        )
    if len(entries) != expected_count:
        raise OutcomeBackedPromptError(
            f"packet-set manifest must contain {expected_count} {split} packet entries"
        )
    source_count = packet_set.get("source_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count <= 0:
        raise OutcomeBackedPromptError("packet-set source_count must be a positive integer")

    parsed_entries: list[tuple[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) != {"case_id", "packet_sha256"}:
            raise OutcomeBackedPromptError(f"invalid packet-set entry at index {index}")
        entry_case_id = _required_text(entry.get("case_id"), f"packet_set.packets[{index}].case_id")
        entry_hash = entry.get("packet_sha256")
        if not isinstance(entry_hash, str) or not _SHA256_RE.fullmatch(entry_hash):
            raise OutcomeBackedPromptError(f"invalid packet hash at packet-set index {index}")
        parsed_entries.append((entry_case_id, entry_hash))
    if parsed_entries != sorted(parsed_entries) or len({item[0] for item in parsed_entries}) != len(
        parsed_entries
    ):
        raise OutcomeBackedPromptError("packet-set case IDs must be unique and sorted")
    if (case_id, packet_sha256) not in parsed_entries:
        raise OutcomeBackedPromptError("source packet is not bound to the packet-set manifest")

    claimed_hash = packet_set.get("packet_set_sha256")
    if not isinstance(claimed_hash, str) or not _SHA256_RE.fullmatch(claimed_hash):
        raise OutcomeBackedPromptError("packet-set manifest has an invalid packet_set_sha256")
    unhashed = dict(packet_set)
    unhashed.pop("packet_set_sha256")
    if canonical_json_sha256(unhashed) != claimed_hash:
        raise OutcomeBackedPromptError("packet-set manifest hash mismatch")
    return claimed_hash


def _condition(condition_id: str) -> ConditionSpec:
    if condition_id not in _FROZEN_CONDITION_IDS:
        raise OutcomeBackedPromptError(f"unknown frozen condition ID: {condition_id!r}")
    for condition in FROZEN_CONDITION_ROSTER:
        if condition.condition_id == condition_id:
            return condition
    raise OutcomeBackedPromptError(f"frozen condition is unavailable: {condition_id!r}")


def _identity_binding(condition: ConditionSpec, *, roster_sha256: str) -> str:
    binding = {
        "benchmark_id": BENCHMARK_ID,
        "condition_id": condition.condition_id,
        "members": [member.to_dict() for member in condition.members],
        "roster_sha256": roster_sha256,
        "schema_version": PROMPT_SCHEMA,
    }
    return json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _task_content(
    packet: Mapping[str, object],
    *,
    packet_set_sha256: str,
    case_id: str,
    option_ids: tuple[str, str],
    forecast_option_id: str,
    source_ids: tuple[str, ...],
) -> str:
    packet_sha256 = str(packet["packet_sha256"])
    response_contract: dict[str, Any] = {
        "case_id": case_id,
        "selected_option_id": f"exactly one of {list(option_ids)!r}",
        "probability_forecast": {
            "option_id": forecast_option_id,
            "probability": "finite number from 0.0 through 1.0",
        },
        "confidence": "finite number from 0.0 through 1.0",
        "rationale": {
            "summary": "concise reasoning based only on the source packet",
            "falsifiable_claims": [
                {
                    "claim": "a decision-relevant claim",
                    "would_falsify": "specific observable evidence that would overturn it",
                    "source_ids": f"one or more values from {list(source_ids)!r}",
                }
            ],
        },
        "cruxes": [
            {
                "crux": "a condition that could change the selected action",
                "direction": "how the decision changes if the crux is false",
                "source_ids": f"one or more values from {list(source_ids)!r}",
            }
        ],
    }
    sections = [
        "OUTCOME-BACKED DECISION TASK",
        f"Packet SHA-256: {packet_sha256}",
        f"Packet-set SHA-256: {packet_set_sha256}",
        "Use only evidence present in the packet and available at its information cutoff. "
        "Do not use outcomes, post-cutoff knowledge, or unstated external facts.",
        "Choose exactly one of the two actions. Return a probability for the packet's "
        "forecast option, a calibrated confidence, three to five decision cruxes, and "
        "source-keyed falsifiable rationale. Every substantive claim must cite source_ids "
        "from the packet.",
        "SOURCE PACKET (canonical JSON)",
        _canonical_json_text(packet),
        "RESPONSE CONTRACT (return one JSON object and no surrounding prose)",
        _canonical_json_text(response_contract),
    ]
    return "\n".join(sections)


def _team_protocol() -> str:
    return "\n".join(
        (
            "TEAM PROTOCOL",
            "1. Proposal phase: each frozen family independently produces the response contract.",
            "2. Adversarial phase: run exactly one round in which each family critiques one "
            "decision-relevant claim from another proposal using packet source_ids.",
            "3. Synthesis phase: produce one final response-contract JSON that explicitly "
            "resolves the critiques. Do not run another critique or revision round.",
        )
    )


def render_outcome_backed_prompt(
    packet: Mapping[str, object],
    *,
    packet_set: Mapping[str, object],
    condition_id: str,
) -> RenderedOutcomeBackedPrompt:
    """Render one exact, content-bound prompt without constructing a model client."""

    case_id, split, option_ids, forecast_option_id, source_ids = _validate_packet(packet)
    packet_set_sha256 = _validate_packet_set(
        packet_set,
        case_id=case_id,
        split=split,
        packet_sha256=str(packet["packet_sha256"]),
    )
    condition = _condition(condition_id)
    roster = preflight_condition_roster()
    identity_binding = _identity_binding(condition, roster_sha256=roster.roster_sha256)
    task_content = _task_content(
        packet,
        packet_set_sha256=packet_set_sha256,
        case_id=case_id,
        option_ids=option_ids,
        forecast_option_id=forecast_option_id,
        source_ids=source_ids,
    )
    sections = ["IDENTITY BINDING", identity_binding, task_content]
    if condition_id == ARAGORA_TEAM:
        sections.append(_team_protocol())
    prompt_text = "\n\n".join(sections) + "\n"
    return RenderedOutcomeBackedPrompt(
        condition_id=condition_id,
        packet_sha256=str(packet["packet_sha256"]),
        packet_set_sha256=packet_set_sha256,
        roster_sha256=roster.roster_sha256,
        identity_binding=identity_binding,
        task_content=task_content,
        prompt_text=prompt_text,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
    )


__all__ = [
    "PROMPT_SCHEMA",
    "OutcomeBackedPromptError",
    "RenderedOutcomeBackedPrompt",
    "render_outcome_backed_prompt",
]
