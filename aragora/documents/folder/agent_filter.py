"""
Agent-based file filtering using LLM evaluation.

This module provides intelligent file filtering by using an LLM to evaluate
whether files are relevant to a user's criteria. It's designed as an optional
enhancement on top of pattern-based filtering.

Example usage:
    from aragora.documents.folder.agent_filter import AgentFileFilter

    filter = AgentFileFilter(model="gemini-2.0-flash")
    decisions = await filter.filter_batch(
        files=scan_result.included_files,
        prompt="Only include financial reports and legal contracts",
    )

    for file_info, include, reason in decisions:
        if include:
            final_files.append(file_info)
        else:
            excluded_files.append((file_info, reason))
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aragora.models.compat import first_text_block

from .config import ExcludedFile, ExclusionReason, FileInfo

logger = logging.getLogger(__name__)


@dataclass
class FilterDecision:
    """Result of agent evaluation for a single file."""

    file: FileInfo
    include: bool
    reason: str
    confidence: float = 1.0


class AgentFileFilter:
    """
    Uses LLM to evaluate file relevance based on user criteria.

    The agent examines file metadata (path, name, extension, size) and optionally
    file content previews to make relevance decisions.
    """

    # Default batch size for grouping files
    DEFAULT_BATCH_SIZE = 50

    # Maximum preview size for text files (characters)
    MAX_PREVIEW_SIZE = 500

    # Text file extensions that can be previewed
    TEXT_EXTENSIONS = {
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".xml",
        ".html",
        ".css",
    }

    def __init__(
        self,
        model: str = "gemini-3.1-pro-preview",
        batch_size: int = DEFAULT_BATCH_SIZE,
        include_previews: bool = True,
        max_preview_size: int = MAX_PREVIEW_SIZE,
    ):
        """
        Initialize the agent file filter.

        Args:
            model: LLM model to use for evaluation
            batch_size: Number of files to evaluate in each batch
            include_previews: Whether to include content previews for text files
            max_preview_size: Maximum characters to include in previews
        """
        self.model = model
        self.batch_size = batch_size
        self.include_previews = include_previews
        self.max_preview_size = max_preview_size
        self._client: Any = None

    async def _get_client(self) -> Any:
        """Get or create the LLM client based on model."""
        if self._client is not None:
            return self._client

        # Determine which client to use based on model name
        if "gemini" in self.model.lower():
            try:
                import google.generativeai as genai
                from aragora.config.secrets import get_secret

                api_key = get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")
                if not api_key:
                    raise ValueError(
                        "GEMINI_API_KEY or GOOGLE_API_KEY environment variable required"
                    )

                genai.configure(api_key=api_key)
                self._client = genai.GenerativeModel(self.model)
                return self._client
            except ImportError:
                raise ImportError("google-generativeai package required for Gemini models")

        elif "claude" in self.model.lower():
            try:
                import anthropic
                from aragora.config.secrets import get_secret

                api_key = get_secret("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY environment variable required")

                self._client = anthropic.Anthropic(api_key=api_key)
                return self._client
            except ImportError:
                raise ImportError("anthropic package required for Claude models")

        elif "gpt" in self.model.lower() or "openai" in self.model.lower():
            try:
                from openai import OpenAI
                from aragora.config.secrets import get_secret

                api_key = get_secret("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY environment variable required")

                self._client = OpenAI(api_key=api_key)
                return self._client
            except ImportError:
                raise ImportError("openai package required for GPT models")

        else:
            raise ValueError(f"Unsupported model: {self.model}. Use gemini-*, claude-*, or gpt-*")

    def _get_file_preview(self, file_info: FileInfo) -> str | None:
        """Get a preview of text file content."""
        if not self.include_previews:
            return None

        if file_info.extension.lower() not in self.TEXT_EXTENSIONS:
            return None

        try:
            path = Path(file_info.absolute_path)
            if not path.exists() or not path.is_file():
                return None

            # Read first N characters
            content = path.read_text(encoding="utf-8", errors="ignore")[: self.max_preview_size]
            if len(content) == self.max_preview_size:
                content += "..."
            return content
        except (OSError, UnicodeDecodeError, ValueError) as e:
            logger.debug("Could not read preview for %s: %s", file_info.path, e)
            return None

    def _format_file_for_prompt(self, file_info: FileInfo, index: int) -> str:
        """Format a file entry for the LLM prompt."""
        lines = [
            f"{index + 1}. {file_info.path}",
            f"   Extension: {file_info.extension}",
            f"   Size: {file_info.size_bytes} bytes",
        ]

        preview = self._get_file_preview(file_info)
        if preview:
            # Escape any special characters and truncate
            preview_lines = preview.replace("\n", " ").replace("\r", "")[:200]
            lines.append(f"   Preview: {preview_lines}")

        return "\n".join(lines)

    def _build_prompt(self, files: list[FileInfo], user_criteria: str) -> str:
        """Build the evaluation prompt for the LLM."""
        file_list = "\n\n".join(self._format_file_for_prompt(f, i) for i, f in enumerate(files))

        return f"""You are a file relevance evaluator. Your task is to determine which files should be included for document processing based on the user's criteria.

USER CRITERIA:
{user_criteria}

FILES TO EVALUATE:
{file_list}

