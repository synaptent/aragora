"""
Domain-Specific Debate Templates.

Pre-built debate structures for high-value use cases:
- Code Review
- RFC/Design Doc Review
- Incident Response
- Research Synthesis
- Policy Review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from aragora.protocols.debate import DebateProtocol


class TemplateType(Enum):
    """Types of debate templates."""

    CODE_REVIEW = "code_review"
    DESIGN_DOC = "design_doc"
    INCIDENT_RESPONSE = "incident_response"
    RESEARCH_SYNTHESIS = "research_synthesis"
    POLICY_REVIEW = "policy_review"
    SECURITY_AUDIT = "security_audit"
    ARCHITECTURE_REVIEW = "architecture_review"
    PRODUCT_STRATEGY = "product_strategy"
    HEALTHCARE_COMPLIANCE = "healthcare_compliance"
    FINANCIAL_RISK = "financial_risk"


# NEW: Define the evidence policy types
EvidencePolicy = Literal["allow-any", "allow-cited", "disallow-external"]


@dataclass
class DebateRole:
    """A role in a debate template."""

    name: str
    description: str
    objectives: list[str]
    evaluation_criteria: list[str]
    example_prompts: list[str] = field(default_factory=list)


@dataclass
class DebatePhase:
    """A phase in a structured debate."""

    name: str
    description: str
    duration_rounds: int
    roles_active: list[str]
    objectives: list[str]
    outputs: list[str]


@dataclass
class DebateTemplate:
    """A complete debate template."""

    template_id: str
    template_type: TemplateType
    name: str
    description: str

    # Structure
    roles: list[DebateRole]
    phases: list[DebatePhase]

    # Configuration
    recommended_agents: int
    max_rounds: int
    consensus_threshold: float

    # Evaluation
    rubric: dict[str, float]  # Criteria -> weight
    output_format: str  # Markdown template for output

    # Metadata
    domain: str

    # New fields with defaults
    topic_prompt: str = ""
    evidence_policy: EvidencePolicy = "allow-cited"
    difficulty: float = 0.5
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate template fields after initialization."""
        # This post_init can be used for template-level validation.
        # Runtime validation of topic_prompt should happen at the orchestration layer.
        pass


# ============================================================================
# Code Review Template
# ============================================================================

CODE_REVIEW_TEMPLATE = DebateTemplate(
    template_id="code-review-v1",
    template_type=TemplateType.CODE_REVIEW,
    name="Multi-Agent Code Review",
    description="Structured code review with security, performance, and maintainability critics",
    roles=[
        DebateRole(
            name="author",
            description="Presents and defends the code",
            objectives=["Explain design decisions", "Address concerns", "Accept valid feedback"],
            evaluation_criteria=["Responsiveness", "Openness to feedback"],
            example_prompts=[
                "This implementation uses X because...",
                "I chose this approach to optimize for...",
            ],
        ),
        DebateRole(
            name="security_critic",
            description="Reviews for security vulnerabilities",
            objectives=["Find injection risks", "Check auth/authz", "Identify data exposure"],
            evaluation_criteria=["OWASP coverage", "Severity accuracy"],
            example_prompts=[
                "This input is not sanitized, allowing SQL injection via...",
                "The authentication check can be bypassed by...",
            ],
        ),
        DebateRole(
            name="performance_critic",
            description="Reviews for performance issues",
            objectives=["Find N+1 queries", "Identify bottlenecks", "Check resource usage"],
            evaluation_criteria=["Impact accuracy", "Scalability awareness"],
            example_prompts=[
                "This loop has O(n²) complexity because...",
                "This query will cause N+1 issues when...",
            ],
        ),
        DebateRole(
            name="maintainability_critic",
            description="Reviews for code quality and maintainability",
            objectives=["Check readability", "Identify code smells", "Suggest refactoring"],
            evaluation_criteria=["Actionable suggestions", "Balance of concerns"],
            example_prompts=[
                "This function does too many things. Consider splitting...",
                "The naming convention is inconsistent with...",
            ],
        ),
        DebateRole(
            name="synthesizer",
            description="Synthesizes feedback into actionable review",
            objectives=["Prioritize issues", "Resolve conflicts", "Create action items"],
            evaluation_criteria=["Clarity", "Prioritization"],
            example_prompts=[
                "The critical issues are: 1) Security: X, 2) Performance: Y",
                "Recommended changes in order of priority...",
            ],
        ),
    ],
    phases=[
        DebatePhase(
            name="initial_review",
            description="Each critic reviews independently",
            duration_rounds=1,
            roles_active=["security_critic", "performance_critic", "maintainability_critic"],
            objectives=["Identify issues in respective domains"],
            outputs=["Issue list per domain"],
        ),
        DebatePhase(
            name="author_response",
            description="Author responds to critiques",
            duration_rounds=1,
            roles_active=["author"],
            objectives=["Address concerns", "Explain decisions", "Accept valid points"],
            outputs=["Response to each critique"],
        ),
        DebatePhase(
            name="debate",
            description="Critics and author discuss unresolved issues",
            duration_rounds=2,
            roles_active=[
                "author",
                "security_critic",
                "performance_critic",
                "maintainability_critic",
            ],
            objectives=["Resolve disagreements", "Prioritize issues"],
            outputs=["Consensus on critical issues"],
        ),
        DebatePhase(
            name="synthesis",
            description="Create final review document",
            duration_rounds=1,
            roles_active=["synthesizer"],
            objectives=["Summarize findings", "Create action items"],
            outputs=["Final review with risk score"],
        ),
    ],
    recommended_agents=4,
    max_rounds=5,
    consensus_threshold=0.7,
    rubric={
        "security_coverage": 0.3,
        "performance_impact": 0.2,
        "maintainability": 0.2,
        "actionability": 0.2,
        "consensus": 0.1,
    },
    output_format="""
# Code Review Summary

## Risk Score: {risk_score}/10

## Critical Issues
{critical_issues}

## Security ({security_score})
{security_findings}

## Performance ({performance_score})
{performance_findings}

## Maintainability ({maintainability_score})
{maintainability_findings}

## Action Items
{action_items}

## Consensus Notes
{consensus_notes}
""",
    domain="software_engineering",
    difficulty=0.6,
    tags=["code", "review", "security", "performance"],
)

