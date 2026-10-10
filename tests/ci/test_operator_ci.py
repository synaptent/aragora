"""Keep the operator CI workflow, image smoke test and pre-push hook effective."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/operator-ci.yml"
HOOK_ID = "operator-gofmt-vet"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def _operator_make_var(name: str) -> str:
    text = (ROOT / "aragora-operator/Makefile").read_text()
    match = re.search(rf"^{name} \?= (\S+)$", text, re.MULTILINE)
    assert match, f"{name} not set in aragora-operator/Makefile"
    return match.group(1)


def _step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def _hook() -> dict:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    return next(h for repo in config["repos"] for h in repo["hooks"] if h["id"] == HOOK_ID)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return _load(WORKFLOW)


def test_triggers_permissions_and_timeouts(workflow: dict) -> None:
    for event in ("pull_request", "push"):
        paths = set(workflow["on"][event]["paths"])
        assert {
            "aragora-operator/**",
            ".github/workflows/operator-ci.yml",
            "scripts/ci/check_file_sizes.py",
            "scripts/baselines/operator-file-sizes.json",
        } <= paths
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"checks", "envtest"}
    for job in workflow["jobs"].values():
        assert int(job["timeout-minutes"]) <= 10
        assert "continue-on-error" not in job
        assert "permissions" not in job


def test_every_action_is_pinned(workflow: dict) -> None:
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            uses = step.get("uses")
            if uses and not uses.startswith("./"):
                assert PINNED.match(uses), uses
            assert "continue-on-error" not in step


def test_checks_job_runs_every_static_gate(workflow: dict) -> None:
    job = workflow["jobs"]["checks"]
    steps = job["steps"]
    assert job["defaults"]["run"]["working-directory"] == "aragora-operator"
    go = _step(steps, "Set up Go")
    assert go["with"]["go-version-file"] == "aragora-operator/go.mod"
    gofmt = _step(steps, "gofmt")["run"]
    assert "gofmt -l $(git ls-files '*.go')" in gofmt
    assert "exit 1" in gofmt
    assert _step(steps, "go build")["run"] == "go build ./..."
    assert _step(steps, "go vet")["run"] == "go vet ./..."
    assert _step(steps, "go mod tidy")["run"] == "go mod tidy -diff"
    lint = _step(steps, "golangci-lint")
    assert lint["uses"].startswith("golangci/golangci-lint-action@")
    assert lint["with"]["version"] == _operator_make_var("GOLANGCI_LINT_VERSION") == "v2.13.2"
    assert lint["with"]["working-directory"] == "aragora-operator"
    sizes = _step(steps, "File-size ratchet")
    assert sizes["working-directory"] == "."
    assert " ".join(sizes["run"].split()) == (
        "python scripts/ci/check_file_sizes.py --glob 'aragora-operator/**/*.go' "
        "--baseline scripts/baselines/operator-file-sizes.json"
    )
    makefile = (ROOT / "Makefile").read_text()
    assert "--glob 'aragora-operator/**/*.go'" in makefile
    assert "--baseline scripts/baselines/operator-file-sizes.json" in makefile
    drift = _step(steps, "Generated code and manifests are up to date")["run"].splitlines()
    assert drift[0] == "make generate manifests"
    assert drift[1] == "git diff --exit-code -- ."
    assert any("git status --porcelain" in line for line in drift)


def test_envtest_job_caches_assets_and_uploads_results(workflow: dict) -> None:
    k8s = _operator_make_var("ENVTEST_K8S_VERSION")
    assert k8s == "1.29.x"
    steps = workflow["jobs"]["envtest"]["steps"]
    install = _step(steps, "Install setup-envtest and gotestsum")["run"]
    assert "go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest" in install
    assert re.search(r"go install gotest\.tools/gotestsum@v\d+\.\d+\.\d+", install)

    cache = _step(steps, "Cache envtest binaries")
    assert cache["uses"].startswith("actions/cache@")
    assert k8s in cache["with"]["key"]
    assets = _step(steps, "Set KUBEBUILDER_ASSETS")["run"]
    assert f"setup-envtest use {k8s}" in assets
    bin_dir = re.search(r'--bin-dir "([^"]+)"', assets).group(1)
    assert bin_dir.replace("$HOME", "~") == cache["with"]["path"]
    assert 'echo "KUBEBUILDER_ASSETS=' in assets and "$GITHUB_ENV" in assets
    assert steps.index(cache) < steps.index(_step(steps, "Set KUBEBUILDER_ASSETS"))

    run = _step(steps, "Run unit and controller tests")["run"]
    assert "gotestsum --junitfile operator-junit.xml" in run
    assert "-- ./... -count=1" in run
    assert "-short" not in run

    upload = _step(steps, "Upload test results")
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["if"] == "always()"
    assert "aragora-operator/operator-junit.xml" in upload["with"]["path"].splitlines()


def test_docker_workflow_smoke_tests_the_operator_image() -> None:
    steps = _load(ROOT / ".github/workflows/docker.yml")["jobs"]["build-operator"]["steps"]
    names = [step.get("name") for step in steps]
    build = names.index("Build operator for scanning")
    assert "-t test-operator:latest" in steps[build]["run"]
    smoke = steps[build + 1]
    assert smoke["run"].strip() == "docker run --rm test-operator:latest --help"
    assert "continue-on-error" not in smoke


def test_hook_is_push_only_and_operator_scoped() -> None:
    hook = _hook()
    assert hook["stages"] == ["pre-push"]
    assert hook["language"] == "system"
    assert hook["pass_filenames"] is False
    assert hook["verbose"] is True
    assert hook["files"] == r"^aragora-operator/.*\.go$"
    assert re.search(hook["files"], "aragora-operator/controllers/foo.go")
    assert not re.search(hook["files"], "aragora-operator/README.md")
    assert not re.search(hook["files"], "aragora/server/foo.go")


def _run_hook(path: str, tmp_path: Path, gofmt_out: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        shlex.split(_hook()["entry"]),
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": path,
            "HOOK_LOG": str(tmp_path / "calls"),
            "GOFMT_OUT": gofmt_out,
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_hook_skips_without_go(tmp_path: Path) -> None:
    result = _run_hook("/usr/bin:/bin", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SKIP operator: go not found"


def _fake_go_tools(tmp_path: Path) -> None:
    for tool, body in (
        ("go", 'printf "%s|%s\\n" "$PWD" "$*" >> "$HOOK_LOG"\n'),
        ("gofmt", 'printf "gofmt %s\\n" "$1" >> "$HOOK_LOG"\nprintf "%s" "$GOFMT_OUT"\n'),
    ):
        binary = tmp_path / tool
        binary.write_text(f"#!/bin/sh\n{body}")
        binary.chmod(0o755)


def test_hook_fails_on_unformatted_files_before_vet(tmp_path: Path) -> None:
    _fake_go_tools(tmp_path)
    result = _run_hook(f"{tmp_path}:/usr/bin:/bin", tmp_path, "controllers/bad.go\n")
    assert result.returncode == 1
    assert "controllers/bad.go" in result.stdout
    assert "SKIP" not in result.stdout
    assert (tmp_path / "calls").read_text().splitlines() == ["gofmt -l"]


def test_hook_runs_vet_in_the_operator_when_formatted(tmp_path: Path) -> None:
    _fake_go_tools(tmp_path)
    result = _run_hook(f"{tmp_path}:/usr/bin:/bin", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "SKIP" not in result.stdout
    assert (tmp_path / "calls").read_text().splitlines() == [
        "gofmt -l",
        f"{ROOT}/aragora-operator|vet ./...",
    ]


# gofmt stub that fails the way real gofmt does when a listed path is missing, and
# also refuses an empty file list (real gofmt would then wait on stdin).
_STRICT_GOFMT = """#!/bin/sh
files=0
for arg in "$@"; do
  case "$arg" in -*) continue ;; esac
  files=$((files + 1))
  [ -e "$arg" ] || { echo "lstat $arg: no such file or directory" >&2; exit 2; }
