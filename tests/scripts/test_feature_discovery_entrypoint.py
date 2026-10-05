from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_DISCOVERY = REPO_ROOT / "docs" / "FEATURE_DISCOVERY.md"
CANONICAL = REPO_ROOT / "docs" / "status" / "FEATURE_DISCOVERY.md"

LEGACY_SECTION_ANCHORS = [
    "1-core-debate-features",
    "2-agent-system",
    "3-memory--learning",
    "4-knowledge-management",
    "5-enterprise-features",
    "6-integrations--connectors",
    "7-observability--monitoring",
    "8-developer-tools",
    "9-self-improvement--nomic-loop",
]


def _github_slug(heading: str) -> str:
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def test_root_feature_discovery_is_a_truthful_entrypoint() -> None:
    content = FEATURE_DISCOVERY.read_text(encoding="utf-8")

    assert "Compatibility entrypoint for older links" in content
    assert "[status/FEATURE_DISCOVERY.md](status/FEATURE_DISCOVERY.md)" in content

    stale_claims = [
        "3,000+ Python modules",
        "153,000+ tests",
        "3,000+ API operations across 2,600+ paths",
        "Debate spectating includes live SSE on `/api/v1/spectate/stream`",
    ]
    for claim in stale_claims:
        assert claim not in content


def test_root_feature_discovery_is_a_short_redirect_stub() -> None:
    lines = [
        line for line in FEATURE_DISCOVERY.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert len(lines) <= 5
    first_md_link = re.search(r"\]\(([^)#]+\.md)", "\n".join(lines))
    assert first_md_link is not None
    assert first_md_link.group(1) == "status/FEATURE_DISCOVERY.md"


def test_root_feature_discovery_links_legacy_sections_to_canonical_headings() -> None:
    content = FEATURE_DISCOVERY.read_text(encoding="utf-8")
    canonical_slugs = {
        _github_slug(match.group(1))
        for match in re.finditer(
            r"^#{1,6}\s+(.+)$", CANONICAL.read_text(encoding="utf-8"), re.MULTILINE
        )
    }

    for anchor in LEGACY_SECTION_ANCHORS:
        assert f"(status/FEATURE_DISCOVERY.md#{anchor})" in content
        assert anchor in canonical_slugs
