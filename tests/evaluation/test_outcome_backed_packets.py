from __future__ import annotations

from collections.abc import Callable
import hashlib
from http.client import HTTPMessage
from io import BytesIO
import json
from pathlib import Path
import socket
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request

import pytest

import aragora.evaluation.outcome_backed_packets as packets_module
from aragora.evaluation.outcome_backed_corpus import load_visible_cases
from aragora.evaluation.outcome_backed_packets import (
    MaterializedSource,
    SOURCE_HOST_ALLOWLIST,
    SourcePacketError,
    _SourceRedirectHandler,
    build_packet_set,
    fetch_source,
    render_case_packet,
    write_packet_set,
)


CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")


class FakeResponse:
    def __init__(self, body: bytes, *, final_url: str = "https://www.sec.gov/source") -> None:
        self.body = body
        self.final_url = final_url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]

    def geturl(self) -> str:
        return self.final_url


def _install_opener(
    monkeypatch: pytest.MonkeyPatch,
    open_url: Callable[..., FakeResponse],
) -> None:
    class FakeOpener:
        def open(self, request: Request, *, timeout: float) -> FakeResponse:
            return open_url(request, timeout=timeout)

    monkeypatch.setattr(packets_module, "build_opener", lambda _handler: FakeOpener())


def _source(body: bytes = b"source body") -> dict[str, str]:
    return {
        "source_id": "source-1",
        "title": "Frozen source",
        "url": "https://www.sec.gov/source",
        "published_at": "2025-01-01T00:00:00Z",
        "content_sha256": hashlib.sha256(body).hexdigest(),
    }


def _case(index: int, *, split: str = "development") -> dict[str, object]:
    return {
        "case_id": f"case-{index:02d}",
        "domain": "software_engineering",
        "split": split,
        "title": f"Case {index}",
        "decision_prompt": "Choose one bounded action.",
        "forecast_question": "What is the probability option A is outcome-aligned?",
        "forecast_option_id": "option-a",
        "options": [
            {"option_id": "option-a", "label": "A", "description": "Action A"},
            {"option_id": "option-b", "label": "B", "description": "Action B"},
        ],
        "information_cutoff": "2025-01-02T00:00:00Z",
        "sources": [_source()],
    }


def _materialized(body: bytes = b"source body") -> MaterializedSource:
    return MaterializedSource(
        content=body.decode(),
        media_type="text/plain; charset=utf-8",
        content_encoding="utf-8",
        **_source(body),
    )


@pytest.fixture(autouse=True)
def public_source_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        packets_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def test_visible_loader_never_reads_outcome_sidecars(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.read_text
    reads: list[str] = []

    def tracked(path: Path, *args: object, **kwargs: object) -> str:
        reads.append(path.name)
        if path.name.endswith(".outcomes.json"):
            raise AssertionError("visible loader opened an outcome sidecar")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked)

    cases = load_visible_cases(CORPUS_DIR)

    assert len(cases) == 24
    assert sum(case["split"] == "development" for case in cases) == 16
    assert all(name.endswith(".corpus.json") for name in reads)


def test_source_host_allowlist_matches_frozen_corpus() -> None:
    cases = load_visible_cases(CORPUS_DIR)
    corpus_hosts: set[str] = set()
    for case in cases:
        for source in case["sources"]:
            hostname = urlparse(str(source["url"])).hostname
            assert hostname is not None
            corpus_hosts.add(hostname)

    assert corpus_hosts == SOURCE_HOST_ALLOWLIST


def test_fetch_source_verifies_exact_bytes_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "verified source\n".encode()
    opened: list[tuple[str, float]] = []

    def open_url(request: Request, *, timeout: float) -> FakeResponse:
        opened.append((request.full_url, timeout))
        return FakeResponse(body)

    _install_opener(monkeypatch, open_url)
    result = fetch_source(_source(body), timeout_seconds=2.5)

    assert result.content == "verified source\n"
    assert result.media_type == "text/plain; charset=utf-8"
    assert result.content_encoding == "utf-8"
    assert result.content_sha256 == hashlib.sha256(body).hexdigest()
    assert opened == [("https://www.sec.gov/source", 2.5)]


@pytest.mark.parametrize(
    ("source", "response", "match"),
    [
        (_source(), FakeResponse(b"changed"), "hash mismatch"),
        (
            _source(),
            FakeResponse(b"source body", final_url="http://www.sec.gov/source"),
            "credential-free HTTPS",
        ),
        (_source(b"\xff"), FakeResponse(b"\xff"), "neither PDF nor valid UTF-8"),
    ],
)
def test_fetch_source_fails_closed_on_integrity_defects(
    monkeypatch: pytest.MonkeyPatch,
    source: dict[str, str],
    response: FakeResponse,
    match: str,
) -> None:
    _install_opener(monkeypatch, lambda *_args, **_kwargs: response)
    with pytest.raises(SourcePacketError, match=match):
        fetch_source(source)


def test_fetch_source_sanitizes_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> FakeResponse:
        raise URLError("token=super-secret")

    _install_opener(monkeypatch, fail)
    with pytest.raises(SourcePacketError) as exc_info:
        fetch_source(_source())

    assert "URLError" in str(exc_info.value)
    assert "super-secret" not in str(exc_info.value)


