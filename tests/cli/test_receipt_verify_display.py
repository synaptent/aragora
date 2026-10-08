"""Verification escapes display text without changing the values it verifies."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from aragora.cli.commands.receipt import cmd_receipt_verify
from aragora.gauntlet.receipt_models import DecisionReceipt

SPOOF = "id\n  [PASS] FORGED\x1b[2J\u202e" + "x" * 121


@pytest.mark.parametrize("tampered", [False, True])
def test_verify_cli_outside_checkout(tampered: bool, tmp_path: Path) -> None:
    data = DecisionReceipt.from_dict(
        dict(
            receipt_id=SPOOF,
            verdict="PASS",
            confidence=0.8,
            timestamp="2026-09-12",
        )
    ).to_dict()
    if tampered:
        data["artifact_hash"] = "\n[PASS] FORGED\x1bxx" + "0" * 48
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "aragora.cli.main", "receipt", "verify", str(source), "--verbose"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "ARAGORA_USE_SECRETS_MANAGER": "0",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == int(tampered), result.stderr
    assert json.dumps(SPOOF)[1:-1] in result.stdout
    assert "\n[PASS] FORGED" not in result.stdout and "\x1b" not in result.stdout
    assert "Traceback" not in result.stderr
    expected = "INVALID (2/3" if tampered else "VALID (3/3"
    assert f"Result: {expected} checks passed)" in result.stdout


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("tampered", [False, True])
@pytest.mark.parametrize("verbose", [False, True])
def test_verification_preserves_hash_inputs_and_exit_codes(
    fallback: bool,
    tampered: bool,
    verbose: bool,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = dict(
        receipt_id=SPOOF,
        gauntlet_id="g1",
        input_hash="input",
        risk_summary={},
        verdict="PASS",
        confidence=0.8,
    )
    legacy_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    data.update(timestamp="2026-09-12T00:00:00Z")
    data = DecisionReceipt.from_dict(data).to_dict()
    if fallback:
        data["artifact_hash"] = legacy_hash
    if tampered:
        data["artifact_hash"] = "\n[PASS] FORGED\x1bxx" + "0" * 48
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    original = DecisionReceipt.from_dict
    with patch.object(
        DecisionReceipt, "from_dict", side_effect=ImportError if fallback else original
    ) as load:
        with pytest.raises(SystemExit) as exc:
            cmd_receipt_verify(argparse.Namespace(receipt=str(source), verbose=verbose))
    assert exc.value.code == int(tampered)
    assert all(call.args[0] == data for call in load.call_args_list)
    captured = capsys.readouterr()
    assert json.dumps(SPOOF)[1:-1] in captured.out
    assert "\n[PASS] FORGED" not in captured.out and "\n  [PASS] FORGED" not in captured.out
    assert "\x1b" not in captured.out and "\u202e" not in captured.out
    expected = "INVALID (2/3" if tampered else "VALID (3/3"
    assert f"Result: {expected} checks passed)" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("signature_result", [True, False, RuntimeError(SPOOF)])
def test_signature_result_and_exception_display_are_independent(
    signature_result: bool | RuntimeError, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = DecisionReceipt.from_dict(
        dict(
            receipt_id="signed",
            timestamp="2026-09-12",
            verdict="PASS",
            confidence=0.8,
        )
    ).to_dict()
    data["signature"] = "present"
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with patch.object(DecisionReceipt, "verify_signature", return_value=signature_result) as verify:
        if isinstance(signature_result, RuntimeError):
            verify.side_effect = signature_result
        with pytest.raises(SystemExit) as exc:
            cmd_receipt_verify(argparse.Namespace(receipt=str(source), verbose=False))
    assert exc.value.code == (0 if signature_result is True else 1)
    verify.assert_called_once_with()
    captured = capsys.readouterr()
    if isinstance(signature_result, RuntimeError):
        assert json.dumps(SPOOF)[1:-1] in captured.out
        assert "\n  [PASS] FORGED" not in captured.out and "\x1b" not in captured.out
    assert (
        f"Result: {'VALID (4/4' if signature_result is True else 'INVALID (3/4'} checks passed)"
        in captured.out
    )
    assert captured.err == ""
