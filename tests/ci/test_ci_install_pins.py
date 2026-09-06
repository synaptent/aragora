"""Every shared install-script pin must mirror the test extra."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN = r"([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^]]+\])?\s*([><=!~][^\"'\n]*)"


def parse_pin(pin: str) -> tuple[str, str]:
    match = re.fullmatch(PIN, pin.strip())
    assert match, f"Invalid version pin: {pin}"
    name, specifier = match.groups()
    return re.sub(r"[-_.]+", "-", name).lower(), re.sub(r"\s+", "", specifier)


def test_ci_install_pins_match_test_extra() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    expected = dict(map(parse_pin, project["project"]["optional-dependencies"]["test"]))
    script = (ROOT / "scripts/ci_install_project.sh").read_text()
    # Keep every occurrence, including duplicate names in different arrays.
    pins = [parse_pin(match.group(1)) for match in re.finditer(rf"""["']({PIN})["']""", script)]
    shared = [(name, specifier) for name, specifier in pins if name in expected]
    assert shared, "No shared pins found; check the install-script parser"
    mismatches = [
        f"{name}: script {specifier} != test extra {expected[name]}"
        for name, specifier in shared
        if specifier != expected[name]
    ]
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.parametrize(
    ("pin", "expected"),
    [
        ("PyYAML>=6.0.3,<7.0", ("pyyaml", ">=6.0.3,<7.0")),
        (" PyTest_Xdist >= 3.8.0, < 4.0 ", ("pytest-xdist", ">=3.8.0,<4.0")),
        ("uvicorn[standard]>=0.50.0,<1.0", ("uvicorn", ">=0.50.0,<1.0")),
    ],
)
def test_parse_pin_normalizes_names_and_whitespace(pin: str, expected: tuple[str, str]) -> None:
    assert parse_pin(pin) == expected
