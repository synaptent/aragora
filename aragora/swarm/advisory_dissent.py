"""Human-readable collection summaries, separate from countable evidence.

The composer accepts a CollectOutcome or its dry-run JSON dictionary unchanged.
An explicit head may differ from the artifact head for offline rendering; posting
requires the body's marker to match the supplied head. Calls for a head are
serialized by the caller (GitHub issue comments have no atomic upsert).
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from aragora.cli.commands.review_queue_comment_verdicts import extract_finding_lines
from aragora.swarm.quorum_evidence import (
    CollectOutcome,
    _neutralize_reviewer_text,
    canonical_family,
    merge_quorum_io,
)

_TOKENS = re.compile(
    r"dogfood|adversarial|cross-author|recheck|codex review|claude review|"
    r"grok independent|gemini independent|independent semantic review|"
    r"independent model review|model-family semantic signal",
    re.I,
)
_PRIORITY = re.compile(r"\[P([0-3])\]", re.I)
_BODY_LIMIT = 60000
_EXCERPT_LIMIT = 8000
_TRUNCATED = "[truncated]"


@dataclass(frozen=True)
class AdvisoryPostResult:
    posted: bool
    comment_url: str | None
    reason: str | None
    edited: bool


def _marker(head_sha: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise ValueError("advisory summary requires a full head SHA")
    return f"<!-- aragora-advisory-summary head={head_sha} -->"


def _clip(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    kept = encoded[: limit - len(_TRUNCATED)].decode("utf-8", errors="ignore")
    if kept.rfind("&") > kept.rfind(";"):
        kept = kept[: kept.rfind("&")]
    return kept + _TRUNCATED


def _safe_text(value: Any, *, inline: bool = False) -> str:
    text = _neutralize_reviewer_text(str(value))
    text = html.escape(" ".join(text.split()) if inline else text, quote=False)
    # Entities preserve readable words without activating substring recognisers.
    while _TOKENS.search(text):
        text = _TOKENS.sub(lambda m: f"{m[0][0]}&#{ord(m[0][1])};{m[0][2:]}", text)
    text = _PRIORITY.sub(r"(P\1)", text)
    return re.sub(
        r"((?:model family|reviewer harness|transport grounding|reviewer)[\s*_]*):",
        r"\1&#58;",
        text,
        flags=re.I,
    )


def _findings(body: str) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for line in extract_finding_lines(body):
        match = re.match(r"\[(P[0-3])\]\s*(.*)", line)
        if match:
            findings.append((match[1], match[2].strip()))
    return findings


def compose_advisory_dissent_summary(outcome: CollectOutcome | dict, *, head_sha: str) -> str:
    """Render all families and findings without emitting an evidence identity."""
    data = outcome.to_dict() if isinstance(outcome, CollectOutcome) else outcome
    items = data.get("items") or []
    if not items:
        return ""
    marker = _marker(head_sha)
    families = []
    findings: list[tuple[str, str, str]] = []
    for item in items:
        family = canonical_family(str(item.get("family") or "unknown"))
        family = (
            family if re.fullmatch(r"[a-z]+", family) and not _TOKENS.search(family) else "unknown"
        )
        families.append(family)
        findings.extend((sev, family, text) for sev, text in _findings(item.get("body") or ""))
    findings.sort(key=lambda finding: finding[0])
    blocking = sum(sev in {"P0", "P1"} for sev, _, _ in findings)
    summary = (
        f"Summary: {blocking} blocking and {len(findings) - blocking} advisory findings."
        if blocking
        else f"Summary: {len(findings)} advisory findings."
    )
    summary += " Severity labels only; not a merge decision."
    flags = [item.get("severity_gated") for item in items]
    if any(flag is False for flag in flags):
        regime = "severity-gated dissent OFF; a changes-requested verdict blocks the merge gate whatever its findings."
    elif all(flag is True for flag in flags):
        regime = "severity-gated dissent ON; P2/P3 findings are advisory to the merge gate."
    else:
        regime = "unknown (outcome carries no severity_gated field)."
    raw = data.get("dissenting_families")
    dissent = "unknown (outcome carries no gate dissent list)."
    if isinstance(raw, list):
        names = (canonical_family(str(name)) for name in raw)
        gate_families = {
            name if re.fullmatch(r"[a-z]+", name) and not _TOKENS.search(name) else "unknown"
            for name in names
        }
        dissent = (", ".join(sorted(gate_families)) or "none") + "."
    lines = [
        marker,
        "",
        "## Collection summary",
        "",
        summary,
        f"Gate regime: {regime}",
        f"Merge-gate dissent: {dissent}",
        "",
        "### Family outcomes",
    ]
    for family, item in zip(families, items):
        verdict = str(item.get("verdict") or "unknown")
        verdict = verdict if verdict in {"pass", "changes_requested", "unknown"} else "unknown"
        lines.append(f"- {family}: {verdict}")
    lines.extend(
        [
            "",
            "### Adjudication",
            "",
            "> " + _clip(_safe_text(data.get("adjudication") or "none", inline=True), 2000),
            "",
            "### Collection action",
            "",
            "> " + _clip(_safe_text(data.get("action", "prepare"), inline=True), 200),
            "> " + _clip(_safe_text(data.get("action_reason", ""), inline=True), 2000),
            "",
            "### Findings",
            "",
        ]
    )
    prefixes = [
        f"- [{sev}] {family} ({'blocking' if sev in {'P0', 'P1'} else 'advisory'}): "
        for sev, family, _ in findings
    ]
    fixed = len(("\n".join(lines) + "\n" + "\n".join(prefixes)).encode())
    detail_limit = (45000 - fixed) // max(1, len(findings))
    if detail_limit < len(_TRUNCATED):
        raise ValueError("too many findings for one advisory summary")
    for prefix, (_, _, detail) in zip(prefixes, findings):
        lines.append(prefix + _clip(_safe_text(detail, inline=True), detail_limit))
    if not findings:
        lines.append("No severity-tagged findings.")
    body = "\n".join(lines)
    for index, item in enumerate(items):
        heading = f"\n\n### Output {index + 1}\n\n"
        remaining = _BODY_LIMIT - len(body.encode()) - len(heading)
        budget = min(_EXCERPT_LIMIT - 2, remaining)
        if budget < 2 + len(_TRUNCATED):
            break
        text = _safe_text(item.get("body") or "")
        quoted = "\n".join("> " + line for line in text.splitlines())
        body += heading + _clip(quoted, budget)
    return body


def post_advisory_summary(repo: str, pr: int, body: str, *, head_sha: str) -> AdvisoryPostResult:
    """Edit the same-head summary or create one; never mutate gate state."""
    if not body.strip():
        return AdvisoryPostResult(False, None, "items: []; no reviewer output", False)
    try:
        marker = _marker(head_sha)
        if body.splitlines()[0] != marker or len(body.encode()) > _BODY_LIMIT:
            raise ValueError("invalid advisory summary body")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or pr <= 0:
            raise ValueError("invalid advisory summary target")
        env = merge_quorum_io.aragora_env()
        endpoint = f"repos/{repo}/issues/{pr}/comments"
        result = merge_quorum_io.run(
            ["gh", "api", endpoint + "?per_page=100", "--paginate", "--slurp"],
            env=merge_quorum_io._read_env(),
            timeout=60,
        )
        if result.returncode:
            raise RuntimeError("could not read existing comments")
        pages = json.loads(result.stdout)
        comments = [comment for page in pages for comment in page]
        existing = next(
            (
                c
                for c in comments
                if str(c.get("body") or "").split("\n", 1)[0].rstrip("\r") == marker
            ),
            None,
        )
        if existing is not None:
            endpoint = f"repos/{repo}/issues/comments/{int(existing['id'])}"
        result = merge_quorum_io.run(
            ["gh", "api", "--method", "PATCH" if existing else "POST", endpoint, "--input", "-"],
            env=env,
            timeout=60,
            input_text=json.dumps({"body": body}),
        )
        if result.returncode:
            raise RuntimeError("could not deliver advisory summary")
        url = json.loads(result.stdout)["html_url"]
        return AdvisoryPostResult(True, url, None, existing is not None)
    except (
        OSError,
        subprocess.SubprocessError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        # Do not copy subprocess stderr (which may contain credentials) into JSON.
        return AdvisoryPostResult(
            False, None, f"advisory delivery failed ({type(exc).__name__})", False
        )
