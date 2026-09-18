"""Outcome-backed decision-quality benchmark harness and deterministic scorer.

The harness is intentionally transport-neutral.  A runner receives one
model-visible case packet and must return a structured response.  This module
owns corpus freezing, family/roster integrity, retry and budget policy,
append-only result recording, independent receipt verification, and scoring.
Outcome sidecars are never passed to the runner.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from aragora.evaluation.decision_quality_corpus import (
    CorpusValidationReport,
    TrancheInput,
    assemble_tranches,
    canonical_json_bytes,
    canonical_sha256,
    load_json_document,
)
from aragora.evaluation.manifold_brier import brier_score

MANIFEST_SCHEMA_VERSION = "decision-quality-benchmark/1.0"
ROSTER_SCHEMA_VERSION = "decision-quality-roster/1.0"
RESULT_SCHEMA_VERSION = "decision-quality-result/1.0"
SCORE_SCHEMA_VERSION = "decision-quality-score/1.0"
HOLDOUT_LOCK_SCHEMA_VERSION = "decision-quality-holdout-lock/1.0"
SCORER_CONTRACT_VERSION = "outcome-decision-quality-scorer/1.0"
CANONICAL_JSON_CONVENTION = "python-json-sort-keys-compact-utf8-no-nan-v1"
REQUIRED_CONDITIONS = (
    "single_claude",
    "single_openai",
    "single_gemini",
    "aragora_team",
)

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ContractIssue:
    path: str
    code: str
    message: str


@dataclass
class BenchmarkContractReport:
    manifest_sha256: str | None = None
    corpus_sha256: str | None = None
    outcomes_sha256: str | None = None
    case_count: int = 0
    issues: list[ContractIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "manifest_sha256": self.manifest_sha256,
            "corpus_sha256": self.corpus_sha256,
            "outcomes_sha256": self.outcomes_sha256,
            "case_count": self.case_count,
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass(frozen=True)
class BenchmarkBundle:
    manifest_path: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    corpus: dict[str, Any]
    outcomes: dict[str, Any]
    prompt_contract: str
    roster: dict[str, Any]

    @property
    def cases(self) -> list[dict[str, Any]]:
        return list(self.corpus["cases"])


@dataclass(frozen=True)
class CostEntry:
    recorded_at: str
    run_id: str
    case_id: str
    condition: str
    family: str
    model: str
    transport: str
    billing_class: str
    cost_usd: float


@dataclass
class CostLedger:
    """Append-only paid-API budget ledger grouped by UTC day."""

    path: Path
    daily_cap_usd: float
    entries: list[CostEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path, daily_cap_usd: float) -> CostLedger:
        ledger = cls(path=path, daily_cap_usd=daily_cap_usd)
        if not path.exists():
            return ledger
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot read cost ledger {path}: {exc}") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                ledger.entries.append(CostEntry(**payload))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"invalid cost ledger line {line_number}: {exc}") from exc
        return ledger

    def paid_total(self, utc_day: str) -> float:
        return sum(
            entry.cost_usd
            for entry in self.entries
            if entry.billing_class == "paid_api" and entry.recorded_at[:10] == utc_day
        )

    def require_capacity(self, utc_day: str, projected_cost_usd: float) -> None:
        if projected_cost_usd < 0:
            raise ValueError("projected cost must not be negative")
        projected = self.paid_total(utc_day) + projected_cost_usd
        if projected > self.daily_cap_usd + 1e-9:
            raise RuntimeError(
                f"paid API budget exhausted for {utc_day}: "
                f"projected ${projected:.4f} > ${self.daily_cap_usd:.4f}"
            )

    def append(self, entries: Iterable[CostEntry]) -> None:
        new_entries = list(entries)
        if not new_entries:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            for entry in new_entries:
                stream.write(json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.entries.extend(new_entries)


Runner = Callable[[dict[str, Any]], dict[str, Any]]


def _contract_issue(report: BenchmarkContractReport, path: str, code: str, message: str) -> None:
    report.issues.append(ContractIssue(path, code, message))


def _safe_artifact_path(manifest_dir: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    resolved = (manifest_dir / relative).resolve()
    try:
        resolved.relative_to(manifest_dir.resolve())
    except ValueError:
        return None
    return resolved


def _read_text(path: Path) -> tuple[str | None, ContractIssue | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, ContractIssue(str(path), "read_error", str(exc))
    except UnicodeError as exc:
        return None, ContractIssue(str(path), "invalid_utf8", str(exc))


def load_benchmark_bundle(
    manifest_path: Path,
) -> tuple[BenchmarkBundle | None, BenchmarkContractReport]:
    """Load and verify every file pinned by the frozen benchmark manifest."""
    report = BenchmarkContractReport()
    manifest_doc, manifest_issue = load_json_document(manifest_path)
    if manifest_issue is not None:
        report.issues.append(ContractIssue(**asdict(manifest_issue)))
        return None, report
    if not isinstance(manifest_doc, dict):
        _contract_issue(report, "$", "invalid_manifest", "manifest must be a JSON object")
        return None, report
    try:
        report.manifest_sha256 = canonical_sha256(manifest_doc)
    except (TypeError, ValueError) as exc:
        _contract_issue(report, "$", "non_canonical_json", str(exc))
        return None, report
    if manifest_doc.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        _contract_issue(report, "$.schema_version", "unsupported_schema", MANIFEST_SCHEMA_VERSION)
    if manifest_doc.get("canonical_json") != CANONICAL_JSON_CONVENTION:
        _contract_issue(report, "$.canonical_json", "canonicalization_mismatch", "unsupported")
    if tuple(manifest_doc.get("conditions", ())) != REQUIRED_CONDITIONS:
        _contract_issue(
            report,
            "$.conditions",
            "condition_roster_mismatch",
            f"must equal {REQUIRED_CONDITIONS}",
        )

    manifest_dir = manifest_path.resolve().parent
    prompt_spec = manifest_doc.get("prompt")
    roster_spec = manifest_doc.get("roster")
    if not isinstance(prompt_spec, dict) or not isinstance(roster_spec, dict):
        _contract_issue(report, "$", "missing_contract_artifact", "prompt and roster are required")
        return None, report
    prompt_path = _safe_artifact_path(manifest_dir, prompt_spec.get("path"))
    roster_path = _safe_artifact_path(manifest_dir, roster_spec.get("path"))
    if prompt_path is None or roster_path is None:
        _contract_issue(report, "$", "unsafe_artifact_path", "artifact paths must stay local")
        return None, report
    prompt_text, prompt_issue = _read_text(prompt_path)
    roster_doc, roster_issue = load_json_document(roster_path)
    if prompt_issue is not None:
        report.issues.append(prompt_issue)
    if roster_issue is not None:
        report.issues.append(ContractIssue(**asdict(roster_issue)))
    if roster_doc is not None and not isinstance(roster_doc, dict):
        _contract_issue(report, "$.roster", "invalid_roster", "must be a JSON object")
    if prompt_text is None or not isinstance(roster_doc, dict):
        return None, report
    prompt_digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    if prompt_digest != prompt_spec.get("sha256"):
        _contract_issue(report, "$.prompt.sha256", "artifact_hash_mismatch", prompt_digest)
    roster_digest = canonical_sha256(roster_doc)
    if roster_digest != roster_spec.get("sha256"):
        _contract_issue(report, "$.roster.sha256", "artifact_hash_mismatch", roster_digest)
    _validate_roster(roster_doc, report)

    tranches = manifest_doc.get("tranches")
    tranche_inputs: list[TrancheInput] = []
    if not isinstance(tranches, list) or len(tranches) != 8:
        _contract_issue(report, "$.tranches", "invalid_tranche_count", "must contain eight")
    else:
        for index, raw in enumerate(tranches):
            if not isinstance(raw, dict):
                _contract_issue(report, f"$.tranches[{index}]", "invalid_tranche", "must be object")
                continue
            corpus_path = _safe_artifact_path(manifest_dir, raw.get("corpus_path"))
            outcomes_path = _safe_artifact_path(manifest_dir, raw.get("outcomes_path"))
            corpus_digest = raw.get("corpus_sha256")
            outcomes_digest = raw.get("outcomes_sha256")
            if corpus_path is None or outcomes_path is None:
                _contract_issue(
                    report, f"$.tranches[{index}]", "unsafe_artifact_path", "invalid path"
                )
            elif not all(
                isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in (corpus_digest, outcomes_digest)
            ):
                _contract_issue(
                    report, f"$.tranches[{index}]", "invalid_sha256", "digests required"
                )
            else:
                tranche_inputs.append(
                    TrancheInput(
                        corpus_path, outcomes_path, str(corpus_digest), str(outcomes_digest)
                    )
                )

    corpus: dict[str, Any] | None = None
    outcomes: dict[str, Any] | None = None
    if len(tranche_inputs) == 8:
        corpus, outcomes, corpus_report = assemble_tranches(
            tranche_inputs,
            benchmark_id=str(manifest_doc.get("benchmark_id", "")),
            revision=str(manifest_doc.get("revision", "")),
            frozen_at=str(manifest_doc.get("frozen_at", "")),
        )
        _copy_corpus_issues(corpus_report, report)
        report.corpus_sha256 = corpus_report.corpus_sha256
        report.outcomes_sha256 = corpus_report.outcomes_sha256
        report.case_count = corpus_report.case_count
    aggregate = manifest_doc.get("aggregate")
    if not isinstance(aggregate, dict):
        _contract_issue(report, "$.aggregate", "missing_aggregate", "required")
    else:
        for key, actual in (
            ("corpus_sha256", report.corpus_sha256),
            ("outcomes_sha256", report.outcomes_sha256),
            ("case_count", report.case_count),
        ):
            if aggregate.get(key) != actual:
                _contract_issue(report, f"$.aggregate.{key}", "aggregate_mismatch", str(actual))
    scorer = manifest_doc.get("scorer")
    if not isinstance(scorer, dict) or scorer.get("contract_version") != SCORER_CONTRACT_VERSION:
        _contract_issue(report, "$.scorer", "scorer_contract_mismatch", SCORER_CONTRACT_VERSION)
    budget = manifest_doc.get("budget")
    if (
        not isinstance(budget, dict)
        or budget.get("paid_api_daily_usd") != 25.0
        or budget.get("infrastructure_retries_per_call") != 1
    ):
        _contract_issue(report, "$.budget", "budget_contract_mismatch", "must be $25 and one retry")
    holdout = manifest_doc.get("holdout")
    if not isinstance(holdout, dict) or holdout.get("repetitions") != 2:
        _contract_issue(
            report, "$.holdout", "holdout_contract_mismatch", "two repetitions required"
        )
    if report.issues or corpus is None or outcomes is None:
        return None, report
    return (
        BenchmarkBundle(
            manifest_path=manifest_path.resolve(),
            manifest=manifest_doc,
            manifest_sha256=report.manifest_sha256 or "",
            corpus=corpus,
            outcomes=outcomes,
            prompt_contract=prompt_text,
            roster=roster_doc,
        ),
        report,
    )


def _copy_corpus_issues(source: CorpusValidationReport, target: BenchmarkContractReport) -> None:
    for issue in source.issues:
        target.issues.append(ContractIssue(issue.path, issue.code, issue.message))


def _validate_roster(roster: dict[str, Any], report: BenchmarkContractReport) -> None:
    if roster.get("schema_version") != ROSTER_SCHEMA_VERSION:
        _contract_issue(
            report, "$.roster.schema_version", "unsupported_schema", ROSTER_SCHEMA_VERSION
        )
    conditions = roster.get("conditions")
    if not isinstance(conditions, dict) or set(conditions) != set(REQUIRED_CONDITIONS):
        _contract_issue(
            report, "$.roster.conditions", "incomplete_roster", "four conditions required"
        )
        return
    for condition_name, condition in conditions.items():
        if not isinstance(condition, dict):
            _contract_issue(report, f"$.roster.{condition_name}", "invalid_condition", "object")
            continue
        members = condition.get("members")
        if not isinstance(members, list) or not members:
            _contract_issue(
                report, f"$.roster.{condition_name}.members", "incomplete_roster", "required"
            )
            continue
        families: set[str] = set()
        for index, member in enumerate(members):
            path = f"$.roster.{condition_name}.members[{index}]"
            if not isinstance(member, dict):
                _contract_issue(report, path, "invalid_member", "must be object")
                continue
            family = member.get("family")
            if family in families:
                _contract_issue(report, f"{path}.family", "duplicate_family", str(family))
            elif isinstance(family, str):
                families.add(family)
            for key in ("requested_model", "transport", "billing_class"):
                if not isinstance(member.get(key), str) or not member[key]:
                    _contract_issue(report, f"{path}.{key}", "missing_field", "required")
            resolved = member.get("allowed_resolved_models")
            if (
                not isinstance(resolved, list)
                or not resolved
                or not all(isinstance(model, str) and model for model in resolved)
            ):
                _contract_issue(
                    report, f"{path}.allowed_resolved_models", "missing_field", "required"
                )
        expected = {condition_name.removeprefix("single_")}
        if condition_name == "aragora_team":
            expected = {"claude", "openai", "gemini"}
            if condition.get("adversarial_rounds") != 1:
                _contract_issue(report, f"$.roster.{condition_name}", "round_contract", "one round")
        if families != expected:
            _contract_issue(
                report,
                f"$.roster.{condition_name}.members",
                "family_roster_mismatch",
                f"expected {sorted(expected)}",
            )


def build_model_visible_request(
    bundle: BenchmarkBundle,
    case: dict[str, Any],
    condition: str,
    *,
    repetition: int,
    implementation_sha: str,
) -> dict[str, Any]:
    """Build one request packet with no outcome-sidecar content."""
    roster_condition = bundle.roster["conditions"][condition]
    return {
        "schema_version": "decision-quality-request/1.0",
        "benchmark_id": bundle.manifest["benchmark_id"],
        "revision": bundle.manifest["revision"],
        "manifest_sha256": bundle.manifest_sha256,
        "implementation_sha": implementation_sha,
        "repetition": repetition,
        "condition": condition,
        "prompt_contract": bundle.prompt_contract,
        "case": json.loads(json.dumps(case)),
        "roster": json.loads(json.dumps(roster_condition)),
    }


def request_contains_outcome_data(request: dict[str, Any], outcome: dict[str, Any]) -> bool:
    """Conservatively detect answer-sidecar strings in a model request."""
    request_text = canonical_json_bytes(request).decode("utf-8")
    forbidden: list[Any] = [
        outcome.get("resolved_at"),
        outcome.get("resolution_summary"),
    ]
    for source in outcome.get("authoritative_sources", []):
        forbidden.extend(source.values())
    for crux in outcome.get("cruxes", []):
        forbidden.extend((crux.get("crux_id"), crux.get("description")))
        # Aliases are intentionally lexical and can occur naturally in the
        # pre-cutoff packet (for example, "compliance readiness").  Treating
        # those coincidences as sidecar disclosure makes valid frozen cases
        # un-runnable.  Stable IDs and full preregistered descriptions remain
        # forbidden and provide the fail-closed structural markers.
    return any(isinstance(value, str) and value and value in request_text for value in forbidden)


def run_subprocess_runner(
    command: list[str], request: dict[str, Any], timeout: float
) -> dict[str, Any]:
    """Invoke a JSON-in/JSON-out runner command with a hard timeout."""
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "infrastructure_failure": True, "error_class": "runner_timeout"}
    except OSError:
        return {
            "ok": False,
            "infrastructure_failure": True,
            "error_class": "runner_spawn_failed",
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "infrastructure_failure": True,
            "error_class": "runner_nonzero_exit",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "infrastructure_failure": True,
            "error_class": "runner_invalid_json",
            "error": f"invalid JSON at line {exc.lineno}, column {exc.colno}",
        }
    if not isinstance(payload, dict):
        return {"ok": False, "infrastructure_failure": True, "error_class": "runner_invalid_shape"}
    return payload


def _member_index(condition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {member["family"]: member for member in condition["members"]}


def _nonnegative_finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def validate_runner_response(response: dict[str, Any], condition: dict[str, Any]) -> list[str]:
    """Validate result shape and exact family/model/transport integrity."""
    errors: list[str] = []
    calls = response.get("calls")
    if not isinstance(calls, list):
        return ["calls must be a list"]
    expected = _member_index(condition)
    observed: Counter[str] = Counter()
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            errors.append(f"calls[{index}] must be an object")
            continue
        family = call.get("family")
        observed[str(family)] += 1
        member = expected.get(str(family))
        if member is None:
            errors.append(f"calls[{index}] unexpected family {family!r}")
            continue
        if call.get("requested_model") != member["requested_model"]:
            errors.append(f"calls[{index}] requested model drift")
        if call.get("resolved_model") not in member["allowed_resolved_models"]:
            errors.append(f"calls[{index}] resolved model identity mismatch")
        if call.get("transport") != member["transport"]:
            errors.append(f"calls[{index}] transport drift")
        if call.get("billing_class") != member["billing_class"]:
            errors.append(f"calls[{index}] billing class drift")
        latency = _nonnegative_finite_number(call.get("latency_ms"))
        cost = _nonnegative_finite_number(call.get("cost_usd"))
        if latency is None:
            errors.append(f"calls[{index}] invalid latency")
        if cost is None:
            errors.append(f"calls[{index}] invalid cost")
    for family in expected:
        count = observed[family]
        if count == 0:
            errors.append(f"incomplete roster: missing {family}")
        elif count != 1:
            errors.append(f"duplicate family {family}: expected exactly one call, observed {count}")
    output = response.get("output")
    if not isinstance(output, dict):
        errors.append("output must be an object")
    else:
        if not isinstance(output.get("selected_option_id"), str):
            errors.append("output.selected_option_id is required")
        probability = output.get("forecast_probability")
        if not isinstance(probability, (int, float)) or not 0 <= float(probability) <= 1:
            errors.append("output.forecast_probability must be in [0,1]")
        for key in ("cruxes", "source_ids"):
            if not isinstance(output.get(key), list) or not all(
                isinstance(item, str) and item.strip() for item in output.get(key, [])
            ):
                errors.append(f"output.{key} must contain non-empty strings")
    return errors


def verify_receipt(
    path: Path | None,
    *,
    expected_input_hash: str | None = None,
    expected_output: dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    """Hash and independently verify a team DecisionReceipt."""
    if path is None:
        return None, "missing"
    payload, issue = load_json_document(path)
    if issue is not None or not isinstance(payload, dict):
        return None, "invalid"
    digest = canonical_sha256(payload)
    if expected_input_hash is not None and payload.get("input_hash") != expected_input_hash:
        return digest, "input_mismatch"
    if expected_output is not None and payload.get("decision_payload") != expected_output:
        return digest, "decision_mismatch"
    try:
        from aragora.gauntlet.receipt_models import DecisionReceipt

        receipt = DecisionReceipt.from_dict(payload)
        verified = receipt.verify_integrity()
    except (AttributeError, ImportError, KeyError, TypeError, ValueError):
        return digest, "invalid"
    return digest, "verified" if verified else "failed"


def holdout_lock_payload(bundle: BenchmarkBundle, implementation_sha: str) -> dict[str, Any]:
    return {
        "schema_version": HOLDOUT_LOCK_SCHEMA_VERSION,
        "benchmark_id": bundle.manifest["benchmark_id"],
        "revision": bundle.manifest["revision"],
        "manifest_sha256": bundle.manifest_sha256,
        "corpus_sha256": canonical_sha256(bundle.corpus),
        "outcomes_sha256": canonical_sha256(bundle.outcomes),
        "prompt_sha256": bundle.manifest["prompt"]["sha256"],
        "roster_sha256": bundle.manifest["roster"]["sha256"],
        "scorer_contract_version": SCORER_CONTRACT_VERSION,
        "implementation_sha": implementation_sha,
    }


def ensure_holdout_lock(path: Path, bundle: BenchmarkBundle, implementation_sha: str) -> None:
    expected = holdout_lock_payload(bundle, implementation_sha)
    if path.exists():
        observed, issue = load_json_document(path)
        if issue is not None or observed != expected:
            raise RuntimeError("holdout lock mismatch: inputs changed between repetitions")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def execute_batch(
    bundle: BenchmarkBundle,
    runner: Runner,
    *,
    split: str,
    repetition: int,
    implementation_sha: str,
    run_id: str,
    results_path: Path,
    cost_ledger: CostLedger,
    recorded_at: datetime | None = None,
    max_cases: int | None = None,
    holdout_lock_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one bounded batch and append every success/failure result."""
    if split not in {"development", "holdout"}:
        raise ValueError("split must be development or holdout")
    if _SHA_PATTERN.fullmatch(implementation_sha) is None:
        raise ValueError("implementation_sha must be a full lowercase git SHA")
    if split == "development" and repetition != 1:
        raise ValueError("development cases run once")
    if split == "holdout" and repetition not in (1, 2):
        raise ValueError("holdout repetition must be 1 or 2")
    if split == "holdout":
        ensure_holdout_lock(
            holdout_lock_path or results_path.parent / "holdout-lock.json",
            bundle,
            implementation_sha,
        )
    now = recorded_at or datetime.now(UTC)
    utc_day = now.date().isoformat()
    outcome_by_case = {item["case_id"]: item for item in bundle.outcomes["outcomes"]}
    cases = [case for case in bundle.cases if case["split"] == split]
    if max_cases is not None:
        cases = cases[:max_cases]
    completed = 0
    failures = 0
    retries = 0
    for case in cases:
        for condition_name in REQUIRED_CONDITIONS:
            condition = bundle.roster["conditions"][condition_name]
            max_paid = float(condition.get("max_paid_cost_usd", 0.0))
            cost_ledger.require_capacity(utc_day, max_paid)
            request = build_model_visible_request(
                bundle,
                case,
                condition_name,
                repetition=repetition,
                implementation_sha=implementation_sha,
            )
            if request_contains_outcome_data(request, outcome_by_case[case["case_id"]]):
                raise RuntimeError(f"outcome leakage detected in request for {case['case_id']}")
            attempts = 0
            response: dict[str, Any]
            while True:
                attempts += 1
                response = runner(request)
                if not response.get("infrastructure_failure") or attempts >= 2:
                    break
                retries += 1
            errors = validate_runner_response(response, condition)
            if response.get("ok") is not True:
                errors.append(str(response.get("error_class") or "runner_failure"))
            receipt_path_value = response.get("receipt_path")
            receipt_path = Path(receipt_path_value) if isinstance(receipt_path_value, str) else None
            response_output = response.get("output")
            receipt_hash, receipt_verification = (
                verify_receipt(
                    receipt_path,
                    expected_input_hash=hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
                    expected_output=response_output if isinstance(response_output, dict) else None,
                )
                if condition_name == "aragora_team"
                else (None, "not_applicable")
            )
            if condition_name == "aragora_team" and receipt_verification != "verified":
                errors.append(f"team receipt {receipt_verification}")
            raw_calls = response.get("calls")
            call_items: list[Any] = raw_calls if isinstance(raw_calls, list) else []
            calls: list[dict[str, Any]] = []
            cost_entries: list[CostEntry] = []
            unknown_paid_cost = False
            for call in call_items:
                if not isinstance(call, dict):
                    continue
                latency = _nonnegative_finite_number(call.get("latency_ms"))
                cost = _nonnegative_finite_number(call.get("cost_usd"))
                recorded_call = dict(call)
                recorded_call["latency_ms"] = latency if latency is not None else 0.0
                recorded_call["cost_usd"] = cost if cost is not None else 0.0
                calls.append(recorded_call)
                billing_class = str(call.get("billing_class", ""))
                if cost is None and billing_class == "paid_api":
                    unknown_paid_cost = True
                    continue
                cost_entries.append(
                    CostEntry(
                        recorded_at=now.isoformat().replace("+00:00", "Z"),
                        run_id=run_id,
                        case_id=case["case_id"],
                        condition=condition_name,
                        family=str(call.get("family", "")),
                        model=str(call.get("resolved_model", "")),
                        transport=str(call.get("transport", "")),
                        billing_class=billing_class,
                        cost_usd=cost if cost is not None else 0.0,
                    )
                )
            if unknown_paid_cost:
                cost_entries = [
                    entry for entry in cost_entries if entry.billing_class != "paid_api"
                ]
                cost_entries.append(
                    CostEntry(
                        recorded_at=now.isoformat().replace("+00:00", "Z"),
                        run_id=run_id,
                        case_id=case["case_id"],
                        condition=condition_name,
                        family="unknown",
                        model="unknown",
                        transport="unknown",
                        billing_class="paid_api",
                        cost_usd=max_paid,
                    )
                )
            actual_paid = sum(
                entry.cost_usd for entry in cost_entries if entry.billing_class == "paid_api"
            )
            try:
                cost_ledger.require_capacity(utc_day, actual_paid)
            except RuntimeError as exc:
                errors.append(str(exc))
            cost_ledger.append(cost_entries)
            primary_call = calls[-1] if calls else {}
            result = {
                "schema_version": RESULT_SCHEMA_VERSION,
                "run_id": run_id,
                "benchmark_id": bundle.manifest["benchmark_id"],
                "revision": bundle.manifest["revision"],
                "manifest_sha256": bundle.manifest_sha256,
                "implementation_sha": implementation_sha,
                "case_id": case["case_id"],
                "domain": case["domain"],
                "split": split,
                "repetition": repetition,
                "condition": condition_name,
                "requested_model": primary_call.get("requested_model"),
                "resolved_model": primary_call.get("resolved_model"),
                "transport": primary_call.get("transport"),
                "calls": calls,
                "output": response.get("output"),
                "latency_ms": sum(float(call["latency_ms"]) for call in calls),
                "cost_usd": sum(entry.cost_usd for entry in cost_entries),
                "errors": sorted(set(errors)),
                "attempt_count": attempts,
                "receipt_hash": receipt_hash,
                "receipt_verification": receipt_verification,
                "recorded_at": now.isoformat().replace("+00:00", "Z"),
            }
            _append_jsonl(results_path, result)
            if errors:
                failures += 1
            else:
                completed += 1
    return {
        "ok": failures == 0,
        "completed": completed,
        "failures": failures,
        "infrastructure_retries": retries,
        "results_path": str(results_path),
        "paid_api_spend_today": cost_ledger.paid_total(utc_day),
    }


