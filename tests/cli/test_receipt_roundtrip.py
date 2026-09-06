"""Regression test for issue #7393.

`aragora demo --receipt <path>` must produce receipt files that pass
`aragora receipt verify <path>` with ``Result: VALID (3/3 checks passed)``.

The original bug was a producer/consumer canonicalization mismatch: the demo
writer stored the receipt *signature* in the ``artifact_hash`` field (and
omitted the ``timestamp`` field), while ``aragora receipt verify`` recomputes a
content-addressable SHA-256 over ``{receipt_id, gauntlet_id, input_hash,
risk_summary, verdict, confidence}`` and also requires ``timestamp``. The two
hashes never agreed, so every demo receipt failed verification (1/3 checks).

This test exercises the *full* CLI repro end-to-end (``demo.main`` with
``--receipt`` followed by ``cmd_receipt_verify``) so the round-trip invariant is
guarded against regression, not just the helper functions.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from aragora.cli.commands.receipt import cmd_receipt_verify
from aragora.cli.demo import (
    _build_live_receipt_data,
    main as demo_main,
)
from aragora.gauntlet.receipt_models import DecisionReceipt


_TOPIC = "Should Aragora prioritize the EU AI Act compliance pipeline?"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_CREDENTIALS = (
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROK_API_KEY",
    "KIMI_API_KEY",
    "MISTRAL_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TINKER_API_KEY",
    "XAI_API_KEY",
)


def _offline_subprocess_env(*, secure_store: Path) -> dict[str, str]:
    """Return a fail-closed environment for the zero-key public journey."""
    env = dict(os.environ)
    for name in tuple(env):
        if name.endswith("_API_KEY") or name.startswith("AWS_"):
            env.pop(name)
    for name in ("ARAGORA_API_URL", "ARAGORA_ODR_SIGNING_KEY_SECRET"):
        env.pop(name, None)
    env.update(
        {
            "ARAGORA_API_KEY_BACKEND": "file",
            "ARAGORA_API_KEY_STORE_PATH": str(secure_store),
            "ARAGORA_OFFLINE": "1",
            "ARAGORA_USE_SECRETS_MANAGER": "false",
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONSAFEPATH": "1",
        }
    )
    return env


def _run_subprocess(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected: int = 0,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    assert completed.returncode == expected, (
        f"command returned {completed.returncode}, expected {expected}: {command!r}\n"
        f"stdout:\n{completed.stdout[-4000:]}\n"
        f"stderr:\n{completed.stderr[-4000:]}"
    )
    return completed


def _build_local_wheel(source: Path, wheel_dir: Path, *, env: dict[str, str]) -> Path:
    uv = shutil.which("uv")
    assert uv, "uv is required for an offline, isolated local wheel build"
    before = set(wheel_dir.glob("*.whl"))
    _run_subprocess(
        [
            uv,
            "build",
            "--offline",
            "--wheel",
            "--out-dir",
            str(wheel_dir),
            str(source),
        ],
        cwd=wheel_dir.parent,
        env=env,
    )
    created = set(wheel_dir.glob("*.whl")) - before
    assert len(created) == 1, f"expected one wheel from {source}, got {sorted(created)}"
    return created.pop()


@pytest.fixture(scope="module")
def installed_public_wedge(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, dict[str, str]]:
    """Build and install both public CLIs outside the source checkout."""
    workspace = tmp_path_factory.mktemp("public_wedge_install")
    wheel_dir = workspace / "wheels"
    runtime_root = workspace / "runtime"
    constraints = workspace / "locked-constraints.txt"
    secure_store = workspace / "empty-api-key-store.json"
    wheel_dir.mkdir()

    build_env = _offline_subprocess_env(secure_store=secure_store)
    build_env.pop("PYTHONPATH", None)
    build_env.update({"PIP_NO_INDEX": "1", "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never"})
    root_wheel = _build_local_wheel(_REPO_ROOT, wheel_dir, env=build_env)
    verifier_wheel = _build_local_wheel(_REPO_ROOT / "aragora-verify", wheel_dir, env=build_env)

    _run_subprocess(
        [sys.executable, "-m", "venv", str(runtime_root)],
        cwd=workspace,
        env=build_env,
    )
    runtime_python = (
        runtime_root / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else runtime_root / "bin" / "python"
    )
    uv = shutil.which("uv")
    assert uv
    _run_subprocess(
        [
            uv,
            "export",
            "--locked",
            "--all-extras",
            "--no-dev",
            "--no-emit-project",
            "--no-annotate",
            "--output-file",
            str(constraints),
        ],
        cwd=_REPO_ROOT,
        env=build_env,
    )

    install_env = dict(build_env)
    for name in ("PIP_NO_INDEX", "UV_OFFLINE"):
        install_env.pop(name, None)
    _run_subprocess(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(runtime_python),
            "--constraint",
            str(constraints),
            str(root_wheel),
            str(verifier_wheel),
        ],
        cwd=workspace,
        env=install_env,
    )
    _run_subprocess(
        [str(runtime_python), "-m", "pip", "check"],
        cwd=workspace,
        env=install_env,
    )

    runtime_env = _offline_subprocess_env(secure_store=secure_store)
    runtime_env.pop("PYTHONPATH", None)
    runtime_env["PYTHONNOUSERSITE"] = "1"
    runtime_env["VIRTUAL_ENV"] = str(runtime_root)
    runtime_env["PATH"] = f"{runtime_python.parent}{os.pathsep}{runtime_env['PATH']}"
    probe = _run_subprocess(
        [
            str(runtime_python),
            "-c",
            "import aragora, aragora_verify, sys; print(sys.prefix); "
            "print(aragora.__file__); print(aragora_verify.__file__)",
        ],
        cwd=workspace,
        env=runtime_env,
    )
    paths = [Path(line).resolve() for line in probe.stdout.splitlines() if line.strip()]
    assert len(paths) == 3
    assert paths[0] == runtime_root.resolve()
    assert all(runtime_root.resolve() in path.parents for path in paths[1:]), paths
    assert not secure_store.exists()
    return runtime_python, runtime_env


def _verify_receipt_file(receipt_path: Path, capsys) -> str:
    """Run ``aragora receipt verify`` on a file and return its stdout."""
    with pytest.raises(SystemExit) as exc:
        cmd_receipt_verify(argparse.Namespace(receipt=str(receipt_path), verbose=True))
    out = capsys.readouterr().out
    assert exc.value.code == 0, f"verify exited {exc.value.code}; output:\n{out}"
    return out


def test_demo_receipt_verifies_end_to_end(tmp_path, capsys):
    """The exact issue #7393 repro: demo --receipt then receipt verify == VALID."""
    receipt_path = tmp_path / "receipt.json"

    args = argparse.Namespace(
        name=None,
        topic=_TOPIC,
        list_demos=False,
        server=False,
        receipt=str(receipt_path),
        offline=True,
    )
    demo_main(args)

    assert receipt_path.exists(), "demo --receipt did not write the receipt file"

    saved = json.loads(receipt_path.read_text(encoding="utf-8"))
    # The two fields whose absence/mismatch caused the original INVALID result.
    assert saved.get("timestamp"), "receipt is missing the required 'timestamp' field"
    assert saved.get("artifact_hash"), "receipt is missing 'artifact_hash'"

    # Stored hash must equal the recomputed content hash (no signature-vs-hash mixup).
    receipt = DecisionReceipt.from_dict(saved)
    assert receipt.verify_integrity() is True

    out = _verify_receipt_file(receipt_path, capsys)
    assert "Result: VALID (3/3 checks passed)" in out


