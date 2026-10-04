"""Org scope on the core document routes (inventory B1-B5).

``DocumentHandler`` runs against a real ``DocumentStore`` on disk and real
JWTs. Users of two orgs (A and B), a user without an org and an anonymous
caller exercise list (B1), get/full text (B2), upload (B3, raw and
multipart) and delete (B4). Another org's document and an unknown-owner
(pre-ownership) document answer exactly like a missing one, and refused
requests leave the store, the upload rate limiter and the request body
untouched. Formats (B5) holds no tenant data and stays as it is.
"""

from __future__ import annotations

import hashlib
import io
import itertools
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.documents.parsing import DocumentStore, ParsedDocument, generate_doc_id
from aragora.server.handlers.features.documents import DocumentHandler

pytestmark = pytest.mark.no_auto_auth

ORG_A = "org-a-documents"
ORG_B = "org-b-documents"
SENTINEL = "DOC-ISOLATION-SENTINEL-4471"
CONTENT = f"# Vendor policy\n\nVendors must rotate keys yearly.\nSentinel: {SENTINEL}\n".encode()
FILENAME = "vendor-policy.md"
NOT_FOUND_BODY = {"error": "Document not found", "code": "not_found"}
AUTH_REQUIRED_BODY = {"error": "Authentication required", "code": "auth_required"}
ORG_REQUIRED_BODY = {
    "error": "This resource belongs to an organization; sign in as a member of one",
    "code": "org_required",
}
NO_KNOWLEDGE = {"process_knowledge": ["false"]}

_client_ips = (f"10.20.{n // 250}.{n % 250 + 1}" for n in itertools.count())


