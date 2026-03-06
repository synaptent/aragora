"""Tests for the CI classification scan script."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# Import from the scripts directory
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from classification_scan import (
    _extract_string_literals,
    _is_allowlisted,
    _load_allowlist,
    main,
    scan,
)


class TestExtractStringLiterals:
    """Verify AST-based string extraction."""

    def test_extracts_simple_string(self):
        source = 'x = "hello world"'
        assert "hello world" in _extract_string_literals(source)

    def test_extracts_multiple_strings(self):
        source = textwrap.dedent("""\
            a = "first"
            b = "second"
        """)
        lits = _extract_string_literals(source)
        assert "first" in lits
        assert "second" in lits

    def test_ignores_syntax_errors(self):
        source = "def broken(:"
        assert _extract_string_literals(source) == []

    def test_extracts_docstrings(self):
        source = textwrap.dedent('''\
            def f():
                """A docstring."""
                pass
        ''')
        lits = _extract_string_literals(source)
        assert "A docstring." in lits


class TestAllowlist:
    """Verify allowlist loading and matching."""

    def test_load_allowlist_from_file(self, tmp_path: Path):
        al_file = tmp_path / "allow.txt"
        al_file.write_text("example.com\n# comment\n\ntest@test.com\n")
        entries = _load_allowlist(str(al_file))
        assert "example.com" in entries
        assert "test@test.com" in entries
        assert len(entries) == 2  # comment and blank skipped

    def test_load_allowlist_none(self):
        assert _load_allowlist(None) == []

    def test_is_allowlisted_match(self):
        text = "user@example.com"
        assert _is_allowlisted(text, 0, len(text), ["example.com"]) is True

    def test_is_allowlisted_no_match(self):
        text = "user@real-company.com"
        assert _is_allowlisted(text, 0, len(text), ["example.com"]) is False


class TestScanDetection:
    """Verify the scanner detects PII in test sources."""

    def test_scan_finds_email(self, tmp_path: Path):
        """A file containing an email address is detected."""
        py_file = tmp_path / "has_email.py"
        py_file.write_text('contact = "john.doe@realcompany.org"\n')

        result = scan(tmp_path, allowlist=[])
        assert result["pii_detections"] >= 1
        assert "email" in result["detection_types"]

    def test_scan_finds_phone(self, tmp_path: Path):
        py_file = tmp_path / "has_phone.py"
        py_file.write_text('phone = "800-555-1234"\n')

        result = scan(tmp_path, allowlist=[])
        assert result["pii_detections"] >= 1
        assert "phone" in result["detection_types"]

    def test_scan_finds_ssn(self, tmp_path: Path):
        py_file = tmp_path / "has_ssn.py"
        py_file.write_text('ssn = "123-45-6789"\n')

        result = scan(tmp_path, allowlist=[])
        assert result["pii_detections"] >= 1
        assert "ssn" in result["detection_types"]

    def test_scan_allowlist_filters(self, tmp_path: Path):
        """Allowlisted patterns are excluded from results."""
        py_file = tmp_path / "safe.py"
        py_file.write_text('email = "test@example.com"\n')

        result = scan(tmp_path, allowlist=["example.com"])
        assert result["pii_detections"] == 0

    def test_clean_scan_no_detections(self, tmp_path: Path):
        """A clean file produces zero detections."""
        py_file = tmp_path / "clean.py"
        py_file.write_text('x = 42\ny = "hello"\n')

        result = scan(tmp_path, allowlist=[])
        assert result["pii_detections"] == 0
        assert result["files_scanned"] == 1


class TestMainExitCode:
    """Verify the CLI entry point returns correct exit codes."""

    def test_clean_returns_zero(self, tmp_path: Path):
        py_file = tmp_path / "clean.py"
        py_file.write_text('x = "no pii here"\n')

        exit_code = main(["--repo-root", str(tmp_path)])
        assert exit_code == 0

    def test_pii_returns_one(self, tmp_path: Path):
        py_file = tmp_path / "dirty.py"
        py_file.write_text('email = "john.doe@realcompany.org"\n')

        exit_code = main(["--repo-root", str(tmp_path)])
        assert exit_code == 1

    def test_allowlist_makes_clean(self, tmp_path: Path):
        py_file = tmp_path / "safe.py"
        py_file.write_text('email = "user@example.com"\n')

        al_file = tmp_path / "allowlist.txt"
        al_file.write_text("example.com\n")

        exit_code = main(
            [
                "--repo-root",
                str(tmp_path),
                "--allowlist",
                str(al_file),
            ]
        )
        assert exit_code == 0
