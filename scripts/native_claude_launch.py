#!/usr/bin/env python3
"""Fail-closed, qualification-only native Claude print launcher (no review authority).

Credentials are read once from private enrollment/source files and passed only in
the model child's environment. This helper never writes or refreshes credentials.
Native runtime state writes are not filesystem-sandboxed by this helper.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import select
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import Any, BinaryIO, cast

MAX_INPUT = 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
IDENTITY = ("email", "account_uuid", "organization_uuid")
FLAGS = (
    "--print",
    "--model",
    "--tools",
    "--strict-mcp-config",
    "--mcp-config",
    "--no-session-persistence",
    "--safe-mode",
    "--setting-sources",
    "--output-format",
    "--max-turns",
)


class LaunchError(Exception):
    """Only static, non-secret category strings may be supplied."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _open_directory(path: Path) -> int:
    parts = list(path.absolute().parts[1:])
    if ".." in parts:
        raise LaunchError("unsafe_directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    at_root = True
    try:
        while True:
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in {0, os.getuid()} or (
                info.st_mode & 0o022 and not (parts and sticky_root)
            ):
                raise LaunchError("unsafe_directory")
            if not parts:
                if info.st_uid != os.getuid():
                    raise LaunchError("unsafe_directory")
                return fd
            part = parts.pop(0)
            # Only macOS's protected root aliases are expanded; the physical
            # target is still opened and checked one descriptor at a time.
            if at_root and sys.platform == "darwin" and part in {"var", "tmp", "etc"}:
                alias = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(alias.st_mode):
                    if alias.st_uid != 0 or os.readlink(part, dir_fd=fd) not in {
                        "private/" + part,
                        "/private/" + part,
                    }:
                        raise LaunchError("unsafe_directory")
                    parts = ["private", part] + parts
                    continue
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            at_root = False
    except BaseException:
        os.close(fd)
        raise


def _directory(path: Path) -> None:
    os.close(_open_directory(path))


def _json(path: Path, private: bool = True) -> dict:
    parent = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & (0o077 if private else 0o022)
                or info.st_size > MAX_INPUT
            ):
                raise LaunchError("unsafe_file")
            raw = stream.read(MAX_INPUT + 1)
    finally:
        os.close(parent)
    if len(raw) > MAX_INPUT:
        raise LaunchError("input_limit")
    try:

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise LaunchError("malformed_input")
                result[key] = value
            return result

        data = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise LaunchError("malformed_input") from None
    if not isinstance(data, dict):
        raise LaunchError("malformed_input")
    return data


def read_private_json(path: Path) -> dict:
    return _json(path)


def _expiry(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise LaunchError("malformed_input") from None


def select_token(
    auth_dir: Path, identity: dict, timeout_seconds: float, now: datetime | None = None
) -> str:
    _directory(auth_dir)
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or any(not isinstance(identity.get(key), str) or not identity[key] for key in IDENTITY)
    ):
        raise LaunchError("enrollment_invalid")
    matches = []
    for path in sorted(auth_dir.iterdir()):
        if path.suffix != ".json":
            continue
        data = read_private_json(path)
        if not isinstance(data.get("type"), str):
            raise LaunchError("malformed_input")
        if data["type"] != "claude":
            continue
        if any(
            not isinstance(data.get(key), str) or not data[key] for key in IDENTITY
        ) or not isinstance(data.get("disabled"), bool):
            raise LaunchError("malformed_input")
        expiry = _expiry(data.get("expired"))
        token = data.get("access_token")
        if not isinstance(token, str) or not re.fullmatch(r"[!-~]+", token):
            raise LaunchError("token_type")
        if all(data[key] == identity.get(key) for key in IDENTITY):
            matches.append((data["disabled"], expiry, token))
    if len(matches) != 1:
        raise LaunchError("identity_ambiguous" if matches else "identity_missing")
    disabled, expiry, token = matches[0]
    if disabled:
        raise LaunchError("source_disabled")
    if (expiry - (now or datetime.now(timezone.utc))).total_seconds() <= timeout_seconds + 300:
        raise LaunchError("token_expiring")
    return token