def _normalize_tokens(text: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(text.lower()))


def crux_recall(predicted: list[str], expected: list[dict[str, Any]]) -> float:
    """Deterministically score preregistered crux coverage."""
    if not expected:
        return 0.0
    predicted_tokens = [_normalize_tokens(item) for item in predicted]
    hits = 0
    for crux in expected:
        candidates = [str(crux.get("description", "")), *crux.get("aliases", [])]
        matched = False
        for candidate in candidates:
            expected_tokens = _normalize_tokens(candidate)
            if not expected_tokens:
                continue
            for observed in predicted_tokens:
                overlap = len(expected_tokens & observed) / len(expected_tokens)
                if overlap >= 0.6:
                    matched = True
                    break
            if matched:
                break
        hits += int(matched)
    return hits / len(expected)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def load_results(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_number}: {exc}")
                continue
            if not isinstance(value, dict) or value.get("schema_version") != RESULT_SCHEMA_VERSION:
                errors.append(f"{path}:{line_number}: invalid result schema")
            else:
                results.append(value)
    return results, errors


def _require_result_bindings(
    bundle: BenchmarkBundle,
    results: list[dict[str, Any]],
    implementation_sha: str,
) -> None:
    if _SHA_PATTERN.fullmatch(implementation_sha) is None:
        raise ValueError("implementation_sha must be a full lowercase git SHA")
    expected = {
        "benchmark_id": bundle.manifest["benchmark_id"],
        "revision": bundle.manifest["revision"],
        "manifest_sha256": bundle.manifest_sha256,
        "implementation_sha": implementation_sha,
    }
    for index, result in enumerate(results):
        for field_name, expected_value in expected.items():
            if result.get(field_name) != expected_value:
                raise ValueError(f"result binding mismatch at result {index}: {field_name}")


