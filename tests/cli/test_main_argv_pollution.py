"""Regression tests for ``aragora.__main__`` ``sys.argv`` pollution (#9239).

Before the fix, ``python -m aragora doctor …`` mutated ``sys.argv`` in place
and never restored it. Under pytest-xdist this caused cross-test leaks in any
worker that transitively imported and invoked the module-level dispatcher.

These tests pin the contract:

* the ``doctor`` branch still receives an argv *without* the ``doctor`` token,
* the process-wide ``sys.argv`` is restored to exactly its pre-call value on
  both normal return and ``SystemExit`` propagation,
* the non-``doctor`` branch never rewrites ``sys.argv``.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _restore_sys_argv():
    """Guard against test-local ``sys.argv`` mutation leaking to sibling tests."""
    saved = list(sys.argv)
    try:
        yield
    finally:
        sys.argv = saved


def _import_dispatch_main():
    """Import ``aragora.__main__.main`` fresh so patching is deterministic."""
    import aragora.__main__ as pkg_main  # intentional local import

    return pkg_main


def test_doctor_dispatch_does_not_leak_sys_argv():
    """``sys.argv`` must be identical after the doctor branch runs."""
    original = ["aragora", "doctor", "--validate-keys"]
    sys.argv = list(original)

    with patch("aragora.cli.doctor.main", return_value=0) as doctor_main:
        with pytest.raises(SystemExit) as exc:
            _import_dispatch_main().main()

    assert exc.value.code == 0
    # The doctor sub-CLI must have seen argv WITHOUT the "doctor" token…
    #
    # We inspected ``sys.argv`` from inside the mock by reading it before the
    # ``finally`` restores it.
    doctor_main.assert_called_once()
    # …and the caller's sys.argv is untouched.
    assert sys.argv == original


def test_doctor_dispatch_restores_argv_on_doctor_exception():
    """A raising ``doctor.main`` must still trigger the ``finally`` restore."""
    original = ["aragora", "doctor"]
    sys.argv = list(original)

    class _Boom(RuntimeError):
        pass

    with patch("aragora.cli.doctor.main", side_effect=_Boom("boom")):
        with pytest.raises(_Boom):
            _import_dispatch_main().main()

    assert sys.argv == original


def test_doctor_dispatch_hides_doctor_token_from_inner_cli():
    """The doctor sub-CLI must observe argv[1:] without the ``doctor`` token."""
    sys.argv = ["aragora", "doctor", "--fast"]

    seen = {}

    def _capture(*_args, **_kwargs):
        seen["argv"] = list(sys.argv)
        return 0

    with patch("aragora.cli.doctor.main", side_effect=_capture):
        with pytest.raises(SystemExit):
            _import_dispatch_main().main()

    # Inside the doctor branch: no "doctor" token, remaining args preserved.
    assert seen["argv"] == ["aragora", "--fast"]


def test_non_doctor_path_never_mutates_sys_argv():
    """Non-doctor commands must not touch ``sys.argv``."""
    original = ["aragora", "stats"]
    sys.argv = list(original)

    with patch("aragora.cli.main.main", return_value=0) as cli_main:
        _import_dispatch_main().main()

    cli_main.assert_called_once()
    assert sys.argv == original


def test_bare_invocation_never_mutates_sys_argv():
    """``python -m aragora`` with no args must not mutate ``sys.argv``."""
    original = ["aragora"]
    sys.argv = list(original)

    with patch("aragora.cli.main.main", return_value=0):
        _import_dispatch_main().main()

    assert sys.argv == original
