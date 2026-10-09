"""Synthesis output parsing, the single repair attempt and failure with raw output kept."""

from __future__ import annotations

import asyncio
import json

import pytest

from aragora.decision_workspace.synthesis import (
    SECTIONS,
    SynthesisFormatError,
    build_synthesis_prompt,
    parse_synthesis,
    synthesize,
)

VALID = {
    "recommendation": "Adopt usage pricing for new customers.",
    "citations": [{"claim": "Customers asked", "passage_label": "S2:P1", "quote": "Three of five"}],
    "alternatives": [
        {
            "title": "Keep seats",
            "summary": "Status quo",
            "why_not_chosen": "Less aligned",
            "citations": [],
        }
    ],
    "dissent": [{"agent": "grok", "position": "Wait a quarter", "citations": []}],
    "missing_evidence": [{"question": "Churn impact?", "why_it_matters": "Revenue risk"}],
    "assumptions": [{"statement": "Usage keeps growing", "basis": "S2:P1"}],
}


class Model:
    """Replies with the queued outputs in order and records every prompt."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def run(model):
    return asyncio.run(synthesize(model, "PROMPT"))


def test_valid_json_is_parsed_with_every_section():
    parsed = parse_synthesis(json.dumps(VALID))
    assert set(parsed) == set(SECTIONS)
    assert parsed["citations"] == [
        {"claim": "Customers asked", "passage_label": "S2:P1", "quote": "Three of five"}
    ]
    assert parsed["dissent"][0]["agent"] == "grok"


def test_fenced_json_is_accepted():
    assert parse_synthesis("```json\n" + json.dumps(VALID) + "\n```")["recommendation"]


@pytest.mark.parametrize(
    "raw, message",
    [
        ("not json at all", "no JSON object"),
        ("[1, 2]", "must be a JSON object"),
        (
            json.dumps({k: v for k, v in VALID.items() if k != "assumptions"}),
            "missing keys: assumptions",
        ),
        (json.dumps({**VALID, "recommendation": "  "}), "recommendation"),
        (json.dumps({**VALID, "citations": {"claim": "x"}}), "citations must be a list"),
        (json.dumps({**VALID, "citations": [{"claim": "x"}]}), "passage_label"),
        (json.dumps({**VALID, "dissent": [{"agent": 3, "position": "p"}]}), "agent"),
    ],
)
def test_invalid_output_is_refused(raw, message):
    with pytest.raises(SynthesisFormatError, match=message):
        parse_synthesis(raw)


def test_valid_first_output_needs_no_repair():
    model = Model(json.dumps(VALID))
    outcome = run(model)
    assert (outcome.attempts, outcome.error) == (1, None)
    assert outcome.result["recommendation"] == VALID["recommendation"]
    assert model.prompts == ["PROMPT"]


def test_invalid_output_gets_exactly_one_repair_which_can_succeed():
    model = Model("Sure! Here is my answer: {oops", json.dumps(VALID))
    outcome = run(model)
    assert outcome.attempts == 2
    assert outcome.error is None
    assert outcome.result["alternatives"][0]["title"] == "Keep seats"
    assert len(model.prompts) == 2
    assert "could not be used" in model.prompts[1]
    assert "{oops" in model.prompts[1]


def test_a_second_invalid_output_fails_with_both_raw_outputs_kept():
    model = Model("first bad", "second bad")
    outcome = run(model)
    assert outcome.result is None
    assert outcome.attempts == 2
    assert outcome.raw_outputs == ["first bad", "second bad"]
    assert "after one repair attempt" in outcome.error
    assert len(model.prompts) == 2


def test_a_failing_repair_call_keeps_the_first_output():
    model = Model("first bad", RuntimeError("proxy down"))
    outcome = run(model)
    assert outcome.result is None
    assert outcome.raw_outputs == ["first bad"]
    assert "repair request failed" in outcome.error


def test_prompt_carries_the_question_context_and_debate_record():
    prompt = build_synthesis_prompt(
        question="Q?",
        context="<<<BEGIN UNTRUSTED SOURCE S1 (pasted text) [n]>>>\n[S1:P1] x",
        final_answer="Final.",
        proposals={"grok": "Proposal text"},
        dissenting_views=["I disagree"],
        cruxes=[{"claim": "Churn matters"}],
    )
    for needle in (
        "Q?",
        "[S1:P1] x",
        "Final.",
        "grok: Proposal text",
        "I disagree",
        "Churn matters",
    ):
        assert needle in prompt
    assert '"missing_evidence"' in prompt
