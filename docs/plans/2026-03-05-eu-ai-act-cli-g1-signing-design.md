# EU AI Act CLI Completion + G1 Signed Context Manifests: Design Document

**Date:** 2026-03-05
**Status:** Approved for implementation
**Tracks:** 2

---

## Context

Two remaining gaps from the roadmap review:

1. **EU AI Act CLI**: Article 9 and 15 artifacts are generated in the bundle JSON but individual
   per-article files are not written (unlike 12, 13, 14). Help text is also outdated.
2. **G1 Signed Context Manifests**: No cryptographic provenance for CLAUDE.md/memory files
   ingested by the Nomic Loop context phase — documented gap in THREAT_MODEL.md.

---

## Track 1: EU AI Act CLI — Article 9 & 15 File Output

**Priority:** Completion of existing feature (already implemented in Python, missing CLI surface)

### What Exists

- `aragora/compliance/eu_ai_act.py` — generates all 5 articles including `Article9Artifact` and
  `Article15Artifact` (added Mar 5)
- `aragora/cli/commands/compliance.py` — writes per-article JSON files for 12, 13, 14 only
- `ComplianceArtifactBundle.to_dict()` includes `article_9_risk_management` and
  `article_15_accuracy_robustness` keys in the bundle JSON

### What's Missing

- Write `article_9_risk_management.json` to output directory (same pattern as 12/13/14)
- Write `article_15_accuracy_robustness.json` to output directory
- Update help text in `compliance.py` from "Articles 12/13/14" to "Articles 9/12/13/14/15"

### Design

**Option A (chosen):** Symmetric 5-file output — emit 9 and 15 alongside 12, 13, 14.

Output directory after fix:
```
compliance_bundle.json              (unchanged — already has all 5)
conformity_report.json              (unchanged)
article_9_risk_management.json      (new)
article_12_transparency.json        (unchanged)
article_13_accuracy.json            (unchanged)
article_14_human_oversight.json     (unchanged)
article_15_accuracy_robustness.json (new)
```

**File write pattern** (mirrors existing 12/13/14 logic):
```python
if bundle.article_9:
    art9_path = output_dir / "article_9_risk_management.json"
    art9_path.write_text(json.dumps(bundle.article_9.to_dict(), indent=2))

if bundle.article_15:
    art15_path = output_dir / "article_15_accuracy_robustness.json"
    art15_path.write_text(json.dumps(bundle.article_15.to_dict(), indent=2))
```

**Help text update** — three locations in `compliance.py`:
- Command docstring
- `generate` subcommand description
- Output summary message

### Success Criteria

- `aragora compliance eu-ai-act generate receipt.json` writes 7 files (5 articles + bundle + report)
- `article_9_risk_management.json` and `article_15_accuracy_robustness.json` are valid JSON with
  `integrity_hash` field
- Help text shows "Articles 9/12/13/14/15"
- Existing tests still pass; new test verifies file presence

---

## Track 2: G1 — Signed Context Manifests

**Priority:** Security roadmap G1 — cryptographic provenance for Nomic Loop context ingestion

### What Exists

- `scripts/nomic_loop.py` — Phase 0 loads CLAUDE.md, memory files, recent commits without
  any integrity verification
- `aragora/security/` — `encryption.py`, `anomaly_detection.py`, `ssrf_protection.py` (pattern
  to follow)
- `THREAT_MODEL.md` — documents G1 gap: "Signed context manifests — cryptographic provenance
  for trusted context sources ingested by Nomic Loop and debate orchestrator"

### What's Missing

- `aragora/security/context_signing.py` — sign/verify module
- `.aragora/context_manifest.json` — manifest file (gitignored)
- Verification call in `scripts/nomic_loop.py` context phase
- `aragora context sign` / `aragora context verify` CLI commands

### Design

**`aragora/security/context_signing.py`:**

```python
@dataclass
class ManifestEntry:
    path: str
    sha256: str
    hmac_sha256: str | None   # None when no signing key available
    signed_at: str            # ISO 8601 timestamp
    size_bytes: int

@dataclass
class VerificationResult:
    ok: bool
    verified_files: list[str]
    violations: list[str]   # "path: hash mismatch" or "path: HMAC invalid"
    missing_files: list[str]
    unsigned_files: list[str]  # present but no HMAC (key-less mode)
```

Functions:
- `sign_file(path: Path, key: bytes | None = None) -> ManifestEntry`
  - Reads file, computes SHA-256
  - If `key` provided: HMAC-SHA256 over `sha256 + path + signed_at`
  - Returns `ManifestEntry`
- `create_manifest(paths: list[Path], key: bytes | None = None) -> dict`
  - Signs each file, writes `.aragora/context_manifest.json`
  - Returns manifest dict
- `verify_manifest(manifest_path: Path, key: bytes | None = None) -> VerificationResult`
  - For each entry: reads current file, recomputes SHA-256, compares
  - If key: recomputes HMAC, compares
  - Returns `VerificationResult`
- `get_signing_key() -> bytes | None`
  - Reads `ARAGORA_CONTEXT_SIGNING_KEY` env var (base64-encoded)
  - Returns `None` if absent (hash-only mode)

**Key management:**
- No key → hash-only integrity (detects accidental corruption, not adversarial tampering)
- With `ARAGORA_CONTEXT_SIGNING_KEY` → HMAC-SHA256 authentication (provenance)
- Key stored in environment, never in manifest file
- Constant-time HMAC comparison (`hmac.compare_digest`)

**`scripts/nomic_loop.py` integration:**

In Phase 0 (context load), after loading context files:
```python
from aragora.security.context_signing import verify_manifest, get_signing_key

manifest_path = Path(".aragora/context_manifest.json")
if manifest_path.exists():
    result = verify_manifest(manifest_path, key=get_signing_key())
    if not result.ok:
        logger.warning("Context manifest violations: %s", result.violations)
        context_metadata["context_tainted"] = True
        context_metadata["taint_violations"] = result.violations
    else:
        context_metadata["context_verified"] = True
        context_metadata["verified_files"] = result.verified_files
# If no manifest: context proceeds unverified (backwards compatible)
```

**CLI commands** (`aragora/cli/commands/context_signing.py`):

```
aragora context sign [paths...]     # Sign listed files (default: CLAUDE.md + memory/)
aragora context verify              # Verify against existing manifest
aragora context show                # Print manifest contents
```

Wired into `aragora/cli/parser.py` as `context` subcommand group.

**`.aragora/` directory:** Created automatically by `aragora context sign`. Added to
`.gitignore` (already has `.gt` entries — add `.aragora/`).

### Success Criteria

- `aragora context sign CLAUDE.md` creates `.aragora/context_manifest.json`
- `aragora context verify` exits 0 when manifest matches, 1 with violation list when tampered
- Nomic Loop Phase 0 logs warning and sets `context_tainted=True` when manifest violations detected
- No manifest → Nomic Loop continues silently (zero breaking changes)
- With key → HMAC validation; without key → hash-only
- Tests: sign → verify (pass), sign → tamper file → verify (fail), no manifest → ok

---

## Summary

| Track | Files | Effort | Value |
|-------|-------|--------|-------|
| 1: EU AI Act CLI | 1 file (compliance.py) + 1 test | Tiny | High (compliance completeness) |
| 2: G1 Context Signing | 3 new files + 2 edits + tests | Medium | High (security) |

---

*Design approved 2026-03-05.*
