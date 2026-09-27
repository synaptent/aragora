"""Tests for aragora.utils.env.preserve_environ.

Regression coverage for #8277: the official ``rlm`` package calls
``dotenv.load_dotenv()`` at import time, which under pytest-xdist workers
resolves from the current working directory upward and can inject a
repository ``.env`` (e.g. ARAGORA_SECRETS_STRICT=true) into ``os.environ``
process-wide. ``preserve_environ`` wraps such imports so any environment
mutation is rolled back.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from aragora.utils.env import preserve_environ


def test_added_keys_are_removed() -> None:
    key = "PRESERVE_ENVIRON_TEST_ADDED"
    assert key not in os.environ
    with preserve_environ():
        os.environ[key] = "injected"
    assert key not in os.environ


def test_changed_keys_are_restored(monkeypatch) -> None:
    key = "PRESERVE_ENVIRON_TEST_CHANGED"
    monkeypatch.setenv(key, "original")
    with preserve_environ():
        os.environ[key] = "mutated"
    assert os.environ[key] == "original"


def test_deleted_keys_are_restored(monkeypatch) -> None:
    key = "PRESERVE_ENVIRON_TEST_DELETED"
    monkeypatch.setenv(key, "original")
    with preserve_environ():
        del os.environ[key]
    assert os.environ[key] == "original"


def test_restores_on_exception() -> None:
    key = "PRESERVE_ENVIRON_TEST_EXC"
    assert key not in os.environ
    try:
        with preserve_environ():
            os.environ[key] = "injected"
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert key not in os.environ


def test_untouched_environment_is_unchanged() -> None:
    before = dict(os.environ)
    with preserve_environ():
        pass
    assert dict(os.environ) == before


_SENTINEL = "ARAGORA_TEST_DOTENV_SENTINEL_8277"


def _probe(module: str, cwd, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # python -c gives __main__ no __file__, so python-dotenv's find_dotenv()
    # treats the process as interactive and searches from cwd upward —
    # the same condition pytest-xdist execnet workers run under.
    code = f"import {module}, os; print('LEAK::' + os.environ.get('{_SENTINEL}', '<unset>'))"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_bridge_import_does_not_inject_repo_dotenv(tmp_path) -> None:
    """Guard the import *site*, not just the utility (#8277 regression).

    The utility tests above pass even if the ``preserve_environ()`` wrapper is
    dropped from aragora/rlm/bridge.py again (the original fix commit sat
    stranded on an unmerged branch for a month while believed merged). This
    test reproduces the real failure mode end to end.
    """
    # Guarded: a bare importorskip("rlm") would itself run rlm's load_dotenv()
    # side effect and pollute this xdist worker's environ — the exact failure
    # mode this test exists to prevent (review P2 on #9319).
    with preserve_environ():
        pytest.importorskip("rlm")
    (tmp_path / ".env").write_text(f"{_SENTINEL}=leaked\n")
    env = {k: v for k, v in os.environ.items() if k != _SENTINEL}

    # Pin the subprocess to the tree under test: an editable install's .pth
    # may otherwise resolve `aragora` to a different checkout.
    import aragora

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(aragora.__file__)))
    env["PYTHONPATH"] = os.pathsep.join(p for p in (repo_root, env.get("PYTHONPATH")) if p)

    # Control: prove the official rlm package still injects dotenv from cwd
    # under these conditions; otherwise the main assertion proves nothing.
    control = _probe("rlm.clients", tmp_path, env)
    if "LEAK::leaked" not in control.stdout:
        pytest.skip("rlm import no longer injects dotenv from cwd; nothing to guard against")

    result = _probe("aragora.rlm.bridge", tmp_path, env)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "LEAK::<unset>" in result.stdout, (
        "repo .env leaked into os.environ via aragora.rlm.bridge import; "
        "is the preserve_environ() guard still wrapping the official-rlm import?"
    )


def test_import_rlm_guarded_returns_cached_module(monkeypatch) -> None:
    """An already-imported rlm is returned as-is via the import machinery."""
    import types

    from aragora.utils import env as env_mod

    sentinel_module = types.ModuleType("rlm")
    monkeypatch.setitem(sys.modules, "rlm", sentinel_module)
    assert env_mod.import_rlm_guarded() is sentinel_module


def test_import_rlm_guarded_serializes_concurrent_first_calls(monkeypatch) -> None:
    """Concurrent first-calls must run the guarded import exactly once (review
    P2 on #9319: interleaved preserve_environ restores can persist pollution)."""
    import threading
    from contextlib import contextmanager

    from aragora.utils import env as env_mod

    monkeypatch.delitem(sys.modules, "rlm", raising=False)
    guard_entries = []
    real_guard = env_mod.preserve_environ

    @contextmanager
    def counting_guard():
        guard_entries.append(threading.get_ident())
        with real_guard():
            yield

    monkeypatch.setattr(env_mod, "preserve_environ", counting_guard)

    results: list[object] = []

    def call():
        try:
            results.append(env_mod.import_rlm_guarded())
        except ImportError:
            results.append(ImportError)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    if ImportError in results:
        # rlm not installed: every thread got ImportError, never a partial
        # module, and guard entries never interleaved (lock serializes).
        assert all(r is ImportError for r in results)
    else:
        # rlm installed: all threads share the identical module object.
        assert all(r is results[0] for r in results)
    # Every call passes through the guard under the lock — entries are
    # strictly sequential, one per call that reached the import.
    assert len(guard_entries) == len(results)
