import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from aragora.evaluation.decision_quality_corpus import corpus_sha256, outcomes_sha256


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "debate_quality_benchmark.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("debate_quality_benchmark", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_benchmark_rejects_empty_prompt_collection() -> None:
    module = _load_module()

    with pytest.raises(ValueError, match="requires at least one prompt"):
        asyncio.run(module.run_benchmark([], dry_run=True))


def test_select_prompts_zero_preserves_all_prompts_sentinel() -> None:
    module = _load_module()

    assert module.parse_args(["--prompts", "0"]).prompts == 0
    assert module.select_prompts(0) == module.PROMPTS


def test_prompt_limit_rejects_negative_values() -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.parse_args(["--prompts", "-1"])
    with pytest.raises(ValueError, match="non-negative integer"):
        module.select_prompts(-1)


def test_select_prompts_positive_limit_returns_prefix() -> None:
    module = _load_module()

    assert module.select_prompts(2) == module.PROMPTS[:2]


def test_validate_corpus_command_emits_structured_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    corpus = {
        "schema_version": "decision-quality-corpus/1.0",
        "benchmark_id": "cli-test",
        "revision": "v1",
        "frozen_at": "2025-03-01T00:00:00Z",
        "cases": [
            {
                "case_id": "case-1",
                "domain": "software_engineering",
                "split": "development",
                "title": "CLI validation case",
                "decision_prompt": "Choose one option.",
                "forecast_question": "What is the probability of yes?",
                "forecast_option_id": "yes",
                "options": [
                    {"option_id": "yes", "label": "Yes", "description": "Occurs."},
                    {"option_id": "no", "label": "No", "description": "Does not occur."},
                ],
                "information_cutoff": "2025-01-01T00:00:00Z",
                "sources": [
                    {
                        "source_id": "evidence",
                        "title": "Evidence",
                        "url": "https://example.com/evidence",
                        "published_at": "2024-12-31T00:00:00Z",
                        "content_sha256": "1" * 64,
                    }
                ],
            }
        ],
    }
    outcomes = {
        "schema_version": "decision-quality-outcomes/1.0",
        "benchmark_id": "cli-test",
        "corpus_sha256": corpus_sha256(corpus),
        "outcomes": [
            {
                "case_id": "case-1",
                "resolved_at": "2025-02-01T00:00:00Z",
                "correct_option_id": "yes",
                "resolution_summary": "Yes occurred.",
                "authoritative_sources": [
                    {
                        "source_id": "outcome",
                        "title": "Outcome",
                        "url": "https://example.com/outcome",
                        "published_at": "2025-02-01T00:00:00Z",
                        "content_sha256": "2" * 64,
                    }
                ],
                "cruxes": [
                    {"crux_id": "one", "description": "One", "aliases": []},
                    {"crux_id": "two", "description": "Two", "aliases": []},
                    {"crux_id": "three", "description": "Three", "aliases": []},
                ],
            }
        ],
    }
    corpus_path = tmp_path / "corpus.json"
    outcomes_path = tmp_path / "outcomes.json"
    corpus_path.write_text(json.dumps(corpus))
    outcomes_path.write_text(json.dumps(outcomes))

    exit_code = module.run_validate_corpus(
        [
            "--corpus",
            str(corpus_path),
            "--outcomes",
            str(outcomes_path),
            "--allow-partial",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["case_count"] == 1
    assert payload["outcomes_sha256"] == outcomes_sha256(outcomes)


def test_validate_corpus_command_enforces_frozen_outcomes_digest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    corpus = {
        "schema_version": "decision-quality-corpus/1.0",
        "benchmark_id": "cli-test",
        "revision": "v1",
        "frozen_at": "2025-03-01T00:00:00Z",
        "cases": [],
    }
    outcomes = {
        "schema_version": "decision-quality-outcomes/1.0",
        "benchmark_id": "cli-test",
        "corpus_sha256": corpus_sha256(corpus),
        "outcomes": [],
    }
    corpus_path = tmp_path / "corpus.json"
    outcomes_path = tmp_path / "outcomes.json"
    corpus_path.write_text(json.dumps(corpus))
    outcomes_path.write_text(json.dumps(outcomes))

    exit_code = module.run_validate_corpus(
        [
            "--corpus",
            str(corpus_path),
            "--outcomes",
            str(outcomes_path),
            "--allow-partial",
            "--expected-outcomes-sha256",
            "0" * 64,
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["outcomes_sha256"] == outcomes_sha256(outcomes)
    assert any(issue["code"] == "outcomes_hash_mismatch" for issue in payload["issues"])


def test_legacy_parser_does_not_consume_validate_corpus_command() -> None:
    module = _load_module()

    args = module.parse_args(["--dry-run", "--prompts", "1"])

    assert args.dry_run is True
    assert args.prompts == 1
