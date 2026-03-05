"""
EU AI Act Compliance Module.

Maps Aragora Decision Receipts to EU AI Act requirements for conformity
assessment. The EU AI Act (Regulation (EU) 2024/1689) takes effect
August 2, 2026 for Annex III high-risk systems.

Key articles mapped:
- Article 6:  Classification rules for high-risk AI systems
- Article 9:  Risk management system
- Article 13: Transparency and provision of information to deployers
- Article 14: Human oversight
- Article 50: Transparency obligations (formerly Art. 52 in drafts)

Annex III defines 8 categories of high-risk AI systems:
1. Biometrics
2. Critical infrastructure
3. Education and vocational training
4. Employment and worker management
5. Access to essential services
6. Law enforcement
7. Migration, asylum and border control
8. Administration of justice and democratic processes
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Risk classification per EU AI Act Article 6 + Annex III
# ---------------------------------------------------------------------------


class RiskLevel(Enum):
    """EU AI Act risk tiers."""

    UNACCEPTABLE = "unacceptable"
    HIGH = "high"
    LIMITED = "limited"
    MINIMAL = "minimal"


@dataclass
class RiskClassification:
    """Result of classifying a use case under the EU AI Act."""

    risk_level: RiskLevel
    annex_iii_category: str | None = None
    annex_iii_number: int | None = None
    rationale: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    applicable_articles: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level.value,
            "annex_iii_category": self.annex_iii_category,
            "annex_iii_number": self.annex_iii_number,
            "rationale": self.rationale,
            "matched_keywords": self.matched_keywords,
            "applicable_articles": self.applicable_articles,
            "obligations": self.obligations,
        }


# Annex III categories with detection keywords
ANNEX_III_CATEGORIES: list[dict[str, Any]] = [
    {
        "number": 1,
        "name": "Biometrics",
        "description": "Remote biometric identification, biometric categorization, emotion recognition",
        "keywords": [
            "biometric",
            "facial recognition",
            "face detection",
            "emotion recognition",
            "fingerprint identification",
            "iris scan",
            "voice identification",
            "remote identification",
            "biometric categorization",
        ],
    },
    {
        "number": 2,
        "name": "Critical infrastructure",
        "description": "Safety components in critical digital infrastructure, road traffic, water, gas, heating, electricity",
        "keywords": [
            "critical infrastructure",
            "power grid",
            "water supply",
            "gas supply",
            "electricity",
            "road traffic",
            "traffic management",
            "digital infrastructure",
            "energy supply",
            "heating supply",
            "safety component",
        ],
    },
    {
        "number": 3,
        "name": "Education and vocational training",
        "description": "Determining access to education, assessing students, monitoring exams",
        "keywords": [
            "student assessment",
            "educational admission",
            "exam proctoring",
            "grading system",
            "academic evaluation",
            "learning assessment",
            "vocational training",
            "educational institution",
            "student scoring",
        ],
    },
    {
        "number": 4,
        "name": "Employment and worker management",
        "description": "Recruitment, CV screening, performance evaluation, task allocation, termination",
        "keywords": [
            "recruitment",
            "cv screening",
            "resume screening",
            "hiring decision",
            "job application",
            "performance evaluation",
            "employee monitoring",
            "worker management",
            "task allocation",
            "termination decision",
            "promotion decision",
            "workforce management",
        ],
    },
    {
        "number": 5,
        "name": "Access to essential services",
        "description": "Credit scoring, insurance risk, public benefit eligibility, emergency dispatch",
        "keywords": [
            "credit scoring",
            "credit score",
            "creditworthiness",
            "loan decision",
            "insurance risk",
            "health insurance",
            "benefit eligibility",
            "public assistance",
            "emergency dispatch",
            "emergency services",
            "essential services",
            "social benefit",
        ],
    },
    {
        "number": 6,
        "name": "Law enforcement",
        "description": "Crime analytics, evidence reliability, recidivism risk, profiling",
        "keywords": [
            "law enforcement",
            "crime prediction",
            "predictive policing",
            "evidence evaluation",
            "recidivism",
            "criminal profiling",
            "crime analytics",
            "suspect identification",
            "polygraph",
        ],
    },
    {
        "number": 7,
        "name": "Migration, asylum and border control",
        "description": "Security risk assessment, visa/asylum application processing, border surveillance",
        "keywords": [
            "migration",
            "asylum",
            "border control",
            "visa application",
            "immigration",
            "border surveillance",
            "refugee",
            "deportation",
            "travel document",
            "security risk assessment",
        ],
    },
    {
        "number": 8,
        "name": "Administration of justice and democratic processes",
        "description": "Judicial research, legal interpretation, election influence",
        "keywords": [
            "judicial",
            "court decision",
            "legal interpretation",
            "sentencing",
            "justice system",
            "election",
            "voting",
            "democratic process",
            "legal reasoning",
            "case law analysis",
        ],
    },
]

# Patterns for unacceptable-risk AI (Article 5 prohibitions)
UNACCEPTABLE_KEYWORDS: list[str] = [
    "social scoring",
    "social credit",
    "subliminal manipulation",
    "exploit vulnerability",
    "real-time remote biometric identification",
    "emotion recognition in workplace",
    "emotion recognition in education",
    "untargeted scraping of facial images",
    "cognitive behavioral manipulation",
]


class RiskClassifier:
    """
    Classify AI use cases by EU AI Act risk level.

    Implements Article 6 classification rules and Annex III category matching.
    """

    def classify(self, description: str) -> RiskClassification:
        """
        Classify a use case description by EU AI Act risk level.

        Args:
            description: Free-text description of the AI use case.

        Returns:
            RiskClassification with level, category, and obligations.
        """
        description_lower = description.lower()

        # Check unacceptable risk first (Article 5)
        unacceptable_matches = [kw for kw in UNACCEPTABLE_KEYWORDS if kw in description_lower]
        if unacceptable_matches:
            return RiskClassification(
                risk_level=RiskLevel.UNACCEPTABLE,
                rationale="Use case matches prohibited AI practices under Article 5.",
                matched_keywords=unacceptable_matches,
                applicable_articles=["Article 5"],
                obligations=["This AI practice is prohibited under the EU AI Act."],
            )

        # Check high-risk (Annex III categories)
        for category in ANNEX_III_CATEGORIES:
            matches = [kw for kw in category["keywords"] if kw in description_lower]
            if matches:
                return RiskClassification(
                    risk_level=RiskLevel.HIGH,
                    annex_iii_category=category["name"],
                    annex_iii_number=category["number"],
                    rationale=(
                        f"Use case falls under Annex III category {category['number']}: "
                        f"{category['name']}. {category['description']}."
                    ),
                    matched_keywords=matches,
                    applicable_articles=[
                        "Article 6 (Classification)",
                        "Article 9 (Risk management)",
                        "Article 13 (Transparency)",
                        "Article 14 (Human oversight)",
                        "Article 15 (Accuracy, robustness, cybersecurity)",
                    ],
                    obligations=_high_risk_obligations(category["name"]),
                )

        # Check limited-risk (Article 50 transparency obligations)
        limited_keywords = [
            "chatbot",
            "generated content",
            "deepfake",
            "synthetic media",
            "ai-generated",
            "virtual assistant",
            "conversational ai",
        ]
        limited_matches = [kw for kw in limited_keywords if kw in description_lower]
        if limited_matches:
            return RiskClassification(
                risk_level=RiskLevel.LIMITED,
                rationale="Use case involves AI systems with transparency obligations under Article 50.",
                matched_keywords=limited_matches,
                applicable_articles=["Article 50 (Transparency obligations)"],
                obligations=[
                    "Inform users they are interacting with an AI system.",
                    "Label AI-generated content as artificially generated or manipulated.",
                    "Maintain technical documentation.",
                ],
            )

        # Default: minimal risk
        return RiskClassification(
            risk_level=RiskLevel.MINIMAL,
            rationale="Use case does not match high-risk or limited-risk categories. Minimal obligations apply.",
            applicable_articles=[],
            obligations=[
                "Voluntary adoption of codes of conduct encouraged (Article 95).",
            ],
        )

    def classify_receipt(self, receipt_dict: dict[str, Any]) -> RiskClassification:
        """
        Classify a DecisionReceipt's underlying use case.

        Uses the input_summary and verdict_reasoning fields to infer the domain.
        """
        text = " ".join(
            [
                receipt_dict.get("input_summary", ""),
                receipt_dict.get("verdict_reasoning", ""),
            ]
        )
        return self.classify(text)


def _high_risk_obligations(category_name: str) -> list[str]:
    """Return obligations for a high-risk AI system."""
    base = [
        "Establish and maintain a risk management system (Art. 9).",
        "Use high-quality training, validation, and testing data (Art. 10).",
        "Maintain technical documentation (Art. 11).",
        "Implement automatic logging of events (Art. 12).",
        "Ensure transparency and provide instructions for deployers (Art. 13).",
        "Design for effective human oversight (Art. 14).",
        "Achieve appropriate accuracy, robustness, and cybersecurity (Art. 15).",
        "Register in the EU database before placing on market (Art. 49).",
        "Undergo conformity assessment (Art. 43).",
    ]
    return base


# ---------------------------------------------------------------------------
# Conformity assessment mapping: Receipt -> EU AI Act articles
# ---------------------------------------------------------------------------


@dataclass
class ArticleMapping:
    """Maps a receipt field to an EU AI Act article requirement."""

    article: str
    article_title: str
    requirement: str
    receipt_field: str
    status: str  # "satisfied", "partial", "not_satisfied", "not_applicable"
    evidence: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": self.article,
            "article_title": self.article_title,
            "requirement": self.requirement,
            "receipt_field": self.receipt_field,
            "status": self.status,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class ConformityReport:
    """EU AI Act conformity assessment report generated from a DecisionReceipt."""

    report_id: str
    receipt_id: str
    generated_at: str
    risk_classification: RiskClassification
    article_mappings: list[ArticleMapping]
    overall_status: str  # "conformant", "partial", "non_conformant"
    summary: str
    recommendations: list[str]
    integrity_hash: str = ""

    def __post_init__(self):
        if not self.integrity_hash:
            self.integrity_hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        content = json.dumps(
            {
                "report_id": self.report_id,
                "receipt_id": self.receipt_id,
                "overall_status": self.overall_status,
                "risk_level": self.risk_classification.risk_level.value,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "risk_classification": self.risk_classification.to_dict(),
            "article_mappings": [m.to_dict() for m in self.article_mappings],
            "overall_status": self.overall_status,
            "summary": self.summary,
            "recommendations": self.recommendations,
            "integrity_hash": self.integrity_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Export as human-readable markdown."""
        lines = [
            "# EU AI Act Conformity Report",
            "",
            f"**Report ID:** {self.report_id}",
            f"**Receipt ID:** {self.receipt_id}",
            f"**Generated:** {self.generated_at}",
            f"**Integrity Hash:** `{self.integrity_hash[:16]}...`",
            "",
            "---",
            "",
            "## Risk Classification",
            "",
            f"**Risk Level:** {self.risk_classification.risk_level.value.upper()}",
        ]

        if self.risk_classification.annex_iii_category:
            lines.append(
                f"**Annex III Category:** {self.risk_classification.annex_iii_number}. "
                f"{self.risk_classification.annex_iii_category}"
            )
        lines.append(f"**Rationale:** {self.risk_classification.rationale}")
        lines.append("")

        if self.risk_classification.obligations:
            lines.append("### Obligations")
            lines.append("")
            for obligation in self.risk_classification.obligations:
                lines.append(f"- {obligation}")
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## Article Compliance Assessment",
                "",
                f"**Overall Status:** {self.overall_status.upper()}",
                "",
                "| Article | Requirement | Status | Evidence |",
                "|---------|-------------|--------|----------|",
            ]
        )

        for m in self.article_mappings:
            status_indicator = {
                "satisfied": "PASS",
                "partial": "PARTIAL",
                "not_satisfied": "FAIL",
                "not_applicable": "N/A",
            }.get(m.status, m.status)
            evidence_short = m.evidence[:60] + "..." if len(m.evidence) > 60 else m.evidence
            lines.append(
                f"| {m.article} | {m.requirement[:50]} | {status_indicator} | {evidence_short} |"
            )

        lines.append("")

        if self.recommendations:
            lines.extend(
                [
                    "---",
                    "",
                    "## Recommendations",
                    "",
                ]
            )
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## Summary",
                "",
                self.summary,
                "",
            ]
        )

        return "\n".join(lines)


