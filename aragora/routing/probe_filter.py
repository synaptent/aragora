"""
Probe-Aware Agent Filtering.

Reads probe vulnerability results and provides filtering/scoring
for agent selection in debates. Agents with high vulnerability rates
can be deprioritized or excluded from critical roles.

Features:
- Load probe history from .nomic/probes/{agent_name}/
- Calculate probe scores (inverse of vulnerability rate)
- Filter agents by vulnerability threshold
- Identify dominant weaknesses for targeted improvement
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProbeProfile:
    """Summary of an agent's probe history."""

    agent_name: str

    # Core metrics
    vulnerability_rate: float = 0.0  # 0-1, fraction of probes that found issues
    probe_score: float = 1.0  # 1 - vulnerability_rate (higher is better)

    # Severity breakdown
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # Dominant weakness (most common vulnerability type)
    dominant_weakness: str | None = None
    weakness_counts: dict[str, int] = field(default_factory=dict)

    # Metadata
    total_probes: int = 0
    last_probe_date: str | None = None
    days_since_probe: int = 999  # High default = stale
    report_count: int = 0

    # Recommendations from reports
    recommendations: list[str] = field(default_factory=list)

    def is_stale(self, max_days: int = 7) -> bool:
        """Check if probe data is too old to be reliable."""
        return self.days_since_probe > max_days

    def is_high_risk(self, threshold: float = 0.4) -> bool:
        """Check if agent has high vulnerability rate."""
        return self.vulnerability_rate > threshold

    def has_critical_issues(self) -> bool:
        """Check if agent has any critical vulnerabilities."""
        return self.critical_count > 0

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "vulnerability_rate": self.vulnerability_rate,
            "probe_score": self.probe_score,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "dominant_weakness": self.dominant_weakness,
            "total_probes": self.total_probes,
            "last_probe_date": self.last_probe_date,
            "days_since_probe": self.days_since_probe,
            "report_count": self.report_count,
        }


