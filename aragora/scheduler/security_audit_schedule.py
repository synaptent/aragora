"""
Security Audit Scheduling.

Provides scheduled security scans using the AuditScheduler with
security-specific configurations and optional multi-agent debate.

Usage:
    from aragora.scheduler.security_audit_schedule import (
        add_daily_security_scan,
        run_security_scan_with_debate,
    )

    # Add daily 2 AM security scan
    scheduler = get_scheduler()
    add_daily_security_scan(scheduler, debate_on_critical=True)

    # Manual trigger with debate
    result = await run_security_scan_with_debate(
        path="aragora/",
        debate_on_critical=True,
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.scheduler.audit_scheduler import AuditScheduler, ScheduledJob

logger = logging.getLogger(__name__)


def add_daily_security_scan(
    scheduler: AuditScheduler,
    cron: str = "0 2 * * *",
    path: str = "aragora/",
    debate_on_critical: bool = True,
    name: str = "daily_security_scan",
    workspace_id: str | None = None,
) -> ScheduledJob:
    """
    Add a daily security scan schedule.

    Args:
        scheduler: The AuditScheduler instance
        cron: Cron expression (default: 2 AM daily)
        path: Directory to scan
        debate_on_critical: Whether to trigger debates on critical findings
        name: Schedule name
        workspace_id: Optional workspace filter

    Returns:
        The created ScheduledJob
    """
    from aragora.scheduler.audit_scheduler import ScheduleConfig, TriggerType

    config = ScheduleConfig(
        name=name,
        description="Automated security vulnerability scan with optional AI debate on critical findings",
        trigger_type=TriggerType.CRON,
        cron=cron,
        preset="Security",
        audit_types=["security_scan"],
        custom_config={
            "scan_type": "security",
            "path": path,
            "debate_on_critical": debate_on_critical,
            "include_low_severity": False,
        },
        workspace_id=workspace_id,
        notify_on_findings=True,
        finding_severity_threshold="high",
        timeout_minutes=30,
        tags=["security", "automated", "scheduled"],
    )

    job = scheduler.add_schedule(config)
    logger.info("Added security scan schedule: %s (cron: %s)", name, cron)

    return job


async def run_security_scan_with_debate(
    path: str = "aragora/",
    debate_on_critical: bool = True,
    include_low_severity: bool = False,
    confidence_threshold: float = 0.7,
) -> dict[str, Any]:
    """
    Run a security scan and optionally trigger a debate on critical findings.

    This is a convenience function for manual or programmatic triggering
    of security scans with AI-assisted analysis.

    Args:
        path: Directory to scan
        debate_on_critical: Whether to debate critical findings
        include_low_severity: Include low severity findings in scan
        confidence_threshold: Debate confidence threshold

    Returns:
        Dict with scan results and optional debate outcome
    """
    from aragora.audit.security_scanner import SecurityScanner, SecuritySeverity

    # Run the scan
    scanner = SecurityScanner(include_low_severity=include_low_severity)
    report = scanner.scan_directory(path)

    result: dict[str, Any] = {
        "scan_id": report.scan_id,
        "path": path,
        "files_scanned": report.files_scanned,
        "lines_scanned": report.lines_scanned,
        "risk_score": report.risk_score,
        "critical_count": report.critical_count,
        "high_count": report.high_count,
        "medium_count": report.medium_count,
        "low_count": report.low_count,
        "total_findings": report.total_findings,
        "debated": False,
    }

    # Trigger debate if critical findings exist
    if debate_on_critical and report.critical_count > 0:
        try:
            from aragora.debate.security_debate import run_security_debate
            from aragora.events.security_events import (
                SecurityEvent,
                SecurityEventType,
                SecurityFinding as EventFinding,
                SecuritySeverity as EventSeverity,
            )

            # Convert scanner findings to event findings
            event_findings = []
            for f in report.findings:
                if f.severity == SecuritySeverity.CRITICAL:
                    event_finding = EventFinding(
                        id=f.id,
                        finding_type="vulnerability",
                        severity=EventSeverity(f.severity.value),
                        title=f.title,
                        description=f.description,
                        file_path=f.file_path,
                        line_number=f.line_number,
                        recommendation=f.recommendation,
                    )
                    event_findings.append(event_finding)

            # Limit to top 10 critical findings for debate
            event_findings = event_findings[:10]

            event = SecurityEvent(
                event_type=SecurityEventType.SAST_CRITICAL,
                severity=EventSeverity.CRITICAL,
                source="scheduler",
                repository=path,
                findings=event_findings,
                metadata={
                    "scan_id": report.scan_id,
                    "total_critical": report.critical_count,
                },
            )

            logger.info("Triggering security debate for %s critical findings", len(event_findings))

            debate_result = await run_security_debate(
                event,
                confidence_threshold=confidence_threshold,
            )

            result["debated"] = True
            result["debate"] = {
                "debate_id": debate_result.debate_id
                if hasattr(debate_result, "debate_id")
                else event.id,
                "consensus_reached": debate_result.consensus_reached,
                "confidence": debate_result.confidence,
                "final_answer": debate_result.final_answer,
                "rounds_used": debate_result.rounds_used,
            }

            logger.info(
                "Security debate completed: consensus=%s, confidence=%.2f",
                debate_result.consensus_reached,
                debate_result.confidence,
            )

        except ImportError as e:
            logger.warning("Security debate module not available: %s", e)
            result["debate_error"] = "Security debate module not available"
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            logger.error("Security debate failed: %s", e)
            result["debate_error"] = "Security debate failed"

    return result


def setup_default_security_schedules(scheduler: AuditScheduler) -> list[ScheduledJob]:
    """
    Set up default security scan schedules.

    Creates:
    - Daily security scan at 2 AM
    - Weekly comprehensive scan on Sundays at 3 AM

    Args:
        scheduler: The AuditScheduler instance

    Returns:
        List of created ScheduledJob instances
    """
    jobs = []

    # Daily scan
    jobs.append(
        add_daily_security_scan(
            scheduler,
            cron="0 2 * * *",
            debate_on_critical=True,
            name="daily_security_scan",
        )
    )

    # Weekly comprehensive scan (includes low severity)
    from aragora.scheduler.audit_scheduler import ScheduleConfig, TriggerType

    weekly_config = ScheduleConfig(
        name="weekly_comprehensive_security_scan",
        description="Weekly comprehensive security scan including all severity levels",
        trigger_type=TriggerType.CRON,
        cron="0 3 * * 0",  # Sunday 3 AM
        preset="Security",
        audit_types=["security_scan"],
        custom_config={
            "scan_type": "security",
            "path": "aragora/",
            "debate_on_critical": True,
            "include_low_severity": True,
        },
        notify_on_findings=True,
        finding_severity_threshold="medium",
        timeout_minutes=60,
        tags=["security", "automated", "weekly", "comprehensive"],
    )
    jobs.append(scheduler.add_schedule(weekly_config))

    logger.info("Set up %s default security schedules", len(jobs))
    return jobs


__all__ = [
    "add_daily_security_scan",
    "run_security_scan_with_debate",
    "setup_default_security_schedules",
]
