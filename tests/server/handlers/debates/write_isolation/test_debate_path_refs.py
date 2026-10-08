"""How per-debate paths name their debate: storage slugs and trailing slashes.

Slugs come from ``DebateStorage.generate_slug``, which keeps Unicode letters and
can run past the 128-character id pattern; the owner reads the debate by such a
slug like by its id, while other callers get the usual 404/401/403. A reference
that no slug or id can be is refused with 400 before any lookup. A write path
with a trailing slash gets the write gate's answer, never a 500.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DA_TASK,
    DP,
    NOT_FOUND,
    ORG_A,
    REFUSALS,
    USER_A,
    USER_B,
    USER_NO_ORG,
    body_of,
    debate_record,
    text_of,
)

DU, DU_TASK = "deb-unicode-a", "Évaluer la stratégie de prix à Zürich"
DL = "deb-long-slug-a"
DL_TASK = (
    "Pneumonoultramicroscopicsilicovolcanoconiosis floccinaucinihilipilification "
    "hippopotomonstrosesquippedaliophobia supercalifragilisticexpialidocious"
)
ORG_REQUIRED = "org_required"


@pytest.fixture
def slugs(storage) -> dict[str, str]:
    """Slugs the storage generated for a Unicode task and for a long one, both A's."""
    unicode_slug = storage.save_dict(debate_record(DU, DU_TASK), org_id=ORG_A)
    long_slug = storage.save_dict(debate_record(DL, DL_TASK), org_id=ORG_A)
    assert not unicode_slug.isascii()
    assert len(long_slug) > 128
    return {DU: unicode_slug, DL: long_slug}


def _slug_paths(slug: str) -> list[str]:
    return [
        f"/api/v1/debates/slug/{slug}",
        f"/api/v1/debates/{slug}",
        f"/api/v1/debates/slug/{quote(slug)}",
        f"/api/v1/debates/{quote(slug)}",
    ]


class TestStorageSlugs:
    @pytest.mark.parametrize("debate_id", [DU, DL])
    def test_owner_reads_the_debate_by_its_slug(self, send, slugs, debate_id):
        for path in _slug_paths(slugs[debate_id]):
            result = send(USER_A, "GET", path)
            assert result.status_code == 200, (path, text_of(result))
            assert body_of(result)["id"] == debate_id, path

    def test_owner_reads_suffix_routes_by_a_unicode_slug(self, send, slugs):
        by_slug = send(USER_A, "GET", f"/api/v1/debates/{quote(slugs[DU])}/messages")
        by_id = send(USER_A, "GET", f"/api/v1/debates/{DU}/messages")

        assert by_slug.status_code == 200, text_of(by_slug)
        assert text_of(by_slug) == text_of(by_id)

    @pytest.mark.parametrize("debate_id", [DU, DL])
    def test_other_callers_get_the_usual_denials(self, send, slugs, debate_id):
        missing = send(USER_B, "GET", "/api/v1/debates/slug/évaluer-nothing-2026-01-01")
        assert (missing.status_code, body_of(missing)) == (404, NOT_FOUND)

        for path in _slug_paths(slugs[debate_id]):
            refused = send(USER_B, "GET", path)
            assert (refused.status_code, body_of(refused)) == (404, NOT_FOUND), path
            assert DU_TASK not in text_of(refused) and DL_TASK not in text_of(refused)
            assert send(ANON, "GET", path).status_code == 401, path
            no_org = send(USER_NO_ORG, "GET", path)
            assert (no_org.status_code, body_of(no_org)["code"]) == (403, ORG_REQUIRED), path

    @pytest.mark.parametrize(
        "ref",
        [
            "..",
            "%2E%2E",
            "a%2Fb",
            "has%20space",
            "has.dot",
            "nul%00byte",
            "ctl%01char",
            "%C3%A9t%C3%A9%0A",
            "%FF%FE",
            "x" * 501,
        ],
    )
    def test_refs_no_slug_or_id_can_be_are_refused_before_lookup(self, send, ref):
        for path in (f"/api/v1/debates/slug/{ref}", f"/api/v1/debates/{ref}"):
            for user in (USER_A, USER_B, ANON):
                result = send(user, "GET", path)
                assert result.status_code == 400, (path, user.user_id, text_of(result))