class ConformityReportGenerator:
    """
    Generate EU AI Act conformity assessment reports from DecisionReceipts.

    Maps receipt fields to article requirements:
    - Article 9  (Risk management):  receipt.risk_summary, confidence, robustness_score
    - Article 13 (Transparency):     provenance_chain, consensus_proof (agent participation)
    - Article 14 (Human oversight):  config_used for human approval indicators
    - Article 12 (Record-keeping):   provenance_chain completeness
    - Article 15 (Accuracy):         confidence, robustness_score
    """

    def __init__(self, classifier: RiskClassifier | None = None):
        self._classifier = classifier or RiskClassifier()

    def generate(self, receipt_dict: dict[str, Any]) -> ConformityReport:
        """
        Generate a conformity report from a receipt dictionary.

        Args:
            receipt_dict: Output of DecisionReceipt.to_dict().

        Returns:
            ConformityReport with article mappings and recommendations.
        """
        report_id = f"EUAIA-{str(uuid.uuid4())[:8]}"
        timestamp = datetime.now(timezone.utc).isoformat()
        receipt_id = receipt_dict.get("receipt_id", "unknown")

        # Classify the underlying use case
        classification = self._classifier.classify_receipt(receipt_dict)

        # Map receipt fields to article requirements
        mappings = self._map_articles(receipt_dict, classification)

        # Determine overall status
        statuses = [m.status for m in mappings if m.status != "not_applicable"]
        if all(s == "satisfied" for s in statuses):
            overall = "conformant"
        elif any(s == "not_satisfied" for s in statuses):
            overall = "non_conformant"
        else:
            overall = "partial"

        # Build recommendations
        recommendations = []
        for m in mappings:
            if m.recommendation and m.status != "satisfied":
                recommendations.append(m.recommendation)

        # Build summary
        satisfied_count = sum(1 for m in mappings if m.status == "satisfied")
        total_applicable = sum(1 for m in mappings if m.status != "not_applicable")
        summary = (
            f"Conformity assessment for receipt {receipt_id} against the EU AI Act. "
            f"Risk level: {classification.risk_level.value}. "
            f"{satisfied_count}/{total_applicable} applicable article requirements satisfied."
        )

        return ConformityReport(
            report_id=report_id,
            receipt_id=receipt_id,
            generated_at=timestamp,
            risk_classification=classification,
            article_mappings=mappings,
            overall_status=overall,
            summary=summary,
            recommendations=recommendations,
        )

    def _map_articles(
        self,
        receipt: dict[str, Any],
        classification: RiskClassification,
    ) -> list[ArticleMapping]:
        """Map receipt fields to EU AI Act article requirements."""
        mappings: list[ArticleMapping] = []

        # --- Article 9: Risk Management ---
        risk_summary = receipt.get("risk_summary", {})
        confidence = receipt.get("confidence", 0.0)
        robustness = receipt.get("robustness_score", 0.0)

        risk_total = risk_summary.get("total", 0)
        risk_critical = risk_summary.get("critical", 0)

        if risk_total > 0 or confidence > 0:
            risk_status = "satisfied" if risk_critical == 0 and confidence >= 0.5 else "partial"
            if risk_critical > 0:
                risk_status = "not_satisfied"
            mappings.append(
                ArticleMapping(
                    article="Article 9",
                    article_title="Risk management system",
                    requirement="Identify and analyze known and reasonably foreseeable risks",
                    receipt_field="risk_summary, confidence",
                    status=risk_status,
                    evidence=(
                        f"Risk assessment performed: {risk_total} risks identified "
                        f"({risk_critical} critical). Confidence: {confidence:.1%}."
                    ),
                    recommendation=(
                        "Address critical risks before deployment." if risk_critical > 0 else ""
                    ),
                )
            )
        else:
            mappings.append(
                ArticleMapping(
                    article="Article 9",
                    article_title="Risk management system",
                    requirement="Identify and analyze known and reasonably foreseeable risks",
                    receipt_field="risk_summary",
                    status="not_satisfied",
                    evidence="No risk assessment data found in receipt.",
                    recommendation="Conduct a risk assessment and record findings in the receipt.",
                )
            )

        # --- Article 12: Record-keeping (automatic logging) ---
        provenance = receipt.get("provenance_chain", [])
        log_status = "satisfied" if len(provenance) >= 2 else "partial"
        if not provenance:
            log_status = "not_satisfied"
        mappings.append(
            ArticleMapping(
                article="Article 12",
                article_title="Record-keeping",
                requirement="Automatic logging of events with traceability",
                receipt_field="provenance_chain",
                status=log_status,
                evidence=f"Provenance chain contains {len(provenance)} events.",
                recommendation=(
                    "Ensure all decision events are logged in the provenance chain."
                    if log_status != "satisfied"
                    else ""
                ),
            )
        )

        # --- Article 13: Transparency ---
        consensus = receipt.get("consensus_proof") or {}
        supporting = consensus.get("supporting_agents", [])
        dissenting = consensus.get("dissenting_agents", [])
        all_agents = list(set(supporting + dissenting))
        dissenting_views = receipt.get("dissenting_views", [])
        verdict_reasoning = receipt.get("verdict_reasoning", "")

        transparency_satisfied = bool(all_agents) and bool(verdict_reasoning)
        mappings.append(
            ArticleMapping(
                article="Article 13",
                article_title="Transparency and provision of information to deployers",
                requirement="Identify participating agents, their arguments, and decision rationale",
                receipt_field="consensus_proof, verdict_reasoning, dissenting_views",
                status="satisfied" if transparency_satisfied else "partial",
                evidence=(
                    f"{len(all_agents)} agents participated. "
                    f"Verdict reasoning: {verdict_reasoning[:100]}{'...' if len(verdict_reasoning) > 100 else ''}. "
                    f"{len(dissenting_views)} dissenting view(s) recorded."
                ),
                recommendation=(
                    "Include agent identities and reasoning in all receipts."
                    if not transparency_satisfied
                    else ""
                ),
            )
        )

        # --- Article 14: Human oversight ---
        config = receipt.get("config_used", {})
        has_human_oversight = _detect_human_oversight(config, receipt)
        mappings.append(
            ArticleMapping(
                article="Article 14",
                article_title="Human oversight",
                requirement="Enable human oversight, including ability to override or halt",
                receipt_field="config_used",
                status="satisfied" if has_human_oversight else "partial",
                evidence=(
                    "Human approval/override mechanism detected in receipt configuration."
                    if has_human_oversight
                    else "No explicit human oversight mechanism found in receipt."
                ),
                recommendation=(
                    ""
                    if has_human_oversight
                    else "Integrate human-in-the-loop approval before critical decisions are finalized."
                ),
            )
        )

        # --- Article 15: Accuracy, robustness, cybersecurity ---
        integrity_valid = bool(receipt.get("artifact_hash"))
        has_signature = bool(receipt.get("signature"))
        acc_status = "satisfied"
        if robustness < 0.5:
            acc_status = "partial"
        if robustness < 0.2:
            acc_status = "not_satisfied"

        mappings.append(
            ArticleMapping(
                article="Article 15",
                article_title="Accuracy, robustness and cybersecurity",
                requirement="Appropriate levels of accuracy and robustness; resilience to attacks",
                receipt_field="robustness_score, artifact_hash, signature",
                status=acc_status,
                evidence=(
                    f"Robustness score: {robustness:.1%}. "
                    f"Integrity hash: {'present' if integrity_valid else 'missing'}. "
                    f"Cryptographic signature: {'present' if has_signature else 'absent'}."
                ),
                recommendation=(
                    "Improve robustness score and add cryptographic signing."
                    if acc_status != "satisfied"
                    else ""
                ),
            )
        )

        return mappings


