"""Tests for boss_validation module: sanitization, contract extraction, pre-dispatch checks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
import subprocess

import pytest

from aragora.swarm.boss_validation import (
    assess_issue_body_sanitation,
    check_pre_dispatch_gate,
    parse_issue_with_llm,
    extract_declared_new_file_paths,
    extract_issue_validation_contract,
    extract_pre_dispatch_validation_commands,
    find_missing_pre_dispatch_validation_targets,
    run_pre_dispatch_validation_commands,
    sanitize_issue_body_for_dispatch,
    discover_focused_tests,
    _normalize_validation_line,
    _ordered_unique_strings,
    _extract_task_block,
)
from aragora.agents.semantic_extraction import ExtractionResult


# -- assess_issue_body_sanitation --


class TestAssessIssueBodySanitation:
    def test_empty_body(self):
        ok, reason = assess_issue_body_sanitation("")
        assert not ok and reason == "empty_body"

    def test_none_body(self):
        ok, reason = assess_issue_body_sanitation(None)
        assert not ok and reason == "empty_body"

    def test_auto_decomposed_missing_task(self):
        ok, reason = assess_issue_body_sanitation("Auto-decomposed from #1\nNo task here")
        assert not ok and reason == "auto_decomposed_missing_task"

    def test_task_too_short(self):
        body = "## Task\nShort."
        ok, reason = assess_issue_body_sanitation(body)
        assert not ok and reason == "task_too_short"

    def test_task_truncated(self):
        body = "## Task\n" + "a" * 50 + "\\\n"
        ok, reason = assess_issue_body_sanitation(body)
        assert not ok and reason == "task_truncated"

    def test_valid_body(self):
        body = "## Task\n" + "Implement a comprehensive feature with enough detail here."
        ok, reason = assess_issue_body_sanitation(body)
        assert ok and reason is None


# -- sanitize_issue_body_for_dispatch --


class TestSanitizeIssueBodyForDispatch:
    def test_empty_input(self):
        assert sanitize_issue_body_for_dispatch("") == ""

    def test_none_input(self):
        assert sanitize_issue_body_for_dispatch(None) == ""

    def test_drops_validation_section(self):
        body = "Hello\n## Acceptance Criteria\n- tests pass\n## Other\nkept"
        result = sanitize_issue_body_for_dispatch(body)
        assert "tests pass" not in result
        assert "kept" in result

    def test_keeps_summary_section(self):
        body = "## Summary\nImportant context here"
        result = sanitize_issue_body_for_dispatch(body)
        assert "Summary" in result
        assert "Important context here" in result


# -- extract_issue_validation_contract --


class TestExtractIssueValidationContract:
    def test_empty(self):
        assert extract_issue_validation_contract("") == []

    def test_acceptance_section_bullets(self):
        body = "## Acceptance Criteria\n- tests pass\n- lint clean"
        result = extract_issue_validation_contract(body)
        assert "tests pass" in result
        assert "lint clean" in result

    def test_inline_validation(self):
        body = "Acceptance: pytest tests/ -q"
        result = extract_issue_validation_contract(body)
        assert "pytest tests/ -q" in result

    def test_standalone_pytest_command(self):
        body = "Some text\npytest tests/foo.py -q\nMore text"
        result = extract_issue_validation_contract(body)
        assert "pytest tests/foo.py -q" in result

    def test_deduplication(self):
        body = "## Validation\n- item\n- item"
        result = extract_issue_validation_contract(body)
        assert result.count("item") == 1


# -- extract_pre_dispatch_validation_commands --


class TestExtractPreDispatchValidationCommands:
    def test_filters_safe_commands(self):
        body = "## Acceptance\n- pytest tests/foo.py -q\n- rm -rf /"
        result = extract_pre_dispatch_validation_commands(body)
        assert any("pytest" in c for c in result)
        assert not any("rm" in c for c in result)

    def test_empty_body(self):
        assert extract_pre_dispatch_validation_commands("") == []


# -- find_missing_pre_dispatch_validation_targets --


class TestFindMissingTargets:
    def test_missing_file(self, tmp_path):
        missing = find_missing_pre_dispatch_validation_targets(
            ["pytest tests/nonexistent.py"], repo_root=tmp_path
        )
        assert "tests/nonexistent.py" in missing

    def test_existing_file(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "real.py").write_text("")
        missing = find_missing_pre_dispatch_validation_targets(
            ["pytest tests/real.py"], repo_root=tmp_path
        )
        assert missing == []


# -- extract_declared_new_file_paths --


class TestExtractDeclaredNewFilePaths:
    def test_new_file_marker(self):
        body = "- `tests/swarm/test_new.py` (new file)"
        result = extract_declared_new_file_paths(body)
        assert "tests/swarm/test_new.py" in result

    def test_create_marker(self):
        body = "- `tests/swarm/test_config.py` (create)"
        result = extract_declared_new_file_paths(body)
        assert "tests/swarm/test_config.py" in result

    def test_create_marker_case_insensitive(self):
        body = "- `tests/foo/test_bar.py` (Create)"
        assert "tests/foo/test_bar.py" in extract_declared_new_file_paths(body)

    def test_new_marker_bare(self):
        body = "- `tests/x/test_y.py` (new)"
        assert "tests/x/test_y.py" in extract_declared_new_file_paths(body)

    def test_to_be_created_marker(self):
        body = "- `tests/a/test_b.py` (to be created)"
        assert "tests/a/test_b.py" in extract_declared_new_file_paths(body)

    def test_will_create_marker(self):
        body = "- `tests/c/test_d.py` (will create)"
        assert "tests/c/test_d.py" in extract_declared_new_file_paths(body)

    def test_generated_marker(self):
        body = "- `tests/e/test_f.py` (generated)"
        assert "tests/e/test_f.py" in extract_declared_new_file_paths(body)

    def test_no_marker(self):
        assert extract_declared_new_file_paths("just text") == []

    def test_none_input(self):
        assert extract_declared_new_file_paths(None) == []

    def test_modify_not_matched(self):
        """Paths without a new/create marker should not appear."""
        body = "- `aragora/swarm/config.py` (modify)"
        assert extract_declared_new_file_paths(body) == []


# -- run_pre_dispatch_validation_commands --


class TestRunPreDispatchValidationCommands:
    @patch("aragora.swarm.boss_validation._run_subprocess")
    def test_passing_command(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        result = run_pre_dispatch_validation_commands(
            ["pytest tests/"], cwd=tmp_path, timeout_seconds=10
        )
        assert result["satisfied"] is True

    @patch("aragora.swarm.boss_validation._run_subprocess")
    def test_failing_command(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess([], 1)
        result = run_pre_dispatch_validation_commands(
            ["pytest tests/"], cwd=tmp_path, timeout_seconds=10
        )
        assert result["satisfied"] is False

    @patch("aragora.swarm.boss_validation._run_subprocess")
    def test_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=1)
        result = run_pre_dispatch_validation_commands(
            ["pytest tests/"], cwd=tmp_path, timeout_seconds=1
        )
        assert result["satisfied"] is False
        assert result["results"][0]["status"] == "timeout"


# -- parse_issue_with_llm --


class TestParseIssueWithLLM:
    def test_uses_shared_semantic_extraction_helper(self, monkeypatch):
        async def fake_extract(prompt, **kwargs):
            assert "Implement a comprehensive feature" in prompt
            providers = kwargs["providers"]
            guarded_providers = {
                provider.agent_type for provider in providers if provider.disable_web_search
            }
            assert "anthropic-api" in guarded_providers
            return ExtractionResult(
                value={
                    "task_summary": "Implement a comprehensive feature with enough detail here.",
                    "is_well_formed": True,
                },
                source="anthropic-api",
            )

        monkeypatch.setattr(
            "aragora.swarm.boss_validation.extract_json_object_llm_first",
            fake_extract,
        )

        result = asyncio.run(
            parse_issue_with_llm(
                "## Task\nImplement a comprehensive feature with enough detail here."
            )
        )

        assert result == {
            "task_summary": "Implement a comprehensive feature with enough detail here.",
            "is_well_formed": True,
        }

    def test_returns_none_when_shared_extraction_fails(self, monkeypatch):
        async def fake_extract(_prompt, **kwargs):
            return ExtractionResult(
                value=None,
                source="openrouter",
                raw_response="not-json",
                error="openrouter:invalid_json",
            )

        monkeypatch.setattr(
            "aragora.swarm.boss_validation.extract_json_object_llm_first",
            fake_extract,
        )

        result = asyncio.run(
            parse_issue_with_llm(
                "## Task\nImplement a comprehensive feature with enough detail here."
            )
        )

        assert result is None


# -- check_pre_dispatch_gate --


class TestCheckPreDispatchGate:
    def test_default_uses_regex_without_llm(self, monkeypatch, tmp_path):
        async def fail_if_called(_body):
            raise AssertionError("LLM parsing should be opt-in")

        monkeypatch.setattr(
            "aragora.swarm.boss_validation.parse_issue_with_llm",
            fail_if_called,
        )

        body = (
            "## Task\n"
            "Implement a comprehensive feature with enough detail here.\n\n"
            "## Validation\n"
            "- pytest tests/missing.py -q\n"
        )

        result = asyncio.run(check_pre_dispatch_gate(body, repo_root=tmp_path))

        assert result["method"] == "regex"
        assert result["pass"] is False
        assert result["unresolved_missing"] == ["tests/missing.py"]
        assert result["gate_evaluation"]["gate_type"] == "dispatch_ready"
        assert result["gate_evaluation"]["verdict"] == "blocked"
        assert result["gate_evaluation"]["failure_classes"] == ["validation_target_missing"]

    def test_llm_gate_allows_declared_new_file(self, monkeypatch, tmp_path):
        async def fake_parse(_body):
            return {
                "file_scope": [{"path": "tests/swarm/test_new_gate.py", "action": "create"}],
                "validation_commands": ["Pytest tests/swarm/test_new_gate.py -q"],
                "task_summary": "Create focused tests for the dispatch gate behavior.",
                "is_well_formed": True,
                "rejection_reason": None,
                "is_auto_decomposed": True,
            }

        monkeypatch.setattr(
            "aragora.swarm.boss_validation.parse_issue_with_llm",
            fake_parse,
        )

        result = asyncio.run(
            check_pre_dispatch_gate("minimal body", repo_root=tmp_path, use_llm=True)
        )

        assert result["method"] == "llm"
        assert result["pass"] is True
        assert result["declared_new_files"] == ["tests/swarm/test_new_gate.py"]
        assert result["missing_targets"] == ["tests/swarm/test_new_gate.py"]
        assert result["unresolved_missing"] == []
        assert result["gate_evaluation"]["verdict"] == "pass"

    def test_llm_gate_falls_back_to_regex(self, monkeypatch, tmp_path):
        async def fake_parse(_body):
            return None

        monkeypatch.setattr(
            "aragora.swarm.boss_validation.parse_issue_with_llm",
            fake_parse,
        )

        body = "## Task\nImplement a comprehensive feature with enough detail here."
        result = asyncio.run(check_pre_dispatch_gate(body, repo_root=tmp_path, use_llm=True))

        assert result["method"] == "regex"
        assert result["pass"] is True
        assert result["gate_evaluation"]["verdict"] == "pass"


# -- helpers --


class TestHelpers:
    def test_normalize_validation_line_empty(self):
        assert _normalize_validation_line("") == ""
        assert _normalize_validation_line(None) == ""

    def test_normalize_strips_bold(self):
        assert "hello" in _normalize_validation_line("**hello**")

    def test_ordered_unique_strings(self):
        assert _ordered_unique_strings(["a", "b", "a", "", "c"]) == ["a", "b", "c"]

    def test_extract_task_block_empty(self):
        assert _extract_task_block([]) == []

    def test_extract_task_block_with_header(self):
        lines = ["## Task", "Do something", "## Other"]
        result = _extract_task_block(lines)
        assert result == ["Do something"]
