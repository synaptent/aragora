"""
Onboarding Orchestration Handler.

Provides a unified onboarding experience for new users and organizations:
- Multi-step onboarding flow management
- Personalized template recommendations
- Progress tracking and analytics
- First debate assistance
- Quick-start configurations

Endpoints:
- GET /api/v1/onboarding/flow - Get current onboarding state
- POST /api/v1/onboarding/flow - Initialize onboarding
- PUT /api/v1/onboarding/flow/step - Update current step
- GET /api/v1/onboarding/templates - Get recommended starter templates
- POST /api/v1/onboarding/first-debate - Start guided first debate
- POST /api/v1/onboarding/quick-start - Apply quick-start configuration
- GET /api/v1/onboarding/analytics - Get onboarding funnel analytics
"""

from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    success_response,
)
from aragora.rbac.decorators import require_permission
from aragora.storage.repositories.onboarding import get_onboarding_repository

logger = logging.getLogger(__name__)

# =============================================================================
# Types and Constants
# =============================================================================


class OnboardingStep(str, Enum):
    """Onboarding steps in order."""

    WELCOME = "welcome"
    USE_CASE = "use_case"
    ORGANIZATION = "organization"
    TEAM_INVITE = "team_invite"
    TEMPLATE_SELECT = "template_select"
    FIRST_DEBATE = "first_debate"
    RECEIPT_REVIEW = "receipt_review"
    COMPLETION = "completion"


class UseCase(str, Enum):
    """Pre-defined use cases for personalized onboarding."""

    TEAM_DECISIONS = "team_decisions"
    ARCHITECTURE_REVIEW = "architecture_review"
    SECURITY_AUDIT = "security_audit"
    POLICY_REVIEW = "policy_review"
    VENDOR_SELECTION = "vendor_selection"
    TECHNICAL_PLANNING = "technical_planning"
    COMPLIANCE = "compliance"
    GENERAL = "general"


class QuickStartProfile(str, Enum):
    """Quick-start profiles for immediate value."""

    DEVELOPER = "developer"
    SECURITY = "security"
    EXECUTIVE = "executive"
    PRODUCT = "product"
    COMPLIANCE = "compliance"
    SME = "sme"  # Small-Medium Enterprise focused profile


@dataclass
class StarterTemplate:
    """Template recommended for onboarding."""

    id: str
    name: str
    description: str
    use_cases: list[str]
    agents_count: int
    rounds: int
    estimated_minutes: int
    example_prompt: str
    tags: list[str] = field(default_factory=list)
    difficulty: str = "beginner"


@dataclass
class OnboardingState:
    """Complete onboarding state for a user/org."""

    id: str
    user_id: str
    organization_id: str | None
    current_step: OnboardingStep
    completed_steps: list[str]
    use_case: str | None
    selected_template_id: str | None
    first_debate_id: str | None
    quick_start_profile: str | None
    team_invites: list[dict[str, str]]
    started_at: str
    updated_at: str
    completed_at: str | None
    skipped: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# In-Memory Storage (Replace with DB in production)
# =============================================================================

_onboarding_flows: dict[str, OnboardingState] = {}
_onboarding_lock = threading.Lock()

_analytics_events: list[dict[str, Any]] = []
_analytics_lock = threading.Lock()


