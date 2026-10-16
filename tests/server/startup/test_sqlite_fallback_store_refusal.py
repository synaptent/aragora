"""Startup initializers when the production storage guard refuses their store.

In production with a SQLite backend, ``require_distributed_store`` raises
``aragora.storage.production_guards.DistributedStateError`` for the job queue
store and the governance store. With ``ARAGORA_ALLOW_SQLITE_FALLBACK``
explicitly enabled, the four sequential-path initializers that open those
stores skip their step instead of aborting startup. Without the flag, for a
refusal of any other store, and for any other error (including the unrelated
leader-election ``DistributedStateError``), the error propagates unchanged.
Skipping approval recovery never grants an approval: runtime approval checks
still fail closed while the governance store is refused.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.rbac.models import AuthorizationContext
from aragora.resilience.leader import DistributedStateError as LeaderDistributedStateError
from aragora.server.middleware import approval_gate
from aragora.server.startup import workers as startup_workers
from aragora.server.startup.security import init_approval_gate_recovery
from aragora.server.startup.workers import (
    init_durable_job_queue_recovery,
    init_gauntlet_worker,
    init_testfixer_worker,
)
from aragora.storage import job_queue_store, production_guards
from aragora.storage.governance.factory import reset_governance_store

_JOB_STORE = "job_queue_store"
_GOVERNANCE_STORE = "governance_store"

# site -> (initializer, value returned when the step is skipped, refused store,
#          patch target for the call that opens the store)
_SITES: dict[str, tuple[Any, Any, str, str]] = {
    "durable_job_queue_recovery": (
        init_durable_job_queue_recovery,
        0,
        _JOB_STORE,
        "aragora.server.workers.gauntlet_worker.recover_interrupted_gauntlets",
    ),
    "gauntlet_worker": (
        init_gauntlet_worker,
        False,
        _JOB_STORE,
        "aragora.server.workers.gauntlet_worker.GauntletWorker",
    ),
    "testfixer_worker": (
        init_testfixer_worker,
        False,
        _JOB_STORE,
        "aragora.nomic.testfixer.queue_worker.TestFixerWorker",
    ),
    "approval_gate_recovery": (
        init_approval_gate_recovery,
        0,
        _GOVERNANCE_STORE,
        "aragora.server.middleware.approval_gate.recover_pending_approvals",
    ),
}
_SITE_IDS = sorted(_SITES)

# Parsed like validate_storage_backend (aragora/server/startup/validation.py)
# and create_persistent_store (aragora/storage/connection_factory.py).
_FLAG_ENABLED = ["true", "1", "TRUE"]
_FLAG_NOT_ENABLED = [None, "", "false", "0", "yes"]


@pytest.fixture
def production_sqlite(monkeypatch, tmp_path):
    """Production with SQLite stores and the guard at its default (enforcing)."""
    for key in (
        "ARAGORA_REQUIRE_DISTRIBUTED",
        "ARAGORA_REQUIRE_DISTRIBUTED_STATE",
        "ARAGORA_ALLOW_SQLITE_FALLBACK",
        "ARAGORA_JOB_STORE_BACKEND",
        "ARAGORA_JOB_BACKEND",
        "ARAGORA_GOVERNANCE_STORE_BACKEND",
        "ARAGORA_DURABLE_GAUNTLET",
        "ARAGORA_TESTFIXER_WORKER",
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "SUPABASE_URL",
        "SUPABASE_POSTGRES_DSN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARAGORA_ENV", "production")
    monkeypatch.setenv("ARAGORA_DB_BACKEND", "sqlite")
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(production_guards, "_config", None)
    monkeypatch.setattr(startup_workers, "_gauntlet_worker", None)
    monkeypatch.setattr(startup_workers, "_testfixer_worker", None)
    monkeypatch.setattr(approval_gate, "_pending_approvals", {})
    job_queue_store.reset_job_store()
    reset_governance_store()
    yield tmp_path
    job_queue_store.reset_job_store()
    reset_governance_store()


def _enforce_guard_in_this_test(monkeypatch) -> None:
    # require_distributed_store waives the guard whenever PYTEST_CURRENT_TEST is
    # set, and pytest sets it again at the start of every phase, so a fixture
    # cannot clear it for the call phase.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def _set_flag(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("ARAGORA_ALLOW_SQLITE_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_ALLOW_SQLITE_FALLBACK", value)


@pytest.mark.parametrize("flag", _FLAG_ENABLED)
@pytest.mark.parametrize("site", _SITE_IDS)
async def test_guard_refusal_with_fallback_flag_skips_the_step(
    site, flag, production_sqlite, monkeypatch, caplog
):
    initializer, skipped, store, _ = _SITES[site]
    _set_flag(monkeypatch, flag)
    _enforce_guard_in_this_test(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="aragora.server.startup"):
        result = await initializer()

    assert result == skipped and type(result) is type(skipped)
    assert startup_workers.get_gauntlet_worker() is None
    assert startup_workers.get_testfixer_worker() is None
    assert any(
        record.levelno == logging.WARNING
        and store in record.getMessage()
        and "ARAGORA_ALLOW_SQLITE_FALLBACK" in record.getMessage()
        for record in caplog.records
    ), [record.getMessage() for record in caplog.records]


@pytest.mark.parametrize("flag", _FLAG_NOT_ENABLED)
@pytest.mark.parametrize("site", _SITE_IDS)
async def test_guard_refusal_without_fallback_flag_propagates(
    site, flag, production_sqlite, monkeypatch
):
    initializer, _, store, _ = _SITES[site]
    _set_flag(monkeypatch, flag)
    _enforce_guard_in_this_test(monkeypatch)

    with pytest.raises(production_guards.DistributedStateError) as raised:
        await initializer()

    assert raised.value.store_name == store
    assert startup_workers.get_gauntlet_worker() is None
    assert startup_workers.get_testfixer_worker() is None


class _UnexpectedStartupError(Exception):
    pass


def _other_store_refusal(store: str) -> Exception:
    other = _GOVERNANCE_STORE if store == _JOB_STORE else _JOB_STORE
    return production_guards.DistributedStateError(other, "refused")


_UNHANDLED_ERRORS = {
    "other_store_guard_refusal": _other_store_refusal,
    "leader_distributed_state_error": lambda store: LeaderDistributedStateError(store, "no redis"),
    "unexpected_error": lambda store: _UnexpectedStartupError(store),
}


@pytest.mark.parametrize("error", sorted(_UNHANDLED_ERRORS))
@pytest.mark.parametrize("site", _SITE_IDS)
async def test_other_errors_propagate_with_fallback_flag(site, error, monkeypatch):
    initializer, _, store, target = _SITES[site]
    monkeypatch.setenv("ARAGORA_ALLOW_SQLITE_FALLBACK", "true")
    monkeypatch.delenv("ARAGORA_DURABLE_GAUNTLET", raising=False)
    monkeypatch.delenv("ARAGORA_TESTFIXER_WORKER", raising=False)
    exc = _UNHANDLED_ERRORS[error](store)

    with patch(target, MagicMock(side_effect=exc)):
        with pytest.raises(type(exc)) as raised:
            await initializer()

    assert raised.value is exc


async def test_runtime_approval_fails_closed_after_skipped_recovery(production_sqlite, monkeypatch):
    monkeypatch.setenv("ARAGORA_ALLOW_SQLITE_FALLBACK", "true")
    _enforce_guard_in_this_test(monkeypatch)
    assert await init_approval_gate_recovery() == 0

    executed: list[str] = []

    @approval_gate.require_approval(operation="test.sensitive", checklist=["confirmed"])
    async def sensitive_operation(auth_context: AuthorizationContext) -> str:
        executed.append(auth_context.user_id)
        return "executed"

    requester = AuthorizationContext(user_id="requester", roles={"member"})

    with pytest.raises(production_guards.DistributedStateError) as refused:
        await sensitive_operation(auth_context=requester)
    assert refused.value.store_name == _GOVERNANCE_STORE

    with pytest.raises(production_guards.DistributedStateError):
        await sensitive_operation(auth_context=requester, _approval_id="never-recorded")

    # The request that could not be persisted cannot be approved and used either.
    (pending_id,) = list(approval_gate._pending_approvals)
    with pytest.raises(production_guards.DistributedStateError):
        await approval_gate.resolve_approval(
            pending_id, approved=True, approver_id="admin", checklist_status={"confirmed": True}
        )
    with pytest.raises(production_guards.DistributedStateError):
        await sensitive_operation(auth_context=requester, _approval_id=pending_id)

    assert executed == []
