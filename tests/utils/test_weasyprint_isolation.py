"""Tests for tests/utils/weasyprint_isolation.py."""

from __future__ import annotations

import importlib
import sys

import pytest

from tests.utils.weasyprint_isolation import (
    hide_weasyprint,
    refuse_in_process_render,
    run_weasyprint_child,
)

_MISSING = object()


def _weasyprint_fonts():
    try:
        from weasyprint.text import fonts
    except (ImportError, OSError):
        pytest.skip("WeasyPrint native dependencies unavailable")
    return fonts


def test_hide_weasyprint_blocks_import_until_undo():
    before = sys.modules.get("weasyprint", _MISSING)

    with pytest.MonkeyPatch.context() as mp:
        hide_weasyprint(mp)
        with pytest.raises(ImportError):
            importlib.import_module("weasyprint")

    assert sys.modules.get("weasyprint", _MISSING) is before


def test_refuse_in_process_render_blocks_font_configuration_until_undo():
    fonts = _weasyprint_fonts()
    original_init = fonts.FontConfiguration.__init__

    with pytest.MonkeyPatch.context() as mp:
        refuse_in_process_render(mp)
        with pytest.raises(AssertionError, match="run_weasyprint_child"):
            fonts.FontConfiguration()

    assert fonts.FontConfiguration.__init__ is original_init


def test_run_weasyprint_child_renders_real_pdf():
    _weasyprint_fonts()

    proc = run_weasyprint_child(
        """
        import gc, sys, weasyprint
        pdfs = [weasyprint.HTML(string="<p>receipt</p>").write_pdf() for _ in range(3)]
        gc.collect()
        sys.stdout.buffer.write(pdfs[-1])
        """
    )

    assert proc.stdout[:4] == b"%PDF"


def test_run_weasyprint_child_passes_stdin_and_args():
    proc = run_weasyprint_child(
        "import sys; sys.stdout.write(sys.stdin.read() + sys.argv[1])",
        stdin=b"in:",
        args=["arg"],
    )

    assert proc.stdout == b"in:arg"


def test_run_weasyprint_child_reports_child_failure():
    with pytest.raises(AssertionError, match="child boom"):
        run_weasyprint_child("raise RuntimeError('child boom')")
