"""Citation checks are mechanical: passage found and quote found, never "supports"."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from aragora.decision_workspace.citations import check_citation, check_result, normalize_label
from aragora.decision_workspace.revisions import revision_content_hash
from aragora.gauntlet.odr_jcs import jcs_canonicalize


@dataclass(frozen=True)
class P:
    passage_id: str
    label: str
    text: str


OURS = {
    "S1:P1": P("psg_1", "S1:P1", "Seat pricing today.\nRevenue is   predictable."),
    "S2:P3": P("psg_2", "S2:P3", "Three of five customers asked for usage pricing."),
}
OTHER_DECISION = {"S9:P1": P("psg_x", "S9:P1", "Another decision's passage.")}


def test_a_label_of_this_decision_exists():
    checked = check_citation({"claim": "c", "passage_label": "S2:P3"}, OURS)
    assert checked["passage_exists"] is True
    assert checked["passage_id"] == "psg_2"


def test_unknown_or_foreign_labels_do_not_exist():
    for label in ("S7:P7", "S9:P1", "", None, "page 3"):
        checked = check_citation({"claim": "c", "passage_label": label}, OURS)
        assert checked["passage_exists"] is False, label
        assert checked["passage_id"] is None
        assert checked["quote_found"] is False


def test_a_label_from_another_decision_is_not_found_even_if_it_exists_there():
    citation = {"claim": "c", "passage_label": "S9:P1", "quote": "Another decision"}
    assert check_citation(citation, OTHER_DECISION)["passage_exists"] is True
    checked = check_citation(citation, OURS)
    assert (checked["passage_exists"], checked["quote_found"]) == (False, False)


def test_label_variants_are_normalized():
    assert normalize_label("[S2:P3]") == "S2:P3"
    assert normalize_label(" s2 : p3 ") == "S2:P3"
    assert normalize_label("S02:P003") == "S2:P3"
    assert check_citation({"claim": "c", "passage_label": "[s2:p3]"}, OURS)["passage_exists"]


def test_a_whitespace_normalized_substring_is_a_found_quote():
    citation = {"claim": "c", "passage_label": "S1:P1", "quote": "today. Revenue is predictable"}
    checked = check_citation(citation, OURS)
    assert (checked["passage_exists"], checked["quote_found"]) == (True, True)


def test_a_quote_not_in_the_passage_is_not_found():
    for quote in ("Revenue is unpredictable", "Three of five customers"):
        citation = {"claim": "c", "passage_label": "S1:P1", "quote": quote}
        checked = check_citation(citation, OURS)
        assert (checked["passage_exists"], checked["quote_found"]) == (True, False), quote


def test_an_absent_quote_is_explicit():
    for citation in (
        {"claim": "c", "passage_label": "S1:P1"},
        {"claim": "c", "passage_label": "S1:P1", "quote": None},
        {"claim": "c", "passage_label": "S1:P1", "quote": "   "},
    ):
        checked = check_citation(citation, OURS)
        assert checked["quote"] is None
        assert checked["quote_provided"] is False
        assert checked["quote_found"] is False


def test_check_result_checks_every_citation_and_never_says_supports():
    result = {
        "recommendation": "Adopt usage pricing for new customers.",
        "citations": [
            {"claim": "Customers asked", "passage_label": "S2:P3", "quote": "Three of five"}
        ],
        "alternatives": [
            {
                "title": "Keep seats",
                "summary": "Status quo",
                "why_not_chosen": "Less aligned",
                "citations": [{"claim": "Predictable", "passage_label": "S1:P1"}],
            }
        ],
        "dissent": [
            {
                "agent": "grok",
                "position": "Wait a quarter",
                "citations": [{"claim": "x", "passage_label": "S5:P5"}],
            }
        ],
        "missing_evidence": [{"question": "Churn?", "why_it_matters": "Revenue risk"}],
        "assumptions": [{"statement": "Usage grows", "basis": "S2:P3"}],
    }
    checked = check_result(result, OURS.values())
    assert checked["citations"][0]["quote_found"] is True
    assert checked["alternatives"][0]["citations"][0]["passage_exists"] is True
    assert checked["dissent"][0]["citations"][0]["passage_exists"] is False
    assert checked["missing_evidence"] == result["missing_evidence"]
    assert checked["assumptions"] == result["assumptions"]
    text = json.dumps(checked).lower()
    for word in ("supports", "supported", "verified support", "proven"):
        assert word not in text


def test_revision_hash_is_sha256_of_the_jcs_document():
    content = {"recommendation": "Adopt", "citations": []}
    expected = hashlib.sha256(
        jcs_canonicalize(
            {"plan_id": "plan_1", "number": 1, "parent_revision_id": None, "content": content}
        )
    ).hexdigest()
    assert revision_content_hash("plan_1", 1, None, content) == expected
    assert len(expected) == 64


def test_revision_hash_changes_with_content_number_and_parent():
    base = revision_content_hash("plan_1", 1, None, {"recommendation": "Adopt"})
    assert revision_content_hash("plan_1", 1, None, {"recommendation": "Adopt!"}) != base
    assert revision_content_hash("plan_1", 2, None, {"recommendation": "Adopt"}) != base
    assert revision_content_hash("plan_1", 1, "rev_0", {"recommendation": "Adopt"}) != base
    assert revision_content_hash("plan_2", 1, None, {"recommendation": "Adopt"}) != base
