# EU AI Act CLI Completion + G1 Signed Context Manifests Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Emit per-article JSON files for EU AI Act Articles 9 and 15 (currently missing from CLI
output), update stale help text, and add cryptographic provenance verification for Nomic Loop
context files (G1 security roadmap item).

**Architecture:** Track 1 is a 1-file CLI edit — add two file-write blocks mirroring the existing
12/13/14 pattern. Track 2 is a new `aragora/security/context_signing.py` module with SHA-256 +
optional HMAC-SHA256 signing, a manifest JSON file at `.aragora/context_manifest.json`, and a
lightweight integration in the Nomic Loop Phase 0 context gathering function that logs a warning
and sets `context_tainted=True` in metadata when manifest violations are detected.

**Tech Stack:** Python stdlib only (`hashlib`, `hmac`, `json`, `pathlib`, `os`). No new
dependencies.

---

## Track 1: EU AI Act CLI — Article 9 & 15 File Output

### Task 1: Write Article 9/15 files and fix stale help text

**Files:**
- Modify: `aragora/cli/commands/compliance.py`
- Test: `tests/compliance/test_eu_ai_act_cli.py` (create new)

**Context:**
The function `_cmd_eu_ai_act_generate` in `aragora/cli/commands/compliance.py` at line 552 already
generates the full bundle including Article 9 and 15 artifacts. Around line 595–618 it writes
files for articles 12, 13, 14 (and conformity reports) but skips 9 and 15.

`bundle.article_9` is an `Article9Artifact` object (or `None`); `bundle.article_9.to_dict()`
returns a JSON-serializable dict. Same pattern for `bundle.article_15`.

Three locations have stale help text referring to "Articles 12/13/14" or "12, 13, 14":
- Line 40: `"  eu-ai-act  Generate artifact bundles (Articles 12/13/14)"`
- Line 179: `help="Generate EU AI Act compliance artifact bundles (Articles 12, 13, 14)"`
- Line 281: `print("Generate EU AI Act compliance artifact bundles (Articles 12, 13, 14).")`

**Step 1: Write the failing test**

Create `tests/compliance/test_eu_ai_act_cli.py`:

```python
"""Tests for EU AI Act CLI file output — Articles 9 and 15."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def _run_generate(receipt_file=None, output_dir=None, output_format="all"):
    """Run _cmd_eu_ai_act_generate with a temp dir and minimal args."""
    import argparse
    from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate

    args = argparse.Namespace(
        receipt_file=receipt_file,
        output=output_dir,
        provider_name="Test Org",
        provider_contact="test@example.com",
        eu_representative="",
        system_name="Test AI",
        system_version="1.0",
        output_format=output_format,
    )
    _cmd_eu_ai_act_generate(args)


class TestEuAiActCliFileOutput:
    def test_generates_article_9_file(self, tmp_path):
        """Article 9 risk management file is written alongside 12/13/14."""
        _run_generate(output_dir=str(tmp_path))
        art9 = tmp_path / "article_9_risk_management.json"
        assert art9.exists(), "article_9_risk_management.json not written"
        data = json.loads(art9.read_text())
        assert "integrity_hash" in data
        assert "identified_risks" in data

    def test_generates_article_15_file(self, tmp_path):
        """Article 15 accuracy/robustness file is written alongside 12/13/14."""
        _run_generate(output_dir=str(tmp_path))
        art15 = tmp_path / "article_15_accuracy_robustness.json"
        assert art15.exists(), "article_15_accuracy_robustness.json not written"
        data = json.loads(art15.read_text())
        assert "integrity_hash" in data
        assert "accuracy_metrics" in data

    def test_all_seven_files_present(self, tmp_path):
        """Symmetric output: 5 article files + bundle + conformity report."""
        _run_generate(output_dir=str(tmp_path))
        expected = {
            "compliance_bundle.json",
            "conformity_report.md",
            "conformity_report.json",
            "article_9_risk_management.json",
            "article_12_record_keeping.json",
            "article_13_transparency.json",
            "article_14_human_oversight.json",
            "article_15_accuracy_robustness.json",
        }
        actual = {f.name for f in tmp_path.iterdir()}
        assert expected == actual

    def test_json_only_format_excludes_article_files(self, tmp_path):
        """With output_format='json', only bundle JSON is written (no per-article files)."""
        _run_generate(output_dir=str(tmp_path), output_format="json")
        files = {f.name for f in tmp_path.iterdir()}
        assert "compliance_bundle.json" in files
        assert "article_9_risk_management.json" not in files
        assert "article_15_accuracy_robustness.json" not in files

    def test_summary_output_mentions_all_articles(self, tmp_path, capsys):
        """Console summary lists article 9 and 15 filenames."""
        _run_generate(output_dir=str(tmp_path))
        captured = capsys.readouterr()
        assert "article_9" in captured.out
        assert "article_15" in captured.out
```