def _detect_human_oversight(config: dict[str, Any], receipt: dict[str, Any]) -> bool:
    """Detect whether human oversight was present in the decision process."""
    # Check for human-related config keys
    oversight_indicators = [
        "human_approval",
        "require_approval",
        "human_in_loop",
        "human_override",
        "approver",
        "approver_id",
        "approval_record",
    ]
    config_str = json.dumps(config).lower()
    for indicator in oversight_indicators:
        if indicator in config_str:
            return True

    # Check provenance chain for human events
    for event in receipt.get("provenance_chain", []):
        event_type = ""
        if isinstance(event, dict):
            event_type = event.get("event_type", "")
        elif hasattr(event, "event_type"):
            event_type = event.event_type
        if event_type in ("human_approval", "plan_approved", "human_override"):
            return True

    return False


# ---------------------------------------------------------------------------
# Article-specific artifact generators
# ---------------------------------------------------------------------------


@dataclass
class Article12Artifact:
    """Article 12 Record-Keeping artifact.

    Captures automatic event logging, reference databases consulted,
    input data records, technical documentation summary (Annex IV),
    and log retention policy per Art. 26(6).
    """

    receipt_id: str
    generated_at: str
    event_log: list[dict[str, Any]]
    reference_databases: list[dict[str, Any]]
    input_record: dict[str, Any]
    technical_documentation: dict[str, Any]
    retention_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": "Article 12",
            "title": "Record-Keeping",
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "event_log": self.event_log,
            "reference_databases": self.reference_databases,
            "input_record": self.input_record,
            "technical_documentation": self.technical_documentation,
            "retention_policy": self.retention_policy,
        }


