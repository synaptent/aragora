"""Reading intake request bodies: multipart framing, field names, JSON shape."""

from __future__ import annotations

import json

import pytest

from aragora.decision_workspace.config import WorkspaceLimits
from aragora.decision_workspace.forms import (
    PASTED,
    IntakeError,
    UploadedFile,
    max_request_bytes,
    parse_json_intake,
    parse_multipart_intake,
)
from tests.decision_workspace.multipart import encode_multipart

LIMITS = WorkspaceLimits(max_documents=10, max_file_bytes=1048576, max_pasted_chars=204800)
FIELDS = [("question", "Ship it?"), ("agents[]", "grok"), ("agents[]", "openai-api|gpt-5.5")]


def _parse(fields=FIELDS, files=(), **kwargs):
    body, content_type = encode_multipart(fields, files, **kwargs)
    return parse_multipart_intake(body, content_type)


def _refused(fields=FIELDS, files=()) -> IntakeError:
    with pytest.raises(IntakeError) as excinfo:
        _parse(fields, files)
    return excinfo.value


def test_fields_and_files_are_read_in_request_order():
    form = _parse(
        [*FIELDS, ("pasted_text", "Notes."), ("rounds", "2")],
        [("files[]", "a.md", b"# A"), ("files", "b.txt", b"B")],
        files_first=True,
    )
    assert (form.question, form.pasted_text, form.rounds) == ("Ship it?", "Notes.", "2")
    assert form.agents == ["grok", "openai-api|gpt-5.5"]
    assert form.items == [
        UploadedFile(form_field="files[]", filename="a.md", content=b"# A"),
        UploadedFile(form_field="files", filename="b.txt", content=b"B"),
        PASTED,
    ]


def test_unknown_text_fields_are_ignored():
    form = _parse([*FIELDS, ("org_id", "org-b"), ("user_id", "user-b")])
    assert (form.question, form.items) == ("Ship it?", [])


def test_unselected_file_input_is_ignored():
    assert _parse(files=[("files[]", "", b"")]).items == []


def test_client_path_components_are_stripped_from_filenames():
    [item] = _parse(files=[("files[]", "C:\\Users\\me\\notes.txt", b"Notes.")]).items
    assert isinstance(item, UploadedFile) and item.filename == "notes.txt"


def test_duplicate_scalar_fields_are_rejected():
    error = _refused([*FIELDS, ("question", "Second question?")])
    assert (error.status, error.field, error.code) == (400, "question", "duplicate_field")


def test_file_in_an_unexpected_field_is_rejected():
    error = _refused(files=[("attachment", "a.txt", b"A.")])
    assert (error.status, error.field, error.code) == (400, "attachment", "unexpected_file")


def test_text_in_the_files_field_is_rejected():
    error = _refused([*FIELDS, ("files[]", "not a file")])
    assert (error.status, error.field) == (400, "files")


def test_malformed_multipart_is_rejected():
    for body, content_type in [
        (b"not multipart at all", "multipart/form-data; boundary=abc"),
        (
            b'--abc\r\nContent-Disposition: form-data; name="question"\r\n\r\nQ?\r\n',
            "multipart/form-data; boundary=abc",
        ),
        (b"", "multipart/form-data"),
    ]:
        with pytest.raises(IntakeError) as excinfo:
            parse_multipart_intake(body, content_type)
        assert (excinfo.value.status, excinfo.value.code) == (400, "invalid_multipart")


def test_non_utf8_text_field_is_rejected_naming_the_field():
    boundary = "b0undary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="question"\r\n\r\n'.encode()
        + b"caf\xe9?\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    with pytest.raises(IntakeError) as excinfo:
        parse_multipart_intake(body, f"multipart/form-data; boundary={boundary}")
    assert (excinfo.value.status, excinfo.value.field) == (400, "question")


def test_error_bodies_carry_field_code_and_message():
    body = _refused([*FIELDS, ("question", "Again?")]).body()
    assert body == {
        "error": "Send the question field only once.",
        "code": "duplicate_field",
        "field": "question",
    }


def test_json_intake_reads_text_only_decisions():
    body = json.dumps(
        {"question": "Ship it?", "pasted_text": "Context.", "agents": ["grok"], "rounds": 2}
    ).encode()
    form = parse_json_intake(body)
    assert (form.question, form.pasted_text, form.agents, form.rounds) == (
        "Ship it?",
        "Context.",
        ["grok"],
        2,
    )
    assert form.items == [PASTED]


@pytest.mark.parametrize(
    "payload, field",
    [
        (b"[]", None),
        (b"{not json", None),
        (b"\xff\xfe", None),
        (json.dumps({"question": 5, "agents": ["grok"]}).encode(), "question"),
        (json.dumps({"question": "Q", "agents": "grok"}).encode(), "agents"),
        (json.dumps({"question": "Q", "agents": [1]}).encode(), "agents"),
        (json.dumps({"question": "Q\ud800", "agents": ["grok"]}).encode(), "question"),
        (json.dumps({"question": "Q", "files": ["a.txt"]}).encode(), "files"),
    ],
)
def test_json_intake_rejects_malformed_bodies(payload, field):
    with pytest.raises(IntakeError) as excinfo:
        parse_json_intake(payload)
    assert (excinfo.value.status, excinfo.value.field) == (400, field)


def test_request_cap_covers_the_largest_valid_request():
    cap = max_request_bytes(LIMITS)
    assert cap >= 10 * 1048576 + 204800 * 4