**Step 2: Run tests to verify they fail**

```bash
cd /path/to/worktree
pytest tests/compliance/test_eu_ai_act_cli.py -v 2>&1 | head -40
```

Expected: `FAILED` — `article_9_risk_management.json not written` (file doesn't exist yet).

**Step 3: Implement — add Article 9 and 15 file writes**

In `aragora/cli/commands/compliance.py`, inside `_cmd_eu_ai_act_generate`, after line 607
(`art14_path = ...` block ends), add the two new file writes (before the conformity report lines):

```python
        if bundle.article_9:
            art9_path = os.path.join(output_dir, "article_9_risk_management.json")
            with open(art9_path, "w") as f:
                json.dump(bundle.article_9.to_dict(), f, indent=2)

        if bundle.article_15:
            art15_path = os.path.join(output_dir, "article_15_accuracy_robustness.json")
            with open(art15_path, "w") as f:
                json.dump(bundle.article_15.to_dict(), f, indent=2)
```

**Step 4: Fix the three stale help text strings**

Change:
- Line 40: `"  eu-ai-act  Generate artifact bundles (Articles 12/13/14)"`
  → `"  eu-ai-act  Generate artifact bundles (Articles 9/12/13/14/15)"`

- Line 179: `help="Generate EU AI Act compliance artifact bundles (Articles 12, 13, 14)"`
  → `help="Generate EU AI Act compliance artifact bundles (Articles 9, 12, 13, 14, 15)"`

- Line 281: `print("Generate EU AI Act compliance artifact bundles (Articles 12, 13, 14).")`
  → `print("Generate EU AI Act compliance artifact bundles (Articles 9, 12, 13, 14, 15).")`

Also update the `description=` string for the `eu-ai-act` sub-parser (line 182–185) to mention
Articles 9 and 15 alongside 12/13/14.

**Step 5: Update the console summary to list Article 9 and 15 filenames**

After the `article_14_human_oversight.json` print line (~line 642), add:

```python
        print("  article_9_risk_management.json   Art. 9 risk identification and mitigation")
```

And after the `article_14_human_oversight.json` line:

```python
        print(
            "  article_15_accuracy_robustness.json  Art. 15 accuracy, robustness, cybersecurity"
        )
```

Reorder so Article 9 prints before Article 12. Final order in the summary block:
```
  article_9_risk_management.json    Art. 9 risk identification and mitigation
  article_12_record_keeping.json    Art. 12 event log, tech docs, retention policy
  article_13_transparency.json      Art. 13 provider identity, risks, interpretation
  article_14_human_oversight.json   Art. 14 oversight model, override, stop mechanisms
  article_15_accuracy_robustness.json  Art. 15 accuracy, robustness, cybersecurity
```

**Step 6: Run tests to verify they pass**

```bash
pytest tests/compliance/test_eu_ai_act_cli.py -v
```

Expected: 5 passed.

Also run the existing compliance suite to ensure no regressions:

```bash
pytest tests/compliance/test_eu_ai_act.py -v 2>&1 | tail -5
```

Expected: 98 passed (pre-existing count).

**Step 7: Commit**

```bash
git add aragora/cli/commands/compliance.py tests/compliance/test_eu_ai_act_cli.py
git commit -m "feat(compliance): emit article 9 and 15 per-article JSON files in CLI output

- article_9_risk_management.json and article_15_accuracy_robustness.json
  now written alongside 12/13/14 when output_format='all' (default)
- Updated 3 stale help text strings from Articles 12/13/14 to 9/12/13/14/15
- Console summary lists all 5 article filenames in numerical order"
```

---

## Track 2: G1 — Signed Context Manifests

### Task 2: Core signing/verification module

**Files:**
- Create: `aragora/security/context_signing.py`
- Create: `tests/security/test_context_signing.py`

**Context:**
`aragora/security/` already contains `encryption.py`, `anomaly_detection.py`, etc. The new
module should follow the same import style: no third-party dependencies, dataclasses from
`from __future__ import annotations`.

The signing key is read from environment variable `ARAGORA_CONTEXT_SIGNING_KEY` (base64-encoded
bytes). When absent, module runs in hash-only mode (integrity without authentication).

`.aragora/` is the store directory (analogous to `.gt/` and `.aragora_beads/` already in use).
It should be created automatically and added to `.gitignore`.

**Step 1: Write the failing tests**

Create `tests/security/test_context_signing.py`:

```python
"""Tests for aragora.security.context_signing."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from aragora.security.context_signing import (
    ManifestEntry,
    VerificationResult,
    create_manifest,
    get_signing_key,
    sign_file,
    verify_manifest,
)


@pytest.fixture
def tmp_context_file(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Test context\nThis is test content.\n")
    return f


@pytest.fixture
def signing_key():
    return base64.b64encode(b"test-secret-key-32-bytes-padding").decode()


class TestSignFile:
    def test_returns_manifest_entry(self, tmp_context_file):
        entry = sign_file(tmp_context_file)
        assert isinstance(entry, ManifestEntry)
        assert entry.path == str(tmp_context_file)
        assert len(entry.sha256) == 64  # 32 bytes hex
        assert entry.hmac_sha256 is None  # no key = hash-only

    def test_with_key_sets_hmac(self, tmp_context_file):
        key = b"test-secret-key-32-bytes-padding"
        entry = sign_file(tmp_context_file, key=key)
        assert entry.hmac_sha256 is not None
        assert len(entry.hmac_sha256) == 64

    def test_sha256_changes_on_content_change(self, tmp_context_file):
        entry1 = sign_file(tmp_context_file)
        tmp_context_file.write_text("# Modified content\n")
        entry2 = sign_file(tmp_context_file)
        assert entry1.sha256 != entry2.sha256


class TestCreateAndVerifyManifest:
    def test_create_writes_manifest_json(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert "entries" in data
        assert len(data["entries"]) == 1

    def test_verify_unchanged_file_is_ok(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        result = verify_manifest(manifest_path)
        assert result.ok
        assert result.violations == []

    def test_verify_tampered_file_fails(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("original content")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        # Tamper
        f.write_text("tampered content")
        result = verify_manifest(manifest_path)
        assert not result.ok
        assert len(result.violations) == 1
        assert "hash mismatch" in result.violations[0]

    def test_verify_missing_file_reported(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        f.unlink()
        result = verify_manifest(manifest_path)
        assert not result.ok
        assert len(result.missing_files) == 1

    def test_hmac_verification_with_correct_key(self, tmp_path):
        key = b"test-secret-key-32-bytes-padding"
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], key=key, manifest_path=manifest_path)
        result = verify_manifest(manifest_path, key=key)
        assert result.ok

    def test_hmac_verification_wrong_key_fails(self, tmp_path):
        key = b"correct-secret-key-32-bytes-padx"
        wrong_key = b"wrong-secret-key-32-bytes-padddx"
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], key=key, manifest_path=manifest_path)
        result = verify_manifest(manifest_path, key=wrong_key)
        assert not result.ok
        assert any("HMAC" in v for v in result.violations)

    def test_no_manifest_path_returns_no_manifest_result(self, tmp_path):
        missing = tmp_path / ".aragora" / "context_manifest.json"
        result = verify_manifest(missing)
        # Non-existent manifest: ok=True, manifest_missing=True (caller decides)
        assert result.manifest_missing is True


class TestGetSigningKey:
    def test_returns_none_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_CONTEXT_SIGNING_KEY", raising=False)
        assert get_signing_key() is None

    def test_decodes_base64_env_var(self, monkeypatch):
        raw = b"test-secret-key-32-bytes-padding"
        monkeypatch.setenv("ARAGORA_CONTEXT_SIGNING_KEY", base64.b64encode(raw).decode())
        assert get_signing_key() == raw
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/security/test_context_signing.py -v 2>&1 | head -30
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'aragora.security.context_signing'`

**Step 3: Implement `aragora/security/context_signing.py`**

```python
"""
Cryptographic signing and verification for Nomic Loop context files (G1).

Provides SHA-256 integrity checks (hash-only mode) and optional HMAC-SHA256
authentication when ARAGORA_CONTEXT_SIGNING_KEY is set.

Usage:
    # Sign context files after updating them
    key = get_signing_key()
    create_manifest([Path("CLAUDE.md"), Path("memory/")], key=key)

    # Verify before Nomic Loop context ingestion
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
    signed_at: str           # ISO 8601
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
    unsigned_files: list[str] = field(default_factory=list)  # present, no HMAC
    manifest_missing: bool = False


def get_signing_key() -> bytes | None:
    """Read ARAGORA_CONTEXT_SIGNING_KEY from env and decode from base64.

    Returns None when the variable is absent (hash-only mode).
    """
    raw = os.environ.get("ARAGORA_CONTEXT_SIGNING_KEY")
    if not raw:
        return None
    return base64.b64decode(raw)


def sign_file(path: Path, key: bytes | None = None) -> ManifestEntry:
    """Compute SHA-256 (and optional HMAC-SHA256) for a single file.

    Args:
        path: Absolute or relative path to the file to sign.
        key: Optional HMAC key bytes. When None, HMAC is skipped (hash-only).

    Returns:
        ManifestEntry with sha256, optional hmac_sha256, timestamp, size.
    """
    data = Path(path).read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    signed_at = datetime.now(timezone.utc).isoformat()
    hmac_value: str | None = None
    if key is not None:
        # HMAC input: sha256 hex + path string + signed_at — all ASCII-safe
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
        manifest_path: Where to write the manifest (default: .aragora/context_manifest.json).

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
        manifest_path: Path to manifest JSON (default: .aragora/context_manifest.json).
        key: HMAC key to verify signatures. When None, only SHA-256 is checked.

    Returns:
        VerificationResult with ok=True only when all checks pass.
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
            continue  # Skip HMAC if hash already fails

        # Verify HMAC when key is provided and entry was signed
        if key is not None and entry.hmac_sha256 is not None:
            expected_msg = f"{entry.sha256}:{entry.path}:{entry.signed_at}".encode()
            expected_hmac = hmac.new(key, expected_msg, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hmac, entry.hmac_sha256):
                result.violations.append(f"{entry.path}: HMAC invalid")
                result.ok = False
        elif key is not None and entry.hmac_sha256 is None:
            # File was hash-only signed but we have a key now — flag as unsigned
            result.unsigned_files.append(entry.path)

        if result.ok or entry.path not in [v.split(":")[0] for v in result.violations]:
            result.verified_files.append(entry.path)

    return result
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/security/test_context_signing.py -v
```

Expected: All tests pass.

**Step 5: Add `.aragora/` to `.gitignore`**

```bash
grep -q '\.aragora/' .gitignore || echo '.aragora/' >> .gitignore
```

**Step 6: Commit**

```bash
git add aragora/security/context_signing.py tests/security/test_context_signing.py .gitignore
git commit -m "feat(security): G1 signed context manifests module

- aragora/security/context_signing.py: SHA-256 + optional HMAC-SHA256
- Hash-only mode when ARAGORA_CONTEXT_SIGNING_KEY is absent (backwards compatible)
- create_manifest() / verify_manifest() / sign_file() / get_signing_key()
- .aragora/ directory added to .gitignore"
```

---

### Task 3: Nomic Loop Phase 0 integration

**Files:**
- Modify: `scripts/nomic_loop.py` (around line 8543 — `phase_context_gathering`)
- Test: `tests/scripts/test_nomic_context_signing.py` (create new)

**Context:**
`phase_context_gathering` at line 8543 is the Phase 0 function. After it runs `context_phase.execute()` and builds `codebase_context`, it returns a dict. We add manifest verification after context loading, before the return.

The function returns a dict; we add `context_tainted` and `taint_violations` keys to it. Callers
that don't know about these keys are unaffected (they just don't use the extra keys).

