"""Audit adapter registration for billing MFA bypass changes."""

from __future__ import annotations


def register_billing_audit_sink() -> None:
    """Register unified administrative audit emission with billing."""
    from aragora.audit.unified import audit_admin
    from aragora.billing.models import register_mfa_bypass_audit_sink

    register_mfa_bypass_audit_sink(audit_admin)
