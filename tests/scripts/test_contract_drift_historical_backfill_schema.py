from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "scripts/schemas/contract-drift-historical-backfill-capsule-v2.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _resolve_object_schema(node: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if node.get("type") == "object":
        found.append(node)
    properties = node.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            if isinstance(child, dict):
                found.extend(_resolve_object_schema(child))
    items = node.get("items")
    if isinstance(items, dict):
        found.extend(_resolve_object_schema(items))
    return found


def test_schema_is_draft_2020_12_and_root_is_exact() -> None:
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["type"] == "object"
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])


def test_every_object_schema_rejects_omitted_and_additional_fields() -> None:
    objects = _resolve_object_schema(SCHEMA)
    assert len(objects) >= 14
    for node in objects:
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(properties)


def test_schema_binds_successor_release_attestation_and_disposition() -> None:
    properties = SCHEMA["properties"]
    assert properties["schema"]["const"] == "contract-drift-historical-backfill-successor-v2"
    assert properties["release"]["properties"]["tag_name"]["pattern"] == (
        "^backfill-v2-[0-9a-f]{40}$"
    )
    assert properties["release"]["properties"]["asset_names"]["const"] == [
        "manifest.json",
        "payload.json",
        "checksums.txt",
    ]
    assert (
        "merged implementation SHA"
        in (properties["release"]["properties"]["tag_target_sha"]["description"])
    )
    assert properties["attestation"]["properties"]["workflow"]["const"] == "actions/attest@v4"
    assert (
        "merged implementation SHA"
        in (properties["attestation"]["properties"]["source_digest"]["description"])
    )
    assert properties["attestation"]["properties"]["subject_asset_names"]["const"] == [
        "manifest.json",
        "payload.json",
        "checksums.txt",
    ]
    disposition = properties["disposition"]["properties"]
    assert disposition["status"]["const"] == "historical_nonconforming"
    assert disposition["precedential"]["const"] is False
    assert disposition["authoritative_for_future_admission"]["const"] is False


def test_schema_rule_suite_region_binds_implementation_push_identity() -> None:
    rule_suite = SCHEMA["properties"]["rule_suite"]["properties"]
    assert "merged implementation SHA" in rule_suite["after_sha"]["description"]
    assert rule_suite["after_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert rule_suite["ref"]["const"] == "refs/heads/main"
    assert rule_suite["result"]["const"] == "pass"
    assert rule_suite["schema"]["const"] == "contract-drift-historical-backfill-rule-suite-v1"


def test_schema_requires_complete_method_specific_projection_edges() -> None:
    record = SCHEMA["properties"]["projection"]["properties"]["records"]["items"]
    edge = record["properties"]["operation_edges"]["items"]
    assert set(record["required"]) == set(record["properties"])
    assert set(edge["required"]) == {
        "evidence",
        "method",
        "normalized_operation",
        "normalized_path",
    }
    assert set(edge["properties"]["method"]["enum"]) == {
        "CONNECT",
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
        "TRACE",
    }


def test_schema_requires_four_sha_receipt_and_all_authority_partition_digests() -> None:
    receipt = SCHEMA["properties"]["receipt"]
    assert {"base_sha", "head_sha", "merge_sha", "first_parent_sha"} <= set(receipt["required"])
    authority = SCHEMA["properties"]["authority"]
    assert {
        "operation_projection_schema_sha256",
        "sdk_original_record_id_set_sha256",
        "core_original_record_id_set_sha256",
        "extended_original_record_id_set_sha256",
    } <= set(authority["required"])


def test_schema_is_valid_draft_2020_12() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
