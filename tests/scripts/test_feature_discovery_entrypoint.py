from __future__ import annotations

import re
from pathlib import Path

from scripts.validate_doc_links import HEADING_RE, github_slug


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

ANCHOR_TAG = re.compile(r"<a\s[^>]*>", re.IGNORECASE)
# Stricter than HTML_ID_RE in validate_doc_links.py, which also matches data-id= attributes.
ANCHOR_ATTRIBUTE = re.compile(r"""(?<![\w-])(?:id|name)=["']([^"']+)["']""", re.IGNORECASE)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _outside_fences(text: str) -> str:
    # CommonMark: only the opener's character, at least as long and with nothing after it, closes a
    # fence, so a ```` block can quote ``` examples.
    kept: list[str] = []
    opener = ""
    for line in text.splitlines():
        fence = FENCE.match(line)
        if opener:
            if (
                fence
                and fence.group(1)[0] == opener[0]
                and len(fence.group(1)) >= len(opener)
                and not fence.group(2).strip()
            ):
                opener = ""
            kept.append("")
        elif fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
            opener = fence.group(1)
            kept.append("")
        else:
            kept.append(line)
    return "\n".join(kept)


def _heading_offsets(text: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        heading = HEADING_RE.match(line.rstrip("\r\n"))
        if heading:
            found.append((github_slug(heading.group(1).strip()), offset))
        offset += len(line)
    return found


def _anchor_offsets(content: str) -> dict[str, list[int]]:
    definitions = [
        (value, tag.start())
        for tag in ANCHOR_TAG.finditer(content)
        # <a name="x" id="x"> defines one anchor, not a duplicate.
        for value in dict.fromkeys(ANCHOR_ATTRIBUTE.findall(tag.group(0)))
    ]
    definitions += _heading_offsets(content)
    offsets: dict[str, list[int]] = {}
    for name, offset in sorted(definitions, key=lambda item: item[1]):
        offsets.setdefault(name, []).append(offset)
    return offsets


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
        slug for slug, _ in _heading_offsets(_outside_fences(CANONICAL.read_text(encoding="utf-8")))
    }

    for anchor in LEGACY_SECTION_ANCHORS:
        assert f"(status/FEATURE_DISCOVERY.md#{anchor})" in content
        assert anchor in canonical_slugs


def test_root_feature_discovery_keeps_legacy_section_anchors() -> None:
    # Links written before this page became a stub still target the old section fragments.
    content = _outside_fences(FEATURE_DISCOVERY.read_text(encoding="utf-8"))
    offsets = _anchor_offsets(content)

    missing = [anchor for anchor in LEGACY_SECTION_ANCHORS if anchor not in offsets]
    assert not missing, f"legacy anchors missing from docs/FEATURE_DISCOVERY.md: {missing}"
    duplicated = [anchor for anchor in LEGACY_SECTION_ANCHORS if len(offsets[anchor]) > 1]
    assert not duplicated, f"legacy anchors defined more than once: {duplicated}"

    starts = sorted(offsets[anchor][0] for anchor in LEGACY_SECTION_ANCHORS)
    for anchor in LEGACY_SECTION_ANCHORS:
        start = offsets[anchor][0]
        end = min((offset for offset in starts if offset > start), default=len(content))
        assert f"(status/FEATURE_DISCOVERY.md#{anchor})" in content[start:end], anchor
