"""
Context Builder: TRUE RLM-powered codebase context for Nomic loop.

Uses TRUE RLM (REPL-based recursive language models) to build queryable
codebase context that supports up to 10M tokens. Instead of stuffing
the entire codebase into a prompt, agents can programmatically query
and explore the context through REPL commands.

This replaces the shallow summary-based context gathering with deep,
searchable codebase comprehension.

Key features:
- Indexes the full codebase as a hierarchical RLM context
- Supports REPL-based queries (grep, partition_map, peek)
- Integrates with Knowledge Mound for semantic search
- Scales to 10M+ token codebases

Usage:
    from aragora.nomic.context_builder import NomicContextBuilder

    builder = NomicContextBuilder(aragora_path=Path("."))
    context = await builder.build_context()

    # Agents query the context via RLM
    result = await builder.query("What modules handle authentication?")
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aragora.nomic.repository_profile import (
    ContextEvidenceReference,
    ContextPack,
    NomicRepositoryProfile,
    RepositoryRevision,
    RepositoryStateError,
    assert_clean_revision,
    http_permalink,
    load_nomic_repository_profile,
    portable_evidence_uri,
)

logger = logging.getLogger(__name__)

# File extensions to index
SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".md",
    ".rst",
    ".txt",
}

# Directories to skip
SKIP_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
}

# Maximum file size to index (1MB per file)
MAX_FILE_SIZE = 1_000_000


@dataclass
class CodebaseIndex:
    """Index of the codebase for RLM context building."""

    root_path: Path
    files: list[IndexedFile] = field(default_factory=list)
    total_bytes: int = 0
    total_files: int = 0
    total_lines: int = 0
    build_time_seconds: float = 0.0

    @property
    def total_tokens_estimate(self) -> int:
        """Estimate total tokens (rough: 1 token per 4 bytes)."""
        return self.total_bytes // 4

    def get_file(self, path: str) -> IndexedFile | None:
        """Get an indexed file by relative path."""
        for f in self.files:
            if f.relative_path == path:
                return f
        return None

    def search_files(self, pattern: str) -> list[IndexedFile]:
        """Search files by path pattern (simple substring match)."""
        pattern_lower = pattern.lower()
        return [f for f in self.files if pattern_lower in f.relative_path.lower()]


@dataclass
class IndexedFile:
    """A file indexed for RLM context."""

    relative_path: str
    size_bytes: int
    line_count: int
    extension: str
    module_path: str = ""  # Python module path (e.g., aragora.debate.protocol)

    @property
    def token_estimate(self) -> int:
        """Estimate token count."""
        return self.size_bytes // 4


class NomicContextBuilder:
    """
    Builds TRUE RLM-powered codebase context for Nomic loop debates.

    Instead of feeding agents a shallow summary, this builder creates
    a searchable, hierarchical representation of the entire codebase
    that agents can query via REPL commands.

    Supports context windows up to 10M tokens by using the RLM's
    recursive decomposition strategy - agents never see the full
    context at once, but can drill into any part of it.
    """

    def __init__(
        self,
        aragora_path: Path,
        max_context_bytes: int = 0,
        include_tests: bool | None = None,
        knowledge_mound: Any | None = None,
        full_corpus: bool | None = None,
    ) -> None:
        self._aragora_path = aragora_path
        env_max = os.environ.get("ARAGORA_NOMIC_MAX_CONTEXT_BYTES") or os.environ.get(
            "NOMIC_MAX_CONTEXT_BYTES"
        )
        if env_max is None:
            env_max = os.environ.get("ARAGORA_RLM_MAX_CONTENT_BYTES")
        default_max = 100_000_000
        try:
            from aragora.rlm import RLMConfig

            default_max = RLMConfig().max_content_bytes_nomic
        except (ImportError, RuntimeError, ValueError) as e:
            logger.debug("Failed to load RLMConfig for max_content_bytes_nomic: %s", e)
        self._max_context_bytes = max_context_bytes or int(env_max or default_max)
        if include_tests is None:
            self._include_tests = os.environ.get("NOMIC_INCLUDE_TESTS", "1") == "1"
        else:
            self._include_tests = include_tests
        self._knowledge_mound = knowledge_mound
        if full_corpus is None:
            self._full_corpus = os.environ.get("NOMIC_RLM_FULL_CORPUS", "1") == "1"
        else:
            self._full_corpus = full_corpus
        self._index: CodebaseIndex | None = None
        self._rlm_context: Any | None = None
        self._pending_pack_verification: (
            tuple[str, tuple[ContextEvidenceReference, ...], dict[str, bytes]] | None
        ) = None
        self._context_dir = self._aragora_path / ".nomic" / "context"

    @property
    def index(self) -> CodebaseIndex | None:
        """Get the current codebase index."""
        return self._index

    async def build_index(self) -> CodebaseIndex:
        """
        Scan and index the codebase.

        Returns a CodebaseIndex with file metadata (not content) for
        efficient querying. Content is loaded on-demand via RLM.
        """
        if self._index is not None:
            return self._index

        manifest_path = self._context_dir / "codebase_manifest.tsv"
        use_manifest = os.environ.get("ARAGORA_CONTEXT_USE_MANIFEST") or os.environ.get(
            "NOMIC_CONTEXT_USE_MANIFEST"
        )
        if use_manifest is None:
            use_manifest = "1"

        tracked_paths: list[Path] | None = None
        try:
            probe = subprocess.run(
                ["git", "-C", str(self._aragora_path), "rev-parse", "--show-toplevel"],
                capture_output=True,
                check=False,
            )
            git_root = (
                Path(os.fsdecode(probe.stdout.strip())).resolve()
                if probe.returncode == 0 and probe.stdout.strip()
                else None
            )
            if git_root == self._aragora_path.resolve():
                tracked = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._aragora_path),
                        "ls-files",
                        "-z",
                        "--cached",
                    ],
                    capture_output=True,
                    check=False,
                )
                if tracked.returncode == 0:
                    candidates = [
                        self._aragora_path / raw.decode("utf-8", errors="surrogateescape")
                        for raw in tracked.stdout.split(b"\0")
                        if raw
                    ]
                    if candidates:
                        tracked_paths = candidates
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
            logger.debug("Git tracked-file enumeration unavailable; using legacy fallback: %s", exc)

        if tracked_paths is None and use_manifest.strip().lower() in {"1", "true", "yes", "on"}:
            manifest_index = self._load_manifest_index(manifest_path)
            if manifest_index is not None:
                self._index = manifest_index
                return self._index

        start = time.monotonic()
        files: list[IndexedFile] = []
        total_bytes = 0

        paths = (
            tracked_paths if tracked_paths is not None else sorted(self._aragora_path.rglob("*"))
        )

        for path in paths:
            if not path.is_file():
                continue
            if path.suffix not in SOURCE_EXTENSIONS:
                continue
            relative_path = path.relative_to(self._aragora_path)
            if any(skip in path.parts for skip in SKIP_DIRS):
                continue
            if not self._include_tests and any(
                part in {"test", "tests"} for part in relative_path.parts
            ):
                continue
            if path.stat().st_size > MAX_FILE_SIZE:
                continue

            rel_path = str(relative_path)
            size = path.stat().st_size

            # Count lines efficiently
            try:
                with open(path, "rb") as handle:
                    line_count = sum(1 for _ in handle)
            except (OSError, UnicodeDecodeError):
                continue

            # Derive Python module path
            module_path = ""
            if path.suffix == ".py":
                module_path = (
                    rel_path.replace("/", ".")
                    .replace("\\", ".")
                    .removesuffix(".py")
                    .removesuffix(".__init__")
                )

            files.append(
                IndexedFile(
                    relative_path=rel_path,
                    size_bytes=size,
                    line_count=line_count,
                    extension=path.suffix,
                    module_path=module_path,
                )
            )
            total_bytes += size

        elapsed = time.monotonic() - start
        self._index = CodebaseIndex(
            root_path=self._aragora_path,
            files=files,
            total_bytes=total_bytes,
            total_files=len(files),
            total_lines=sum(f.line_count for f in files),
            build_time_seconds=elapsed,
        )

        logger.info(
            "Codebase indexed: %d files, %d lines, ~%dK tokens in %.1fs",
            self._index.total_files,
            self._index.total_lines,
            self._index.total_tokens_estimate // 1000,
            elapsed,
        )
        return self._index

    def _write_manifest(self) -> Path | None:
        """Write a lightweight manifest for REPL-based context access."""
        if self._index is None:
            return None

        manifest_path = self._context_dir / "codebase_manifest.tsv"
        try:
            self._context_dir.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("w", encoding="utf-8") as handle:
                handle.write(
                    f"# Aragora codebase manifest\n"
                    f"# root={self._index.root_path}\n"
                    f"# files={self._index.total_files} lines={self._index.total_lines}\n"
                    f"# format=path\\tlines\\tbytes\\textension\\tmodule\n"
                )
                for f in self._index.files:
                    handle.write(
                        f"{f.relative_path}\t{f.line_count}\t{f.size_bytes}\t"
                        f"{f.extension}\t{f.module_path}\n"
                    )
            return manifest_path
        except OSError as exc:
            logger.warning("Failed to write manifest: %s", exc)
            return None

    async def build_context_pack(
        self,
        objective: str = "",
        *,
        profile: NomicRepositoryProfile | None = None,
        config_path: Path | None = None,
    ) -> ContextPack:
        """Build and atomically publish a clean, commit-addressed planning context pack."""
        root = self._aragora_path.resolve()
        if self._max_context_bytes <= 0:
            raise RepositoryStateError("context pack byte budget must be a positive integer")
        runtime_root = root / ".nomic" / "context" / "packs"
        self._assert_pack_destination_safe(root, runtime_root)
        revision = assert_clean_revision(root)
        normalized_objective = objective.strip()
        resolved_profile = profile or load_nomic_repository_profile(root, config_path)
        resolved_profile.validate_files(root, revision)

        evidence, contents = self._collect_commit_evidence(resolved_profile, revision)
        self._index = self._index_from_evidence(root, evidence)
        manifest = self._render_pack_manifest(revision, resolved_profile, evidence)
        corpus, corpus_truncated = self._render_pack_corpus(evidence, contents)
        rlm_summary = await self._build_pack_rlm_summary(corpus, resolved_profile)
        context = self._render_pack_context(
            normalized_objective,
            resolved_profile,
            revision,
            evidence,
            contents,
            rlm_summary,
            corpus_truncated,
        )

        artifacts: dict[str, bytes] = {
            "context.md": context.encode(),
            "manifest.tsv": manifest.encode(),
        }
        if self._full_corpus:
            artifacts["corpus.txt"] = corpus.encode()
        digests = {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}
        pack_id = self._compute_pack_id(
            normalized_objective,
            resolved_profile,
            revision,
            digests,
            include_tests=self._include_tests,
        )
        destination = root / ".nomic" / "context" / "packs" / revision.commit_sha / pack_id
        self._assert_pack_destination_safe(root, destination)
        relative_destination = destination.relative_to(root).as_posix()
        artifact_names = [*artifacts, "context-pack.json"]
        self._assert_artifact_paths_ignored(
            root,
            [f"{relative_destination}/{name}" for name in artifact_names],
        )
        pack = ContextPack(
            pack_id=pack_id,
            objective=normalized_objective,
            repository=resolved_profile,
            revision=revision,
            profile_hash=resolved_profile.profile_hash,
            evidence=tuple(evidence),
            artifact_digests=digests,
            pack_path=destination,
            corpus_included=self._full_corpus,
            corpus_truncated=corpus_truncated,
            context_byte_budget=self._max_context_bytes,
            include_tests=self._include_tests,
            rlm_summary=rlm_summary,
        )
        metadata = (json.dumps(pack.to_dict(), sort_keys=True, indent=2) + "\n").encode()

        if destination.exists():
            self.verify_context_pack(pack)
            return pack

        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._assert_pack_destination_safe(root, destination)
        temporary = Path(tempfile.mkdtemp(prefix=f".{pack_id}.", dir=parent))
        try:
            for name, data in artifacts.items():
                (temporary / name).write_bytes(data)
            (temporary / "context-pack.json").write_bytes(metadata)
            self._before_pack_publish()
            assert_clean_revision(root, revision)
            self._assert_pack_destination_safe(root, destination)
            try:
                os.replace(temporary, destination)
            except OSError:
                self._assert_pack_destination_safe(root, destination)
                if not destination.exists():
                    raise
            self._pending_pack_verification = (pack.pack_id, tuple(evidence), contents)
            try:
                self.verify_context_pack(pack)
            finally:
                self._pending_pack_verification = None
        finally:
            self._cleanup_temporary_pack(root, parent, temporary)
        return pack

    @staticmethod
    def _assert_pack_destination_safe(repo_root: Path, destination: Path) -> None:
        """Reject symlinked, non-directory, or repository-escaping pack paths."""
        root = repo_root.resolve()
        try:
            relative = destination.relative_to(root)
        except ValueError as exc:
            raise RepositoryStateError("context pack destination escapes repository root") from exc
        if not relative.parts or relative.parts[0] != ".nomic":
            raise RepositoryStateError("context pack destination must be beneath .nomic")

        current = root
        for part in relative.parts:
            current /= part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError) as exc:
                raise RepositoryStateError(
                    f"context pack destination cannot be inspected: {current}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise RepositoryStateError(
                    f"context pack destination contains a symlink: {current}"
                )
            if not stat.S_ISDIR(mode):
                raise RepositoryStateError(
                    f"context pack destination contains a non-directory component: {current}"
                )

        try:
            destination.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RepositoryStateError("context pack destination escapes repository root") from exc

    @classmethod
    def _cleanup_temporary_pack(cls, repo_root: Path, parent: Path, temporary: Path) -> None:
        """Remove only a real temporary directory beneath the validated pack parent."""
        if not os.path.lexists(temporary):
            return
        cls._assert_pack_destination_safe(repo_root, temporary)
        try:
            resolved_parent = parent.resolve(strict=True)
            resolved_temporary = temporary.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RepositoryStateError("temporary context pack path cannot be resolved") from exc
        if resolved_temporary.parent != resolved_parent or not temporary.is_dir():
            raise RepositoryStateError("temporary context pack path is not safe to remove")
        shutil.rmtree(temporary)

    @staticmethod
    def _assert_artifact_paths_ignored(repo_root: Path, paths: list[str]) -> None:
        """Fail unless every concrete runtime artifact is untracked and ignored."""
        for path in paths:
            tracked = subprocess.run(
                ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", path],
                capture_output=True,
                check=False,
            )
            if tracked.returncode == 0:
                raise RepositoryStateError(f"runtime artifact path is tracked by Git: {path}")
            ignored = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "check-ignore",
                    "--quiet",
                    "--no-index",
                    "--",
                    path,
                ],
                capture_output=True,
                check=False,
            )
            if ignored.returncode != 0:
                raise RepositoryStateError(
                    f"repository must ignore .nomic runtime artifact path {path!r}; add '.nomic/' "
                    "to .gitignore or a local Git exclude"
                )

    def verify_context_pack(self, pack: ContextPack) -> None:
        """Verify metadata, content address, manifest, and bound artifact digests."""
        expected_path = (
            self._aragora_path.resolve()
            / ".nomic"
            / "context"
            / "packs"
            / pack.revision.commit_sha
            / pack.pack_id
        )
        if pack.pack_path.resolve() != expected_path:
            raise RepositoryStateError("context pack path does not match its content address")
        if pack.profile_hash != pack.repository.profile_hash:
            raise RepositoryStateError("context pack profile hash does not match its profile")
        if not isinstance(pack.context_byte_budget, int) or pack.context_byte_budget <= 0:
            raise RepositoryStateError("context pack byte budget must be a positive integer")
        if not isinstance(pack.include_tests, bool):
            raise RepositoryStateError("context pack test-inclusion policy must be boolean")
        required_artifacts = {"context.md", "manifest.tsv"}
        if pack.corpus_included:
            required_artifacts.add("corpus.txt")
        if set(pack.artifact_digests) != required_artifacts:
            raise RepositoryStateError("context pack artifact inventory is invalid")

        metadata_path = pack.pack_path / "context-pack.json"
        if not metadata_path.is_file():
            raise RepositoryStateError(f"context pack metadata is missing: {pack.reference}")
        expected_entries = required_artifacts | {"context-pack.json"}
        try:
            actual_entries = list(pack.pack_path.iterdir())
        except OSError as exc:
            raise RepositoryStateError(
                f"context pack directory cannot be inspected: {pack.reference}"
            ) from exc
        if {entry.name for entry in actual_entries} != expected_entries or any(
            not entry.is_file() or entry.is_symlink() for entry in actual_entries
        ):
            raise RepositoryStateError("context pack directory contains unexpected artifacts")
        try:
            stored = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RepositoryStateError(f"invalid context pack metadata: {pack.reference}") from exc
        if stored != pack.to_dict():
            raise RepositoryStateError(f"context pack metadata mismatch: {pack.reference}")
        pending = self._pending_pack_verification
        if pending is not None and pending[0] == pack.pack_id:
            expected_evidence = list(pending[1])
            contents = pending[2]
        else:
            expected_evidence, contents = self._collect_commit_evidence(
                pack.repository,
                pack.revision,
                include_tests=pack.include_tests,
            )
        if tuple(expected_evidence) != pack.evidence:
            raise RepositoryStateError(
                "context pack evidence does not match the claimed Git revision"
            )
        self._index = self._index_from_evidence(self._aragora_path.resolve(), expected_evidence)
        expected_corpus, corpus_truncated = self._render_pack_corpus(
            expected_evidence,
            contents,
            max_context_bytes=pack.context_byte_budget,
        )
        if corpus_truncated != pack.corpus_truncated:
            raise RepositoryStateError("context pack corpus truncation metadata is invalid")
        expected_rlm_summary = self._render_pack_rlm_summary(
            expected_corpus,
            pack.repository,
        )
        if pack.rlm_summary != expected_rlm_summary:
            raise RepositoryStateError(
                "context pack RLM summary does not match verified Git evidence"
            )
        expected_manifest = self._render_pack_manifest(
            pack.revision,
            pack.repository,
            expected_evidence,
        ).encode()
        manifest_path = pack.pack_path / "manifest.tsv"
        if not manifest_path.is_file() or manifest_path.read_bytes() != expected_manifest:
            raise RepositoryStateError("context pack manifest does not match its evidence metadata")
        for name, expected in pack.artifact_digests.items():
            path = pack.pack_path / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RepositoryStateError(f"context pack artifact verification failed: {name}")
        expected_context = self._render_pack_context(
            pack.objective,
            pack.repository,
            pack.revision,
            expected_evidence,
            contents,
            expected_rlm_summary,
            corpus_truncated,
            context_byte_budget=pack.context_byte_budget,
            full_corpus=pack.corpus_included,
        ).encode()
        if (pack.pack_path / "context.md").read_bytes() != expected_context:
            raise RepositoryStateError("context pack context does not match verified Git evidence")
        if pack.corpus_included and (pack.pack_path / "corpus.txt").read_bytes() != (
            expected_corpus.encode()
        ):
            raise RepositoryStateError("context pack corpus does not match verified Git evidence")
        expected_pack_id = self._compute_pack_id(
            pack.objective,
            pack.repository,
            pack.revision,
            pack.artifact_digests,
            include_tests=pack.include_tests,
        )
        if expected_pack_id != pack.pack_id:
            raise RepositoryStateError("context pack identifier does not match bound artifacts")

    @staticmethod
    def _compute_pack_id(
        objective: str,
        profile: NomicRepositoryProfile,
        revision: RepositoryRevision,
        artifact_digests: Any,
        *,
        include_tests: bool,
    ) -> str:
        """Compute the portable content address shared by build and verification."""
        digests = dict(sorted(dict(artifact_digests).items()))
        pack_basis = {
            "objective": objective,
            "repository_id": profile.repository_id,
            "revision": revision.to_dict(),
            "profile_hash": profile.profile_hash,
            "include_tests": include_tests,
            "manifest_digest": digests["manifest.tsv"],
            "artifact_digests": digests,
        }
        return hashlib.sha256(
            json.dumps(pack_basis, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _collect_commit_evidence(
        self,
        profile: NomicRepositoryProfile,
        revision: RepositoryRevision,
        *,
        include_tests: bool | None = None,
    ) -> tuple[list[ContextEvidenceReference], dict[str, bytes]]:
        resolved_include_tests = self._include_tests if include_tests is None else include_tests
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self._aragora_path),
                "ls-tree",
                "-r",
                "-z",
                "-l",
                "--full-tree",
                revision.commit_sha,
            ],
            capture_output=True,
            check=True,
        )
        configured = set(profile.roadmap_paths) | set(profile.context_entry_files)
        rows: list[tuple[str, str, int]] = []
        for raw in result.stdout.split(b"\0"):
            if not raw or b"\t" not in raw:
                continue
            metadata, raw_path = raw.split(b"\t", 1)
            _mode, object_type, blob_id, raw_size = metadata.decode().split()
            path = raw_path.decode("utf-8", errors="surrogateescape")
            if object_type != "blob" or raw_size == "-":
                continue
            size = int(raw_size)
            if path in configured and size > MAX_FILE_SIZE:
                raise RepositoryStateError(
                    "configured Nomic evidence file exceeds the "
                    f"{MAX_FILE_SIZE}-byte limit: {path} ({size} bytes)"
                )
            parts = tuple(part for part in path.replace("\\", "/").split("/") if part)
            include = path in configured or (
                Path(path).suffix in SOURCE_EXTENSIONS
                and not any(part in SKIP_DIRS for part in parts)
                and (resolved_include_tests or not any(part in {"test", "tests"} for part in parts))
                and size <= MAX_FILE_SIZE
            )
            if include:
                rows.append((path, blob_id, size))

        evidence: list[ContextEvidenceReference] = []
        sorted_rows = sorted(rows)
        contents = self._read_commit_blobs(sorted_rows)
        for path, blob_id, size in sorted_rows:
            data = contents[path]
            lines = data.count(b"\n") + int(bool(data) and not data.endswith(b"\n"))
            role = (
                "roadmap"
                if path in profile.roadmap_paths
                else "context_entry"
                if path in profile.context_entry_files
                else "source"
            )
            evidence_id = (
                "ev-"
                + hashlib.sha256(f"{revision.commit_sha}:{path}:{blob_id}".encode()).hexdigest()[
                    :20
                ]
            )
            evidence.append(
                ContextEvidenceReference(
                    evidence_id=evidence_id,
                    path=path,
                    blob_id=blob_id,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=size,
                    line_count=lines,
                    role=role,
                    uri=portable_evidence_uri(
                        profile.repository_id, revision.commit_sha, path, lines
                    ),
                    http_permalink=http_permalink(
                        profile.remote_url, revision.commit_sha, path, lines
                    ),
                )
            )
        return evidence, contents

    def _read_commit_blobs(self, rows: list[tuple[str, str, int]]) -> dict[str, bytes]:
        """Read a validated set of Git blobs through one batch object stream."""
        if not rows:
            return {}
        result = subprocess.run(
            ["git", "-C", str(self._aragora_path), "cat-file", "--batch"],
            input=b"".join(blob_id.encode("ascii") + b"\n" for _, blob_id, _ in rows),
            capture_output=True,
            check=True,
        )
        stream = io.BytesIO(result.stdout)
        contents: dict[str, bytes] = {}
        for path, expected_blob_id, expected_size in rows:
            fields = stream.readline().rstrip(b"\n").split()
            if len(fields) != 3:
                raise RepositoryStateError(f"invalid Git batch response for evidence file: {path}")
            try:
                actual_blob_id = fields[0].decode("ascii")
                object_type = fields[1].decode("ascii")
                actual_size = int(fields[2])
            except (UnicodeDecodeError, ValueError) as exc:
                raise RepositoryStateError(
                    f"invalid Git batch metadata for evidence file: {path}"
                ) from exc
            if (
                actual_blob_id != expected_blob_id
                or object_type != "blob"
                or actual_size != expected_size
            ):
                raise RepositoryStateError(
                    f"Git batch metadata does not match evidence manifest: {path}"
                )
            data = stream.read(expected_size)
            if len(data) != expected_size or stream.read(1) != b"\n":
                raise RepositoryStateError(
                    f"truncated Git batch response for evidence file: {path}"
                )
            contents[path] = data
        if stream.read():
            raise RepositoryStateError("Git batch response contains unexpected trailing data")
        return contents

    @staticmethod
    def _index_from_evidence(root: Path, evidence: list[ContextEvidenceReference]) -> CodebaseIndex:
        files = [
            IndexedFile(
                relative_path=item.path,
                size_bytes=item.size_bytes,
                line_count=item.line_count,
                extension=Path(item.path).suffix,
                module_path=item.path.replace("/", ".")
                .removesuffix(".py")
                .removesuffix(".__init__")
                if item.path.endswith(".py")
                else "",
            )
            for item in evidence
        ]
        return CodebaseIndex(
            root_path=root,
            files=files,
            total_bytes=sum(item.size_bytes for item in evidence),
            total_files=len(files),
            total_lines=sum(item.line_count for item in evidence),
        )

    def _render_pack_manifest(
        self,
        revision: RepositoryRevision,
        profile: NomicRepositoryProfile,
        evidence: list[ContextEvidenceReference],
    ) -> str:
        rows = [
            f"# commit={revision.commit_sha}",
            f"# profile_hash={profile.profile_hash}",
            "evidence_id\tpath\tblob_id\tsha256\tbytes\tlines\trole\turi\thttp_permalink",
        ]
        for item in evidence:
            if any(delimiter in item.path for delimiter in ("\t", "\n", "\r")):
                escaped_path = json.dumps(item.path, ensure_ascii=True)
                raise RepositoryStateError(
                    "tracked evidence path contains an unsupported manifest delimiter: "
                    f"{escaped_path}"
                )
            rows.append(
                "\t".join(
                    [
                        item.evidence_id,
                        item.path,
                        item.blob_id,
                        item.sha256,
                        str(item.size_bytes),
                        str(item.line_count),
                        item.role,
                        item.uri,
                        item.http_permalink or "",
                    ]
                )
            )
        return "\n".join(rows) + "\n"

    def _render_pack_corpus(
        self,
        evidence: list[ContextEvidenceReference],
        contents: dict[str, bytes],
        *,
        max_context_bytes: int | None = None,
    ) -> tuple[str, bool]:
        budget = self._max_context_bytes if max_context_bytes is None else max_context_bytes
        sections: list[str] = []
        used = 0
        truncated = False
        for item in sorted(evidence, key=lambda ref: (ref.role == "source", ref.path)):
            text = contents[item.path].decode("utf-8", errors="replace")
            section = f"\n--- {item.evidence_id} {item.path} ---\n{text}"
            remaining = budget - used
            if remaining <= 0:
                truncated = True
                break
            encoded = section.encode()
            if len(encoded) > remaining:
                section = encoded[:remaining].decode("utf-8", errors="ignore")
                truncated = True
            sections.append(section)
            used += len(section.encode())
            if truncated:
                break
        return "".join(sections).lstrip(), truncated

    async def _build_pack_rlm_summary(self, corpus: str, profile: NomicRepositoryProfile) -> str:
        """Build the independently verifiable map for RLM traversal of the corpus."""
        return self._render_pack_rlm_summary(corpus, profile)

    def _render_pack_rlm_summary(
        self,
        corpus: str,
        profile: NomicRepositoryProfile,
    ) -> str:
        """Render the deterministic RLM map from commit-derived evidence."""
        if self._index is None:
            return ""
        grouped: dict[str, list[IndexedFile]] = {}
        for item in self._index.files:
            parts = item.relative_path.split("/", 1)
            group = parts[0] if len(parts) > 1 else "root"
            grouped.setdefault(group, []).append(item)
        lines = [
            "The corpus is queryable by evidence marker (`--- ev-… path ---`) and path.",
            f"Corpus bytes available to the RLM: {len(corpus.encode())}",
            "Priority layers: " + ", ".join([*profile.roadmap_paths, *profile.context_entry_files])
            if profile.roadmap_paths or profile.context_entry_files
            else "Priority layers: none configured",
        ]
        for group in sorted(grouped):
            files = grouped[group]
            lines.append(
                f"- {group}/: {len(files)} files, "
                f"{sum(item.line_count for item in files)} lines, "
                f"{sum(item.size_bytes for item in files)} bytes"
            )
        return "\n".join(lines)

    def _render_pack_context(
        self,
        objective: str,
        profile: NomicRepositoryProfile,
        revision: RepositoryRevision,
        evidence: list[ContextEvidenceReference],
        contents: dict[str, bytes],
        rlm_summary: str,
        corpus_truncated: bool,
        *,
        context_byte_budget: int | None = None,
        full_corpus: bool | None = None,
    ) -> str:
        budget = self._max_context_bytes if context_byte_budget is None else context_byte_budget
        corpus_enabled = self._full_corpus if full_corpus is None else full_corpus
        by_path = {item.path: item for item in evidence}
        configured_paths = set(profile.roadmap_paths) | set(profile.context_entry_files)
        configured_covered = len(configured_paths & set(by_path))
        sections = [
            f"# {profile.repository_name} Repository Planning Context",
            f"Objective: {objective}",
            f"Repository: {profile.repository_id}",
            f"Commit: {revision.commit_sha}",
            f"Tree: {revision.tree_sha}",
            f"Profile: {profile.profile_hash}",
            "",
            "## Evaluation Criteria",
        ]
        sections.extend(
            f"- `{item.id}`: {item.description}" for item in profile.evaluation_criteria
        )
        for title, configured in (
            ("Roadmap", profile.roadmap_paths),
            ("Context Entry Files", profile.context_entry_files),
        ):
            sections.extend(["", f"## {title}"])
            for path in configured:
                reference = by_path[path]
                text = contents[path].decode("utf-8", errors="replace")
                sections.extend(
                    [
                        f"### {path} [{reference.evidence_id}]",
                        reference.uri,
                        text[:50000] + ("\n... (truncated)" if len(text) > 50000 else ""),
                    ]
                )
        sections.extend(["", "## Tracked-file Evidence Index"])
        sections.extend(
            f"- [{item.evidence_id}] {item.path} ({item.line_count} lines, {item.role}) {item.uri}"
            for item in evidence
        )
        sections.extend(
            [
                "",
                "## RLM Corpus Map",
                rlm_summary
                or "No generated summary; use the evidence index and corpus map directly.",
                "",
                "## Budgets and Coverage",
                f"- Included evidence files: {len(evidence)}",
                f"- Configured evidence coverage: {configured_covered}/{len(configured_paths)}"
                if configured_paths
                else "- Configured evidence coverage: no configured files",
                f"- Context byte budget: {budget}",
                f"- Full corpus enabled: {str(corpus_enabled).lower()}",
                f"- Corpus truncated: {str(corpus_truncated).lower()}",
            ]
        )
        return "\n".join(sections).rstrip() + "\n"

    def _before_pack_publish(self) -> None:
        """Test seam executed immediately before the final clean-revision check."""

    def _load_manifest_index(self, manifest_path: Path) -> CodebaseIndex | None:
        """Load an index from a previously written manifest."""
        if not manifest_path.exists():
            return None

        files: list[IndexedFile] = []
        total_bytes = 0
        total_lines = 0
        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip() or line.startswith("#"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 4:
                        continue
                    rel_path, line_count_raw, size_raw, extension = parts[:4]
                    module_path = parts[4] if len(parts) > 4 else ""
                    try:
                        line_count = int(line_count_raw)
                        size_bytes = int(size_raw)
                    except ValueError:
                        continue

                    files.append(
                        IndexedFile(
                            relative_path=rel_path,
                            size_bytes=size_bytes,
                            line_count=line_count,
                            extension=extension,
                            module_path=module_path,
                        )
                    )
                    total_bytes += size_bytes
                    total_lines += line_count
        except OSError as exc:
            logger.warning("Failed to read manifest index: %s", exc)
            return None

        if not files:
            return None

        return CodebaseIndex(
            root_path=self._aragora_path,
            files=files,
            total_bytes=total_bytes,
            total_files=len(files),
            total_lines=total_lines,
            build_time_seconds=0.0,
        )

    async def build_rlm_context(self) -> Any:
        """
        Build a TRUE RLM context from the codebase index.

        Uses the official RLM library's REPL-based approach when available,
        falling back to hierarchical compression otherwise.

        Returns an RLMContext that agents can query programmatically.
        """
        if self._index is None:
            await self.build_index()

        try:
            from aragora.rlm.bridge import AragoraRLM, HAS_OFFICIAL_RLM
            from aragora.rlm.types import RLMConfig, RLMMode

            require_true = os.environ.get("ARAGORA_NOMIC_RLM_REQUIRE_TRUE", "0") == "1"
            allow_compression = os.environ.get("ARAGORA_NOMIC_RLM_ALLOW_COMPRESSION", "0") == "1"
            if require_true and not HAS_OFFICIAL_RLM:
                raise RuntimeError("TRUE RLM required but official RLM library not installed")
            if not HAS_OFFICIAL_RLM and not allow_compression:
                logger.warning("RLM not available; skipping REPL context build")
                return None

            target_tokens = int(os.environ.get("ARAGORA_NOMIC_RLM_TARGET_TOKENS", "8000"))
            max_depth = int(os.environ.get("ARAGORA_NOMIC_RLM_MAX_DEPTH", "3"))
            max_sub_calls = int(os.environ.get("ARAGORA_NOMIC_RLM_MAX_SUB_CALLS", "20"))
            parallel_sub_calls = os.environ.get("ARAGORA_NOMIC_RLM_PARALLEL_SUB_CALLS", "1") == "1"

            config = RLMConfig(
                mode=RLMMode.TRUE_RLM if require_true else RLMMode.AUTO,
                prefer_true_rlm=True,
                max_content_bytes=self._max_context_bytes,
                target_tokens=target_tokens,
                max_depth=max_depth,
                max_sub_calls=max_sub_calls,
                parallel_sub_calls=parallel_sub_calls,
                cache_compressions=True,
            )

            rlm = AragoraRLM(aragora_config=config)

            # Build content from index (structure map + key files)
            content = self._build_structured_content()
            manifest_path = self._write_manifest()

            self._rlm_context = await rlm.build_context(
                content,
                source_type="codebase",
                source_root=str(self._index.root_path) if self._index else None,
                source_manifest=str(manifest_path) if manifest_path else None,
            )
            if getattr(self._rlm_context, "metadata", None) is not None:
                self._rlm_context.metadata.setdefault("context_dir", str(self._context_dir))
            logger.info(
                "RLM context built: %s mode",
                "TRUE RLM"
                if hasattr(rlm, "_official_rlm") and rlm._official_rlm
                else "compression",
            )
            return self._rlm_context

        except ImportError:
            logger.warning("RLM not available, using index-only context")
            return None

    async def query(self, question: str) -> str:
        """
        Query the codebase context using TRUE RLM.

        The agent's question is processed through the RLM's recursive
        decomposition - the model writes code to grep, peek, and
        partition the codebase to find the answer.
        """
        if self._rlm_context is not None:
            try:
                from aragora.rlm.bridge import AragoraRLM, HAS_OFFICIAL_RLM
                from aragora.rlm.types import RLMConfig, RLMMode

                require_true = os.environ.get("ARAGORA_NOMIC_RLM_REQUIRE_TRUE", "0") == "1"
                if require_true and not HAS_OFFICIAL_RLM:
                    raise RuntimeError("TRUE RLM required but official RLM library not installed")

                config = RLMConfig(
                    mode=RLMMode.TRUE_RLM if require_true else RLMMode.AUTO,
                    prefer_true_rlm=True,
                    max_content_bytes=self._max_context_bytes,
                )
                rlm = AragoraRLM(aragora_config=config)
                result = await rlm.query(question, self._rlm_context)
                return result.answer
            except (ImportError, RuntimeError, ValueError) as exc:
                logger.warning("RLM query failed, falling back to index search: %s", exc)

        # Fallback: search index
        return self._index_search(question)

    async def build_debate_context(self) -> str:
        """
        Build a structured context string for debate agents.

        This provides a navigable map of the codebase that agents can
        reference during structured debate rounds. For TRUE RLM agents,
        this also registers the context for REPL queries.

        Returns an empty string when the index contains no files (empty or
        nonexistent root), so callers can truthiness-check the result
        instead of receiving a header-only map.
        """
        if self._index is None:
            await self.build_index()
        if self._index is None:
            raise RuntimeError("Index not built - call build_index() first")

        if self._index.total_files == 0:
            logger.debug(
                "Skipping debate context: no files indexed under %s",
                self._index.root_path,
            )
            return ""

        sections = []
        sections.append(
            f"# Aragora Codebase Context ({self._index.total_files} files, "
            f"~{self._index.total_tokens_estimate // 1000}K tokens)"
        )
        sections.append(f"Repo root: {self._index.root_path}")
        manifest_path = self._write_manifest()
        if manifest_path:
            sections.append(f"Manifest: {manifest_path}")
        sections.append("")

        # Group files by top-level directory
        dirs: dict[str, list[IndexedFile]] = {}
        for f in self._index.files:
            parts = f.relative_path.split("/")
            top_dir = parts[0] if len(parts) > 1 else "root"
            dirs.setdefault(top_dir, []).append(f)

        for dir_name in sorted(dirs.keys()):
            files = dirs[dir_name]
            total_lines = sum(f.line_count for f in files)
            sections.append(f"## {dir_name}/ ({len(files)} files, {total_lines} lines)")
            # Show largest files
            for f in sorted(files, key=lambda x: x.size_bytes, reverse=True)[:10]:
                sections.append(f"  - {f.relative_path} ({f.line_count} lines)")
            if len(files) > 10:
                sections.append(f"  ... and {len(files) - 10} more files")
            sections.append("")

        # Add Knowledge Mound context if available
        if self._knowledge_mound is not None:
            try:
                km_context = await self._query_knowledge_mound()
                if km_context:
                    sections.append("## Knowledge Mound Context")
                    sections.append(km_context)
                    sections.append("")
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("Knowledge Mound query failed: %s", exc)

        # Optional: augment with full-corpus TRUE RLM summary (file-backed)
        if self._full_corpus:
            try:
                from aragora.nomic.rlm_codebase import summarize_codebase_with_rlm
                from aragora.rlm.bridge import HAS_OFFICIAL_RLM

                require_true_env = os.environ.get("NOMIC_RLM_REQUIRE_TRUE")
                if require_true_env is None:
                    require_true = HAS_OFFICIAL_RLM
                else:
                    require_true = require_true_env == "1"
                max_files = int(os.environ.get("NOMIC_RLM_MAX_FILES", "25000"))
                max_file_bytes = int(os.environ.get("NOMIC_RLM_MAX_FILE_BYTES", "2000000"))
                force_rebuild = os.environ.get("NOMIC_RLM_FORCE_REBUILD", "0") == "1"

                output_dir = self._aragora_path / ".nomic" / "rlm"
                result = await summarize_codebase_with_rlm(
                    repo_path=self._aragora_path,
                    output_dir=output_dir,
                    require_true_rlm=require_true,
                    max_content_bytes=self._max_context_bytes,
                    max_files=max_files,
                    max_file_bytes=max_file_bytes,
                    force_rebuild=force_rebuild,
                )

                if result.summary:
                    sections.append("## RLM Full-Corpus Summary (REPL)")
                    sections.append(result.summary)
                    sections.append("")
                    sections.append(f"Corpus: {result.corpus.corpus_path}")
                    sections.append(f"Manifest: {result.corpus.manifest_path}")
                    if result.corpus.truncated:
                        sections.append(
                            "Warning: corpus truncated to size cap; set NOMIC_MAX_CONTEXT_BYTES to increase."
                        )
                    sections.append("")
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("RLM full-corpus summary failed: %s", exc)

        # Add explicit feature inventory from CLAUDE.md
        feature_inventory = self._extract_feature_inventory()
        if feature_inventory:
            sections.append("## FEATURE INVENTORY FROM CLAUDE.md")
            sections.append(
                "The following features are ALREADY IMPLEMENTED. DO NOT propose recreating them."
            )
            sections.append(feature_inventory)
            sections.append("")

        return "\n".join(sections)

    def _extract_feature_inventory(self) -> str:
        """
        Extract feature inventory from CLAUDE.md for duplicate detection.

        Specifically extracts the Feature Status and Quick Reference sections
        to give agents a clear list of what already exists.
        """
        claude_md_path = self._aragora_path / "CLAUDE.md"
        if not claude_md_path.exists():
            return ""

        try:
            content = claude_md_path.read_text(errors="replace")
        except OSError:
            return ""

        features = []

        # Extract Quick Reference table
        if "## Quick Reference" in content:
            start = content.find("## Quick Reference")
            end = content.find("\n## ", start + 1)
            if end == -1:
                end = len(content)
            quick_ref = content[start:end]
            features.append(quick_ref)

        # Extract Feature Status section
        if "## Feature Status" in content:
            start = content.find("## Feature Status")
            end = content.find("\n## ", start + 1)
            if end == -1:
                end = len(content)
            status = content[start:end]
            features.append(status)

        # Extract "Core (stable)" and "Integrated" sections
        for section in [
            "**Core (stable):**",
            "**Integrated:**",
            "**Enterprise (production-ready):**",
        ]:
            if section in content:
                start = content.find(section)
                # Find end of list (next ** section or ##)
                end = len(content)
                for marker in ["**", "\n\n##"]:
                    next_marker = content.find(marker, start + len(section))
                    if next_marker != -1 and next_marker < end:
                        end = next_marker
                section_content = content[start:end].strip()
                if section_content:
                    features.append(f"\n### {section.strip('*:')}")
                    features.append(section_content)

        if not features:
            return ""

        return "\n\n".join(features)

    def _build_structured_content(self) -> str:
        """Build structured content string from the codebase index."""
        if self._index is None:
            return ""

        parts = []
        parts.append(
            f"CODEBASE: aragora ({self._index.total_files} files, {self._index.total_lines} lines)"
        )
        parts.append(f"REPO_ROOT: {self._index.root_path}")
        manifest_path = self._write_manifest()
        if manifest_path:
            parts.append(f"MANIFEST_PATH: {manifest_path}")
        parts.append("")

        # File tree
        parts.append("FILE TREE:")
        for f in sorted(self._index.files, key=lambda x: x.relative_path):
            parts.append(f"  {f.relative_path} [{f.line_count}L]")
        parts.append("")

        # Read key files inline (README, __init__, protocol, etc.)
        key_patterns = ["CLAUDE.md", "__init__.py", "protocol.py", "settings.py"]
        parts.append("KEY FILES CONTENT:")
        for f in self._index.files:
            if any(p in f.relative_path for p in key_patterns):
                try:
                    content = (self._index.root_path / f.relative_path).read_text(errors="replace")
                    parts.append(f"\n--- {f.relative_path} ---")
                    # Truncate large files
                    if len(content) > 50000:
                        content = content[:50000] + "\n... (truncated)"
                    parts.append(content)
                except OSError as e:
                    logger.debug("build structured content encountered an error: %s", e)

        return "\n".join(parts)

    def _index_search(self, question: str) -> str:
        """Simple keyword-based search over the index."""
        if self._index is None:
            return "No index available."

        keywords = question.lower().split()
        scored: list[tuple[int, IndexedFile]] = []

        for f in self._index.files:
            path_lower = f.relative_path.lower()
            module_lower = f.module_path.lower()
            score = sum(1 for kw in keywords if kw in path_lower or kw in module_lower)
            if score > 0:
                scored.append((score, f))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return "No matching files found."

        lines = [f"Found {len(scored)} relevant files:"]
        for score, f in scored[:20]:
            lines.append(f"  [{score}] {f.relative_path} ({f.line_count} lines)")
        return "\n".join(lines)

    async def _query_knowledge_mound(self) -> str:
        """Query Knowledge Mound for relevant context."""
        if self._knowledge_mound is None:
            return ""

        try:
            # Use RLM-powered query if available
            if hasattr(self._knowledge_mound, "query_with_true_rlm"):
                result = await self._knowledge_mound.query_with_true_rlm(
                    query="What are the most important recent insights about the codebase?",
                    limit=20,
                )
                if result:
                    return str(result.answer) if hasattr(result, "answer") else str(result)

            # Fallback to semantic query
            if hasattr(self._knowledge_mound, "query_semantic"):
                items = await self._knowledge_mound.query_semantic(
                    "codebase architecture improvements recent changes",
                    limit=20,
                )
                if items:
                    lines = []
                    for item in items[:10]:
                        title = getattr(item, "title", str(item))
                        lines.append(f"- {title}")
                    return "\n".join(lines)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("Knowledge Mound query error: %s", exc)

        return ""
