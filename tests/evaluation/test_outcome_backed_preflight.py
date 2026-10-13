from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

import aragora.evaluation.outcome_backed_preflight as preflight_module
from aragora.evaluation.outcome_backed_conditions import FROZEN_CONDITION_ROSTER
from aragora.agents.transports.vibeproxy import (
    VibeProxyCatalog,
    VibeProxyMetadata,
    VibeProxyUnavailableError,
)
from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    CorpusIntegrityReport,
    canonical_json_sha256,
)
from aragora.evaluation.outcome_backed_packets import PACKET_SET_SCHEMA, SOURCE_PACKET_SCHEMA
from aragora.evaluation.outcome_backed_preflight import (
    OutcomeBackedPreflightError,
    preflight_development_run,
)


HEAD = "a" * 40
TODAY = date(2026, 8, 31)
REQUIRED_ROUTE = "POST /v1/chat/completions"


class FakeVibeProxyClient:
    base_url = "http://127.0.0.1:8318/v1"

    def __init__(
        self,
        *,
        models: frozenset[str] | None = None,
        owners: frozenset[tuple[str, str]] | None = None,
        routes: tuple[str, ...] = ("GET /v1/models", REQUIRED_ROUTE),
        loopback: bool = True,
        failure: Exception | None = None,
    ) -> None:
        identities = tuple(condition.members for condition in FROZEN_CONDITION_ROSTER[:3])
        members = tuple(items[0] for items in identities)
        self._models = models or frozenset(member.requested_model for member in members)
        self._owners = owners or frozenset(
            (member.requested_model, member.catalog_owner) for member in members
        )
        self._routes = routes
        self.is_loopback = loopback
        self._failure = failure

    def catalog(self, *, force: bool, timeout: float) -> VibeProxyCatalog:
        assert force is True
        assert timeout > 0
        if self._failure is not None:
            raise self._failure
        return VibeProxyCatalog(
            models=self._models,
            fetched_at=0.0,
            model_owners=self._owners,
        )

    def metadata(self, *, timeout: float) -> VibeProxyMetadata:
        assert timeout > 0
        if self._failure is not None:
            raise self._failure
        return VibeProxyMetadata(
            advertised_routes=self._routes,
            version=None,
            version_source="unknown",
        )


def _case(index: int) -> dict[str, object]:
    content = f"Frozen pre-cutoff evidence for case {index}."
    return {
        "case_id": f"case-{index:02d}",
        "domain": "software_engineering",
        "split": "development",
        "title": f"Case {index}",
        "decision_prompt": "Choose one bounded action.",
        "forecast_question": "What is the probability option A is outcome-aligned?",
        "forecast_option_id": "option-a",
        "options": [
            {"option_id": "option-a", "label": "A", "description": "Action A"},
            {"option_id": "option-b", "label": "B", "description": "Action B"},
        ],
        "information_cutoff": "2025-01-02T00:00:00Z",
        "sources": [
            {
                "source_id": f"source-{index:02d}",
                "title": "Frozen source",
                "url": "https://www.sec.gov/source",
                "published_at": "2025-01-01T00:00:00Z",
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        ],
        "_content": content,
    }


def _packet(case: dict[str, object]) -> dict[str, object]:
    visible = {key: value for key, value in case.items() if key not in {"sources", "_content"}}
    sources = case["sources"]
    assert isinstance(sources, list)
    assert isinstance(sources[0], dict)
    source = dict(sources[0])
    source.update(
        {
            "media_type": "text/plain; charset=utf-8",
            "content_encoding": "utf-8",
            "content": case["_content"],
        }
    )
    packet: dict[str, object] = {
        "schema_version": SOURCE_PACKET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "case": visible,
        "sources": [source],
    }
    packet["packet_sha256"] = canonical_json_sha256(packet)
    return packet


def _install_valid_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    corpus_dir = tmp_path / "corpus"
    packet_dir = tmp_path / "packets"
    ledger_path = tmp_path / "budget.jsonl"
    corpus_dir.mkdir()
    packet_dir.mkdir()
    corpus_dir.joinpath("fixture.json").write_text("{}\n")
    cases = tuple(_case(index) for index in range(16))
    clean_cases = tuple(
        {key: value for key, value in case.items() if key != "_content"} for case in cases
    )
    monkeypatch.setattr(
        preflight_module,
        "validate_corpus_directory",
        lambda _path: CorpusIntegrityReport(
            benchmark_id=BENCHMARK_ID,
            corpus_files=8,
            outcome_files=8,
            case_count=24,
            split_counts={"development": 16, "holdout": 8},
            domain_counts={"software_engineering": 6},
            issues=(),
        ),
    )
    monkeypatch.setattr(preflight_module, "load_visible_cases", lambda _path: clean_cases)

    packets = {str(case["case_id"]): _packet(case) for case in cases}
    entries = [
        {"case_id": case_id, "packet_sha256": packet["packet_sha256"]}
        for case_id, packet in sorted(packets.items())
    ]
    manifest: dict[str, object] = {
        "schema_version": PACKET_SET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "split": "development",
        "packet_count": 16,
        "source_count": 16,
        "packets": entries,
    }
    manifest["packet_set_sha256"] = canonical_json_sha256(manifest)
    packet_dir.joinpath("packet-set.json").write_text(json.dumps(manifest) + "\n")
    for case_id, packet in packets.items():
        packet_dir.joinpath(f"{case_id}.packet.json").write_text(json.dumps(packet) + "\n")
    return corpus_dir, packet_dir, ledger_path


def test_preflight_renders_all_prompts_without_mutating_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)

    first = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(),
        utc_date=TODAY,
    )
    second = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(),
        utc_date=TODAY,
    )

    assert first.ready is True
    assert first == second
    assert first.to_dict()["prompt_count"] == 64
    assert first.prompt_set_sha256 is not None
    assert len(first.case_ids) == 16
    assert first.condition_ids == tuple(item.condition_id for item in FROZEN_CONDITION_ROSTER)
    assert not ledger_path.exists()
    serialized = json.dumps(first.to_dict())
    assert "API_KEY" not in serialized
    assert {item["observed_catalog_owner"] for item in first.transport_readiness} == {
        "anthropic",
        "openai",
        "antigravity",
    }
    assert all(item["ready"] is True for item in first.transport_readiness)