# ============================================================================
# Design Doc / RFC Template
# ============================================================================

DESIGN_DOC_TEMPLATE = DebateTemplate(
    template_id="design-doc-v1",
    template_type=TemplateType.DESIGN_DOC,
    name="RFC/Design Doc Review",
    description="Structured review for technical design documents and RFCs",
    roles=[
        DebateRole(
            name="author",
            description="Presents the design",
            objectives=["Explain architecture", "Justify tradeoffs", "Address concerns"],
            evaluation_criteria=["Clarity", "Completeness"],
        ),
        DebateRole(
            name="devils_advocate",
            description="Challenges assumptions and proposes alternatives",
            objectives=[
                "Find unstated assumptions",
                "Propose alternatives",
                "Stress-test scalability",
            ],
            evaluation_criteria=["Quality of alternatives", "Assumption coverage"],
        ),
        DebateRole(
            name="stakeholder",
            description="Represents user/business requirements",
            objectives=["Ensure requirements met", "Identify gaps", "Validate priorities"],
            evaluation_criteria=["Requirements coverage", "Priority alignment"],
        ),
        DebateRole(
            name="implementer",
            description="Evaluates implementation feasibility",
            objectives=["Assess complexity", "Identify blockers", "Estimate effort"],
            evaluation_criteria=["Realism", "Risk identification"],
        ),
    ],
    phases=[
        DebatePhase(
            name="presentation",
            description="Author presents the design",
            duration_rounds=1,
            roles_active=["author"],
            objectives=["Present problem and solution"],
            outputs=["Design overview"],
        ),
        DebatePhase(
            name="critique",
            description="Each role critiques from their perspective",
            duration_rounds=1,
            roles_active=["devils_advocate", "stakeholder", "implementer"],
            objectives=["Identify concerns"],
            outputs=["Critique list"],
        ),
        DebatePhase(
            name="debate",
            description="Resolve disagreements through structured debate",
            duration_rounds=3,
            roles_active=["author", "devils_advocate", "stakeholder", "implementer"],
            objectives=["Reach consensus on key decisions"],
            outputs=["Decision record"],
        ),
    ],
    recommended_agents=4,
    max_rounds=5,
    consensus_threshold=0.6,
    rubric={
        "technical_soundness": 0.25,
        "requirement_coverage": 0.25,
        "feasibility": 0.2,
        "risk_assessment": 0.15,
        "alternatives_considered": 0.15,
    },
    output_format="""
# Design Review: {title}

## Decision: {decision} (Confidence: {confidence})

## Summary
{summary}

## Key Decisions
{decisions}

## Risks & Mitigations
{risks}

## Open Questions
{questions}

## Next Steps
{next_steps}
""",
    domain="architecture",
    difficulty=0.7,
    tags=["design", "rfc", "architecture", "review"],
)

# ============================================================================
# Incident Response Template
# ============================================================================

