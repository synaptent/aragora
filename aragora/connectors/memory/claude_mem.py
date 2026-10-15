"""
Claude-Mem connector (optional).

Provides read-only access to a local claude-mem worker API for memory search
and observation retrieval.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from aragora.connectors.base import BaseConnector, ConnectorAPIError, Evidence
from aragora.reasoning.provenance import SourceType


@dataclass(frozen=True)
class ClaudeMemConfig:
    base_url: str = "http://localhost:37777"
    timeout_seconds: float = 10.0
    project: str | None = None

    @classmethod
    def from_env(cls) -> ClaudeMemConfig:
        base_url = os.environ.get("ARAGORA_CLAUDE_MEM_BASE_URL", "http://localhost:37777")
        timeout_seconds = float(os.environ.get("ARAGORA_CLAUDE_MEM_TIMEOUT", "10"))
        project = os.environ.get("ARAGORA_CLAUDE_MEM_PROJECT")
        return cls(base_url=base_url, timeout_seconds=timeout_seconds, project=project)


class ClaudeMemConnector(BaseConnector):
    """Connector for claude-mem local memory search."""

    def __init__(self, config: ClaudeMemConfig | None = None):
        super().__init__()
        self.config = config or ClaudeMemConfig.from_env()

    @property
    def source_type(self) -> SourceType:
        return SourceType.EXTERNAL_API

    @property
    def name(self) -> str:
        return "Claude-Mem"

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[Evidence]:
        params = {
            "query": query,
            "limit": str(limit),
            "format": "json",
        }
        project = kwargs.get("project") or self.config.project
        if project:
            params["project"] = project
        url = f"{self.config.base_url.rstrip('/')}/api/search?{urllib.parse.urlencode(params)}"
        payload = await self._get_json(url)
        observations = payload.get("observations", [])

        results: list[Evidence] = []
        for obs in observations:
            obs_id = obs.get("id")
            content = obs.get("text") or obs.get("narrative") or obs.get("title") or ""
            if not content:
                continue
            results.append(
                Evidence(
                    id=f"obs_{obs_id}",
                    source_type=self.source_type,
                    source_id=str(obs_id),
                    content=content,
                    title=obs.get("title") or "",
                    created_at=obs.get("created_at"),
                    metadata={
                        "source": "claude-mem",
                        "project": obs.get("project"),
                        "type": obs.get("type"),
                        "files_read": obs.get("files_read"),
                        "files_modified": obs.get("files_modified"),
                        "raw": obs,
                    },
                )
            )
        return results

    async def fetch(self, evidence_id: str) -> Evidence | None:
        obs_id = evidence_id.replace("obs_", "")
        url = f"{self.config.base_url.rstrip('/')}/api/observation/{urllib.parse.quote(obs_id)}"
        payload = await self._get_json(url)
        if not payload:
            return None
        content = payload.get("text") or payload.get("narrative") or payload.get("title") or ""
        if not content:
            return None
        return Evidence(
            id=f"obs_{payload.get('id', obs_id)}",
            source_type=self.source_type,
            source_id=str(payload.get("id", obs_id)),
            content=content,
            title=payload.get("title") or "",
            created_at=payload.get("created_at"),
            metadata={
                "source": "claude-mem",
                "project": payload.get("project"),
                "type": payload.get("type"),
                "files_read": payload.get("files_read"),
                "files_modified": payload.get("files_modified"),
                "raw": payload,
            },
        )

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            # config URL
            with urllib.request.urlopen(url, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise ConnectorAPIError(
                f"Claude-Mem request failed: {exc}",
                connector_name=self.name,
            ) from exc
