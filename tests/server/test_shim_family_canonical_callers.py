"""First-party callers use the canonical homes of the API-error, distributed-state, pool-loop and debate-storage shims."""

from __future__ import annotations

import ast
import importlib
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEGACY_IMPORTS = frozenset(
    {
        "aragora.server.errors",
        "aragora.control_plane.leader.is_distributed_state_required",
        "aragora.storage.pool_manager.get_pool_event_loop",
        "aragora.server.storage",
    }
)

MIGRATED_CALLERS = (
    "aragora/cli/commands/status.py",
    "aragora/control_plane/scheduler.py",
    "aragora/control_plane/shared_state.py",
    "aragora/integrations/email_reply_loop.py",
    "aragora/rbac/cache.py",
    "aragora/server/debate_origin/registry.py",
    "aragora/server/handler_registry/core.py",
    "aragora/server/handlers/admin/health/kubernetes.py",
    "aragora/server/handlers/admin/health/probes.py",
    "aragora/server/handlers/analytics_dashboard/_shared.py",
    "aragora/server/handlers/auth/handler.py",
    "aragora/server/handlers/auth/signup_handlers.py",
    "aragora/server/handlers/auth/sso_handlers.py",
    "aragora/server/handlers/base.py",
    "aragora/server/handlers/bots/slack/events.py",
    "aragora/server/handlers/bots/slack/interactions.py",
    "aragora/server/handlers/catalog/template_marketplace.py",
    "aragora/server/handlers/debates/auditing.py",
    "aragora/server/handlers/debates/critique.py",
    "aragora/server/handlers/debates/moments.py",
    "aragora/server/handlers/evolution/genesis.py",
    "aragora/server/handlers/features/audio.py",
    "aragora/server/handlers/features/broadcast.py",
    "aragora/server/handlers/integrations/cloud_storage.py",
    "aragora/server/handlers/integrations/integration_management.py",
    "aragora/server/handlers/payments/billing.py",
    "aragora/server/handlers/social/_slack_impl/config.py",
    "aragora/server/handlers/social/_slack_impl/events.py",
    "aragora/server/handlers/social/_slack_impl/interactive.py",
    "aragora/server/handlers/social/relationship.py",
    "aragora/server/handlers/social/social_media.py",
    "aragora/server/handlers/utils/responses.py",
    "aragora/server/middleware/abac.py",
    "aragora/server/middleware/approval_gate.py",
    "aragora/server/middleware/exception_handler.py",
    "aragora/server/middleware/token_revocation.py",
    "aragora/server/session_store.py",
    "aragora/server/startup/__init__.py",
    "aragora/server/startup/parallel.py",
    "aragora/server/stream/__init__.py",
    "aragora/server/stream/arena_hooks.py",
)


def _imported_names(relative_path: str) -> set[str]:
    """Absolute import targets plus module-path string constants (lazy import maps)."""
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("aragora."):
                imported.add(node.value)
    return imported


@pytest.mark.parametrize("relative_path", MIGRATED_CALLERS)
def test_caller_does_not_import_legacy_shim(relative_path: str) -> None:
    assert not (_imported_names(relative_path) & LEGACY_IMPORTS)


@pytest.mark.parametrize(
    ("module_name", "attribute", "canonical_module", "canonical_attribute"),
    [
        (
            "aragora.control_plane.scheduler",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.control_plane.shared_state",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.integrations.email_reply_loop",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.server.debate_origin.registry",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.server.session_store",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.server.middleware.exception_handler",
            "safe_error_message",
            "aragora.api_errors",
            "safe_error_message",
        ),
        (
            "aragora.server.stream.arena_hooks",
            "_safe_error_message",
            "aragora.api_errors",
            "safe_error_message",
        ),
        (
            "aragora.server.stream",
            "_safe_error_message",
            "aragora.api_errors",
            "safe_error_message",
        ),
        (
            "aragora.rbac.cache",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.server.handlers.catalog.template_marketplace",
            "is_distributed_state_required",
            "aragora.config.distributed",
            "is_distributed_state_required",
        ),
        (
            "aragora.server.handlers.base",
            "safe_error_message",
            "aragora.api_errors",
            "safe_error_message",
        ),
        (
            "aragora.server.handlers.utils.responses",
            "ErrorCode",
            "aragora.api_errors",
            "ErrorCode",
        ),
        (
            "aragora.server.handlers.social.relationship",
            "_safe_error_message",
            "aragora.api_errors",
            "safe_error_message",
        ),
        (
            "aragora.server.handlers.auth.sso_handlers",
            "safe_error_message",
            "aragora.api_errors",
            "safe_error_message",
        ),
    ],
)
def test_module_level_caller_binds_canonical_object(
    module_name: str, attribute: str, canonical_module: str, canonical_attribute: str
) -> None:
    caller = importlib.import_module(module_name)
    canonical = importlib.import_module(canonical_module)

    assert getattr(caller, attribute) is getattr(canonical, canonical_attribute)


def test_revocation_store_lookup_emits_no_distributed_state_shim_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.server.middleware import token_revocation

    monkeypatch.setattr(token_revocation, "_revocation_store", None)
    with patch.dict("os.environ", {}, clear=True):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            store = token_revocation.get_revocation_store()

    assert isinstance(store, token_revocation.InMemoryRevocationStore)
    shim_warnings = [
        str(w.message)
        for w in caught
        if "aragora.control_plane.leader.is_distributed_state_required is deprecated"
        in str(w.message)
    ]
    assert not shim_warnings, shim_warnings