def _parse_event_timestamp(raw_timestamp: Any) -> datetime | None:
    """Parse ISO timestamps from analytics events."""
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        return None
    try:
        return datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return None


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    """Calculate a percentile using linear interpolation."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (percentile / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return (sorted_values[lower] * (1 - weight)) + (sorted_values[upper] * weight)


def _summarize_durations_seconds(values: list[float]) -> dict[str, Any]:
    """Summarize duration distributions with standard percentiles."""
    if not values:
        return {
            "count": 0,
            "avg": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
        }

    normalized = sorted(v for v in values if v >= 0.0)
    if not normalized:
        return {
            "count": 0,
            "avg": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
        }

    avg = sum(normalized) / len(normalized)
    return {
        "count": len(normalized),
        "avg": round(avg, 3),
        "p50": round(_percentile(normalized, 50.0) or 0.0, 3),
        "p95": round(_percentile(normalized, 95.0) or 0.0, 3),
        "min": round(normalized[0], 3),
        "max": round(normalized[-1], 3),
    }


def _sync_flow_to_repo(flow: OnboardingState) -> None:
    """Sync flow state to persistent repository."""
    try:
        repo = get_onboarding_repository()
        repo.update_flow(
            flow.id,
            {
                "current_step": flow.current_step.value,
                "completed_steps": flow.completed_steps,
                "use_case": flow.use_case,
                "selected_template": flow.selected_template_id,
                "first_debate_id": flow.first_debate_id,
                "quick_start_profile": flow.quick_start_profile,
                "metadata": {
                    **flow.metadata,
                    "team_invites": flow.team_invites,
                    "skipped": flow.skipped,
                },
                "completed_at": flow.completed_at,
            },
        )
    except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
        logger.warning("Failed to sync flow to repository: %s", e)


# =============================================================================
# Starter Templates
# =============================================================================

# Fast-path onboarding defaults (intentionally small for quick starts).
ONBOARDING_FAST_ROUNDS = 3
ONBOARDING_QUICK_ROUNDS = 2
ONBOARDING_DEEP_ROUNDS = 4

STARTER_TEMPLATES: list[StarterTemplate] = [
    StarterTemplate(
        id="arch_review_starter",
        name="Architecture Review",
        description="Have AI agents review your system architecture for scalability, maintainability, and best practices.",
        use_cases=[UseCase.ARCHITECTURE_REVIEW.value, UseCase.TECHNICAL_PLANNING.value],
        agents_count=4,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=5,
        example_prompt="Review this architecture: We have a monolithic Django app serving 10k daily users. We're considering migrating to microservices. What are the trade-offs?",
        tags=["architecture", "review", "starter"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="security_scan_starter",
        name="Security Assessment",
        description="Get AI agents to identify potential security vulnerabilities and recommend mitigations.",
        use_cases=[UseCase.SECURITY_AUDIT.value, UseCase.COMPLIANCE.value],
        agents_count=5,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=7,
        example_prompt="Assess security concerns: We store user PII in PostgreSQL, use JWT for auth, and deploy on AWS. What vulnerabilities should we address?",
        tags=["security", "audit", "starter"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="team_decision_starter",
        name="Team Decision",
        description="Facilitate team decisions with structured AI debate and clear reasoning.",
        use_cases=[UseCase.TEAM_DECISIONS.value, UseCase.GENERAL.value],
        agents_count=3,
        rounds=ONBOARDING_QUICK_ROUNDS,
        estimated_minutes=3,
        example_prompt="Help us decide: Should we build this feature in-house or use a third-party solution? Consider development time, cost, and maintenance.",
        tags=["decisions", "team", "starter"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="vendor_eval_starter",
        name="Vendor Evaluation",
        description="Compare vendors or tools with multi-perspective AI analysis.",
        use_cases=[UseCase.VENDOR_SELECTION.value, UseCase.TECHNICAL_PLANNING.value],
        agents_count=4,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=5,
        example_prompt="Compare AWS, GCP, and Azure for our startup's infrastructure needs. We prioritize cost-effectiveness and developer experience.",
        tags=["vendor", "comparison", "starter"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="policy_review_starter",
        name="Policy Review",
        description="Review policies and procedures for gaps, inconsistencies, and improvements.",
        use_cases=[UseCase.POLICY_REVIEW.value, UseCase.COMPLIANCE.value],
        agents_count=4,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=6,
        example_prompt="Review our remote work policy: Employees must be available 9-5 in their timezone, use VPN for company resources, and attend weekly team syncs.",
        tags=["policy", "review", "hr", "starter"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="quick_question_starter",
        name="Quick Question",
        description="Get rapid multi-perspective answers to any question.",
        use_cases=[UseCase.GENERAL.value],
        agents_count=3,
        rounds=ONBOARDING_QUICK_ROUNDS,
        estimated_minutes=2,
        example_prompt="What's the best way to handle database migrations in a microservices architecture?",
        tags=["quick", "general", "starter"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="express_onboarding",
        name="Express Debate (2 min)",
        description="Ultra-fast first debate to see Aragora in action. Perfect for onboarding.",
        use_cases=[UseCase.GENERAL.value],
        agents_count=2,
        rounds=ONBOARDING_QUICK_ROUNDS,
        estimated_minutes=2,
        example_prompt="What's more important for a startup: fast iteration speed or code quality?",
        tags=["onboarding", "express", "fast", "starter"],
        difficulty="beginner",
    ),
    # SME Starter Templates
    StarterTemplate(
        id="sme_hiring_decision",
        name="Hiring Decision",
        description="Evaluate candidates with structured multi-agent debate for balanced, fair hiring decisions.",
        use_cases=[UseCase.TEAM_DECISIONS.value],
        agents_count=2,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=5,
        example_prompt="Should we hire [candidate] for the [role] position? Consider their technical skills, cultural fit, and growth potential.",
        tags=["sme", "hiring", "hr", "team"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_performance_review",
        name="Performance Review",
        description="Generate balanced performance assessments with multiple AI perspectives on strengths and growth areas.",
        use_cases=[UseCase.TEAM_DECISIONS.value],
        agents_count=2,
        rounds=ONBOARDING_QUICK_ROUNDS,
        estimated_minutes=3,
        example_prompt="Evaluate [employee]'s Q4 performance: they exceeded sprint goals but had communication challenges with stakeholders.",
        tags=["sme", "hr", "performance", "team"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_feature_prioritization",
        name="Feature Prioritization",
        description="Prioritize product features based on impact, effort, and strategic alignment using multi-agent debate.",
        use_cases=[UseCase.TECHNICAL_PLANNING.value],
        agents_count=3,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=5,
        example_prompt="Prioritize these features for next quarter: dark mode, API v2, mobile app, export to PDF. We have 2 developers available.",
        tags=["sme", "product", "planning", "project"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_sprint_planning",
        name="Sprint Planning",
        description="Plan sprint scope and commitments with AI-assisted capacity and estimation analysis.",
        use_cases=[UseCase.TECHNICAL_PLANNING.value],
        agents_count=2,
        rounds=ONBOARDING_QUICK_ROUNDS,
        estimated_minutes=3,
        example_prompt="Plan Sprint 24 for our 5-person team. Backlog: user auth, dashboard redesign, API refactor. Historical velocity: 32 points.",
        tags=["sme", "agile", "sprint", "project"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_tool_selection",
        name="Tool Selection",
        description="Compare and select tools with comprehensive multi-agent analysis of features, pricing, and fit.",
        use_cases=[UseCase.VENDOR_SELECTION.value],
        agents_count=3,
        rounds=ONBOARDING_DEEP_ROUNDS,
        estimated_minutes=7,
        example_prompt="Compare Jira, Linear, and Asana for our 15-person team. We need GitHub integration and good Agile support. Budget: $50/user/month.",
        tags=["sme", "tools", "vendor", "selection"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_contract_review",
        name="Contract Review",
        description="Review contracts for risks and negotiate favorable terms with multi-perspective legal analysis.",
        use_cases=[UseCase.VENDOR_SELECTION.value, UseCase.POLICY_REVIEW.value],
        agents_count=2,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=5,
        example_prompt="Review our SaaS agreement with Vendor Corp ($120k/year). Key concerns: data ownership, SLA commitments, termination terms.",
        tags=["sme", "legal", "contract", "vendor"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_remote_work_policy",
        name="Remote Work Policy",
        description="Design or refine remote work policies balancing flexibility, productivity, and compliance.",
        use_cases=[UseCase.POLICY_REVIEW.value],
        agents_count=3,
        rounds=ONBOARDING_FAST_ROUNDS,
        estimated_minutes=5,
        example_prompt="Review our remote policy: 3 days in office required. We're a 75-person fintech. Concerns: collaboration quality, timezone coverage.",
        tags=["sme", "hr", "policy", "remote"],
        difficulty="beginner",
    ),
    StarterTemplate(
        id="sme_budget_allocation",
        name="Budget Allocation",
        description="Allocate budgets across categories with data-driven multi-agent analysis and proposals.",
        use_cases=[UseCase.POLICY_REVIEW.value, UseCase.TEAM_DECISIONS.value],
        agents_count=3,
        rounds=ONBOARDING_QUICK_ROUNDS,
        estimated_minutes=3,
        example_prompt="Allocate $500k Engineering budget for FY2025 across: infrastructure (cloud), tools (dev tools), training, contractors.",
        tags=["sme", "budget", "finance", "policy"],
        difficulty="beginner",
    ),
]

QUICK_START_CONFIGS: dict[str, dict[str, Any]] = {
    QuickStartProfile.DEVELOPER.value: {
        "default_template": "arch_review_starter",
        "suggested_templates": [
            "arch_review_starter",
            "security_scan_starter",
            "quick_question_starter",
        ],
        "default_agents": ["claude", "gpt-4", "gemini"],
        "default_rounds": ONBOARDING_FAST_ROUNDS,
        "focus_areas": ["architecture", "code_quality", "performance"],
    },
    QuickStartProfile.SECURITY.value: {
        "default_template": "security_scan_starter",
        "suggested_templates": ["security_scan_starter", "policy_review_starter"],
        "default_agents": ["claude", "gpt-4", "gemini", "grok"],
        "default_rounds": ONBOARDING_DEEP_ROUNDS,
        "focus_areas": ["vulnerabilities", "compliance", "access_control"],
    },
    QuickStartProfile.EXECUTIVE.value: {
        "default_template": "team_decision_starter",
        "suggested_templates": [
            "team_decision_starter",
            "vendor_eval_starter",
            "policy_review_starter",
        ],
        "default_agents": ["claude", "gpt-4"],
        "default_rounds": ONBOARDING_QUICK_ROUNDS,
        "focus_areas": ["strategy", "roi", "risk"],
    },
    QuickStartProfile.PRODUCT.value: {
        "default_template": "team_decision_starter",
        "suggested_templates": [
            "team_decision_starter",
            "vendor_eval_starter",
            "quick_question_starter",
        ],
        "default_agents": ["claude", "gpt-4", "gemini"],
        "default_rounds": ONBOARDING_FAST_ROUNDS,
        "focus_areas": ["user_experience", "feasibility", "market_fit"],
    },
    QuickStartProfile.COMPLIANCE.value: {
        "default_template": "policy_review_starter",
        "suggested_templates": ["policy_review_starter", "security_scan_starter"],
        "default_agents": ["claude", "gpt-4", "gemini", "grok"],
        "default_rounds": ONBOARDING_DEEP_ROUNDS,
        "focus_areas": ["regulations", "audit", "documentation"],
    },
    QuickStartProfile.SME.value: {
        "default_template": "sme_hiring_decision",
        "suggested_templates": [
            "sme_hiring_decision",
            "sme_feature_prioritization",
            "sme_tool_selection",
            "sme_budget_allocation",
        ],
        "default_agents": ["claude", "gpt-4"],
        "default_rounds": ONBOARDING_FAST_ROUNDS,
        "focus_areas": ["team_decisions", "vendor_selection", "policy", "project_planning"],
        "budget_enabled": True,
        "max_debates_free": 50,
    },
}

# =============================================================================
# Helper Functions
# =============================================================================


def _get_step_order() -> list[OnboardingStep]:
    """Get ordered list of onboarding steps."""
    return [
        OnboardingStep.WELCOME,
        OnboardingStep.USE_CASE,
        OnboardingStep.ORGANIZATION,
        OnboardingStep.TEAM_INVITE,
        OnboardingStep.TEMPLATE_SELECT,
        OnboardingStep.FIRST_DEBATE,
        OnboardingStep.RECEIPT_REVIEW,
        OnboardingStep.COMPLETION,
    ]


def _get_next_step(current: OnboardingStep) -> OnboardingStep:
    """Get next step in onboarding flow."""
    steps = _get_step_order()
    idx = steps.index(current)
    return steps[min(idx + 1, len(steps) - 1)]


def _get_recommended_templates(use_case: str | None) -> list[StarterTemplate]:
    """Get templates recommended for a use case.

    Merges hardcoded starter templates with marketplace templates,
    prioritizing marketplace templates that match the use case and
    have higher ratings.
    """
    # Collect marketplace templates (lazy import to avoid circular deps)
    marketplace_starters = _load_marketplace_templates()

    # Combine: marketplace first (higher quality metadata), then starters
    all_templates = marketplace_starters + STARTER_TEMPLATES

    # Deduplicate by id (marketplace wins if same id exists)
    seen: set[str] = set()
    unique: list[StarterTemplate] = []
    for t in all_templates:
        if t.id not in seen:
            seen.add(t.id)
            unique.append(t)

    if not use_case:
        return unique[:8]

    # Prioritize templates matching the use case
    matching = [t for t in unique if use_case in t.use_cases]
    others = [t for t in unique if use_case not in t.use_cases]

    return (matching + others)[:8]


# Category → UseCase mapping for marketplace templates
_CATEGORY_USE_CASE_MAP: dict[str, list[str]] = {
    "security": [UseCase.SECURITY_AUDIT.value, UseCase.COMPLIANCE.value],
    "legal": [UseCase.POLICY_REVIEW.value, UseCase.COMPLIANCE.value],
    "sme": [UseCase.TEAM_DECISIONS.value, UseCase.VENDOR_SELECTION.value],
    "research": [UseCase.GENERAL.value, UseCase.TECHNICAL_PLANNING.value],
    "data": [UseCase.TECHNICAL_PLANNING.value],
    "content": [UseCase.GENERAL.value],
    "quickstart": [UseCase.GENERAL.value],
}

# Pattern → default agent/round estimates
_PATTERN_DEFAULTS: dict[str, tuple[int, int, int]] = {
    # (agents_count, rounds, estimated_minutes)
    "debate": (3, 2, 4),
    "review_cycle": (4, 3, 6),
    "pipeline": (3, 2, 5),
    "hive_mind": (4, 2, 5),
    "map_reduce": (3, 2, 5),
}


def _load_marketplace_templates() -> list[StarterTemplate]:
    """Load marketplace templates and convert to StarterTemplate format."""
    try:
        from aragora.server.handlers.template_marketplace import (
            _marketplace_templates,
            _seed_marketplace_templates,
        )

        _seed_marketplace_templates()

        return [_marketplace_to_starter(t) for t in _marketplace_templates.values()]
    except (ImportError, TypeError, ValueError, KeyError, AttributeError) as exc:
        logger.debug("Marketplace templates unavailable, using starters only: %s", exc)
        return []


def _marketplace_to_starter(t: Any) -> StarterTemplate:
    """Convert a MarketplaceTemplate to a StarterTemplate."""
    agents, rounds, minutes = _PATTERN_DEFAULTS.get(t.pattern, (3, 2, 5))
    return StarterTemplate(
        id=t.id,
        name=t.name,
        description=t.description,
        use_cases=_CATEGORY_USE_CASE_MAP.get(t.category, [UseCase.GENERAL.value]),
        agents_count=agents,
        rounds=rounds,
        estimated_minutes=minutes,
        example_prompt=t.description,
        tags=t.tags[:5] if t.tags else [],
        difficulty="beginner" if t.category == "quickstart" else "intermediate",
    )


def _track_event(
    event_type: str,
    user_id: str,
    organization_id: str | None,
    data: dict[str, Any],
):
    """Track onboarding analytics event."""
    with _analytics_lock:
        _analytics_events.append(
            {
                "event_type": event_type,
                "user_id": user_id,
                "organization_id": organization_id,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        # Keep only last 10000 events
        if len(_analytics_events) > 10000:
            _analytics_events.pop(0)


# =============================================================================
# Handlers
# =============================================================================


@require_permission("onboarding:read")
async def handle_get_flow(
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Get current onboarding flow state.

    GET /api/v1/onboarding/flow
    """
    try:
        # Try persistent storage first, fall back to in-memory
        repo = get_onboarding_repository()
        flow_data = repo.get_flow(user_id, organization_id)

        if flow_data:
            # Convert dict from repo to OnboardingState for compatibility
            flow = OnboardingState(
                id=flow_data["id"],
                user_id=flow_data["user_id"],
                organization_id=flow_data["org_id"],
                current_step=OnboardingStep(flow_data["current_step"]),
                completed_steps=flow_data["completed_steps"],
                use_case=flow_data["use_case"],
                selected_template_id=flow_data["selected_template"],
                first_debate_id=flow_data["first_debate_id"],
                quick_start_profile=flow_data["quick_start_profile"],
                team_invites=flow_data.get("metadata", {}).get("team_invites", []),
                started_at=flow_data["started_at"],
                updated_at=flow_data["updated_at"],
                completed_at=flow_data["completed_at"],
                skipped=flow_data.get("metadata", {}).get("skipped", False),
                metadata=flow_data.get("metadata", {}),
            )
        else:
            # Fall back to in-memory storage for backward compatibility
            flow_key = f"{user_id}:{organization_id or 'personal'}"
            with _onboarding_lock:
                flow = _onboarding_flows.get(flow_key)

        if not flow:
            return success_response(
                {
                    "exists": False,
                    "needs_onboarding": True,
                    "message": "No onboarding in progress",
                }
            )

        # Get recommended templates based on use case
        templates = _get_recommended_templates(flow.use_case)

        return success_response(
            {
                "exists": True,
                "needs_onboarding": flow.completed_at is None and not flow.skipped,
                "flow": {
                    "id": flow.id,
                    "current_step": flow.current_step.value,
                    "completed_steps": flow.completed_steps,
                    "use_case": flow.use_case,
                    "selected_template_id": flow.selected_template_id,
                    "first_debate_id": flow.first_debate_id,
                    "quick_start_profile": flow.quick_start_profile,
                    "team_invites_count": len(flow.team_invites),
                    "started_at": flow.started_at,
                    "updated_at": flow.updated_at,
                    "completed_at": flow.completed_at,
                    "skipped": flow.skipped,
                    "progress_percentage": int(
                        len(flow.completed_steps) / len(_get_step_order()) * 100
                    ),
                },
                "recommended_templates": [asdict(t) for t in templates],
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        logger.exception("Failed to get onboarding flow")
        return error_response("Failed to retrieve flow", status=500)


@require_permission("onboarding:create")
async def handle_init_flow(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Initialize a new onboarding flow.

    POST /api/v1/onboarding/flow
    Body: {
        use_case: str (optional),
        quick_start_profile: str (optional),
        skip_to_step: str (optional)
    }
    """
    try:
        use_case = data.get("use_case")
        quick_start_profile = data.get("quick_start_profile")
        skip_to_step = data.get("skip_to_step")

        flow_key = f"{user_id}:{organization_id or 'personal'}"
        flow_id = f"onb_{secrets.token_hex(8)}"
        now = datetime.now(timezone.utc).isoformat()

        # Determine starting step
        starting_step = OnboardingStep.WELCOME
        if skip_to_step:
            try:
                starting_step = OnboardingStep(skip_to_step)
            except ValueError:
                pass

        # Apply quick-start profile if provided
        template_id = None
        if quick_start_profile and quick_start_profile in QUICK_START_CONFIGS:
            config = QUICK_START_CONFIGS[quick_start_profile]
            template_id = config.get("default_template")

        flow = OnboardingState(
            id=flow_id,
            user_id=user_id,
            organization_id=organization_id,
            current_step=starting_step,
            completed_steps=[],
            use_case=use_case,
            selected_template_id=template_id,
            first_debate_id=None,
            quick_start_profile=quick_start_profile,
            team_invites=[],
            started_at=now,
            updated_at=now,
            completed_at=None,
            skipped=False,
            metadata={},
        )

        # Save to persistent storage
        repo = get_onboarding_repository()
        repo.create_flow(
            user_id=user_id,
            org_id=organization_id,
            current_step=starting_step.value,
            use_case=use_case,
            metadata={
                "quick_start_profile": quick_start_profile,
                "selected_template": template_id,
                "team_invites": [],
                "skipped": False,
            },
        )

        # Also save to in-memory for backward compatibility
        with _onboarding_lock:
            _onboarding_flows[flow_key] = flow

        _track_event(
            "onboarding_started",
            user_id,
            organization_id,
            {
                "flow_id": flow_id,
                "use_case": use_case,
                "quick_start_profile": quick_start_profile,
            },
        )

        templates = _get_recommended_templates(use_case)

        return success_response(
            {
                "flow_id": flow_id,
                "current_step": starting_step.value,
                "use_case": use_case,
                "quick_start_profile": quick_start_profile,
                "recommended_templates": [asdict(t) for t in templates],
                "message": "Onboarding flow initialized",
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        logger.exception("Failed to initialize onboarding")
        return error_response("Initialization failed", status=500)


@require_permission("onboarding:update")
async def handle_update_step(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Update onboarding step progress.

    PUT /api/v1/onboarding/flow/step
    Body: {
        action: "next" | "previous" | "complete" | "skip",
        step_data: dict (optional) - Data collected in current step,
        jump_to_step: str (optional) - Specific step to jump to
    }
    """
    try:
        action = data.get("action", "next")
        step_data = data.get("step_data", {})
        jump_to_step = data.get("jump_to_step")

        flow_key = f"{user_id}:{organization_id or 'personal'}"

        with _onboarding_lock:
            flow = _onboarding_flows.get(flow_key)

            if not flow:
                return error_response("No onboarding flow found", status=404)

            now = datetime.now(timezone.utc).isoformat()
            current_step = flow.current_step

            # Handle different actions
            if action == "skip":
                flow.skipped = True
                flow.completed_at = now

            elif action == "complete":
                # Mark all steps as completed
                flow.completed_steps = [s.value for s in _get_step_order()]
                flow.current_step = OnboardingStep.COMPLETION
                flow.completed_at = now

            elif action == "previous":
                steps = _get_step_order()
                idx = steps.index(current_step)
                if idx > 0:
                    flow.current_step = steps[idx - 1]

            elif jump_to_step:
                try:
                    flow.current_step = OnboardingStep(jump_to_step)
                except ValueError:
                    return error_response(f"Invalid step: {jump_to_step}", status=400)

            else:  # action == "next"
                # Mark current step as completed
                if current_step.value not in flow.completed_steps:
                    flow.completed_steps.append(current_step.value)

                # Store step data in metadata
                if step_data:
                    flow.metadata[current_step.value] = step_data

                    # Extract specific data for common fields
                    if current_step == OnboardingStep.USE_CASE:
                        flow.use_case = step_data.get("use_case")
                    elif current_step == OnboardingStep.TEMPLATE_SELECT:
                        flow.selected_template_id = step_data.get("template_id")
                    elif current_step == OnboardingStep.FIRST_DEBATE:
                        flow.first_debate_id = step_data.get("debate_id")
                    elif current_step == OnboardingStep.TEAM_INVITE:
                        flow.team_invites = step_data.get("invites", [])

                # Move to next step
                next_step = _get_next_step(current_step)
                flow.current_step = next_step

                # Check if completed
                if next_step == OnboardingStep.COMPLETION:
                    if OnboardingStep.COMPLETION.value not in flow.completed_steps:
                        flow.completed_steps.append(OnboardingStep.COMPLETION.value)
                    flow.completed_at = now

            flow.updated_at = now

        # Sync to persistent storage
        _sync_flow_to_repo(flow)

        _track_event(
            "step_updated",
            user_id,
            organization_id,
            {
                "flow_id": flow.id,
                "action": action,
                "from_step": current_step.value,
                "to_step": flow.current_step.value,
                "completed_steps": list(flow.completed_steps),
            },
        )

        return success_response(
            {
                "current_step": flow.current_step.value,
                "completed_steps": flow.completed_steps,
                "progress_percentage": int(
                    len(flow.completed_steps) / len(_get_step_order()) * 100
                ),
                "is_complete": flow.completed_at is not None,
                "is_skipped": flow.skipped,
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError):
        logger.exception("Failed to update step")
        return error_response("Update operation failed", status=500)


@require_permission("onboarding:read")
async def handle_get_templates(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Get recommended starter templates.

    GET /api/v1/onboarding/templates
    Query params:
        use_case: str (optional)
        profile: str (optional) - Quick-start profile
    """
    try:
        use_case = data.get("use_case")
        profile = data.get("profile")

        templates = _get_recommended_templates(use_case)

        # If profile specified, prioritize its templates
        if profile and profile in QUICK_START_CONFIGS:
            config = QUICK_START_CONFIGS[profile]
            suggested_ids = config.get("suggested_templates", [])

            # Reorder to put suggested first
            suggested = [t for t in templates if t.id in suggested_ids]
            others = [t for t in templates if t.id not in suggested_ids]
            templates = suggested + others

        return success_response(
            {
                "templates": [asdict(t) for t in templates],
                "total": len(templates),
                "use_case": use_case,
                "profile": profile,
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError):
        logger.exception("Failed to get templates")
        return error_response("Failed to retrieve templates", status=500)


@require_permission("debates:create")
async def handle_first_debate(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Start a guided first debate.

    POST /api/v1/onboarding/first-debate
    Body: {
        template_id: str (optional),
        topic: str (optional) - Custom topic if not using template,
        use_example: bool (optional) - Use template's example prompt
    }
    """
    try:
        template_id = data.get("template_id")
        topic = data.get("topic")
        use_example = data.get("use_example", False)

        flow_key = f"{user_id}:{organization_id or 'personal'}"

        # Find template if specified
        template = None
        if template_id:
            template = next((t for t in STARTER_TEMPLATES if t.id == template_id), None)

        # Determine the debate topic
        if not topic:
            if template and use_example:
                topic = template.example_prompt
            elif template:
                topic = f"Let's discuss: {template.name}"
            else:
                topic = "What are the trade-offs between building vs buying software solutions?"

        # Prepare debate configuration with receipt generation enabled
        debate_config = {
            "topic": topic,
            "rounds": template.rounds if template else 2,
            "agents_count": template.agents_count if template else 3,
            "is_onboarding": True,
            # Enable receipt generation for onboarding - users should see a receipt
            "enable_receipt_generation": True,
            "receipt_min_confidence": 0.5,  # Lower threshold for first debate
        }

        # Create the debate (in production, this would call the debate service)
        debate_id = f"debate_{secrets.token_hex(8)}"

        # Update onboarding flow
        with _onboarding_lock:
            flow = _onboarding_flows.get(flow_key)
            if flow:
                flow.first_debate_id = debate_id
                flow.selected_template_id = template_id
                flow.updated_at = datetime.now(timezone.utc).isoformat()

        # Sync to persistent storage
        if flow:
            _sync_flow_to_repo(flow)

        _track_event(
            "first_debate_started",
            user_id,
            organization_id,
            {
                "flow_id": flow.id if flow else None,
                "debate_id": debate_id,
                "template_id": template_id,
                "use_example": use_example,
            },
        )

        return success_response(
            {
                "debate_id": debate_id,
                "topic": topic,
                "config": debate_config,
                "template": asdict(template) if template else None,
                "message": "First debate created successfully",
                "next_steps": [
                    "Watch the agents debate your topic",
                    "See how consensus emerges",
                    "View your decision receipt when complete",
                ],
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError):
        logger.exception("Failed to start first debate")
        return error_response("Debate start failed", status=500)


@require_permission("debates:create")
async def handle_quick_debate(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    One-click quick debate creation for onboarding.

    POST /api/v1/onboarding/quick-debate
    Body: {
        template_id: str (optional, default: "express_onboarding"),
        topic: str (optional, use template example if not provided),
        profile: str (optional, quick-start profile to use for agents)
    }

    Returns:
        debate_id, websocket_url, estimated_duration, agents used
    """
    try:
        from aragora.server.debate_controller import DebateController, DebateRequest
        from aragora.server.debate_factory import DebateFactory
        from aragora.server.stream import SyncEventEmitter

        template_id = data.get("template_id", "express_onboarding")
        topic = data.get("topic")
        profile = data.get("profile")

        # Find template
        template = next(
            (t for t in STARTER_TEMPLATES if t.id == template_id),
            STARTER_TEMPLATES[-1],  # Default to express template
        )

        # Determine topic
        if not topic:
            topic = template.example_prompt

        flow_key = f"{user_id}:{organization_id or 'personal'}"
        flow_id: str | None = None
        with _onboarding_lock:
            existing_flow = _onboarding_flows.get(flow_key)
            if existing_flow:
                flow_id = existing_flow.id

        if flow_id is None:
            try:
                repo_flow = get_onboarding_repository().get_flow(user_id, organization_id)
                if repo_flow and isinstance(repo_flow.get("id"), str):
                    flow_id = repo_flow["id"]
            except (KeyError, TypeError, AttributeError, OSError):
                flow_id = None

        # Determine agents based on profile or template
        if profile and profile in QUICK_START_CONFIGS:
            config = QUICK_START_CONFIGS[profile]
            agents = config.get("default_agents", ["claude", "gpt-4"])
        else:
            # Use minimal agents for quick onboarding
            agents = ["anthropic-api", "openai-api"]

        # Limit agents to template's count
        agents = agents[: template.agents_count]
        agents_str = ",".join(agents)

        # Create debate request with light format for speed
        request = DebateRequest(
            question=topic,
            agents_str=agents_str,
            rounds=template.rounds,
            consensus="judge",
            debate_format="light",  # Always light for onboarding speed
            metadata={
                "is_onboarding": True,
                "user_id": user_id,
                "organization_id": organization_id,
                "flow_id": flow_id,
                "template_id": template_id,
            },
        )

        # Create controller and start debate
        emitter = SyncEventEmitter()
        factory = DebateFactory()
        controller = DebateController(factory=factory, emitter=emitter)

        response = controller.start_debate(request)

        if not response.success:
            return error_response(
                response.error or "Failed to start debate",
                status=response.status_code,
            )

        # Update onboarding flow
        with _onboarding_lock:
            flow = _onboarding_flows.get(flow_key)
            if flow:
                flow.first_debate_id = response.debate_id
                flow.selected_template_id = template_id
                flow.current_step = OnboardingStep.FIRST_DEBATE
                flow.updated_at = datetime.now(timezone.utc).isoformat()

        if flow:
            flow_id = flow.id

        _track_event(
            "quick_debate_started",
            user_id,
            organization_id,
            {
                "flow_id": flow_id,
                "debate_id": response.debate_id,
                "template_id": template_id,
                "profile": profile,
                "agents": agents,
            },
        )

        return success_response(
            {
                "debate_id": response.debate_id,
                "websocket_url": f"/ws/debates/{response.debate_id}",
                "topic": topic,
                "agents": agents,
                "rounds": template.rounds,
                "estimated_duration_seconds": template.estimated_minutes * 60,
                "template": asdict(template),
                "message": "Quick debate started successfully",
            }
        )

    except (ImportError, KeyError, ValueError, TypeError, AttributeError, ConnectionError, OSError):
        logger.exception("Failed to start quick debate")
        return error_response("Quick debate start failed", status=500)


@require_permission("onboarding:create")
async def handle_quick_start(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Apply quick-start configuration for immediate value.

    POST /api/v1/onboarding/quick-start
    Body: {
        profile: str - Quick-start profile (developer, security, executive, etc.)
    }
    """
    try:
        profile = data.get("profile")

        if not profile or profile not in QUICK_START_CONFIGS:
            return error_response(
                f"Invalid profile. Must be one of: {', '.join(QUICK_START_CONFIGS.keys())}",
                status=400,
            )

        config = QUICK_START_CONFIGS[profile]
        flow_key = f"{user_id}:{organization_id or 'personal'}"
        now = datetime.now(timezone.utc).isoformat()

        # Create or update flow with quick-start settings
        with _onboarding_lock:
            flow = _onboarding_flows.get(flow_key)

            if not flow:
                flow = OnboardingState(
                    id=f"onb_{secrets.token_hex(8)}",
                    user_id=user_id,
                    organization_id=organization_id,
                    current_step=OnboardingStep.FIRST_DEBATE,
                    completed_steps=[
                        OnboardingStep.WELCOME.value,
                        OnboardingStep.USE_CASE.value,
                    ],
                    use_case=config.get("focus_areas", ["general"])[0],
                    selected_template_id=config["default_template"],
                    first_debate_id=None,
                    quick_start_profile=profile,
                    team_invites=[],
                    started_at=now,
                    updated_at=now,
                    completed_at=None,
                    skipped=False,
                    metadata={"quick_start": True},
                )
                _onboarding_flows[flow_key] = flow
                # Create in repository as well
                repo = get_onboarding_repository()
                repo.create_flow(
                    user_id=user_id,
                    org_id=organization_id,
                    current_step=OnboardingStep.FIRST_DEBATE.value,
                    use_case=config.get("focus_areas", ["general"])[0],
                    metadata={
                        "quick_start": True,
                        "quick_start_profile": profile,
                        "selected_template": config["default_template"],
                        "team_invites": [],
                        "skipped": False,
                    },
                )
            else:
                flow.quick_start_profile = profile
                flow.selected_template_id = config["default_template"]
                flow.current_step = OnboardingStep.FIRST_DEBATE
                flow.updated_at = now

        # Sync to persistent storage
        _sync_flow_to_repo(flow)

        # Get the default template
        template = next(
            (t for t in STARTER_TEMPLATES if t.id == config["default_template"]),
            STARTER_TEMPLATES[0],
        )

        _track_event(
            "quick_start_applied",
            user_id,
            organization_id,
            {
                "profile": profile,
            },
        )

        return success_response(
            {
                "profile": profile,
                "config": config,
                "default_template": asdict(template),
                "suggested_templates": [
                    asdict(t)
                    for t in STARTER_TEMPLATES
                    if t.id in config.get("suggested_templates", [])
                ],
                "message": f"Quick-start profile '{profile}' applied",
                "next_action": {
                    "type": "start_debate",
                    "template_id": template.id,
                    "example_prompt": template.example_prompt,
                },
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        logger.exception("Failed to apply quick-start")
        return error_response("Quick-start application failed", status=500)


@require_permission("analytics:read")
async def handle_analytics(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str | None = None,
) -> HandlerResult:
    """
    Get onboarding funnel analytics.

    GET /api/v1/onboarding/analytics
    """
    try:
        with _analytics_lock:
            # Filter events for this organization if specified
            events = [
                e
                for e in _analytics_events
                if not organization_id or e.get("organization_id") == organization_id
            ]

        # Calculate funnel metrics
        started = len([e for e in events if e["event_type"] == "onboarding_started"])
        first_debate = len(
            [
                e
                for e in events
                if e["event_type"] in {"first_debate_started", "quick_debate_started"}
            ]
        )
        completed = len(
            [
                e
                for e in events
                if e["event_type"] == "step_updated"
                and e.get("data", {}).get("to_step") == "completion"
            ]
        )

        started_by_flow: dict[str, datetime] = {}
        reached_by_flow: dict[str, set[str]] = {}
        completed_by_flow: dict[str, set[str]] = {}
        first_debate_by_flow: dict[str, datetime] = {}
        first_receipt_by_flow: dict[str, datetime] = {}
        valid_steps = {step.value for step in _get_step_order()}

        for event in events:
            event_type = event.get("event_type")
            payload = event.get("data", {})
            flow_id = payload.get("flow_id") if isinstance(payload, dict) else None
            event_time = _parse_event_timestamp(event.get("timestamp"))

            if event_type == "onboarding_started" and isinstance(flow_id, str) and event_time:
                previous = started_by_flow.get(flow_id)
                started_by_flow[flow_id] = (
                    event_time if previous is None or event_time < previous else previous
                )
                reached_by_flow.setdefault(flow_id, set()).add(OnboardingStep.WELCOME.value)
                continue

            if not isinstance(payload, dict) or not isinstance(flow_id, str):
                continue

            reached = reached_by_flow.setdefault(flow_id, set())

            from_step = payload.get("from_step")
            if isinstance(from_step, str) and from_step in valid_steps:
                reached.add(from_step)

            to_step = payload.get("to_step")
            if isinstance(to_step, str) and to_step in valid_steps:
                reached.add(to_step)

            completed_steps = payload.get("completed_steps")
            if isinstance(completed_steps, list):
                completed_filtered = {
                    step
                    for step in completed_steps
                    if isinstance(step, str) and step in valid_steps
                }
                if completed_filtered:
                    reached.update(completed_filtered)
                    existing_completed = completed_by_flow.get(flow_id, set())
                    if len(completed_filtered) >= len(existing_completed):
                        completed_by_flow[flow_id] = completed_filtered

            if (
                event_type in {"first_debate_started", "quick_debate_started"}
                and event_time
                and flow_id in started_by_flow
            ):
                reached.add(OnboardingStep.FIRST_DEBATE.value)
                previous = first_debate_by_flow.get(flow_id)
                first_debate_by_flow[flow_id] = (
                    event_time if previous is None or event_time < previous else previous
                )
            elif (
                event_type == "first_receipt_generated"
                and event_time
                and flow_id in started_by_flow
            ):
                reached.add(OnboardingStep.RECEIPT_REVIEW.value)
                previous = first_receipt_by_flow.get(flow_id)
                first_receipt_by_flow[flow_id] = (
                    event_time if previous is None or event_time < previous else previous
                )

        debate_durations: list[float] = []
        receipt_durations: list[float] = []
        for flow_id, started_at in started_by_flow.items():
            debate_at = first_debate_by_flow.get(flow_id)
            if debate_at and debate_at >= started_at:
                debate_durations.append((debate_at - started_at).total_seconds())

            receipt_at = first_receipt_by_flow.get(flow_id)
            if receipt_at and receipt_at >= started_at:
                receipt_durations.append((receipt_at - started_at).total_seconds())

        # Get step completion counts by flow progression snapshots
        step_counts: dict[str, int] = {}
        for step in _get_step_order():
            step_counts[step.value] = sum(
                1 for completed_steps in completed_by_flow.values() if step.value in completed_steps
            )

        step_drop_off: dict[str, dict[str, Any]] = {}
        ordered_steps = _get_step_order()
        for idx, step in enumerate(ordered_steps):
            reached = sum(1 for seen in reached_by_flow.values() if step.value in seen)
            if idx + 1 < len(ordered_steps):
                next_step = ordered_steps[idx + 1]
                advanced = sum(
                    1
                    for seen in reached_by_flow.values()
                    if step.value in seen and next_step.value in seen
                )
                dropped = max(reached - advanced, 0)
                drop_off_rate = (dropped / reached * 100.0) if reached > 0 else 0.0
            else:
                advanced = reached
                dropped = 0
                drop_off_rate = 0.0

            step_drop_off[step.value] = {
                "reached": reached,
                "advanced": advanced,
                "dropped": dropped,
                "drop_off_rate_percent": round(drop_off_rate, 2),
            }

        parsed_times = [
            parsed
            for parsed in (_parse_event_timestamp(e.get("timestamp")) for e in events)
            if parsed
        ]
        earliest = min(parsed_times).isoformat() if parsed_times else None
        latest = max(parsed_times).isoformat() if parsed_times else None

        return success_response(
            {
                "funnel": {
                    "started": started,
                    "first_debate": first_debate,
                    "completed": completed,
                    "completion_rate": (completed / started * 100) if started > 0 else 0,
                },
                "step_completion": step_counts,
                "step_drop_off": step_drop_off,
                "timing": {
                    "time_to_first_debate_seconds": _summarize_durations_seconds(debate_durations),
                    "time_to_first_receipt_seconds": _summarize_durations_seconds(
                        receipt_durations
                    ),
                },
                "total_events": len(events),
                "time_range": {
                    "earliest": earliest,
                    "latest": latest,
                },
            }
        )

    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        logger.exception("Failed to get analytics")
        return error_response("Failed to retrieve analytics", status=500)


# =============================================================================
# Handler Registration
# =============================================================================


def get_onboarding_handlers() -> dict[str, Any]:
    """Get all onboarding handlers for registration."""
    return {
        "get_flow": handle_get_flow,
        "init_flow": handle_init_flow,
        "update_step": handle_update_step,
        "get_templates": handle_get_templates,
        "first_debate": handle_first_debate,
        "quick_start": handle_quick_start,
        "quick_debate": handle_quick_debate,
        "analytics": handle_analytics,
    }


class OnboardingHandler:
    """Handler class for onboarding endpoints (for handler registry)."""

    ROUTES = [
        "/api/onboarding/flow",
        "/api/onboarding/templates",
        "/api/onboarding/first-debate",
        "/api/onboarding/quick-start",
        "/api/onboarding/quick-debate",
        "/api/onboarding/analytics",
        "/api/v1/onboarding/flow/step",
        "/api/v1/templates/recommended",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None):
        """Initialize handler with server context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        # Strip version prefix if present
        normalized = path
        if path.startswith("/api/v1/"):
            normalized = "/api/" + path[8:]
        elif path.startswith("/api/v2/"):
            normalized = "/api/" + path[8:]
        return normalized.startswith("/api/onboarding/")

    async def handle(
        self,
        path: str,
        method: str,
        data: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        user_id: str = "default",
        organization_id: str | None = None,
    ) -> HandlerResult:
        """Route request to appropriate handler function."""
        # Normalize path
        normalized = path
        if path.startswith("/api/v1/"):
            normalized = "/api/" + path[8:]
        elif path.startswith("/api/v2/"):
            normalized = "/api/" + path[8:]

        data = data or {}
        query_params = query_params or {}

        # Route based on path and method
        if normalized == "/api/onboarding/flow":
            if method == "GET":
                return await handle_get_flow(user_id, organization_id)
            elif method == "POST":
                return await handle_init_flow(data, user_id, organization_id)

        if normalized == "/api/onboarding/flow/step" and method == "PUT":
            return await handle_update_step(data, user_id, organization_id)

        if normalized == "/api/onboarding/templates" and method == "GET":
            return await handle_get_templates(query_params, user_id, organization_id)

        if normalized == "/api/onboarding/first-debate" and method == "POST":
            return await handle_first_debate(data, user_id, organization_id)

        if normalized == "/api/onboarding/quick-start" and method == "POST":
            return await handle_quick_start(data, user_id, organization_id)

        if normalized == "/api/onboarding/quick-debate" and method == "POST":
            return await handle_quick_debate(data, user_id, organization_id)

        if normalized == "/api/onboarding/analytics" and method == "GET":
            return await handle_analytics(query_params, user_id, organization_id)

        return error_response(f"Unknown onboarding endpoint: {path}", status=404)


__all__ = [
    "handle_get_flow",
    "handle_init_flow",
    "handle_update_step",
    "handle_get_templates",
    "handle_first_debate",
    "handle_quick_start",
    "handle_quick_debate",
    "handle_analytics",
    "get_onboarding_handlers",
    "OnboardingHandler",
    "OnboardingStep",
    "UseCase",
    "QuickStartProfile",
    "StarterTemplate",
    "OnboardingState",
    "STARTER_TEMPLATES",
    "QUICK_START_CONFIGS",
]
