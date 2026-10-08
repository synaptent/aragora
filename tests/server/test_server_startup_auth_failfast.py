"""Startup-time fail-fast contract for token-less production server boots.

``AuthConfig.configure_from_env`` raises ``AuthenticationError`` when
``ARAGORA_ENV=production`` and ``ARAGORA_API_TOKEN`` is unset, but since the
``auth_config`` singleton went lazy (PEP 562) that raise fires on FIRST USE.
A real boot currently dies at import only because ``unified_server``'s
module-level stream imports happen to touch ``auth_config``. These subprocess
probes simulate that import graph going lazy (discard the incidentally
materialized singleton after import) and pin the explicit guarantee:

1. A token-less production boot raises ``AuthenticationError`` during the
   startup-validation region of ``run_unified_server``, before storage or any
   server component initializes.
2. Configured production boots and token-less dev boots are unaffected: they
   proceed past startup validation, observed via a deterministic storage-init
   canary (an un-creatable ``nomic_dir``) so no ports are bound and no
   components start.

Subprocess conventions follow ``tests/server/test_auth_lazy_init.py``:
cold interpreter, inherited env minus ``ARAGORA_*``, AWS neutralization.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Exit-code protocol for the boot probe below.
_EXIT_AUTH_FAILFAST = 0
_EXIT_REACHED_STORAGE_INIT = 3

_BOOT_PROBE = """
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Import in development mode so the incidental module-level
# `from aragora.server.auth import auth_config` chain (unified_server ->
# stream) materializes a benign singleton instead of raising at import.
os.environ["ARAGORA_ENV"] = "development"
os.environ.pop("ARAGORA_API_TOKEN", None)

import aragora.server.auth as auth_mod
import aragora.server.unified_server as us
from aragora.exceptions import AuthenticationError

# Simulate the import graph going lazy: drop any incidentally materialized
# singleton so only an explicit startup-validation materialization can
# re-create it (and re-run configure_from_env under the target env).
with auth_mod._auth_config_lock:
    auth_mod._auth_config = None

os.environ["ARAGORA_ENV"] = os.environ.pop("PROBE_TARGET_ENV")
probe_token = os.environ.pop("PROBE_TARGET_TOKEN", "")
if probe_token:
    os.environ["ARAGORA_API_TOKEN"] = probe_token

# Storage-init canary: a nomic_dir whose parent is a regular file makes
# run_unified_server raise RuntimeError("Cannot create nomic directory ...")
# immediately after its startup-validation region, before any component is
# constructed or any port is bound.
blocker = Path(tempfile.mkdtemp()) / "blocker"
blocker.write_text("not a directory")

try:
    asyncio.run(us.run_unified_server(nomic_dir=blocker / "nomic"))
except AuthenticationError:
    print("AUTH_FAILFAST_AT_STARTUP_VALIDATION")
    sys.exit(0)
except RuntimeError as exc:
    if "nomic directory" in str(exc):
        print("PASSED_STARTUP_VALIDATION_REACHED_STORAGE_INIT")
        sys.exit(3)
    raise
print("SERVER_RETURNED_UNEXPECTEDLY")
sys.exit(4)
"""


def _bootable_env(target_env: str, *, token: str = "") -> dict[str, str]:
    """Inherited env minus ``ARAGORA_*``, plus a config that passes validate_all.

    ``ARAGORA_ENCRYPTION_KEY``, ``ARAGORA_SINGLE_INSTANCE`` and the sqlite
    backend satisfy ``aragora.config.validator.validate_all``'s production
    error checks (which do not cover ``ARAGORA_API_TOKEN``), so the probe
    isolates the auth guarantee rather than tripping unrelated config errors.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARAGORA_")}
    env.update(
        {
            # Importing aragora.server without AWS neutralization can hit
            # botocore MFA getpass on this machine class.
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "ARAGORA_SECRETS_STRICT": "false",
            "ARAGORA_ENCRYPTION_KEY": "startup-probe-encryption-key",
            "ARAGORA_SINGLE_INSTANCE": "true",
            "ARAGORA_DB_BACKEND": "sqlite",
            "PROBE_TARGET_ENV": target_env,
        }
    )
    if token:
        env["PROBE_TARGET_TOKEN"] = token
    return env


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


class TestStartupAuthFailFast:
    """Cold-process proofs that the fail-fast guarantee is explicit."""

    def test_tokenless_production_boot_fails_during_startup_validation(self):
        proc = _run_probe(_bootable_env("production"))
        assert proc.returncode == _EXIT_AUTH_FAILFAST, (
            f"expected token-less production boot to raise AuthenticationError "
            f"during startup validation; rc={proc.returncode}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr[-2000:]}"
        )
        assert "AUTH_FAILFAST_AT_STARTUP_VALIDATION" in proc.stdout

    def test_configured_production_boot_passes_startup_validation(self):
        proc = _run_probe(_bootable_env("production", token="startup-probe-token"))
        assert proc.returncode == _EXIT_REACHED_STORAGE_INIT, (
            f"expected configured production boot to pass startup validation "
            f"and reach storage init; rc={proc.returncode}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr[-2000:]}"
        )
        assert "PASSED_STARTUP_VALIDATION_REACHED_STORAGE_INIT" in proc.stdout

    def test_tokenless_development_boot_passes_startup_validation(self):
        proc = _run_probe(_bootable_env("development"))
        assert proc.returncode == _EXIT_REACHED_STORAGE_INIT, (
            f"expected token-less development boot to pass startup validation "
            f"and reach storage init; rc={proc.returncode}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr[-2000:]}"
        )
        assert "PASSED_STARTUP_VALIDATION_REACHED_STORAGE_INIT" in proc.stdout
