# ARAGORA SECURITY AUDIT REPORT - INPUT VALIDATION ACROSS HANDLER LAYER

**Generated:** 2026-02-02
**Scope:** `~/aragora/aragora/server/handlers` (579 files analyzed)
**Analysis Type:** Input validation, injection vulnerability detection, SSRF/XXE/CSRF/command injection assessment

---

## FINDINGS SUMMARY

| Severity | Count | Status |
|----------|-------|--------|
| Critical | 0 | ✓ None Found |
| High | 0 | ✓ Fixed (2026-02-03) |
| Medium | 2 | ⚠ Requires Improvement |
| Low | 0 | ✓ None Found |
| **Total** | **2** | |

---

## CRITICAL FINDINGS

None found.

---

## HIGH SEVERITY FINDINGS

### Issue #1: Missing SSRF Validation for Webhook URLs

**File:** `~/aragora/aragora/server/handlers/external_integrations.py`
**Lines:** 555-576, 768-792, 910
**Severity:** HIGH → ✓ FIXED (2026-02-03)
**Type:** Server-Side Request Forgery (SSRF)
**Resolution:** `validate_webhook_url()` is now called at all three locations (Zapier line 570, Make line 783, n8n line 919)

#### Description

The `external_integrations.py` handler accepts user-supplied webhook URLs for third-party integrations (Zapier, Make, n8n) but **does NOT validate them against SSRF attacks**.

#### Vulnerable Code Pattern

```python
# Line 559: Gets webhook_url from user input WITHOUT validation
webhook_url = body.get("webhook_url")

# Line 565-566: Only checks if field exists
if not webhook_url:
    return error_response("webhook_url is required", 400)

# Line 572: Passes directly to integration (UNSANITIZED)
trigger = zapier.subscribe_trigger(
    app_id=app_id,
    trigger_type=trigger_type,
    webhook_url=webhook_url,  # ⚠ NO SSRF VALIDATION
    workspace_id=body.get("workspace_id"),
    debate_tags=body.get("debate_tags"),
    min_confidence=body.get("min_confidence"),
)
```

Also affected:
- Lines 768-792: Make integration webhook registration
- Line 910: `api_url` parameter for integrations

#### Attack Vectors

An attacker could supply malicious URLs to probe internal infrastructure:

```
POST /api/integrations/zapier/triggers
{
    "webhook_url": "http://127.0.0.1:5432",           # PostgreSQL port scan
    "webhook_url": "http://169.254.169.254/latest/meta-data",  # AWS metadata
    "webhook_url": "http://internal-service.local/api/admin",   # Internal service
    "webhook_url": "http://192.168.1.100:8080",       # Private network scan
}
```

#### Recommended Fix

Import and use the existing `validate_webhook_url()` function (already in codebase):

```python
from aragora.server.handlers.utils.url_security import validate_webhook_url

# Validate webhook URL before use
webhook_url = body.get("webhook_url")
if not webhook_url:
    return error_response("webhook_url is required", 400)

is_valid, error_msg = validate_webhook_url(webhook_url, allow_localhost=False)
if not is_valid:
    return error_response(f"Invalid webhook URL: {error_msg}", 400)

# Now safe to use webhook_url
trigger = zapier.subscribe_trigger(
    app_id=app_id,
    trigger_type=trigger_type,
    webhook_url=webhook_url,  # ✓ VALIDATED
    ...
)
```

#### Evidence of Safe Implementation

The same validation function is **already properly used** in:
- `~/aragora/aragora/server/handlers/debates/batch.py:237`
- `~/aragora/aragora/server/handlers/webhooks.py:617, 723`

This demonstrates the team is aware of SSRF protection; the gap is only in `external_integrations.py`.

---

## MEDIUM SEVERITY FINDINGS

### Issue #2: Subprocess Parameter Validation Improvements

**File:** `~/aragora/aragora/server/handlers/nomic.py`
**Lines:** 716-722 (subprocess call), 687-695 (parameter validation)
**Severity:** MEDIUM
**Type:** Command Injection (Low Risk - Currently Safe, but Could Be More Defensive)

#### Current Assessment: SAFE

