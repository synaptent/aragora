"""
Codebase Context Builder - shared RLM-powered codebase context.

Provides a non-Nomic wrapper around NomicContextBuilder so other
systems (agents, workflows, handlers) can reuse the 10M-token
codebase context pipeline without importing nomic directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aragora.rlm.context_builder import NomicContextBuilder


_MAX_CONTEXT_BYTES_ENV_VARS = (
    "ARAGORA_CODEBASE_MAX_CONTEXT_BYTES",
    "ARAGORA_NOMIC_MAX_CONTEXT_BYTES",
    "NOMIC_MAX_CONTEXT_BYTES",
    "ARAGORA_RLM_MAX_CONTEXT_BYTES",
    "ARAGORA_RLM_MAX_CONTENT_BYTES",
)


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _env_flag(name: str, default: str) -> bool:
    return os.environ.get(name, default) == "1"


class CodebaseContextBuilder(NomicContextBuilder):
    """
    Shared codebase context builder using TRUE RLM + REPL when available.

    This wrapper exposes more general env vars so the pipeline can be
    enabled across the codebase without tying callers to Nomic settings.
    """

    def __init__(
        self,
        root_path: Path,
        max_context_bytes: int = 0,
        include_tests: bool | None = None,
        knowledge_mound: Any | None = None,
        full_corpus: bool | None = None,
    ) -> None:
        env_max = _first_env_value(_MAX_CONTEXT_BYTES_ENV_VARS)
        if max_context_bytes == 0 and env_max:
            try:
                max_context_bytes = int(env_max)
            except ValueError:
                max_context_bytes = 0

        if include_tests is None:
            include_tests = _env_flag("ARAGORA_CODEBASE_INCLUDE_TESTS", "1")

        if full_corpus is None:
            # Default to off outside Nomic to avoid heavy LLM calls unless explicitly enabled.
            full_corpus = _env_flag("ARAGORA_CODEBASE_RLM_FULL_CORPUS", "0")

        super().__init__(
            aragora_path=root_path,
            max_context_bytes=max_context_bytes,
            include_tests=include_tests,
            knowledge_mound=knowledge_mound,
            full_corpus=full_corpus,
        )


__all__ = ["CodebaseContextBuilder"]