def build_environment(
    environ: Mapping[str, str], profile: str, profile_home: Path
) -> dict[str, str]:
    if environ.get("ARAGORA_CLAUDE_PROFILE", profile) != profile:
        raise LaunchError("profile_conflict")
    for name in environ:
        upper = name.upper()
        if (
            upper.startswith(
                (
                    "ANTHROPIC",
                    "AWS_",
                    "AZURE_",
                    "GOOGLE_",
                    "GCLOUD_",
                    "VERTEX_",
                    "BEDROCK_",
                    "CLOUD_ML_",
                )
            )
            or (upper.startswith("CLAUDE") and upper != "CLAUDE_PROFILE_ROOT")
            or upper
            in {
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "OPENAI_BASE_URL",
                "OPENAI_API_BASE",
                "OPENROUTER_BASE_URL",
            }
        ):
            raise LaunchError("environment_conflict")
    safe = {
        key: value
        for key, value in environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ", "SYSTEMROOT"}
    }
    safe.update(
        HOME=str(profile_home),
        XDG_CONFIG_HOME=str(profile_home / ".config"),
        CLAUDE_CONFIG_DIR=str(profile_home / ".claude"),
        CLAUDE_CODE_MAX_RETRIES="0",
        CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK="1",
        CLAUDE_CODE_DISABLE_TERMINAL_TITLE="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL="1",
    )
    return safe


def _conflicting_settings(data) -> bool:
    if isinstance(data, list):
        return any(_conflicting_settings(value) for value in data)
    if not isinstance(data, dict):
        return False
    for key, value in data.items():
        normalized = re.sub(r"[^a-z]", "", key.lower())
        if normalized == "env" or any(
            term in normalized
            for term in (
                "apikey",
                "authhelper",
                "credentialhelper",
                "bedrock",
                "vertex",
                "foundry",
                "gateway",
                "baseurl",
                "provider",
                "aws",
                "managedsettings",
                "remotesettings",
                "forcelogin",
                "fallbackmodel",
                "policy",
                "oauthhelper",
            )
        ):
            return True
        if _conflicting_settings(value):
            return True
    return False


def check_settings(profile_home: Path, cwd: Path, original_home: Path) -> None:
    """Never disable managed policy: known policy sources make admission unknown."""
    if sys.platform not in {"darwin", "linux"}:
        raise LaunchError("platform_unsupported")
    _directory(profile_home)
    _directory(profile_home / ".claude")
    policy_roots = [
        Path("/etc/claude-code"),
        Path("/Library/Application Support/ClaudeCode"),
        profile_home / ".claude",
        original_home / ".claude",
    ]
    for root in policy_roots:
        for name in (
            "managed-settings.json",
            "managed-settings.d",
            "managed-mcp.json",
            "remote-settings.json",
            "remote-settings-consent.json",
            "remote-config.json",
            "policy-limits.json",
        ):
            if os.path.lexists(root / name):
                raise LaunchError("managed_policy_unknown")
    if sys.platform == "darwin":
        for path in (
            Path("/Library/Managed Preferences"),
            Path("/Library/Preferences/com.anthropic.claudecode.plist"),
            original_home / "Library/Preferences/com.anthropic.claudecode.plist",
        ):
            if os.path.lexists(path):
                raise LaunchError("managed_policy_unknown")
    files = {profile_home / ".claude.json", profile_home / ".claude" / ".claude.json"}
    for root in {profile_home, cwd, *cwd.parents}:
        directory = root / ".claude"
        if os.path.lexists(directory):
            _directory(directory)
            files.update(directory.glob("settings*.json"))
    for path in files:
        if os.path.lexists(path) and _conflicting_settings(_json(path, private=False)):
            raise LaunchError("settings_conflict")