INCIDENT_RESPONSE_TEMPLATE = DebateTemplate(
    template_id="incident-response-v1",
    template_type=TemplateType.INCIDENT_RESPONSE,
    name="Incident Response Analysis",
    description="Structured post-incident analysis and remediation planning",
    roles=[
        DebateRole(
            name="investigator",
            description="Leads root cause analysis",
            objectives=["Establish timeline", "Identify root cause", "Document evidence"],
            evaluation_criteria=["Thoroughness", "Evidence quality"],
        ),
        DebateRole(
            name="responder",
            description="Evaluates response effectiveness",
            objectives=["Assess response time", "Identify gaps", "Evaluate communication"],
            evaluation_criteria=["Response analysis", "Gap identification"],
        ),
        DebateRole(
            name="prevention",
            description="Proposes preventive measures",
            objectives=["Suggest monitoring", "Propose safeguards", "Recommend processes"],
            evaluation_criteria=["Actionability", "Coverage"],
        ),
        DebateRole(
            name="challenger",
            description="Challenges proposed solutions",
            objectives=["Find gaps in solutions", "Stress-test proposals", "Consider edge cases"],
            evaluation_criteria=["Critical thinking", "Scenario coverage"],
        ),
    ],
    phases=[
        DebatePhase(
            name="timeline",
            description="Establish incident timeline",
            duration_rounds=1,
            roles_active=["investigator"],
            objectives=["Document what happened when"],
            outputs=["Timeline"],
        ),
        DebatePhase(
            name="root_cause",
            description="Debate root cause",
            duration_rounds=2,
            roles_active=["investigator", "responder", "challenger"],
            objectives=["Agree on root cause(s)"],
            outputs=["Root cause analysis"],
        ),
        DebatePhase(
            name="remediation",
            description="Plan remediation",
            duration_rounds=2,
            roles_active=["prevention", "challenger", "responder"],
            objectives=["Agree on action items"],
            outputs=["Remediation plan"],
        ),
    ],
    recommended_agents=4,
    max_rounds=5,
    consensus_threshold=0.7,
    rubric={
        "root_cause_accuracy": 0.3,
        "timeline_completeness": 0.2,
        "remediation_quality": 0.3,
        "prevention_coverage": 0.2,
    },
    output_format="""
# Incident Post-Mortem: {incident_id}

## Severity: {severity}
## Duration: {duration}
## Impact: {impact}

## Timeline
{timeline}

## Root Cause
{root_cause}

## What Went Well
{went_well}

## What Went Poorly
{went_poorly}

## Action Items
{action_items}

## Prevention Measures
{prevention}
""",
    domain="operations",
    difficulty=0.8,
    tags=["incident", "postmortem", "sre", "reliability"],
)

# ============================================================================
# Research Synthesis Template
# ============================================================================

RESEARCH_SYNTHESIS_TEMPLATE = DebateTemplate(
    template_id="research-synthesis-v1",
    template_type=TemplateType.RESEARCH_SYNTHESIS,
    name="Research Synthesis",
    description="Synthesize findings from multiple research sources",
    roles=[
        DebateRole(
            name="extractor",
            description="Extracts key claims from sources",
            objectives=["Identify key findings", "Extract methodology", "Note limitations"],
            evaluation_criteria=["Accuracy", "Completeness"],
        ),
        DebateRole(
            name="validator",
            description="Cross-validates claims across sources",
            objectives=["Find agreements", "Identify conflicts", "Assess evidence quality"],
            evaluation_criteria=["Rigor", "Citation accuracy"],
        ),
        DebateRole(
            name="synthesizer",
            description="Creates unified synthesis",
            objectives=["Integrate findings", "Identify gaps", "Propose conclusions"],
            evaluation_criteria=["Coherence", "Insight quality"],
        ),
        DebateRole(
            name="critic",
            description="Challenges synthesis quality",
            objectives=["Check for bias", "Identify missing perspectives", "Assess confidence"],
            evaluation_criteria=["Critical thinking", "Balance"],
        ),
    ],
    phases=[
        DebatePhase(
            name="extraction",
            description="Extract claims from sources",
            duration_rounds=1,
            roles_active=["extractor"],
            objectives=["Document all key claims"],
            outputs=["Claim matrix"],
        ),
        DebatePhase(
            name="validation",
            description="Cross-validate claims",
            duration_rounds=2,
            roles_active=["validator", "critic"],
            objectives=["Assess claim validity"],
            outputs=["Validated claims with confidence"],
        ),
        DebatePhase(
            name="synthesis",
            description="Create integrated synthesis",
            duration_rounds=2,
            roles_active=["synthesizer", "critic"],
            objectives=["Produce coherent synthesis"],
            outputs=["Research synthesis"],
        ),
    ],
    recommended_agents=4,
    max_rounds=5,
    consensus_threshold=0.6,
    rubric={
        "claim_accuracy": 0.25,
        "source_coverage": 0.2,
        "synthesis_quality": 0.25,
        "gap_identification": 0.15,
        "confidence_calibration": 0.15,
    },
    output_format="""
# Research Synthesis: {topic}

## Key Findings
{findings}

## Consensus Claims (High Confidence)
{consensus}

## Contested Claims
{contested}

## Evidence Gaps
{gaps}

## Methodology Notes
{methodology}

## Recommendations
{recommendations}

## Sources
{sources}
""",
    domain="research",
    difficulty=0.7,
    tags=["research", "synthesis", "literature", "analysis"],
)

