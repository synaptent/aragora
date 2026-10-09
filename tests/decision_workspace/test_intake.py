"""Intake validation: limits, file types, agents, rounds (VAL-INTAKE-009..015)."""

from __future__ import annotations

import hashlib
import json

import pytest

from aragora.decision_workspace.config import (
    ENV_AGENTS,
    WorkspaceLimits,
    agent_options,
)
from aragora.decision_workspace.forms import IntakeError, parse_json_intake, parse_multipart_intake
from aragora.decision_workspace.intake import prepare_decision
from tests.decision_workspace.multipart import encode_multipart

AGENTS = agent_options({ENV_AGENTS: "openai-api|gpt-5.5,grok"})
LIMITS = WorkspaceLimits(max_documents=10, max_file_bytes=1048576, max_pasted_chars=204800)
VALID_FIELDS = [
    ("question", "Should we move to usage-based pricing?"),
    ("agents[]", "openai-api|gpt-5.5"),
    ("agents[]", "grok"),
]


def _prepare(fields=VALID_FIELDS, files=(), *, files_first=False, limits=LIMITS, options=AGENTS):
    body, content_type = encode_multipart(fields, files, files_first=files_first)
    form = parse_multipart_intake(body, content_type)
    return prepare_decision(form, options=options, limits=limits)


def _rejected(*args, **kwargs) -> IntakeError:
    with pytest.raises(IntakeError) as excinfo:
        _prepare(*args, **kwargs)
    return excinfo.value


def test_valid_intake_labels_sources_in_intake_order():
    decision = _prepare(
        [*VALID_FIELDS, ("pasted_text", "Pasted notes.\n\nSecond pasted paragraph.")],
        [
            ("files[]", "brief.md", b"# Brief\nShort brief."),
            ("files[]", "notes.txt", b"Plain notes."),
        ],
    )
    assert decision.question == "Should we move to usage-based pricing?"
    assert decision.agents == ("openai-api|gpt-5.5", "grok")
    assert decision.rounds == 1
    assert [(s.label, s.kind, s.filename) for s in decision.sources] == [
        ("S1", "pasted", None),
        ("S2", "upload", "brief.md"),
        ("S3", "upload", "notes.txt"),
    ]
    pasted, brief, notes = decision.sources
    assert pasted.content_sha256 == hashlib.sha256(pasted.text.encode()).hexdigest()
    assert brief.content_sha256 == hashlib.sha256(b"# Brief\nShort brief.").hexdigest()
    assert [p.text for p in pasted.passages] == ["Pasted notes.", "Second pasted paragraph."]
    assert [(p.heading, p.text) for p in brief.passages] == [("Brief", "Short brief.")]
    assert notes.char_count == len("Plain notes.")


def test_files_sent_before_the_pasted_text_come_first():
    decision = _prepare(
        [*VALID_FIELDS, ("pasted_text", "Pasted.")],
        [("files", "a.txt", b"File A.")],
        files_first=True,
    )
    assert [(s.label, s.kind) for s in decision.sources] == [("S1", "upload"), ("S2", "pasted")]


def test_rounds_default_to_one_and_accept_two():
    assert _prepare([*VALID_FIELDS, ("rounds", "2")]).rounds == 2
    for bad in ("0", "3", "two", ""):
        error = _rejected([*VALID_FIELDS, ("rounds", bad)])
        assert (error.status, error.field) == (400, "rounds")


@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
def test_empty_or_whitespace_question_is_rejected_naming_the_field(question):
    fields = [("question", question), *VALID_FIELDS[1:]]
    error = _rejected(fields)
    assert error.status == 400
    assert error.field == "question"
    assert "question" in error.message


def test_missing_question_is_rejected():
    error = _rejected(VALID_FIELDS[1:])
    assert (error.status, error.field) == (400, "question")


def test_agent_not_offered_is_rejected_naming_the_agent():
    error = _rejected([*VALID_FIELDS, ("agents[]", "anthropic-api")])
    assert error.status == 400
    assert error.field == "agents"
    assert "anthropic-api" in error.message
    assert error.body()["agent"] == "anthropic-api"


def test_no_agents_is_rejected():
    error = _rejected(VALID_FIELDS[:1])
    assert (error.status, error.field, error.code) == (400, "agents", "agents_required")


def test_repeated_agent_is_rejected():
    error = _rejected([*VALID_FIELDS, ("agents[]", "grok")])
    assert (error.status, error.field) == (400, "agents")
    assert "grok" in error.message


def test_missing_agent_configuration_is_refused_naming_the_variable():
    error = _rejected(options=agent_options({}))
    assert error.status == 400
    assert error.code == "agents_not_configured"
    assert ENV_AGENTS in error.message


