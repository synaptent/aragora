#!/usr/bin/env python3
"""Collect and measure the Factory review quorum-vs-single smoke benchmark.

``collect`` makes live, no-publish reviewer calls against manifest-pinned PR
heads. ``measure`` is offline: it validates a committed adjudication artifact,
computes single-model and quorum metrics, and emits canonical CollectOutcome
fixtures for receipt replay.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aragora.agents import create_agent  # noqa: E402
from aragora.agents.api_agents.common import close_shared_connector  # noqa: E402
from aragora.cli.commands.review_pr import (  # noqa: E402
    _build_review_prompt,
    _extract_first_json_object,
    _fetch_pr_diff,
    _fetch_pr_target,
    _normalize_findings,
)
from aragora.swarm.quorum_evidence import CollectOutcome, EvidenceItem  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "docs/benchmarks/factory_review_benchmark_manifest.json"
DEFAULT_EVIDENCE = REPO_ROOT / "docs/benchmarks/factory_review_quorum_vs_single_evidence.json"
DEFAULT_LIVE_COLLECTION = (
    REPO_ROOT / "docs/benchmarks/factory_review_quorum_vs_single_live_collection.json"
)
DEFAULT_RESULTS = REPO_ROOT / "docs/benchmarks/factory_review_quorum_vs_single_results.json"
DEFAULT_OUTCOME_DIR = REPO_ROOT / "docs/benchmarks/fixtures"

PROVIDER_FAMILIES = {
    "grok": "grok",
    "mistral-api": "mistral",
}
FAMILY_ALIASES = {
    "grok": "xai",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_family(family: str) -> str:
    return FAMILY_ALIASES.get(family, family)


def _resolve_output_path(path: Path, *, label: str, allow_external: bool) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        if not allow_external:
            raise ValueError(
                f"{label} is outside the repository; pass --allow-external-output "
                "to permit external writes"
            ) from exc
    return resolved


def _output_path_label(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _manifest_cases(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = manifest.get("smoke_cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest smoke_cases must be a non-empty list")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("manifest source must be an object")
    benchmark_head_sha = source.get("benchmark_head_sha")
    if not isinstance(benchmark_head_sha, str) or not benchmark_head_sha.strip():
        raise ValueError("manifest source.benchmark_head_sha must be non-empty")
    benchmark_head_sha = benchmark_head_sha.strip()
    cases: dict[str, dict[str, Any]] = {}
    required = {
        "case_id",
        "repo",
        "pr_number",
        "pr_url",
        "base_sha",
        "head_sha",
        "validation_path",
        "validation_blob_sha",
        "validation_url",
    }
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("each manifest smoke case must be an object")
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"manifest case missing fields: {', '.join(missing)}")
        case_id = str(raw["case_id"])
        if case_id in cases:
            raise ValueError(f"duplicate manifest case: {case_id}")
        validation_url = urlsplit(str(raw["validation_url"]))
        path_parts = [part for part in validation_url.path.split("/") if part]
        if (
            validation_url.scheme != "https"
            or validation_url.netloc != "raw.githubusercontent.com"
            or len(path_parts) < 4
            or path_parts[2] != benchmark_head_sha
        ):
            raise ValueError(f"{case_id}: validation_url is not pinned to benchmark_head_sha")
        cases[case_id] = raw
    return cases


def _fetch_pr_base_sha(target: Any) -> str:
    completed = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(target.number),
            "--repo",
            str(target.repo),
            "--json",
            "baseRefOid",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown gh error"
        raise ValueError(f"unable to resolve PR base SHA: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("unable to resolve PR base SHA: gh returned invalid JSON") from exc
    base_sha = payload.get("baseRefOid") if isinstance(payload, dict) else None
    if not isinstance(base_sha, str) or not base_sha.strip():
        raise ValueError("unable to resolve PR base SHA: baseRefOid is missing")
    return base_sha.strip()


def _validate_pinned_pr_state(target: Any, case: dict[str, Any]) -> None:
    if target.head_sha != case["head_sha"]:
        raise ValueError(
            f"{case['case_id']}: PR head drifted, expected {case['head_sha']}, got {target.head_sha}"
        )
    base_sha = _fetch_pr_base_sha(target)
    if base_sha != case["base_sha"]:
        raise ValueError(
            f"{case['case_id']}: PR base drifted, expected {case['base_sha']}, got {base_sha}"
        )


async def _collect_one(provider: str, case: dict[str, Any]) -> dict[str, Any]:
    if provider not in PROVIDER_FAMILIES:
        raise ValueError(f"unsupported benchmark provider: {provider}")
    target = _fetch_pr_target(
        str(case["pr_url"]),
        repo_override=str(case["repo"]),
        repo_root=REPO_ROOT,
    )
    _validate_pinned_pr_state(target, case)
    diff_text = _fetch_pr_diff(target)
    prompt = _build_review_prompt(target=target, diff_text=diff_text)
    agent = create_agent(provider, name=f"m9_{provider}_reviewer", role="critic")
    try:
        raw_response = await agent.generate(prompt)
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            closed = close()
            if asyncio.iscoroutine(closed):
                await closed
        await close_shared_connector()
    parsed = _extract_first_json_object(raw_response)
    status = str(parsed.get("status", "")).strip().lower()
    if status not in {"passed", "changes_requested", "blocked_nonreviewable"}:
        raise ValueError(f"{case['case_id']} {provider}: response has no valid status")
    findings = _normalize_findings(parsed.get("findings"))
    for index, finding in enumerate(findings, start=1):
        finding["finding_id"] = f"{PROVIDER_FAMILIES[provider]}-{index}"
    return {
        "provider": provider,
        "family": PROVIDER_FAMILIES[provider],
        "model": str(agent.model),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "status": status,
        "summary": str(parsed.get("summary", "")).strip(),
        "findings": findings,
        "raw_response": raw_response,
    }


async def collect_live(
    manifest: dict[str, Any],
    *,
    providers: list[str],
) -> dict[str, Any]:
    cases = _manifest_cases(manifest)
    output_cases = []
    for case_id, case in cases.items():
        model_results = []
        for provider in providers:
            model_results.append(await _collect_one(provider, case))
        output_cases.append(
            {
                "case_id": case_id,
                "repo": case["repo"],
                "pr_number": case["pr_number"],
                "base_sha": case["base_sha"],
                "head_sha": case["head_sha"],
                "validation_blob_sha": case["validation_blob_sha"],
                "validation_url": case["validation_url"],
                "model_results": model_results,
            }
        )
    return {
        "schema_version": 1,
        "kind": "factory_review_quorum_vs_single_live_collection",
        "collected_at": datetime.now(UTC).isoformat(),
        "providers": providers,
        "cases": output_cases,
    }


def _verdict_body(model: dict[str, Any]) -> str:
    status = str(model["status"])
    verdict = {
        "passed": "PASS",
        "changes_requested": "CHANGES-REQUESTED",
    }.get(status, "UNKNOWN")
    lines = [
        f"Provider: {model.get('provider', '')}; model: {model.get('model', '')}",
        f"Verdict: {verdict}",
        str(model.get("summary", "")).strip(),
    ]
    for finding in model.get("findings", []):
        golden = finding.get("golden_comment_id")
        adjudication = f" [adjudicated golden_comment_id={golden}]" if golden is not None else ""
        lines.append(
            f"- [{finding.get('priority', 'P2')}] {finding.get('file', '')}: "
            f"{finding.get('title', 'Finding')}: {finding.get('body', '')}{adjudication}"
        )
    return "\n".join(line for line in lines if line.strip())


def _outcome_for(case: dict[str, Any], live_collection_sha256: str) -> dict[str, Any]:
    items = []
    for model in case["model_results"]:
        status = str(model["status"])
        evidence_verdict = {
            "passed": "pass",
            "changes_requested": "changes_requested",
        }.get(status, "unknown")
        items.append(
            EvidenceItem(
                family=str(model["family"]),
                body=_verdict_body(model),
                would_count=status in {"passed", "changes_requested"},
                verdict=evidence_verdict,
                severity_gated=False,
            )
        )
    outcome = CollectOutcome(
        repo=str(case["repo"]),
        pr=int(case["pr_number"]),
        head_sha=str(case["head_sha"]),
        head_committed_at="",
        tier=None,
        action="prepare",
        action_reason=(
            "offline replay of committed live reviewer output collection "
            f"canonical sha256:{live_collection_sha256}; golden mappings are manual adjudication"
        ),
        items=items,
        posted=[],
        tiered_gate=False,
    )
    return outcome.to_dict()


def _join_live_collection(
    evidence: dict[str, Any],
    live_collection: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_cases = evidence.get("cases")
    live_cases = live_collection.get("cases")
    if not isinstance(evidence_cases, list) or not isinstance(live_cases, list):
        raise ValueError("evidence and live collection cases must be lists")
    live_by_id = {
        str(case.get("case_id", "")): case for case in live_cases if isinstance(case, dict)
    }
    if len(live_by_id) != len(live_cases):
        raise ValueError("live collection contains duplicate or invalid cases")

    joined = []
    for adjudicated in evidence_cases:
        if not isinstance(adjudicated, dict):
            raise ValueError("each evidence case must be an object")
        case_id = str(adjudicated.get("case_id", ""))
        live = live_by_id.get(case_id)
        if live is None:
            raise ValueError(f"{case_id}: missing from live collection")
        for field in ("repo", "pr_number", "base_sha", "head_sha", "validation_blob_sha"):
            if adjudicated.get(field) != live.get(field):
                raise ValueError(f"{case_id}: live collection {field} differs from adjudication")

        live_models = {
            str(model.get("provider", "")): model
            for model in live.get("model_results", [])
            if isinstance(model, dict)
        }
        merged_models = []
        for annotated in adjudicated.get("model_results", []):
            provider = str(annotated.get("provider", ""))
            raw_model = live_models.get(provider)
            if raw_model is None:
                raise ValueError(f"{case_id}: {provider} missing from live collection")
            for field in ("family", "model", "status"):
                if annotated.get(field) != raw_model.get(field):
                    raise ValueError(f"{case_id} {provider}: {field} differs from live collection")
            annotations = {
                str(item["finding_id"]): item.get("golden_comment_id")
                for item in annotated.get("findings", [])
            }
            raw_findings = raw_model.get("findings", [])
            raw_ids = {str(item["finding_id"]) for item in raw_findings}
            if set(annotations) != raw_ids:
                raise ValueError(f"{case_id} {provider}: finding set differs from live collection")
            merged = dict(raw_model)
            merged["findings"] = [
                {
                    **finding,
                    **(
                        {"golden_comment_id": annotations[str(finding["finding_id"])]}
                        if annotations[str(finding["finding_id"])] is not None
                        else {}
                    ),
                }
                for finding in raw_findings
            ]
            merged_models.append(merged)
        if set(live_models) != {str(model["provider"]) for model in merged_models}:
            raise ValueError(f"{case_id}: provider set differs from live collection")
        joined.append({**adjudicated, "model_results": merged_models})
    if {str(case.get("case_id", "")) for case in joined} != set(live_by_id):
        raise ValueError("adjudication does not exactly cover live collection cases")
    return joined


def measure(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    live_collection: dict[str, Any],
    *,
    baseline_provider: str,
    outcome_dir: Path,
) -> dict[str, Any]:
    manifest_cases = _manifest_cases(manifest)
    evidence_cases = _join_live_collection(evidence, live_collection)
    if len(evidence_cases) != len(manifest_cases):
        raise ValueError("evidence cases must exactly cover the manifest smoke cases")
    live_collection_sha256 = _canonical_sha256(live_collection)

    measured_cases = []
    all_families: set[str] = set()
    for case in evidence_cases:
        if not isinstance(case, dict):
            raise ValueError("each evidence case must be an object")
        case_id = str(case.get("case_id", ""))
        manifest_case = manifest_cases.get(case_id)
        if manifest_case is None:
            raise ValueError(f"evidence references unknown case: {case_id}")
        for field in ("repo", "pr_number", "base_sha", "head_sha", "validation_blob_sha"):
            if case.get(field) != manifest_case.get(field):
                raise ValueError(f"{case_id}: evidence {field} differs from manifest")

        goldens = case.get("goldens")
        models = case.get("model_results")
        if not isinstance(goldens, list) or not goldens:
            raise ValueError(f"{case_id}: no golden findings")
        if not isinstance(models, list) or len(models) < 2:
            raise ValueError(f"{case_id}: quorum requires at least two model results")
        golden_ids = {str(golden["comment_id"]) for golden in goldens}
        model_metrics = []
        baseline_matches: set[str] | None = None
        quorum_matches: set[str] = set()
        for model in models:
            provider = str(model.get("provider", ""))
            family = _canonical_family(str(model.get("family", "")))
            all_families.add(family)
            matches: set[str] = set()
            for finding in model.get("findings", []):
                golden_id = finding.get("golden_comment_id")
                if golden_id is not None:
                    matches.add(str(golden_id))
            unknown = sorted(matches - golden_ids)
            if unknown:
                raise ValueError(f"{case_id} {provider}: unknown golden IDs {unknown}")
            quorum_matches.update(matches)
            if provider == baseline_provider:
                baseline_matches = matches
            model_metrics.append(
                {
                    "provider": provider,
                    "family": family,
                    "model": model.get("model"),
                    "status": model.get("status"),
                    "finding_set": model.get("findings", []),
                    "true_positive_golden_ids": sorted(matches),
                    "missed_golden_ids": sorted(golden_ids - matches),
                    "unmatched_finding_ids": sorted(
                        str(finding["finding_id"])
                        for finding in model.get("findings", [])
                        if finding.get("golden_comment_id") is None
                    ),
                }
            )
        if baseline_matches is None:
            raise ValueError(f"{case_id}: named baseline {baseline_provider} is absent")
        families = {_canonical_family(str(model["family"])) for model in models}
        if len(families) < 2:
            raise ValueError(f"{case_id}: quorum has fewer than two distinct families")

        fixture_path = outcome_dir / f"{case_id}.collect-outcome.json"
        _write_json(fixture_path, _outcome_for(case, live_collection_sha256))
        measured_cases.append(
            {
                "case_id": case_id,
                "repo": case["repo"],
                "pr_number": case["pr_number"],
                "base_sha": case["base_sha"],
                "head_sha": case["head_sha"],
                "validation_blob_sha": case["validation_blob_sha"],
                "validation_url": manifest_case["validation_url"],
                "goldens": goldens,
                "baseline": {
                    "provider": baseline_provider,
                    "true_positive_golden_ids": sorted(baseline_matches),
                    "missed_golden_ids": sorted(golden_ids - baseline_matches),
                },
                "models": model_metrics,
                "quorum": {
                    "families": sorted(families),
                    "distinct_model_families": len(families),
                    "true_positive_golden_ids": sorted(quorum_matches),
                    "missed_golden_ids": sorted(golden_ids - quorum_matches),
                    "caught_beyond_baseline_golden_ids": sorted(quorum_matches - baseline_matches),
                },
                "collect_outcome_fixture": _output_path_label(fixture_path),
                "receipt_path": (f"docs/benchmarks/receipts/{case_id}-receipt.odr.json"),
            }
        )

    single_miss_cases = [
        {
            "case_id": case["case_id"],
            "baseline_provider": baseline_provider,
            "golden_ids": case["quorum"]["caught_beyond_baseline_golden_ids"],
        }
        for case in measured_cases
        if case["quorum"]["caught_beyond_baseline_golden_ids"]
    ]
    return {
        "schema_version": 1,
        "kind": "factory_review_quorum_vs_single_measurement",
        "manifest": str(DEFAULT_MANIFEST.relative_to(REPO_ROOT)),
        "benchmark_head_sha": manifest["source"]["benchmark_head_sha"],
        "manifest_blob_sha": manifest["source"]["manifest_blob_sha"],
        "live_collection": str(DEFAULT_LIVE_COLLECTION.relative_to(REPO_ROOT)),
        "live_collection_canonical_sha256": live_collection_sha256,
        "adjudication_scope": "manual golden_comment_id mappings only; finding text is live output",
        "family_aliases": dict(sorted(FAMILY_ALIASES.items())),
        "baseline_provider": baseline_provider,
        "quorum_families": sorted(all_families),
        "cases": measured_cases,
        "summary": {
            "case_count": len(measured_cases),
            "single_model_miss_case_count": len(single_miss_cases),
            "single_model_miss_cases": single_miss_cases,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="run live no-publish model reviews")
    collect.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    collect.add_argument("--providers", nargs="+", default=["grok", "mistral-api"])
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument(
        "--allow-external-output",
        action="store_true",
        help="permit --output outside the repository (disabled by default)",
    )

    offline = subparsers.add_parser("measure", help="measure committed evidence offline")
    offline.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    offline.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    offline.add_argument("--live-collection", type=Path, default=DEFAULT_LIVE_COLLECTION)
    offline.add_argument("--baseline-provider", default="mistral-api")
    offline.add_argument("--outcome-dir", type=Path, default=DEFAULT_OUTCOME_DIR)
    offline.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    offline.add_argument(
        "--allow-external-output",
        action="store_true",
        help="permit --output and --outcome-dir outside the repository (disabled by default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_path = _resolve_output_path(
            args.output,
            label="--output",
            allow_external=args.allow_external_output,
        )
        manifest = _read_json(args.manifest)
        if args.command == "collect":
            result = asyncio.run(collect_live(manifest, providers=args.providers))
        else:
            outcome_dir = _resolve_output_path(
                args.outcome_dir,
                label="--outcome-dir",
                allow_external=args.allow_external_output,
            )
            evidence = _read_json(args.evidence)
            live_collection = _read_json(args.live_collection)
            result = measure(
                manifest,
                evidence,
                live_collection,
                baseline_provider=args.baseline_provider,
                outcome_dir=outcome_dir,
            )
        _write_json(output_path, result)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(output_path), "cases": len(result["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