def test_missing_catalog_model_blocks_before_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)
    members = tuple(condition.members[0] for condition in FROZEN_CONDITION_ROSTER[:3])
    models = frozenset(member.requested_model for member in members if member.family != "openai")

    report = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(models=models),
        utc_date=TODAY,
    )

    assert report.ready is False
    assert [item.code for item in report.blockers] == ["vibeproxy_model_unavailable"]
    openai = next(item for item in report.transport_readiness if item["family"] == "openai")
    assert openai["catalog_model_present"] is False
    assert openai["ready"] is False


def test_catalog_owner_must_match_frozen_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)
    members = tuple(condition.members[0] for condition in FROZEN_CONDITION_ROSTER[:3])
    owners = frozenset(
        (member.requested_model, "other" if member.family == "gemini" else member.catalog_owner)
        for member in members
    )

    report = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(owners=owners),
        utc_date=TODAY,
    )

    assert report.ready is False
    assert [item.code for item in report.blockers] == ["vibeproxy_owner_mismatch"]
    gemini = next(item for item in report.transport_readiness if item["family"] == "gemini")
    assert gemini["expected_catalog_owner"] == "antigravity"
    assert gemini["observed_catalog_owner"] == "other"
    assert gemini["ready"] is False


def test_ambiguous_catalog_owner_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)
    members = tuple(condition.members[0] for condition in FROZEN_CONDITION_ROSTER[:3])
    owners = frozenset(
        (member.requested_model, member.catalog_owner) for member in members
    ) | frozenset({(members[0].requested_model, "other")})

    report = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(owners=owners),
        utc_date=TODAY,
    )

    assert report.ready is False
    assert [item.code for item in report.blockers] == ["vibeproxy_owner_mismatch"]
    claude = next(item for item in report.transport_readiness if item["family"] == "claude")
    assert claude["observed_catalog_owner"] is None
    assert claude["ready"] is False


@pytest.mark.parametrize(
    ("client", "blocker"),
    [
        (
            FakeVibeProxyClient(
                loopback=False,
                failure=AssertionError("non-loopback endpoint must not be probed"),
            ),
            "vibeproxy_not_loopback",
        ),
        (FakeVibeProxyClient(routes=("GET /v1/models",)), "vibeproxy_protocol_unavailable"),
        (
            FakeVibeProxyClient(failure=VibeProxyUnavailableError("credential detail")),
            "vibeproxy_unavailable",
        ),
    ],
)
def test_transport_probe_fails_closed_without_exposing_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: FakeVibeProxyClient,
    blocker: str,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)

    report = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=client,
        utc_date=TODAY,
    )

    assert report.ready is False
    assert blocker in {item.code for item in report.blockers}
    assert "credential detail" not in json.dumps(report.to_dict())


def test_packet_tampering_blocks_before_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)
    path = packet_dir / "case-00.packet.json"
    packet = json.loads(path.read_text())
    packet["sources"][0]["content"] = "tampered"
    packet["packet_sha256"] = canonical_json_sha256(
        {key: value for key, value in packet.items() if key != "packet_sha256"}
    )
    path.write_text(json.dumps(packet) + "\n")

    report = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(),
        utc_date=TODAY,
    )

    assert report.ready is False
    assert any(item.code == "development_packets_not_ready" for item in report.blockers)
    assert report.prompt_set_sha256 is None


def test_open_budget_reservation_blocks_and_snapshot_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir, packet_dir, ledger_path = _install_valid_inputs(tmp_path, monkeypatch)
    ledger = preflight_module.OutcomeBackedBudgetLedger(ledger_path)
    ledger.reserve(
        reservation_id="reservation-1",
        logical_call_id="logical-1",
        run_id="development-run",
        case_id="case-00",
        condition_id="claude-single",
        attempt=1,
        estimated_cost_usd="2",
        recorded_at=datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
    )
    before = ledger_path.read_bytes()

    report = preflight_development_run(
        corpus_dir,
        packet_dir,
        ledger_path,
        implementation_sha=HEAD,
        vibeproxy_client=FakeVibeProxyClient(),
        utc_date=TODAY,
    )

    assert any(item.code == "open_budget_reservations" for item in report.blockers)
    assert ledger_path.read_bytes() == before


@pytest.mark.parametrize("sha", ["", "A" * 40, "a" * 39, "not-a-sha"])
def test_invalid_implementation_sha_fails_closed(
    tmp_path: Path,
    sha: str,
) -> None:
    with pytest.raises(OutcomeBackedPreflightError, match="lowercase 40-hex"):
        preflight_development_run(
            tmp_path,
            tmp_path,
            tmp_path / "budget.jsonl",
            implementation_sha=sha,
            vibeproxy_client=FakeVibeProxyClient(),
            utc_date=TODAY,
        )
