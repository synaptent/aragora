"""Exercise the installed live lint rules without writing probes into the tree."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "aragora/live"
NAMING = "@typescript-eslint/naming-convention"
BOUNDARY = "boundaries/dependencies"


def test_live_scripts_and_strict_typing() -> None:
    scripts = json.loads((LIVE / "package.json").read_text())["scripts"]
    assert scripts["typecheck"] == "tsc --noEmit -p tsconfig.json"
    assert scripts["lint"] == "eslint . --max-warnings 0"
    assert scripts["format"] == "prettier --write ."
    assert scripts["format:check"] == "prettier --check ."
    assert json.loads((LIVE / "tsconfig.json").read_text())["compilerOptions"]["strict"]
    assert (LIVE / ".prettierrc").is_file()
    assert (LIVE / ".prettierignore").is_file()


def test_live_make_targets_use_package_scripts() -> None:
    result = subprocess.run(
        ["make", "-n", "readiness-lint-live", "readiness-typecheck-live"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    for command in ("npm run lint", "npm run format:check", "npm run typecheck"):
        assert command in result.stdout


def test_native_suppressions_are_scoped_and_documented() -> None:
    data = json.loads((LIVE / "eslint-suppressions.json").read_text())
    assert data
    for path, rules in data.items():
        assert not Path(path).is_absolute()
        assert set(rules) <= {NAMING, "complexity"}
        assert all(entry["count"] > 0 for entry in rules.values())
    for doc in ("RATCHETS.md", "TECH_DEBT.md"):
        text = (ROOT / "docs" / doc).read_text()
        assert "aragora/live/eslint-suppressions.json" in text
        assert "npx eslint . --prune-suppressions" in text


@pytest.fixture(scope="module")
def lint_probes() -> dict:
    if not shutil.which("node") or not (LIVE / "node_modules/eslint").is_dir():
        pytest.skip("live ESLint toolchain not installed")
    # ESLint's API uses the real config and auto-loaded suppressions, with
    # virtual source paths. Boundary imports resolve real modules in src/.
    script = """
import { ESLint } from 'eslint';
const eslint = new ESLint();
const probes = JSON.parse(process.argv[1]);
const output = {};
for (const [name, filePath, source] of probes) {
  const [result] = await eslint.lintText(source, { filePath });
  output[name] = result.messages;
}
const config = await eslint.calculateConfigForFile('src/lib/__quality_probe.ts');
output.complexity = config.rules.complexity;
console.log(JSON.stringify(output));
"""
    probes = [
        ("naming", "src/lib/__quality_probe.ts", "const Bad_name = 1; export default Bad_name;"),
        (
            "validNames",
            "src/lib/__quality_probe.ts",
            "export const camelCase = 1, UPPER_CASE = 2, PascalCase = 3;",
        ),
    ]
    for branches in (14, 15, 20):
        source = (
            "export function branchCount(value: number) {"
            + "".join(f"if (value === {n}) return {n};" for n in range(branches))
            + "return -1; }"
        )
        probes.append((f"branches{branches}", "src/lib/__quality_probe.ts", source))
    for name, path, source in (
        ("relativeImport", "src/lib/__quality_probe.ts", "import '../app/page';"),
        ("aliasImport", "src/lib/__quality_probe.ts", "import '@/app/page';"),
        ("nestedImport", "src/lib/nested/__quality_probe.ts", "import '../../app/page';"),
        ("reexport", "src/lib/__quality_probe.ts", "export { default } from '@/app/page';"),
        (
            "dynamicImport",
            "src/lib/__quality_probe.ts",
            "export const page = import('@/app/page');",
        ),
        ("allowedLibImport", "src/lib/__quality_probe.ts", "import './utils';"),
        ("allowedAppImport", "src/app/__quality_probe.ts", "import '@/lib/utils';"),
    ):
        probes.append((name, path, source))
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(probes)],
        cwd=LIVE,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_naming_rejects_new_debt_and_accepts_supported_formats(lint_probes: dict) -> None:
    assert any(m["ruleId"] == NAMING and m["severity"] == 2 for m in lint_probes["naming"])
    assert lint_probes["validNames"] == []


def test_complexity_enforces_fifteen(lint_probes: dict) -> None:
    assert lint_probes["complexity"] == [2, {"max": 15}]
    assert lint_probes["branches14"] == []  # Initial path + 14 branches = 15.
    for name in ("branches15", "branches20"):
        assert any(m["ruleId"] == "complexity" and m["severity"] == 2 for m in lint_probes[name])


@pytest.mark.parametrize(
    "name", ["relativeImport", "aliasImport", "nestedImport", "reexport", "dynamicImport"]
)
def test_lib_cannot_depend_on_app(lint_probes: dict, name: str) -> None:
    assert any(m["ruleId"] == BOUNDARY and m["severity"] == 2 for m in lint_probes[name])


def test_allowed_import_directions(lint_probes: dict) -> None:
    assert lint_probes["allowedLibImport"] == []
    assert lint_probes["allowedAppImport"] == []
