"""Folder scan and upload are confined to ARAGORA_ALLOWED_UPLOAD_DIRS (VAL-DOC-018).

The folder handler runs against a real ``DocumentStore`` on disk and real JWTs.
Without configured upload directories both routes refuse before reading the
request path; with them, a folder inside a configured directory works as before
and anything that resolves outside one is refused with one fixed answer,
whether or not it exists.
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

from aragora.documents.parsing import DocumentStore
from aragora.server.handlers.features import folder_upload
from aragora.server.handlers.features.folder_upload import FolderUploadHandler

pytestmark = pytest.mark.no_auto_auth

ENV = "ARAGORA_ALLOWED_UPLOAD_DIRS"
ORG_A = "org-a-upload-root"
ORG_B = "org-b-upload-root"
USER_A = "user-a-upload-root"
USER_B = "user-b-upload-root"
ROUTES = ["/api/v1/documents/folder/scan", "/api/v1/documents/folder/upload"]
NOT_CONFIGURED_CODE = "upload_dirs_not_configured"

_client_ips = (f"10.41.{n // 250}.{n % 250 + 1}" for n in itertools.count())


@pytest.fixture(autouse=True)
def _isolated_auth(monkeypatch):
    """Real JWTs and the stock (unset) static API token."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.server import auth as server_auth

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "upload-root-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)


class _DeferredThread:
    started: list[_DeferredThread] = []

    def __init__(self, target, args=(), kwargs=None, **_ignored):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self) -> None:
        _DeferredThread.started.append(self)


@pytest.fixture(autouse=True)
def _deferred_upload_work(monkeypatch):
    _DeferredThread.started = []
    fake_threading = SimpleNamespace(Thread=_DeferredThread, Lock=__import__("threading").Lock)
    monkeypatch.setattr(folder_upload, "threading", fake_threading)
    monkeypatch.delenv(ENV, raising=False)
    FolderUploadHandler._jobs.clear()
    yield
    FolderUploadHandler._jobs.clear()


def _run_background_work() -> None:
    while _DeferredThread.started:
        work = _DeferredThread.started.pop(0)
        work.target(*work.args, **work.kwargs)


def _bearer(user_id: str, org_id: str | None) -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token(user_id, f"{user_id}@example.test", org_id, "owner")


class _Request:
    def __init__(self, authorization: str | None, payload: dict[str, Any]):
        body = json.dumps(payload).encode()
        self.headers: dict[str, str] = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        if authorization is not None:
            self.headers["Authorization"] = authorization
        self.rfile = io.BytesIO(body)
        self.client_address = (next(_client_ips), 50123)


@pytest.fixture
def auth_a() -> str:
    return _bearer(USER_A, ORG_A)


@pytest.fixture
def auth_b() -> str:
    return _bearer(USER_B, ORG_B)


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    return DocumentStore(tmp_path / "data" / "documents")


@pytest.fixture
def folders(store) -> FolderUploadHandler:
    return FolderUploadHandler(server_context={"document_store": store})


@pytest.fixture
def upload_root(tmp_path: Path) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def a_folder(upload_root: Path) -> Path:
    folder = upload_root / "a-folder"
    folder.mkdir()
    (folder / "notes.md").write_text("upload root notes")
    (folder / "plan.txt").write_text("upload root plan")
    return folder


def _post(folders: FolderUploadHandler, auth: str | None, route: str, payload: dict[str, Any]):
    result = asyncio.run(folders.handle_post(route, {}, _Request(auth, payload)))
    assert result is not None
    return result.status_code, json.loads(result.body.decode("utf-8"))


def _doc_ids(store: DocumentStore) -> set[str]:
    return {path.stem for path in store.storage_dir.glob("*.json")}


# ---------------------------------------------------------------------------
# Not configured: refused before the request path is looked at
# ---------------------------------------------------------------------------


class TestNotConfigured:
    @pytest.mark.parametrize("route", ROUTES)
    @pytest.mark.parametrize(
        "value", [None, "", " , ", "/nonexistent/aragora-upload-root-xyz", "relative/uploads"]
    )
    def test_refused_with_clear_error_and_no_side_effect(
        self, monkeypatch, folders, store, auth_a, a_folder, route, value, tmp_path
    ):
        if value is not None:
            monkeypatch.setenv(ENV, value)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "relative" / "uploads").mkdir(parents=True)

        def _must_not_run(*_args, **_kwargs):
            raise AssertionError("the request path must not be inspected")

        monkeypatch.setattr(folder_upload, "_validate_upload_path", _must_not_run)
        before = _doc_ids(store)

        status, body = _post(folders, auth_a, route, {"path": str(a_folder)})

        assert status == 403
        assert body["code"] == NOT_CONFIGURED_CODE
        assert "ARAGORA_ALLOWED_UPLOAD_DIRS" in body["error"]
        assert FolderUploadHandler._jobs == {}
        assert _DeferredThread.started == []
        assert _doc_ids(store) == before

    @pytest.mark.parametrize("route", ROUTES)
    def test_refused_even_without_a_path(self, folders, auth_a, route):
        status, body = _post(folders, auth_a, route, {})
        assert status == 403
        assert body["code"] == NOT_CONFIGURED_CODE

    @pytest.mark.parametrize("route", ROUTES)
    def test_anonymous_still_gets_401(self, folders, a_folder, route):
        status, body = _post(folders, None, route, {"path": str(a_folder)})
        assert status == 401
        assert body["code"] == "auth_required"
        assert FolderUploadHandler._jobs == {}

    @pytest.mark.parametrize("route", ROUTES)
    def test_user_without_org_still_gets_org_required(self, folders, a_folder, route):
        status, body = _post(folders, _bearer("user-loner", None), route, {"path": str(a_folder)})
        assert status == 403
        assert body["code"] == "org_required"
        assert FolderUploadHandler._jobs == {}