@pytest.fixture(autouse=True)
def _isolated_auth(monkeypatch):
    """Real JWTs, the stock (unset) static API token and an empty upload limiter."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.server import auth as server_auth

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "documents-isolation-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)

    DocumentHandler._upload_counts.clear()
    yield
    DocumentHandler._upload_counts.clear()


def _bearer(user_id: str, org_id: str | None) -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token(user_id, f"{user_id}@example.test", org_id, "member")


@pytest.fixture
def user_a() -> str:
    return _bearer("user-a", ORG_A)


@pytest.fixture
def user_b() -> str:
    return _bearer("user-b", ORG_B)


@pytest.fixture
def user_no_org() -> str:
    return _bearer("user-loner", None)


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    return DocumentStore(tmp_path / "documents")


@pytest.fixture
def docs(store: DocumentStore) -> DocumentHandler:
    return DocumentHandler(server_context={"document_store": store})


class _Request:
    """The parts of the HTTP request handler that DocumentHandler reads."""

    def __init__(self, authorization: str | None, body: bytes = b"", **headers: str):
        self.headers: dict[str, str] = {"Content-Length": str(len(body)), **headers}
        if authorization is not None:
            self.headers["Authorization"] = authorization
        self.rfile = io.BytesIO(body)
        self.client_address = (next(_client_ips), 50123)


def _result(result: Any) -> tuple[int, dict[str, Any]]:
    assert result is not None
    return result.status_code, json.loads(result.body.decode("utf-8"))


def _list(docs: DocumentHandler, auth: str | None) -> tuple[int, dict[str, Any]]:
    return _result(docs.handle("/api/v1/documents", {}, _Request(auth)))


def _get(docs: DocumentHandler, auth: str | None, doc_id: str) -> tuple[int, dict[str, Any]]:
    return _result(docs.handle(f"/api/v1/documents/{doc_id}", {}, _Request(auth)))


def _delete(docs: DocumentHandler, auth: str | None, doc_id: str) -> tuple[int, dict[str, Any]]:
    return _result(docs.handle_delete(f"/api/v1/documents/{doc_id}", {}, _Request(auth)))


def _raw_request(auth: str | None, content: bytes = CONTENT, filename: str = FILENAME) -> _Request:
    return _Request(auth, content, **{"Content-Type": "text/markdown", "X-Filename": filename})


def _multipart_request(
    auth: str | None,
    content: bytes = CONTENT,
    filename: str = FILENAME,
    *,
    boundary: str = "------------------------d74496d66958873e",
    trailing_fields: dict[str, str] | None = None,
    truncate_by: int = 0,
) -> _Request:
    """The body curl -F "file=@x;type=text/markdown" (or a browser FormData) sends."""
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
    ).encode() + content
    for name, value in (trailing_fields or {}).items():
        body += (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}'
        ).encode()
    body += f"\r\n--{boundary}--\r\n".encode()
    request = _Request(auth, body, **{"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if truncate_by:
        request.rfile = io.BytesIO(body[:-truncate_by])
    return request


def _upload(
    docs: DocumentHandler, request: _Request, query: dict[str, list[str]] | None = None
) -> tuple[int, dict[str, Any]]:
    return _result(docs.handle_post("/api/v1/documents/upload", query or NO_KNOWLEDGE, request))


def _upload_id(docs: DocumentHandler, request: _Request) -> str:
    status, body = _upload(docs, request)
    assert status == 200, body
    assert body["success"] is True
    return body["document"]["id"]


def _stored(store: DocumentStore, doc_id: str) -> dict[str, Any]:
    return json.loads((store.storage_dir / f"{doc_id}.json").read_text())


def _write_legacy_document(store: DocumentStore, doc_id: str = "legacy0000000001") -> str:
    """A document saved before ownership existed: no org, creator or content hash."""
    payload = ParsedDocument(
        id=doc_id, filename="legacy.md", content_type="text/markdown", text=f"old {SENTINEL}"
    ).to_dict()
    for key in ("org_id", "created_by", "content_sha256"):
        payload.pop(key, None)
    (store.storage_dir / f"{doc_id}.json").write_text(json.dumps(payload))
    return doc_id


# ---------------------------------------------------------------------------
# VAL-DOC-001 / VAL-DOC-002: uploads record the owner and multipart works
# ---------------------------------------------------------------------------


class TestUploadRecordsOwner:
    def test_raw_upload_records_org_creator_and_content_hash(self, docs, store, user_a):
        doc_id = _upload_id(docs, _raw_request(user_a))

        stored = _stored(store, doc_id)
        assert stored["org_id"] == ORG_A
        assert stored["created_by"] == "user-a"
        assert stored["content_sha256"] == hashlib.sha256(CONTENT).hexdigest()
        assert doc_id == generate_doc_id(CONTENT, FILENAME, ORG_A)

    def test_curl_style_multipart_upload_succeeds_and_keeps_the_exact_text(
        self, docs, store, user_a
    ):
        status, body = _upload(docs, _multipart_request(user_a))

        assert status == 200, body
        assert body["success"] is True
        doc_id = body["document"]["id"]
        assert body["document"]["filename"] == FILENAME
        stored = _stored(store, doc_id)
        assert stored["org_id"] == ORG_A
        assert stored["created_by"] == "user-a"
        assert stored["content_sha256"] == hashlib.sha256(CONTENT).hexdigest()

        status, fetched = _get(docs, user_a, doc_id)
        assert status == 200
        assert fetched["text"] == CONTENT.decode()

    def test_browser_style_multipart_with_extra_fields_succeeds(self, docs, user_a):
        request = _multipart_request(
            user_a,
            boundary="----WebKitFormBoundary7MA4YWxkTrZu0gW",
            trailing_fields={"action": "document"},
        )

        status, body = _upload(docs, request)

        assert status == 200, body
        status, fetched = _get(docs, user_a, body["document"]["id"])
        assert status == 200
        assert fetched["text"] == CONTENT.decode()

    def test_multipart_file_ending_in_dashes_keeps_its_bytes(self, docs, user_a):
        content = b"divider below\n--"

        doc_id = _upload_id(docs, _multipart_request(user_a, content, "dashes.txt"))

        assert _get(docs, user_a, doc_id)[1]["text"] == content.decode()

    def test_truncated_multipart_body_is_rejected(self, docs, store, user_a):
        status, body = _upload(docs, _multipart_request(user_a, truncate_by=10))

        assert status == 400
        assert body["error_code"] == "corrupted_upload"
        assert list(store.storage_dir.glob("*.json")) == []

    def test_truncated_raw_body_is_still_rejected(self, docs, store, user_a):
        request = _raw_request(user_a)
        request.headers["Content-Length"] = str(len(CONTENT) + 10)

        status, body = _upload(docs, request)

        assert status == 400
        assert body["error_code"] == "corrupted_upload"
        assert list(store.storage_dir.glob("*.json")) == []

    def test_knowledge_processing_receives_the_callers_org(self, docs, user_a):
        knowledge = MagicMock()
        knowledge.process_uploaded_document.return_value = {
            "knowledge_processing": {"status": "queued", "job_id": "job-1"}
        }

        with patch.dict("sys.modules", {"aragora.knowledge.integration": knowledge}):
            status, _ = _upload(docs, _raw_request(user_a), {"process_knowledge": ["true"]})

        assert status == 200
        metadata = knowledge.process_uploaded_document.call_args.kwargs["metadata"]
        assert metadata["org_id"] == ORG_A
        assert metadata["user_id"] == "user-a"


# ---------------------------------------------------------------------------
# VAL-DOC-003..006: separate records per org; other org's docs are not found
# ---------------------------------------------------------------------------


class TestCrossOrgIsolation:
    def test_identical_uploads_from_two_orgs_create_two_records(self, docs, store, user_a, user_b):
        id_a = _upload_id(docs, _raw_request(user_a))
        id_b = _upload_id(docs, _multipart_request(user_b))

        assert id_a != id_b
        assert _get(docs, user_a, id_a)[0] == 200
        assert _get(docs, user_a, id_b) == (404, NOT_FOUND_BODY)
        assert _get(docs, user_b, id_b)[0] == 200
        assert _get(docs, user_b, id_a) == (404, NOT_FOUND_BODY)
        assert _stored(store, id_a)["org_id"] == ORG_A
        assert _stored(store, id_b)["org_id"] == ORG_B

    def test_other_org_read_is_indistinguishable_from_missing(self, docs, user_a, user_b):
        doc_id = _upload_id(docs, _raw_request(user_a))

        other_org = docs.handle(f"/api/v1/documents/{doc_id}", {}, _Request(user_b))
        missing = docs.handle("/api/v1/documents/0123456789abcdef", {}, _Request(user_b))

        assert other_org.status_code == missing.status_code == 404
        assert other_org.body == missing.body
        assert SENTINEL.encode() not in other_org.body
        assert doc_id.encode() not in other_org.body

    def test_lists_exclude_other_org_documents(self, docs, user_a, user_b):
        id_a = _upload_id(docs, _raw_request(user_a))
        id_b = _upload_id(docs, _raw_request(user_b, b"B's own notes", "b-notes.md"))

        status_a, list_a = _list(docs, user_a)
        status_b, list_b = _list(docs, user_b)

        assert status_a == status_b == 200
        assert [d["id"] for d in list_a["documents"]] == [id_a]
        assert list_a["count"] == 1
        assert [d["id"] for d in list_b["documents"]] == [id_b]
        assert list_b["count"] == 1

    def test_other_org_delete_is_not_found_and_changes_nothing(self, docs, store, user_a, user_b):
        doc_id = _upload_id(docs, _raw_request(user_a))
        before = _get(docs, user_a, doc_id)

        other_org = docs.handle_delete(f"/api/v1/documents/{doc_id}", {}, _Request(user_b))
        missing = docs.handle_delete("/api/v1/documents/0123456789abcdef", {}, _Request(user_b))

        assert other_org.status_code == missing.status_code == 404
        assert other_org.body == missing.body
        assert json.loads(other_org.body) == NOT_FOUND_BODY
        assert (store.storage_dir / f"{doc_id}.json").exists()
        assert _get(docs, user_a, doc_id) == before
        assert before[1]["text"] == CONTENT.decode()


# ---------------------------------------------------------------------------
# Unknown-owner documents written before ownership existed
# ---------------------------------------------------------------------------


class TestLegacyDocumentsWithoutOwner:
    def test_invisible_to_every_org(self, docs, store, user_a, user_b):
        legacy_id = _write_legacy_document(store)

        for user in (user_a, user_b):
            assert _get(docs, user, legacy_id) == (404, NOT_FOUND_BODY)
            assert legacy_id not in {d["id"] for d in _list(docs, user)[1]["documents"]}

    def test_cannot_be_deleted(self, docs, store, user_a, user_b):
        legacy_id = _write_legacy_document(store)

        for user in (user_a, user_b):
            assert _delete(docs, user, legacy_id) == (404, NOT_FOUND_BODY)
        assert (store.storage_dir / f"{legacy_id}.json").exists()


# ---------------------------------------------------------------------------
# VAL-DOC-007: anonymous callers; users without an org
# ---------------------------------------------------------------------------


class TestCallerWithoutOrgScope:
    @pytest.fixture
    def seeded(self, docs, user_a) -> str:
        return _upload_id(docs, _raw_request(user_a))

    @pytest.mark.parametrize(
        ("caller", "expected"),
        [("anonymous", (401, AUTH_REQUIRED_BODY)), ("no_org", (403, ORG_REQUIRED_BODY))],
    )
    def test_list_get_and_delete_are_refused(
        self, docs, store, seeded, user_no_org, caller, expected
    ):
        auth = None if caller == "anonymous" else user_no_org

        assert _list(docs, auth) == expected
        assert _get(docs, auth, seeded) == expected
        assert _get(docs, auth, "0123456789abcdef") == expected
        assert _delete(docs, auth, seeded) == expected
        assert (store.storage_dir / f"{seeded}.json").exists()

    @pytest.mark.parametrize("shape", ["raw", "multipart"])
    @pytest.mark.parametrize(
        ("caller", "expected"),
        [("anonymous", (401, AUTH_REQUIRED_BODY)), ("no_org", (403, ORG_REQUIRED_BODY))],
    )
    def test_upload_is_refused_before_reading_the_body(
        self, docs, store, user_no_org, shape, caller, expected
    ):
        auth = None if caller == "anonymous" else user_no_org
        request = _raw_request(auth) if shape == "raw" else _multipart_request(auth)

        assert _upload(docs, request) == expected
        assert request.rfile.tell() == 0
        assert list(store.storage_dir.glob("*.json")) == []
        assert dict(DocumentHandler._upload_counts) == {}

    def test_formats_needs_no_org(self, docs):
        status, body = _result(docs.handle("/api/v1/documents/formats", {}, _Request(None)))

        assert status == 200
        assert "formats" in body


# ---------------------------------------------------------------------------
# VAL-DOC-008: the owning org keeps full access
# ---------------------------------------------------------------------------


class TestOwnerAccess:
    def test_owner_lists_reads_and_deletes(self, docs, store, user_a):
        raw_id = _upload_id(docs, _raw_request(user_a))
        throwaway_id = _upload_id(docs, _multipart_request(user_a, b"temporary", "throwaway.txt"))

        listed = {d["id"] for d in _list(docs, user_a)[1]["documents"]}
        assert listed == {raw_id, throwaway_id}

        status, fetched = _get(docs, user_a, raw_id)
        assert status == 200
        assert fetched["text"] == CONTENT.decode()
        assert fetched["org_id"] == ORG_A

        status, deleted = _delete(docs, user_a, throwaway_id)
        assert status == 200
        assert deleted["success"] is True
        assert _get(docs, user_a, throwaway_id) == (404, NOT_FOUND_BODY)
        assert not (store.storage_dir / f"{throwaway_id}.json").exists()
        assert {d["id"] for d in _list(docs, user_a)[1]["documents"]} == {raw_id}

    def test_another_user_of_the_same_org_shares_the_documents(self, docs, user_a):
        doc_id = _upload_id(docs, _raw_request(user_a))
        teammate = _bearer("user-a2", ORG_A)

        assert _get(docs, teammate, doc_id)[0] == 200
        assert doc_id in {d["id"] for d in _list(docs, teammate)[1]["documents"]}