def run_child(
    argv: list[str], env: dict, prompt: bytes, timeout_seconds: float
) -> tuple[int, bytes, bytes]:
    """Bounded capture, monotonic deadline, and cleanup limited to our process group."""
    deadline = time.monotonic() + timeout_seconds
    proc = None
    previous = {}
    buffers = {"out": bytearray(), "err": bytearray()}

    def interrupted(signum, frame):
        raise LaunchError("interrupted")

    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, interrupted)
        proc = subprocess.Popen(
            argv,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
        with selectors.DefaultSelector() as selector:
            for pipe, label in ((proc.stdout, "out"), (proc.stderr, "err"), (proc.stdin, "in")):
                pipe = cast(BinaryIO, pipe)  # Popen created every stream with PIPE.
                os.set_blocking(pipe.fileno(), False)
                selector.register(
                    pipe, selectors.EVENT_WRITE if label == "in" else selectors.EVENT_READ, label
                )
            offset = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LaunchError("timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == "in":
                        try:
                            offset += os.write(key.fd, prompt[offset : offset + 65536])
                        except BrokenPipeError:
                            offset = len(prompt)
                        if offset == len(prompt):
                            selector.unregister(key.fileobj)
                            cast(BinaryIO, key.fileobj).close()
                    else:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            cast(BinaryIO, key.fileobj).close()
                            continue
                        buffers[key.data].extend(chunk)
                        if sum(map(len, buffers.values())) > MAX_OUTPUT:
                            raise LaunchError("output_limit")
            try:
                code = proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise LaunchError("timeout") from None
        return code, bytes(buffers["out"]), bytes(buffers["err"])
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if proc is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    pass
            proc.wait()
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                cast(BinaryIO, pipe).close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LaunchError("timeout")
    return remaining


def verify_binary(binary: str, env: dict, deadline: float) -> None:
    code, version, _ = run_child([binary, "--version"], env, b"", min(5, _remaining(deadline)))
    if code or not re.match(rb"2\.\d+\.\d+(?:\s|$)", version):
        raise LaunchError("runtime_unsupported")
    code, help_text, _ = run_child([binary, "--help"], env, b"", min(5, _remaining(deadline)))
    if code or any(flag.encode() not in help_text for flag in FLAGS):
        raise LaunchError("runtime_unsupported")


def _failure(code: int, out: bytes, err: bytes, expected_model: str) -> str | None:
    malformed = False
    try:
        data = json.loads(out)
        if not isinstance(data, dict) or data.get("type") != "result":
            malformed = True
        elif data.get("is_error") or data.get("subtype", "success") != "success":
            code = code or 1
        elif not isinstance(data.get("result"), str):
            malformed = True
    except (ValueError, UnicodeError, RecursionError):
        malformed = True
    if code:
        combined = (out + err).lower()
        for category, markers in (
            ("auth_revoked", (b"revoked",)),
            (
                "auth_failure",
                (b"401", b"unauthorized", b"authentication", b"invalid token", b"login"),
            ),
            ("quota", (b"429", b"rate limit", b"quota", b"usage limit")),
            (
                "model",
                (
                    b"model_not_found",
                    b"model not found",
                    b"unknown model",
                    b"invalid model",
                    b"model unavailable",
                ),
            ),
            ("transport", (b"connection", b"network", b"tls", b"503", b"overloaded")),
        ):
            if any(marker in combined for marker in markers):
                return category
        return "malformed_result" if malformed else "child_failure"
    if malformed:
        return "malformed_result"
    usage = data.get("modelUsage")
    if not isinstance(usage, dict) or not usage:
        return "model_identity_missing"
    return "wrong_model" if set(usage) != {expected_model} else None


def _secret_output(token: str, *outputs: bytes) -> bool:
    for raw in outputs:
        if token.encode() in raw or b"sk-ant-oat01-" in raw:
            return True
        try:
            pending = [json.loads(raw)]
        except (ValueError, UnicodeError, RecursionError):
            continue
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str) and (token in value or "sk-ant-oat01-" in value):
                return True
    return False


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise LaunchError("arguments")


def _read_prompt(deadline: float) -> bytes:
    if sys.stdin.isatty():
        raise LaunchError("interactive_input")
    prompt = bytearray()
    while len(prompt) <= MAX_INPUT:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([sys.stdin.buffer], [], [], remaining)[0]:
            raise LaunchError("timeout")
        chunk = os.read(sys.stdin.fileno(), min(65536, MAX_INPUT + 1 - len(prompt)))
        if not chunk:
            return bytes(prompt)
        prompt.extend(chunk)
    raise LaunchError("input_limit")


def _deliver(payload: bytes, deadline: float) -> None:
    fd = sys.stdout.fileno()
    blocking = os.get_blocking(fd)
    try:
        os.set_blocking(fd, False)
        pending = memoryview(payload)
        while pending:
            if not select.select([], [fd], [], _remaining(deadline))[1]:
                raise LaunchError("timeout")
            _remaining(deadline)
            try:
                count = os.write(fd, pending[:65536])
            except BlockingIOError:
                continue
            pending = pending[count:]
        _remaining(deadline)
    finally:
        os.set_blocking(fd, blocking)


def _diagnostic(category: str) -> None:
    # A blocked diagnostic sink must not defeat timeout/error termination.
    fd = sys.stderr.fileno()
    try:
        blocking = os.get_blocking(fd)
        try:
            os.set_blocking(fd, False)
            os.write(fd, ("native_claude_launch: " + category + "\n").encode())
        finally:
            os.set_blocking(fd, blocking)
    except OSError:
        pass


def main(argv=None) -> int:
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        tail = args[args.index("--") + 1 :] if "--" in args else []
        args = args[: args.index("--")] if "--" in args else args
        parser = _Parser(allow_abbrev=False)
        parser.add_argument("profile")
        parser.add_argument("--model", required=True)
        parser.add_argument("--timeout-seconds", required=True, type=float)
        options = parser.parse_args(args)
        deadline = time.monotonic() + options.timeout_seconds
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", options.profile)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", options.model)
            or not math.isfinite(options.timeout_seconds)
            or not 0 < options.timeout_seconds <= 3600
            or tail not in ([], ["--output-format", "json"], ["--output-format", "text"])
        ):
            raise LaunchError("arguments")
        original_home = Path(os.environ["HOME"]).absolute()
        profile_home = (
            Path(os.environ.get("CLAUDE_PROFILE_ROOT", original_home / ".aragora-claude"))
            / options.profile
        )
        env = build_environment(os.environ, options.profile, profile_home)
        check_settings(profile_home, Path.cwd(), original_home)
        enrollment = read_private_json(
            Path(
                os.environ.get(
                    "ARAGORA_NATIVE_CLAUDE_ENROLLMENT",
                    original_home / ".aragora/claude_launch_profiles.json",
                )
            )
        )
        profiles = enrollment.get("profiles")
        identity = profiles.get(options.profile) if isinstance(profiles, dict) else None
        if (
            type(enrollment.get("version")) is not int
            or enrollment["version"] != 1
            or not isinstance(identity, dict)
            or any(not isinstance(identity.get(key), str) or not identity[key] for key in IDENTITY)
        ):
            raise LaunchError("enrollment_invalid")
        binary = shutil.which("claude", path=env.get("PATH", os.defpath))
        if not binary:
            raise LaunchError("runtime_missing")
        verify_binary(binary, env, deadline)
        prompt = _read_prompt(deadline)
        if not prompt or len(prompt) > MAX_INPUT:
            raise LaunchError("input_limit")
        token = select_token(
            Path(os.environ.get("VIBEPROXY_AUTH_DIR", original_home / ".cli-proxy-api")),
            identity,
            options.timeout_seconds,
        )
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        output_format = tail[1] if tail else "json"
        command = [
            binary,
            "--print",
            "--max-turns",
            "1",
            "--model",
            options.model,
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--no-session-persistence",
            "--safe-mode",
            "--setting-sources",
            "",
            "--output-format",
            "json",
        ]
        code, out, err = run_child(command, env, prompt, _remaining(deadline))
        if _secret_output(token, out, err):
            raise LaunchError("secret_output")
        category = _failure(code, out, err, options.model)
        if category:
            raise LaunchError(category)
        _deliver(
            (json.loads(out)["result"] + "\n").encode() if output_format == "text" else out,
            deadline,
        )
        # Never forward untrusted CLI diagnostics, which may echo prompt/config.
        return 0
    except LaunchError as exc:
        _diagnostic(exc.category)
        return 124 if exc.category == "timeout" else 1
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        _diagnostic("input_or_runtime_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
