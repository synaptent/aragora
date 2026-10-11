from __future__ import annotations

import re
from pathlib import Path

import pytest

from aragora.cli.commands.review_queue_park_records import (
    TRUSTED_OPERATOR_LOGINS_ENV,
    collaborator_admin_permission_checker,
    current_head_park_record,
)


HEAD_X = "a" * 40
HEAD_Y = "b" * 40


@pytest.fixture(autouse=True)
def _default_trusted_operators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRUSTED_OPERATOR_LOGINS_ENV, raising=False)


def _comment(
    body: str,
    *,
    created_at: str,
    author_association: str = "OWNER",
    author_login: str | None = None,
) -> dict[str, object]:
    comment: dict[str, object] = {
        "body": body,
        "createdAt": created_at,
        "authorAssociation": author_association,
        "url": f"https://github.example/comment/{created_at}",
    }
    if author_login is not None:
        comment["author"] = {"login": author_login}
    return comment


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


_PARK_BODY = f"""## Current-head repeat-blocker park

Exact head: `{HEAD_X}`

Do not merge this PR on this head.
"""
_LIFT_BODY = f"""## Current-head park lift

Exact head: `{HEAD_X}`

I explicitly lift the current-head park for this head.
"""


def _park(association: str = "MEMBER") -> dict[str, object]:
    return _comment(
        _PARK_BODY,
        created_at="2026-07-08T05:20:08Z",
        author_association=association,
        author_login="an0mium",
    )


def _lift(
    association: str,
    login: str | None,
    body: str = _LIFT_BODY,
) -> dict[str, object]:
    return _comment(
        body,
        created_at="2026-07-08T05:30:00Z",
        author_association=association,
        author_login=login,
    )


def _no_permission_lookup(login: str) -> bool:
    raise AssertionError(f"unexpected admin permission lookup for {login}")


def test_member_lift_by_default_trusted_operator_clears_park() -> None:
    record = current_head_park_record(
        [_park(), _lift("MEMBER", "scarmani")],
        head_sha=HEAD_X,
        admin_permission_checker=_no_permission_lookup,
    )

    assert record["blocked"] is False
    assert record["lifted_by"]["created_at"] == "2026-07-08T05:30:00Z"
    assert record["lifted_by"]["author_login"] == "scarmani"
    assert record["lifted_by"]["author_association"] == "MEMBER"


@pytest.mark.parametrize("login", ["an0mium", "", None])
def test_member_lift_off_the_trusted_operator_allowlist_does_not_clear_park(
    login: str | None,
) -> None:
    record = current_head_park_record(
        [_park(), _lift("MEMBER", login)],
        head_sha=HEAD_X,
        admin_permission_checker=_no_permission_lookup,
    )

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head repeat-blocker park"


def test_trusted_operator_env_replaces_the_default_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TRUSTED_OPERATOR_LOGINS_ENV, " Other-Operator , second ")

    default_login = current_head_park_record(
        [_park(), _lift("MEMBER", "scarmani")], head_sha=HEAD_X
    )
    configured_login = current_head_park_record(
        [_park(), _lift("MEMBER", "other-operator")], head_sha=HEAD_X
    )

    assert default_login["blocked"] is True
    assert configured_login["blocked"] is False


def test_explicit_trusted_operator_logins_take_precedence_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TRUSTED_OPERATOR_LOGINS_ENV, "scarmani")

    record = current_head_park_record(
        [_park(), _lift("MEMBER", "scarmani")],
        head_sha=HEAD_X,
        trusted_operator_logins=["Release-Captain"],
    )
    captain = current_head_park_record(
        [_park(), _lift("MEMBER", "release-captain")],
        head_sha=HEAD_X,
        trusted_operator_logins=["Release-Captain"],
    )

    assert record["blocked"] is True
    assert captain["blocked"] is False


@pytest.mark.parametrize(
    ("login", "is_admin", "expected_blocked", "expected_lookups"),
    [
        ("scarmani", True, False, ["scarmani"]),
        ("scarmani", False, True, ["scarmani"]),
        ("an0mium", True, True, []),
    ],
)
def test_collaborator_lift_needs_allowlist_entry_and_live_admin_permission(
    login: str,
    is_admin: bool,
    expected_blocked: bool,
    expected_lookups: list[str],
) -> None:
    lookups: list[str] = []

    def checker(candidate: str) -> bool:
        lookups.append(candidate)
        return is_admin

    record = current_head_park_record(
        [_park(), _lift("COLLABORATOR", login)],
        head_sha=HEAD_X,
        admin_permission_checker=checker,
    )

    assert record["blocked"] is expected_blocked
    assert lookups == expected_lookups


def test_collaborator_lift_fails_closed_when_permission_lookup_fails() -> None:
    def failing_checker(login: str) -> bool:
        raise RuntimeError(f"gh api failed for {login}")

    record = current_head_park_record(
        [_park(), _lift("COLLABORATOR", "scarmani")],
        head_sha=HEAD_X,
        admin_permission_checker=failing_checker,
    )

    assert record["blocked"] is True


def test_collaborator_lift_without_permission_checker_does_not_clear_park() -> None:
    record = current_head_park_record(
        [_park(), _lift("COLLABORATOR", "scarmani")],
        head_sha=HEAD_X,
    )

    assert record["blocked"] is True


