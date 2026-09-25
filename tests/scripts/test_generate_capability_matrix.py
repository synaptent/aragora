from __future__ import annotations

from pathlib import Path

import pytest

import scripts.generate_capability_matrix as generate_capability_matrix


def test_static_cli_count_matches_runtime_parser() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert generate_capability_matrix._count_cli_commands_static(
        repo_root
    ) == generate_capability_matrix._count_cli_commands(repo_root)


@pytest.mark.parametrize(
    "import_line",
    [
        "from aragora.cli.synthetic_registration import register_commands as install",
        "from .synthetic_registration import register_commands as install",
    ],
)
def test_static_cli_count_discovers_imported_two_argument_registration(
    tmp_path: Path, import_line: str
) -> None:
    cli = tmp_path / "aragora" / "cli"
    cli.mkdir(parents=True)
    (cli / "parser.py").write_text(
        f"""raise AssertionError("parser must not execute")
{import_line}

def build_parser():
    subparsers = parser.add_subparsers()
    install(subparsers, lazy)
    _add_direct(subparsers)

def _add_direct(subparsers):
    subparsers.add_parser("direct", aliases=["d"])
""",
        encoding="utf-8",
    )
    (cli / "synthetic_registration.py").write_text(
        """raise AssertionError("helper must not execute")

def register_commands(subparsers, lazy):
    first = subparsers.add_parser("delegated", aliases=("alias",))
    nested = first.add_subparsers()
    nested.add_parser("not-top-level")
    subparsers.add_parser("second")
""",
        encoding="utf-8",
    )

    # Two direct choices and three imported choices, not one guessed delegate.
    assert generate_capability_matrix._count_cli_commands_static(tmp_path) == 5
