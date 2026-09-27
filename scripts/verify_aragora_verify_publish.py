#!/usr/bin/env python3
"""Verify the public ``aragora-verify`` PyPI install after publishing.

The publish workflow already builds, checks, and uploads the package. This
helper closes the transport loop by installing the exact published version into
a fresh virtual environment, then proving the installed CLI still accepts a
valid ODR receipt and rejects a spoofed ``key_id`` signature label.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class PublishVerificationError(RuntimeError):
    """Raised when a post-publish verification step fails."""


# PyPI index/CDN propagation lags the upload by seconds to minutes, so the
# freshly published version is routinely not installable the instant the
# publish step returns. This step runs *after* an irreversible upload and
# *before* the GitHub Release is created, and PyPI versions are immutable — so
# a bare single-attempt install turns ordinary propagation delay into a red
# release with no clean rerun path (re-publishing the same version fails).
# Retry with exponential backoff instead of failing on the first miss.
DEFAULT_INSTALL_ATTEMPTS = 8
DEFAULT_INSTALL_BACKOFF = 5.0
MAX_INSTALL_BACKOFF = 60.0

# The whole point of this helper is to prove the artifact is installable from
# *public* PyPI. A self-hosted runner carrying PIP_INDEX_URL / PIP_EXTRA_INDEX_URL
# / pip.conf / find-links pointing at a mirror or local cache could satisfy the
# install from somewhere else entirely and report success while the published
# version is not actually reachable by users. `--isolated` drops env vars and
# config files; the explicit index pins where the package must come from.
DEFAULT_INDEX_URL = "https://pypi.org/simple"


PROBE_SCRIPT = r"""
from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aragora_verify import compute_key_id, odr_content_digest


def valid_odr() -> dict:
    return {
        "odr_version": "0.1",
        "profile": "https://aragora.ai/specs/open-decision-receipt/v0.1",
        "receipt_id": "post-publish-smoke",
        "issued_at": "2026-06-14T00:00:00Z",
        "subject": {
            "identifier": "5f1b14e4b5e113dc978d60d1f6bd21b5a478c744",
            "digest": {"status": "present", "alg": "sha-256", "value": "deadbeef"},
            "summary": "post-publish verifier smoke",
        },
        "claim": {"verdict": "PASS", "statement": "public verifier install works"},
        "reasoning": {"status": "present", "summary": "post-publish smoke"},
        "quorum": {
            "status": "present",
            "method": "majority",
            "reached": True,
            "supporting_agents": ["claude", "grok"],
            "participants": [
                {"agent": "claude", "model_family": "anthropic", "model_id": "claude-opus-4-8"},
                {"agent": "grok", "model_family": "xai", "model_id": "grok-4"},
            ],
            "independence": {
                "disclosed": True,
                "distinct_model_families": 2,
                "model_families": ["anthropic", "xai"],
            },
            "dissent": {"present": False, "dissenting_agents": [], "views": []},
        },
        "confidence": {
            "status": "present",
            "value": 0.9,
            "scale": "unit_interval",
            "calibration": {"status": "absent", "reason": "post-publish smoke"},
        },
        "cruxes": {"status": "absent", "reason": "post-publish smoke"},
        "attestation": {"disposition": "autonomous"},
        "routing": {"status": "reserved"},
        "signatures": [],
    }


def sign_odr(doc: dict, private_key: Ed25519PrivateKey) -> dict:
    signed = copy.deepcopy(doc)
    message = bytes.fromhex(odr_content_digest(signed))
    signature = private_key.sign(message)
    signed["signatures"] = [
        {
            "alg": "Ed25519",
            "key_id": compute_key_id(private_key.public_key()),
            "signature": base64.b64encode(signature).decode("ascii"),
            "signed_at": "2026-06-14T00:00:01Z",
        }
    ]
    return signed


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aragora_verify", *args],
        check=False,
        capture_output=True,
        text=True,
    )


root = Path.cwd()
valid_path = root / "valid.odr.json"
valid_path.write_text(json.dumps(valid_odr(), sort_keys=True), encoding="utf-8")

valid_run = run_cli([str(valid_path), "--json"])
if valid_run.returncode != 0:
    raise SystemExit(
        f"valid receipt failed with exit {valid_run.returncode}: {valid_run.stderr or valid_run.stdout}"
    )

private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()
pubkey_path = root / "pubkey.pem"
pubkey_path.write_bytes(
    public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)

# Positive control: the SAME signing path, unmutated, must verify clean.
# Without this, a spoofed-key_id failure proves nothing — if sign_odr's scheme
# did not match the CLI's, every signed receipt would fail as a bad signature
# and the spoof assertion below would still see exit 1 plus a failing signature
# check, going green for the wrong reason. Establishing that sign_odr produces
# a signature the CLI accepts is what makes the spoof case isolate key_id.
signed = sign_odr(valid_odr(), private_key)
signed_path = root / "signed.odr.json"
signed_path.write_text(json.dumps(signed, sort_keys=True), encoding="utf-8")

signed_run = run_cli([str(signed_path), "--pubkey", str(pubkey_path), "--json"])
if signed_run.returncode != 0:
    raise SystemExit(
        "correctly signed receipt must verify clean, so that the spoofed-key_id "
        f"case isolates key_id binding; got exit {signed_run.returncode}: "
        f"{signed_run.stderr or signed_run.stdout}"
    )

spoofed = sign_odr(valid_odr(), private_key)
spoofed["signatures"][0]["key_id"] = "spoofed-signer-label"
spoofed_path = root / "spoofed-key-id.odr.json"
spoofed_path.write_text(json.dumps(spoofed, sort_keys=True), encoding="utf-8")

