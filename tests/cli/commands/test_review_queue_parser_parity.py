"""Parity tests for the two record-settlement parser registration surfaces.

The main CLI (``aragora.cli.parser``) and the standalone review-queue CLI
(``aragora.cli.commands.review_queue.add_review_queue_parser``, which routes
through ``review_queue_parsers.add_record_settlement_parser``) must expose an
identical record-settlement option surface. Three consecutive live settlements
(#9817, #9822, #9858 lineage) hit drift between the two registrations, so the
comparison is structural: ``(option_strings, dest, required, choices)`` for
every action, not just flag presence.
"""

from __future__ import annotations

import argparse

import pytest

from aragora.cli.commands.review_queue import add_review_queue_parser
from aragora.cli.parser import build_parser


def _subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError(f"no subparsers registered on {parser.prog!r}")


def _record_settlement_parser(root: argparse.ArgumentParser) -> argparse.ArgumentParser:
    review_queue = _subparsers_action(root).choices["review-queue"]
    return _subparsers_action(review_queue).choices["record-settlement"]


def _main_cli_root() -> argparse.ArgumentParser:
    return build_parser()


def _standalone_root() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="review-queue-standalone")
    add_review_queue_parser(root.add_subparsers(dest="command"))
    return root


def _option_surface(
    parser: argparse.ArgumentParser,
) -> set[tuple[tuple[str, ...], str, bool, tuple[str, ...] | None]]:
    surface: set[tuple[tuple[str, ...], str, bool, tuple[str, ...] | None]] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        choices = tuple(str(c) for c in action.choices) if action.choices is not None else None
        surface.add(
            (
                tuple(action.option_strings),
                str(action.dest),
                bool(action.required),
                choices,
            )
        )
    return surface


class TestRecordSettlementParserParity:
    def test_surfaces_expose_identical_option_tuples(self) -> None:
        main_surface = _option_surface(_record_settlement_parser(_main_cli_root()))
        standalone_surface = _option_surface(_record_settlement_parser(_standalone_root()))

        assert main_surface == standalone_surface, (
            "record-settlement registrations diverged:\n"
            f"main CLI only: {sorted(main_surface - standalone_surface)}\n"
            f"standalone only: {sorted(standalone_surface - main_surface)}"
        )

    def test_main_cli_registers_post_github_status(self) -> None:
        args = _main_cli_root().parse_args(
            [
                "review-queue",
                "record-settlement",
                "9817",
                "--head-sha",
                "017d33990628ed8a3369dfb600cafcc0a6548bc7",
                "--action",
                "approve",
                "--reason",
                "exact-head operator settlement",
                "--post-github-status",
            ]
        )

        assert args.post_github_status is True
        assert args.github_status_context == "aragora/human-settlement"

    def test_main_cli_post_github_status_defaults_off(self) -> None:
        args = _main_cli_root().parse_args(
            [
                "review-queue",
                "record-settlement",
                "9817",
                "--head-sha",
                "017d33990628ed8a3369dfb600cafcc0a6548bc7",
                "--action",
                "approve",
                "--reason",
                "exact-head operator settlement",
            ]
        )

        assert args.post_github_status is False

    def test_main_cli_github_status_context_override(self) -> None:
        args = _main_cli_root().parse_args(
            [
                "review-queue",
                "record-settlement",
                "9817",
                "--head-sha",
                "017d33990628ed8a3369dfb600cafcc0a6548bc7",
                "--action",
                "approve",
                "--reason",
                "exact-head operator settlement",
                "--post-github-status",
                "--github-status-context",
                "aragora/custom-settlement",
            ]
        )

        assert args.github_status_context == "aragora/custom-settlement"

    @pytest.mark.parametrize("root_factory", [_main_cli_root, _standalone_root])
    def test_reason_stays_mandatory_on_both_surfaces(self, root_factory) -> None:
        # Original registration semantics, not drift: recording an external
        # settlement without an operator reason must be rejected at parse time.
        with pytest.raises(SystemExit):
            root_factory().parse_args(
                [
                    "review-queue",
                    "record-settlement",
                    "9817",
                    "--head-sha",
                    "017d33990628ed8a3369dfb600cafcc0a6548bc7",
                    "--action",
                    "approve",
                ]
            )
