"""Canonical-metrics + legacy alias coverage for ``aragora.config.model_pins``.

The security gate ``security.model_pins.frontier_aligned`` (see
``scripts/check_canonical_metrics.py``) verifies that the underscored
frontier names ``OPUS_4_8`` / ``OPUS_4_7`` / ``GPT_5_4`` / ``GEMINI_3_1_PRO`` are
exported alongside the ``*_DIRECT`` constants. These tests pin that
contract so it can't silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

from aragora.config import model_pins


class TestUnderscoredAliasesExist:
    def test_opus_4_8_is_module_attribute(self) -> None:
        assert hasattr(model_pins, "OPUS_4_8")

    def test_opus_4_7_is_module_attribute(self) -> None:
        assert hasattr(model_pins, "OPUS_4_7")

    def test_gpt_5_4_is_module_attribute(self) -> None:
        assert hasattr(model_pins, "GPT_5_4")

    def test_gemini_3_1_pro_is_module_attribute(self) -> None:
        assert hasattr(model_pins, "GEMINI_3_1_PRO")


class TestAliasesMatchFrontier:
    def test_opus_4_8_matches_direct(self) -> None:
        assert model_pins.OPUS_4_8 == model_pins.OPUS_48_DIRECT

    def test_opus_4_7_matches_direct(self) -> None:
        assert model_pins.OPUS_4_7 == model_pins.OPUS_47_DIRECT

    def test_gpt_5_4_matches_direct(self) -> None:
        assert model_pins.GPT_5_4 == model_pins.GPT55_DIRECT

    def test_gemini_3_1_pro_matches_direct(self) -> None:
        assert model_pins.GEMINI_3_1_PRO == model_pins.GEMINI_31_PRO_DIRECT

    def test_grok_openrouter_pin_uses_live_soaked_frontier(self) -> None:
        assert model_pins.GROK_4_VIA_OPENROUTER == "x-ai/grok-4.5"


class TestAliasesInAll:
    def test_all_includes_three_aliases(self) -> None:
        required = {"OPUS_4_8", "OPUS_4_7", "GPT_5_4", "GEMINI_3_1_PRO"}
        assert required <= set(model_pins.__all__)


class TestCanonicalMetricsRegex:
    """Mirror the exact regex that ``check_canonical_metrics.py`` uses
    so we catch regressions in module-level binding form (not just
    presence in ``__all__``)."""

    def _matches(self, name: str) -> bool:
        text = Path(model_pins.__file__).read_text(encoding="utf-8")
        return bool(re.search(rf"^\s*{name}\s*[:=]", text, re.MULTILINE))

    def test_check_regex_matches_opus_4_8(self) -> None:
        assert self._matches("OPUS_4_8")

    def test_check_regex_matches_opus_4_7(self) -> None:
        assert self._matches("OPUS_4_7")

    def test_check_regex_matches_gpt_5_4(self) -> None:
        assert self._matches("GPT_5_4")

    def test_check_regex_matches_gemini_3_1_pro(self) -> None:
        assert self._matches("GEMINI_3_1_PRO")
