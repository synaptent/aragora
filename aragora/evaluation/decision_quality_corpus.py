"""Frozen corpus validation for the outcome-backed decision-quality benchmark.

The model-visible corpus and resolved outcomes remain separate.  Tranche files
are immutable construction inputs; the benchmark manifest binds their canonical
digests and the aggregate corpus/outcome digests before any inference occurs.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CORPUS_SCHEMA_VERSION = "decision-quality-corpus/1.0"
OUTCOMES_SCHEMA_VERSION = "decision-quality-outcomes/1.0"
DOMAINS = (
    "software_engineering",
    "business_operations",
    "policy_compliance",
    "science_forecasting",
)
SPLITS = ("development", "holdout")

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NON_PUBLIC_SUFFIXES = (".home", ".internal", ".lan", ".local", ".localhost")

_CORPUS_KEYS = {"schema_version", "benchmark_id", "revision", "frozen_at", "cases"}
_CASE_KEYS = {
    "case_id",
    "domain",
    "split",
    "title",
    "decision_prompt",
    "forecast_question",
    "forecast_option_id",
    "options",
    "information_cutoff",
    "sources",
}
_OPTION_KEYS = {"option_id", "label", "description"}
_SOURCE_KEYS = {"source_id", "title", "url", "published_at", "content_sha256"}
_OUTCOMES_KEYS = {"schema_version", "benchmark_id", "corpus_sha256", "outcomes"}
_OUTCOME_KEYS = {
    "case_id",
    "resolved_at",
    "correct_option_id",
    "resolution_summary",
    "authoritative_sources",
    "cruxes",
}
_CRUX_KEYS = {"crux_id", "description", "aliases"}


class DuplicateObjectKeyError(ValueError):
    """Raised when a JSON object repeats a key."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"duplicate JSON object key: {key!r}")


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateObjectKeyError(key)
        result[key] = value
    return result


@dataclass(frozen=True)
class ValidationIssue:
    """One fail-closed corpus validation issue."""

    path: str
    code: str
    message: str


@dataclass
class CorpusValidationReport:
    """Structured corpus validation result."""

    corpus_sha256: str | None = None
    outcomes_sha256: str | None = None
    case_count: int = 0
    domain_counts: dict[str, int] = field(default_factory=dict)
    split_counts: dict[str, int] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "corpus_sha256": self.corpus_sha256,
            "outcomes_sha256": self.outcomes_sha256,
            "case_count": self.case_count,
            "domain_counts": self.domain_counts,
            "split_counts": self.split_counts,
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass(frozen=True)
class TrancheInput:
    """One manifest-pinned corpus/outcome tranche pair."""

    corpus_path: Path
    outcomes_path: Path
    corpus_sha256: str
    outcomes_sha256: str


def canonical_json_bytes(document: Any) -> bytes:
    """Return the benchmark's documented Python canonical JSON encoding."""
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(document: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def _issue(report: CorpusValidationReport, path: str, code: str, message: str) -> None:
    report.issues.append(ValidationIssue(path, code, message))


def load_json_document(path: Path) -> tuple[Any | None, ValidationIssue | None]:
    """Load JSON with duplicate-key and encoding failures returned as data."""
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw, object_pairs_hook=_reject_duplicate_object_keys), None
    except OSError as exc:
        return None, ValidationIssue(str(path), "read_error", str(exc))
    except UnicodeError as exc:
        return None, ValidationIssue(str(path), "invalid_utf8", str(exc))
    except DuplicateObjectKeyError as exc:
        return None, ValidationIssue(str(path), "duplicate_json_key", str(exc))
    except json.JSONDecodeError as exc:
        return None, ValidationIssue(
            str(path),
            "invalid_json",
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )


def _object(value: Any, path: str, report: CorpusValidationReport) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _issue(report, path, "invalid_type", "must be a JSON object")
        return None
    return value


def _keys(
    value: dict[str, Any], allowed: set[str], path: str, report: CorpusValidationReport
) -> None:
    for key in sorted(allowed - value.keys()):
        _issue(report, f"{path}.{key}", "missing_field", "field is required")
    for key in sorted(value.keys() - allowed):
        _issue(report, f"{path}.{key}", "unknown_field", "field is not permitted")


