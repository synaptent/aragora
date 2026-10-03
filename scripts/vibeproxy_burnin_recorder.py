#!/usr/bin/env python3
"""Record VibeProxy burn-in calls and non-countable PR shadow reviews.

This command never posts GitHub comments and never composes merge-quorum
evidence.  Shadow-review output is reduced to a verdict and SHA-256 digest
before the append-only record is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aragora.agents.transports.burnin import (  # noqa: E402
    BurninRecorder,
    BurninRecordError,
    CallOutcome,
    DEFAULT_PROOF_PATH,
    DEFAULT_RECORDS_PATH,
    infer_model_family,
    write_proof_artifact,
)
from aragora.agents.transports.claude_vibeproxy import (  # noqa: E402
    DEFAULT_CLAUDE_MODEL,
    ClaudeVibeProxyAttempt,
    run_claude_vibeproxy,
)
from aragora.agents.transports.vibeproxy import (  # noqa: E402
    ModelTransportPolicy,
    OpenAIProtocol,
    ResolvedModelRoute,
    TransportMode,
    VibeProxyConfigurationError,
    VibeProxyUnavailableError,
)

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_REVIEW_TIMEOUT_SECONDS = 300.0
DEFAULT_INFERENCE_TIMEOUT_SECONDS = 60.0
DEFAULT_INFERENCE_MAX_TOKENS = 16
DEFAULT_GITHUB_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_DIFF_CHARS = 120_000
INFERENCE_SENTINEL = "ARAGORA_VIBEPROXY_BURNIN_OK"
INFERENCE_PROMPT = f"Reply with exactly: {INFERENCE_SENTINEL}"
_CATALOG_OWNER_FAMILIES = {
    "anthropic": "claude",
    "openai": "openai",
    "google": "gemini",
    "antigravity": "gemini",
    "xai": "grok",
    "moonshot": "kimi",
}
_VERDICT = re.compile(r"^\s*Verdict\s*:\s*(PASS|CHANGES-REQUESTED)\s*$", re.MULTILINE)


def _run_gh(args: list[str], *, timeout: float = DEFAULT_GITHUB_TIMEOUT_SECONDS) -> str:
    """Run a read-only gh command used to ground a shadow review."""

    completed = subprocess.run(
        ["gh", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:300]
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {detail}")
    return completed.stdout


def _load_pr(repo: str, pr: int) -> dict[str, Any]:
    raw = _run_gh(
        [
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "number,state,isDraft,title,body,headRefOid,url,files",
        ]
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh pr view returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("gh pr view returned a non-object")
    return payload


def _load_diff(repo: str, pr: int) -> str:
    return _run_gh(["pr", "diff", str(pr), "--repo", repo])


def _bound_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    marker = "\n\n[diff truncated by VibeProxy shadow recorder]\n"
    return value[: max(0, limit - len(marker))] + marker, True


def _changed_files(pr: dict[str, Any]) -> list[str]:
    files = pr.get("files")
    if not isinstance(files, list):
        return []
    return sorted(
        {
            str(item.get("path"))
            for item in files
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
    )


def build_shadow_prompt(
    *,
    repo: str,
    pr: dict[str, Any],
    diff: str,
    max_diff_chars: int,
) -> str:
    """Build a bounded exact-head review prompt that cannot become evidence."""

    head = str(pr.get("headRefOid") or "").strip()
    if not head:
        raise RuntimeError("PR has no headRefOid")
    bounded_diff, truncated = _bound_text(diff, max_diff_chars)
    file_list = "\n".join(f"- {path}" for path in _changed_files(pr)) or "- unavailable"
    body = str(pr.get("body") or "")[:5_000]
    return f"""You are running a NON-COUNTABLE VibeProxy shadow review.
Do not post anything and do not claim merge authorization. Review only the exact PR state below.
Return blocking findings first, each tagged [P0], [P1], [P2], or [P3].
End with exactly one line: Verdict: PASS or Verdict: CHANGES-REQUESTED.

Repository: {repo}
PR: #{pr["number"]}
Exact head: {head}
Title: {pr.get("title", "")}
Diff truncated: {str(truncated).lower()}

PR body:
{body}

Complete changed-file list:
{file_list}

