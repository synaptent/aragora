"""Synthetic subprocess acceptance: no real Claude, account or Keychain calls."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone

import pytest


WRAPPER = Path(__file__).resolve().parents[2] / "scripts/claude_profile.sh"
TOKEN = "unit-only-access-token"
REFRESH = "never-forward-this-refresh-token"
IDENTITY = {
    "email": "fixture@example.invalid",
    "account_uuid": "account-fixture",
    "organization_uuid": "org-fixture",
}


def put(path: Path, value: object, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value))
    path.chmod(mode)


@pytest.fixture
def launch(tmp_path):
    home = tmp_path / "home"
    source = home / ".cli-proxy-api"
    profile = home / ".aragora-claude/max-test"
    cfg = home / ".aragora/claude_launch_profiles.json"
    credential = source / "arbitrary-rotated-name.json"
    put(cfg, {"version": 1, "profiles": {"max-test": IDENTITY}})
    put(
        credential,
        {
            **IDENTITY,
            "type": "claude",
            "disabled": False,
            "access_token": TOKEN,
            "refresh_token": REFRESH,
            "expired": "2099-01-01T00:00:00+00:00",
        },
    )
    put(profile / ".claude/settings.json", {"model": "old-default"})
    put(
        profile / ".claude/.credentials.json",
        {"claudeAiOauth": {"accessToken": "stale-stored-token"}},
    )
    bindir = tmp_path / "bin"
    bindir.mkdir(mode=0o700)
    fake = bindir / "claude"
    fake.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent("""\
        import json, os, sys, time, subprocess
        if '--version' in sys.argv:
            print('2.1.268 (Claude Code)'); sys.exit(0)
        if '--help' in sys.argv:
            print('--print --model --tools --strict-mcp-config --mcp-config --no-session-persistence --safe-mode --setting-sources --output-format --max-turns'); sys.exit(0)
        with open(__file__ + '.calls', 'a') as counter: counter.write('generation' + chr(10))
        prompt = sys.stdin.read()
        token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', 'stale-keychain-token')
        assert os.environ.get('CLAUDE_CODE_MAX_RETRIES') == '0'
        assert os.environ.get('CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK') == '1'
        assert os.environ.get('CLAUDE_CODE_DISABLE_TERMINAL_TITLE') == '1'
        if prompt == 'sleep': time.sleep(30)
        if prompt == 'descendant':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            with open(__file__ + '.pids', 'w') as pids: json.dump([os.getpid(), child.pid], pids)
            time.sleep(30)
        if prompt == 'leak':
            print(json.dumps({'type': 'result', 'result': token, 'modelUsage': {'fixture-model': {}}})); sys.exit(0)
        if prompt == 'encoded-leak':
            print('{"type":"result","result":"' + ''.join(chr(92) + 'u%04x' % ord(c) for c in token) + '","modelUsage":{"fixture-model":{}}}'); sys.exit(0)
        if prompt == 'malformed': print('{}'); sys.exit(0)
        if prompt == 'missing-model': print('{"type":"result","result":"OK"}'); sys.exit(0)
        if prompt.startswith('fail:'):
            print(prompt[5:], file=sys.stderr); sys.exit(1)
        if token not in ('unit-only-access-token', 'rotated-access-token'):
            print('401 OAuth access token has been revoked', file=sys.stderr); sys.exit(1)
        print(json.dumps({'type': 'result', 'result': ('x' * 1048576 if prompt == 'large' else 'OK'), 'argv': sys.argv[1:],
                          'fresh_auth': True, 'env_keys': sorted(os.environ),
                          'modelUsage': {(prompt if prompt == 'wrong-model' else 'fixture-model'): {'inputTokens': 1}}}))
    """)
    )
    fake.chmod(0o700)
    compile(fake.read_text(), str(fake), "exec")
    env = {
        "PATH": f"{bindir}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "HOME": str(home),
        "ARAGORA_NATIVE_CLAUDE_ENROLLMENT": str(cfg),
        "VIBEPROXY_AUTH_DIR": str(source),
        "CLAUDE_PROFILE_ROOT": str(home / ".aragora-claude"),
    }

    def run(prompt="ok", timeout="2", extra=(), updates=None):
        return subprocess.run(
            [
                "/bin/bash",
                str(WRAPPER),
                "exec-claude",
                "max-test",
                "--model",
                "fixture-model",
                "--timeout-seconds",
                timeout,
                "--",
                *extra,
            ],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=8,
            cwd=tmp_path,
            env={**env, **(updates or {})},
        )

    return run, credential, cfg, profile, env, fake


def assert_blocked(result):
    assert result.returncode != 0, result.stdout
    assert '"result": "OK"' not in result.stdout
    assert TOKEN not in result.stdout + result.stderr
    assert REFRESH not in result.stdout + result.stderr


@pytest.mark.parametrize("teams", [None, "0", "1"])
@pytest.mark.parametrize("scope", [0, 3])
def test_launch_selects_fresh_token_without_touching_stored_credentials(launch, teams, scope):
    run, source, cfg, profile, _, _ = launch
    if teams is not None:
        put(
            (profile, *profile.parents)[scope] / ".claude/settings.json",
            {"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": teams}},
        )
    before = {p: p.read_bytes() for p in (source, cfg, profile / ".claude/.credentials.json")}
    result = run(extra=("--output-format", "json"))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["fresh_auth"]
    assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in data["env_keys"]
    assert data["argv"][data["argv"].index("--setting-sources") + 1] == ""
    assert "--safe-mode" in data["argv"] and "--no-session-persistence" in data["argv"]
    assert data["argv"][data["argv"].index("--model") + 1] == "fixture-model"
    assert TOKEN not in result.stdout + result.stderr
    assert REFRESH not in result.stdout + result.stderr
    assert before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize(
    "change",
    [
        {"disabled": True},
        {"type": "codex"},
        {"account_uuid": "wrong"},
        {"organization_uuid": "wrong"},
        {"email": "wrong@example.invalid"},
        {"expired": "malformed"},
        {"expired": "2099-01-01T00:00:00"},
        {"expired": "2000-01-01T00:00:00Z"},
        {"access_token": ""},
        {"access_token": 5},
    ],
)
def test_invalid_source_fails_without_saved_login_fallback(launch, change):
    run, source, *_ = launch
    put(source, {**json.loads(source.read_text()), **change})
    assert_blocked(run())


def test_lifetime_includes_entire_deadline_and_safety_margin(launch):
    run, source, *_ = launch
    put(
        source,
        {
            **json.loads(source.read_text()),
            "expired": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
        },
    )
    assert_blocked(run())


@pytest.mark.parametrize(
    "kind", ["duplicate", "disabled_duplicate", "symlink", "public", "missing", "malformed"]
)
def test_unsafe_or_ambiguous_discovery_stops(launch, kind):
    run, source, *_ = launch
    payload = json.loads(source.read_text())
    if kind in {"duplicate", "disabled_duplicate"}:
        put(source.with_name("other.json"), {**payload, "disabled": kind == "disabled_duplicate"})
    elif kind == "symlink":
        target = source.with_suffix(".secret")
        source.rename(target)
        source.symlink_to(target)
    elif kind == "public":
        source.chmod(0o644)
    elif kind == "missing":
        source.unlink()
    else:
        source.write_text("not-json")
    assert_blocked(run())


def test_rotation_and_filename_change_are_seen_at_next_launch(launch):
    run, source, *_ = launch
    assert run().returncode == 0
    data = json.loads(source.read_text())
    source.unlink()
    put(
        source.with_name("new-account-prefixed-file.json"),
        {**data, "access_token": "rotated-access-token"},
    )
    assert run().returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "ANTHROPIC_PROFILE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ARAGORA_CLAUDE_PROFILE",
    ],
)
def test_conflicting_environment_is_rejected(launch, name):
    assert_blocked(launch[0](updates={name: "conflicting-value"}))


@pytest.mark.parametrize(
    "settings",
    [
        {"apiKeyHelper": "echo bad"},
        {"env": {"ANTHROPIC_API_KEY": "bad"}},
        {"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1", "ANTHROPIC_API_KEY": "bad"}},
        {"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": True}},
        {"env": {"UNRECOGNIZED_SETTING": "1"}},
        {"env": ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]},
        {"forceLoginMethod": "gateway"},
        {"fallbackModel": "other-model"},
    ],
)
def test_profile_settings_conflicts_are_not_silently_ignored(launch, settings):
    put(launch[3] / ".claude/settings.json", settings)
    assert_blocked(launch[0]())


@pytest.mark.parametrize(
    "args",
    [
        ("--model", "other"),
        ("--settings", "{}"),
        ("--tools", "Bash"),
        ("--resume", "id"),
        ("--fallback-model", "other"),
        ("--dangerously-skip-permissions",),
    ],
)
def test_forwarded_flags_cannot_override_contract(launch, args):
    assert_blocked(launch[0](extra=args))


def test_unrelated_secrets_not_inherited(launch):
    result = launch[0](
        updates={"GH_TOKEN": "unrelated-gh-secret", "OPENAI_API_KEY": "other-secret"}
    )
    assert result.returncode == 0, result.stderr
    keys = json.loads(result.stdout)["env_keys"]
    assert "GH_TOKEN" not in keys and "OPENAI_API_KEY" not in keys


@pytest.mark.parametrize(
    "prompt", ["leak", "encoded-leak", "malformed", "wrong-model", "missing-model"]
)
def test_unsafe_or_ineligible_output_is_rejected(launch, prompt):
    assert_blocked(launch[0](prompt=prompt))


def test_managed_policy_blocks_instead_of_being_disabled(launch):
    put(launch[3] / ".claude/remote-settings.json", {})
    result = launch[0]()
    assert_blocked(result)
    assert "managed_policy_unknown" in result.stderr


@pytest.mark.parametrize("runtime", ["1.9.99", "3.0.0"])
def test_unqualified_runtime_stops(launch, runtime):
    fake = launch[5]
    fake.write_text(fake.read_text().replace("2.1.268", runtime))
    assert_blocked(launch[0]())


def test_deadline_terminates_own_child(launch):
    import time

    started = time.monotonic()
    result = launch[0](prompt="sleep", timeout="0.2")
    assert_blocked(result)
    assert time.monotonic() - started < 5
    assert "timeout" in result.stderr.lower()


@pytest.mark.parametrize(
    "message,kind",
    [
        ("401 OAuth access token has been revoked", "auth"),
        ("usage limit exceeded", "quota"),
        ("model not found", "model"),
        ("connection reset", "transport"),
    ],
)
def test_failure_categories_remain_distinct(launch, message, kind):
    result = launch[0](prompt="fail:" + message)
    assert_blocked(result)
    assert kind in result.stderr.lower()
    assert Path(str(launch[5]) + ".calls").read_text().splitlines() == ["generation"]


def test_generic_exec_does_not_resolve_or_inject_oauth(launch):
    _, _, cfg, _, env, _ = launch
    cfg.unlink()
    result = subprocess.run(
        [
            "/bin/bash",
            str(WRAPPER),
            "exec",
            "native-only",
            "--",
            sys.executable,
            "-c",
            "import os; print('TOKEN_PRESENT=' + str('CLAUDE_CODE_OAUTH_TOKEN' in os.environ))",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert "TOKEN_PRESENT=False" in result.stdout


@pytest.mark.parametrize("mode", ["deadline", "signal"])
def test_owned_descendants_are_reaped_without_touching_neighbor(launch, mode):
    _, _, _, _, env, fake = launch
    neighbor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    command = [
        "/bin/bash",
        str(WRAPPER),
        "exec-claude",
        "max-test",
        "--model",
        "fixture-model",
        "--timeout-seconds",
        "2",
        "--",
    ]
    proc = subprocess.Popen(
        command,
        env=env,
        cwd=fake.parent.parent,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    owned = []
    try:
        proc.stdin.write(b"descendant")
        proc.stdin.close()
        proc.stdin = None
        marker = Path(str(fake) + ".pids")
        end = time.monotonic() + 1.5
        while not marker.exists() and time.monotonic() < end:
            time.sleep(0.01)
        assert marker.exists(), "fake generation did not start"
        owned = json.loads(marker.read_text())
        if mode == "signal":
            proc.terminate()
        out, err = proc.communicate(timeout=4)
        assert proc.returncode != 0 and not out
        assert (b"interrupted" if mode == "signal" else b"timeout") in err
        end = time.monotonic() + 2
        while any(_running(pid) for pid in owned) and time.monotonic() < end:
            time.sleep(0.01)
        assert not any(_running(pid) for pid in owned)
        assert neighbor.poll() is None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for pid in owned:
            try:
                if _running(pid) and os.getpgid(pid) == owned[0]:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        neighbor.terminate()
        neighbor.wait()


def _running(pid):
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(state.stdout.strip()) and not state.stdout.lstrip().startswith("Z")


def test_preflight_cannot_extend_overall_deadline(launch):
    run, _, _, _, _, fake = launch
    fake.write_text(fake.read_text().replace("print('2.1.268", "time.sleep(1); print('2.1.268"))
    result = run(timeout="0.2")
    assert result.returncode == 124 and "timeout" in result.stderr
    assert not Path(str(fake) + ".calls").exists()


@pytest.mark.parametrize("version", ["2.0.0", "2.99.1"])
def test_two_x_runtime_with_required_capabilities_is_eligible(launch, version):
    launch[5].write_text(launch[5].read_text().replace("2.1.268", version))
    assert launch[0](extra=("--output-format", "text")).stdout == "OK\n"


@pytest.mark.parametrize("output_format", ["json", "text"])
@pytest.mark.parametrize("sink", ["blocked", "closed", "draining"])
def test_result_delivery_owns_remaining_deadline(launch, output_format, sink):
    _, _, _, _, env, fake = launch
    args = ["/bin/bash", str(WRAPPER), "exec-claude", "max-test"]
    args += ["--model", "fixture-model", "--timeout-seconds", "1"]
    args += ["--", "--output-format", output_format]
    with subprocess.Popen(
        args,
        env=env,
        cwd=fake.parent.parent,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        try:
            proc.stdin.write(b"large")
            proc.stdin.close()
            proc.stdin = None
            if sink == "closed":
                proc.stdout.close()
            if sink != "draining":
                assert proc.wait(timeout=3) == (124 if sink == "blocked" else 1)
                assert b"native_claude_launch:" in proc.stderr.read()
            else:
                out, err = proc.communicate(timeout=3)
                assert proc.returncode == 0 and not err
                value = (
                    json.loads(out)["result"] if output_format == "json" else out.decode().strip()
                )
                assert value == "x" * 1048576
            assert Path(str(fake) + ".calls").read_text().splitlines() == ["generation"]
        finally:
            if proc.poll() is None:
                proc.kill()


@pytest.fixture
def native():
    spec = importlib.util.spec_from_file_location(
        "native_launch", WRAPPER.with_name("native_claude_launch.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", [0o700, 0o777])
def test_private_read_rejects_intermediate_symlink(native, tmp_path, mode):
    root = tmp_path.resolve()
    target = root / "physical" / "owned" / "auth"
    put(target / "credential.json", {"synthetic": True})
    (root / "physical").chmod(mode)
    alias = root / "alias"
    alias.symlink_to(target.parent, target_is_directory=True)
    with pytest.raises((native.LaunchError, OSError)):
        native.read_private_json(alias / "auth" / "credential.json")
    if mode == 0o700:
        assert native.read_private_json(target / "credential.json") == {"synthetic": True}
    else:
        with pytest.raises(native.LaunchError):
            native.read_private_json(target / "credential.json")


def test_private_read_remains_bound_when_ancestor_is_replaced(native, tmp_path, monkeypatch):
    root = tmp_path.resolve() / "trusted"
    put(root / "auth" / "credential.json", {"original": True})
    replacement = tmp_path.resolve() / "replacement"
    put(replacement / "auth" / "credential.json", {"substituted": True})
    original_open = os.open
    replaced = []

    def swap_after_open(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        if path == "trusted" and not replaced:
            root.rename(root.with_name("preserved"))
            root.symlink_to(replacement, target_is_directory=True)
            replaced.append(True)
        return fd

    monkeypatch.setattr(native.os, "open", swap_after_open)
    assert native.read_private_json(root / "auth" / "credential.json") == {"original": True}
    assert replaced, "must open and validate each directory component"


def test_system_temporary_alias_is_safe(native, tmp_path):
    physical = tmp_path.resolve() / "safe.json"
    put(physical, {"synthetic": True})
    alias = Path(str(physical).replace("/private/var/", "/var/", 1))
    assert native.read_private_json(alias) == {"synthetic": True}
