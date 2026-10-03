from __future__ import annotations

import copy
import json
from pathlib import Path

from aragora.evaluation.outcome_backed_corpus import (
    canonical_json_sha256,
    validate_corpus_directory,
)


REPO_CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _copy_corpus(tmp_path: Path) -> Path:
    target = tmp_path / "tranches"
    target.mkdir()
    for source in REPO_CORPUS_DIR.glob("*.json"):
        target.joinpath(source.name).write_bytes(source.read_bytes())
    return target


def _mutate_pair(
    directory: Path,
    filename: str,
    mutate: object,
    *,
    rebind: bool = True,
) -> None:
    corpus_path = directory / filename
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert callable(mutate)
    mutate(corpus)
    _write_json(corpus_path, corpus)
    if rebind:
        outcome_path = corpus_path.with_name(filename.replace(".corpus.json", ".outcomes.json"))
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["corpus_sha256"] = canonical_json_sha256(corpus)
        _write_json(outcome_path, outcome)


def _codes(directory: Path) -> set[str]:
    return {issue.code for issue in validate_corpus_directory(directory).issues}


def test_checked_in_corpus_is_complete_and_valid() -> None:
    report = validate_corpus_directory(REPO_CORPUS_DIR)

    assert report.valid, report.to_dict()
    assert report.case_count == 24
    assert report.corpus_files == 8
    assert report.outcome_files == 8
    assert report.split_counts == {"development": 16, "holdout": 8}
    assert report.domain_counts == {
        "business_operations": 6,
        "policy_compliance": 6,
        "science_forecasting": 6,
        "software_engineering": 6,
    }


def test_rejects_recursive_outcome_leakage(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)

    def add_leak(corpus: dict[str, object]) -> None:
        cases = corpus["cases"]
        assert isinstance(cases, list)
        cases[0]["metadata"] = {"correct_option_id": "secret"}

    _mutate_pair(directory, "software-development-1.corpus.json", add_leak)

    assert "outcome_leakage" in _codes(directory)


def test_rejects_post_cutoff_model_visible_source(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)

    def move_source(corpus: dict[str, object]) -> None:
        cases = corpus["cases"]
        assert isinstance(cases, list)
        cases[0]["sources"][0]["published_at"] = "2099-01-01T00:00:00Z"

    _mutate_pair(directory, "software-development-1.corpus.json", move_source)

    assert "post_cutoff_source" in _codes(directory)


def test_rejects_pre_cutoff_outcome_and_source(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)
    outcome_path = directory / "software-development-1.outcomes.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    outcome["outcomes"][0]["resolved_at"] = "2000-01-01T00:00:00Z"
    outcome["outcomes"][0]["authoritative_sources"][0]["published_at"] = "1999-01-01T00:00:00Z"
    _write_json(outcome_path, outcome)

    codes = _codes(directory)
    assert "pre_cutoff_resolution" in codes
    assert "pre_resolution_outcome_source" in codes


def test_rejects_unbound_outcome_sidecar(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)

    def change_title(corpus: dict[str, object]) -> None:
        cases = corpus["cases"]
        assert isinstance(cases, list)
        cases[0]["title"] = "Changed after the sidecar was frozen"

    _mutate_pair(
        directory,
        "software-development-1.corpus.json",
        change_title,
        rebind=False,
    )

    assert "corpus_hash_mismatch" in _codes(directory)


def test_rejects_domain_split_and_alignment_drift(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)

    def change_split(corpus: dict[str, object]) -> None:
        cases = corpus["cases"]
        assert isinstance(cases, list)
        cases[0]["split"] = "holdout"

    _mutate_pair(directory, "software-development-1.corpus.json", change_split)

    codes = _codes(directory)
    assert "split_count" in codes
    assert "domain_split_count" in codes
    assert "target_alignment_count" in codes


def test_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)
    duplicate_path = directory / "business-operations-1.corpus.json"
    duplicate_path.write_text('{"schema_version":"a","schema_version":"b"}\n')
    nonfinite_path = directory / "policy-compliance-1.corpus.json"
    nonfinite_path.write_text('{"schema_version":NaN}\n')

    issues = validate_corpus_directory(directory).issues

    invalid_messages = [issue.message for issue in issues if issue.code == "invalid_json"]
    assert any("duplicate JSON key" in message for message in invalid_messages)
    assert any("non-finite JSON number" in message for message in invalid_messages)


def test_rejects_incomplete_source_provenance(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)

    def mutate_source(corpus: dict[str, object]) -> None:
        cases = corpus["cases"]
        assert isinstance(cases, list)
        cases[0]["sources"][0]["content_sha256"] = "ABC"
        cases[0]["sources"][0]["url"] = "https://user:secret@example.com/source"

    _mutate_pair(directory, "science-forecasting-1.corpus.json", mutate_source)

    codes = _codes(directory)
    assert "invalid_source_hash" in codes
    assert "invalid_source_url" in codes


def test_rejects_crux_count_outside_preregistered_range(tmp_path: Path) -> None:
    directory = _copy_corpus(tmp_path)
    outcome_path = directory / "science-forecasting-1.outcomes.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    outcome["outcomes"][0]["cruxes"] = copy.deepcopy(outcome["outcomes"][0]["cruxes"][:2])
    _write_json(outcome_path, outcome)

    assert "invalid_crux_count" in _codes(directory)
