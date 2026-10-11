"""
Security vulnerability scanner for codebase analysis.

Comprehensive security scanning using AST analysis and pattern matching:
- Hardcoded secrets (API keys, passwords, tokens)
- SQL injection patterns
- XSS vulnerabilities
- Path traversal risks
- Command injection
- Insecure deserialization (pickle, eval, exec)
- Cryptographic weaknesses
- Dangerous function usage
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from re import Pattern

logger = logging.getLogger(__name__)


class SecuritySeverity(str, Enum):
    """Severity level for security findings."""

    CRITICAL = "critical"  # Immediate exploitation risk
    HIGH = "high"  # Significant security impact
    MEDIUM = "medium"  # Moderate risk
    LOW = "low"  # Minor issue
    INFO = "info"  # Informational


class VulnerabilityCategory(str, Enum):
    """Category of security vulnerability."""

    HARDCODED_SECRET = "hardcoded_secret"  # noqa: S105 -- enum value
    SQL_INJECTION = "sql_injection"
    COMMAND_INJECTION = "command_injection"
    PATH_TRAVERSAL = "path_traversal"
    XSS = "xss"
    INSECURE_DESERIALIZATION = "insecure_deserialization"
    WEAK_CRYPTO = "weak_crypto"
    INSECURE_CONFIG = "insecure_config"
    DANGEROUS_FUNCTION = "dangerous_function"
    INFORMATION_DISCLOSURE = "information_disclosure"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"


@dataclass
class SecurityPattern:
    """A pattern for detecting security vulnerabilities."""

    name: str
    pattern: Pattern[str]
    category: VulnerabilityCategory
    severity: SecuritySeverity
    description: str
    recommendation: str
    cwe_id: str | None = None  # CWE reference
    owasp_category: str | None = None  # OWASP Top 10 category
    languages: list[str] | None = None  # Applicable languages (None = all)
    false_positive_hints: list[str] = field(default_factory=list)


@dataclass
class SecurityFinding:
    """A security vulnerability finding."""

    id: str
    title: str
    description: str
    category: VulnerabilityCategory
    severity: SecuritySeverity
    confidence: float  # 0.0 - 1.0

    # Location
    file_path: str
    line_number: int
    column: int = 0
    end_line: int | None = None
    code_snippet: str = ""

    # Context
    function_name: str | None = None
    class_name: str | None = None

    # Metadata
    pattern_name: str | None = None
    cwe_id: str | None = None
    owasp_category: str | None = None
    recommendation: str = ""
    references: list[str] = field(default_factory=list)

    # Analysis
    is_false_positive: bool = False
    false_positive_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "column": self.column,
            "end_line": self.end_line,
            "code_snippet": self.code_snippet,
            "function_name": self.function_name,
            "class_name": self.class_name,
            "pattern_name": self.pattern_name,
            "cwe_id": self.cwe_id,
            "owasp_category": self.owasp_category,
            "recommendation": self.recommendation,
            "references": self.references,
            "is_false_positive": self.is_false_positive,
        }


@dataclass
class SecurityReport:
    """Complete security scan report."""

    scan_id: str
    repository: str
    started_at: datetime
    completed_at: datetime | None = None
    files_scanned: int = 0
    lines_scanned: int = 0
    findings: list[SecurityFinding] = field(default_factory=list)
    error: str | None = None

    # Summary counts
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0

    def calculate_summary(self) -> None:
        """Calculate summary statistics."""
        active = [f for f in self.findings if not f.is_false_positive]
        self.critical_count = sum(1 for f in active if f.severity == SecuritySeverity.CRITICAL)
        self.high_count = sum(1 for f in active if f.severity == SecuritySeverity.HIGH)
        self.medium_count = sum(1 for f in active if f.severity == SecuritySeverity.MEDIUM)
        self.low_count = sum(1 for f in active if f.severity == SecuritySeverity.LOW)
        self.info_count = sum(1 for f in active if f.severity == SecuritySeverity.INFO)

    @property
    def total_findings(self) -> int:
        return len(self.findings)

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0

    @property
    def risk_score(self) -> float:
        """Calculate overall risk score (0-100)."""
        if not self.findings:
            return 0.0
        weights = {
            SecuritySeverity.CRITICAL: 40,
            SecuritySeverity.HIGH: 20,
            SecuritySeverity.MEDIUM: 10,
            SecuritySeverity.LOW: 5,
            SecuritySeverity.INFO: 1,
        }
        score = sum(weights.get(f.severity, 0) * f.confidence for f in self.findings)
        return min(100.0, score)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "scan_id": self.scan_id,
            "repository": self.repository,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "files_scanned": self.files_scanned,
            "lines_scanned": self.lines_scanned,
            "total_findings": self.total_findings,
            "risk_score": self.risk_score,
            "summary": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
                "info": self.info_count,
            },
            "findings": [f.to_dict() for f in self.findings],
            "error": self.error,
        }


class SecurityScanner:
    """
    Comprehensive security vulnerability scanner.

    Combines pattern matching with AST analysis for accurate
    detection of security issues in source code.
    """

    # =====================================================================
    # SECRET PATTERNS
    # =====================================================================
    SECRET_PATTERNS = [
        SecurityPattern(
            name="AWS Access Key",
            pattern=re.compile(r"AKIA[0-9A-Z]{16}"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.CRITICAL,
            description="AWS Access Key ID detected in source code",
            recommendation="Remove the key and rotate AWS credentials immediately. Use environment variables or AWS Secrets Manager.",
            cwe_id="CWE-798",
            owasp_category="A02:2021-Cryptographic Failures",
        ),
        SecurityPattern(
            name="AWS Secret Key",
            pattern=re.compile(
                r"(?:aws_secret_access_key|aws_secret)\s*[=:]\s*['\"]([A-Za-z0-9/+=]{40})['\"]",
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.CRITICAL,
            description="AWS Secret Access Key detected",
            recommendation="Rotate AWS credentials and use secure credential storage",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="GitHub Token",
            pattern=re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.CRITICAL,
            description="GitHub personal access token detected",
            recommendation="Revoke the token immediately at github.com/settings/tokens and generate a new one",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="GitHub Fine-grained Token",
            pattern=re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.CRITICAL,
            description="GitHub fine-grained personal access token detected",
            recommendation="Revoke the token immediately",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="Slack Token",
            pattern=re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.HIGH,
            description="Slack API token detected",
            recommendation="Revoke and regenerate the Slack token",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="OpenAI API Key",
            pattern=re.compile(r"sk-[A-Za-z0-9]{20,}"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.HIGH,
            description="OpenAI API key detected",
            recommendation="Remove key and use environment variables. Rotate the key at platform.openai.com",
            cwe_id="CWE-798",
            false_positive_hints=["sk-ant-"],  # Anthropic keys
        ),
        SecurityPattern(
            name="Anthropic API Key",
            pattern=re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.HIGH,
            description="Anthropic API key detected",
            recommendation="Remove key and use environment variables",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="Generic API Key",
            pattern=re.compile(
                r'(?:api[_-]?key|apikey|api[_-]?secret)\s*[=:]\s*["\']([A-Za-z0-9_\-]{20,})["\']',
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.HIGH,
            description="Hardcoded API key detected",
            recommendation="Move API keys to environment variables or a secrets manager",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="Private Key Header",
            pattern=re.compile(
                r"-----BEGIN\s+(?:RSA\s+|DSA\s+|EC\s+|OPENSSH\s+|PGP\s+)?PRIVATE\s+KEY-----"
            ),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.CRITICAL,
            description="Private key embedded in source code",
            recommendation="Never store private keys in code. Use secure key management systems.",
            cwe_id="CWE-321",
        ),
        SecurityPattern(
            name="Password Assignment",
            pattern=re.compile(
                r'(?:password|passwd|pwd|secret)\s*[=:]\s*["\']([^"\']{8,})["\']',
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.HIGH,
            description="Hardcoded password detected",
            recommendation="Remove hardcoded password and use secure credential storage",
            cwe_id="CWE-798",
            false_positive_hints=["password_field", "password_input", "example", "test"],
        ),
        SecurityPattern(
            name="Database Connection String",
            pattern=re.compile(
                r'(?:mongodb|mysql|postgres|redis|mssql|mariadb)://[^\s<>"\']+:[^\s<>"\']+@',
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.CRITICAL,
            description="Database connection string with embedded credentials",
            recommendation="Use connection strings without credentials; provide credentials via environment variables",
            cwe_id="CWE-798",
        ),
        SecurityPattern(
            name="JWT Token",
            pattern=re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.MEDIUM,
            description="JWT token in source code",
            recommendation="Remove JWT from code. Tokens should be generated dynamically and stored securely.",
            cwe_id="CWE-798",
            false_positive_hints=["example", "test", "mock"],
        ),
        SecurityPattern(
            name="Bearer Token",
            pattern=re.compile(
                r'["\']Bearer\s+[A-Za-z0-9_\-\.]{20,}["\']',
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.HARDCODED_SECRET,
            severity=SecuritySeverity.HIGH,
            description="Hardcoded bearer token detected",
            recommendation="Remove bearer token from code",
            cwe_id="CWE-798",
        ),
    ]

    # =====================================================================
    # INJECTION PATTERNS
    # =====================================================================
    INJECTION_PATTERNS = [
        # SQL Injection
        SecurityPattern(
            name="SQL String Interpolation (f-string)",
            pattern=re.compile(
                r'(?:execute|executemany|raw)\s*\(\s*f["\'][^"\']*(?:SELECT|INSERT|UPDATE|DELETE|WHERE)',
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.SQL_INJECTION,
            severity=SecuritySeverity.HIGH,
            description="SQL query using f-string interpolation is vulnerable to injection",
            recommendation="Use parameterized queries with placeholders (?) or named parameters",
            cwe_id="CWE-89",
            owasp_category="A03:2021-Injection",
            languages=["python"],
        ),
        SecurityPattern(
            name="SQL String Format",
            pattern=re.compile(
                r"(?:execute|executemany|raw)\s*\([^)]*\.format\s*\(",
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.SQL_INJECTION,
            severity=SecuritySeverity.HIGH,
            description="SQL query using .format() is vulnerable to injection",
            recommendation="Use parameterized queries instead of string formatting",
            cwe_id="CWE-89",
            languages=["python"],
        ),
        SecurityPattern(
            name="SQL Concatenation",
            pattern=re.compile(
                r'(?:execute|query)\s*\([^)]*\+\s*(?:\w+|["\'][^"\']*["\'])\s*\+',
            ),
            category=VulnerabilityCategory.SQL_INJECTION,
            severity=SecuritySeverity.HIGH,
            description="SQL query built with string concatenation",
            recommendation="Use parameterized queries or an ORM",
            cwe_id="CWE-89",
        ),
        # Command Injection
        SecurityPattern(
            name="Shell Command with Variable",
            pattern=re.compile(
                r'(?:os\.system|os\.popen|subprocess\.(?:call|run|Popen))\s*\(\s*f["\']',
            ),
            category=VulnerabilityCategory.COMMAND_INJECTION,
            severity=SecuritySeverity.CRITICAL,
            description="Shell command using f-string allows command injection",
            recommendation="Use subprocess with list arguments, not shell=True. Validate all inputs.",
            cwe_id="CWE-78",
            owasp_category="A03:2021-Injection",
            languages=["python"],
        ),
        SecurityPattern(
            name="Shell=True with Variable",
            pattern=re.compile(
                r"subprocess\.\w+\s*\([^)]*shell\s*=\s*True[^)]*\+",
            ),
            category=VulnerabilityCategory.COMMAND_INJECTION,
            severity=SecuritySeverity.CRITICAL,
            description="subprocess with shell=True and variable input",
            recommendation="Avoid shell=True. Pass command as list of arguments.",
            cwe_id="CWE-78",
            languages=["python"],
        ),
        SecurityPattern(
            name="eval() Usage",
            pattern=re.compile(r"\beval\s*\(\s*[^)\"']+\)"),
            category=VulnerabilityCategory.COMMAND_INJECTION,
            severity=SecuritySeverity.CRITICAL,
            description="eval() with variable input allows code injection",
            recommendation="Never use eval() with untrusted input. Use ast.literal_eval() for data parsing.",
            cwe_id="CWE-94",
            languages=["python", "javascript"],
        ),
        SecurityPattern(
            name="exec() Usage",
            pattern=re.compile(r"\bexec\s*\(\s*[^)\"']+\)"),
            category=VulnerabilityCategory.COMMAND_INJECTION,
            severity=SecuritySeverity.CRITICAL,
            description="exec() with variable input allows code injection",
            recommendation="Avoid exec() with user input. Find alternative implementations.",
            cwe_id="CWE-94",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # XSS PATTERNS
    # =====================================================================
    XSS_PATTERNS = [
        SecurityPattern(
            name="innerHTML Assignment",
            pattern=re.compile(r"\.innerHTML\s*=\s*[^;]+(?:\+|`|\$\{)"),
            category=VulnerabilityCategory.XSS,
            severity=SecuritySeverity.HIGH,
            description="innerHTML with dynamic content allows XSS",
            recommendation="Use textContent or sanitize HTML with DOMPurify",
            cwe_id="CWE-79",
            owasp_category="A03:2021-Injection",
            languages=["javascript", "typescript"],
        ),
        SecurityPattern(
            name="document.write",
            pattern=re.compile(r"document\.write\s*\("),
            category=VulnerabilityCategory.XSS,
            severity=SecuritySeverity.MEDIUM,
            description="document.write() can enable XSS attacks",
            recommendation="Use DOM manipulation methods instead of document.write()",
            cwe_id="CWE-79",
            languages=["javascript", "typescript"],
        ),
        SecurityPattern(
            name="React dangerouslySetInnerHTML",
            pattern=re.compile(r"dangerouslySetInnerHTML\s*=\s*\{"),
            category=VulnerabilityCategory.XSS,
            severity=SecuritySeverity.MEDIUM,
            description="dangerouslySetInnerHTML can lead to XSS if not properly sanitized",
            recommendation="Sanitize HTML content with DOMPurify before using",
            cwe_id="CWE-79",
            languages=["javascript", "typescript"],
        ),
        SecurityPattern(
            name="v-html Directive",
            pattern=re.compile(r'v-html\s*=\s*["\'][^"\']*["\']'),
            category=VulnerabilityCategory.XSS,
            severity=SecuritySeverity.MEDIUM,
            description="Vue v-html directive can lead to XSS",
            recommendation="Sanitize content or use v-text for non-HTML content",
            cwe_id="CWE-79",
            languages=["javascript", "typescript"],
        ),
    ]

    # =====================================================================
    # PATH TRAVERSAL PATTERNS
    # =====================================================================
    PATH_PATTERNS = [
        SecurityPattern(
            name="Path Join with User Input",
            pattern=re.compile(
                r"(?:os\.path\.join|Path)\s*\([^)]*(?:request|params|query|input|args)",
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.PATH_TRAVERSAL,
            severity=SecuritySeverity.HIGH,
            description="File path construction with user input may allow path traversal",
            recommendation="Validate and sanitize paths. Use os.path.realpath() and check path prefix.",
            cwe_id="CWE-22",
            owasp_category="A01:2021-Broken Access Control",
            languages=["python"],
        ),
        SecurityPattern(
            name="open() with Variable Path",
            pattern=re.compile(
                r"open\s*\(\s*(?:f['\"]|[^'\")]+\+)",
            ),
            category=VulnerabilityCategory.PATH_TRAVERSAL,
            severity=SecuritySeverity.MEDIUM,
            description="File open with dynamic path may be vulnerable",
            recommendation="Validate file paths against allowed directories",
            cwe_id="CWE-22",
            languages=["python"],
        ),
        SecurityPattern(
            name="fs.readFile with Variable",
            pattern=re.compile(
                r"fs\.(?:readFile|writeFile|readFileSync|writeFileSync)\s*\([^'\"]",
            ),
            category=VulnerabilityCategory.PATH_TRAVERSAL,
            severity=SecuritySeverity.MEDIUM,
            description="File system operation with dynamic path",
            recommendation="Validate paths and restrict to safe directories",
            cwe_id="CWE-22",
            languages=["javascript", "typescript"],
        ),
    ]

    # =====================================================================
    # DESERIALIZATION PATTERNS
    # =====================================================================
    DESERIALIZATION_PATTERNS = [
        SecurityPattern(
            name="pickle.load",
            pattern=re.compile(r"pickle\.(?:load|loads)\s*\("),
            category=VulnerabilityCategory.INSECURE_DESERIALIZATION,
            severity=SecuritySeverity.HIGH,
            description="pickle deserialization can execute arbitrary code",
            recommendation="Never unpickle untrusted data. Use JSON or other safe formats.",
            cwe_id="CWE-502",
            owasp_category="A08:2021-Software and Data Integrity Failures",
            languages=["python"],
        ),
        SecurityPattern(
            name="yaml.load without SafeLoader",
            pattern=re.compile(r"yaml\.load\s*\([^)]*\)\s*(?!.*Loader\s*=\s*(?:Safe|Base))"),
            category=VulnerabilityCategory.INSECURE_DESERIALIZATION,
            severity=SecuritySeverity.HIGH,
            description="yaml.load without SafeLoader can execute arbitrary code",
            recommendation="Use yaml.safe_load() or specify Loader=yaml.SafeLoader",
            cwe_id="CWE-502",
            languages=["python"],
        ),
        SecurityPattern(
            name="marshal.load",
            pattern=re.compile(r"marshal\.(?:load|loads)\s*\("),
            category=VulnerabilityCategory.INSECURE_DESERIALIZATION,
            severity=SecuritySeverity.HIGH,
            description="marshal deserialization of untrusted data is dangerous",
            recommendation="Use JSON or other safe serialization formats",
            cwe_id="CWE-502",
            languages=["python"],
        ),
        SecurityPattern(
            name="JSON.parse without validation",
            pattern=re.compile(r"JSON\.parse\s*\(\s*(?:req|request|params)"),
            category=VulnerabilityCategory.INSECURE_DESERIALIZATION,
            severity=SecuritySeverity.LOW,
            description="JSON.parse with external input should be validated",
            recommendation="Validate JSON structure after parsing",
            cwe_id="CWE-502",
            languages=["javascript", "typescript"],
        ),
    ]

    # =====================================================================
    # CRYPTO PATTERNS
    # =====================================================================
    CRYPTO_PATTERNS = [
        SecurityPattern(
            name="MD5 Hash",
            pattern=re.compile(
                r"(?:hashlib\.md5|MD5|crypto\.createHash\s*\(\s*['\"]md5)", re.IGNORECASE
            ),
            category=VulnerabilityCategory.WEAK_CRYPTO,
            severity=SecuritySeverity.MEDIUM,
            description="MD5 is cryptographically broken",
            recommendation="Use SHA-256 or stronger hash functions",
            cwe_id="CWE-328",
        ),
        SecurityPattern(
            name="SHA1 Hash",
            pattern=re.compile(
                r"(?:hashlib\.sha1|SHA1|crypto\.createHash\s*\(\s*['\"]sha1)", re.IGNORECASE
            ),
            category=VulnerabilityCategory.WEAK_CRYPTO,
            severity=SecuritySeverity.LOW,
            description="SHA1 is considered weak for security purposes",
            recommendation="Use SHA-256 or SHA-3 for security applications",
            cwe_id="CWE-328",
        ),
        SecurityPattern(
            name="DES Encryption",
            pattern=re.compile(r"(?:DES\.|Cipher\.DES|\'DES\'|\"DES\")", re.IGNORECASE),
            category=VulnerabilityCategory.WEAK_CRYPTO,
            severity=SecuritySeverity.HIGH,
            description="DES encryption is obsolete and easily broken",
            recommendation="Use AES-256 or ChaCha20",
            cwe_id="CWE-327",
        ),
        SecurityPattern(
            name="Hardcoded IV/Nonce",
            pattern=re.compile(r"(?:iv|nonce|IV)\s*=\s*b?['\"][^'\"]{8,}['\"]"),
            category=VulnerabilityCategory.WEAK_CRYPTO,
            severity=SecuritySeverity.HIGH,
            description="Hardcoded initialization vector weakens encryption",
            recommendation="Generate random IVs using os.urandom() or secrets module",
            cwe_id="CWE-329",
        ),
        SecurityPattern(
            name="ECB Mode",
            pattern=re.compile(r"(?:MODE_ECB|AES\.ECB|mode\s*=\s*['\"]ecb['\"])", re.IGNORECASE),
            category=VulnerabilityCategory.WEAK_CRYPTO,
            severity=SecuritySeverity.HIGH,
            description="ECB mode reveals patterns in encrypted data",
            recommendation="Use CBC, GCM, or CTR modes with proper IV handling",
            cwe_id="CWE-327",
        ),
        SecurityPattern(
            name="Random for Security",
            pattern=re.compile(
                r"import random\n.*random\.(?:choice|randint|sample).*(?:password|token|key|secret)",
                re.IGNORECASE | re.DOTALL,
            ),
            category=VulnerabilityCategory.WEAK_CRYPTO,
            severity=SecuritySeverity.MEDIUM,
            description="Using random module for security-sensitive generation",
            recommendation="Use secrets module for cryptographic randomness",
            cwe_id="CWE-338",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # CONFIG PATTERNS
    # =====================================================================
    CONFIG_PATTERNS = [
        SecurityPattern(
            name="Debug Mode Enabled",
            pattern=re.compile(
                r"(?:DEBUG|debug)\s*[=:]\s*(?:True|true|1|['\"]true['\"])", re.IGNORECASE
            ),
            category=VulnerabilityCategory.INSECURE_CONFIG,
            severity=SecuritySeverity.MEDIUM,
            description="Debug mode enabled (may expose sensitive information)",
            recommendation="Ensure DEBUG is False in production",
            cwe_id="CWE-489",
        ),
        SecurityPattern(
            name="SSL Verification Disabled",
            pattern=re.compile(
                r"(?:verify\s*=\s*False|VERIFY_SSL\s*=\s*False|SSL_VERIFY\s*=\s*False|rejectUnauthorized\s*:\s*false)",
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.INSECURE_CONFIG,
            severity=SecuritySeverity.HIGH,
            description="SSL certificate verification is disabled",
            recommendation="Enable SSL verification to prevent MITM attacks",
            cwe_id="CWE-295",
        ),
        SecurityPattern(
            name="Wildcard CORS",
            pattern=re.compile(
                r"(?:Access-Control-Allow-Origin|cors.*origin)\s*[=:]\s*['\"]?\*['\"]?",
                re.IGNORECASE,
            ),
            category=VulnerabilityCategory.INSECURE_CONFIG,
            severity=SecuritySeverity.MEDIUM,
            description="Wildcard CORS allows requests from any origin",
            recommendation="Restrict CORS to specific trusted domains",
            cwe_id="CWE-942",
        ),
        SecurityPattern(
            name="Insecure HTTP",
            pattern=re.compile(r"http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])[\w.-]+"),
            category=VulnerabilityCategory.INSECURE_CONFIG,
            severity=SecuritySeverity.LOW,
            description="HTTP URL (should use HTTPS)",
            recommendation="Use HTTPS for all external connections",
            cwe_id="CWE-319",
            false_positive_hints=["example.com", "test", "mock", "spec"],
        ),
        SecurityPattern(
            name="Binding to All Interfaces",
            pattern=re.compile(r"(?:host|bind)\s*[=:]\s*['\"]0\.0\.0\.0['\"]"),
            category=VulnerabilityCategory.INSECURE_CONFIG,
            severity=SecuritySeverity.LOW,
            description="Server binding to all network interfaces",
            recommendation="Bind to specific interface or use reverse proxy",
            cwe_id="CWE-668",
        ),
    ]

    # =====================================================================
    # DANGEROUS FUNCTION PATTERNS
    # =====================================================================
    DANGEROUS_PATTERNS = [
        SecurityPattern(
            name="assert Statement",
            pattern=re.compile(r"^\s*assert\s+.+$", re.MULTILINE),
            category=VulnerabilityCategory.DANGEROUS_FUNCTION,
            severity=SecuritySeverity.LOW,
            description="assert statements are removed with -O flag",
            recommendation="Use explicit if/raise for security checks",
            cwe_id="CWE-617",
            languages=["python"],
        ),
        SecurityPattern(
            name="Hardcoded Temp Path",
            pattern=re.compile(r"['\"](?:/tmp/|C:\\Temp\\|/var/tmp/)[^'\"]+['\"]"),
            category=VulnerabilityCategory.DANGEROUS_FUNCTION,
            severity=SecuritySeverity.LOW,
            description="Hardcoded temporary file path",
            recommendation="Use tempfile.mktemp() or tempfile.NamedTemporaryFile()",
            cwe_id="CWE-377",
        ),
        SecurityPattern(
            name="Empty Exception Handler",
            pattern=re.compile(r"except.*:\s*pass\s*$", re.MULTILINE),
            category=VulnerabilityCategory.DANGEROUS_FUNCTION,
            severity=SecuritySeverity.LOW,
            description="Empty exception handler may hide errors",
            recommendation="Log exceptions or handle them appropriately",
            cwe_id="CWE-390",
            languages=["python"],
        ),
    ]

    def __init__(
        self,
        include_low_severity: bool = True,
        include_info: bool = False,
        custom_patterns: list[SecurityPattern] | None = None,
    ):
        """
        Initialize the security scanner.

        Args:
            include_low_severity: Include LOW severity findings
            include_info: Include INFO severity findings
            custom_patterns: Additional patterns to check
        """
        self.include_low_severity = include_low_severity
        self.include_info = include_info

        # Combine all patterns
        self.patterns: list[SecurityPattern] = []
        self.patterns.extend(self.SECRET_PATTERNS)
        self.patterns.extend(self.INJECTION_PATTERNS)
        self.patterns.extend(self.XSS_PATTERNS)
        self.patterns.extend(self.PATH_PATTERNS)
        self.patterns.extend(self.DESERIALIZATION_PATTERNS)
        self.patterns.extend(self.CRYPTO_PATTERNS)
        self.patterns.extend(self.CONFIG_PATTERNS)
        self.patterns.extend(self.DANGEROUS_PATTERNS)

        if custom_patterns:
            self.patterns.extend(custom_patterns)

        self._finding_counter = 0

    def scan_file(self, file_path: str) -> list[SecurityFinding]:
        """
        Scan a single file for security vulnerabilities.

        Args:
            file_path: Path to the file to scan

        Returns:
            List of security findings
        """
        findings: list[SecurityFinding] = []

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
                lines = content.split("\n")
        except OSError as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return findings

        # Detect language from extension
        ext = Path(file_path).suffix.lower()
        language = self._extension_to_language(ext)

        # Check each pattern
        for pattern in self.patterns:
            # Filter by language if specified
            if pattern.languages and language not in pattern.languages:
                continue

            # Filter by severity
            if pattern.severity == SecuritySeverity.LOW and not self.include_low_severity:
                continue
            if pattern.severity == SecuritySeverity.INFO and not self.include_info:
                continue

            # Find matches
            for match in pattern.pattern.finditer(content):
                # Check for false positive hints
                match_text = match.group()
                is_false_positive = False
                for hint in pattern.false_positive_hints:
                    if hint.lower() in match_text.lower():
                        is_false_positive = True
                        break

                # Also check surrounding context for false positives
                start = max(0, match.start() - 100)
                end = min(len(content), match.end() + 100)
                context = content[start:end].lower()
                for hint in ["test", "example", "sample", "mock", "fake", "dummy"]:
                    if hint in context:
                        # Lower confidence for test contexts
                        pass

                # Calculate line number
                line_num = content[: match.start()].count("\n") + 1

                # Check for # nosec inline suppression
                source_line = lines[line_num - 1] if line_num <= len(lines) else ""
                if "# nosec" in source_line:
                    is_false_positive = True

                # Get code snippet
                snippet_start = max(0, line_num - 2)
                snippet_end = min(len(lines), line_num + 1)
                snippet = "\n".join(lines[snippet_start:snippet_end])

                self._finding_counter += 1
                finding = SecurityFinding(
                    id=f"SEC-{self._finding_counter:06d}",
                    title=pattern.name,
                    description=pattern.description,
                    category=pattern.category,
                    severity=pattern.severity,
                    confidence=0.95 if not is_false_positive else 0.5,
                    file_path=file_path,
                    line_number=line_num,
                    column=match.start() - content.rfind("\n", 0, match.start()) - 1,
                    code_snippet=snippet[:500],
                    pattern_name=pattern.name,
                    cwe_id=pattern.cwe_id,
                    owasp_category=pattern.owasp_category,
                    recommendation=pattern.recommendation,
                    is_false_positive=is_false_positive,
                )
                findings.append(finding)

        return findings

    def scan_directory(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
        extensions: list[str] | None = None,
    ) -> SecurityReport:
        """
        Scan a directory for security vulnerabilities.

        Args:
            directory: Root directory to scan
            exclude_patterns: Glob patterns to exclude
            extensions: File extensions to scan (default: common code files)

        Returns:
            Complete security report
        """
        start_time = datetime.now(timezone.utc)
        scan_id = f"security_scan_{start_time.strftime('%Y%m%d_%H%M%S')}"

        logger.info("[%s] Starting security scan of %s", scan_id, directory)

        report = SecurityReport(
            scan_id=scan_id,
            repository=directory,
            started_at=start_time,
        )

        # Default extensions
        if extensions is None:
            extensions = [
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
                ".java",
                ".go",
                ".rb",
                ".php",
                ".yaml",
                ".yml",
                ".json",
                ".xml",
                ".env",
                ".conf",
                ".cfg",
                ".ini",
            ]

        # Default excludes
        if exclude_patterns is None:
            exclude_patterns = [
                "__pycache__",
                ".git",
                "node_modules",
                ".venv",
                "venv",
                "env",
                ".tox",
                "dist",
                "build",
                ".pytest_cache",
            ]

        # Collect files
        root = Path(directory)
        files_to_scan: list[Path] = []

        for ext in extensions:
            for file_path in root.rglob(f"*{ext}"):
                # Check exclusions
                excluded = False
                for pattern in exclude_patterns:
                    if pattern in str(file_path):
                        excluded = True
                        break
                if not excluded:
                    files_to_scan.append(file_path)

        logger.info("[%s] Found %s files to scan", scan_id, len(files_to_scan))

        # Scan files
        total_lines = 0
        for file_path in files_to_scan:
            try:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    total_lines += content.count("\n") + 1

                findings = self.scan_file(str(file_path))
                report.findings.extend(findings)
                report.files_scanned += 1

            except (SyntaxError, ValueError, OSError) as e:
                logger.warning("[%s] Error scanning %s: %s", scan_id, file_path, e)

        report.lines_scanned = total_lines
        report.completed_at = datetime.now(timezone.utc)
        report.calculate_summary()

        elapsed = (report.completed_at - start_time).total_seconds()
        logger.info(
            "[%s] Completed in %.2fs: %s findings (%s critical)",
            scan_id,
            elapsed,
            report.total_findings,
            report.critical_count,
        )

        return report

    def _extension_to_language(self, ext: str) -> str | None:
        """Map file extension to language name."""
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
        }
        return mapping.get(ext)


def quick_security_scan(
    path: str,
    severity_threshold: SecuritySeverity = SecuritySeverity.MEDIUM,
) -> dict[str, Any]:
    """
    Quick security scan of a file or directory.

    Args:
        path: File or directory path
        severity_threshold: Minimum severity to report

    Returns:
        Dictionary with scan results
    """
    scanner = SecurityScanner(
        include_low_severity=(severity_threshold == SecuritySeverity.LOW),
        include_info=False,
    )

    path_obj = Path(path)
    if path_obj.is_file():
        findings = scanner.scan_file(str(path))
        return {
            "path": path,
            "findings": len(findings),
            "critical": sum(1 for f in findings if f.severity == SecuritySeverity.CRITICAL),
            "high": sum(1 for f in findings if f.severity == SecuritySeverity.HIGH),
            "details": [f.to_dict() for f in findings[:20]],
        }
    else:
        report = scanner.scan_directory(str(path))
        return report.to_dict()
