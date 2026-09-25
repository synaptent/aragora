from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_script(name: str, filename: str) -> Any:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pal = _load_script("parked_authorization_ledger_under_test", "parked_authorization_ledger.py")
fdq = _load_script("founder_decision_queue_for_ledger_test", "founder_decision_queue.py")
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
HEAD = "a" * 40


def _ask(*, pr: int, head: str = HEAD, tier: int = 3) -> str:
    return f"""## Exact-head Tier {tier} readiness / evidence authorization request

### Exact operator authorization needed

```text
Tier-{tier} Ready-for-Review Authorization

PR: #{pr}
Exact head: {head}

I authorize marking #{pr} ready and collecting current-head model evidence.
This does not authorize settlement or merge.
```
"""


def _pr(*, number: int = 42, head: str = HEAD, comments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "number": number,
        "title": "Bounded test PR",
        "headRefOid": head,
        "headRefName": "codex/bounded-test",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "author": {"login": "contributor"},
        "comments": comments,
    }


def _comment(
    body: str,
    *,
    author: str = "scarmani",
    association: str = "MEMBER",
    created: str = "2026-08-20T12:00:00Z",
) -> dict[str, Any]:
    return {
        "author": {"login": author},
        "authorAssociation": association,
        "body": body,
        "createdAt": created,
        "url": "https://github.com/synaptent/aragora/pull/42#issuecomment-1",
    }


def _green(_: int) -> Any:
    return pal.RequiredCheckSummary(True, "5/5 green")


