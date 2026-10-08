"""Guards for public first-run demo documentation."""

from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")


REPO_ROOT = Path(__file__).resolve().parents[2]


def _section_between(text: str, start: str, end: str) -> str:
    assert start in text
    assert end in text
    after_start = text.split(start, 1)[1]
    return after_start.split(end, 1)[0]


def _line_containing(text: str, needle: str) -> str:
    matches = [line for line in text.splitlines() if needle in line]
    assert len(matches) == 1
    return matches[0]


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def test_readme_advertises_current_pypi_receipt_round_trip() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    collapsed_readme = _collapsed(readme)
    pypi_try_it_now = _section_between(
        readme,
        "Current PyPI package:",
        "Current source checkout:",
    )
    source_try_it_now = _section_between(
        readme,
        "Current source checkout:",
        "Live review with a provider key:",
    )
    live_review = _section_between(
        readme,
        "Live review with a provider key:",
        "## Core workflows",
    )
    pypi_table_row = _line_containing(readme, "Run the current PyPI zero-key receipt demo")

    assert "pip install -U 'aragora>=2.9.0' && aragora demo --offline" in readme
    assert "--offline" in pypi_table_row
    assert "--receipt" in pypi_table_row
    assert "receipt verify" in pypi_table_row
    assert "aragora demo --offline --receipt aragora-demo-receipt.json" in pypi_try_it_now
    assert "aragora receipt verify aragora-demo-receipt.json" in pypi_try_it_now
    assert "Current source checkout:" in readme
    assert "Use `aragora>=2.9.0` for the explicit offline demo receipt round trip" in readme
    assert "Earlier PyPI releases do not support the `--offline` receipt flags" in collapsed_readme
    assert "aragora demo --offline --receipt aragora-demo-receipt.json" in source_try_it_now
    assert "aragora receipt verify aragora-demo-receipt.json" in source_try_it_now
    assert (
        "aragora receipt export aragora-demo-receipt.json --format odr -o receipt.odr.json"
        in source_try_it_now
    )
    assert "aragora receipt export" not in live_review


def test_pypi_long_description_advertises_zero_key_receipt_round_trip() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_readme = pyproject["project"]["readme"]

    assert package_readme["content-type"] == "text/markdown"
    description = package_readme["text"]
    assert "pip install aragora" in description
    assert "aragora demo --offline --receipt aragora-demo-receipt.json" in description
    assert "aragora receipt verify aragora-demo-receipt.json" in description
    assert "https://github.com/synaptent/aragora#readme" in description
    assert "https://pypi.org/project/aragora-debate/" in description
    assert "aragora-debate/ subproject" not in description


def test_quickstart_advertises_current_pypi_receipt_round_trip() -> None:
    quickstart = (REPO_ROOT / "docs" / "quickstart.md").read_text()
    collapsed_quickstart = _collapsed(quickstart)
    pypi_section = _section_between(
        quickstart,
        "Current PyPI package:",
        "Current source checkout:",
    )
    source_section = quickstart.split("Current source checkout:", 1)[1]

    assert "Current PyPI package" in quickstart
    assert "Current source checkout" in quickstart
    assert "pip install -U 'aragora>=2.9.0'" in pypi_section
    assert "aragora demo --offline --receipt aragora-demo-receipt.json" in pypi_section
    assert "aragora receipt verify aragora-demo-receipt.json" in pypi_section
    assert "aragora demo --offline --receipt aragora-demo-receipt.json" in source_section
    assert "aragora receipt verify aragora-demo-receipt.json" in source_section
    assert "Use `aragora>=2.9.0` for the explicit offline demo receipt round trip" in quickstart
    assert (
        "Earlier PyPI releases do not support the `--offline` receipt flags" in collapsed_quickstart
    )