# ============================================================================
# Security Audit Template
# ============================================================================

SECURITY_AUDIT_TEMPLATE = DebateTemplate(
    template_id="security-audit-v1",
    template_type=TemplateType.SECURITY_AUDIT,
    name="Security Audit & Penetration Test Planning",
    description="Structured security assessment with threat modeling and vulnerability analysis",
    roles=[
        DebateRole(
            name="threat_modeler",
            description="Identifies attack surfaces and threat vectors",
            objectives=["Map attack surface", "Identify threat actors", "Model attack paths"],
            evaluation_criteria=["STRIDE coverage", "Threat completeness"],
            example_prompts=[
                "The primary attack surface includes...",
                "A sophisticated attacker could exploit...",
            ],
        ),
        DebateRole(
            name="vulnerability_analyst",
            description="Analyzes technical vulnerabilities",
            objectives=[
                "Find OWASP Top 10 issues",
                "Identify misconfigurations",
                "Check dependencies",
            ],
            evaluation_criteria=["CVE coverage", "Severity accuracy"],
            example_prompts=[
                "This endpoint is vulnerable to injection because...",
                "The authentication flow has a weakness at...",
            ],
        ),
        DebateRole(
            name="red_team",
            description="Simulates adversarial perspective",
            objectives=["Chain vulnerabilities", "Identify escalation paths", "Test defenses"],
            evaluation_criteria=["Attack realism", "Impact assessment"],
            example_prompts=[
                "An attacker could chain these issues to...",
                "The defense can be bypassed by...",
            ],
        ),
        DebateRole(
            name="blue_team",
            description="Evaluates defensive controls",
            objectives=["Assess detection capability", "Review logging", "Evaluate response"],
            evaluation_criteria=["Defense coverage", "Detection accuracy"],
            example_prompts=[
                "Current monitoring would detect this via...",
                "The incident response gap is...",
            ],
        ),
        DebateRole(
            name="compliance_officer",
            description="Maps findings to compliance requirements",
            objectives=["Map to frameworks", "Assess regulatory risk", "Prioritize remediations"],
            evaluation_criteria=["Framework coverage", "Risk prioritization"],
            example_prompts=[
                "This finding impacts SOC 2 control...",
                "Regulatory exposure includes...",
            ],
        ),
    ],
    phases=[
        DebatePhase(
            name="reconnaissance",
            description="Map attack surface and identify assets",
            duration_rounds=1,
            roles_active=["threat_modeler", "vulnerability_analyst"],
            objectives=["Complete asset inventory", "Identify entry points"],
            outputs=["Attack surface map"],
        ),
        DebatePhase(
            name="vulnerability_assessment",
            description="Identify and validate vulnerabilities",
            duration_rounds=2,
            roles_active=["vulnerability_analyst", "red_team"],
            objectives=["Find vulnerabilities", "Validate exploitability"],
            outputs=["Vulnerability list with severity"],
        ),
        DebatePhase(
            name="attack_simulation",
            description="Red team vs blue team analysis",
            duration_rounds=2,
            roles_active=["red_team", "blue_team"],
            objectives=["Test attack paths", "Evaluate defenses"],
            outputs=["Attack scenarios and defense gaps"],
        ),
        DebatePhase(
            name="remediation_planning",
            description="Prioritize and plan fixes",
            duration_rounds=1,
            roles_active=["compliance_officer", "blue_team", "vulnerability_analyst"],
            objectives=["Prioritize remediations", "Create action plan"],
            outputs=["Prioritized remediation roadmap"],
        ),
    ],
    recommended_agents=5,
    max_rounds=6,
    consensus_threshold=0.8,
    rubric={
        "threat_coverage": 0.2,
        "vulnerability_accuracy": 0.25,
        "attack_realism": 0.2,
        "defense_assessment": 0.15,
        "remediation_quality": 0.2,
    },
    output_format="""
# Security Audit Report

## Executive Summary
Risk Level: {risk_level}
Critical Findings: {critical_count}
High Findings: {high_count}

## Attack Surface
{attack_surface}

## Threat Model
{threat_model}

## Vulnerabilities

### Critical
{critical_vulnerabilities}

### High
{high_vulnerabilities}

### Medium
{medium_vulnerabilities}

## Attack Scenarios
{attack_scenarios}

## Defense Gaps
{defense_gaps}

## Compliance Impact
{compliance_impact}

## Remediation Roadmap
{remediation_roadmap}

## Appendix: Testing Methodology
{methodology}
""",
    domain="security",
    difficulty=0.9,
    tags=["security", "audit", "pentest", "vulnerability", "compliance"],
)

