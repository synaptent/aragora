#!/usr/bin/env python3
"""Lightweight consistency lint for Aragora docs and issue tracking."""

# fmt: off
from __future__ import annotations
import argparse
import fnmatch
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote
GITHUB_REPO = "synaptent/aragora"
# Files allowed to reference archived snapshots as redirects or archive policy indexes.
ARCHIVE_REFERENCE_WHITELIST = {
    "docs/ARAGORA_BUSINESS_SUMMARY.md": "redirect stub to the archived business snapshot",
    "docs/OMNIVOROUS_ROADMAP.md": "redirect stub to the archived roadmap snapshot",
    "docs/STRATEGY_INDEX.md": "canonical map from retired docs to live replacements",
    "docs/archive/README.md": "archive policy and inventory",
    "docs/ARCHITECTURE_REVIEW_RESPONSE.md": "redirect stub to the archived architecture-review-response snapshot",
    "docs/status/COMMERCIAL_POSITIONING.md": "redirect stub to the archived commercial-positioning snapshot",
    "docs/compliance/EU_AI_ACT_WALKTHROUGH_2026-06.md": "redirect stub to the archived EU AI Act walkthrough snapshot",
    "docs/reference/ROOT_ALLOWLIST.md": "root-clutter inventory documents archived former-root files",
}
# Files/patterns where metric numbers are intentionally historical, local-suite scoped,
# generated from live measurements, or not repo-wide canonical marketing/product claims.
METRIC_DRIFT_WHITELIST = {
    "docs/archive/**": "historical snapshots may preserve old counts", "docs/status/**": "status docs may cite live measurements and historical scorecards", "docs/deprecated/**": "deprecated docs preserve old implementation state",
    "docs/deployment/**": "release notes and deployment checklists preserve release-era counts", "docs/testing/**": "testing docs cite local suite sizes and audit buckets", "docs/plans/**": "planning docs cite local acceptance estimates and dogfood outputs",
    "docs/superpowers/**": "research plans cite local test expectations", "docs/internal/**": "internal audits cite subsystem-local counts", "docs/architecture/**": "architecture docs include subsystem-local diagrams and old reviews",
    "docs/STATUS.md": "top-level status log preserves historical count snapshots", "docs/COORDINATION.md": "coordination log preserves closed issue-era measurements", "docs/assessments/**": "dated assessments preserve point-in-time metric claims",
    "docs/debate/**": "debate transcripts preserve prompt-time metric claims", "docs/research/**": "research notes cite exploratory subsystem-local counts", "docs/observability/**": "observability docs cite live suite measurements",
    "docs/workflow/**": "workflow docs cite older local validation counts", "docs/governance/subsystem-ledger.md": "subsystem ledger is explicitly module-local", "docs/PACKAGING.md": "packaging guide cites package-local tests and adapter surfaces",
    "docs/PYTHON_SDK_CONSOLIDATION.md": "SDK consolidation guide cites namespace-local modules", "docs/STRANDED_FEATURES_AUDIT.md": "audit entries cite feature-local test counts",
    "docs/strategy/POSITIONING_AND_MESSAGING.md": "positioning guide quotes '43 agent types' as an anti-pattern to avoid, not a factual claim",
    "docs/outreach/DESIGN_PARTNER_QUALIFICATION.md": "qualifies '43 agent types' as anti-pattern messaging, not a factual claim",
    "docs/STRATEGIC_ANALYSIS.md": "point-in-time (March 2026) documentation-drift snapshot; historical counts preserved for the audit narrative",
}
LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
HTML_ID_RE = re.compile(r"""<a\s+[^>]*id=["']([^"']+)["']""", re.IGNORECASE)
METRIC_RE = re.compile(r"\b(\d+(?:,\d+)*)(\+)?\s+(tests|adapters|agent types|API operations|modules)\b", re.IGNORECASE)
CODE_RE = re.compile(r"\b([A-Z]{2,4})-(\d{2})(?:\.\.(\d{2}))?\b")
TRACKED_ISSUE_CODE_PREFIXES = ("DIC-", "TW-")
DIC_TITLE_RE = re.compile(r"^\[(DIC-\d{2})\]")
DESIGN_DOC_RE = re.compile(r"docs/(?:plans|strategy|status)/[A-Za-z0-9_.\-/]+\.md")
@dataclass(frozen=True)
class Finding:
    location: str
    message: str
