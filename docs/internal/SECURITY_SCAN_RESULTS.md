# Security Scan Results

**Date:** 2026-02-12
**Tool:** Bandit 1.9.3
**Scope:** `aragora/` (excluding test directories)
**Code Scanned:** 1,175,363 lines across all source modules

## Summary

| Severity | Total Findings | Fixed | Accepted Risk |
|----------|---------------|-------|---------------|
| HIGH     | 10            | 10    | 0             |
| MEDIUM   | 426           | 6     | 420           |
| LOW      | 567           | 0     | 567           |

## Fixes Applied (16 changes across 6 files)

### B324: Weak MD5 Hash Without `usedforsecurity=False` (HIGH, 5 findings fixed)

MD5 was used for non-cryptographic purposes (generating IDs and content hashes) but without
the `usedforsecurity=False` parameter. While not exploitable in context, the parameter
explicitly communicates intent and satisfies FIPS-compliant environments.

**Files changed:**
- `aragora/connectors/conversation_ingestor.py` (3 occurrences) -- conversation ID fallback generation
- `aragora/nomic/sica_improver.py` (2 occurrences) -- cycle ID and file backup hash

**Fix:** Added `usedforsecurity=False` to all `hashlib.md5()` calls.

### B602: Subprocess with `shell=True` (HIGH, 5 findings fixed)

Subprocess calls using `shell=True` allow shell injection if command strings contain
untrusted input. Even with allowlists, `shell=True` enables shell metacharacter injection
(`;`, `|`, `&&`, backticks) within otherwise-allowed command prefixes.

**Files changed:**
- `aragora/agents/devops/agent.py` (1 occurrence) -- command execution engine
- `aragora/nomic/sica_improver.py` (4 occurrences) -- lint, typecheck, and test runners

**Fix:** Replaced `shell=True` with `shell=False` + `shlex.split()` to parse command
strings into argument lists safely. This prevents shell metacharacter injection while
preserving the ability to use space-separated command configs like `"ruff check"`.

### B306: Insecure `tempfile.mktemp()` (MEDIUM, 6 findings fixed)

`tempfile.mktemp()` has a TOCTOU (time-of-check-to-time-of-use) race condition:
another process can create a file at the generated path between name generation and
file creation, potentially leading to symlink attacks or data interception.

**Files changed:**
- `aragora/queue/workers/transcription_worker.py` (2 occurrences) -- audio/video temp files
- `aragora/server/handlers/transcription.py` (2 occurrences) -- uploaded file temp storage
- `aragora/transcription/whisper_backend.py` (2 occurrences) -- WAV conversion and audio extraction

**Fix:** Replaced `tempfile.mktemp()` with `tempfile.mkstemp()` which atomically creates
the file and returns an open file descriptor, eliminating the race window.

## Accepted Risks

### B608: SQL Injection via String Formatting (354 findings, all MEDIUM)

**Status:** Accepted -- false positives.

All flagged instances use f-strings only for table names and column names that come from
class-level constants (e.g., `self.TABLE_NAME`, `self._WEBHOOK_COLUMNS`). All user-supplied
values use parameterized query placeholders (`?` for SQLite, `$N` for PostgreSQL). The
f-string pattern `f"SELECT ... FROM {self.TABLE_NAME} WHERE id = ?"` is safe because
the interpolated parts are developer-controlled constants, not user input.

### B310: `urlopen` with Unaudited URL Schemes (27 findings, all MEDIUM)

**Status:** Accepted -- controlled usage.

All `urlopen` calls target URLs from:
- Configuration (webhook URLs, OAuth provider endpoints)
- Internal service endpoints (billing, CLI commands)
- Pre-validated URLs (the webhook retry queue validates URLs at registration time)

No instances accept arbitrary user-supplied URLs without validation.

### B108: Hardcoded Temp Directory `/tmp` (13 findings, all MEDIUM)

**Status:** Accepted -- operational requirement.

Uses are for sandbox execution directories, backup staging, and operational temp files.
These are appropriate uses of the system temp directory and follow cleanup patterns.

### B104: Binding to All Interfaces `0.0.0.0` (12 findings, all MEDIUM)

**Status:** Accepted -- intentional for containerized deployment.

Server binding to `0.0.0.0` is the standard pattern for Docker/Kubernetes deployments
where the container network handles access control. All instances are in server startup
code where this is the expected behavior.

### B615: HuggingFace Unpinned Model Downloads (10 findings, all MEDIUM)

**Status:** Accepted -- deployment configuration concern.

Model IDs come from application configuration, not user input. Revision pinning is a
deployment-time concern handled through config management, not source code.

### B102: Use of `exec()` (1 finding, MEDIUM)

**Status:** Accepted -- already sandboxed.

The single `exec()` call in `aragora/rlm/repl.py:638` is the RLM REPL execution engine
which is sandboxed with:
- `{"__builtins__": {}}` (empty builtins)
- AST validation before execution
- Post-execution namespace security checks
- Explicit `# noqa: S102` annotation

### B604: Shell Parameter from Variable (1 finding, MEDIUM)

**Status:** Accepted -- guarded.

`aragora/nomic/convoy_executor.py:443` uses a runtime boolean for the `shell` parameter
determined by whether the test command is a string (needs shell) or list (does not).
The command source is either a configured test command or a constructed pytest invocation.

### B704: Markup XSS (1 finding, MEDIUM)

**Status:** Accepted -- by design.

`aragora/server/middleware/xss_protection.py:101` is a `mark_safe()` utility explicitly
documented as "only use for trusted, already-escaped content." This is a standard pattern
in HTML templating frameworks.

### B103: Permissive File Permissions (1 finding, MEDIUM)

**Status:** Accepted -- intentional.

`aragora/worktree/hook_runner.py:290` sets `0o755` on git hook scripts, which is the
standard permission for executable scripts.

### LOW Severity (567 findings)

Low-severity findings (B105 hardcoded strings that look like passwords, B404 subprocess
import, B113 request without timeout) are informational and do not represent actionable
security risks in this codebase.

## Verification

All fixes verified with:
1. `python -c "import ast; ast.parse(...)"` syntax checks on all 6 modified files
2. Full test suite execution for affected modules:
   - `tests/agents/test_devops_agent.py` -- 48 passed
   - `tests/research/test_sica_improver.py` + `tests/nomic/test_sica_settings.py` -- 18 passed
   - `tests/transcription/test_whisper_backend.py` -- 24 passed, 4 skipped
   - `tests/test_conversation_ingestor.py` -- 11 passed
   - `tests/server/handlers/test_transcription_handler.py` + related -- 113 passed
3. Re-scan of fixed files with bandit confirms 0 HIGH findings remaining
