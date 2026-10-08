#!/usr/bin/env python3
"""
Golden Path 4: EU AI Act Compliance Check
==========================================

Run an EU AI Act compliance scan on an AI system decision. Uses Aragora's
compliance framework to classify risk level, generate a conformity report,
and produce audit-ready compliance artifacts.

This example covers:
  1. Risk classification under Article 6 + Annex III
  2. Conformity report generation from a decision receipt
  3. Article compliance mapping (Art. 9, 12, 13, 14, 15)

No API keys required -- works entirely with Aragora's compliance module.

Usage:
    python examples/golden_paths/compliance_check/main.py

Expected runtime: <2 seconds
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

# Allow running as a standalone script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from aragora.compliance.eu_ai_act import (
    ConformityReportGenerator,
    RiskClassifier,
)


# ----------------------------------------------------------------
# Sample decision receipt (simulating a real Aragora debate output)
# ----------------------------------------------------------------


def build_sample_receipt() -> dict[str, Any]:
    """Create a realistic decision receipt for an AI hiring system."""
    return {
        "receipt_id": "RCP-HR-2026-0312",
        "input_summary": (
            "Should we deploy the AI-powered candidate screening system to "
            "automate initial resume filtering for software engineering roles? "
            "The system uses NLP to score resumes against job requirements."
        ),
        "verdict": "approve_with_conditions",
        "verdict_reasoning": (
            "The screening system achieves 91% agreement with human recruiters "
            "on the validation set. However, demographic parity analysis shows "
            "a 6% gap in the gender dimension and a 4% gap in the age dimension. "
            "The system should not be deployed until bias mitigation reduces "
            "these gaps below acceptable thresholds."
        ),
        "confidence": 0.76,
        "robustness_score": 0.68,
        "risk_summary": {
            "total": 4,
            "critical": 0,
            "high": 2,
            "medium": 1,
            "low": 1,
        },
        "consensus_proof": {
            "method": "weighted_majority",
            "threshold": 0.66,
            "supporting_agents": ["claude-analyst", "mistral-auditor", "gpt4-ethics"],
            "dissenting_agents": ["gemini-challenger"],
            "agreement_ratio": 0.75,
        },
        "dissenting_views": [
            {
                "agent": "gemini-challenger",
                "view": (
                    "The 6% demographic parity gap exceeds acceptable thresholds "
                    "for employment AI under the EU AI Act. Delaying deployment "
                    "is the only responsible course of action."
                ),
            },
        ],
        "provenance_chain": [
            {
                "event_type": "debate_started",
                "timestamp": "2026-02-24T10:00:00Z",
                "actor": "system",
            },
            {
                "event_type": "proposal_submitted",
                "timestamp": "2026-02-24T10:01:00Z",
                "actor": "claude-analyst",
            },
            {
                "event_type": "critique_submitted",
                "timestamp": "2026-02-24T10:02:00Z",
                "actor": "gemini-challenger",
            },
            {
                "event_type": "vote_cast",
                "timestamp": "2026-02-24T10:04:00Z",
                "actor": "claude-analyst",
            },
            {
                "event_type": "vote_cast",
                "timestamp": "2026-02-24T10:04:01Z",
                "actor": "gpt4-ethics",
            },
            {
                "event_type": "vote_cast",
                "timestamp": "2026-02-24T10:04:02Z",
                "actor": "gemini-challenger",
            },
            {
                "event_type": "vote_cast",
                "timestamp": "2026-02-24T10:04:03Z",
                "actor": "mistral-auditor",
            },
            {
                "event_type": "human_approval",
                "timestamp": "2026-02-24T10:10:00Z",
                "actor": "hr-director@acme.com",
            },
            {
                "event_type": "receipt_generated",
                "timestamp": "2026-02-24T10:10:05Z",
                "actor": "system",
            },
        ],
        "config_used": {
            "protocol": "adversarial",
            "rounds": 2,
            "require_approval": True,
            "human_in_loop": True,
        },
        "artifact_hash": hashlib.sha256(b"golden-path-compliance-demo").hexdigest(),
    }


# ----------------------------------------------------------------
# Use cases for risk classification
# ----------------------------------------------------------------

CLASSIFICATION_EXAMPLES = [
    {
        "name": "Resume Screening AI",
        "description": (
            "AI-powered CV screening and recruitment decision system "
            "for filtering job applications in hiring processes"
        ),
    },
    {
        "name": "Customer Support Chatbot",
        "description": (
            "Virtual assistant chatbot providing generated content "
            "for product inquiries and order status"
        ),
    },
    {
        "name": "Weather Forecast Model",
        "description": (
            "Machine learning model for 7-day weather prediction "
            "using satellite imagery and historical data"
        ),
    },
]


def main() -> int:
    print("=" * 64)
    print("  Aragora Golden Path: EU AI Act Compliance Check")
    print("=" * 64)
    print()
    print("  Regulation (EU) 2024/1689 | Effective August 2, 2026")
    print("  Automated conformity assessment for AI decision receipts")
    print()

    # ----------------------------------------------------------------
    # Part 1: Risk Classification (Article 6 + Annex III)
    # ----------------------------------------------------------------
    print("--- Part 1: Risk Classification ---")
    print()

    classifier = RiskClassifier()

    for example in CLASSIFICATION_EXAMPLES:
        result = classifier.classify(example["description"])
        level = result.risk_level.value.upper()

        indicator = {
            "UNACCEPTABLE": "[PROHIBITED]",
            "HIGH": "[HIGH RISK] ",
            "LIMITED": "[LIMITED]   ",
            "MINIMAL": "[MINIMAL]   ",
        }.get(level, level)

        print(f"  {indicator}  {example['name']}")

        if result.annex_iii_category:
            print(
                f"              Annex III Category {result.annex_iii_number}: "
                f"{result.annex_iii_category}"
            )
        if result.matched_keywords:
            print(f"              Keywords: {', '.join(result.matched_keywords[:3])}")
        if result.obligations:
            print(f"              Obligations: {len(result.obligations)} article requirements")
        print()

    # ----------------------------------------------------------------
    # Part 2: Conformity Report from Decision Receipt
    # ----------------------------------------------------------------
    print("--- Part 2: Conformity Assessment Report ---")
    print()

    generator = ConformityReportGenerator()
    receipt = build_sample_receipt()
    report = generator.generate(receipt)

    print(f"  Receipt ID:     {receipt['receipt_id']}")
    print(f"  Risk Level:     {report.risk_classification.risk_level.value.upper()}")
    if report.risk_classification.annex_iii_category:
        print(
            f"  Annex III:      Cat. {report.risk_classification.annex_iii_number} "
            f"({report.risk_classification.annex_iii_category})"
        )
    print(f"  Overall Status: {report.overall_status.upper()}")
    print(f"  Report ID:      {report.report_id}")
    print(f"  Integrity Hash: {report.integrity_hash[:24]}...")
    print()

    # ----------------------------------------------------------------
    # Part 3: Article Compliance Table
    # ----------------------------------------------------------------
    print("--- Part 3: Article Compliance Mapping ---")
    print()
    print(f"  {'Article':<12s} {'Requirement':<42s} {'Status':<10s}")
    print(f"  {'-' * 12} {'-' * 42} {'-' * 10}")

    for mapping in report.article_mappings:
        status_display = {
            "satisfied": "PASS",
            "partial": "PARTIAL",
            "not_satisfied": "FAIL",
            "not_applicable": "N/A",
        }.get(mapping.status, mapping.status)

        req_short = mapping.requirement[:40]
        if len(mapping.requirement) > 40:
            req_short = req_short.rstrip() + ".."

        print(f"  {mapping.article:<12s} {req_short:<42s} {status_display:<10s}")

    print()

    # ----------------------------------------------------------------
    # Part 4: Recommendations and Dissent
    # ----------------------------------------------------------------
    if report.recommendations:
        print(f"--- Recommendations ({len(report.recommendations)}) ---")
        for i, rec in enumerate(report.recommendations, 1):
            print(f"  {i}. {rec[:80]}")
        print()

    dissenting = receipt.get("dissenting_views", [])
    if dissenting:
        print(f"--- Dissenting Views ({len(dissenting)}) ---")
        for dv in dissenting:
            print(f"  [{dv['agent']}]: {dv['view'][:80]}...")
        print()

    # ----------------------------------------------------------------
    # Part 5: Export Formats
    # ----------------------------------------------------------------
    print("--- Export Formats ---")

    json_output = report.to_json(indent=2)
    json_lines = json_output.split("\n")
    print(f"  JSON:     {len(json_output):,} bytes ({len(json_lines)} lines)")

    md_output = report.to_markdown()
    md_lines = md_output.split("\n")
    print(f"  Markdown: {len(md_output):,} bytes ({len(md_lines)} lines)")

    print()
    print("  Both formats are audit-ready for regulatory submission.")
    print("  JSON is machine-readable; Markdown is human-readable.")
    print()

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print("-" * 64)
    print("Compliance check complete. The EU AI Act module maps Aragora")
    print("decision receipts to regulatory requirements automatically.")
    print()
    print("Key articles covered: 6 (classification), 9 (risk management),")
    print("12 (record-keeping), 13 (transparency), 14 (human oversight),")
    print("15 (accuracy/robustness), 26 (deployer log retention).")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
