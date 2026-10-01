"""Tests for scripts/ci/check_docs_reachability.py.

Every behavior test runs the real CLI as a subprocess against a throwaway
repository whose Markdown is git-indexed (``git add``, no commit). The child
environment is built from scratch: no inherited variables, so no credentials,
and git never reads the user's global or system configuration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_docs_reachability.py"

D2_KEYS = [
    "schema_version",
    "scope",
    "seeds",
    "candidate_count",
    "reachable_count",
    "reachable",
    "orphans",
    "orphan_count",
    "whole_tree_orphan_count",
]


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "en_US.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        # Stop git from discovering a repository above the fixture directory.
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def _git(root: Path, tmp_path: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, env=_env(tmp_path), check=True, capture_output=True, timeout=60
    )


def _repo(tmp_path: Path, files: dict[str, str], untracked: dict[str, str] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, files)
    _git(root, tmp_path, "init", "-q", "--template=")
    _git(root, tmp_path, "add", "-A")
    _write(root, untracked or {})
    return root


def _run(
    tmp_path: Path, *args: str, cwd: Path | None = None, script: Path = SCRIPT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd or tmp_path,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _report(tmp_path: Path, root: Path) -> tuple[int, dict]:
    proc = _run(tmp_path, "--root", str(root), "--scope", "curated", "--json")
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def _index(body: str) -> dict[str, str]:
    """Root README linking the docs index, plus the given docs index body."""
    return {"README.md": "# Root\n\nSee [docs](docs/README.md).\n", "docs/README.md": body}


def test_help_documents_scope_json_and_exit_codes(tmp_path: Path) -> None:
    proc = _run(tmp_path, "--help")
    assert proc.returncode == 0
    for needle in ("--scope", "curated", "--json", "--root", "README.md", "docs/README.md"):
        assert needle in proc.stdout, needle
    assert "exit" in proc.stdout.lower()


def test_invalid_scope_is_usage_error(tmp_path: Path) -> None:
    root = _repo(tmp_path, _index("# Docs\n"))
    proc = _run(tmp_path, "--root", str(root), "--scope", "everything", "--json")
    assert proc.returncode == 2
    assert "invalid choice" in proc.stderr
    assert proc.stdout == ""


def test_non_git_root_is_tool_error(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    _write(plain, _index("# Docs\n"))
    proc = _run(tmp_path, "--root", str(plain), "--scope", "curated", "--json")
    assert proc.returncode == 2
    assert "check_docs_reachability: error: git ls-files failed" in proc.stderr
    assert proc.stdout == ""


def test_fenced_and_inline_code_links_are_ignored(tmp_path: Path) -> None:
    body = (
        "# Docs\n\n"
        "```md\n[fenced](guides/fenced.md)\n```\n\n"
        "~~~\n[tilde](guides/tilde.md)\n```\nstill fenced [x](guides/tilde.md)\n~~~\n\n"
        "````\n```\n[nested](guides/nested.md)\n```\n````\n\n"
        "Inline `[code](guides/inline.md)` is not a link.\n\n"
        "After the fences: [real](guides/after.md).\n"
    )
    pages = {f"docs/guides/{n}.md": f"# {n}\n" for n in ("fenced", "tilde", "nested", "inline")}
    root = _repo(tmp_path, {**_index(body), **pages, "docs/guides/after.md": "# After\n"})
    rc, report = _report(tmp_path, root)
    assert rc == 1
    assert report["reachable"] == ["docs/README.md", "docs/guides/after.md"]
    assert report["orphans"] == sorted(pages)


def test_reference_links_fragments_and_external_targets(tmp_path: Path) -> None:
    body = (
        "# Docs\n\n"
        "[a](guides/a.md#intro), [b][ref], [same page](#local) and [shortcut].\n"
        "[web](https://example.com/docs/guides/ext.md) [mail](mailto:x@example.com)\n\n"
        '[ref]: ./guides/b.md "B title"\n'
        "[shortcut]: <guides/c.md>\n"
        "[^note]: guides/footnote.md\n"
    )
    pages = {f"docs/guides/{n}.md": f"# {n}\n" for n in ("a", "b", "c", "ext", "footnote")}
    root = _repo(tmp_path, {**_index(body), **pages})
    rc, report = _report(tmp_path, root)
    assert rc == 1
    assert report["reachable"] == [
        "docs/README.md",
        "docs/guides/a.md",
        "docs/guides/b.md",
        "docs/guides/c.md",
    ]
    assert report["orphans"] == ["docs/guides/ext.md", "docs/guides/footnote.md"]


def test_directory_links_resolve_to_readme_index(tmp_path: Path) -> None:
    body = "# Docs\n\n[reference](reference/) and [operations](./operations)\n"
    files = {
        "docs/reference/README.md": "# Reference\n",
        "docs/operations/README.md": "# Operations\n",
        "docs/strategy/README.md": "# Strategy\n",
    }
    root = _repo(tmp_path, {**_index(body), **files})
    rc, report = _report(tmp_path, root)
    assert rc == 1
    assert report["reachable"] == [
        "docs/README.md",
        "docs/operations/README.md",
        "docs/reference/README.md",
    ]
    assert report["orphans"] == ["docs/strategy/README.md"]


def test_parent_relative_titled_and_root_relative_links(tmp_path: Path) -> None:
    files = {
        **_index("# Docs\n\n[a](guides/a.md)\n"),
        "docs/guides/a.md": (
            "# A\n\n"
            '[c](../reference/c.md "C title") and [d](</docs/strategy/d plan.md>)\n'
            "[e](../governance/e%20rules.md 'E') and [escape](../../../outside.md)\n"
        ),
        "docs/reference/c.md": "# C\n",
        "docs/strategy/d plan.md": "# D\n",
        "docs/governance/e rules.md": "# E\n",
    }
    root = _repo(tmp_path, files)
    rc, report = _report(tmp_path, root)
    assert rc == 0
    assert report["orphans"] == []
    assert report["reachable"] == [
        "docs/README.md",
        "docs/governance/e rules.md",
        "docs/guides/a.md",
        "docs/reference/c.md",
        "docs/strategy/d plan.md",
    ]


def test_cycles_terminate_and_traversal_crosses_non_candidates(tmp_path: Path) -> None:
    files = {
        "README.md": "# Root\n\n[docs](docs/README.md) [contributing](CONTRIBUTING.md)\n",
        "CONTRIBUTING.md": "# Contributing\n\n[style](docs/guides/style.md)\n",
        "docs/README.md": "# Docs\n\n[deploy](deployment/x.md) [self](README.md)\n",
        "docs/deployment/x.md": "# X\n\n[y](../guides/y.md) [back](../README.md)\n",
        "docs/guides/y.md": "# Y\n\n[x](../deployment/x.md) [y](y.md)\n",
        "docs/guides/style.md": "# Style\n\n[root](../../README.md)\n",
    }
    root = _repo(tmp_path, files)
    rc, report = _report(tmp_path, root)
    assert rc == 0
    assert report["reachable"] == ["docs/README.md", "docs/guides/style.md", "docs/guides/y.md"]
    assert report["orphans"] == []
    assert report["whole_tree_orphan_count"] == 0


def test_untracked_markdown_is_neither_candidate_nor_traversed(tmp_path: Path) -> None:
    files = {**_index("# Docs\n\n[bridge](guides/bridge.md)\n"), "docs/guides/t.md": "# T\n"}
    untracked = {
        "docs/guides/bridge.md": "# Bridge\n\n[t](t.md)\n",
        "docs/guides/new.md": "# New\n",
    }
    root = _repo(tmp_path, files, untracked=untracked)
    rc, report = _report(tmp_path, root)
    assert rc == 1
    assert report["reachable"] == ["docs/README.md"]
    assert report["orphans"] == ["docs/guides/t.md"]


def test_archive_is_excluded_from_reports_and_traversal(tmp_path: Path) -> None:
    files = {
        **_index("# Docs\n\n[old](archive/old.md)\n"),
        "docs/archive/old.md": "# Old\n\n[via archive](../guides/only-archive.md)\n",
        "docs/archive/unlinked.md": "# Unlinked\n",
        "docs/guides/only-archive.md": "# Only archive\n",
    }
    root = _repo(tmp_path, files)
    rc, report = _report(tmp_path, root)
    assert rc == 1
    assert report["orphans"] == ["docs/guides/only-archive.md"]
    assert not any(p.startswith("docs/archive/") for p in report["reachable"] + report["orphans"])
    assert report["whole_tree_orphan_count"] == 1


def test_schema_partition_and_deterministic_output(tmp_path: Path) -> None:
    files = {
        **_index(
            "# Docs\n\n[g](guides/sub/deep.md) [ops](deployment/ops.md) [n](guides/notes.txt)\n"
        ),
        "docs/OVERVIEW.md": "# Overview\n",
        "docs/guides/sub/deep.md": "# Deep\n",
        "docs/reference/api.md": "# API\n",
        "docs/deployment/ops.md": "# Ops\n",
        "docs/deployment/lost.md": "# Lost\n",
        "docs/guides/notes.txt": "[x](../OVERVIEW.md)\n",
    }
    root = _repo(tmp_path, files)
    first = _run(tmp_path, "--root", str(root), "--scope", "curated", "--json")
    second = _run(tmp_path, "--root", str(root), "--scope", "curated", "--json")
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert list(report) == D2_KEYS
    assert report["schema_version"] == 1
    assert report["scope"] == "curated"
    assert report["seeds"] == ["README.md", "docs/README.md"]
    assert report["reachable"] == ["docs/README.md", "docs/guides/sub/deep.md"]
    assert report["orphans"] == ["docs/OVERVIEW.md", "docs/reference/api.md"]
    assert report["reachable_count"] == 2
    assert report["orphan_count"] == 2
    assert report["candidate_count"] == 4
    # Curated orphans plus the unreached non-curated docs/deployment/lost.md.
    assert report["whole_tree_orphan_count"] == 3


def test_human_output_names_orphans(tmp_path: Path) -> None:
    root = _repo(tmp_path, {**_index("# Docs\n"), "docs/guides/lonely.md": "# Lonely\n"})
    proc = _run(tmp_path, "--root", str(root))
    assert proc.returncode == 1
    assert "docs/guides/lonely.md" in proc.stdout
    assert "whole-tree" in proc.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(proc.stdout)


def test_validator_fixture_two_orphans_then_zero(tmp_path: Path) -> None:
    """Independent link-model fixture: the shipped CLI copied into a fresh repo."""
    files = {
        "README.md": (
            "# Root\n\nSee [docs](docs/README.md).\n\n"
            "```\n[not a link](docs/guides/codeonly.md)\n```\n"
        ),
        "docs/README.md": (
            "# Index\n\n[a](guides/a.md#intro) and [b][ref] and [ref dir](reference/)\n\n"
            "[ref]: ./guides/b.md\n"
        ),
        "docs/guides/a.md": '# A\n\n## Intro\n\n[c](../reference/c.md "title")\n',
        "docs/guides/b.md": "# B\n",
        "docs/guides/codeonly.md": "# Only linked from a fence\n",
        "docs/guides/orphan.md": "# Orphan\n",
        "docs/reference/README.md": "# Ref index\n",
        "docs/reference/c.md": "# C\n",
        "docs/archive/old.md": "# Old\n",
    }
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "ci" / SCRIPT.name)
    _write(root, files)
    _git(root, tmp_path, "init", "-q", "--template=")
    _git(root, tmp_path, "add", "-A")
    # Relative path, resolved against cwd: no --root, so the default root is exercised.
    shipped = Path("scripts/ci/check_docs_reachability.py")
    args = ("--scope", "curated", "--json")

    first = _run(tmp_path, *args, cwd=root, script=shipped)
    assert first.returncode == 1, first.stderr
    report = json.loads(first.stdout)
    assert report["orphans"] == ["docs/guides/codeonly.md", "docs/guides/orphan.md"]
    for page in ("a.md", "b.md"):
        assert f"docs/guides/{page}" in report["reachable"]
    assert {"docs/reference/README.md", "docs/reference/c.md"} <= set(report["reachable"])
    assert not any("archive" in p for p in report["reachable"] + report["orphans"])

    # -f: without a commit, git rm refuses to drop files that are only staged.
    _git(root, tmp_path, "rm", "-q", "-f", "docs/guides/codeonly.md", "docs/guides/orphan.md")
    second = _run(tmp_path, *args, cwd=root, script=shipped)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["orphan_count"] == 0
