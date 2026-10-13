"""Fail-closed readiness checks for outcome-backed development inference."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Protocol

from aragora.agents.transports.vibeproxy import (
    VibeProxyClient,
    VibeProxyCatalog,
    VibeProxyConfigurationError,
    VibeProxyMetadata,
    VibeProxyUnavailableError,
)

from aragora.evaluation.outcome_backed_budget import (
    DAILY_BUDGET_CAP_USD,
    BudgetLedgerError,
    OutcomeBackedBudgetLedger,
)
from aragora.evaluation.outcome_backed_conditions import (
    ConditionRosterError,
    preflight_condition_roster,
)
from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    VisibleCorpusError,
    canonical_json_sha256,
    load_visible_cases,
    validate_corpus_directory,
)
from aragora.evaluation.outcome_backed_prompt import (
    OutcomeBackedPromptError,
    render_outcome_backed_prompt,
)


DEVELOPMENT_PREFLIGHT_SCHEMA = "outcome-backed-development-preflight/2.0"
EXPECTED_DEVELOPMENT_CASES = 16
EXPECTED_CONDITIONS = 4
EXPECTED_PROMPTS = EXPECTED_DEVELOPMENT_CASES * EXPECTED_CONDITIONS
_IMPLEMENTATION_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_VIBEPROXY_ROUTE = "POST /v1/chat/completions"
_VIBEPROXY_PREFLIGHT_TIMEOUT_SECONDS = 3.0


class OutcomeBackedPreflightError(ValueError):
    """Raised when preflight inputs cannot be represented safely."""


class VibeProxyReadinessClient(Protocol):
    """No-inference VibeProxy surface required by development preflight."""

    base_url: str
    is_loopback: bool

    def catalog(self, *, force: bool, timeout: float) -> VibeProxyCatalog: ...

    def metadata(self, *, timeout: float) -> VibeProxyMetadata: ...


@dataclass(frozen=True)
class PreflightBlocker:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class DevelopmentPreflightReport:
    implementation_sha: str
    corpus_sha256: str | None
    packet_set_sha256: str | None
    roster_sha256: str | None
    case_ids: tuple[str, ...]
    condition_ids: tuple[str, ...]
    prompt_set_sha256: str | None
    transport_readiness: tuple[Mapping[str, object], ...]
    budget: Mapping[str, object] | None
    blockers: tuple[PreflightBlocker, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": DEVELOPMENT_PREFLIGHT_SCHEMA,
            "benchmark_id": BENCHMARK_ID,
            "implementation_sha": self.implementation_sha,
            "corpus_sha256": self.corpus_sha256,
            "packet_set_sha256": self.packet_set_sha256,
            "roster_sha256": self.roster_sha256,
            "development_case_ids": list(self.case_ids),
            "case_count": len(self.case_ids),
            "condition_ids": list(self.condition_ids),
            "condition_count": len(self.condition_ids),
            "prompt_count": EXPECTED_PROMPTS if self.prompt_set_sha256 else 0,
            "prompt_set_sha256": self.prompt_set_sha256,
            "transport_readiness": [dict(item) for item in self.transport_readiness],
            "budget": dict(self.budget) if self.budget is not None else None,
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "ready": self.ready,
        }


def _reject_duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OutcomeBackedPreflightError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise OutcomeBackedPreflightError(f"non-finite JSON number: {value}")


def _load_json_object(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_key,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OutcomeBackedPreflightError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise OutcomeBackedPreflightError(f"{path} must contain one JSON object")
    return value


def _tree_sha256(root: Path) -> str:
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise OutcomeBackedPreflightError(f"no corpus JSON files found in {root}")
    entries = [
        {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in paths
    ]
    return canonical_json_sha256(entries)


def _packet_content_bytes(source: Mapping[str, object], *, case_id: str) -> bytes:
    content = source.get("content")
    encoding = source.get("content_encoding")
    media_type = source.get("media_type")
    if not isinstance(content, str):
        raise OutcomeBackedPreflightError(f"case {case_id} packet source content must be text")
    if encoding == "utf-8" and media_type == "text/plain; charset=utf-8":
        return content.encode("utf-8")
    if encoding == "base64" and media_type == "application/pdf":
        try:
            decoded = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise OutcomeBackedPreflightError(
                f"case {case_id} packet source contains invalid base64"
            ) from exc
        if not decoded.startswith(b"%PDF-"):
            raise OutcomeBackedPreflightError(
                f"case {case_id} packet PDF source lacks a PDF signature"
            )
        return decoded
    raise OutcomeBackedPreflightError(
        f"case {case_id} packet source has an unsupported media type or encoding"
    )


def _validate_packet_against_case(
    packet: Mapping[str, object],
    case: Mapping[str, object],
) -> None:
    case_id = str(case.get("case_id", ""))
    expected_case = dict(case)
    expected_sources = expected_case.pop("sources", None)
    if packet.get("case") != expected_case:
        raise OutcomeBackedPreflightError(
            f"case {case_id} packet is not bound to the visible corpus case"
        )
    if not isinstance(expected_sources, list):
        raise OutcomeBackedPreflightError(f"case {case_id} has invalid source metadata")
    packet_sources = packet.get("sources")
    if not isinstance(packet_sources, list) or len(packet_sources) != len(expected_sources):
        raise OutcomeBackedPreflightError(f"case {case_id} packet source set mismatch")

    metadata_fields = ("source_id", "title", "url", "published_at", "content_sha256")
    expected_by_id: dict[str, Mapping[str, object]] = {}
    for source in expected_sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("source_id"), str):
            raise OutcomeBackedPreflightError(f"case {case_id} has invalid source metadata")
        source_id = str(source["source_id"])
        if source_id in expected_by_id:
            raise OutcomeBackedPreflightError(f"case {case_id} has duplicate source IDs")
        expected_by_id[source_id] = source

    seen: set[str] = set()
    for packet_source in packet_sources:
        if not isinstance(packet_source, Mapping) or not isinstance(
            packet_source.get("source_id"), str
        ):
            raise OutcomeBackedPreflightError(f"case {case_id} packet has invalid source metadata")
        source_id = str(packet_source["source_id"])
        expected = expected_by_id.get(source_id)
        if expected is None or source_id in seen:
            raise OutcomeBackedPreflightError(f"case {case_id} packet source set mismatch")
        seen.add(source_id)
        if any(packet_source.get(field) != expected.get(field) for field in metadata_fields):
            raise OutcomeBackedPreflightError(
                f"case {case_id} packet source {source_id} metadata mismatch"
            )
        digest = hashlib.sha256(_packet_content_bytes(packet_source, case_id=case_id)).hexdigest()
        if digest != packet_source.get("content_sha256"):
            raise OutcomeBackedPreflightError(
                f"case {case_id} packet source {source_id} content hash mismatch"
            )


def _transport_readiness(
    roster_members: tuple[Mapping[str, object], ...],
    client: VibeProxyReadinessClient | None,
) -> tuple[tuple[Mapping[str, object], ...], tuple[PreflightBlocker, ...]]:
    readiness: list[Mapping[str, object]] = []
    blockers: list[PreflightBlocker] = []
    resolved_client = client
    if resolved_client is None:
        try:
            resolved_client = VibeProxyClient()
        except VibeProxyConfigurationError as exc:
            blockers.append(
                PreflightBlocker(
                    "vibeproxy_configuration_invalid",
                    f"VibeProxy configuration is invalid ({type(exc).__name__})",
                )
            )
            return (), tuple(blockers)

    if not resolved_client.is_loopback:
        blockers.append(
            PreflightBlocker(
                "vibeproxy_not_loopback",
                "outcome-backed inference requires a loopback VibeProxy endpoint",
            )
        )
        return (), tuple(blockers)

    try:
        catalog = resolved_client.catalog(
            force=True,
            timeout=_VIBEPROXY_PREFLIGHT_TIMEOUT_SECONDS,
        )
        metadata = resolved_client.metadata(timeout=_VIBEPROXY_PREFLIGHT_TIMEOUT_SECONDS)
    except VibeProxyUnavailableError as exc:
        blockers.append(
            PreflightBlocker(
                "vibeproxy_unavailable",
                f"VibeProxy readiness probe failed ({type(exc).__name__})",
            )
        )
        return (), tuple(blockers)

    route_available = _REQUIRED_VIBEPROXY_ROUTE in metadata.advertised_routes
    if not route_available:
        blockers.append(
            PreflightBlocker(
                "vibeproxy_protocol_unavailable",
                f"VibeProxy does not advertise {_REQUIRED_VIBEPROXY_ROUTE}",
            )
        )

    for member in roster_members:
        family = str(member["family"])
        model = str(member["requested_model"])
        expected_owner = str(member["catalog_owner"])
        model_present = model in catalog.models
        observed_owner = catalog.owner_for(model) if model_present else None
        ready = (
            resolved_client.is_loopback
            and route_available
            and model_present
            and observed_owner == expected_owner
        )
        readiness.append(
            {
                "family": family,
                "requested_model": model,
                "expected_resolved_model": member["expected_resolved_model"],
                "transport": member["transport"],
                "protocol": member["protocol"],
                "identity_attestation": member["identity_attestation"],
                "allow_fallback": member["allow_fallback"],
                "endpoint_loopback": resolved_client.is_loopback,
                "required_route": _REQUIRED_VIBEPROXY_ROUTE,
                "route_available": route_available,
                "catalog_model_present": model_present,
                "expected_catalog_owner": expected_owner,
                "observed_catalog_owner": observed_owner,
                "ready": ready,
            }
        )
        if not model_present:
            blockers.append(
                PreflightBlocker(
                    "vibeproxy_model_unavailable",
                    f"{family} frozen model is absent from the VibeProxy catalog",
                )
            )
        elif observed_owner != expected_owner:
            blockers.append(
                PreflightBlocker(
                    "vibeproxy_owner_mismatch",
                    f"{family} frozen model lacks its exact catalog owner",
                )
            )
    return tuple(readiness), tuple(blockers)


def preflight_development_run(
    corpus_dir: Path | str,
    packet_dir: Path | str,
    budget_ledger_path: Path | str,
    *,
    implementation_sha: str,
    vibeproxy_client: VibeProxyReadinessClient | None = None,
    utc_date: date | None = None,
) -> DevelopmentPreflightReport:
    """Attest development-run readiness without model calls or ledger writes."""

    if not _IMPLEMENTATION_SHA_RE.fullmatch(implementation_sha):
        raise OutcomeBackedPreflightError("implementation_sha must be a lowercase 40-hex SHA")

    blockers: list[PreflightBlocker] = []
    corpus_sha256: str | None = None
    packet_set_sha256: str | None = None
    roster_sha256: str | None = None
    prompt_set_sha256: str | None = None
    case_ids: tuple[str, ...] = ()
    condition_ids: tuple[str, ...] = ()
    transport_readiness: tuple[Mapping[str, object], ...] = ()
    budget: Mapping[str, object] | None = None
    root = Path(corpus_dir)

    report = validate_corpus_directory(root)
    if not report.valid:
        blockers.append(
            PreflightBlocker(
                "invalid_corpus",
                f"frozen corpus has {len(report.issues)} integrity issue(s)",
            )
        )
    else:
        corpus_sha256 = _tree_sha256(root)

    cases: tuple[Mapping[str, Any], ...] = ()
    try:
        visible = load_visible_cases(root)
        cases = tuple(case for case in visible if case.get("split") == "development")
        case_ids = tuple(str(case.get("case_id", "")) for case in cases)
        if len(cases) != EXPECTED_DEVELOPMENT_CASES:
            blockers.append(
                PreflightBlocker(
                    "development_case_count",
                    f"expected {EXPECTED_DEVELOPMENT_CASES} development cases, found {len(cases)}",
                )
            )
    except VisibleCorpusError as exc:
        blockers.append(PreflightBlocker("visible_corpus_invalid", str(exc)))

    roster = None
    try:
        roster = preflight_condition_roster()
        roster_sha256 = roster.roster_sha256
        condition_ids = tuple(condition.condition_id for condition in roster.conditions)
        if len(condition_ids) != EXPECTED_CONDITIONS:
            blockers.append(
                PreflightBlocker(
                    "condition_count",
                    f"expected {EXPECTED_CONDITIONS} conditions, found {len(condition_ids)}",
                )
            )
    except ConditionRosterError as exc:
        blockers.append(PreflightBlocker("invalid_condition_roster", str(exc)))

    if roster is not None:
        unique_members: dict[str, Mapping[str, object]] = {}
        for condition in roster.conditions:
            for member in condition.members:
                unique_members.setdefault(member.family, member.to_dict())
        transport_readiness, transport_blockers = _transport_readiness(
            tuple(unique_members.values()), vibeproxy_client
        )
        blockers.extend(transport_blockers)

    packet_root = Path(packet_dir)
    prompt_entries: list[dict[str, str]] = []
    if len(cases) == EXPECTED_DEVELOPMENT_CASES and len(condition_ids) == EXPECTED_CONDITIONS:
        try:
            packet_set = _load_json_object(packet_root / "packet-set.json")
            expected_case_ids = set(case_ids)
            packet_entries = packet_set.get("packets")
            if not isinstance(packet_entries, list):
                raise OutcomeBackedPreflightError("packet-set packets must be a list")
            manifest_case_ids = {
                str(entry.get("case_id"))
                for entry in packet_entries
                if isinstance(entry, Mapping) and isinstance(entry.get("case_id"), str)
            }
            if manifest_case_ids != expected_case_ids:
                raise OutcomeBackedPreflightError(
                    "packet-set case IDs do not match the frozen development corpus"
                )
            cases_by_id = {str(case["case_id"]): case for case in cases}
            rendered_packet_set_sha: str | None = None
            for case_id in case_ids:
                packet = _load_json_object(packet_root / f"{case_id}.packet.json")
                _validate_packet_against_case(packet, cases_by_id[case_id])
                for condition_id in condition_ids:
                    rendered = render_outcome_backed_prompt(
                        packet,
                        packet_set=packet_set,
                        condition_id=condition_id,
                    )
                    if rendered_packet_set_sha is None:
                        rendered_packet_set_sha = rendered.packet_set_sha256
                    elif rendered.packet_set_sha256 != rendered_packet_set_sha:
                        raise OutcomeBackedPreflightError(
                            "rendered prompts disagree on packet-set identity"
                        )
                    prompt_entries.append(
                        {
                            "case_id": case_id,
                            "condition_id": condition_id,
                            "prompt_sha256": rendered.prompt_sha256,
                        }
                    )
            if len(prompt_entries) != EXPECTED_PROMPTS:
                raise OutcomeBackedPreflightError(
                    f"expected {EXPECTED_PROMPTS} prompts, rendered {len(prompt_entries)}"
                )
            if len({entry["prompt_sha256"] for entry in prompt_entries}) != EXPECTED_PROMPTS:
                raise OutcomeBackedPreflightError("development prompts are not all unique")
            packet_set_sha256 = rendered_packet_set_sha
            prompt_set_sha256 = canonical_json_sha256(prompt_entries)
        except (OSError, OutcomeBackedPreflightError, OutcomeBackedPromptError) as exc:
            blockers.append(PreflightBlocker("development_packets_not_ready", str(exc)))

    try:
        snapshot = OutcomeBackedBudgetLedger(budget_ledger_path).snapshot(utc_date=utc_date)
        budget = snapshot.to_dict()
        if snapshot.cap_usd != DAILY_BUDGET_CAP_USD:
            blockers.append(
                PreflightBlocker(
                    "budget_cap_mismatch",
                    f"expected daily cap ${DAILY_BUDGET_CAP_USD}, found ${snapshot.cap_usd}",
                )
            )
        if snapshot.exceeded:
            blockers.append(PreflightBlocker("budget_exceeded", "daily budget is exceeded"))
        if snapshot.open_reservations:
            blockers.append(
                PreflightBlocker(
                    "open_budget_reservations",
                    f"{snapshot.open_reservations} budget reservation(s) remain open",
                )
            )
        if snapshot.remaining_usd <= 0:
            blockers.append(PreflightBlocker("budget_exhausted", "no paid-call budget remains"))
    except (BudgetLedgerError, OSError, ValueError) as exc:
        blockers.append(PreflightBlocker("budget_ledger_invalid", str(exc)))

    unique_blockers = tuple(
        PreflightBlocker(code, message)
        for code, message in dict.fromkeys((item.code, item.message) for item in blockers)
    )
    return DevelopmentPreflightReport(
        implementation_sha=implementation_sha,
        corpus_sha256=corpus_sha256,
        packet_set_sha256=packet_set_sha256,
        roster_sha256=roster_sha256,
        case_ids=case_ids,
        condition_ids=condition_ids,
        prompt_set_sha256=prompt_set_sha256,
        transport_readiness=transport_readiness,
        budget=budget,
        blockers=unique_blockers,
    )


__all__ = [
    "DEVELOPMENT_PREFLIGHT_SCHEMA",
    "DevelopmentPreflightReport",
    "OutcomeBackedPreflightError",
    "PreflightBlocker",
    "preflight_development_run",
]