done
[ "$files" -gt 0 ] || { echo "gofmt stub: no file arguments" >&2; exit 2; }
echo "$files" >> "$GOFMT_LOG"
"""


def _strict_go_tools(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gofmt").write_text(_STRICT_GOFMT)
    (bin_dir / "go").write_text("#!/bin/sh\nexit 0\n")
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    return bin_dir


def _env_without_git_location() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
    }


def test_hook_passes_with_and_without_exported_git_dir(tmp_path: Path) -> None:
    # A real `git push` exports GIT_DIR (without GIT_WORK_TREE) to hooks, which makes
    # git treat the current directory as the work-tree top; `pre-commit run` does not.
    bin_dir = _strict_go_tools(tmp_path)
    base_env = _env_without_git_location()
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=ROOT,
        env=base_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    go_files = subprocess.run(
        ["git", "ls-files", "aragora-operator/*.go"],
        cwd=ROOT,
        env=base_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert go_files

    entry = _hook()["entry"]
    assert shlex.split(entry)[:2] == ["bash", "-c"]
    gofmt_log = tmp_path / "gofmt-calls"
    env = {
        **base_env,
        "PATH": f"{bin_dir}{os.pathsep}{base_env['PATH']}",
        "GOFMT_LOG": str(gofmt_log),
    }
    for label, run_env in (
        ("GIT_DIR exported", {**env, "GIT_DIR": git_dir}),
        ("GIT_DIR unset", env),
    ):
        result = subprocess.run(
            shlex.split(entry),
            cwd=ROOT,
            env=run_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, f"{label}: {output}"
        assert "lstat" not in output and "no such file" not in output, f"{label}: {output}"
        assert "SKIP" not in output, f"{label}: {output}"
    assert gofmt_log.read_text().split() == [str(len(go_files))] * 2


def test_hook_refuses_an_empty_go_file_list(tmp_path: Path) -> None:
    bin_dir = _strict_go_tools(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _env_without_git_location()
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    gofmt_log = tmp_path / "gofmt-calls"
    result = subprocess.run(
        shlex.split(_hook()["entry"]),
        cwd=repo,
        env={
            **env,
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "GOFMT_LOG": str(gofmt_log),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "no tracked Go files" in result.stdout
    assert not gofmt_log.exists()


def _make_recipe(target: str) -> str:
    text = (ROOT / "Makefile").read_text()
    match = re.search(rf"^{re.escape(target)}:.*\n((?:\t.*\n)+)", text, re.MULTILINE)
    assert match, f"{target} recipe not found in Makefile"
    return match.group(1)


def test_make_lint_operator_lists_go_files_from_the_root_for_git_dir() -> None:
    recipe = _make_recipe("readiness-lint-operator")
    listing = "git ls-files 'aragora-operator/*.go'"
    assert listing in recipe
    first_cd = recipe.index("cd aragora-operator")
    assert recipe.index(listing) < first_cd
    assert "git ls-files" not in recipe[first_cd:]
    assert 'echo "SKIP operator: go not found"; exit 0;' in recipe
    assert "readiness-lint-operator: no tracked Go files" in recipe
