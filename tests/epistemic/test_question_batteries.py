"""Tests for shared epistemic question batteries (#8815)."""

from __future__ import annotations

from aragora.epistemic.question_batteries import (
    BATTERY_NAMES,
    build_intake_battery_questions,
    get_question_battery,
)


def test_named_batteries_are_available() -> None:
    assert BATTERY_NAMES == (
        "outsider",
        "falsifier",
        "assumption_surfacer",
        "deleter",
        "stranger_test",
        "moat_audit",
    )
    falsifier = get_question_battery("falsifier")
    assert "wrong" in falsifier.question.lower() or "falsif" in falsifier.question.lower()
    assert falsifier.persona_role == "Falsifier"


def test_intake_battery_prioritizes_vague_product_prompts() -> None:
    questions = build_intake_battery_questions(
        "Make our product better for enterprise customers", max_questions=4
    )
    texts = [q.question for q in questions]

    assert any("need from me" in text.lower() for text in texts)
    assert any("would make this wrong" in text.lower() for text in texts)
    assert any("assum" in text.lower() for text in texts)
    assert any("should this be done" in text.lower() for text in texts)


def test_intake_battery_does_not_flood_specific_prompts() -> None:
    questions = build_intake_battery_questions(
        "In /tmp/app.py line 14, replace timeout=30 with timeout=60 and update "
        "tests/test_config.py::test_timeout_default.",
        max_questions=4,
    )
    assert questions == []
