"""Data Classification Evidence Bundle Generator.

Produces audit-ready evidence bundles documenting the data classification
policy configuration, enforcement rules, encryption status, retention
policies, and CI scan configuration.  Bundles include a SHA-256 integrity
hash and can be rendered as JSON or Markdown.

Usage::

    from aragora.compliance.evidence_bundle import DataClassificationEvidenceBundle

    bundle = DataClassificationEvidenceBundle()
    result = bundle.generate(period_days=30)
    print(bundle.to_markdown())
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aragora.compliance.data_classification import (
    DEFAULT_POLICIES,
    DataClassification,
    DataClassifier,
)

logger = logging.getLogger(__name__)


def _check_crypto_available() -> bool:
    """Return ``True`` if ``cryptography`` is importable."""
    try:
        from aragora.security.encryption import CRYPTO_AVAILABLE  # type: ignore[import-untyped]

        return bool(CRYPTO_AVAILABLE)
    except (ImportError, AttributeError):
        return False


class DataClassificationEvidenceBundle:
    """Generates audit evidence bundles for data classification policies.

    Each bundle captures a point-in-time snapshot of:

    * Active classification policies and their enforcement rules.
    * Classification levels and sensitivity ordering.
    * Encryption availability.
    * Retention policy summary per classification level.
    * CI scan configuration details.
    * A SHA-256 integrity hash covering the bundle payload.
    """

    def __init__(self, classifier: DataClassifier | None = None) -> None:
        self._classifier = classifier or DataClassifier()
        self._bundle: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, period_days: int = 30) -> dict[str, Any]:
        """Generate the evidence bundle.

        Parameters
        ----------
        period_days:
            The reporting period length in days (for metadata purposes).

        Returns
        -------
        dict
            The complete evidence bundle as a JSON-serializable dictionary.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        crypto_available = _check_crypto_available()
        active_policy = self._classifier.get_active_policy()

        # Build per-level enforcement rules
        enforcement_rules: list[dict[str, Any]] = []
        for level in DataClassification:
            policy = DEFAULT_POLICIES[level]
            enforcement_rules.append(
                {
                    "level": level.value,
                    "encryption_required": policy.encryption_required,
                    "audit_logging": policy.audit_logging,
                    "retention_days": policy.retention_days,
                    "requires_consent": policy.requires_consent,
                    "allowed_regions": policy.allowed_regions or ["*"],
                    "allowed_operations": policy.allowed_operations,
                }
            )

        # Retention policy summary
        retention_summary: dict[str, int] = {
            level.value: DEFAULT_POLICIES[level].retention_days for level in DataClassification
        }

        # CI scan configuration
        ci_scan_config = {
            "scan_type": "ast_string_literal_extraction",
            "scanner": "aragora.compliance.data_classification.DataClassifier.scan_for_pii",
            "patterns_checked": ["email", "phone", "ssn", "credit_card"],
            "allowlist_file": "scripts/pii_allowlist.txt",
            "excluded_directories": ["tests/", "docs/", ".git/"],
            "blocking": False,
            "ci_step_name": "NON-BLOCKING: Data classification PII scan",
        }

        payload = {
            "bundle_type": "data_classification_evidence",
            "generated_at": timestamp,
            "period_days": period_days,
            "active_policy": active_policy,
            "classification_levels": [level.value for level in DataClassification],
            "enforcement_rules": enforcement_rules,
            "encryption_status": {
                "crypto_available": crypto_available,
                "algorithm": "AES-256-GCM" if crypto_available else "unavailable",
                "library": "cryptography" if crypto_available else "not_installed",
            },
            "retention_summary": retention_summary,
            "ci_scan_config": ci_scan_config,
        }

        # Compute integrity hash over the deterministic payload
        hash_input = json.dumps(payload, sort_keys=True, default=str)
        integrity_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        payload["integrity_hash"] = integrity_hash

        self._bundle = payload
        return payload

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Render the bundle as human-readable Markdown.

        :meth:`generate` must be called first.

        Raises
        ------
        RuntimeError
            If no bundle has been generated yet.
        """
        if self._bundle is None:
            raise RuntimeError("Call generate() before to_markdown().")

        b = self._bundle
        lines = [
            "# Data Classification Evidence Bundle",
            "",
            f"**Generated:** {b['generated_at']}",
            f"**Period:** {b['period_days']} days",
            f"**Integrity Hash:** `{b['integrity_hash']}`",
            "",
            "---",
            "",
            "## Classification Levels",
            "",
        ]
        for level in b["classification_levels"]:
            lines.append(f"- `{level}`")
        lines.append("")

        lines.append("## Enforcement Rules")
        lines.append("")
        lines.append("| Level | Encryption | Audit Log | Retention | Consent | Regions |")
        lines.append("|-------|-----------|-----------|-----------|---------|---------|")
        for rule in b["enforcement_rules"]:
            enc = "Yes" if rule["encryption_required"] else "No"
            audit = "Yes" if rule["audit_logging"] else "No"
            consent = "Yes" if rule["requires_consent"] else "No"
            regions = ", ".join(rule["allowed_regions"])
            lines.append(
                f"| {rule['level']} | {enc} | {audit} | "
                f"{rule['retention_days']}d | {consent} | {regions} |"
            )
        lines.append("")

        lines.append("## Encryption Status")
        lines.append("")
        enc_status = b["encryption_status"]
        lines.append(f"- **Available:** {'Yes' if enc_status['crypto_available'] else 'No'}")
        lines.append(f"- **Algorithm:** {enc_status['algorithm']}")
        lines.append(f"- **Library:** {enc_status['library']}")
        lines.append("")

        lines.append("## Retention Policy Summary")
        lines.append("")
        for level, days in b["retention_summary"].items():
            lines.append(f"- **{level}:** {days} days")
        lines.append("")

        lines.append("## CI Scan Configuration")
        lines.append("")
        ci = b["ci_scan_config"]
        lines.append(f"- **Scan Type:** {ci['scan_type']}")
        lines.append(f"- **Scanner:** `{ci['scanner']}`")
        lines.append(f"- **Patterns:** {', '.join(ci['patterns_checked'])}")
        lines.append(f"- **Allowlist:** `{ci['allowlist_file']}`")
        lines.append(f"- **Excluded Dirs:** {', '.join(ci['excluded_directories'])}")
        lines.append(f"- **Blocking:** {'Yes' if ci['blocking'] else 'No'}")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(
            "*This bundle was generated automatically by the Aragora Decision Integrity Platform.*"
        )
        lines.append("")

        return "\n".join(lines)


__all__ = ["DataClassificationEvidenceBundle"]
