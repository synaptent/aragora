"""The committed example receipt is the emitter<->verifier contract. It must
be (a) exactly what odr_export emits today (regeneration guard) and (b)
schema-conformant with a recomputable JCS digest."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from aragora.gauntlet.odr_export import (
    decision_receipt_to_odr,
    load_odr_schema,
    odr_content_digest,
)

from tests.gauntlet.test_odr_export import _full_receipt

EXAMPLE = Path("docs/specs/examples/example-decision-receipt.odr.json")


def test_example_matches_current_emitter_output():
    # The committed example is a v0.1 document (it must keep verifying under
    # aragora-verify 0.1.x), so it is regenerated at an explicit 0.1, not the default.
    expected = decision_receipt_to_odr(_full_receipt(), odr_version="0.1")
    actual = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert actual == expected, "example receipt is stale; regenerate it"


def test_example_is_schema_conformant_and_digestible():
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    jsonschema.validate(doc, load_odr_schema())
    digest = odr_content_digest(doc)
    assert len(digest) == 64  # sha-256 hex
