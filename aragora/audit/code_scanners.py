"""Registers the audit package's code scanners with :mod:`aragora.agents.code_scanners`."""

from __future__ import annotations

from typing import Any

from aragora.agents.code_scanners import BUG_DETECTOR, SECURITY_SCANNER, register_code_scanner


# The scanner modules load only when a scanner is first built.
def _security_scanner() -> Any:
    from aragora.audit.security_scanner import SecurityScanner

    return SecurityScanner()


def _bug_detector() -> Any:
    from aragora.audit.bug_detector import BugDetector

    return BugDetector()


def register_code_scanners() -> None:
    """Register the security scanner and bug detector factories; safe to call more than once."""
    register_code_scanner(SECURITY_SCANNER, _security_scanner)
    register_code_scanner(BUG_DETECTOR, _bug_detector)


__all__ = ["register_code_scanners"]