# ============================================================================
# Architecture Review Template
# ============================================================================

ARCHITECTURE_REVIEW_TEMPLATE = DebateTemplate(
    template_id="architecture-review-v1",
    template_type=TemplateType.ARCHITECTURE_REVIEW,
    name="System Architecture Review",
    description="Comprehensive architecture validation for scalability, reliability, and maintainability",
    roles=[
        DebateRole(
            name="architect",
            description="Presents and defends the architecture",
            objectives=["Explain design rationale", "Justify tradeoffs", "Address concerns"],
            evaluation_criteria=["Clarity", "Completeness"],
            example_prompts=[
                "The system is designed this way because...",
                "We chose this pattern to handle...",
            ],
        ),
        DebateRole(
            name="scalability_reviewer",
            description="Evaluates scale and performance characteristics",
            objectives=["Identify bottlenecks", "Assess horizontal scaling", "Review data growth"],
            evaluation_criteria=["Scale accuracy", "Bottleneck identification"],
            example_prompts=[
                "At 10x load, this component will...",
                "The database sharding strategy limits...",
            ],
        ),
        DebateRole(
            name="reliability_reviewer",
            description="Assesses fault tolerance and resilience",
            objectives=[
                "Find single points of failure",
                "Review disaster recovery",
                "Assess degradation",
            ],
            evaluation_criteria=["Failure mode coverage", "Recovery assessment"],
            example_prompts=[
                "If this service fails, the impact is...",
                "The failover mechanism doesn't handle...",
            ],
        ),
        DebateRole(
            name="security_reviewer",
            description="Reviews security architecture",
            objectives=["Assess defense in depth", "Review data flow security", "Check compliance"],
            evaluation_criteria=["Security coverage", "Threat mitigation"],
            example_prompts=[
                "The trust boundary here is...",
                "Data at rest encryption is missing for...",
            ],
        ),
        DebateRole(
            name="operations_reviewer",
            description="Evaluates operational complexity",
            objectives=[
                "Assess deployment complexity",
                "Review observability",
                "Check maintainability",
            ],
            evaluation_criteria=["Operational clarity", "Maintenance burden"],
            example_prompts=[
                "Deploying this requires...",
                "Debugging production issues will be difficult because...",
            ],
        ),
    ],
    phases=[
        DebatePhase(
            name="presentation",
            description="Architect presents the design",
            duration_rounds=1,
            roles_active=["architect"],
            objectives=["Present architecture", "Explain key decisions"],
            outputs=["Architecture overview"],
        ),
        DebatePhase(
            name="review",
            description="Each reviewer evaluates from their perspective",
            duration_rounds=1,
            roles_active=[
                "scalability_reviewer",
                "reliability_reviewer",
                "security_reviewer",
                "operations_reviewer",
            ],
            objectives=["Identify concerns in each domain"],
            outputs=["Domain-specific findings"],
        ),
        DebatePhase(
            name="debate",
            description="Discuss and resolve concerns",
            duration_rounds=2,
            roles_active=[
                "architect",
                "scalability_reviewer",
                "reliability_reviewer",
                "security_reviewer",
                "operations_reviewer",
            ],
            objectives=["Resolve disagreements", "Validate mitigations"],
            outputs=["Consensus on key issues"],
        ),
        DebatePhase(
            name="synthesis",
            description="Create final assessment",
            duration_rounds=1,
            roles_active=["architect", "operations_reviewer"],
            objectives=["Summarize findings", "Create action items"],
            outputs=["Architecture decision record"],
        ),
    ],
    recommended_agents=5,
    max_rounds=5,
    consensus_threshold=0.7,
    rubric={
        "scalability_assessment": 0.2,
        "reliability_assessment": 0.2,
        "security_assessment": 0.2,
        "operational_assessment": 0.2,
        "overall_coherence": 0.2,
    },
    output_format="""
# Architecture Review: {system_name}

## Overall Assessment: {assessment} ({confidence}% confidence)

## Architecture Summary
{summary}

## Scalability
Score: {scalability_score}/10
{scalability_findings}

## Reliability
Score: {reliability_score}/10
{reliability_findings}

## Security
Score: {security_score}/10
{security_findings}

## Operations
Score: {operations_score}/10
{operations_findings}

## Key Risks
{risks}

## Recommendations
{recommendations}

## Architecture Decision Records
{adrs}
""",
    domain="architecture",
    difficulty=0.8,
    tags=["architecture", "review", "scalability", "reliability", "security"],
)

