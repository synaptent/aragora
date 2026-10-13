"""The codebase context builder, repository profile and codebase summary live in ``aragora.rlm``.

``aragora.rlm.codebase_context`` (domain layer) extends the context builder. The three modules
used to live in ``aragora.nomic`` (application layer) and import nothing above the domain layer,
so they now sit in the rlm package. The old ``aragora.nomic`` paths re-export the same objects.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MOVES = {
    "aragora.nomic.context_builder": (
        "aragora.rlm.context_builder",
        "CodebaseIndex IndexedFile MAX_FILE_SIZE NomicContextBuilder SKIP_DIRS "
        "SOURCE_EXTENSIONS".split(),
    ),
    "aragora.nomic.repository_profile": (
        "aragora.rlm.repository_profile",
        "ContextEvidenceReference ContextPack DEFAULT_EVALUATION_CRITERIA EvaluationCriterion "
        "NomicProfileError NomicRepositoryProfile RepositoryRevision RepositoryStateError "
        "assert_clean_revision http_permalink infer_repository_id load_nomic_repository_profile "
        "normalize_remote_url portable_evidence_uri validate_repository_path".split(),
    ),
    "aragora.nomic.rlm_codebase": (
        "aragora.rlm.codebase_summary",
        "CodebaseCorpus CodebaseRLMResult build_codebase_corpus summarize_codebase_with_rlm".split(),
    ),
}
CASES = [(old, new, name) for old, (new, names) in MOVES.items() for name in names]
PROFILE_PATHS = ["aragora.nomic.repository_profile", "aragora.rlm.repository_profile"]
SUMMARY_PATHS = ["aragora.nomic.rlm_codebase", "aragora.rlm.codebase_summary"]


@pytest.mark.parametrize(("old", "new", "name"), CASES)
def test_the_old_path_is_the_same_object(old, new, name):
    assert getattr(importlib.import_module(old), name) is getattr(
        importlib.import_module(new), name
    )


@pytest.mark.parametrize(("old", "new"), [(old, new) for old, (new, _) in MOVES.items()])
def test_the_modules_are_defined_in_the_rlm_package(old, new):
    module = importlib.import_module(new)
    names = MOVES[old][1]
    classes = [getattr(module, name) for name in names if isinstance(getattr(module, name), type)]
    assert classes and all(cls.__module__ == new for cls in classes)
    assert sorted(importlib.import_module(old).__all__) == sorted(names)


def test_the_codebase_context_builder_extends_the_moved_builder():
    from aragora.rlm.codebase_context import CodebaseContextBuilder

    builder = importlib.import_module("aragora.rlm.context_builder").NomicContextBuilder
    assert issubclass(CodebaseContextBuilder, builder)


@pytest.mark.parametrize("module_name", PROFILE_PATHS)
def test_remote_urls_normalize_the_same_through_both_paths(module_name):
    module = importlib.import_module(module_name)
    remote = "git@github.com:synaptent/aragora.git"
    assert module.normalize_remote_url(remote) == "https://github.com/synaptent/aragora"
    assert module.infer_repository_id(remote, "fallback") == "synaptent/aragora"
    assert module.infer_repository_id("/srv/repo", "fallback") == "fallback"


@pytest.mark.parametrize("module_name", PROFILE_PATHS)
def test_traversal_is_rejected_with_the_same_error_through_both_paths(module_name):
    module = importlib.import_module(module_name)
    other = importlib.import_module(PROFILE_PATHS[1 - PROFILE_PATHS.index(module_name)])
    assert module.validate_repository_path("aragora/rlm/bridge.py") == "aragora/rlm/bridge.py"
    with pytest.raises(other.NomicProfileError):
        module.validate_repository_path("../outside.py")


@pytest.mark.parametrize("module_name", SUMMARY_PATHS)
def test_a_cached_corpus_loads_the_same_through_both_paths(module_name, tmp_path):
    module = importlib.import_module(module_name)
    manifest = {"file_count": 3, "total_bytes": 120, "estimated_tokens": 30, "top_dirs": {"a": 3}}
    (tmp_path / "codebase_corpus.txt").write_text("### FILE: a/b.py\n", encoding="utf-8")
    (tmp_path / "codebase_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    corpus = asyncio.run(module.build_codebase_corpus(tmp_path, tmp_path, max_content_bytes=1000))
    assert isinstance(corpus, importlib.import_module(SUMMARY_PATHS[1]).CodebaseCorpus)
    assert (corpus.file_count, corpus.total_bytes, corpus.top_dirs) == (3, 120, {"a": 3})


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call) and node.args:
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if callee in {"import_module", "__import__"}:
                found.append((node.lineno, ast.unparse(node.args[0]).strip("'\"")))
    return found


def test_rlm_holds_no_import_of_nomic_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "rlm").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.nomic" or name.startswith("aragora.nomic.")
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("module_name", "allowed"),
    [
        (
            "aragora.rlm.context_builder",
            {
                "aragora.rlm",
                "aragora.rlm.bridge",
                "aragora.rlm.codebase_summary",
                "aragora.rlm.repository_profile",
                "aragora.rlm.types",
            },
        ),
        ("aragora.rlm.repository_profile", set()),
        (
            "aragora.rlm.codebase_summary",
            {"aragora.analysis.codebase.repository_crawler", "aragora.rlm", "aragora.rlm.types"},
        ),
    ],
)
def test_the_homes_import_only_the_domain_layer_and_below(module_name, allowed):
    path = Path(importlib.import_module(module_name).__file__)
    imported = {name for _, name in _imported_modules(path) if name.startswith("aragora")}
    assert imported == allowed
