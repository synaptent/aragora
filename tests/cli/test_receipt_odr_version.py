"""The receipt export CLI shares the PR script's opt-in profile policy."""

import argparse
import json

import pytest

from aragora.cli.commands.receipt import add_receipt_parser
from aragora.gauntlet.odr_verify import verify_odr_document


def parser():
    root = argparse.ArgumentParser()
    add_receipt_parser(root.add_subparsers())
    return root


@pytest.mark.parametrize(
    "explicit,env,expected",
    [
        (None, None, "0.1"),
        (None, "", "0.1"),
        (None, "0.2", "0.2"),
        ("0.2", "0.1", "0.2"),
        ("0.1", "0.2", "0.1"),
        ("0.2", "banana", "0.2"),
    ],
)
def test_profile_version_precedence(tmp_path, monkeypatch, explicit, env, expected):
    monkeypatch.delenv("ARAGORA_ODR_PROFILE_VERSION", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_FILE", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_SECRET", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    if env is not None:
        monkeypatch.setenv("ARAGORA_ODR_PROFILE_VERSION", env)
    source, output = tmp_path / "receipt.json", tmp_path / "receipt.odr.json"
    source.write_text(json.dumps({"receipt_id": "demo", "verdict": "PASS"}))
    argv = ["receipt", "export", str(source), "--format", "odr", "--output", str(output)]
    if explicit:
        argv += ["--odr-version", explicit]
    args = parser().parse_args(argv)
    args.func(args)
    doc = json.loads(output.read_text())
    assert doc["odr_version"] == expected
    assert verify_odr_document(doc).ok


@pytest.mark.parametrize("explicit,env", [("0.3", ""), (None, "banana")])
def test_profile_version_usage_error_writes_nothing(tmp_path, monkeypatch, capsys, explicit, env):
    monkeypatch.setenv("ARAGORA_ODR_PROFILE_VERSION", env)
    output = tmp_path / "receipt.odr.json"
    argv = [
        "receipt",
        "export",
        str(tmp_path / "missing.json"),
        "--format",
        "odr",
        "--output",
        str(output),
    ]
    if explicit:
        argv += ["--odr-version", explicit]
    with pytest.raises(SystemExit) as exc:
        args = parser().parse_args(argv)
        args.func(args)
    assert exc.value.code == 2
    assert not output.exists()
    assert (
        "--odr-version" if explicit else "ARAGORA_ODR_PROFILE_VERSION"
    ) in capsys.readouterr().err