# ============================================================================
# Healthcare Compliance Template
# ============================================================================

HEALTHCARE_COMPLIANCE_TEMPLATE = DebateTemplate(
    template_id="healthcare-compliance-v1",
    template_type=TemplateType.HEALTHCARE_COMPLIANCE,
    name="Healthcare Compliance Audit (HIPAA/HITECH)",
    description="Structured compliance review for healthcare data handling and patient privacy",
    roles=[
        DebateRole(
            name="privacy_officer",
            description="Evaluates patient privacy protections",
            objectives=[
                "Assess PHI handling",
                "Review consent mechanisms",
                "Check access controls",
            ],
            evaluation_criteria=["Privacy Rule coverage", "Patient rights"],
            example_prompts=[
                "PHI is exposed in this flow because...",
                "The minimum necessary principle is violated when...",
            ],
        ),
        DebateRole(
            name="security_analyst",
            description="Reviews technical safeguards",
            objectives=["Assess encryption", "Review audit logging", "Check access management"],
            evaluation_criteria=["Security Rule coverage", "Technical controls"],
            example_prompts=[
                "Data at rest encryption is insufficient because...",
                "Audit logs don't capture...",
            ],
        ),
        DebateRole(
            name="compliance_auditor",
            description="Maps controls to regulatory requirements",
            objectives=["Map to HIPAA requirements", "Identify gaps", "Assess penalties"],
            evaluation_criteria=["Regulatory accuracy", "Gap completeness"],
            example_prompts=[
                "This violates 45 CFR 164.312(a)(1) because...",
                "The potential penalty exposure is...",
            ],
        ),
        DebateRole(
            name="clinical_operations",
            description="Represents clinical workflow needs",
            objectives=[
                "Ensure usability",
                "Validate workflow integration",
                "Balance security with care",
            ],
            evaluation_criteria=["Clinical practicality", "Workflow impact"],
            example_prompts=[
                "This control would impact patient care by...",
                "Clinicians need access to X because...",
            ],
        ),
        DebateRole(
            name="breach_analyst",
            description="Evaluates breach notification readiness",
            objectives=[
                "Assess detection capability",
                "Review notification process",
                "Evaluate containment",
            ],
            evaluation_criteria=["Breach readiness", "Response capability"],
            example_prompts=[
                "A breach of this system would require notification within...",
                "The detection gap means breaches could go unnoticed for...",
            ],
        ),
    ],
    phases=[
        DebatePhase(
            name="inventory",
            description="Identify PHI touchpoints and data flows",
            duration_rounds=1,
            roles_active=["privacy_officer", "security_analyst"],
            objectives=["Map all PHI", "Document data flows"],
            outputs=["PHI inventory and data flow diagram"],
        ),
        DebatePhase(
            name="control_assessment",
            description="Evaluate administrative, physical, and technical safeguards",
            duration_rounds=2,
            roles_active=["security_analyst", "compliance_auditor", "privacy_officer"],
            objectives=["Assess all safeguard categories", "Identify gaps"],
            outputs=["Control assessment matrix"],
        ),
        DebatePhase(
            name="risk_analysis",
            description="Conduct risk analysis per HIPAA requirements",
            duration_rounds=2,
            roles_active=["compliance_auditor", "breach_analyst", "security_analyst"],
            objectives=["Quantify risks", "Prioritize remediations"],
            outputs=["Risk analysis report"],
        ),
        DebatePhase(
            name="remediation",
            description="Plan compliance improvements",
            duration_rounds=1,
            roles_active=["compliance_auditor", "clinical_operations", "privacy_officer"],
            objectives=["Create remediation plan", "Balance compliance with operations"],
            outputs=["Compliance roadmap"],
        ),
    ],
    recommended_agents=5,
    max_rounds=6,
    consensus_threshold=0.8,
    rubric={
        "privacy_rule_coverage": 0.25,
        "security_rule_coverage": 0.25,
        "breach_readiness": 0.2,
        "risk_analysis_quality": 0.15,
        "remediation_practicality": 0.15,
    },
    output_format="""
# Healthcare Compliance Audit Report

## Executive Summary
Compliance Status: {status}
Critical Gaps: {critical_gaps}
Risk Level: {risk_level}

## PHI Inventory
{phi_inventory}

## Data Flow Analysis
{data_flows}

## Privacy Rule Assessment

### Notice of Privacy Practices
{npp_assessment}

### Patient Rights
{patient_rights}

### Minimum Necessary
{minimum_necessary}

## Security Rule Assessment

### Administrative Safeguards
{administrative_safeguards}

### Physical Safeguards
{physical_safeguards}

### Technical Safeguards
{technical_safeguards}

## Breach Notification Readiness
{breach_readiness}

## Risk Analysis
{risk_analysis}

## Compliance Gaps
{gaps}

## Remediation Roadmap
{remediation}

## Business Associate Agreements
{baa_status}
""",
    domain="healthcare",
    difficulty=0.9,
    tags=["healthcare", "hipaa", "compliance", "privacy", "phi"],
)

