"""Org scope on the document-derived routes (inventory B6-B12).

The batch, query and folder handlers run against one real ``DocumentStore`` on
disk, a real ``BatchProcessor`` and real JWTs. Users of two orgs (A and B), a
user without an org and an anonymous caller exercise batch upload/status/
results/delete, processing stats, chunks, context, knowledge jobs,
query/summarize/compare/extract/search and folder scan/upload/list/get/status/
delete. Another org's records and unknown-owner documents answer exactly like
missing ones, refused requests change nothing and never reach a model, and
batch- and folder-created documents land in the uploader's org.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.analysis.nl_query import DocumentQueryEngine
from aragora.documents.ingestion.batch_processor import BatchProcessor
from aragora.documents.parsing import DocumentStore, ParsedDocument, parse_document
from aragora.server.handlers.features import documents_batch, folder_upload
from aragora.server.handlers.features.document_query import DocumentQueryHandler
from aragora.server.handlers.features.documents import DocumentHandler
from aragora.server.handlers.features.documents_batch import DocumentBatchHandler
from aragora.server.handlers.features.folder_upload import FolderUploadHandler

pytestmark = pytest.mark.no_auto_auth

ORG_A = "org-a-derived"
ORG_B = "org-b-derived"
SENTINEL_A = "DERIVED-SENTINEL-ALPHA-8812"
SENTINEL_B = "DERIVED-SENTINEL-BRAVO-3307"
SENTINEL_LEGACY = "DERIVED-SENTINEL-LEGACY-5150"
SHARED_TERM = "procurement"
AUTH_REQUIRED = {"error": "Authentication required", "code": "auth_required"}

_client_ips = (f"10.40.{n // 250}.{n % 250 + 1}" for n in itertools.count())


@pytest.fixture(autouse=True)
def _isolated_auth(monkeypatch):
    """Real JWTs and the stock (unset) static API token."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.server import auth as server_auth

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "derived-isolation-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)


class _DeferredThread:
    """Records background work instead of starting it, so tests run it in order."""

    started: list[_DeferredThread] = []

    def __init__(self, target, args=(), kwargs=None, **_ignored):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self) -> None:
        _DeferredThread.started.append(self)

    def run(self) -> None:
        self.target(*self.args, **self.kwargs)


@pytest.fixture(autouse=True)
def _deferred_background_work(monkeypatch, tmp_path):
    """Batch and folder workers run when the test says so; knowledge jobs never run."""
    import aragora.knowledge.integration as knowledge

    _DeferredThread.started = []
    fake_threading = SimpleNamespace(Thread=_DeferredThread, Lock=__import__("threading").Lock)
    monkeypatch.setattr(documents_batch, "threading", fake_threading)
    monkeypatch.setattr(folder_upload, "threading", fake_threading)
    monkeypatch.setattr(knowledge, "_jobs", {})
    monkeypatch.setattr(knowledge, "_executor", SimpleNamespace(submit=lambda fn: None))
    roots = json.dumps({ORG_A: [str(tmp_path / "a-folder")]})
    monkeypatch.setenv("ARAGORA_ORG_IMPORT_ROOTS", roots)
    FolderUploadHandler._jobs.clear()
    yield
    FolderUploadHandler._jobs.clear()


@pytest.fixture
def model_calls(monkeypatch) -> list[str]:
    """Prompts sent to the answer model; no provider is ever contacted."""
    prompts: list[str] = []

    async def _fake_call_llm(self, prompt, context_messages):
        prompts.append(prompt)
        return "Answer from [Source 1].", "stub-model"

    monkeypatch.setattr(DocumentQueryEngine, "_call_llm", _fake_call_llm)
    return prompts


def _bearer(user_id: str, org_id: str | None) -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token(user_id, f"{user_id}@example.test", org_id, "member")


USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture
def auth_a() -> str:
    return _bearer(USER_A, ORG_A)


@pytest.fixture
def auth_b() -> str:
    return _bearer(USER_B, ORG_B)


@pytest.fixture
def auth_no_org() -> str:
    return _bearer("user-loner", None)


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    return DocumentStore(tmp_path / "documents")


def _seed(store: DocumentStore, text: str, filename: str, org_id: str, user_id: str) -> str:
    return store.add(parse_document(text.encode(), filename, org_id=org_id, created_by=user_id))


@pytest.fixture
def doc_a(store) -> str:
    return _seed(store, f"{SHARED_TERM} policy for A {SENTINEL_A}", "a-policy.md", ORG_A, USER_A)


