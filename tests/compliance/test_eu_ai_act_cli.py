"""Tests for EU AI Act CLI file output — Articles 9 and 15."""

from __future__ import annotations

import argparse
import json

import pytest


def _run_generate(receipt_file=None, output_dir=None, output_format="all"):
    """Run _cmd_eu_ai_act_generate with a temp dir and minimal args."""
    from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate

    args = argparse.Namespace(
        receipt_file=receipt_file,
        output=output_dir,
        provider_name="Test Org",
        provider_contact="test@example.com",
        eu_representative="",
        system_name="Test AI",
        system_version="1.0",
        output_format=output_format,
    )
    _cmd_eu_ai_act_generate(args)


class TestEuAiActCliFileOutput:
    def test_generates_article_9_file(self, tmp_path):
        """Article 9 risk management file is written alongside 12/13/14."""
        _run_generate(output_dir=str(tmp_path))
        art9 = tmp_path / "article_9_risk_management.json"
        assert art9.exists(), "article_9_risk_management.json not written"
        data = json.loads(art9.read_text())
        assert "integrity_hash" in data
        assert "identified_risks" in data

    def test_generates_article_15_file(self, tmp_path):
        """Article 15 accuracy/robustness file is written alongside 12/13/14."""
        _run_generate(output_dir=str(tmp_path))
        art15 = tmp_path / "article_15_accuracy_robustness.json"
        assert art15.exists(), "article_15_accuracy_robustness.json not written"
        data = json.loads(art15.read_text())
        assert "integrity_hash" in data
        assert "accuracy_metrics" in data

    def test_all_seven_files_present(self, tmp_path):
        """Symmetric output: 5 article files + bundle + conformity report files."""
        _run_generate(output_dir=str(tmp_path))
        expected = {
            "compliance_bundle.json",
            "conformity_report.md",
            "conformity_report.json",
            "article_9_risk_management.json",
            "article_12_record_keeping.json",
            "article_13_transparency.json",
            "article_14_human_oversight.json",
            "article_15_accuracy_robustness.json",
        }
        actual = {f.name for f in tmp_path.iterdir()}
        assert expected == actual

    def test_json_only_format_excludes_article_files(self, tmp_path):
        """With output_format='json', only bundle JSON is written (no per-article files)."""
        _run_generate(output_dir=str(tmp_path), output_format="json")
        files = {f.name for f in tmp_path.iterdir()}
        assert "compliance_bundle.json" in files
        assert "article_9_risk_management.json" not in files
        assert "article_15_accuracy_robustness.json" not in files

    def test_summary_output_mentions_all_articles(self, tmp_path, capsys):
        """Console summary lists article 9 and 15 filenames."""
        _run_generate(output_dir=str(tmp_path))
        captured = capsys.readouterr()
        assert "article_9" in captured.out
        assert "article_15" in captured.out
