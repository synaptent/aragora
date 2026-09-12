"""Module entry point preserves the existing verifier's output and exit codes."""

from importlib.metadata import version
import json
import subprocess
import sys

import pytest

from _fixtures import valid_odr


@pytest.mark.parametrize("module", ["aragora_verify", "aragora_verify.cli"])
@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_self_checks(module, flag):
    result = subprocess.run(
        [sys.executable, "-m", module, flag],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    if flag == "--version":
        assert version("aragora-verify") in result.stdout.split()
    else:
        assert "usage:" in result.stdout and "--version" in result.stdout
        assert "--pubkey" in result.stdout


@pytest.mark.parametrize("valid", [True, False])
def test_module_verification_preserves_exit_code(tmp_path, valid):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(valid_odr() if valid else {}))
    result = subprocess.run(
        [sys.executable, "-m", "aragora_verify", str(path), "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (0 if valid else 1)
    assert json.loads(result.stdout)["ok"] is valid