@dataclass
class Article13Artifact:
    """Article 13 Transparency artifact.

    Contains provider identity, intended purpose, accuracy/robustness
    metrics, known risks, output interpretation guidance, and human
    oversight cross-references.
    """

    receipt_id: str
    generated_at: str
    provider_identity: dict[str, Any]
    intended_purpose: dict[str, Any]
    accuracy_robustness: dict[str, Any]
    known_risks: list[dict[str, Any]]
    output_interpretation: dict[str, Any]
    human_oversight_reference: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": "Article 13",
            "title": "Transparency and Provision of Information to Deployers",
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "provider_identity": self.provider_identity,
            "intended_purpose": self.intended_purpose,
            "accuracy_robustness": self.accuracy_robustness,
            "known_risks": self.known_risks,
            "output_interpretation": self.output_interpretation,
            "human_oversight_reference": self.human_oversight_reference,
        }


@dataclass
class Article14Artifact:
    """Article 14 Human Oversight artifact.

    Documents oversight model, understanding/monitoring capabilities,
    automation bias safeguards, output interpretation features,
    override mechanisms, and intervention (stop) capabilities.
    """

    receipt_id: str
    generated_at: str
    oversight_model: dict[str, Any]
    understanding_monitoring: dict[str, Any]
    automation_bias_safeguards: dict[str, Any]
    interpretation_features: dict[str, Any]
    override_capability: dict[str, Any]
    intervention_capability: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": "Article 14",
            "title": "Human Oversight",
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "oversight_model": self.oversight_model,
            "understanding_monitoring": self.understanding_monitoring,
            "automation_bias_safeguards": self.automation_bias_safeguards,
            "interpretation_features": self.interpretation_features,
            "override_capability": self.override_capability,
            "intervention_capability": self.intervention_capability,
        }


