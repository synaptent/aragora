#!/usr/bin/env python3
"""
Check version alignment across all package manifests.

This script validates that all version sources in the repository are aligned.
It fails with exit code 1 if any version mismatch is detected.

Usage:
    python scripts/check_version_alignment.py          # check (the default)
    python scripts/check_version_alignment.py --check  # check, explicitly
    python scripts/check_version_alignment.py --fix    # auto-fix mismatches

Tracked set
-----------
Everything below is compared to ``aragora/__version__.py`` (``VERSION_*`` and
``RELEASE_DATE``).  Every spot that states the *current* version or release
date is tracked, so a bump is ``aragora/__version__.py`` plus ``--fix``:

* package manifests (``pyproject.toml``, ``package.json``) and the Python SDK
  ``__version__`` string (``VERSION_SOURCES`` / ``PYTHON_VERSION_SOURCES``);
* the four npm ``package-lock.json`` roots (top-level ``version``, the
  ``packages[""]`` entry and the ``../../sdk/typescript`` link entry in
  ``aragora/live``) and the ``aragora`` package in ``uv.lock``;
* the ``README.md`` metrics block, the ``project_version`` claim in
  ``docs/status/metrics/catalog.toml`` and the ``CHANGELOG.md`` Unreleased line;
* documentation spots matched by the regex patterns in ``DOC_SOURCES``,
  including every ``aragora==X.Y.Z`` install command in ``UPGRADE_ROADMAP.md``.

Deliberately untracked, because they are content rather than version spots:
release history (``## [X.Y.Z]`` changelog entries, ``### vX.Y.Z Behavioral
Changes`` sections, prior release notes, archived status receipts) and
third-party packages in lockfiles that happen to share a version number.

Doc patterns that name a ``date`` group are also checked against
``RELEASE_DATE`` (and rewritten with it under ``--fix``), so a version cannot
sit next to the previous release's date.  Patterns that name a ``series`` group
are compared to the ``major.minor`` series instead of the full version.  The
``UPGRADE_ROADMAP.md`` support-matrix row is fixed by inserting a new
``Current`` row and demoting the previous series to ``Supported``; individual
``Supported`` rows beyond ``SUPPORTED_ROWS_KEPT`` fold into one range row so
the table stays bounded.  A series' status (Supported, Deprecated, End of
life) is a policy decision and is never changed here.

A tracked spot that matches nothing (a missing manifest or a dead doc pattern)
is a mismatch, not an aligned spot: it is a silent hole in the guarantee.
Remove the entry or restore the file or line it tracked.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path


def get_canonical_version() -> str:
    """Get the canonical version from aragora/__version__.py."""
    version_file = Path("aragora/__version__.py")
    if not version_file.exists():
        raise FileNotFoundError("aragora/__version__.py not found")

    content = version_file.read_text()

    # Extract version components
    major = re.search(r"VERSION_MAJOR\s*=\s*(\d+)", content)
    minor = re.search(r"VERSION_MINOR\s*=\s*(\d+)", content)
    patch = re.search(r"VERSION_PATCH\s*=\s*(\d+)", content)

    if major is None or minor is None or patch is None:
        raise ValueError("Could not parse version from aragora/__version__.py")

    return f"{major.group(1)}.{minor.group(1)}.{patch.group(1)}"


def get_pyproject_version(path: Path) -> str | None:
    """Extract version from a pyproject.toml file."""
    if not path.exists():
        return None

    content = path.read_text()
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return match.group(1) if match else None


def get_package_json_version(path: Path) -> str | None:
    """Extract version from a package.json file."""
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        return data.get("version")
    except json.JSONDecodeError:
        return None


def fix_pyproject_version(path: Path, new_version: str) -> bool:
    """Update version in a pyproject.toml file."""
    if not path.exists():
        return False

    content = path.read_text()
    new_content = re.sub(
        r'^(version\s*=\s*["\'])([^"\']+)(["\'])',
        rf"\g<1>{new_version}\g<3>",
        content,
        flags=re.MULTILINE,
    )

    if new_content != content:
        path.write_text(new_content)
        return True
    return False


def fix_package_json_version(path: Path, new_version: str) -> bool:
    """Update version in a package.json file."""
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text())
        if data.get("version") != new_version:
            data["version"] = new_version
            path.write_text(json.dumps(data, indent=2) + "\n")
            return True
    except json.JSONDecodeError:
        pass
    return False


def get_canonical_release_date() -> str | None:
    """Get RELEASE_DATE from aragora/__version__.py, if declared."""
    version_file = Path("aragora/__version__.py")
    if not version_file.exists():
        return None
    match = re.search(r'RELEASE_DATE\s*=\s*["\'](\d{4}-\d{2}-\d{2})["\']', version_file.read_text())
    return match.group(1) if match else None


def _version_group(pattern: str) -> str | int:
    """Doc patterns carry the version in group 2 unless they name a ``version`` or ``series`` group.

    Named groups are numbered too, so a pattern that names any group (``date``,
    ``since``) must also name the value group; otherwise group 2 could be the
    date and ``--fix`` would write the version into the date slot.
    """
    if "(?P<series>" in pattern:
        return "series"
    if "(?P<version>" in pattern:
        return "version"
    if "(?P<" in pattern:
        raise ValueError(f"pattern names groups but neither 'version' nor 'series': {pattern}")
    return 2


def _expected_version(pattern: str, canonical: str) -> str:
    """The value a doc spot must carry: the full version, or its ``major.minor`` series."""
    if "(?P<series>" in pattern:
        return canonical.rsplit(".", 1)[0]
    return canonical


def get_doc_versions(path: Path, pattern: str) -> list[str]:
    """Extract every version string a regex pattern matches in a documentation file.

    A pattern may legitimately match several spots in one file (for example an
    image tag repeated in a compose example and an env-var example); each match
    is returned so a single stale occurrence cannot hide behind a fresh one.
    """
    if not path.exists():
        return []
    content = path.read_text()
    group = _version_group(pattern)
    return [match.group(group) for match in re.finditer(pattern, content, re.MULTILINE)]


def get_doc_dates(path: Path, pattern: str) -> list[str]:
    """Extract every release date a pattern's ``date`` group matches.

    Returns ``[]`` for patterns without a ``date`` group, so only spots that
    pair a version with the release date are held to ``RELEASE_DATE``.
    """
    if "(?P<date>" not in pattern or not path.exists():
        return []
    content = path.read_text()
    return [match.group("date") for match in re.finditer(pattern, content, re.MULTILINE)]


def fix_doc_version(
    path: Path, pattern: str, new_version: str, release_date: str | None = None
) -> bool:
    """Update a version string in documentation using a regex pattern.

    When the pattern names a ``date`` group and a release date is supplied, the
    date is rewritten in the same pass so "Last Updated" style lines cannot end
    up carrying the new version next to the previous release's date.
    """
    if not path.exists():
        return False
    content = path.read_text()
    group = _version_group(pattern)

    def _rewrite(match: re.Match[str]) -> str:
        text = match.group(0)
        base = match.start()
        edits = [(match.span(group), new_version)]
        if release_date and "date" in match.re.groupindex and match.group("date"):
            edits.append((match.span("date"), release_date))
        for (start, end), value in sorted(edits, reverse=True):
            text = text[: start - base] + value + text[end - base :]
        return text

    new_content = re.sub(pattern, _rewrite, content, flags=re.MULTILINE)
    if new_content != content:
        path.write_text(new_content)
        return True
    return False


# Individual ``Supported`` rows kept under ``**Current**`` before older series
# fold into one range row: the two minors after the current one, the grace
# window docs/reference/DEPRECATION_POLICY.md gives deprecations.
SUPPORTED_ROWS_KEPT = 2
_SUPPORTED_ROW = re.compile(r"^\| v(\d+\.\d+)\.x \| (\d{4}-\d{2}-\d{2}) \| Active \| Supported \|$")
_SUPPORTED_RANGE_ROW = re.compile(
    r"^\| v(\d+\.\d+)\.x–v(\d+\.\d+)\.x \| (\d{4}-\d{2}-\d{2})–(\d{4}-\d{2}-\d{2}) "
    r"\| Active \| Supported \|$"
)


def _fold_supported_rows(
    lines: list[str], start: int, keep: int = SUPPORTED_ROWS_KEPT
) -> list[str]:
    """Fold the individual ``Supported`` rows from ``start`` beyond ``keep`` into one range row.

    Rows run newest-first, so the excess is the tail.  A standard range row
    directly beneath absorbs the folded series; otherwise a new one is written.
    Status is never touched: expiring a series is a policy edit, not a bump.
    """
    rows: list[re.Match[str]] = []
    while start + len(rows) < len(lines):
        row = _SUPPORTED_ROW.match(lines[start + len(rows)])
        if row is None:
            break
        rows.append(row)
    excess = rows[keep:]
    if not excess:
        return lines
    end = start + len(rows)
    newest_series, newest_date = excess[0].group(1), excess[0].group(2)
    oldest_series, oldest_date = excess[-1].group(1), excess[-1].group(2)
    below = _SUPPORTED_RANGE_ROW.match(lines[end]) if end < len(lines) else None
    if below is not None:
        oldest_series, oldest_date = below.group(1), below.group(3)
        end += 1
    folded = (
        f"| v{oldest_series}.x–v{newest_series}.x | {oldest_date}–{newest_date} "
        "| Active | Supported |"
    )
    return lines[: start + keep] + [folded] + lines[end:]


def fix_support_matrix_row(
    path: Path, pattern: str, new_series: str, release_date: str | None = None
) -> bool:
    """Move the ``**Current**`` row of a support matrix to a new ``major.minor`` series.

    A minor bump is a history event, not an edit: the new series gets a fresh
    ``Current`` row carrying the release date and the previous series is
    demoted to ``Supported`` keeping its own release date (the ``since``
    group), so the timeline never loses a series.  Older ``Supported`` rows fold
    into a range row (``_fold_supported_rows``) so the table stays bounded.
    Without a release date there is nothing truthful to put in the new row, so
    the spot is left to the operator.
    """
    if not path.exists() or not release_date:
        return False
    lines = path.read_text().split("\n")
    row = re.compile(pattern, re.MULTILINE)
    for index, line in enumerate(lines):
        match = row.match(line)
        if match is None:
            continue
        if match.group("series") == new_series:
            return False
        lines[index : index + 1] = [
            f"| **v{new_series}.x** | {release_date} | Active | **Current** |",
            f"| v{match.group('series')}.x | {match.group('since')} | Active | Supported |",
        ]
        path.write_text("\n".join(_fold_supported_rows(lines, index + 1)))
        return True
    return False


def get_python_version(path: Path) -> str | None:
    """Extract __version__ from a Python source file."""
    if not path.exists():
        return None
    content = path.read_text()
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return match.group(1) if match else None


def fix_python_version(path: Path, new_version: str) -> bool:
    """Update __version__ in a Python source file."""
    if not path.exists():
        return False
    content = path.read_text()
    new_content = re.sub(
        r'^(__version__\s*=\s*["\'])([^"\']+)(["\'])',
        rf"\g<1>{new_version}\g<3>",
        content,
        flags=re.MULTILINE,
    )
    if new_content != content:
        path.write_text(new_content)
        return True
    return False


# Package manifests compared to the canonical version; a missing manifest is a
# mismatch, not a skipped spot.
VERSION_SOURCES: list[tuple[str, Path, str]] = [
    ("pyproject.toml", Path("pyproject.toml"), "pyproject"),
    ("sdk/python/pyproject.toml", Path("sdk/python/pyproject.toml"), "pyproject"),
    ("aragora/live/package.json", Path("aragora/live/package.json"), "package"),
    ("sdk/typescript/package.json", Path("sdk/typescript/package.json"), "package"),
    ("ide/vscode-aragora/package.json", Path("ide/vscode-aragora/package.json"), "package"),
    (
        "ide/vscode-aragora/webview-ui/package.json",
        Path("ide/vscode-aragora/webview-ui/package.json"),
        "package",
    ),
]
PYTHON_VERSION_SOURCES: list[tuple[str, Path]] = [
    ("sdk/python/aragora_sdk/__init__.py", Path("sdk/python/aragora_sdk/__init__.py")),
]

# Regex-tracked spots: docs, plus the lockfile roots, README metrics block and
# metrics catalog that used to be aligned by hand.  Group 2 (or the ``version``
# / ``series`` group) is the value; a ``date`` group is held to RELEASE_DATE.
DOC_SOURCES: list[tuple[str, Path, str]] = [
    (
        "docs/status/STATUS.md",
        Path("docs/status/STATUS.md"),
        r"^(Current released version is \*\*v?)(?P<version>\d+\.\d+\.\d+)(\*\* \(released )"
        r"(?P<date>\d{4}-\d{2}-\d{2})(\)\.)$",
    ),
    (
        "docs/deployment/SCALING.md",
        Path("docs/deployment/SCALING.md"),
        r'(\s*"version":\s*")(\d+\.\d+\.\d+)(",)',
    ),
    (
        "docs/api/API_REFERENCE.md",
        Path("docs/api/API_REFERENCE.md"),
        r"^(\|\s*TypeScript\s*\([^)]+\)\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs/api/API_REFERENCE.md (Python SDK)",
        Path("docs/api/API_REFERENCE.md"),
        r"^(\|\s*Python\s*\([^)]+\)\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs/CANONICAL_GOALS.md",
        Path("docs/CANONICAL_GOALS.md"),
        r"^(\|\s*Version\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs/DEPLOYMENT.md",
        Path("docs/DEPLOYMENT.md"),
        r"(`)(\d+\.\d+\.\d+)(` \(version from pyproject\.toml\))",
    ),
    (
        "docs/DEPLOYMENT.md (git tag)",
        Path("docs/DEPLOYMENT.md"),
        r"(`v)(\d+\.\d+\.\d+)(` \(git tag\))",
    ),
    (
        "docs/DEPLOYMENT.md (image pin)",
        Path("docs/DEPLOYMENT.md"),
        r"(ghcr\.io/synaptent/aragora/backend:)(\d+\.\d+\.\d+)(\b)",
    ),
    (
        "docs/deployment/GO_LIVE_CHECKLIST.md",
        Path("docs/deployment/GO_LIVE_CHECKLIST.md"),
        r"(ghcr\.io/synaptent/aragora/(?:backend|frontend):)(\d+\.\d+\.\d+)(\b)",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"^(\|\s*Root platform\s*\|[^|]*\|[^|]*\|\s*\*\*)(\d+\.\d+\.\d+)(\*\*\s*\|.*)$",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (Python SDK)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"^(\|\s*Python SDK\s*\|[^|]*\|[^|]*\|\s*\*\*)(\d+\.\d+\.\d+)(\*\*\s*\|.*)$",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (checkout)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"^(\|\s*This checkout \(`pip install \./sdk/python`\)\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (build ships)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"(; the )(\d+\.\d+\.\d+)( build ships when the operator tags)",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (in-tree moved)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"(in-tree version has moved to )(\d+\.\d+\.\d+)( but)",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (not yet)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"(gives you \d+\.\d+\.\d+, not )(\d+\.\d+\.\d+)(\b)",
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (in-tree prose)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"(in-tree version \()(\d+\.\d+\.\d+)(, not yet released to)",
    ),
    (
        "docs/api/API_REFERENCE.md (last updated)",
        Path("docs/api/API_REFERENCE.md"),
        r"^(> \*\*Last Updated:\*\* )(?P<date>\d{4}-\d{2}-\d{2})( \(v)(?P<version>\d+\.\d+\.\d+)"
        r"( alignment with repo versions\))$",
    ),
    (
        "docs/STATUS.md",
        Path("docs/STATUS.md"),
        r"^(Current released version is \*\*v?)(?P<version>\d+\.\d+\.\d+)(\*\* \(released )"
        r"(?P<date>\d{4}-\d{2}-\d{2})(\)\.)$",
    ),
    (
        "docs/STATUS.md (version bullet)",
        Path("docs/STATUS.md"),
        r"^(- \*\*Version\*\*: v)(\d+\.\d+\.\d+)()$",
    ),
    (
        "docs/status/STATUS.md (version bullet)",
        Path("docs/status/STATUS.md"),
        r"^(- \*\*Version\*\*: v)(\d+\.\d+\.\d+)()$",
    ),
    (
        "docs/guides/SELF_HOSTED_QUICKSTART.md",
        Path("docs/guides/SELF_HOSTED_QUICKSTART.md"),
        r"^(\*Updated: )(?P<date>\d{4}-\d{2}-\d{2})(\*\n\*Version: )(?P<version>\d+\.\d+\.\d+)(\*)$",
    ),
    (
        "docs/guides/SELF_HOSTED_QUICKSTART.md (health response)",
        Path("docs/guides/SELF_HOSTED_QUICKSTART.md"),
        r'(\{"status": "healthy", "version": ")(\d+\.\d+\.\d+)("\})',
    ),
    (
        "docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md",
        Path("docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md"),
        r"^(\*Version: )(?P<version>\d+\.\d+\.\d+)( \| Updated: )(?P<date>\d{4}-\d{2}-\d{2})(\*)$",
    ),
    (
        "docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md (header)",
        Path("docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md"),
        r"^(\*\*Version:\*\* )(?P<version>\d+\.\d+\.\d+)(\n\*\*Last Updated:\*\* )(?P<date>\d{4}-\d{2}-\d{2})()$",
    ),
    (
        "docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md (health response)",
        Path("docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md"),
        r'^(\s*"version": ")(\d+\.\d+\.\d+)(",)$',
    ),
    (
        "docs-site/docs/deployment/scaling.md",
        Path("docs-site/docs/deployment/scaling.md"),
        r'(\s*"version":\s*")(\d+\.\d+\.\d+)(",)',
    ),
    (
        "docs-site/docs/api/reference.md",
        Path("docs-site/docs/api/reference.md"),
        r"^(\|\s*TypeScript\s*\([^)]+\)\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs-site/docs/api/reference.md (Python SDK)",
        Path("docs-site/docs/api/reference.md"),
        r"^(\|\s*Python\s*\([^)]+\)\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs-site/docs/deployment/overview.md",
        Path("docs-site/docs/deployment/overview.md"),
        r"(`)(\d+\.\d+\.\d+)(` \(version from pyproject\.toml\))",
    ),
    (
        "docs-site/docs/deployment/overview.md (git tag)",
        Path("docs-site/docs/deployment/overview.md"),
        r"(`v)(\d+\.\d+\.\d+)(` \(git tag\))",
    ),
    (
        "docs-site/docs/deployment/overview.md (image pin)",
        Path("docs-site/docs/deployment/overview.md"),
        r"(ghcr\.io/synaptent/aragora/backend:)(\d+\.\d+\.\d+)(\b)",
    ),
    (
        "docs-site/docs/reference/install-matrix.md",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"^(\|\s*Root platform\s*\|[^|]*\|[^|]*\|\s*\*\*)(\d+\.\d+\.\d+)(\*\*\s*\|.*)$",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (Python SDK)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"^(\|\s*Python SDK\s*\|[^|]*\|[^|]*\|\s*\*\*)(\d+\.\d+\.\d+)(\*\*\s*\|.*)$",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (checkout)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"^(\|\s*This checkout \(`pip install \./sdk/python`\)\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (build ships)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"(; the )(\d+\.\d+\.\d+)( build ships when the operator tags)",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (in-tree moved)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"(in-tree version has moved to )(\d+\.\d+\.\d+)( but)",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (not yet)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"(gives you \d+\.\d+\.\d+, not )(\d+\.\d+\.\d+)(\b)",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (in-tree prose)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"(in-tree version \()(\d+\.\d+\.\d+)(, not yet released to)",
    ),
    (
        "docs-site/docs/api/reference.md (last updated)",
        Path("docs-site/docs/api/reference.md"),
        r"^(> \*\*Last Updated:\*\* )(?P<date>\d{4}-\d{2}-\d{2})( \(v)(?P<version>\d+\.\d+\.\d+)"
        r"( alignment with repo versions\))$",
    ),
    (
        "docs-site/docs/contributing/status.md",
        Path("docs-site/docs/contributing/status.md"),
        r"^(Current released version is \*\*v?)(?P<version>\d+\.\d+\.\d+)(\*\* \(released )"
        r"(?P<date>\d{4}-\d{2}-\d{2})(\)\.)$",
    ),
    (
        "docs-site/docs/contributing/status.md (version bullet)",
        Path("docs-site/docs/contributing/status.md"),
        r"^(- \*\*Version\*\*: v)(\d+\.\d+\.\d+)()$",
    ),
    (
        "docs/migration/V3_MIGRATION_GUIDE.md",
        Path("docs/migration/V3_MIGRATION_GUIDE.md"),
        r"^(> \*\*Current version:\*\* v)(\d+\.\d+\.\d+)()$",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"^(\*\*Aragora v)(?P<version>\d+\.\d+\.\d+)(\*\* \(released )"
        r"(?P<date>\d{4}-\d{2}-\d{2})(\))$",
    ),
    (
        # The ``since`` group is the series' own first-release date and is kept
        # when the row is demoted; it is deliberately not a ``date`` group, so a
        # patch release (same series, new RELEASE_DATE) leaves the row alone.
        "docs/deployment/UPGRADE_ROADMAP.md (support matrix)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"^(\| \*\*v)(?P<series>\d+\.\d+)(\.x\*\* \| )(?P<since>\d{4}-\d{2}-\d{2})"
        r"( \| Active \| \*\*Current\*\* \|)$",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (version check)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r'^(print\(__version__\)\s*# ")(\d+\.\d+\.\d+)(")$',
    ),
    (
        "docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md (image pin)",
        Path("docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md"),
        r"(ghcr\.io/synaptent/aragora/backend:)(\d+\.\d+\.\d+)(\b)",
    ),
    (
        "docs/SDK_GUIDE.md (cadence example)",
        Path("docs/SDK_GUIDE.md"),
        r"(\(e\.g\. the repo can declare )(\d+\.\d+\.\d+)( while PyPI serves)",
    ),
    (
        "docs-site/docs/guides/sdk.md (cadence example)",
        Path("docs-site/docs/guides/sdk.md"),
        r"(\(e\.g\. the repo can declare )(\d+\.\d+\.\d+)( while PyPI serves)",
    ),
    (
        "README.md (metrics block)",
        Path("README.md"),
        r"(Python \+ TypeScript SDKs · v)(\d+\.\d+\.\d+)(\.\*\*)",
    ),
    (
        "docs/status/metrics/catalog.toml (project_version)",
        Path("docs/status/metrics/catalog.toml"),
        r'^(\s*\{ key = "project_version",.*?display_value = ")(\d+\.\d+\.\d+)(")',
    ),
    (
        "uv.lock (aragora)",
        Path("uv.lock"),
        r'^(name = "aragora"\nversion = ")(\d+\.\d+\.\d+)(")$',
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (PyPI availability wheel)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"(\*\*PyPI availability:\*\* the `)(\d+\.\d+\.\d+)(` wheel ships when the operator pushes)",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (PyPI availability tag)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"(wheel ships when the operator pushes the `v)(\d+\.\d+\.\d+)(` tag)",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (upgrade path headings)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"^(### v[\d.x]+ -> v)(\d+\.\d+\.\d+)( \((?:Minor|Major|Legacy) Upgrade\))$",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (pip install --upgrade)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"^(pip install --upgrade aragora==)(\d+\.\d+\.\d+)()$",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (legacy step 3 heading)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"^(# Step 3: Upgrade to v)(\d+\.\d+\.\d+)()$",
    ),
    (
        # Anchored on the step heading so the ``aragora==1.0.0`` steps stay untouched.
        "docs/deployment/UPGRADE_ROADMAP.md (legacy step 3 install)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r"^(# Step 3: Upgrade to v\d+\.\d+\.\d+\npip install aragora==)(\d+\.\d+\.\d+)()$",
    ),
    (
        "docs/deployment/UPGRADE_ROADMAP.md (backup labels)",
        Path("docs/deployment/UPGRADE_ROADMAP.md"),
        r'(--label "pre-upgrade-v)(\d+\.\d+\.\d+)(")',
    ),
    (
        "docs/reference/INSTALL_MATRIX.md (operator tag)",
        Path("docs/reference/INSTALL_MATRIX.md"),
        r"(build ships when the operator tags `v)(\d+\.\d+\.\d+)(`)",
    ),
    (
        "docs-site/docs/reference/install-matrix.md (operator tag)",
        Path("docs-site/docs/reference/install-matrix.md"),
        r"(build ships when the operator tags `v)(\d+\.\d+\.\d+)(`)",
    ),
    (
        "docs-site/docs/contributing/canonical-goals.md",
        Path("docs-site/docs/contributing/canonical-goals.md"),
        r"^(\|\s*Version\s*\|\s*)(\d+\.\d+\.\d+)(\s*\|.*)$",
    ),
    (
        "docs/migration/V3_MIGRATION_GUIDE.md (warnings emitted by)",
        Path("docs/migration/V3_MIGRATION_GUIDE.md"),
        r"^(> \*\*Deprecation warnings active since:\*\* v\d+\.\d+ \(still emitted by v)"
        r"(?P<series>\d+\.\d+)(\))$",
    ),
    (
        "CHANGELOG.md (Unreleased)",
        Path("CHANGELOG.md"),
        r"^(_Post-v)(\d+\.\d+\.\d+)( changes land here until the next stable tag\._)$",
    ),
    (
        "aragora/__version__.py (RELEASE_DATE comment)",
        Path("aragora/__version__.py"),
        r"(# Release date \(ISO 8601 format\) — set when the v)(\d+\.\d+\.\d+)( tag is pushed)",
    ),
]

# npm lockfiles carry the package version twice: at the top level and in the
# ``packages[""]`` root entry.  Both are rewritten line-by-line so ``--fix``
# produces exactly the two-line diff ``npm version`` would.
for _lockfile in (
    "aragora/live/package-lock.json",
    "sdk/typescript/package-lock.json",
    "ide/vscode-aragora/package-lock.json",
    "ide/vscode-aragora/webview-ui/package-lock.json",
):
    DOC_SOURCES.append(
        (f"{_lockfile} (root)", Path(_lockfile), r'^(  "version": ")(\d+\.\d+\.\d+)("),?$')
    )
    DOC_SOURCES.append(
        (
            f"{_lockfile} (packages root)",
            Path(_lockfile),
            r'^(    "": \{\n      "name": "[^"]+",\n      "version": ")(\d+\.\d+\.\d+)("),?$',
        )
    )

# ``aragora/live`` links the in-tree TypeScript SDK (``file:../../sdk/typescript``);
# npm records the linked package's version, which is the canonical version too.
DOC_SOURCES.append(
    (
        "aragora/live/package-lock.json (../../sdk/typescript link)",
        Path("aragora/live/package-lock.json"),
        r'^(    "\.\./\.\./sdk/typescript": \{\n      "name": "@aragora/sdk",\n      "version": ")'
        r'(\d+\.\d+\.\d+)("),?$',
    )
)

# Spots whose fix is not an in-place rewrite of the matched text.
DOC_FIXERS: dict[str, Callable[[Path, str, str, str | None], bool]] = {
    "docs/deployment/UPGRADE_ROADMAP.md (support matrix)": fix_support_matrix_row,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check version alignment across packages")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check only and exit 1 on any misalignment (the default mode)",
    )
    mode.add_argument("--fix", action="store_true", help="Auto-fix version mismatches")
    args = parser.parse_args()

    # Get canonical version
    try:
        canonical = get_canonical_version()
        print(f"Canonical version (aragora/__version__.py): {canonical}")
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    release_date = get_canonical_release_date()

    mismatches: list[tuple[str, str | None]] = []
    fixed: list[str] = []

    print("\nChecking version alignment:")
    print("-" * 50)

    for name, path, file_type in VERSION_SOURCES:
        if file_type == "pyproject":
            version = get_pyproject_version(path)
        else:
            version = get_package_json_version(path)

        if version is None:
            print(f"  {name}: (not found) [MISMATCH] - tracked manifest is missing")
            mismatches.append((name, None))
            continue

        status = "OK" if version == canonical else "MISMATCH"
        print(f"  {name}: {version} [{status}]")

        if version != canonical:
            mismatches.append((name, version))

            if args.fix:
                if file_type == "pyproject":
                    if fix_pyproject_version(path, canonical):
                        fixed.append(name)
                else:
                    if fix_package_json_version(path, canonical):
                        fixed.append(name)

    for name, path in PYTHON_VERSION_SOURCES:
        version = get_python_version(path)
        if version is None:
            print(f"  {name}: (not found) [MISMATCH] - tracked manifest is missing")
            mismatches.append((name, None))
            continue

        status = "OK" if version == canonical else "MISMATCH"
        print(f"  {name}: {version} [__version__] [{status}]")

        if version != canonical:
            mismatches.append((name, version))

            if args.fix:
                if fix_python_version(path, canonical):
                    fixed.append(name)

    for name, path, pattern in DOC_SOURCES:
        expected = _expected_version(pattern, canonical)
        versions = get_doc_versions(path, pattern)
        if not versions:
            # A dead entry is a hole in the tracked set, not an aligned spot.
            print(
                f"  {name}: (version not found) [doc] [MISMATCH] - tracked pattern matches nothing"
            )
            mismatches.append((name, None))
            continue

        stale = [v for v in versions if v != expected]
        stale_dates = (
            [d for d in get_doc_dates(path, pattern) if d != release_date] if release_date else []
        )
        version = stale[0] if stale else versions[0]
        status = "OK" if not stale and not stale_dates else "MISMATCH"
        suffix = f" ({len(versions)} occurrences)" if len(versions) > 1 else ""
        if stale_dates:
            suffix += f" (date {stale_dates[0]}, release date is {release_date})"
        print(f"  {name}: {version} [doc] [{status}]{suffix}")

        if stale or stale_dates:
            mismatches.append((name, version))

            if args.fix:
                fixer = DOC_FIXERS.get(name, fix_doc_version)
                if fixer(path, pattern, expected, release_date):
                    fixed.append(name)

    print("-" * 50)

    if fixed:
        print(f"\nFixed {len(fixed)} file(s):")
        for name in fixed:
            print(f"  - {name} -> {canonical}")

    if mismatches and not args.fix:
        print(f"\nERROR: {len(mismatches)} version mismatch(es) found!")
        print("Run with --fix to auto-fix, or manually update the files.")
        return 1

    if mismatches:
        remaining = len(mismatches) - len(fixed)
        if remaining > 0:
            print(f"\nWARNING: {remaining} mismatch(es) could not be fixed.")
            return 1

    print("\nAll versions aligned!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
