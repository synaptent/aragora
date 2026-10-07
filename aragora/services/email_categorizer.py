"""
Email Categorization Service.

Intelligent email folder assignment using pattern matching and multi-agent debate.
Automatically categorizes emails into smart folders:
- invoices: Financial documents, bills, receipts
- hr: HR, benefits, payroll, PTO
- newsletters: Marketing, digests, auto-archive candidates
- projects: Active project threads, task updates
- meetings: Calendar-related, scheduling
- support: Customer support, tickets
- personal: Non-work, personal contacts

Supports both rule-based fast categorization and multi-agent debate for ambiguous cases.

Usage:
    from aragora.services.email_categorizer import EmailCategorizer

    categorizer = EmailCategorizer(gmail_connector=connector)

    # Categorize single email
    result = await categorizer.categorize_email(email)
    print(f"Category: {result.category} ({result.confidence:.0%})")

    # Batch categorize
    results = await categorizer.categorize_batch(emails)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.gmail import GmailConnector


@runtime_checkable
class EmailLike(Protocol):
    """Protocol for objects that can be categorized as emails.

    This protocol defines the minimal interface needed for email categorization.
    All attributes are optional at runtime (accessed via getattr with defaults),
    but defining them here provides type safety.
    """

    id: str
    subject: str
    body: str
    sender: str


logger = logging.getLogger(__name__)


class EmailCategory(Enum):
    """Email category types for smart folders."""

    INVOICES = "invoices"  # Financial documents
    HR = "hr"  # HR, benefits, payroll
    NEWSLETTERS = "newsletters"  # Marketing, auto-archive
    PROJECTS = "projects"  # Project threads
    MEETINGS = "meetings"  # Calendar-related
    SUPPORT = "support"  # Customer support
    PERSONAL = "personal"  # Non-work
    SECURITY = "security"  # Security alerts, 2FA
    RECEIPTS = "receipts"  # Purchase confirmations
    SOCIAL = "social"  # Social media notifications
    UNCATEGORIZED = "uncategorized"  # Default


@dataclass
class CategoryPattern:
    """Pattern definition for category detection."""

    pattern: str
    weight: float = 1.0
    field: str = "all"  # "subject", "body", "from", "all"


# Category detection patterns
CATEGORY_PATTERNS: dict[EmailCategory, list[CategoryPattern]] = {
    EmailCategory.INVOICES: [
        CategoryPattern(r"\binvoice\b", 0.8),
        CategoryPattern(r"\bbilling\b", 0.6),
        CategoryPattern(r"\bpayment\s+(due|received|processed)", 0.7),
        CategoryPattern(r"\$\d+[\d,]*\.\d{2}", 0.5),
        CategoryPattern(r"\bstatement\b", 0.5),
        CategoryPattern(r"\bnet\s+\d+\s+days", 0.6),
        CategoryPattern(r"\bdue\s+date", 0.5),
        CategoryPattern(r"accounts?\s*(payable|receivable)", 0.7),
        CategoryPattern(r"\bpo\s*#?\s*\d+", 0.5),  # Purchase order
    ],
    EmailCategory.HR: [
        CategoryPattern(r"\bpayroll\b", 0.8),
        CategoryPattern(r"\bpto\b", 0.7),
        CategoryPattern(r"\b(vacation|leave)\s+(request|approved|balance)", 0.7),
        CategoryPattern(r"\bbenefits?\s+(enrollment|update|open)", 0.7),
        CategoryPattern(r"\b(401k|retirement|pension)", 0.7),
        CategoryPattern(r"\bperformance\s+review", 0.6),
        CategoryPattern(r"\bonboarding\b", 0.6),
        CategoryPattern(r"\btime\s*sheet", 0.6),
        CategoryPattern(r"\bexpense\s+(report|reimbursement)", 0.6),
        CategoryPattern(r"\b(salary|compensation)", 0.5),
        CategoryPattern(r"hr@|human.?resources?@", 0.8, field="from"),
    ],
    EmailCategory.NEWSLETTERS: [
        CategoryPattern(r"\bunsubscribe\b", 0.9),
        CategoryPattern(r"\bweekly\s+(digest|update|newsletter)", 0.8),
        CategoryPattern(r"\bmonthly\s+(digest|update|newsletter)", 0.8),
        CategoryPattern(r"\bnewsletter\b", 0.8),
        CategoryPattern(r"\bdigest\b", 0.6),
        CategoryPattern(r"\bview\s+in\s+browser", 0.7),
        CategoryPattern(r"\bemail\s+preferences", 0.6),
        CategoryPattern(r"no-?reply@|noreply@", 0.5, field="from"),
        CategoryPattern(r"\blist-unsubscribe", 0.9),  # Header
        CategoryPattern(r"\btop\s+stories", 0.6),
        CategoryPattern(r"\bthis\s+week\s+in", 0.7),
    ],
    EmailCategory.PROJECTS: [
        CategoryPattern(r"\btask\s+(assigned|completed|updated)", 0.7),
        CategoryPattern(r"\bsprint\b", 0.6),
        CategoryPattern(r"\bmilestone\b", 0.6),
        CategoryPattern(r"\bproject\s+(update|status|kickoff)", 0.7),
        CategoryPattern(r"\bjira|asana|trello|linear|monday\b", 0.6),
        CategoryPattern(r"\bpull\s+request", 0.6),
        CategoryPattern(r"\bmerge\s+request", 0.6),
        CategoryPattern(r"\bcode\s+review", 0.6),
        CategoryPattern(r"\bdeployment", 0.5),
        CategoryPattern(r"\brelease\s+(notes|candidate)", 0.6),
        CategoryPattern(r"\[(.*?)\]\s+#\d+", 0.5),  # [Project] #123 pattern
    ],
    EmailCategory.MEETINGS: [
        CategoryPattern(r"\bmeeting\s+(invite|invitation|request)", 0.9),
        CategoryPattern(r"\bcalendar\s+(invite|event)", 0.9),
        CategoryPattern(r"\breschedule", 0.7),
        CategoryPattern(r"\bagenda\b", 0.6),
        CategoryPattern(r"\bscheduled\s+(for|at|on)", 0.6),
        CategoryPattern(r"\bzoom\.us|meet\.google|teams\.microsoft", 0.7),
        CategoryPattern(r"\bstandup\b", 0.5),
        CategoryPattern(r"\bsync\b", 0.4),
        CategoryPattern(r"\b1:1|one-on-one", 0.5),
        CategoryPattern(r"calendar-notification@google|outlook.*calendar", 0.8, field="from"),
    ],
    EmailCategory.SUPPORT: [
        CategoryPattern(r"\bticket\s*#?\s*\d+", 0.7),
        CategoryPattern(r"\bcase\s*#?\s*\d+", 0.7),
        CategoryPattern(r"\bsupport\s+(request|ticket)", 0.8),
        CategoryPattern(r"\bhelp\s+desk", 0.7),
        CategoryPattern(r"\bissue\s+(reported|resolved|updated)", 0.6),
        CategoryPattern(r"\bcustomer\s+(support|service)", 0.7),
        CategoryPattern(r"support@|help@|helpdesk@", 0.7, field="from"),
        CategoryPattern(r"\b(zendesk|intercom|freshdesk)", 0.6),
        CategoryPattern(r"\bfeedback\s+(request|survey)", 0.5),
    ],
    EmailCategory.SECURITY: [
        CategoryPattern(r"\b(2fa|two-factor|mfa|multi-factor)", 0.8),
        CategoryPattern(r"\bverification\s+code", 0.8),
        CategoryPattern(r"\bsecurity\s+(alert|warning|notice)", 0.9),
        CategoryPattern(r"\bpassword\s+(reset|changed|expired)", 0.8),
        CategoryPattern(r"\bnew\s+(sign-?in|login|device)", 0.7),
        CategoryPattern(r"\bsuspicious\s+activity", 0.9),
        CategoryPattern(r"\baccount\s+(locked|compromised|alert)", 0.8),
        CategoryPattern(r"\bauth(entication|orization)\s+(code|failed)", 0.7),
        CategoryPattern(r"security@|noreply.*security", 0.6, field="from"),
    ],
    EmailCategory.RECEIPTS: [
        CategoryPattern(r"\border\s+(confirm|receipt|shipped)", 0.8),
        CategoryPattern(r"\breceipt\s+(for|from)", 0.8),
        CategoryPattern(r"\bpurchase\s+(confirm|receipt)", 0.8),
        CategoryPattern(r"\bshipping\s+(confirm|notification|update)", 0.7),
        CategoryPattern(r"\bdelivery\s+(scheduled|confirm)", 0.7),
        CategoryPattern(r"\btracking\s+(number|info)", 0.6),
        CategoryPattern(r"\border\s*#?\s*\d+", 0.6),
        CategoryPattern(r"\bthank\s+you\s+for\s+(your\s+)?(order|purchase)", 0.7),
    ],
    EmailCategory.SOCIAL: [
        CategoryPattern(r"\b(liked|commented|shared|mentioned|tagged)\s+your", 0.8),
        CategoryPattern(r"\bnew\s+(follower|connection)", 0.8),
        CategoryPattern(r"\bfriend\s+request", 0.8),
        CategoryPattern(r"\b(facebook|instagram|twitter|linkedin|tiktok)", 0.6),
        CategoryPattern(r"notification.*@(facebook|linkedin|twitter)", 0.8, field="from"),
        CategoryPattern(r"\bsomeone\s+(viewed|endorsed)", 0.6),
        CategoryPattern(r"\bconnect\s+with", 0.5),
    ],
}

# Sender domain patterns for quick categorization
SENDER_DOMAIN_CATEGORIES: dict[str, EmailCategory] = {
    # HR
    "workday.com": EmailCategory.HR,
    "adp.com": EmailCategory.HR,
    "gusto.com": EmailCategory.HR,
    "bamboohr.com": EmailCategory.HR,
    # Newsletters
    "substack.com": EmailCategory.NEWSLETTERS,
    "mailchimp.com": EmailCategory.NEWSLETTERS,
    "constantcontact.com": EmailCategory.NEWSLETTERS,
    # Projects
    "github.com": EmailCategory.PROJECTS,
    "gitlab.com": EmailCategory.PROJECTS,
    "atlassian.net": EmailCategory.PROJECTS,
    "linear.app": EmailCategory.PROJECTS,
    "asana.com": EmailCategory.PROJECTS,
    # Support
    "zendesk.com": EmailCategory.SUPPORT,
    "intercom.io": EmailCategory.SUPPORT,
    "freshdesk.com": EmailCategory.SUPPORT,
    # Social
    "facebookmail.com": EmailCategory.SOCIAL,
    "linkedin.com": EmailCategory.SOCIAL,
    "twitter.com": EmailCategory.SOCIAL,
    # Security
    "auth0.com": EmailCategory.SECURITY,
    "okta.com": EmailCategory.SECURITY,
    "onelogin.com": EmailCategory.SECURITY,
    # Receipts/Commerce
    "amazon.com": EmailCategory.RECEIPTS,
    "shopify.com": EmailCategory.RECEIPTS,
    "stripe.com": EmailCategory.INVOICES,
    "square.com": EmailCategory.INVOICES,
}


@dataclass
class CategorizationResult:
    """Result of email categorization."""

    email_id: str
    category: EmailCategory
    confidence: float
    secondary_category: EmailCategory | None = None
    matched_patterns: list[str] = field(default_factory=list)
    suggested_label: str = ""
    auto_archive: bool = False
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "email_id": self.email_id,
            "category": self.category.value,
            "confidence": self.confidence,
            "secondary_category": (
                self.secondary_category.value if self.secondary_category else None
            ),
            "matched_patterns": self.matched_patterns,
            "suggested_label": self.suggested_label,
            "auto_archive": self.auto_archive,
            "rationale": self.rationale,
        }


@dataclass
class EmailCategorizerConfig:
    """Configuration for email categorizer."""

    # Confidence thresholds
    high_confidence_threshold: float = 0.7
    low_confidence_threshold: float = 0.3

    # Auto-archive settings
    auto_archive_newsletters: bool = True
    auto_archive_social: bool = False

    # Custom category mappings (sender -> category)
    custom_sender_categories: dict[str, str] = field(default_factory=dict)

    # Categories to enable
    enabled_categories: set[EmailCategory] = field(
        default_factory=lambda: {cat for cat in EmailCategory if cat != EmailCategory.UNCATEGORIZED}
    )


class EmailCategorizer:
    """
    Intelligent email categorization service.

    Uses pattern matching for fast categorization with optional
    multi-agent debate for ambiguous cases.
    """

    def __init__(
        self,
        gmail_connector: GmailConnector | None = None,
        config: EmailCategorizerConfig | None = None,
    ):
        self.gmail = gmail_connector
        self.config = config or EmailCategorizerConfig()
        self._compiled_patterns: dict[EmailCategory, list[tuple]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance."""
        for category, patterns in CATEGORY_PATTERNS.items():
            if category not in self.config.enabled_categories:
                continue
            self._compiled_patterns[category] = [
                (re.compile(p.pattern, re.IGNORECASE), p.weight, p.field) for p in patterns
            ]

    def _extract_domain(self, email_address: str) -> str:
        """Extract domain from email address."""
        if "@" in email_address:
            return email_address.split("@")[1].lower()
        return ""

    def _get_text_for_field(
        self,
        field: str,
        subject: str,
        body: str,
        sender: str,
    ) -> str:
        """Get appropriate text based on field specification."""
        if field == "subject":
            return subject
        elif field == "body":
            return body
        elif field == "from":
            return sender
        else:  # "all"
            return f"{subject} {body} {sender}"

    async def categorize_email(
        self,
        email: EmailLike,
    ) -> CategorizationResult:
        """
        Categorize a single email.

        Args:
            email: Email message to categorize

        Returns:
            CategorizationResult with category and confidence
        """
        email_id = getattr(email, "id", str(hash(email)))
        subject = getattr(email, "subject", "")
        body = getattr(email, "body", getattr(email, "snippet", ""))
        sender = getattr(email, "sender", getattr(email, "from_", ""))

        # Quick domain-based categorization
        domain = self._extract_domain(sender)
        if domain in SENDER_DOMAIN_CATEGORIES:
            category = SENDER_DOMAIN_CATEGORIES[domain]
            return CategorizationResult(
                email_id=email_id,
                category=category,
                confidence=0.85,
                matched_patterns=[f"Sender domain: {domain}"],
                suggested_label=f"Aragora/{category.value.title()}",
                auto_archive=self._should_auto_archive(category),
                rationale=f"Recognized sender domain {domain}",
            )

        # Custom sender mapping
        if sender.lower() in self.config.custom_sender_categories:
            category_str = self.config.custom_sender_categories[sender.lower()]
            category = EmailCategory(category_str)
            return CategorizationResult(
                email_id=email_id,
                category=category,
                confidence=0.9,
                matched_patterns=["Custom sender mapping"],
                suggested_label=f"Aragora/{category.value.title()}",
                auto_archive=self._should_auto_archive(category),
                rationale=f"Custom mapping for sender {sender}",
            )

        # Pattern-based scoring
        scores: dict[EmailCategory, float] = {}
        matched: dict[EmailCategory, list[str]] = {}

        for category, patterns in self._compiled_patterns.items():
            category_score = 0.0
            category_matches = []

            for regex, weight, field_name in patterns:
                text = self._get_text_for_field(field_name, subject, body, sender)
                if regex.search(text):
                    category_score += weight
                    category_matches.append(regex.pattern)

            if category_score > 0:
                scores[category] = category_score
                matched[category] = category_matches

        # Determine best category
        if not scores:
            return CategorizationResult(
                email_id=email_id,
                category=EmailCategory.UNCATEGORIZED,
                confidence=1.0,
                rationale="No category patterns matched",
            )

        # Sort by score
        sorted_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_category, best_score = sorted_categories[0]

        # Calculate confidence based on score and gap to second place
        total_score = sum(scores.values())
        confidence = min(0.95, best_score / max(total_score, 1.0))

        # Secondary category if close
        secondary = None
        if len(sorted_categories) > 1:
            second_category, second_score = sorted_categories[1]
            if second_score >= best_score * 0.7:
                secondary = second_category

        return CategorizationResult(
            email_id=email_id,
            category=best_category,
            confidence=confidence,
            secondary_category=secondary,
            matched_patterns=matched.get(best_category, []),
            suggested_label=f"Aragora/{best_category.value.title()}",
            auto_archive=self._should_auto_archive(best_category),
            rationale=self._generate_rationale(best_category, matched.get(best_category, [])),
        )

    async def categorize_batch(
        self,
        emails: list[EmailLike],
        concurrency: int = 10,
    ) -> list[CategorizationResult]:
        """
        Categorize multiple emails concurrently.

        Args:
            emails: List of emails to categorize
            concurrency: Max concurrent categorizations

        Returns:
            List of categorization results in same order as input
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def categorize_with_limit(email: EmailLike) -> CategorizationResult:
            async with semaphore:
                return await self.categorize_email(email)

        tasks = [categorize_with_limit(email) for email in emails]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        final_results: list[CategorizationResult] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error("Categorization failed for email %s: %s", i, result)
                final_results.append(
                    CategorizationResult(
                        email_id=str(i),
                        category=EmailCategory.UNCATEGORIZED,
                        confidence=0.0,
                        rationale=f"Error: {str(result)}",
                    )
                )
            else:
                final_results.append(result)

        return final_results

    def _should_auto_archive(self, category: EmailCategory) -> bool:
        """Determine if category should be auto-archived."""
        if category == EmailCategory.NEWSLETTERS and self.config.auto_archive_newsletters:
            return True
        if category == EmailCategory.SOCIAL and self.config.auto_archive_social:
            return True
        return False

    def _generate_rationale(
        self,
        category: EmailCategory,
        patterns: list[str],
    ) -> str:
        """Generate human-readable rationale for categorization."""
        descriptions = {
            EmailCategory.INVOICES: "financial/billing content",
            EmailCategory.HR: "HR/benefits/payroll content",
            EmailCategory.NEWSLETTERS: "newsletter/marketing content",
            EmailCategory.PROJECTS: "project/task management content",
            EmailCategory.MEETINGS: "calendar/meeting content",
            EmailCategory.SUPPORT: "support ticket content",
            EmailCategory.SECURITY: "security/authentication content",
            EmailCategory.RECEIPTS: "order/receipt content",
            EmailCategory.SOCIAL: "social media notification",
            EmailCategory.PERSONAL: "personal correspondence",
        }

        desc = descriptions.get(category, "matching content")
        pattern_summary = f"Matched {len(patterns)} pattern(s)" if patterns else ""

        return f"Detected {desc}. {pattern_summary}".strip()

    async def apply_gmail_label(
        self,
        email_id: str,
        category: EmailCategory,
    ) -> bool:
        """
        Apply Gmail label based on category.

        Args:
            email_id: Gmail message ID
            category: Category to apply

        Returns:
            True if label was applied successfully
        """
        if not self.gmail:
            logger.warning("No Gmail connector configured")
            return False

        label_name = f"Aragora/{category.value.title()}"

        try:
            # Get or create label
            labels = await self.gmail.list_labels()
            label_id = None

            for label in labels:
                if label.name == label_name:
                    label_id = label.id
                    break

            if not label_id:
                # Create label
                new_label = await self.gmail.create_label(label_name)
                label_id = new_label.id

            if label_id:
                await self.gmail.add_label(email_id, label_id)
                return True

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("Failed to apply label: %s", e)

        return False

    def get_category_stats(
        self,
        results: list[CategorizationResult],
    ) -> dict[str, Any]:
        """
        Get statistics from categorization results.

        Args:
            results: List of categorization results

        Returns:
            Stats dictionary with counts and distributions
        """
        stats: dict[str, Any] = {
            "total": len(results),
            "categories": {},
            "confidence_avg": 0.0,
            "auto_archive_count": 0,
            "uncategorized_count": 0,
        }

        if not results:
            return stats

        for result in results:
            cat_name = result.category.value
            if cat_name not in stats["categories"]:
                stats["categories"][cat_name] = 0
            stats["categories"][cat_name] += 1

            if result.auto_archive:
                stats["auto_archive_count"] += 1
            if result.category == EmailCategory.UNCATEGORIZED:
                stats["uncategorized_count"] += 1

        stats["confidence_avg"] = sum(r.confidence for r in results) / len(results)

        return stats


# Convenience function for quick categorization
async def categorize_email_quick(
    subject: str,
    body: str,
    sender: str,
) -> CategorizationResult:
    """
    Quick categorization without full email object.

    Args:
        subject: Email subject
        body: Email body text
        sender: Sender email address

    Returns:
        CategorizationResult
    """

    # Create minimal email-like object
    class SimpleEmail:
        def __init__(self, subject: str, body: str, sender: str):
            self.id = f"quick_{hash((subject, body, sender))}"
            self.subject = subject
            self.body = body
            self.sender = sender

    email = SimpleEmail(subject, body, sender)
    categorizer = EmailCategorizer()
    return await categorizer.categorize_email(email)