Unified diff:
{bounded_diff}
"""


def _required_policy() -> ModelTransportPolicy:
    policy = ModelTransportPolicy.from_env(default_mode=TransportMode.REQUIRED)
    if policy.mode is not TransportMode.REQUIRED:
        raise VibeProxyConfigurationError(
            "shadow-review requires ARAGORA_MODEL_TRANSPORT=vibeproxy-required or unset"
        )
    return policy


def _attempt_error_class(attempt: ClaudeVibeProxyAttempt) -> str:
    value = attempt.error.lower()
    if "response model did not match" in value:
        return "family_identity_error"
    if "401" in value:
        return "http_401"
    if "403" in value or "credential" in value or "unauthorized" in value:
        return "credential_error"
    if "timed out" in value or "timeout" in value:
        return "timeout"
    if "configuration" in value or "configured" in value:
        return "configuration_error"
    return "transport_error"


def _exception_error_class(exc: BaseException) -> str:
    value = str(exc).lower()
    if "owner disclosure" in value:
        return "alias_disclosure_error"
    if "omitted its model identity" in value:
        return "family_identity_error"
    if "response model owner did not match" in value:
        return "family_identity_error"
    if "response model did not match" in value:
        return "family_identity_error"
    if "401" in value:
        return "http_401"
    if "403" in value or "credential" in value or "unauthorized" in value:
        return "credential_error"
    if "timed out" in value or "timeout" in value:
        return "timeout"
    if isinstance(exc, VibeProxyConfigurationError):
        return "configuration_error"
    return "transport_error"


def _extract_verdict(text: str) -> str | None:
    matches = _VERDICT.findall(text)
    return matches[-1] if matches else None


def _openai_chat_response(body: dict[str, Any]) -> tuple[str | None, bool]:
    """Extract the first chat message and whether generation was truncated."""

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, False
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        return None, choice.get("finish_reason") == "length"
    content = message.get("content")
    text = content.strip() if isinstance(content, str) else None
    return text or None, choice.get("finish_reason") == "length"


def run_inference(
    *,
    family: str,
    model: str,
    timeout: float,
    max_tokens: int,
    records_path: Path,
    proof_path: Path,
) -> tuple[int, dict[str, Any]]:
    """Run one bounded real inference and append only its sanitized outcome."""

    normalized_family = family.strip().lower()
    inferred_family = infer_model_family(model)
    if inferred_family != normalized_family:
        raise BurninRecordError(
            f"model {model!r} belongs to {inferred_family or 'an unknown family'}, "
            f"not {normalized_family!r}"
        )

    started = time.monotonic()
    route = ResolvedModelRoute(
        "anthropic" if normalized_family == "claude" else "openai",
        model,
        model,
        "vibeproxy",
        None,
        frozenset({"chat"}),
    )
    response_model: str | None = None
    catalog_owner: str | None = None
    catalog_family: str | None = None
    alias_family: str | None = None
    alias_sources: list[str] = []
    error_class: str | None = None
    response_text: str | None = None
    truncated = False
    ok = False
    try:
        policy = _required_policy()
        if policy.client is None:
            raise VibeProxyUnavailableError("required inference has no VibeProxy client")

        discovery_timeout = min(6.0, timeout)
        route = policy.resolve(
            route.provider,
            model,
            capabilities=("chat",),
            timeout=discovery_timeout,
        )
        if route.transport != "vibeproxy":
            raise VibeProxyUnavailableError("required inference did not resolve to VibeProxy")
        if route.requested_model != route.resolved_model:
            alias_sources.append("ARAGORA_VIBEPROXY_MODEL_MAP")
        request_timeout = max(0.1, timeout - (time.monotonic() - started))

        if normalized_family == "claude":
            response_text = policy.client.anthropic_message(
                model=route.resolved_model,
                prompt=INFERENCE_PROMPT,
                timeout=request_timeout,
                max_tokens=max_tokens,
            )
            # anthropic_message() returns only after exact response-model
            # verification inside VibeProxyClient.
            response_model = route.resolved_model
        else:
            catalog = policy.client.catalog(timeout=discovery_timeout)
            catalog_owner = catalog.owner_for(route.resolved_model)
            catalog_family = _CATALOG_OWNER_FAMILIES.get(catalog_owner or "")
            if catalog_owner is None:
                error_class = "alias_disclosure_error"
            elif catalog_family != normalized_family:
                error_class = "family_identity_error"
            else:
                body = policy.client.openai_catalog_alias_request(
                    protocol=OpenAIProtocol.CHAT,
                    model=route.resolved_model,
                    catalog=catalog,
                    payload={
                        "model": route.resolved_model,
                        "messages": [{"role": "user", "content": INFERENCE_PROMPT}],
                        "max_tokens": max_tokens,
                    },
                    timeout=request_timeout,
                )
                observed_model = body.get("model")
                response_model = observed_model if isinstance(observed_model, str) else None
                response_text, truncated = _openai_chat_response(body)
                response_owner = (
                    catalog.owner_for(response_model)
                    if response_model is not None and response_model in catalog.models
                    else None
                )
                if response_model is not None and response_owner is None:
                    error_class = "alias_disclosure_error"
                elif response_model is not None and response_owner != catalog_owner:
                    error_class = "family_identity_error"
                elif response_model != route.resolved_model:
                    alias_family = catalog_family
                    alias_sources.append(f"VibeProxy /v1/models owned_by={catalog_owner}")
        if error_class is None:
            if truncated:
                error_class = "truncated_response"
            elif response_text != INFERENCE_SENTINEL:
                error_class = "sentinel_mismatch"
            elif response_model is None:
                error_class = "missing_response_model"
            else:
                ok = True
    except (VibeProxyConfigurationError, VibeProxyUnavailableError) as exc:
        error_class = _exception_error_class(exc)
    except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        error_class = _exception_error_class(exc)

    record = BurninRecorder(records_path).append(
        CallOutcome(
            family=normalized_family,
            requested_model=route.requested_model,
            resolved_model=response_model or route.resolved_model,
            response_model=response_model,
            latency_ms=(time.monotonic() - started) * 1000,
            ok=ok,
            error_class=error_class,
            alias_source="; ".join(alias_sources) or None,
            alias_family=alias_family,
        )
    )
    proof = write_proof_artifact(records_path, proof_path)
    result = {
        "ok": record["clean"],
        "action": "inference_recorded",
        "record": record,
        "proof": proof,
        "response_body_persisted": False,
        "countable": False,
    }
    return (0 if record["clean"] else 1), result


def run_shadow_review(
    *,
    repo: str,
    pr_number: int,
    model: str,
    reviewer_timeout: float,
    max_diff_chars: int,
    records_path: Path,
    proof_path: Path,
) -> tuple[int, dict[str, Any]]:
    """Run one required-transport Claude shadow review and record its outcome."""

    pr = _load_pr(repo, pr_number)
    if pr.get("state") != "OPEN":
        raise RuntimeError(f"PR #{pr_number} is not open")
    head = str(pr.get("headRefOid") or "").strip()
    diff = _load_diff(repo, pr_number)
    if str(_load_pr(repo, pr_number).get("headRefOid") or "") != head:
        raise RuntimeError(f"PR #{pr_number} head drifted while loading its diff")
    prompt = build_shadow_prompt(
        repo=repo,
        pr=pr,
        diff=diff,
        max_diff_chars=max_diff_chars,
    )

    started = time.monotonic()
    route = ResolvedModelRoute("anthropic", model, model, "vibeproxy", None, frozenset({"chat"}))
    attempt: ClaudeVibeProxyAttempt | None = None
    error_class: str | None = None
    try:
        policy = _required_policy()
        route = policy.resolve("anthropic", model, capabilities=("chat",))
        if route.transport != "vibeproxy":
            raise VibeProxyUnavailableError("required shadow review did not resolve to VibeProxy")
        attempt = run_claude_vibeproxy(
            prompt,
            reviewer_timeout=reviewer_timeout,
            model=model,
            policy=policy,
        )
        if not attempt.attempted or not attempt.required:
            raise VibeProxyUnavailableError("shadow review did not use the required transport")
        if not attempt.ok:
            error_class = _attempt_error_class(attempt)
    except Exception as exc:
        error_class = _exception_error_class(exc)

    latency_ms = (time.monotonic() - started) * 1000
    response_text = attempt.text if attempt is not None and attempt.ok else ""
    verdict = _extract_verdict(response_text) if response_text else None
    response_model = attempt.response_model if attempt is not None and attempt.ok else None
    if response_text and response_model is None:
        error_class = error_class or "missing_response_model"
    if response_text and verdict is None:
        error_class = error_class or "unstructured_review"
    try:
        live_head = str(_load_pr(repo, pr_number).get("headRefOid") or "")
        head_stable = live_head == head
    except (RuntimeError, subprocess.TimeoutExpired):
        head_stable = False
        error_class = error_class or "github_recheck_error"
    alias_source = (
        "ARAGORA_VIBEPROXY_MODEL_MAP" if route.requested_model != route.resolved_model else None
    )
    record = BurninRecorder(records_path).append(
        CallOutcome(
            family="claude",
            requested_model=route.requested_model,
            resolved_model=route.resolved_model,
            response_model=response_model,
            latency_ms=latency_ms,
            ok=bool(response_text),
            error_class=error_class,
            alias_source=alias_source,
            call_kind="shadow_review",
            pr_number=pr_number,
            pr_head_sha=head,
            head_stable=head_stable,
            review_verdict=verdict,
            review_digest=(
                hashlib.sha256(response_text.encode("utf-8")).hexdigest() if response_text else None
            ),
        )
    )
    proof = write_proof_artifact(records_path, proof_path)
    result = {
        "ok": record["clean"],
        "action": "shadow_review_recorded",
        "record": record,
        "proof": proof,
        "review_body_persisted": False,
        "comment_posted": False,
        "evidence_composed": False,
    }
    return (0 if record["clean"] else 1), result


def _render_human(result: dict[str, Any]) -> str:
    if result.get("action") == "inference_recorded":
        record = result["record"]
        proof = result["proof"]
        return (
            f"VibeProxy inference: {'clean' if record['clean'] else 'failed'}; "
            f"family={record['family']} model={record['resolved_model']} "
            f"latency_ms={record['latency_ms']} error={record['error_class'] or 'none'}; "
            f"proof_ready={str(proof['ready']).lower()}"
        )
    if result.get("action") == "shadow_review_recorded":
        record = result["record"]
        proof = result["proof"]
        return (
            f"VibeProxy shadow review: {'clean' if record['clean'] else 'failed'}; "
            f"family={record['family']} latency_ms={record['latency_ms']} "
            f"error={record['error_class'] or 'none'}; "
            f"proof_ready={str(proof['ready']).lower()}"
        )
    return f"VibeProxy burn-in proof: ready={str(result['ready']).lower()}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS_PATH)
    parser.add_argument("--proof", type=Path, default=DEFAULT_PROOF_PATH)
    parser.add_argument("--json", action="store_true", dest="json_output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inference = subparsers.add_parser(
        "inference",
        help="Run one non-countable real inference through vibeproxy-required",
    )
    inference.add_argument("--family", required=True)
    inference.add_argument("--model", required=True)
    inference.add_argument("--timeout", type=float, default=DEFAULT_INFERENCE_TIMEOUT_SECONDS)
    inference.add_argument("--max-tokens", type=int, default=DEFAULT_INFERENCE_MAX_TOKENS)

    shadow = subparsers.add_parser(
        "shadow-review",
        help="Run one non-countable Claude review through vibeproxy-required",
    )
    shadow.add_argument("--repo", default=DEFAULT_REPO)
    shadow.add_argument("--pr", required=True, type=int)
    shadow.add_argument("--model", default=DEFAULT_CLAUDE_MODEL)
    shadow.add_argument("--timeout", type=float, default=DEFAULT_REVIEW_TIMEOUT_SECONDS)
    shadow.add_argument("--max-diff-chars", type=int, default=DEFAULT_MAX_DIFF_CHARS)

    subparsers.add_parser("summarize", help="Verify the JSONL chain and emit latest.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inference":
            if args.timeout <= 0 or args.max_tokens <= 0:
                parser.error("--timeout and --max-tokens must be positive")
            code, result = run_inference(
                family=args.family,
                model=args.model,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                records_path=args.records,
                proof_path=args.proof,
            )
        elif args.command == "shadow-review":
            if args.timeout <= 0 or args.max_diff_chars <= 0:
                parser.error("--timeout and --max-diff-chars must be positive")
            code, result = run_shadow_review(
                repo=args.repo,
                pr_number=args.pr,
                model=args.model,
                reviewer_timeout=args.timeout,
                max_diff_chars=args.max_diff_chars,
                records_path=args.records,
                proof_path=args.proof,
            )
        else:
            result = write_proof_artifact(args.records, args.proof)
            code = 0
    except (BurninRecordError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = {
            "ok": False,
            "action": "failed",
            "error_class": type(exc).__name__,
            "error": str(exc)[:300],
        }
        code = 2

    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            _render_human(result) if code != 2 else f"VibeProxy burn-in failed: {result['error']}"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
