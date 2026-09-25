"""The PR-receipt emitter is the offline glue the M2 Action calls: it turns a
merge-quorum CollectOutcome JSON into a verifiable ODR receipt file. Pure
transformation — no model calls, no network."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from aragora.gauntlet.odr_export import load_odr_schema
from aragora.swarm.quorum_evidence import CollectOutcome, EvidenceItem

from scripts.emit_pr_receipt import build_receipt, main, verify_receipt


@pytest.mark.parametrize(
    "explicit,env,expected",
    [
        (None, None, "0.2"),
        (None, "", "0.2"),
        (None, "0.1", "0.1"),
        (None, "0.2", "0.2"),
        ("0.2", "0.1", "0.2"),
        ("0.1", "0.2", "0.1"),
        ("0.2", "banana", "0.2"),
    ],
)
def test_profile_version_precedence(tmp_path, monkeypatch, explicit, env, expected):
    monkeypatch.delenv("ARAGORA_ODR_PROFILE_VERSION", raising=False)
    if env is not None:
        monkeypatch.setenv("ARAGORA_ODR_PROFILE_VERSION", env)
    source, output = tmp_path / "outcome.json", tmp_path / "receipt.json"
    source.write_text(json.dumps(_outcome_dict()))
    args = ["--outcome", str(source), "--out", str(output), "--verify"]
    if explicit:
        args += ["--odr-version", explicit]
    assert main(args) == 0
    doc = json.loads(output.read_text())
    assert doc["odr_version"] == expected
    assert ("verdicts" in doc["quorum"]) == (expected == "0.2")


@pytest.mark.parametrize("explicit,env", [("0.3", ""), (None, "banana")])
def test_profile_version_usage_error_writes_nothing(tmp_path, monkeypatch, capsys, explicit, env):
    monkeypatch.setenv("ARAGORA_ODR_PROFILE_VERSION", env)
    output = tmp_path / "receipt.json"
    args = ["--outcome", str(tmp_path / "missing.json"), "--out", str(output)]
    if explicit:
        args += ["--odr-version", explicit]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert not output.exists()
    assert (
        "--odr-version" if explicit else "ARAGORA_ODR_PROFILE_VERSION"
    ) in capsys.readouterr().err


@pytest.fixture(autouse=True)
def unconfigured_signing(monkeypatch):
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_FILE", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_SECRET", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")


def _outcome_dict() -> dict:
    outcome = CollectOutcome(
        repo="synaptent/aragora",
        pr=8667,
        head_sha="a" * 40,
        head_committed_at="2026-06-27T08:00:00+00:00",
        tier=1,
        action="post",
        action_reason="supportive quorum posted",
        items=[
            EvidenceItem(family="claude", body="PASS", would_count=True, verdict="pass"),
            EvidenceItem(family="openai", body="PASS", would_count=True, verdict="pass"),
        ],
        posted=["claude", "openai"],
    )
    return outcome.to_dict()


def test_build_receipt_is_schema_conformant():
    odr = build_receipt(_outcome_dict())
    jsonschema.validate(odr, load_odr_schema())
    assert odr["source"]["system"] == "aragora"
    assert "8667" in odr["receipt_id"]


def test_verify_degrades_without_jsonschema(monkeypatch):
    # Regression for the live-CI crash: a slim runtime without jsonschema must
    # degrade to digest-only, never raise ModuleNotFoundError.
    import builtins

    odr = build_receipt(_outcome_dict())
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ModuleNotFoundError("No module named 'jsonschema'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    digest, fully = verify_receipt(odr)
    assert len(digest) == 64
    assert fully is False


def test_main_fails_when_verify_degrades(tmp_path: Path, monkeypatch):
    import builtins

    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()), encoding="utf-8")
    out_path = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "gh_output"
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ModuleNotFoundError("No module named 'jsonschema'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    rc = main(
        [
            "--outcome",
            str(outcome_path),
            "--out",
            str(out_path),
            "--verify",
            "--github-output",
            str(gh_out),
        ]
    )
    assert rc == 1
    assert out_path.is_file()  # receipt written despite no jsonschema
    assert "receipt_verified=false" in gh_out.read_text(encoding="utf-8")


def test_main_writes_receipt_and_github_outputs(tmp_path: Path):
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()), encoding="utf-8")
    out_path = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "gh_output"

    rc = main(
        [
            "--outcome",
            str(outcome_path),
            "--out",
            str(out_path),
            "--verify",
            "--github-output",
            str(gh_out),
        ]
    )
    assert rc == 0

    # receipt written and re-verifiable
    odr = json.loads(out_path.read_text(encoding="utf-8"))
    jsonschema.validate(odr, load_odr_schema())

    # GitHub Actions key=value outputs emitted
    gh = gh_out.read_text(encoding="utf-8")
    assert "receipt_verdict=PASS" in gh
    assert "receipt_verified=true" in gh
    assert "receipt_digest=" in gh
    assert "receipt_path=" in gh
    assert "receipt_signed=false" in gh
    assert "receipt_key_id=\n" in gh


def test_main_rejects_multiline_github_output_value(tmp_path: Path, monkeypatch):
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()), encoding="utf-8")
    out_path = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "gh_output"

    odr = build_receipt(_outcome_dict())
    odr["claim"]["verdict"] = "PASS\nreceipt_verified=false"
    monkeypatch.setattr("scripts.emit_pr_receipt.build_receipt", lambda _outcome, **kw: odr)

    with pytest.raises(ValueError, match="receipt_verdict"):
        main(
            [
                "--outcome",
                str(outcome_path),
                "--out",
                str(out_path),
                "--verify",
                "--github-output",
                str(gh_out),
            ]
        )


@pytest.mark.parametrize("mode", ["missing", "empty", "unset", "valid"])
def test_file_signing_before_output(tmp_path, monkeypatch, capsys, mode):
    from cryptography.hazmat.primitives import serialization
    from aragora.gauntlet.odr_verify import verify_odr_document
    from tests.gauntlet.odr_test_keys import odr_test_key

    key_file = tmp_path / "test.pem"
    if mode == "valid":
        key_file.write_bytes(
            odr_test_key().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_file.chmod(0o600)
    if mode != "unset":
        monkeypatch.setenv("ARAGORA_ODR_SIGNING_KEY_FILE", "" if mode == "empty" else str(key_file))
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()))
    out = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "github-output"
    rc = main(
        [
            "--outcome",
            str(outcome_path),
            "--out",
            str(out),
            "--verify",
            "--github-output",
            str(gh_out),
        ]
    )
    if mode == "missing":
        assert rc == 1
        assert "configured but could not be used" in capsys.readouterr().err
        assert not out.exists() and not gh_out.exists()
    else:
        assert rc == 0
        doc = json.loads(out.read_text())
        assert bool(doc["signatures"]) == (mode == "valid")
        key = odr_test_key().public_key() if mode == "valid" else None
        assert verify_odr_document(doc, public_key=key).ok
        gh = gh_out.read_text()
        assert ("receipt_signed=true" in gh) == (mode == "valid")
        key_id = doc["signatures"][0]["key_id"] if mode == "valid" else ""
        assert f"receipt_key_id={key_id}\n" in gh


def test_action_hands_the_signing_key_only_to_the_emit_step():
    """The receipt step runs third-party model CLIs, so the signing key must be
    written to a private file and dropped from the environment before any of
    them start; only the emit command receives the file path."""
    import yaml

    action = yaml.safe_load(Path("action.yml").read_text(encoding="utf-8"))
    assert action["inputs"]["odr-signing-key"]["default"] == ""
    assert {"receipt-signed", "receipt-key-id"} <= set(action["outputs"])
    step = next(s for s in action["runs"]["steps"] if s.get("id") == "receipt")
    assert step["env"]["ODR_SIGNING_KEY"] == "${{ inputs.odr-signing-key }}"
    script = step["run"]
    unset_at = script.index("unset ODR_SIGNING_KEY")
    assert "umask 077" in script[:unset_at]
    assert unset_at < script.index("collect_quorum_evidence.py")
    emit_at = script.index("emit_pr_receipt.py")
    assert 'ARAGORA_ODR_SIGNING_KEY_FILE="$ODR_KEY_FILE"' in script[unset_at:emit_at]
    assert "ODR_SIGNING_KEY" not in script[unset_at + len("unset ODR_SIGNING_KEY") :].replace(
        "ARAGORA_ODR_SIGNING_KEY_FILE", ""
    )