def test_demo_receipt_survives_json_persistence(tmp_path, capsys):
    """Receipt integrity holds across the file write/read JSON round-trip."""
    receipt_path = tmp_path / "receipt.json"
    args = argparse.Namespace(
        name=None,
        topic=_TOPIC,
        list_demos=False,
        server=False,
        receipt=str(receipt_path),
        offline=True,
    )
    demo_main(args)

    reloaded = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert DecisionReceipt.from_dict(reloaded).verify_integrity() is True


def test_live_demo_receipt_builder_is_verifiable(tmp_path, capsys):
    """The live-demo receipt *builder* produces a verifiable receipt.

    This covers ``_build_live_receipt_data`` (the helper that maps a playground
    debate response into receipt fields) and asserts the resulting receipt
    satisfies the same round-trip invariant. It does not drive the full live
    ``_run_real_demo`` → ``_save_live_demo_receipt`` path (which requires API
    access); it guards the builder against the same hash/timestamp regression.
    """
    live_result = {
        "receipt_id": "DR-LIVE-7393",
        "consensus_reached": True,
        "participants": ["claude", "gpt", "gemini"],
        "verdict": "consensus",
        "confidence": 0.71,
        "rounds_used": 3,
        "final_answer": "Prioritize the EU AI Act compliance pipeline.",
        "dissenting_views": [],
        "proposals": {"claude": "yes", "gpt": "yes"},
    }

    receipt_data = _build_live_receipt_data(live_result, _TOPIC, elapsed=2.5)
    assert receipt_data.get("timestamp")
    assert receipt_data.get("artifact_hash")
    assert receipt_data["question"] == _TOPIC

    receipt_path = tmp_path / "live-receipt.json"
    receipt_path.write_text(json.dumps(receipt_data, indent=2, default=str), encoding="utf-8")

    out = _verify_receipt_file(receipt_path, capsys)
    assert "Result: VALID (3/3 checks passed)" in out


