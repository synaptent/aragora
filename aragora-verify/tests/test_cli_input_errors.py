"""File and decode errors retain the standalone CLI's input-error exit code."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from aragora_verify.cli import main

from _fixtures import valid_odr


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("target", ["receipt", "pubkey", "chain"])
@pytest.mark.parametrize("kind", ["missing", "directory", "permission", "read_failure"])
def test_unreadable_input_returns_two(
    target: str, kind: str, json_output: bool, tmp_path: Path, capsys
) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(valid_odr()), encoding="utf-8")
    unreadable = tmp_path / "unreadable"
    if kind == "directory":
        unreadable.mkdir()
    args = (
        [str(unreadable)] if target == "receipt" else [str(receipt), f"--{target}", str(unreadable)]
    )
    if json_output:
        args.append("--json")
    if kind in {"permission", "read_failure"}:
        real_open = open

        def failing_open(path, *open_args, **open_kwargs):
            if str(path) == str(unreadable):
                if kind == "permission":
                    raise PermissionError(errno.EACCES, "Permission denied", str(path))
                raise OSError(errno.EIO, "Input/output error", str(path))
            return real_open(path, *open_args, **open_kwargs)

        with patch("builtins.open", side_effect=failing_open):
            rc = main(args)
    else:
        rc = main(args)

    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
    assert str(unreadable) in captured.err


@pytest.mark.parametrize("target", ["receipt", "chain"])
@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("content", [b"\xff", b"{broken"])
def test_invalid_text_input_returns_two(target, json_output, content, tmp_path, capsys) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(valid_odr()), encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(content)
    args = [str(invalid)] if target == "receipt" else [str(receipt), "--chain", str(invalid)]
    if json_output:
        args.append("--json")
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


@pytest.mark.parametrize("content", [[], None, True, 42, "text"])
def test_wrong_top_level_shape_remains_verification_failure(content, tmp_path, capsys) -> None:
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(content), encoding="utf-8")
    assert main([str(source), "--json"]) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["ok"] is False
    assert result["checks"][0]["name"] == "schema_conformance"
    assert result["checks"][0]["status"] == "fail"
    assert captured.err == ""


@pytest.mark.parametrize("kind", ["directory", "invalid_encoding"])
def test_input_errors_through_module_process(kind: str, tmp_path: Path) -> None:
    source = tmp_path / "receipt.json"
    if kind == "directory":
        source.mkdir()
    else:
        source.write_bytes(b"\xff")
    result = subprocess.run(
        [sys.executable, "-m", "aragora_verify", str(source), "--json"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
