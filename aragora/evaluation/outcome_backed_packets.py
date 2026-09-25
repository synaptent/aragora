"""Deterministic, outcome-blind source packets for decision-quality inference."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from http.client import HTTPMessage
import ipaddress
import json
from pathlib import Path
import re
import socket
from typing import IO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    canonical_json_sha256,
    load_visible_cases,
)


SOURCE_PACKET_SCHEMA = "outcome-backed-source-packet/1.0"
PACKET_SET_SCHEMA = "outcome-backed-source-packet-set/1.0"
DEFAULT_MAX_SOURCE_BYTES = 10_000_000
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_USER_AGENT = "Mozilla/5.0 (compatible; AragoraBot/1.0; +https://aragora.ai)"
SOURCE_HOST_ALLOWLIST = frozenset(
    {
        "assets.publishing.service.gov.uk",
        "ntrs.nasa.gov",
        "raw.githubusercontent.com",
        "science.nasa.gov",
        "www.ftc.gov",
        "www.govinfo.gov",
        "www.justice.gov",
        "www.nasa.gov",
        "www.nist.gov",
        "www.noaa.gov",
        "www.sec.gov",
    }
)

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_OUTCOME_KEYS = frozenset(
    {
        "authoritative_sources",
        "correct_option_id",
        "cruxes",
        "outcome",
        "outcomes",
        "resolution_summary",
        "resolved_at",
    }
)


class SourcePacketError(ValueError):
    """Raised when source material cannot be packetized fail-closed."""


def _source_hostname(url: str, *, source_id: str, expected_hostname: str | None = None) -> str:
    """Return an allowlisted HTTPS hostname without performing network I/O."""

    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise SourcePacketError(f"source {source_id} URL is malformed") from exc
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        raise SourcePacketError(f"source {source_id} URL must be credential-free HTTPS on port 443")
    if hostname not in SOURCE_HOST_ALLOWLIST:
        raise SourcePacketError(f"source {source_id} hostname is not in the frozen allowlist")
    if expected_hostname is not None and hostname != expected_hostname:
        raise SourcePacketError(f"source {source_id} redirect changed hostname")
    return hostname


def _validate_public_source_url(
    url: str,
    *,
    source_id: str,
    expected_hostname: str | None = None,
) -> str:
    """Fail closed unless every resolved address is globally routable."""

    hostname = _source_hostname(
        url,
        source_id=source_id,
        expected_hostname=expected_hostname,
    )
    try:
        addresses = socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (TimeoutError, socket.gaierror, OSError) as exc:
        raise SourcePacketError(f"source {source_id} DNS resolution failed") from exc
    if not addresses:
        raise SourcePacketError(f"source {source_id} DNS resolution returned no addresses")
    for address in addresses:
        try:
            resolved = ipaddress.ip_address(str(address[4][0]))
        except (IndexError, TypeError, ValueError) as exc:
            raise SourcePacketError(f"source {source_id} DNS returned an invalid address") from exc
        if not resolved.is_global:
            raise SourcePacketError(f"source {source_id} resolved to a non-public address")
    return hostname


class _SourceRedirectHandler(HTTPRedirectHandler):
    """Validate every redirect target before urllib opens it."""

    def __init__(self, *, source_id: str, expected_hostname: str) -> None:
        super().__init__()
        self._source_id = source_id
        self._expected_hostname = expected_hostname

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        _validate_public_source_url(
            newurl,
            source_id=self._source_id,
            expected_hostname=self._expected_hostname,
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class MaterializedSource:
    source_id: str
    title: str
    url: str
    published_at: str
    content_sha256: str
    media_type: str
    content_encoding: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "content_encoding": self.content_encoding,
            "content": self.content,
        }


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourcePacketError(f"{field} must be a non-empty string")
    return value


def _source_metadata(source: Mapping[str, object]) -> dict[str, str]:
    metadata = {
        field: _required_text(source.get(field), f"source.{field}")
        for field in ("source_id", "title", "url", "published_at", "content_sha256")
    }
    _source_hostname(metadata["url"], source_id=metadata["source_id"])
    if not re.fullmatch(r"[0-9a-f]{64}", metadata["content_sha256"]):
        raise SourcePacketError("source.content_sha256 must be lowercase SHA-256")
    return metadata


def fetch_source(
    source: Mapping[str, object],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
) -> MaterializedSource:
    """Fetch one pinned source and verify its exact bytes before decoding."""

    metadata = _source_metadata(source)
    if timeout_seconds <= 0:
        raise SourcePacketError("timeout_seconds must be positive")
    if max_source_bytes <= 0:
        raise SourcePacketError("max_source_bytes must be positive")

    source_hostname = _validate_public_source_url(
        metadata["url"],
        source_id=metadata["source_id"],
    )
    request = Request(
        metadata["url"],
        headers={"User-Agent": SOURCE_USER_AGENT},
        method="GET",
    )
    opener = build_opener(
        _SourceRedirectHandler(
            source_id=metadata["source_id"],
            expected_hostname=source_hostname,
        )
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            _source_hostname(
                final_url,
                source_id=metadata["source_id"],
                expected_hostname=source_hostname,
            )
            raw = response.read(max_source_bytes + 1)
    except SourcePacketError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise SourcePacketError(
            f"source {metadata['source_id']} fetch failed ({type(exc).__name__})"
        ) from exc

    if len(raw) > max_source_bytes:
        raise SourcePacketError(f"source {metadata['source_id']} exceeds {max_source_bytes} bytes")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != metadata["content_sha256"]:
        raise SourcePacketError(
            f"source {metadata['source_id']} hash mismatch: expected "
            f"{metadata['content_sha256']}, got {digest}"
        )
    if raw.startswith(b"%PDF-"):
        media_type = "application/pdf"
        content_encoding = "base64"
        content = base64.b64encode(raw).decode("ascii")
    else:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourcePacketError(
                f"source {metadata['source_id']} is neither PDF nor valid UTF-8"
            ) from exc
        media_type = "text/plain; charset=utf-8"
        content_encoding = "utf-8"
    return MaterializedSource(
        content=content,
        media_type=media_type,
        content_encoding=content_encoding,
        **metadata,
    )


def _reject_outcome_keys(value: object, path: str = "packet") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in _OUTCOME_KEYS:
                raise SourcePacketError(f"outcome-only key {key!r} found at {path}")
            _reject_outcome_keys(child, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _reject_outcome_keys(child, f"{path}[{index}]")


def render_case_packet(
    case: Mapping[str, object],
    sources: Sequence[MaterializedSource],
) -> dict[str, object]:
    """Render one deterministic packet without any outcome-sidecar fields."""

    case_id = _required_text(case.get("case_id"), "case.case_id")
    if not _SAFE_ID_RE.fullmatch(case_id):
        raise SourcePacketError(f"unsafe case_id: {case_id!r}")
    split = _required_text(case.get("split"), "case.split")
    if split not in {"development", "holdout"}:
        raise SourcePacketError(f"unsupported case split: {split}")

    visible_case = dict(case)
    declared_sources = visible_case.pop("sources", None)
    if not isinstance(declared_sources, list) or not declared_sources:
        raise SourcePacketError(f"case {case_id} must declare at least one source")
    declared_ids = [
        _required_text(source.get("source_id"), "source.source_id")
        for source in declared_sources
        if isinstance(source, Mapping)
    ]
    materialized = sorted(sources, key=lambda source: source.source_id)
    actual_ids = [source.source_id for source in materialized]
    if sorted(declared_ids) != actual_ids or len(declared_ids) != len(declared_sources):
        raise SourcePacketError(
            f"case {case_id} source set mismatch: declared={sorted(declared_ids)}, "
            f"materialized={actual_ids}"
        )

    payload: dict[str, object] = {
        "schema_version": SOURCE_PACKET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "case": visible_case,
        "sources": [source.to_dict() for source in materialized],
    }
    _reject_outcome_keys(payload)
    payload["packet_sha256"] = canonical_json_sha256(payload)
    return payload


def _collect_source_metadata(cases: Sequence[Mapping[str, object]]) -> dict[str, dict[str, str]]:
    collected: dict[str, dict[str, str]] = {}
    for case in cases:
        case_id = _required_text(case.get("case_id"), "case.case_id")
        sources = case.get("sources")
        if not isinstance(sources, list) or not sources:
            raise SourcePacketError(f"case {case_id} must declare at least one source")
        for source in sources:
            if not isinstance(source, Mapping):
                raise SourcePacketError(f"case {case_id} contains a non-object source")
            metadata = _source_metadata(source)
            source_id = metadata["source_id"]
            previous = collected.get(source_id)
            if previous is not None and previous != metadata:
                raise SourcePacketError(f"source_id {source_id!r} has conflicting metadata")
            collected[source_id] = metadata
    return collected


def build_packet_set(
    cases: Sequence[Mapping[str, object]],
    *,
    split: str,
    fetch: Callable[[Mapping[str, object]], MaterializedSource] = fetch_source,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Build a deterministic split-specific packet set in memory."""

    if split not in {"development", "holdout"}:
        raise SourcePacketError("split must be development or holdout")
    selected = [case for case in cases if case.get("split") == split]
    expected = 16 if split == "development" else 8
    if len(selected) != expected:
        raise SourcePacketError(f"expected {expected} {split} cases, found {len(selected)}")
    selected.sort(key=lambda case: _required_text(case.get("case_id"), "case.case_id"))

    metadata = _collect_source_metadata(selected)
    materialized = {source_id: fetch(source) for source_id, source in sorted(metadata.items())}
    packets: dict[str, dict[str, object]] = {}
    for case in selected:
        case_id = _required_text(case.get("case_id"), "case.case_id")
        sources = case.get("sources")
        if not isinstance(sources, list):
            raise SourcePacketError(f"case {case_id} sources changed after validation")
        packets[case_id] = render_case_packet(
            case,
            [materialized[str(source["source_id"])] for source in sources],
        )

    packet_entries = [
        {"case_id": case_id, "packet_sha256": packet["packet_sha256"]}
        for case_id, packet in sorted(packets.items())
    ]
    manifest: dict[str, object] = {
        "schema_version": PACKET_SET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "split": split,
        "packet_count": len(packets),
        "source_count": len(materialized),
        "packets": packet_entries,
    }
    manifest["packet_set_sha256"] = canonical_json_sha256(manifest)
    return manifest, packets


