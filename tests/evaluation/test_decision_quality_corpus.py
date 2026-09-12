from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from aragora.evaluation.decision_quality_corpus import (
    DOMAINS,
    corpus_sha256,
    outcomes_sha256,
    validate_corpus_documents,
    validate_corpus_files,
)


def _case(case_id: str, domain: str, split: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "domain": domain,
        "split": split,
        "title": f"Resolved public decision {case_id}",
        "decision_prompt": "Choose the more likely outcome using only the supplied evidence.",
        "forecast_question": "What is the probability that option yes is correct?",
        "forecast_option_id": "yes",
        "options": [
            {"option_id": "yes", "label": "Yes", "description": "The event occurs."},
            {"option_id": "no", "label": "No", "description": "The event does not occur."},
        ],
        "information_cutoff": "2025-01-01T00:00:00Z",
        "sources": [
            {
                "source_id": "evidence-1",
                "title": "Public evidence snapshot",
                "url": "https://example.com/evidence",
                "published_at": "2024-12-31T00:00:00Z",
                "content_sha256": "1" * 64,
            }
        ],
    }


def _outcome(case_id: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "resolved_at": "2025-02-01T00:00:00Z",
        "correct_option_id": "yes",
        "resolution_summary": "The authoritative record confirms the event occurred.",
        "authoritative_sources": [
            {
                "source_id": "outcome-1",
                "title": "Authoritative outcome record",
                "url": "https://example.com/outcome",
                "published_at": "2025-02-01T00:00:00Z",
                "content_sha256": "2" * 64,
            }
        ],
        "cruxes": [
            {"crux_id": "crux-1", "description": "First crux", "aliases": []},
            {"crux_id": "crux-2", "description": "Second crux", "aliases": ["two"]},
            {"crux_id": "crux-3", "description": "Third crux", "aliases": []},
        ],
    }


def _documents(
    cases: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    selected_cases = cases or [_case("software-development-1", DOMAINS[0], "development")]
    corpus: dict[str, object] = {
        "schema_version": "decision-quality-corpus/1.0",
        "benchmark_id": "outcome-backed-decision-quality",
        "revision": "v1",
        "frozen_at": "2025-03-01T00:00:00Z",
        "cases": selected_cases,
    }
    outcomes: dict[str, object] = {
        "schema_version": "decision-quality-outcomes/1.0",
        "benchmark_id": "outcome-backed-decision-quality",
        "corpus_sha256": corpus_sha256(corpus),
        "outcomes": [_outcome(str(case["case_id"])) for case in selected_cases],
    }
    return corpus, outcomes


def _full_documents() -> tuple[dict[str, object], dict[str, object]]:
    cases: list[dict[str, object]] = []
    for domain in DOMAINS:
        for index in range(4):
            cases.append(_case(f"{domain}-development-{index + 1}", domain, "development"))
        for index in range(2):
            cases.append(_case(f"{domain}-holdout-{index + 1}", domain, "holdout"))
    return _documents(cases)


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}  # type: ignore[attr-defined]


def test_partial_corpus_accepts_hash_bound_resolved_case() -> None:
    corpus, outcomes = _documents()

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert report.ok
    assert report.case_count == 1
    assert report.corpus_sha256 == corpus_sha256(corpus)
    assert report.outcomes_sha256 == outcomes_sha256(outcomes)


def test_complete_corpus_requires_six_cases_and_four_two_split_per_domain() -> None:
    corpus, outcomes = _full_documents()

    report = validate_corpus_documents(corpus, outcomes)

    assert report.ok
    assert report.case_count == 24
    assert report.domain_counts == dict.fromkeys(DOMAINS, 6)
    assert report.split_counts == {"development": 16, "holdout": 8}


def test_incomplete_corpus_fails_without_explicit_partial_mode() -> None:
    corpus, outcomes = _documents()

    report = validate_corpus_documents(corpus, outcomes)

    assert not report.ok
    assert "wrong_case_count" in _issue_codes(report)
    assert "wrong_domain_count" in _issue_codes(report)


def test_partial_mode_does_not_allow_an_empty_benchmark() -> None:
    corpus, outcomes = _documents()
    corpus["cases"] = []
    outcomes["corpus_sha256"] = corpus_sha256(corpus)
    outcomes["outcomes"] = []

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert {"empty_corpus", "empty_outcomes"} <= _issue_codes(report)


def test_model_visible_source_after_cutoff_is_rejected_as_leakage() -> None:
    corpus, outcomes = _documents()
    corpus["cases"][0]["sources"][0]["published_at"] = "2025-01-02T00:00:00Z"  # type: ignore[index]
    outcomes["corpus_sha256"] = corpus_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "outcome_leakage" in _issue_codes(report)