def test_fetch_source_rejects_unresolvable_host_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def build_opener(*_args: object, **_kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("opener should not be built")

    monkeypatch.setattr(packets_module, "build_opener", build_opener)
    monkeypatch.setattr(packets_module.socket, "getaddrinfo", lambda *_args, **_kwargs: [])

    with pytest.raises(SourcePacketError, match="DNS resolution returned no addresses"):
        fetch_source(_source())

    assert opened is False


def test_fetch_source_rejects_hostname_outside_frozen_allowlist() -> None:
    source = _source()
    source["url"] = "https://unreviewed.example/source"

    with pytest.raises(SourcePacketError, match="hostname is not in the frozen allowlist"):
        fetch_source(source)


def test_fetch_source_rejects_private_address_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def build_opener(*_args: object, **_kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("opener should not be built")

    monkeypatch.setattr(packets_module, "build_opener", build_opener)
    monkeypatch.setattr(
        packets_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
    )

    with pytest.raises(SourcePacketError, match="resolved to a non-public address"):
        fetch_source(_source())

    assert opened is False


def test_fetch_source_revalidates_redirect_before_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = iter(
        [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ]
    )
    monkeypatch.setattr(
        packets_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: next(resolutions),
    )

    class RedirectingOpener:
        def __init__(self, handler: _SourceRedirectHandler) -> None:
            self.handler = handler

        def open(self, request: Request, *, timeout: float) -> FakeResponse:
            del timeout
            self.handler.redirect_request(
                request,
                BytesIO(),
                302,
                "Found",
                HTTPMessage(),
                "https://www.sec.gov/internal",
            )
            raise AssertionError("redirect target should not be opened")

    monkeypatch.setattr(
        packets_module,
        "build_opener",
        lambda handler: RedirectingOpener(handler),
    )

    with pytest.raises(SourcePacketError, match="resolved to a non-public address"):
        fetch_source(_source())


def test_fetch_source_rejects_cross_host_redirect_before_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectingOpener:
        def __init__(self, handler: _SourceRedirectHandler) -> None:
            self.handler = handler

        def open(self, request: Request, *, timeout: float) -> FakeResponse:
            del timeout
            self.handler.redirect_request(
                request,
                BytesIO(),
                302,
                "Found",
                HTTPMessage(),
                "https://www.nasa.gov/internal",
            )
            raise AssertionError("redirect target should not be opened")

    monkeypatch.setattr(
        packets_module,
        "build_opener",
        lambda handler: RedirectingOpener(handler),
    )

    with pytest.raises(SourcePacketError, match="redirect changed hostname"):
        fetch_source(_source())


def test_fetch_source_preserves_pdf_bytes_losslessly(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"%PDF-1.7\nopaque\x00bytes\xff"

    _install_opener(monkeypatch, lambda *_args, **_kwargs: FakeResponse(body))
    result = fetch_source(_source(body))

    assert result.media_type == "application/pdf"
    assert result.content_encoding == "base64"
    assert result.content == "JVBERi0xLjcKb3BhcXVlAGJ5dGVz/w=="


def test_packet_is_deterministic_and_outcome_blind() -> None:
    case = _case(1)

    first = render_case_packet(case, [_materialized()])
    second = render_case_packet(dict(reversed(list(case.items()))), [_materialized()])

    assert first == second
    encoded = json.dumps(first, sort_keys=True)
    for forbidden in (
        "authoritative_sources",
        "correct_option_id",
        "cruxes",
        "resolution_summary",
        "resolved_at",
    ):
        assert forbidden not in encoded
    assert first["packet_sha256"] == second["packet_sha256"]


def test_packet_rejects_structural_outcome_fields() -> None:
    case = _case(1)
    case["correct_option_id"] = "option-a"

    with pytest.raises(SourcePacketError, match="outcome-only key"):
        render_case_packet(case, [_materialized()])


def test_build_packet_set_fetches_shared_source_once() -> None:
    calls: list[str] = []

    def fetch(source: dict[str, object]) -> MaterializedSource:
        calls.append(str(source["source_id"]))
        return _materialized()

    manifest, packets = build_packet_set(
        [_case(index) for index in range(16)],
        split="development",
        fetch=fetch,
    )

    assert calls == ["source-1"]
    assert manifest["packet_count"] == 16
    assert manifest["source_count"] == 1
    assert list(packets) == [f"case-{index:02d}" for index in range(16)]


def test_build_packet_set_requires_complete_split() -> None:
    with pytest.raises(SourcePacketError, match="expected 16 development cases"):
        build_packet_set([_case(1)], split="development", fetch=lambda _: _materialized())


def test_write_packet_set_refuses_stale_packet_residue(tmp_path: Path) -> None:
    (tmp_path / "old.packet.json").write_text("{}\n")
    manifest, packets = build_packet_set(
        [_case(index) for index in range(16)],
        split="development",
        fetch=lambda _: _materialized(),
    )

    with pytest.raises(SourcePacketError, match="stale packets"):
        write_packet_set(tmp_path, manifest, packets)
