"""Opt-in publish-time debate gate for boss-loop deliverables.

The gate is intentionally small, fail-open by default, and only evaluates
branch deliverables immediately before PR publication. It never changes worker
classification; it can only allow or skip the publish step.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

from aragora.swarm.env_utils import git_safe_env
from aragora.swarm.worker_process import is_ignored_changed_path

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return [_text(value) for value in values if _text(value)]


def _bounded(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _normalize_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, confidence))


def _normalize_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    lowered = _text(value).lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ValueError("Debate gate response missing strict boolean 'passed' field.")


@dataclass(slots=True)
class DebateGateConfig:
    """Runtime configuration for the publish-time debate gate."""

    enabled: bool = False
    fail_closed: bool = False
    agent_type: str = "codex"
    timeout_seconds: float = 90.0
    max_changed_files: int = 12
    max_diff_chars: int = 12000
    max_issue_body_chars: int = 1500


@dataclass(slots=True)
class DebateGateRequest:
    """Bounded context for one publish-time gate decision."""

    issue_number: int | None = None
    issue_title: str = ""
    issue_body: str = ""
    source_branch: str = ""
    target_branch: str = "main"
    commit_shas: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    receipt_id: str | None = None


@dataclass(slots=True)
class DebateGateResult:
    """Structured machine-readable publish-gate verdict."""

    verdict: str
    publication_allowed: bool
    passed: bool
    confidence: float | None = None
    concerns: list[str] = field(default_factory=list)
    fail_open_used: bool = False
    reason: str = ""
    ran: bool = False
    agent_type: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    changed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "publication_allowed": self.publication_allowed,
            "passed": self.passed,
            "confidence": self.confidence,
            "concerns": list(self.concerns),
            "fail_open_used": self.fail_open_used,
            "reason": self.reason,
            "ran": self.ran,
            "agent_type": self.agent_type,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "changed_files": list(self.changed_files),
        }


class DebateGate:
    """Evaluate whether a verified branch deliverable should be published."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: DebateGateConfig,
        llm_caller: Callable[[str, str, float], str] | None = None,
        diff_loader: Callable[[Path, DebateGateRequest, DebateGateConfig], dict[str, Any]]
        | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.config = config
        self._llm_caller = llm_caller or self._default_llm_caller
        self._diff_loader = diff_loader or self._default_diff_loader

    def evaluate(self, request: DebateGateRequest) -> DebateGateResult:
        """Return a structured publish verdict for one branch deliverable."""
        agent_type = _text(self.config.agent_type) or "codex"
        if not self.config.enabled:
            return DebateGateResult(
                verdict="skipped_disabled",
                publication_allowed=True,
                passed=False,
                reason="Debate publish gate disabled.",
                ran=False,
                agent_type=agent_type,
                source_branch=request.source_branch or None,
                target_branch=request.target_branch or None,
                changed_files=list(request.changed_files),
            )

        try:
            payload = self._diff_loader(self.repo_root, request, self.config)
            prompt = self._build_prompt(request, payload)
            raw = self._llm_caller(prompt, agent_type, float(self.config.timeout_seconds or 90.0))
            parsed = self._parse_response(raw)
            parsed.agent_type = agent_type
            parsed.source_branch = request.source_branch or None
            parsed.target_branch = request.target_branch or None
            parsed.changed_files = list(payload.get("changed_files", []))
            return parsed
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            fail_open = not self.config.fail_closed
            verdict = "fail_open" if fail_open else "blocked"
            logger.info("Debate publish gate %s: %s", verdict, reason)
            return DebateGateResult(
                verdict=verdict,
                publication_allowed=fail_open,
                passed=False,
                fail_open_used=fail_open,
                reason=reason,
                ran=False,
                agent_type=agent_type,
                source_branch=request.source_branch or None,
                target_branch=request.target_branch or None,
                changed_files=list(request.changed_files),
            )

    @staticmethod
    def _default_llm_caller(prompt: str, agent_type: str, timeout_seconds: float) -> str:
        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def _worker() -> None:
            try:
                from aragora.agents.base import create_agent

                agent = cast(Any, create_agent)(
                    agent_type,
                    name="debate-publish-gate",
                    role="critic",
                )
                result["raw"] = asyncio.run(agent.generate(prompt))
            except BaseException as exc:  # pragma: no cover - defensive thread handoff
                error["exc"] = exc

        thread = threading.Thread(target=_worker, name="debate-publish-gate", daemon=True)
        thread.start()
        thread.join(timeout_seconds)
        if thread.is_alive():
            raise TimeoutError(f"Debate gate timed out after {timeout_seconds:.1f}s")
        if "exc" in error:
            raise RuntimeError(str(error["exc"])) from error["exc"]
        return _text(result.get("raw"))

    @staticmethod
    def _default_diff_loader(
        repo_root: Path,
        request: DebateGateRequest,
        config: DebateGateConfig,
    ) -> dict[str, Any]:
        changed_files = DebateGate._resolve_changed_files(repo_root, request, config)
        diff_target = f"{request.target_branch}...{request.source_branch}"
        diff_stat = DebateGate._run_git_capture(
            repo_root,
            ["git", "diff", "--stat", diff_target, "--", *changed_files]
            if changed_files
            else ["git", "diff", "--stat", diff_target],
        )
        diff_excerpt = DebateGate._run_git_capture(
            repo_root,
            [
                "git",
                "diff",
                "--unified=2",
                "--no-ext-diff",
                diff_target,
                "--",
                *changed_files,
            ]
            if changed_files
            else [
                "git",
                "diff",
                "--unified=2",
                "--no-ext-diff",
                diff_target,
            ],
            max_chars=config.max_diff_chars,
        )
        return {
            "changed_files": changed_files,
            "diff_stat": diff_stat,
            "diff_excerpt": diff_excerpt,
            "verification_summary": DebateGate._verification_summary(request),
        }

    @staticmethod
    def _resolve_changed_files(
        repo_root: Path,
        request: DebateGateRequest,
        config: DebateGateConfig,
    ) -> list[str]:
        files = [path for path in request.changed_files if not is_ignored_changed_path(path)]
        if not files:
            raw = DebateGate._run_git_capture(
                repo_root,
                [
                    "git",
                    "diff",
                    "--name-only",
                    f"{request.target_branch}...{request.source_branch}",
                ],
            )
            files = [
                path for path in raw.splitlines() if path and not is_ignored_changed_path(path)
            ]

        seen: set[str] = set()
        ordered: list[str] = []
        for path in files:
            clean = _text(path)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            ordered.append(clean)
            if len(ordered) >= max(int(config.max_changed_files or 0), 1):
                break
        return ordered

    @staticmethod
    def _run_git_capture(repo_root: Path, cmd: list[str], *, max_chars: int | None = None) -> str:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=git_safe_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git diff failed")
        return _bounded(proc.stdout, max_chars or 1_000_000)

    @staticmethod
    def _verification_summary(request: DebateGateRequest) -> dict[str, Any]:
        checks = list(request.verification_results)
        passed = sum(1 for item in checks if item.get("passed") is True)
        failed = sum(1 for item in checks if item.get("passed") is False)
        names = [
            _text(item.get("name") or item.get("command") or item.get("target"))
            for item in checks
            if _text(item.get("name") or item.get("command") or item.get("target"))
        ]
        return {
            "tests_run": list(request.tests_run),
            "checks_observed": len(checks),
            "checks_passed": passed,
            "checks_failed": failed,
            "check_names": names[:10],
        }

    def _build_prompt(self, request: DebateGateRequest, payload: dict[str, Any]) -> str:
        prompt_payload = {
            "issue": {
                "number": request.issue_number,
                "title": request.issue_title,
                "body_excerpt": _bounded(
                    _text(request.issue_body), self.config.max_issue_body_chars
                ),
            },
            "publish_candidate": {
                "source_branch": request.source_branch,
                "target_branch": request.target_branch,
                "commit_shas": list(request.commit_shas),
                "changed_files": list(payload.get("changed_files", [])),
                "receipt_id": request.receipt_id,
            },
            "verification": payload.get("verification_summary", {}),
            "diff_stat": _text(payload.get("diff_stat")),
            "diff_excerpt": _text(payload.get("diff_excerpt")),
        }
        return (
            "You are a conservative publish gate for an autonomous software lane. "
            "A worker already passed verification and produced a branch deliverable. "
            "Decide only whether PR publication should proceed now. "
            "Block only for concrete correctness, safety, or task-intent problems visible in the context. "
            "Do not require perfection or merge-readiness.\n\n"
            "Return ONLY JSON with this exact shape:\n"
            '{"passed": true, "confidence": 0.0, "reason": "short reason", "concerns": ["optional concern"]}\n\n'
            f"{json.dumps(prompt_payload, indent=2, sort_keys=True)}"
        )

    @staticmethod
    def _parse_response(raw: str) -> DebateGateResult:
        payload = DebateGate._extract_json_payload(raw)
        passed = _normalize_passed(payload.get("passed"))
        concerns = _string_list(payload.get("concerns"))
        reason = _text(payload.get("reason"))
        if not reason and concerns:
            reason = concerns[0]
        if not reason:
            reason = "Gate approved publication." if passed else "Gate requested human review."
        return DebateGateResult(
            verdict="passed" if passed else "blocked",
            publication_allowed=passed,
            passed=passed,
            confidence=_normalize_confidence(payload.get("confidence")),
            concerns=concerns,
            fail_open_used=False,
            reason=reason,
            ran=True,
        )

    @staticmethod
    def _extract_json_payload(raw: str) -> dict[str, Any]:
        text = _text(raw)
        if not text:
            raise ValueError("Debate gate returned empty output.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = _JSON_OBJECT_RE.search(text)
            if not match:
                raise ValueError("Debate gate did not return JSON.") from None
            payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            raise ValueError("Debate gate JSON payload must be an object.")
        return payload
