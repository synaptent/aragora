"""Receipt export failures must not masquerade as another artifact format."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from aragora.cli.commands.receipt import cmd_receipt_export
from aragora.cli.receipt_formatter import receipt_to_html, receipt_to_markdown
from aragora.gauntlet.receipt_models import DecisionReceipt


@pytest.fixture
def receipt_path(tmp_path: Path) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps(
            {
                "receipt_id": "export-contract",
                "gauntlet_id": "export-contract",
                "timestamp": "2026-09-07T00:00:00Z",
                "verdict": "PASS",
                "confidence": 0.8,
                "risk_summary": {"total": 0},
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "output_format,method", [("pdf", "to_pdf"), ("sarif", "to_sarif_json"), ("csv", "to_csv")]
)
@pytest.mark.parametrize(
    "error_type", [ImportError, AttributeError, KeyError, ValueError, TypeError]
)
@pytest.mark.parametrize("destination", ["stdout", "new", "existing"])
def test_conversion_failure_never_outputs_native_json(
    receipt_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    method: str,
    error_type: type[Exception],
    destination: str,
) -> None:
    output = tmp_path / f"output.{output_format}"
    if destination == "existing":
        output.write_bytes(b"preserve existing artifact")
    args = argparse.Namespace(
        receipt=str(receipt_path),
        format=output_format,
        output=None if destination == "stdout" else str(output),
    )

    with patch.object(DecisionReceipt, method, side_effect=error_type("conversion failed")):
        with pytest.raises(SystemExit) as exc:
            cmd_receipt_export(args)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert output_format.upper() in captured.err
    assert "Error:" in captured.err
    if destination == "existing":
        assert output.read_bytes() == b"preserve existing artifact"
    else:
        assert not output.exists()


def test_missing_pdf_dependency_is_actionable(
    receipt_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch.dict("sys.modules", {"weasyprint": None}):
        with pytest.raises(SystemExit) as exc:
            cmd_receipt_export(
                argparse.Namespace(receipt=str(receipt_path), format="pdf", output=None)
            )
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "weasyprint" in captured.err


def test_missing_pdf_dependency_fails_through_cli_process(
    receipt_path: Path, tmp_path: Path
) -> None:
    output = tmp_path / "receipt.pdf"
    output.write_bytes(b"preserve existing artifact")
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "ARAGORA_USE_SECRETS_MANAGER": "0",
        "AWS_EC2_METADATA_DISABLED": "true",
        "ARAGORA_SSRF_ALLOW_LOCALHOST": "false",
        "ARAGORA_DATA_DIR": str(tmp_path / "data"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['weasyprint'] = None; "
            "from aragora.cli.main import main; raise SystemExit(main())",
            "receipt",
            "export",
            str(receipt_path),
            "--format",
            "pdf",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr.decode()
    assert result.stdout == b""
    assert b"weasyprint" in result.stderr
    assert b"Traceback" not in result.stderr
    assert output.read_bytes() == b"preserve existing artifact"


@pytest.mark.parametrize("output_format", ["sarif", "csv"])
def test_successful_export_through_cli_process(
    receipt_path: Path, tmp_path: Path, output_format: str
) -> None:
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
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "ARAGORA_USE_SECRETS_MANAGER": "0",
            "AWS_EC2_METADATA_DISABLED": "true",
            "ARAGORA_SSRF_ALLOW_LOCALHOST": "false",
            "ARAGORA_DATA_DIR": str(tmp_path / "data"),
        },
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stderr == b""
    if output_format == "sarif":
        assert json.loads(result.stdout)["version"] == "2.1.0"
    else:
        assert result.stdout.startswith(b"Finding ID,Category,Severity,Title,")


@pytest.mark.parametrize(
    "output_format,method,content",
    [
        ("pdf", "to_pdf", b"%PDF-1.7\n"),
        ("sarif", "to_sarif_json", '{"version":"2.1.0"}'),
        ("csv", "to_csv", "title,severity\n"),
    ],
)
@pytest.mark.parametrize("to_file", [False, True])
def test_successful_export_preserves_format_bytes(
    receipt_path: Path,
    tmp_path: Path,
    capfdbinary: pytest.CaptureFixture[bytes],
    output_format: str,
    method: str,
    content: str | bytes,
    to_file: bool,
) -> None:
    output = tmp_path / f"output.{output_format}"
    args = argparse.Namespace(
        receipt=str(receipt_path), format=output_format, output=str(output) if to_file else None
    )
    with patch.object(DecisionReceipt, method, return_value=content):
        cmd_receipt_export(args)
    expected = content if isinstance(content, bytes) else content.encode("utf-8")
    captured = capfdbinary.readouterr()
    assert captured.err == b""
    if to_file:
        assert output.read_bytes() == expected
        assert captured.out == f"Exported to {output}\n".encode()
    else:
        assert captured.out == expected + (b"" if isinstance(content, bytes) else b"\n")


@pytest.mark.parametrize("output_format", ["html", "md", "markdown"])
def test_legacy_fallback_still_produces_requested_format(
    receipt_path: Path, capsys: pytest.CaptureFixture[str], output_format: str
) -> None:
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected = receipt_to_html(data) if output_format == "html" else receipt_to_markdown(data)
    with patch.object(DecisionReceipt, "from_dict", side_effect=ValueError("legacy shape")):
        cmd_receipt_export(
            argparse.Namespace(receipt=str(receipt_path), format=output_format, output=None)
        )
    captured = capsys.readouterr()
    assert captured.out == expected + "\n"
    assert captured.err == ""
