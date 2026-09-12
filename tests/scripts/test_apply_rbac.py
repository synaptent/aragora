"""Regression tests for scripts/apply_rbac.py exclusion semantics."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.apply_rbac as apply_rbac

HANDLER_ROOT = PROJECT_ROOT / "aragora" / "server" / "handlers"

# Handler name outside EXCLUDED_HANDLERS so path rules alone decide the outcome.
NON_EXCLUDED_FUNCTION = "handle_example"

# Directory rules exclude whole subtrees; every other exclusion is one exact file,
# spelled relative to the handlers root.
EXPECTED_DIRECTORY_RULES = {
    "admin/health/",
}

EXPECTED_EXACT_EXCLUDED_FILES = {
    "admin/health_utils.py",
    "agents/probes.py",
    "auth/signup_handlers.py",
    "auth/sso_handlers.py",
    "_oauth/oidc.py",
    "oauth/oauth_wizard.py",
    "webhook_management.py",
    "features/email_webhooks.py",
    "base.py",
    "_oauth/base.py",
    "bots/base.py",
    "social/slack/commands/base.py",
    "utils/database.py",
    "interface.py",
    "types.py",
    "utils/decorators.py",
    "api_decorators.py",
    "utils/auth_mixins.py",
    "utils/lazy_stores.py",
    "social/tts_helper.py",
    "auth/store.py",
    "features/marketplace/store.py",
    "openclaw/store.py",
    "explainability_store.py",
}


def _audit_visible_files() -> list[str]:
    """Handler files the RBAC audit enumerates, relative to the handlers root."""
    files = []
    for py_file in HANDLER_ROOT.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        files.append(py_file.relative_to(HANDLER_ROOT).as_posix())
    return sorted(files)


def test_substring_near_misses_are_not_excluded() -> None:
    """A rule for one file must not swallow other files that merely end the same way."""
    near_misses = [
        "aragora/server/handlers/rebase.py",
        "aragora/server/handlers/prototypes.py",
        "aragora/server/handlers/restore.py",
        "aragora/server/handlers/social/telegram/webhooks.py",
        "aragora/server/handlers/social/whatsapp/webhooks.py",
    ]
    for path in near_misses:
        assert not apply_rbac.is_excluded(path, NON_EXCLUDED_FUNCTION), path


def test_path_rules_only_apply_to_handler_tree_paths() -> None:
    """Files outside the handlers tree never match handler path rules."""
    assert not apply_rbac.is_excluded("aragora/other/base.py", NON_EXCLUDED_FUNCTION)
    assert not apply_rbac.is_excluded("base.py", NON_EXCLUDED_FUNCTION)


def test_exact_entries_match_across_path_spellings() -> None:
    """Repo-relative, audit-relative, and absolute spellings all resolve the same."""
    spellings = [
        "aragora/server/handlers/base.py",
        "server/handlers/base.py",
        str(HANDLER_ROOT / "base.py"),
    ]
    for path in spellings:
        assert apply_rbac.is_excluded(path, NON_EXCLUDED_FUNCTION), path


def test_directory_rule_excludes_whole_subtree() -> None:
    """Directory entries end with a slash and cover every file beneath them."""
    assert apply_rbac.is_excluded(
        "aragora/server/handlers/admin/health/database.py", NON_EXCLUDED_FUNCTION
    )
    assert apply_rbac.is_excluded(
        "aragora/server/handlers/admin/health/probes.py", NON_EXCLUDED_FUNCTION
    )
    assert not apply_rbac.is_excluded(
        "aragora/server/handlers/admin/health_dashboard.py", NON_EXCLUDED_FUNCTION
    )


def test_excluded_handler_names_still_apply_anywhere() -> None:
    """External-callback receivers stay excluded by handler name, not by path."""
    receiver = "aragora/server/handlers/social/telegram/webhooks.py"
    assert apply_rbac.is_excluded(receiver, "handle_webhook")
    assert not apply_rbac.is_excluded(receiver, NON_EXCLUDED_FUNCTION)


def test_every_path_rule_points_at_a_real_path() -> None:
    """Every entry names a real file or directory under the handlers root."""
    for entry in apply_rbac.EXCLUDED_PATHS:
        target = HANDLER_ROOT / entry
        if entry.endswith("/"):
            assert target.is_dir(), entry
        else:
            assert target.is_file(), entry


def test_effective_exclusion_set_is_pinned() -> None:
    """The exclusion rules resolve to exactly the pinned file set over the live tree."""
    for rel in sorted(EXPECTED_EXACT_EXCLUDED_FILES):
        assert (HANDLER_ROOT / rel).is_file(), rel

    visible = _audit_visible_files()
    actual_excluded = {
        rel
        for rel in visible
        if apply_rbac.is_excluded(f"aragora/server/handlers/{rel}", NON_EXCLUDED_FUNCTION)
    }
    expected_excluded = EXPECTED_EXACT_EXCLUDED_FILES | {
        rel for rel in visible if any(rel.startswith(rule) for rule in EXPECTED_DIRECTORY_RULES)
    }
    assert actual_excluded == expected_excluded
