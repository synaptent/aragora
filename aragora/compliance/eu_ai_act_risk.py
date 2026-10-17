"""EU AI Act risk classification (Article 5 prohibitions, Article 6 and Annex III).

Public names stay importable from :mod:`aragora.compliance.eu_ai_act`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
