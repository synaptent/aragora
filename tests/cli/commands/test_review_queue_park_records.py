from __future__ import annotations

import re
from pathlib import Path

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


def test_untrusted_author_park_does_not_block() -> None:
    comments = [
        _comment(
            f"""## Current-head repeat-blocker park

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:20:08Z",
            author_association="NONE",
        )
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is False


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_maintainer_park_blocks(association: str) -> None:
    comments = [
        _comment(
            f"""## Current-head evidence blocker

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
""",
            created_at="2026-07-08T05:07:24Z",
            author_association=association,
        )
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head evidence blocker"


def test_park_marker_in_prose_does_not_block() -> None:
    comments = [
        _comment(
            f"""## Conductor status digest

Current head: `{HEAD_X}`

The earlier Current-head evidence blocker on this PR was resolved by the repair.
""",
            created_at="2026-07-08T05:20:08Z",
            author_association="MEMBER",
        )
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is False


def test_trusted_lift_that_names_the_park_in_prose_clears_it() -> None:
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

I lift the Current-head repeat-blocker park for this head.
""",
            created_at="2026-07-08T05:30:00Z",
        ),
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is False
    assert record["lifted_by"]["created_at"] == "2026-07-08T05:30:00Z"


def test_prose_mention_after_lift_does_not_reblock() -> None:
    comments = [
        _comment(
            f"""## Current-head evidence blocker

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
        ),
        _comment(
            f"""Status digest. Current head: `{HEAD_X}`.

The earlier Current-head evidence blocker was lifted by the operator.
""",
            created_at="2026-07-08T05:40:00Z",
            author_association="MEMBER",
        ),
    ]

    record = current_head_park_record(comments, head_sha=HEAD_X)

    assert record["blocked"] is False
    assert record["lifted_by"]["created_at"] == "2026-07-08T05:30:00Z"


_GOVERNANCE_DOC = (
    Path(__file__).resolve().parents[3] / "docs" / "governance" / "MERGE_GATE_RECONCILIATION.md"
)
_TEMPLATE_HEAD_PLACEHOLDER = "<full 40-character head SHA>"


def _park_section() -> str:
    doc = _GOVERNANCE_DOC.read_text(encoding="utf-8")
    return doc[doc.index("## Parking an exact head") :]


def test_documented_park_and_lift_templates_are_recognized() -> None:
    park_template, lift_template = re.findall(r"```text\n(.*?)```", _park_section(), flags=re.S)[:2]
    assert _TEMPLATE_HEAD_PLACEHOLDER in park_template
    assert _TEMPLATE_HEAD_PLACEHOLDER in lift_template
    park = _comment(
        park_template.replace(_TEMPLATE_HEAD_PLACEHOLDER, HEAD_X),
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([park], head_sha=HEAD_X)["blocked"] is True
    assert current_head_park_record([park], head_sha=HEAD_Y)["blocked"] is False

    lift = _comment(
        lift_template.replace(_TEMPLATE_HEAD_PLACEHOLDER, HEAD_X),
        created_at="2026-07-08T05:30:00Z",
    )
    lifted = current_head_park_record([park, lift], head_sha=HEAD_X)
    assert lifted["blocked"] is False
    assert lifted["lifted_by"]["created_at"] == "2026-07-08T05:30:00Z"


@pytest.mark.parametrize(
    "body",
    [
        f"## Current-head repeat-blocker park\n\nHead SHA: {HEAD_X}\n",
        f"## Current-head repeat-blocker park\n\nhead_sha: {HEAD_X}\n",
        f"**Current-head repeat-blocker park**\n\nExact head: {HEAD_X}\n",
        f"Current-head repeat-blocker park - PR #9011\n\nExact head: {HEAD_X}\n",
        f"## Current-head repeat-blocker park\n\nExact head: {HEAD_X[:12]}\n",
    ],
)
def test_formats_outside_the_documented_template_do_not_park(body: str) -> None:
    assert "is not recognized" in _park_section()
    comment = _comment(body, created_at="2026-07-08T05:20:08Z", author_association="MEMBER")

    assert current_head_park_record([comment], head_sha=HEAD_X)["blocked"] is False
