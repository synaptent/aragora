"""
Email-Specific Agent Personas for Intelligent Inbox Management.

Specialized agents for email prioritization debates:
- SenderReputationAgent: Analyzes sender importance and relationship
- ContentUrgencyAgent: Detects time-sensitive content and deadlines
- ContextRelevanceAgent: Cross-references with user's activities
- BillingCriticalityAgent: Identifies financial/contract-related emails
- TimelineAgent: Considers user's schedule and response patterns

These agents participate in multi-agent debates to reach consensus on
email priority, providing transparent decision receipts.

Usage:
    from aragora.agents.email_agents import (
        SenderReputationAgent,
        ContentUrgencyAgent,
        ContextRelevanceAgent,
        get_email_agent_team,
    )

    # Create specialized team
    team = get_email_agent_team()

    # Or use individual agents
    sender_agent = SenderReputationAgent()
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.agents.base import BaseDebateAgent

logger = logging.getLogger(__name__)


class EmailAgentPersona:
    """Base persona configuration for email agents."""

    def __init__(
        self,
        name: str,
        role: str,
        focus: str,
        priority_bias: str | None = None,
    ):
        self.name = name
        self.role = role
        self.focus = focus
        self.priority_bias = priority_bias

    def get_system_prompt(self) -> str:
        """Generate system prompt for this persona."""
        prompt = f"""You are {self.name}, an AI agent specialized in email prioritization.

ROLE: {self.role}

FOCUS AREA: {self.focus}

YOUR TASK:
Analyze emails and provide priority recommendations (1-5 scale):
1 = CRITICAL: Immediate attention required
2 = HIGH: Important, respond today
3 = MEDIUM: Standard priority
4 = LOW: Can wait, review when time allows
5 = DEFER: Auto-archive candidate

RESPONSE FORMAT:
PRIORITY: [1-5]
CONFIDENCE: [0.0-1.0]
RATIONALE: [Your analysis from your specialized perspective]
KEY_SIGNALS: [Bullet list of signals you detected]

{f"BIAS NOTE: {self.priority_bias}" if self.priority_bias else ""}

Be specific about what signals informed your decision. When uncertain, express lower confidence.
Consider how your specialized perspective complements other agents' analyses."""

        return prompt


class SenderReputationAgent(BaseDebateAgent):
    """
    Analyzes sender importance and relationship history.

    Considers:
    - VIP/executive status
    - Internal vs external sender
    - Past interaction history
    - Response patterns
    - Sender's typical email importance
    """

    def __init__(self, **kwargs: Any) -> None:
        persona = EmailAgentPersona(
            name="SenderReputationAgent",
            role="Sender Relationship Analyst",
            focus="""Evaluate who sent the email and their relationship to the user:
- Is this a VIP (executive, key client, important contact)?
- Is this an internal colleague or external party?
- What is the historical importance of emails from this sender?
- How often does the user respond to this sender?
- Is this sender typically associated with urgent matters?""",
            priority_bias="Tends to weight sender importance heavily - VIP emails get boosted priority",
        )

        super().__init__(
            name="sender_reputation",
            system_prompt=persona.get_system_prompt(),
            **kwargs,
        )
        self._email_persona = persona

    def analyze_sender(self, sender_info: dict[str, Any]) -> dict[str, Any]:
        """
        Pre-analysis of sender information.

        Args:
            sender_info: Dict with email, domain, is_vip, is_internal, etc.

        Returns:
            Analysis dict with reputation_score and signals
        """
        signals = []
        score = 0.5  # Baseline

        email = sender_info.get("email", "")
        sender_info.get("domain", "")

        # VIP check
        if sender_info.get("is_vip"):
            score += 0.3
            signals.append("VIP sender identified")

        # Internal sender
        if sender_info.get("is_internal"):
            score += 0.15
            signals.append("Internal organization sender")

        # High response rate indicates important sender
        response_rate = sender_info.get("response_rate", 0.0)
        if response_rate > 0.8:
            score += 0.15
            signals.append(f"High response rate ({response_rate:.0%})")
        elif response_rate < 0.1:
            score -= 0.1
            signals.append(f"Low response rate ({response_rate:.0%})")

        # Executive domain patterns
        exec_domains = ["ceo", "cfo", "cto", "vp", "director", "president"]
        if any(d in email.lower() for d in exec_domains):
            score += 0.2
            signals.append("Executive email pattern detected")

        # No-reply senders are low priority
        if "noreply" in email.lower() or "no-reply" in email.lower():
            score -= 0.3
            signals.append("No-reply sender (automated)")

        return {
            "reputation_score": max(0.0, min(1.0, score)),
            "signals": signals,
            "recommend_priority": self._score_to_priority(score),
        }

    def _score_to_priority(self, score: float) -> int:
        """Convert reputation score to priority recommendation."""
        if score >= 0.8:
            return 1  # Critical
        elif score >= 0.6:
            return 2  # High
        elif score >= 0.4:
            return 3  # Medium
        elif score >= 0.2:
            return 4  # Low
        else:
            return 5  # Defer


