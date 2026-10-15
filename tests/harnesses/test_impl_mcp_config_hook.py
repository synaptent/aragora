"""The Claude Code harness gets its MCP config through ``aragora.harnesses.mcp_config``.

``aragora.harnesses`` (application layer) must not import ``aragora.mcp`` (interface layer),
which writes the config pointing Claude Code at Aragora's MCP server. ``aragora.mcp`` registers
its generator through the ``aragora.harness_mcp_configs`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.harnesses import mcp_config as hook
from aragora.harnesses.claude_code import ClaudeCodeConfig, ClaudeCodeHarness
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_REGISTRATION = ("mcp", "aragora.mcp.harness_registration:register_harness_impl_mcp_config")


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_generator", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


async def _launch_command(tmp_path: Path) -> list[str]:
    harness = ClaudeCodeHarness(ClaudeCodeConfig(use_mcp_tools=True))
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"done", b""))
    proc.returncode = 0
    proc.kill = MagicMock()
    with (
        patch("asyncio.create_subprocess_exec", return_value=proc) as spawn,
        patch("asyncio.wait_for", return_value=(b"done", b"")),
    ):
        await harness.execute_implementation(tmp_path, "fix bug")
    return list(spawn.call_args.args)


def test_an_unregistered_generator_raises(isolated_hook, tmp_path):
    with pytest.raises(hook.ImplMcpConfigNotRegisteredError, match="aragora.harness_mcp"):
        hook.generate_impl_mcp_config(tmp_path)


@pytest.mark.asyncio
async def test_without_a_generator_the_session_runs_without_mcp_config(isolated_hook, tmp_path):
    command = await _launch_command(tmp_path)
    assert "--mcp-config" not in command
    assert "--allowedTools" in command


@pytest.mark.asyncio
async def test_the_session_attaches_the_registered_config(isolated_hook, tmp_path):
    written = tmp_path / "written.json"
    calls = []

    def generator(repo_path):
        calls.append(repo_path)
        return written

    hook.register_impl_mcp_config_generator(generator)
    command = await _launch_command(tmp_path)
    assert calls == [tmp_path]
    assert command[command.index("--mcp-config") + 1] == str(written)


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch, tmp_path):
    calls = []

    def register():
        calls.append("register")
        hook.register_impl_mcp_config_generator(lambda repo_path: repo_path / "c.json")

    entry_point = SimpleNamespace(name="m0", value="tests.declared:m0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP else [],
    )
    assert hook.generate_impl_mcp_config(tmp_path) == tmp_path / "c.json"
    assert hook.generate_impl_mcp_config(tmp_path) == tmp_path / "c.json"
    assert calls == ["register"]


def test_pyproject_declares_the_mcp_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP)._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [MCP_REGISTRATION]


def test_the_registration_writes_the_mcp_server_config(isolated_hook, tmp_path):
    from aragora.mcp.harness_registration import register_harness_impl_mcp_config

    register_harness_impl_mcp_config()
    register_harness_impl_mcp_config()
    path = hook.generate_impl_mcp_config(tmp_path)
    assert path == tmp_path / ".nomic" / "mcp" / "impl_config.json"
    server = json.loads(path.read_text())["mcpServers"]["aragora"]
    assert server["args"] == ["-m", "aragora.mcp.server", "--transport", "stdio"]
    assert server["env"] == {"ARAGORA_MCP_IMPL_MODE": "1", "ARAGORA_REPO_PATH": str(tmp_path)}


def test_the_registration_reads_the_generator_at_call_time(isolated_hook, monkeypatch, tmp_path):
    from aragora.mcp import impl_config
    from aragora.mcp.harness_registration import register_harness_impl_mcp_config

    register_harness_impl_mcp_config()
    monkeypatch.setattr(impl_config, "generate_impl_mcp_config", lambda repo_path: repo_path)
    assert hook.generate_impl_mcp_config(tmp_path) == tmp_path


def test_a_harness_only_process_reaches_the_mcp_generator(tmp_path):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "import aragora.harnesses.claude_code\n"
        "from aragora.harnesses.mcp_config import generate_impl_mcp_config\n"
        "print(generate_impl_mcp_config(Path(sys.argv[1])))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-1] == str(tmp_path / ".nomic" / "mcp" / "impl_config.json")


def test_harnesses_hold_no_import_of_mcp_at_any_scope():
    offenders = []
    for path in sorted((REPO_ROOT / "aragora" / "harnesses").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}"
                for name in names
                if name == "aragora.mcp" or name.startswith("aragora.mcp.")
            ]
    assert offenders == []
