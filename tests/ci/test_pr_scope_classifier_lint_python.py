"""Pin the ``lint_python`` scope filter of the shared PR scope classifier.

The required ``lint`` check runs its worker job only when ``lint_python``
matches a changed path, so the import-layer contract inputs (``.importlinter``,
the baseline and the checker) and the classifier itself must stay in scope.

The one-path cases are evaluated twice: with a small matcher for the glob
subset the filter uses, and, when node and picomatch (the matcher behind
``dorny/paths-filter``) are available, with picomatch itself using the
action's ``dot: true`` option. Set ``ARAGORA_PICOMATCH_DIR`` to a picomatch
package directory to use one outside ``aragora/live/node_modules``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_ACTION = REPO_ROOT / ".github" / "actions" / "pr-scope-classifier" / "action.yml"

_PREVIOUS_GLOBS = (
    "aragora/**",
    "aragora-verify/**",
    "tests/**",
    "scripts/**",
    "pyproject.toml",
    "requirements*.txt",
    ".github/workflows/**",
    "deploy/**",
    "security/policies/**",
    "aragora-operator/**",
)
_ADDED_GLOBS = (".importlinter", ".github/actions/pr-scope-classifier/**")

_ONE_PATH_CASES = {
    ".importlinter": True,
    "scripts/baselines/import_contracts_baseline.json": True,
    "scripts/ci/check_import_contracts.py": True,
    "aragora/utils/__init__.py": True,
    "pyproject.toml": True,
    ".github/workflows/lint.yml": True,
    ".github/actions/pr-scope-classifier/action.yml": True,
    "docs/README.md": False,
}

# Characters with glob meaning beyond ``*``/``**``; the local matcher refuses them
# so it cannot silently disagree with picomatch.
_UNSUPPORTED_GLOB_CHARS = set("?[]{}()!+@")


def _lint_python_globs() -> list[str]:
    action = yaml.safe_load(_ACTION.read_text(encoding="utf-8"))
    step = next(s for s in action["runs"]["steps"] if "paths-filter" in s.get("uses", ""))
    return yaml.safe_load(step["with"]["filters"])["lint_python"]


def _segment_matches(pattern: str, segment: str) -> bool:
    regex = "[^/]*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, segment) is not None


def _parts_match(glob_parts: list[str], path_parts: list[str]) -> bool:
    if not glob_parts:
        return not path_parts
    head, rest = glob_parts[0], glob_parts[1:]
    if head == "**":
        return any(_parts_match(rest, path_parts[i:]) for i in range(len(path_parts) + 1))
    return (
        bool(path_parts)
        and _segment_matches(head, path_parts[0])
        and _parts_match(rest, path_parts[1:])
    )


def _glob_matches(glob: str, path: str) -> bool:
    unsupported = _UNSUPPORTED_GLOB_CHARS & set(glob)
    assert not unsupported, (glob, unsupported)
    return _parts_match(glob.split("/"), path.split("/"))


def _picomatch_dir() -> Path | None:
    override = os.environ.get("ARAGORA_PICOMATCH_DIR")
    candidate = (
        Path(override)
        if override
        else REPO_ROOT / "aragora" / "live" / "node_modules" / "picomatch"
    )
    return candidate if (candidate / "package.json").is_file() else None


def test_lint_python_keeps_previous_globs_and_adds_contract_inputs() -> None:
    globs = _lint_python_globs()
    for glob in (*_PREVIOUS_GLOBS, *_ADDED_GLOBS):
        assert globs.count(glob) == 1, (glob, globs)


@pytest.mark.parametrize(("path", "expected"), sorted(_ONE_PATH_CASES.items()))
def test_one_path_scope(path: str, expected: bool) -> None:
    globs = _lint_python_globs()
    assert any(_glob_matches(glob, path) for glob in globs) is expected


def test_one_path_scope_with_picomatch() -> None:
    node = shutil.which("node")
    picomatch = _picomatch_dir()
    if node is None or picomatch is None:
        pytest.skip("node or picomatch not available (requires node and a picomatch package)")
    script = (
        "const pm = require(process.argv[1]);"
        "const [globs, paths] = JSON.parse(process.argv[2]);"
        "const isMatch = pm(globs, { dot: true });"
        "console.log(JSON.stringify(Object.fromEntries(paths.map((p) => [p, isMatch(p)]))));"
    )
    payload = json.dumps([_lint_python_globs(), sorted(_ONE_PATH_CASES)])
    result = subprocess.run(
        [node, "-e", script, str(picomatch), payload],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert json.loads(result.stdout) == _ONE_PATH_CASES