class ContentUrgencyAgent(BaseDebateAgent):
    """
    Detects time-sensitive content and deadlines.

    Analyzes:
    - Urgency keywords (URGENT, ASAP, immediately)
    - Deadline mentions (by EOD, due Friday)
    - Time-sensitive requests
    - Action required indicators
    - Meeting/call scheduling urgency
    """

    def __init__(self, **kwargs):
        persona = EmailAgentPersona(
            name="ContentUrgencyAgent",
            role="Urgency and Deadline Detector",
            focus="""Analyze email content for time-sensitivity:
- Are there explicit deadline mentions (by EOD, due Friday, need by)?
- Does the email use urgency language (URGENT, ASAP, critical)?
- Is there a specific action requested with a timeframe?
- Are there calendar/meeting implications (reschedule needed)?
- What would happen if the user doesn't respond promptly?""",
            priority_bias="Focuses heavily on temporal signals - may boost priority for time-sensitive content",
        )

        super().__init__(
            name="content_urgency",
            system_prompt=persona.get_system_prompt(),
            **kwargs,
        )
        self.persona = persona

    def analyze_urgency(self, email_content: dict[str, Any]) -> dict[str, Any]:
        """
        Pre-analysis of email content for urgency signals.

        Args:
            email_content: Dict with subject, body, snippet

        Returns:
            Analysis dict with urgency_score and detected signals
        """
        import re

        signals = []
        score = 0.3  # Baseline (most emails aren't urgent)

        subject = email_content.get("subject", "")
        body = email_content.get("body", "")
        text = f"{subject} {body}".lower()

        # Urgency keywords
        urgent_keywords = [
            (r"\burgent\b", 0.3, "URGENT keyword"),
            (r"\basap\b", 0.25, "ASAP keyword"),
            (r"\bimmediately\b", 0.25, "Immediately keyword"),
            (r"\bcritical\b", 0.2, "Critical keyword"),
            (r"\bemergency\b", 0.35, "Emergency keyword"),
            (r"\btime.?sensitive\b", 0.2, "Time-sensitive phrase"),
        ]

        for pattern, boost, signal in urgent_keywords:
            if re.search(pattern, text):
                score += boost
                signals.append(signal)

        # Deadline patterns
        deadline_patterns = [
            (r"by\s+(monday|tuesday|wednesday|thursday|friday)", 0.2, "Deadline: day of week"),
            (r"by\s+eod", 0.25, "Deadline: EOD"),
            (r"by\s+end\s+of\s+(day|week)", 0.2, "Deadline: end of period"),
            (r"due\s+(today|tomorrow)", 0.3, "Due: imminent"),
            (r"need\s+(this\s+)?by", 0.2, "Need-by deadline"),
            (r"respond\s+by", 0.2, "Response deadline"),
            (r"expires?\s+(today|tomorrow|soon)", 0.25, "Expiration imminent"),
        ]

        for pattern, boost, signal in deadline_patterns:
            if re.search(pattern, text):
                score += boost
                signals.append(signal)

        # Action required indicators
        action_patterns = [
            (r"action\s+required", 0.15, "Action required"),
            (r"please\s+(review|approve|sign|confirm)", 0.15, "Approval/review needed"),
            (r"waiting\s+(for|on)\s+your", 0.1, "Waiting on user"),
            (r"blocking\s+(on|issue)", 0.2, "Blocker mentioned"),
        ]

        for pattern, boost, signal in action_patterns:
            if re.search(pattern, text):
                score += boost
                signals.append(signal)

        # Question detection (may need response)
        question_count = text.count("?")
        if question_count >= 3:
            score += 0.1
            signals.append(f"Multiple questions ({question_count})")
        elif question_count > 0:
            score += 0.05
            signals.append("Contains question")

        return {
            "urgency_score": max(0.0, min(1.0, score)),
            "signals": signals,
            "deadline_detected": any("Deadline" in s or "Due" in s for s in signals),
            "recommend_priority": self._score_to_priority(score),
        }

    def _score_to_priority(self, score: float) -> int:
        """Convert urgency score to priority recommendation."""
        if score >= 0.7:
            return 1  # Critical
        elif score >= 0.5:
            return 2  # High
        elif score >= 0.35:
            return 3  # Medium
        elif score >= 0.2:
            return 4  # Low
        else:
            return 5  # Defer