# ============================================================================
# Financial Risk Analysis Template
# ============================================================================

FINANCIAL_RISK_TEMPLATE = DebateTemplate(
    template_id="financial-risk-v1",
    template_type=TemplateType.FINANCIAL_RISK,
    name="Financial Risk Analysis & Red Team",
    description="Trading strategy stress-testing and financial risk assessment",
    roles=[
        DebateRole(
            name="strategist",
            description="Presents and defends the trading strategy",
            objectives=["Explain strategy logic", "Present backtests", "Justify parameters"],
            evaluation_criteria=["Strategy clarity", "Evidence quality"],
            example_prompts=[
                "The strategy generates alpha by...",
                "Historical performance shows...",
            ],
        ),
        DebateRole(
            name="quant_analyst",
            description="Analyzes quantitative aspects",
            objectives=["Validate statistics", "Check assumptions", "Assess model risk"],
            evaluation_criteria=["Statistical rigor", "Model validation"],
            example_prompts=[
                "The Sharpe ratio is overstated because...",
                "The correlation assumptions break down when...",
            ],
        ),
        DebateRole(
            name="risk_manager",
            description="Evaluates risk exposures",
            objectives=["Assess tail risks", "Review position limits", "Evaluate drawdowns"],
            evaluation_criteria=["Risk coverage", "Limit appropriateness"],
            example_prompts=[
                "Maximum drawdown in stress scenarios would be...",
                "The VaR calculation misses...",
            ],
        ),
        DebateRole(
            name="market_skeptic",
            description="Challenges market assumptions",
            objectives=["Identify regime changes", "Challenge liquidity", "Test market impact"],
            evaluation_criteria=["Scenario realism", "Assumption challenges"],
            example_prompts=[
                "In a liquidity crisis, this position would...",
                "The 2008-style scenario would cause...",
            ],
        ),
        DebateRole(
            name="compliance_reviewer",
            description="Reviews regulatory and compliance aspects",
            objectives=["Check regulatory limits", "Review reporting", "Assess fiduciary duty"],
            evaluation_criteria=["Regulatory coverage", "Compliance accuracy"],
            example_prompts=[
                "This strategy may violate rule...",
                "Disclosure requirements include...",
            ],
        ),
    ],
    phases=[
        DebatePhase(
            name="strategy_presentation",
            description="Present the trading strategy",
            duration_rounds=1,
            roles_active=["strategist"],
            objectives=["Present strategy and evidence"],
            outputs=["Strategy documentation"],
        ),
        DebatePhase(
            name="quantitative_review",
            description="Analyze quantitative foundations",
            duration_rounds=2,
            roles_active=["quant_analyst", "risk_manager"],
            objectives=["Validate statistics", "Assess risk metrics"],
            outputs=["Quantitative assessment"],
        ),
        DebatePhase(
            name="stress_testing",
            description="Red team the strategy under stress",
            duration_rounds=2,
            roles_active=["market_skeptic", "risk_manager", "strategist"],
            objectives=["Test extreme scenarios", "Identify breaking points"],
            outputs=["Stress test results"],
        ),
        DebatePhase(
            name="final_assessment",
            description="Synthesize findings and make recommendation",
            duration_rounds=1,
            roles_active=["risk_manager", "compliance_reviewer", "quant_analyst"],
            objectives=["Final risk assessment", "Go/no-go recommendation"],
            outputs=["Investment committee memo"],
        ),
    ],
    recommended_agents=5,
    max_rounds=6,
    consensus_threshold=0.75,
    rubric={
        "strategy_validity": 0.2,
        "quantitative_rigor": 0.25,
        "risk_assessment": 0.25,
        "stress_test_coverage": 0.2,
        "compliance_check": 0.1,
    },
    output_format="""
# Financial Risk Analysis Report

## Executive Summary
Recommendation: {recommendation}
Risk Rating: {risk_rating}
Confidence: {confidence}%

## Strategy Overview
{strategy_overview}

## Quantitative Analysis

### Performance Metrics
{performance_metrics}

### Statistical Validation
{statistical_validation}

### Model Risk Assessment
{model_risk}

## Risk Analysis

### Market Risk
{market_risk}

### Liquidity Risk
{liquidity_risk}

### Tail Risk
{tail_risk}

### Concentration Risk
{concentration_risk}

## Stress Test Results

### Historical Scenarios
{historical_scenarios}

### Hypothetical Scenarios
{hypothetical_scenarios}

### Breaking Points
{breaking_points}

## Compliance Review
{compliance_review}

## Risk Limits Recommendation
{risk_limits}

## Conditions for Approval
{conditions}

## Monitoring Requirements
{monitoring}
""",
    domain="finance",
    difficulty=0.9,
    tags=["finance", "trading", "risk", "quant", "stress-test"],
)