INSTRUCTIONS:
1. Evaluate each file based on the user's criteria
2. Consider file path, name, extension, and content preview (if available)
3. Be inclusive when uncertain - prefer to include files that might be relevant
4. Exclude files that are clearly not relevant (e.g., test files, generated files, binaries)

Respond with a JSON object in this exact format:
{{
  "decisions": [
    {{"index": 1, "include": true, "reason": "Brief explanation"}},
    {{"index": 2, "include": false, "reason": "Brief explanation"}},
    ...
  ]
}}

Provide a decision for every file listed above."""

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM and get a response."""
        client = await self._get_client()

        if "gemini" in self.model.lower():
            response = await asyncio.to_thread(client.generate_content, prompt)
            return str(response.text)

        elif "claude" in self.model.lower():
            response = await asyncio.to_thread(
                client.messages.create,
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            # Gemini by default, but a caller may pass a modern Claude id,
            # which emits a leading thinking block. Scan for the text block.
            return first_text_block(response.content)

        elif "gpt" in self.model.lower() or "openai" in self.model.lower():
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=self.model.replace("openai-", ""),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            return str(response.choices[0].message.content)

        raise ValueError(f"Unsupported model: {self.model}")

    def _parse_response(self, response: str, files: list[FileInfo]) -> list[FilterDecision]:
        """Parse the LLM response into filter decisions."""
        decisions: list[FilterDecision] = []

        # Try to extract JSON from response
        try:
            # Handle case where response has markdown code blocks
            if "```json" in response:
                json_start = response.index("```json") + 7
                json_end = response.index("```", json_start)
                response = response[json_start:json_end]
            elif "```" in response:
                json_start = response.index("```") + 3
                json_end = response.index("```", json_start)
                response = response[json_start:json_end]

            data = json.loads(response.strip())

            if "decisions" not in data:
                raise ValueError("Missing 'decisions' key in response")

            # Map decisions by index
            decision_map = {d["index"]: d for d in data["decisions"]}

            for i, file_info in enumerate(files):
                idx = i + 1  # 1-indexed in prompt
                if idx in decision_map:
                    d = decision_map[idx]
                    decisions.append(
                        FilterDecision(
                            file=file_info,
                            include=d.get("include", True),
                            reason=d.get("reason", ""),
                            confidence=d.get("confidence", 1.0),
                        )
                    )
                else:
                    # Default to include if missing
                    decisions.append(
                        FilterDecision(
                            file=file_info,
                            include=True,
                            reason="No decision returned, defaulting to include",
                            confidence=0.5,
                        )
                    )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Failed to parse LLM response: %s. Including all files.", e)
            # Default to including all files on parse error
            for file_info in files:
                decisions.append(
                    FilterDecision(
                        file=file_info,
                        include=True,
                        reason=f"Parse error: {str(e)[:50]}",
                        confidence=0.5,
                    )
                )

        return decisions

    async def filter_batch(
        self,
        files: list[FileInfo],
        prompt: str,
    ) -> list[FilterDecision]:
        """
        Evaluate a batch of files for relevance.

        Args:
            files: List of files to evaluate
            prompt: User's criteria for relevance

        Returns:
            List of FilterDecision objects for each file
        """
        if not files:
            return []

        if not prompt.strip():
            # No criteria - include everything
            return [
                FilterDecision(file=f, include=True, reason="No filter criteria provided")
                for f in files
            ]

        all_decisions: list[FilterDecision] = []

        # Process in batches
        for i in range(0, len(files), self.batch_size):
            batch = files[i : i + self.batch_size]
            llm_prompt = self._build_prompt(batch, prompt)

            try:
                response = await self._call_llm(llm_prompt)
                batch_decisions = self._parse_response(response, batch)
                all_decisions.extend(batch_decisions)
            except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
                logger.error("Agent filter batch %s failed: %s", i // self.batch_size + 1, e)
                # On error, default to including all files in this batch
                for file_info in batch:
                    all_decisions.append(
                        FilterDecision(
                            file=file_info,
                            include=True,
                            reason=f"Filter error: {str(e)[:50]}",
                            confidence=0.0,
                        )
                    )

        return all_decisions

    async def filter_files(
        self,
        files: list[FileInfo],
        prompt: str,
    ) -> tuple[list[FileInfo], list[ExcludedFile]]:
        """
        Filter files and return included/excluded lists.

        This is a convenience method that returns the same format as other filters.

        Args:
            files: List of files to evaluate
            prompt: User's criteria for relevance

        Returns:
            Tuple of (included_files, excluded_files)
        """
        decisions = await self.filter_batch(files, prompt)

        included: list[FileInfo] = []
        excluded: list[ExcludedFile] = []

        for decision in decisions:
            if decision.include:
                included.append(decision.file)
            else:
                excluded.append(
                    ExcludedFile(
                        path=decision.file.path,
                        reason=ExclusionReason.AGENT,
                        details=decision.reason,
                    )
                )

        return included, excluded


def get_agent_filter(
    model: str = "gemini-2.0-flash",
    batch_size: int = AgentFileFilter.DEFAULT_BATCH_SIZE,
) -> AgentFileFilter:
    """
    Get an agent file filter instance.

    Args:
        model: LLM model to use
        batch_size: Files per batch

    Returns:
        AgentFileFilter instance
    """
    return AgentFileFilter(model=model, batch_size=batch_size)