def score_results(
    bundle: BenchmarkBundle,
    results: list[dict[str, Any]],
    *,
    implementation_sha: str,
) -> dict[str, Any]:
    """Produce deterministic per-condition metrics and best-single deltas."""
    _require_result_bindings(bundle, results, implementation_sha)
    case_by_id = {case["case_id"]: case for case in bundle.cases}
    outcome_by_id = {outcome["case_id"]: outcome for outcome in bundle.outcomes["outcomes"]}
    per_condition: dict[str, list[dict[str, float]]] = defaultdict(list)
    per_split: dict[str, dict[str, list[dict[str, float]]]] = {
        "development": defaultdict(list),
        "holdout": defaultdict(list),
    }
    incomplete: list[str] = []
    observed_keys: Counter[str] = Counter()
    for result in sorted(
        results,
        key=lambda item: (
            item.get("split", ""),
            item.get("repetition", 0),
            item.get("case_id", ""),
            item.get("condition", ""),
        ),
    ):
        key = f"{result.get('case_id')}:{result.get('condition')}:r{result.get('repetition')}"
        observed_keys[key] += 1
        if result.get("errors"):
            incomplete.append(key)
            continue
        case = case_by_id.get(result.get("case_id"))
        outcome = outcome_by_id.get(result.get("case_id"))
        output = result.get("output")
        if case is None or outcome is None or not isinstance(output, dict):
            incomplete.append(key)
            continue
        try:
            probability = float(output["forecast_probability"])
        except (KeyError, TypeError, ValueError):
            incomplete.append(key)
            continue
        if not 0 <= probability <= 1:
            incomplete.append(key)
            continue
        target = int(outcome["correct_option_id"] == case["forecast_option_id"])
        source_ids = {source["source_id"] for source in case["sources"]}
        cited = {str(item) for item in output.get("source_ids", [])}
        provenance = len(source_ids & cited) / len(source_ids) if source_ids else 1.0
        try:
            row = {
                "brier": brier_score(probability, target),
                "accuracy": float(output["selected_option_id"] == outcome["correct_option_id"]),
                "crux_recall": crux_recall(output.get("cruxes", []), outcome["cruxes"]),
                "provenance": provenance,
                "receipt_verified": float(result.get("receipt_verification") == "verified"),
                "latency_ms": float(result.get("latency_ms", 0.0)),
                "cost_usd": float(result.get("cost_usd", 0.0)),
                "calls": float(len(result.get("calls", []))),
            }
        except (KeyError, TypeError, ValueError):
            incomplete.append(key)
            continue
        condition_name = str(result.get("condition", ""))
        split_name = str(result.get("split", ""))
        if condition_name not in REQUIRED_CONDITIONS or split_name not in per_split:
            incomplete.append(key)
            continue
        per_condition[condition_name].append(row)
        per_split[split_name][condition_name].append(row)

    expected_keys = {
        f"{case['case_id']}:{condition}:r{repetition}"
        for case in bundle.cases
        for condition in REQUIRED_CONDITIONS
        for repetition in ((1,) if case["split"] == "development" else (1, 2))
    }
    incomplete.extend(sorted(expected_keys - observed_keys.keys()))
    incomplete.extend(sorted(key for key, count in observed_keys.items() if count != 1))
    summaries: dict[str, dict[str, Any]] = {}
    for condition in REQUIRED_CONDITIONS:
        rows = per_condition.get(condition, [])
        summaries[condition] = _summarize_rows(rows)
    split_summaries = {
        split_name: {
            condition: _summarize_rows(per_split[split_name].get(condition, []))
            for condition in REQUIRED_CONDITIONS
        }
        for split_name in ("development", "holdout")
    }
    primary = split_summaries["holdout"]
    complete_singles = [name for name in REQUIRED_CONDITIONS[:3] if primary[name]["n"] > 0]
    best_single = (
        min(complete_singles, key=lambda name: primary[name]["mean_brier"])
        if complete_singles
        else None
    )
    team_brier = primary["aragora_team"]["mean_brier"]
    delta = (
        primary[best_single]["mean_brier"] - team_brier
        if best_single is not None and team_brier is not None
        else None
    )
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "benchmark_id": bundle.manifest["benchmark_id"],
        "revision": bundle.manifest["revision"],
        "manifest_sha256": bundle.manifest_sha256,
        "implementation_sha": implementation_sha,
        "result_count": len(results),
        "incomplete_results": sorted(set(incomplete)),
        "conditions": summaries,
        "splits": split_summaries,
        "best_single_condition": best_single,
        "team_brier_improvement": delta,
        "target_team_brier_improvement": 0.05,
        "decision": _score_decision(summaries, incomplete, delta),
        "uncertainty_note": (
            "Descriptive ranges are reported for this small frozen corpus; "
            "no statistical-significance claim is made."
        ),
    }


