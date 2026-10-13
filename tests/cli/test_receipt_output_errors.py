"""Export destination failures are unsuccessful, diagnostic, and traceback-free."""

from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from aragora.cli.commands.receipt import cmd_receipt_export
from aragora.gauntlet.receipt_models import DecisionReceipt

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def receipt_path(tmp_path: Path) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps(
            {
                "receipt_id": "output-contract",
                "gauntlet_id": "output-contract",
                "timestamp": "2026-09-13T00:00:00Z",
                "verdict": "PASS",
                "confidence": 0.8,
                "risk_summary": {"total": 0},
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "output_format,converter,content,writer",
    [
        ("csv", "to_csv", "title,severity\n", "write_text"),
        ("pdf", "to_pdf", b"%PDF-1.7\n", "write_bytes"),
    ],
)
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.ENOSPC, errno.EIO])
def test_export_write_failure_never_reports_success(
    receipt_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    converter: str,
    content: str | bytes,
    writer: str,
    error_number: int,
) -> None:
    output = tmp_path / f"output.{output_format}"
    error = OSError(error_number, os.strerror(error_number), str(output))
    with (
        patch.object(DecisionReceipt, converter, return_value=content),
        patch.object(Path, writer, side_effect=error) as write,
        pytest.raises(SystemExit) as exc,
    ):
        cmd_receipt_export(
            argparse.Namespace(receipt=str(receipt_path), format=output_format, output=str(output))
        )

    assert exc.value.code == 1
    write.assert_called_once_with(content)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error: Cannot write receipt export:" in captured.err
    assert str(output) in captured.err
    assert "Traceback" not in captured.err


def test_export_encoding_failure_never_reports_success(
    receipt_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    error = UnicodeEncodeError("ascii", "\u00e9", 0, 1, "ordinal not in range(128)")
    with (
        patch.object(Path, "write_text", side_effect=error),
        pytest.raises(SystemExit) as exc,
    ):
        cmd_receipt_export(
            argparse.Namespace(
                receipt=str(receipt_path), format="json", output=str(tmp_path / "output.json")
            )
        )

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error: Cannot write receipt export:" in captured.err
    assert "ascii" in captured.err


@pytest.mark.parametrize("output_format", ["json", "csv"])
@pytest.mark.parametrize("kind", ["directory", "missing_parent", "permission"])
def test_unwritable_destination_through_cli_process(
    receipt_path: Path, tmp_path: Path, kind: str, output_format: str
) -> None:
    output = tmp_path / f"output.{output_format}"
    if kind == "directory":
        output.mkdir()
    elif kind == "missing_parent":
        output = tmp_path / "missing" / output.name
    else:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root bypasses file permissions; mocked EACCES is covered separately")
        if os.name == "nt":
            pytest.skip("chmod read-only semantics differ on Windows")
        output.write_bytes(b"preserve existing output")
        output.chmod(0o400)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "aragora.cli.main",
                "receipt",
                "export",
                str(receipt_path),
                "--format",
                output_format,
                "--output",
                str(output),
            ],
            cwd=tmp_path,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "ARAGORA_USE_SECRETS_MANAGER": "0",
                "AWS_EC2_METADATA_DISABLED": "true",
                "ARAGORA_SSRF_ALLOW_LOCALHOST": "false",
                "ARAGORA_DATA_DIR": str(tmp_path / "data"),
            },
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 1, result.stderr.decode()
        assert result.stdout == b""
        assert b"Error: Cannot write receipt export:" in result.stderr
        assert b"Traceback" not in result.stderr
        if kind == "permission":
            assert output.read_bytes() == b"preserve existing output"
        elif kind == "missing_parent":
            assert not output.parent.exists()
        else:
            assert output.is_dir()
    finally:
        if kind == "permission":
            output.chmod(0o600)