spoofed_run = run_cli([str(spoofed_path), "--pubkey", str(pubkey_path), "--json"])
if spoofed_run.returncode != 1:
    raise SystemExit(
        "spoofed key_id receipt should fail with exit 1, got "
        f"{spoofed_run.returncode}: {spoofed_run.stderr or spoofed_run.stdout}"
    )

spoofed_payload = json.loads(spoofed_run.stdout)
signature_checks = [
    check for check in spoofed_payload.get("checks", [])
    if check.get("name") == "signature"
]
if not signature_checks or signature_checks[0].get("status") != "fail":
    raise SystemExit(f"missing failing signature check: {spoofed_run.stdout}")

print(json.dumps({
    "valid_receipt_exit": valid_run.returncode,
    "signed_receipt_exit": signed_run.returncode,
    "spoofed_key_id_exit": spoofed_run.returncode,
    "spoofed_signature_status": signature_checks[0]["status"],
}, sort_keys=True))
"""


@contextmanager
def _verification_workspace(path: Path | None) -> Iterator[Path]:
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="aragora-verify-publish-") as tmp:
        yield Path(tmp)


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _run(
    cmd: list[str], *, timeout: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise PublishVerificationError(
            f"command failed with exit {completed.returncode}: {' '.join(cmd)}\n{detail}"
        )
    return completed


def _run_with_retry(
    cmd: list[str],
    *,
    timeout: int,
    attempts: int,
    backoff: float,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], int]:
    """Run ``cmd``, retrying transient failures with exponential backoff.

    Returns the completed process and the (1-based) attempt number that
    succeeded, so callers can report how much propagation delay was absorbed.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _run(cmd, timeout=timeout, cwd=cwd), attempt
        except (PublishVerificationError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(backoff * (2 ** (attempt - 1)), MAX_INSTALL_BACKOFF))

    raise PublishVerificationError(
        f"command still failing after {attempts} attempt(s): {' '.join(cmd)}\n{last_error}"
    ) from last_error


def verify_publish(
    *,
    version: str,
    python: str,
    work_dir: Path | None = None,
    timeout: int = 240,
    install_attempts: int = DEFAULT_INSTALL_ATTEMPTS,
    install_backoff: float = DEFAULT_INSTALL_BACKOFF,
    index_url: str = DEFAULT_INDEX_URL,
) -> dict[str, object]:
    with _verification_workspace(work_dir) as workspace:
        venv = workspace / ".venv"
        _run([python, "-m", "venv", str(venv)], timeout=timeout)
        venv_python = _venv_python(venv)
        _run_with_retry(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            timeout=timeout,
            attempts=install_attempts,
            backoff=install_backoff,
        )
        _, install_attempts_used = _run_with_retry(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--isolated",
                "--no-cache-dir",
                "--index-url",
                index_url,
                f"aragora-verify=={version}",
            ],
            timeout=timeout,
            attempts=install_attempts,
            backoff=install_backoff,
        )

        version_result = _run(
            [str(venv_python), "-m", "aragora_verify", "--version"],
            timeout=timeout,
        )
        expected_version = f"aragora-verify {version}"
        if version_result.stdout.strip() != expected_version:
            raise PublishVerificationError(
                f"installed CLI version mismatch: expected {expected_version!r}, "
                f"got {version_result.stdout.strip()!r}"
            )

        probe_path = workspace / "post_publish_probe.py"
        probe_path.write_text(textwrap.dedent(PROBE_SCRIPT).strip() + "\n", encoding="utf-8")
        probe_result = _run([str(venv_python), str(probe_path)], timeout=timeout, cwd=workspace)
        try:
            probe_payload = json.loads(probe_result.stdout)
        except json.JSONDecodeError as exc:
            raise PublishVerificationError("post-publish probe returned malformed JSON") from exc

        return {
            "ok": True,
            "package": "aragora-verify",
            "version": version,
            "workspace": str(workspace),
            "install_attempts": install_attempts_used,
            "probe": probe_payload,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a freshly published aragora-verify version from PyPI."
    )
    parser.add_argument("--version", required=True, help="Exact aragora-verify version to install.")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to create the fresh verification virtualenv.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Optional directory for the verification virtualenv and probe artifacts.",
    )
    parser.add_argument("--timeout", type=int, default=240, help="Per-command timeout in seconds.")
    parser.add_argument(
        "--install-attempts",
        type=int,
        default=DEFAULT_INSTALL_ATTEMPTS,
        help=(
            "Attempts for the pip install steps before giving up. Absorbs PyPI "
            "index propagation delay after publish (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--install-backoff",
        type=float,
        default=DEFAULT_INSTALL_BACKOFF,
        help=(
            "Base seconds for exponential backoff between install attempts, "
            f"capped at {MAX_INSTALL_BACKOFF:g}s (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--index-url",
        default=DEFAULT_INDEX_URL,
        help=(
            "Index the published package must be installable from. Combined "
            "with pip --isolated so runner pip config/env cannot satisfy the "
            "install from a mirror or cache (default: %(default)s)."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_publish(
            version=args.version,
            python=args.python,
            work_dir=Path(args.work_dir) if args.work_dir else None,
            timeout=args.timeout,
            install_attempts=args.install_attempts,
            install_backoff=args.install_backoff,
            index_url=args.index_url,
        )
    except PublishVerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"verified aragora-verify=={args.version} from PyPI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
