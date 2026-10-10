"""Keep real WeasyPrint PDF renders out of the pytest process.

Gotcha this module exists to prevent
====================================

WeasyPrint 68.0-69.0 ``FontConfiguration.__init__`` (``weasyprint/text/fonts.py``)
calls ``FcConfigDestroy()`` on its ``FcConfig`` and also leaves an
``ffi.gc(..., FcConfigDestroy)`` destructor attached, so the config is released
twice. Upstream fixed it in 70.0 (Kozea/WeasyPrint@98778130c9). Once a
``FontConfiguration`` is garbage-collected, ``pango_fc_font_map_finalize()``
writes into freed memory. Inside a pytest worker that corrupts unrelated CPython
allocations, usually several tests after the render: a dataclass ``__init__``
compiled without its ``_dflt_metadata`` cell (``NameError: cannot access free
variable '_dflt_metadata'``) or a segfault in ``dataclasses``. CI does not
install WeasyPrint, so only local runs are exposed.

Every render constructs a ``FontConfiguration``, so:

* a test about the no-WeasyPrint fallback calls :func:`hide_weasyprint`;
* a test that needs a real render runs it through :func:`run_weasyprint_child`,
  which detaches the redundant destructor inside a throwaway interpreter;
* a module-level autouse fixture calling :func:`refuse_in_process_render` turns
  an accidental in-process render into a test failure instead of heap damage.

Usage::

    from tests.utils.weasyprint_isolation import refuse_in_process_render

    @pytest.fixture(autouse=True)
    def _no_in_process_weasyprint_render(monkeypatch):
        refuse_in_process_render(monkeypatch)
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Prepended to every child script. A no-op where WeasyPrint is missing (the code
# under test then takes its fallback path) or is outside the affected versions.
_CHILD_PRELUDE = """\
try:
    import weasyprint as _wp
    from weasyprint.text import fonts as _wp_fonts
except (ImportError, OSError):
    pass
else:
    if 68 <= int(_wp.__version__.split(".")[0]) < 70:
        _wp_init = _wp_fonts.FontConfiguration.__init__

        def _wp_init_without_double_release(self, *args, **kwargs):
            _wp_init(self, *args, **kwargs)
            _wp_fonts.ffi.gc(self._config, None)

        _wp_fonts.FontConfiguration.__init__ = _wp_init_without_double_release
"""


def hide_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import weasyprint`` raise ``ImportError`` until the test ends.

    ``monkeypatch`` restores an already-imported real module afterwards. Deleting
    it from ``sys.modules`` instead would force a second native initialisation.
    """
    monkeypatch.setitem(sys.modules, "weasyprint", None)


def refuse_in_process_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any real WeasyPrint render in this process until the test ends.

    A no-op where WeasyPrint is not importable, as in CI.
    """
    try:
        from weasyprint.text import fonts
    except (ImportError, OSError):
        return

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "render real WeasyPrint PDFs with "
            "tests.utils.weasyprint_isolation.run_weasyprint_child, not in the pytest process"
        )

    monkeypatch.setattr(fonts.FontConfiguration, "__init__", _refuse)


def run_weasyprint_child(
    script: str,
    *,
    stdin: bytes = b"",
    args: Sequence[str] = (),
    timeout: float = 120,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``script`` in a child interpreter at the repo root and assert it exits 0.

    The child renders with real WeasyPrint when it is installed, minus the
    redundant destructor. ``script`` is dedented, so it can be an indented literal.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_PRELUDE + textwrap.dedent(script), *args],
        input=stdin,
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=timeout,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc
