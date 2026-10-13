"""
Accounting Audit Type.

Specialized auditor for financial document analysis targeting:
- Financial irregularities and anomalies
- Journal entry validation
- Duplicate invoice detection
- Revenue recognition issues
- SOX compliance checks
- Number verification and cross-reference validation

Designed for accounting firms, finance departments, and auditors.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from collections.abc import Sequence

from ..base_auditor import AuditorCapabilities, AuditContext, BaseAuditor, ChunkData
from ..document_auditor import AuditFinding, AuditType, FindingSeverity

logger = logging.getLogger(__name__)


class FinancialCategory(str, Enum):
    """Categories of financial findings."""

    IRREGULARITY = "irregularity"
    JOURNAL_ENTRY = "journal_entry"
    DUPLICATE = "duplicate"
    REVENUE_RECOGNITION = "revenue_recognition"
    SOX_COMPLIANCE = "sox_compliance"
    RECONCILIATION = "reconciliation"
    THRESHOLD = "threshold"
    TIMING = "timing"
    SEGREGATION = "segregation"


@dataclass
class FinancialPattern:
    """Pattern for detecting financial issues."""

    name: str
    pattern: str
    category: FinancialCategory
    severity: FindingSeverity
    description: str
    recommendation: str
    flags: int = re.IGNORECASE | re.MULTILINE


@dataclass
class AmountPattern:
    """Pattern for suspicious amount detection."""

    name: str
    check_type: str  # "round", "threshold", "sequence", "benford"
    threshold: float | None = None
    description: str = ""
    severity: FindingSeverity = FindingSeverity.MEDIUM


@dataclass
class ExtractedAmount:
    """An extracted monetary amount from text."""

    value: Decimal
    currency: str
    location: str
    context: str
    line_number: int


@dataclass
class JournalEntry:
    """Extracted journal entry for validation."""

    date: str | None
    description: str
    debits: list[tuple[str, Decimal]]  # (account, amount)
    credits: list[tuple[str, Decimal]]
    location: str
    reference: str | None = None


class AccountingAuditor(BaseAuditor):
    """
    Auditor for financial documents and accounting records.

    Detects:
    - Round number anomalies (potential estimation/manipulation)
    - Just-under-threshold amounts (approval circumvention)
    - Unbalanced journal entries
    - Duplicate transactions
    - Revenue recognition timing issues
    - SOX control deficiencies
    - Benford's Law violations
    """

    # Patterns for financial irregularities
    IRREGULARITY_PATTERNS: list[FinancialPattern] = [
        FinancialPattern(
            name="round_number_large",
            pattern=r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.00)?)\b",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Large round number amounts may indicate estimates rather than actual transactions",
            recommendation="Verify supporting documentation for round-number transactions",
        ),
        FinancialPattern(
            name="manual_adjustment",
            pattern=r"(?:manual\s+)?(?:adjustment|correction|entry|override).*?\$[\d,]+",
            category=FinancialCategory.JOURNAL_ENTRY,
            severity=FindingSeverity.MEDIUM,
            description="Manual adjustments require additional scrutiny",
            recommendation="Review approval documentation and supporting rationale for manual entries",
        ),
        FinancialPattern(
            name="year_end_entry",
            pattern=r"(?:year[- ]?end|12/31|dec(?:ember)?\s*3[01]).*?(?:adjustment|entry|accrual)",
            category=FinancialCategory.TIMING,
            severity=FindingSeverity.MEDIUM,
            description="Year-end entries warrant closer examination for earnings management",
            recommendation="Verify year-end entries have proper support and business rationale",
        ),
        FinancialPattern(
            name="related_party",
            pattern=r"(?:related\s+party|affiliate|subsidiary|parent\s+company|intercompany).*?(?:transaction|payment|transfer|loan)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.HIGH,
            description="Related party transactions require arms-length verification",
            recommendation="Ensure related party transactions are at fair market value with proper disclosure",
        ),
        FinancialPattern(
            name="unusual_vendor",
            pattern=r"(?:new\s+vendor|first[- ]time|one[- ]time|unusual).*?(?:payment|invoice|transaction)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Transactions with new or unusual vendors warrant verification",
            recommendation="Verify vendor legitimacy and proper procurement procedures",
        ),
        FinancialPattern(
            name="cash_transaction",
            pattern=r"(?:cash|currency).*?(?:payment|receipt|transaction).*?\$[\d,]+",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.HIGH,
            description="Cash transactions increase fraud risk",
            recommendation="Verify cash handling controls and documentation",
        ),
        FinancialPattern(
            name="wire_transfer_international",
            pattern=r"(?:wire|transfer|remittance).*?(?:international|foreign|offshore|overseas)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.HIGH,
            description="International wire transfers require enhanced due diligence",
            recommendation="Verify recipient, business purpose, and compliance with regulations",
        ),
        # Additional Financial Risk Patterns
        FinancialPattern(
            name="cryptocurrency_transaction",
            pattern=r"(?:bitcoin|btc|ethereum|eth|crypto|cryptocurrency|wallet).*?(?:payment|transfer|transaction|purchase)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.HIGH,
            description="Cryptocurrency transaction detected - requires enhanced monitoring",
            recommendation="Verify business purpose, source of funds, and regulatory compliance",
        ),
        FinancialPattern(
            name="check_splitting",
            pattern=r"(?:check|cheque)\s*#?\d+.*?(?:same\s+(?:date|day|vendor)|multiple|split)",
            category=FinancialCategory.THRESHOLD,
            severity=FindingSeverity.MEDIUM,
            description="Potential check splitting to avoid controls",
            recommendation="Review for proper authorization and business rationale",
        ),
        FinancialPattern(
            name="consulting_generic",
            pattern=r"(?:consulting|advisory|professional)\s+(?:services?|fees?)\s*[:=]?\s*\$[\d,]+",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Generic consulting fee without detailed description",
            recommendation="Require detailed invoices with specific deliverables and work performed",
        ),
        FinancialPattern(
            name="expense_reimbursement_large",
            pattern=r"(?:expense|reimbursement|travel).*?\$\s*(?:[5-9]\d{3}|[1-9]\d{4,})",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Large expense reimbursement requires additional review",
            recommendation="Verify receipts, business purpose, and policy compliance",
        ),
        FinancialPattern(
            name="bonus_accrual",
            pattern=r"(?:bonus|incentive|commission)\s+(?:accrual|accrued|reserve)",
            category=FinancialCategory.TIMING,
            severity=FindingSeverity.MEDIUM,
            description="Bonus accrual detected - verify estimation methodology",
            recommendation="Review calculation methodology and supporting documentation",
        ),
        FinancialPattern(
            name="prior_period_adjustment",
            pattern=r"(?:prior\s+period|correction|restatement|error\s+correction).*?(?:adjustment|entry)",
            category=FinancialCategory.JOURNAL_ENTRY,
            severity=FindingSeverity.HIGH,
            description="Prior period adjustment requires careful review and disclosure",
            recommendation="Evaluate materiality and disclosure requirements",
        ),
        FinancialPattern(
            name="allowance_write_off",
            pattern=r"(?:allowance|reserve|provision).*?(?:write[- ]?off|bad\s+debt|uncollectible)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Allowance/write-off - verify reasonableness of estimates",
            recommendation="Review aging analysis and collection efforts before write-off",
        ),
        FinancialPattern(
            name="goodwill_impairment",
            pattern=r"(?:goodwill|intangible|impairment).*?(?:test|review|analysis|charge)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.HIGH,
            description="Goodwill/intangible impairment involves significant judgment",
            recommendation="Review valuation assumptions and market comparables",
        ),
        FinancialPattern(
            name="lease_classification",
            pattern=r"(?:lease|rent).*?(?:capital|finance|operating|classification)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Lease classification affects balance sheet presentation",
            recommendation="Verify lease classification per ASC 842",
        ),
        FinancialPattern(
            name="payroll_ghost_employee",
            pattern=r"(?:payroll|salary).*?(?:no\s+(?:timecard|hours)|inactive|terminated)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.CRITICAL,
            description="Potential ghost employee indicator",
            recommendation="Verify active employment status and reconcile to HR records",
        ),
        FinancialPattern(
            name="inventory_obsolescence",
            pattern=r"(?:inventory|stock).*?(?:obsolete|slow[- ]?moving|write[- ]?down|reserve)",
            category=FinancialCategory.IRREGULARITY,
            severity=FindingSeverity.MEDIUM,
            description="Inventory obsolescence requires judgment and estimation",
            recommendation="Review inventory aging and sales velocity",
        ),
    ]

    # Journal entry validation patterns
    JOURNAL_PATTERNS: list[FinancialPattern] = [
        FinancialPattern(
            name="unbalanced_entry",
            pattern=r"(?:debit|dr\.?)\s*[:=]?\s*\$?([\d,]+(?:\.\d{2})?)",
            category=FinancialCategory.JOURNAL_ENTRY,
            severity=FindingSeverity.CRITICAL,
            description="Journal entries must have equal debits and credits",
            recommendation="Review and correct unbalanced journal entries",
        ),
        FinancialPattern(
            name="missing_description",
            pattern=r"(?:journal\s+entry|je|entry\s+#?\d+)(?![^.]*(?:for|to|from|re:|regarding|description))",
            category=FinancialCategory.JOURNAL_ENTRY,
            severity=FindingSeverity.MEDIUM,
            description="Journal entries should have clear business descriptions",
            recommendation="Add description explaining business purpose of entry",
        ),
        FinancialPattern(
            name="round_trip",
            pattern=r"(?:reverse|offset|cancel).*?(?:entry|transaction|adjustment)",
            category=FinancialCategory.JOURNAL_ENTRY,
            severity=FindingSeverity.HIGH,
            description="Reversing entries may indicate error correction or manipulation",
            recommendation="Verify business rationale for reversing entries",
        ),
    ]

    # Revenue recognition patterns
    REVENUE_PATTERNS: list[FinancialPattern] = [
        FinancialPattern(
            name="bill_and_hold",
            pattern=r"bill[- ]and[- ]hold|held\s+for\s+(?:customer|shipment)",
            category=FinancialCategory.REVENUE_RECOGNITION,
            severity=FindingSeverity.HIGH,
            description="Bill-and-hold arrangements require specific criteria per ASC 606",
            recommendation="Verify all bill-and-hold criteria are met and documented",
        ),
        FinancialPattern(
            name="side_letter",
            pattern=r"side\s+(?:letter|agreement)|verbal\s+agreement|undocumented\s+(?:term|condition)",
            category=FinancialCategory.REVENUE_RECOGNITION,
            severity=FindingSeverity.CRITICAL,
            description="Side letters may modify revenue recognition terms",
            recommendation="Identify and document all side agreements affecting revenue",
        ),
        FinancialPattern(
            name="channel_stuffing",
            pattern=r"(?:quarter|month|year)[- ]end\s+(?:push|sale|shipment|order)",
            category=FinancialCategory.REVENUE_RECOGNITION,
            severity=FindingSeverity.HIGH,
            description="Period-end sales spikes may indicate channel stuffing",
            recommendation="Analyze sales patterns and return rates for channel stuffing indicators",
        ),
        FinancialPattern(
            name="contingent_revenue",
            pattern=r"(?:contingent|conditional|milestone|performance)[- ]based.*?(?:revenue|payment|fee)",
            category=FinancialCategory.REVENUE_RECOGNITION,
            severity=FindingSeverity.MEDIUM,
            description="Contingent revenue requires careful timing assessment",
            recommendation="Verify milestone completion and revenue recognition timing",
        ),
        FinancialPattern(
            name="percentage_completion",
            pattern=r"(?:percentage|percent)[- ]of[- ]completion|poc\s+method",
            category=FinancialCategory.REVENUE_RECOGNITION,
            severity=FindingSeverity.MEDIUM,
            description="Percentage-of-completion estimates require verification",
            recommendation="Verify completion percentage calculations and assumptions",
        ),
    ]

    # SOX compliance patterns
    SOX_PATTERNS: list[FinancialPattern] = [
        FinancialPattern(
            name="segregation_violation",
            pattern=r"(?:same\s+person|single\s+(?:user|employee)|no\s+(?:separation|segregation)).*?(?:approve|authorize|record|custody)",
            category=FinancialCategory.SEGREGATION,
            severity=FindingSeverity.CRITICAL,
            description="Segregation of duties violation - SOX control deficiency",
            recommendation="Implement proper segregation of duties controls",
        ),
        FinancialPattern(
            name="override",
            pattern=r"(?:management|supervisor|executive)\s+override|bypassed?\s+(?:control|approval)",
            category=FinancialCategory.SOX_COMPLIANCE,
            severity=FindingSeverity.CRITICAL,
            description="Management override of controls is a significant deficiency",
            recommendation="Document override rationale and implement compensating controls",
        ),
        FinancialPattern(
            name="missing_approval",
            pattern=r"(?:no|missing|lacking|without)\s+(?:approval|authorization|sign[- ]?off)",
            category=FinancialCategory.SOX_COMPLIANCE,
            severity=FindingSeverity.HIGH,
            description="Missing approval documentation is a control deficiency",
            recommendation="Ensure all transactions have required approvals documented",
        ),
        FinancialPattern(
            name="insufficient_documentation",
            pattern=r"(?:insufficient|inadequate|missing|no)\s+(?:documentation|support|evidence|backup)",
            category=FinancialCategory.SOX_COMPLIANCE,
            severity=FindingSeverity.HIGH,
            description="Insufficient documentation impairs audit trail",
            recommendation="Maintain complete supporting documentation for all transactions",
        ),
        FinancialPattern(
            name="it_access_control",
            pattern=r"(?:shared\s+password|generic\s+(?:user|login|account)|no\s+(?:password|access)\s+control)",
            category=FinancialCategory.SOX_COMPLIANCE,
            severity=FindingSeverity.HIGH,
            description="IT access control weakness - SOX ITGC deficiency",
            recommendation="Implement individual user accounts with proper access controls",
        ),
    ]

    # Threshold patterns for approval circumvention
    THRESHOLD_AMOUNTS: list[AmountPattern] = [
        AmountPattern(
            name="just_under_1000",
            check_type="threshold",
            threshold=1000.0,
            description="Amount just under $1,000 approval threshold",
            severity=FindingSeverity.MEDIUM,
        ),
        AmountPattern(
            name="just_under_5000",
            check_type="threshold",
            threshold=5000.0,
            description="Amount just under $5,000 approval threshold",
            severity=FindingSeverity.MEDIUM,
        ),
        AmountPattern(
            name="just_under_10000",
            check_type="threshold",
            threshold=10000.0,
            description="Amount just under $10,000 approval threshold",
            severity=FindingSeverity.HIGH,
        ),
        AmountPattern(
            name="just_under_25000",
            check_type="threshold",
            threshold=25000.0,
            description="Amount just under $25,000 approval threshold",
            severity=FindingSeverity.HIGH,
        ),
    ]

    # Currency patterns for extraction
    CURRENCY_PATTERN = re.compile(
        r"(?P<currency>\$|USD|EUR|GBP|€|£)?\s*(?P<amount>[\d,]+(?:\.\d{1,2})?)\s*(?P<suffix>USD|EUR|GBP)?",
        re.IGNORECASE,
    )

    @property
    def audit_type_id(self) -> str:
        return "accounting"

    @property
    def display_name(self) -> str:
        return "Accounting & Financial"

    @property
    def description(self) -> str:
        return (
            "Financial document analysis for irregularities, journal entry validation, "
            "duplicate detection, revenue recognition, and SOX compliance"
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> AuditorCapabilities:
        return AuditorCapabilities(
            supports_chunk_analysis=True,
            supports_cross_document=True,
            supports_streaming=False,
            requires_llm=True,
            supported_doc_types=["pdf", "xlsx", "xls", "csv", "txt", "docx"],
            max_chunk_size=8000,
            custom_capabilities={
                "benford_analysis": True,
                "journal_validation": True,
                "duplicate_detection": True,
                "threshold_analysis": True,
                "sox_compliance": True,
            },
        )

    async def analyze_chunk(
        self,
        chunk: ChunkData,
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Analyze a document chunk for financial issues."""
        findings: list[AuditFinding] = []
        text = chunk.content

        # Extract amounts for analysis
        amounts = self._extract_amounts(text)

        # Check for financial irregularities
        findings.extend(self._check_patterns(text, self.IRREGULARITY_PATTERNS, chunk))

        # Check journal entry patterns
        findings.extend(self._check_patterns(text, self.JOURNAL_PATTERNS, chunk))

        # Check revenue recognition issues
        findings.extend(self._check_patterns(text, self.REVENUE_PATTERNS, chunk))

        # Check SOX compliance patterns
        findings.extend(self._check_patterns(text, self.SOX_PATTERNS, chunk))

        # Check for threshold circumvention
        findings.extend(self._check_threshold_amounts(amounts, chunk))

        # Check for suspicious round numbers
        findings.extend(self._check_round_numbers(amounts, chunk))

        # Check Benford's Law (if enough amounts)
        if len(amounts) >= 50:
            benford_finding = self._check_benford_distribution(amounts, chunk)
            if benford_finding:
                findings.append(benford_finding)

        return findings

    async def cross_document_analysis(
        self,
        chunks: Sequence[ChunkData],
        context: AuditContext,
    ) -> list[AuditFinding]:
        """Analyze across documents for duplicates and reconciliation issues."""
        findings: list[AuditFinding] = []

        # Collect all amounts with context
        all_amounts: list[tuple[ExtractedAmount, ChunkData]] = []
        for chunk in chunks:
            amounts = self._extract_amounts(chunk.content)
            for amt in amounts:
                all_amounts.append((amt, chunk))

        # Check for duplicate amounts (potential duplicate payments)
        findings.extend(self._check_duplicate_amounts(all_amounts))

        # Check for split transactions
        findings.extend(self._check_split_transactions(all_amounts))

        return findings

    def _check_patterns(
        self,
        text: str,
        patterns: list[FinancialPattern],
        chunk: ChunkData,
    ) -> list[AuditFinding]:
        """Check text against a list of patterns."""
        findings = []

        for pattern_def in patterns:
            try:
                pattern = re.compile(pattern_def.pattern, pattern_def.flags)
                matches = pattern.finditer(text)

                for match in matches:
                    # Get context around match
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    evidence = text[start:end]

                    findings.append(
                        AuditFinding(
                            title=f"Financial: {pattern_def.name.replace('_', ' ').title()}",
                            description=pattern_def.description,
                            severity=pattern_def.severity,
                            category=pattern_def.category.value,
                            audit_type=AuditType.COMPLIANCE,
                            document_id=chunk.document_id,
                            confidence=0.75,
                            evidence_text=f"...{evidence}...",
                            evidence_location=f"Chunk {chunk.id}",
                            recommendation=pattern_def.recommendation,
                            found_by="accounting_auditor",
                        )
                    )
            except re.error as e:
                logger.warning("Invalid regex pattern %s: %s", pattern_def.name, e)

        return findings

    def _extract_amounts(self, text: str) -> list[ExtractedAmount]:
        """Extract monetary amounts from text."""
        amounts = []
        lines = text.split("\n")

        for line_num, line in enumerate(lines, 1):
            for match in self.CURRENCY_PATTERN.finditer(line):
                try:
                    amount_str = match.group("amount").replace(",", "")
                    value = Decimal(amount_str)

                    if value <= 0:
                        continue

                    # Determine currency
                    currency = match.group("currency") or match.group("suffix") or "USD"
                    currency = (
                        currency.upper().replace("$", "USD").replace("€", "EUR").replace("£", "GBP")
                    )

                    # Get context
                    start = max(0, match.start() - 30)
                    end = min(len(line), match.end() + 30)
                    context = line[start:end].strip()

                    amounts.append(
                        ExtractedAmount(
                            value=value,
                            currency=currency,
                            location=f"line {line_num}",
                            context=context,
                            line_number=line_num,
                        )
                    )
                except (InvalidOperation, ValueError):
                    continue

        return amounts

    def _check_threshold_amounts(
        self,
        amounts: list[ExtractedAmount],
        chunk: ChunkData,
    ) -> list[AuditFinding]:
        """Check for amounts just under common approval thresholds."""
        findings = []

        for amt in amounts:
            for threshold in self.THRESHOLD_AMOUNTS:
                if threshold.threshold is None:
                    continue

                # Check if amount is within 5% below threshold
                lower_bound = threshold.threshold * 0.95
                upper_bound = threshold.threshold

                if lower_bound <= float(amt.value) < upper_bound:
                    findings.append(
                        AuditFinding(
                            title=f"Financial: {threshold.name.replace('_', ' ').title()}",
                            description=(
                                f"{threshold.description}. Amount ${amt.value:,.2f} is "
                                f"{((threshold.threshold - float(amt.value)) / threshold.threshold) * 100:.1f}% "
                                f"below ${threshold.threshold:,.0f} threshold."
                            ),
                            severity=threshold.severity,
                            category=FinancialCategory.THRESHOLD.value,
                            audit_type=AuditType.COMPLIANCE,
                            document_id=chunk.document_id,
                            confidence=0.65,
                            evidence_text=amt.context,
                            evidence_location=f"Chunk {chunk.id}, {amt.location}",
                            recommendation="Review transaction for potential threshold circumvention",
                            found_by="accounting_auditor",
                        )
                    )

        return findings

    def _check_round_numbers(
        self,
        amounts: list[ExtractedAmount],
        chunk: ChunkData,
    ) -> list[AuditFinding]:
        """Check for suspicious round number amounts."""
        findings = []

        for amt in amounts:
            value = float(amt.value)

            # Skip small amounts
            if value < 1000:
                continue

            # Check if it's a round number (ends in multiple zeros)
            if value >= 10000 and value % 1000 == 0:
                # Large round thousands
                zeros = 0
                temp = int(value)
                while temp % 10 == 0:
                    zeros += 1
                    temp //= 10

                if zeros >= 4:  # At least $10,000 with trailing zeros
                    findings.append(
                        AuditFinding(
                            title="Financial: Suspicious Round Amount",
                            description=(
                                f"Amount ${amt.value:,.2f} is a round number with {zeros} trailing zeros. "
                                "Large round amounts may indicate estimates or manipulated figures."
                            ),
                            severity=FindingSeverity.LOW if zeros < 5 else FindingSeverity.MEDIUM,
                            category=FinancialCategory.IRREGULARITY.value,
                            audit_type=AuditType.COMPLIANCE,
                            document_id=chunk.document_id,
                            confidence=0.50,
                            evidence_text=amt.context,
                            evidence_location=f"Chunk {chunk.id}, {amt.location}",
                            recommendation="Verify supporting documentation for round-number amounts",
                            found_by="accounting_auditor",
                        )
                    )

        return findings

    def _check_benford_distribution(
        self,
        amounts: list[ExtractedAmount],
        chunk: ChunkData,
    ) -> AuditFinding | None:
        """
        Check if first digits follow Benford's Law.

        Benford's Law: In natural datasets, leading digit d occurs with probability log10(1 + 1/d).
        Expected distribution: 1=30.1%, 2=17.6%, 3=12.5%, 4=9.7%, 5=7.9%, 6=6.7%, 7=5.8%, 8=5.1%, 9=4.6%
        """
        expected = {
            1: 0.301,
            2: 0.176,
            3: 0.125,
            4: 0.097,
            5: 0.079,
            6: 0.067,
            7: 0.058,
            8: 0.051,
            9: 0.046,
        }

        # Count first digits
        digit_counts = dict.fromkeys(range(1, 10), 0)
        total = 0

        for amt in amounts:
            value = float(amt.value)
            if value >= 1:
                first_digit = int(str(value).lstrip("0.")[0])
                if 1 <= first_digit <= 9:
                    digit_counts[first_digit] += 1
                    total += 1

        if total < 50:
            return None

        # Calculate chi-square statistic
        chi_square = 0.0
        observed_dist = {}
        for digit in range(1, 10):
            observed = digit_counts[digit] / total
            observed_dist[digit] = observed
            expected_count = expected[digit] * total
            chi_square += ((digit_counts[digit] - expected_count) ** 2) / expected_count

        # Critical value for df=8 at 0.05 significance is 15.51
        if chi_square > 15.51:
            # Build distribution summary
            dist_summary = ", ".join(f"{d}:{observed_dist[d]:.1%}" for d in range(1, 10))

            return AuditFinding(
                title="Financial: Benford's Law Anomaly",
                description=(
                    f"First digit distribution deviates significantly from Benford's Law "
                    f"(chi-square={chi_square:.1f} > 15.51). This may indicate data manipulation "
                    f"or non-natural data generation. Observed: {dist_summary}"
                ),
                severity=FindingSeverity.HIGH,
                category=FinancialCategory.IRREGULARITY.value,
                audit_type=AuditType.COMPLIANCE,
                document_id=chunk.document_id,
                confidence=0.70,
                evidence_text=f"Analyzed {total} amounts in document",
                evidence_location=f"Chunk {chunk.id}",
                recommendation="Perform detailed analysis of data source and entry patterns",
                found_by="accounting_auditor",
            )

        return None

    def _check_duplicate_amounts(
        self,
        amounts: list[tuple[ExtractedAmount, ChunkData]],
    ) -> list[AuditFinding]:
        """Check for potential duplicate payments across documents."""
        findings = []

        # Group by amount value
        amount_groups: dict[Decimal, list[tuple[ExtractedAmount, ChunkData]]] = {}
        for amt, chunk in amounts:
            if amt.value not in amount_groups:
                amount_groups[amt.value] = []
            amount_groups[amt.value].append((amt, chunk))

        # Find duplicates
        for value, occurrences in amount_groups.items():
            if len(occurrences) >= 2 and float(value) >= 1000:
                # Check if from different documents
                doc_ids = set(chunk.document_id for _, chunk in occurrences)
                if len(doc_ids) >= 2:
                    locations = [
                        f"{chunk.document_id}:{amt.location}" for amt, chunk in occurrences[:3]
                    ]

                    findings.append(
                        AuditFinding(
                            title="Financial: Potential Duplicate Payment",
                            description=(
                                f"Amount ${value:,.2f} appears in {len(occurrences)} "
                                f"different documents ({len(doc_ids)} unique). "
                                "May indicate duplicate payment or invoice."
                            ),
                            severity=(
                                FindingSeverity.HIGH
                                if float(value) >= 10000
                                else FindingSeverity.MEDIUM
                            ),
                            category=FinancialCategory.DUPLICATE.value,
                            audit_type=AuditType.COMPLIANCE,
                            document_id=occurrences[0][1].document_id,
                            confidence=0.60,
                            evidence_text=f"Found in: {', '.join(locations)}",
                            evidence_location="Cross-document analysis",
                            recommendation="Verify these are not duplicate payments for the same transaction",
                            found_by="accounting_auditor",
                        )
                    )

        return findings

    def _check_split_transactions(
        self,
        amounts: list[tuple[ExtractedAmount, ChunkData]],
    ) -> list[AuditFinding]:
        """Check for split transactions (amounts that sum to just under thresholds)."""
        findings = []

        # Group amounts by document
        by_document: dict[str, list[ExtractedAmount]] = {}
        for amt, chunk in amounts:
            if chunk.document_id not in by_document:
                by_document[chunk.document_id] = []
            by_document[chunk.document_id].append(amt)

        # Check for combinations that sum to threshold
        thresholds = [1000, 5000, 10000, 25000, 50000]

        for doc_id, doc_amounts in by_document.items():
            if len(doc_amounts) < 2:
                continue

            values = [float(a.value) for a in doc_amounts if 100 <= float(a.value) <= 25000]

            # Check pairs that sum to just under thresholds
            for i, v1 in enumerate(values):
                for v2 in values[i + 1 :]:
                    total = v1 + v2
                    for threshold in thresholds:
                        if threshold * 0.95 <= total < threshold:
                            findings.append(
                                AuditFinding(
                                    title="Financial: Potential Split Transaction",
                                    description=(
                                        f"Amounts ${v1:,.2f} and ${v2:,.2f} sum to ${total:,.2f}, "
                                        f"which is just under the ${threshold:,} threshold. "
                                        "May indicate transaction splitting to avoid approval requirements."
                                    ),
                                    severity=FindingSeverity.MEDIUM,
                                    category=FinancialCategory.THRESHOLD.value,
                                    audit_type=AuditType.COMPLIANCE,
                                    document_id=doc_id,
                                    confidence=0.55,
                                    evidence_text=f"Combined: ${v1:,.2f} + ${v2:,.2f} = ${total:,.2f}",
                                    evidence_location="Cross-amount analysis",
                                    recommendation="Review for potential transaction splitting",
                                    found_by="accounting_auditor",
                                )
                            )
                            break  # Only report once per pair

        return findings


# Register with the audit registry on import
def register_accounting_auditor() -> None:
    """Register the accounting auditor with the global registry."""
    try:
        from ..registry import audit_registry

        audit_registry.register(AccountingAuditor())
    except ImportError:
        pass  # Registry not available


__all__ = [
    "AccountingAuditor",
    "FinancialCategory",
    "FinancialPattern",
    "AmountPattern",
    "ExtractedAmount",
    "JournalEntry",
    "register_accounting_auditor",
]