@pytest.fixture
def doc_a2(store) -> str:
    return _seed(store, f"{SHARED_TERM} budget for A {SENTINEL_A}", "a-budget.md", ORG_A, USER_A)


@pytest.fixture
def doc_b(store) -> str:
    return _seed(store, f"{SHARED_TERM} policy for B {SENTINEL_B}", "b-policy.md", ORG_B, USER_B)


@pytest.fixture
def doc_legacy(store) -> str:
    """A document saved before ownership existed: no org at all."""
    doc_id = "legacy0000000042"
    payload = ParsedDocument(
        id=doc_id,
        filename="legacy.md",
        content_type="text/markdown",
        text=f"{SHARED_TERM} legacy notes {SENTINEL_LEGACY}",
    ).to_dict()
    for key in ("org_id", "created_by", "content_sha256"):
        payload.pop(key, None)
    (store.storage_dir / f"{doc_id}.json").write_text(json.dumps(payload))
    return doc_id


@pytest.fixture
def ctx(store) -> dict[str, Any]:
    return {"document_store": store, "batch_processor": BatchProcessor()}


@pytest.fixture
def batch(ctx) -> DocumentBatchHandler:
    return DocumentBatchHandler(server_context=ctx)


@pytest.fixture
def query(ctx) -> DocumentQueryHandler:
    return DocumentQueryHandler(server_context=ctx)


@pytest.fixture
def folders(ctx) -> FolderUploadHandler:
    return FolderUploadHandler(server_context=ctx)


@pytest.fixture
def docs(ctx) -> DocumentHandler:
    return DocumentHandler(server_context=ctx)


class _Request:
    """The parts of the HTTP request handler these handlers read."""

    def __init__(self, authorization: str | None, body: bytes = b"", **headers: str):
        self.headers: dict[str, str] = {"Content-Length": str(len(body)), **headers}
        if authorization is not None:
            self.headers["Authorization"] = authorization
        self.rfile = io.BytesIO(body)
        self.client_address = (next(_client_ips), 50123)


def _json_request(auth: str | None, payload: dict[str, Any]) -> _Request:
    return _Request(auth, json.dumps(payload).encode(), **{"Content-Type": "application/json"})


def _result(result: Any) -> tuple[int, dict[str, Any]]:
    assert result is not None
    return result.status_code, json.loads(result.body.decode("utf-8"))


def _run(result: Any) -> tuple[int, dict[str, Any]]:
    return _result(asyncio.run(result) if asyncio.iscoroutine(result) else result)


def _b1_ids(docs: DocumentHandler, auth: str) -> set[str]:
    status, body = _result(docs.handle("/api/v1/documents", {}, _Request(auth)))
    assert status == 200, body
    return {d["id"] for d in body["documents"]}