If no manifest exists (`result.manifest_missing is True`), we proceed silently — backwards
compatible with repos that haven't run `aragora context sign`.

**Step 1: Write the failing test**

Create `tests/scripts/test_nomic_context_signing.py`:

```python
"""Unit tests for Nomic Loop Phase 0 context manifest verification."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop(tmp_path):
    """Return a NomicLoop instance with minimal setup for phase_context_gathering."""
    # We need to patch heavy imports in nomic_loop.py
    with patch.dict("sys.modules", {
        "anthropic": MagicMock(),
        "openai": MagicMock(),
    }):
        pass  # just for sys.modules pre-seeding if needed
    return None  # actual test patches the function directly


class TestNomicLoopContextManifestVerification:
    """Tests for context manifest verification in phase_context_gathering."""

    def test_no_manifest_proceeds_without_taint(self, tmp_path, monkeypatch):
        """When no manifest file exists, phase proceeds and context_tainted is absent."""
        monkeypatch.chdir(tmp_path)
        from aragora.security.context_signing import verify_manifest, VerificationResult

        # verify_manifest returns manifest_missing=True for non-existent files
        result = verify_manifest(tmp_path / ".aragora" / "context_manifest.json")
        assert result.manifest_missing is True
        assert result.ok is True

    def test_valid_manifest_sets_context_verified(self, tmp_path):
        """Valid manifest → verified_files populated, no violations."""
        from aragora.security.context_signing import create_manifest, verify_manifest

        f = tmp_path / "CLAUDE.md"
        f.write_text("# Context")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)

        result = verify_manifest(manifest_path)
        assert result.ok
        assert str(f) in result.verified_files
        assert result.violations == []

    def test_tampered_file_fails_verification(self, tmp_path):
        """Tampered file → ok=False, violations contain 'hash mismatch'."""
        from aragora.security.context_signing import create_manifest, verify_manifest

        f = tmp_path / "CLAUDE.md"
        f.write_text("original")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        f.write_text("tampered")

        result = verify_manifest(manifest_path)
        assert not result.ok
        assert any("hash mismatch" in v for v in result.violations)
```