def _text(value: Any, path: str, report: CorpusValidationReport) -> str | None:
    if not isinstance(value, str) or not value.strip():
        _issue(report, path, "invalid_string", "must be a non-empty string")
        return None
    return value


def _identifier(value: Any, path: str, report: CorpusValidationReport) -> str | None:
    text = _text(value, path, report)
    if text is not None and _ID_PATTERN.fullmatch(text) is None:
        _issue(report, path, "invalid_identifier", "must be a lowercase benchmark identifier")
        return None
    return text


def _timestamp(value: Any, path: str, report: CorpusValidationReport) -> datetime | None:
    text = _text(value, path, report)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _issue(report, path, "invalid_timestamp", "must be an ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _issue(report, path, "naive_timestamp", "must include a UTC offset")
        return None
    return parsed


def _sha256(value: Any, path: str, report: CorpusValidationReport) -> str | None:
    text = _text(value, path, report)
    if text is not None and _SHA256_PATTERN.fullmatch(text) is None:
        _issue(report, path, "invalid_sha256", "must be a lowercase 64-character SHA-256")
        return None
    return text


def _public_https(value: Any, path: str, report: CorpusValidationReport) -> str | None:
    text = _text(value, path, report)
    if text is not None and not is_public_https_url(text):
        _issue(report, path, "non_public_url", "must use a syntactically public HTTPS URL")
        return None
    return text


def is_public_https_url(text: str) -> bool:
    """Fail closed for local, credential-bearing, or malformed source URLs."""
    try:
        parsed = urlsplit(text)
        host = parsed.hostname
        parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    normalized = host.rstrip(".").lower()
    if not normalized:
        return False
    try:
        return ipaddress.ip_address(normalized).is_global
    except ValueError:
        try:
            ascii_host = normalized.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        if "." not in ascii_host or ascii_host.endswith(_NON_PUBLIC_SUFFIXES):
            return False
        return all(_HOST_LABEL_PATTERN.fullmatch(label) for label in ascii_host.split("."))


def _source(
    value: Any,
    path: str,
    report: CorpusValidationReport,
    *,
    cutoff: datetime | None = None,
    not_before: datetime | None = None,
) -> str | None:
    source = _object(value, path, report)
    if source is None:
        return None
    _keys(source, _SOURCE_KEYS, path, report)
    source_id = _identifier(source.get("source_id"), f"{path}.source_id", report)
    _text(source.get("title"), f"{path}.title", report)
    _public_https(source.get("url"), f"{path}.url", report)
    published_at = _timestamp(source.get("published_at"), f"{path}.published_at", report)
    _sha256(source.get("content_sha256"), f"{path}.content_sha256", report)
    if cutoff is not None and published_at is not None and published_at > cutoff:
        _issue(
            report,
            f"{path}.published_at",
            "outcome_leakage",
            "model-visible evidence must not postdate the information cutoff",
        )
    if not_before is not None and published_at is not None and published_at < not_before:
        _issue(
            report,
            f"{path}.published_at",
            "premature_outcome_source",
            "authoritative outcome evidence must not predate resolution",
        )
    return source_id


def _case(
    value: Any, index: int, report: CorpusValidationReport
) -> tuple[str | None, set[str], datetime | None, str | None, str | None, str | None]:
    path = f"$.cases[{index}]"
    case = _object(value, path, report)
    if case is None:
        return None, set(), None, None, None, None
    _keys(case, _CASE_KEYS, path, report)
    case_id = _identifier(case.get("case_id"), f"{path}.case_id", report)
    domain = _text(case.get("domain"), f"{path}.domain", report)
    split = _text(case.get("split"), f"{path}.split", report)
    if domain is not None and domain not in DOMAINS:
        _issue(report, f"{path}.domain", "invalid_domain", f"must be one of {DOMAINS}")
    if split is not None and split not in SPLITS:
        _issue(report, f"{path}.split", "invalid_split", f"must be one of {SPLITS}")
    for key in ("title", "decision_prompt", "forecast_question"):
        _text(case.get(key), f"{path}.{key}", report)
    cutoff = _timestamp(case.get("information_cutoff"), f"{path}.information_cutoff", report)

    option_ids: set[str] = set()
    option_id_order: list[str] = []
    options = case.get("options")
    if not isinstance(options, list) or len(options) != 2:
        _issue(report, f"{path}.options", "invalid_options", "must contain exactly two options")
    else:
        for option_index, raw in enumerate(options):
            option_path = f"{path}.options[{option_index}]"
            option = _object(raw, option_path, report)
            if option is None:
                continue
            _keys(option, _OPTION_KEYS, option_path, report)
            option_id = _identifier(option.get("option_id"), f"{option_path}.option_id", report)
            _text(option.get("label"), f"{option_path}.label", report)
            _text(option.get("description"), f"{option_path}.description", report)
            if option_id in option_ids:
                _issue(report, f"{option_path}.option_id", "duplicate_option_id", "must be unique")
            elif option_id is not None:
                option_ids.add(option_id)
                option_id_order.append(option_id)
        if len(option_id_order) == 2 and option_id_order != sorted(option_id_order):
            _issue(
                report,
                f"{path}.options",
                "unsorted_options",
                "option IDs must be in lexicographic order to prevent position leakage",
            )
    forecast_option = _identifier(
        case.get("forecast_option_id"), f"{path}.forecast_option_id", report
    )
    if forecast_option is not None and forecast_option not in option_ids:
        _issue(report, f"{path}.forecast_option_id", "unknown_forecast_option", "unknown option")

    sources = case.get("sources")
    if not isinstance(sources, list) or not sources:
        _issue(report, f"{path}.sources", "missing_sources", "must contain public evidence")
    else:
        source_ids: set[str] = set()
        for source_index, raw in enumerate(sources):
            source_path = f"{path}.sources[{source_index}]"
            source_id = _source(raw, source_path, report, cutoff=cutoff)
            if source_id in source_ids:
                _issue(report, f"{source_path}.source_id", "duplicate_source_id", "must be unique")
            elif source_id is not None:
                source_ids.add(source_id)
    return case_id, option_ids, cutoff, domain, split, forecast_option


def _outcome(
    value: Any,
    index: int,
    case_options: dict[str, set[str]],
    case_cutoffs: dict[str, datetime],
    report: CorpusValidationReport,
) -> tuple[str | None, datetime | None, str | None]:
    path = f"$.outcomes[{index}]"
    outcome = _object(value, path, report)
    if outcome is None:
        return None, None, None
    _keys(outcome, _OUTCOME_KEYS, path, report)
    case_id = _identifier(outcome.get("case_id"), f"{path}.case_id", report)
    resolved_at = _timestamp(outcome.get("resolved_at"), f"{path}.resolved_at", report)
    correct_option = _identifier(
        outcome.get("correct_option_id"), f"{path}.correct_option_id", report
    )
    _text(outcome.get("resolution_summary"), f"{path}.resolution_summary", report)
    if case_id is not None:
        if case_id not in case_options:
            _issue(report, f"{path}.case_id", "unknown_case", "has no matching corpus case")
        elif correct_option not in case_options[case_id]:
            _issue(report, f"{path}.correct_option_id", "unknown_correct_option", "unknown option")
        cutoff = case_cutoffs.get(case_id)
        if cutoff is not None and resolved_at is not None and resolved_at <= cutoff:
            _issue(
                report,
                f"{path}.resolved_at",
                "invalid_resolution_time",
                "must be later than the information cutoff",
            )

    sources = outcome.get("authoritative_sources")
    if not isinstance(sources, list) or not sources:
        _issue(report, f"{path}.authoritative_sources", "missing_outcome_sources", "required")
    else:
        source_ids: set[str] = set()
        for source_index, raw in enumerate(sources):
            source_path = f"{path}.authoritative_sources[{source_index}]"
            source_id = _source(raw, source_path, report, not_before=resolved_at)
            if source_id in source_ids:
                _issue(report, f"{source_path}.source_id", "duplicate_source_id", "must be unique")
            elif source_id is not None:
                source_ids.add(source_id)

    cruxes = outcome.get("cruxes")
    if not isinstance(cruxes, list) or not 3 <= len(cruxes) <= 5:
        _issue(report, f"{path}.cruxes", "invalid_crux_count", "must contain 3 to 5 cruxes")
    else:
        crux_ids: set[str] = set()
        for crux_index, raw in enumerate(cruxes):
            crux_path = f"{path}.cruxes[{crux_index}]"
            crux = _object(raw, crux_path, report)
            if crux is None:
                continue
            _keys(crux, _CRUX_KEYS, crux_path, report)
            crux_id = _identifier(crux.get("crux_id"), f"{crux_path}.crux_id", report)
            _text(crux.get("description"), f"{crux_path}.description", report)
            aliases = crux.get("aliases")
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias.strip() for alias in aliases
            ):
                _issue(report, f"{crux_path}.aliases", "invalid_aliases", "must be strings")
            if crux_id in crux_ids:
                _issue(report, f"{crux_path}.crux_id", "duplicate_crux_id", "must be unique")
            elif crux_id is not None:
                crux_ids.add(crux_id)
    return case_id, resolved_at, correct_option


