"""Tests for the aragora.server.redis_config deprecation shim.

The Redis connection-pool surface moved down to aragora.utils.redis_config
during the P4a layering work so foundation modules (aragora.utils.redis_cache)
can reach it without importing aragora.server. The old module must remain
importable as a shim that:

1. Emits a DeprecationWarning on import naming the old and new paths.
2. Re-exports every public name identity-equal to its canonical target in
   aragora.utils.redis_config (same objects, shared module-level pool/availability
   state -- not copies).
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path

import pytest

SHIM_MODULE = "aragora.server.redis_config"
CANONICAL_MODULE = "aragora.utils.redis_config"

# Public API the shim must preserve (aragora.utils.redis_config.__all__).
PUBLIC_NAMES = [
    "get_redis_url",
    "get_redis_pool",
    "get_redis_client",
    "get_async_redis_client",
    "is_redis_available",
    "close_redis_pool",
    "reset_redis_state",
]


def _fresh_import_shim():
    """Import the shim module fresh so import-time warnings re-fire."""
    sys.modules.pop(SHIM_MODULE, None)
    return importlib.import_module(SHIM_MODULE)


class TestDeprecationWarning:
    def test_import_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _fresh_import_shim()

        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "importing aragora.server.redis_config must emit DeprecationWarning"
        message = str(deprecations[0].message)
        assert "aragora.server.redis_config" in message
        assert "aragora.utils.redis_config" in message

    def test_cached_reimport_does_not_rewarn(self):
        """A second (cached) import must not re-emit the warning."""
        _fresh_import_shim()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.import_module(SHIM_MODULE)

        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert not deprecations


class TestReExportIdentity:
    @pytest.fixture()
    def modules(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            shim = _fresh_import_shim()
        canonical = importlib.import_module(CANONICAL_MODULE)
        return shim, canonical

    @pytest.mark.parametrize("name", PUBLIC_NAMES)
    def test_public_name_identity(self, modules, name):
        shim, canonical = modules
        assert getattr(shim, name) is getattr(canonical, name)

    def test_all_matches_public_names(self, modules):
        shim, _ = modules
        assert sorted(shim.__all__) == sorted(PUBLIC_NAMES)

    def test_state_reset_is_shared(self, modules):
        """reset_redis_state via the shim must clear the canonical module's state."""
        shim, canonical = modules
        canonical._redis_available = True
        canonical._redis_pool = object()
        shim.reset_redis_state()
        assert canonical._redis_available is None
        assert canonical._redis_pool is None


_REPO_ROOT = Path(__file__).resolve().parents[2]

# The shim warns once per interpreter at its own import time, so an in-process
# probe would be masked by module caching from earlier tests; each probe runs
# the consumer in a fresh interpreter and counts shim warnings there.
_PROBE_TEMPLATE = """\
import warnings

with warnings.catch_warnings(record=True) as _caught:
    warnings.simplefilter("always")
__BODY__

_shim_warnings = [
    w
    for w in _caught
    if issubclass(w.category, DeprecationWarning)
    and "aragora.server.redis_config" in str(w.message)
]
print("SHIM_WARNINGS=%d" % len(_shim_warnings))
"""