def test_collects_unanswered_exact_head_ask() -> None:
    items = pal.collect_authorizations(
        [_pr(comments=[_comment(_ask(pr=42))])],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert len(items) == 1
    assert items[0].pr == 42
    assert items[0].tier == 3
    assert items[0].head_matches is True
    assert items[0].settlement_shape_green is True
    assert items[0].expected_reply.startswith("Tier-3 Ready-for-Review Authorization")


def test_later_decisive_owner_reply_resolves_ask() -> None:
    comments = [
        _comment(_ask(pr=42)),
        _comment(
            f"For PR #42 at exact head {HEAD}, I authorize the requested review step.",
            author="an0mium",
            created="2026-08-21T12:00:00Z",
        ),
    ]

    items = pal.collect_authorizations(
        [_pr(comments=comments)],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert items == []


def test_quoted_authorization_request_does_not_resolve_ask() -> None:
    quoted_request = "\n".join(f"> {line}" for line in _ask(pr=42).splitlines())
    comments = [
        _comment(_ask(pr=42)),
        _comment(
            f"{quoted_request}\n\nCan you confirm whether the focused tests passed?",
            author="an0mium",
            created="2026-08-21T12:00:00Z",
        ),
    ]

    items = pal.collect_authorizations(
        [_pr(comments=comments)],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert [item.pr for item in items] == [42]


def test_unquoted_decision_below_quoted_request_resolves_ask() -> None:
    quoted_request = "\n".join(f"> {line}" for line in _ask(pr=42).splitlines())
    comments = [
        _comment(_ask(pr=42)),
        _comment(
            f"{quoted_request}\n\nI authorize PR #42 at exact head {HEAD}.",
            author="an0mium",
            created="2026-08-21T12:00:00Z",
        ),
    ]

    items = pal.collect_authorizations(
        [_pr(comments=comments)],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert items == []


def test_decisive_reply_requires_exact_pr_number() -> None:
    comments = [
        _comment(_ask(pr=42)),
        _comment(
            f"For PR #425 at exact head {'b' * 40}, I authorize the requested review step.",
            author="an0mium",
            created="2026-08-21T12:00:00Z",
        ),
    ]

    items = pal.collect_authorizations(
        [_pr(comments=comments)],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert [item.pr for item in items] == [42]
    assert (
        pal._decisive_operator_reply(f"I authorize PR #42 at {HEAD}", pr=425, head="b" * 40)
        is False
    )


def test_untrusted_authorization_ask_is_ignored(caplog: Any) -> None:
    items = pal.collect_authorizations(
        [
            _pr(
                comments=[
                    _comment(
                        _ask(pr=42),
                        author="outside-contributor",
                        association="CONTRIBUTOR",
                    )
                ]
            )
        ],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert items == []
    assert "untrusted author" in caplog.text


def test_explicitly_trusted_ask_author_is_accepted() -> None:
    items = pal.collect_authorizations(
        [
            _pr(
                comments=[
                    _comment(
                        _ask(pr=42),
                        author="trusted-review-bot",
                        association="CONTRIBUTOR",
                    )
                ]
            )
        ],
        now=NOW,
        operator_logins={"an0mium"},
        trusted_ask_logins={"trusted-review-bot"},
        check_loader=_green,
    )

    assert [item.pr for item in items] == [42]


def test_head_moved_is_retained_and_ranked_after_current_head() -> None:
    moved = _pr(number=41, head="b" * 40, comments=[_comment(_ask(pr=41))])
    current = _pr(number=42, comments=[_comment(_ask(pr=42))])

    items = pal.collect_authorizations(
        [moved, current],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert [item.pr for item in items] == [42, 41]
    assert items[1].head_matches is False


def test_pr_without_terminal_ask_is_ignored() -> None:
    items = pal.collect_authorizations(
        [_pr(comments=[_comment("CI is green. No operator decision requested.")])],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )

    assert items == []


def test_dependabot_pr_is_excluded() -> None:
    pr = _pr(comments=[_comment(_ask(pr=42))])
    pr["headRefName"] = "dependabot/pip/cryptography-99"

    assert (
        pal.collect_authorizations([pr], now=NOW, operator_logins={"an0mium"}, check_loader=_green)
        == []
    )


def test_packet_is_consumable_by_existing_decision_parser() -> None:
    item = pal.collect_authorizations(
        [_pr(comments=[_comment(_ask(pr=42))])],
        now=NOW,
        operator_logins={"an0mium"},
        check_loader=_green,
    )[0]

    packet = pal.render_packet([item], repo="synaptent/aragora", now=NOW)
    parsed = fdq.parse_decision_packet(packet, source="ledger.md")

    assert len(parsed) == 1
    assert parsed[0].target.startswith("PR #42")
    assert parsed[0].requested_action.startswith("Paste the exact PR #42 block")
    assert parsed[0].expected_reply == "See exact block for PR #42 below"
    assert item.expected_reply in packet


def test_rest_fallback_normalizes_comments_and_candidate_state(monkeypatch: Any) -> None:
    pull = {
        "number": 42,
        "title": "Fallback PR",
        "draft": True,
        "head": {"sha": HEAD, "ref": "codex/fallback"},
        "user": {"login": "contributor"},
    }
    comment = {
        "user": {"login": "scarmani"},
        "author_association": "MEMBER",
        "body": _ask(pr=42),
        "created_at": "2026-08-20T12:00:00Z",
        "html_url": "https://github.com/synaptent/aragora/pull/42#issuecomment-1",
    }

    def fake_run_json(command: list[str]) -> Any:
        endpoint = command[-1]
        if endpoint.endswith("pulls?state=open&per_page=100"):
            return [[pull]]
        if endpoint.endswith("issues/42/comments?per_page=100"):
            return [[comment]]
        if endpoint.endswith("pulls/42"):
            return {"mergeable": True, "mergeable_state": "clean"}
        raise AssertionError(command)

    monkeypatch.setattr(pal, "_run_json", fake_run_json)

    prs = pal._load_open_prs_rest(repo="synaptent/aragora")

    assert len(prs) == 1
    assert prs[0]["headRefOid"] == HEAD
    assert prs[0]["mergeable"] == "MERGEABLE"
    assert prs[0]["mergeStateStatus"] == "CLEAN"
    assert prs[0]["comments"][0]["author"]["login"] == "scarmani"
    assert prs[0]["comments"][0]["authorAssociation"] == "MEMBER"


def test_default_cli_writes_nothing(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pal, "load_open_prs", lambda *, repo: [])

    assert pal.main(["--repo", "synaptent/aragora", "--now", "2026-08-29T12:00:00Z"]) == 0

    assert not (tmp_path / ".aragora").exists()
    assert "# Parked Authorization Ledger" in capsys.readouterr().out


def test_explicit_output_writes_packet(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "ledger.md"
    monkeypatch.setattr(pal, "load_open_prs", lambda *, repo: [])

    assert (
        pal.main(
            [
                "--repo",
                "synaptent/aragora",
                "--now",
                "2026-08-29T12:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert output.read_text(encoding="utf-8").startswith("# Parked Authorization Ledger")