def _summarize_rows(rows: list[dict[str, float]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mean_brier": None,
            "brier_range": None,
            "directional_accuracy": None,
            "crux_recall": None,
            "provenance_completeness": None,
            "receipt_verification_rate": None,
            "p50_latency_ms": None,
            "p95_latency_ms": None,
            "model_calls": 0,
            "cost_usd": 0.0,
        }
    briers = [row["brier"] for row in rows]
    return {
        "n": len(rows),
        "mean_brier": statistics.fmean(briers),
        "brier_range": [min(briers), max(briers)],
        "directional_accuracy": statistics.fmean(row["accuracy"] for row in rows),
        "crux_recall": statistics.fmean(row["crux_recall"] for row in rows),
        "provenance_completeness": statistics.fmean(row["provenance"] for row in rows),
        "receipt_verification_rate": statistics.fmean(row["receipt_verified"] for row in rows),
        "p50_latency_ms": _percentile([row["latency_ms"] for row in rows], 0.5),
        "p95_latency_ms": _percentile([row["latency_ms"] for row in rows], 0.95),
        "model_calls": int(sum(row["calls"] for row in rows)),
        "cost_usd": sum(row["cost_usd"] for row in rows),
    }


def _score_decision(
    summaries: dict[str, dict[str, Any]], incomplete: list[str], delta: float | None
) -> str:
    if incomplete or any(summaries[name]["n"] == 0 for name in REQUIRED_CONDITIONS):
        return "incomplete"
    team = summaries["aragora_team"]
    if team["receipt_verification_rate"] != 1.0:
        return "no_go"
    return "go" if delta is not None and delta >= 0.05 else "conditional_go"


def render_markdown(score: dict[str, Any]) -> str:
    """Render a deterministic concise decision-quality report."""
    lines = [
        "# Outcome-Backed Decision Quality Report",
        "",
        f"- Benchmark: `{score['benchmark_id']}`",
        f"- Revision: `{score['revision']}`",
        f"- Manifest: `{score['manifest_sha256']}`",
        f"- Decision: `{score['decision']}`",
        f"- Best single: `{score['best_single_condition']}`",
        f"- Holdout team Brier improvement: `{_format_metric(score['team_brier_improvement'])}`",
        "- Target improvement: `0.05`",
        "",
        "## Metrics",
        "",
        "| Condition | N | Brier | Accuracy | Crux recall | Provenance | Receipt verify | Calls | Cost USD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in REQUIRED_CONDITIONS:
        metrics = score["conditions"][condition]
        lines.append(
            f"| `{condition}` | {metrics['n']} | {_format_metric(metrics['mean_brier'])} | "
            f"{_format_metric(metrics['directional_accuracy'])} | "
            f"{_format_metric(metrics['crux_recall'])} | "
            f"{_format_metric(metrics['provenance_completeness'])} | "
            f"{_format_metric(metrics['receipt_verification_rate'])} | "
            f"{metrics['model_calls']} | {metrics['cost_usd']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            f"- {score['uncertainty_note']}",
            f"- Incomplete result records: `{len(score['incomplete_results'])}`.",
            "- Outcomes and post-cutoff sources were withheld from all model prompts.",
            "",
        ]
    )
    return "\n".join(lines)


def _format_metric(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


__all__ = [
    "BenchmarkBundle",
    "BenchmarkContractReport",
    "CANONICAL_JSON_CONVENTION",
    "CostEntry",
    "CostLedger",
    "HOLDOUT_LOCK_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_CONDITIONS",
    "RESULT_SCHEMA_VERSION",
    "ROSTER_SCHEMA_VERSION",
    "SCORER_CONTRACT_VERSION",
    "SCORE_SCHEMA_VERSION",
    "build_model_visible_request",
    "crux_recall",
    "ensure_holdout_lock",
    "execute_batch",
    "holdout_lock_payload",
    "load_benchmark_bundle",
    "load_results",
    "render_markdown",
    "request_contains_outcome_data",
    "run_subprocess_runner",
    "score_results",
    "validate_runner_response",
    "verify_receipt",
]
