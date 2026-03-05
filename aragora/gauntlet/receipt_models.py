"""
Data model classes for Decision Receipts.

Contains the core dataclass definitions for receipt components:
- ProvenanceRecord: A single provenance record in the chain
- ConsensusProof: Proof of agent consensus
- DecisionReceipt: The main audit-ready receipt dataclass

These are extracted from receipt.py for modularity.
The main receipt.py re-exports all models for backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from typing import TYPE_CHECKING, Any

from aragora.core_types import Verdict  # noqa: F401 - re-exported for receipt consumers

if TYPE_CHECKING:
    from .result import GauntletResult
    from .signing import ReceiptSigner


@dataclass
class ProvenanceRecord:
    """A single provenance record in the chain."""

    timestamp: str
    event_type: str  # "attack", "probe", "scenario", "verdict"
    agent: str | None = None
    description: str = ""
    evidence_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "agent": self.agent,
            "description": self.description,
            "evidence_hash": self.evidence_hash,
        }


@dataclass
class ConsensusProof:
    """Proof of agent consensus."""

    reached: bool
    confidence: float
    supporting_agents: list[str] = field(default_factory=list)
    dissenting_agents: list[str] = field(default_factory=list)
    method: str = "majority"
    evidence_hash: str = ""
    # Taint tracking (G2)
    tainted_proposals: list[str] = field(default_factory=list)
    trust_score: float = 1.0  # 1.0 = all clean; lower = tainted proposals in consensus

    def to_dict(self) -> dict:
        return {
            "reached": self.reached,
            "confidence": self.confidence,
            "supporting_agents": self.supporting_agents,
            "dissenting_agents": self.dissenting_agents,
            "method": self.method,
            "evidence_hash": self.evidence_hash,
            "tainted_proposals": self.tainted_proposals,
            "trust_score": self.trust_score,
        }


@dataclass
class DecisionReceipt:
    """
    Audit-ready receipt for a Gauntlet validation.

    Contains:
    - Input identification and hash
    - Complete findings summary
    - Verdict with reasoning
    - Provenance chain for auditability
    - Content-addressable artifact hash
    """

    # Identification
    receipt_id: str
    gauntlet_id: str
    timestamp: str

    # Input
    input_summary: str
    input_hash: str  # SHA-256 for integrity verification

    # Findings summary
    risk_summary: dict  # Critical/High/Medium/Low counts
    attacks_attempted: int
    attacks_successful: int
    probes_run: int
    vulnerabilities_found: int

    # Verdict
    verdict: str  # "PASS", "CONDITIONAL", "FAIL"
    confidence: float
    robustness_score: float

    # Fields with defaults must come after fields without defaults
    vulnerability_details: list[dict] = field(default_factory=list)
    verdict_reasoning: str = ""

    # Evidence
    dissenting_views: list[str] = field(default_factory=list)
    consensus_proof: ConsensusProof | None = None
    provenance_chain: list[ProvenanceRecord] = field(default_factory=list)

    # Explainability (why the decision was made)
    explainability: dict[str, Any] | None = None  # Decision explanation from ExplanationBuilder

    # Cost summary (per-debate cost breakdown when available)
    cost_summary: dict[str, Any] | None = None

    # Epistemic settlement metadata (optional, for quality feedback loop)
    settlement_metadata: dict[str, Any] | None = None

    # Taint analysis (G2 — populated when tainted context influenced any proposal)
    taint_analysis: dict[str, Any] | None = None

    # Extended thinking traces from Anthropic agents (optional, for explainability)
    # Maps agent name -> thinking trace string produced during the debate
    thinking_traces: dict[str, str] | None = None

    # Schema version for forward compatibility
    schema_version: str = "1.1"

    # Integrity
    artifact_hash: str = ""  # Content-addressable hash of entire receipt
    config_used: dict = field(default_factory=dict)

    # Signature fields for cryptographic signing
    signature: str | None = None
    signature_algorithm: str | None = None
    signature_key_id: str | None = None
    signed_at: str | None = None  # ISO format timestamp

    def __post_init__(self):
        """Calculate artifact hash if not provided."""
        if not self.artifact_hash:
            self.artifact_hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """Calculate content-addressable hash."""
        content = json.dumps(
            {
                "receipt_id": self.receipt_id,
                "gauntlet_id": self.gauntlet_id,
                "input_hash": self.input_hash,
                "risk_summary": self.risk_summary,
                "verdict": self.verdict,
                "confidence": self.confidence,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        """Verify receipt has not been tampered with."""
        expected_hash = self._calculate_hash()
        return expected_hash == self.artifact_hash

    def sign(self, signer: ReceiptSigner | None = None) -> DecisionReceipt:
        """
        Sign this receipt and return self with signature populated.

        Args:
            signer: Optional ReceiptSigner instance. Uses default if not provided.

        Returns:
            Self with signature fields populated.
        """
        from aragora.gauntlet.signing import get_default_signer

        signer = signer or get_default_signer()
        signed = signer.sign(self.to_dict())

        self.signature = signed.signature
        self.signature_algorithm = signed.signature_metadata.algorithm
        self.signature_key_id = signed.signature_metadata.key_id
        self.signed_at = signed.signature_metadata.timestamp

        return self

    def verify_signature(self, signer: ReceiptSigner | None = None) -> bool:
        """
        Verify the cryptographic signature on this receipt.

        Args:
            signer: Optional ReceiptSigner instance. Uses default if not provided.

        Returns:
            True if signature is valid, False otherwise.
        """
        if not self.signature:
            return False

        from aragora.gauntlet.signing import (
            SignedReceipt,
            SignatureMetadata,
            get_default_signer,
        )

        signer = signer or get_default_signer()

        # Reconstruct SignedReceipt for verification
        # Note: We need to exclude signature fields from the receipt data
        receipt_data = self._to_dict_for_signing()

        metadata = SignatureMetadata(
            algorithm=self.signature_algorithm or "",
            timestamp=self.signed_at or "",
            key_id=self.signature_key_id or "",
        )

        signed_receipt = SignedReceipt(
            receipt_data=receipt_data,
            signature=self.signature,
            signature_metadata=metadata,
        )

        return signer.verify(signed_receipt)

    def _to_dict_for_signing(self) -> dict:
        """Return dict without signature fields for signing/verification."""
        data = self.to_dict()
        # Remove signature fields to get the original data that was signed
        data.pop("signature", None)
        data.pop("signature_algorithm", None)
        data.pop("signature_key_id", None)
        data.pop("signed_at", None)
        return data

    def _signature_verification_html(self) -> str:
        """Generate HTML signature verification block for PDF embedding.

        Returns an empty string if the receipt is not signed.
        When signed, returns a styled verification section with:
        - Signature algorithm and key ID
        - Timestamp of signing
        - Truncated signature for visual verification
        - QR-code placeholder for verification URL
        """
        if not self.signature:
            return ""

        # Truncate signature for display (show first and last 16 chars)
        sig_display = self.signature
        if len(sig_display) > 40:
            sig_display = f"{sig_display[:16]}...{sig_display[-16:]}"

        verification_url = f"https://aragora.ai/verify/{escape(self.receipt_id)}"

        return f"""
    <div class="section" style="margin-top: 32px; padding-top: 20px; border-top: 2px solid #28a745;">
        <h2 style="color: #28a745;">
            <span style="margin-right: 8px;">&#x2714;</span>
            Cryptographically Signed Document
        </h2>
        <div style="background: #f0fff0; border: 1px solid #28a745; border-radius: 8px; padding: 16px; margin-top: 12px;">
            <table style="width: 100%; border: none; margin: 0;">
                <tr style="border: none;">
                    <td style="border: none; padding: 4px 8px; width: 140px;"><strong>Algorithm:</strong></td>
                    <td style="border: none; padding: 4px 8px;"><code>{escape(self.signature_algorithm or "Unknown")}</code></td>
                </tr>
                <tr style="border: none;">
                    <td style="border: none; padding: 4px 8px;"><strong>Key ID:</strong></td>
                    <td style="border: none; padding: 4px 8px;"><code>{escape(self.signature_key_id or "N/A")}</code></td>
                </tr>
                <tr style="border: none;">
                    <td style="border: none; padding: 4px 8px;"><strong>Signed At:</strong></td>
                    <td style="border: none; padding: 4px 8px;">{escape(self.signed_at or "Unknown")}</td>
                </tr>
                <tr style="border: none;">
                    <td style="border: none; padding: 4px 8px;"><strong>Signature:</strong></td>
                    <td style="border: none; padding: 4px 8px;"><code style="font-size: 11px; word-break: break-all;">{escape(sig_display)}</code></td>
                </tr>
            </table>
        </div>
        <p style="margin-top: 12px; font-size: 12px; color: #666;">
            <strong>Verification:</strong> To verify this document's authenticity, visit
            <a href="{verification_url}" style="color: #007bff;">{verification_url}</a>
            or use the Aragora CLI: <code>aragora verify {escape(self.receipt_id)}</code>
        </p>
        <p style="margin-top: 8px; font-size: 11px; color: #999;">
            This signature cryptographically binds the receipt content to the signing key.
            Any modification to the document will invalidate the signature.
        </p>
    </div>
