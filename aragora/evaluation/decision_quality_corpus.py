"""Validation for the outcome-backed decision-quality benchmark corpus.

The model-visible corpus and resolved-outcome sidecar are deliberately
separate. Validation reports canonical digests for both documents so a frozen
benchmark manifest can pin the question set and answer key before inference.
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
_NON_PUBLIC_HOST_SUFFIXES = (".home", ".internal", ".lan", ".local", ".localhost")

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
_OUTCOMES_KEYS = {
    "schema_version",
    "benchmark_id",
    "corpus_sha256",
    "outcomes",
}
_OUTCOME_KEYS = {
    "case_id",
    "resolved_at",
    "correct_option_id",
    "resolution_summary",
    "authoritative_sources",
    "cruxes",
}
_CRUX_KEYS = {"crux_id", "description", "aliases"}


class _DuplicateObjectKeyError(ValueError):
    """Raised when a JSON object repeats a key."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"duplicate JSON object key: {key!r}")


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting ambiguous duplicate keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateObjectKeyError(key)
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
    """Structured result returned by corpus validation."""

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


def canonical_json_bytes(document: Any) -> bytes:
    """Return the stable JSON representation used by the corpus hash."""
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def corpus_sha256(corpus: Any) -> str:
    """Return the canonical SHA-256 digest of a model-visible corpus."""
    return hashlib.sha256(canonical_json_bytes(corpus)).hexdigest()


def outcomes_sha256(outcomes: Any) -> str:
    """Return the canonical SHA-256 digest of a resolved-outcome sidecar."""
    return hashlib.sha256(canonical_json_bytes(outcomes)).hexdigest()


def _issue(
    report: CorpusValidationReport,
    path: str,
    code: str,
    message: str,
) -> None:
    report.issues.append(ValidationIssue(path=path, code=code, message=message))