The current implementation is **already safe** because:
1. ✓ Uses `subprocess.Popen()` with **list form** (not `shell=True`)
2. ✓ Integer parameters are **strictly validated and bounded**
3. ✓ Script path is **hardcoded** and checked for existence

#### Code Review

```python
# Lines 687-694: Parameter validation is good
cycles = int(body.get("cycles", 1))
max_cycles = int(body.get("max_cycles", 10))
cycles = max(1, min(cycles, 100))          # ✓ Bounded to 1-100
max_cycles = max(1, min(max_cycles, 100))

# Lines 706-713: Safe use of subprocess (list form)
cmd = [
    "python",
    str(script_path),
    "--cycles",
    str(min(cycles, max_cycles)),
]
if auto_approve:
    cmd.append("--auto-approve")

# Lines 716-722: Popen with list (prevents shell injection)
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(nomic_dir.parent.parent),
    start_new_session=True,
)
```

#### Recommended Improvement

Add explicit type/range validation to be more defensive:

```python
# Add validation helpers
def validate_cycle_params(cycles: int, max_cycles: int) -> tuple[bool, str]:
    """Validate cycle parameters."""
    if not isinstance(cycles, int):
        return False, "cycles must be an integer"
    if not isinstance(max_cycles, int):
        return False, "max_cycles must be an integer"
    if cycles < 1 or cycles > 100:
        return False, "cycles must be between 1 and 100"
    if max_cycles < 1 or max_cycles > 100:
        return False, "max_cycles must be between 1 and 100"
    return True, ""

# Use in handler
try:
    cycles = int(body.get("cycles", 1))
    max_cycles = int(body.get("max_cycles", 10))
except (ValueError, TypeError):
    return error_response("cycles and max_cycles must be integers", 400)

is_valid, error_msg = validate_cycle_params(cycles, max_cycles)
if not is_valid:
    return error_response(error_msg, 400)
```

---

### Issue #3: Code Example in Codebase Audit Handler

**File:** `~/aragora/aragora/server/handlers/features/codebase_audit/scanning.py`
**Line:** 473
**Severity:** MEDIUM (Low Risk - Intentional)
**Type:** Security Pattern Detection

#### Assessment: ACCEPTABLE

```python
code_snippet='os.system(f"convert {filename} output.pdf")',
```

This is a **static string** used as a test case to demonstrate the codebase audit tool's ability to detect command injection vulnerabilities. It is **NOT executed or evaluated**.

**Why This Is Acceptable:**
- ✓ Part of security scanning functionality itself
- ✓ Used only as a detection pattern, not executed
- ✓ Demonstrates correct pattern matching for vulnerability detection

---

## VALIDATION STRENGTHS FOUND

### 1. File Upload Validation - EXCELLENT ✓

**File:** `~/aragora/aragora/server/handlers/features/smart_upload.py`

- ✓ Magic byte signature validation (89 PNG, FFD8FF JPEG, etc.)
- ✓ Blocks dangerous MIME types (executables, shell scripts)
- ✓ Detects extension/content mismatches
- ✓ Blocks known dangerous file signatures:
  - `MZ` (Windows executables)
  - `\x7fELF` (Linux executables)
  - `#!` (shell scripts)

---

### 2. SSRF Protection Infrastructure - EXCELLENT ✓

**File:** `~/aragora/aragora/server/handlers/utils/url_security.py`

Comprehensive SSRF protection with:
- ✓ Blocks private IP ranges (10.x, 172.16-31.x, 192.168.x)
- ✓ Blocks loopback addresses (127.x, ::1)
- ✓ Blocks link-local addresses (169.254.x, fe80::)
- ✓ Blocks cloud metadata endpoints:
  - AWS: 169.254.169.254
  - GCP: metadata.google.internal
  - Azure: instance-data
- ✓ Blocks internal hostnames (.internal, .local, .localhost, .lan, .corp)
- ✓ DNS resolution timeout (prevents slow lookups)
- ✓ IPv6-mapped IPv4 address validation

**Currently Used In:**
- debates/batch.py:237 ✓
- webhooks.py:617, 723 ✓