@dataclass(frozen=True)
class CheckResult:
    name: str
    label: str
    noun: str
    findings: list[Finding]
    skipped: bool = False
    skip_reason: str = ""
@dataclass(frozen=True)
class StrategyTarget:
    path: str
    part: str | None = None
def rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
def markdown_files(root: Path) -> list[Path]:
    # NOTE: `docs/**/*.md` in git pathspec misses top-level `docs/*.md`
    # (e.g. `docs/COMMERCIAL_OVERVIEW.md`, `docs/WHY_ARAGORA.md`), so we scan
    # `docs/*.md` (which git expands recursively across the tree) and also
    # include top-level positioning docs like `CLAUDE.md` and `AGENTS.md`.
    result = subprocess.run(
        [
            "git", "-C", str(root), "ls-files", "--",
            "README.md", "CLAUDE.md", "AGENTS.md", "docs/*.md",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        seen: set[Path] = set()
        files: list[Path] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            path = root / stripped
            if path in seen:
                continue
            seen.add(path)
            files.append(path)
        return files

    files: list[Path] = []
    for top in ("README.md", "CLAUDE.md", "AGENTS.md"):
        candidate = root / top
        if candidate.exists():
            files.append(candidate)
    docs = root / "docs"
    if docs.exists():
        files.extend(sorted(docs.rglob("*.md")))
    return files
def strip_link_title(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split()[0] if target.split() else target
def is_url(target: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE)) or target.startswith("//")
def split_target(target: str) -> tuple[str, str]:
    no_title = strip_link_title(target)
    path_part, sep, anchor = no_title.partition("#")
    path_part = unquote(path_part.split("?", 1)[0])
    return path_part, unquote(anchor) if sep else ""
def resolve_link(root: Path, source: Path, path_part: str) -> Path:
    if not path_part:
        return source
    if path_part.startswith("/"):
        return root / path_part.lstrip("/")
    return (source.parent / path_part).resolve()
def normalize_anchor(value: str) -> str:
    value = unquote(value).lower()
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[[^\]]+\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())
def github_slug(value: str) -> str:
    normalized = normalize_anchor(value)
    return normalized.replace(" ", "-")
def headings_for(path: Path) -> set[str]:
    anchors: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return anchors
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        for title in ([heading.group(1).strip()] if heading else []) + HTML_ID_RE.findall(line):
            anchors.add(normalize_anchor(title))
            anchors.add(github_slug(title))
            anchors.add(normalize_anchor(title).replace(" ", ""))
    return anchors
def anchor_exists(path: Path, anchor: str) -> bool:
    wanted = normalize_anchor(anchor)
    compact = wanted.replace(" ", "")
    for existing in headings_for(path):
        normalized = normalize_anchor(existing)
        if normalized == wanted or existing == github_slug(anchor):
            return True
        if wanted and normalized.startswith(f"{wanted} "):
            return True
        if compact and normalized.replace(" ", "").startswith(compact):
            return True
    return False
def extract_links(path: Path) -> list[tuple[int, str, str]]:
    links: list[tuple[int, str, str]] = []
    in_fence = False
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fence = line.lstrip().startswith("```")
        if fence:
            in_fence = not in_fence
        if fence or in_fence:
            continue
        searchable = INLINE_CODE_RE.sub("", line)
        for match in LINK_RE.finditer(searchable):
            target = match.group(1).strip()
            links.append((line_no, target, match.group(0)))
    return links
def parse_strategy_index(root: Path) -> dict[str, StrategyTarget]:
    index = root / "docs" / "STRATEGY_INDEX.md"
    if not index.exists():
        return {}
    mapping: dict[str, StrategyTarget] = {}
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`(?:\s+Part\s+(\d+))?\s*\|")
    for line in index.read_text(encoding="utf-8").splitlines():
        row = row_re.match(line)
        if not row:
            continue
        old_name, new_path, part = row.groups()
        if new_path.startswith("("):
            continue
        mapping[Path(old_name).name] = StrategyTarget(path=f"docs/{new_path}" if not new_path.startswith("docs/") else new_path, part=f"Part {part}" if part else None)
    return mapping
def replacement_for_broken_link(
    root: Path, source: Path, target: str, strategy_map: dict[str, StrategyTarget]
) -> str | None:
    path_part, _anchor = split_target(target)
    if not path_part:
        return None
    candidate = strategy_map.get(Path(path_part).name)
    if not candidate:
        return None
    target_path = root / candidate.path
    if not target_path.exists():
        return None
    rel_path = posixpath.relpath(target_path, source.parent)
    rel_path = "." if rel_path == "." else rel_path
    if candidate.part:
        rel_path = f"{rel_path}#{github_slug(candidate.part)}"
    return rel_path
def apply_link_fixes(root: Path, broken: list[Finding], strategy_map: dict[str, StrategyTarget]) -> int:
    replacements_by_file: dict[Path, list[tuple[str, str]]] = {}
    for finding in broken:
        source_text, _, link_text = finding.location.partition(":")
        source = root / source_text
        target_match = re.search(r"<([^>]+)>$", finding.message)
        if not target_match:
            continue
        old_target = target_match.group(1)
        replacement = replacement_for_broken_link(root, source, old_target, strategy_map)
        if replacement:
            replacements_by_file.setdefault(source, []).append((old_target, replacement))
    fixed = 0
    for source, replacements in replacements_by_file.items():
        text = source.read_text(encoding="utf-8")
        updated = text
        for old_target, replacement in replacements:
            updated = updated.replace(f"]({old_target})", f"]({replacement})", 1)
        if updated != text:
            source.write_text(updated, encoding="utf-8")
            fixed += sum(1 for old, new in replacements if old != new)
    return fixed
def check_broken_links(root: Path, fix: bool = False) -> tuple[list[Finding], int]:
    docs_archive = root / "docs" / "archive"
    strategy_map = parse_strategy_index(root)
    findings: list[Finding] = []
    for source in markdown_files(root):
        if is_relative_to(source, docs_archive):
            continue
        for line_no, target, link in extract_links(source):
            if is_url(strip_link_title(target)):
                continue
            path_part, anchor = split_target(target)
            target_path = resolve_link(root, source, path_part)
            if is_relative_to(target_path, docs_archive):
                continue
            location = f"{rel(source, root)}:{line_no}"
            if not target_path.exists():
                findings.append(Finding(location, f"{link} <{target}>"))
                continue
            if anchor and target_path.suffix.lower() == ".md":
                if not anchor_exists(target_path, anchor):
                    findings.append(Finding(location, f"{link} <{target}>"))
    fixed = apply_link_fixes(root, findings, strategy_map) if fix else 0
    return (check_broken_links(root, fix=False)[0], fixed) if fixed else (findings, fixed)
def archive_tokens_for_line(root: Path, source: Path, line: str) -> set[str]:
    tokens: set[str] = set()
    for _line_no, target, _link in [(0, t, l) for _ln, t, l in extract_links_from_line(line)]:
        path_part, _anchor = split_target(target)
        if path_part and is_relative_to(resolve_link(root, source, path_part), root / "docs" / "archive"):
            tokens.add(strip_link_title(target))
    raw_re = re.compile(r"(?:docs/archive|(?:\.\./)*archive)/[A-Za-z0-9_.\-/]+\.md")
    tokens.update(raw_re.findall(line))
    return tokens
def extract_links_from_line(line: str) -> list[tuple[int, str, str]]:
    return [(0, m.group(1).strip(), m.group(0)) for m in LINK_RE.finditer(line)]
def check_archive_references(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    docs_archive = root / "docs" / "archive"
    for source in markdown_files(root):
        source_rel = rel(source, root)
        if is_relative_to(source, docs_archive) or source_rel in ARCHIVE_REFERENCE_WHITELIST:
            continue
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for token in sorted(archive_tokens_for_line(root, source, line)):
                findings.append(Finding(f"{source_rel}:{line_no}", f"live doc references archive path: {token}"))
    return findings
def parse_canonical_metrics(root: Path) -> dict[str, tuple[int, str]]:
    path = root / "docs" / "CANONICAL_GOALS.md"
    metrics: dict[str, tuple[int, str]] = {}
    key_for = {"python modules": "modules", "automated tests": "tests", "api operations": "api operations", "knowledge mound adapters": "adapters", "agent types": "agent types", "agent types (registered)": "agent types"}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("*") for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        key = key_for.get(cells[0].lower())
        if not key:
            continue
        num = re.search(r"\d+(?:,\d+)*", cells[1])
        if num:
            value = int(num.group(0).replace(",", ""))
            suffix = "+" if "+" in cells[1].split()[0] else ""
            metrics[key] = (value, f"{num.group(0)}{suffix} {key}")
    return metrics
def is_metric_whitelisted(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in METRIC_DRIFT_WHITELIST)
def should_check_metric(kind: str, value: int, line: str) -> bool:
    lower = line.lower()
    if kind == "tests":
        return value >= 100000
    if kind == "api operations":
        return value >= 1000
    if kind == "modules":
        return value >= 1000 and ("python modules" in lower or "codebase" in lower or "scale:" in lower)
    if kind == "adapters":
        return value >= 30
    if kind == "agent types":
        return True
    return True
def check_metric_drift(root: Path) -> list[Finding]:
    canonical = parse_canonical_metrics(root)
    findings: list[Finding] = []
    for source in markdown_files(root):
        source_rel = rel(source, root)
        if is_metric_whitelisted(source_rel):
            continue
        in_fence = False
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in METRIC_RE.finditer(line):
                raw_num, plus, raw_kind = match.groups()
                kind = raw_kind.lower()
                value = int(raw_num.replace(",", ""))
                if not should_check_metric(kind, value, line):
                    continue
                canonical_value, canonical_label = canonical[kind]
                if value == canonical_value:
                    continue
                claim = f"{raw_num}{plus or ''} {raw_kind}"
                message = f"claim '{claim}' diverges from canonical {canonical_label} in CANONICAL_GOALS.md. If intentional, add this file to the whitelist at the top of this script and include a comment explaining why."
                findings.append(Finding(f"{source_rel}:{line_no}", message))
    return findings
def expand_codes(line: str) -> set[str]:
    codes: set[str] = set()
    for prefix, start, end in CODE_RE.findall(line):
        if end:
            for number in range(int(start), int(end) + 1):
                codes.add(f"{prefix}-{number:02d}")
        else:
            codes.add(f"{prefix}-{int(start):02d}")
    return codes
def delayed_codes(root: Path) -> set[str]:
    path = root / "docs" / "status" / "NEXT_STEPS_CANONICAL.md"
    codes: set[str] = set()
    in_delay = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            heading = line.lstrip("#").strip().lower()
            in_delay = "delay" in heading or "delayed" in heading or "not until" in heading
            continue
        if in_delay:
            codes.update(expand_codes(line))
    return codes
def dic_issue_map(root: Path) -> dict[str, str]:
    path = root / "docs" / "plans" / "EPISTEMIC_CI_AND_CRUX_ENGINE.md"
    mapping: dict[str, str] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        code = re.search(r"\b(DIC-\d{2})\b", line)
        if code:
            current = code.group(1)
        issue = re.search(r"github\.com/synaptent/aragora/issues/(\d+)", line)
        if current and issue:
            mapping[current] = issue.group(1)
    return mapping
def check_tier_contradictions(root: Path) -> list[Finding]:
    delayed = delayed_codes(root)
    issue_to_code = {issue: code for code, issue in dic_issue_map(root).items() if code in delayed}
    findings: list[Finding] = []
    path = root / "docs" / "FEATURE_GAP_LIST.md"
    current_tier: str | None = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        heading = re.match(r"^##\s+(P[0-4])\b", line.lstrip())
        if heading:
            current_tier = heading.group(1) if heading.group(1) in {"P0", "P1"} else None
            continue
        if current_tier is None or not line.startswith("|"):
            continue
        row_codes = expand_codes(line).intersection(delayed)
        row_issues = {
            issue_to_code[number]
            for number in re.findall(r"github\.com/synaptent/aragora/issues/(\d+)|#(\d+)", line)
            for number in number
            if number in issue_to_code
        }
        contradictions = sorted(row_codes.union(row_issues))
        for code in contradictions:
            findings.append(
                Finding(
                    f"docs/FEATURE_GAP_LIST.md:{line_no}",
                    f"{current_tier} row mentions delayed-track {code}: {line.strip()}",
                )
            )
    return findings
def run_gh_issue_list(root: Path) -> list[dict[str, object]]:
    cmd = ["gh", "issue", "list", "--repo", GITHUB_REPO, "--state", "open", "--json", "number,title,labels,body", "--limit", "200"]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "gh issue list failed")
    return json.loads(result.stdout)
def check_gh_hygiene(root: Path) -> CheckResult:
    if os.environ.get("AIRSCRIPT_CHECK_GH") != "1":
        return CheckResult("gh hygiene", "Check 5 (gh hygiene)", "warnings", [], True, "AIRSCRIPT_CHECK_GH!=1")
    if not shutil.which("gh"):
        return CheckResult("gh hygiene", "Check 5 (gh hygiene)", "warnings", [], True, "gh not on PATH")
    try:
        issues = run_gh_issue_list(root)
    except Exception as exc:
        return CheckResult("gh hygiene", "Check 5 (gh hygiene)", "warnings", [Finding("gh", str(exc))])
    plan_text = (root / "docs" / "plans" / "EPISTEMIC_CI_AND_CRUX_ENGINE.md").read_text(encoding="utf-8")
    delayed = delayed_codes(root)
    by_code: dict[str, list[dict[str, object]]] = {}
    by_doc: dict[str, list[dict[str, object]]] = {}
    findings: list[Finding] = []
    for issue in issues:
        title = str(issue.get("title") or "")
        body = str(issue.get("body") or "")
        number = issue.get("number")
        title_code = DIC_TITLE_RE.search(title)
        if title_code and title_code.group(1) not in plan_text:
            findings.append(Finding(f"#{number}", f"title code {title_code.group(1)} is not in EPISTEMIC_CI_AND_CRUX_ENGINE.md"))
        for code in expand_codes(f"{title}\n{body}"):
            if code.startswith(TRACKED_ISSUE_CODE_PREFIXES):
                by_code.setdefault(code, []).append(issue)
        for doc in DESIGN_DOC_RE.findall(body):
            by_doc.setdefault(doc, []).append(issue)
        labels = {str(label.get("name", "")) for label in issue.get("labels") or [] if isinstance(label, dict)}
        if "boss-ready" in labels:
            for code in sorted(expand_codes(f"{title}\n{body}").intersection(delayed)):
                findings.append(Finding(f"#{number}", f"boss-ready issue mentions delayed-track {code}"))
    for code, matches in sorted(by_code.items()):
        numbers = sorted({str(issue.get("number")) for issue in matches})
        if len(numbers) > 1:
            findings.append(Finding("gh", f"potential duplicate tracked code {code}: issues #{', #'.join(numbers)}"))
    for doc, matches in sorted(by_doc.items()):
        numbers = sorted({str(issue.get("number")) for issue in matches})
        if len(numbers) > 1:
            findings.append(Finding("gh", f"potential duplicate design doc {doc}: issues #{', #'.join(numbers)}"))
    return CheckResult("gh hygiene", "Check 5 (gh hygiene)", "warnings", findings)
def format_summary(result: CheckResult) -> str:
    if result.skipped:
        return f"{result.label + ':':<31} SKIPPED ({result.skip_reason})"
    if result.findings:
        return f"{result.label + ':':<31} FAIL ({len(result.findings)} {result.noun})"
    return f"{result.label + ':':<31} PASS"
def print_report(results: list[CheckResult]) -> None:
    print("aragora docs consistency check")
    print("==============================")
    for result in results:
        print(format_summary(result))
    print()
    print("-- details --")
    any_details = False
    for result in results:
        if result.skipped or not result.findings:
            continue
        any_details = True
        print(f"[{result.label}]")
        for finding in result.findings:
            print(f"{finding.location}: {finding.message}")
        print()
    if not any_details:
        print("No findings.")
def run(root: Path, fix: bool = False) -> list[CheckResult]:
    broken, fixed = check_broken_links(root, fix=fix)
    if fixed:
        print(f"Applied {fixed} safe broken-link fix(es).")
    return [
        CheckResult("broken links", "Check 1 (broken links)", "broken", broken),
        CheckResult("live archive refs", "Check 2 (live->archive refs)", "violations", check_archive_references(root)),
        CheckResult("metric drift", "Check 3 (metric drift)", "drifts", check_metric_drift(root)),
        CheckResult("tier contradictions", "Check 4 (tier contradictions)", "contradictions", check_tier_contradictions(root)),
        check_gh_hygiene(root),
    ]
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root(), help="Repository root")
    parser.add_argument("--fix", action="store_true", help="Apply safe unambiguous broken-link fixes")
    args = parser.parse_args(argv)
    results = run(args.root.resolve(), fix=args.fix)
    print_report(results)
    return 1 if any(result.findings and not result.skipped for result in results) else 0
if __name__ == "__main__":
    raise SystemExit(main())
