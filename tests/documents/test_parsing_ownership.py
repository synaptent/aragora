"""Document ownership in the parsed-document store (architecture §2.3).

Every stored document records the uploader's org, the uploading user and the
SHA-256 of the uploaded bytes. The id hashes the org together with the bytes
and filename, so two orgs uploading the same file get separate records.
Documents written before ownership existed have no org and belong to nobody.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aragora.documents.parsing import (
    DocumentStore,
    ParsedDocument,
    generate_doc_id,
    parse_document,
)

ORG_A = "org-a-docs"
ORG_B = "org-b-docs"
CONTENT = b"# Vendor policy\n\nSentinel: DOC-OWNERSHIP-SENTINEL-7731\n"
FILENAME = "vendor-policy.md"


def _expected_id(org_id: str, content: bytes, filename: str) -> str:
    return hashlib.sha256(org_id.encode() + content + filename.encode()).hexdigest()[:16]


class TestDocumentId:
    def test_id_hashes_org_content_and_filename(self):
        assert generate_doc_id(CONTENT, FILENAME, ORG_A) == _expected_id(ORG_A, CONTENT, FILENAME)

    def test_identical_bytes_from_two_orgs_get_different_ids(self):
        assert generate_doc_id(CONTENT, FILENAME, ORG_A) != generate_doc_id(
            CONTENT, FILENAME, ORG_B
        )

    def test_without_org_the_id_is_the_pre_ownership_id(self):
        legacy = hashlib.sha256(CONTENT + FILENAME.encode()).hexdigest()[:16]

        assert generate_doc_id(CONTENT, FILENAME) == legacy
        assert generate_doc_id(CONTENT, FILENAME, None) == legacy


class TestParseDocumentOwnership:
    @pytest.mark.parametrize("filename", ["vendor-policy.md", "notes.txt", "notes.markdown"])
    def test_owner_fields_are_recorded(self, filename):
        doc = parse_document(CONTENT, filename, org_id=ORG_A, created_by="user-a")

        assert doc.org_id == ORG_A
        assert doc.created_by == "user-a"
        assert doc.content_sha256 == hashlib.sha256(CONTENT).hexdigest()
        assert doc.id == _expected_id(ORG_A, CONTENT, filename)

    def test_content_hash_is_recorded_without_an_owner(self):
        doc = parse_document(CONTENT, FILENAME)

        assert doc.org_id is None
        assert doc.created_by is None
        assert doc.content_sha256 == hashlib.sha256(CONTENT).hexdigest()
        assert doc.id == generate_doc_id(CONTENT, FILENAME)

    def test_blank_org_is_no_owner(self):
        doc = parse_document(CONTENT, FILENAME, org_id="  ", created_by="user-a")

        assert doc.org_id is None
        assert doc.id == generate_doc_id(CONTENT, FILENAME)

    def test_to_dict_carries_owner_fields(self):
        data = parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a").to_dict()

        assert data["org_id"] == ORG_A
        assert data["created_by"] == "user-a"
        assert data["content_sha256"] == hashlib.sha256(CONTENT).hexdigest()


class TestDocumentStoreOwnership:
    def test_owner_fields_survive_a_reload_from_disk(self, tmp_path: Path):
        doc = parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a")
        DocumentStore(tmp_path).add(doc)

        reloaded = DocumentStore(tmp_path).get(doc.id)

        assert reloaded is not None
        assert reloaded.org_id == ORG_A
        assert reloaded.created_by == "user-a"
        assert reloaded.content_sha256 == hashlib.sha256(CONTENT).hexdigest()
        assert reloaded.text == CONTENT.decode()

    def test_owner_fields_are_written_to_the_json_record(self, tmp_path: Path):
        doc = parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a")
        DocumentStore(tmp_path).add(doc)

        stored = json.loads((tmp_path / f"{doc.id}.json").read_text())

        assert stored["org_id"] == ORG_A
        assert stored["created_by"] == "user-a"
        assert stored["content_sha256"] == hashlib.sha256(CONTENT).hexdigest()

    def test_identical_uploads_from_two_orgs_are_two_records(self, tmp_path: Path):
        store = DocumentStore(tmp_path)
        doc_a = parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a")
        doc_b = parse_document(CONTENT, FILENAME, org_id=ORG_B, created_by="user-b")

        id_a = store.add(doc_a)
        id_b = store.add(doc_b)

        assert id_a != id_b
        assert sorted(p.stem for p in tmp_path.glob("*.json")) == sorted([id_a, id_b])
        assert store.get(id_a).org_id == ORG_A
        assert store.get(id_b).org_id == ORG_B

    def test_legacy_record_without_org_loads_with_unknown_owner(self, tmp_path: Path):
        legacy = ParsedDocument(
            id="legacydoc0000001", filename="old.md", content_type="text/markdown", text="old"
        )
        payload = legacy.to_dict()
        for key in ("org_id", "created_by", "content_sha256"):
            payload.pop(key, None)
        (tmp_path / "legacydoc0000001.json").write_text(json.dumps(payload))

        doc = DocumentStore(tmp_path).get("legacydoc0000001")

        assert doc is not None
        assert doc.org_id is None
        assert doc.created_by is None
        assert doc.content_sha256 is None

    def test_list_for_org_returns_only_that_orgs_records(self, tmp_path: Path):
        store = DocumentStore(tmp_path)
        id_a = store.add(parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a"))
        id_b = store.add(parse_document(CONTENT, FILENAME, org_id=ORG_B, created_by="user-b"))
        id_legacy = store.add(parse_document(b"legacy", "legacy.txt"))

        listed_a = store.list_for_org(ORG_A)
        listed_b = store.list_for_org(ORG_B)

        assert [d["id"] for d in listed_a] == [id_a]
        assert [d["id"] for d in listed_b] == [id_b]
        assert id_legacy not in {d["id"] for d in listed_a + listed_b}
        assert listed_a[0]["filename"] == FILENAME

    @pytest.mark.parametrize("org_id", ["", None])
    def test_list_for_org_without_an_org_lists_nothing(self, tmp_path: Path, org_id):
        store = DocumentStore(tmp_path)
        store.add(parse_document(b"legacy", "legacy.txt"))
        store.add(parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a"))

        assert store.list_for_org(org_id) == []  # type: ignore[arg-type]

    def test_list_for_org_skips_unreadable_records(self, tmp_path: Path):
        store = DocumentStore(tmp_path)
        id_a = store.add(parse_document(CONTENT, FILENAME, org_id=ORG_A, created_by="user-a"))
        (tmp_path / "broken.json").write_text("{not json")
        (tmp_path / "nofields.json").write_text(json.dumps({"org_id": ORG_A}))

        assert [d["id"] for d in store.list_for_org(ORG_A)] == [id_a]
