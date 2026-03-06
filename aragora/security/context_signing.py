"""
Cryptographic signing and verification for Nomic Loop context files (G1).

Provides SHA-256 integrity checks (hash-only mode) and optional HMAC-SHA256
authentication when ARAGORA_CONTEXT_SIGNING_KEY is set.

Usage:
    key = get_signing_key()
    create_manifest([Path("CLAUDE.md"), Path("memory/")], key=key)

    result = verify_manifest(Path(".aragora/context_manifest.json"), key=key)
    if not result.ok:
        logger.warning("Context manifest violations: %s", result.violations)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST_PATH = Path(".aragora/context_manifest.json")


@dataclass
class ManifestEntry:
    path: str
    sha256: str
    hmac_sha256: str | None  # None in hash-only mode
    signed_at: str  # ISO 8601
    size_bytes: int

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "hmac_sha256": self.hmac_sha256,
            "signed_at": self.signed_at,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ManifestEntry":
        return cls(
            path=d["path"],
            sha256=d["sha256"],
            hmac_sha256=d.get("hmac_sha256"),
            signed_at=d["signed_at"],
            size_bytes=d.get("size_bytes", 0),
        )


@dataclass
class VerificationResult:
    ok: bool
    verified_files: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    unsigned_files: list[str] = field(default_factory=list)
    manifest_missing: bool = False


def get_signing_key() -> bytes | None:
    """Read ARAGORA_CONTEXT_SIGNING_KEY from env and decode from base64.

    Returns None when absent (hash-only mode).
    """
    raw = os.environ.get("ARAGORA_CONTEXT_SIGNING_KEY")
    if not raw:
        return None
    return base64.b64decode(raw)


def sign_file(path: Path, key: bytes | None = None) -> ManifestEntry:
    """Compute SHA-256 (and optional HMAC-SHA256) for a single file.

    Args:
        path: Path to the file to sign.
        key: Optional HMAC key bytes. When None, HMAC is skipped (hash-only).

    Returns:
        ManifestEntry with sha256, optional hmac_sha256, timestamp, size.
    """
    data = Path(path).read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    signed_at = datetime.now(timezone.utc).isoformat()
    hmac_value: str | None = None
    if key is not None:
        msg = f"{sha256}:{path}:{signed_at}".encode()
        hmac_value = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return ManifestEntry(
        path=str(path),
        sha256=sha256,
        hmac_sha256=hmac_value,
        signed_at=signed_at,
        size_bytes=len(data),
    )


def create_manifest(
    paths: list[Path],
    key: bytes | None = None,
    manifest_path: Path | None = None,
) -> dict:
    """Sign a list of files and write a manifest JSON.

    Args:
        paths: Files to include in the manifest.
        key: Optional HMAC key. When None, hash-only mode.
        manifest_path: Where to write the manifest.

    Returns:
        The manifest dict that was written.
    """
    if manifest_path is None:
        manifest_path = _DEFAULT_MANIFEST_PATH
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    for p in paths:
        p = Path(p)
        if p.is_file():
            entries.append(sign_file(p, key=key).to_dict())
        else:
            logger.warning("context_signing: skipping non-file path: %s", p)

    manifest = {
        "version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signed": key is not None,
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def verify_manifest(
    manifest_path: Path | None = None,
    key: bytes | None = None,
) -> VerificationResult:
    """Verify all files in a context manifest.

    Args:
        manifest_path: Path to manifest JSON.
        key: HMAC key to verify signatures. When None, only SHA-256 is checked.

    Returns:
        VerificationResult with ok=True only when all checks pass.
        When manifest does not exist, returns ok=True with manifest_missing=True.
    """
    if manifest_path is None:
        manifest_path = _DEFAULT_MANIFEST_PATH
    manifest_path = Path(manifest_path)

    if not manifest_path.exists():
        return VerificationResult(ok=True, manifest_missing=True)

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return VerificationResult(ok=False, violations=[f"Cannot read manifest: {e}"])

    result = VerificationResult(ok=True)
    for entry_dict in manifest.get("entries", []):
        entry = ManifestEntry.from_dict(entry_dict)
        p = Path(entry.path)

        if not p.exists():
            result.missing_files.append(entry.path)
            result.violations.append(f"{entry.path}: file missing")
            result.ok = False
            continue

        current_data = p.read_bytes()
        current_sha256 = hashlib.sha256(current_data).hexdigest()

        if current_sha256 != entry.sha256:
            result.violations.append(f"{entry.path}: hash mismatch")
            result.ok = False
            continue

        if key is not None:
            if entry.hmac_sha256 is None:
                # Signed without key, now verifying with key — treat as failure
                result.unsigned_files.append(entry.path)
                result.violations.append(f"{entry.path}: HMAC signature missing")
                result.ok = False
                continue
            expected_msg = f"{entry.sha256}:{entry.path}:{entry.signed_at}".encode()
            expected_hmac = hmac.new(key, expected_msg, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hmac, entry.hmac_sha256):
                result.violations.append(f"{entry.path}: HMAC invalid")
                result.ok = False
                continue

        # Only reach here if all checks passed
        result.verified_files.append(entry.path)

    return result