def validate_corpus_documents(
    corpus: Any,
    outcomes: Any,
    *,
    allow_partial: bool = False,
    expected_outcomes_sha256: str | None = None,
) -> CorpusValidationReport:
    """Validate model-visible cases and their hash-bound outcome sidecar."""
    report = CorpusValidationReport()
    corpus_object = _object(corpus, "$corpus", report)
    outcomes_object = _object(outcomes, "$outcomes", report)
    if corpus_object is None or outcomes_object is None:
        return report
    try:
        report.corpus_sha256 = canonical_sha256(corpus_object)
        report.outcomes_sha256 = canonical_sha256(outcomes_object)
    except (TypeError, ValueError) as exc:
        _issue(report, "$", "non_canonical_json", str(exc))
        return report
    _keys(corpus_object, _CORPUS_KEYS, "$corpus", report)
    _keys(outcomes_object, _OUTCOMES_KEYS, "$outcomes", report)
    if corpus_object.get("schema_version") != CORPUS_SCHEMA_VERSION:
        _issue(report, "$corpus.schema_version", "unsupported_schema", CORPUS_SCHEMA_VERSION)
    if outcomes_object.get("schema_version") != OUTCOMES_SCHEMA_VERSION:
        _issue(
            report,
            "$outcomes.schema_version",
            "unsupported_schema",
            OUTCOMES_SCHEMA_VERSION,
        )
    benchmark_id = _identifier(corpus_object.get("benchmark_id"), "$corpus.benchmark_id", report)
    outcome_benchmark = _identifier(
        outcomes_object.get("benchmark_id"), "$outcomes.benchmark_id", report
    )
    if benchmark_id is not None and outcome_benchmark != benchmark_id:
        _issue(report, "$outcomes.benchmark_id", "benchmark_id_mismatch", "must match corpus")
    _identifier(corpus_object.get("revision"), "$corpus.revision", report)
    frozen_at = _timestamp(corpus_object.get("frozen_at"), "$corpus.frozen_at", report)
    declared_corpus_hash = _sha256(
        outcomes_object.get("corpus_sha256"), "$outcomes.corpus_sha256", report
    )
    if declared_corpus_hash is not None and declared_corpus_hash != report.corpus_sha256:
        _issue(report, "$outcomes.corpus_sha256", "corpus_hash_mismatch", "must bind corpus")
    if expected_outcomes_sha256 is not None:
        if _SHA256_PATTERN.fullmatch(expected_outcomes_sha256) is None:
            _issue(report, "$expected_outcomes_sha256", "invalid_sha256", "invalid digest")
        elif expected_outcomes_sha256 != report.outcomes_sha256:
            _issue(report, "$expected_outcomes_sha256", "outcomes_hash_mismatch", "digest drift")

    cases = corpus_object.get("cases")
    if not isinstance(cases, list):
        _issue(report, "$corpus.cases", "invalid_type", "must be an array")
        cases = []
    report.case_count = len(cases)
    if not cases:
        _issue(report, "$corpus.cases", "empty_corpus", "must contain cases")
    case_options: dict[str, set[str]] = {}
    case_cutoffs: dict[str, datetime] = {}
    case_domains: dict[str, str] = {}
    case_splits: dict[str, str] = {}
    case_forecast_options: dict[str, str] = {}
    domains: list[str] = []
    splits: list[str] = []
    domain_splits: Counter[tuple[str, str]] = Counter()
    for index, raw in enumerate(cases):
        case_id, options, cutoff, domain, split, forecast_option = _case(raw, index, report)
        if case_id in case_options:
            _issue(report, f"$corpus.cases[{index}].case_id", "duplicate_case_id", "must be unique")
        elif case_id is not None:
            case_options[case_id] = options
            if cutoff is not None:
                case_cutoffs[case_id] = cutoff
            if domain in DOMAINS:
                case_domains[case_id] = domain
            if split in SPLITS:
                case_splits[case_id] = split
            if forecast_option is not None:
                case_forecast_options[case_id] = forecast_option
        if domain in DOMAINS:
            domains.append(domain)
        if split in SPLITS:
            splits.append(split)
        if domain in DOMAINS and split in SPLITS:
            domain_splits[(domain, split)] += 1
    report.domain_counts = dict(sorted(Counter(domains).items()))
    report.split_counts = dict(sorted(Counter(splits).items()))
    if not allow_partial:
        if len(cases) != 24:
            _issue(report, "$corpus.cases", "wrong_case_count", "must contain exactly 24 cases")
        for domain in DOMAINS:
            if report.domain_counts.get(domain, 0) != 6:
                _issue(report, "$corpus.cases", "wrong_domain_count", f"{domain} must have 6")
            if domain_splits[(domain, "development")] != 4:
                _issue(report, "$corpus.cases", "wrong_development_count", f"{domain} must have 4")
            if domain_splits[(domain, "holdout")] != 2:
                _issue(report, "$corpus.cases", "wrong_holdout_count", f"{domain} must have 2")

    raw_outcomes = outcomes_object.get("outcomes")
    if not isinstance(raw_outcomes, list):
        _issue(report, "$outcomes.outcomes", "invalid_type", "must be an array")
        raw_outcomes = []
    if not raw_outcomes:
        _issue(report, "$outcomes.outcomes", "empty_outcomes", "must contain outcomes")
    outcome_ids: set[str] = set()
    positive_targets: list[str] = []
    for index, raw in enumerate(raw_outcomes):
        case_id, resolved_at, correct_option = _outcome(
            raw, index, case_options, case_cutoffs, report
        )
        if case_id in outcome_ids:
            _issue(
                report,
                f"$outcomes.outcomes[{index}].case_id",
                "duplicate_outcome",
                "must be unique",
            )
        elif case_id is not None:
            outcome_ids.add(case_id)
            if correct_option == case_forecast_options.get(case_id):
                positive_targets.append(case_id)
        if frozen_at is not None and resolved_at is not None and frozen_at < resolved_at:
            _issue(
                report,
                f"$outcomes.outcomes[{index}].resolved_at",
                "premature_freeze",
                "corpus freeze must not predate any resolved outcome",
            )
    missing = sorted(case_options.keys() - outcome_ids)
    extra = sorted(outcome_ids - case_options.keys())
    if missing:
        _issue(report, "$outcomes.outcomes", "missing_outcomes", ", ".join(missing))
    if extra:
        _issue(report, "$outcomes.outcomes", "extra_outcomes", ", ".join(extra))
    if not allow_partial:
        if len(positive_targets) != 12:
            _issue(
                report,
                "$outcomes.outcomes",
                "wrong_target_balance",
                "exactly 12 of 24 outcomes must match the forecast option",
            )
        target_domain_splits = Counter(
            (case_domains.get(case_id), case_splits.get(case_id)) for case_id in positive_targets
        )
        for domain in DOMAINS:
            if sum(target_domain_splits[(domain, split)] for split in SPLITS) != 3:
                _issue(
                    report,
                    "$outcomes.outcomes",
                    "wrong_domain_target_balance",
                    f"{domain} must contain exactly 3 positive targets",
                )
            if target_domain_splits[(domain, "development")] != 2:
                _issue(
                    report,
                    "$outcomes.outcomes",
                    "wrong_development_target_balance",
                    f"{domain} development must contain exactly 2 positive targets",
                )
            if target_domain_splits[(domain, "holdout")] != 1:
                _issue(
                    report,
                    "$outcomes.outcomes",
                    "wrong_holdout_target_balance",
                    f"{domain} holdout must contain exactly 1 positive target",
                )
    return report


