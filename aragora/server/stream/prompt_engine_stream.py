"""WebSocket stream handler for prompt engine pipeline events.

Provides real-time streaming of prompt-to-specification pipeline stages
to connected WebSocket clients.

Event types:
- prompt_engine_start      - Pipeline begins
- prompt_engine_stage      - Stage started (decompose/interrogate/research/specify)
- prompt_engine_intent     - Decomposition complete
- prompt_engine_questions  - Clarifying questions generated
- prompt_engine_research   - Research complete
- prompt_engine_spec       - Specification built
- prompt_engine_validation - Validation complete
- prompt_engine_complete   - Pipeline finished
- prompt_engine_error      - Error occurred
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)


@dataclass
class PromptEngineStreamClient:
    """A connected WebSocket client for prompt engine events."""

    ws: web.WebSocketResponse
    client_id: str
    session_id: str
    connected_at: float = field(default_factory=time.time)


class PromptEngineStreamEmitter:
    """Emitter for prompt engine pipeline events.

    Broadcasts pipeline stage events to connected WebSocket clients,
    filtered by session_id so each client only receives events for
    their own pipeline run.
    """

    def __init__(self) -> None:
        self._clients: dict[str, PromptEngineStreamClient] = {}
        self._client_counter = 0

    def add_client(
        self,
        ws: web.WebSocketResponse,
        session_id: str,
    ) -> str:
        self._client_counter += 1
        client_id = f"pe_{self._client_counter}_{int(time.time())}"
        self._clients[client_id] = PromptEngineStreamClient(
            ws=ws,
            client_id=client_id,
            session_id=session_id,
        )
        logger.info("Prompt engine client connected: %s (session %s)", client_id, session_id)
        return client_id

    def remove_client(self, client_id: str) -> None:
        if client_id in self._clients:
            del self._clients[client_id]
            logger.info("Prompt engine client disconnected: %s", client_id)

    async def emit(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Emit an event to all clients watching a specific session."""
        message = {
            "type": event_type,
            "session_id": session_id,
            "timestamp": time.time(),
            **data,
        }

        disconnected: list[str] = []
        for cid, client in self._clients.items():
            if client.session_id != session_id:
                continue
            try:
                await client.ws.send_json(message)
            except (ConnectionError, RuntimeError):
                disconnected.append(cid)

        for cid in disconnected:
            self.remove_client(cid)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Module-level singleton
_emitter: PromptEngineStreamEmitter | None = None


def get_prompt_engine_emitter() -> PromptEngineStreamEmitter:
    global _emitter
    if _emitter is None:
        _emitter = PromptEngineStreamEmitter()
    return _emitter


def set_prompt_engine_emitter(emitter: PromptEngineStreamEmitter) -> None:
    global _emitter
    _emitter = emitter


async def _run_pipeline(
    emitter: PromptEngineStreamEmitter,
    session_id: str,
    prompt: str,
    profile: str,
    context: dict[str, Any] | None,
) -> None:
    """Run the prompt engine pipeline, emitting events at each stage."""
    from aragora.prompt_engine import (
        ConductorConfig,
        PromptConductor,
        SpecValidator,
    )

    try:
        config = ConductorConfig.from_profile(profile)
        conductor = PromptConductor(config=config)

        # Stage 1: Decompose
        await emitter.emit(
            session_id,
            "prompt_engine_stage",
            {
                "stage": "decompose",
                "status": "started",
            },
        )
        intent = await conductor.decompose_only(prompt, context)
        await emitter.emit(
            session_id,
            "prompt_engine_intent",
            {
                "intent": intent.to_dict(),
            },
        )

        # Stage 2: Interrogate
        if intent.needs_clarification and not config.skip_interrogation:
            await emitter.emit(
                session_id,
                "prompt_engine_stage",
                {
                    "stage": "interrogate",
                    "status": "started",
                },
            )
            questions = await conductor.interrogate_only(intent)
            await emitter.emit(
                session_id,
                "prompt_engine_questions",
                {
                    "questions": [q.to_dict() for q in questions],
                },
            )
        else:
            questions = []

        # Stage 3: Research
        if not config.skip_research:
            await emitter.emit(
                session_id,
                "prompt_engine_stage",
                {
                    "stage": "research",
                    "status": "started",
                },
            )
            research = await conductor.research_only(intent, questions or None)
            await emitter.emit(
                session_id,
                "prompt_engine_research",
                {
                    "research": research.to_dict(),
                },
            )
        else:
            research = None

        # Stage 4: Specify
        await emitter.emit(
            session_id,
            "prompt_engine_stage",
            {
                "stage": "specify",
                "status": "started",
            },
        )
        spec = await conductor.specify_only(intent, questions or None, research)
        await emitter.emit(
            session_id,
            "prompt_engine_spec",
            {
                "specification": spec.to_dict(),
            },
        )

        # Validation
        validator = SpecValidator()
        validation = validator.validate_heuristic(spec)
        await emitter.emit(
            session_id,
            "prompt_engine_validation",
            {
                "validation": validation.to_dict(),
            },
        )

        # Complete
        await emitter.emit(
            session_id,
            "prompt_engine_complete",
            {
                "stages_completed": ["decompose", "interrogate", "research", "specify"],
            },
        )

    except Exception as exc:
        logger.exception("Prompt engine pipeline error: %s", exc)
        await emitter.emit(
            session_id,
            "prompt_engine_error",
            {
                "error": "Pipeline failed",
            },
        )


async def prompt_engine_websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """WebSocket handler for prompt engine pipeline streaming."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    emitter = get_prompt_engine_emitter()
    session_id = str(uuid.uuid4())
    client_id = emitter.add_client(ws, session_id)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    action = data.get("action", "run")

                    if action == "run":
                        prompt = data.get("prompt", "").strip()
                        if not prompt:
                            await ws.send_json(
                                {
                                    "type": "prompt_engine_error",
                                    "error": "prompt is required",
                                }
                            )
                            continue

                        profile = data.get("profile", "founder")
                        context = data.get("context")

                        await emitter.emit(
                            session_id,
                            "prompt_engine_start",
                            {
                                "prompt": prompt,
                                "profile": profile,
                            },
                        )

                        # Run pipeline as a background task so we can
                        # continue receiving messages
                        asyncio.create_task(
                            _run_pipeline(emitter, session_id, prompt, profile, context)
                        )

                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})

            elif msg.type == WSMsgType.ERROR:
                logger.error("Prompt engine WS error: %s", ws.exception())
                break
    finally:
        emitter.remove_client(client_id)

    return ws


def register_prompt_engine_stream_routes(app: web.Application) -> None:
    """Register the prompt engine stream WebSocket route."""
    app.router.add_get("/ws/prompt-engine", prompt_engine_websocket_handler)


__all__ = [
    "PromptEngineStreamClient",
    "PromptEngineStreamEmitter",
    "get_prompt_engine_emitter",
    "set_prompt_engine_emitter",
    "prompt_engine_websocket_handler",
    "register_prompt_engine_stream_routes",
]
