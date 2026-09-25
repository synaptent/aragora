"""`receipt export --format odr --acta` writes the signed pair, or nothing."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

_ROOT = Path(__file__).resolve().parents[2]
_ARAGORA_VERIFY_SRC = _ROOT / "aragora-verify" / "src"
if str(_ARAGORA_VERIFY_SRC) not in sys.path:
    sys.path.insert(0, str(_ARAGORA_VERIFY_SRC))

from aragora_verify.acta import verify_acta_projection  # noqa: E402

from aragora.cli.commands.receipt import add_receipt_parser  # noqa: E402
from aragora.gauntlet.odr_signing import compute_key_id  # noqa: E402
from aragora.gauntlet.odr_verify import verify_odr_document  # noqa: E402
from tests.gauntlet.odr_test_keys import odr_test_key  # noqa: E402

FILE_ENV = "ARAGORA_ODR_SIGNING_KEY_FILE"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    add_receipt_parser(root.add_subparsers())
    return root


@pytest.fixture(autouse=True)
def isolated_signing(monkeypatch):
    monkeypatch.delenv(FILE_ENV, raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_SECRET", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_PROFILE_VERSION", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")


@pytest.fixture
def receipt(tmp_path: Path) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps({"receipt_id": "demo", "verdict": "PASS"}))
    return path


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "signing.pem"
    path.write_bytes(
        odr_test_key().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return path


def _run(argv: list[str]) -> None:
    args = parser().parse_args(argv)
    args.func(args)


def _export_argv(receipt: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "receipt",
        "export",
        str(receipt),
        "--format",
        "odr",
        "--output",
        str(tmp_path / "x.odr.json"),
        *extra,
    ]


def test_writes_both_files_and_they_verify(tmp_path, receipt, key_file, monkeypatch):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    odr_path, acta_path = tmp_path / "x.odr.json", tmp_path / "x.acta.json"

    _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(acta_path)))

    odr = json.loads(odr_path.read_text())
    envelope = json.loads(acta_path.read_text())
    public_key = odr_test_key().public_key()
    assert odr["odr_version"] == "0.2"
    assert verify_odr_document(odr, public_key=public_key).ok
    assert envelope["signature"]["kid"] == odr["signatures"][0]["key_id"]
    assert envelope["signature"]["kid"] == compute_key_id(public_key)
    assert envelope["payload"]["odr"] == odr
    assert verify_acta_projection(envelope, public_key).ok


def test_without_acta_no_projection_file_appears(tmp_path, receipt, key_file, monkeypatch):
    monkeypatch.setenv(FILE_ENV, str(key_file))

    _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2"))

    assert (tmp_path / "x.odr.json").exists()
    assert not (tmp_path / "x.acta.json").exists()
    assert not list(tmp_path.glob("*.acta.json"))


def test_without_a_signing_key_exits_1_and_writes_neither_file(tmp_path, receipt, capsys):
    acta_path = tmp_path / "x.acta.json"

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(acta_path)))

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "--acta" in err and "signing key" in err
    assert not acta_path.exists()
    assert not (tmp_path / "x.odr.json").exists()


def test_unusable_signing_key_exits_1_and_writes_neither_file(
    tmp_path, receipt, capsys, monkeypatch
):
    monkeypatch.setenv(FILE_ENV, str(tmp_path / "missing.pem"))
    acta_path = tmp_path / "x.acta.json"

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(acta_path)))

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "--acta" in err and "signing key" in err
    assert not acta_path.exists()
    assert not (tmp_path / "x.odr.json").exists()


def test_acta_with_another_format_is_a_usage_error(
    tmp_path, receipt, key_file, capsys, monkeypatch
):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    output, acta_path = tmp_path / "y.json", tmp_path / "y2.acta.json"

    with pytest.raises(SystemExit) as exc:
        _run(
            [
                "receipt",
                "export",
                str(receipt),
                "--format",
                "json",
                "--odr-version",
                "0.2",
                "--output",
                str(output),
                "--acta",
                str(acta_path),
            ]
        )

    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "--format odr" in err
    assert not acta_path.exists()
    assert not output.exists()


@pytest.mark.parametrize("env,explicit", [(None, "0.1"), ("0.1", None), ("0.2", "0.1")])
def test_acta_requires_an_effective_v02_document(
    tmp_path, receipt, key_file, capsys, monkeypatch, env, explicit
):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    if env is not None:
        monkeypatch.setenv("ARAGORA_ODR_PROFILE_VERSION", env)
    acta_path = tmp_path / "x.acta.json"
    extra = ["--acta", str(acta_path)]
    if explicit:
        extra += ["--odr-version", explicit]

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, *extra))

    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "--odr-version" in err
    assert not acta_path.exists()
    assert not (tmp_path / "x.odr.json").exists()


@pytest.mark.parametrize("env", ["0.2", None])
def test_acta_env_var_or_default_supplies_the_effective_version(
    tmp_path, receipt, key_file, monkeypatch, env
):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    if env is not None:
        monkeypatch.setenv("ARAGORA_ODR_PROFILE_VERSION", env)
    acta_path = tmp_path / "x.acta.json"

    _run(_export_argv(receipt, tmp_path, "--acta", str(acta_path)))

    assert json.loads((tmp_path / "x.odr.json").read_text())["odr_version"] == "0.2"
    assert json.loads(acta_path.read_text())["payload"]["chain_scope"] == "acta-02"


def test_acta_requires_an_output_path(tmp_path, receipt, key_file, capsys, monkeypatch):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    acta_path = tmp_path / "x.acta.json"

    with pytest.raises(SystemExit) as exc:
        _run(
            [
                "receipt",
                "export",
                str(receipt),
                "--format",
                "odr",
                "--odr-version",
                "0.2",
                "--acta",
                str(acta_path),
            ]
        )

    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "--output" in err
    assert not acta_path.exists()


def test_unwritable_projection_path_leaves_no_receipt_behind(
    tmp_path, receipt, key_file, capsys, monkeypatch
):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    unwritable = tmp_path / "missing-dir" / "x.acta.json"

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(unwritable)))

    assert exc.value.code == 1
    assert "Cannot write" in capsys.readouterr().err
    assert not (tmp_path / "x.odr.json").exists()
    assert not list(tmp_path.glob("*.part"))


def test_a_failed_pair_write_keeps_an_existing_output_file(
    tmp_path, receipt, key_file, capsys, monkeypatch
):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    existing = tmp_path / "x.odr.json"
    existing.write_text("PREVIOUS EXPORT")
    unwritable = tmp_path / "missing-dir" / "x.acta.json"

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(unwritable)))

    assert exc.value.code == 1
    assert existing.read_text() == "PREVIOUS EXPORT"


def test_acta_and_output_may_not_be_the_same_file(tmp_path, receipt, key_file, capsys, monkeypatch):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    both = tmp_path / "x.odr.json"

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(both)))

    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "--acta" in err and "--output" in err
    assert not both.exists()


def test_exported_pair_respects_the_umask_rather_than_landing_private(
    tmp_path, receipt, key_file, monkeypatch
):
    """Staging through a temp file must not silently make exports 0600."""
    monkeypatch.setenv(FILE_ENV, str(key_file))
    acta_path = tmp_path / "x.acta.json"
    umask = os.umask(0o022)
    os.umask(umask)

    _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(acta_path)))

    expected = 0o666 & ~umask
    assert stat.S_IMODE((tmp_path / "x.odr.json").stat().st_mode) == expected
    assert stat.S_IMODE(acta_path.stat().st_mode) == expected


def test_a_move_that_fails_after_the_receipt_landed_rolls_it_back(
    tmp_path, receipt, key_file, capsys, monkeypatch
):
    """Staging both files is not enough: the second move can still fail."""
    monkeypatch.setenv(FILE_ENV, str(key_file))
    odr_path = tmp_path / "x.odr.json"
    odr_path.write_text("PREVIOUS EXPORT")
    blocked = tmp_path / "blocked.acta.json"
    blocked.mkdir()

    with pytest.raises(SystemExit) as exc:
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(blocked)))

    assert exc.value.code == 1
    assert "Cannot write" in capsys.readouterr().err
    assert odr_path.read_text() == "PREVIOUS EXPORT"
    assert not list(tmp_path.glob("*.part"))


def test_a_move_that_fails_after_a_new_receipt_landed_removes_it(
    tmp_path, receipt, key_file, monkeypatch
):
    monkeypatch.setenv(FILE_ENV, str(key_file))
    blocked = tmp_path / "blocked.acta.json"
    blocked.mkdir()

    with pytest.raises(SystemExit):
        _run(_export_argv(receipt, tmp_path, "--odr-version", "0.2", "--acta", str(blocked)))

    assert not (tmp_path / "x.odr.json").exists()
    assert not list(tmp_path.glob("*.part"))
