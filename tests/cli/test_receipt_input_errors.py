"""Receipt file input failures stay diagnostic, nonzero, and traceback-free."""

from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from aragora.cli.commands.receipt import (
    cmd_receipt_export,
    cmd_receipt_inspect,
    cmd_receipt_verify,
)

COMMANDS = (cmd_receipt_inspect, cmd_receipt_verify, cmd_receipt_export)
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    "content", [b"\xff", b"{broken", b"[]", b"null", b"true", b"42", b'"text"']
)
def test_invalid_receipt_input_has_no_success_output(
    command, content: bytes, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "receipt.json"
    source.write_bytes(content)
    output = tmp_path / "export.json"
    output.write_bytes(b"preserve existing output")
    args = argparse.Namespace(receipt=str(source), format="json", output=str(output))

    with pytest.raises(SystemExit) as exc:
        command(args)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err
    assert output.read_bytes() == b"preserve existing output"


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("kind", ["missing", "directory", "permission", "read_failure"])
def test_unreadable_receipt_input(
    command, kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "receipt.json"
    args = argparse.Namespace(receipt=str(source), format="json", output=None)
    if kind == "directory":
        source.mkdir()
    if kind in {"permission", "read_failure"}:
        source.write_text("{}", encoding="utf-8")
        error = (
            PermissionError(errno.EACCES, "Permission denied", str(source))
            if kind == "permission"
            else OSError(errno.EIO, "Input/output error", str(source))
        )
        with patch.object(Path, "read_text", side_effect=error):
            with pytest.raises(SystemExit) as exc:
                command(args)
    else:
        with pytest.raises(SystemExit) as exc:
            command(args)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(source) in captured.err
    assert "Error:" in captured.err


@pytest.mark.parametrize("action", ["inspect", "verify", "export"])
def test_invalid_encoding_through_cli_process(action: str, tmp_path: Path) -> None:
    source = tmp_path / "invalid-utf8.json"
    source.write_bytes(b"\xff")
    result = subprocess.run(
        [sys.executable, "-m", "aragora.cli.main", "receipt", action, str(source)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_export_path_inspection_error_does_not_fall_back_to_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "receipt.json"
    error = PermissionError(errno.EACCES, "Permission denied", str(source))
    with patch.object(Path, "exists", side_effect=error):
        with patch("aragora.cli.commands.receipt._load_storage_receipt") as storage:
            with pytest.raises(SystemExit) as exc:
                cmd_receipt_export(
                    argparse.Namespace(receipt=str(source), format="json", output=None)
                )
    assert exc.value.code == 1
    storage.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(source) in captured.err
