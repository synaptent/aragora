"""
Vertical Persona Framework for Enterprise Multi-Agent Control Plane.

Provides domain-specific persona management for industry verticals:
- Software: Code review, security, architecture
- Legal: Contract analysis, compliance, litigation
- Healthcare: Clinical review, HIPAA, research
- Accounting: Financial audit, tax, forensics

Each vertical has:
- Recommended personas for different task types
- Compliance frameworks that apply
- Model preferences based on task complexity

Usage:
    from aragora.agents.vertical_personas import (
        Vertical,
        VerticalPersonaManager,
        get_vertical_personas,
    )

    # Get personas for a vertical
    manager = VerticalPersonaManager()
    personas = manager.get_personas_for_vertical(Vertical.LEGAL)

    # Get recommended team for a task
    team = manager.recommend_team(
        vertical=Vertical.LEGAL,
        task_type="contract_review",
        complexity="high",
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aragora.agents.personas import (
    DEFAULT_PERSONAS,
    EXPERTISE_DOMAINS,
    Persona,
    PersonaManager,
)


class Vertical(Enum):
    """Industry verticals supported by the control plane."""

    SOFTWARE = "software"
    LEGAL = "legal"
    HEALTHCARE = "healthcare"
    ACCOUNTING = "accounting"
    ACADEMIC = "academic"
    GENERAL = "general"


class TaskComplexity(Enum):
    """Complexity levels for task-based model selection."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class VerticalConfig:
    """Configuration for an industry vertical."""

    vertical: Vertical
    description: str
    primary_personas: list[str]  # Persona names
    compliance_frameworks: list[str]  # Framework IDs
    preferred_models: dict[TaskComplexity, list[str]]  # Complexity -> models
    expertise_domains: list[str]  # Relevant expertise domains
    typical_tasks: list[str]  # Common task types

    # Model preferences
    default_model: str = "claude"
    requires_high_accuracy: bool = False
    max_temperature: float = 0.7