"""

    @classmethod
    def from_result(cls, result: GauntletResult) -> DecisionReceipt:
        """Create receipt from GauntletResult."""
        receipt_id = str(uuid.uuid4())

        # Build provenance chain
        provenance = []

        # Add attack events
        for vuln in result.vulnerabilities:
            if vuln.source == "red_team":
                provenance.append(
                    ProvenanceRecord(
                        timestamp=vuln.created_at,
                        event_type="attack",
                        agent=vuln.agent_name,
                        description=f"[{vuln.severity.value}] {vuln.title[:50]}",
                        evidence_hash=hashlib.sha256(vuln.description.encode()).hexdigest()[:16],
                    )
                )

        # Add probe events
        for vuln in result.vulnerabilities:
            if vuln.source == "capability_probe":
                provenance.append(
                    ProvenanceRecord(
                        timestamp=vuln.created_at,
                        event_type="probe",
                        agent=vuln.agent_name,
                        description=f"[{vuln.category}] {vuln.title[:50]}",
                        evidence_hash=hashlib.sha256(vuln.description.encode()).hexdigest()[:16],
                    )
                )

        # Add verdict event
        provenance.append(
            ProvenanceRecord(
                timestamp=result.completed_at,
                event_type="verdict",
                description=f"Verdict: {result.verdict.value} ({result.confidence:.1%} confidence)",
            )
        )

        # Build consensus proof
        consensus = ConsensusProof(
            reached=result.verdict.value != "fail",
            confidence=result.confidence,
            supporting_agents=result.agents_used,
            method="adversarial_validation",
        )

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=result.gauntlet_id,
            timestamp=result.completed_at,
            input_summary=result.input_summary,
            input_hash=result.input_hash,
            risk_summary=result.risk_summary.to_dict(),
            attacks_attempted=result.attack_summary.total_attacks,
            attacks_successful=result.attack_summary.successful_attacks,
            probes_run=result.probe_summary.probes_run,
            vulnerabilities_found=result.risk_summary.total,
            vulnerability_details=[v.to_dict() for v in result.get_critical_vulnerabilities()],
            verdict=result.verdict.value.upper(),
            confidence=result.confidence,
            robustness_score=result.attack_summary.robustness_score,
            verdict_reasoning=result.verdict_reasoning,
            dissenting_views=result.dissenting_views,
            consensus_proof=consensus,
            provenance_chain=provenance,
            config_used=result.config_used,
        )

    @classmethod
    def from_mode_result(
        cls,
        result: Any,
        input_hash: str | None = None,
    ) -> DecisionReceipt:
        """Create receipt from aragora.gauntlet.GauntletResult."""
        receipt_id = str(uuid.uuid4())

        findings = list(getattr(result, "all_findings", []))
        critical = len(getattr(result, "critical_findings", []))
        high = len(getattr(result, "high_findings", []))
        medium = len(getattr(result, "medium_findings", []))
        low = len(getattr(result, "low_findings", []))

        redteam = getattr(result, "redteam_result", None)
        probe_report = getattr(result, "probe_report", None)
        audit_verdict = getattr(result, "audit_verdict", None)

        provenance = []
        for finding in findings:
            provenance.append(
                ProvenanceRecord(
                    timestamp=getattr(finding, "timestamp", ""),
                    event_type="finding",
                    agent=None,
                    description=f"[{finding.severity_level}] {finding.title[:50]}",
                    evidence_hash=hashlib.sha256(finding.description.encode()).hexdigest()[:16],
                )
            )

        provenance.append(
            ProvenanceRecord(
                timestamp=getattr(result, "created_at", ""),
                event_type="verdict",
                description=f"Verdict: {result.verdict.value} ({result.confidence:.1%} confidence)",
            )
        )

        dissenting = []
        for dissent in getattr(result, "dissenting_views", []):
            if hasattr(dissent, "agent"):
                reasons = "; ".join(getattr(dissent, "reasons", []) or [])
                summary = f"{dissent.agent}: {reasons}".strip()
                if getattr(dissent, "alternative_view", None):
                    summary = f"{summary} | alt: {dissent.alternative_view}".strip()
                dissenting.append(summary)
            else:
                dissenting.append(str(dissent))

        dissenting_agents = [
            getattr(d, "agent", "")
            for d in getattr(result, "dissenting_views", [])
            if getattr(d, "agent", None)
        ]

        consensus = ConsensusProof(
            reached=bool(getattr(result, "consensus_reached", False)),
            confidence=result.confidence,
            supporting_agents=list(getattr(result, "agents_involved", [])),
            dissenting_agents=dissenting_agents,
            method="gauntlet_consensus",
            evidence_hash=getattr(result, "checksum", ""),
        )

        verdict_reasoning = (
            f"Risk score: {result.risk_score:.0%}, "
            f"Coverage: {result.coverage_score:.0%}, "
            f"Verification: {getattr(result, 'verification_coverage', 0.0):.0%}"
        )
        if audit_verdict and getattr(audit_verdict, "recommendation", None):
            verdict_reasoning = audit_verdict.recommendation[:500]

        severity_details = [
            {
                "id": f.finding_id,
                "category": f.category,
                "severity": f.severity,
                "severity_level": f.severity_level,
                "title": f.title,
                "description": f.description,
                "evidence": f.evidence,
                "mitigation": f.mitigation,
                "source": f.source,
                "verified": f.verified,
                "timestamp": f.timestamp,
            }
            for f in findings
            if f.severity_level in ("CRITICAL", "HIGH")
        ]

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=result.gauntlet_id,
            timestamp=getattr(result, "created_at", ""),
            input_summary=result.input_summary,
            input_hash=input_hash
            or getattr(result, "input_hash", "")
            or getattr(result, "checksum", ""),
            risk_summary={
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
                "total": len(findings),
            },
            attacks_attempted=getattr(redteam, "total_attacks", 0) if redteam else 0,
            attacks_successful=getattr(redteam, "successful_attacks", 0) if redteam else 0,
            probes_run=getattr(probe_report, "probes_run", 0) if probe_report else 0,
            vulnerabilities_found=len(findings),
            verdict=result.verdict.value.upper(),
            confidence=result.confidence,
            robustness_score=result.robustness_score,
            vulnerability_details=severity_details,
            verdict_reasoning=verdict_reasoning,
            dissenting_views=dissenting,
            consensus_proof=consensus,
            provenance_chain=provenance,
        )

    @classmethod
    def from_gauntlet_result(cls, result: Any) -> DecisionReceipt:
        """Create receipt from aragora.gauntlet.config.GauntletResult.

        This handles the GauntletResult dataclass from config.py which has
        different attributes than the one from result.py.
        """
        receipt_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Build provenance chain from findings
        provenance: list[ProvenanceRecord] = []
        for finding in getattr(result, "findings", []):
            provenance.append(
                ProvenanceRecord(
                    timestamp=timestamp,
                    event_type="finding",
                    description=f"[{finding.severity.value}] {finding.title[:50]}",
                    evidence_hash=hashlib.sha256(finding.description.encode()).hexdigest()[:16],
                )
            )

        # Add verdict event
        verdict_str = "PASS" if result.passed else "FAIL"
        provenance.append(
            ProvenanceRecord(
                timestamp=timestamp,
                event_type="verdict",
                description=f"Verdict: {verdict_str} ({result.confidence:.1%} confidence)",
            )
        )

        # Build consensus proof
        consensus = ConsensusProof(
            reached=result.consensus_reached,
            confidence=result.confidence,
            supporting_agents=result.agents_used,
            method="gauntlet_validation",
        )

        # Build risk summary from severity counts
        severity_counts = result.severity_counts
        risk_summary = {
            "critical": severity_counts.get("critical", 0),
            "high": severity_counts.get("high", 0),
            "medium": severity_counts.get("medium", 0),
            "low": severity_counts.get("low", 0),
            "total": len(result.findings),
        }

        # Build vulnerability details from critical findings
        vulnerability_details = [
            {
                "id": f.id,
                "category": f.category,
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "recommendations": f.recommendations,
            }
            for f in result.critical_findings
        ]

        # Calculate input hash
        input_hash = hashlib.sha256(result.input_text.encode()).hexdigest()

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=result.id,
            timestamp=timestamp,
            input_summary=result.input_text[:500] if result.input_text else "",
            input_hash=input_hash,
            risk_summary=risk_summary,
            attacks_attempted=result.probes_executed,
            attacks_successful=len(result.findings),
            probes_run=result.probes_executed,
            vulnerabilities_found=len(result.findings),
            verdict=verdict_str,
            confidence=result.confidence,
            robustness_score=result.robustness_score,
            vulnerability_details=vulnerability_details,
            verdict_reasoning=result.verdict_summary,
            consensus_proof=consensus,
            provenance_chain=provenance,
            config_used=result.config.to_dict() if result.config else {},
        )

    @classmethod
    def from_debate_result(
        cls,
        result: Any,
        input_hash: str | None = None,
        cost_summary: dict[str, Any] | None = None,
        settlement_metadata: dict[str, Any] | None = None,
    ) -> DecisionReceipt:
        """Create receipt from aragora.core_types.DebateResult.

        Used for auto-generating decision receipts after debate completion
        when receipt generation is enabled in arena config.

        Args:
            result: A DebateResult from the debate system
            input_hash: Optional pre-computed hash of input content
            cost_summary: Optional per-debate cost breakdown dict from
                DebateCostSummary.to_dict()
            settlement_metadata: Optional settlement metadata dict from
                SettlementMetadata.to_dict() for epistemic quality tracking

        Returns:
            DecisionReceipt for audit trail
        """
        receipt_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Extract debate ID
        debate_id = getattr(result, "debate_id", "") or getattr(result, "id", "")
        if not debate_id:
            debate_id = f"debate-{receipt_id[:8]}"

        # Build provenance chain from messages and votes
        provenance: list[ProvenanceRecord] = []

        # Add message events (sample key messages to avoid bloat)
        messages = list(getattr(result, "messages", []))
        for msg in messages[:10]:  # Limit to 10 messages
            provenance.append(
                ProvenanceRecord(
                    timestamp=getattr(msg, "timestamp", timestamp),
                    event_type="message",
                    agent=getattr(msg, "agent", None),
                    description=f"[{getattr(msg, 'role', 'participant')}] {str(getattr(msg, 'content', ''))[:50]}",
                    evidence_hash=hashlib.sha256(
                        str(getattr(msg, "content", "")).encode()
                    ).hexdigest()[:16],
                )
            )

        # Add vote events
        votes = list(getattr(result, "votes", []))
        for vote in votes:
            provenance.append(
                ProvenanceRecord(
                    timestamp=timestamp,
                    event_type="vote",
                    agent=getattr(vote, "voter", None),
                    description=f"Voted for {getattr(vote, 'choice', 'unknown')} (confidence: {getattr(vote, 'confidence', 0):.1%})",
                )
            )

        # Add verdict/consensus event
        provenance.append(
            ProvenanceRecord(
                timestamp=timestamp,
                event_type="verdict",
                description=f"Consensus: {'reached' if result.consensus_reached else 'not reached'} "
                f"({result.confidence:.1%} confidence)",
            )
        )

        # Build consensus proof
        participants = list(getattr(result, "participants", []))
        dissenting_views = list(getattr(result, "dissenting_views", []))

        # Identify dissenting agents from dissenting_views if possible
        dissenting_agents: list[str] = []
        for view in dissenting_views:
            if isinstance(view, str) and ":" in view:
                agent_name = view.split(":")[0].strip()
                if agent_name:
                    dissenting_agents.append(agent_name)

        # Supporting agents = participants minus dissenters
        supporting_agents = [p for p in participants if p not in dissenting_agents]

        consensus = ConsensusProof(
            reached=result.consensus_reached,
            confidence=result.confidence,
            supporting_agents=supporting_agents,
            dissenting_agents=dissenting_agents,
            method=getattr(result, "consensus_strength", "majority") or "majority",
            evidence_hash=(
                hashlib.sha256(result.final_answer.encode()).hexdigest()[:16]
                if result.final_answer
                else ""
            ),
        )

        # Compute input hash from task if not provided
        task = getattr(result, "task", "")
        if not input_hash and task:
            input_hash = hashlib.sha256(task.encode()).hexdigest()
        elif not input_hash:
            input_hash = ""

        # Determine verdict from consensus
        if result.consensus_reached and result.confidence >= 0.7:
            verdict = "PASS"
        elif result.consensus_reached:
            verdict = "CONDITIONAL"
        else:
            verdict = "FAIL"

        # Calculate robustness from consensus metrics
        robustness_score = result.confidence * (0.8 if result.consensus_reached else 0.5)
        if hasattr(result, "convergence_similarity"):
            robustness_score = (robustness_score + result.convergence_similarity) / 2

        # Build verdict reasoning
        reasoning_parts = []
        if result.consensus_reached:
            reasoning_parts.append(f"Consensus reached with {result.confidence:.1%} confidence")
        else:
            reasoning_parts.append("No consensus reached")

        if hasattr(result, "consensus_strength") and result.consensus_strength:
            reasoning_parts.append(f"Strength: {result.consensus_strength}")

        if result.winner:
            reasoning_parts.append(f"Winner: {result.winner}")

        verdict_reasoning = ". ".join(reasoning_parts)

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=debate_id,  # Use debate_id for gauntlet_id field
            timestamp=timestamp,
            input_summary=task[:500] if task else "",
            input_hash=input_hash,
            risk_summary={
                "critical": 0,  # Debates don't have severity-based findings
                "high": 0,
                "medium": 0,
                "low": 0,
                "total": len(dissenting_views),  # Use dissenting views as "findings"
            },
            attacks_attempted=0,  # Not applicable for debates
            attacks_successful=0,
            probes_run=result.rounds_used,  # Map rounds to probes
            vulnerabilities_found=len(dissenting_views),
            verdict=verdict,
            confidence=result.confidence,
            robustness_score=robustness_score,
            vulnerability_details=[],  # No vulnerability details for debates
            verdict_reasoning=verdict_reasoning,
            dissenting_views=dissenting_views,
            consensus_proof=consensus,
            provenance_chain=provenance,
            cost_summary=cost_summary,
            settlement_metadata=settlement_metadata,
            config_used={
                "rounds": result.rounds_used,
                "participants": participants,
                "duration_seconds": result.duration_seconds,
            },
        )

    @classmethod
    def from_review_result(
        cls,
        review_result: dict,
        *,
        pr_url: str | None = None,
        reviewer_agents: list[str] | None = None,
    ) -> DecisionReceipt:
        """Create a decision receipt from a PR review result.

        Bridges the gap between ``aragora.cli.review.extract_review_findings()``
        output and cryptographic decision receipts, giving every code review an
        audit-ready, tamper-evident record.

        Args:
            review_result: The findings dict produced by
                ``extract_review_findings()`` with keys such as
                ``unanimous_critiques``, ``critical_issues``, ``high_issues``,
                ``medium_issues``, ``low_issues``, ``agreement_score``,
                ``split_opinions``, ``risk_areas``, ``final_summary``, and
                ``agents_used``.
            pr_url: Optional GitHub PR URL for metadata.
            reviewer_agents: Explicit list of agent names.  Falls back to
                ``review_result["agents_used"]`` when not provided.

        Returns:
            A ``DecisionReceipt`` with SHA-256 integrity hash, provenance
            chain, and consensus proof derived from the review findings.
        """
        receipt_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # --- agents ---
        agents_used: list[str] = reviewer_agents or list(review_result.get("agents_used", []))

        # --- severity counts ---
        critical_issues = list(review_result.get("critical_issues", []))
        high_issues = list(review_result.get("high_issues", []))
        medium_issues = list(review_result.get("medium_issues", []))
        low_issues = list(review_result.get("low_issues", []))

        total_issues = (
            len(critical_issues) + len(high_issues) + len(medium_issues) + len(low_issues)
        )

        risk_summary = {
            "critical": len(critical_issues),
            "high": len(high_issues),
            "medium": len(medium_issues),
            "low": len(low_issues),
            "total": total_issues,
        }

        # --- input hash (deterministic for same review content) ---
        # Canonical representation: sorted JSON of the stable review fields
        canonical_content = json.dumps(
            {
                "unanimous_critiques": review_result.get("unanimous_critiques", []),
                "critical_issues": [
                    i.get("issue", "") if isinstance(i, dict) else str(i) for i in critical_issues
                ],
                "high_issues": [
                    i.get("issue", "") if isinstance(i, dict) else str(i) for i in high_issues
                ],
                "medium_issues": [
                    i.get("issue", "") if isinstance(i, dict) else str(i) for i in medium_issues
                ],
                "low_issues": [
                    i.get("issue", "") if isinstance(i, dict) else str(i) for i in low_issues
                ],
                "final_summary": review_result.get("final_summary", ""),
            },
            sort_keys=True,
        )
        input_hash = hashlib.sha256(canonical_content.encode()).hexdigest()

        # --- determine verdict ---
        agreement_score = float(review_result.get("agreement_score", 0))

        if critical_issues:
            verdict = "FAIL"
        elif high_issues and agreement_score < 0.7:
            verdict = "FAIL"
        elif high_issues:
            verdict = "CONDITIONAL"
        elif total_issues == 0:
            verdict = "PASS"
        else:
            verdict = "PASS" if agreement_score >= 0.7 else "CONDITIONAL"

        # --- provenance chain ---
        provenance: list[ProvenanceRecord] = []

        # Record each agent's individual assessments
        all_issues = (
            [(i, "CRITICAL") for i in critical_issues]
            + [(i, "HIGH") for i in high_issues]
            + [(i, "MEDIUM") for i in medium_issues]
            + [(i, "LOW") for i in low_issues]
        )

        for issue_data, severity in all_issues:
            if isinstance(issue_data, dict):
                agent = issue_data.get("agent")
                description = f"[{severity}] {str(issue_data.get('issue', ''))[:80]}"
                evidence_content = json.dumps(issue_data, sort_keys=True, default=str)
            else:
                agent = None
                description = f"[{severity}] {str(issue_data)[:80]}"
                evidence_content = str(issue_data)

            provenance.append(
                ProvenanceRecord(
                    timestamp=timestamp,
                    event_type="review_finding",
                    agent=agent,
                    description=description,
                    evidence_hash=hashlib.sha256(evidence_content.encode()).hexdigest()[:16],
                )
            )

        # Record unanimous critiques
        for critique in review_result.get("unanimous_critiques", []):
            provenance.append(
                ProvenanceRecord(
                    timestamp=timestamp,
                    event_type="unanimous_critique",
                    description=str(critique)[:80],
                    evidence_hash=hashlib.sha256(str(critique).encode()).hexdigest()[:16],
                )
            )

        # Record split opinions
        for opinion in review_result.get("split_opinions", []):
            if isinstance(opinion, (list, tuple)) and len(opinion) >= 3:
                desc, majority, minority = opinion[0], opinion[1], opinion[2]
                provenance.append(
                    ProvenanceRecord(
                        timestamp=timestamp,
                        event_type="split_opinion",
                        description=f"{str(desc)[:60]} (for: {majority}, against: {minority})",
                        evidence_hash=hashlib.sha256(str(desc).encode()).hexdigest()[:16],
                    )
                )

        # Final verdict event
        provenance.append(
            ProvenanceRecord(
                timestamp=timestamp,
                event_type="verdict",
                description=(
                    f"Review verdict: {verdict} "
                    f"(agreement: {agreement_score:.1%}, "
                    f"{total_issues} issue(s) found)"
                ),
            )
        )

        # --- consensus proof ---
        # All agents are "supporting" if they participated; dissent captured
        # through split_opinions
        dissenting_agents: list[str] = []
        split_opinions = review_result.get("split_opinions", [])
        for opinion in split_opinions:
            if isinstance(opinion, (list, tuple)) and len(opinion) >= 3:
                minority = opinion[2]
                if isinstance(minority, list):
                    dissenting_agents.extend(minority)

        dissenting_agents = list(set(dissenting_agents))
        supporting_agents = [a for a in agents_used if a not in dissenting_agents]

        consensus = ConsensusProof(
            reached=agreement_score >= 0.5 and not critical_issues,
            confidence=agreement_score,
            supporting_agents=supporting_agents,
            dissenting_agents=dissenting_agents,
            method="multi_agent_review",
            evidence_hash=input_hash[:16],
        )

        # --- dissenting views ---
        dissenting_views: list[str] = list(review_result.get("risk_areas", []))
        for opinion in split_opinions:
            if isinstance(opinion, (list, tuple)) and len(opinion) >= 1:
                dissenting_views.append(str(opinion[0]))

        # --- vulnerability details (critical + high) ---
        vulnerability_details: list[dict] = []
        for issue_data in critical_issues + high_issues:
            if isinstance(issue_data, dict):
                vulnerability_details.append(
                    {
                        "agent": issue_data.get("agent", ""),
                        "issue": issue_data.get("issue", ""),
                        "target": issue_data.get("target", ""),
                        "severity": ("CRITICAL" if issue_data in critical_issues else "HIGH"),
                    }
                )
            else:
                vulnerability_details.append(
                    {
                        "issue": str(issue_data),
                        "severity": "HIGH",
                    }
                )

        # --- robustness score ---
        robustness_score = agreement_score * (1.0 - (len(critical_issues) * 0.2))
        robustness_score = max(0.0, min(1.0, robustness_score))

        # --- verdict reasoning ---
        summary = review_result.get("final_summary", "")
        verdict_reasoning = (
            summary[:500]
            if summary
            else f"Review found {total_issues} issue(s) with {agreement_score:.0%} agent agreement."
        )

        # --- input summary ---
        if pr_url:
            input_summary = f"PR review: {pr_url}"
        elif summary:
            input_summary = summary[:200]
        else:
            input_summary = f"Code review with {len(agents_used)} agents"

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=f"review-{receipt_id[:8]}",
            timestamp=timestamp,
            input_summary=input_summary,
            input_hash=input_hash,
            risk_summary=risk_summary,
            attacks_attempted=0,
            attacks_successful=0,
            probes_run=len(agents_used),
            vulnerabilities_found=total_issues,
            verdict=verdict,
            confidence=agreement_score,
            robustness_score=robustness_score,
            vulnerability_details=vulnerability_details,
            verdict_reasoning=verdict_reasoning,
            dissenting_views=dissenting_views,
            consensus_proof=consensus,
            provenance_chain=provenance,
            config_used={
                "pr_url": pr_url,
                "reviewer_agents": agents_used,
                "source": "aragora_review",
            },
        )

    @classmethod
    def from_plan_outcome(
        cls,
        outcome: Any,
        plan: Any | None = None,
        input_hash: str | None = None,
    ) -> DecisionReceipt:
        """Create receipt from PlanOutcome after decision plan execution.

        Used for generating cryptographic receipts after a DecisionPlan
        has been executed, providing an audit trail for the implementation.

        Args:
            outcome: A PlanOutcome from the pipeline executor
            plan: Optional DecisionPlan for additional context
            input_hash: Optional pre-computed hash of input content

        Returns:
            DecisionReceipt for audit trail
        """
        receipt_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        plan_id = getattr(outcome, "plan_id", "")
        debate_id = getattr(outcome, "debate_id", "")

        # Build provenance chain from execution
        provenance: list[ProvenanceRecord] = []

        # Add plan creation event if we have the plan
        if plan:
            created_at = getattr(plan, "created_at", None)
            if created_at:
                created_ts = (
                    created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
                )
            else:
                created_ts = timestamp
            provenance.append(
                ProvenanceRecord(
                    timestamp=created_ts,
                    event_type="plan_created",
                    description=f"Decision plan {plan_id} created from debate {debate_id}",
                )
            )

            # Add approval event if approved
            approval = getattr(plan, "approval_record", None)
            if approval:
                approval_ts = getattr(approval, "approved_at", timestamp)
                if hasattr(approval_ts, "isoformat"):
                    approval_ts = approval_ts.isoformat()
                provenance.append(
                    ProvenanceRecord(
                        timestamp=str(approval_ts),
                        event_type="plan_approved",
                        agent=getattr(approval, "approver_id", None),
                        description=f"Approved by {getattr(approval, 'approver_id', 'unknown')}",
                    )
                )

        # Add task completion events
        tasks_completed = getattr(outcome, "tasks_completed", 0)
        tasks_total = getattr(outcome, "tasks_total", 0)
        for i in range(tasks_completed):
            provenance.append(
                ProvenanceRecord(
                    timestamp=timestamp,
                    event_type="task_completed",
                    description=f"Task {i + 1}/{tasks_total} completed",
                )
            )

        # Add verification events
        verification_passed = getattr(outcome, "verification_passed", 0)
        verification_total = getattr(outcome, "verification_total", 0)
        if verification_total > 0:
            provenance.append(
                ProvenanceRecord(
                    timestamp=timestamp,
                    event_type="verification",
                    description=f"Verification: {verification_passed}/{verification_total} passed",
                )
            )

        # Add final outcome event
        success = getattr(outcome, "success", False)
        error = getattr(outcome, "error", None)
        provenance.append(
            ProvenanceRecord(
                timestamp=timestamp,
                event_type="verdict",
                description=f"Execution {'succeeded' if success else 'failed'}"
                + (f": {error}" if error else ""),
            )
        )

        # Build consensus proof from plan execution
        lessons = list(getattr(outcome, "lessons", []))
        consensus = ConsensusProof(
            reached=success,
            confidence=1.0 if success else 0.0,
            method="plan_execution",
            evidence_hash=hashlib.sha256(
                json.dumps(
                    {
                        "plan_id": plan_id,
                        "success": success,
                        "tasks_completed": tasks_completed,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:16],
        )

        # Compute input hash from task if not provided
        task = getattr(outcome, "task", "")
        if not input_hash and task:
            input_hash = hashlib.sha256(task.encode()).hexdigest()
        elif not input_hash:
            input_hash = ""

        # Determine verdict
        if success:
            verdict = "PASS"
        elif tasks_completed > 0 and tasks_completed < tasks_total:
            verdict = "CONDITIONAL"  # Partial success
        else:
            verdict = "FAIL"

        # Calculate robustness score
        if tasks_total > 0:
            task_ratio = tasks_completed / tasks_total
        else:
            task_ratio = 1.0 if success else 0.0

        if verification_total > 0:
            verify_ratio = verification_passed / verification_total
        else:
            verify_ratio = 1.0 if success else 0.0

        robustness_score = (task_ratio + verify_ratio) / 2

        # Build verdict reasoning
        reasoning_parts = []
        if success:
            reasoning_parts.append("Execution completed successfully")
        else:
            reasoning_parts.append(f"Execution failed: {error or 'unknown error'}")

        reasoning_parts.append(f"Tasks: {tasks_completed}/{tasks_total}")
        if verification_total > 0:
            reasoning_parts.append(f"Verification: {verification_passed}/{verification_total}")

        verdict_reasoning = ". ".join(reasoning_parts)

        # Get cost if available
        total_cost = getattr(outcome, "total_cost_usd", 0.0)
        duration = getattr(outcome, "duration_seconds", 0.0)

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=plan_id,  # Use plan_id for gauntlet_id field
            timestamp=timestamp,
            input_summary=task[:500] if task else "",
            input_hash=input_hash,
            risk_summary={
                "critical": 0,
                "high": 0 if success else 1,  # Failed execution is high risk
                "medium": 0,
                "low": len(lessons),  # Lessons are low-severity findings
                "total": 0 if success else 1,
            },
            attacks_attempted=0,  # Not applicable for plan execution
            attacks_successful=0,
            probes_run=tasks_total,  # Map tasks to probes
            vulnerabilities_found=0 if success else 1,
            verdict=verdict,
            confidence=robustness_score,
            robustness_score=robustness_score,
            vulnerability_details=[],
            verdict_reasoning=verdict_reasoning,
            dissenting_views=lessons,  # Lessons as dissenting views
            consensus_proof=consensus,
            provenance_chain=provenance,
            config_used={
                "plan_id": plan_id,
                "debate_id": debate_id,
                "tasks_total": tasks_total,
                "tasks_completed": tasks_completed,
                "verification_passed": verification_passed,
                "verification_total": verification_total,
                "total_cost_usd": total_cost,
                "duration_seconds": duration,
            },
        )

    def generate_compliance_artifacts(
        self,
        frameworks: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Generate regulatory compliance artifacts from this receipt.

        Creates framework-specific compliance documentation suitable for
        regulatory audit trails. Supported frameworks:

        - ``eu_ai_act``: EU AI Act (Regulation 2024/1689)
        - ``soc2``: SOC 2 Type II (AICPA Trust Services Criteria)
        - ``hipaa``: HIPAA Security and Privacy Rule

        Args:
            frameworks: List of framework identifiers to generate.
                If ``None``, all supported frameworks are generated.
            **kwargs: Additional keyword arguments passed to
                ``ReceiptComplianceGenerator``.

        Returns:
            ComplianceArtifactResult containing the requested artifacts.

        Example::

            result = receipt.generate_compliance_artifacts(
                frameworks=["eu_ai_act", "soc2"]
            )
            print(result.eu_ai_act.risk_classification)
            print(result.soc2.to_json())
        """
        from aragora.compliance.artifact_generator import ReceiptComplianceGenerator

        generator = ReceiptComplianceGenerator(**kwargs)
        return generator.generate(self.to_dict(), frameworks=frameworks)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Recursively convert values into JSON-serializable primitives."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): DecisionReceipt._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [DecisionReceipt._json_safe(v) for v in value]
        return value

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        data = {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "timestamp": self.timestamp,
            "input_summary": self.input_summary,
            "input_hash": self.input_hash,
            "risk_summary": self.risk_summary,
            "attacks_attempted": self.attacks_attempted,
            "attacks_successful": self.attacks_successful,
            "probes_run": self.probes_run,
            "vulnerabilities_found": self.vulnerabilities_found,
            "vulnerability_details": self.vulnerability_details,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "robustness_score": self.robustness_score,
            "verdict_reasoning": self.verdict_reasoning,
            "dissenting_views": self.dissenting_views,
            "consensus_proof": self.consensus_proof.to_dict() if self.consensus_proof else None,
            "provenance_chain": [p.to_dict() for p in self.provenance_chain],
            "cost_summary": self.cost_summary,
            "settlement_metadata": self.settlement_metadata,
            "explainability": self.explainability,
            "schema_version": self.schema_version,
            "artifact_hash": self.artifact_hash,
            "config_used": self.config_used,
        }
        # Include signature fields if present
        if self.signature:
            data["signature"] = self.signature
            data["signature_algorithm"] = self.signature_algorithm
            data["signature_key_id"] = self.signature_key_id
            data["signed_at"] = self.signed_at
        return self._json_safe(data)

    @classmethod
    def from_dict(cls, data: dict) -> DecisionReceipt:
        """Reconstruct a DecisionReceipt from a dictionary."""
        consensus_data = data.get("consensus_proof")
        consensus = ConsensusProof(**consensus_data) if isinstance(consensus_data, dict) else None
        provenance_data = data.get("provenance_chain") or []
        provenance = [
            ProvenanceRecord(**record) if isinstance(record, dict) else record
            for record in provenance_data
        ]

        return cls(
            receipt_id=data.get("receipt_id", ""),
            gauntlet_id=data.get("gauntlet_id", ""),
            timestamp=data.get("timestamp", ""),
            input_summary=data.get("input_summary", ""),
            input_hash=data.get("input_hash", ""),
            risk_summary=data.get("risk_summary", {}),
            attacks_attempted=data.get("attacks_attempted", 0),
            attacks_successful=data.get("attacks_successful", 0),
            probes_run=data.get("probes_run", 0),
            vulnerabilities_found=data.get("vulnerabilities_found", 0),
            verdict=data.get("verdict", ""),
            confidence=float(data.get("confidence", 0.0)),
            robustness_score=float(data.get("robustness_score", 0.0)),
            vulnerability_details=data.get("vulnerability_details", []) or [],
            verdict_reasoning=data.get("verdict_reasoning", ""),
            dissenting_views=data.get("dissenting_views", []) or [],
            consensus_proof=consensus,
            provenance_chain=provenance,
            schema_version=data.get("schema_version", "1.0"),
            artifact_hash=data.get("artifact_hash", ""),
            cost_summary=data.get("cost_summary"),
            settlement_metadata=data.get("settlement_metadata"),
            config_used=data.get("config_used", {}) or {},
            # Signature fields
            signature=data.get("signature"),
            signature_algorithm=data.get("signature_algorithm"),
            signature_key_id=data.get("signature_key_id"),
            signed_at=data.get("signed_at"),
        )

    def to_markdown(self, include_provenance: bool = True, include_evidence: bool = True) -> str:
        """Generate markdown report with full provenance and evidence links."""
        from aragora.gauntlet.receipt_exporters import receipt_to_markdown

        return receipt_to_markdown(
            self, include_provenance=include_provenance, include_evidence=include_evidence
        )

    def to_html(self, max_findings: int = 20, max_provenance: int = 50) -> str:
        """Export as self-contained HTML document."""
        from aragora.gauntlet.receipt_exporters import receipt_to_html

        return receipt_to_html(self, max_findings=max_findings, max_provenance=max_provenance)

    def to_html_paginated(
        self,
        findings_per_page: int = 10,
        max_provenance: int = 50,
        provenance_sampling: str = "first_last",
    ) -> str:
        """Export as paginated HTML document optimized for PDF rendering."""
        from aragora.gauntlet.receipt_exporters import receipt_to_html_paginated

        return receipt_to_html_paginated(
            self,
            findings_per_page=findings_per_page,
            max_provenance=max_provenance,
            provenance_sampling=provenance_sampling,
        )

    def _sample_provenance(self, max_records: int, strategy: str) -> list[ProvenanceRecord]:
        """Sample provenance chain based on strategy.

        Args:
            max_records: Maximum records to return
            strategy: "all", "first_last", or "sampled"

        Returns:
            Sampled list of ProvenanceRecord
        """
        records = self.provenance_chain
        if not records or max_records <= 0:
            return []

        if len(records) <= max_records:
            return records

        if strategy == "first_last":
            # Take first half and last half
            half = max_records // 2
            return list(records[:half]) + list(records[-half:])
        elif strategy == "sampled":
            # Evenly sample across the chain
            step = max(1, len(records) // max_records)
            return list(records[::step])[:max_records]
        else:
            # "all" or unknown: just truncate
            return list(records[:max_records])

    def to_json(self, indent: int = 2) -> str:
        """Export as JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_sarif(self) -> dict:
        """Export as SARIF 2.1.0 format."""
        from aragora.gauntlet.receipt_exporters import receipt_to_sarif

        return receipt_to_sarif(self)

    def to_sarif_json(self, indent: int = 2) -> str:
        """Export as SARIF JSON string."""
        return json.dumps(self.to_sarif(), indent=indent)

    def to_pdf(self) -> bytes:
        """Export as PDF document.

        Requires weasyprint to be installed: pip install weasyprint

        Returns:
            PDF content as bytes

        Raises:
            ImportError: If weasyprint is not installed
        """
        try:
            from weasyprint import HTML
        except ImportError as e:
            raise ImportError(
                "weasyprint is required for PDF export. Install with: pip install weasyprint"
            ) from e

        html_content = self.to_html()
        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes

    def to_csv(self) -> str:
        """Export findings as CSV format."""
        from aragora.gauntlet.receipt_exporters import receipt_to_csv

        return receipt_to_csv(self)
