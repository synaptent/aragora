"""Comment verdict parsing helpers for review-queue evidence gates."""

from __future__ import annotations

import re

# Explicit "no Pn finding" heads. A `[P0]`/`[P1]`/`[P2]` line is blocking UNLESS the text
# before its first colon is EXACTLY one of these — models emit `"[P1] None:"`,
# `"[P1] N/A"`, `"[P1] no issues: ..."` to declare the absence of a finding. Matched
# exactly (not as a prefix) so a real finding that merely starts with "none"/"no"
# (e.g. "[P1] None of the inputs are validated") still blocks.
_NO_FINDING_HEADS = frozenset(
    {
        "none",
        "none found",
        "none identified",
        "none noted",
        "none here",
        "n/a",
        "na",
        "nil",
        "0",
        "zero",
        "false",
        "[]",
        "not applicable",
        "no issues",
        "no issue",
        "no findings",
        "no finding",
        "no blockers",
        "no blocker",
        "no blocking",
        "no blocking findings",
        "no concerns",
        "no concern",
        "no critical issues",
        "no critical issue",
        "no critical findings",
    }
)

# Prefixes a `Verdict:/Decision:/Recommendation:` value may start with to count as a
# *negative* verdict line. Shared by ``has_blocking_or_negative_verdict``.
_NEGATIVE_VERDICT_PREFIXES = (
    "fail",
    "failed",
    "failing",
    "fails",
    "failure",
    "block",
    "blocked",
    "blocking",
    "request changes",
    "request_changes",
    "changes requested",
    "reject",
    "rejected",
    "not ready",
    "needs repair",
)

# Prefixes a populated Blocker-label value may start with that mean "no blocker".
# NOTE: a bare ``"no"`` is intentionally absent. ``"no"`` alone matched real
# security findings such as "no authentication on admin endpoint" / "no validation"
# / "no rate limiting" and silently demoted them to advisory — a merge-gate bypass.
# A leading ``"no"`` only counts as non-blocking when it is immediately followed by
# a no-finding NOUN (issue(s)/finding(s)/blocker(s)/concern(s)/problem(s)/change(s)),
# handled by :data:`_NO_FINDING_NO_PHRASE`.
_NON_BLOCKING_PREFIXES = (
    "none",
    "none found",
    "not found",
    "0",
    "zero",
    "false",
    "n/a",
    "not applicable",
    "[]",
)

# A populated Blocker-label value that is a no-finding declaration: "no issues",
# "no blockers", "no concerns", optionally hedged with a closed set of adjectives
# ("no MAJOR concerns", "no SIGNIFICANT issues", "no REMAINING blockers"). The
# adjective allowlist is bounded so the match stays fail-CLOSED for real findings:
# "no authentication", "no validation", "no SQLi" do NOT match (their head word is
# a real subject, not a no-finding noun, and is not an allowlisted hedge), so they
# still block. The standalone "blocking" alternative is intentionally absent — it
# made "no blocking on the auth path but SQLi" match as non-blocking, re-opening the
# exact bypass class this guard exists to close. The legacy "no blocking findings"
# form is still covered by the optional ``blocking\s+`` prefix on ``findings?``.
# NOTE (bounded heuristic): a trailing "… but <real finding>" after a matched
# no-finding phrase is not parsed out (prefix match), so "no major concerns but X"
# reads as non-blocking; this is a pre-existing limit of label-value prefix matching
# (the prior bare-"no" was strictly more permissive) and is low-realism in a Blocker
# label. Substantive blockers belong in the label value itself, where they block.
_NO_FINDING_HEDGE = (
    r"(?:major|minor|significant|serious|critical|real|actual|further|other|"
    r"remaining|additional|outstanding|notable|material|known|new|obvious)"
)
_NO_FINDING_NO_PHRASE = re.compile(
    r"no\s+"
    rf"(?:{_NO_FINDING_HEDGE}\s+){{0,2}}"
    r"(?:blocking\s+)?"
    r"(?:issues?|findings?|blockers?|concerns?|problems?|changes?)(?!\w)",
    re.I,
)

