"""Characterization corpus for the CLI parser split (C-1 to C-4).

Step 1 of ``docs/architecture/P5_CLI_PARSER_SPLIT_DESIGN.md``: the facade's public names, the
parser tree built by ``build_parser()``, its help text and the modules it loads are recorded
under ``parser_characterization/`` and must hold while registration helpers move out of
``aragora/cli/parser.py``. Rewriting a golden file is a behavior change that needs its own
reviewed PR; ``PARSER_CHARACTERIZATION_REGEN=1`` only produces that diff.
"""

from __future__ import annotations

import difflib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).parent / "parser_characterization"
REPO_ROOT = Path(__file__).resolve().parents[2]
REGEN = os.environ.get("PARSER_CHARACTERIZATION_REGEN") == "1"
HELP_PYTHON = (3, 11)
# The code's own fallbacks for the six defaults read from the environment (design C-2);
# None means unset. Every other ARAGORA_* variable is dropped from the child environment.
PINNED_ENV: dict[str, str | None] = {
    "ARAGORA_API_URL": "http://localhost:8080",
    "ARAGORA_API_KEY": None,
    "ARAGORA_DEFAULT_ROUNDS": "9",
    "ARAGORA_DEFAULT_CONSENSUS": "judge",
    "ARAGORA_DEFAULT_AGENTS": "grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi",
    "ARAGORA_ASK_TIMEOUT_SECONDS": "3600",
}
# Registration modules the split creates (design section 4); C-4 accepts them as additions.
SPLIT_MODULE_PREFIX = "aragora.cli._parser_"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _write_golden(name: str, entries: dict[str, Any]) -> None:
    rows = [f"{json.dumps(key)}: {_canonical(value)}" for key, value in sorted(entries.items())]
    (GOLDEN_DIR / name).write_text("{\n" + ",\n".join(rows) + "\n}\n", encoding="utf-8")


def _read_golden(name: str) -> dict[str, Any]:
    path = GOLDEN_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _assert_matches_golden(name: str, actual: dict[str, Any]) -> None:
    """Byte-equal per key; the failure names every drifted key and diffs the first one."""
    if REGEN:
        _write_golden(name, actual)
    expected = _read_golden(name)
    assert expected, f"{name} is missing or empty"
    keys = {
        "missing": sorted(set(expected) - set(actual)),
        "added": sorted(set(actual) - set(expected)),
    }
    assert keys == {"missing": [], "added": []}, f"{name}: {keys}"
    drifted = [
        key for key in sorted(expected) if _canonical(expected[key]) != _canonical(actual[key])
    ]
    if drifted:
        first = drifted[0]
        old, new = (
            json.dumps(v, indent=1, sort_keys=True).split("\n")
            for v in (expected[first], actual[first])
        )
        diff = difflib.unified_diff(old, new, f"golden[{first}]", f"actual[{first}]", lineterm="")
        pytest.fail(f"{name} drifted for {drifted}:\n" + "\n".join(list(diff)[:120]))


@pytest.fixture(scope="module")
def dump(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One fresh interpreter: environment-read defaults are fixed at import, and other tests in
    this process may already have imported the parser or its command modules."""
    tmp = tmp_path_factory.mktemp("parser_dump")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ARAGORA_")}
    env.update({key: value for key, value in PINNED_ENV.items() if value is not None})
    env["ARAGORA_DATA_DIR"] = str(tmp / "data")
    env["COLUMNS"] = "100"
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(REPO_ROOT), os.environ.get("PYTHONPATH")))
    )
    out = tmp / "dump.json"
    subprocess.run(
        [sys.executable, str(GOLDEN_DIR / "parser_dump.py"), str(out)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        timeout=180,
    )
    return json.loads(out.read_text(encoding="utf-8"))


# --- C-1 public surface -----------------------------------------------------
def test_public_surface_keeps_every_recorded_name(dump: dict[str, Any]) -> None:
    if REGEN:
        _write_golden("public_surface.json", {"names": dump["surface"]})
    recorded = _read_golden("public_surface.json")["names"]
    assert recorded and recorded == sorted(recorded)
    assert sorted(set(recorded) - set(dump["surface"])) == []
    facade = importlib.import_module("aragora.cli.parser")
    for name in recorded:
        obj = getattr(facade, name)
        owner = getattr(obj, "__module__", None)
        if callable(obj) and isinstance(owner, str) and owner.startswith("aragora."):
            home = importlib.import_module(owner)
            assert getattr(home, obj.__name__, None) is obj, (name, owner)


# --- C-2 parser tree --------------------------------------------------------
def test_parser_tree_matches_the_golden_dump(dump: dict[str, Any]) -> None:
    assert len(dump["tree"]) > 100
    _assert_matches_golden("parser_tree.json", dump["tree"])


# --- C-3 help text ----------------------------------------------------------
@pytest.mark.skipif(
    sys.version_info[:2] != HELP_PYTHON,
    reason="argparse help layout differs across Python minor versions; recorded on 3.11",
)
def test_root_and_command_help_is_byte_identical(dump: dict[str, Any]) -> None:
    assert set(dump["help"]) == set(dump["tree"])
    _assert_matches_golden("help_py311.json", dump["help"])


# --- C-4 import footprint ---------------------------------------------------
def _footprint(dump: dict[str, Any]) -> dict[str, list[str]]:
    # The full post-build set also follows imports inside unrelated packages; the
    # aragora.cli part is what a registration helper controls.
    return {
        "import": dump["imported"],
        "build_cli": [name for name in dump["built"] if name.split(".")[:2] == ["aragora", "cli"]],
    }


def test_import_footprint_is_the_recorded_set_plus_split_modules(dump: dict[str, Any]) -> None:
    live = _footprint(dump)
    if REGEN:
        _write_golden("import_footprint.json", live)
    recorded = _read_golden("import_footprint.json")
    assert set(recorded) == set(live)
    for stage, modules in recorded.items():
        assert modules, stage
        drift = {
            "missing": sorted(set(modules) - set(live[stage])),
            "unexpected": sorted(
                name
                for name in set(live[stage]) - set(modules)
                if not name.startswith(SPLIT_MODULE_PREFIX)
            ),
        }
        assert drift == {"missing": [], "unexpected": []}, stage
