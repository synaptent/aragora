"""Post-delivery acceptance-criteria binding gate (SpecUpgrader v1.3).

This module adds a conservative, pure-Python gate that runs AFTER a worker
produces a deliverable but BEFORE the supervisor auto-publishes the PR.

Three checks, all **fail-closed** (err toward ``needs_human``):

1. ``file_scope_adherence`` - every changed path must be in the spec's
   ``file_scope_hints`` OR be an obvious companion file (a test file for
   the same module).  An empty ``file_scope_hints`` list means no
   enforcement (open scope) - this is the existing supervisor behaviour.

2. ``test_presence`` - when any acceptance criterion mentions "test" or
   "tests", the deliverable MUST include at least one file under
   ``tests/``.  A one-line non-test change does NOT satisfy "add tests".

3. ``file_creation`` - when the issue's ``## Files`` (or ``File Scope``,
   ``Deliverables``) section names a new test file (typically annotated
   with ``(new)``), the deliverable MUST create that file OR a sibling
   under the same directory whose name matches the ``test_<subject>.py``
   convention.

The module exports a single entry point, :func:`evaluate_acceptance`,
which returns :class:`AcceptanceGateResult`.  The caller decides how to
act on failures (typically: mark needs_human, skip PR publish, emit a
``spec_upgrade`` telemetry row).

Design principles:

* Conservative - false negatives (reject valid) are cheaper than false
  positives (accept tangential).
* Pure - no I/O, no subprocess, no network.  Easy to unit test.
* Small surface - one function, one dataclass, a handful of helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

__all__ = [
    "AcceptanceGateResult",
    "evaluate_acceptance",
    "inject_closes_into_pr_body",
    "pr_body_already_closes",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Match acceptance criterion text that references testing.
_TEST_CRITERION_RE = re.compile(
    r"\b("
    r"test|tests|pytest|python\s+-m\s+pytest|unittest|coverage|assert"
    r")\b",
    re.IGNORECASE,
)

# Phrases that guard ALREADY-EXISTING tests rather than ask for new ones.
# These are subtracted from a criterion before the test-mention check above is
# applied to what remains, so a criterion carrying both ("add tests, and keep
# existing tests passing") still demands tests on the strength of its residue.
#
# Every alternative must assert something about tests *continuing to hold* —
# a qualifier alone is not enough. "existing tests" is only subtracted when it
# comes with a pass-clause, so "extend existing tests" (a request to edit test
# files) still demands tests, while "existing tests still pass" does not.
# A bare "tests pass" is likewise not matched: "the new tests pass"
# presupposes tests that must be written. Both choices fail closed.
#
# Motivation: the auto-generated narrowing and silent-exception issues all end
# with "Existing tests still pass", which made that whole class of refactor
# work structurally ungateable (#9638).
_TEST_REGRESSION_ONLY_RE = re.compile(
    r"\b(?:"
    r"(?:existing|all|current)\s+(?:unit\s+|integration\s+)?tests?"
    r"\s+(?:still\s+|continue\s+to\s+|should\s+still\s+)?pass(?:es|ing)?|"
    r"tests?\s+(?:still|continue\s+to|should\s+still)\s+pass(?:es|ing)?|"
    r"no\s+(?:new\s+)?test\s+(?:failures|regressions)|"
    r"(?:do(?:es)?\s+not|don't|doesn't)\s+break\s+(?:existing\s+)?tests?|"
    r"without\s+breaking\s+(?:existing\s+)?tests?"
    r")\b",
    re.IGNORECASE,
)

# Pull explicit pytest target file paths out of a criterion.
_PYTEST_TARGET_RE = re.compile(
    r"(?:pytest|python\s+-m\s+pytest)\s+([^\s'\"`]+\.py)",
    re.IGNORECASE,
)

# Detect whether a path is a pytest file.  Either under a ``tests`` tree OR
# matches the ``test_*.py`` / ``*_test.py`` convention at any depth.
_TEST_PATH_RE = re.compile(
    r"(^|/)tests?(/|$)"
    r"|(^|/)test_[^/]+\.py$"
    r"|(^|/)[^/]+_test\.py$"
)

# Match a path-like string in markdown bullets (subject of `(new)` or similar).
_BULLET_PATH_RE = re.compile(r"(?:^|\s)`?(?P<path>(?:\./)?[A-Za-z0-9_./-]+\.py)`?")

# Match `Closes`, `Fixes`, or `Resolves` followed by `#<n>`.
# GitHub supports: close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved.
_CLOSES_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(?P<num>\d+)\b",
    re.IGNORECASE,
)

# Reasonable companion-file markers for a subject source file ``aragora/x/foo.py``:
# * ``tests/**/test_foo.py``
# * ``aragora/x/tests/test_foo.py``
# * ``tests/swarm/test_foo_extra.py`` (prefix match, same stem)
#
# This companion logic is permissive - we deliberately want to accept
# legitimate sibling test edits that the worker added.


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcceptanceGateResult:
    """Structured result from :func:`evaluate_acceptance`.

    Attributes:
        passed: True iff every enabled check passed.
        failure_classes: Stable machine-readable identifiers for failed
            checks, e.g. ``"test_presence_missing"``.
        reasons: Human-readable reason strings, one per failure.
        checks_run: Identifiers of the checks that actually ran given the
            inputs (vs. those skipped because the spec lacked data).
        out_of_scope_paths: Paths that violated file-scope adherence.
        missing_expected_files: Expected new files that were not created.
    """

    passed: bool
    failure_classes: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    checks_run: tuple[str, ...] = field(default_factory=tuple)
    out_of_scope_paths: tuple[str, ...] = field(default_factory=tuple)
    missing_expected_files: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_classes": list(self.failure_classes),
            "reasons": list(self.reasons),
            "checks_run": list(self.checks_run),
            "out_of_scope_paths": list(self.out_of_scope_paths),
            "missing_expected_files": list(self.missing_expected_files),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_paths(paths: Iterable[str]) -> list[str]:
    """Normalize a path iterable: strip, drop empties, drop ``./`` prefix."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in paths or []:
        text = str(raw or "").strip()
        if not text:
            continue
        text = text.removeprefix("./").lstrip("/")
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _is_test_path(path: str) -> bool:
    """Heuristic: is ``path`` a pytest-style test file?"""
    if not path:
        return False
    normalized = path.strip().removeprefix("./").lstrip("/")
    return bool(_TEST_PATH_RE.search(normalized))