**Missing From:**
- external_integrations.py ⚠ (Issue #1)

---

### 3. SQL Injection Protection - EXCELLENT ✓

**Files:** Multiple handlers including `explainability_store.py`

- ✓ All database operations use parameterized queries
- ✓ No string concatenation in SQL statements
- ✓ Proper use of `execute_write()` with parameter tuples:

```python
# Correct pattern (used throughout codebase)
self._backend.execute_write(
    f"DELETE FROM {self._TABLE_NAME} WHERE batch_id = ?",
    (batch_id,),  # ✓ Parameters separated
)
```

---

### 4. Path Traversal Protection - EXCELLENT ✓

**File:** `~/aragora/aragora/server/handlers/codebase/security/storage.py`

- ✓ `validate_no_path_traversal()` function blocks ".." sequences
- ✓ `safe_repo_id()` validates against path traversal:
  - Blocks ".." sequences
  - Blocks "/" and "\" directory separators
  - Pattern validation: alphanumeric, hyphens, underscores only

```python
# Example validation
>>> safe_repo_id("../etc/passwd")
(False, "Invalid repo ID: path traversal not allowed")

>>> safe_repo_id("repo/subdir")
(False, "Invalid repo ID: must not contain path separators")
```

---

### 5. Command Injection Protection - GOOD ✓

**File:** `~/aragora/aragora/server/handlers/nomic.py`

- ✓ Uses `subprocess.Popen()` with list form (not `shell=True`)
- ✓ Integer parameters strictly validated and bounded
- ✓ No user input passed to shell

---

### 6. Authentication & CSRF Protection - GOOD ✓

**File:** `~/aragora/aragora/server/handlers/base.py` (lines 16-39)

- ✓ Bearer token authentication via Authorization header
- ✓ **Inherently immune to CSRF** because:
  - Tokens sent via Authorization header, not cookies
  - JavaScript must explicitly set the header
  - Cross-origin requests cannot access the header
- ✓ No cookie-based authentication

---

### 7. JSON Input Validation - GOOD ✓

**Files:** `document_query.py`, `rlm.py`, `gauntlet_v1.py`

- ✓ JSON parsing with error handling
- ✓ Required field validation
- ✓ Type checking (int, str, list, dict)
- ✓ Whitelist-based validation for enum values
- ✓ Safe unpacking of optional nested config objects

```python
# Example from document_query.py:100-128
body = self.read_json_body(handler)  # ✓ With error handling
if not body:
    return error_response("Request body required", 400)

question = body.get("question", "").strip()
if not question:
    return error_response("'question' field is required", 400)

# Config validation with whitelist
config = QueryConfig(
    max_chunks=config_dict.get("max_chunks", 10),
    search_alpha=config_dict.get("search_alpha", 0.5),
    use_agents=config_dict.get("use_agents", False),
)
```

---

### 8. Regular Expression Safety - GOOD ✓

All regex patterns use **simple character classes** without complex patterns vulnerable to ReDoS:
- ✓ `[a-z0-9]` - simple character class
- ✓ `[A-Z0-9]+` - simple repetition
- ✓ `^[a-zA-Z0-9_\-]+$` - anchored simple class

No complex nested patterns, alternation, or backtracking patterns found.

---

### 9. No Dangerous Functions - EXCELLENT ✓

Comprehensive scan found **ZERO instances of:**
- ❌ `pickle.loads()` or deserialization
- ❌ `eval()` of user input
- ❌ `exec()` of user input
- ❌ `os.system()` with user input
- ❌ Dynamic imports from user input
- ❌ Hardcoded credentials/passwords
- ❌ `marshal.loads()`
- ❌ `shelve` database deserialization

---

## VULNERABILITY SCAN RESULTS

| Category | Status | Notes |
|----------|--------|-------|
| SQL Injection | ✓ SAFE | Parameterized queries used throughout |
| Command Injection | ✓ SAFE | No shell=True, validated parameters |
| Path Traversal | ✓ SAFE | Validation functions in place |
| SSRF (Webhook URLs) | ⚠ PARTIAL | Missing in external_integrations.py (Issue #1) |
| SSRF (Network URLs) | ✓ SAFE | Validation infrastructure exists |
| Deserialization | ✓ SAFE | No pickle/marshal usage |
| Code Execution | ✓ SAFE | No eval/exec of user input |
| Template Injection | ✓ SAFE | Templates use safe format enums |
| ReDoS | ✓ SAFE | Simple regex patterns only |
| CSRF | ✓ SAFE | Bearer token auth (header-based) |
| XSS | ✓ SAFE | No unescaped user output in HTML |
| Authentication | ✓ SAFE | Bearer token validation in place |

---

## RECOMMENDATIONS

### Priority 1: CRITICAL (Address Immediately)

1. **Add webhook URL validation to external_integrations.py**
   - File: `~/aragora/aragora/server/handlers/external_integrations.py`
   - Apply: Lines 555-576 (Zapier), 768-792 (Make), 910 (n8n)
   - Use: `validate_webhook_url()` from `utils.url_security`
   - Estimated effort: 30 minutes

### Priority 2: MEDIUM (Address in Next Sprint)

1. **Improve subprocess parameter validation in nomic.py**
   - File: `~/aragora/aragora/server/handlers/nomic.py`
   - Add explicit type/range validation (see Issue #2)
   - Estimated effort: 1 hour

2. **Ensure consistent webhook validation across all handlers**
   - Audit all handlers that accept webhook/callback URLs
   - Ensure `validate_webhook_url()` is used consistently
   - Estimated effort: 2 hours

### Priority 3: NICE-TO-HAVE (Future Improvements)

1. Add request rate limiting for parameter fuzzing attacks
2. Add request signing validation for external API callbacks
3. Implement Content Security Policy headers for responses with user content
4. Add automated security scanning to CI/CD pipeline
5. Implement request/response logging for security auditing

---

## COMPLIANCE ASSESSMENT

| Control | Status | Evidence |
|---------|--------|----------|
| No SQL Injection | ✓ PASS | Parameterized queries throughout |
| No Command Injection | ✓ PASS | Subprocess with list form, no shell=True |
| No Deserialization Attacks | ✓ PASS | No pickle/marshal usage |
| No Code Execution | ✓ PASS | No eval/exec of user input |
| No Path Traversal | ✓ PASS | Validation functions in place |
| No Hardcoded Secrets | ✓ PASS | All secrets from env vars |
| CSRF Protection | ✓ PASS | Bearer token auth (header-based) |
| Webhook URL Validation | ⚠ PARTIAL | Missing in 1 file (external_integrations.py) |

**Overall Assessment:** **SECURE** with one medium-severity gap in SSRF validation

---

## AUDIT METHODOLOGY

1. **File Coverage:** Scanned all 579 Python files in handlers directory
2. **Pattern Matching:** Searched for dangerous functions:
   - `eval()`, `exec()`, `os.system()`, `subprocess` with `shell=True`
   - `pickle.loads()`, `marshal.loads()`, `shelve`
   - SQL injection patterns (string concatenation)
   - Path traversal patterns (`../`, `os.path.join` with user input)

3. **Code Analysis:** Manual review of critical handlers:
   - File upload handlers
   - Webhook/URL handlers
   - Database query handlers
   - Subprocess execution handlers
   - Deserialization handlers

4. **Validation Check:** Verified existing security utilities:
   - SSRF protection (`url_security.py`)
   - File validation (`file_validation.py`)
   - Path traversal protection (`storage.py`)

---

## CONCLUSION

The Aragora handler layer demonstrates **strong security practices** for input validation. The codebase:

✓ Properly validates user input in most critical areas
✓ Uses parameterized queries to prevent SQL injection
✓ Protects against command injection via subprocess list form
✓ Implements SSRF protection infrastructure
✓ Blocks dangerous file uploads
✓ Avoids dangerous functions like eval/exec

⚠ Has **one identified gap**: Missing SSRF validation in `external_integrations.py` for webhook URLs

The gap is straightforward to fix by using the existing `validate_webhook_url()` function already in the codebase and properly used in other handlers.

**Recommendation:** Prioritize Issue #1 (High Severity SSRF) for immediate remediation, then address Issues #2 and #3 in the next sprint.

---

**Report Generated:** 2026-02-02
**Analyst:** Claude Security Audit Tool
**Confidence Level:** High (comprehensive static analysis + manual code review)