def write_packet_set(
    output_dir: Path | str,
    manifest: Mapping[str, object],
    packets: Mapping[str, Mapping[str, object]],
) -> None:
    """Write one packet set atomically while refusing stale packet residue."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    expected = {f"{case_id}.packet.json" for case_id in packets}
    stale = sorted(path.name for path in root.glob("*.packet.json") if path.name not in expected)
    if stale:
        raise SourcePacketError(f"output directory contains stale packets: {', '.join(stale)}")

    documents: dict[str, Mapping[str, object]] = {
        **{f"{case_id}.packet.json": packet for case_id, packet in packets.items()},
        "packet-set.json": manifest,
    }
    for name, document in sorted(documents.items()):
        target = root / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(target)


def materialize_source_packets(
    corpus_dir: Path | str,
    output_dir: Path | str,
    *,
    split: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
) -> dict[str, object]:
    """Load visible cases, fetch pinned evidence, and persist deterministic packets."""

    cases = load_visible_cases(corpus_dir)

    def fetch(metadata: Mapping[str, object]) -> MaterializedSource:
        return fetch_source(
            metadata,
            timeout_seconds=timeout_seconds,
            max_source_bytes=max_source_bytes,
        )

    manifest, packets = build_packet_set(cases, split=split, fetch=fetch)
    write_packet_set(output_dir, manifest, packets)
    return manifest