def _criterion_requires_tests(criteria: Sequence[str]) -> bool:
    """True when the criteria ask for test files, not merely mention tests.

    Regression-guard phrases are subtracted from each criterion and the
    module's original conservative rule is applied to the residue. Deleting
    only the guard phrase — rather than discarding the whole criterion —
    keeps the fallback alive for the rest of the sentence, so a criterion
    that both asks for tests and guards existing ones still demands tests,
    and any phrasing this module does not anticipate still requires them.
    """
    for item in criteria or []:
        text = str(item or "").strip()
        if not text:
            continue
        residual = _TEST_REGRESSION_ONLY_RE.sub(" ", text)
        if _TEST_CRITERION_RE.search(residual):
            return True
    return False


def _pytest_targets_from_criteria(criteria: Sequence[str]) -> list[str]:
    """Extract pytest file target paths from acceptance criterion strings."""
    targets: list[str] = []
    for item in criteria or []:
        for match in _PYTEST_TARGET_RE.finditer(str(item or "")):
            path = match.group(1).strip().strip("`'\"")
            if path:
                targets.append(path.removeprefix("./"))
    # Preserve order but dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def _extract_expected_new_files(issue_body: str | None) -> list[str]:
    """Pull explicitly-declared new file paths out of the issue body.

    Recognises bullet entries under sections like ``## Files``,
    ``## Deliverables``, ``## File Scope``, where entries are annotated
    with ``(new)`` or explicitly described as new/to create.
    """
    if not issue_body:
        return []
    expected: list[str] = []
    in_files_section = False
    for raw_line in str(issue_body).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().rstrip(":").lower()
            in_files_section = heading in {
                "files",
                "deliverables",
                "file scope",
                "new files",
                "expected files",
            }
            continue
        if not in_files_section or not stripped:
            continue
        lowered = stripped.lower()
        # Require an explicit "new" annotation to avoid false positives
        # from bulleted source-file references.
        if "(new)" not in lowered and " new" not in lowered and "new test" not in lowered:
            continue
        for match in _BULLET_PATH_RE.finditer(stripped):
            path = match.group("path").strip().strip("`'\"").removeprefix("./")
            if path and path not in expected:
                expected.append(path)
    return expected


