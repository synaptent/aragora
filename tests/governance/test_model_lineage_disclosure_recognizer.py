"""Governance tests for strict lineage-bound reviewer identity parsing."""

from __future__ import annotations

from aragora.cli.commands.review_queue import _resolve_model_review_identity


def _body(
    heading: str,
    *,
    model_family: str | None = None,
    model_id: str = "gpt-5.5",
    receipt: str | None = "/tmp/review.md",
) -> str:
    text = f"## {heading}\n\n"
    text += "**Reviewer harness:** factory\n"
    if model_family is not None:
        text += f"**Model family:** {model_family}\n"
    text += f"**Model id:** {model_id}\n"
    if receipt is not None:
        text += f"**Receipt artifact:** {receipt}\n"
    text += "\nNo blocking findings.\n"
    return text


def test_router_heading_requires_model_family_disclosure() -> None:
    identity = _resolve_model_review_identity(_body("Factory focused dogfood"))

    assert identity.surface_reviewer_id == "factory"
    assert identity.model_family == ""
    assert "missing_model_family_disclosure" in identity.identity_problems


def test_router_heading_with_canonical_family_counts_by_model_family() -> None:
    identity = _resolve_model_review_identity(
        _body("Factory focused dogfood", model_family="openai", model_id="gpt-5.5")
    )

    assert identity.surface_reviewer_id == "factory"
    assert identity.model_family == "openai"
    assert identity.model_id == "gpt-5.5"
    assert identity.identity_source == "model_family_metadata"


def test_new_direct_family_heading_requires_complete_identity_metadata() -> None:
    identity = _resolve_model_review_identity(
        "## Claude independent semantic review on head abc1234\n\nNo findings.\n"
    )

    assert identity.surface_reviewer_id == "claude"
    assert identity.model_family == "claude"
    assert identity.identity_source == "direct_heading"
    assert "missing_model_family_disclosure" in identity.identity_problems
    assert "missing_reviewer_harness" in identity.identity_problems
    assert "missing_model_id" in identity.identity_problems
    assert "missing_receipt_artifact" in identity.identity_problems


def test_transition_direct_family_heading_is_counted_but_flagged() -> None:
    identity = _resolve_model_review_identity(
        "## Claude independent semantic review on head abc1234\n\nNo findings.\n",
        allow_lineage_transition=True,
    )

    assert identity.model_family == "claude"
    assert identity.lineage_undisclosed is True
    assert identity.lineage_transition_receipt
    assert identity.identity_problems == ("lineage_undisclosed",)


def test_direct_heading_conflicting_model_family_is_rejected() -> None:
    identity = _resolve_model_review_identity(
        _body("Claude independent semantic review", model_family="openai", model_id="gpt-5.5")
    )

    assert identity.surface_reviewer_id == "claude"
    assert identity.model_family == "openai"
    assert "heading_model_family_conflict" in identity.identity_problems


def test_unknown_model_family_is_reported() -> None:
    identity = _resolve_model_review_identity(
        _body("Factory independent semantic review", model_family="not-a-family")
    )

    assert identity.surface_reviewer_id == "factory"
    assert identity.model_family == ""
    assert "unknown_model_family" in identity.identity_problems


def test_body_only_metadata_does_not_override_unknown_heading() -> None:
    identity = _resolve_model_review_identity(
        "## Aragora Code Review\n\n"
        "**Reviewer harness:** factory\n"
        "**Model family:** openai\n"
        "**Model id:** gpt-5.5\n"
        "**Receipt artifact:** /tmp/review.md\n"
    )

    assert identity.surface_reviewer_id == "unknown_model_reviewer"
    assert identity.model_family == "openai"
    assert "unknown_surface_reviewer" in identity.identity_problems


def test_fenced_metadata_does_not_override_nearby_block() -> None:
    identity = _resolve_model_review_identity(
        "## Factory independent semantic review\n\n"
        "```md\n"
        "**Model family:** openai\n"
        "```\n"
        "No structured metadata outside the example block.\n"
    )

    assert identity.surface_reviewer_id == "factory"
    assert identity.model_family == ""
    assert "missing_model_family_disclosure" in identity.identity_problems


def test_later_heading_metadata_does_not_override_first_heading() -> None:
    identity = _resolve_model_review_identity(
        "## Factory independent semantic review\n\n"
        "No metadata near the first heading.\n\n"
        "## Claude follow-up\n\n"
        "**Model family:** claude\n"
        "**Model id:** claude-opus-4-7\n"
        "**Receipt artifact:** /tmp/review.md\n"
    )

    assert identity.surface_reviewer_id == "factory"
    assert identity.model_family == ""
    assert "missing_model_family_disclosure" in identity.identity_problems