# Vertical configurations
VERTICAL_CONFIGS: dict[Vertical, VerticalConfig] = {
    Vertical.SOFTWARE: VerticalConfig(
        vertical=Vertical.SOFTWARE,
        description="Software development, code review, and architecture analysis",
        primary_personas=[
            "code_security_specialist",
            "architecture_reviewer",
            "code_quality_reviewer",
            "api_design_reviewer",
            "performance_engineer",
            "devops_engineer",
            "data_architect",
        ],
        compliance_frameworks=[
            "owasp",
            "soc2",
            "iso_27001",
            "pci_dss",
        ],
        preferred_models={
            TaskComplexity.LOW: ["claude", "gpt4", "deepseek"],
            TaskComplexity.MEDIUM: ["claude", "gpt4"],
            TaskComplexity.HIGH: ["claude", "gpt4"],
            TaskComplexity.CRITICAL: ["claude", "gpt4"],
        },
        expertise_domains=[
            "security",
            "performance",
            "architecture",
            "testing",
            "api_design",
            "database",
            "concurrency",
            "devops",
        ],
        typical_tasks=[
            "code_review",
            "security_audit",
            "architecture_review",
            "performance_analysis",
            "api_design",
            "refactoring",
        ],
        default_model="claude",
        requires_high_accuracy=True,
        max_temperature=0.6,
    ),
    Vertical.LEGAL: VerticalConfig(
        vertical=Vertical.LEGAL,
        description="Legal analysis, contract review, and compliance assessment",
        primary_personas=[
            "contract_analyst",
            "compliance_officer",
            "litigation_support",
            "m_and_a_counsel",
            "gdpr",
            "sox",
        ],
        compliance_frameworks=[
            "aba_ethics",
            "gdpr",
            "ccpa",
            "sox",
            "finra",
        ],
        preferred_models={
            TaskComplexity.LOW: ["claude", "gpt4"],
            TaskComplexity.MEDIUM: ["claude", "gpt4"],
            TaskComplexity.HIGH: ["claude"],  # Higher accuracy needed
            TaskComplexity.CRITICAL: ["claude"],
        },
        expertise_domains=[
            "legal",
            "data_privacy",
            "sox_compliance",
            "gdpr",
            "audit_trails",
            "documentation",
        ],
        typical_tasks=[
            "contract_review",
            "compliance_assessment",
            "risk_analysis",
            "due_diligence",
            "policy_review",
            "litigation_support",
        ],
        default_model="claude",
        requires_high_accuracy=True,
        max_temperature=0.4,
    ),
    Vertical.HEALTHCARE: VerticalConfig(
        vertical=Vertical.HEALTHCARE,
        description="Clinical documentation, HIPAA compliance, and medical research",
        primary_personas=[
            "clinical_reviewer",
            "hipaa_auditor",
            "research_analyst_clinical",
            "medical_coder",
            "hipaa",
            "fda_21_cfr",
        ],
        compliance_frameworks=[
            "hipaa",
            "fda_21_cfr",
            "hitrust",
            "gdpr",
        ],
        preferred_models={
            TaskComplexity.LOW: ["claude", "gpt4"],
            TaskComplexity.MEDIUM: ["claude"],
            TaskComplexity.HIGH: ["claude"],  # Patient safety critical
            TaskComplexity.CRITICAL: ["claude"],
        },
        expertise_domains=[
            "hipaa",
            "fda_21_cfr",
            "data_privacy",
            "documentation",
            "clinical",
            "audit_trails",
        ],
        typical_tasks=[
            "clinical_review",
            "hipaa_audit",
            "protocol_review",
            "coding_review",
            "research_analysis",
            "consent_review",
        ],
        default_model="claude",
        requires_high_accuracy=True,
        max_temperature=0.4,
    ),
    Vertical.ACCOUNTING: VerticalConfig(
        vertical=Vertical.ACCOUNTING,
        description="Financial audit, tax compliance, and forensic accounting",
        primary_personas=[
            "financial_auditor",
            "tax_specialist",
            "forensic_accountant",
            "internal_auditor",
            "sox",
            "finra",
        ],
        compliance_frameworks=[
            "sox",
            "gaap",
            "ifrs",
            "finra",
            "sec",
        ],
        preferred_models={
            TaskComplexity.LOW: ["claude", "gpt4"],
            TaskComplexity.MEDIUM: ["claude", "gpt4"],
            TaskComplexity.HIGH: ["claude"],
            TaskComplexity.CRITICAL: ["claude"],
        },
        expertise_domains=[
            "sox_compliance",
            "finra",
            "audit_trails",
            "financial",
            "database",
            "access_control",
        ],
        typical_tasks=[
            "financial_audit",
            "sox_compliance",
            "tax_review",
            "fraud_investigation",
            "internal_audit",
            "control_assessment",
        ],
        default_model="claude",
        requires_high_accuracy=True,
        max_temperature=0.4,
    ),
    Vertical.ACADEMIC: VerticalConfig(
        vertical=Vertical.ACADEMIC,
        description="Academic research, peer review, and grant analysis",
        primary_personas=[
            "research_methodologist",
            "peer_reviewer",
            "grant_reviewer",
            "irb_reviewer",
        ],
        compliance_frameworks=[
            "irb",
            "hipaa",
            "fda_21_cfr",
        ],
        preferred_models={
            TaskComplexity.LOW: ["claude", "gpt4", "gemini"],
            TaskComplexity.MEDIUM: ["claude", "gpt4"],
            TaskComplexity.HIGH: ["claude", "gpt4"],
            TaskComplexity.CRITICAL: ["claude"],
        },
        expertise_domains=[
            "testing",
            "documentation",
            "ethics",
            "psychology",
            "philosophy",
        ],
        typical_tasks=[
            "peer_review",
            "methodology_review",
            "grant_review",
            "irb_review",
            "literature_analysis",
        ],
        default_model="claude",
        requires_high_accuracy=False,
        max_temperature=0.6,
    ),
    Vertical.GENERAL: VerticalConfig(
        vertical=Vertical.GENERAL,
        description="General-purpose analysis and multi-domain tasks",
        primary_personas=[
            "claude",
            "gpt4",
            "gemini",
            "synthesizer",
        ],
        compliance_frameworks=[],
        preferred_models={
            TaskComplexity.LOW: ["claude", "gpt4", "gemini", "deepseek"],
            TaskComplexity.MEDIUM: ["claude", "gpt4", "gemini"],
            TaskComplexity.HIGH: ["claude", "gpt4"],
            TaskComplexity.CRITICAL: ["claude"],
        },
        expertise_domains=EXPERTISE_DOMAINS[:12],  # Technical domains
        typical_tasks=[
            "analysis",
            "research",
            "writing",
            "summarization",
            "brainstorming",
        ],
        default_model="claude",
        requires_high_accuracy=False,
        max_temperature=0.7,
    ),
}


@dataclass
class VerticalTeamRecommendation:
    """Recommended team configuration for a vertical task."""

    vertical: Vertical
    task_type: str
    complexity: TaskComplexity
    personas: list[str]
    models: list[str]
    compliance_frameworks: list[str]
    max_temperature: float
    estimated_cost_tier: str  # "low", "medium", "high"
    reasoning: str


