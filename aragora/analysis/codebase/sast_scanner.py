"""
SAST Scanner - backward-compatible re-export stub.

This module has been decomposed into the ``aragora.analysis.codebase.sast``
package.  All public names are re-exported here so that existing imports
continue to work unchanged.
"""

import asyncio  # noqa: F401 - needed for test patching

from aragora.analysis.codebase.sast import (
    AVAILABLE_RULESETS,
    CWE_FIX_RECOMMENDATIONS,
    CWE_TO_OWASP,
    LANGUAGE_EXTENSIONS,
    LOCAL_PATTERNS,
    OWASPCategory,
    ProgressCallback,
    SASTConfig,
    SASTFinding,
    SASTScanResult,
    SASTScanner,
    SASTSeverity,
    check_semgrep_installation,
    get_available_rulesets,
    scan_for_vulnerabilities,
)

__all__ = [
    # Main classes
    "SASTScanner",
    "SASTScanResult",
    "SASTFinding",
    "SASTSeverity",
    "SASTConfig",
    "OWASPCategory",
    # Convenience functions
    "scan_for_vulnerabilities",
    "get_available_rulesets",
    "check_semgrep_installation",
    # Type aliases
    "ProgressCallback",
    # Constants
    "AVAILABLE_RULESETS",
    "CWE_TO_OWASP",
    "CWE_FIX_RECOMMENDATIONS",
    "LOCAL_PATTERNS",
    "LANGUAGE_EXTENSIONS",
]