# ---------------------------------------------------------------------------
# Configured: inside works, outside is refused identically
# ---------------------------------------------------------------------------


@pytest.fixture
def configured(monkeypatch, upload_root: Path) -> Path:
    monkeypatch.setenv(ENV, str(upload_root))
    return upload_root


class TestInsideTheRoot:
    def test_scan_lists_the_folder(self, configured, folders, auth_a, a_folder):
        status, body = _post(folders, auth_a, ROUTES[0], {"path": str(a_folder)})
        assert status == 200, body
        assert body["statistics"]["included_count"] == 2
        assert sorted(f["path"] for f in body["included_files"]) == ["notes.md", "plan.txt"]
        assert FolderUploadHandler._jobs == {}

    def test_upload_stores_documents_under_the_callers_org(
        self, configured, folders, store, auth_a, a_folder
    ):
        status, body = _post(folders, auth_a, ROUTES[1], {"path": str(a_folder)})
        assert status == 200, body
        _run_background_work()

        job = FolderUploadHandler._jobs[body["folder_id"]]
        assert job.status.value == "completed"
        assert job.org_id == ORG_A
        assert job.root_path == str(a_folder)
        assert len(job.document_ids) == 2
        for doc_id in job.document_ids:
            doc = store.get(doc_id)
            assert doc.org_id == ORG_A
            assert doc.created_by == USER_A
        assert store.list_for_org(ORG_B) == []

    def test_any_configured_directory_is_accepted(
        self, monkeypatch, folders, auth_a, a_folder, tmp_path
    ):
        other = tmp_path / "other-root"
        other.mkdir()
        monkeypatch.setenv(ENV, f"{other}, {a_folder.parent}")
        status, _ = _post(folders, auth_a, ROUTES[0], {"path": str(a_folder)})
        assert status == 200

    @pytest.mark.parametrize("route", ROUTES)
    def test_missing_path_inside_the_root_is_404(self, configured, folders, auth_a, route):
        status, _ = _post(folders, auth_a, route, {"path": str(configured / "missing")})
        assert status == 404
        assert FolderUploadHandler._jobs == {}

    @pytest.mark.parametrize("route", ROUTES)
    def test_file_inside_the_root_is_400(self, configured, folders, auth_a, a_folder, route):
        status, _ = _post(folders, auth_a, route, {"path": str(a_folder / "notes.md")})
        assert status == 400
        assert FolderUploadHandler._jobs == {}


class TestOutsideTheRoot:
    @pytest.fixture
    def outside_paths(self, tmp_path: Path, configured: Path, store) -> dict[str, Path]:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("outside the upload root")
        escape = configured / "escape-link"
        escape.symlink_to(outside, target_is_directory=True)
        return {
            "existing": outside,
            "missing": tmp_path / "outside-missing" / "deeper",
            "document_store": store.storage_dir,
            "symlink_escape": escape,
            "dotdot_escape": configured / ".." / "outside",
            "filesystem_root": Path("/"),
        }

    @pytest.mark.parametrize("route", ROUTES)
    def test_every_outside_path_gets_the_same_refusal(
        self, folders, store, auth_a, auth_b, outside_paths, route
    ):
        from aragora.documents.parsing import parse_document

        store.add(parse_document(b"stored by B", "b.md", org_id=ORG_B, created_by=USER_B))
        before = _doc_ids(store)
        answers = {}
        for name, path in outside_paths.items():
            answers[name] = _post(folders, auth_a, route, {"path": str(path)})

        statuses = {name: status for name, (status, _) in answers.items()}
        assert set(statuses.values()) == {403}, statuses
        bodies = {json.dumps(body, sort_keys=True) for _, body in answers.values()}
        assert len(bodies) == 1, answers
        body = answers["existing"][1]
        assert body["code"] == "path_not_allowed"
        assert "outside" not in body["error"]
        assert FolderUploadHandler._jobs == {}
        assert _DeferredThread.started == []
        assert _doc_ids(store) == before
        assert store.list_for_org(ORG_A) == []


# ---------------------------------------------------------------------------
# The accessor reads the environment on every call
# ---------------------------------------------------------------------------


class TestAccessor:
    def test_unset_and_empty_yield_nothing(self, monkeypatch):
        assert folder_upload.get_allowed_upload_dirs() == []
        monkeypatch.setenv(ENV, "")
        assert folder_upload.get_allowed_upload_dirs() == []

    def test_skips_relative_missing_and_file_entries(self, monkeypatch, tmp_path):
        good = tmp_path / "good"
        good.mkdir()
        a_file = tmp_path / "file.txt"
        a_file.write_text("x")
        monkeypatch.setenv(ENV, f"relative, {tmp_path / 'missing'}, {a_file}, {good}")
        assert folder_upload.get_allowed_upload_dirs() == [good.resolve()]

    def test_reflects_changes_without_reimport(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV, str(tmp_path))
        assert folder_upload.get_allowed_upload_dirs() == [tmp_path.resolve()]
        monkeypatch.delenv(ENV)
        assert folder_upload.get_allowed_upload_dirs() == []
