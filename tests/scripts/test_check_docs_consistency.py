from __future__ import annotations

import re
import textwrap
from pathlib import Path

from scripts import check_docs_consistency as docs_consistency
from scripts.check_docs_consistency import (
    check_archive_references,
    check_broken_links,
    check_gh_hygiene,
    check_metric_drift,
    check_tier_contradictions,
    delayed_codes,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")


def test_check_1_reports_missing_files_and_bad_anchors(tmp_path: Path) -> None:
    root = tmp_path
    _write(
        root / "docs" / "README.md",
        """
        # Target Doc

        ## Part 1: Stable Heading
        """,
    )
    _write(root / "docs" / "archive" / "OLD.md", "[missing](../gone.md)")
    _write(
        root / "README.md",
        """
        [ok](docs/README.md#part-1-stable-heading)
        [bad file](docs/MISSING.md)
        [bad anchor](docs/README.md#not-present)
        """,
    )

    findings, fixed = check_broken_links(root)

    assert fixed == 0
    assert [finding.location for finding in findings] == ["README.md:2", "README.md:3"]
    assert "docs/MISSING.md" in findings[0].message
    assert "not-present" in findings[1].message


def test_check_1_fix_uses_strategy_index_single_candidate(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "docs" / "strategy" / "PRECISION_AND_TERMS.md", "## Part 1: Glossary")
    _write(
        root / "docs" / "STRATEGY_INDEX.md",
        """
        | Old file | New location |
        |----------|-------------|
        | `TERMINOLOGY_GLOSSARY.md` | `strategy/PRECISION_AND_TERMS.md` Part 1 |
        """,
    )
    source = root / "docs" / "guide.md"
    _write(source, "[terms](strategy/TERMINOLOGY_GLOSSARY.md)")

    findings, fixed = check_broken_links(root, fix=True)

    assert findings == []
    assert fixed == 1
    assert "[terms](strategy/PRECISION_AND_TERMS.md#part-1)" in source.read_text()
    second_findings, second_fixed = check_broken_links(root, fix=True)
    assert second_findings == []
    assert second_fixed == 0


def test_check_1_ignores_markdown_syntax_inside_inline_code(tmp_path: Path) -> None:
    root = tmp_path
    _write(
        root / "docs" / "metrics.md",
        r"""
        Reproduce with `git grep -h -o -E "@require_permission\(['\"]([^'\"]+)['\"]\)" -- aragora`.
        """,
    )

    findings, fixed = check_broken_links(root)

    assert fixed == 0
    assert findings == []


def test_check_2_flags_live_archive_refs_except_allowed_sources(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "docs" / "archive" / "README.md", "# Archive")
    _write(root / "docs" / "archive" / "OLD.md", "# Old")
    _write(root / "docs" / "STRATEGY_INDEX.md", "[old](archive/OLD.md)")
    _write(root / "docs" / "OMNIVOROUS_ROADMAP.md", "[snapshot](archive/OLD.md)")
    _write(root / "docs" / "live.md", "[snapshot](archive/OLD.md)")

    findings = check_archive_references(root)

    assert len(findings) == 1
    assert findings[0].location == "docs/live.md:1"
    assert "archive/OLD.md" in findings[0].message


def test_check_3_flags_metric_drift_against_canonical_table(tmp_path: Path) -> None:
    root = tmp_path
    _write(
        root / "docs" / "CANONICAL_GOALS.md",
        """
        | Metric | Value | Source |
        |--------|-------|--------|
        | Python modules | 3,800+ | count |
        | Automated tests | 210,000+ | count |
        | API operations | 3,100+ across 2,600+ paths | spec |
        | Knowledge Mound adapters | 42 registered adapter specs | registry |
        | Agent types | 43 across 6+ LLM providers | registry |
        """,
    )
    _write(root / "docs" / "live.md", "Knowledge Mound has 45 adapters.")
    _write(root / "docs" / "small.md", "This module has 12 tests.")
    _write(root / "docs" / "status" / "snapshot.md", "The old run had 45 adapters.")

    findings = check_metric_drift(root)

    assert len(findings) == 1
    assert findings[0].location == "docs/live.md:1"
    assert "45 adapters" in findings[0].message
    assert "42 adapters" in findings[0].message


def test_check_4_flags_p0_p1_rows_linking_delayed_codes_or_issues(tmp_path: Path) -> None:
    root = tmp_path
    _write(
        root / "docs" / "status" / "NEXT_STEPS_CANONICAL.md",
        """
        # Next Steps

        ### Delay

        - `DIC-13..14` until Foreman proof is stable
        - `TW-07..09` until the wedge is reliable
        """,
    )
    _write(
        root / "docs" / "plans" / "EPISTEMIC_CI_AND_CRUX_ENGINE.md",
        """
        ### DIC-13: Executable Claim Manifest
        Issue: [#6023](https://github.com/synaptent/aragora/issues/6023)
        """,
    )
    _write(
        root / "docs" / "FEATURE_GAP_LIST.md",
        """
        ## P0 - Now
        | Feature | Status | Notes |
        |---|---|---|
        | Crux | Ready | Tracked in [#6023](https://github.com/synaptent/aragora/issues/6023). |
        ## P2 - Later
        | Feature | Status | Notes |
        |---|---|---|
        | Crux later | Gated | Mentions `DIC-14`. |
        """,
    )

    assert {"DIC-13", "DIC-14", "TW-07", "TW-08", "TW-09"} <= delayed_codes(root)
    findings = check_tier_contradictions(root)

    assert len(findings) == 1
    assert findings[0].location == "docs/FEATURE_GAP_LIST.md:4"
    assert "DIC-13" in findings[0].message


def test_check_5_tracks_duplicate_tw_issue_codes(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "docs" / "plans" / "EPISTEMIC_CI_AND_CRUX_ENGINE.md", "# Plan")
    _write(root / "docs" / "status" / "NEXT_STEPS_CANONICAL.md", "# Next Steps")
    monkeypatch.setenv("AIRSCRIPT_CHECK_GH", "1")
    monkeypatch.setattr(docs_consistency.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(
        docs_consistency,
        "run_gh_issue_list",
        lambda _root: [
            {"number": 101, "title": "[TW-03] First lane", "body": "", "labels": []},
            {"number": 102, "title": "Follow-up", "body": "Tracks TW-03", "labels": []},
        ],
    )

    findings = check_gh_hygiene(root).findings

    assert [finding.message for finding in findings] == [
        "potential duplicate tracked code TW-03: issues #101, #102"
    ]


def test_dormant_capabilities_have_activation_contracts() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs" / "FEATURE_GAP_LIST.md").read_text(encoding="utf-8")
    section = text.split("## Built But Dormant", 1)[1].split(
        "### Dormant-Module Disposition Policy", 1
    )[0]
    table_lines = [line for line in section.splitlines() if line.startswith("|")]
    header = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    assert header == [
        "Capability",
        "Where it lives",
        "Verified state (2026-07-11)",
        "Activation trigger",
        "Minimum first exposure",
        "Owner issue",
    ]

    rows: dict[str, list[str]] = {}
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 6
        rows[cells[0]] = cells

    assert set(rows) == {
        "Crux detector",
        "Blockchain / ERC-8004",
        "Marketplace + skills",
        "Verticals",
        "Genesis",
        "Broadcast",
        "Tournaments",
        "Inbox trust wedge",
        "Pareto provider router",
        "Tamper-evident audit trail",
    }
    owner_issues: dict[str, str] = {}
    for capability, cells in rows.items():
        assert cells[3], capability
        assert cells[4], capability
        issue_links = re.findall(r"https://github\.com/synaptent/aragora/issues/(\d+)", cells[5])
        assert len(issue_links) == 1, capability
        owner_issues[capability] = issue_links[0]

    assert {capability for capability, issue in owner_issues.items() if issue == "9046"} == {
        "Blockchain / ERC-8004",
        "Marketplace + skills",
        "Verticals",
        "Genesis",
        "Broadcast",
        "Tournaments",
        "Inbox trust wedge",
        "Tamper-evident audit trail",
    }

    policy = text.split("### Dormant-Module Disposition Policy", 1)[1]
    assert "Integrate or park by default; do not archive for tidiness" in policy
    assert "One activation path and one open owner issue per row" in policy
    assert "#9046](https://github.com/synaptent/aragora/issues/9046) is the standing-open" in policy
    assert "It must remain\n   open while any row names it" in policy
    assert "Activation requires external evidence" in policy