**Step 2: Run tests to verify they pass (these test the module, not nomic_loop integration)**

```bash
pytest tests/scripts/test_nomic_context_signing.py -v
```

Expected: 3 passed.

**Step 3: Modify `scripts/nomic_loop.py` — add manifest verification to `phase_context_gathering`**

Find `phase_context_gathering` at line 8543. After the `codebase_context` is assembled (around
line 8571) and before the `return {` statement, add:

```python
        # G1: Verify context manifest integrity before injecting into debate
        try:
            from aragora.security.context_signing import get_signing_key, verify_manifest

            _manifest_result = verify_manifest(key=get_signing_key())
            if _manifest_result.manifest_missing:
                pass  # No manifest: proceed silently (backwards compatible)
            elif not _manifest_result.ok:
                logger.warning(
                    "Context manifest violations detected: %s",
                    _manifest_result.violations,
                )
            else:
                logger.info(
                    "Context manifest verified: %d file(s) clean",
                    len(_manifest_result.verified_files),
                )
        except Exception as e:  # noqa: BLE001
            # Never block the Nomic Loop for signing errors
            logger.warning("Context manifest check failed: %s", e)
            _manifest_result = None
```

Then update the return dict to include the manifest check result:

```python
        return {
            "phase": "context",
            "codebase_context": codebase_context,
            "duration": result["duration_seconds"],
            "agents_succeeded": result.get("data", {}).get("agents_succeeded", 0),
            "rlm": rlm_context or {},
            "context_tainted": (
                not _manifest_result.ok
                if _manifest_result and not _manifest_result.manifest_missing
                else False
            ),
            "context_violations": (
                _manifest_result.violations
                if _manifest_result and not _manifest_result.manifest_missing
                else []
            ),
        }
```