class ContextRelevanceAgent(BaseDebateAgent):
    """
    Cross-references email with user's context and activities.

    Integrates:
    - Knowledge Mound queries
    - Current project context
    - Recent Slack activity
    - Calendar proximity
    - Google Drive document activity
    """

    def __init__(self, knowledge_mound=None, **kwargs):
        persona = EmailAgentPersona(
            name="ContextRelevanceAgent",
            role="Cross-Channel Context Analyst",
            focus="""Evaluate how this email relates to user's current context:
- Does this email relate to an active project or priority?
- Is the sender active in related Slack channels?
- Are there recent documents in Drive related to this topic?
- Does this align with upcoming calendar events?
- What's the broader conversation context?""",
            priority_bias="Elevates priority when email connects to active user contexts",
        )

        super().__init__(
            name="context_relevance",
            system_prompt=persona.get_system_prompt(),
            **kwargs,
        )
        self.persona = persona
        self.mound = knowledge_mound

    async def analyze_context(
        self,
        email_content: dict[str, Any],
        sender_email: str,
    ) -> dict[str, Any]:
        """
        Analyze email in context of user's activities.

        Args:
            email_content: Email subject and body
            sender_email: Sender's email address

        Returns:
            Analysis dict with relevance signals
        """
        signals = []
        score = 0.5  # Baseline

        subject = email_content.get("subject", "")
        body = email_content.get("body", "")

        # Query knowledge mound for context
        if self.mound:
            try:
                # Check for related knowledge
                query = f"{subject} {body[:200]}"
                results = await self.mound.query(query, limit=5)

                if results and hasattr(results, "items") and results.items:
                    score += 0.1 * min(len(results.items), 3)
                    signals.append(f"Related to {len(results.items)} known topics")

                # Check sender history
                sender_results = await self.mound.query(
                    f"sender:{sender_email}",
                    limit=3,
                )
                if sender_results and hasattr(sender_results, "items") and sender_results.items:
                    score += 0.1
                    signals.append("Sender in knowledge base")

            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.debug("Context query failed: %s", e)

        # Check for project keywords (would integrate with actual project tracking)
        project_keywords = ["project", "milestone", "sprint", "release", "launch"]
        text = f"{subject} {body}".lower()
        for keyword in project_keywords:
            if keyword in text:
                score += 0.05
                signals.append(f"Project-related keyword: {keyword}")

        return {
            "relevance_score": max(0.0, min(1.0, score)),
            "signals": signals,
            "recommend_priority": self._score_to_priority(score),
        }

    def _score_to_priority(self, score: float) -> int:
        """Convert relevance score to priority recommendation."""
        if score >= 0.75:
            return 2  # High (context alone rarely makes critical)
        elif score >= 0.55:
            return 3  # Medium
        elif score >= 0.35:
            return 4  # Low
        else:
            return 5  # Defer


