"""Follow-up records never overwrite each other, whoever creates them and when.

Ad hoc debate ids share their first eight characters (``adhoc_ab...``), so ids
built from the parent's prefix and the clock collided across orgs and the
second write replaced the first org's record.
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

from tests.server.handlers.debates.write_isolation.support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    body_of,
    debate_record,
    text_of,
)

PARENT_A, PARENT_B = "adhoc_ab111111", "adhoc_ab222222"


def _seed_parents(storage) -> None:
    storage.save_dict(debate_record(PARENT_A, "Parent debate of org A"), org_id=ORG_A)
    storage.save_dict(debate_record(PARENT_B, "Parent debate of org B"), org_id=ORG_B)


def _record(tmp_path, followup_id: str) -> dict:
    return json.loads((tmp_path / "followups" / f"{followup_id}.json").read_text())


def test_same_second_followups_from_prefix_sharing_parents_stay_apart(
    send, storage, tmp_path, monkeypatch
):
    _seed_parents(storage)
    monkeypatch.setattr(time, "time", lambda: 1_791_460_800.0)

    made = {}
    for user, parent, task in (
        (USER_A, PARENT_A, "Follow-up for A"),
        (USER_B, PARENT_B, "Follow-up for B"),
        (USER_A, PARENT_A, "Second follow-up for A"),
    ):
        result = send(user, "POST", f"/api/v1/debates/{parent}/followup", {"task": task})
        assert result.status_code == 200, text_of(result)
        made[task] = body_of(result)["followup_id"]

    assert len(set(made.values())) == 3
    assert len(list((tmp_path / "followups").glob("*.json"))) == 3
    for task, org, user_id, parent in (
        ("Follow-up for A", ORG_A, "user-a", PARENT_A),
        ("Follow-up for B", ORG_B, "user-b", PARENT_B),
        ("Second follow-up for A", ORG_A, "user-a", PARENT_A),
    ):
        record = _record(tmp_path, made[task])
        assert (record["id"], record["task"]) == (made[task], task)
        assert (record["org_id"], record["created_by"]) == (org, user_id)
        assert record["parent_debate_id"] == parent


def test_an_existing_followup_file_is_never_replaced(send, storage, tmp_path, monkeypatch):
    from aragora.server.handlers.debates import fork

    _seed_parents(storage)
    taken, fresh = uuid.UUID(int=1), uuid.UUID(int=2)
    (tmp_path / "followups").mkdir()
    existing = tmp_path / "followups" / f"followup-{taken.hex}.json"
    existing.write_text('{"org_id": "org-a", "task": "already here"}')
    ids = iter([taken, fresh])
    monkeypatch.setattr(fork, "uuid", SimpleNamespace(uuid4=lambda: next(ids)))

    result = send(USER_B, "POST", f"/api/v1/debates/{PARENT_B}/followup", {"task": "B task"})

    assert result.status_code == 200, text_of(result)
    assert body_of(result)["followup_id"] == f"followup-{fresh.hex}"
    assert json.loads(existing.read_text()) == {"org_id": "org-a", "task": "already here"}
    assert _record(tmp_path, f"followup-{fresh.hex}")["org_id"] == ORG_B