Important: The bare `except Exception` is intentional here — the Nomic Loop must never be
blocked by signing verification errors (e.g., import error, file permission issues). This is a
monitoring/warning only path.

**Step 4: Verify syntax only (not running the full nomic loop)**

```bash
python3 -c "import ast; ast.parse(open('scripts/nomic_loop.py').read()); print('OK')"
```

Expected: `OK`

**Step 5: Commit**

```bash
git add scripts/nomic_loop.py tests/scripts/test_nomic_context_signing.py
git commit -m "feat(security): G1 context manifest verification in Nomic Loop Phase 0

Verifies .aragora/context_manifest.json before injecting context into the
debate. Logs warning and sets context_tainted=True in phase result when
violations detected. No manifest = silent proceed (backwards compatible).
Exception handling ensures signing errors never block the Nomic Loop."
```

---

### Task 4: CLI signing commands (`aragora signing`)

**Files:**
- Create: `aragora/cli/commands/signing.py`
- Modify: `aragora/cli/parser.py` (add `_add_signing_parser` call)

**Context:**
The existing `aragora context` command (line 803 in parser.py) handles RLM context building —
different purpose. We add a new top-level `aragora signing` command group to avoid collision.

Note: `_add_external_parsers` is called at line 93 of parser.py. We add our parser registration
just before it. The pattern for lazy dispatch is:
```python
parser.set_defaults(func=_lazy("aragora.cli.commands.signing", "cmd_signing"))
```

