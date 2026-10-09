"""Startup prerequisite validation parity between the two init paths.

``UnifiedServer.start()`` boots through ``parallel_init`` by default
(``ARAGORA_PARALLEL_INIT`` unset) and through ``run_startup_sequence`` only
when parallel init is disabled. The sequential path validates configuration
(Phase 1) and production requirements (Phase 2) before initializing any
component; these subprocess probes pin that the default parallel path applies
the same checks with the same outcome:

1. A production boot missing a non-auth prerequisite
   (``ARAGORA_REQUIRE_DATABASE=true`` without ``DATABASE_URL``) enters degraded
   mode with ``DATABASE_UNAVAILABLE`` before any component initializes, on
   both paths.
2. Under ``ARAGORA_STRICT_STARTUP`` the same boot raises during startup
   validation on both paths.
3. Configured production boots and development boots are unaffected: both
   paths reach component initialization without entering degraded mode.
4. The production recipe used by ``.github/workflows/deploy-secure.yml``
   (sqlite backend, no ``ARAGORA_ALLOW_SQLITE_FALLBACK``) still reaches
   component initialization on the default parallel path; the storage-backend
   check is not part of the parallel path's startup validation.

Each probe drives the real ``UnifiedServer.start`` on an instance built
without ``__init__`` and replaces the component-initialization entry points
(``parallel_init`` and ``_init_all_components``) and the post-startup handler
initialization with canaries, so no component starts and no port is bound.

Subprocess conventions follow ``tests/server/test_server_startup_auth_failfast.py``:
cold interpreter, inherited env minus ``ARAGORA_*``, AWS neutralization.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Exit-code protocol for the boot probe below.
_EXIT_DEGRADED_AT_STARTUP_VALIDATION = 0
_EXIT_REACHED_COMPONENT_INIT = 3
_EXIT_PASSED_STARTUP_WITHOUT_DEGRADED = 4
_EXIT_STARTUP_VALIDATION_RAISED = 5

_BOOT_PROBE = """
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Import in development mode so module-level imports in the server package
# (for example the auth_config singleton) never see the target environment.
os.environ["ARAGORA_ENV"] = "development"

import aragora.server.startup as startup_mod
import aragora.server.unified_server as us
from aragora.server import degraded_mode

os.environ["ARAGORA_ENV"] = os.environ.pop("PROBE_TARGET_ENV")
use_parallel_init = os.environ.pop("PROBE_PARALLEL_INIT") == "true"


class ReachedComponentInit(Exception):
    pass


class PassedStartupSequence(Exception):
    pass


async def _component_init_canary(*args, **kwargs):
    raise ReachedComponentInit


def _post_startup_canary(*args, **kwargs):
    raise PassedStartupSequence


# start() imports parallel_init from the package at call time and
# run_startup_sequence resolves _init_all_components as a module global, so
# patching the package attributes intercepts both paths' component init.
startup_mod.parallel_init = _component_init_canary
startup_mod._init_all_components = _component_init_canary
# A degraded boot skips component init; stop it at the first post-startup
# step, before any server or port is started.
us.UnifiedHandler._init_handlers = staticmethod(_post_startup_canary)

server = object.__new__(us.UnifiedServer)
server.nomic_dir = Path(os.environ["ARAGORA_DATA_DIR"])
server.stream_server = SimpleNamespace(emitter=None)

try:
    asyncio.run(server.start(use_parallel_init=use_parallel_init))
except ReachedComponentInit:
    if degraded_mode.is_degraded():
        print("DEGRADED_BUT_REACHED_COMPONENT_INIT")
        sys.exit(6)
    print("REACHED_COMPONENT_INIT")
    sys.exit(3)
except PassedStartupSequence:
    state = degraded_mode.get_degraded_state()
    if state.is_degraded:
        code = state.error_code.value if state.error_code else "NONE"
        print(f"DEGRADED_AT_STARTUP_VALIDATION code={code}")
        sys.exit(0)
    print("PASSED_STARTUP_WITHOUT_DEGRADED")
    sys.exit(4)
except RuntimeError as exc:
    print(f"STARTUP_VALIDATION_RAISED: {exc}")
    sys.exit(5)