def _match_test_companion(subject_path: str, candidate: str) -> bool:
    """Is ``candidate`` a plausible test companion for ``subject_path``?

    Rules:
    * candidate is a test path (``_is_test_path``)
    * candidate's basename starts with ``test_<subject_stem>`` OR
      candidate's basename matches ``<subject_stem>_test.py``
    """
    if not subject_path or not candidate:
        return False
    if not _is_test_path(candidate):
        return False
    subject_stem = subject_path.rsplit("/", 1)[-1].removesuffix(".py")
    if not subject_stem:
        return False
    candidate_name = candidate.rsplit("/", 1)[-1]
    return (
        candidate_name.startswith(f"test_{subject_stem}")
        or candidate_name == f"{subject_stem}_test.py"
    )


def _path_in_scope(path: str, scope: str) -> bool:
    """Permissive path-in-scope check.

    A ``path`` is in scope when:
    * ``path == scope``
    * ``path`` starts with ``scope + "/"`` (directory prefix)
    * ``scope`` itself is a parent directory
    """
    if not path or not scope:
        return False
    path_n = path.strip().removeprefix("./").lstrip("/")
    scope_n = scope.strip().removeprefix("./").rstrip("/").lstrip("/")
    if not path_n or not scope_n:
        return False
    if path_n == scope_n:
        return True
    return path_n.startswith(f"{scope_n}/")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_acceptance(
    *,
    acceptance_criteria: Sequence[str] | None,
    file_scope_hints: Sequence[str] | None,
    changed_paths: Sequence[str] | None,
    issue_body: str | None = None,
) -> AcceptanceGateResult:
    """Evaluate whether a deliverable satisfies the spec's acceptance terms.

    The gate is conservative.  Any check that lacks sufficient input data
    is skipped (not treated as a failure).  The caller can inspect
    :attr:`AcceptanceGateResult.checks_run` to see what ran.

    Args:
        acceptance_criteria: Criterion strings from ``spec.acceptance_criteria``.
        file_scope_hints: Path patterns from ``spec.file_scope_hints``.
        changed_paths: Paths the worker modified (from the work order).
        issue_body: Optional sanitized issue body - used to find explicit
            new-file declarations.

    Returns:
        An :class:`AcceptanceGateResult` - ``passed=True`` iff all enabled
        checks passed.
    """
    criteria = [str(c).strip() for c in acceptance_criteria or [] if str(c).strip()]
    scope = _clean_paths(file_scope_hints or [])
    changed = _clean_paths(changed_paths or [])

    checks_run: list[str] = []
    failure_classes: list[str] = []
    reasons: list[str] = []
    out_of_scope: list[str] = []
    missing_files: list[str] = []

    # -----------------------------------------------------------------
    # Check 1: file-scope adherence
    # -----------------------------------------------------------------
    if scope and changed:
        checks_run.append("file_scope_adherence")
        for path in changed:
            if any(_path_in_scope(path, s) for s in scope):
                continue
            # Allow companion test files for any scope entry ending in .py.
            if any(_match_test_companion(s, path) for s in scope if s.endswith(".py")):
                continue
            out_of_scope.append(path)
        if out_of_scope:
            failure_classes.append("file_scope_out_of_bounds")
            reasons.append(
                "Deliverable modified files outside the declared file_scope_hints: "
                + ", ".join(sorted(out_of_scope))
            )

    # -----------------------------------------------------------------
    # Check 2: test-presence
    # -----------------------------------------------------------------
    if criteria and _criterion_requires_tests(criteria):
        checks_run.append("test_presence")
        test_touch = [p for p in changed if _is_test_path(p)]
        if not test_touch:
            failure_classes.append("test_presence_missing")
            reasons.append(
                "Acceptance criteria require tests, but the deliverable did not "
                "add or modify any file under `tests/` (or a `test_*.py` / "
                "`*_test.py` file). Changed: " + (", ".join(changed) if changed else "(no files)")
            )

    # -----------------------------------------------------------------
    # Check 3: file-creation for explicit new-file declarations
    # -----------------------------------------------------------------
    # Source 1: explicit ``(new)`` annotations in the issue body.
    expected_from_body = _extract_expected_new_files(issue_body or "")
    # Source 2: explicit pytest file targets in acceptance criteria.
    expected_from_criteria = _pytest_targets_from_criteria(criteria)

    expected_new_files: list[str] = []
    for path in (*expected_from_body, *expected_from_criteria):
        if path and path not in expected_new_files:
            expected_new_files.append(path)

    if expected_new_files:
        checks_run.append("file_creation")
        changed_set = set(changed)
        for expected in expected_new_files:
            if expected in changed_set:
                continue
            # Permissive sibling match: accept ``tests/foo/test_X_extras.py``
            # when the expected was ``tests/foo/test_X.py`` as long as the
            # worker created SOMETHING under the same parent directory that
            # looks like a test for the same subject.
            expected_parent = expected.rsplit("/", 1)[0] if "/" in expected else ""
            expected_stem = expected.rsplit("/", 1)[-1].removesuffix(".py")
            # Strip leading ``test_`` when comparing stems.
            expected_subject = expected_stem.removeprefix("test_")
            sibling_found = False
            for path in changed:
                if not _is_test_path(path):
                    continue
                if expected_parent and not path.startswith(f"{expected_parent}/"):
                    # Also allow the exact parent directory as a path match.
                    if path.rsplit("/", 1)[0] != expected_parent:
                        continue
                candidate_stem = path.rsplit("/", 1)[-1].removesuffix(".py")
                candidate_subject = candidate_stem.removeprefix("test_")
                if expected_subject and (
                    expected_subject == candidate_subject
                    or candidate_subject.startswith(f"{expected_subject}_")
                    or expected_subject.startswith(f"{candidate_subject}_")
                ):
                    sibling_found = True
                    break
            if not sibling_found:
                missing_files.append(expected)
        if missing_files:
            failure_classes.append("expected_file_not_created")
            reasons.append(
                "Acceptance criteria / issue body named new test files that were "
                "not created or edited by the deliverable: " + ", ".join(missing_files)
            )

    passed = not failure_classes
    return AcceptanceGateResult(
        passed=passed,
        failure_classes=tuple(failure_classes),
        reasons=tuple(reasons),
        checks_run=tuple(checks_run),
        out_of_scope_paths=tuple(out_of_scope),
        missing_expected_files=tuple(missing_files),
    )