def _batch_upload(
    batch: DocumentBatchHandler,
    auth: str | None,
    files: dict[str, str],
    *,
    process_knowledge: bool = False,
    workspace_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    boundary = "----derived-isolation-boundary"
    body = b""
    for name, text in files.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n{text}\r\n"
        ).encode()
    fields = {"process_knowledge": "true" if process_knowledge else "false"}
    if workspace_id:
        fields["workspace_id"] = workspace_id
    for name, value in fields.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    body += f"--{boundary}--\r\n".encode()
    request = _Request(auth, body, **{"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _run(batch.handle_post("/api/v1/documents/batch", {}, request))


def _run_background_work() -> None:
    while _DeferredThread.started:
        _DeferredThread.started.pop(0).run()


def _get(handler: Any, auth: str | None, path: str, query: dict | None = None):
    return _run(handler.handle(path, query or {}, _Request(auth)))


def _delete(handler: Any, auth: str | None, path: str):
    return _run(handler.handle_delete(path, {}, _Request(auth)))


@pytest.fixture
def a_batch(batch, auth_a) -> dict[str, Any]:
    """A's finished two-file batch: job ids and the stored document ids."""
    status, body = _batch_upload(
        batch,
        auth_a,
        {"a-batch-1.md": f"first {SENTINEL_A}", "a-batch-2.md": f"second {SENTINEL_A}"},
    )
    assert status == 202, body
    _run_background_work()
    processor = batch.ctx["batch_processor"]
    jobs = [asyncio.run(processor.get_result(job_id)) for job_id in body["job_ids"]]
    assert [job.status.value for job in jobs] == ["completed", "completed"]
    return {"job_ids": body["job_ids"], "document_ids": [job.document_id for job in jobs]}


def _folder_upload(folders, auth: str, root: Path) -> str:
    status, body = _run(
        folders.handle_post(
            "/api/v1/documents/folder/upload", {}, _json_request(auth, {"path": str(root)})
        )
    )
    assert status == 200, body
    _run_background_work()
    return body["folder_id"]


@pytest.fixture
def a_folder(folders, auth_a, tmp_path) -> dict[str, Any]:
    root = tmp_path / "a-folder"
    root.mkdir()
    (root / "notes.md").write_text(f"folder notes {SENTINEL_A}")
    (root / "plan.txt").write_text(f"folder plan {SENTINEL_A}")
    folder_id = _folder_upload(folders, auth_a, root)
    job = FolderUploadHandler._jobs[folder_id]
    assert job.status.value == "completed"
    assert len(job.document_ids) == 2
    return {"folder_id": folder_id, "document_ids": list(job.document_ids)}


# ---------------------------------------------------------------------------
# VAL-DOC-009: batch and folder uploads carry the uploader's org
# ---------------------------------------------------------------------------


class TestUploadsCarryUploaderOrg:
    def test_batch_documents_belong_to_the_uploader_org(self, docs, store, a_batch, auth_a, auth_b):
        for doc_id in a_batch["document_ids"]:
            doc = store.get(doc_id)
            assert doc.org_id == ORG_A
            assert doc.created_by == USER_A
        assert set(a_batch["document_ids"]) <= _b1_ids(docs, auth_a)
        assert not set(a_batch["document_ids"]) & _b1_ids(docs, auth_b)

    def test_batch_job_results_name_the_stored_document(self, batch, a_batch, auth_a):
        for job_id, doc_id in zip(a_batch["job_ids"], a_batch["document_ids"]):
            status, body = _get(batch, auth_a, f"/api/v1/documents/batch/{job_id}/results")
            assert status == 200, body
            assert body["document"]["id"] == doc_id

    def test_folder_documents_belong_to_the_uploader_org(
        self, docs, store, a_folder, auth_a, auth_b
    ):
        for doc_id in a_folder["document_ids"]:
            doc = store.get(doc_id)
            assert doc.org_id == ORG_A
            assert doc.created_by == USER_A
        assert set(a_folder["document_ids"]) <= _b1_ids(docs, auth_a)
        assert not set(a_folder["document_ids"]) & _b1_ids(docs, auth_b)

    def test_same_files_from_two_orgs_stay_separate(self, docs, batch, auth_a, auth_b):
        files = {"same.md": f"identical {SHARED_TERM} content"}
        _, body_a = _batch_upload(batch, auth_a, files)
        _, body_b = _batch_upload(batch, auth_b, files)
        _run_background_work()

        ids_a, ids_b = _b1_ids(docs, auth_a), _b1_ids(docs, auth_b)
        assert len(ids_a) == len(ids_b) == 1
        assert not ids_a & ids_b


# ---------------------------------------------------------------------------
# VAL-DOC-010 / VAL-DOC-013: another org's records answer like missing ones
# ---------------------------------------------------------------------------


class TestOtherOrgRecordsAreNotFound:
    def test_batch_job_reads(self, batch, a_batch, auth_b):
        job_id = a_batch["job_ids"][0]
        for path in (
            f"/api/v1/documents/batch/{job_id}",
            f"/api/v1/documents/batch/{job_id}/results",
        ):
            assert _get(batch, auth_b, path) == (
                404,
                {"error": "Job not found", "code": "not_found"},
            )
        assert _get(batch, auth_b, "/api/v1/documents/batch/job-missing") == (
            404,
            {"error": "Job not found", "code": "not_found"},
        )

    def test_batch_job_delete_leaves_job_in_place(self, batch, a_batch, auth_a, auth_b):
        job_id = a_batch["job_ids"][0]
        before = _get(batch, auth_a, f"/api/v1/documents/batch/{job_id}")

        status, body = _delete(batch, auth_b, f"/api/v1/documents/batch/{job_id}")

        assert (status, body) == (404, {"error": "Job not found", "code": "not_found"})
        assert _get(batch, auth_a, f"/api/v1/documents/batch/{job_id}") == before

    def test_document_chunks_and_context(self, batch, doc_a, auth_b):
        missing = {"error": "Document not found", "code": "not_found"}
        for view in ("chunks", "context"):
            assert _get(batch, auth_b, f"/api/v1/documents/{doc_a}/{view}") == (404, missing)
            assert _get(batch, auth_b, f"/api/v1/documents/nosuchdoc000001/{view}") == (
                404,
                missing,
            )

    def test_knowledge_job_status(self, batch, auth_a, auth_b):
        _, body = _batch_upload(batch, auth_a, {"k.md": SENTINEL_A}, process_knowledge=True)
        kp_job = body["knowledge_processing"]["job_ids"][0]

        status, own = _get(batch, auth_a, f"/api/v1/knowledge/jobs/{kp_job}")
        assert status == 200
        assert own["job_id"] == kp_job
        assert _get(batch, auth_b, f"/api/v1/knowledge/jobs/{kp_job}") == (
            404,
            {"error": "Knowledge job not found", "code": "not_found"},
        )

    def test_folder_reads(self, folders, a_folder, auth_b):
        folder_id = a_folder["folder_id"]
        missing = (404, {"error": "Folder not found", "code": "not_found"})
        for path in (
            f"/api/v1/documents/folders/{folder_id}",
            f"/api/v1/documents/folder/upload/{folder_id}/status",
            "/api/v1/documents/folders/folder-missing",
        ):
            assert _get(folders, auth_b, path) == missing

    def test_folder_delete_leaves_folder_in_place(self, folders, store, a_folder, auth_a, auth_b):
        folder_id = a_folder["folder_id"]
        before = _get(folders, auth_a, f"/api/v1/documents/folders/{folder_id}")

        status, body = _delete(folders, auth_b, f"/api/v1/documents/folders/{folder_id}")

        assert (status, body) == (404, {"error": "Folder not found", "code": "not_found"})
        assert _get(folders, auth_a, f"/api/v1/documents/folders/{folder_id}") == before
        assert all(store.get(doc_id) is not None for doc_id in a_folder["document_ids"])


# ---------------------------------------------------------------------------
# VAL-DOC-011: lists, stats and search hold only the caller org's records
# ---------------------------------------------------------------------------


class TestListsHoldOnlyTheCallerOrg:
    def test_processing_stats_count_only_own_jobs(self, batch, a_batch, auth_a, auth_b):
        _batch_upload(batch, auth_b, {"b-only.md": SENTINEL_B})
        _run_background_work()

        _, stats_a = _get(batch, auth_a, "/api/v1/documents/processing/stats")
        _, stats_b = _get(batch, auth_b, "/api/v1/documents/processing/stats")

        assert stats_a["processor"]["total_processed"] == 2
        assert stats_b["processor"]["total_processed"] == 1

    def test_knowledge_job_list_ignores_workspace_id(self, batch, auth_a, auth_b):
        _, body = _batch_upload(
            batch, auth_a, {"k.md": SENTINEL_A}, process_knowledge=True, workspace_id="shared-ws"
        )
        kp_job = body["knowledge_processing"]["job_ids"][0]

        _, list_a = _get(batch, auth_a, "/api/v1/knowledge/jobs")
        _, list_b = _get(batch, auth_b, "/api/v1/knowledge/jobs", {"workspace_id": ["shared-ws"]})

        assert [job["job_id"] for job in list_a["jobs"]] == [kp_job]
        assert list_b["jobs"] == []
        assert SENTINEL_A not in json.dumps(list_b)

    def test_search_finds_only_own_documents(self, query, doc_a, doc_b, doc_legacy, auth_a, auth_b):
        for auth, own, other in ((auth_a, doc_a, SENTINEL_B), (auth_b, doc_b, SENTINEL_A)):
            status, body = _get(query, auth, "/api/v1/documents/search", {"q": [SHARED_TERM]})
            assert status == 200
            assert [hit["document_id"] for hit in body["results"]] == [own]
            assert other not in json.dumps(body)
            assert SENTINEL_LEGACY not in json.dumps(body)

        _, body = _get(query, auth_b, "/api/v1/documents/search", {"q": [SENTINEL_A]})
        assert {hit["document_id"] for hit in body["results"]} <= {doc_b}
        assert SENTINEL_A not in json.dumps(body["results"])

    def test_folder_list(self, folders, a_folder, auth_a, auth_b):
        _, list_a = _get(folders, auth_a, "/api/v1/documents/folders")
        _, list_b = _get(folders, auth_b, "/api/v1/documents/folders")
        assert [f["folder_id"] for f in list_a["folders"]] == [a_folder["folder_id"]]
        assert list_b == {"folders": [], "count": 0}


# ---------------------------------------------------------------------------
# VAL-DOC-012: query/summarize/compare/extract treat other-org ids as missing
# ---------------------------------------------------------------------------

_QUERY_BODIES = {
    "/api/v1/documents/query": lambda ids: {"question": "What is the policy?", "document_ids": ids},
    "/api/v1/documents/summarize": lambda ids: {"document_ids": ids},
    "/api/v1/documents/compare": lambda ids: {"document_ids": ids},
    "/api/v1/documents/extract": lambda ids: {"document_ids": ids, "fields": {"p": "Policy?"}},
}


class TestQueriesNeverReadOtherOrgDocuments:
    @pytest.mark.parametrize("path", sorted(_QUERY_BODIES))
    def test_other_org_id_is_not_found_without_a_model_call(
        self, query, model_calls, doc_a, doc_b, auth_b, path
    ):
        for ids in ([doc_a], [doc_b, doc_a], [doc_a, doc_b]):
            status, body = _run(
                query.handle_post(path, {}, _json_request(auth_b, _QUERY_BODIES[path](ids)))
            )
            assert (status, body) == (404, {"error": "Document not found", "code": "not_found"})
        assert model_calls == []

    @pytest.mark.parametrize("path", sorted(_QUERY_BODIES))
    def test_unknown_owner_id_is_not_found_for_everyone(
        self, query, model_calls, doc_a, doc_legacy, auth_a, auth_b, path
    ):
        for auth in (auth_a, auth_b):
            status, _ = _run(
                query.handle_post(
                    path, {}, _json_request(auth, _QUERY_BODIES[path]([doc_a, doc_legacy]))
                )
            )
            assert status == 404
        assert model_calls == []

    @pytest.mark.parametrize("path", sorted(_QUERY_BODIES))
    def test_owner_queries_own_documents(
        self, query, model_calls, doc_a, doc_a2, doc_b, auth_a, path
    ):
        status, body = _run(
            query.handle_post(path, {}, _json_request(auth_a, _QUERY_BODIES[path]([doc_a, doc_a2])))
        )

        assert status == 200, body
        assert model_calls
        assert all(SENTINEL_A in prompt for prompt in model_calls)
        assert not any(SENTINEL_B in prompt for prompt in model_calls)
        assert SENTINEL_B not in json.dumps(body)

    def test_query_without_ids_reads_only_own_documents(
        self, query, model_calls, doc_a, doc_b, doc_legacy, auth_a
    ):
        status, body = _run(
            query.handle_post(
                "/api/v1/documents/query",
                {},
                _json_request(auth_a, {"question": f"What is the {SHARED_TERM} policy?"}),
            )
        )

        assert status == 200, body
        assert {c["document_id"] for c in body["citations"]} == {doc_a}
        assert len(model_calls) == 1
        assert SENTINEL_A in model_calls[0]
        assert SENTINEL_B not in model_calls[0]
        assert SENTINEL_LEGACY not in model_calls[0]


# ---------------------------------------------------------------------------
# VAL-DOC-014: anonymous callers get 401; a user without an org gets 403
# ---------------------------------------------------------------------------

_GET_ROUTES = [
    ("batch", "/api/v1/documents/batch/job-1"),
    ("batch", "/api/v1/documents/batch/job-1/results"),
    ("batch", "/api/v1/documents/doc-1/chunks"),
    ("batch", "/api/v1/documents/doc-1/context"),
    ("batch", "/api/v1/documents/processing/stats"),
    ("batch", "/api/v1/knowledge/jobs"),
    ("batch", "/api/v1/knowledge/jobs/kp-1"),
    ("query", "/api/v1/documents/search"),
    ("folders", "/api/v1/documents/folders"),
    ("folders", "/api/v1/documents/folders/f-1"),
    ("folders", "/api/v1/documents/folder/upload/f-1/status"),
]
_POST_ROUTES = [
    ("batch", "/api/v1/documents/batch"),
    ("query", "/api/v1/documents/query"),
    ("query", "/api/v1/documents/search"),
    ("query", "/api/v1/documents/summarize"),
    ("query", "/api/v1/documents/compare"),
    ("query", "/api/v1/documents/extract"),
    ("folders", "/api/v1/documents/folder/scan"),
    ("folders", "/api/v1/documents/folder/upload"),
]
_DELETE_ROUTES = [
    ("batch", "/api/v1/documents/batch/job-1"),
    ("folders", "/api/v1/documents/folders/f-1"),
]


class TestCallersWithoutAnOrg:
    @pytest.fixture
    def handlers(self, batch, query, folders) -> dict[str, Any]:
        return {"batch": batch, "query": query, "folders": folders}

    def _all_routes(self, handlers, auth, tmp_path):
        payload = {"path": str(tmp_path), "question": "q", "document_ids": ["a", "b"]}
        for name, path in _GET_ROUTES:
            yield path, _get(handlers[name], auth, path, {"q": ["x"]})
        for name, path in _POST_ROUTES:
            yield path, _run(handlers[name].handle_post(path, {}, _json_request(auth, payload)))
        for name, path in _DELETE_ROUTES:
            yield path, _delete(handlers[name], auth, path)

    def test_anonymous_gets_401_everywhere(self, handlers, model_calls, ctx, tmp_path):
        for path, (status, body) in self._all_routes(handlers, None, tmp_path):
            assert (path, status, body) == (path, 401, AUTH_REQUIRED)
        assert model_calls == []
        assert FolderUploadHandler._jobs == {}
        assert ctx["batch_processor"].get_stats()["queued_jobs"] == 0

    def test_user_without_org_gets_403_everywhere(self, handlers, auth_no_org, tmp_path):
        for path, (status, body) in self._all_routes(handlers, auth_no_org, tmp_path):
            assert (path, status, body["code"]) == (path, 403, "org_required")


# ---------------------------------------------------------------------------
# VAL-DOC-015: the owner keeps working on every derived route
# ---------------------------------------------------------------------------


class TestOwnerKeepsWorking:
    def test_batch_routes(self, batch, a_batch, doc_a, auth_a):
        job_id = a_batch["job_ids"][0]
        doc_id = a_batch["document_ids"][0]

        status, job = _get(batch, auth_a, f"/api/v1/documents/batch/{job_id}")
        assert status == 200
        assert job["status"] == "completed"
        assert _get(batch, auth_a, f"/api/v1/documents/{doc_id}/chunks")[0] == 200
        status, context = _get(batch, auth_a, f"/api/v1/documents/{doc_a}/context")
        assert status == 200
        assert SENTINEL_A in context["context"]

        status, body = _delete(batch, auth_a, f"/api/v1/documents/batch/{job_id}")
        assert (status, body) == (200, {"deleted": True, "job_id": job_id})
        assert _get(batch, auth_a, f"/api/v1/documents/batch/{job_id}")[0] == 404

    def test_queued_batch_job_can_be_cancelled(self, batch, auth_a):
        _, body = _batch_upload(batch, auth_a, {"later.md": "later"})
        job_id = body["job_ids"][0]

        assert _delete(batch, auth_a, f"/api/v1/documents/batch/{job_id}") == (
            200,
            {"cancelled": True, "job_id": job_id},
        )

    def test_folder_routes(self, folders, a_folder, auth_a, tmp_path):
        folder_id = a_folder["folder_id"]
        assert _get(folders, auth_a, f"/api/v1/documents/folders/{folder_id}")[0] == 200
        assert (
            _get(folders, auth_a, f"/api/v1/documents/folder/upload/{folder_id}/status")[0] == 200
        )

        status, scan = _run(
            folders.handle_post(
                "/api/v1/documents/folder/scan",
                {},
                _json_request(auth_a, {"path": str(tmp_path / "a-folder")}),
            )
        )
        assert status == 200, scan
        assert scan["statistics"]["included_count"] == 2

        status, body = _delete(folders, auth_a, f"/api/v1/documents/folders/{folder_id}")
        assert status == 200
        assert body["success"] is True
        assert folder_id not in FolderUploadHandler._jobs


# ---------------------------------------------------------------------------
# VAL-DOC-016: unknown-owner documents are invisible
# ---------------------------------------------------------------------------


class TestUnknownOwnerDocumentsAreInvisible:
    def test_hidden_on_derived_routes_and_never_deleted(
        self, docs, batch, query, store, doc_legacy, auth_a, auth_b
    ):
        for auth in (auth_a, auth_b):
            assert doc_legacy not in _b1_ids(docs, auth)
            for view in ("chunks", "context"):
                status, body = _get(batch, auth, f"/api/v1/documents/{doc_legacy}/{view}")
                assert status == 404
                assert SENTINEL_LEGACY not in json.dumps(body)
            _, search = _get(query, auth, "/api/v1/documents/search", {"q": [SENTINEL_LEGACY]})
            assert search["results"] == []
        assert (store.storage_dir / f"{doc_legacy}.json").exists()
