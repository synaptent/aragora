"""
Vertical Specialist System.

Provides domain-specific AI agents with specialized prompts, tools,
compliance frameworks, and fine-tuned model support.

Usage:
    from aragora.verticals import (
        VerticalRegistry,
        VerticalConfig,
        VerticalSpecialistAgent,
    )

    # Get a vertical specialist
    software_agent = VerticalRegistry.create_specialist(
        "software",
        name="code-reviewer-1",
        model="claude-opus-5",
    )

    # Use in workflows
    response = await software_agent.respond(task, context)
"""

from aragora.verticals.registry import VerticalRegistry, VerticalSpec
from aragora.verticals.config import VerticalConfig, ToolConfig, ComplianceConfig
from aragora.verticals.base import VerticalSpecialistAgent

# Import specialist implementations to trigger registration
from aragora.verticals.specialists.software import SoftwareSpecialist
from aragora.verticals.specialists.legal import LegalSpecialist
from aragora.verticals.specialists.healthcare import HealthcareSpecialist
from aragora.verticals.specialists.accounting import AccountingSpecialist
from aragora.verticals.specialists.research import ResearchSpecialist

__all__ = [
    # Registry
    "VerticalRegistry",
    "VerticalSpec",
    # Config
    "VerticalConfig",
    "ToolConfig",
    "ComplianceConfig",
    # Base
    "VerticalSpecialistAgent",
    # Specialists
    "SoftwareSpecialist",
    "LegalSpecialist",
    "HealthcareSpecialist",
    "AccountingSpecialist",
    "ResearchSpecialist",
]
