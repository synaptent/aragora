"""Folder scan and upload are confined to the caller org's ARAGORA_ORG_IMPORT_ROOTS (VAL-DOC-018).

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
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.documents.parsing import DocumentStore, parse_document
from aragora.documents.folder import import_roots
from aragora.server.handlers.features import folder_upload
from aragora.server.handlers.features.folder_upload import FolderUploadHandler

pytestmark = pytest.mark.no_auto_auth

ENV = "ARAGORA_ORG_IMPORT_ROOTS"
ORG_A = "org-a-upload-root"
ORG_B = "org-b-upload-root"
USER_A = "user-a-upload-root"
USER_B = "user-b-upload-root"
ROUTES = ["/api/v1/documents/folder/scan", "/api/v1/documents/folder/upload"]
NOT_CONFIGURED_CODE = "import_roots_not_configured"

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
def _deferred_upload_work(monkeypatch, tmp_path):
    _DeferredThread.started = []
    fake_threading = SimpleNamespace(Thread=_DeferredThread, Lock=threading.Lock)
    monkeypatch.setattr(folder_upload, "threading", fake_threading)
    for name in (ENV, "ARAGORA_ALLOWED_UPLOAD_DIRS", *import_roots.SECRET_FILE_ENV_VARS):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "app-data").mkdir()
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path / "app-data"))
    FolderUploadHandler._jobs.clear()
    yield
    FolderUploadHandler._jobs.clear()


def _run_background_work() -> None:
    """Run each deferred job on its own joined thread, as production does, re-raising failures."""
    while _DeferredThread.started:
        work, failures = _DeferredThread.started.pop(0), []

        def _job(work=work) -> None:
            try:
                work.target(*work.args, **work.kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the test thread below
                failures.append(exc)

        thread = threading.Thread(target=_job, daemon=True)
        thread.start()
        thread.join(timeout=60)
        assert not thread.is_alive(), "background upload job did not finish"
        if failures:
            raise failures[0]


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
def folders(store, tmp_path: Path) -> FolderUploadHandler:
    ctx = {"document_store": store, "nomic_dir": tmp_path / "nomic"}
    return FolderUploadHandler(server_context=ctx)


@pytest.fixture
def upload_root(tmp_path: Path) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def b_root(tmp_path: Path) -> Path:
    (tmp_path / "b-uploads").mkdir()
    return (tmp_path / "b-uploads").resolve()


@pytest.fixture
def a_folder(upload_root: Path) -> Path:
    folder = upload_root / "a-folder"
    folder.mkdir()
    (folder / "notes.md").write_text("upload root notes")
    (folder / "plan.txt").write_text("upload root plan")
    return folder


def _configure(monkeypatch, mapping: dict[str, list[Path]]) -> None:
    monkeypatch.setenv(ENV, json.dumps({org: [str(p) for p in ps] for org, ps in mapping.items()}))


def _post(folders: FolderUploadHandler, auth: str | None, route: str, payload: dict[str, Any]):
    result = asyncio.run(folders.handle_post(route, {}, _Request(auth, payload)))
    assert result is not None
    return result.status_code, json.loads(result.body.decode("utf-8"))


def _doc_ids(store: DocumentStore) -> set[str]:
    return {path.stem for path in store.storage_dir.glob("*.json")}


# ---------------------------------------------------------------------------
# Not configured: refused before the request path is looked at
# ---------------------------------------------------------------------------


NOT_CONFIGURED = {
    "unset": None,
    "empty": "",
    "empty_object": "{}",
    "invalid_json": "{not json",
    "not_an_object": lambda a, b: json.dumps([str(a)]),
    "string_not_list": lambda a, b: json.dumps({ORG_A: str(a)}),
    "relative_root": lambda a, b: json.dumps({ORG_A: ["uploads"]}),
    "missing_root": lambda a, b: json.dumps({ORG_A: [str(a / "missing")]}),
    "other_org_only": lambda a, b: json.dumps({ORG_B: [str(b)]}),
}


class TestNotConfigured:
    @pytest.mark.parametrize("route", ROUTES)
    @pytest.mark.parametrize("case", sorted(NOT_CONFIGURED))
    def test_refused_with_clear_error_and_no_side_effect(
        self, monkeypatch, folders, store, auth_a, b_root, a_folder, route, case, tmp_path
    ):
        value = NOT_CONFIGURED[case]
        if value is not None:
            monkeypatch.setenv(ENV, value(a_folder.parent, b_root) if callable(value) else value)
        monkeypatch.chdir(tmp_path)

        def _must_not_run(*_args, **_kwargs):
            raise AssertionError("the request path must not be inspected")

        monkeypatch.setattr(folder_upload, "_validate_upload_path", _must_not_run)
        before = _doc_ids(store)

        status, body = _post(folders, auth_a, route, {"path": str(a_folder)})

        assert status == 403
        assert body["code"] == NOT_CONFIGURED_CODE
        assert ENV in body["error"]
        assert FolderUploadHandler._jobs == {}
        assert _DeferredThread.started == []
        assert _doc_ids(store) == before

    @pytest.mark.parametrize("route", ROUTES)
    def test_legacy_upload_dirs_alone_authorize_nothing(
        self, monkeypatch, caplog, folders, auth_a, upload_root, a_folder, route
    ):
        monkeypatch.setenv("ARAGORA_ALLOWED_UPLOAD_DIRS", str(upload_root))
        with caplog.at_level(logging.WARNING, logger=import_roots.__name__):
            status, body = _post(folders, auth_a, route, {"path": str(a_folder)})
        assert (status, body["code"]) == (403, NOT_CONFIGURED_CODE)
        assert "ARAGORA_ALLOWED_UPLOAD_DIRS" in caplog.text
        assert FolderUploadHandler._jobs == {}

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
def configured(monkeypatch, upload_root: Path, b_root: Path) -> Path:
    _configure(monkeypatch, {ORG_A: [upload_root], ORG_B: [b_root]})
    return upload_root


class TestInsideTheRoot:
    def test_scan_lists_the_folder(self, configured, folders, auth_a, auth_b, b_root, a_folder):
        status, body = _post(folders, auth_a, ROUTES[0], {"path": str(a_folder)})
        assert status == 200, body
        assert body["statistics"]["included_count"] == 2
        assert sorted(f["path"] for f in body["included_files"]) == ["notes.md", "plan.txt"]
        assert _post(folders, auth_b, ROUTES[0], {"path": str(b_root)})[0] == 200
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

    def test_background_job_leaves_the_main_thread_event_loop_open(
        self, configured, folders, auth_a, a_folder
    ):
        status, body = _post(folders, auth_a, ROUTES[1], {"path": str(a_folder)})
        assert status == 200, body
        policy = asyncio.get_event_loop_policy()
        try:
            previous = policy.get_event_loop()
        except RuntimeError:
            previous = None
        main_loop = asyncio.new_event_loop()
        policy.set_event_loop(main_loop)
        try:
            _run_background_work()
            assert policy.get_event_loop() is main_loop
            assert main_loop.run_until_complete(asyncio.sleep(0, "open")) == "open"
        finally:
            policy.set_event_loop(previous)
            main_loop.close()
        assert FolderUploadHandler._jobs[body["folder_id"]].status.value == "completed"

    def test_an_org_may_have_several_roots(self, monkeypatch, folders, auth_a, b_root, a_folder):
        _configure(monkeypatch, {ORG_A: [b_root, a_folder.parent]})
        status, _ = _post(folders, auth_a, ROUTES[0], {"path": str(a_folder)})
        assert status == 200

    @pytest.mark.parametrize("follow", [False, True])
    def test_entries_resolving_outside_the_folder_are_skipped(
        self, configured, folders, store, auth_a, b_root, a_folder, tmp_path, follow
    ):
        (tmp_path / "secret.md").write_text("outside secret")
        (a_folder / "linked.md").symlink_to(tmp_path / "secret.md")
        (a_folder / "linked-dir").symlink_to(b_root, target_is_directory=True)
        payload = {"path": str(a_folder), "config": {"followSymlinks": follow}}

        status, scan = _post(folders, auth_a, ROUTES[0], payload)
        assert status == 200, scan
        assert "linked" not in json.dumps(scan)
        assert sorted(f["path"] for f in scan["included_files"]) == ["notes.md", "plan.txt"]

        status, body = _post(folders, auth_a, ROUTES[1], payload)
        assert status == 200, body
        _run_background_work()
        docs = [store.get(d) for d in FolderUploadHandler._jobs[body["folder_id"]].document_ids]
        assert sorted(doc.filename for doc in docs) == ["notes.md", "plan.txt"]
        assert not any("outside secret" in doc.text for doc in docs)

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
    def outside_paths(self, tmp_path: Path, configured: Path, b_root, store) -> dict[str, Any]:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("outside the upload root")
        (b_root / "b-folder").mkdir()
        escape = configured / "escape-link"
        escape.symlink_to(outside, target_is_directory=True)
        return {
            "existing": ("a", outside),
            "missing": ("a", tmp_path / "outside-missing" / "deeper"),
            "data_dir": ("a", tmp_path / "app-data"),
            "document_store": ("a", store.storage_dir),
            "b_root": ("a", b_root),
            "b_folder": ("a", b_root / "b-folder"),
            "b_missing": ("a", b_root / "missing"),
            "symlink_escape": ("a", escape),
            "dotdot_escape": ("a", configured / ".." / "outside"),
            "filesystem_root": ("a", Path("/")),
            "a_root_for_b": ("b", configured),
            "a_missing_for_b": ("b", configured / "missing"),
        }

    @pytest.mark.parametrize("route", ROUTES)
    def test_every_outside_path_gets_the_same_refusal(
        self, folders, store, auth_a, auth_b, outside_paths, route
    ):
        store.add(parse_document(b"stored by B", "b.md", org_id=ORG_B, created_by=USER_B))
        before = _doc_ids(store)
        auth = {"a": auth_a, "b": auth_b}
        answers = {}
        for name, (caller, path) in outside_paths.items():
            answers[name] = _post(folders, auth[caller], route, {"path": str(path)})

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


B_SECRET = "org b folder secret text"


def _swap_for_link(path: Path, target: Path) -> None:
    """Move ``path`` aside and put a symlink to ``target`` in its place."""
    path.rename(path.with_name(path.name + ".orig"))
    path.symlink_to(target, target_is_directory=target.is_dir())


def _swap_when_scanned(monkeypatch, swap) -> None:
    from aragora.documents.folder.scanner import FolderScanner

    original = FolderScanner.scan

    async def scan(self, root_path):
        swap()
        return await original(self, root_path)

    monkeypatch.setattr(FolderScanner, "scan", scan)


def _swap_before_open(monkeypatch, filename: str, swap) -> None:
    """Run ``swap`` once, after the job checked ``filename`` and before it opens it."""
    original, pending = folder_upload.validate_file_upload, [swap]

    def validate(*args, **kwargs):
        if kwargs.get("filename") == filename and pending:
            pending.pop()()
        return original(*args, **kwargs)

    monkeypatch.setattr(folder_upload, "validate_file_upload", validate)


def _stored_text(store: DocumentStore) -> str:
    return " ".join(path.read_text() for path in store.storage_dir.glob("*.json"))


class TestConfinementAfterTheRequest:
    @pytest.fixture
    def b_folder(self, b_root: Path) -> Path:
        (b_root / "b-folder").mkdir()
        for name in ("notes.md", "inner.md", "b-only.md"):
            (b_root / "b-folder" / name).write_text(B_SECRET)
        return b_root / "b-folder"

    @pytest.mark.parametrize("when", ["before_the_job", "when_scanned"])
    def test_folder_swapped_for_a_link_after_the_request_imports_nothing(
        self, monkeypatch, configured, folders, store, auth_a, a_folder, b_folder, when
    ):
        status, body = _post(folders, auth_a, ROUTES[1], {"path": str(a_folder)})
        assert status == 200, body
        swap = lambda: _swap_for_link(a_folder, b_folder)  # noqa: E731
        swap() if when == "before_the_job" else _swap_when_scanned(monkeypatch, swap)

        _run_background_work()

        job = FolderUploadHandler._jobs[body["folder_id"]]
        assert job.status.value == "failed"
        assert job.document_ids == [] and store.list_for_org(ORG_A) == []
        assert B_SECRET not in _stored_text(store)

    def test_scan_of_a_folder_swapped_for_a_link_is_refused(
        self, monkeypatch, configured, folders, auth_a, a_folder, b_folder
    ):
        _swap_when_scanned(monkeypatch, lambda: _swap_for_link(a_folder, b_folder))
        status, body = _post(folders, auth_a, ROUTES[0], {"path": str(a_folder)})
        assert (status, body["code"]) == (403, "path_not_allowed")
        assert "b-only" not in json.dumps(body) and str(b_folder) not in json.dumps(body)

    @pytest.mark.parametrize("swapped", ["file", "parent_dir"])
    def test_entry_swapped_for_a_link_between_check_and_open_is_not_read(
        self, monkeypatch, configured, folders, store, auth_a, a_folder, b_folder, swapped
    ):
        (a_folder / "sub").mkdir()
        (a_folder / "sub" / "inner.md").write_text("a nested note")
        victim, filename, target = {
            "file": (a_folder / "notes.md", "notes.md", b_folder / "notes.md"),
            "parent_dir": (a_folder / "sub", "inner.md", b_folder),
        }[swapped]
        _swap_before_open(monkeypatch, filename, lambda: _swap_for_link(victim, target))

        status, body = _post(folders, auth_a, ROUTES[1], {"path": str(a_folder)})
        assert status == 200, body
        _run_background_work()

        job = FolderUploadHandler._jobs[body["folder_id"]]
        assert (job.files_uploaded, job.files_failed) == (2, 1)
        assert B_SECRET not in _stored_text(store)

    def test_nested_files_and_links_inside_the_folder_are_still_imported(
        self, configured, folders, store, auth_a, a_folder
    ):
        (a_folder / "nested" / "deep").mkdir(parents=True)
        (a_folder / "nested" / "deep" / "deep.md").write_text("deep note")
        (a_folder / "alias.md").symlink_to(a_folder / "notes.md")
        payload = {"path": str(a_folder), "config": {"followSymlinks": True}}

        status, body = _post(folders, auth_a, ROUTES[1], payload)
        assert status == 200, body
        _run_background_work()

        docs = [store.get(d) for d in FolderUploadHandler._jobs[body["folder_id"]].document_ids]
        by_name = {doc.filename: doc.text for doc in docs}
        assert sorted(by_name) == ["alias.md", "deep.md", "notes.md", "plan.txt"]
        assert by_name["alias.md"] == by_name["notes.md"] == "upload root notes"
        assert by_name["deep.md"] == "deep note"


class TestInvalidRoots:
    @pytest.fixture(autouse=True)
    def _key_file(self, monkeypatch, tmp_path):
        key = tmp_path / "secrets" / "keys" / "odr-signing-key.pem"
        key.parent.mkdir(parents=True)
        key.write_text("not a real key")
        monkeypatch.setenv("ARAGORA_ODR_SIGNING_KEY_FILE", str(key))

    @pytest.mark.parametrize(
        "root",
        ["app-data", "app-data/imports", "", "data/documents", "data/documents/imports", "data"]
        + ["nomic", "nomic/imports", "secrets/keys", "secrets/keys/imports", "secrets"],
    )
    def test_root_overlapping_a_protected_path_grants_nothing(
        self, monkeypatch, caplog, folders, auth_a, tmp_path, root
    ):
        (tmp_path / root).mkdir(parents=True, exist_ok=True)
        _configure(monkeypatch, {ORG_A: [tmp_path / root]})
        with caplog.at_level(logging.ERROR, logger=import_roots.__name__):
            status, body = _post(folders, auth_a, ROUTES[0], {"path": str(tmp_path / root)})
        assert (status, body["code"]) == (403, NOT_CONFIGURED_CODE)
        assert "protected server path" in caplog.text
        assert FolderUploadHandler._jobs == {}

    @pytest.mark.parametrize("a_dir, b_dir", [("x", "x"), ("x", "x/in"), ("x/in", "x")])
    def test_overlapping_roots_of_two_orgs_grant_nothing_to_either(
        self, monkeypatch, caplog, folders, auth_a, auth_b, tmp_path, a_dir, b_dir
    ):
        a, b = tmp_path / "shared" / a_dir, tmp_path / "shared" / b_dir
        (tmp_path / "shared" / "x" / "in").mkdir(parents=True)
        _configure(monkeypatch, {ORG_A: [a], ORG_B: [b]})
        with caplog.at_level(logging.ERROR, logger=import_roots.__name__):
            for auth, path in ((auth_a, a), (auth_b, b)):
                status, body = _post(folders, auth, ROUTES[0], {"path": str(path)})
                assert (status, body["code"]) == (403, NOT_CONFIGURED_CODE)
        assert "another org" in caplog.text

    @pytest.mark.parametrize("b_invalid", ["overlaps_protected_path", "not_a_list"])
    def test_overlap_with_a_root_invalid_for_another_reason_still_rejects_both(
        self, monkeypatch, caplog, folders, auth_a, tmp_path, b_invalid
    ):
        a_root = tmp_path / "shared" / "a"
        a_root.mkdir(parents=True)
        # B's root contains A's root; it is also invalid on its own (it holds the data dir,
        # or it is not given as a list).
        b_value = {"overlaps_protected_path": [str(tmp_path)], "not_a_list": str(a_root.parent)}
        monkeypatch.setenv(ENV, json.dumps({ORG_A: [str(a_root)], ORG_B: b_value[b_invalid]}))
        with caplog.at_level(logging.ERROR, logger=import_roots.__name__):
            status, body = _post(folders, auth_a, ROUTES[0], {"path": str(a_root)})
        assert (status, body["code"]) == (403, NOT_CONFIGURED_CODE)
        assert "another org" in caplog.text

    @pytest.mark.parametrize("name", import_roots.SECRET_FILE_ENV_VARS)
    def test_every_key_file_setting_protects_the_directory_of_its_link_target(
        self, monkeypatch, tmp_path, name
    ):
        target = tmp_path / "imports" / "credentials.json"
        target.parent.mkdir()
        target.write_text("{}")
        link = tmp_path / "config" / "credentials.json"
        link.parent.mkdir()
        link.symlink_to(target)
        _configure(monkeypatch, {ORG_A: [target.parent]})
        roots, protected = import_roots.org_import_roots, import_roots.protected_paths
        assert roots(ORG_A, protected()) == [target.parent.resolve()]
        monkeypatch.setenv(name, str(link))
        assert roots(ORG_A, protected()) == []

    @pytest.mark.parametrize("name", import_roots.SECRET_FILE_ENV_VARS)
    def test_every_key_file_setting_protects_its_directory(self, monkeypatch, tmp_path, name):
        key = tmp_path / "creds" / "secret.key"
        key.parent.mkdir()
        key.write_text("x")
        _configure(monkeypatch, {ORG_A: [key.parent]})
        roots = import_roots.org_import_roots
        protected = import_roots.protected_paths
        assert roots(ORG_A, protected()) == [key.parent.resolve()]
        monkeypatch.setenv(name, str(key))
        assert roots(ORG_A, protected()) == []
