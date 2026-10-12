"""
Red Team validator for TestFixer proposed fixes.

Uses adversarial attack/defend cycles to stress-test proposed fixes
before they are applied. Identifies edge cases, regressions, and
issues that simple review might miss.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum

from aragora.agents.base import create_agent
from aragora.core import Agent
from aragora.nomic.testfixer.analyzer import FailureAnalysis
from aragora.nomic.testfixer.proposer import PatchProposal

logger = logging.getLogger(__name__)


class CodeAttackType(str, Enum):
    """Types of attacks specific to code fixes."""

    REGRESSION = "regression"  # Will this break existing functionality?
    EDGE_CASE = "edge_case"  # Boundary conditions not handled
    INCOMPLETE_FIX = "incomplete_fix"  # Only partially fixes the issue
    NEW_BUG = "new_bug"  # Introduces a different bug
    SIDE_EFFECT = "side_effect"  # Unintended changes elsewhere
    TYPE_ERROR = "type_error"  # Type mismatches
    CONCURRENCY = "concurrency"  # Race conditions, deadlocks
    SECURITY = "security"  # Security vulnerabilities
    PERFORMANCE = "performance"  # Performance degradation
    API_BREAK = "api_break"  # Breaks public API contract


@dataclass
class CodeAttack:
    """An attack on a proposed fix."""

    id: str
    attack_type: CodeAttackType
    attacker: str
    description: str
    severity: float  # 0-1
    exploit: str  # How this could manifest
    evidence: str = ""  # Specific code/scenario


@dataclass
class CodeDefense:
    """A defense against an attack."""

    attack_id: str
    defender: str
    defense_type: str  # "refute", "mitigate", "accept"
    explanation: str
    success: bool
    residual_risk: float = 0.0


@dataclass
class RedTeamResult:
    """Result of red team validation."""

    # Overall assessment
    passes: bool
    robustness_score: float  # 0-1, how well fix held up
    confidence: float

    # Attack/defense details
    total_attacks: int
    successful_attacks: int
    mitigated_attacks: int
    accepted_risks: int

    # Specific findings
    critical_issues: list[CodeAttack] = field(default_factory=list)
    warnings: list[CodeAttack] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    # Rounds
    attack_rounds: int = 0
    defend_rounds: int = 0

    def summary(self) -> str:
        """Human-readable summary."""
        status = "PASS" if self.passes else "FAIL"
        return (
            f"{status} (robustness: {self.robustness_score:.0%}, "
            f"{self.successful_attacks}/{self.total_attacks} attacks succeeded, "
            f"{len(self.critical_issues)} critical issues)"
        )


@dataclass
class RedTeamValidatorConfig:
    """Configuration for red team validation."""

    # Agents to use
    attacker_types: list[str] = field(default_factory=lambda: ["anthropic-api", "openai-api"])
    defender_type: str = "anthropic-api"

    # Attack settings
    attack_rounds: int = 2
    attacks_per_round: int = 3
    attack_types: list[CodeAttackType] = field(
        default_factory=lambda: [
            CodeAttackType.REGRESSION,
            CodeAttackType.EDGE_CASE,
            CodeAttackType.INCOMPLETE_FIX,
            CodeAttackType.NEW_BUG,
            CodeAttackType.SIDE_EFFECT,
        ]
    )

    # Defense settings
    defend_rounds: int = 1
    allow_defense: bool = True

    # Thresholds
    max_critical_issues: int = 0  # Fail if more than this
    max_successful_attacks: int = 2
    min_robustness_score: float = 0.6

    # Timeouts
    agent_timeout: float = 60.0
    total_timeout: float = 300.0

    # Context limits
    max_context_chars: int = 40_000


class RedTeamValidator:
    """Validates fixes using adversarial red team attacks.

    Uses attack/defend cycles where:
    1. Attacker agents try to find issues with the fix
    2. Defender agent explains why issues are invalid or how to mitigate
    3. Result scored based on how well fix held up

    Example:
        config = RedTeamValidatorConfig(
            attack_rounds=2,
            attacker_types=["anthropic-api", "openai-api"],
        )
        validator = RedTeamValidator(config)

        result = await validator.validate(proposal, analysis)

        if result.passes and not result.critical_issues:
            proposal.apply_all(repo_path)
    """

    def __init__(self, config: RedTeamValidatorConfig | None = None):
        """Initialize the red team validator."""
        self.config = config or RedTeamValidatorConfig()
        self.attackers: list[Agent] = []
        self.defender: Agent | None = None
        self._initialized = False

    def _ensure_agents(self) -> None:
        """Lazily initialize agents on first use."""
        if self._initialized:
            return

        # Create attacker agents
        for agent_type in self.config.attacker_types:
            try:
                agent = create_agent(
                    model_type=agent_type,  # type: ignore[arg-type]
                    name=f"attacker_{agent_type}",
                    role="critic",
                    timeout=self.config.agent_timeout,
                )
                self.attackers.append(agent)
                logger.info("redteam_validator.attacker_created type=%s", agent_type)
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
                logger.warning(
                    "redteam_validator.attacker_failed type=%s: %s",
                    agent_type,
                    e,
                )

        # Create defender agent
        if self.config.allow_defense:
            try:
                self.defender = create_agent(
                    model_type=self.config.defender_type,  # type: ignore[arg-type]
                    name=f"defender_{self.config.defender_type}",
                    role="proposer",
                    timeout=self.config.agent_timeout,
                )
                logger.info("redteam_validator.defender_created type=%s", self.config.defender_type)
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
                logger.warning(
                    "redteam_validator.defender_failed type=%s: %s",
                    self.config.defender_type,
                    e,
                )

        if not self.attackers:
            raise RuntimeError("No attacker agents could be initialized")

        self._initialized = True

    def _truncate(self, text: str, limit: int) -> str:
        """Truncate text with middle ellipsis."""
        if len(text) <= limit:
            return text
        head = limit // 2 - 100
        tail = limit // 2 - 100
        return f"{text[:head]}\n\n[... {len(text) - limit} chars truncated ...]\n\n{text[-tail:]}"

    def _build_attack_prompt(
        self,
        proposal: PatchProposal,
        analysis: FailureAnalysis,
        attack_types: list[CodeAttackType],
        round_num: int,
    ) -> str:
        """Build prompt for attack phase."""
        patches_summary = []
        for patch in proposal.patches[:3]:
            patches_summary.append(
                f"**{patch.file_path}**:\n```python\n{self._truncate(patch.patched_content, 3000)}\n```"
            )

        patches_text = "\n\n".join(patches_summary)
        attack_types_text = ", ".join(t.value.replace("_", " ").upper() for t in attack_types)

        return f"""## RED TEAM ATTACK MISSION

