"""``docs/architecture/MODEL_CATALOG.md``'s table must match ``CATALOG``.

The document embeds the exact snippet that generates its own table and says
"never hand-edit the rows, they will drift the moment a price or id changes
underneath them" -- but nothing checked, and it drifted: by the 2026-09-05
wave-2 re-review it listed 26 of 28 rows, missing ``mistral-large-2411`` and
``claude-haiku-4-5-20251001`` entirely.

This test IS the check. It re-runs the document's own generator and asserts
the rendered table appears verbatim, so the doc can only go stale by failing
here first.
"""

from __future__ import annotations

import re
from pathlib import Path

from aragora.models.catalog import CATALOG

DOC = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "MODEL_CATALOG.md"


def _render_table() -> str:
    """The generator embedded in the document, verbatim."""
    rows = sorted(CATALOG.values(), key=lambda s: (s.family, s.tier != "flagship", s.canonical_id))
    lines = [
        "| Family | Canonical ID | Direct ID | OpenRouter slug | $/1M in | $/1M out | Context | Tier | Retired |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for s in rows:
        lines.append(
            f"| {s.family} | `{s.canonical_id}` | `{s.direct_id}` | `{s.openrouter_id}` | "
            f"{s.input_per_mtok:g} | {s.output_per_mtok:g} | {s.context_window:,} | "
            f"{s.tier} | {s.retired} |"
        )
    return "\n".join(lines)


def test_document_table_matches_the_catalog() -> None:
    text = DOC.read_text(encoding="utf-8")
    expected = _render_table()
    assert expected in text, (
        "docs/architecture/MODEL_CATALOG.md's table has drifted from CATALOG. "
        "Re-run the generator embedded in the document and paste the result:\n\n"
        f"{expected}"
    )


def test_document_row_count_matches_the_catalog() -> None:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(r"Output as of this commit \((\d+) rows\):", text)
    assert match is not None, "the row-count line is gone; the doc's shape changed"
    assert int(match.group(1)) == len(CATALOG)


def test_every_retired_row_is_named_in_the_retired_paragraph() -> None:
    """Retired rows are kept on purpose, and the document explains which
    ones and why -- a list that silently omits one is the same drift."""
    text = DOC.read_text(encoding="utf-8")
    paragraph = text.split("Retired rows (", 1)[1].split(") are kept in `CATALOG`", 1)[0]
    named = set(re.findall(r"`([^`]+)`", paragraph))
    retired = {s.canonical_id for s in CATALOG.values() if s.retired}
    assert named == retired, f"doc names {sorted(named)}, catalog has {sorted(retired)}"