class VerticalPersonaManager:
    """
    Manages personas for industry verticals.

    Provides:
    - Vertical-specific persona recommendations
    - Team composition for different task types
    - Compliance framework mapping
    - Model selection based on vertical and complexity
    """

    def __init__(self, persona_manager: PersonaManager | None = None):
        self._persona_manager = persona_manager
        self._vertical_configs = VERTICAL_CONFIGS

    def get_vertical_config(self, vertical: Vertical) -> VerticalConfig:
        """Get configuration for a vertical."""
        return self._vertical_configs.get(vertical, self._vertical_configs[Vertical.GENERAL])

    def get_personas_for_vertical(self, vertical: Vertical) -> list[Persona]:
        """
        Get all personas suitable for a vertical.

        Returns both vertical-specific and general personas.
        """
        config = self.get_vertical_config(vertical)
        personas = []

        for persona_name in config.primary_personas:
            if persona_name in DEFAULT_PERSONAS:
                personas.append(DEFAULT_PERSONAS[persona_name])

        return personas

    def get_persona_by_expertise(
        self,
        vertical: Vertical,
        expertise_domain: str,
        min_score: float = 0.5,
    ) -> list[Persona]:
        """
        Get personas with specific expertise in a vertical.

        Args:
            vertical: Industry vertical
            expertise_domain: Domain to search for (e.g., "security")
            min_score: Minimum expertise score (0.0-1.0)

        Returns:
            Personas with matching expertise, sorted by score
        """
        config = self.get_vertical_config(vertical)
        matching = []

        for persona_name in config.primary_personas:
            if persona_name in DEFAULT_PERSONAS:
                persona = DEFAULT_PERSONAS[persona_name]
                score = persona.expertise.get(expertise_domain, 0.0)
                if score >= min_score:
                    matching.append((persona, score))

        # Sort by expertise score descending
        matching.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in matching]

    def recommend_team(
        self,
        vertical: Vertical,
        task_type: str,
        complexity: TaskComplexity = TaskComplexity.MEDIUM,
        team_size: int = 3,
        include_compliance: bool = True,
    ) -> VerticalTeamRecommendation:
        """
        Recommend a team of personas for a specific task.

        Args:
            vertical: Industry vertical
            task_type: Type of task (e.g., "contract_review")
            complexity: Task complexity level
            team_size: Desired team size
            include_compliance: Whether to include compliance specialists

        Returns:
            VerticalTeamRecommendation with personas, models, and frameworks
        """
        config = self.get_vertical_config(vertical)

        # Select personas based on task type
        selected_personas = self._select_personas_for_task(
            config, task_type, team_size, include_compliance
        )

        # Get recommended models for complexity
        models = config.preferred_models.get(complexity, [config.default_model])

        # Get applicable compliance frameworks
        frameworks = config.compliance_frameworks if include_compliance else []

        # Determine cost tier
        cost_tier = self._estimate_cost_tier(complexity, len(selected_personas))

        # Generate reasoning
        reasoning = self._generate_recommendation_reasoning(
            vertical, task_type, complexity, selected_personas, models
        )

        return VerticalTeamRecommendation(
            vertical=vertical,
            task_type=task_type,
            complexity=complexity,
            personas=selected_personas,
            models=models[:team_size],  # Match team size
            compliance_frameworks=frameworks,
            max_temperature=config.max_temperature,
            estimated_cost_tier=cost_tier,
            reasoning=reasoning,
        )

    def _select_personas_for_task(
        self,
        config: VerticalConfig,
        task_type: str,
        team_size: int,
        include_compliance: bool,
    ) -> list[str]:
        """Select personas for a specific task."""
        selected = []

        # Task-specific mappings
        task_persona_map = {
            # Software
            "code_review": ["code_quality_reviewer", "code_security_specialist"],
            "security_audit": ["code_security_specialist", "security_engineer"],
            "architecture_review": ["architecture_reviewer", "api_design_reviewer"],
            "performance_analysis": ["performance_engineer", "data_architect"],
            # Legal
            "contract_review": ["contract_analyst", "compliance_officer"],
            "compliance_assessment": ["compliance_officer", "sox", "gdpr"],
            "due_diligence": ["m_and_a_counsel", "contract_analyst"],
            "litigation_support": ["litigation_support", "forensic_accountant"],
            # Healthcare
            "clinical_review": ["clinical_reviewer", "hipaa_auditor"],
            "hipaa_audit": ["hipaa_auditor", "hipaa"],
            "protocol_review": ["clinical_reviewer", "irb_reviewer"],
            # Accounting
            "financial_audit": ["financial_auditor", "internal_auditor"],
            "sox_compliance": ["sox", "internal_auditor"],
            "tax_review": ["tax_specialist", "financial_auditor"],
            "fraud_investigation": ["forensic_accountant", "internal_auditor"],
            # Academic
            "peer_review": ["peer_reviewer", "research_methodologist"],
            "grant_review": ["grant_reviewer", "research_methodologist"],
        }

        # Get task-specific personas
        task_personas = task_persona_map.get(task_type, [])
        for persona_name in task_personas:
            if persona_name in config.primary_personas or persona_name in DEFAULT_PERSONAS:
                selected.append(persona_name)

        # Fill remaining slots from vertical's primary personas
        for persona_name in config.primary_personas:
            if persona_name not in selected and len(selected) < team_size:
                selected.append(persona_name)

        # Add compliance specialist if needed
        if include_compliance and len(selected) < team_size:
            compliance_personas = ["compliance_officer", "sox", "hipaa", "gdpr"]
            for cp in compliance_personas:
                if cp in DEFAULT_PERSONAS and cp not in selected:
                    selected.append(cp)
                    break

        return selected[:team_size]

    def _estimate_cost_tier(self, complexity: TaskComplexity, team_size: int) -> str:
        """Estimate cost tier based on complexity and team size."""
        if complexity == TaskComplexity.LOW and team_size <= 2:
            return "low"
        elif complexity in (TaskComplexity.LOW, TaskComplexity.MEDIUM) and team_size <= 3:
            return "medium"
        else:
            return "high"

    def _generate_recommendation_reasoning(
        self,
        vertical: Vertical,
        task_type: str,
        complexity: TaskComplexity,
        personas: list[str],
        models: list[str],
    ) -> str:
        """Generate human-readable reasoning for recommendation."""
        return (
            f"For {vertical.value} {task_type} with {complexity.value} complexity: "
            f"Selected {len(personas)} specialists ({', '.join(personas[:3])}) "
            f"using {models[0]} for primary processing. "
            f"This configuration balances expertise coverage with cost efficiency."
        )

    def get_compliance_frameworks(self, vertical: Vertical) -> list[str]:
        """Get compliance frameworks applicable to a vertical."""
        config = self.get_vertical_config(vertical)
        return config.compliance_frameworks

    def get_typical_tasks(self, vertical: Vertical) -> list[str]:
        """Get typical tasks for a vertical."""
        config = self.get_vertical_config(vertical)
        return config.typical_tasks

    def detect_vertical_from_task(self, task_description: str) -> Vertical:
        """
        Detect the most appropriate vertical based on task description.

        Uses keyword matching to identify the vertical.
        """
        task_lower = task_description.lower()

        # Vertical detection keywords
        vertical_keywords = {
            Vertical.SOFTWARE: [
                "code",
                "api",
                "security",
                "architecture",
                "performance",
                "database",
                "software",
                "programming",
                "bug",
                "refactor",
            ],
            Vertical.LEGAL: [
                "contract",
                "legal",
                "compliance",
                "litigation",
                "clause",
                "agreement",
                "liability",
                "indemnification",
                "counsel",
            ],
            Vertical.HEALTHCARE: [
                "clinical",
                "medical",
                "patient",
                "hipaa",
                "health",
                "diagnosis",
                "treatment",
                "phi",
                "protocol",
                "fda",
            ],
            Vertical.ACCOUNTING: [
                "audit",
                "financial",
                "tax",
                "sox",
                "accounting",
                "fraud",
                "reconciliation",
                "gaap",
                "ifrs",
                "revenue",
            ],
            Vertical.ACADEMIC: [
                "research",
                "study",
                "peer review",
                "methodology",
                "academic",
                "grant",
                "publication",
                "irb",
                "hypothesis",
            ],
        }

        scores = dict.fromkeys(Vertical, 0)
        for vertical, keywords in vertical_keywords.items():
            for keyword in keywords:
                if keyword in task_lower:
                    scores[vertical] += 1

        # Return highest scoring vertical (or GENERAL if no matches)
        max_score = max(scores.values())
        if max_score == 0:
            return Vertical.GENERAL

        for vertical, score in scores.items():
            if score == max_score:
                return vertical

        return Vertical.GENERAL


def get_vertical_personas(vertical: Vertical) -> list[Persona]:
    """
    Convenience function to get personas for a vertical.

    Args:
        vertical: Industry vertical

    Returns:
        List of Persona instances for the vertical
    """
    manager = VerticalPersonaManager()
    return manager.get_personas_for_vertical(vertical)


__all__ = [
    "Vertical",
    "TaskComplexity",
    "VerticalConfig",
    "VerticalTeamRecommendation",
    "VerticalPersonaManager",
    "VERTICAL_CONFIGS",
    "get_vertical_personas",
]
