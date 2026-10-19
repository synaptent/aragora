"""Characterization tests for the decode fallback in ``agent_bridge._json_payload``."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aragora.server.handlers.agents import agent_bridge as agent_bridge_module
from aragora.server.handlers.agents.agent_bridge import _json_payload
from aragora.server.handlers.utils.responses import HandlerResult


def _result(body: bytes) -> HandlerResult:
    return HandlerResult(status_code=200, content_type="application/json", body=body)


@pytest.mark.parametrize(
    ("raw", "expected_exc"),
    [
        pytest.param("{bad", json.JSONDecodeError, id="malformed-json"),
        pytest.param("1" * 5000, ValueError, id="integer-digit-limit"),
        pytest.param("[" * 100_000, RecursionError, id="deep-nesting"),
    ],
)
def test_undecodable_body_falls_back_to_empty_dict(
    raw: str, expected_exc: type[BaseException]
) -> None:
    with pytest.raises(expected_exc) as excinfo:
        json.loads(raw)
    assert excinfo.type is expected_exc

    assert _json_payload(_result(raw.encode("utf-8"))) == {}


def test_memory_error_while_decoding_falls_back_to_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoded: list[str] = []

    def _loads(raw: str) -> object:
        decoded.append(raw)
        raise MemoryError("simulated allocation failure")

    # Replace only this module's ``json`` binding so other users of ``json.loads`` are untouched.
    monkeypatch.setattr(agent_bridge_module, "json", SimpleNamespace(loads=_loads))

    assert _json_payload(_result(b'{"turn": 3}')) == {}
    assert decoded == ['{"turn": 3}']


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(b"", {}, id="empty-body"),
        pytest.param(b"[1, 2]", {}, id="non-object-json"),
        pytest.param(b'{"turn": 3}', {"turn": 3}, id="object-json"),
    ],
)
def test_decodable_body_is_returned_only_when_it_is_an_object(
    body: bytes, expected: dict[str, object]
) -> None:
    assert _json_payload(_result(body)) == expected