def _run_shim_warning_probe(body: str) -> int:
    """Run *body* in a fresh interpreter and count shim DeprecationWarnings."""
    env = os.environ.copy()
    # aragora.server imports probe AWS secrets at import time; neutralize so
    # the probe is hermetic on machines with real AWS configuration.
    env["AWS_CONFIG_FILE"] = "/dev/null"
    env["AWS_SHARED_CREDENTIALS_FILE"] = "/dev/null"
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    env["ARAGORA_QUOTA_REDIS_ENABLED"] = "true"
    for var in (
        "ARAGORA_REQUIRE_DISTRIBUTED",
        "ARAGORA_REQUIRE_DISTRIBUTED_STATE",
        "ARAGORA_MULTI_INSTANCE",
        "ARAGORA_ENV",
    ):
        env.pop(var, None)
    code = _PROBE_TEMPLATE.replace(
        "__BODY__", textwrap.indent(textwrap.dedent(body).strip(), "    ")
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        f"probe failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    match = re.search(r"SHIM_WARNINGS=(\d+)", result.stdout)
    assert match, f"probe emitted no marker\nstdout={result.stdout}\nstderr={result.stderr}"
    return int(match.group(1))


class TestConsumersUseCanonicalPath:
    """Repointed tier-1/2 consumers must not touch the deprecated shim.

    Covers import time (module-level importers) and call time (function-level
    importers) for every consumer repointed to aragora.utils.redis_config.
    """

    def test_pubsub_import_chain_emits_no_shim_warning(self):
        assert _run_shim_warning_probe("import aragora.server.pubsub") == 0

    def test_checkpoint_compat_import_emits_no_shim_warning(self):
        assert _run_shim_warning_probe("import aragora.workflow.checkpoints._compat") == 0

    def test_redis_limiter_get_redis_client_emits_no_shim_warning(self):
        body = """
        from aragora.server.middleware.rate_limit import redis_limiter

        redis_limiter.get_redis_client()
        """
        assert _run_shim_warning_probe(body) == 0

    def test_get_session_store_emits_no_shim_warning(self):
        body = """
        from aragora.server import session_store

        session_store.reset_session_store()
        session_store.get_session_store()
        session_store.reset_session_store()
        """
        assert _run_shim_warning_probe(body) == 0

    def test_shutdown_close_redis_phase_emits_no_shim_warning(self):
        body = """
        import asyncio

        from aragora.server.shutdown_sequence import ShutdownPhaseBuilder, ShutdownSequence

        sequence = ShutdownSequence()
        ShutdownPhaseBuilder(server=None)._phase_close_connection_pools(sequence)
        phase = next(p for p in sequence._phases if p.name == "Close Redis pool")
        asyncio.run(phase.execute())
        """
        assert _run_shim_warning_probe(body) == 0

    def test_quota_persistence_get_redis_emits_no_shim_warning(self):
        body = """
        import asyncio
        import inspect

        from aragora.tenancy.quota_persistence import QuotaPersistence

        async def _probe():
            client = await QuotaPersistence()._get_redis()
            if client is not None:
                closer = getattr(client, "aclose", None) or getattr(client, "close", None)
                if closer is not None:
                    result = closer()
                    if inspect.isawaitable(result):
                        await result

        asyncio.run(_probe())
        """
        assert _run_shim_warning_probe(body) == 0


class TestRbacAndHandlerConsumersUseCanonicalPath:
    """Repointed rbac/ and server-handler consumers must not touch the shim.

    Same fresh-interpreter call-time probe pattern as
    TestConsumersUseCanonicalPath; every remaining consumer here imports the
    Redis helpers lazily inside a method, so each probe exercises the actual
    call path rather than mere module import.
    """

    def test_quota_enforcer_get_redis_emits_no_shim_warning(self):
        body = """
        from aragora.rbac.quotas import QuotaEnforcer

        QuotaEnforcer(enable_persistence=False)._get_redis()
        """
        assert _run_shim_warning_probe(body) == 0

    def test_break_glass_get_redis_emits_no_shim_warning(self):
        body = """
        from aragora.rbac.emergency import BreakGlassAccess

        BreakGlassAccess(enable_persistence=False)._get_redis()
        """
        assert _run_shim_warning_probe(body) == 0

    def test_batch_store_explicit_redis_backend_emits_no_shim_warning(self):
        body = """
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARAGORA_EXPLAINABILITY_STORE_BACKEND"] = "redis"
            os.environ["ARAGORA_EXPLAINABILITY_DB"] = os.path.join(tmp, "probe.db")
            from aragora.server.handlers.explainability_store import (
                get_batch_job_store,
                reset_batch_job_store,
            )

            reset_batch_job_store()
            get_batch_job_store()
            reset_batch_job_store()
        """
        assert _run_shim_warning_probe(body) == 0

    def test_batch_store_default_backend_emits_no_shim_warning(self):
        body = """
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            os.environ.pop("ARAGORA_EXPLAINABILITY_STORE_BACKEND", None)
            os.environ["ARAGORA_EXPLAINABILITY_DB"] = os.path.join(tmp, "probe.db")
            from aragora.server.handlers.explainability_store import (
                get_batch_job_store,
                reset_batch_job_store,
            )

            reset_batch_job_store()
            get_batch_job_store()
            reset_batch_job_store()
        """
        assert _run_shim_warning_probe(body) == 0

    def test_status_page_redis_health_emits_no_shim_warning(self):
        body = """
        from aragora.server.handlers.public.status_page import StatusPageHandler

        StatusPageHandler()._check_redis_health()
        """
        assert _run_shim_warning_probe(body) == 0