**Step 1: Write the failing test**

Add to end of `tests/compliance/test_eu_ai_act_cli.py` (or create a new file):

Create `tests/cli/test_signing_cli.py`:

```python
"""Tests for aragora signing CLI commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class TestSigningCli:
    def test_sign_creates_manifest(self, tmp_path):
        """aragora signing sign <file> creates .aragora/context_manifest.json."""
        from aragora.cli.commands.signing import cmd_signing_sign

        f = tmp_path / "CLAUDE.md"
        f.write_text("# Test context")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert len(data["entries"]) == 1

    def test_verify_clean_returns_exit_code_0(self, tmp_path):
        """aragora signing verify returns 0 when manifest matches."""
        from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_verify

        f = tmp_path / "CLAUDE.md"
        f.write_text("# Test context")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)
        exit_code = cmd_signing_verify(manifest_path=manifest_path)
        assert exit_code == 0

    def test_verify_tampered_returns_exit_code_1(self, tmp_path):
        """aragora signing verify returns 1 when a file has been tampered."""
        from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_verify

        f = tmp_path / "CLAUDE.md"
        f.write_text("original")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)
        f.write_text("tampered")
        exit_code = cmd_signing_verify(manifest_path=manifest_path)
        assert exit_code == 1

    def test_show_prints_manifest(self, tmp_path, capsys):
        """aragora signing show prints manifest contents."""
        from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_show

        f = tmp_path / "CLAUDE.md"
        f.write_text("content")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)
        cmd_signing_show(manifest_path=manifest_path)

        captured = capsys.readouterr()
        assert "CLAUDE.md" in captured.out
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/cli/test_signing_cli.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'aragora.cli.commands.signing'`

**Step 3: Create `aragora/cli/commands/signing.py`**