# ============================================================================
# Template Registry
# ============================================================================

TEMPLATES = {
    TemplateType.CODE_REVIEW: CODE_REVIEW_TEMPLATE,
    TemplateType.DESIGN_DOC: DESIGN_DOC_TEMPLATE,
    TemplateType.INCIDENT_RESPONSE: INCIDENT_RESPONSE_TEMPLATE,
    TemplateType.RESEARCH_SYNTHESIS: RESEARCH_SYNTHESIS_TEMPLATE,
    TemplateType.SECURITY_AUDIT: SECURITY_AUDIT_TEMPLATE,
    TemplateType.ARCHITECTURE_REVIEW: ARCHITECTURE_REVIEW_TEMPLATE,
    TemplateType.HEALTHCARE_COMPLIANCE: HEALTHCARE_COMPLIANCE_TEMPLATE,
    TemplateType.FINANCIAL_RISK: FINANCIAL_RISK_TEMPLATE,
}


def get_template(template_type: TemplateType) -> DebateTemplate:
    """Get a debate template by type."""
    if template_type not in TEMPLATES:
        raise ValueError(f"Unknown template type: {template_type}")
    return TEMPLATES[template_type]


def list_templates() -> list[dict]:
    """List all available templates."""
    return [
        {
            "id": t.template_id,
            "type": t.template_type.value,
            "name": t.name,
            "description": t.description,
            "agents": t.recommended_agents,
            "domain": t.domain,
        }
        for t in TEMPLATES.values()
    ]


def template_to_protocol(
    template: DebateTemplate,
    overrides: dict | None = None,
) -> DebateProtocol:
    """Convert a DebateTemplate to a DebateProtocol.

    Maps template structure to protocol mechanics:
    - template.max_rounds -> protocol.rounds
    - template.consensus_threshold -> protocol.consensus_threshold
    - template.phases -> total rounds from phase durations
    - Multiple roles -> round-robin topology for structured exchanges

    Note: Template roles (e.g., "author", "security_critic") are domain-specific
    and don't directly map to CognitiveRole. Role rotation uses default cognitive
    roles (analyst, skeptic, lateral_thinker, synthesizer) which complement
    the template structure.

    Args:
        template: The DebateTemplate to convert
        overrides: Optional dict of protocol fields to override

    Returns:
        Configured DebateProtocol matching the template structure
    """
    from aragora.protocols.debate import DebateProtocol

    overrides = overrides or {}

    # Calculate total rounds from phases
    total_rounds = sum(phase.duration_rounds for phase in template.phases)
    rounds = overrides.get("rounds", max(total_rounds, template.max_rounds))

    # Determine topology based on template structure
    # Templates with distinct critic roles benefit from round-robin
    # Research templates benefit from all-to-all for synthesis
    topology = overrides.get("topology")
    if topology is None:
        if template.template_type == TemplateType.RESEARCH_SYNTHESIS:
            topology = "all-to-all"
        elif len(template.roles) >= 4:
            topology = "round-robin"
        else:
            topology = "all-to-all"

    return DebateProtocol(
        rounds=rounds,
        topology=topology,
        consensus=overrides.get("consensus", "majority"),
        consensus_threshold=overrides.get("consensus_threshold", template.consensus_threshold),
        role_rotation=overrides.get("role_rotation", True),
        require_reasoning=True,
        early_stopping=overrides.get("early_stopping", True),
        convergence_detection=overrides.get("convergence_detection", True),
        enable_calibration=overrides.get("enable_calibration", True),
    )


__all__ = [
    "DebateTemplate",
    "DebateRole",
    "DebatePhase",
    "TemplateType",
    "CODE_REVIEW_TEMPLATE",
    "DESIGN_DOC_TEMPLATE",
    "INCIDENT_RESPONSE_TEMPLATE",
    "RESEARCH_SYNTHESIS_TEMPLATE",
    "SECURITY_AUDIT_TEMPLATE",
    "ARCHITECTURE_REVIEW_TEMPLATE",
    "HEALTHCARE_COMPLIANCE_TEMPLATE",
    "FINANCIAL_RISK_TEMPLATE",
    "get_template",
    "list_templates",
    "template_to_protocol",
    "TEMPLATES",
]
