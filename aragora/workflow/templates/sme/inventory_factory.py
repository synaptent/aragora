"""Inventory and vendor workflow factory functions.

Provides workflow templates for inventory monitoring, alerts,
vendor evaluation, and tool selection processes.
"""

from __future__ import annotations

from datetime import datetime

from aragora.workflow.types import (
    StepDefinition,
    WorkflowCategory,
    WorkflowDefinition,
)


def create_inventory_alert_workflow(
    alert_threshold: int = 20,
    auto_reorder: bool = False,
    notification_channels: list[str] | None = None,
    categories: list[str] | None = None,
) -> WorkflowDefinition:
    """Create an inventory monitoring and alert workflow.

    Args:
        alert_threshold: Percentage of safety stock to trigger alert
        auto_reorder: Whether to auto-create purchase orders
        notification_channels: Channels for alerts (email, slack, sms)
        categories: Product categories to monitor (all if None)

    Returns:
        WorkflowDefinition ready for execution

    Example:
        workflow = create_inventory_alert_workflow(
            alert_threshold=25,
            auto_reorder=True,
            notification_channels=["email", "slack"],
        )
        result = await engine.execute(workflow)
    """
    workflow_id = f"inventory_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    channels = notification_channels or ["email"]

    return WorkflowDefinition(
        id=workflow_id,
        name="Inventory Alert Check",
        description="Monitor inventory levels and send alerts",
        category=WorkflowCategory.GENERAL,
        tags=["sme", "inventory", "alerts", "supply-chain"],
        inputs={
            "alert_threshold": alert_threshold,
            "auto_reorder": auto_reorder,
            "notification_channels": channels,
            "categories": categories,
        },
        steps=[
            StepDefinition(
                id="fetch",
                name="Fetch Inventory",
                step_type="task",
                config={
                    "handler": "fetch_inventory_data",
                    "categories": categories,
                },
                next_steps=["analyze"],
            ),
            StepDefinition(
                id="analyze",
                name="Analyze Levels",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": f"Analyze inventory with {alert_threshold}% threshold",
                },
                next_steps=["calculate"],
            ),
            StepDefinition(
                id="calculate",
                name="Calculate Reorder",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": "Calculate optimal reorder quantities",
                },
                next_steps=["alert"],
            ),
            StepDefinition(
                id="alert",
                name="Send Alerts",
                step_type="parallel",
                config={
                    "channels": channels,
                },
                next_steps=["reorder"] if auto_reorder else ["store"],
            ),
            StepDefinition(
                id="reorder",
                name="Create Orders",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": "Generate purchase orders",
                },
                next_steps=["submit"],
            ),
            StepDefinition(
                id="submit",
                name="Submit Orders",
                step_type="task",
                config={
                    "handler": "submit_purchase_orders",
                },
                next_steps=["store"],
            ),
            StepDefinition(
                id="store",
                name="Store Results",
                step_type="memory_write",
                config={
                    "collection": "inventory_checks",
                },
                next_steps=[],
            ),
        ],
        entry_step="fetch",
    )


def daily_inventory_check(
    slack_channel: str | None = None,
) -> WorkflowDefinition:
    """Create a daily inventory check workflow.

    Args:
        slack_channel: Optional Slack channel for alerts

    Returns:
        WorkflowDefinition for daily inventory monitoring
    """
    channels = ["email"]
    if slack_channel:
        channels.append("slack")

    return create_inventory_alert_workflow(
        alert_threshold=20,
        auto_reorder=False,
        notification_channels=channels,
    )