def test_exactly_the_document_limit_is_accepted_and_one_more_is_rejected():
    ten = [("files[]", f"f{n}.txt", f"File {n}.".encode()) for n in range(10)]
    assert len(_prepare(files=ten).sources) == 10

    error = _rejected(files=[*ten, ("files[]", "f10.txt", b"File 10.")])
    assert error.status in (400, 413)
    assert error.field == "files"
    assert "10" in error.message
    assert error.body()["limit"] == 10


def test_file_at_the_byte_limit_is_accepted_and_one_byte_more_is_rejected():
    at_limit = b"a" * 1048576
    decision = _prepare(files=[("files[]", "big.txt", at_limit)])
    assert decision.sources[0].char_count == 1048576

    error = _rejected(files=[("files[]", "too-big.txt", at_limit + b"a")])
    assert error.status in (400, 413)
    assert error.field == "files"
    assert "too-big.txt" in error.message
    assert "1048576" in error.message
    assert error.body()["filename"] == "too-big.txt"


def test_pasted_text_at_the_char_limit_is_accepted_and_one_more_is_rejected():
    at_limit = "\u00e9" * 204800  # characters, not bytes
    decision = _prepare([*VALID_FIELDS, ("pasted_text", at_limit)])
    assert decision.sources[0].char_count == 204800

    error = _rejected([*VALID_FIELDS, ("pasted_text", at_limit + "x")])
    assert error.status in (400, 413)
    assert error.field == "pasted_text"
    assert "204800" in error.message


def test_pasted_crlf_line_breaks_count_as_one_character():
    decision = _prepare([*VALID_FIELDS, ("pasted_text", "a\r\nb\r\n\r\nc")])
    assert decision.sources[0].text == "a\nb\n\nc"
    limits = WorkspaceLimits(max_documents=10, max_file_bytes=100, max_pasted_chars=6)
    assert _prepare([*VALID_FIELDS, ("pasted_text", "a\r\nb\r\n\r\nc")], limits=limits)


def test_pdf_is_rejected_with_the_planned_later_message():
    error = _rejected(files=[("files[]", "report.pdf", b"%PDF-1.7 fake")])
    assert error.status in (400, 415)
    assert error.field == "files"
    assert "PDF support is planned for a later stage" in error.message
    assert "report.pdf" in error.message


@pytest.mark.parametrize("filename", ["memo.docx", "data.csv", "page.html", "README", "x.MD.exe"])
def test_other_types_are_rejected_naming_the_file_and_the_accepted_types(filename):
    error = _rejected(files=[("files[]", filename, b"content")])
    assert error.status in (400, 415)
    assert error.field == "files"
    assert filename in error.message
    assert "only .md and .txt are accepted" in error.message


def test_extension_check_ignores_case():
    decision = _prepare(
        files=[("files[]", "NOTES.TXT", b"Upper."), ("files[]", "Plan.Md", b"Mixed.")]
    )
    assert [s.filename for s in decision.sources] == ["NOTES.TXT", "Plan.Md"]


def test_empty_file_is_rejected():
    error = _rejected(files=[("files[]", "blank.txt", b"  \n\n ")])
    assert (error.status, error.field) == (400, "files")
    assert "blank.txt" in error.message


def test_latin1_file_is_decoded_via_the_fallback():
    decision = _prepare(
        files=[("files[]", "legacy.txt", "Caf\u00e9 r\u00e9sum\u00e9.".encode("latin-1"))]
    )
    assert decision.sources[0].text == "Caf\u00e9 r\u00e9sum\u00e9."


def test_first_error_wins_and_errors_carry_field_code_and_message():
    error = _rejected([("question", " ")], [("files[]", "x.pdf", b"%PDF")])
    body = error.body()
    assert set(body) >= {"error", "code", "field"}
    assert body["field"] == "question"


def test_json_intake_accepts_text_only_decisions():
    body = json.dumps(
        {
            "question": "Ship it?",
            "pasted_text": "Context.",
            "agents": ["grok", "openai-api|gpt-5.5"],
            "rounds": 2,
        }
    ).encode()
    decision = prepare_decision(parse_json_intake(body), options=AGENTS, limits=LIMITS)
    assert (decision.question, decision.agents, decision.rounds) == (
        "Ship it?",
        ("grok", "openai-api|gpt-5.5"),
        2,
    )
    assert [s.kind for s in decision.sources] == ["pasted"]


@pytest.mark.parametrize("rounds", ["x", [1], 1.5, True, {"n": 1}, "1" * 5000])
def test_json_rounds_that_are_not_a_small_whole_number_are_rejected(rounds):
    body = json.dumps({"question": "Q", "agents": ["grok"], "rounds": rounds}).encode()
    with pytest.raises(IntakeError) as excinfo:
        prepare_decision(parse_json_intake(body), options=AGENTS, limits=LIMITS)
    assert (excinfo.value.status, excinfo.value.field, excinfo.value.code) == (
        400,
        "rounds",
        "invalid_rounds",
    )


def test_an_unselected_file_input_adds_no_source():
    assert _prepare(files=[("files[]", "", b"")]).sources == ()
