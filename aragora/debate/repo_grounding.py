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
    r"(?i)\b(add|create|implement|update|refactor|remove|wire|integrate|validate|test|harden|instrument|enforce|ship)\b"
)
_PLACEHOLDER_PATTERNS: dict[str, re.Pattern[str]] = {
    "new_marker": re.compile(r"\[new\]", re.IGNORECASE),
    "inferred_marker": re.compile(r"\[inferred\]", re.IGNORECASE),
    "tbd": re.compile(r"\btbd\b", re.IGNORECASE),
    "todo": re.compile(r"\btodo\b", re.IGNORECASE),
    "placeholder": re.compile(r"\bplaceholder\b", re.IGNORECASE),
    "fill_me": re.compile(r"<\s*fill[^>]*>", re.IGNORECASE),
    "tk": re.compile(r"\btk\b", re.IGNORECASE),
    "as_needed": re.compile(r"\bas needed\b", re.IGNORECASE),
    "to_be_determined": re.compile(r"\bto be determined\b", re.IGNORECASE),
    "future_enhancement": re.compile(r"\bfuture enhancement\b", re.IGNORECASE),
    "as_appropriate": re.compile(r"\bas appropriate\b", re.IGNORECASE),
}


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
    if len(line.split()) >= 6:
        score += 0.1
    return min(1.0, score)


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

    ranked_text = _find_section_content(sections, _normalize_heading("Ranked High-Level Tasks"))
    subtasks_text = _find_section_content(sections, _normalize_heading("Suggested Subtasks"))
    # Score best of top 5 lines per section, take max across sections.
    # LLMs often write a generic intro on the first line and put actionable
    # content on subsequent lines, so first-only scoring is too pessimistic.
    section_best_scores: list[float] = []
    for section_text in [ranked_text, subtasks_text]:
        if not section_text:
            continue
        lines = [l.strip() for l in section_text.split("\n") if l.strip()]
        per_line = [_line_concreteness(l) for l in lines[:5]]
        if per_line:
            section_best_scores.append(max(per_line))
    if section_best_scores:
        first_batch_concreteness = round(max(section_best_scores), 4)
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