print("SERVER_RETURNED_UNEXPECTEDLY")
sys.exit(7)
"""

_PATHS = pytest.mark.parametrize("parallel_init", [True, False], ids=["parallel", "sequential"])


def _probe_env(
    target_env: str,
    *,
    parallel_init: bool,
    data_dir: Path,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Inherited env minus ``ARAGORA_*`` and backend URLs, plus probe settings.

    ``ARAGORA_USE_SECRETS_MANAGER=false`` keeps production-mode config lookups
    off AWS, and ``ARAGORA_AUTO_MIGRATE_ON_STARTUP=false`` keeps the sequential
    reference run from migrating databases (migrations are not a validation
    phase and the parallel path never runs them).
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("ARAGORA_") and k not in ("DATABASE_URL", "REDIS_URL")
    }
    env.update(
        {
            # Importing aragora.server without AWS neutralization can hit
            # botocore MFA getpass on this machine class.
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "ARAGORA_SECRETS_STRICT": "false",
            "ARAGORA_USE_SECRETS_MANAGER": "false",
            "ARAGORA_AUTO_MIGRATE_ON_STARTUP": "false",
            "ARAGORA_DATA_DIR": str(data_dir),
            "PROBE_TARGET_ENV": target_env,
            "PROBE_PARALLEL_INIT": "true" if parallel_init else "false",
        }
    )
    if extra:
        env.update(extra)
    return env


# Passes every production check that can degrade or abort a graceful boot.
_CONFIGURED_PRODUCTION = {
    "ARAGORA_ENCRYPTION_KEY": "startup-probe-encryption-key",
    "ARAGORA_API_TOKEN": "startup-probe-api-token",
    "ARAGORA_SINGLE_INSTANCE": "true",
    "ARAGORA_DB_BACKEND": "sqlite",
    "ARAGORA_ALLOW_SQLITE_FALLBACK": "true",
}

# Configured production plus a missing non-auth hard requirement.
_PRODUCTION_MISSING_DATABASE_URL = {
    **_CONFIGURED_PRODUCTION,
    "ARAGORA_REQUIRE_DATABASE": "true",
}

# Production settings written by .github/workflows/deploy-secure.yml.
_DEPLOY_SECURE_PRODUCTION = {
    "ARAGORA_ENCRYPTION_KEY": "startup-probe-encryption-key",
    "ARAGORA_API_TOKEN": "startup-probe-api-token",
    "ARAGORA_SINGLE_INSTANCE": "true",
    "ARAGORA_DB_BACKEND": "sqlite",
    "ARAGORA_SECRETS_STRICT": "false",
}


def _run_probe(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BOOT_PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _describe(proc: subprocess.CompletedProcess[str]) -> str:
    return f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr[-2000:]}"


class TestStartupPrereqParity:
    """Cold-process proofs that both init paths validate prerequisites alike."""

    @_PATHS
    def test_production_missing_non_auth_prereq_degrades_before_component_init(
        self, parallel_init: bool, tmp_path: Path
    ):
        proc = _run_probe(
            _probe_env(
                "production",
                parallel_init=parallel_init,
                data_dir=tmp_path,
                extra=_PRODUCTION_MISSING_DATABASE_URL,
            )
        )
        assert proc.returncode == _EXIT_DEGRADED_AT_STARTUP_VALIDATION, (
            "expected a production boot with ARAGORA_REQUIRE_DATABASE=true and no "
            "DATABASE_URL to enter degraded mode during startup validation, before "
            f"component init; {_describe(proc)}"
        )
        assert "DEGRADED_AT_STARTUP_VALIDATION code=DATABASE_UNAVAILABLE" in proc.stdout

    @_PATHS
    def test_strict_production_missing_non_auth_prereq_raises_during_startup_validation(
        self, parallel_init: bool, tmp_path: Path
    ):
        proc = _run_probe(
            _probe_env(
                "production",
                parallel_init=parallel_init,
                data_dir=tmp_path,
                extra={**_PRODUCTION_MISSING_DATABASE_URL, "ARAGORA_STRICT_STARTUP": "true"},
            )
        )
        assert proc.returncode == _EXIT_STARTUP_VALIDATION_RAISED, (
            "expected a strict production boot without DATABASE_URL to raise during "
            f"startup validation; {_describe(proc)}"
        )
        assert "DATABASE_URL" in proc.stdout

    @_PATHS
    def test_configured_production_boot_reaches_component_init(
        self, parallel_init: bool, tmp_path: Path
    ):
        proc = _run_probe(
            _probe_env(
                "production",
                parallel_init=parallel_init,
                data_dir=tmp_path,
                extra=_CONFIGURED_PRODUCTION,
            )
        )
        assert proc.returncode == _EXIT_REACHED_COMPONENT_INIT, (
            "expected a configured production boot to pass startup validation and "
            f"reach component init; {_describe(proc)}"
        )

    @_PATHS
    def test_development_boot_reaches_component_init(self, parallel_init: bool, tmp_path: Path):
        proc = _run_probe(_probe_env("development", parallel_init=parallel_init, data_dir=tmp_path))
        assert proc.returncode == _EXIT_REACHED_COMPONENT_INIT, (
            "expected a development boot to pass startup validation and reach "
            f"component init; {_describe(proc)}"
        )

    def test_deploy_secure_production_recipe_reaches_component_init_on_parallel_path(
        self, tmp_path: Path
    ):
        proc = _run_probe(
            _probe_env(
                "production",
                parallel_init=True,
                data_dir=tmp_path,
                extra=_DEPLOY_SECURE_PRODUCTION,
            )
        )
        assert proc.returncode == _EXIT_REACHED_COMPONENT_INIT, (
            "expected the deploy-secure production recipe (sqlite backend without "
            "ARAGORA_ALLOW_SQLITE_FALLBACK) to keep reaching component init on the "
            f"default parallel path; {_describe(proc)}"
        )