@pytest.mark.no_auto_auth
class TestStorageSlugsThroughTheServer:
    def test_owner_reads_by_percent_encoded_slug_and_others_are_refused(self, server, slugs):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_a = jwt("user-a", ORG_A, "owner")
        token_b = jwt("user-b", "org-b", "owner")
        for debate_id in (DU, DL):
            for path in _slug_paths(slugs[debate_id])[2:]:
                status, payload = dispatch(server, "GET", path, token_a)
                assert (status, payload.get("id")) == (200, debate_id), (path, payload)
                assert dispatch(server, "GET", path, token_b) == (404, NOT_FOUND), path
                assert dispatch(server, "GET", path)[0] == 401, path


# POST suffixes that the plain form gates: served writes and unserved ones.
GATED_POST_SUFFIXES = (
    "fork",
    "followup",
    "verify",
    "cancel",
    "decision-integrity",
    "intervene",
    "checkpoint",
    "checkpoint/pause",
    "bridge",
)


class TestTrailingSlashWrites:
    @pytest.mark.parametrize("suffix", GATED_POST_SUFFIXES)
    def test_trailing_slash_gets_the_same_denial_as_the_plain_form(self, send, suffix):
        cases = REFUSALS + ((ANON, DP, 401), (USER_NO_ORG, DP, 403))
        for user, debate_id, status in cases:
            for prefix in ("/api/v1/debates", "/api/debates"):
                path = f"{prefix}/{debate_id}/{suffix}/"
                result = send(user, "POST", path, {"task": "probe", "branch_point": 0})
                assert result.status_code == status, (path, user.user_id, text_of(result))
                if status == 404:
                    assert body_of(result) == NOT_FOUND, path
                if status == 403:
                    assert body_of(result)["code"] == ORG_REQUIRED, path

    @pytest.mark.parametrize("suffix", GATED_POST_SUFFIXES)
    def test_owner_trailing_slash_is_not_served_and_writes_nothing(self, send, tmp_path, suffix):
        for debate_id in (DA, DP):
            result = send(USER_A, "POST", f"/api/v1/debates/{debate_id}/{suffix}/", {"task": "x"})
            assert (result.status_code, body_of(result)) == (404, NOT_FOUND), suffix
        assert list(tmp_path.glob("branches/*.json")) == []
        assert list(tmp_path.glob("followups/*.json")) == []

    @pytest.mark.parametrize("method", ["PATCH", "DELETE"])
    def test_patch_and_delete_with_a_trailing_slash(self, send, storage, method):
        before = storage.get_debate(DA)
        cases = REFUSALS + ((USER_A, DA, 404), (USER_A, DP, 404), (ANON, DP, 401))
        for user, debate_id, status in cases:
            result = send(user, method, f"/api/v1/debates/{debate_id}/", {"title": "Hijacked"})
            assert result.status_code == status, (method, debate_id, user.user_id)
        assert storage.get_debate(DA) == before
        assert storage.get_debate(DA)["task"] == DA_TASK


@pytest.mark.no_auto_auth
class TestTrailingSlashThroughTheServer:
    def test_trailing_slash_posts_on_a_public_debate_never_500(self, server, tmp_path):
        from aragora.debate.intervention import get_intervention_queue
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch, jwt

        callers = (
            (None, 401, None),
            (jwt("user-no-org", None, "owner"), 403, ORG_REQUIRED_BODY),
            (jwt("user-b", "org-b", "owner"), 404, NOT_FOUND),
            (jwt("user-a", ORG_A, "owner"), 404, NOT_FOUND),
        )
        for suffix in GATED_POST_SUFFIXES:
            path = f"/api/v1/debates/{DP}/{suffix}/"
            for token, status, expected in callers:
                got, payload = dispatch(server, "POST", path, token, body={"task": "x"})
                assert got == status, (path, payload)
                assert expected is None or payload == expected, (path, payload)
        assert get_intervention_queue().get_debate_interventions(DP) == []
        assert list(tmp_path.glob("followups/*.json")) == []