@dataclass
class Article9Artifact:
    """EU AI Act Article 9 — Risk Management System artifact."""

    artifact_id: str
    receipt_id: str
    generated_at: str

    # Risk identification
    risk_identification_methodology: str
    identified_risks: list[dict]  # [{risk_id, description, likelihood, severity, category}]

    # Reasonably foreseeable misuse
    foreseeable_misuse_scenarios: list[str]

    # Risk mitigation
    risk_mitigation_measures: list[dict]  # [{risk_id, measure, residual_risk_level}]

    # Residual risk assessment
    residual_risks: list[dict]
    overall_residual_risk_level: str  # "acceptable" | "conditional" | "unacceptable"

    # Monitoring plan
    post_market_monitoring_plan: str

    integrity_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "risk_identification_methodology": self.risk_identification_methodology,
            "identified_risks": self.identified_risks,
            "foreseeable_misuse_scenarios": self.foreseeable_misuse_scenarios,
            "risk_mitigation_measures": self.risk_mitigation_measures,
            "residual_risks": self.residual_risks,
            "overall_residual_risk_level": self.overall_residual_risk_level,
            "post_market_monitoring_plan": self.post_market_monitoring_plan,
            "integrity_hash": self.integrity_hash,
        }


@dataclass
class ComplianceArtifactBundle:
    """Complete EU AI Act compliance artifact bundle.

    Combines conformity report with dedicated Art. 12/13/14 artifacts
    into a single auditable package with integrity hash.
    """

    bundle_id: str
    receipt_id: str
    generated_at: str
    risk_classification: RiskClassification
    conformity_report: ConformityReport
    article_12: Article12Artifact
    article_13: Article13Artifact
    article_14: Article14Artifact
    article_9: "Article9Artifact | None" = None
    integrity_hash: str = ""

    def __post_init__(self):
        if not self.integrity_hash:
            self.integrity_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        content = json.dumps(
            {
                "bundle_id": self.bundle_id,
                "receipt_id": self.receipt_id,
                "risk_level": self.risk_classification.risk_level.value,
                "conformity_status": self.conformity_report.overall_status,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "regulation": "EU AI Act (Regulation 2024/1689)",
            "compliance_deadline": "2026-08-02",
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "risk_classification": self.risk_classification.to_dict(),
            "conformity_report": self.conformity_report.to_dict(),
            "article_9_risk_management": self.article_9.to_dict() if self.article_9 else None,
            "article_12_record_keeping": self.article_12.to_dict(),
            "article_13_transparency": self.article_13.to_dict(),
            "article_14_human_oversight": self.article_14.to_dict(),
            "integrity_hash": self.integrity_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class ComplianceArtifactGenerator:
    """Generate complete EU AI Act compliance artifact bundles.

    Produces dedicated Art. 12 (Record-Keeping), Art. 13 (Transparency),
    and Art. 14 (Human Oversight) artifacts from a decision receipt,
    bundled with a conformity assessment report.
    """

    def __init__(
        self,
        *,
        provider_name: str = "Aragora Inc.",
        provider_contact: str = "compliance@aragora.ai",
        eu_representative: str = "",
        system_name: str = "Aragora Decision Integrity Platform",
        system_version: str = "2.6.3",
    ) -> None:
        self._provider_name = provider_name
        self._provider_contact = provider_contact
        self._eu_representative = eu_representative
        self._system_name = system_name
        self._system_version = system_version
        self._report_generator = ConformityReportGenerator()

    def generate(self, receipt: dict[str, Any]) -> ComplianceArtifactBundle:
        """Generate a complete compliance artifact bundle from a receipt."""
        receipt_id = receipt.get("receipt_id", f"rcpt-{uuid.uuid4().hex[:8]}")
        timestamp = datetime.now(timezone.utc).isoformat()
        bundle_id = f"EUAIA-{uuid.uuid4().hex[:8]}"

        classification = self._report_generator._classifier.classify_receipt(receipt)
        report = self._report_generator.generate(receipt)

        return ComplianceArtifactBundle(
            bundle_id=bundle_id,
            receipt_id=receipt_id,
            generated_at=timestamp,
            risk_classification=classification,
            conformity_report=report,
            article_12=self._generate_art12(receipt, receipt_id, timestamp),
            article_13=self._generate_art13(receipt, receipt_id, timestamp, classification),
            article_14=self._generate_art14(receipt, receipt_id, timestamp),
            article_9=self._generate_art9(receipt, receipt_id, timestamp),
        )

    # -- Article 12: Record-Keeping --

    def _generate_art12(
        self,
        receipt: dict[str, Any],
        receipt_id: str,
        timestamp: str,
    ) -> Article12Artifact:
        provenance = receipt.get("provenance_chain", [])
        event_log = []
        for i, entry in enumerate(provenance):
            if isinstance(entry, dict):
                event_log.append(
                    {
                        "event_id": f"evt_{i + 1:04d}",
                        "event_type": entry.get("event_type", "unknown"),
                        "timestamp": entry.get("timestamp", ""),
                        "actor": entry.get("actor", "system"),
                    }
                )
            elif hasattr(entry, "event_type"):
                event_log.append(
                    {
                        "event_id": f"evt_{i + 1:04d}",
                        "event_type": entry.event_type,
                        "timestamp": getattr(entry, "timestamp", ""),
                        "actor": getattr(entry, "actor", "system"),
                    }
                )

        config = receipt.get("config_used", {})
        consensus = receipt.get("consensus_proof", {})
        agents = list(
            set(consensus.get("supporting_agents", []) + consensus.get("dissenting_agents", []))
        )

        input_text = receipt.get("input_summary", receipt.get("question", ""))
        input_hash = hashlib.sha256(input_text.encode()).hexdigest() if input_text else ""

        return Article12Artifact(
            receipt_id=receipt_id,
            generated_at=timestamp,
            event_log=event_log,
            reference_databases=[
                {"source": src, "type": "knowledge_base"}
                for src in receipt.get("knowledge_sources", [])
            ],
            input_record={
                "input_summary": input_text[:200],
                "input_hash": input_hash,
                "agents_participating": agents,
            },
            technical_documentation={
                "annex_iv_sec1_general": {
                    "system_name": self._system_name,
                    "version": self._system_version,
                    "provider": self._provider_name,
                    "intended_purpose": (
                        "Multi-agent adversarial vetting of decisions against "
                        "organizational knowledge, delivering audit-ready "
                        "decision receipts."
                    ),
                },
                "annex_iv_sec2_development": {
                    "architecture": "Multi-agent debate with adversarial consensus",
                    "consensus_method": consensus.get("method", "weighted_majority"),
                    "agents": agents,
                    "protocol": config.get("protocol", "adversarial"),
                    "rounds": config.get("rounds", 0),
                },
                "annex_iv_sec5_risk_management": {
                    "adversarial_debate": "Multi-agent challenge reduces single-point-of-failure",
                    "hollow_consensus_detection": "Trickster module",
                    "circuit_breakers": "Per-agent failure isolation",
                    "calibration_monitoring": "Continuous Brier score tracking",
                },
            },
            retention_policy={
                "minimum_months": 6,
                "basis": "Art. 26(6) — minimum 6 months for high-risk systems",
                "provenance_events": len(event_log),
                "integrity_mechanism": "SHA-256 hash chain",
            },
        )

    # -- Article 13: Transparency --

    def _generate_art13(
        self,
        receipt: dict[str, Any],
        receipt_id: str,
        timestamp: str,
        classification: RiskClassification,
    ) -> Article13Artifact:
        consensus = receipt.get("consensus_proof", {})
        agents = list(
            set(consensus.get("supporting_agents", []) + consensus.get("dissenting_agents", []))
        )
        confidence = receipt.get("confidence", 0.0)
        robustness = receipt.get("robustness_score", 0.0)
        dissenting = receipt.get("dissenting_views", [])

        return Article13Artifact(
            receipt_id=receipt_id,
            generated_at=timestamp,
            provider_identity={
                "name": self._provider_name,
                "contact": self._provider_contact,
                "eu_representative": self._eu_representative or "Not yet designated",
            },
            intended_purpose={
                "description": (
                    "Aragora orchestrates adversarial debate among heterogeneous "
                    "AI models to vet decisions against organizational knowledge. "
                    "It produces audit-ready decision receipts with cryptographic "
                    "integrity for regulatory compliance."
                ),
                "not_intended_for": [
                    "Fully autonomous decision-making without human oversight",
                    "Real-time biometric identification",
                    "Social scoring or behavioral manipulation",
                ],
            },
            accuracy_robustness={
                "consensus_confidence": confidence,
                "robustness_score": robustness,
                "agents_participating": len(agents),
                "consensus_method": consensus.get("method", "unknown"),
                "agreement_ratio": consensus.get("agreement_ratio", 0.0),
                "integrity_hash_present": bool(receipt.get("artifact_hash")),
                "signature_present": bool(receipt.get("signature")),
            },
            known_risks=[
                {
                    "risk": "Automation bias",
                    "description": "Over-reliance on AI recommendations",
                    "mitigation": "Mandatory human review, dissent highlighting",
                    "article_ref": "Art. 14(4)(b)",
                },
                {
                    "risk": "Hollow consensus",
                    "description": "Surface-level agreement without substantive reasoning",
                    "mitigation": "Trickster detection module, evidence grounding",
                    "article_ref": "Art. 15(4)",
                },
                {
                    "risk": "Model hallucination",
                    "description": "Plausible but incorrect claims persisting through consensus",
                    "mitigation": "Multi-agent challenge, calibration tracking",
                    "article_ref": "Art. 15(1)",
                },
            ],
            output_interpretation={
                "verdict": receipt.get("verdict", ""),
                "confidence": confidence,
                "confidence_interpretation": (
                    "High confidence — strong agreement"
                    if confidence >= 0.8
                    else "Moderate confidence — some reservations"
                    if confidence >= 0.6
                    else "Low confidence — significant disagreement"
                ),
                "dissent_count": len(dissenting),
                "dissent_significance": (
                    "No dissent — unanimous agreement."
                    if not dissenting
                    else (
                        f"{len(dissenting)} dissenting view(s) recorded. "
                        "Review dissenting reasoning before finalizing."
                    )
                ),
            },
            human_oversight_reference={
                "human_approval_detected": _detect_human_oversight(
                    receipt.get("config_used", {}), receipt
                ),
                "approval_config": {
                    k: v
                    for k, v in receipt.get("config_used", {}).items()
                    if any(
                        term in k.lower() for term in ("human", "approval", "override", "approver")
                    )
                },
            },
        )

    # -- Article 14: Human Oversight --

    def _generate_art14(
        self,
        receipt: dict[str, Any],
        receipt_id: str,
        timestamp: str,
    ) -> Article14Artifact:
        config = receipt.get("config_used", {})
        has_human = _detect_human_oversight(config, receipt)

        return Article14Artifact(
            receipt_id=receipt_id,
            generated_at=timestamp,
            oversight_model={
                "primary": "Human-in-the-Loop (HITL)" if has_human else "Human-on-the-Loop (HOTL)",
                "description": (
                    "All final decisions require explicit human approval."
                    if has_human
                    else (
                        "System operates with monitoring-based oversight. "
                        "Human intervention on anomalies."
                    )
                ),
                "human_approval_detected": has_human,
            },
            understanding_monitoring={
                "capabilities_documented": [
                    "Multi-agent adversarial debate with consensus",
                    "Tamper-evident decision receipts",
                    "Calibration tracking per agent",
                    "Dissent recording for minority opinions",
                ],
                "limitations_documented": [
                    "Consensus does not guarantee correctness",
                    "Confidence != probability of being correct",
                    "Performance varies by domain complexity",
                    "Underlying model knowledge cutoff dates apply",
                ],
                "monitoring_features": [
                    "Real-time debate spectate view",
                    "Agent performance dashboard",
                    "Calibration drift alerts",
                    "Anomaly detection",
                ],
            },
            automation_bias_safeguards={
                "warnings_present": True,
                "mechanisms": [
                    "Dissent views prominently displayed alongside verdict",
                    "Confidence scores presented with interpretation context",
                    "Periodic independent evaluation prompts",
                    "Mandatory review intervals",
                ],
            },
            interpretation_features={
                "explainability": [
                    "Factor decomposition: contributing factors with weights",
                    "Counterfactual analysis: what-if scenarios",
                    "Evidence chain: claims linked to sources",
                    "Vote pivot: which arguments changed outcomes",
                ],
            },
            override_capability={
                "override_available": True,
                "mechanisms": [
                    {
                        "action": "Reject verdict",
                        "description": "Deployer rejects AI consensus and decides independently",
                        "audit_logged": True,
                    },
                    {
                        "action": "Override with reason",
                        "description": "Deployer overrides with documented rationale",
                        "audit_logged": True,
                    },
                    {
                        "action": "Reverse prior decision",
                        "description": "Previously accepted decisions can be reversed",
                        "audit_logged": True,
                    },
                ],
            },
            intervention_capability={
                "stop_available": True,
                "mechanisms": [
                    {
                        "action": "Stop debate",
                        "description": "Halts debate mid-round, partial results preserved",
                        "safe_state": True,
                    },
                    {
                        "action": "Cancel decision",
                        "description": "Cancels in-progress decision, no downstream actions",
                        "safe_state": True,
                    },
                ],
            },
        )

    # -- Article 9: Risk Management System --

    def _generate_art9(
        self,
        receipt: dict[str, Any],
        receipt_id: str,
        timestamp: str,
    ) -> Article9Artifact:
        """Generate Article 9 (Risk Management System) artifact."""
        artifact_id = f"ART9-{uuid.uuid4().hex[:8]}"

        risk_summary = receipt.get("risk_summary", {})
        dissenting = receipt.get("dissenting_agents", [])
        confidence = receipt.get("confidence", 0.0)

        # Build identified risks from the receipt's risk summary
        identified_risks = []
        for severity, count in risk_summary.items():
            if count > 0:
                identified_risks.append(
                    {
                        "risk_id": f"RISK-{severity.upper()}-001",
                        "description": f"{count} {severity}-severity risk(s) identified during debate",
                        "likelihood": "medium" if severity in ("high", "critical") else "low",
                        "severity": severity,
                        "category": "operational",
                    }
                )

        # Foreseeable misuse based on topic
        foreseeable_misuse = [
            "Use for irreversible decisions without human review",
            "Applying verdict to out-of-scope domains",
            "Treating low-confidence verdicts as definitive",
        ]
        if dissenting:
            foreseeable_misuse.append(f"Ignoring minority dissent from: {', '.join(dissenting)}")

        # Mitigation measures
        mitigations = [
            {
                "risk_id": "RISK-HALLUCINATION",
                "measure": "Multi-agent adversarial debate with dissent capture",
                "residual_risk_level": "low",
            },
            {
                "risk_id": "RISK-BIAS",
                "measure": "Heterogeneous model ensemble (different providers and RLHF targets)",
                "residual_risk_level": "low",
            },
            {
                "risk_id": "RISK-SYCOPHANCY",
                "measure": "Trickster hollow-consensus detection + RhetoricalObserver",
                "residual_risk_level": "low",
            },
        ]

        # Residual risk level
        critical_count = risk_summary.get("critical", 0)
        high_count = risk_summary.get("high", 0)
        if critical_count > 0:
            residual_level = "unacceptable"
        elif high_count > 2 or confidence < 0.5:
            residual_level = "conditional"
        else:
            residual_level = "acceptable"

        residual_risks = [
            {
                "description": "Correlated model failures on shared blind spots",
                "likelihood": "low",
                "severity": "medium",
                "accepted": True,
                "rationale": "Heterogeneous ensemble reduces but does not eliminate shared failures",
            }
        ]

        integrity_input = f"{artifact_id}:{receipt_id}:{residual_level}"
        integrity_hash = hashlib.sha256(integrity_input.encode()).hexdigest()

        return Article9Artifact(
            artifact_id=artifact_id,
            receipt_id=receipt_id,
            generated_at=timestamp,
            risk_identification_methodology=(
                "Multi-agent adversarial debate with structured critique phases. "
                "Risk identification emerges from agent disagreement, dissent, and "
                "confidence calibration across heterogeneous model ensemble."
            ),
            identified_risks=identified_risks,
            foreseeable_misuse_scenarios=foreseeable_misuse,
            risk_mitigation_measures=mitigations,
            residual_risks=residual_risks,
            overall_residual_risk_level=residual_level,
            post_market_monitoring_plan=(
                "Periodic re-evaluation via SettlementTracker (automated data checks: days, "
                "human review panels: months, market resolution: years). ELO calibration "
                "tracks model performance over time. Brier scores updated after settlement."
            ),
            integrity_hash=integrity_hash,
        )


# ---------------------------------------------------------------------------
# Bundle generator with SQLite-backed storage
# ---------------------------------------------------------------------------

import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = os.path.join(os.path.expanduser("~"), ".aragora")


class EUAIActBundleGenerator:
    """Generate and persist EU AI Act compliance artifact bundles.

    Wraps ``ComplianceArtifactGenerator`` with SQLite storage so bundles
    can be created via a POST endpoint and retrieved later via GET.

    Each bundle is stored as a JSON blob keyed by ``bundle_id``.
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        provider_name: str = "Aragora Inc.",
        provider_contact: str = "compliance@aragora.ai",
        eu_representative: str = "",
        system_name: str = "Aragora Decision Integrity Platform",
        system_version: str = "2.6.3",
    ) -> None:
        if db_path is None:
            os.makedirs(_DEFAULT_DB_DIR, exist_ok=True)
            db_path = os.path.join(_DEFAULT_DB_DIR, "eu_ai_act_bundles.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._generator = ComplianceArtifactGenerator(
            provider_name=provider_name,
            provider_contact=provider_contact,
            eu_representative=eu_representative,
            system_name=system_name,
            system_version=system_version,
        )
        self._ensure_table()

    # -- DB helpers --

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS eu_ai_act_bundles (
                        bundle_id TEXT PRIMARY KEY,
                        receipt_id TEXT,
                        status TEXT DEFAULT 'complete',
                        articles_json TEXT NOT NULL,
                        generated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    # -- Public API --

    def generate(
        self,
        receipt: dict[str, Any],
        *,
        scope: str | None = None,
        articles: list[int] | None = None,
    ) -> dict[str, Any]:
        """Generate a compliance artifact bundle and persist it.

        Args:
            receipt: Decision receipt dict (may be empty for demo bundles).
            scope: Optional human-readable scope description.
            articles: Limit to specific articles (12, 13, 14). None means all.

        Returns:
            Dict with ``bundle_id``, ``articles``, ``generated_at``, and
            ``status``.
        """
        bundle = self._generator.generate(receipt)
        bundle_dict = bundle.to_dict()

        # Filter articles if requested
        article_data: dict[str, Any] = {}
        article_map = {
            12: "article_12_record_keeping",
            13: "article_13_transparency",
            14: "article_14_human_oversight",
        }
        target_articles = articles or [12, 13, 14]
        for art_num in target_articles:
            key = article_map.get(art_num)
            if key and key in bundle_dict:
                article_data[key] = bundle_dict[key]

        # Always include conformity report and risk classification
        article_data["risk_classification"] = bundle_dict.get("risk_classification", {})
        article_data["conformity_report"] = bundle_dict.get("conformity_report", {})
        article_data["integrity_hash"] = bundle_dict.get("integrity_hash", "")

        if scope:
            article_data["scope"] = scope

        result = {
            "bundle_id": bundle.bundle_id,
            "articles": article_data,
            "generated_at": bundle.generated_at,
            "status": "complete",
        }

        # Persist
        self._store(result)

        return result

    def get(self, bundle_id: str) -> dict[str, Any] | None:
        """Retrieve a previously generated bundle by ID.

        Returns:
            Bundle dict or None if not found.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT bundle_id, articles_json, status, generated_at "
                    "FROM eu_ai_act_bundles WHERE bundle_id = ?",
                    (bundle_id,),
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return None

        return {
            "bundle_id": row[0],
            "articles": json.loads(row[1]),
            "status": row[2],
            "generated_at": row[3],
        }

    def _store(self, result: dict[str, Any]) -> None:
        """Persist a bundle result to SQLite."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO eu_ai_act_bundles "
                    "(bundle_id, receipt_id, status, articles_json, generated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        result["bundle_id"],
                        result["articles"].get("conformity_report", {}).get("receipt_id", ""),
                        result.get("status", "complete"),
                        json.dumps(result["articles"], default=str),
                        result["generated_at"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()


__all__ = [
    "RiskLevel",
    "RiskClassification",
    "RiskClassifier",
    "ANNEX_III_CATEGORIES",
    "ArticleMapping",
    "ConformityReport",
    "ConformityReportGenerator",
    "Article12Artifact",
    "Article13Artifact",
    "Article14Artifact",
    "ComplianceArtifactBundle",
    "ComplianceArtifactGenerator",
    "EUAIActBundleGenerator",
]