def test_owner_lift_needs_no_allowlist_entry_or_permission_lookup() -> None:
    record = current_head_park_record(
        [_park(), _lift("OWNER", "repo-owner")],
        head_sha=HEAD_X,
        admin_permission_checker=_no_permission_lookup,
    )

    assert record["blocked"] is False


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"permission": "admin"}, True),
        ({"permission": "write", "role_name": "admin"}, True),
        ({"permission": "write", "role_name": "maintain"}, False),
        (None, False),
    ],
)
def test_collaborator_admin_permission_checker_reads_the_collaborator_permission_api(
    payload: object, expected: bool
) -> None:
    calls: list[list[str]] = []

    def fake_gh_json(args: list[str]) -> object:
        calls.append(args)
        return payload

    checker = collaborator_admin_permission_checker("synaptent/aragora", gh_json=fake_gh_json)

    assert checker("Some User") is expected
    assert calls == [["api", "repos/synaptent/aragora/collaborators/Some%20User/permission"]]


def test_collaborator_admin_permission_checker_without_repo_slug_fails_closed() -> None:
    checker = collaborator_admin_permission_checker("", gh_json=_no_permission_lookup)

    assert checker("scarmani") is False


_FENCED_PARK_TEMPLATES = [
    f"```text\n## Current-head repeat-blocker park\n\nExact head: {HEAD_X}\n\nDo not merge.\n```\n",
    f"~~~\n## Current-head repeat-blocker park\n\nExact head: {HEAD_X}\n~~~\n",
    f"````markdown\n```\n## Current-head evidence blocker\n\nExact head: {HEAD_X}\n```\n````\n",
    f"> ## Current-head repeat-blocker park\n>\n> Exact head: {HEAD_X}\n",
    f"    ## Current-head repeat-blocker park\n\n    Exact head: {HEAD_X}\n",
    f"```\n## Current-head repeat-blocker park\n\nExact head: {HEAD_X}\n",
]


@pytest.mark.parametrize("quoted", _FENCED_PARK_TEMPLATES)
def test_quoted_park_template_does_not_park(quoted: str) -> None:
    comment = _comment(
        f"## Model Review Evidence\n\nExact head: `{HEAD_X}`\n\nFor reference, a park reads:\n\n{quoted}",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([comment], head_sha=HEAD_X)["blocked"] is False


def test_bare_marker_line_without_its_own_head_line_does_not_park() -> None:
    comment = _comment(
        f"""Status digest.

Exact head: `{HEAD_X}`

Current-head evidence blocker

was resolved by the repair.
""",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([comment], head_sha=HEAD_X)["blocked"] is False


def test_head_line_after_the_next_heading_does_not_belong_to_the_marker() -> None:
    comment = _comment(
        f"""## Current-head evidence blocker

See the review below.

## Model review

Exact head: `{HEAD_X}`
""",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([comment], head_sha=HEAD_X)["blocked"] is False


def test_fenced_head_line_does_not_belong_to_the_marker() -> None:
    comment = _comment(
        f"## Current-head evidence blocker\n\n```\nExact head: {HEAD_X}\n```\n",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([comment], head_sha=HEAD_X)["blocked"] is False


def test_head_line_later_in_the_marker_block_parks() -> None:
    comment = _comment(
        f"""## Current-head evidence blocker

PR: #9011
Reviewer: claude

Exact head: `{HEAD_X}`
""",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    record = current_head_park_record([comment], head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head evidence blocker"


def test_longer_hex_string_is_not_a_full_head_sha() -> None:
    comment = _comment(
        f"## Current-head evidence blocker\n\nExact head: {HEAD_X}{'a' * 24}\n",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([comment], head_sha=HEAD_X)["blocked"] is False


@pytest.mark.parametrize(("association", "login"), [("OWNER", None), ("MEMBER", "scarmani")])
def test_quoted_lift_template_does_not_clear_park(association: str, login: str | None) -> None:
    quoted_lift = _lift(
        association,
        login,
        body=f"""Not lifting yet.

Exact head: `{HEAD_X}`

For reference, a lift reads:

```text
## Current-head park lift

Exact head: {HEAD_X}

<reason>
```
""",
    )

    record = current_head_park_record([_park(), quoted_lift], head_sha=HEAD_X)

    assert record["blocked"] is True
    assert record["park_marker"] == "Current-head repeat-blocker park"


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

    for association in ("OWNER", "MEMBER"):
        lift = _comment(
            lift_template.replace(_TEMPLATE_HEAD_PLACEHOLDER, HEAD_X),
            created_at="2026-07-08T05:30:00Z",
            author_association=association,
            author_login="scarmani",
        )
        lifted = current_head_park_record([park, lift], head_sha=HEAD_X)
        assert lifted["blocked"] is False
        assert lifted["lifted_by"]["created_at"] == "2026-07-08T05:30:00Z"


def test_quoting_the_documented_park_template_does_not_park() -> None:
    park_template = re.findall(r"```text\n(.*?)```", _park_section(), flags=re.S)[0]
    quoted = _comment(
        f"Evidence note.\n\nExact head: `{HEAD_X}`\n\nTemplate for reference:\n\n```text\n"
        + park_template.replace(_TEMPLATE_HEAD_PLACEHOLDER, HEAD_X)
        + "```\n",
        created_at="2026-07-08T05:20:08Z",
        author_association="MEMBER",
    )

    assert current_head_park_record([quoted], head_sha=HEAD_X)["blocked"] is False


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