class BillingCriticalityAgent(BaseDebateAgent):
    """
    Identifies financial and contract-related emails.

    Detects:
    - Invoice and billing notifications
    - Contract deadlines and renewals
    - Payment confirmations/failures
    - Financial reports
    - Subscription changes
    """

    def __init__(self, **kwargs):
        persona = EmailAgentPersona(
            name="BillingCriticalityAgent",
            role="Financial and Contract Analyst",
            focus="""Identify emails with financial or contractual importance:
- Is this related to billing, invoices, or payments?
- Are there contract deadlines or renewal notices?
- Is this about subscription changes or cancellations?
- Are there financial reports or statements?
- Could missing this email have financial consequences?""",
            priority_bias="Elevates priority for financial/legal implications",
        )

        super().__init__(
            name="billing_criticality",
            system_prompt=persona.get_system_prompt(),
            **kwargs,
        )
        self.persona = persona

    def analyze_financial(self, email_content: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze email for financial/contract signals.

        Args:
            email_content: Email subject and body

        Returns:
            Analysis dict with financial signals
        """
        import re

        signals = []
        score = 0.2  # Baseline

        subject = email_content.get("subject", "")
        body = email_content.get("body", "")
        text = f"{subject} {body}".lower()

        # Financial keywords
        financial_patterns = [
            (r"invoice", 0.25, "Invoice mention"),
            (r"payment\s+(due|failed|received)", 0.3, "Payment status"),
            (r"billing", 0.2, "Billing mention"),
            (r"\$\d+", 0.15, "Dollar amount mentioned"),
            (r"subscription\s+(cancel|renew|expir)", 0.25, "Subscription change"),
            (r"contract\s+(sign|renew|expir)", 0.3, "Contract action"),
            (r"overdue", 0.35, "Overdue notice"),
            (r"final\s+notice", 0.4, "Final notice"),
            (r"account\s+(suspend|terminat)", 0.4, "Account threat"),
        ]

        for pattern, boost, signal in financial_patterns:
            if re.search(pattern, text):
                score += boost
                signals.append(signal)

        # Common billing sender domains
        billing_domains = ["billing", "invoice", "payment", "finance", "accounts"]
        sender = email_content.get("from", "").lower()
        for domain in billing_domains:
            if domain in sender:
                score += 0.1
                signals.append(f"Billing-related sender ({domain})")

        return {
            "financial_score": max(0.0, min(1.0, score)),
            "signals": signals,
            "is_financial": score > 0.4,
            "recommend_priority": self._score_to_priority(score),
        }

    def _score_to_priority(self, score: float) -> int:
        """Convert financial score to priority recommendation."""
        if score >= 0.7:
            return 1  # Critical (financial issues are urgent)
        elif score >= 0.5:
            return 2  # High
        elif score >= 0.3:
            return 3  # Medium
        else:
            return 4  # Low


class TimelineAgent(BaseDebateAgent):
    """
    Considers user's schedule and response patterns.

    Analyzes:
    - User's typical response times
    - Current calendar availability
    - Time of day / week patterns
    - Historical response urgency
    """

    def __init__(self, **kwargs):
        persona = EmailAgentPersona(
            name="TimelineAgent",
            role="Schedule and Response Pattern Analyst",
            focus="""Consider timing and response patterns:
- What time/day was this email sent?
- Does this align with user's typical work hours?
- Is user typically quick to respond to similar emails?
- Are there calendar conflicts that affect response time?
- What's the optimal response window for this type of email?""",
            priority_bias="May lower priority for emails that can wait until specific time slots",
        )

        super().__init__(
            name="timeline",
            system_prompt=persona.get_system_prompt(),
            **kwargs,
        )
        self.persona = persona


class CategorizationAgent(BaseDebateAgent):
    """
    Categorizes emails into smart folders.

    Categories:
    - invoices: Financial documents, bills, receipts
    - hr: HR, benefits, payroll
    - newsletters: Marketing, digests
    - projects: Project threads, task updates
    - meetings: Calendar-related
    - support: Customer support tickets
    - security: Security alerts, 2FA
    - receipts: Order confirmations
    - social: Social media notifications
    """

    CATEGORIES = [
        "invoices",
        "hr",
        "newsletters",
        "projects",
        "meetings",
        "support",
        "security",
        "receipts",
        "social",
        "personal",
        "uncategorized",
    ]

    def __init__(self, **kwargs):
        persona = EmailAgentPersona(
            name="CategorizationAgent",
            role="Email Category Classifier",
            focus="""Classify emails into the most appropriate folder:
- INVOICES: Bills, payment requests, financial statements
- HR: Payroll, PTO, benefits, performance reviews
- NEWSLETTERS: Marketing emails, weekly digests, unsubscribe-able content
- PROJECTS: Task updates, code reviews, sprint notifications
- MEETINGS: Calendar invites, reschedule requests, agenda items
- SUPPORT: Customer tickets, help desk responses
- SECURITY: 2FA codes, password resets, security alerts
- RECEIPTS: Order confirmations, shipping notifications
- SOCIAL: LinkedIn, Facebook, Twitter notifications
- PERSONAL: Family, friends, non-work correspondence

Your task is to identify the MOST appropriate category based on content, sender, and context.""",
            priority_bias="Focuses on categorization accuracy over priority",
        )

        super().__init__(
            name="categorization",
            system_prompt=persona.get_system_prompt(),
            **kwargs,
        )
        self.persona = persona

    def analyze_category(self, email_content: dict[str, Any]) -> dict[str, Any]:
        """
        Pre-analysis of email for category signals.

        Args:
            email_content: Dict with subject, body, sender

        Returns:
            Analysis dict with category scores and signals
        """
        import re

        signals = []
        scores = dict.fromkeys(self.CATEGORIES, 0.0)

        subject = email_content.get("subject", "")
        body = email_content.get("body", "")
        sender = email_content.get("from", "")
        text = f"{subject} {body}".lower()

        # Invoice patterns
        if re.search(r"\b(invoice|billing|payment\s+due|\$\d+[\d,]*\.\d{2})\b", text):
            scores["invoices"] += 0.4
            signals.append("Financial patterns detected")

        # HR patterns
        if re.search(r"\b(payroll|pto|benefits|401k|hr@|human.?resources)\b", text):
            scores["hr"] += 0.4
            signals.append("HR-related content")

        # Newsletter patterns
        if re.search(r"\b(unsubscribe|newsletter|weekly\s+digest|view\s+in\s+browser)\b", text):
            scores["newsletters"] += 0.5
            signals.append("Newsletter indicators")

        # Project patterns
        if re.search(r"\b(task|sprint|pull\s+request|code\s+review|jira|asana|github)\b", text):
            scores["projects"] += 0.4
            signals.append("Project management content")

        # Meeting patterns
        if re.search(r"\b(meeting|calendar|invite|agenda|reschedule|zoom|teams)\b", text):
            scores["meetings"] += 0.4
            signals.append("Meeting-related content")

        # Support patterns
        if re.search(r"\b(ticket\s*#|case\s*#|support|help\s+desk|zendesk)\b", text):
            scores["support"] += 0.4
            signals.append("Support ticket indicators")

        # Security patterns
        if re.search(r"\b(2fa|verification\s+code|password|security\s+alert|sign-?in)\b", text):
            scores["security"] += 0.5
            signals.append("Security/auth content")

        # Receipt patterns
        if re.search(r"\b(order\s+(confirm|shipped)|receipt|tracking|delivery)\b", text):
            scores["receipts"] += 0.4
            signals.append("Order/receipt content")

        # Social patterns
        if re.search(r"\b(liked|commented|followed|linkedin|facebook|twitter)\b", text):
            scores["social"] += 0.4
            signals.append("Social media notification")

        # Sender domain checks
        if "noreply" in sender.lower():
            scores["newsletters"] += 0.2

        # Find best category
        best_category = max(scores, key=lambda k: scores[k])
        best_score = scores[best_category]

        if best_score < 0.2:
            best_category = "uncategorized"

        return {
            "category": best_category,
            "confidence": min(0.95, best_score),
            "signals": signals,
            "all_scores": scores,
        }