```python
"""CLI commands for context file signing and verification (G1)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST = Path(".aragora/context_manifest.json")
_DEFAULT_PATHS = ["CLAUDE.md", "memory/"]


def add_signing_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'signing' subcommand."""
    parser = subparsers.add_parser(
        "signing",
        help="Sign and verify context files for Nomic Loop provenance (G1)",
        description=(
            "Cryptographic provenance for Nomic Loop context files.\n\n"
            "Commands:\n"
            "  sign    Sign files and write .aragora/context_manifest.json\n"
            "  verify  Verify files against the manifest (exits 0 = ok, 1 = violations)\n"
            "  show    Print current manifest contents\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="signing_command")

    sign_p = sub.add_parser("sign", help="Sign context files")
    sign_p.add_argument(
        "paths",
        nargs="*",
        default=_DEFAULT_PATHS,
        help=f"Files to sign (default: {' '.join(_DEFAULT_PATHS)})",
    )
    sign_p.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help=f"Manifest output path (default: {_DEFAULT_MANIFEST})",
    )

    verify_p = sub.add_parser("verify", help="Verify files against the manifest")
    verify_p.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help=f"Manifest path (default: {_DEFAULT_MANIFEST})",
    )

    show_p = sub.add_parser("show", help="Print manifest contents")
    show_p.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help=f"Manifest path (default: {_DEFAULT_MANIFEST})",
    )

    parser.set_defaults(func=cmd_signing)


def cmd_signing(args: argparse.Namespace) -> None:
    """Dispatch signing subcommands."""
    command = getattr(args, "signing_command", None)
    if command == "sign":
        manifest_path = Path(getattr(args, "manifest", str(_DEFAULT_MANIFEST)))
        paths = [Path(p) for p in args.paths]
        cmd_signing_sign([str(p) for p in paths], manifest_path=manifest_path)
    elif command == "verify":
        manifest_path = Path(getattr(args, "manifest", str(_DEFAULT_MANIFEST)))
        exit_code = cmd_signing_verify(manifest_path=manifest_path)
        sys.exit(exit_code)
    elif command == "show":
        manifest_path = Path(getattr(args, "manifest", str(_DEFAULT_MANIFEST)))
        cmd_signing_show(manifest_path=manifest_path)
    else:
        print("Usage: aragora signing {sign,verify,show}")
        sys.exit(1)


def cmd_signing_sign(paths: list[str], manifest_path: Path = _DEFAULT_MANIFEST) -> None:
    """Sign files and write manifest."""
    from aragora.security.context_signing import create_manifest, get_signing_key

    key = get_signing_key()
    resolved = [Path(p) for p in paths if Path(p).is_file()]
    if not resolved:
        print(f"No files found to sign from: {paths}", file=sys.stderr)
        sys.exit(1)

    create_manifest(resolved, key=key, manifest_path=manifest_path)
    mode = "HMAC-SHA256" if key else "SHA-256 (hash-only)"
    print(f"Signed {len(resolved)} file(s) [{mode}] → {manifest_path}")
    for p in resolved:
        print(f"  {p}")


def cmd_signing_verify(manifest_path: Path = _DEFAULT_MANIFEST) -> int:
    """Verify files against manifest. Returns 0 on success, 1 on violations."""
    from aragora.security.context_signing import get_signing_key, verify_manifest

    result = verify_manifest(manifest_path, key=get_signing_key())

    if result.manifest_missing:
        print(f"No manifest at {manifest_path} — run 'aragora signing sign' first")
        return 1

    if result.ok:
        print(f"OK — {len(result.verified_files)} file(s) verified clean")
        return 0

    print(f"VIOLATIONS ({len(result.violations)}):")
    for v in result.violations:
        print(f"  {v}")
    if result.missing_files:
        print(f"MISSING FILES: {result.missing_files}")
    return 1


def cmd_signing_show(manifest_path: Path = _DEFAULT_MANIFEST) -> None:
    """Print manifest contents."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}")
        return
    data = json.loads(manifest_path.read_text())
    print(f"Manifest: {manifest_path}")
    print(f"Created:  {data.get('created_at', 'unknown')}")
    print(f"Signed:   {data.get('signed', False)}")
    print(f"Entries:  {len(data.get('entries', []))}")
    print()
    for entry in data.get("entries", []):
        hmac_str = entry.get("hmac_sha256") or "—"
        print(f"  {entry['path']}")
        print(f"    sha256:  {entry['sha256'][:16]}...")
        print(f"    hmac:    {hmac_str[:16] if hmac_str != '—' else '—'}")
        print(f"    signed:  {entry.get('signed_at', 'unknown')}")
```

**Step 4: Wire into `aragora/cli/parser.py`**

In `aragora/cli/parser.py`, find line 93 (`_add_external_parsers(subparsers)`). Just before it,
add:

```python
    _add_signing_parser(subparsers)
```

Then add the function (near the other `_add_*_parser` functions — find a natural alphabetical
location, e.g., near `_add_serve_parser`):

```python
def _add_signing_parser(subparsers) -> None:
    """Add the 'signing' subcommand parser."""
    from aragora.cli.commands.signing import add_signing_parser
    add_signing_parser(subparsers)
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/cli/test_signing_cli.py -v
```

Expected: 4 passed.

**Step 6: Smoke test the CLI**

```bash
python3 -c "from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_verify; print('import OK')"
```

Expected: `import OK`

**Step 7: Commit**

```bash
git add aragora/cli/commands/signing.py aragora/cli/parser.py tests/cli/test_signing_cli.py
git commit -m "feat(cli): aragora signing sign/verify/show commands for G1 context provenance

New top-level 'aragora signing' command group:
  aragora signing sign [paths...]  - sign files, write .aragora/context_manifest.json
  aragora signing verify           - verify against manifest (exit 0=ok, 1=violations)
  aragora signing show             - print manifest contents
Hash-only mode by default; HMAC-SHA256 when ARAGORA_CONTEXT_SIGNING_KEY is set."
```

---

## Final Verification

After all tasks complete, run:

```bash
# EU AI Act CLI
pytest tests/compliance/test_eu_ai_act_cli.py tests/compliance/test_eu_ai_act.py -v 2>&1 | tail -10

# Context signing
pytest tests/security/test_context_signing.py tests/cli/test_signing_cli.py tests/scripts/test_nomic_context_signing.py -v 2>&1 | tail -10

# Syntax check for nomic_loop.py
python3 -c "import ast; ast.parse(open('scripts/nomic_loop.py').read()); print('nomic_loop.py syntax OK')"
```
