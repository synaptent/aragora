"""Tests for the aragora triage CLI command."""

from __future__ import annotations

from unittest.mock import patch

from aragora.cli.commands.triage import add_triage_parser, cmd_triage, _show_status


def test_add_triage_parser_registers():
    """Parser registration creates 'triage' subcommand."""
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_triage_parser(sub)

    args = parser.parse_args(["triage", "run", "--batch", "3"])
    assert args.command == "triage"
    assert args.triage_command == "run"
    assert args.batch == 3


def test_add_triage_parser_auto_approve():
    """--auto-approve flag is parsed."""
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_triage_parser(sub)

    args = parser.parse_args(["triage", "run", "--auto-approve"])
    assert args.auto_approve is True


def test_add_triage_parser_status():
    """Status subcommand is parsed."""
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_triage_parser(sub)

    args = parser.parse_args(["triage", "status"])
    assert args.triage_command == "status"


def test_show_status_runs(capsys):
    """Status command prints config without crashing."""
    _show_status()
    captured = capsys.readouterr()
    assert "Gmail configured:" in captured.out
    assert "Durable signing key:" in captured.out


def test_cmd_triage_dispatches_status(capsys):
    """cmd_triage dispatches to _show_status for status command."""
    import argparse

    args = argparse.Namespace(triage_command="status")
    cmd_triage(args)
    captured = capsys.readouterr()
    assert "Inbox Triage Status" in captured.out


def test_cmd_triage_no_command_exits():
    """cmd_triage exits with error when no subcommand given."""
    import argparse
    import pytest

    args = argparse.Namespace(triage_command=None)
    with pytest.raises(SystemExit) as exc_info:
        cmd_triage(args)
    assert exc_info.value.code == 1
