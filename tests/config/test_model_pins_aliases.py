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
        # Re-pinned by the 2026-09-04 frontier-model-refresh: grok-4.6
        # supersedes grok-4.5 as the devil's-advocate frontier.
        assert model_pins.GROK_4_VIA_OPENROUTER == "x-ai/grok-4.6"


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


class TestPinsDerivedFromCatalog:
    """Frontier-model-refresh (2026-09-04): pins are derived from
    ``aragora.models.catalog.CATALOG`` instead of hand-copied literals, and
    every role is re-pinned to the current per-family frontier."""

    def test_pins_come_from_catalog(self) -> None:
        from aragora.models.catalog import CATALOG

        assert model_pins.FABLE_51_DIRECT == CATALOG["claude-fable-5-1"].direct_id
        assert model_pins.FABLE_51_VIA_OPENROUTER == CATALOG["claude-fable-5-1"].openrouter_id
        assert model_pins.GPT6_ASTRA_DIRECT == "gpt-6-astra"
        assert model_pins.GEMINI_31_PRO_DIRECT == "gemini-3.1-pro-preview"  # real Gemini API code
        assert model_pins.GROK_46_DIRECT == "grok-4.6"
        assert model_pins.GROK_46_VIA_OPENROUTER == "x-ai/grok-4.6"

    def test_legacy_constant_names_still_exported(self) -> None:
        for name in (
            "OPUS_4_7",
            "GPT_5_4",
            "GEMINI_3_1_PRO",
            "FABLE_5_DIRECT",
            "GPT56_SOL_DIRECT",
            "GPT55_DIRECT",
            "GROK_4_DIRECT",
        ):
            assert hasattr(model_pins, name), name

    def test_every_role_pins_fable_or_astra_or_family_frontier(self) -> None:
        for role in (
            "proposer",
            "critic",
            "synthesizer",
            "quality_reviewer",
            "security_auditor",
            "compliance_auditor",
            "judge",
            "default",
        ):
            assert model_pins.direct_model_for_role(role) == "claude-fable-5-1", role
        assert model_pins.direct_model_for_role("reviewer") == "gpt-6-astra"
        assert model_pins.direct_model_for_role("devils_advocate") == "grok-4.6"
        assert model_pins.direct_model_for_role("researcher") == "gemini-3.1-pro-preview"
        assert model_pins.openrouter_alias_for_role("reviewer") == "openai/gpt-6-astra"
