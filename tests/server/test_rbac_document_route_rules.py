"""Document RBAC route rules through the real dispatch, with the API token set.

Owner A reaches every mapped route, B never sees or changes A's records,
anonymous callers get 401 and static-token-only callers 403 ``org_required``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aragora.documents.parsing import DocumentStore, parse_document
from aragora.server.handlers.features.folder_upload import (
    FolderUploadHandler,
    FolderUploadJob,
    FolderUploadStatus,
)
from tests.server.rbac_dispatch import (
    AUTH_REQUIRED_BODY,
    ORG_REQUIRED_BODY,
    STATIC_TOKEN,
    build_server,
    dispatch,
    handler_for,
    install_api_token,
    isolate_auth,
    jwt,
)

pytestmark = pytest.mark.no_auto_auth

ORG_A = "org-a-doc-rules"
ORG_B = "org-b-doc-rules"
FOLDER_A = "folder-a-doc-rules"
MISSING = "missing-doc-rules"

# Owner A's requests on every mapped route and the status the handler answers.
OWNER_SUCCESS_ROUTES = [
    ("GET", "/api/v1/documents"),
    ("GET", "/api/documents"),
    ("GET", "/api/v1/documents/formats"),
    ("GET", "/api/v1/documents/{doc}"),
    ("GET", "/api/v1/documents/{doc}/chunks"),
    ("GET", "/api/v1/documents/processing/stats"),
    ("GET", "/api/v1/knowledge/jobs"),
    ("GET", "/api/v1/documents/folders"),
    ("GET", "/api/v1/documents/folders/{folder}"),
    ("GET", "/api/v1/documents/folder/upload/{folder}/status"),
]
# Routes the handler answers with its own validation or not-found status once
# both permission checks have passed.
OWNER_REACHES_HANDLER_ROUTES = [
    ("GET", f"/api/v1/documents/batch/{MISSING}", 404),
    ("GET", f"/api/v1/knowledge/jobs/{MISSING}", 404),
    ("DELETE", f"/api/v1/documents/batch/{MISSING}", 404),
    ("POST", "/api/v1/documents/batch", 400),
    ("POST", "/api/v1/documents/query", 400),
    ("POST", "/api/v1/documents/summarize", 400),
    ("POST", "/api/v1/documents/compare", 400),
    ("POST", "/api/v1/documents/extract", 400),
    ("POST", "/api/v1/documents/folder/scan", 400),
    ("POST", "/api/v1/documents/folder/upload", 400),
]
ALL_ROUTES = [
    *OWNER_SUCCESS_ROUTES,
    *[(m, p) for m, p, _status in OWNER_REACHES_HANDLER_ROUTES],
    ("POST", "/api/v1/documents/upload"),
    ("DELETE", "/api/v1/documents/{doc}"),
    ("DELETE", "/api/v1/documents/folders/{folder}"),
]


@pytest.fixture(scope="module")
def server():
    return build_server()


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    isolate_auth(monkeypatch)


@pytest.fixture
def users() -> SimpleNamespace:
    return SimpleNamespace(
        a=jwt("user-a", ORG_A, "owner"),
        a2=jwt("user-a2", ORG_A, "admin"),
        b=jwt("user-b", ORG_B, "owner"),
    )


@pytest.fixture
def records(server, tmp_path, monkeypatch) -> SimpleNamespace:
    import aragora.knowledge.integration as knowledge

    store = DocumentStore(tmp_path / "documents")
    doc_a = store.add(parse_document(b"probe A", "a.md", org_id=ORG_A, created_by="user-a"))
    doc_b = store.add(parse_document(b"probe B", "b.md", org_id=ORG_B, created_by="user-b"))
    for path in ("/api/v1/documents", "/api/v1/documents/batch", "/api/v1/documents/query"):
        monkeypatch.setitem(handler_for(server, path).ctx, "document_store", store)
    monkeypatch.setattr(knowledge, "_jobs", {})
    monkeypatch.setattr(knowledge, "_executor", SimpleNamespace(submit=lambda fn: None))
    monkeypatch.setenv("ARAGORA_ALLOWED_UPLOAD_DIRS", str(tmp_path))

    now = datetime.now(timezone.utc)
    FolderUploadHandler._jobs.clear()
    FolderUploadHandler._jobs[FOLDER_A] = FolderUploadJob(
        folder_id=FOLDER_A,
        root_path=str(tmp_path),
        status=FolderUploadStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        user_id="user-a",
        org_id=ORG_A,
    )
    yield SimpleNamespace(store=store, a=doc_a, b=doc_b)
    FolderUploadHandler._jobs.clear()


def _path(template: str, records: SimpleNamespace) -> str:
    return template.format(doc=records.a, folder=FOLDER_A)


def _doc_ids(server, auth: str) -> set[str]:
    status, body = dispatch(server, "GET", "/api/v1/documents", auth)
    assert status == 200, body
    return {d["id"] for d in body["documents"]}


def _folder_ids(server, auth: str) -> set[str]:
    status, body = dispatch(server, "GET", "/api/v1/documents/folders", auth)
    assert status == 200, body
    return {f["folder_id"] for f in body["folders"]}


class TestOwnerReachesMappedRoutes:
    @pytest.mark.parametrize(("method", "template"), OWNER_SUCCESS_ROUTES)
    def test_owner_gets_success(self, server, users, records, method, template):
        status, body = dispatch(server, method, _path(template, records), users.a)

        assert status == 200, body

    @pytest.mark.parametrize(("method", "path", "expected"), OWNER_REACHES_HANDLER_ROUTES)
    def test_owner_passes_both_permission_checks(
        self, server, users, records, method, path, expected
    ):
        status, body = dispatch(server, method, path, users.a)

        assert status == expected, body
        assert body.get("code") != "permission_denied"

    def test_owner_lists_only_their_documents(self, server, users, records):
        assert _doc_ids(server, users.a) == {records.a}

    def test_owner_uploads_into_their_org(self, server, users, records):
        status, body = dispatch(server, "POST", "/api/v1/documents/upload", users.a)

        assert status == 200, body
        assert records.store.get(body["document"]["id"]).org_id == ORG_A

    def test_owner_deletes_their_document(self, server, users, records):
        status, _ = dispatch(server, "DELETE", f"/api/v1/documents/{records.a}", users.a)

        assert status == 200
        assert records.store.get(records.a) is None


class TestOtherOrgSeesNothingOfA:
    def test_lists_never_contain_a_records(self, server, users, records):
        assert _doc_ids(server, users.b) == {records.b}
        assert _folder_ids(server, users.b) == set()

    @pytest.mark.parametrize("template", [t for _m, t in OWNER_SUCCESS_ROUTES if "{" in t])
    def test_per_id_reads_answer_like_a_missing_id(self, server, users, records, template):
        foreign = dispatch(server, "GET", _path(template, records), users.b)
        missing = dispatch(server, "GET", template.format(doc=MISSING, folder=MISSING), users.b)

        assert foreign == missing
        assert foreign[0] == 404

    def test_document_delete_is_404_and_changes_nothing(self, server, users, records):
        status, _ = dispatch(server, "DELETE", f"/api/v1/documents/{records.a}", users.b)

        assert status == 404
        assert records.store.get(records.a) is not None


class TestRefusedCallers:
    @pytest.mark.parametrize(("method", "template"), ALL_ROUTES)
    def test_anonymous_gets_401(self, server, records, method, template):
        status, body = dispatch(server, method, _path(template, records))

        assert (status, body) == (401, AUTH_REQUIRED_BODY)

    @pytest.mark.parametrize(("method", "template"), ALL_ROUTES)
    def test_static_token_only_gets_403_org_required(self, server, records, method, template):
        status, body = dispatch(server, method, _path(template, records), f"Bearer {STATIC_TOKEN}")

        assert (status, body) == (403, ORG_REQUIRED_BODY)
        assert records.store.get(records.a) is not None
        assert FOLDER_A in FolderUploadHandler._jobs


@pytest.mark.parametrize("api_token", [STATIC_TOKEN, None], ids=["token-set", "token-unset"])
class TestFolderDelete:
    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch, api_token):
        install_api_token(monkeypatch, api_token)

    def test_owner_deletes_their_folder(self, server, users, records):
        status, body = dispatch(server, "DELETE", f"/api/v1/documents/folders/{FOLDER_A}", users.a)

        assert (status, body["success"]) == (200, True)
        assert dispatch(server, "GET", f"/api/v1/documents/folders/{FOLDER_A}", users.a)[0] == 404
        assert _folder_ids(server, users.a) == set()

    def test_other_org_gets_the_missing_id_404(self, server, users, records):
        foreign = dispatch(server, "DELETE", f"/api/v1/documents/folders/{FOLDER_A}", users.b)
        missing = dispatch(server, "DELETE", f"/api/v1/documents/folders/{MISSING}", users.b)

        assert foreign == missing
        assert foreign[0] == 404
        assert _folder_ids(server, users.a) == {FOLDER_A}

    def test_same_org_admin_without_documents_delete_gets_403(self, server, users, records):
        status, _ = dispatch(server, "DELETE", f"/api/v1/documents/folders/{FOLDER_A}", users.a2)

        assert status == 403
        assert _folder_ids(server, users.a) == {FOLDER_A}

    def test_anonymous_gets_401(self, server, records):
        status, _ = dispatch(server, "DELETE", f"/api/v1/documents/folders/{FOLDER_A}")

        assert status == 401
        assert FOLDER_A in FolderUploadHandler._jobs