# What may follow a matched no-finding phrase for the value to still read as a PURE
# no-finding declaration: only benign closers ("found"/"identified"/"noted"/…) and
# punctuation/whitespace. Anything else (notably a contrastive "… but <real
# finding>") means the value carries a substantive blocker and must NOT be demoted.
_NO_FINDING_TAIL = re.compile(
    r"[\s.,;:!?)\]—–-]*"
    r"(?:found|identified|noted|detected|seen|present|reported|observed|raised|flagged|"
    r"needed|required|necessary|requested|warranted|remaining|here|at all|whatsoever)?"
    r"[\s.,;:!?)\]—–-]*",
    re.I,
)

_BLOCKER_LABELS = frozenset({"blocking finding", "blocking findings", "blocker", "blockers"})


def _starts_with_phrase(
    value: str, phrases: tuple[str, ...], *, match_no_finding: bool = False
) -> bool:
    # ``_NO_FINDING_NO_PHRASE`` ("no issues" / "no blockers" / …) means "absence of
    # a blocker" ONLY in the Blocker-label non-blocking check (``match_no_finding=True``).
    # It MUST NOT short-circuit the negative-verdict check: a *positive* verdict such
    # as "Verdict: no concerns" / "Recommendation: no changes needed" / "Decision: no
    # blockers" would otherwise be promoted to a blocking dissent — a regression in the
    # default flag-OFF merge-gate path. So the no-finding match is opt-in per caller.
    if match_no_finding:
        # Fail-CLOSED for EVERY no-finding token (the no-<noun> phrase AND each legacy
        # ``_NON_BLOCKING_PREFIXES`` entry like "none"/"n/a"/"zero"): the token must be
        # essentially the WHOLE value. Only benign trailing words ("found"/"identified"/
        # …) and punctuation may follow. A contrastive continuation leaves substantive
        # content in the tail ("none but SQLi on L40", "n/a - auth bypass remains", "no
        # major concerns BUT X"), so it does NOT read as no-finding and the Blocker
        # label still blocks — closing the prefix-bypass class (claude/grok/openai #8574).
        m = _NO_FINDING_NO_PHRASE.match(value)
        if m and _NO_FINDING_TAIL.fullmatch(value[m.end() :]):
            return True
        for phrase in phrases:
            pm = re.match(rf"{re.escape(phrase)}(?!\w)", value)
            if pm and _NO_FINDING_TAIL.fullmatch(value[pm.end() :]):
                return True
        return False
    return any(re.match(rf"{re.escape(phrase)}(?!\w)", value) for phrase in phrases)


# The DEFAULT (flag-OFF) blocking scanner treats `[P0]`/`[P1]`/`[P2]` marker lines as
# blocking findings — #8555 added `[P2]` to the default merge gate. ``has_blocking_or_
# negative_verdict`` (the flag-OFF path) uses these so flag-OFF stays byte-identical to
# main.
_DEFAULT_BLOCKING_MARKER = re.compile(r"^(?:\*\*)?\[(?:p0|p1|p2)\](?:\*\*)?(?:\s|$|[:.;—–-])", re.I)
_DEFAULT_BLOCKING_MARKER_STRIP = re.compile(r"^(?:\*\*)?\[(?:p0|p1|p2)\](?:\*\*)?\s*", re.I)

