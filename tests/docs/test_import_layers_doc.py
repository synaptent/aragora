"""Keep docs/architecture/IMPORT_LAYERS.md in step with the `.importlinter` contract.

The current-membership table, the sanctioned seams and the TYPE_CHECKING policy are
facts about `.importlinter`; a tranche or seam change must update the page in the
same PR. The Partition A handover table changes with every server-site fix and is
validated against the live import graph by the mission evidence, not here.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "architecture" / "IMPORT_LAYERS.md"
DOCS_INDEX = REPO_ROOT / "docs" / "README.md"
CONFIG = REPO_ROOT / ".importlinter"
LAYERS = ("interface", "application", "domain", "infrastructure", "foundation")


def _config() -> tuple[configparser.ConfigParser, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(CONFIG, encoding="utf-8")
    contract = next(s for s in parser.sections() if parser.get(s, "type", fallback="") == "layers")
    return parser, contract


def _membership() -> dict[str, list[str]]:
    parser, contract = _config()
    lines = [ln.strip() for ln in parser.get(contract, "layers").splitlines() if ln.strip()]
    assert len(lines) == len(LAYERS)
    return {
        layer: [n.strip() for n in line.split(":") if n.strip()]
        for layer, line in zip(LAYERS, lines)
    }


def _section(heading_word: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(
        r"^#+[^\n]*" + heading_word + r"[^\n]*\n(.*?)(?=^#+ |\Z)", text, re.S | re.M | re.I
    )
    assert match, f"no section heading containing {heading_word!r}"
    return match.group(1)


def _table_rows(section: str) -> list[list[str]]:
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def test_docs_index_links_the_page() -> None:
    links = re.findall(r"\]\(([^)#\s]+)", DOCS_INDEX.read_text(encoding="utf-8"))
    targets = {(DOCS_INDEX.parent / link).resolve() for link in links}
    assert DOC.resolve() in targets


def test_current_table_matches_importlinter_membership_per_layer() -> None:
    rows = {row[0]: row for row in _table_rows(_section("current"))}
    for layer, names in _membership().items():
        row = rows[layer]
        assert int(row[1]) == len(names), layer
        assert re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", row[2]) == names, layer
    assert set(rows) == set(LAYERS)


def test_planned_table_keeps_every_current_member_on_its_layer() -> None:
    planned: dict[str, set[str]] = {layer: set() for layer in LAYERS}
    for row in _table_rows(_section("planned")):
        planned[row[0]] |= set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", row[-1]))
    for layer, names in _membership().items():
        assert set(names) <= planned[layer], layer


def test_seams_section_lists_exactly_the_ignore_imports() -> None:
    parser, contract = _config()
    configured = {
        line.strip()
        for line in parser.get(contract, "ignore_imports", fallback="").splitlines()
        if line.strip()
    }
    documented = set(re.findall(r"aragora\.[a-z_.]+ -> aragora\.[a-z_.]+", _section("seams")))
    assert documented == configured


def test_type_checking_policy_matches_config() -> None:
    parser, _ = _config()
    assert parser.get("importlinter", "exclude_type_checking_imports") == "True"
    assert "`exclude_type_checking_imports = True`" in DOC.read_text(encoding="utf-8")


def test_procedure_names_adopting_and_shrink_only_freeze() -> None:
    procedure = _section("tranche procedure")
    assert "check_import_contracts.py --freeze --adopt" in procedure
    assert re.search(r"check_import_contracts\.py --freeze\s*$", procedure, re.M)


def test_relative_links_resolve() -> None:
    links = re.findall(r"\]\(([^)#\s]+)", DOC.read_text(encoding="utf-8"))
    relative = [link for link in links if not re.match(r"[a-z]+:", link)]
    assert relative
    missing = [link for link in relative if not (DOC.parent / link).exists()]
    assert not missing, missing
