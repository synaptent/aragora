from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aragora.evaluation.decision_quality_corpus import (
    canonical_sha256,
    is_public_https_url,
    validate_corpus_documents,
    validate_corpus_files,
)
from aragora.evaluation.outcome_decision_quality import load_benchmark_bundle

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/benchmarks/decision_quality/benchmark-manifest.json"


def _case() -> dict[str, object]:
    return {
        "case_id": "case-1",
        "domain": "software_engineering",
        "split": "development",
        "title": "A resolved decision",
        "decision_prompt": "Choose one action.",
        "forecast_question": "What is the probability of option a?",
        "forecast_option_id": "a",
        "options": [
            {"option_id": "a", "label": "A", "description": "Action A"},
            {"option_id": "b", "label": "B", "description": "Action B"},
        ],
        "information_cutoff": "2025-01-01T00:00:00Z",
        "sources": [
            {
                "source_id": "evidence-1",
                "title": "Evidence",
                "url": "https://example.com/evidence",
                "published_at": "2024-12-31T00:00:00Z",
                "content_sha256": "1" * 64,
            }
        ],
    }


def _documents() -> tuple[dict[str, object], dict[str, object]]:
    corpus: dict[str, object] = {
        "schema_version": "decision-quality-corpus/1.0",
        "benchmark_id": "benchmark-v1",
        "revision": "v1",
        "frozen_at": "2025-03-01T00:00:00Z",
        "cases": [_case()],
    }
    outcomes: dict[str, object] = {
        "schema_version": "decision-quality-outcomes/1.0",
        "benchmark_id": "benchmark-v1",
        "corpus_sha256": canonical_sha256(corpus),
        "outcomes": [
            {
                "case_id": "case-1",
                "resolved_at": "2025-02-01T00:00:00Z",
                "correct_option_id": "a",
                "resolution_summary": "A occurred.",
                "authoritative_sources": [
                    {
                        "source_id": "outcome-1",
                        "title": "Outcome",
                        "url": "https://example.com/outcome",
                        "published_at": "2025-02-01T00:00:00Z",
                        "content_sha256": "2" * 64,
                    }
                ],
                "cruxes": [
                    {"crux_id": "c1", "description": "First crux", "aliases": []},
                    {"crux_id": "c2", "description": "Second crux", "aliases": []},
                    {"crux_id": "c3", "description": "Third crux", "aliases": []},
                ],
            }
        ],
    }
    return corpus, outcomes


def _codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}  # type: ignore[attr-defined]


def test_live_manifest_freezes_complete_balanced_corpus() -> None:
    bundle, report = load_benchmark_bundle(MANIFEST)

    assert report.ok
    assert bundle is not None
    assert report.case_count == 24
    assert (
        report.corpus_sha256 == "3a46198fe33e4cc984cf777c6db7f046e4adb7db10840e775f83e9a46e87172b"
    )
    assert (
        report.outcomes_sha256 == "98702fe5d220d171e77fd0276d5803ec851e46c6900445dd73ccb4cbfdbf194d"
    )


def test_outcome_leakage_after_cutoff_is_rejected() -> None:
    corpus, outcomes = _documents()
    corpus["cases"][0]["sources"][0]["published_at"] = "2025-01-02T00:00:00Z"  # type: ignore[index]
    outcomes["corpus_sha256"] = canonical_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "outcome_leakage" in _codes(report)


def test_options_must_have_stable_lexicographic_order() -> None:
    corpus, outcomes = _documents()
    corpus["cases"][0]["options"].reverse()  # type: ignore[index, union-attr]
    outcomes["corpus_sha256"] = canonical_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "unsorted_options" in _codes(report)


def test_outcome_source_must_not_predate_resolution() -> None:
    corpus, outcomes = _documents()
    outcomes["outcomes"][0]["authoritative_sources"][0]["published_at"] = (  # type: ignore[index]
        "2025-01-31T00:00:00Z"
    )

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "premature_outcome_source" in _codes(report)


def test_freeze_must_follow_every_resolution() -> None:
    corpus, outcomes = _documents()
    corpus["frozen_at"] = "2025-01-15T00:00:00Z"
    outcomes["corpus_sha256"] = canonical_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "premature_freeze" in _codes(report)


def test_full_corpus_rejects_unbalanced_answer_targets() -> None:
    bundle, manifest_report = load_benchmark_bundle(MANIFEST)
    assert manifest_report.ok and bundle is not None
    corpus = copy.deepcopy(bundle.corpus)
    outcomes = copy.deepcopy(bundle.outcomes)
    cases = {case["case_id"]: case for case in corpus["cases"]}
    changed = False
    for outcome in outcomes["outcomes"]:
        case = cases[outcome["case_id"]]
        if outcome["correct_option_id"] != case["forecast_option_id"]:
            outcome["correct_option_id"] = case["forecast_option_id"]
            changed = True
            break
    assert changed

    report = validate_corpus_documents(corpus, outcomes)

    assert "wrong_target_balance" in _codes(report)


def test_answer_key_is_rejected_from_model_visible_case() -> None:
    corpus, outcomes = _documents()
    corpus["cases"][0]["correct_option_id"] = "a"  # type: ignore[index]
    outcomes["corpus_sha256"] = canonical_sha256(corpus)

    report = validate_corpus_documents(corpus, outcomes, allow_partial=True)

    assert "unknown_field" in _codes(report)


def test_canonical_hash_ignores_object_key_order_and_rejects_nan() -> None:
    corpus, _ = _documents()
    reordered = {key: corpus[key] for key in reversed(corpus)}
    assert canonical_sha256(corpus) == canonical_sha256(reordered)
    with pytest.raises(ValueError):
        canonical_sha256({"value": float("nan")})


def test_mutating_answer_key_fails_frozen_outcomes_hash() -> None:
    corpus, outcomes = _documents()
    frozen = canonical_sha256(outcomes)
    mutated = copy.deepcopy(outcomes)
    mutated["outcomes"][0]["correct_option_id"] = "b"  # type: ignore[index]

    report = validate_corpus_documents(
        corpus,
        mutated,
        allow_partial=True,
        expected_outcomes_sha256=frozen,
    )

    assert "outcomes_hash_mismatch" in _codes(report)


def test_file_loader_returns_structured_invalid_utf8(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.json"
    outcomes_path = tmp_path / "outcomes.json"
    corpus_path.write_bytes(b"\xff\xfe")
    outcomes_path.write_text("{}", encoding="utf-8")

    report = validate_corpus_files(corpus_path, outcomes_path, allow_partial=True)

    assert not report.ok
    assert "invalid_utf8" in _codes(report)


def test_file_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    corpus, outcomes = _documents()
    corpus_path = tmp_path / "corpus.json"
    outcomes_path = tmp_path / "outcomes.json"
    corpus_path.write_text(
        json.dumps(corpus).replace('"revision": "v1"', '"revision": "v1", "revision": "v2"')
    )
    outcomes_path.write_text(json.dumps(outcomes))

    report = validate_corpus_files(corpus_path, outcomes_path, allow_partial=True)

    assert "duplicate_json_key" in _codes(report)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a",
        "https://localhost/a",
        "https://service.internal/a",
        "https://127.0.0.1/a",
        "https://[::1]/a",
        "https://bad host/a",
        "https://example.com:bad/a",
    ],
)
def test_public_source_url_validation_fails_closed(url: str) -> None:
    assert not is_public_https_url(url)


def test_public_source_url_accepts_normal_https() -> None:
    assert is_public_https_url("https://example.com/evidence")