You are a code security and quality red team agent. Your mission is to find
vulnerabilities and issues in this proposed fix BEFORE it's applied.

### Original Failure Being Fixed
**Test:** {analysis.failure.test_name}
**Error:** {analysis.failure.error_type}: {analysis.failure.error_message}

### Proposed Fix
{patches_text}

### Fix Description
{proposal.description}

### Attack Categories to Explore
Focus on these issue types: {attack_types_text}

### Your Task (Round {round_num}/{self.config.attack_rounds})

Find {self.config.attacks_per_round} potential issues with this fix. For each issue:

1. **ATTACK_TYPE**: Which category (one of: {attack_types_text})
2. **DESCRIPTION**: What is the problem?
3. **SEVERITY**: CRITICAL / HIGH / MEDIUM / LOW
4. **EXPLOIT**: How would this issue manifest? Give a specific scenario.
5. **EVIDENCE**: Code example or test case that would expose this issue.

Format each attack as:

---
ATTACK_TYPE: [type]
DESCRIPTION: [what's wrong]
SEVERITY: [level]
EXPLOIT: [how it could fail]
EVIDENCE: [specific example]
---

Be adversarial but realistic. Focus on REAL issues, not theoretical nitpicks.
Prioritize issues that would cause test failures or production bugs.
"""

    def _build_defense_prompt(
        self,
        proposal: PatchProposal,
        attacks: list[CodeAttack],
        round_num: int,
    ) -> str:
        """Build prompt for defense phase."""
        attacks_text = "\n".join(
            [
                f"- **{a.attack_type.value}**: {a.description} (Severity: {a.severity:.0%})\n  Exploit: {a.exploit}"
                for a in attacks
            ]
        )

        return f"""## DEFENSE MISSION

You are defending this proposed fix against red team attacks.

### Your Fix
{proposal.description}

### Attacks Against Your Fix
{attacks_text}

### Your Task (Round {round_num}/{self.config.defend_rounds})

For EACH attack, respond with:

1. **ATTACK_ID**: Reference the attack
2. **DEFENSE**: One of:
   - REFUTE: The attack is invalid because...
   - MITIGATE: Accept the issue but it can be fixed by...
   - ACCEPT: Accept the risk because the tradeoff is worth it...
3. **EXPLANATION**: Detailed reasoning
4. **RESIDUAL_RISK**: If mitigated/accepted, what risk remains? (0-100%)

Format each defense as:

---
ATTACK_ID: [attack type]
DEFENSE: [REFUTE/MITIGATE/ACCEPT]
EXPLANATION: [reasoning]
RESIDUAL_RISK: [0-100%]
---

Be honest. Don't dismiss valid concerns - acknowledge and explain tradeoffs.
"""

    def _parse_attacks(self, response: str, attacker: str) -> list[CodeAttack]:
        """Parse attacks from agent response."""
        attacks = []

        # Split on --- separators
        sections = re.split(r"\n---+\n", response)

        for section in sections:
            if not section.strip():
                continue

            # Parse attack fields
            attack_type_match = re.search(r"ATTACK_TYPE:\s*(\S+)", section, re.IGNORECASE)
            description_match = re.search(
                r"DESCRIPTION:\s*(.+?)(?=\n[A-Z_]+:|$)", section, re.IGNORECASE | re.DOTALL
            )
            severity_match = re.search(r"SEVERITY:\s*(\S+)", section, re.IGNORECASE)
            exploit_match = re.search(
                r"EXPLOIT:\s*(.+?)(?=\n[A-Z_]+:|$)", section, re.IGNORECASE | re.DOTALL
            )
            evidence_match = re.search(
                r"EVIDENCE:\s*(.+?)(?=\n---|\Z)", section, re.IGNORECASE | re.DOTALL
            )

            if not attack_type_match or not description_match:
                continue

            # Map severity to float
            severity_str = (severity_match.group(1) if severity_match else "medium").upper()
            severity_map = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}
            severity = severity_map.get(severity_str, 0.5)

            # Map attack type
            attack_type_str = attack_type_match.group(1).upper().replace(" ", "_")
            try:
                attack_type = CodeAttackType(attack_type_str.lower())
            except ValueError:
                attack_type = CodeAttackType.NEW_BUG  # Default

            attack = CodeAttack(
                id=f"attack_{uuid.uuid4().hex[:8]}",
                attack_type=attack_type,
                attacker=attacker,
                description=description_match.group(1).strip(),
                severity=severity,
                exploit=exploit_match.group(1).strip() if exploit_match else "",
                evidence=evidence_match.group(1).strip() if evidence_match else "",
            )
            attacks.append(attack)

        return attacks

    def _parse_defenses(
        self, response: str, defender: str, attacks: list[CodeAttack]
    ) -> list[CodeDefense]:
        """Parse defenses from agent response."""
        defenses = []

        sections = re.split(r"\n---+\n", response)

        for section in sections:
            if not section.strip():
                continue

            attack_id_match = re.search(r"ATTACK_ID:\s*(.+)", section, re.IGNORECASE)
            defense_match = re.search(r"DEFENSE:\s*(\S+)", section, re.IGNORECASE)
            explanation_match = re.search(
                r"EXPLANATION:\s*(.+?)(?=\n[A-Z_]+:|$)", section, re.IGNORECASE | re.DOTALL
            )
            risk_match = re.search(r"RESIDUAL_RISK:\s*(\d+)", section, re.IGNORECASE)

            if not defense_match:
                continue

            defense_type = defense_match.group(1).upper()
            success = defense_type == "REFUTE"
            residual_risk = (
                int(risk_match.group(1)) / 100 if risk_match else (0.0 if success else 0.5)
            )

            # Try to match to an attack
            attack_ref = attack_id_match.group(1).strip().lower() if attack_id_match else ""
            matched_attack = None
            for attack in attacks:
                if (
                    attack.attack_type.value in attack_ref
                    or attack_ref in attack.description.lower()
                ):
                    matched_attack = attack
                    break

            if matched_attack:
                defense = CodeDefense(
                    attack_id=matched_attack.id,
                    defender=defender,
                    defense_type=defense_type.lower(),
                    explanation=explanation_match.group(1).strip() if explanation_match else "",
                    success=success,
                    residual_risk=residual_risk,
                )
                defenses.append(defense)

        return defenses

    async def _run_attack_round(
        self,
        proposal: PatchProposal,
        analysis: FailureAnalysis,
        round_num: int,
    ) -> list[CodeAttack]:
        """Run one round of attacks."""
        all_attacks = []

        # Select attack types for this round
        attack_types = (
            self.config.attack_types[(round_num - 1) * 2 : round_num * 2 + 1]
            or self.config.attack_types[:3]
        )

        prompt = self._build_attack_prompt(proposal, analysis, attack_types, round_num)

        # Run attacks in parallel
        attack_tasks = []
        for attacker in self.attackers:
            attack_tasks.append(attacker.generate(prompt))

        try:
            responses = await asyncio.wait_for(
                asyncio.gather(*attack_tasks, return_exceptions=True),
                timeout=self.config.agent_timeout * len(self.attackers),
            )

            for attacker, response in zip(self.attackers, responses):
                if isinstance(response, Exception):
                    logger.warning(
                        "redteam_validator.attack_error agent=%s error=%s", attacker.name, response
                    )
                    continue
                attacks = self._parse_attacks(str(response), attacker.name)
                all_attacks.extend(attacks)

        except asyncio.TimeoutError:
            logger.warning("redteam_validator.attack_round_timeout round=%d", round_num)

        return all_attacks

    async def _run_defense_round(
        self,
        proposal: PatchProposal,
        attacks: list[CodeAttack],
        round_num: int,
    ) -> list[CodeDefense]:
        """Run one round of defenses."""
        if not self.defender or not attacks:
            return []

        prompt = self._build_defense_prompt(proposal, attacks, round_num)

        try:
            response = await asyncio.wait_for(
                self.defender.generate(prompt),
                timeout=self.config.agent_timeout,
            )
            return self._parse_defenses(response, self.defender.name, attacks)

        except asyncio.TimeoutError:
            logger.warning("redteam_validator.defense_timeout round=%d", round_num)
            return []
        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.warning("redteam_validator.defense_error: %s", e)
            return []

    async def validate(
        self,
        proposal: PatchProposal,
        analysis: FailureAnalysis,
    ) -> RedTeamResult:
        """Validate a proposed fix using red team attacks.

        Args:
            proposal: The proposed fix to validate
            analysis: The failure analysis that led to this fix

        Returns:
            RedTeamResult with attack/defense details
        """
        self._ensure_agents()

        logger.info(
            "redteam_validator.start proposal_id=%s attack_rounds=%d",
            proposal.id,
            self.config.attack_rounds,
        )

        all_attacks: list[CodeAttack] = []
        all_defenses: list[CodeDefense] = []

        try:
            # Run attack rounds
            for round_num in range(1, self.config.attack_rounds + 1):
                attacks = await self._run_attack_round(proposal, analysis, round_num)
                all_attacks.extend(attacks)
                logger.info(
                    "redteam_validator.attack_round round=%d attacks=%d",
                    round_num,
                    len(attacks),
                )

            # Run defense rounds
            if self.config.allow_defense and all_attacks:
                for round_num in range(1, self.config.defend_rounds + 1):
                    defenses = await self._run_defense_round(proposal, all_attacks, round_num)
                    all_defenses.extend(defenses)
                    logger.info(
                        "redteam_validator.defense_round round=%d defenses=%d",
                        round_num,
                        len(defenses),
                    )

        except asyncio.TimeoutError:
            logger.warning("redteam_validator.total_timeout")

        # Calculate results
        total_attacks = len(all_attacks)
        _successful_defenses = len([d for d in all_defenses if d.success])

        # An attack is "successful" if not refuted
        defended_attack_ids = {d.attack_id for d in all_defenses if d.success}
        mitigated_attack_ids = {d.attack_id for d in all_defenses if d.defense_type == "mitigate"}
        accepted_attack_ids = {d.attack_id for d in all_defenses if d.defense_type == "accept"}

        successful_attacks = len([a for a in all_attacks if a.id not in defended_attack_ids])

        critical_issues = [
            a for a in all_attacks if a.severity >= 0.8 and a.id not in defended_attack_ids
        ]
        warnings = [
            a for a in all_attacks if 0.4 <= a.severity < 0.8 and a.id not in defended_attack_ids
        ]

        # Calculate robustness score
        if total_attacks > 0:
            robustness_score = 1.0 - (successful_attacks / total_attacks)
        else:
            robustness_score = 1.0

        # Determine if validation passes
        passes = (
            len(critical_issues) <= self.config.max_critical_issues
            and successful_attacks <= self.config.max_successful_attacks
            and robustness_score >= self.config.min_robustness_score
        )

        # Calculate confidence
        confidence = robustness_score * 0.7 + (0.3 if total_attacks >= 3 else 0.1)
        confidence = min(1.0, confidence)

        # Extract suggestions from mitigations
        suggestions = []
        for defense in all_defenses:
            if defense.defense_type == "mitigate" and defense.explanation:
                suggestions.append(defense.explanation[:200])

        result = RedTeamResult(
            passes=passes,
            robustness_score=robustness_score,
            confidence=confidence,
            total_attacks=total_attacks,
            successful_attacks=successful_attacks,
            mitigated_attacks=len(mitigated_attack_ids),
            accepted_risks=len(accepted_attack_ids),
            critical_issues=critical_issues,
            warnings=warnings,
            suggestions=suggestions[:5],
            attack_rounds=self.config.attack_rounds,
            defend_rounds=self.config.defend_rounds,
        )

        logger.info(
            "redteam_validator.complete proposal_id=%s passes=%s robustness=%.2f critical=%d",
            proposal.id,
            result.passes,
            result.robustness_score,
            len(result.critical_issues),
        )

        return result