def validate_corpus_files(
    corpus_path: Path,
    outcomes_path: Path,
    *,
    allow_partial: bool = False,
    expected_outcomes_sha256: str | None = None,
) -> CorpusValidationReport:
    """Load and validate two files without raising on malformed input."""
    corpus, corpus_issue = load_json_document(corpus_path)
    outcomes, outcomes_issue = load_json_document(outcomes_path)
    if corpus_issue is not None or outcomes_issue is not None:
        return CorpusValidationReport(
            issues=[issue for issue in (corpus_issue, outcomes_issue) if issue is not None]
        )
    return validate_corpus_documents(
        corpus,
        outcomes,
        allow_partial=allow_partial,
        expected_outcomes_sha256=expected_outcomes_sha256,
    )


def assemble_tranches(
    inputs: list[TrancheInput],
    *,
    benchmark_id: str,
    revision: str,
    frozen_at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, CorpusValidationReport]:
    """Assemble manifest-pinned tranche inputs into one canonical benchmark."""
    report = CorpusValidationReport()
    cases: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for index, item in enumerate(inputs):
        corpus_doc, corpus_issue = load_json_document(item.corpus_path)
        outcomes_doc, outcomes_issue = load_json_document(item.outcomes_path)
        for issue in (corpus_issue, outcomes_issue):
            if issue is not None:
                report.issues.append(issue)
        if corpus_doc is None or outcomes_doc is None:
            continue
        try:
            actual_corpus = canonical_sha256(corpus_doc)
            actual_outcomes = canonical_sha256(outcomes_doc)
        except (TypeError, ValueError) as exc:
            _issue(report, f"$tranches[{index}]", "non_canonical_json", str(exc))
            continue
        if actual_corpus != item.corpus_sha256:
            _issue(report, f"$tranches[{index}].corpus", "tranche_hash_mismatch", actual_corpus)
        if actual_outcomes != item.outcomes_sha256:
            _issue(report, f"$tranches[{index}].outcomes", "tranche_hash_mismatch", actual_outcomes)
        partial = validate_corpus_documents(corpus_doc, outcomes_doc, allow_partial=True)
        report.issues.extend(partial.issues)
        if partial.ok:
            cases.extend(corpus_doc["cases"])
            outcomes.extend(outcomes_doc["outcomes"])
    if report.issues:
        return None, None, report
    corpus = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "revision": revision,
        "frozen_at": frozen_at,
        "cases": sorted(cases, key=lambda item: item["case_id"]),
    }
    outcome_sidecar = {
        "schema_version": OUTCOMES_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "corpus_sha256": canonical_sha256(corpus),
        "outcomes": sorted(outcomes, key=lambda item: item["case_id"]),
    }
    return corpus, outcome_sidecar, validate_corpus_documents(corpus, outcome_sidecar)


__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "OUTCOMES_SCHEMA_VERSION",
    "DOMAINS",
    "SPLITS",
    "CorpusValidationReport",
    "TrancheInput",
    "ValidationIssue",
    "assemble_tranches",
    "canonical_json_bytes",
    "canonical_sha256",
    "is_public_https_url",
    "load_json_document",
    "validate_corpus_documents",
    "validate_corpus_files",
]
