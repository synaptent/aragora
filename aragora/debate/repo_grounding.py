"""Deterministic repository-grounding and practicality heuristics for debate outputs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_PATH_RE = re.compile(r"((?:/?[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)")
_THRESHOLD_RE = re.compile(
    r"(?i)(<=|>=|<|>|=|==)\s*\d+(?:\.\d+)?\s*(?:%|ms|s|sec|seconds|m|min|minutes|h|hours|rps|qps|req/s)?"
)
_ACTION_VERB_RE = re.compile(
    r"(?i)\b(add|create|implement|update|refactor|remove|wire|integrate|validate|test|harden|instrument|enforce|ship"
    r"|build|deploy|configure|construct|establish|develop|provision|run|execute|design|migrate|setup|parse|route"
    r"|initialize|instantiate|enable|monitor|track|define|connect|aggregate|extract|detect|optimize|fix|resolve"
    r"|extend|introduce|scaffold|verify|ensure|check"
    r"|improve|enhance|strengthen|upgrade|increase|decrease|reduce|modularize|encapsulate|augment"
    r"|standardize|consolidate|unify|simplify|normalize|expand|scale|wrap|patch|align|refine"
    r"|decouple|deprecate|emit|inject|register|rewrite|split|merge|expose|publish|document"
    r"|measure|benchmark|profile|audit|scan|lint|format|generate|transform|convert|serialize"
    r"|throttle|debounce|cache|index|query|fetch|load|store|persist|flush|evict|invalidate"
    r"|assert|mock|stub|parametrize|isolate|snapshot|replay|record|capture|intercept"
    r"|rename|move|relocate|deduplicate|dedupe|prune|trim|compress|decompress|encrypt|decrypt)\b"
)
# Tiered placeholder/hedging patterns with severity weights.
# HIGH (0.30): hard placeholders that indicate missing content.
# MEDIUM (0.15): LLM hedging phrases that weaken actionability.
# LOW (0.05): weak commitment language (common but less harmful).
_HEDGING_TIERS: list[tuple[float, dict[str, re.Pattern[str]]]] = [
    # --- Tier HIGH (weight 0.30): hard placeholders ---
    (
        0.30,
        {
            "new_marker": re.compile(r"\[new\]", re.IGNORECASE),
            "inferred_marker": re.compile(r"\[inferred\]", re.IGNORECASE),
            "tbd": re.compile(r"\btbd\b", re.IGNORECASE),
            "todo": re.compile(r"\btodo\b", re.IGNORECASE),
            "placeholder": re.compile(r"\bplaceholder\b", re.IGNORECASE),
            "fill_me": re.compile(r"<\s*fill[^>]*>", re.IGNORECASE),
            "tk": re.compile(r"\btk\b", re.IGNORECASE),
            "ellipsis_trail": re.compile(r"\.\.\.\s*$"),
        },
    ),
    # --- Tier MEDIUM (weight 0.15): LLM hedging phrases ---
    (
        0.15,
        {
            "as_needed": re.compile(r"\bas needed\b", re.IGNORECASE),
            "to_be_determined": re.compile(r"\bto be determined\b", re.IGNORECASE),
            "as_appropriate": re.compile(r"\bas appropriate\b", re.IGNORECASE),
            "future_enhancement": re.compile(r"\bfuture enhancement\b", re.IGNORECASE),
            "consider_adding": re.compile(
                r"\bconsider (?:adding|implementing|using)\b", re.IGNORECASE
            ),
            "if_applicable": re.compile(r"\bif (?:applicable|necessary|desired)\b", re.IGNORECASE),
            "may_require": re.compile(r"\bmay (?:require|need|involve)\b", re.IGNORECASE),
            "could_potentially": re.compile(r"\bcould potentially\b", re.IGNORECASE),
            "depending_on": re.compile(
                r"\bdepending on (?:requirements|needs|context)\b", re.IGNORECASE
            ),
            "optional_step": re.compile(r"\b(?:optional|optionally)\b", re.IGNORECASE),
        },
    ),
    # --- Tier LOW (weight 0.05): weak commitment ---
    (
        0.05,
        {
            "should_consider": re.compile(r"\bshould consider\b", re.IGNORECASE),
            "might_want": re.compile(r"\bmight want to\b", re.IGNORECASE),
            "various": re.compile(
                r"\bvarious (?:approaches|methods|options|strategies)\b", re.IGNORECASE
            ),
            "etc_trailing": re.compile(r"\betc\.?\s*$", re.IGNORECASE),
        },
    ),
]

# Flat lookup for backwards-compatible _collect_placeholder_hits().
_PLACEHOLDER_PATTERNS: dict[str, re.Pattern[str]] = {}
for _weight, _tier_patterns in _HEDGING_TIERS:
    _PLACEHOLDER_PATTERNS.update(_tier_patterns)


def _normalize_heading(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    # Strip leading numeric prefixes that LLMs often add (e.g. "3 owner module file paths"
    # from heading "## 3. Owner module / file paths").
    normalized = re.sub(r"^\d+\s+", "", normalized)
    return normalized


def _extract_sections(markdown: str) -> list[dict[str, Any]]:
    matches = list(_HEADER_RE.finditer(markdown))
    if not matches:
        return []

    sections: list[dict[str, Any]] = []
    for idx, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        sections.append(
            {
                "title": title,
                "normalized": _normalize_heading(title),
                "content": markdown[start:end].strip(),
            }
        )
    return sections


def _normalize_repo_path(candidate: str) -> str | None:
    value = candidate.strip().strip("`'\".,:;()[]{}")
    if not value:
        return None
    if "://" in value:
        return None
    while value.startswith("./"):
        value = value[2:]
    value = value.lstrip("/")
    if not value or "/" not in value:
        return None
    return value


def _resolve_path_against_repo(candidate: str, repo_root: Path) -> tuple[str, Path]:
    """Resolve extracted path against repo root, handling stripped absolute paths."""
    raw = candidate.strip()
    root = repo_root.resolve()
    root_prefix = str(root).lstrip("/")

    # Absolute paths are normalized by _normalize_repo_path() via lstrip("/"),
    # so remap `<root>/...` back to a repo-relative path when possible.
    if root_prefix and (raw == root_prefix or raw.startswith(f"{root_prefix}/")):
        rel = "." if raw == root_prefix else raw[len(root_prefix) + 1 :]
        return rel, root / rel

    abs_candidate = Path("/" + raw)
    try:
        rel = str(abs_candidate.relative_to(root))
        return rel, abs_candidate
    except ValueError:
        pass

    return raw, root / raw


def extract_repo_paths(text: str) -> list[str]:
    """Extract normalized candidate repository paths from text."""
    if not text:
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for raw in _PATH_RE.findall(text):
        normalized = _normalize_repo_path(raw)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(normalized)
    return paths


def _find_section_content(sections: list[dict[str, Any]], normalized_title: str) -> str:
    for section in sections:
        if section["normalized"] == normalized_title:
            return str(section["content"] or "")
    return ""


def _collect_placeholder_hits(text: str) -> list[str]:
    hits: list[str] = []
    for label, pattern in _PLACEHOLDER_PATTERNS.items():
        if pattern.search(text):
            hits.append(label)
    return hits


def _estimate_placeholder_rate(text: str, hits: list[str]) -> float:
    if not text.strip():
        return 0.0
    if not hits:
        return 0.0
    total_tokens = max(1, len(re.findall(r"\w+", text)))
    # Scale count against token volume and clamp into [0, 1].
    density = min(1.0, (len(hits) * 25.0) / float(total_tokens))
    return round(density, 4)


def _first_nonempty_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip(" \t-")
        if line:
            return line
    return ""


_FILE_EXT_RE = re.compile(r"\b\w+\.(py|ts|tsx|js|jsx|yaml|yml|toml|json|md)\b")
_SUBHEADER_RE = re.compile(r"^\s*\*\*[^*]+\*\*:?\s*$")

# Qualitative gate-criteria patterns: express pass/fail conditions without
# numeric operators.  Lines like "all tests must pass", "no regressions",
# "100% of smoke tests must pass" are legitimate gate criteria that deserve
# concreteness credit even though they lack file paths or numeric thresholds.
_QUALITATIVE_GATE_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\bmust\s+(?:pass|succeed|complete|not\s+(?:fail|decrease|increase|exceed|regress|break))\b"
    r"|\bshould\s+not\s+(?:fail|decrease|increase|exceed|regress|break)\b"
    r"|\b(?:all|every)\s+(?:existing\s+)?tests?\s+(?:must\s+)?pass\b"
    r"|\bno\s+(?:new\s+)?(?:regression|failure|warning|error|lint)s?\b"
    r"|\b(?:100%|full)\s+(?:success|pass|compliance)\b"
    r"|\bzero\s+(?:blocker|error|failure|timeout|crash)s?\b"
    r"|\b(?:0|no)\s+(?:blocker|error|failure|timeout|crash|regression|duplicate|empty)\w*\b"
    r"|\bci\s+(?:must\s+)?(?:be\s+)?green\b"
    r"|\bbranch\s+(?:must\s+)?(?:be\s+)?(?:green|clean|passing)\b"
    r"|\bgit\s+revert\b"
    r"|\bfeature\s+flag\b"
    r"|\b(?:revert|rollback|roll\s+back)\s+(?:the\s+)?(?:commit|merge|deploy|change)\b"
    r")"
)


def _is_subheader_line(line: str) -> bool:
    """Return True for bold-only sub-header lines like '**Task 1 Subtasks:**'."""
    return bool(_SUBHEADER_RE.match(line))


def _line_hedging_penalty(line: str) -> float:
    """Compute a tiered hedging penalty for a single line, capped at 0.5."""
    penalty = 0.0
    for weight, patterns in _HEDGING_TIERS:
        for _label, pattern in patterns.items():
            if pattern.search(line):
                penalty += weight
    return min(0.5, penalty)


def _line_concreteness(line: str) -> float:
    if not line:
        return 0.0
    score = 0.0
    if _ACTION_VERB_RE.search(line):
        score += 0.35
    if _PATH_RE.search(line):
        score += 0.35
    elif _FILE_EXT_RE.search(line):
        # Bare filenames without directory separators (e.g., "output_quality.py")
        score += 0.2
    if _THRESHOLD_RE.search(line):
        score += 0.2
    elif _QUALITATIVE_GATE_RE.search(line):
        # Qualitative gate criteria (e.g. "all tests must pass", "no regressions",
        # "CI must be green") are practical content that deserves credit even
        # without numeric operators.  Weighted lower than numeric thresholds.
        score += 0.15
    if len(line.split()) >= 6:
        score += 0.1
    raw = min(1.0, score)
    # Apply per-line hedging penalty so lines with vague language score lower.
    penalty = _line_hedging_penalty(line)
    return max(0.0, raw - penalty)


@dataclass
class RepoGroundingReport:
    """Deterministic grounding metrics for practical executability."""

    mentioned_paths: list[str] = field(default_factory=list)
    existing_paths: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)
    new_paths: list[str] = field(default_factory=list)
    path_existence_rate: float = 0.0
    placeholder_hits: list[str] = field(default_factory=list)
    placeholder_rate: float = 0.0
    first_batch_concreteness: float = 0.0
    practicality_score_10: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mentioned_paths": list(self.mentioned_paths),
            "existing_paths": list(self.existing_paths),
            "missing_paths": list(self.missing_paths),
            "new_paths": list(self.new_paths),
            "path_existence_rate": self.path_existence_rate,
            "placeholder_hits": list(self.placeholder_hits),
            "placeholder_rate": self.placeholder_rate,
            "first_batch_concreteness": self.first_batch_concreteness,
            "practicality_score_10": self.practicality_score_10,
        }


def _fuzzy_path_exists(root: Path, rel_path: str) -> bool:
    """Check if a close match for rel_path exists in the repository.

    LLM agents often hallucinate slightly wrong filenames (e.g.
    ``aragora/debate/quality.py`` instead of ``output_quality.py``).
    This checks whether the parent directory exists and contains a file
    whose name contains the stem of the referenced path.
    """
    full = root / rel_path
    parent = full.parent
    stem = full.stem  # e.g. "quality" from "quality.py"
    suffix = full.suffix

    if not parent.is_dir() or not stem or not suffix:
        return False

    try:
        for child in parent.iterdir():
            if child.suffix == suffix and stem in child.stem:
                return True
    except OSError:
        pass
    return False


def assess_repo_grounding(
    answer: str,
    *,
    repo_root: str | None = None,
    require_owner_paths: bool = True,
) -> RepoGroundingReport:
    """Evaluate whether output is grounded in real repo paths and concrete first steps."""
    text = answer or ""
    sections = _extract_sections(text)

    owner_text = _find_section_content(sections, _normalize_heading("Owner module / file paths"))
    path_source = owner_text or text
    extracted_paths = extract_repo_paths(path_source)

    root = Path(repo_root or os.getcwd())
    mentioned_paths: list[str] = []
    _seen_mentioned: set[str] = set()
    existing_paths: list[str] = []
    missing_paths: list[str] = []
    new_paths: list[str] = []
    _NEW_FILE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".md"}
    for extracted in extracted_paths:
        rel_path, full = _resolve_path_against_repo(extracted, root)
        if rel_path in _seen_mentioned:
            continue
        _seen_mentioned.add(rel_path)
        mentioned_paths.append(rel_path)

        if full.exists():
            existing_paths.append(rel_path)
        elif _fuzzy_path_exists(root, rel_path):
            # The exact path doesn't exist but a close match does (e.g.
            # "aragora/debate/quality.py" matches "aragora/debate/output_quality.py").
            existing_paths.append(rel_path)
        elif full.suffix in _NEW_FILE_EXTENSIONS:
            # Path has a valid file extension -- likely a new file proposal.
            # Check if at least the grandparent directory exists so the
            # proposal is structurally plausible (e.g. aragora/new_mod/foo.py
            # is plausible when aragora/ exists).
            parent = full.parent
            if parent.exists() or (parent.parent.exists() if parent != root else False):
                new_paths.append(rel_path)
            else:
                missing_paths.append(rel_path)
        else:
            missing_paths.append(rel_path)

    if mentioned_paths:
        # New file proposals count as half-grounded (parent/grandparent dir exists)
        grounded_count = len(existing_paths) + 0.5 * len(new_paths)
        path_existence_rate = round(grounded_count / len(mentioned_paths), 4)
    else:
        path_existence_rate = 1.0 if not require_owner_paths else 0.0

    placeholder_hits = _collect_placeholder_hits(text)
    placeholder_rate = _estimate_placeholder_rate(text, placeholder_hits)

    _CONCRETENESS_SECTIONS = [
        "Ranked High-Level Tasks",
        "Suggested Subtasks",
        "Test Plan",
        "Rollback Plan",
        "Gate Criteria",
    ]
    # Score top lines per section and average their concreteness.
    # Using mean instead of max gives a better signal: one good line among
    # several vague lines should not produce a high score.
    # Scanning 5 sections (including Test Plan, Rollback Plan, Gate Criteria)
    # captures lines with thresholds and test filenames that reliably score high.
    section_avg_scores: list[float] = []
    for heading in _CONCRETENESS_SECTIONS:
        section_text = _find_section_content(sections, _normalize_heading(heading))
        if not section_text:
            continue
        lines = [
            l.strip()
            for l in section_text.split("\n")
            if l.strip() and not _is_subheader_line(l.strip())
        ]
        per_line = [_line_concreteness(l) for l in lines[:8]]
        if per_line:
            section_avg_scores.append(sum(per_line) / len(per_line))
    if section_avg_scores:
        first_batch_concreteness = round(max(section_avg_scores), 4)
    else:
        first_batch_concreteness = 0.0

    no_placeholder_factor = max(0.0, 1.0 - placeholder_rate)
    # Rebalanced weights: path existence further de-emphasized because LLM
    # agents don't have filesystem access.  After deterministic path repair,
    # existence is a supplementary signal.  Content concreteness (action verbs,
    # specificity, measurability) is the primary indicator of execution readiness.
    practicality_score = (
        0.15 * path_existence_rate + 0.55 * first_batch_concreteness + 0.30 * no_placeholder_factor
    ) * 10.0

    return RepoGroundingReport(
        mentioned_paths=mentioned_paths,
        existing_paths=existing_paths,
        missing_paths=missing_paths,
        new_paths=new_paths,
        path_existence_rate=path_existence_rate,
        placeholder_hits=placeholder_hits,
        placeholder_rate=placeholder_rate,
        first_batch_concreteness=first_batch_concreteness,
        practicality_score_10=round(min(10.0, max(0.0, practicality_score)), 2),
    )


def format_path_verification_summary(report: RepoGroundingReport) -> str:
    """Format a compact CLI summary for path grounding verification."""
    total = len(report.mentioned_paths)
    existing = len(report.existing_paths)
    new_paths = len(report.new_paths)
    missing = len(report.missing_paths)
    rate_pct = int(round(report.path_existence_rate * 100))

    lines = [
        f"[path-check] grounded={rate_pct}% existing={existing} new={new_paths} missing={missing} total={total}"
    ]

    if report.missing_paths:
        preview = ", ".join(report.missing_paths[:5])
        if len(report.missing_paths) > 5:
            preview += ", ..."
        lines.append(f"[path-check] missing paths: {preview}")

    return "\n".join(lines)