def _as_object(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _issue(report, path, "invalid_type", "must be a JSON object")
        return None
    return value


def _check_keys(
    value: dict[str, Any],
    *,
    allowed: set[str],
    path: str,
    report: CorpusValidationReport,
) -> None:
    for key in sorted(allowed - value.keys()):
        _issue(report, f"{path}.{key}", "missing_field", "field is required")
    for key in sorted(value.keys() - allowed):
        _issue(
            report,
            f"{path}.{key}",
            "unknown_field",
            "field is not permitted by the frozen corpus contract",
        )


def _nonempty_string(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        _issue(report, path, "invalid_string", "must be a non-empty string")
        return None
    return value


def _identifier(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
) -> str | None:
    text = _nonempty_string(value, path=path, report=report)
    if text is not None and _ID_PATTERN.fullmatch(text) is None:
        _issue(
            report,
            path,
            "invalid_identifier",
            "must use lowercase letters, digits, dots, underscores, or hyphens",
        )
        return None
    return text


def _timestamp(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
) -> datetime | None:
    text = _nonempty_string(value, path=path, report=report)
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


def _sha256(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
) -> str | None:
    text = _nonempty_string(value, path=path, report=report)
    if text is not None and _SHA256_PATTERN.fullmatch(text) is None:
        _issue(report, path, "invalid_sha256", "must be a lowercase 64-character SHA-256")
        return None
    return text


def _https_url(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
) -> str | None:
    text = _nonempty_string(value, path=path, report=report)
    if text is not None and not _is_public_https_url(text):
        _issue(report, path, "non_public_url", "must use an https:// public source URL")
        return None
    return text


def _is_public_https_url(text: str) -> bool:
    """Return whether a URL has a syntactically public HTTPS authority."""
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

    normalized_host = host.rstrip(".").lower()
    if not normalized_host:
        return False
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        try:
            ascii_host = normalized_host.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        if (
            "." not in ascii_host
            or ascii_host == "localhost"
            or ascii_host.endswith(_NON_PUBLIC_HOST_SUFFIXES)
        ):
            return False
        return all(_HOST_LABEL_PATTERN.fullmatch(label) for label in ascii_host.split("."))
    return address.is_global


def _validate_source(
    value: Any,
    *,
    path: str,
    report: CorpusValidationReport,
    cutoff: datetime | None = None,
) -> tuple[str | None, datetime | None]:
    source = _as_object(value, path=path, report=report)
    if source is None:
        return None, None
    _check_keys(source, allowed=_SOURCE_KEYS, path=path, report=report)
    source_id = _identifier(source.get("source_id"), path=f"{path}.source_id", report=report)
    _nonempty_string(source.get("title"), path=f"{path}.title", report=report)
    _https_url(source.get("url"), path=f"{path}.url", report=report)
    published_at = _timestamp(
        source.get("published_at"),
        path=f"{path}.published_at",
        report=report,
    )
    _sha256(source.get("content_sha256"), path=f"{path}.content_sha256", report=report)
    if cutoff is not None and published_at is not None and published_at > cutoff:
        _issue(
            report,
            f"{path}.published_at",
            "outcome_leakage",
            "model-visible evidence must not be published after the information cutoff",
        )
    return source_id, published_at


def _validate_case(
    value: Any,
    *,
    index: int,
    report: CorpusValidationReport,
) -> tuple[str | None, set[str], datetime | None, str | None, str | None]:
    path = f"$.cases[{index}]"
    case = _as_object(value, path=path, report=report)
    if case is None:
        return None, set(), None, None, None
    _check_keys(case, allowed=_CASE_KEYS, path=path, report=report)

    case_id = _identifier(case.get("case_id"), path=f"{path}.case_id", report=report)
    domain = _nonempty_string(case.get("domain"), path=f"{path}.domain", report=report)
    if domain is not None and domain not in DOMAINS:
        _issue(report, f"{path}.domain", "invalid_domain", f"must be one of {DOMAINS}")
    split = _nonempty_string(case.get("split"), path=f"{path}.split", report=report)
    if split is not None and split not in SPLITS:
        _issue(report, f"{path}.split", "invalid_split", f"must be one of {SPLITS}")
    _nonempty_string(case.get("title"), path=f"{path}.title", report=report)
    _nonempty_string(
        case.get("decision_prompt"),
        path=f"{path}.decision_prompt",
        report=report,
    )
    _nonempty_string(
        case.get("forecast_question"),
        path=f"{path}.forecast_question",
        report=report,
    )
    cutoff = _timestamp(
        case.get("information_cutoff"),
        path=f"{path}.information_cutoff",
        report=report,
    )

    option_ids: set[str] = set()
    options = case.get("options")
    if not isinstance(options, list) or len(options) != 2:
        _issue(report, f"{path}.options", "invalid_options", "must contain exactly two options")
    else:
        for option_index, raw_option in enumerate(options):
            option_path = f"{path}.options[{option_index}]"
            option = _as_object(raw_option, path=option_path, report=report)
            if option is None:
                continue
            _check_keys(option, allowed=_OPTION_KEYS, path=option_path, report=report)
            option_id = _identifier(
                option.get("option_id"),
                path=f"{option_path}.option_id",
                report=report,
            )
            _nonempty_string(option.get("label"), path=f"{option_path}.label", report=report)
            _nonempty_string(
                option.get("description"),
                path=f"{option_path}.description",
                report=report,
            )
            if option_id in option_ids:
                _issue(
                    report,
                    f"{option_path}.option_id",
                    "duplicate_option_id",
                    "option identifiers must be unique within a case",
                )
            elif option_id is not None:
                option_ids.add(option_id)

    forecast_option_id = _identifier(
        case.get("forecast_option_id"),
        path=f"{path}.forecast_option_id",
        report=report,
    )
    if forecast_option_id is not None and forecast_option_id not in option_ids:
        _issue(
            report,
            f"{path}.forecast_option_id",
            "unknown_forecast_option",
            "must reference one of the case option identifiers",
        )

    sources = case.get("sources")
    if not isinstance(sources, list) or not sources:
        _issue(report, f"{path}.sources", "missing_sources", "must contain public evidence")
    else:
        source_ids: set[str] = set()
        for source_index, source in enumerate(sources):
            source_path = f"{path}.sources[{source_index}]"
            source_id, _ = _validate_source(
                source,
                path=source_path,
                report=report,
                cutoff=cutoff,
            )
            if source_id in source_ids:
                _issue(
                    report,
                    f"{source_path}.source_id",
                    "duplicate_source_id",
                    "source identifiers must be unique within a case",
                )
            elif source_id is not None:
                source_ids.add(source_id)

    return case_id, option_ids, cutoff, domain, split


def _validate_outcome(
    value: Any,
    *,
    index: int,
    case_options: dict[str, set[str]],
    case_cutoffs: dict[str, datetime],
    report: CorpusValidationReport,
) -> tuple[str | None, datetime | None]:
    path = f"$.outcomes[{index}]"
    outcome = _as_object(value, path=path, report=report)
    if outcome is None:
        return None, None
    _check_keys(outcome, allowed=_OUTCOME_KEYS, path=path, report=report)

    case_id = _identifier(outcome.get("case_id"), path=f"{path}.case_id", report=report)
    resolved_at = _timestamp(
        outcome.get("resolved_at"),
        path=f"{path}.resolved_at",
        report=report,
    )
    correct_option_id = _identifier(
        outcome.get("correct_option_id"),
        path=f"{path}.correct_option_id",
        report=report,
    )
    _nonempty_string(
        outcome.get("resolution_summary"),
        path=f"{path}.resolution_summary",
        report=report,
    )

    if case_id is not None:
        if case_id not in case_options:
            _issue(report, f"{path}.case_id", "unknown_case", "has no matching corpus case")
        elif correct_option_id not in case_options[case_id]:
            _issue(
                report,
                f"{path}.correct_option_id",
                "unknown_correct_option",
                "must reference one of the matching case options",
            )
        cutoff = case_cutoffs.get(case_id)
        if cutoff is not None and resolved_at is not None and resolved_at <= cutoff:
            _issue(
                report,
                f"{path}.resolved_at",
                "invalid_resolution_time",
                "must be later than the model-visible information cutoff",
            )

    sources = outcome.get("authoritative_sources")
    if not isinstance(sources, list) or not sources:
        _issue(
            report,
            f"{path}.authoritative_sources",
            "missing_outcome_sources",
            "must contain authoritative outcome evidence",
        )
    else:
        source_ids: set[str] = set()
        for source_index, source in enumerate(sources):
            source_path = f"{path}.authoritative_sources[{source_index}]"
            source_id, published_at = _validate_source(
                source,
                path=source_path,
                report=report,
            )
            if source_id in source_ids:
                _issue(
                    report,
                    f"{source_path}.source_id",
                    "duplicate_source_id",
                    "source identifiers must be unique within an outcome",
                )
            elif source_id is not None:
                source_ids.add(source_id)
            if resolved_at is not None and published_at is not None and published_at < resolved_at:
                _issue(
                    report,
                    f"{source_path}.published_at",
                    "premature_outcome_source",
                    "authoritative outcome evidence must not predate resolution",
                )

    cruxes = outcome.get("cruxes")
    if not isinstance(cruxes, list) or not 3 <= len(cruxes) <= 5:
        _issue(report, f"{path}.cruxes", "invalid_crux_count", "must contain 3 to 5 cruxes")
    else:
        crux_ids: set[str] = set()
        for crux_index, raw_crux in enumerate(cruxes):
            crux_path = f"{path}.cruxes[{crux_index}]"
            crux = _as_object(raw_crux, path=crux_path, report=report)
            if crux is None:
                continue
            _check_keys(crux, allowed=_CRUX_KEYS, path=crux_path, report=report)
            crux_id = _identifier(
                crux.get("crux_id"),
                path=f"{crux_path}.crux_id",
                report=report,
            )
            _nonempty_string(
                crux.get("description"),
                path=f"{crux_path}.description",
                report=report,
            )
            aliases = crux.get("aliases")
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias.strip() for alias in aliases
            ):
                _issue(
                    report,
                    f"{crux_path}.aliases",
                    "invalid_aliases",
                    "must be a list of non-empty strings",
                )
            if crux_id in crux_ids:
                _issue(
                    report,
                    f"{crux_path}.crux_id",
                    "duplicate_crux_id",
                    "crux identifiers must be unique within an outcome",
                )
            elif crux_id is not None:
                crux_ids.add(crux_id)

    return case_id, resolved_at


def validate_corpus_documents(
    corpus: Any,
    outcomes: Any,
    *,
    allow_partial: bool = False,
    expected_outcomes_sha256: str | None = None,
) -> CorpusValidationReport:
    """Validate the model-visible corpus and hash-bound outcome sidecar."""
    report = CorpusValidationReport()
    corpus_object = _as_object(corpus, path="$", report=report)
    outcomes_object = _as_object(outcomes, path="$", report=report)
    if corpus_object is None or outcomes_object is None:
        return report

    report.corpus_sha256 = corpus_sha256(corpus_object)
    report.outcomes_sha256 = outcomes_sha256(outcomes_object)
    if expected_outcomes_sha256 is not None:
        expected_hash = _sha256(
            expected_outcomes_sha256,
            path="$expected_outcomes_sha256",
            report=report,
        )
        if expected_hash is not None and expected_hash != report.outcomes_sha256:
            _issue(
                report,
                "$expected_outcomes_sha256",
                "outcomes_hash_mismatch",
                "outcome sidecar does not match the frozen expected digest",
            )
    _check_keys(corpus_object, allowed=_CORPUS_KEYS, path="$", report=report)
    _check_keys(outcomes_object, allowed=_OUTCOMES_KEYS, path="$", report=report)

    if corpus_object.get("schema_version") != CORPUS_SCHEMA_VERSION:
        _issue(
            report,
            "$.schema_version",
            "unsupported_schema",
            f"must equal {CORPUS_SCHEMA_VERSION!r}",
        )
    if outcomes_object.get("schema_version") != OUTCOMES_SCHEMA_VERSION:
        _issue(
            report,
            "$.schema_version",
            "unsupported_outcomes_schema",
            f"must equal {OUTCOMES_SCHEMA_VERSION!r}",
        )

    benchmark_id = _identifier(
        corpus_object.get("benchmark_id"),
        path="$.benchmark_id",
        report=report,
    )
    outcomes_benchmark_id = _identifier(
        outcomes_object.get("benchmark_id"),
        path="$.benchmark_id",
        report=report,
    )
    if benchmark_id is not None and outcomes_benchmark_id != benchmark_id:
        _issue(
            report,
            "$.benchmark_id",
            "benchmark_id_mismatch",
            "outcome sidecar must name the same benchmark",
        )
    _identifier(corpus_object.get("revision"), path="$.revision", report=report)
    frozen_at = _timestamp(
        corpus_object.get("frozen_at"),
        path="$.frozen_at",
        report=report,
    )

    declared_hash = _sha256(
        outcomes_object.get("corpus_sha256"),
        path="$.corpus_sha256",
        report=report,
    )
    if declared_hash is not None and declared_hash != report.corpus_sha256:
        _issue(
            report,
            "$.corpus_sha256",
            "corpus_hash_mismatch",
            "outcome sidecar is not bound to the canonical corpus document",
        )

    cases = corpus_object.get("cases")
    if not isinstance(cases, list):
        _issue(report, "$.cases", "invalid_type", "must be a JSON array")
        cases = []
    report.case_count = len(cases)
    if report.case_count == 0:
        _issue(report, "$.cases", "empty_corpus", "must contain at least one resolved case")

    case_options: dict[str, set[str]] = {}
    case_cutoffs: dict[str, datetime] = {}
    domains: list[str] = []
    splits: list[str] = []
    domain_splits: Counter[tuple[str, str]] = Counter()
    for index, case in enumerate(cases):
        case_id, options, cutoff, domain, split = _validate_case(
            case,
            index=index,
            report=report,
        )
        if case_id in case_options:
            _issue(
                report,
                f"$.cases[{index}].case_id",
                "duplicate_case_id",
                "case identifiers must be unique",
            )
        elif case_id is not None:
            case_options[case_id] = options
            if cutoff is not None:
                case_cutoffs[case_id] = cutoff
        if domain in DOMAINS:
            domains.append(domain)
        if split in SPLITS:
            splits.append(split)
        if domain in DOMAINS and split in SPLITS:
            domain_splits[(domain, split)] += 1

    report.domain_counts = dict(sorted(Counter(domains).items()))
    report.split_counts = dict(sorted(Counter(splits).items()))
    if not allow_partial:
        if report.case_count != 24:
            _issue(report, "$.cases", "wrong_case_count", "must contain exactly 24 cases")
        for domain in DOMAINS:
            if report.domain_counts.get(domain, 0) != 6:
                _issue(
                    report,
                    "$.cases",
                    "wrong_domain_count",
                    f"domain {domain!r} must contain exactly 6 cases",
                )
            if domain_splits[(domain, "development")] != 4:
                _issue(
                    report,
                    "$.cases",
                    "wrong_development_count",
                    f"domain {domain!r} must contain exactly 4 development cases",
                )
            if domain_splits[(domain, "holdout")] != 2:
                _issue(
                    report,
                    "$.cases",
                    "wrong_holdout_count",
                    f"domain {domain!r} must contain exactly 2 holdout cases",
                )

    raw_outcomes = outcomes_object.get("outcomes")
    if not isinstance(raw_outcomes, list):
        _issue(report, "$.outcomes", "invalid_type", "must be a JSON array")
        raw_outcomes = []
    if not raw_outcomes:
        _issue(report, "$.outcomes", "empty_outcomes", "must contain at least one outcome")
    outcome_ids: set[str] = set()
    resolution_times: list[datetime] = []
    for index, outcome in enumerate(raw_outcomes):
        case_id, resolved_at = _validate_outcome(
            outcome,
            index=index,
            case_options=case_options,
            case_cutoffs=case_cutoffs,
            report=report,
        )
        if case_id in outcome_ids:
            _issue(
                report,
                f"$.outcomes[{index}].case_id",
                "duplicate_outcome",
                "each corpus case must have exactly one outcome",
            )
        elif case_id is not None:
            outcome_ids.add(case_id)
        if resolved_at is not None:
            resolution_times.append(resolved_at)

    missing_outcomes = sorted(case_options.keys() - outcome_ids)
    extra_outcomes = sorted(outcome_ids - case_options.keys())
    if missing_outcomes:
        _issue(
            report,
            "$.outcomes",
            "missing_outcomes",
            f"missing outcomes for cases: {', '.join(missing_outcomes)}",
        )
    if extra_outcomes:
        _issue(
            report,
            "$.outcomes",
            "extra_outcomes",
            f"outcomes reference unknown cases: {', '.join(extra_outcomes)}",
        )
    if frozen_at is not None and any(resolved_at > frozen_at for resolved_at in resolution_times):
        _issue(
            report,
            "$.frozen_at",
            "premature_freeze",
            "must be at or after every authoritative outcome resolution",
        )

    return report


def validate_corpus_files(
    corpus_path: Path,
    outcomes_path: Path,
    *,
    allow_partial: bool = False,
    expected_outcomes_sha256: str | None = None,
) -> CorpusValidationReport:
    """Load and validate corpus files without raising on malformed input."""
    report = CorpusValidationReport()
    documents: list[Any] = []
    for label, path in (("corpus", corpus_path), ("outcomes", outcomes_path)):
        try:
            documents.append(
                json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=_reject_duplicate_object_keys,
                )
            )
        except OSError as exc:
            _issue(report, f"${label}", "read_error", f"cannot read {path}: {exc}")
        except _DuplicateObjectKeyError as exc:
            _issue(
                report,
                f"${label}",
                "duplicate_json_key",
                f"{path}: duplicate object key {exc.key!r}",
            )
        except json.JSONDecodeError as exc:
            _issue(
                report,
                f"${label}",
                "invalid_json",
                f"{path}:{exc.lineno}:{exc.colno}: {exc.msg}",
            )
    if report.issues:
        return report
    return validate_corpus_documents(
        documents[0],
        documents[1],
        allow_partial=allow_partial,
        expected_outcomes_sha256=expected_outcomes_sha256,
    )


__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "OUTCOMES_SCHEMA_VERSION",
    "DOMAINS",
    "SPLITS",
    "ValidationIssue",
    "CorpusValidationReport",
    "canonical_json_bytes",
    "corpus_sha256",
    "outcomes_sha256",
    "validate_corpus_documents",
    "validate_corpus_files",
]