def test_clean_install_demo_to_standalone_odr_verifier_round_trip(
    installed_public_wedge: tuple[Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    """One installed artifact crosses every documented zero-key receipt seam."""
    runtime_python, runtime_env = installed_public_wedge
    assert all(name not in runtime_env for name in _PROVIDER_CREDENTIALS)
    assert not any(name.endswith("_API_KEY") for name in runtime_env)
    assert runtime_env["ARAGORA_USE_SECRETS_MANAGER"] == "false"

    workdir = tmp_path / "outside-source-checkout"
    workdir.mkdir()
    native_path = workdir / "decision-receipt.json"
    odr_path = workdir / "decision-receipt.odr.json"

    demo = _run_subprocess(
        [
            str(runtime_python),
            "-m",
            "aragora.cli.main",
            "demo",
            "--offline",
            "--topic",
            _TOPIC,
            "--receipt",
            str(native_path),
        ],
        cwd=workdir,
        env=runtime_env,
    )
    assert "Mode:   Offline" in demo.stdout

    native = json.loads(native_path.read_text(encoding="utf-8"))
    receipt_id = native["receipt_id"]
    assert receipt_id
    native_verify = _run_subprocess(
        [
            str(runtime_python),
            "-m",
            "aragora.cli.main",
            "receipt",
            "verify",
            str(native_path),
        ],
        cwd=workdir,
        env=runtime_env,
    )
    assert receipt_id in native_verify.stdout
    assert "Result: VALID (3/3 checks passed)" in native_verify.stdout

    _run_subprocess(
        [
            str(runtime_python),
            "-m",
            "aragora.cli.main",
            "receipt",
            "export",
            str(native_path),
            "--format",
            "odr",
            "--output",
            str(odr_path),
        ],
        cwd=workdir,
        env=runtime_env,
    )
    odr = json.loads(odr_path.read_text(encoding="utf-8"))
    assert odr["receipt_id"] == receipt_id
    assert odr["source"]["receipt_id"] == receipt_id
    assert odr["source"]["artifact_hash"] == native["artifact_hash"]

    standalone = _run_subprocess(
        [str(runtime_python), "-m", "aragora_verify", str(odr_path), "--json"],
        cwd=workdir,
        env=runtime_env,
    )
    result = json.loads(standalone.stdout)
    assert result["ok"] is True
    assert result["receipt_id"] == receipt_id
    checks = {check["name"]: check["status"] for check in result["checks"]}
    assert checks["schema_conformance"] == "pass"
    assert checks["canonical_digest"] == "pass"
    assert checks["quorum_consistency"] == "pass"
    assert checks["signature"] == "warn"  # unsigned is truthful, never authenticated

    # Mutation/break proof: remove a required claim member from this same
    # exported artifact and require the independently installed verifier to fail closed.
    del odr["claim"]["verdict"]
    tampered_path = workdir / "tampered.odr.json"
    tampered_path.write_text(json.dumps(odr), encoding="utf-8")
    tampered = _run_subprocess(
        [str(runtime_python), "-m", "aragora_verify", str(tampered_path), "--json"],
        cwd=workdir,
        env=runtime_env,
        expected=1,
    )
    tampered_result = json.loads(tampered.stdout)
    assert tampered_result["ok"] is False
    tampered_checks = {check["name"]: check["status"] for check in tampered_result["checks"]}
    assert tampered_checks["schema_conformance"] == "fail"
    assert not Path(runtime_env["ARAGORA_API_KEY_STORE_PATH"]).exists()