def test_answer_key_field_in_model_visible_case_is_rejected() -> None:
    corpus, outcomes = _documents()
    corpus["cases"][0]["correct_option_id"] = "yes"  # type: ignore[index]
    outcomes["corpus_sha256"] = corpus_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "unknown_field" in _issue_codes(report)


def test_outcome_sidecar_must_match_canonical_corpus_hash() -> None:
    corpus, outcomes = _documents()
    outcomes["corpus_sha256"] = "0" * 64

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "corpus_hash_mismatch" in _issue_codes(report)


def test_every_case_requires_exactly_one_outcome() -> None:
    corpus, outcomes = _documents()
    outcomes["outcomes"] = []

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "missing_outcomes" in _issue_codes(report)


def test_outcome_must_resolve_after_information_cutoff() -> None:
    corpus, outcomes = _documents()
    outcomes["outcomes"][0]["resolved_at"] = "2025-01-01T00:00:00Z"  # type: ignore[index]

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "invalid_resolution_time" in _issue_codes(report)


def test_canonical_hash_is_independent_of_object_key_order() -> None:
    corpus, _ = _documents()
    reordered = {key: corpus[key] for key in reversed(corpus)}

    assert corpus_sha256(corpus) == corpus_sha256(reordered)


def test_json_schema_accepts_both_documents() -> None:
    corpus, outcomes = _documents()
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "benchmarks"
        / "decision_quality"
        / "corpus.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema)

    assert not list(validator.iter_errors(corpus))
    assert not list(validator.iter_errors(outcomes))


def test_mutating_corpus_requires_new_sidecar_hash() -> None:
    corpus, outcomes = _documents()
    mutated = copy.deepcopy(corpus)
    mutated["cases"][0]["title"] = "Silently changed title"  # type: ignore[index]

    report = validate_corpus_documents(mutated, outcomes, allow_partial=True)

    assert "corpus_hash_mismatch" in _issue_codes(report)


def test_mutating_answer_key_fails_against_frozen_outcomes_hash() -> None:
    corpus, outcomes = _documents()
    frozen_hash = outcomes_sha256(outcomes)
    mutated = copy.deepcopy(outcomes)
    mutated["outcomes"][0]["correct_option_id"] = "no"  # type: ignore[index]

    report = validate_corpus_documents(
        corpus,
        mutated,
        allow_partial=True,
        expected_outcomes_sha256=frozen_hash,
    )

    assert report.outcomes_sha256 == outcomes_sha256(mutated)
    assert report.outcomes_sha256 != frozen_hash
    assert "outcomes_hash_mismatch" in _issue_codes(report)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/evidence",
        "https://",
        "https://localhost/internal",
        "https://service.internal/evidence",
        "https://127.0.0.1/evidence",
        "https://[::1]/evidence",
        "https://bad host/evidence",
        "https://example.com:invalid/evidence",
    ],
)
def test_runtime_rejects_non_public_source_urls(url: str) -> None:
    corpus, outcomes = _documents()
    corpus["cases"][0]["sources"][0]["url"] = url  # type: ignore[index]
    outcomes["corpus_sha256"] = corpus_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "non_public_url" in _issue_codes(report)


@pytest.mark.parametrize(
    "url",
    [
        "https://",
        "https://localhost/internal",
        "https://service.internal/evidence",
    ],
)
def test_json_schema_rejects_non_public_source_urls(url: str) -> None:
    corpus, _ = _documents()
    corpus["cases"][0]["sources"][0]["url"] = url  # type: ignore[index]
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "benchmarks"
        / "decision_quality"
        / "corpus.schema.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_text()))

    assert list(validator.iter_errors(corpus))


@pytest.mark.parametrize("duplicate_in", ["corpus", "outcomes"])
def test_file_loader_rejects_duplicate_object_keys_at_any_depth(
    tmp_path: Path,
    duplicate_in: str,
) -> None:
    corpus, outcomes = _documents()
    corpus_text = json.dumps(corpus)
    outcomes_text = json.dumps(outcomes)
    if duplicate_in == "corpus":
        corpus_text = corpus_text.replace(
            '"revision": "v1"',
            '"revision": "v1", "revision": "v2"',
            1,
        )
    else:
        outcomes_text = outcomes_text.replace(
            '"case_id": "software-development-1"',
            '"case_id": "software-development-1", "case_id": "other"',
            1,
        )
    corpus_path = tmp_path / "corpus.json"
    outcomes_path = tmp_path / "outcomes.json"
    corpus_path.write_text(corpus_text)
    outcomes_path.write_text(outcomes_text)

    report = validate_corpus_files(corpus_path, outcomes_path, allow_partial=True)

    assert not report.ok
    assert _issue_codes(report) == {"duplicate_json_key"}
    assert report.issues[0].path == f"${duplicate_in}"