def create_vendor_evaluation_workflow(
    vendor_name: str,
    evaluation_criteria: list[str] | None = None,
    budget_range: str | None = None,
    timeline: str = "30 days",
    require_approval: bool = True,
) -> WorkflowDefinition:
    """Create a vendor evaluation workflow.

    Evaluates potential vendors based on criteria like cost, reliability,
    quality, and fit with business needs.

    Args:
        vendor_name: Name of vendor to evaluate
        evaluation_criteria: Custom criteria (defaults to standard set)
        budget_range: Budget constraints (e.g., "$10k-$50k")
        timeline: Decision timeline
        require_approval: Whether to require human approval

    Returns:
        WorkflowDefinition for vendor evaluation

    Example:
        workflow = create_vendor_evaluation_workflow(
            vendor_name="Acme Corp",
            evaluation_criteria=["price", "support", "integration"],
            budget_range="$20k-$40k",
        )
    """
    workflow_id = (
        f"vendor_eval_{vendor_name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}"
    )
    criteria = evaluation_criteria or [
        "pricing",
        "reliability",
        "support",
        "integration",
        "scalability",
    ]

    return WorkflowDefinition(
        id=workflow_id,
        name=f"Vendor Evaluation: {vendor_name}",
        description=f"Evaluate {vendor_name} as a potential vendor",
        category=WorkflowCategory.GENERAL,
        tags=["sme", "vendor", "evaluation", "decision"],
        inputs={
            "vendor_name": vendor_name,
            "criteria": criteria,
            "budget_range": budget_range,
            "timeline": timeline,
        },
        steps=[
            StepDefinition(
                id="gather",
                name="Gather Information",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": f"Research {vendor_name}: pricing, reviews, capabilities",
                },
                next_steps=["debate"],
            ),
            StepDefinition(
                id="debate",
                name="Multi-Agent Evaluation",
                step_type="debate",
                config={
                    "agents": ["claude", "gpt-4", "gemini"],
                    "topic": f"Should we proceed with {vendor_name}?",
                    "rounds": 3,
                    "criteria": criteria,
                },
                next_steps=["score"],
            ),
            StepDefinition(
                id="score",
                name="Score Criteria",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": "Score vendor on each criterion (1-10)",
                },
                next_steps=["recommend"],
            ),
            StepDefinition(
                id="recommend",
                name="Generate Recommendation",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": "Synthesize debate and generate recommendation",
                },
                next_steps=["review"] if require_approval else ["store"],
            ),
            StepDefinition(
                id="review",
                name="Human Review",
                step_type="human_checkpoint",
                config={
                    "checkpoint_type": "approval",
                    "title": f"Review {vendor_name} Evaluation",
                },
                next_steps=["store"],
            ),
            StepDefinition(
                id="store",
                name="Store Decision",
                step_type="memory_write",
                config={
                    "collection": "vendor_evaluations",
                },
                next_steps=[],
            ),
        ],
        entry_step="gather",
    )


def create_tool_selection_workflow(
    category: str,
    candidates: list[str],
    requirements: list[str] | None = None,
    budget: str | None = None,
    team_size: int = 10,
) -> WorkflowDefinition:
    """Create a tool selection workflow.

    Uses multi-agent debate to evaluate and compare tools or
    software solutions for a specific category.

    Args:
        category: Tool category (e.g., "CI/CD", "CRM", "Analytics")
        candidates: List of tools to evaluate
        requirements: Must-have requirements
        budget: Budget constraint
        team_size: Number of users

    Returns:
        WorkflowDefinition for tool selection

    Example:
        workflow = create_tool_selection_workflow(
            category="Project Management",
            candidates=["Jira", "Linear", "Asana", "Monday"],
            requirements=["GitHub integration", "Agile support"],
            budget="$50/user/month",
        )
    """
    workflow_id = (
        f"tool_select_{category.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}"
    )
    reqs = requirements or []

    return WorkflowDefinition(
        id=workflow_id,
        name=f"Tool Selection: {category}",
        description=f"Select best {category} tool from {len(candidates)} options",
        category=WorkflowCategory.GENERAL,
        tags=["sme", "tools", "selection", "vendor"],
        inputs={
            "category": category,
            "candidates": candidates,
            "requirements": reqs,
            "budget": budget,
            "team_size": team_size,
        },
        steps=[
            StepDefinition(
                id="research",
                name="Research Tools",
                step_type="parallel",
                config={
                    "sub_steps": [
                        f"research_{c.lower().replace(' ', '_')}" for c in candidates[:4]
                    ],
                },
                next_steps=["debate"],
            ),
            StepDefinition(
                id="debate",
                name="Tool Comparison Debate",
                step_type="debate",
                config={
                    "agents": ["claude", "gpt-4", "gemini"],
                    "topic": f"Which {category} tool is best: {', '.join(candidates)}?",
                    "rounds": 4,
                    "requirements": reqs,
                },
                next_steps=["score"],
            ),
            StepDefinition(
                id="score",
                name="Score Matrix",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": "Create comparison matrix scoring each tool",
                },
                next_steps=["cost"],
            ),
            StepDefinition(
                id="cost",
                name="Cost Analysis",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": f"Calculate TCO for {team_size} users over 1-3 years",
                },
                next_steps=["recommend"],
            ),
            StepDefinition(
                id="recommend",
                name="Final Recommendation",
                step_type="agent",
                config={
                    "agent_type": "claude",
                    "prompt_template": "Generate recommendation with migration plan",
                },
                next_steps=["review"],
            ),
            StepDefinition(
                id="review",
                name="Stakeholder Review",
                step_type="human_checkpoint",
                config={
                    "checkpoint_type": "selection",
                    "title": f"Select {category} tool",
                },
                next_steps=["store"],
            ),
            StepDefinition(
                id="store",
                name="Record Selection",
                step_type="memory_write",
                config={
                    "collection": "tool_selections",
                },
                next_steps=[],
            ),
        ],
        entry_step="research",
    )


__all__ = [
    "create_inventory_alert_workflow",
    "daily_inventory_check",
    "create_vendor_evaluation_workflow",
    "create_tool_selection_workflow",
]
