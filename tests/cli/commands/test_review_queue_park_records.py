from __future__ import annotations

import pytest

from aragora.cli.commands.review_queue_park_records import current_head_park_record


HEAD_X = "a" * 40
HEAD_Y = "b" * 40


def _comment(
    body: str,
    *,
    created_at: str,
    author_association: str = "OWNER",
) -> dict[str, str]:
    return {
        "body": body,
        "createdAt": created_at,
        "authorAssociation": author_association,
        "url": f"https://github.example/comment/{created_at}",
    }


def test_current_head_repeat_blocker_survives_later_single_model_pass() -> None:
    comments = [
        _comment(
            f"""## Current-head repeat-blocker park

Exact head: `{HEAD_X}`

Gemini returned CHANGES-REQUESTED with [P2] findings.
Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:20:08Z",
        ),
        _comment(
            f"""## Model Review Evidence

PR: #9005
Exact head: `{HEAD_X}`
Verdict: PASS
Reviewer: OpenAI
""",
            created_at="2026-07-08T05:23:00Z",
        ),
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head repeat-blocker park"
    assert "Do not merge this PR on this head" in record["reason"]


def test_old_head_park_does_not_block_new_head() -> None:
    comments = [
        _comment(
            f"""## Current-head evidence blocker

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:07:24Z",
        )
    ]

    record = current_head_park_record(comments, head_sha=HEAD_Y)

    assert record["blocked"] is False


def test_later_trusted_structured_lift_clears_same_head_park() -> None:
    comments = [
        _comment(
            f"""## Evidence safety correction

Exact head: `{HEAD_X}`

Existing park remains authoritative. Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:24:26Z",
        ),
        _comment(
            f"""## Current-head park lift

Exact head: `{HEAD_X}`

I explicitly lift the current-head park for this head.
""",
            created_at="2026-07-08T05:30:00Z",
        ),
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is False
    assert record["lifted_by"]["created_at"] == "2026-07-08T05:30:00Z"


def test_untrusted_structured_lift_does_not_clear_park() -> None:
    comments = [
        _comment(
            f"""## Current-head repeat-blocker park

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:20:08Z",
        ),
        _comment(
            f"""## Current-head park lift

Exact head: `{HEAD_X}`

I explicitly lift the current-head park for this head.
""",
            created_at="2026-07-08T05:30:00Z",
            author_association="NONE",
        ),
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head repeat-blocker park"


def test_rejected_lift_prose_does_not_clear_park() -> None:
    comments = [
        _comment(
            f"""## Current-head evidence blocker

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:20:08Z",
        ),
        _comment(
            f"""## Current-head park lift request rejected

Exact head: `{HEAD_X}`

The park lift request is rejected; the current-head park remains in force.
""",
            created_at="2026-07-08T05:30:00Z",
        ),
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head evidence blocker"


def test_same_comment_park_and_lift_keeps_park_authoritative() -> None:
    comments = [
        _comment(
            f"""## Current-head repeat-blocker park

Exact head: `{HEAD_X}`

Do not merge this PR on this head.

## Current-head park lift

This same comment also says to lift the park, which must not self-cancel.
""",
            created_at="2026-07-08T05:20:08Z",
        )
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head repeat-blocker park"


def test_naive_comment_timestamps_sort_with_aware_timestamps() -> None:
    comments = [
        _comment(
            f"""## Current-head repeat-blocker park

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:20:08",
        ),
        _comment(
            f"""## Current-head park lift

Exact head: `{HEAD_X}`

I explicitly lift the current-head park for this head.
""",
            created_at="2026-07-08T05:30:00Z",
        ),
    ]

    try:
        record = current_head_park_record(comments, head_sha=HEAD_X)
    except TypeError as exc:  # pragma: no cover - guards the regression message.
        pytest.fail(f"naive and aware timestamps should be comparable: {exc}")

    assert record["blocked"] is False