class ProbeFilter:
    """
    Loads probe history and provides filtering for agent selection.

    Usage:
        filter = ProbeFilter(nomic_dir=".nomic")
        profile = filter.get_agent_profile("claude-sonnet")

        # Filter agents for debate
        safe_agents = filter.filter_agents(
            candidates=["claude", "gemini", "grok"],
            max_vulnerability_rate=0.3,
            exclude_critical=True
        )

        # Get weighted scores for team selection
        scores = filter.get_team_scores(["claude", "gemini", "grok"])
    """

    def __init__(
        self,
        nomic_dir: str = ".nomic",
        cache_ttl_seconds: int = 300,  # 5 minute cache
    ):
        self.nomic_dir = Path(nomic_dir)
        self.probes_dir = self.nomic_dir / "probes"
        self.cache_ttl_seconds = cache_ttl_seconds

        # Cache profiles to avoid repeated file reads
        # Format: agent_name -> (profile, cached_at, dir_mtime)
        self._profile_cache: dict[str, tuple[ProbeProfile, datetime, float]] = {}

    def _get_dir_mtime(self, agent_name: str) -> float:
        """Get the latest modification time of probe files for an agent.

        Returns 0.0 if directory doesn't exist.
        """
        agent_probes_dir = self.probes_dir / agent_name
        if not agent_probes_dir.exists():
            return 0.0

        try:
            # Get max mtime of all probe files + directory itself
            mtimes = [agent_probes_dir.stat().st_mtime]
            for probe_file in agent_probes_dir.glob("*.json"):
                try:
                    mtimes.append(probe_file.stat().st_mtime)
                except OSError:
                    continue
            return max(mtimes)
        except OSError as e:
            logger.debug("Failed to get mtime for %s: %s", agent_name, e)
            return 0.0

    def get_agent_profile(self, agent_name: str) -> ProbeProfile:
        """
        Get probe profile for an agent.

        Loads and aggregates all probe reports for the agent,
        calculating overall vulnerability rate and identifying weaknesses.

        Cache invalidation occurs when:
        - TTL expires (cache_ttl_seconds)
        - Probe files have been modified (mtime check)
        """
        current_mtime = self._get_dir_mtime(agent_name)

        # Check cache
        if agent_name in self._profile_cache:
            profile, cached_at, cached_mtime = self._profile_cache[agent_name]

            # Check TTL and mtime
            ttl_valid = (datetime.now() - cached_at).total_seconds() < self.cache_ttl_seconds
            mtime_valid = current_mtime <= cached_mtime

            if ttl_valid and mtime_valid:
                return profile
            elif not mtime_valid:
                logger.debug("Cache invalidated for %s: probe files modified", agent_name)

        # Build fresh profile
        profile = self._load_profile(agent_name)
        self._profile_cache[agent_name] = (profile, datetime.now(), current_mtime)
        return profile

    def _load_profile(self, agent_name: str) -> ProbeProfile:
        """Load probe profile from stored reports."""
        profile = ProbeProfile(agent_name=agent_name)

        agent_probes_dir = self.probes_dir / agent_name
        if not agent_probes_dir.exists():
            logger.debug("No probe history for %s", agent_name)
            return profile

        # Load all probe reports
        reports = []
        for probe_file in agent_probes_dir.glob("*.json"):
            try:
                data = json.loads(probe_file.read_text())
                reports.append(data)
            except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
                logger.debug("Failed to load probe file %s: %s", probe_file, e)

        if not reports:
            return profile

        # Aggregate metrics from reports
        total_probes = 0
        total_vulnerabilities = 0
        weakness_counts: dict[str, int] = {}
        all_recommendations: list[str] = []
        latest_date: str | None = None

        for report in reports:
            probes_run = report.get("probes_run", 0)
            vulns_found = report.get("vulnerabilities_found", 0)

            total_probes += probes_run
            total_vulnerabilities += vulns_found

            # Count severities
            breakdown = report.get("breakdown", {})
            profile.critical_count += breakdown.get("critical", 0)
            profile.high_count += breakdown.get("high", 0)
            profile.medium_count += breakdown.get("medium", 0)
            profile.low_count += breakdown.get("low", 0)

            # Count weakness types
            by_type = report.get("by_type", {})
            for probe_type, results in by_type.items():
                vuln_count = sum(1 for r in results if r.get("vulnerability_found"))
                weakness_counts[probe_type] = weakness_counts.get(probe_type, 0) + vuln_count

            # Collect recommendations
            recs = report.get("recommendations", [])
            all_recommendations.extend(recs)

            # Track latest date
            created_at = report.get("created_at", "")
            if created_at and (not latest_date or created_at > latest_date):
                latest_date = created_at

        # Calculate aggregate metrics
        profile.total_probes = total_probes
        profile.report_count = len(reports)
        profile.vulnerability_rate = total_vulnerabilities / total_probes if total_probes > 0 else 0
        profile.probe_score = 1.0 - profile.vulnerability_rate
        profile.weakness_counts = weakness_counts
        profile.recommendations = list(set(all_recommendations))[:5]  # Top 5 unique

        # Find dominant weakness
        if weakness_counts:
            profile.dominant_weakness = max(
                weakness_counts.keys(), key=lambda k: weakness_counts[k]
            )

        # Calculate days since last probe
        if latest_date:
            profile.last_probe_date = latest_date
            try:
                last_dt = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
                profile.days_since_probe = (datetime.now() - last_dt.replace(tzinfo=None)).days
            except (ValueError, AttributeError) as e:
                logger.debug("Could not parse probe date '%s': %s", latest_date, e)
                profile.days_since_probe = 999

        return profile

    def filter_agents(
        self,
        candidates: list[str],
        max_vulnerability_rate: float = 0.5,
        exclude_critical: bool = True,
        exclude_stale: bool = False,
        stale_days: int = 7,
    ) -> list[str]:
        """
        Filter agent candidates based on probe results.

        Args:
            candidates: List of agent names to filter
            max_vulnerability_rate: Maximum allowed vulnerability rate (0-1)
            exclude_critical: Exclude agents with any critical vulnerabilities
            exclude_stale: Exclude agents with stale (old) probe data
            stale_days: Days after which probe data is considered stale

        Returns:
            List of agent names that pass the filter
        """
        filtered = []

        for agent in candidates:
            profile = self.get_agent_profile(agent)

            # No probe data = allow (can't penalize unprobed agents)
            if profile.total_probes == 0:
                filtered.append(agent)
                continue

            # Check exclusion criteria
            if profile.vulnerability_rate > max_vulnerability_rate:
                logger.debug(
                    "Excluding %s: vulnerability rate %.0f%% > %.0f%%",
                    agent,
                    profile.vulnerability_rate * 100,
                    max_vulnerability_rate * 100,
                )
                continue

            if exclude_critical and profile.has_critical_issues():
                logger.debug("Excluding %s: has critical vulnerabilities", agent)
                continue

            if exclude_stale and profile.is_stale(stale_days):
                logger.debug(
                    "Excluding %s: probe data is %s days old", agent, profile.days_since_probe
                )
                continue

            filtered.append(agent)

        return filtered

    def get_team_scores(
        self,
        candidates: list[str],
        base_score: float = 1.0,
    ) -> dict[str, float]:
        """
        Get weighted scores for team selection.

        Agents with lower vulnerability rates get higher scores,
        enabling weighted random selection that favors reliable agents.

        Args:
            candidates: List of agent names
            base_score: Base score for agents without probe data

        Returns:
            Dict mapping agent names to selection scores
        """
        scores = {}

        for agent in candidates:
            profile = self.get_agent_profile(agent)

            if profile.total_probes == 0:
                # No probe data = base score
                scores[agent] = base_score
            else:
                # Score based on probe performance
                # probe_score is 1 - vulnerability_rate
                score = profile.probe_score

                # Penalty for critical issues
                if profile.critical_count > 0:
                    score *= 0.5

                # Penalty for stale data (less trust in old results)
                if profile.days_since_probe > 14:
                    score = (score + base_score) / 2  # Blend toward base

                scores[agent] = max(0.1, score)  # Minimum 0.1 to keep in pool

        return scores

    def get_role_recommendation(
        self,
        agent_name: str,
    ) -> str:
        """
        Recommend appropriate debate role based on probe profile.

        Returns role suggestion: "proposer", "critic", "judge", or "observer"
        """
        profile = self.get_agent_profile(agent_name)

        if profile.total_probes == 0:
            return "proposer"  # No data, allow normal participation

        if profile.has_critical_issues():
            return "observer"  # Too risky for active role

        if profile.vulnerability_rate > 0.4:
            return "critic"  # Can critique but not propose

        if profile.vulnerability_rate > 0.2:
            return "proposer"  # Normal participation

        # Low vulnerability = trusted for judgment
        return "judge"

    def clear_cache(self):
        """Clear the profile cache."""
        self._profile_cache.clear()

    def get_all_profiles(self) -> dict[str, ProbeProfile]:
        """Get profiles for all agents with probe data."""
        profiles: dict[str, ProbeProfile] = {}

        if not self.probes_dir.exists():
            return profiles

        for agent_dir in self.probes_dir.iterdir():
            if agent_dir.is_dir():
                agent_name = agent_dir.name
                profiles[agent_name] = self.get_agent_profile(agent_name)

        return profiles

    def format_summary(self) -> str:
        """Format a summary of all probe profiles for logging."""
        profiles = self.get_all_profiles()

        if not profiles:
            return "No probe data available"

        lines = ["Agent Probe Summary:", "-" * 40]

        for name, profile in sorted(profiles.items(), key=lambda x: x[1].probe_score, reverse=True):
            status = (
                "OK"
                if profile.probe_score >= 0.7
                else "WARN"
                if profile.probe_score >= 0.5
                else "RISK"
            )
            weakness = f" [{profile.dominant_weakness}]" if profile.dominant_weakness else ""
            lines.append(
                f"  {name}: {profile.probe_score:.0%} score, "
                f"{profile.total_probes} probes, "
                f"{profile.critical_count}C/{profile.high_count}H issues "
                f"({status}){weakness}"
            )

        return "\n".join(lines)