# The SEVERITY-GATE marker is deliberately `[P0]`/`[P1]` ONLY. ``_PRIORITY_MARKER``
# detects a marker line (sev captured); ``_PRIORITY_MARKER_STRIP`` removes the prefix to
# expose the finding head. Shared by ``_priority_finding_severity`` /
# ``highest_blocking_severity`` / ``has_blocking_finding_or_label`` — the flag-ON path.
# It intentionally diverges from ``_DEFAULT_BLOCKING_MARKER``: with
# ARAGORA_ENABLE_SEVERITY_GATED_DISSENT=1 a `[P2]`-only dissent is NOT a blocking
# severity, so it becomes advisory (that is the whole point of the flag). `[P2]` blocks
# by default and is advisory under the flag — these two marker sets encode exactly that.
_PRIORITY_MARKER = re.compile(r"^(?:\*\*)?\[(?P<sev>p0|p1)\](?:\*\*)?(?:\s|$|[:.;—–-])", re.I)
_PRIORITY_MARKER_STRIP = re.compile(r"^(?:\*\*)?\[(?:p0|p1)\](?:\*\*)?\s*", re.I)

# Any-severity variants, used ONLY by the diagnostic :func:`extract_finding_lines`.
# Kept separate from the gate markers above so widening the diagnostic view can
# never widen what counts as blocking.
_ANY_PRIORITY_MARKER = re.compile(r"^(?:\*\*)?\[(?P<sev>p\d)\](?:\*\*)?(?:\s|$|[:.;—–-])", re.I)
_ANY_PRIORITY_MARKER_STRIP = re.compile(r"^(?:\*\*)?\[p\d\](?:\*\*)?\s*", re.I)


def _strip_decoration(text: str) -> str:
    return re.sub(r"^(?:[#>\-*+\s]+|\d+[.)]\s+)+", "", text.strip())


def _normalize_value(text: str) -> str:
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"[-_]+", " ", text)
    return re.sub(r"\s+", " ", text.strip().strip("*_").strip().lower())


_FENCE_LINE = re.compile(r"^\s*(?:`{3,}|~{3,})(?:[\w.+-]+)?\s*$")
_INDENTED_CODE_LINE = re.compile(r"^(?: {4,}|\t)")


def _strip_blockquote_prefix(line: str) -> str:
    return re.sub(r"^\s*>\s?", "", line).strip()


def _blockquote_group_is_example(lines: list[str]) -> bool:
    combined = " ".join(_normalize_value(line) for line in lines)
    return bool(
        re.search(r"\b(?:quoted|example|sample|demonstrat(?:e|ion)|not a live finding)\b", combined)
    )


def _flush_blockquote_group(lines: list[str], blockquote_group: list[str]) -> None:
    if not blockquote_group:
        return
    if not _blockquote_group_is_example(blockquote_group):
        lines.extend(blockquote_group)
    blockquote_group.clear()


def _semantic_review_lines(body: str) -> list[str]:
    """Lines that should participate in verdict/finding classification.

    Reviewers often quote the gate syntax itself while reviewing parser changes,
    e.g. fenced examples of ``Verdict: CHANGES-REQUESTED`` or blockquoted
    ``[P2]`` snippets. Those are not the reviewer's live verdict/finding lines
    and must not become blocking dissent. Normal bullet/list findings are kept.
    """
    lines: list[str] = []
    in_fence = False
    fence_buffer: list[str] = []
    blockquote_group: list[str] = []
    for raw_line in str(body or "").splitlines():
        stripped = raw_line.strip()
        if _FENCE_LINE.match(stripped):
            _flush_blockquote_group(lines, blockquote_group)
            in_fence = not in_fence
            if not in_fence:
                fence_buffer.clear()
            continue
        if in_fence:
            fence_buffer.append(stripped)
            continue
        if stripped.startswith(">"):
            blockquote_group.append(_strip_blockquote_prefix(raw_line))
            continue
        _flush_blockquote_group(lines, blockquote_group)
        if _INDENTED_CODE_LINE.match(raw_line):
            continue
        lines.append(stripped)
    _flush_blockquote_group(lines, blockquote_group)
    if in_fence:
        # Fail closed for malformed evidence: if a reviewer opens a fence and never closes it,
        # do not silently discard the rest of the comment.
        lines.extend(fence_buffer)
    return lines