def get_email_agent_team(
    knowledge_mound=None,
    include_billing: bool = True,
    include_timeline: bool = False,
    include_categorization: bool = False,
) -> list[BaseDebateAgent]:
    """
    Get the standard email prioritization agent team.

    Args:
        knowledge_mound: Optional KM for context queries
        include_billing: Include billing/financial agent
        include_timeline: Include timeline/schedule agent
        include_categorization: Include categorization agent

    Returns:
        List of configured email agents
    """
    agents: list[BaseDebateAgent] = [
        SenderReputationAgent(),
        ContentUrgencyAgent(),
        ContextRelevanceAgent(knowledge_mound=knowledge_mound),
    ]

    if include_billing:
        agents.append(BillingCriticalityAgent())

    if include_timeline:
        agents.append(TimelineAgent())

    if include_categorization:
        agents.append(CategorizationAgent())

    return agents


def get_categorization_agent_team() -> list[BaseDebateAgent]:
    """
    Get the agent team for email categorization debates.

    Returns:
        List of agents specialized for categorization
    """
    return [
        CategorizationAgent(),
        ContentUrgencyAgent(),
        BillingCriticalityAgent(),
    ]


# Agent configuration for AGENTS.md registration
AGENT_CONFIGS = {
    "sender_reputation": {
        "class": "SenderReputationAgent",
        "description": "Analyzes sender importance and relationship history",
        "capabilities": ["sender_analysis", "vip_detection", "relationship_scoring"],
    },
    "content_urgency": {
        "class": "ContentUrgencyAgent",
        "description": "Detects time-sensitive content and deadlines",
        "capabilities": ["urgency_detection", "deadline_extraction", "action_detection"],
    },
    "context_relevance": {
        "class": "ContextRelevanceAgent",
        "description": "Cross-references email with user context",
        "capabilities": ["knowledge_query", "project_matching", "activity_correlation"],
    },
    "billing_criticality": {
        "class": "BillingCriticalityAgent",
        "description": "Identifies financial and contract-related emails",
        "capabilities": ["financial_detection", "contract_analysis", "payment_alerts"],
    },
    "timeline": {
        "class": "TimelineAgent",
        "description": "Considers schedule and response patterns",
        "capabilities": ["calendar_integration", "response_prediction", "timing_optimization"],
    },
    "categorization": {
        "class": "CategorizationAgent",
        "description": "Classifies emails into smart folder categories",
        "capabilities": [
            "category_detection",
            "folder_assignment",
            "newsletter_filtering",
            "auto_archive_suggestion",
        ],
    },
}
