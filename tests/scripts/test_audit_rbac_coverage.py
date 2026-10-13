"""Regression tests for scripts/audit_rbac_coverage.py exclusion semantics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.audit_rbac_coverage as audit_rbac_coverage

HANDLER_ROOT = PROJECT_ROOT / "aragora" / "server" / "handlers"

# The effective exclusion sets the substring-era rules resolved to over the
# live tree, now pinned as exact handlers-root-relative paths. The four
# substring rules that matched nothing (/saml.py, /auth_flow.py, /callback.py,
# /oauth_providers/) were dropped: every remaining entry must name a real path.
EXPECTED_STORAGE_EXCLUDED_FILES = {
    "_oauth/utils.py",
    "admin/health/database_utils.py",
    "admin/health/diagnostics.py",
    "admin/health/probes.py",
    "admin/health/stores.py",
    "agents/probes.py",
    "auth/store.py",
    "codebase/security/storage.py",
    "debates/diagnostics.py",
    "email/categorization.py",
    "email/storage.py",
    "features/marketplace/store.py",
    "gauntlet/storage.py",
    "openclaw/store.py",
    "shared_inbox/storage.py",
    "utils/params.py",
}

EXPECTED_AUTH_FLOW_FILES = {
    "_oauth/oidc.py",
    "auth/login.py",
    "auth/password.py",
    "auth/signup_handlers.py",
    "auth/sso_handlers.py",
    "bots/slack/oauth.py",
    "bots/teams/oauth.py",
    "email/oauth.py",
}


def _audit_visible_files() -> list[str]:
    """Handler files the RBAC audit enumerates, relative to the handlers root."""
    return sorted(
        py_file.relative_to(HANDLER_ROOT).as_posix()
        for py_file in audit_rbac_coverage.iter_handler_files(HANDLER_ROOT)
    )


def test_substring_near_misses_are_not_excluded() -> None:
    """A rule for one file must not swallow same-named files elsewhere in the tree."""
    near_misses = [
        # Basename matches at un-pinned locations: substring-era rules
        # excluded these anywhere; exact-path rules must not.
        "aragora/server/handlers/newfeature/store.py",
        "aragora/server/handlers/inbox/storage.py",
        "aragora/server/handlers/social/probes.py",
        # Suffix near-miss: ends the same way but is a different file.
        "aragora/server/handlers/auth/backing_store.py",
    ]
    for path in near_misses:
        assert not audit_rbac_coverage.is_storage_path(path), path

    auth_near_misses = [
        "aragora/server/handlers/social/oauth.py",
        "aragora/server/handlers/features/login.py",
        # Dropped zero-match rules must not resurrect by name anywhere.
        "aragora/server/handlers/auth/callback.py",
        "aragora/server/handlers/auth/saml.py",
    ]
    for path in auth_near_misses:
        assert not audit_rbac_coverage.is_auth_flow_path(path), path


def test_path_rules_only_apply_to_handler_tree_paths() -> None:
    """Files outside the handlers tree never match handler path rules."""
    assert not audit_rbac_coverage.is_storage_path("aragora/other/auth/store.py")
    assert not audit_rbac_coverage.is_storage_path("store.py")
    assert not audit_rbac_coverage.is_auth_flow_path("aragora/other/auth/login.py")
    assert not audit_rbac_coverage.is_auth_flow_path("login.py")


def test_exact_entries_match_across_path_spellings() -> None:
    """Repo-relative, audit-relative, and absolute spellings all resolve the same."""
    storage_spellings = [
        "aragora/server/handlers/auth/store.py",
        "server/handlers/auth/store.py",
        str(HANDLER_ROOT / "auth" / "store.py"),
    ]
    for path in storage_spellings:
        assert audit_rbac_coverage.is_storage_path(path), path

    auth_spellings = [
        "aragora/server/handlers/auth/login.py",
        "server/handlers/auth/login.py",
        str(HANDLER_ROOT / "auth" / "login.py"),
    ]
    for path in auth_spellings:
        assert audit_rbac_coverage.is_auth_flow_path(path), path


def test_directory_rules_exclude_whole_subtree() -> None:
    """Slash-terminated entries cover every file beneath them; siblings stay out."""
    rules = frozenset({"admin/health/"})
    assert audit_rbac_coverage._matches_exclusion_rules(
        "aragora/server/handlers/admin/health/database.py", rules
    )
    assert audit_rbac_coverage._matches_exclusion_rules(
        "aragora/server/handlers/admin/health/nested/deep.py", rules
    )
    assert not audit_rbac_coverage._matches_exclusion_rules(
        "aragora/server/handlers/admin/health_dashboard.py", rules
    )


def test_every_path_rule_points_at_a_real_path() -> None:
    """Every entry names a real file or directory under the handlers root."""
    for entry in audit_rbac_coverage.STORAGE_EXCLUDED_PATHS | audit_rbac_coverage.AUTH_FLOW_PATHS:
        target = HANDLER_ROOT / entry
        if entry.endswith("/"):
            assert target.is_dir(), entry
        else:
            assert target.is_file(), entry


def test_storage_and_auth_flow_groups_are_disjoint() -> None:
    """One file cannot be both denominator-excluded and auth-flow-protected."""
    overlap = audit_rbac_coverage.STORAGE_EXCLUDED_PATHS & audit_rbac_coverage.AUTH_FLOW_PATHS
    assert overlap == frozenset()


def test_effective_exclusion_sets_are_pinned() -> None:
    """The rules resolve to exactly the pinned file sets over the live tree."""
    for rel in sorted(EXPECTED_STORAGE_EXCLUDED_FILES | EXPECTED_AUTH_FLOW_FILES):
        assert (HANDLER_ROOT / rel).is_file(), rel

    visible = _audit_visible_files()
    actual_storage = {
        rel
        for rel in visible
        if audit_rbac_coverage.is_storage_path(f"aragora/server/handlers/{rel}")
    }
    actual_auth_flow = {
        rel
        for rel in visible
        if audit_rbac_coverage.is_auth_flow_path(f"aragora/server/handlers/{rel}")
    }
    assert actual_storage == EXPECTED_STORAGE_EXCLUDED_FILES
    assert actual_auth_flow == EXPECTED_AUTH_FLOW_FILES


def test_marker_less_tree_is_audited_with_exclusions_disabled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tree whose path lacks the handlers-root marker audits fail-open, and says so."""
    copy_root = tmp_path / "handlers_copy"
    (copy_root / "auth").mkdir(parents=True)
    (copy_root / "auth" / "store.py").write_text("def get_data():\n    return None\n")

    handlers = audit_rbac_coverage.find_handlers(copy_root)

    captured = capsys.readouterr()
    assert audit_rbac_coverage._HANDLER_PATH_MARKER in captured.err
    # Exclusions are disabled, so the storage file is audited rather than skipped.
    assert [handler.function for handler in handlers] == ["get_data"]


def test_marker_bearing_tree_keeps_exclusions_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same file under a marker-bearing root stays excluded, with no warning."""
    handlers_root = tmp_path / "server" / "handlers"
    (handlers_root / "auth").mkdir(parents=True)
    (handlers_root / "auth" / "store.py").write_text("def get_data():\n    return None\n")

    handlers = audit_rbac_coverage.find_handlers(handlers_root)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert handlers == []