def _priority_finding_severity(stripped: str) -> str | None:
    """Return ``"P0"``/``"P1"`` if ``stripped`` is a *real* `[P0]`/`[P1]` finding
    line (head-before-colon NOT in :data:`_NO_FINDING_HEADS`), else ``None``.

    Reuses the exact decoration/normalization/head-extraction logic that
    :func:`has_blocking_or_negative_verdict` applies, so the severity scanner and
    the blocking scanner never disagree on what a real finding line is.
    """
    priority_marker_line = _strip_decoration(stripped)
    marker = _PRIORITY_MARKER.match(priority_marker_line)
    if not marker:
        return None
    rest = _PRIORITY_MARKER_STRIP.sub("", priority_marker_line)
    head = _normalize_value(rest).split(":", 1)[0].strip(" .;—–-")
    if head in _NO_FINDING_HEADS:
        # explicit "[Pn] None:/N/A/no issues" non-finding
        return None
    return marker.group("sev").upper()


def _populated_blocker_label(stripped: str, follow_lines: list[str]) -> bool:
    """Whether ``stripped`` is a populated ``Blocking finding(s):/Blocker(s):`` label.

    ``follow_lines`` are the remaining stripped (non-empty filtered happens here)
    lines after this one, used to resolve a label whose value is on the next line.
    Mirrors the Blocker-label branch of :func:`has_blocking_or_negative_verdict`.
    """
    line = _strip_decoration(stripped).replace("**", "").replace("__", "")
    match = re.match(r"^(?P<label>[^:—–-]+?)\s*(?::|—|–|-)\s*(?P<value>.*)$", line)
    if not match:
        return False
    normalized_label = re.sub(r"\s+", " ", match.group("label").strip().lower())
    normalized_label = normalized_label.strip("*_ ")
    if normalized_label not in _BLOCKER_LABELS:
        return False
    normalized_value = _normalize_value(match.group("value"))
    candidate = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", normalized_value)
    if candidate in {"-", "*", "[]", "[ ]", "—", "–"}:
        return False
    if not candidate:
        follow = next((entry for entry in follow_lines if entry), "")
        is_list_item = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", follow))
        if not is_list_item and (follow.startswith("#") or re.match(r"^[^:]+?:\s+\S", follow)):
            return False
        candidate = _normalize_value(_strip_decoration(follow))
    return bool(candidate) and not _starts_with_phrase(
        candidate, _NON_BLOCKING_PREFIXES, match_no_finding=True
    )


def has_blocking_or_negative_verdict(body: str) -> bool:
    """Return True for explicit evidence comments that report blockers."""
    lines = _semantic_review_lines(body)
    for idx, stripped in enumerate(lines):
        if not stripped:
            continue
        priority_marker_line = _strip_decoration(stripped)
        if _DEFAULT_BLOCKING_MARKER.match(priority_marker_line):
            rest = _DEFAULT_BLOCKING_MARKER_STRIP.sub("", priority_marker_line)
            head = _normalize_value(rest).split(":", 1)[0].strip(" .;—–-")
            if head not in _NO_FINDING_HEADS:
                return True
            # explicit "[Pn] None:/N/A/no issues" non-finding -> keep scanning
            continue
        line = _strip_decoration(stripped).replace("**", "").replace("__", "")
        match = re.match(r"^(?P<label>[^:—–-]+?)\s*(?::|—|–|-)\s*(?P<value>.*)$", line)
        if not match:
            continue
        normalized_label = re.sub(r"\s+", " ", match.group("label").strip().lower())
        normalized_label = normalized_label.strip("*_ ")
        normalized_value = _normalize_value(match.group("value"))
        if normalized_label in {"verdict", "decision", "recommendation"}:
            if _starts_with_phrase(normalized_value, _NEGATIVE_VERDICT_PREFIXES):
                return True
            continue
        if normalized_label not in _BLOCKER_LABELS:
            continue
        candidate = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", normalized_value)
        if candidate in {"-", "*", "[]", "[ ]", "—", "–"}:
            continue
        if not candidate:
            follow = next((entry for entry in lines[idx + 1 :] if entry), "")
            is_list_item = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", follow))
            if not is_list_item and (follow.startswith("#") or re.match(r"^[^:]+?:\s+\S", follow)):
                continue
            candidate = _normalize_value(_strip_decoration(follow))
        if candidate and not _starts_with_phrase(
            candidate, _NON_BLOCKING_PREFIXES, match_no_finding=True
        ):
            return True
    return False


