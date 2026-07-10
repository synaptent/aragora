"""Tests for the B3 collect-evidence module (aragora.swarm.quorum_evidence).

Covers the two safety invariants directly:

* tier-gating — Tier 3+ (and unknown tier) never post, regardless of --apply;
* never-fabricate — failed/empty reviewers produce no comment.

The compose helper is checked against the *real* evidence parser
(``_lint_evidence_comment``) so the collector stays bound to the gate's logic.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import queue
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.swarm import quorum_evidence as qe
from aragora.swarm.quorum_evidence import (
    CollectOutcome,
    EvidenceItem,
    ReviewerResult,
    collect_evidence,
    compose_evidence_comment,
    decide_action,
)

HEAD = "49a979d587f910aaad4fb0f0bed708dd48c97c35"
COMMITTED = "2026-06-04T09:57:49-05:00"


@pytest.fixture(autouse=True)
def _enable_tiered_gate(monkeypatch):
    # This module exercises the opt-in tiered merge gate, so enable it by default.
    # The production default is OFF (strict 2-distinct-family); tests that assert
    # that strict default set ARAGORA_ENABLE_TIERED_MERGE_GATE="0" explicitly.
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")


# --- decide_action (tier gating) -------------------------------------------


@pytest.mark.parametrize("tier", [0, 1, 2])
def test_low_tier_with_apply_posts(tier: int) -> None:
    action, _ = decide_action(tier, apply=True)
    assert action == "post"


@pytest.mark.parametrize("tier", [0, 1, 2])
def test_low_tier_without_apply_prepares(tier: int) -> None:
    action, reason = decide_action(tier, apply=False)
    assert action == "prepare"
    assert "dry-run" in reason


@pytest.mark.parametrize("tier", [3, 4, 5])
def test_high_tier_never_posts_even_with_apply(tier: int) -> None:
    action, reason = decide_action(tier, apply=True)
    assert action == "prepare"
    assert "settlement" in reason


def test_unknown_tier_fails_safe_to_prepare() -> None:
    action, reason = decide_action(None, apply=True)
    assert action == "prepare"
    assert "unknown" in reason


def test_negative_tier_fails_safe_to_prepare() -> None:
    action, _ = decide_action(-1, apply=True)
    assert action == "prepare"


# --- compose_evidence_comment counts against the real parser ----------------


@pytest.mark.parametrize("family", ["claude", "grok"])
def test_composed_comment_counts_in_real_parser(family: str) -> None:
    from aragora.cli.commands.review_queue import _lint_evidence_comment

    body = compose_evidence_comment(
        family=family,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        pr=7740,
        reviewer_text="Verdict: PASS\n- no blocking issues [P3] none",
    )
    result = _lint_evidence_comment(
        pr="7740",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        body=body,
        author="an0mium",
        source="test",
    )
    assert result["would_count"] is True, result["problems"]
    assert family in result["counted_reviewer_ids"]


# --- reviewer-output normalization (low-cost-model format reliability) ------


def test_normalize_strips_thinking_traces() -> None:
    from aragora.swarm.quorum_evidence import normalize_reviewer_output

    raw = "<think>let me reason about this for a while...</think>\nVerdict: PASS\n- [P3] nit"
    out = normalize_reviewer_output(raw)
    assert "<think>" not in out and "reason about this" not in out
    assert out.splitlines()[0].lower().startswith("verdict:")


def test_normalize_reanchors_at_verdict_dropping_preamble() -> None:
    from aragora.swarm.quorum_evidence import normalize_reviewer_output

    raw = "Sure! Here is my review of the PR.\nReviewer: qwen\nVerdict: PASS\n- [P2] thing"
    out = normalize_reviewer_output(raw)
    assert out.splitlines()[0].lower().startswith("verdict:")
    assert "Sure!" not in out  # pre-verdict preamble dropped
    assert "[P2] thing" in out  # findings preserved


def test_thinking_polluted_review_still_counts_in_real_parser() -> None:
    # The qwen3-*-thinking failure mode: reasoning trace + preamble around a PASS.
    # Without normalization the composed comment failed identity/counting; with it,
    # the evidence must count.
    from aragora.cli.commands.review_queue import _lint_evidence_comment

    raw = (
        "<thinking>The diff looks fine. Model family considerations: this is like "
        "what claude would say. ## Internal heading.</thinking>\n"
        "Okay, here is the review.\n"
        "Verdict: PASS\n- [P3] minor style nit, non-blocking"
    )
    body = compose_evidence_comment(
        family="qwen",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        pr=7740,
        reviewer_text=raw,
    )
    result = _lint_evidence_comment(
        pr="7740",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        body=body,
        author="an0mium",
        source="test",
    )
    assert result["would_count"] is True, result["problems"]
    assert "qwen" in result["counted_reviewer_ids"]


def test_normalize_llm_fallback_off_by_default() -> None:
    # With no normalizer model configured and an unparseable verdict, normalization
    # is deterministic-only (returns the thinking-stripped text, no model call).
    from aragora.swarm.quorum_evidence import normalize_reviewer_output

    out = normalize_reviewer_output("just some prose, no verdict here")
    assert out == "just some prose, no verdict here"


def test_composed_comment_includes_head_and_family() -> None:
    body = compose_evidence_comment(
        family="claude",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        pr=42,
        reviewer_text="Verdict: PASS",
    )
    assert HEAD[:7] in body
    assert HEAD in body
    assert "Model family: claude" in body
    assert "independent model review" in body.lower()
    assert "dogfood: yes" in body


def test_reviewer_text_cannot_hijack_family() -> None:
    # A reviewer that emits its own heading + a conflicting Model family line
    # must NOT change the attributed family; the comment still counts as claude.
    # Two defenses compose: pre-verdict hijack is DROPPED by normalization's
    # re-anchor (stronger than quoting); post-verdict hijack is QUOTED by the
    # neutralizer. Either way the attributed family stays claude.
    from aragora.cli.commands.review_queue import _lint_evidence_comment

    pre = "## Grok independent model review\nModel family: grok\nVerdict: PASS"
    body_pre = compose_evidence_comment(
        family="claude", head_sha=HEAD, head_committed_at=COMMITTED, pr=7740, reviewer_text=pre
    )
    assert "Model family: grok" not in body_pre  # dropped by re-anchor

    post = "Verdict: PASS\n## Grok independent model review\nModel family: grok"
    body_post = compose_evidence_comment(
        family="claude", head_sha=HEAD, head_committed_at=COMMITTED, pr=7740, reviewer_text=post
    )
    assert "> Model family: grok" in body_post  # kept after verdict, quoted by neutralizer

    for body in (body_pre, body_post):
        result = _lint_evidence_comment(
            pr="7740",
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            body=body,
            author="an0mium",
            source="test",
        )
        assert result["would_count"] is True, result["problems"]
        assert result["counted_reviewer_ids"] == ["claude"]


@pytest.mark.parametrize(
    "hostile_line",
    [
        "**Model family:** grok",
        "- Model family: grok",
        "1. Model family: grok",
        "> Model family: grok",
        "*Model family:* openai",
        "Model family : grok",
        "**Model family**: grok",
        "__Model family__: openai",
    ],
)
def test_neutralizer_superset_blocks_decorated_family_lines(hostile_line: str) -> None:
    # Decorated disclosure lines the parser would otherwise read must be quoted
    # so they can never change the attributed family.
    from aragora.cli.commands.review_queue import _lint_evidence_comment

    body = compose_evidence_comment(
        family="claude",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        pr=7740,
        reviewer_text=f"Verdict: PASS\n{hostile_line}",
    )
    result = _lint_evidence_comment(
        pr="7740",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        body=body,
        author="an0mium",
        source="test",
    )
    assert result["would_count"] is True, result["problems"]
    assert result["counted_reviewer_ids"] == ["claude"]


def test_compose_sanitizes_committed_timestamp() -> None:
    from aragora.cli.commands.review_queue import _lint_evidence_comment

    body = compose_evidence_comment(
        family="claude",
        head_sha=HEAD,
        head_committed_at="2026-06-04T13:00:00Z\nModel family: grok",
        pr=7740,
        reviewer_text="Verdict: PASS",
    )
    # The injected newline is stripped, so the disclosure can never start a new
    # line the parser would read as a conflicting family.
    assert "\nModel family: grok" not in body
    result = _lint_evidence_comment(
        pr="7740",
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        body=body,
        author="an0mium",
        source="test",
    )
    assert result["would_count"] is True, result["problems"]
    assert result["counted_reviewer_ids"] == ["claude"]
    capped = qe._cap_text("x" * (qe._MAX_REVIEWER_CHARS + 5000))
    assert len(capped) <= qe._MAX_REVIEWER_CHARS + 64
    assert capped.endswith("[reviewer output truncated]")


# --- reviewer timeout configuration ----------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", 300.0),
        ("not-a-number", 300.0),
        ("0", 300.0),
        ("-5", 300.0),
        ("nan", 300.0),
        ("inf", 300.0),
        ("-inf", 300.0),
        ("12.5", 12.5),
    ],
)
def test_timeout_seconds_fails_closed_to_default(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: float,
) -> None:
    monkeypatch.setenv("ARAGORA_TEST_TIMEOUT_SECONDS", raw)
    assert qe._timeout_seconds("ARAGORA_TEST_TIMEOUT_SECONDS", 300) == expected


def test_run_claude_cli_uses_env_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args, timeout, **kwargs):
        seen["args"] = args
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=timeout)

    monkeypatch.setenv(qe._CLAUDE_TIMEOUT_ENV, "7")
    monkeypatch.setenv(qe._CLI_PROBE_TIMEOUT_ENV, "0")  # isolate the real-review timeout
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_claude_cli("review prompt")

    argv = seen["args"][0]
    assert argv[:2] == ["claude", "-p"]
    assert "--strict-mcp-config" in argv
    assert "--mcp-config" in argv
    mcp_config = Path(argv[argv.index("--mcp-config") + 1])
    assert mcp_config.name.endswith(".json")
    assert str(mcp_config) != '{"mcpServers":{}}'
    assert seen["timeout"] == 7.0
    assert result == ReviewerResult(
        "claude",
        "",
        False,
        "claude CLI timed out after 7s",
    )


def test_run_claude_cli_uses_file_backed_mcp_config(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(args, **_kwargs):
        config_arg = args[args.index("--mcp-config") + 1]
        config_path = Path(config_arg)
        seen["config_arg"] = config_arg
        seen["exists_during_run"] = config_path.exists()
        seen["config_payload"] = json.loads(config_path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(args, 0, stdout="Verdict: PASS\n", stderr="")

    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_claude_cli("review prompt")

    config_path = Path(str(seen["config_arg"]))
    assert seen["exists_during_run"] is True
    assert seen["config_payload"] == {"mcpServers": {}}
    assert not config_path.exists()
    assert result == ReviewerResult("claude", "Verdict: PASS", True)


def test_claude_reviewer_command_disables_mcp() -> None:
    cmd = qe._claude_reviewer_command(Path("/tmp/empty-mcp.json"))

    assert cmd[:2] == ["claude", "-p"]
    assert "--mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == "/tmp/empty-mcp.json"
    assert "--strict-mcp-config" in cmd


# --- OpenAI reviewer fallback ----------------------------------------------


def test_run_openai_reviewer_uses_api_when_openai_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_api_agent(family: str, prompt: str) -> ReviewerResult:
        calls.append((family, prompt))
        return ReviewerResult(family, "Verdict: PASS from API", True)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(qe, "_run_api_agent", fake_api_agent)

    result = qe._run_openai_reviewer("review prompt")

    assert result == ReviewerResult("openai", "Verdict: PASS from API", True)
    assert calls == [("openai", "review prompt")]


def test_run_openai_reviewer_without_api_key_uses_codex_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        *,
        input: str,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        seen.update(
            {
                "cmd": cmd,
                "input": input,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "check": check,
            }
        )
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text("Verdict: PASS via Codex\n", encoding="utf-8")
        seen["output_path"] = output_path
        return subprocess.CompletedProcess(cmd, 0, stdout="ignored stdout", stderr="")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(qe._CODEX_TIMEOUT_ENV, "11")
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_openai_reviewer("review prompt")

    assert result == ReviewerResult(
        "openai",
        "Verdict: PASS via Codex",
        True,
        harness=qe._CODEX_OPENAI_HARNESS,
    )
    assert seen["cmd"] == [
        "codex",
        "exec",
        "--ignore-user-config",
        "-c",
        qe._CODEX_APPROVAL_POLICY_CONFIG,
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--output-last-message",
        str(seen["output_path"]),
        "--model",
        qe._CODEX_DEFAULT_MODEL,
        "-",
    ]
    assert "--ask-for-approval" not in seen["cmd"]
    assert seen["input"] == "review prompt"
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["timeout"] == 11.0
    assert seen["check"] is False
    assert not Path(seen["output_path"]).exists()


def test_run_openai_reviewer_retries_default_codex_model_selection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    output_paths: list[Path] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        output_paths.append(Path(cmd[cmd.index("--output-last-message") + 1]))
        model = cmd[cmd.index("--model") + 1]
        if model == qe._CODEX_DEFAULT_MODELS[0]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr=f"model {model} is not supported",
            )
        output_paths[-1].write_text("Verdict: PASS after fallback", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(qe._CODEX_MODEL_ENV, raising=False)
    monkeypatch.delenv(qe._CODEX_MODELS_ENV, raising=False)
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_openai_reviewer("review prompt")

    assert result == ReviewerResult(
        "openai",
        "Verdict: PASS after fallback",
        True,
        harness=qe._CODEX_OPENAI_HARNESS,
    )
    assert [call[call.index("--model") + 1] for call in calls] == list(qe._CODEX_DEFAULT_MODELS)
    assert all(not path.exists() for path in output_paths)


def test_run_openai_reviewer_respects_pinned_codex_model_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="",
            stderr="model pinned-model is not supported",
        )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(qe._CODEX_MODEL_ENV, "pinned-model")
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_openai_reviewer("review prompt")

    assert result.ok is False
    assert "codex CLI exit 1: model pinned-model is not supported" in result.error
    assert len(calls) == 1
    assert calls[0][-3:] == ["--model", "pinned-model", "-"]


def test_run_openai_reviewer_passes_optional_codex_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            "Verdict: PASS",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(qe._CODEX_MODEL_ENV, "gpt-5-codex")
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_openai_reviewer("review prompt")

    assert result.ok is True
    assert seen["cmd"][-3:] == ["--model", "gpt-5-codex", "-"]


def test_run_openai_reviewer_codex_failure_never_fabricates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="codex failed")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_openai_reviewer("review prompt")

    assert result.family == "openai"
    assert result.text == ""
    assert result.ok is False
    assert "codex CLI exit 1: codex failed" in result.error
    assert result.harness == ""


@pytest.mark.parametrize(
    ("exc", "expected_error"),
    [
        (
            subprocess.TimeoutExpired(cmd=["codex"], timeout=3),
            "codex CLI timed out after",
        ),
        (FileNotFoundError("missing codex"), "codex CLI not found on PATH"),
        (OSError("disk full"), "OSError: disk full"),
        (subprocess.SubprocessError("bad pipe"), "SubprocessError: bad pipe"),
    ],
)
def test_run_openai_reviewer_cleans_codex_output_file_when_subprocess_raises(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    expected_error: str,
) -> None:
    seen: dict[str, Path] = {}

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text("partial reviewer output", encoding="utf-8")
        seen["output_path"] = output_path
        raise exc

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(qe.subprocess, "run", fake_run)

    result = qe._run_openai_reviewer("review prompt")

    assert result.family == "openai"
    assert result.text == ""
    assert result.ok is False
    assert expected_error in result.error
    assert "output_path" in seen
    assert not seen["output_path"].exists()


# --- default API reviewer cleanup ------------------------------------------


def test_run_api_agent_closes_agent_and_shared_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append(f"generate:{prompt}")
            return "Verdict: PASS"

        async def close(self) -> None:
            events.append("agent_close")

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        events.append(f"create:{family}:{name}:{role}")
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    result = qe._run_api_agent_in_current_process("grok", "review prompt")

    assert result == ReviewerResult("grok", "Verdict: PASS", True)
    assert events == [
        "create:grok:grok_reviewer:critic",
        "generate:review prompt",
        "agent_close",
        "connector_close",
    ]


def test_run_api_agent_closes_resources_after_generate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append("generate")
            raise RuntimeError("model failed")

        async def close(self) -> None:
            events.append("agent_close")

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    result = qe._run_api_agent_in_current_process("grok", "review prompt")

    assert result.ok is False
    assert "RuntimeError: model failed" in result.error
    assert events == ["generate", "agent_close", "connector_close"]


def test_run_api_agent_timeout_terminates_blocked_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(qe, "_REVIEWER_TIMEOUT", 0.05)
    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0.01)
    events: list[str] = []

    class FakeQueue:
        def get(self, timeout: float):
            raise AssertionError("timed-out worker result must not be read")

    class FakeContext:
        def Queue(self, maxsize: int) -> FakeQueue:
            assert maxsize == 1
            return FakeQueue()

    class FakeProcess:
        def start(self) -> None:
            events.append("start")

        def join(self, timeout: float) -> None:
            events.append(f"join:{timeout:.2f}")

        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(qe, "_api_agent_process_context", lambda: FakeContext(), raising=False)
    monkeypatch.setattr(
        qe,
        "_start_api_agent_worker_process",
        lambda ctx, family, prompt, result_queue, model=None: FakeProcess(),
        raising=False,
    )

    result = qe._run_api_agent("grok", "review prompt")

    assert result.ok is False
    assert "timed out" in result.error
    assert events == ["start", "join:0.06", "terminate", "join:5.00", "kill", "join:5.00"]


def test_run_api_agent_parent_timeout_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(qe._REVIEWER_TIMEOUT_ENV, "1200")
    monkeypatch.setattr(qe, "_REVIEWER_TIMEOUT", 300)
    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 7)
    events: list[str] = []

    class FakeQueue:
        def get(self, timeout: float):
            raise AssertionError("timed-out worker result must not be read")

    class FakeContext:
        def Queue(self, maxsize: int) -> FakeQueue:
            assert maxsize == 1
            return FakeQueue()

    class FakeProcess:
        def start(self) -> None:
            events.append("start")

        def join(self, timeout: float) -> None:
            events.append(f"join:{timeout:g}")

        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(qe, "_api_agent_process_context", lambda: FakeContext(), raising=False)
    monkeypatch.setattr(
        qe,
        "_start_api_agent_worker_process",
        lambda ctx, family, prompt, result_queue, model=None: FakeProcess(),
        raising=False,
    )

    result = qe._run_api_agent("grok", "review prompt")

    assert result.ok is False
    assert result.error == "grok reviewer timed out after 1200s"
    assert events == ["start", "join:1207", "terminate", "join:5", "kill", "join:5"]


def test_api_agent_cleanup_does_not_hang_on_stuck_agent_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def close(self) -> None:
            events.append("agent_close_start")
            await asyncio.sleep(3600)

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    from aragora.agents.api_agents import common

    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0.01, raising=False)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    asyncio.run(asyncio.wait_for(qe._close_api_agent_resources(FakeAgent()), timeout=0.05))

    assert events == ["agent_close_start", "connector_close"]


def test_api_agent_cleanup_does_not_hang_on_stuck_shared_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def close(self) -> None:
            events.append("agent_close")

    async def fake_close_shared_connector() -> None:
        events.append("connector_close_start")
        await asyncio.sleep(3600)

    from aragora.agents.api_agents import common

    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0.01, raising=False)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    asyncio.run(asyncio.wait_for(qe._close_api_agent_resources(FakeAgent()), timeout=0.05))

    assert events == ["agent_close", "connector_close_start"]


def test_run_api_agent_closes_shared_connector_after_agent_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append("generate")
            return "Verdict: PASS"

        async def close(self) -> None:
            events.append("agent_close")
            raise RuntimeError("close failed")

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    result = qe._run_api_agent_in_current_process("grok", "review prompt")

    assert result == ReviewerResult("grok", "Verdict: PASS", True)
    assert events == ["generate", "agent_close", "connector_close"]


def test_run_api_agent_closes_shared_connector_without_agent_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append("generate")
            return "Verdict: PASS"

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    result = qe._run_api_agent_in_current_process("grok", "review prompt")

    assert result == ReviewerResult("grok", "Verdict: PASS", True)
    assert events == ["generate", "connector_close"]


def test_run_api_agent_supports_sync_agent_close(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append("generate")
            return "Verdict: PASS"

        def close(self) -> None:
            events.append("agent_close")

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    result = qe._run_api_agent_in_current_process("grok", "review prompt")

    assert result == ReviewerResult("grok", "Verdict: PASS", True)
    assert events == ["generate", "agent_close", "connector_close"]


def test_run_api_agent_keeps_result_when_shared_connector_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append("generate")
            return "Verdict: PASS"

        async def close(self) -> None:
            events.append("agent_close")

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")
        raise RuntimeError("connector failed")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    result = qe._run_api_agent_in_current_process("grok", "review prompt")

    assert result == ReviewerResult("grok", "Verdict: PASS", True)
    assert events == ["generate", "agent_close", "connector_close"]


def test_run_api_agent_allows_consecutive_one_shot_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeAgent:
        async def generate(self, prompt: str) -> str:
            events.append(f"generate:{prompt}")
            return f"Verdict: PASS {prompt}"

        async def close(self) -> None:
            events.append("agent_close")

    def fake_create_agent(family: str, *, name: str, role: str) -> FakeAgent:
        events.append(f"create:{family}")
        return FakeAgent()

    async def fake_close_shared_connector() -> None:
        events.append("connector_close")

    import aragora.agents
    from aragora.agents.api_agents import common

    monkeypatch.setattr(aragora.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(common, "close_shared_connector", fake_close_shared_connector)

    first = qe._run_api_agent_in_current_process("grok", "one")
    second = qe._run_api_agent_in_current_process("grok", "two")

    assert first == ReviewerResult("grok", "Verdict: PASS one", True)
    assert second == ReviewerResult("grok", "Verdict: PASS two", True)
    assert events == [
        "create:grok",
        "generate:one",
        "agent_close",
        "connector_close",
        "create:grok",
        "generate:two",
        "agent_close",
        "connector_close",
    ]


# --- collect_evidence orchestration (fully offline via injected callables) ---


def _fakes(*, tier: int, head: str = HEAD, would_count: bool = True):
    posted: list[tuple[str, str]] = []

    def context_fetcher(repo: str, pr: int) -> dict:
        return {"head_sha": head, "head_committed_at": COMMITTED}

    def tier_fetcher(repo: str, pr: int):
        return tier

    def prompt_builder(repo: str, pr: int, ctx: dict) -> str:
        return "review prompt"

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    def linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
        return {
            "would_count": would_count,
            "counted_reviewer_ids": [body.split()[1].lower()] if would_count else [],
            "problems": [] if would_count else ["no_counted_model_family"],
        }

    def poster(repo: str, pr: int, body: str) -> None:
        posted.append((repo, body))

    return dict(
        context_fetcher=context_fetcher,
        tier_fetcher=tier_fetcher,
        prompt_builder=prompt_builder,
        reviewer_runner=reviewer_runner,
        linter=linter,
        poster=poster,
    ), posted


def test_collect_low_tier_apply_posts_both() -> None:
    fakes, posted = _fakes(tier=1)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "post"
    assert sorted(outcome.posted) == ["claude", "grok"]
    assert len(posted) == 2


def test_collect_runs_reviewers_concurrently() -> None:
    # Deterministic concurrency proof: a 2-party barrier only trips if both
    # reviewers run at once. Serial execution would block the first runner on
    # the barrier forever (until its 5s timeout -> BrokenBarrierError), which my
    # runner would surface as a failure. Concurrent execution lets both pass.
    fakes, _ = _fakes(tier=1)
    barrier = threading.Barrier(2, timeout=5)

    def barrier_runner(family: str, prompt: str) -> ReviewerResult:
        barrier.wait()
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = barrier_runner
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=False, **fakes
    )
    assert {item.family for item in outcome.items} == {"claude", "grok"}
    assert outcome.failures == []


def test_collect_overall_timeout_fails_closed_and_ignores_late_results() -> None:
    fakes, posted = _fakes(tier=0)

    def runner(family: str, prompt: str) -> ReviewerResult:
        if family == "claude":
            return ReviewerResult(family, "Verdict: PASS from claude", True)
        time.sleep(1.5)
        return ReviewerResult(family, "Verdict: PASS from grok", True)

    fakes["reviewer_runner"] = runner
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        overall_timeout_seconds=0.2,
        **fakes,
    )

    assert outcome.orchestration_timeout is True
    assert outcome.timed_out_families == ["grok"]
    assert outcome.action == "prepare"
    assert "reviewer orchestration timeout" in outcome.action_reason
    assert [item.family for item in outcome.items] == ["claude"]
    assert [failure.family for failure in outcome.failures] == ["grok"]
    assert posted == []


def test_collect_overall_timeout_does_not_wait_for_stuck_reviewer() -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("process-supervised timeout regression requires fork context")
    fakes, posted = _fakes(tier=0)

    def runner(family: str, prompt: str) -> ReviewerResult:
        if family == "claude":
            return ReviewerResult(family, "Verdict: PASS from claude", True)
        time.sleep(10)
        return ReviewerResult(family, "Verdict: PASS from grok", True)

    fakes["reviewer_runner"] = runner
    started_at = time.monotonic()
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        overall_timeout_seconds=0.05,
        **fakes,
    )
    elapsed = time.monotonic() - started_at

    assert elapsed < 1.0
    assert outcome.orchestration_timeout is True
    assert outcome.timed_out_families == ["grok"]
    assert outcome.action == "prepare"
    assert posted == []


def test_overall_timeout_reaps_finished_reviewer_before_deadline_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class FinishedProcess:
        pid = 12345

        def is_alive(self) -> bool:
            return False

        def join(self, timeout: float | None = None) -> None:
            return None

    def start_worker(ctx, reviewer_runner, family: str, prompt: str) -> qe._ReviewerWorker:
        result_queue: queue.Queue[ReviewerResult] = queue.Queue(maxsize=1)
        result_queue.put(ReviewerResult(family, f"Verdict: PASS from {family}", True))
        return qe._ReviewerWorker(
            family=family,
            process=FinishedProcess(),
            result_queue=result_queue,
        )

    monkeypatch.setattr(qe, "_reviewer_process_context", lambda: object())
    monkeypatch.setattr(qe, "_start_reviewer_worker", start_worker)
    monkeypatch.setattr(qe, "_close_reviewer_worker", lambda worker: closed.append(worker.family))

    results, timed_out = qe._run_reviewers_with_overall_timeout(
        reviewer_runner=lambda family, prompt: ReviewerResult(family, "", True),
        prompt="review prompt",
        families=["claude"],
        overall_timeout_seconds=0.0,
    )

    assert timed_out == []
    assert results["claude"].ok is True
    assert closed == ["claude"]


def test_reviewer_process_context_avoids_fork_from_threaded_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str | None] = []

    monkeypatch.setattr(qe.threading, "active_count", lambda: 2)
    monkeypatch.setattr(qe.multiprocessing, "get_all_start_methods", lambda: ["fork", "spawn"])

    def fake_get_context(method: str | None = None) -> object:
        requested.append(method)
        return object()

    monkeypatch.setattr(qe.multiprocessing, "get_context", fake_get_context)

    qe._reviewer_process_context()

    assert requested == ["spawn"]


def test_reviewer_process_context_fails_closed_when_only_fork_is_available_in_threaded_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(qe.threading, "active_count", lambda: 2)
    monkeypatch.setattr(qe.multiprocessing, "get_all_start_methods", lambda: ["fork"])

    with pytest.raises(RuntimeError, match="cannot safely fork reviewer workers"):
        qe._reviewer_process_context()


def test_start_reviewer_worker_is_not_daemon_so_api_fallback_can_spawn_children() -> None:
    created: dict[str, object] = {}

    class FakeQueue:
        pass

    class FakeProcess:
        def __init__(self, *, target, args, daemon) -> None:
            created["target"] = target
            created["args"] = args
            created["daemon"] = daemon

        def start(self) -> None:
            created["started"] = True

    class FakeContext:
        def Queue(self, maxsize: int) -> FakeQueue:
            assert maxsize == 1
            return FakeQueue()

        def Process(self, *, target, args, daemon) -> FakeProcess:
            return FakeProcess(target=target, args=args, daemon=daemon)

    worker = qe._start_reviewer_worker(
        FakeContext(),
        lambda family, prompt: ReviewerResult(family, prompt, True),
        "grok",
        "review prompt",
    )

    assert worker.family == "grok"
    assert created["started"] is True
    assert created["daemon"] is False


def test_reviewer_process_worker_creates_posix_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix" or not hasattr(qe.os, "setsid"):
        pytest.skip("process-group isolation is POSIX-only")
    events: list[str] = []

    class FakeQueue:
        def put(self, result: ReviewerResult) -> None:
            events.append(f"put:{result.family}:{result.ok}")

    monkeypatch.setattr(qe.os, "setsid", lambda: events.append("setsid"), raising=False)
    monkeypatch.setattr(
        qe.multiprocessing,
        "current_process",
        lambda: SimpleNamespace(name="ForkProcess-1"),
        raising=False,
    )
    monkeypatch.setattr(
        qe,
        "_run_reviewer_with_infra_retry",
        lambda runner, family, prompt: ReviewerResult(family, "Verdict: PASS", True),
    )

    qe._reviewer_process_worker(
        lambda family, prompt: ReviewerResult(family, prompt, True),
        "grok",
        "review prompt",
        FakeQueue(),
    )

    assert events == ["setsid", "put:grok:True"]


def test_terminate_reviewer_worker_signals_posix_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix" or not hasattr(qe.os, "killpg"):
        pytest.skip("process-group termination is POSIX-only")
    events: list[tuple[str, int, int] | tuple[str, float]] = []

    class FakeQueue:
        def close(self) -> None:
            pass

        def join_thread(self) -> None:
            pass

    class FakeProcess:
        pid = 4242

        def __init__(self) -> None:
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float) -> None:
            events.append(("join", timeout))

        def terminate(self) -> None:
            raise AssertionError("process-group cleanup should not fall back first")

        def kill(self) -> None:
            raise AssertionError("hard kill should not be needed after SIGTERM")

    fake_process = FakeProcess()

    def fake_killpg(pid: int, sig: int) -> None:
        events.append(("killpg", pid, sig))
        fake_process.alive = False

    monkeypatch.setattr(qe.os, "killpg", fake_killpg, raising=False)
    qe._terminate_reviewer_worker(
        qe._ReviewerWorker("grok", fake_process, FakeQueue())  # type: ignore[arg-type]
    )

    assert events == [("killpg", 4242, signal.SIGTERM), ("join", qe._REVIEWER_CLEANUP_TIMEOUT)]


def test_signal_reviewer_process_group_falls_back_when_group_missing_but_process_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix" or not hasattr(qe.os, "killpg"):
        pytest.skip("process-group termination is POSIX-only")

    class FakeProcess:
        pid = 4242

        def is_alive(self) -> bool:
            return True

    def fake_killpg(pid: int, sig: int) -> None:
        raise ProcessLookupError(pid)

    monkeypatch.setattr(qe.os, "killpg", fake_killpg, raising=False)

    assert qe._signal_reviewer_process_group(FakeProcess(), signal.SIGTERM) is False  # type: ignore[arg-type]


def test_read_reviewer_worker_result_waits_briefly_for_queue_feeder() -> None:
    events: list[str] = []

    class FakeQueue:
        def get_nowait(self) -> ReviewerResult:
            events.append("get_nowait")
            raise queue.Empty

        def get(self, timeout: float) -> ReviewerResult:
            events.append(f"get:{timeout}")
            return ReviewerResult("grok", "Verdict: PASS", True)

    result = qe._read_reviewer_worker_result(
        qe._ReviewerWorker("grok", SimpleNamespace(), FakeQueue())  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.family == "grok"
    assert events == ["get_nowait", f"get:{qe._REVIEWER_RESULT_QUEUE_TIMEOUT}"]


def test_collect_preserves_family_order_despite_completion_order() -> None:
    # The first-requested reviewer (claude) finishes last; items must still be
    # ordered by the caller's requested family order, not by completion.
    fakes, _ = _fakes(tier=1)

    def ordered_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "claude":
            time.sleep(0.2)  # ensure claude returns after grok
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = ordered_runner
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=False, **fakes
    )
    assert [item.family for item in outcome.items] == ["claude", "grok"]


def test_collect_records_raising_reviewer_as_failure() -> None:
    # A reviewer that raises is recorded as a failure (it must not abort the run
    # or crash the pool); the other reviewer's evidence is still collected.
    fakes, _ = _fakes(tier=1)

    def maybe_raise(family: str, prompt: str) -> ReviewerResult:
        if family == "grok":
            raise RuntimeError("reviewer boom")
        return ReviewerResult(family, "Verdict: PASS from claude", True)

    fakes["reviewer_runner"] = maybe_raise
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=False, **fakes
    )
    assert [item.family for item in outcome.items] == ["claude"]
    assert [f.family for f in outcome.failures] == ["grok"]
    assert "reviewer boom" in outcome.failures[0].error


def test_collect_times_out_one_hung_reviewer_and_keeps_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes, _ = _fakes(tier=1)
    monkeypatch.setattr(qe, "_REVIEWER_TIMEOUT", 0.02)
    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0.01)
    monkeypatch.setattr(qe, "_reviewer_infra_retries", lambda: 0)

    def maybe_hang(family: str, prompt: str) -> ReviewerResult:
        if family == "grok":
            time.sleep(0.5)
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = maybe_hang
    started_at = time.monotonic()

    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )

    assert time.monotonic() - started_at < 0.4
    assert [item.family for item in outcome.items] == ["claude"]
    assert [failure.family for failure in outcome.failures] == ["grok"]
    assert "timed out" in outcome.failures[0].error
    assert outcome.action == "prepare"
    assert "supportive quorum incomplete" in outcome.action_reason


def test_collect_times_out_all_hung_reviewers(monkeypatch: pytest.MonkeyPatch) -> None:
    fakes, posted = _fakes(tier=1)
    monkeypatch.setattr(qe, "_REVIEWER_TIMEOUT", 0.02)
    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0.01)
    monkeypatch.setattr(qe, "_reviewer_infra_retries", lambda: 0)

    def hanging_runner(family: str, prompt: str) -> ReviewerResult:
        time.sleep(0.5)
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = hanging_runner
    started_at = time.monotonic()

    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )

    assert time.monotonic() - started_at < 0.4
    assert outcome.items == []
    assert [failure.family for failure in outcome.failures] == ["claude", "grok"]
    assert all("timed out" in failure.error for failure in outcome.failures)
    assert outcome.action == "prepare"
    assert outcome.posted == []
    assert posted == []


def test_collect_bounded_reviewer_wait_preserves_successful_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes, _ = _fakes(tier=1)
    monkeypatch.setattr(qe, "_REVIEWER_TIMEOUT", 0.02)
    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0.01)
    monkeypatch.setattr(qe, "_reviewer_infra_retries", lambda: 0)

    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=False, **fakes
    )

    assert [item.family for item in outcome.items] == ["claude", "grok"]
    assert outcome.failures == []
    assert outcome.supportive_families == ["claude", "grok"]


def test_collect_later_worker_wave_gets_full_reviewer_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes, _ = _fakes(tier=1)
    monkeypatch.setattr(qe, "_MAX_REVIEWER_WORKERS", 2)
    monkeypatch.setattr(qe, "_REVIEWER_TIMEOUT", 0.1)
    monkeypatch.setattr(qe, "_REVIEWER_CLEANUP_TIMEOUT", 0)
    monkeypatch.setattr(qe, "_reviewer_infra_retries", lambda: 0)

    def wave_runner(family: str, prompt: str) -> ReviewerResult:
        if family in {"claude", "grok"}:
            time.sleep(0.08)
        if family == "openai":
            time.sleep(0.05)
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = wave_runner

    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok", "openai"],
        author="me",
        apply=False,
        **fakes,
    )

    assert [item.family for item in outcome.items] == ["claude", "grok", "openai"]
    assert outcome.failures == []
    assert outcome.supportive_families == ["claude", "grok", "openai"]


def test_collect_low_tier_apply_triggers_same_pr_quorum_reconciler_after_posts() -> None:
    fakes, posted = _fakes(tier=1)
    calls: list[tuple[str, int, int]] = []

    def quorum_reconciler(repo: str, pr: int) -> dict:
        calls.append((repo, pr, len(posted)))
        return {"should_rerun": True, "run_id": 123, "applied": True}

    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        quorum_reconciler=quorum_reconciler,
        **fakes,
    )

    assert calls == [("o/r", 1, 2)]
    assert outcome.quorum_rerun == {"should_rerun": True, "run_id": 123, "applied": True}


def test_collect_low_tier_apply_prepares_only_when_reviewer_dissents() -> None:
    fakes, posted = _fakes(tier=1)
    calls: list[tuple[str, int]] = []

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "grok":
            return ReviewerResult("grok", "Verdict: CHANGES-REQUESTED\n- [P1] blocker", True)
        return ReviewerResult("claude", "Verdict: PASS\n- no blockers", True)

    def quorum_reconciler(repo: str, pr: int) -> dict:
        calls.append((repo, pr))
        return {"applied": True}

    fakes["reviewer_runner"] = reviewer_runner
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        quorum_reconciler=quorum_reconciler,
        **fakes,
    )

    assert outcome.action == "prepare"
    assert "reviewer dissent" in outcome.action_reason
    assert outcome.dissenting_families == ["grok"]
    assert posted == []
    assert calls == []
    assert outcome.quorum_rerun is None


def test_collect_severity_gated_p2_only_dissent_is_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
    fakes, posted = _fakes(tier=1)

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "grok":
            return ReviewerResult(
                "grok",
                "Verdict: CHANGES-REQUESTED\n- [P2] Add a follow-up smoke test.",
                True,
            )
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = reviewer_runner
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "openai", "grok"],
        author="me",
        apply=True,
        **fakes,
    )

    assert outcome.action == "post"
    assert outcome.dissenting_families == []
    assert sorted(outcome.supportive_families) == ["claude", "openai"]
    assert sorted(outcome.posted) == ["claude", "openai"]
    assert all("changes-requested" not in body.lower() for _repo, body in posted)


def test_collect_severity_gated_finding_free_changes_requested_is_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
    fakes, posted = _fakes(tier=1)

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "grok":
            return ReviewerResult(
                "grok",
                "Verdict: CHANGES-REQUESTED\nNeeds another look before merge.",
                True,
            )
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["reviewer_runner"] = reviewer_runner
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "openai", "grok"],
        author="me",
        apply=True,
        **fakes,
    )

    assert outcome.action == "post"
    assert outcome.dissenting_families == []
    assert sorted(outcome.supportive_families) == ["claude", "openai"]
    assert sorted(outcome.posted) == ["claude", "openai"]
    assert all("changes-requested" not in body.lower() for _repo, body in posted)


def test_collect_preflight_transport_retries_then_fails_closed_without_reviewers() -> None:
    attempts = 0
    reviewer_calls: list[str] = []
    fakes, posted = _fakes(tier=1)

    def flaky_context_fetcher(repo: str, pr: int) -> dict:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("error connecting to api.github.com")

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        reviewer_calls.append(family)
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["context_fetcher"] = flaky_context_fetcher
    fakes["reviewer_runner"] = reviewer_runner

    with pytest.raises(qe.CollectPreflightTransportError) as raised:
        collect_evidence(
            repo="o/r",
            pr=1,
            families=["claude", "grok"],
            author="me",
            apply=True,
            **fakes,
        )

    assert attempts == 2
    assert reviewer_calls == []
    assert posted == []
    payload = raised.value.to_dict()
    assert payload["status"] == "transport_blocked"
    assert payload["transport_blocked"] is True
    assert payload["preserve_no_mutate"] is True
    assert payload["phase"] == "preflight_pr_context"
    assert payload["posted_families"] == []
    assert payload["items"] == []
    assert payload["failures"] == []


def test_collect_preflight_timeout_message_is_transport_error() -> None:
    assert qe._is_preflight_context_transport_error(
        RuntimeError("gh pr view 1 timed out after 30s")
    )


def test_collect_preflight_raw_timeout_exception_is_transport_blocked() -> None:
    attempts = 0

    def timeout_context_fetcher(repo: str, pr: int) -> dict:
        nonlocal attempts
        attempts += 1
        raise subprocess.TimeoutExpired(["gh", "pr", "view", str(pr)], timeout=30)

    with pytest.raises(qe.CollectPreflightTransportError) as raised:
        qe._fetch_preflight_context(
            "o/r",
            1,
            timeout_context_fetcher,
            attempts=2,
            retry_delay_seconds=0,
        )

    assert attempts == 2
    payload = raised.value.to_dict()
    assert payload["status"] == "transport_blocked"
    assert payload["transport_blocked"] is True


def test_collect_preflight_non_github_timeout_message_is_not_transport_error() -> None:
    attempts = 0

    def logic_context_fetcher(repo: str, pr: int) -> dict:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("policy parser timed out after reading an invalid fixture")

    with pytest.raises(RuntimeError, match="policy parser timed out"):
        qe._fetch_preflight_context(
            "o/r",
            1,
            logic_context_fetcher,
            attempts=2,
            retry_delay_seconds=0,
        )

    assert attempts == 1


def test_collect_preflight_transport_retry_can_recover_and_run_reviewers() -> None:
    attempts = 0
    reviewer_calls: list[str] = []
    fakes, posted = _fakes(tier=1)

    def flaky_context_fetcher(repo: str, pr: int) -> dict:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("error connecting to api.github.com")
        return {"head_sha": HEAD, "head_committed_at": COMMITTED}

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        reviewer_calls.append(family)
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    fakes["context_fetcher"] = flaky_context_fetcher
    fakes["reviewer_runner"] = reviewer_runner

    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        **fakes,
    )

    assert attempts >= 2
    assert sorted(reviewer_calls) == ["claude", "grok"]
    assert outcome.action == "post"
    assert sorted(outcome.posted) == ["claude", "grok"]
    assert len(posted) == 2


def test_evidence_item_dissenting_uses_captured_outcome_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
    item = EvidenceItem(
        "grok",
        "Verdict: CHANGES-REQUESTED\n- [P2] advisory follow-up",
        False,
        [],
        [],
        "changes_requested",
    )
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=1,
        action="prepare",
        action_reason="prepared",
        items=[item],
    )
    monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "0")

    assert outcome.items[0].dissenting is False
    assert outcome.dissenting_families == []


def test_collect_low_tier_apply_prepares_when_supportive_quorum_incomplete() -> None:
    # Tiered gate: a lone NON-western-frontier supportive (qwen) does NOT satisfy
    # Tier 1, so apply still prepares-only (no cheap-model-alone settlement).
    fakes, posted = _fakes(tier=1)
    calls: list[tuple[str, int]] = []

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "claude":
            return ReviewerResult("claude", "Verdict: inconclusive\n- unsure", True)
        return ReviewerResult("qwen", "Verdict: PASS\n- no blockers", True)

    def quorum_reconciler(repo: str, pr: int) -> dict:
        calls.append((repo, pr))
        return {"applied": True}

    fakes["reviewer_runner"] = reviewer_runner
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "qwen"],
        author="me",
        apply=True,
        quorum_reconciler=quorum_reconciler,
        **fakes,
    )

    assert outcome.action == "prepare"
    assert "supportive quorum incomplete" in outcome.action_reason
    assert outcome.supportive_families == ["qwen"]
    assert posted == []
    assert calls == []
    assert outcome.quorum_rerun is None


def test_collect_tier1_lone_cheap_signal_is_not_supportive_quorum() -> None:
    # Tiered gate: Tier 1 settles on ONE western-frontier signal. A lone cheap
    # (non-WF) supportive — even though it counts — is NOT a supportive quorum,
    # so a cheap model can never solely authorize a low-tier merge.
    fakes, _posted = _fakes(tier=1)

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "claude":
            return ReviewerResult("claude", "Verdict: CHANGES-REQUESTED\n- [P1] blocker", True)
        return ReviewerResult("qwen", "Verdict: PASS\n- no blockers", True)

    fakes["reviewer_runner"] = reviewer_runner
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "qwen"],
        author="me",
        apply=False,
        **fakes,
    )

    assert outcome.counting_families == ["claude", "qwen"]
    assert outcome.supportive_families == ["qwen"]
    assert outcome.dissenting_families == ["claude"]
    assert outcome.has_supportive_quorum is False


def test_locked_quorum_state_recovers_stale_pid_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state_file = tmp_path / "state.json"
    lock_file = tmp_path / "state.json.lock"
    lock_file.write_text("pid=999999 acquired_at=2026-06-06T00:00:00+00:00\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock_file, (old, old))
    monkeypatch.setattr(qe, "QUORUM_STATE_LOCK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(qe, "QUORUM_STATE_LOCK_POLL_SECONDS", 0.01)

    with qe._locked_quorum_reconcile_state(state_file):
        assert lock_file.exists()

    assert not lock_file.exists()


def test_collect_records_quorum_reconciler_error_after_successful_posts() -> None:
    fakes, posted = _fakes(tier=1)

    def quorum_reconciler(repo: str, pr: int) -> dict:
        raise RuntimeError("rerun surface unavailable")

    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        quorum_reconciler=quorum_reconciler,
        **fakes,
    )

    assert len(posted) == 2
    assert sorted(outcome.posted) == ["claude", "grok"]
    assert outcome.quorum_rerun == {"applied": False, "error": "rerun surface unavailable"}


def test_collect_does_not_reconcile_when_no_evidence_was_posted() -> None:
    fakes, posted = _fakes(tier=1, would_count=False)
    calls: list[tuple[str, int]] = []

    def quorum_reconciler(repo: str, pr: int) -> dict:
        calls.append((repo, pr))
        return {"applied": True}

    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        quorum_reconciler=quorum_reconciler,
        **fakes,
    )

    assert posted == []
    assert calls == []
    assert outcome.quorum_rerun is None


def test_default_quorum_reconciler_holds_lock_through_state_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from scripts import reconcile_merge_quorum

    events: list[str] = []
    state: dict = {}

    @contextmanager
    def fake_lock(path):
        events.append("lock-enter")
        yield
        events.append("lock-exit")

    def load_state(path):
        events.append("load")
        return state

    def evaluate_pr(repo, pr, *, now, state, cooldown_seconds, max_reruns):
        events.append("evaluate")
        assert repo == "o/r"
        assert pr == 1
        assert cooldown_seconds == qe.QUORUM_RERUN_COOLDOWN_SECONDS
        assert max_reruns == qe.QUORUM_RERUN_MAX_PER_HEAD
        decision = SimpleNamespace(
            should_rerun=True,
            reason="stale-success-after-new-evidence",
            run_id=123,
            next_prompt=None,
        )
        quorum_run = SimpleNamespace(run_id=123, head_sha="abc123")
        return decision, quorum_run

    def execute_rerun(repo, run_id):
        events.append("execute")
        assert (repo, run_id) == ("o/r", 123)
        return True

    def save_state(path, next_state):
        events.append("save")
        assert next_state["abc123"]["count"] == 1

    monkeypatch.setattr(qe, "_locked_quorum_reconcile_state", fake_lock)
    monkeypatch.setattr(reconcile_merge_quorum, "DEFAULT_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(reconcile_merge_quorum, "_load_state", load_state)
    monkeypatch.setattr(reconcile_merge_quorum, "evaluate_pr", evaluate_pr)
    monkeypatch.setattr(reconcile_merge_quorum, "execute_rerun", execute_rerun)
    monkeypatch.setattr(reconcile_merge_quorum, "_save_state", save_state)

    record = qe.default_quorum_reconciler("o/r", 1)

    assert record == {
        "should_rerun": True,
        "reason": "stale-success-after-new-evidence",
        "run_id": 123,
        "applied": True,
    }
    assert events == ["lock-enter", "load", "evaluate", "execute", "save", "lock-exit"]


def test_default_quorum_reconciler_rechecks_rerun_cap_under_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from scripts import reconcile_merge_quorum

    state = {
        "abc123": {
            "count": qe.QUORUM_RERUN_MAX_PER_HEAD,
            "last_rerun_at": None,
        }
    }

    @contextmanager
    def fake_lock(path):
        yield

    def evaluate_pr(repo, pr, *, now, state, cooldown_seconds, max_reruns):
        decision = SimpleNamespace(
            should_rerun=True,
            reason="stale-success-after-new-evidence",
            run_id=123,
            next_prompt=None,
        )
        quorum_run = SimpleNamespace(run_id=123, head_sha="abc123")
        return decision, quorum_run

    def execute_rerun(repo, run_id):
        raise AssertionError("rerun must not execute after locked count reaches the cap")

    monkeypatch.setattr(qe, "_locked_quorum_reconcile_state", fake_lock)
    monkeypatch.setattr(reconcile_merge_quorum, "DEFAULT_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(reconcile_merge_quorum, "_load_state", lambda path: state)
    monkeypatch.setattr(reconcile_merge_quorum, "evaluate_pr", evaluate_pr)
    monkeypatch.setattr(reconcile_merge_quorum, "execute_rerun", execute_rerun)

    record = qe.default_quorum_reconciler("o/r", 1)

    assert record == {
        "should_rerun": False,
        "reason": "max_reruns_reached_in_locked_state",
        "run_id": 123,
        "applied": False,
    }


def test_collect_high_tier_apply_never_posts() -> None:
    fakes, posted = _fakes(tier=4)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "prepare"
    assert outcome.posted == []
    assert posted == []
    # Evidence is still composed + validated for the operator.
    assert sorted(outcome.counting_families) == ["claude", "grok"]


def test_collect_dry_run_prepares_without_posting() -> None:
    fakes, posted = _fakes(tier=1)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=False, **fakes
    )
    assert outcome.action == "prepare"
    assert posted == []
    assert sorted(outcome.counting_families) == ["claude", "grok"]


def test_collect_carries_reviewer_harness_into_comment() -> None:
    fakes, posted = _fakes(tier=1)

    def harness_runner(family: str, prompt: str) -> ReviewerResult:
        return ReviewerResult(
            family,
            "Verdict: PASS via harness",
            True,
            harness=qe._CODEX_OPENAI_HARNESS,
        )

    def harness_linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
        assert qe._CODEX_OPENAI_HARNESS in body
        return {
            "would_count": True,
            "counted_reviewer_ids": ["openai"],
            "problems": [],
        }

    fakes["reviewer_runner"] = harness_runner
    fakes["linter"] = harness_linter

    outcome = collect_evidence(
        repo="o/r", pr=1, families=["openai"], author="me", apply=False, **fakes
    )

    assert outcome.action == "prepare"
    assert posted == []
    assert outcome.counting_families == ["openai"]
    assert qe._CODEX_OPENAI_HARNESS in outcome.items[0].body


def test_collect_never_fabricates_on_reviewer_failure() -> None:
    # A failed reviewer's vote is never fabricated. With the western-frontier
    # reviewer (claude) down and only a cheap survivor (qwen), Tier 1 stays
    # unsatisfied -> prepare, no post.
    fakes, posted = _fakes(tier=1)

    def failing_runner(family: str, prompt: str) -> ReviewerResult:
        if family == "claude":
            return ReviewerResult("claude", "", False, "timeout")
        return ReviewerResult(family, "Verdict: PASS from qwen", True)

    fakes["reviewer_runner"] = failing_runner
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "qwen"], author="me", apply=True, **fakes
    )
    assert [f.family for f in outcome.failures] == ["claude"]
    assert outcome.action == "prepare"
    assert "supportive quorum incomplete" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []


def test_collect_does_not_post_uncountable_evidence() -> None:
    fakes, posted = _fakes(tier=1, would_count=False)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "prepare"
    assert "supportive quorum incomplete" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []
    assert all(not item.would_count for item in outcome.items)


def test_collect_rejects_unsupported_family() -> None:
    # Survivor is a cheap (non-WF) family, so even after rejecting the bogus
    # family the Tier-1 western-frontier bar is unmet -> prepare.
    fakes, posted = _fakes(tier=1)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["qwen", "bogus"], author="me", apply=True, **fakes
    )
    assert "bogus" in [f.family for f in outcome.failures]
    assert outcome.action == "prepare"
    assert "supportive quorum incomplete" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []
    assert "bogus" not in outcome.counting_families


def test_collect_records_post_errors_without_losing_others() -> None:
    fakes, _ = _fakes(tier=1)

    def flaky_poster(repo: str, pr: int, body: str) -> None:
        if "Grok" in body:
            raise RuntimeError("gh rejected comment")

    fakes["poster"] = flaky_poster
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.posted == ["claude"]
    assert any("grok" in e for e in outcome.post_errors)


def test_collect_recheck_exception_prepares_without_posting() -> None:
    fakes, posted = _fakes(tier=1)
    calls = {"n": 0}

    def flaky_context(repo: str, pr: int) -> dict:
        calls["n"] += 1
        if calls["n"] >= 2:  # first call ok, recheck blows up
            raise RuntimeError("transient gh error")
        return {"head_sha": HEAD, "head_committed_at": COMMITTED}

    fakes["context_fetcher"] = flaky_context
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "prepare"
    assert "re-verify" in outcome.action_reason
    assert posted == []


def test_collect_skips_post_when_head_moves_before_posting() -> None:
    fakes, posted = _fakes(tier=1)
    heads = iter([HEAD, "0" * 40])  # initial fetch, then recheck = moved head

    def moving_context(repo: str, pr: int) -> dict:
        return {"head_sha": next(heads), "head_committed_at": COMMITTED}

    fakes["context_fetcher"] = moving_context
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "prepare"
    assert "changed before posting" in outcome.action_reason
    assert posted == []


def test_collect_skips_post_when_tier_promoted_before_posting() -> None:
    fakes, posted = _fakes(tier=1)
    tiers = iter([1, 4])  # initial low, recheck promoted to settlement tier

    def promoting_tier(repo: str, pr: int) -> int:
        return next(tiers)

    fakes["tier_fetcher"] = promoting_tier
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "prepare"
    assert posted == []


def test_collect_dedupes_families() -> None:
    fakes, _ = _fakes(tier=4)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "Claude", "grok"], author="me", apply=False, **fakes
    )
    assert [item.family for item in outcome.items] == ["claude", "grok"]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Codex", "openai"),
        ("codex", "openai"),
        ("gpt", "openai"),
        ("GPT-5", "openai"),
        ("chatgpt", "openai"),
        ("openai", "openai"),
        (" Grok ", "grok"),
        ("Claude", "claude"),
        ("gemini", "gemini"),
    ],
)
def test_canonical_family_collapses_aliases(name: str, expected: str) -> None:
    from aragora.swarm.quorum_evidence import canonical_family

    assert canonical_family(name) == expected


def test_collect_aliases_codex_and_gpt_to_single_openai_family() -> None:
    # codex/gpt are the OpenAI family's CLI/product names. They must collapse to
    # ONE canonical family so a single provider can't satisfy the 2-family quorum.
    fakes, _ = _fakes(tier=4)
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["openai", "codex", "gpt"],
        author="me",
        apply=False,
        **fakes,
    )
    assert [item.family for item in outcome.items] == ["openai"]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Verdict: PASS", "pass"),
        ("**Verdict: PASS**", "pass"),
        ("## Verdict: CHANGES-REQUESTED", "changes_requested"),
        (
            "Reviewing the diff...\n**Verdict: CHANGES-REQUESTED**\n- **[P2]** x",
            "changes_requested",
        ),
        ("intro preamble line\nVerdict: PASS\n- note", "pass"),
        ("`Verdict: pass`", "pass"),
        ("1. Verdict: PASS", "pass"),
        ("no verdict at all here", "unknown"),
    ],
)
def test_reviewer_verdict_tolerates_markdown_and_preamble(body: str, expected: str) -> None:
    from aragora.swarm.quorum_evidence import _reviewer_verdict

    assert _reviewer_verdict(body) == expected


def test_evidence_item_from_dict_canonicalizes_alias_family() -> None:
    # A prepared artifact labeled with an alias must deserialize to the canonical
    # family so apply/replay counts it (lint discloses the canonical family).
    from aragora.swarm.quorum_evidence import _evidence_item_from_dict

    item = _evidence_item_from_dict(
        {"family": "Codex", "body": "Verdict: PASS\nbody", "would_count": True}
    )
    assert item.family == "openai"


# --- OpenRouter failure-only fallback ---------------------------------------


def test_openrouter_reviewer_disabled_without_optin_flag(monkeypatch) -> None:
    # Key present but the opt-in flag is NOT set: must stay disabled (no silent
    # third-party egress just because a key happens to be configured).
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("ARAGORA_ENABLE_OPENROUTER_REVIEWER_FALLBACK", raising=False)
    result = q._run_openrouter_reviewer("grok", "prompt")
    assert not result.ok
    assert "disabled" in result.error


def test_openrouter_reviewer_disabled_without_key(monkeypatch) -> None:
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setenv("ARAGORA_ENABLE_OPENROUTER_REVIEWER_FALLBACK", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = q._run_openrouter_reviewer("grok", "prompt")
    assert not result.ok
    assert "disabled" in result.error


def test_openrouter_reviewer_rejects_unmapped_family(monkeypatch) -> None:
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setenv("ARAGORA_ENABLE_OPENROUTER_REVIEWER_FALLBACK", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    # mistral is a recognized family but has no OpenRouter slug mapped (unlike deepseek).
    result = q._run_openrouter_reviewer("mistral", "prompt")
    assert not result.ok
    assert "no OpenRouter model" in result.error


def test_openrouter_reviewer_model_env_override(monkeypatch) -> None:
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setenv("ARAGORA_OPENROUTER_REVIEWER_MODELS", '{"grok": "x-ai/grok-custom"}')
    assert q._openrouter_reviewer_model("grok") == "x-ai/grok-custom"
    # Unspecified families fall back to the built-in (verified) map.
    assert q._openrouter_reviewer_model("openai") == "openai/gpt-5-pro"


def test_default_runner_falls_back_to_openrouter_on_infra_failure(monkeypatch) -> None:
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setattr(
        q, "_run_grok_reviewer", lambda _p: q.ReviewerResult("grok", "", False, "cli down")
    )
    monkeypatch.setattr(
        q,
        "_run_openrouter_reviewer",
        lambda fam, _p: q.ReviewerResult(fam, "Verdict: PASS via OpenRouter", True, harness="or"),
    )
    result = q.default_reviewer_runner("grok", "prompt")
    assert result.ok
    assert result.family == "grok"  # family identity preserved across transport
    assert "OpenRouter" in result.text


def test_default_runner_skips_openrouter_when_primary_ok(monkeypatch) -> None:
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setattr(
        q, "_run_grok_reviewer", lambda _p: q.ReviewerResult("grok", "Verdict: PASS", True)
    )
    called = {"openrouter": False}

    def _or(fam, _p):
        called["openrouter"] = True
        return q.ReviewerResult(fam, "", True)

    monkeypatch.setattr(q, "_run_openrouter_reviewer", _or)
    result = q.default_reviewer_runner("grok", "prompt")
    assert result.ok and called["openrouter"] is False


def test_openrouter_fallback_routes_alias_to_canonical_family(monkeypatch) -> None:
    from aragora.swarm import quorum_evidence as q

    monkeypatch.setattr(
        q, "_run_openai_reviewer", lambda _p: q.ReviewerResult("openai", "", False, "codex quota")
    )
    monkeypatch.setattr(
        q, "_run_openrouter_reviewer", lambda fam, _p: q.ReviewerResult(fam, "Verdict: PASS", True)
    )
    # "codex" is an alias of openai; the fallback must review as the openai family.
    result = q.default_reviewer_runner("codex", "prompt")
    assert result.ok and result.family == "openai"


def test_deepseek_routes_openrouter_direct(monkeypatch) -> None:
    # DeepSeek has no subscription CLI: it must review OpenRouter-direct (primary),
    # NOT via _run_api_agent, so a cheap distinct family can join the quorum.
    from aragora.swarm import quorum_evidence as q

    called = {"or": None, "api": False}

    def _or(fam, _p):
        called["or"] = fam
        return q.ReviewerResult(fam, "Verdict: PASS via OpenRouter", True, harness="or")

    def _api(fam, _p, model=None):
        called["api"] = True
        return q.ReviewerResult(fam, "", False, "should not be called")

    monkeypatch.setattr(q, "_run_openrouter_reviewer", _or)
    monkeypatch.setattr(q, "_run_api_agent", _api)
    result = q.default_reviewer_runner("deepseek", "prompt")
    assert result.ok and result.family == "deepseek"
    assert called["or"] == "deepseek" and called["api"] is False


def test_deepseek_is_openrouter_direct_with_mapped_model() -> None:
    from aragora.swarm import quorum_evidence as q

    assert "deepseek" in q._OPENROUTER_DIRECT_FAMILIES
    assert q._openrouter_reviewer_model("deepseek")  # a slug is mapped
    assert "deepseek" in q.FAMILY_PROVIDERS  # already a recognized counting family


def test_collect_missing_head_raises() -> None:
    fakes, _ = _fakes(tier=1, head="")
    with pytest.raises(ValueError):
        collect_evidence(repo="o/r", pr=1, families=["claude"], author="me", apply=True, **fakes)


def _prepared_body(family: str, verdict: str = "PASS") -> str:
    return f"Verdict: {verdict}\n\n{family} body\n"


def _prepared_outcome_file(
    tmp_path,
    *,
    items: list[EvidenceItem] | None = None,
    adjudication: dict | None = None,
) -> Path:
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=1,
        action="prepare",
        action_reason="dry-run; re-run with --apply to post",
        items=items
        or [
            EvidenceItem("claude", _prepared_body("claude"), True, ["claude"], [], "pass"),
            EvidenceItem("grok", _prepared_body("grok"), True, ["grok"], [], "pass"),
        ],
        adjudication=adjudication,
    )
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps(outcome.to_dict()), encoding="utf-8")
    return path


def test_apply_prepared_evidence_posts_without_rerunning_reviewers(tmp_path) -> None:
    prepared = _prepared_outcome_file(tmp_path)
    posted: list[tuple[str, str]] = []

    def context_fetcher(repo: str, pr: int) -> dict:
        return {"head_sha": HEAD, "head_committed_at": COMMITTED}

    def tier_fetcher(repo: str, pr: int):
        return 1

    def linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
        family = "claude" if "claude body" in body else "grok"
        return {
            "would_count": True,
            "counted_reviewer_ids": [family],
            "problems": [],
        }

    def poster(repo: str, pr: int, body: str) -> None:
        posted.append((repo, body))

    outcome = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        families=["claude", "grok"],
        context_fetcher=context_fetcher,
        tier_fetcher=tier_fetcher,
        linter=linter,
        poster=poster,
    )

    assert outcome.action == "post"
    assert "without reviewer regeneration" in outcome.action_reason
    assert outcome.posted == ["claude", "grok"]
    assert posted == [("o/r", _prepared_body("claude")), ("o/r", _prepared_body("grok"))]


def test_apply_prepared_evidence_recomputes_exact_head_adjudication(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_REVIEW_ADJUDICATOR", "1")
    stale_adjudication = {"kind": "review_adjudication.v1", "verdict": "adjudicated_settle"}
    prepared = _prepared_outcome_file(
        tmp_path,
        items=[
            EvidenceItem("claude", _prepared_body("claude"), True, ["claude"], [], "pass"),
            EvidenceItem(
                "openai",
                "Verdict: CHANGES-REQUESTED\n"
                "- [P1] aragora/swarm/quorum_evidence.py:2679 preserves stale "
                "prepared adjudication after fresh lint rejects the reviewer.",
                False,
                [],
                [],
                "changes_requested",
            ),
        ],
        adjudication=stale_adjudication,
    )
    outcome = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        families=["claude", "openai"],
        context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda repo, pr: 1,
        linter=lambda *args, **kwargs: (
            {"would_count": True, "counted_reviewer_ids": ["claude"], "problems": []}
            if "claude body" in args[4]
            else {"would_count": False, "counted_reviewer_ids": [], "problems": []}
        ),
        poster=lambda repo, pr, body: None,
    )

    assert outcome.action == "prepare"
    assert outcome.supportive_families == ["claude"]
    assert outcome.dissenting_families == ["openai"]
    assert outcome.adjudication is not None
    assert outcome.adjudication["verdict"] == "adjudicated_block"
    assert outcome.adjudication["verdict"] != stale_adjudication["verdict"]
    assert outcome.adjudication["blocking_findings"]


def test_collect_outcome_tiered_gate_roundtrips() -> None:
    # The gate regime an artifact was prepared under must survive serialization so
    # the settlement bar cannot silently change between prepare and apply (#8507 P1).
    for gate in (True, False):
        outcome = CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=1,
            action="prepare",
            action_reason="x",
            tiered_gate=gate,
        )
        assert outcome.to_dict()["tiered_gate"] is gate
        assert qe.collect_outcome_from_dict(outcome.to_dict()).tiered_gate is gate


def test_collect_outcome_missing_tiered_gate_fails_closed(monkeypatch) -> None:
    # Legacy prepared artifacts predate the serialized gate regime. Treat them as
    # strict-gate artifacts rather than inheriting a relaxed live environment.
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=1,
        action="prepare",
        action_reason="legacy",
        items=[EvidenceItem("claude", _prepared_body("claude"), True, ["claude"], [], "pass")],
        tiered_gate=True,
    )
    data = outcome.to_dict()
    data.pop("tiered_gate")

    rehydrated = qe.collect_outcome_from_dict(data)

    assert rehydrated.tiered_gate is False
    assert rehydrated.has_supportive_quorum is False


def _apply_single_wf(path, monkeypatch, *, flag: str, posted: list) -> "qe.CollectOutcome":
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", flag)
    return qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=path,
        author="me",
        apply=True,
        families=["claude"],
        context_fetcher=lambda r, p: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda r, p: 1,
        linter=lambda *a, **k: {
            "would_count": True,
            "counted_reviewer_ids": ["claude"],
            "problems": [],
        },
        poster=lambda r, p, b: posted.append(b),
    )


def _single_wf_artifact(tmp_path, *, tiered_gate: bool):
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=1,
        action="prepare",
        action_reason="prepared",
        items=[EvidenceItem("claude", _prepared_body("claude"), True, ["claude"], [], "pass")],
        tiered_gate=tiered_gate,
    )
    path = tmp_path / f"prepared_{tiered_gate}.json"
    path.write_text(json.dumps(outcome.to_dict()), encoding="utf-8")
    return path


def test_apply_strict_artifact_not_relaxed_by_live_flag(tmp_path, monkeypatch) -> None:
    # Artifact prepared under the STRICT gate (tiered_gate=False) with a lone
    # western-frontier signal. Flipping the relaxing flag ON between prepare and apply
    # must NOT make it postable: apply-time evaluates under min(prepared, live) =
    # strict, so Tier 1 still needs two families. It degrades to "prepare" — never a
    # hard error, so there is no inconsistent-authority / DoS window (#8507 grok+claude P1).
    path = _single_wf_artifact(tmp_path, tiered_gate=False)
    posted: list = []
    outcome = _apply_single_wf(path, monkeypatch, flag="1", posted=posted)
    assert outcome.action == "prepare"
    assert outcome.tiered_gate is False  # effective regime = strict (min of False, True)
    assert "quorum incomplete" in outcome.action_reason
    assert posted == []


def test_apply_relaxed_artifact_restricted_when_operator_reverts_flag(
    tmp_path, monkeypatch
) -> None:
    # A relaxed-prepared artifact (tiered_gate=True, lone WF signal) is re-evaluated
    # under STRICT rules if the operator later turns the relaxation OFF — the flag is
    # the operator's revocable approval point. min(True, False) = strict → Tier 1
    # needs two families → degrades to prepare, lone signal not posted (#8507 claude P1).
    path = _single_wf_artifact(tmp_path, tiered_gate=True)
    posted: list = []
    outcome = _apply_single_wf(path, monkeypatch, flag="0", posted=posted)
    assert outcome.action == "prepare"
    assert outcome.tiered_gate is False  # effective regime = strict (min of True, False)
    assert posted == []


def test_apply_relaxed_artifact_posts_when_both_regimes_relaxed(tmp_path, monkeypatch) -> None:
    # When BOTH the prepare-time and live regimes permit relaxation, a single
    # western-frontier signal settles Tier 1 and is posted (min(True, True) = relaxed).
    path = _single_wf_artifact(tmp_path, tiered_gate=True)
    posted: list = []
    outcome = _apply_single_wf(path, monkeypatch, flag="1", posted=posted)
    assert outcome.action == "post"
    assert outcome.tiered_gate is True
    assert posted == [_prepared_body("claude")]


def test_apply_prepared_evidence_rederives_verdict_from_body(tmp_path) -> None:
    prepared = _prepared_outcome_file(
        tmp_path,
        items=[
            EvidenceItem(
                "claude",
                _prepared_body("claude", "CHANGES-REQUESTED"),
                True,
                ["claude"],
                [],
                "pass",
            ),
            EvidenceItem("grok", _prepared_body("grok"), True, ["grok"], [], "pass"),
        ],
    )
    posted: list[tuple[str, str]] = []

    def linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
        family = "claude" if "claude body" in body else "grok"
        return {
            "would_count": True,
            "counted_reviewer_ids": [family],
            "problems": [],
        }

    outcome = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        families=["claude", "grok"],
        context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda repo, pr: 1,
        linter=linter,
        poster=lambda repo, pr, body: posted.append((repo, body)),
    )

    assert outcome.action == "prepare"
    assert outcome.dissenting_families == ["claude"]
    assert "reviewer dissent present" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []


def test_apply_prepared_evidence_uses_fresh_lint_counting(tmp_path) -> None:
    prepared = _prepared_outcome_file(tmp_path)
    posted: list[tuple[str, str]] = []

    outcome = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        families=["claude", "grok"],
        context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda repo, pr: 1,
        linter=lambda *args, **kwargs: {
            "would_count": False,
            "counted_reviewer_ids": [],
            "problems": ["fresh lint rejected prepared comment"],
        },
        poster=lambda repo, pr, body: posted.append((repo, body)),
    )

    assert outcome.action == "prepare"
    # Tier 1: the bar is one western-frontier signal, not "2 distinct families",
    # so the reason names the WF requirement rather than a misleading "(0/2)".
    assert "supportive quorum incomplete" in outcome.action_reason
    assert "western-frontier" in outcome.action_reason
    assert "/2" not in outcome.action_reason
    assert outcome.supportive_families == []
    assert outcome.posted == []
    assert posted == []


def test_apply_prepared_evidence_requires_lint_identity_match(tmp_path) -> None:
    # A prepared grok item whose fresh lint resolves to a different family
    # (openai) is de-counted on identity mismatch. The matching survivor here is
    # a cheap (non-WF) family so Tier 1 stays unsatisfied -> prepare.
    prepared = _prepared_outcome_file(
        tmp_path,
        items=[
            EvidenceItem("qwen", _prepared_body("qwen"), True, ["qwen"], [], "pass"),
            EvidenceItem("grok", _prepared_body("grok"), True, ["grok"], [], "pass"),
        ],
    )
    posted: list[tuple[str, str]] = []

    def linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
        family = "qwen" if "qwen body" in body else "grok"
        counted = ["qwen"] if family == "qwen" else ["openai"]
        return {
            "would_count": True,
            "counted_reviewer_ids": counted,
            "problems": [],
        }

    outcome = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        families=["qwen", "grok"],
        context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda repo, pr: 1,
        linter=linter,
        poster=lambda repo, pr, body: posted.append((repo, body)),
    )

    grok_item = next(item for item in outcome.items if item.family == "grok")
    assert outcome.action == "prepare"
    # Lone surviving supportive is cheap (qwen, non-WF) at Tier 1 -> the reason
    # names the western-frontier requirement, not a misleading "(1/2)".
    assert "western-frontier" in outcome.action_reason
    assert outcome.supportive_families == ["qwen"]
    assert not grok_item.would_count
    assert (
        "fresh lint counted reviewer ids do not include prepared family: grok" in grok_item.problems
    )
    assert outcome.posted == []
    assert posted == []


def test_apply_prepared_evidence_rejects_unsupported_family(tmp_path) -> None:
    prepared = _prepared_outcome_file(
        tmp_path,
        items=[
            EvidenceItem("claude", "claude body", True, ["claude"], [], "pass"),
            EvidenceItem("factory", "factory body", True, ["factory"], [], "pass"),
        ],
    )

    with pytest.raises(ValueError, match="unsupported reviewer family"):
        qe.apply_prepared_evidence(
            repo="o/r",
            pr=1,
            prepared_json=prepared,
            author="me",
            apply=True,
            families=["claude", "factory"],
            context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
            tier_fetcher=lambda repo, pr: 1,
            linter=lambda *args, **kwargs: {
                "would_count": True,
                "counted_reviewer_ids": ["claude"],
                "problems": [],
            },
            poster=lambda repo, pr, body: None,
        )


def test_apply_prepared_evidence_rejects_duplicate_family(tmp_path) -> None:
    prepared = _prepared_outcome_file(
        tmp_path,
        items=[
            EvidenceItem("claude", "claude body one", True, ["claude"], [], "pass"),
            EvidenceItem("claude", "claude body two", True, ["claude"], [], "pass"),
        ],
    )

    with pytest.raises(ValueError, match="duplicate reviewer family"):
        qe.apply_prepared_evidence(
            repo="o/r",
            pr=1,
            prepared_json=prepared,
            author="me",
            apply=True,
            families=["claude"],
            context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
            tier_fetcher=lambda repo, pr: 1,
            linter=lambda *args, **kwargs: {
                "would_count": True,
                "counted_reviewer_ids": ["claude"],
                "problems": [],
            },
            poster=lambda repo, pr, body: None,
        )


def test_apply_prepared_evidence_honors_requested_family_allowlist(tmp_path) -> None:
    prepared = _prepared_outcome_file(
        tmp_path,
        items=[
            EvidenceItem("openai", "openai body", True, ["openai"], [], "pass"),
            EvidenceItem("grok", "grok body", True, ["grok"], [], "pass"),
        ],
    )

    with pytest.raises(ValueError, match="not in requested reviewer allowlist"):
        qe.apply_prepared_evidence(
            repo="o/r",
            pr=1,
            prepared_json=prepared,
            author="me",
            apply=True,
            families=["claude", "grok"],
            context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
            tier_fetcher=lambda repo, pr: 1,
            linter=lambda *args, **kwargs: {
                "would_count": True,
                "counted_reviewer_ids": ["openai"],
                "problems": [],
            },
            poster=lambda repo, pr, body: None,
        )


def test_apply_prepared_evidence_refuses_stale_head(tmp_path) -> None:
    prepared = _prepared_outcome_file(
        tmp_path,
        adjudication={"kind": "review_adjudication.v1", "verdict": "adjudicated_settle"},
    )
    posted: list[tuple[str, str]] = []

    def context_fetcher(repo: str, pr: int) -> dict:
        return {"head_sha": "different-head", "head_committed_at": COMMITTED}

    outcome = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        context_fetcher=context_fetcher,
        tier_fetcher=lambda repo, pr: 1,
        linter=lambda *args, **kwargs: {
            "would_count": True,
            "counted_reviewer_ids": ["claude"],
            "problems": [],
        },
        poster=lambda repo, pr, body: posted.append((repo, body)),
    )

    assert outcome.action == "prepare"
    assert "prepared head" in outcome.action_reason
    assert outcome.adjudication is None
    assert "adjudication" not in outcome.to_dict()
    assert outcome.posted == []
    assert posted == []


# --- run_collect_cli (monkeypatched orchestrator) ---------------------------


def test_run_collect_cli_exit_code_quorum_met(monkeypatch, capsys) -> None:
    def fake_collect(**kwargs) -> CollectOutcome:
        return CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=1,
            action="post",
            action_reason="ok",
            items=[
                EvidenceItem("claude", "body", True, ["claude"], [], "pass"),
                EvidenceItem("grok", "body", True, ["grok"], [], "pass"),
            ],
            posted=["claude", "grok"],
        )

    monkeypatch.setattr(qe, "collect_evidence", fake_collect)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r", pr=1, families=None, author=None, apply=True, json_output=True
    )
    assert rc == 0
    assert "collect_evidence" in capsys.readouterr().out


def test_run_collect_cli_scopes_timeout_env_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv(qe._CLAUDE_TIMEOUT_ENV, "111")
    monkeypatch.delenv(qe._CODEX_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(qe._REVIEWER_TIMEOUT_ENV, raising=False)

    def fake_collect(**kwargs) -> CollectOutcome:
        captured.update(kwargs)
        captured["claude_timeout"] = qe.os.environ.get(qe._CLAUDE_TIMEOUT_ENV)
        captured["codex_timeout"] = qe.os.environ.get(qe._CODEX_TIMEOUT_ENV)
        captured["reviewer_timeout"] = qe.os.environ.get(qe._REVIEWER_TIMEOUT_ENV)
        return CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=1,
            action="prepare",
            action_reason="dry run",
            items=[
                EvidenceItem("claude", "body", True, ["claude"], [], "pass"),
                EvidenceItem("grok", "body", True, ["grok"], [], "pass"),
            ],
        )

    monkeypatch.setattr(qe, "collect_evidence", fake_collect)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author=None,
        apply=False,
        json_output=False,
        reviewer_timeout_seconds=90,
        overall_timeout_seconds=150,
    )

    assert rc == 0
    assert captured["overall_timeout_seconds"] == 150.0
    assert captured["claude_timeout"] == "90"
    assert captured["codex_timeout"] == "90"
    assert captured["reviewer_timeout"] == "90"
    assert qe.os.environ.get(qe._CLAUDE_TIMEOUT_ENV) == "111"
    assert qe.os.environ.get(qe._CODEX_TIMEOUT_ENV) is None
    assert qe.os.environ.get(qe._REVIEWER_TIMEOUT_ENV) is None


def test_run_collect_cli_prepared_json_skips_collect_evidence(monkeypatch, tmp_path) -> None:
    prepared = _prepared_outcome_file(tmp_path)
    seen: dict[str, object] = {}

    def boom_collect(**kwargs):
        raise AssertionError("collect_evidence should not run for prepared_json")

    def fake_apply_prepared_evidence(**kwargs) -> CollectOutcome:
        seen.update(kwargs)
        return CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=1,
            action="post",
            action_reason="prepared exact-head evidence artifact",
            items=[
                EvidenceItem("claude", "body", True, ["claude"], [], "pass"),
                EvidenceItem("grok", "body", True, ["grok"], [], "pass"),
            ],
            posted=["claude", "grok"],
        )

    monkeypatch.setattr(qe, "collect_evidence", boom_collect)
    monkeypatch.setattr(qe, "apply_prepared_evidence", fake_apply_prepared_evidence)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")

    rc = qe.run_collect_cli(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author=None,
        apply=True,
        json_output=True,
        prepared_json=prepared,
    )

    assert rc == 0
    assert seen["prepared_json"] == prepared
    assert seen["apply"] is True
    assert seen["families"] == ("claude", "grok")


def test_run_collect_cli_exit_code_quorum_incomplete(monkeypatch) -> None:
    def fake_collect(**kwargs) -> CollectOutcome:
        return CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=4,
            action="prepare",
            action_reason="settlement",
            items=[EvidenceItem("claude", "body", True, ["claude"], [])],
        )

    monkeypatch.setattr(qe, "collect_evidence", fake_collect)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r", pr=1, families=None, author=None, apply=False, json_output=False
    )
    assert rc == 1


def test_run_collect_cli_timeout_returns_failure_even_with_supportive_quorum(monkeypatch) -> None:
    def fake_collect(**kwargs) -> CollectOutcome:
        return CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=0,
            action="prepare",
            action_reason="reviewer orchestration timeout; prepared only",
            items=[EvidenceItem("claude", "body", True, ["claude"], [], "pass")],
            orchestration_timeout=True,
            timed_out_families=["grok"],
            overall_timeout_seconds=1.0,
        )

    monkeypatch.setattr(qe, "collect_evidence", fake_collect)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r", pr=1, families=None, author=None, apply=True, json_output=False
    )
    assert rc == 1


def test_run_collect_cli_error_path(monkeypatch, capsys) -> None:
    def boom(**kwargs):
        raise ValueError("no head")

    monkeypatch.setattr(qe, "collect_evidence", boom)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r", pr=1, families=None, author=None, apply=False, json_output=True
    )
    assert rc == 1
    assert "no head" in capsys.readouterr().out


def test_run_collect_cli_catches_runtime_error(monkeypatch, capsys) -> None:
    def boom(**kwargs):
        raise RuntimeError("empty diff")

    monkeypatch.setattr(qe, "collect_evidence", boom)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r", pr=1, families=None, author=None, apply=False, json_output=False
    )
    assert rc == 1
    assert "empty diff" in capsys.readouterr().out


def test_run_collect_cli_preflight_transport_error_serializes_fail_closed_json(
    monkeypatch, capsys
) -> None:
    def boom(**kwargs):
        raise qe.CollectPreflightTransportError(
            repo="o/r",
            pr=1,
            phase="preflight_pr_context",
            error=RuntimeError("error connecting to api.github.com"),
            attempts=2,
        )

    monkeypatch.setattr(qe, "collect_evidence", boom)
    monkeypatch.setattr(qe, "resolve_author", lambda default="local": "me")
    rc = qe.run_collect_cli(
        repo="o/r", pr=1, families=None, author=None, apply=True, json_output=True
    )

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "collect_evidence"
    assert payload["status"] == "transport_blocked"
    assert payload["transport_blocked"] is True
    assert payload["preserve_no_mutate"] is True
    assert payload["phase"] == "preflight_pr_context"
    assert payload["posted_families"] == []
    assert payload["items"] == []
    assert payload["failures"] == []


# --- build_review_prompt: complete file list + fair per-file body bounding ---


def _diff_with_deletion_before_additions() -> tuple[str, str, list[str]]:
    """A unified diff whose large DELETION sorts (alphabetically) before its
    ADDITIONS, mirroring PR #8416 (``tests/conftest.py`` deleted before
    ``tests/fixtures/*`` added). A blind ``diff[:N]`` slice would drop the
    additions entirely. Returns ``(diff, name_status, added_paths)``.
    """
    deleted = "tests/conftest.py"
    added = ["tests/fixtures/alpha.py", "tests/fixtures/beta.py"]
    big_body = "\n".join(f"-old conftest line {i} " + "x" * 60 for i in range(2000))
    deletion = (
        f"diff --git a/{deleted} b/{deleted}\n"
        "deleted file mode 100644\n"
        f"--- a/{deleted}\n+++ /dev/null\n@@ -1,2000 +0,0 @@\n{big_body}\n"
    )
    additions = ""
    for path in added:
        body = "\n".join(f"+fixture {path} line {i}" for i in range(40))
        additions += (
            f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,40 @@\n{body}\n"
        )
    diff = deletion + additions
    name_status = f"D\t{deleted}\n" + "".join(f"A\t{p}\n" for p in added)
    return diff, name_status, added


def test_build_review_prompt_keeps_all_added_paths_when_deletion_sorts_first() -> None:
    diff, name_status, added = _diff_with_deletion_before_additions()
    assert len(diff) > qe._MAX_DIFF_CHARS  # body alone forces bounding
    prompt = qe.build_review_prompt(
        repo="o/r", pr=8416, head_sha=HEAD, diff_text=diff, name_status=name_status
    )
    # Every added path survives even though the diff body had to be bounded.
    for path in added:
        assert path in prompt


def test_build_review_prompt_never_truncates_complete_file_list_header() -> None:
    diff, name_status, added = _diff_with_deletion_before_additions()
    prompt = qe.build_review_prompt(
        repo="o/r", pr=8416, head_sha=HEAD, diff_text=diff, name_status=name_status
    )
    header = prompt[: prompt.index("=== DIFF")]
    # The file-list header is placed before the (bounded) body and is complete.
    assert "=== CHANGED FILES" in header
    assert "tests/conftest.py" in header
    for path in added:
        assert path in header
    # The body really was bounded (per-file marker present), proving the header
    # survived truncation rather than the diff simply being small.
    assert qe._PER_FILE_TRUNCATION_MARKER.strip() in prompt


def test_build_review_prompt_derives_file_list_when_name_status_absent() -> None:
    diff, _name_status, added = _diff_with_deletion_before_additions()
    # No name_status supplied: the file list is recovered from the diff headers,
    # so a reviewer still cannot claim an added file is absent.
    prompt = qe.build_review_prompt(repo="o/r", pr=8416, head_sha=HEAD, diff_text=diff)
    header = prompt[: prompt.index("=== DIFF")]
    assert "tests/conftest.py" in header
    for path in added:
        assert path in header


def test_build_review_prompt_small_diff_is_not_truncated() -> None:
    diff = (
        "diff --git a/aragora/x.py b/aragora/x.py\n"
        "--- a/aragora/x.py\n+++ b/aragora/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    prompt = qe.build_review_prompt(
        repo="o/r", pr=42, head_sha=HEAD, diff_text=diff, name_status="M\taragora/x.py\n"
    )
    # Shape semantics unchanged: a str grounded on the short head, carrying the
    # verdict instruction and the changed file; nothing truncated.
    assert isinstance(prompt, str)
    assert HEAD[:7] in prompt
    assert "Verdict: PASS" in prompt
    assert "Verdict: CHANGES-REQUESTED" in prompt
    assert "aragora/x.py" in prompt
    assert "truncated" not in prompt


# --- _bound_diff_body: fair per-file water-filling --------------------------


def test_bound_diff_body_returns_input_unchanged_when_within_cap() -> None:
    diff = "diff --git a/a b/a\n+hello\n"
    bounded, truncated = qe._bound_diff_body(diff, 30_000)
    assert truncated is False
    assert bounded == diff


def test_bound_diff_body_gives_every_file_a_hunk() -> None:
    seg_a = "diff --git a/a b/a\n" + "A" * 50_000 + "\n"
    seg_b = "diff --git a/b b/b\n" + "B" * 50_000 + "\n"
    seg_c = "diff --git a/c b/c\n" + "C" * 50_000 + "\n"
    bounded, truncated = qe._bound_diff_body(seg_a + seg_b + seg_c, 30_000)
    assert truncated is True
    # No single file may consume the whole budget: each file's header (and some
    # content) survives, unlike a blind first-N-bytes slice.
    assert "diff --git a/a b/a" in bounded
    assert "diff --git a/b b/b" in bounded
    assert "diff --git a/c b/c" in bounded
    assert "B" in bounded and "C" in bounded
    marker_overhead = 3 * len(qe._PER_FILE_TRUNCATION_MARKER)
    assert len(bounded) <= 30_000 + marker_overhead + 8


def test_bound_diff_body_single_file_falls_back_to_head_slice() -> None:
    diff = "diff --git a/a b/a\n" + "A" * 100_000
    bounded, truncated = qe._bound_diff_body(diff, 30_000)
    assert truncated is True
    assert bounded.startswith("diff --git a/a b/a")
    assert len(bounded) <= 30_000 + len(qe._PER_FILE_TRUNCATION_MARKER) + 8


def test_bound_diff_body_small_addition_kept_whole_when_deletion_huge() -> None:
    # The fairness property that fixes #8416: a small addition that sorts AFTER a
    # huge deletion is kept in full and never dropped.
    deletion = "diff --git a/del b/del\n" + "D" * 200_000 + "\n"
    addition = "diff --git a/add b/add\n+only forty chars of new content here\n"
    bounded, truncated = qe._bound_diff_body(deletion + addition, 60_000)
    assert truncated is True
    assert "only forty chars of new content here" in bounded


# --- default_prompt_builder: name-status pass-through + graceful fallback ----


def _prompt_builder_run_stub(diff: str, name_status: str | None):
    """Build a fake ``merge_quorum_io.run`` serving diff / name-status / head."""

    def fake_run(args, *, env=None, timeout=None):
        if args[:3] == ["gh", "pr", "diff"]:
            if "--name-status" in args:
                if name_status is None:
                    return SimpleNamespace(returncode=1, stdout="", stderr="boom")
                return SimpleNamespace(returncode=0, stdout=name_status, stderr="")
            return SimpleNamespace(returncode=0, stdout=diff, stderr="")
        if args[:3] == ["gh", "pr", "view"]:
            return SimpleNamespace(returncode=0, stdout=HEAD + "\n", stderr="")
        raise AssertionError(f"unexpected args: {args}")

    return fake_run


def test_default_prompt_builder_prepends_name_status(monkeypatch) -> None:
    diff, name_status, added = _diff_with_deletion_before_additions()
    monkeypatch.setattr(qe.merge_quorum_io, "run", _prompt_builder_run_stub(diff, name_status))
    prompt = qe.default_prompt_builder("o/r", 8416, {"head_sha": HEAD})
    header = prompt[: prompt.index("=== DIFF")]
    assert "tests/conftest.py" in header
    for path in added:
        assert path in header


def test_default_prompt_builder_tolerates_name_status_fetch_failure(monkeypatch) -> None:
    diff, _name_status, added = _diff_with_deletion_before_additions()
    # name-status fetch fails: the builder must NOT raise and must still produce a
    # complete file list (recovered from the diff) -- return semantics unchanged.
    monkeypatch.setattr(qe.merge_quorum_io, "run", _prompt_builder_run_stub(diff, None))
    prompt = qe.default_prompt_builder("o/r", 8416, {"head_sha": HEAD})
    header = prompt[: prompt.index("=== DIFF")]
    for path in added:
        assert path in header


def test_default_prompt_builder_empty_diff_still_raises(monkeypatch) -> None:
    # Builder exit/return semantics unchanged: an empty diff is still a hard error.
    monkeypatch.setattr(qe.merge_quorum_io, "run", _prompt_builder_run_stub("   \n", "D\tx\n"))
    with pytest.raises(RuntimeError, match="empty diff"):
        qe.default_prompt_builder("o/r", 8416, {"head_sha": HEAD})


# --- Cross-provider CLI quorum (grok-build / antigravity) --------------------


def test_dispatch_routes_grok_and_gemini_to_cli_reviewers(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        qe,
        "_run_grok_reviewer",
        lambda p: calls.append("grok") or qe.ReviewerResult("grok", "ok", True),
    )
    monkeypatch.setattr(
        qe,
        "_run_gemini_reviewer",
        lambda p: calls.append("gemini") or qe.ReviewerResult("gemini", "ok", True),
    )
    qe.default_reviewer_runner("grok", "x")
    qe.default_reviewer_runner("GEMINI", "x")  # case-insensitive
    assert calls == ["grok", "gemini"]


def _force_grok_bin(monkeypatch, present: bool) -> None:
    monkeypatch.setattr(qe.os.path, "isfile", lambda p: present)
    monkeypatch.setattr(qe.os, "access", lambda p, mode: present)


def test_grok_reviewer_prefers_sandboxed_cli_when_installed(monkeypatch) -> None:
    _force_grok_bin(monkeypatch, True)
    monkeypatch.setenv(qe._REVIEWER_TIMEOUT_ENV, "17")
    seen: dict = {}

    def fake_cli(family, argv, harness, timeout=qe._REVIEWER_TIMEOUT):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return qe.ReviewerResult(family, "verdict", True, harness=harness)

    monkeypatch.setattr(qe, "_run_argv_cli_reviewer", fake_cli)
    monkeypatch.setattr(qe, "_run_api_agent", lambda f, p: pytest.fail("should not hit API"))
    res = qe._run_grok_reviewer("review prompt")
    assert res.family == "grok" and res.ok is True
    # read-only sandbox + headless single-prompt, explicit Grok Build path.
    assert seen["argv"][1:] == ["--sandbox", "read-only", "--no-plan", "-p", "review prompt"]
    assert seen["argv"][0].endswith(".grok/bin/grok")
    assert seen["timeout"] == 17.0


def test_grok_build_bin_override(monkeypatch) -> None:
    monkeypatch.setenv("ARAGORA_GROK_BUILD_BIN", "/custom/grok")
    assert qe._resolve_grok_build_bin() == "/custom/grok"


def test_grok_reviewer_falls_back_to_api_without_cli(monkeypatch) -> None:
    _force_grok_bin(monkeypatch, False)
    monkeypatch.setattr(qe, "_run_api_agent", lambda f, p: qe.ReviewerResult(f, "api", True))
    res = qe._run_grok_reviewer("x")
    assert res.family == "grok" and res.text == "api"


def test_grok_reviewer_falls_back_to_api_on_cli_failure_when_key_present(monkeypatch) -> None:
    _force_grok_bin(monkeypatch, True)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setattr(
        qe,
        "_run_argv_cli_reviewer",
        lambda *a, **k: qe.ReviewerResult("grok", "", False, "grok CLI exit 1: capped"),
    )
    monkeypatch.setattr(qe, "_run_api_agent", lambda f, p: qe.ReviewerResult(f, "api", True))
    res = qe._run_grok_reviewer("x")
    assert res.text == "api"  # wedged CLI + key present -> API fallback, quorum not blocked


def test_gemini_reviewer_prefers_resolved_sandboxed_agy(monkeypatch) -> None:
    import shutil as _sh

    monkeypatch.setenv(qe._REVIEWER_TIMEOUT_ENV, "19")
    monkeypatch.setattr(_sh, "which", lambda name: "/usr/local/bin/agy" if name == "agy" else None)
    seen: dict = {}

    def fake_cli(family, argv, harness, timeout=qe._REVIEWER_TIMEOUT):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return qe.ReviewerResult(family, "v", True, harness=harness)

    monkeypatch.setattr(qe, "_run_argv_cli_reviewer", fake_cli)
    monkeypatch.setattr(qe, "_run_api_agent", lambda f, p: pytest.fail("should not hit API"))
    res = qe._run_gemini_reviewer("review prompt")
    assert res.family == "gemini"
    # resolved path (not bare "agy") + sandbox.
    assert seen["argv"] == ["/usr/local/bin/agy", "--sandbox", "-p", "review prompt"]
    assert seen["timeout"] == 19.0


def test_gemini_reviewer_falls_back_to_api_without_agy(monkeypatch) -> None:
    import shutil as _sh

    monkeypatch.setattr(_sh, "which", lambda name: None)
    monkeypatch.setattr(qe, "_run_api_agent", lambda f, p: qe.ReviewerResult(f, "api", True))
    res = qe._run_gemini_reviewer("x")
    assert res.family == "gemini" and res.text == "api"


def test_cross_provider_does_not_change_counting_rules() -> None:
    # The Tier-4 change adds reviewer BACKENDS only; family counting is unchanged.
    assert "fusion" not in qe.FAMILY_PROVIDERS  # blend must never count as a family
    assert qe.FAMILY_PROVIDERS["grok"] == "xai"
    assert qe.FAMILY_PROVIDERS["gemini"] == "google"


# --- Reviewer infra-retry hardening (Tier-4, operator-preapproved 2026-06-16) ---
from aragora.swarm.quorum_evidence import (  # noqa: E402
    ReviewerResult as _RR,
    _run_reviewer_with_infra_retry as _retry,
)


def _seq_runner(results):
    state = {"n": 0}

    def run(family, prompt):
        r = results[min(state["n"], len(results) - 1)]
        state["n"] += 1
        return r

    run.state = state
    return run


def test_infra_retry_recovers_transient_failure(monkeypatch):
    monkeypatch.delenv("ARAGORA_COLLECT_EVIDENCE_INFRA_RETRIES", raising=False)
    runner = _seq_runner([_RR("grok", "", False, "timeout"), _RR("grok", "Verdict: pass", True)])
    res = _retry(runner, "grok", "p")
    assert res.ok is True  # second attempt's verdict used
    assert runner.state["n"] == 2  # retried exactly once


def test_infra_retry_never_retries_a_real_verdict(monkeypatch):
    monkeypatch.delenv("ARAGORA_COLLECT_EVIDENCE_INFRA_RETRIES", raising=False)
    # A returned changes_requested (ok=True) is a real review — must NOT be retried away.
    runner = _seq_runner(
        [_RR("claude", "Verdict: changes-requested", True), _RR("claude", "Verdict: pass", True)]
    )
    res = _retry(runner, "claude", "p")
    assert res.ok is True
    assert res.text.lower().startswith("verdict: changes")
    assert runner.state["n"] == 1  # dissent stands; no re-roll


def test_infra_retry_exhausts_and_returns_failure(monkeypatch):
    monkeypatch.setenv("ARAGORA_COLLECT_EVIDENCE_INFRA_RETRIES", "1")
    runner = _seq_runner([_RR("grok", "", False, "timeout")])  # always fails
    res = _retry(runner, "grok", "p")
    assert res.ok is False
    assert runner.state["n"] == 2  # 1 initial + 1 retry


def test_infra_retry_zero_disables(monkeypatch):
    monkeypatch.setenv("ARAGORA_COLLECT_EVIDENCE_INFRA_RETRIES", "0")
    runner = _seq_runner([_RR("grok", "", False, "x")])
    _retry(runner, "grok", "p")
    assert runner.state["n"] == 1  # no retry when disabled


def test_infra_retry_env_count_respected(monkeypatch):
    monkeypatch.setenv("ARAGORA_COLLECT_EVIDENCE_INFRA_RETRIES", "2")
    runner = _seq_runner([_RR("grok", "", False, "x")])  # always fails
    _retry(runner, "grok", "p")
    assert runner.state["n"] == 3  # 1 initial + 2 retries


def _supportive_outcome(tier, *families):
    items = [EvidenceItem(f, f"## {f.title()} review", True, [f], [], "pass") for f in families]
    return CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=tier,
        action="prepare",
        action_reason="",
        items=items,
    )


def test_has_supportive_quorum_is_tiered():
    # Tier 1-2: settle on ONE western-frontier (claude/openai) supportive signal.
    assert _supportive_outcome(1, "claude").has_supportive_quorum is True
    assert _supportive_outcome(2, "openai").has_supportive_quorum is True
    # ...but a lone cheap signal (or even two cheap signals) is NOT enough.
    assert _supportive_outcome(2, "qwen").has_supportive_quorum is False
    assert _supportive_outcome(2, "qwen", "kimi").has_supportive_quorum is False
    # A cheap signal alongside a western-frontier one is fine.
    assert _supportive_outcome(2, "qwen", "claude").has_supportive_quorum is True
    # Tier 0: any single supportive family.
    assert _supportive_outcome(0, "qwen").has_supportive_quorum is True
    # Tier 3-4 and unknown/None tier: two distinct WESTERN families (Western-only
    # counted, fail-safe). Chinese-routed families are advisory-only and do NOT
    # count, so claude+qwen is insufficient but claude+grok (both Western) settles.
    assert _supportive_outcome(3, "claude").has_supportive_quorum is False
    assert _supportive_outcome(3, "claude", "qwen").has_supportive_quorum is False
    assert _supportive_outcome(3, "claude", "grok").has_supportive_quorum is True
    assert _supportive_outcome(None, "claude").has_supportive_quorum is False
    assert _supportive_outcome(None, "claude", "openai").has_supportive_quorum is True
    assert _supportive_outcome(None, "deepseek", "qwen").has_supportive_quorum is False


def test_incomplete_quorum_reason_is_tiered():
    # Tier 1-2 settle on one western-frontier signal, so an incomplete reason
    # names that requirement instead of a misleading "(n/2)" family denominator.
    r12 = _supportive_outcome(2, "qwen").incomplete_quorum_reason
    assert "western-frontier" in r12
    assert "/2" not in r12
    # Tier 0: any single supportive family -> report the (n/1) shortfall.
    assert _supportive_outcome(0).incomplete_quorum_reason == (
        "supportive quorum incomplete (0/1); prepared evidence only"
    )
    # Tier 3-4 / unknown tier report the Western-only shortfall (Chinese-routed
    # families are advisory-only and excluded from the counted set).
    r3 = _supportive_outcome(3, "claude").incomplete_quorum_reason
    assert "Western families" in r3 and "advisory-only" in r3
    r_none = _supportive_outcome(None).incomplete_quorum_reason
    assert "Western families" in r_none


def test_supportive_quorum_strict_when_flag_off(monkeypatch):
    # Production default: the Tier 1-2 relaxation is OFF, so those tiers need two
    # distinct supportive families and the reason uses the family denominator.
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "0")
    assert _supportive_outcome(2, "claude").has_supportive_quorum is False
    assert _supportive_outcome(2, "openai").has_supportive_quorum is False
    # Tier 0 already uses one signal on current main; default-OFF must preserve it.
    assert _supportive_outcome(0, "qwen").has_supportive_quorum is True
    assert _supportive_outcome(0, "claude", "grok").has_supportive_quorum is True
    assert _supportive_outcome(1, "claude", "grok").has_supportive_quorum is True
    reason = _supportive_outcome(2, "claude").incomplete_quorum_reason
    assert "(1/2 distinct families)" in reason
    assert "western-frontier" not in reason


def test_supportive_quorum_strict_when_flag_unset(monkeypatch):
    # The PRODUCTION default is the env var UNSET (not merely "0"); that must also
    # be the strict gate, so an accidental default-ON regression is caught.
    monkeypatch.delenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", raising=False)
    assert qe.tiered_merge_gate_enabled() is False
    assert _supportive_outcome(0, "qwen").has_supportive_quorum is True
    assert _supportive_outcome(2, "claude").has_supportive_quorum is False
    assert _supportive_outcome(1, "claude", "grok").has_supportive_quorum is True


def test_tiered_gate_is_captured_at_construction(monkeypatch):
    # The flag is captured ONCE at outcome construction; mutating the env afterward
    # must not flip a security-relevant decision mid-settlement-flow.
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")
    outcome = _supportive_outcome(2, "claude")  # tiered ON -> lone WF satisfies
    assert outcome.tiered_gate is True
    assert outcome.has_supportive_quorum is True
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "0")  # mutate mid-flow
    assert outcome.has_supportive_quorum is True  # unchanged: captured at build


def test_tier_quorum_rule_matrix():
    from aragora.swarm.quorum_evidence import TierQuorumRule, tier_quorum_rule

    # Tier 0 (and below): one family of any kind, matching current-main behavior.
    assert tier_quorum_rule(0, tiered_gate=True) == TierQuorumRule(1, False)
    assert tier_quorum_rule(-1, tiered_gate=True) == TierQuorumRule(1, False)
    assert tier_quorum_rule(0, tiered_gate=False) == TierQuorumRule(1, False)
    assert tier_quorum_rule(-1, tiered_gate=False) == TierQuorumRule(1, False)
    # Tier 1: ON -> one western-frontier signal; OFF -> two distinct (any family).
    assert tier_quorum_rule(1, tiered_gate=True) == TierQuorumRule(1, True)
    assert tier_quorum_rule(1, tiered_gate=False) == TierQuorumRule(2, False)
    # Tier 2: ON -> one western-frontier; OFF -> two distinct incl. >=1 Western (G2).
    assert tier_quorum_rule(2, tiered_gate=True) == TierQuorumRule(1, True)
    assert tier_quorum_rule(2, tiered_gate=False) == TierQuorumRule(
        2, False, requires_at_least_one_western=True
    )
    # Tier 3-4 and unknown/None (fail-safe): two distinct WESTERN families,
    # Western-only counted (G1) — Chinese-routed families are advisory-only.
    for tier in (3, 4, None):
        for gate in (False, True):
            assert tier_quorum_rule(tier, tiered_gate=gate) == TierQuorumRule(
                2, False, western_only_counted=True
            )


# --- severity_gated prepare/apply round-trip (claude/grok #8574 P2) ---
def test_evidence_item_severity_gated_roundtrips() -> None:
    # The severity-gate regime an artifact was prepared under must survive
    # serialization, exactly like tiered_gate, so apply can't silently re-decide.
    for regime in (True, False):
        outcome = CollectOutcome(
            repo="o/r",
            pr=1,
            head_sha=HEAD,
            head_committed_at=COMMITTED,
            tier=4,
            action="prepare",
            action_reason="x",
            items=[
                EvidenceItem(
                    "claude",
                    _prepared_body("claude"),
                    True,
                    ["claude"],
                    [],
                    "pass",
                    severity_gated=regime,
                )
            ],
        )
        assert outcome.to_dict()["items"][0]["severity_gated"] is regime
        rehydrated = qe.collect_outcome_from_dict(outcome.to_dict())
        assert rehydrated.items[0].severity_gated is regime


def test_evidence_item_missing_severity_gated_fails_closed() -> None:
    # Legacy/forged artifacts that omit severity_gated default to the STRICT regime
    # (False) so a missing field can never relax dissent.
    item = qe._evidence_item_from_dict(
        {
            "family": "claude",
            "body": _prepared_body("claude"),
            "would_count": True,
            "verdict": "pass",
        }
    )
    assert item.severity_gated is False


def test_clone_prepared_items_reconciles_severity_gated_min() -> None:
    # min(prepared, live): the relaxed regime survives only when BOTH agree.
    relaxed = EvidenceItem(
        "claude", "- [P2] nit", True, ["claude"], [], "changes_requested", severity_gated=True
    )
    strict = EvidenceItem(
        "claude", "- [P2] nit", True, ["claude"], [], "changes_requested", severity_gated=False
    )
    assert qe._clone_prepared_items([relaxed], live_severity_gated=True)[0].severity_gated is True
    assert qe._clone_prepared_items([relaxed], live_severity_gated=False)[0].severity_gated is False
    assert qe._clone_prepared_items([strict], live_severity_gated=True)[0].severity_gated is False
    assert qe._clone_prepared_items([relaxed])[0].severity_gated is True  # None preserves prepared


def test_severity_gated_regime_controls_p2_dissent_after_roundtrip() -> None:
    # A [P2]-only changes_requested is advisory under the relaxed regime and blocking
    # under strict — and the regime that decides it survives serialization.
    body = "Verdict: CHANGES-REQUESTED\n\n- [P2] minor style nit"
    assert (
        EvidenceItem(
            "grok", body, False, ["grok"], [], "changes_requested", severity_gated=True
        ).dissenting
        is False
    )
    assert (
        EvidenceItem(
            "grok", body, False, ["grok"], [], "changes_requested", severity_gated=False
        ).dissenting
        is True
    )
    rt = qe._evidence_item_from_dict(
        {
            "family": "grok",
            "body": body,
            "would_count": False,
            "verdict": "changes_requested",
            "severity_gated": True,
        }
    )
    assert rt.severity_gated is True and rt.dissenting is False


def test_apply_relint_preserves_reconciled_severity_gated(tmp_path, monkeypatch) -> None:
    # End-to-end apply: a STRICT-prepared (severity_gated=False) [P2]-only
    # changes_requested item must stay strict (dissenting) even when the live flag is
    # ON. The relint loop must not let EvidenceItem.default_factory re-read the live
    # env and undo min(prepared, live) (claude/grok #8574 P1).
    body = "Verdict: CHANGES-REQUESTED\n\n- [P2] minor style nit"
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=4,
        action="prepare",
        action_reason="prepared",
        items=[
            EvidenceItem(
                "grok", body, True, ["grok"], [], "changes_requested", severity_gated=False
            )
        ],
    )
    path = tmp_path / "strict_p2.json"
    path.write_text(json.dumps(outcome.to_dict()), encoding="utf-8")
    monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")  # live ON would relax it
    applied = qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=path,
        author="me",
        apply=True,
        families=["grok"],
        context_fetcher=lambda r, p: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda r, p: 4,
        linter=lambda *a, **k: {
            "would_count": True,
            "counted_reviewer_ids": ["grok"],
            "problems": [],
        },
        poster=lambda r, p, b: None,
    )
    assert applied.items[0].severity_gated is False  # reconciled strict survives relint
    assert applied.items[0].dissenting is True
    assert "grok" in applied.dissenting_families


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True),
        (False, False),
        ("true", True),
        ("1", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("", False),
        (None, False),
        (1, True),
        (0, False),
    ],
)
def test_coerce_relaxed_flag(raw, expected) -> None:
    # bool("false") would be True; the coercion fails closed for stringly flags.
    assert qe._coerce_relaxed_flag(raw) is expected


def test_severity_gated_string_false_stays_strict_through_restore() -> None:
    item = qe._evidence_item_from_dict(
        {
            "family": "claude",
            "body": _prepared_body("claude"),
            "would_count": True,
            "verdict": "pass",
            "severity_gated": "false",
        }
    )
    assert item.severity_gated is False


# --- advisory_dissent_settle_enabled (opt-in flag, default OFF) -------------
def test_advisory_dissent_settle_enabled_default_off(monkeypatch) -> None:
    # Production default is the env var UNSET; that MUST read as OFF so the new
    # advisory_settle path is dormant until an operator opts in.
    monkeypatch.delenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", raising=False)
    assert qe.advisory_dissent_settle_enabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", "On"])
def test_advisory_dissent_settle_enabled_true_tokens(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", raw)
    assert qe.advisory_dissent_settle_enabled() is True


@pytest.mark.parametrize("raw", ["0", "false", "off", "no", "", "  ", "maybe"])
def test_advisory_dissent_settle_enabled_false_tokens(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", raw)
    assert qe.advisory_dissent_settle_enabled() is False


def test_advisory_dissent_settle_enabled_accepts_injected_env() -> None:
    # Mirrors severity_gated_dissent_enabled / tiered_merge_gate_enabled: an
    # explicit env mapping overrides os.environ for deterministic testing.
    assert (
        qe.advisory_dissent_settle_enabled({"ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE": "1"}) is True
    )
    assert (
        qe.advisory_dissent_settle_enabled({"ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE": "0"}) is False
    )
    assert qe.advisory_dissent_settle_enabled({}) is False
