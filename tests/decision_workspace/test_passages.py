"""Deterministic passage splitting (VAL-INTAKE-017)."""

from __future__ import annotations

import hashlib

from aragora.decision_workspace.passages import (
    MAX_PASSAGE_CHARS,
    decode_source_bytes,
    split_passages,
)

MARKDOWN = """# Pricing review

We charge per seat today. Most customers have fewer than ten seats.

Usage-based pricing would align cost with value.


## Risks
Revenue becomes less predictable.
Finance needs a new forecast model.

### Mitigations ###

Offer an annual commitment with overage billing.
"""


def _texts(text: str) -> list[str]:
    return [passage.text for passage in split_passages(text)]


def test_splitting_the_same_text_twice_is_identical():
    first = split_passages(MARKDOWN)
    second = split_passages(MARKDOWN)
    assert first == second
    assert [p.seq for p in first] == list(range(1, len(first) + 1))


def test_splits_on_blank_lines_and_markdown_headings():
    assert _texts(MARKDOWN) == [
        "We charge per seat today. Most customers have fewer than ten seats.",
        "Usage-based pricing would align cost with value.",
        "Revenue becomes less predictable.\nFinance needs a new forecast model.",
        "Offer an annual commitment with overage billing.",
    ]


def test_each_passage_carries_its_nearest_heading():
    headings = [passage.heading for passage in split_passages(MARKDOWN)]
    assert headings == ["Pricing review", "Pricing review", "Risks", "Mitigations"]


def test_text_before_any_heading_has_no_heading():
    passages = split_passages("Intro line.\n\n# Later\nBody.")
    assert [(p.heading, p.text) for p in passages] == [(None, "Intro line."), ("Later", "Body.")]


def test_hash_without_space_is_not_a_heading():
    passages = split_passages("#hashtag in a line\nstill the same paragraph")
    assert len(passages) == 1
    assert passages[0].heading is None
    assert passages[0].text.startswith("#hashtag")


def test_offsets_point_at_the_passage_text_and_sha256_is_over_the_text():
    for passage in split_passages(MARKDOWN):
        assert MARKDOWN[passage.start_char : passage.end_char] == passage.text
        assert passage.sha256 == hashlib.sha256(passage.text.encode("utf-8")).hexdigest()
        assert len(passage.sha256) == 64


def test_empty_passages_are_dropped():
    assert split_passages("") == []
    assert split_passages("   \n\n\t\n") == []
    assert split_passages("# Only a heading\n\n## Another\n") == []
    assert _texts("\n\n\nA.\n\n   \n\nB.\n\n") == ["A.", "B."]


def test_long_paragraph_is_split_at_sentence_boundaries():
    sentences = [f"Sentence number {n} explains one more detail of the plan." for n in range(60)]
    paragraph = " ".join(sentences)
    assert len(paragraph) > MAX_PASSAGE_CHARS

    passages = split_passages("## Detail\n" + paragraph)

    assert len(passages) > 1
    for passage in passages:
        assert len(passage.text) <= MAX_PASSAGE_CHARS
        assert passage.text.endswith("of the plan.")
        assert passage.text.startswith("Sentence number")
        assert passage.heading == "Detail"
    rejoined = " ".join(p.text for p in passages)
    assert rejoined == paragraph


def test_paragraph_at_the_limit_is_not_split():
    paragraph = ("x" * (MAX_PASSAGE_CHARS - 1)) + "."
    assert _texts(paragraph) == [paragraph]


def test_single_sentence_longer_than_the_limit_is_split_at_whitespace():
    words = ["word"] * 700
    sentence = " ".join(words) + "."
    passages = split_passages(sentence)
    assert len(passages) > 1
    assert all(len(p.text) <= MAX_PASSAGE_CHARS for p in passages)
    assert " ".join(p.text for p in passages) == sentence


def test_unbroken_text_longer_than_the_limit_is_cut_at_the_limit():
    blob = "y" * (MAX_PASSAGE_CHARS * 2 + 5)
    passages = split_passages(blob)
    assert [len(p.text) for p in passages] == [MAX_PASSAGE_CHARS, MAX_PASSAGE_CHARS, 5]
    assert "".join(p.text for p in passages) == blob


def test_crlf_text_splits_like_lf_text():
    crlf = MARKDOWN.replace("\n", "\r\n")
    assert [p.text.replace("\r\n", "\n") for p in split_passages(crlf)] == _texts(MARKDOWN)
    for passage in split_passages(crlf):
        assert crlf[passage.start_char : passage.end_char] == passage.text


def test_latin1_txt_input_is_decoded_via_the_fallback():
    raw = "Caf\u00e9 cr\u00e8me, na\u00efve r\u00e9sum\u00e9.\n\nSecond paragraph \u00a3 5.".encode(
        "latin-1"
    )
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:  # pragma: no cover - guards the fixture itself
        raise AssertionError("fixture must not be valid UTF-8")

    text = decode_source_bytes(raw)

    assert (
        text == "Caf\u00e9 cr\u00e8me, na\u00efve r\u00e9sum\u00e9.\n\nSecond paragraph \u00a3 5."
    )
    assert _texts(text) == [
        "Caf\u00e9 cr\u00e8me, na\u00efve r\u00e9sum\u00e9.",
        "Second paragraph \u00a3 5.",
    ]


def test_utf8_input_is_decoded_as_utf8_and_a_bom_is_dropped():
    assert decode_source_bytes("na\u00efve \u2014 ok".encode()) == "na\u00efve \u2014 ok"
    assert decode_source_bytes(b"\xef\xbb\xbf# Title\nBody") == "# Title\nBody"
