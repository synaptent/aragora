"""Fail-closed validation for the outcome-backed decision-quality corpus."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlparse


BENCHMARK_ID = "outcome-backed-decision-quality-v1"
CORPUS_SCHEMA = "decision-quality-corpus/1.0"
OUTCOME_SCHEMA = "decision-quality-outcomes/1.0"
DOMAINS = (
    "business_operations",
    "policy_compliance",
    "science_forecasting",
    "software_engineering",
)
SPLIT_COUNTS = {"development": 16, "holdout": 8}
DOMAIN_SPLIT_COUNTS = {"development": 4, "holdout": 2}
ALIGNMENT_COUNTS = {"development": 2, "holdout": 1}
EXPECTED_CASES = 24
EXPECTED_PAIRS = 8

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OUTCOME_ONLY_KEYS = frozenset(
    {"authoritative_sources", "correct_option_id", "cruxes", "resolution_summary", "resolved_at"}
)
_CORPUS_KEYS = frozenset({"schema_version", "benchmark_id", "revision", "frozen_at", "cases"})
_CASE_KEYS = frozenset(
    {
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
)
_OPTION_KEYS = frozenset({"option_id", "label", "description"})
_SOURCE_KEYS = frozenset({"source_id", "title", "url", "published_at", "content_sha256"})
_SIDECAR_KEYS = frozenset({"schema_version", "benchmark_id", "corpus_sha256", "outcomes"})
_OUTCOME_KEYS = frozenset(
    {
        "case_id",
        "resolved_at",
        "correct_option_id",
        "resolution_summary",
        "authoritative_sources",
        "cruxes",
    }
)
_CRUX_KEYS = frozenset({"crux_id", "description", "aliases"})


class _DuplicateKeyError(ValueError):
    pass


class VisibleCorpusError(ValueError):
    """Raised when the model-visible corpus cannot be loaded safely."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        detail = "; ".join(f"{issue.code}: {issue.path}: {issue.message}" for issue in issues[:5])
        if len(issues) > 5:
            detail += f"; ... and {len(issues) - 5} more"
        super().__init__(detail)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class CorpusIntegrityReport:
    benchmark_id: str | None
    corpus_files: int
    outcome_files: int
    case_count: int
    split_counts: Mapping[str, int]
    domain_counts: Mapping[str, int]
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "benchmark_id": self.benchmark_id,
            "corpus_files": self.corpus_files,
            "outcome_files": self.outcome_files,
            "case_count": self.case_count,
            "split_counts": dict(sorted(self.split_counts.items())),
            "domain_counts": dict(sorted(self.domain_counts.items())),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def canonical_json_sha256(value: Any) -> str:
    """Hash the canonical JSON representation used by the corpus sidecars."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _add(issues: list[ValidationIssue], code: str, path: str, message: str) -> None:
    issues.append(ValidationIssue(code, path, message))


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _load(path: Path, issues: list[ValidationIssue]) -> Mapping[str, Any] | None:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _add(issues, "invalid_json", str(path), str(exc))
        return None
    if not isinstance(value, dict):
        _add(issues, "invalid_type", str(path), "top-level JSON value must be an object")
        return None
    return value


def _keys(
    value: Mapping[str, Any], expected: frozenset[str], path: str, issues: list[ValidationIssue]
) -> None:
    actual = set(value)
    if missing := sorted(expected - actual):
        _add(issues, "missing_keys", path, f"missing required keys: {', '.join(missing)}")
    if unexpected := sorted(actual - expected):
        _add(issues, "unexpected_keys", path, f"unexpected keys: {', '.join(unexpected)}")


def _text(value: Any, path: str, issues: list[ValidationIssue]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        _add(issues, "invalid_string", path, "must be a non-empty string")
        return None
    return value


def _time(value: Any, path: str, issues: list[ValidationIssue]) -> datetime | None:
    text = _text(value, path, issues)
    if text is None:
        return None
    if not text.endswith("Z"):
        _add(issues, "non_utc_timestamp", path, "timestamp must end in Z")
        return None
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        _add(issues, "invalid_timestamp", path, f"invalid ISO-8601 timestamp: {text}")
        return None


def _list(value: Any, path: str, code: str, issues: list[ValidationIssue]) -> list[Any]:
    if not isinstance(value, list) or not value:
        _add(issues, code, path, "must be a non-empty list")
        return []
    return value


def _leakage(value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _OUTCOME_ONLY_KEYS:
                _add(issues, "outcome_leakage", child_path, "outcome-only field in visible corpus")
            _leakage(child, child_path, issues)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _leakage(child, f"{path}[{index}]", issues)


def _source(
    value: Any, path: str, issues: list[ValidationIssue]
) -> tuple[str | None, datetime | None]:
    if not isinstance(value, dict):
        _add(issues, "invalid_type", path, "source must be an object")
        return None, None
    _keys(value, _SOURCE_KEYS, path, issues)
    source_id = _text(value.get("source_id"), f"{path}.source_id", issues)
    _text(value.get("title"), f"{path}.title", issues)
    url = _text(value.get("url"), f"{path}.url", issues)
    if url is not None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            _add(issues, "invalid_source_url", f"{path}.url", "must be credential-free HTTPS")
    published_at = _time(value.get("published_at"), f"{path}.published_at", issues)
    content_hash = value.get("content_sha256")
    if not isinstance(content_hash, str) or not _SHA256_RE.fullmatch(content_hash):
        _add(issues, "invalid_source_hash", f"{path}.content_sha256", "must be lowercase SHA-256")
    return source_id, published_at


def _options(value: Any, path: str, issues: list[ValidationIssue]) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != 2:
        _add(issues, "invalid_options", path, "must contain exactly two options")
        return ()
    ids: list[str] = []
    for index, option in enumerate(value):
        option_path = f"{path}[{index}]"
        if not isinstance(option, dict):
            _add(issues, "invalid_type", option_path, "option must be an object")
            continue
        _keys(option, _OPTION_KEYS, option_path, issues)
        option_id = _text(option.get("option_id"), f"{option_path}.option_id", issues)
        for field in ("label", "description"):
            _text(option.get(field), f"{option_path}.{field}", issues)
        if option_id is not None:
            ids.append(option_id)
    if len(set(ids)) != len(ids):
        _add(issues, "duplicate_option_id", path, "option IDs must be unique")
    if ids != sorted(ids):
        _add(issues, "option_order", path, "options must be sorted by option_id")
    return tuple(ids)


def _cruxes(value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(value, list) or not 3 <= len(value) <= 5:
        _add(issues, "invalid_crux_count", path, "must contain 3 to 5 cruxes")
        return
    ids: list[str] = []
    for index, crux in enumerate(value):
        crux_path = f"{path}[{index}]"
        if not isinstance(crux, dict):
            _add(issues, "invalid_type", crux_path, "crux must be an object")
            continue
        _keys(crux, _CRUX_KEYS, crux_path, issues)
        crux_id = _text(crux.get("crux_id"), f"{crux_path}.crux_id", issues)
        _text(crux.get("description"), f"{crux_path}.description", issues)
        aliases = _list(crux.get("aliases"), f"{crux_path}.aliases", "invalid_aliases", issues)
        for alias_index, alias in enumerate(aliases):
            _text(alias, f"{crux_path}.aliases[{alias_index}]", issues)
        if crux_id is not None:
            ids.append(crux_id)
    if len(set(ids)) != len(ids):
        _add(issues, "duplicate_crux_id", path, "crux IDs must be unique")


def _case(
    value: Any, path: str, issues: list[ValidationIssue]
) -> tuple[str | None, str | None, str | None, datetime | None, tuple[str, ...]]:
    if not isinstance(value, dict):
        _add(issues, "invalid_type", path, "case must be an object")
        return None, None, None, None, ()
    _keys(value, _CASE_KEYS, path, issues)
    case_id = _text(value.get("case_id"), f"{path}.case_id", issues)
    domain = _text(value.get("domain"), f"{path}.domain", issues)
    split = _text(value.get("split"), f"{path}.split", issues)
    for field in ("title", "decision_prompt", "forecast_question"):
        _text(value.get(field), f"{path}.{field}", issues)
    forecast_option = _text(value.get("forecast_option_id"), f"{path}.forecast_option_id", issues)
    cutoff = _time(value.get("information_cutoff"), f"{path}.information_cutoff", issues)
    option_ids = _options(value.get("options"), f"{path}.options", issues)
    if forecast_option is not None and forecast_option not in option_ids:
        _add(issues, "unknown_forecast_option", f"{path}.forecast_option_id", "not a case option")
    sources = _list(value.get("sources"), f"{path}.sources", "invalid_sources", issues)
    source_ids: list[str] = []
    for index, item in enumerate(sources):
        source_id, published = _source(item, f"{path}.sources[{index}]", issues)
        if source_id is not None:
            source_ids.append(source_id)
        if cutoff is not None and published is not None and published > cutoff:
            _add(issues, "post_cutoff_source", f"{path}.sources[{index}]", "published after cutoff")
    if len(set(source_ids)) != len(source_ids):
        _add(issues, "duplicate_source_id", f"{path}.sources", "source IDs must be unique")
    if domain is not None and domain not in DOMAINS:
        _add(issues, "unknown_domain", f"{path}.domain", domain)
    if split is not None and split not in SPLIT_COUNTS:
        _add(issues, "unknown_split", f"{path}.split", split)
    return case_id, domain, split, cutoff, option_ids


def _outcome(
    value: Any, path: str, issues: list[ValidationIssue]
) -> tuple[str | None, datetime | None, str | None]:
    if not isinstance(value, dict):
        _add(issues, "invalid_type", path, "outcome must be an object")
        return None, None, None
    _keys(value, _OUTCOME_KEYS, path, issues)
    case_id = _text(value.get("case_id"), f"{path}.case_id", issues)
    resolved_at = _time(value.get("resolved_at"), f"{path}.resolved_at", issues)
    correct = _text(value.get("correct_option_id"), f"{path}.correct_option_id", issues)
    _text(value.get("resolution_summary"), f"{path}.resolution_summary", issues)
    sources = _list(
        value.get("authoritative_sources"),
        f"{path}.authoritative_sources",
        "invalid_authoritative_sources",
        issues,
    )
    source_ids: list[str] = []
    for index, item in enumerate(sources):
        source_path = f"{path}.authoritative_sources[{index}]"
        source_id, published = _source(item, source_path, issues)
        if source_id is not None:
            source_ids.append(source_id)
        if resolved_at is not None and published is not None and published < resolved_at:
            _add(issues, "pre_resolution_outcome_source", source_path, "predates resolved_at")
    if len(set(source_ids)) != len(source_ids):
        _add(issues, "duplicate_source_id", f"{path}.authoritative_sources", "duplicate IDs")
    _cruxes(value.get("cruxes"), f"{path}.cruxes", issues)
    return case_id, resolved_at, correct


def _count(issues: list[ValidationIssue], code: str, path: str, actual: int, expected: int) -> None:
    if actual != expected:
        _add(issues, code, path, f"expected {expected}, found {actual}")


def load_visible_cases(directory: Path | str) -> tuple[Mapping[str, Any], ...]:
    """Load and validate only model-visible corpus files.

    This intentionally never opens ``*.outcomes.json``.  Callers that build
    inference packets can therefore prove that outcome sidecars were not part
    of the packet-construction path.
    """

    root = Path(directory)
    issues: list[ValidationIssue] = []
    corpus_paths = sorted(root.glob("*.corpus.json"))
    _count(issues, "corpus_file_count", str(root), len(corpus_paths), EXPECTED_PAIRS)

    benchmark_ids: set[str] = set()
    frozen_times: set[str] = set()
    cases: dict[str, Mapping[str, Any]] = {}
    split_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    domain_splits: Counter[tuple[str, str]] = Counter()

    for corpus_path in corpus_paths:
        corpus = _load(corpus_path, issues)
        if corpus is None:
            continue
        corpus_name = str(corpus_path)
        _keys(corpus, _CORPUS_KEYS, corpus_name, issues)
        _leakage(corpus, corpus_name, issues)
        if corpus.get("schema_version") != CORPUS_SCHEMA:
            _add(issues, "schema_version", f"{corpus_name}.schema_version", CORPUS_SCHEMA)
        benchmark = _text(corpus.get("benchmark_id"), f"{corpus_name}.benchmark_id", issues)
        if benchmark is not None:
            benchmark_ids.add(benchmark)
        _text(corpus.get("revision"), f"{corpus_name}.revision", issues)
        frozen = corpus.get("frozen_at")
        if _time(frozen, f"{corpus_name}.frozen_at", issues) is not None:
            frozen_times.add(str(frozen))
        corpus_cases = _list(corpus.get("cases"), f"{corpus_name}.cases", "invalid_cases", issues)
        for index, value in enumerate(corpus_cases):
            case_path = f"{corpus_name}.cases[{index}]"
            case_id, domain, split, _, _ = _case(value, case_path, issues)
            if case_id is not None:
                if case_id in cases:
                    _add(issues, "duplicate_case_id", f"{case_path}.case_id", case_id)
                elif isinstance(value, dict):
                    cases[case_id] = value
            if domain is not None:
                domain_counts[domain] += 1
            if split is not None:
                split_counts[split] += 1
            if domain is not None and split is not None:
                domain_splits[(domain, split)] += 1

    if benchmark_ids != {BENCHMARK_ID}:
        _add(issues, "benchmark_id_set", str(root), f"found {sorted(benchmark_ids)}")
    if len(frozen_times) != 1:
        _add(issues, "freeze_timestamp_set", str(root), f"found {sorted(frozen_times)}")
    _count(issues, "case_count", str(root), len(cases), EXPECTED_CASES)
    for split, expected in SPLIT_COUNTS.items():
        _count(issues, "split_count", f"{root}:{split}", split_counts[split], expected)
    for domain in DOMAINS:
        _count(issues, "domain_count", f"{root}:{domain}", domain_counts[domain], 6)
        for split, expected in DOMAIN_SPLIT_COUNTS.items():
            _count(
                issues,
                "domain_split_count",
                f"{root}:{domain}:{split}",
                domain_splits[(domain, split)],
                expected,
            )

    if issues:
        raise VisibleCorpusError(tuple(issues))
    return tuple(cases[case_id] for case_id in sorted(cases))


def validate_corpus_directory(directory: Path | str) -> CorpusIntegrityReport:
    """Validate all paired corpus and outcome JSON documents in ``directory``."""

    root = Path(directory)
    issues: list[ValidationIssue] = []
    corpus_paths = sorted(root.glob("*.corpus.json"))
    outcome_paths = sorted(root.glob("*.outcomes.json"))
    _count(issues, "corpus_file_count", str(root), len(corpus_paths), EXPECTED_PAIRS)
    _count(issues, "outcome_file_count", str(root), len(outcome_paths), EXPECTED_PAIRS)
    paired_outcomes = {
        path.with_name(path.name.replace(".corpus.json", ".outcomes.json")) for path in corpus_paths
    }
    for missing_path in sorted(paired_outcomes - set(outcome_paths)):
        _add(issues, "missing_outcome_sidecar", str(missing_path), "sidecar missing")
    for orphan_path in sorted(set(outcome_paths) - paired_outcomes):
        _add(issues, "orphan_outcome_sidecar", str(orphan_path), "corpus missing")

    benchmark_ids: set[str] = set()
    frozen_times: set[str] = set()
    cases: dict[str, tuple[Mapping[str, Any], str, datetime | None, tuple[str, ...]]] = {}
    outcomes: dict[str, str] = {}
    split_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    domain_splits: Counter[tuple[str, str]] = Counter()
    alignments: Counter[tuple[str, str]] = Counter()

    for corpus_path in corpus_paths:
        corpus = _load(corpus_path, issues)
        if corpus is None:
            continue
        corpus_name = str(corpus_path)
        _keys(corpus, _CORPUS_KEYS, corpus_name, issues)
        _leakage(corpus, corpus_name, issues)
        if corpus.get("schema_version") != CORPUS_SCHEMA:
            _add(issues, "schema_version", f"{corpus_name}.schema_version", CORPUS_SCHEMA)
        benchmark = _text(corpus.get("benchmark_id"), f"{corpus_name}.benchmark_id", issues)
        if benchmark is not None:
            benchmark_ids.add(benchmark)
        _text(corpus.get("revision"), f"{corpus_name}.revision", issues)
        frozen = corpus.get("frozen_at")
        if _time(frozen, f"{corpus_name}.frozen_at", issues) is not None:
            frozen_times.add(str(frozen))
        corpus_cases = _list(corpus.get("cases"), f"{corpus_name}.cases", "invalid_cases", issues)
        local_case_ids: set[str] = set()
        for index, value in enumerate(corpus_cases):
            case_path = f"{corpus_name}.cases[{index}]"
            case_id, domain, split, cutoff, option_ids = _case(value, case_path, issues)
            if case_id is not None:
                local_case_ids.add(case_id)
                if case_id in cases:
                    _add(issues, "duplicate_case_id", f"{case_path}.case_id", case_id)
                elif isinstance(value, dict):
                    cases[case_id] = (value, case_path, cutoff, option_ids)
            if domain is not None:
                domain_counts[domain] += 1
            if split is not None:
                split_counts[split] += 1
            if domain is not None and split is not None:
                domain_splits[(domain, split)] += 1

        sidecar_path = corpus_path.with_name(
            corpus_path.name.replace(".corpus.json", ".outcomes.json")
        )
        sidecar = _load(sidecar_path, issues) if sidecar_path.exists() else None
        if sidecar is None:
            continue
        sidecar_name = str(sidecar_path)
        _keys(sidecar, _SIDECAR_KEYS, sidecar_name, issues)
        if sidecar.get("schema_version") != OUTCOME_SCHEMA:
            _add(issues, "schema_version", f"{sidecar_name}.schema_version", OUTCOME_SCHEMA)
        if sidecar.get("benchmark_id") != benchmark:
            _add(issues, "benchmark_mismatch", f"{sidecar_name}.benchmark_id", "does not match")
        digest = canonical_json_sha256(corpus)
        if sidecar.get("corpus_sha256") != digest:
            _add(issues, "corpus_hash_mismatch", f"{sidecar_name}.corpus_sha256", digest)
        sidecar_outcomes = _list(
            sidecar.get("outcomes"), f"{sidecar_name}.outcomes", "invalid_outcomes", issues
        )
        local_outcome_ids: set[str] = set()
        for index, value in enumerate(sidecar_outcomes):
            outcome_path = f"{sidecar_name}.outcomes[{index}]"
            case_id, resolved_at, correct = _outcome(value, outcome_path, issues)
            if case_id is None:
                continue
            local_outcome_ids.add(case_id)
            if case_id in outcomes:
                _add(issues, "duplicate_outcome_case_id", f"{outcome_path}.case_id", case_id)
            else:
                outcomes[case_id] = outcome_path
            record = cases.get(case_id)
            if record is None:
                continue
            case_value, _, cutoff, option_ids = record
            if correct is not None and correct not in option_ids:
                _add(
                    issues,
                    "unknown_correct_option",
                    f"{outcome_path}.correct_option_id",
                    "not a case option",
                )
            if cutoff is not None and resolved_at is not None and resolved_at <= cutoff:
                _add(
                    issues,
                    "pre_cutoff_resolution",
                    f"{outcome_path}.resolved_at",
                    "must be after cutoff",
                )
            domain, split = case_value.get("domain"), case_value.get("split")
            if (
                isinstance(domain, str)
                and isinstance(split, str)
                and correct == case_value.get("forecast_option_id")
            ):
                alignments[(domain, split)] += 1
        if local_case_ids != local_outcome_ids:
            missing = sorted(local_case_ids - local_outcome_ids)
            extra = sorted(local_outcome_ids - local_case_ids)
            _add(issues, "case_outcome_mismatch", sidecar_name, f"missing={missing}; extra={extra}")

    if benchmark_ids != {BENCHMARK_ID}:
        _add(issues, "benchmark_id_set", str(root), f"found {sorted(benchmark_ids)}")
    if len(frozen_times) != 1:
        _add(issues, "freeze_timestamp_set", str(root), f"found {sorted(frozen_times)}")
    _count(issues, "case_count", str(root), len(cases), EXPECTED_CASES)
    _count(issues, "outcome_count", str(root), len(outcomes), EXPECTED_CASES)
    for split, expected in SPLIT_COUNTS.items():
        _count(issues, "split_count", f"{root}:{split}", split_counts[split], expected)
    for domain in DOMAINS:
        _count(issues, "domain_count", f"{root}:{domain}", domain_counts[domain], 6)
        for split, expected in DOMAIN_SPLIT_COUNTS.items():
            _count(
                issues,
                "domain_split_count",
                f"{root}:{domain}:{split}",
                domain_splits[(domain, split)],
                expected,
            )
        for split, expected in ALIGNMENT_COUNTS.items():
            _count(
                issues,
                "target_alignment_count",
                f"{root}:{domain}:{split}",
                alignments[(domain, split)],
                expected,
            )
    return CorpusIntegrityReport(
        benchmark_id=next(iter(benchmark_ids)) if len(benchmark_ids) == 1 else None,
        corpus_files=len(corpus_paths),
        outcome_files=len(outcome_paths),
        case_count=len(cases),
        split_counts=dict(split_counts),
        domain_counts=dict(domain_counts),
        issues=tuple(issues),
    )