def highest_blocking_severity(body: str) -> str | None:
    """Return ``"P0"``/``"P1"`` if ``body`` carries a real (non-:data:`_NO_FINDING_HEADS`)
    `[P0]`/`[P1]` finding line, else ``None``.

    Reuses the EXACT `[P0]`/`[P1]` detection that drives
    :func:`has_blocking_or_negative_verdict`. ``"P0"`` is reported in preference to
    ``"P1"`` when both are present.
    """
    best: str | None = None
    for stripped in _semantic_review_lines(body):
        if not stripped:
            continue
        severity = _priority_finding_severity(stripped)
        if severity == "P0":
            return "P0"
        if severity == "P1":
            best = "P1"
    return best


def extract_finding_lines(body: str) -> list[str]:
    """Return every real ``[Pn]`` finding line in ``body``, at any severity.

    Purely **diagnostic**: this reports what a reviewer wrote so a dissent can be
    read without re-running the reviewer. It gates nothing — blocking severity
    stays :func:`highest_blocking_severity` / :func:`has_blocking_finding_or_label`,
    which are deliberately ``[P0]``/``[P1]`` only.

    Severity is deliberately *not* filtered here: a ``[P2]``-only dissent is the
    common case a human needs to read (it blocks by default, and is advisory only
    under ``ARAGORA_ENABLE_SEVERITY_GATED_DISSENT``), so hiding it would leave the
    exact gap this exists to close.

    Reuses :func:`_semantic_review_lines` and the same decoration/no-finding-head
    handling as the gate, so a fenced or blockquoted ``[P2]`` example that the gate
    ignores is never reported here as a live finding.
    """
    findings: list[str] = []
    for stripped in _semantic_review_lines(body):
        if not stripped:
            continue
        line = _strip_decoration(stripped)
        marker = _ANY_PRIORITY_MARKER.match(line)
        if not marker:
            continue
        rest = _ANY_PRIORITY_MARKER_STRIP.sub("", line)
        head = _normalize_value(rest).split(":", 1)[0].strip(" .;—–-")
        if head in _NO_FINDING_HEADS:
            # "[P2] None" / "[P3] N/A" are explicit non-findings.
            continue
        # Re-emit as a normalised "[Pn] text" line. `_strip_decoration` removes the
        # leading "- **" of a bolded bullet but leaves the closing "**" stranded on
        # the marker, so echoing the raw line would print "[P2]** ...".
        severity = marker.group("sev").upper()
        detail = rest.lstrip(" :.;—–-").strip()
        findings.append(f"[{severity}] {detail}" if detail else f"[{severity}]")
    return findings


def has_blocking_finding_or_label(body: str) -> bool:
    """Return True when ``body`` carries a real `[P0]`/`[P1]` finding line OR a
    populated Blocker-label.

    This is everything :func:`has_blocking_or_negative_verdict` blocks on EXCEPT a
    bare negative ``Verdict:/Decision:/Recommendation:`` line that carries no real
    finding and no populated Blocker-label. It is the severity-gated trigger: a
    ``CHANGES-REQUESTED`` comment promotes a *blocking* dissent only when it is
    backed by a real `[P0]`/`[P1]` finding or a populated Blocker label.
    """
    lines = _semantic_review_lines(body)
    for idx, stripped in enumerate(lines):
        if not stripped:
            continue
        if _priority_finding_severity(stripped) is not None:
            return True
        if _populated_blocker_label(stripped, lines[idx + 1 :]):
            return True
    return False