# ---------------------------------------------------------------------------
# ``Closes #N`` helpers
# ---------------------------------------------------------------------------


def pr_body_already_closes(body: str | None, *, issue_number: int | None = None) -> bool:
    """Return True if ``body`` already contains a GitHub-auto-close keyword.

    When ``issue_number`` is provided, require an exact match.  When it is
    omitted, any ``Closes/Fixes/Resolves #<n>`` occurrence counts.
    """
    if not body:
        return False
    for match in _CLOSES_KEYWORD_RE.finditer(str(body)):
        if issue_number is None:
            return True
        try:
            found = int(match.group("num"))
        except (ValueError, TypeError):
            continue
        if found == int(issue_number):
            return True
    return False


def inject_closes_into_pr_body(
    body: str | None,
    *,
    issue_number: int,
) -> str:
    """Return a PR body with ``Closes #<issue_number>`` prepended when absent.

    Idempotent: if the body already contains any ``Closes/Fixes/Resolves``
    keyword pointing at this issue number, the original body is returned
    unchanged.  Otherwise the closer is placed on its own line at the top
    of the body, preceded by a single blank line separator.
    """
    normalized_body = str(body or "").strip()
    if issue_number is None or int(issue_number) <= 0:
        return normalized_body
    if pr_body_already_closes(normalized_body, issue_number=int(issue_number)):
        return normalized_body
    closer = f"Closes #{int(issue_number)}"
    if not normalized_body:
        return closer
    return f"{closer}\n\n{normalized_body}"
