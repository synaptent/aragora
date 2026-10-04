"""Opt-in exact-head restricted read-only Claude reviewer context (offline, faked CLI)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import aragora.swarm.quorum_evidence as qe
from scripts import collect_quorum_evidence as cli

_REAL_RUN = subprocess.run
_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
VALIDATED_ARGV = (  # claude_argv of the validated restricted-reviewer bootstrap
    "claude -p --safe-mode --restricted --tools Read,Grep,Glob --disallowedTools "
    "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Task,Agent,Skill --permission-prompts none "
    "--disable-slash-commands --strict-mcp-config --mcp-config {mcp} --output-format stream-json "
    "--verbose --include-hook-events"
).split()
NEVER = {"--bare", "--model", "--settings", "--add-dir", "--worktree", "bypassPermissions"}
NEVER |= {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"}
INIT = {"tools": ["Glob", "Grep", "Read"], "mcp_servers": [], "model": "claude-opus-5"}
DEFAULT_KWARGS = {"input", "capture_output", "text", "timeout", "check"}
CONTEXT_ENVS = ("ARAGORA_CLAUDE_REVIEW_CHECKOUT", "ARAGORA_CLAUDE_REVIEW_EXPECTED_HEAD")
CHANGES = "Verdict: CHANGES-REQUESTED\n- [P2] Gap."
HOOK = {"type": "system", "subtype": "hook_started", "hook_event": "SessionStart"}


def _git(repo, *args):
    return _REAL_RUN([*_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _ev(kind, **fields):
    kind, _, subtype = kind.partition("/")
    return {"type": kind, **({"subtype": subtype} if subtype else {}), **fields}


def _stream(cwd, uses=("Glob", "Read"), extra=(), result="Verdict: PASS", error=False, **init):
    # Event shapes trimmed from a captured Claude Code 2.1.288 --safe-mode --restricted run.
    head = [] if init.pop("absent", False) else [_ev("system/init", **{**INIT, "cwd": cwd, **init})]
    tail = [] if result is None else [_ev("result/success", is_error=error, result=result)]
    body = [_ev("system/thinking_tokens", estimated_tokens=50)]
    for name in uses:
        body.append(_ev("assistant", message={"content": [_ev("tool_use", name=name)]}))
        body.append(_ev("user", message={"content": [_ev("tool_result", content="README.md")]}))
    return "\n".join(json.dumps(event) for event in [*head, *body, *extra, *tail]) + "\n"


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    repo = tmp_path / "wt"
    (repo / "__pycache__").mkdir(parents=True)
    (repo / ".gitignore").write_text("__pycache__/\n")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "c0"]):
        _git(repo, *args)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    for name in (qe._CLAUDE_TIMEOUT_ENV, qe._CLI_PROBE_TIMEOUT_ENV, "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = {"ANTHROPIC_MODEL": "claude-opus-5", "ARAGORA_MODEL_TRANSPORT": "direct"}
    for name, value in {**env, **dict(zip(CONTEXT_ENVS, (str(repo), head)))}.items():
        monkeypatch.setenv(name, value)
    return repo, os.path.realpath(repo), head


def _install(monkeypatch, *outputs, mutate=None):
    calls = []

    def fake_run(argv, **kwargs):
        if argv[0] == "git":
            return _REAL_RUN(argv, **kwargs)
        calls.append((list(argv), kwargs))
        if mutate and len(calls) == 2:
            mutate()
        rc, out, err = outputs[len(calls) - 1]
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)

    monkeypatch.setattr(qe.subprocess, "run", fake_run)
    return calls


def _probe_then(monkeypatch, real, review, **kwargs):
    probe = (0, _stream(real, uses=(), result="OK", tools=review.get("tools", INIT["tools"])), "")
    return _install(monkeypatch, probe, (0, _stream(real, **review), ""), **kwargs)


def _failed_closed(result, needle="provenance unavailable"):
    assert (result.ok, result.text, result.grounded) == (False, "", False)
    assert result.allow_transport_fallback is False and needle in result.error


def test_default_mode_argv_and_kwargs_unchanged(monkeypatch):
    calls = _install(monkeypatch, (0, "OK", ""), (0, "Verdict: PASS", ""))
    assert qe._run_claude_cli("p") == qe.ReviewerResult("claude", "Verdict: PASS", True)
    for argv, kwargs in calls:
        assert argv == ["claude", "-p", "--strict-mcp-config", "--mcp-config", argv[-1]]
        assert set(kwargs) == DEFAULT_KWARGS


@pytest.mark.parametrize(
    ("tools", "text"), [(INIT["tools"], "Verdict: PASS"), (["Read", "EndConversation"], CHANGES)]
)
def test_restricted_review_pins_argv_cwd_env_and_composes(monkeypatch, checkout, tools, text):
    repo, real, head = checkout
    (repo / "__pycache__" / "x.pyc").write_text("ignored cache stays allowed")
    calls = _probe_then(monkeypatch, real, {"tools": tools, "result": text})
    env_before = dict(os.environ)
    result = qe._run_claude_cli("review prompt")
    assert (result.ok, result.text, result.grounded) == (True, text, True)
    assert head[:12] in result.harness and dict(os.environ) == env_before
    expected = [(qe._CLI_PROBE_PROMPT, 90.0), ("review prompt", 600.0)]
    assert [(kwargs["input"], kwargs["timeout"]) for _, kwargs in calls] == expected
    for argv, kwargs in calls:
        assert argv == [argv[-5] if token == "{mcp}" else token for token in VALIDATED_ARGV]
        for variadic in ("--tools", "--disallowedTools", "--mcp-config"):
            assert argv[argv.index(variadic) + 2].startswith("--")
        assert not NEVER & set(argv) and kwargs["cwd"] == real and "env" not in kwargs
    pr = {"family": "claude", "head_sha": "a" * 40, "head_committed_at": "", "pr": 7}
    body = qe.compose_evidence_comment(reviewer_text=text, harness=result.harness, **pr)
    default = qe.compose_evidence_comment(reviewer_text=text, **pr)
    assert body.replace(result.harness, "H") == default.replace("the Aragora Claude reviewer", "H")


@pytest.mark.parametrize(
    "breaker",
    [
        lambda repo, mp: mp.setenv(CONTEXT_ENVS[0], str(repo / "missing")),
        lambda repo, mp: mp.setenv(CONTEXT_ENVS[0], str(repo / "__pycache__")),
        lambda repo, mp: mp.setenv(CONTEXT_ENVS[1], "0" * 40),
        lambda repo, mp: (repo / ".gitignore").write_text("modified\n"),
        lambda repo, mp: (repo / "untracked.txt").write_text("x"),
        lambda repo, mp: mp.delenv(CONTEXT_ENVS[1]),
        lambda repo, mp: mp.setenv(CONTEXT_ENVS[1], "ABC123"),
        lambda repo, mp: mp.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-required"),
    ],
    ids=["missing", "subdir", "head", "tracked", "untracked", "half", "hex", "vp-required"],
)
def test_precheck_fails_closed_before_any_claude_call(monkeypatch, checkout, breaker):
    breaker(checkout[0], monkeypatch)
    calls = _install(monkeypatch)
    _failed_closed(qe._run_claude_reviewer("p"))
    assert calls == []


@pytest.mark.parametrize(
    ("stage", "bad"),
    [
        (1, {"absent": True}),
        *[(1, {"tools": ["Read", tool]}) for tool in ("Bash", "Write", "Task", "mcp__s__t")],
        (1, {"tools": ["EndConversation"]}),
        (1, {"mcp_servers": [{"name": "srv", "status": "connected"}]}),
        (1, {"model": "claude-fable-5"}),
        (1, {"extra": [HOOK]}),
        (2, {"uses": ["Read", "Bash"]}),
        (2, {"extra": [HOOK]}),
        (2, {"result": None}),
        (2, {"error": True}),
        (2, {"result": "  "}),
        (2, {"extra": ["not-an-object"]}),
    ],
)
def test_stream_attestation_fails_closed_at_probe_or_review(monkeypatch, checkout, stage, bad):
    good = (0, _stream(checkout[1], uses=(), result="OK"), "")
    probe = (0, _stream(checkout[1], uses=(), result="OK", **bad), "") if stage == 1 else good
    calls = _install(monkeypatch, probe, (0, _stream(checkout[1], **bad), ""))
    _failed_closed(qe._run_claude_cli("p"))
    assert len(calls) == stage


def test_restricted_probe_credential_wall_is_classified(monkeypatch, checkout):
    calls = _install(monkeypatch, (1, "", "Not logged in · Please run /login"))
    _failed_closed(qe._run_claude_cli("p"), "credential_unhealthy(claude)")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda repo: _git(repo, "commit", "-q", "--allow-empty", "-m", "moved"),
        lambda repo: _git(repo, "switch", "-q", "-c", "other"),
        lambda repo: (repo / "dirty.txt").write_text("x"),
    ],
    ids=["head", "branch-ref", "dirty"],
)
def test_postcheck_drift_discards_text_without_fallback(monkeypatch, checkout, mutation):
    repo, real, _ = checkout
    for name in ("run_claude_vibeproxy", "_run_api_agent", "_run_openrouter_reviewer"):
        monkeypatch.setattr(qe, name, lambda *_a, **_k: pytest.fail("no stand-in transport"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _probe_then(monkeypatch, real, {}, mutate=lambda: mutation(repo))
    _failed_closed(qe.default_reviewer_runner("claude", "p"), "reviewer context mutated")


def test_collect_evidence_aborts_on_expected_head_mismatch(monkeypatch):
    monkeypatch.setenv(CONTEXT_ENVS[1], "b" * 40)
    with pytest.raises(ValueError, match="expected head"):
        qe.collect_evidence(
            **{"repo": "o/r", "pr": 7, "families": ("claude",), "author": "x", "apply": False},
            context_fetcher=lambda *_: {"head_sha": "a" * 40},
            tier_fetcher=lambda *_: pytest.fail("no tier read"),
            reviewer_runner=lambda *_: pytest.fail("no reviewer may run"),
        )


def test_other_families_unchanged_while_context_set(monkeypatch, checkout):
    for name in (qe._CODEX_MODEL_ENV, qe._CODEX_MODELS_ENV, qe._CODEX_TIMEOUT_ENV):
        monkeypatch.delenv(name, raising=False)
    calls = _install(monkeypatch, (0, "Verdict: PASS", ""))
    assert qe.default_reviewer_runner("openai", "p").ok and len(calls) == 1
    argv, kwargs = calls[0]
    output = argv[argv.index("--output-last-message") + 1]
    assert argv == qe._codex_openai_command(output, model="gpt-5.5")
    assert set(kwargs) == DEFAULT_KWARGS


def test_cli_flags_both_or_neither_and_env_scoped(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_hydrate_provider_secrets", lambda: None)
    seen = []

    def fake_collect(**_kwargs):
        seen.append([os.environ.get(name) for name in CONTEXT_ENVS])
        raise ValueError("stop")

    monkeypatch.setattr(qe, "collect_evidence", fake_collect)
    args = ["--repo", "o/r", "--pr", "7", "--author", "x", "--json"]
    args += ["--claude-review-checkout", "/w"]
    with pytest.raises(SystemExit, match="2"):
        cli.main(args)
    assert cli.main(args + ["--claude-review-expected-head", "c" * 40]) == 1
    assert seen == [["/w", "c" * 40]] and not any(name in os.environ for name in CONTEXT_ENVS)
    kwargs = {"repo": "o/r", "pr": 7, "families": None, "author": "x", "apply": False}
    assert qe.run_collect_cli(json_output=True, claude_review_checkout="/w", **kwargs) == 1
    assert "together" in capsys.readouterr().out
