"""Degenerate quorum members must yield a verdict, never an uncaught traceback.

A default ``pip install aragora-verify`` resolves ``cryptography`` alone, so the
dependency-free walker in :mod:`aragora_verify.schema` is the only structural
check that runs. The ``walker_only`` fixture neutralises the optional
``jsonschema`` extra for the standalone verifier so that walker is what these
tests measure; the parity test additionally runs the in-repo twin as installed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aragora_verify import schema, verifier, verify
from aragora_verify.cli import main
from aragora_verify.verifier import FAIL

from _fixtures import valid_odr

# Degenerate values that reached the quorum-consistency check unvalidated: a
# member present but null is not absent, so ``dict.get(key, [])`` returns None.
_INNER = {
    "null-agents": ("dissenting_agents", None),
    "str-agents": ("dissenting_agents", "openai"),
    "null-views": ("views", None),
    "str-present": ("present", "yes"),
}
MUTANTS = [*_INNER, "null-dissent", "null-supporting"]


def _mutant(kind: str) -> dict[str, Any]:
    doc = valid_odr()
    quorum = doc["quorum"]
    if kind == "null-dissent":
        quorum["dissent"] = None
    elif kind == "null-supporting":
        quorum["supporting_agents"] = None
    else:
        member, value = _INNER[kind]
        quorum["dissent"][member] = value
    return doc


def _failing(result: Any) -> list[str]:
    return sorted(check.name for check in result.checks if check.status == FAIL)


@pytest.fixture
def walker_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])


@pytest.mark.parametrize("kind", MUTANTS)
def test_degenerate_quorum_member_fails_schema_conformance(kind, walker_only) -> None:
    errors = schema.validate_structure(_mutant(kind))
    assert errors, f"{kind}: the walker accepted a degenerate quorum member"
    result = verify(_mutant(kind))
    assert result.ok is False
    assert _failing(result) == ["schema_conformance"]


@pytest.mark.parametrize("kind", MUTANTS)
def test_degenerate_quorum_agrees_with_in_repo_engine(kind, walker_only) -> None:
    """Both bundled engines must name the same failing check for each mutant."""
    odr_verify = pytest.importorskip("aragora.gauntlet.odr_verify")
    twin = odr_verify.verify_odr_document(_mutant(kind))
    assert _failing(verify(_mutant(kind))) == sorted(
        check.name for check in twin.checks if check.status == "fail"
    )


@pytest.mark.parametrize("kind", MUTANTS)
def test_degenerate_quorum_exits_one_without_a_traceback(kind, walker_only, tmp_path, capsys):
    receipt = tmp_path / f"{kind}.odr.json"
    receipt.write_text(json.dumps(_mutant(kind)), encoding="utf-8")

    assert main([str(receipt), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert [c["name"] for c in payload["checks"] if c["status"] == "fail"] == ["schema_conformance"]


@pytest.mark.parametrize("value", [None, "openai", 5, [], True])
def test_non_object_dissent_fails_schema_conformance(value, walker_only) -> None:
    doc = valid_odr()
    doc["quorum"]["dissent"] = value
    assert "quorum.dissent: must be a dict" in schema.validate_structure(doc)
    assert _failing(verify(doc)) == ["schema_conformance"]


def test_conformant_dissent_is_still_accepted(walker_only) -> None:
    result = verify(valid_odr())
    assert result.ok is True
    assert _failing(result) == []


def _nonpass(result: Any) -> list[str]:
    return sorted(check.name for check in result.checks if check.status != "pass")


@pytest.mark.parametrize("value", [None, "x", [], {}])
def test_non_integer_family_count_warns_like_the_in_repo_engine(value, walker_only) -> None:
    """A non-integer weakening signal degrades to a warning, never a crash or a FAIL.

    Both dependency-free walkers leave ``distinct_model_families`` untyped (spec §8:
    weakening signals warn rather than fail), so with the optional ``schema`` extra
    absent the two engines must agree exactly. The bundled JSON schema does type the
    member as ``integer``, so an install that also carries ``jsonschema`` reports
    ``schema_conformance`` for these values instead; that is pre-existing behaviour of
    the extra, which is why ``walker_only`` pins the dependency-free path here.
    """
    odr_verify = pytest.importorskip("aragora.gauntlet.odr_verify")
    doc = valid_odr()
    doc["quorum"]["independence"]["distinct_model_families"] = value

    result = verify(doc)
    twin = odr_verify.verify_odr_document(doc)
    assert (result.ok, _nonpass(result)) == (
        twin.ok,
        sorted(check.name for check in twin.checks if check.status != "pass"),
    )


@pytest.mark.parametrize(
    ("attribute", "name"),
    [
        ("_check_quorum_consistency", "quorum_consistency"),
        ("_check_signatures", "signature"),
        ("_check_chain", "chain_link"),
    ],
)
def test_a_raising_check_becomes_a_fail_verdict(attribute, name, monkeypatch, walker_only) -> None:
    """Boundary contract: malformed input yields a FAIL check, not a traceback."""

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(verifier, attribute, _raise)
    result = verify(valid_odr())
    assert result.ok is False
    assert _failing(result) == [name]
    detail = next(c.detail for c in result.checks if c.name == name)
    assert "RuntimeError: boom" in detail
