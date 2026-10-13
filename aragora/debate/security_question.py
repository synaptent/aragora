"""
Security debate question builder.

Turns a SecurityEvent into the remediation prompt that the security debate
runner feeds to Arena. It depends only on the domain-free events module so
that both the runner (aragora.debate.security_debate) and the events-side
trigger (aragora.debate.security_response) can share it without importing
each other.
"""

from __future__ import annotations

from typing import Any

from aragora.events.security_events import (
    SecurityEvent,
    is_secret_finding,
    safe_secret_type,
)

__all__ = ["build_security_debate_question"]


def build_security_debate_question(event: SecurityEvent) -> str:
    """
    Build a debate question from security findings.

    Args:
        event: Security event with findings

    Returns:
        Formatted debate question
    """
    findings = event.findings[:5]  # Limit to top 5 findings

    if not findings:
        return f"Analyze and recommend remediation for security findings in {event.repository or 'the codebase'}."

    event_metadata = getattr(event, "metadata", None)
    if not isinstance(event_metadata, dict) or len(findings) != 1:
        event_metadata = None

    def _is_secret(finding: Any) -> bool:
        return is_secret_finding(finding, event_metadata=event_metadata)

    # Group secret-like findings first so aliases or mislabeled scanner output
    # never reach the unredacted vulnerability summary.
    secrets = [f for f in findings if _is_secret(f)]
    vulns = [f for f in findings if not _is_secret(f) and f.finding_type == "vulnerability"]

    question_parts = []

    if vulns:
        vuln_summary = ", ".join(f"{v.cve_id or v.title} in {v.package_name}" for v in vulns[:3])
        question_parts.append(f"vulnerabilities ({vuln_summary})")

    if secrets:
        secret_types = set(safe_secret_type(s.metadata.get("secret_type")) for s in secrets)
        question_parts.append(f"exposed secrets ({', '.join(secret_types)})")

    findings_str = " and ".join(question_parts)

    def _prompt_safe_title(finding: Any) -> str:
        if _is_secret(finding):
            return "Secret finding"
        return str(getattr(finding, "title", ""))

    def _prompt_safe_description(finding: Any) -> str:
        if _is_secret(finding):
            return "[redacted secret finding description]"
        return str(getattr(finding, "description", ""))[:200]

    return (
        f"Analyze the following critical security findings and provide remediation recommendations:\n\n"
        f"Repository: {event.repository or 'Unknown'}\n"
        f"Findings: {findings_str}\n\n"
        f"Details:\n"
        + "\n".join(
            f"- {f.severity.value.upper()}: {_prompt_safe_title(f)} - {_prompt_safe_description(f)}"
            for f in findings
        )
        + "\n\n"
        "What is the recommended prioritized remediation plan, considering:\n"
        "1. Immediate mitigations (quick wins)\n"
        "2. Root cause fixes\n"
        "3. Preventive measures for future\n"
        "4. Impact on existing functionality"
    )
