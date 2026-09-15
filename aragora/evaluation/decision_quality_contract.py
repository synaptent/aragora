"""Frozen contract loading for the outcome-backed decision-quality benchmark.

This module validates the benchmark manifest, prompt, roster, tranche hashes,
and aggregate corpus without running models or scoring results. Execution and
scoring are deliberately separate so the frozen contract can land first.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aragora.evaluation.decision_quality_corpus import (
    CorpusValidationReport,
    TrancheInput,
    assemble_tranches,
    canonical_sha256,
    load_json_document,
)

MANIFEST_SCHEMA_VERSION = "decision-quality-benchmark/1.0"
ROSTER_SCHEMA_VERSION = "decision-quality-roster/1.0"
SCORER_CONTRACT_VERSION = "outcome-decision-quality-scorer/1.0"
CANONICAL_JSON_CONVENTION = "python-json-sort-keys-compact-utf8-no-nan-v1"
REQUIRED_CONDITIONS = (
    "single_claude",
    "single_openai",
    "single_gemini",
    "aragora_team",
)
EXPECTED_FAMILY_MODELS = {
    "claude": "claude-fable-5",
    "openai": "gpt-5.6-sol",
    "gemini": "gemini-3.1-pro-preview",
}
EXPECTED_TRANSPORT = "vibeproxy-required"
EXPECTED_BILLING_CLASS = "subscription"

_ROSTER_KEYS = {"schema_version", "conditions"}
_SINGLE_CONDITION_KEYS = {"mode", "max_paid_cost_usd", "members"}
_TEAM_CONDITION_KEYS = _SINGLE_CONDITION_KEYS | {
    "adversarial_rounds",
    "synthesizer_family",
}
_MEMBER_KEYS = {
    "family",
    "requested_model",
    "allowed_resolved_models",
    "transport",
    "billing_class",
}


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


def _contract_issue(report: BenchmarkContractReport, path: str, code: str, message: str) -> None:
    report.issues.append(ContractIssue(path, code, message))


def _exact_keys(
    value: dict[str, Any], expected: set[str], path: str, report: BenchmarkContractReport
) -> None:
    for key in sorted(expected - value.keys()):
        _contract_issue(report, f"{path}.{key}", "missing_field", "field is required")
    for key in sorted(value.keys() - expected):
        _contract_issue(report, f"{path}.{key}", "unknown_field", "field is not permitted")


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
    _exact_keys(roster, _ROSTER_KEYS, "$.roster", report)
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
        condition_path = f"$.roster.{condition_name}"
        expected_mode = "team" if condition_name == "aragora_team" else "single"
        expected_keys = (
            _TEAM_CONDITION_KEYS if condition_name == "aragora_team" else _SINGLE_CONDITION_KEYS
        )
        _exact_keys(condition, expected_keys, condition_path, report)
        if condition.get("mode") != expected_mode:
            _contract_issue(
                report,
                f"{condition_path}.mode",
                "mode_contract_mismatch",
                f"must equal {expected_mode!r}",
            )
        max_paid_cost = condition.get("max_paid_cost_usd")
        if (
            isinstance(max_paid_cost, bool)
            or not isinstance(max_paid_cost, (int, float))
            or float(max_paid_cost) != 0.0
        ):
            _contract_issue(
                report,
                f"{condition_path}.max_paid_cost_usd",
                "paid_cost_contract_mismatch",
                "must be numeric zero for the subscription-only frozen roster",
            )
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
            _exact_keys(member, _MEMBER_KEYS, path, report)
            family = member.get("family")
            if family in families:
                _contract_issue(report, f"{path}.family", "duplicate_family", str(family))
            elif isinstance(family, str):
                families.add(family)
            expected_model = EXPECTED_FAMILY_MODELS.get(family) if isinstance(family, str) else None
            requested_model = member.get("requested_model")
            if requested_model != expected_model:
                _contract_issue(
                    report,
                    f"{path}.requested_model",
                    "model_contract_mismatch",
                    f"must equal {expected_model!r} for family {family!r}",
                )
            resolved = member.get("allowed_resolved_models")
            if resolved != [expected_model]:
                _contract_issue(
                    report,
                    f"{path}.allowed_resolved_models",
                    "model_contract_mismatch",
                    f"must equal [{expected_model!r}] for family {family!r}",
                )
            if member.get("transport") != EXPECTED_TRANSPORT:
                _contract_issue(
                    report,
                    f"{path}.transport",
                    "transport_contract_mismatch",
                    f"must equal {EXPECTED_TRANSPORT!r}",
                )
            if member.get("billing_class") != EXPECTED_BILLING_CLASS:
                _contract_issue(
                    report,
                    f"{path}.billing_class",
                    "billing_contract_mismatch",
                    f"must equal {EXPECTED_BILLING_CLASS!r}",
                )
        expected = {condition_name.removeprefix("single_")}
        if condition_name == "aragora_team":
            expected = {"claude", "openai", "gemini"}
            adversarial_rounds = condition.get("adversarial_rounds")
            if isinstance(adversarial_rounds, bool) or adversarial_rounds != 1:
                _contract_issue(report, f"$.roster.{condition_name}", "round_contract", "one round")
            if condition.get("synthesizer_family") != "claude":
                _contract_issue(
                    report,
                    f"$.roster.{condition_name}.synthesizer_family",
                    "synthesizer_contract_mismatch",
                    "must equal 'claude'",
                )
        if families != expected:
            _contract_issue(
                report,
                f"$.roster.{condition_name}.members",
                "family_roster_mismatch",
                f"expected {sorted(expected)}",
            )


__all__ = [
    "BenchmarkBundle",
    "BenchmarkContractReport",
    "CANONICAL_JSON_CONVENTION",
    "ContractIssue",
    "EXPECTED_BILLING_CLASS",
    "EXPECTED_FAMILY_MODELS",
    "EXPECTED_TRANSPORT",
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_CONDITIONS",
    "ROSTER_SCHEMA_VERSION",
    "SCORER_CONTRACT_VERSION",
    "load_benchmark_bundle",
]
