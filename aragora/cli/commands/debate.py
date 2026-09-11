"""
Debate-related CLI commands and helpers.

Contains the core debate execution logic: agent parsing, debate running,
and the 'ask' command handler.
"""

import argparse
import asyncio
from dataclasses import fields
import json
import logging
import math
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from aragora.agents.base import AgentType, create_agent
from aragora.agents.spec import AgentSpec
from aragora.config import (
    DEFAULT_AGENTS,
    DEFAULT_CONSENSUS,
    DEFAULT_ROUNDS,
    MAX_AGENTS_PER_DEBATE,
)
from aragora.config.secrets import get_secret_presence, is_secret_presence_available
from aragora.core import Environment
from aragora.debate.arena_primary_configs import MLConfig, MemoryConfig
from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.memory.store import CritiqueStore
from aragora.modes import ModeRegistry
from aragora.topic_handler import handle_ambiguous_task


logger = logging.getLogger(__name__)

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")
_MEMORY_CONFIG_KEYS = {field.name for field in fields(MemoryConfig)}
_ML_CONFIG_KEYS = {field.name for field in fields(MLConfig)}

_AGENT_FAILURE_RESPONSE_MARKERS = (
    "[system: agent ",
    "[error generating proposal:",
    "[no proposals available",
    "agent timed out",
    "connection failed",
    "encountered an error",
    "encountered an unexpected situation",
    "something went wrong with",
    "needs to restart their thought process",
    "tripped over an edge case",
    "experienced a minor cognitive hiccup",
    "got confused and needs to recalibrate",
    "a wild bug appeared",
    "has achieved unexpected behavior",
    "fatal exception in",
    "error 418:",
)


class _StrictWallClockTimeout(TimeoutError):
    """Raised when a hard wall-clock timeout expires."""


def _looks_like_agent_failure_response(text: Any) -> bool:
    """Detect autonomic failure placeholders that should not count as answers."""

    normalized = str(text or "").strip().lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in _AGENT_FAILURE_RESPONSE_MARKERS)


def _result_has_only_agent_failure_outputs(result: Any) -> bool:
    """Return true when a debate produced only failure placeholders."""

    proposals = getattr(result, "proposals", None)
    if isinstance(proposals, dict) and proposals:
        return all(_looks_like_agent_failure_response(value) for value in proposals.values())

    final_answer = getattr(result, "final_answer", "")
    return _looks_like_agent_failure_response(final_answer)


@contextmanager
def _strict_wall_clock_timeout(timeout_seconds: float):
    """Enforce a hard wall-clock timeout using SIGALRM when available.

    Falls back to a no-op context on platforms/threads where SIGALRM is unavailable.
    """
    if timeout_seconds <= 0:
        yield
        return

    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer: tuple[float, float] | None = None

    def _on_timeout(_signum: int, _frame: Any) -> None:
        raise _StrictWallClockTimeout(f"strict wall-clock timeout after {timeout_seconds:.2f}s")

    try:
        signal.signal(signal.SIGALRM, _on_timeout)
        if hasattr(signal, "setitimer") and hasattr(signal, "ITIMER_REAL"):
            previous_timer = signal.getitimer(signal.ITIMER_REAL)
            signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
        else:
            signal.alarm(max(1, math.ceil(timeout_seconds)))
        yield
    finally:
        if hasattr(signal, "setitimer") and hasattr(signal, "ITIMER_REAL"):
            signal.setitimer(signal.ITIMER_REAL, 0.0)
        else:
            signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        if (
            previous_timer is not None
            and hasattr(signal, "setitimer")
            and hasattr(signal, "ITIMER_REAL")
        ):
            remaining, interval = previous_timer
            if remaining > 0 or interval > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining, interval)


def get_event_emitter_if_available(server_url: str = DEFAULT_API_URL) -> Any | None:
    """
    Try to connect to the streaming server for audience participation.
    Returns event emitter if server is available, None otherwise.
    """
    try:
        import urllib.request

        # Quick health check
        with urllib.request.urlopen(f"{server_url}/api/health", timeout=2) as resp:  # noqa: S310 -- local server health check
            status_code = getattr(resp, "status", None) or resp.getcode()
            if status_code == 200:
                # Server is up, try to get emitter
                try:
                    from aragora.server.stream import SyncEventEmitter

                    return SyncEventEmitter()
                except ImportError:
                    logger.debug("SyncEventEmitter not available")
    except (OSError, TimeoutError) as e:
        logger.debug("Streaming server not available at %s: %s", server_url, e)
    return None


def parse_agents(agents_str: str) -> list[AgentSpec]:
    """Parse agent string using unified AgentSpec.

    Supports both formats:
    - New pipe format: provider|model|persona|role (explicit fields)
    - Legacy colon format: provider:role or provider:persona

    Args:
        agents_str: Comma-separated agent specs

    Returns:
        List of AgentSpec objects with all parsed fields
    """
    from aragora.agents.spec import AgentSpec

    return AgentSpec.coerce_list(agents_str, warn=False)


def _resolved_cli_provider_key(provider: str) -> str | None:
    """Return the CLI-resolved key for an explicit provider, if configured.

    The CLI key store is the same surface used by ``validate-env`` live
    provider checks. Passing this key into direct API agents keeps explicit
    ``aragora ask --agents <provider>`` runs from re-discovering credentials
    through unrelated fallback probes.
    """
    try:
        from aragora.cli.api_keys import get_provider_key

        value, _source = get_provider_key(provider)
    except (RuntimeError, ValueError):
        return None
    return value.strip() if value and value.strip() else None


def _coalesce_grouped_arena_configs(arena_kwargs: dict[str, Any]) -> None:
    """Backfill grouped Arena config objects from legacy per-flag kwargs."""
    existing_memory_cfg = arena_kwargs.get("memory_config")
    if isinstance(existing_memory_cfg, dict):
        arena_kwargs["memory_config"] = MemoryConfig(**existing_memory_cfg)
    elif existing_memory_cfg is None:
        memory_overrides = {k: arena_kwargs[k] for k in _MEMORY_CONFIG_KEYS if k in arena_kwargs}
        if memory_overrides:
            arena_kwargs["memory_config"] = MemoryConfig(**memory_overrides)

    existing_ml_cfg = arena_kwargs.get("ml_config")
    if isinstance(existing_ml_cfg, dict):
        arena_kwargs["ml_config"] = MLConfig(**existing_ml_cfg)
    elif existing_ml_cfg is None:
        ml_overrides = {k: arena_kwargs[k] for k in _ML_CONFIG_KEYS if k in arena_kwargs}
        if ml_overrides:
            arena_kwargs["ml_config"] = MLConfig(**ml_overrides)


def _split_agents_list(agents_str: str) -> list[str]:
    """Split comma-separated agents string into a clean list."""
    if not agents_str:
        return []
    return [agent.strip() for agent in agents_str.split(",") if agent.strip()]


def _normalize_agents_combo(agents_str: str) -> str:
    """Normalize an agent combination string for display and deduplication."""
    return ",".join(_split_agents_list(agents_str))


def _collect_comparison_agent_sets(
    baseline_agents: str,
    additional_agents: list[str] | None,
) -> list[str]:
    """Build a deduplicated list of agent combinations for compare mode."""
    combinations: list[str] = []
    seen: set[str] = set()
    for raw in [baseline_agents, *(additional_agents or [])]:
        normalized = _normalize_agents_combo(raw)
        if not normalized or normalized in seen:
            continue
        combinations.append(normalized)
        seen.add(normalized)
    return combinations


def _agent_names_for_graph_matrix(agents_str: str) -> list[str]:
    """Resolve agent names for graph/matrix debates (provider-only)."""
    try:
        specs = parse_agents(agents_str)
        return [spec.provider for spec in specs if spec.provider]
    except (ValueError, AttributeError, TypeError) as e:
        logger.debug("Agent spec parsing failed, falling back to split: %s", e)
        return _split_agents_list(agents_str)


def _agents_payload_for_api(agents_str: str) -> list[Any]:
    """Build API payload for agents (strings or dicts) from CLI input."""
    try:
        specs = parse_agents(agents_str)
    except (ValueError, AttributeError, TypeError) as e:
        logger.debug("Agent spec parsing failed, falling back to split: %s", e)
        return _split_agents_list(agents_str)

    if not specs:
        return []

    advanced = any(
        spec.model or spec.persona or spec.role or spec.name or spec.hierarchy_role
        for spec in specs
    )
    if not advanced:
        return [spec.provider for spec in specs if spec.provider]

    payload: list[dict[str, Any]] = []
    for spec in specs:
        item: dict[str, Any] = {"provider": spec.provider}
        if spec.model:
            item["model"] = spec.model
        if spec.persona:
            item["persona"] = spec.persona
        if spec.role:
            item["role"] = spec.role
        if spec.name:
            item["name"] = spec.name
        if spec.hierarchy_role:
            item["hierarchy_role"] = spec.hierarchy_role
        payload.append(item)
    return payload


def _is_server_available(server_url: str) -> bool:
    """Check if the API server is reachable."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{server_url}/api/health", timeout=2) as resp:  # noqa: S310 -- local server health check
            status_code = getattr(resp, "status", None) or resp.getcode()
            return status_code == 200
    except (OSError, TimeoutError) as e:
        logger.debug("Server health check failed at %s: %s", server_url, e)
        return False


# Statuses Aragora's health endpoint can report. The public (unauthenticated)
# ``/api/health`` response is exactly {"status": "healthy"|"degraded",
# "timestamp": "<iso8601>Z"} (see aragora/server/handlers/admin/health).
_ARAGORA_HEALTH_STATUSES = frozenset({"healthy", "degraded"})


def _identifies_as_aragora(body: bytes) -> bool:
    """Return True when a health response body matches Aragora's health schema.

    This is a positive-signal check: the payload must be a JSON object whose
    ``status`` is one of Aragora's health statuses and which carries a
    ``timestamp`` field. Anything else (HTML login pages, Jenkins/Tomcat
    banners, other projects' ``{"status": "ok"}`` probes) is rejected.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    return (
        isinstance(status, str)
        and status.lower() in _ARAGORA_HEALTH_STATUSES
        and "timestamp" in payload
    )


def _probe_server_identity(server_url: str) -> str:
    """Probe ``server_url`` and classify what is listening.

    Returns:
        ``"aragora"``: HTTP 200 whose payload matches Aragora's health schema.
        ``"foreign"``: something answered HTTP 200 but does not identify as an
            Aragora server (e.g. another dev service squatting the port).
        ``"unavailable"``: nothing healthy is listening.
    """
    try:
        import urllib.request

        with urllib.request.urlopen(f"{server_url}/api/health", timeout=2) as resp:  # noqa: S310 -- local server health check
            status_code = getattr(resp, "status", None) or resp.getcode()
            if status_code != 200:
                return "unavailable"
            body = resp.read(8192)
    except (OSError, TimeoutError, ValueError) as e:
        logger.debug("Server health probe failed at %s: %s", server_url, e)
        return "unavailable"
    if _identifies_as_aragora(body):
        return "aragora"
    logger.debug("Service at %s answered 200 but does not identify as Aragora", server_url)
    return "foreign"


def _is_explicitly_configured_api_url(server_url: str, *, flag_passed: bool = False) -> bool:
    """True when the user opted in to this API URL (env var or --api-url flag).

    ``flag_passed`` carries actual flag presence from argparse (the parser
    defaults ``--api-url`` to ``None``), so ``--api-url http://localhost:8080``
    counts as explicit even though it equals the default URL. The value
    comparison remains as a fallback for callers without flag information.
    """
    if flag_passed:
        return True
    if os.environ.get("ARAGORA_API_URL", "").strip():
        return True
    return server_url.rstrip("/") != DEFAULT_API_URL.rstrip("/")


def _trusted_server_available(server_url: str, *, flag_passed: bool = False) -> bool:
    """Availability gate for auto-discovery: reachable AND identifies as Aragora.

    Fail-closed trust check: port 8080 is the most commonly squatted dev port
    (Jenkins, Tomcat, other projects' dev servers), so a bare HTTP 200 on
    ``/api/health`` is not enough to route the user's debate content there.
    An explicitly configured URL (``ARAGORA_API_URL`` or ``--api-url``) is
    trusted as-is because the user opted in.
    """
    if not _is_server_available(server_url):
        return False
    if _is_explicitly_configured_api_url(server_url, flag_passed=flag_passed):
        return True
    identity = _probe_server_identity(server_url)
    if identity == "aragora":
        return True
    if identity == "foreign":
        print(
            f"Note: service at {server_url} does not identify as an Aragora API server; "
            "running the debate locally. Set ARAGORA_API_URL or pass --api-url to use it anyway.",
            file=sys.stderr,
        )
    return False


def _build_api_client(server_url: str, api_key: str | None):
    """Build an AragoraClient for API-backed runs."""
    from aragora.client import AragoraClient

    return AragoraClient(base_url=server_url, api_key=api_key)


def _parse_matrix_scenarios(raw: list[str] | None) -> list[dict[str, Any]]:
    """Parse matrix scenario CLI inputs into structured dicts."""
    scenarios: list[dict[str, Any]] = []
    for item in raw or []:
        value = str(item).strip()
        if not value:
            continue
        if value.startswith("{") or value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid scenario JSON: {e}")
            if isinstance(parsed, list):
                scenarios.extend([s for s in parsed if isinstance(s, dict)])
            elif isinstance(parsed, dict):
                scenarios.append(parsed)
            else:
                raise ValueError("Scenario JSON must be an object or list of objects")
        else:
            scenarios.append({"name": value})
    return scenarios


def _parse_auto_select_config(raw: str | None) -> dict[str, Any] | None:
    """Parse auto-select config JSON string into a dict."""
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid auto-select config JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("Auto-select config must be a JSON object")
    return parsed


def _append_context_file(context: str, context_file: str) -> str:
    """Read a file and append its content to the context string."""
    from pathlib import Path

    path = Path(context_file)
    if not path.is_file():
        raise ValueError(f"Context file not found: {context_file}")
    content = path.read_text(encoding="utf-8")
    if context:
        return f"{context}\n\n--- Context from {path.name} ---\n{content}"
    return content


def _cleanup_cli_subprocesses_for_timeout() -> dict[str, int]:
    """Best-effort cleanup for CLI subprocesses after timeout."""
    try:
        from aragora.agents.cli_agents import terminate_tracked_cli_processes

        return terminate_tracked_cli_processes()
    except Exception as e:  # noqa: BLE001 - timeout cleanup must never crash CLI
        logger.warning("Failed to clean up tracked CLI subprocesses: %s", e)
        return {"tracked": 0, "terminated": 0, "killed": 0, "remaining": 0}


async def _shutdown_cmd_ask_resources() -> None:
    """Best-effort cleanup for CLI ask shared resources on the active loop."""
    try:
        from aragora.moderation.spam_integration import close_spam_moderation

        await close_spam_moderation()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask spam moderation shutdown skipped: %s", exc)

    try:
        from aragora.events.dispatcher import shutdown_dispatcher

        shutdown_dispatcher(wait=True)
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask dispatcher shutdown skipped: %s", exc)

    try:
        from aragora.server.startup.database import close_postgres_pool

        await close_postgres_pool()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask postgres shutdown skipped: %s", exc)

    try:
        from aragora.server.http_client_pool import close_http_pool

        await close_http_pool()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask HTTP client pool shutdown skipped: %s", exc)

    try:
        from aragora.agents.api_agents.common import close_shared_connector

        await close_shared_connector()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask API connector shutdown skipped: %s", exc)

    try:
        from aragora.storage.connection_factory import close_all_pools

        await close_all_pools()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask connection-factory shutdown skipped: %s", exc)

    try:
        from aragora.storage.receipt_store import close_receipt_store

        close_receipt_store()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask receipt store shutdown skipped: %s", exc)

    try:
        from aragora.storage.webhook_config_store import reset_webhook_config_store

        reset_webhook_config_store()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask webhook config store shutdown skipped: %s", exc)

    try:
        from aragora.storage.schema import DatabaseManager

        DatabaseManager.clear_instances()
    except Exception as exc:  # noqa: BLE001 - shutdown must never hide CLI result
        logger.debug("Ask SQLite manager shutdown skipped: %s", exc)

    # Give async transport/connector close callbacks one loop turn before
    # asyncio.run() tears the loop down. This avoids intermittent unclosed
    # socket warnings in CLI proof-path tests.
    await asyncio.sleep(0)


async def _run_coro_with_cmd_ask_cleanup(coro: Any) -> Any:
    """Await a CLI ask coroutine and close shared resources on the same loop."""
    try:
        return await coro
    finally:
        await _shutdown_cmd_ask_resources()


def _emit_timeout_failure_payload(
    *,
    error_type: str,
    timeout_seconds: int,
    elapsed_seconds: float,
    task: str,
    agents_str: str,
    comparison_agents: list[str] | None,
    mode: str | None,
    cleanup: dict[str, int],
) -> None:
    """Emit machine-parseable timeout payload for benchmark/scoring harnesses."""
    task_value = str(task or "")
    payload = {
        "status": "timeout",
        "error_type": error_type,
        "timeout_seconds": int(timeout_seconds),
        "elapsed_seconds": round(max(0.0, float(elapsed_seconds)), 3),
        "task_preview": task_value[:240],
        "task_length": len(task_value),
        "agents": _split_agents_list(agents_str),
        "mode": mode or "default",
        "cleanup": cleanup,
        "final_answer": "",
    }
    if comparison_agents:
        payload["comparison_agents"] = list(comparison_agents)
    encoded = json.dumps(payload, sort_keys=True)
    print(f"ARAGORA_TIMEOUT_JSON={encoded}")

    report_path_raw = os.environ.get("ARAGORA_ASK_TIMEOUT_REPORT_PATH")
    if report_path_raw:
        try:
            Path(report_path_raw).expanduser().write_text(encoded + "\n", encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to write timeout report %s: %s", report_path_raw, e)


def _looks_like_self_improvement_task(task: str) -> bool:
    """Heuristic detection for codebase self-improvement prompts."""
    lowered = (task or "").lower()
    keywords = (
        "improve",
        "improvement",
        "self-improve",
        "self improvement",
        "refactor",
        "codebase",
        "aragora",
        "architecture",
        "module",
        "component",
        "dogfood",
        "pipeline",
        "orchestration",
    )
    return any(token in lowered for token in keywords)


def _parse_document_ids(
    document: str | None,
    documents: str | None,
) -> list[str]:
    """Parse document ID arguments into a list of document IDs."""
    result: list[str] = []
    if document:
        result.append(document.strip())
    if documents:
        for doc in documents.split(","):
            doc = doc.strip()
            if doc and doc not in result:
                result.append(doc)
    return result


def _auto_select_agents_local(task: str, config: dict[str, Any] | None) -> str | None:
    """Run local auto-selection using server selection logic (best-effort)."""
    try:
        from aragora.server.agent_selection import auto_select_agents

        return auto_select_agents(task, config or {})
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Auto-select failed: %s", e)
        return None


def _maybe_add_vertical_specialist_local(
    task: str,
    agents: list[Any],
    enable_verticals: bool,
    vertical_id: str | None,
) -> list[Any]:
    """Optionally inject a vertical specialist into a local debate run."""
    if not enable_verticals:
        return agents

    try:
        import aragora.verticals.specialists  # noqa: F401
        from aragora.verticals.registry import VerticalRegistry
    except ImportError:
        logger.debug("Verticals registry not available; skipping specialist injection")
        return agents

    resolved_vertical = vertical_id or VerticalRegistry.get_for_task(task)
    if not resolved_vertical:
        logger.debug("No matching vertical found for task; skipping specialist injection")
        return agents

    for agent in agents:
        if getattr(agent, "vertical_id", None) == resolved_vertical:
            return agents

    if len(agents) >= MAX_AGENTS_PER_DEBATE:
        logger.info(
            "Skipping vertical specialist (%s): max agents limit reached (%s)",
            resolved_vertical,
            MAX_AGENTS_PER_DEBATE,
        )
        return agents

    try:
        specialist = VerticalRegistry.create_specialist(
            vertical_id=resolved_vertical,
            name=f"{resolved_vertical}_specialist",
            role="critic",
        )
        try:
            specialist.system_prompt = specialist.build_system_prompt()
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(
                "Failed to build system prompt for specialist %s: %s", resolved_vertical, e
            )
        agents.append(specialist)
        print(f"[verticals] Injected specialist: {resolved_vertical}")
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to create vertical specialist %s: %s", resolved_vertical, e)

    return agents


def _provider_display_name(provider: str | None) -> str:
    """Convert provider keys into a stable user-facing label."""
    raw = str(provider or "").strip()
    if not raw:
        return ""
    key = raw.lower()
    if "/" in key:
        key = key.split("/", 1)[0]
    aliases = {
        "anthropic": "Anthropic",
        "anthropic-api": "Anthropic",
        "claude": "Anthropic",
        "openai": "OpenAI",
        "openai-api": "OpenAI",
        "codex": "OpenAI",
        "google": "Google",
        "gemini": "Google",
        "gemini-cli": "Google",
        "xai": "xAI",
        "grok": "xAI",
        "grok-cli": "xAI",
        "mistral": "Mistral",
        "mistral-api": "Mistral",
        "codestral": "Mistral",
        "deepseek": "DeepSeek",
        "deepseek-cli": "DeepSeek",
        "openrouter": "OpenRouter",
        "qwen": "Qwen",
        "qwen-cli": "Qwen",
        "ollama": "Ollama",
        "lm-studio": "LM Studio",
        "kimi": "Moonshot",
        "kimi-thinking": "Moonshot",
        "kilocode": "KiloCode",
        "demo": "Demo",
    }
    if key in aliases:
        return aliases[key]
    if key.endswith("-api"):
        key = key[:-4]
    return " ".join(part.capitalize() for part in key.replace("_", "-").split("-") if part)


def _detect_provider(model: str | None) -> str:
    """Infer a provider from a model string when the agent doesn't expose one."""
    candidate = str(model or "").strip()
    if not candidate:
        return ""
    if "/" in candidate:
        return candidate.split("/", 1)[0]
    try:
        from aragora.debate.provider_diversity import detect_provider

        detected = detect_provider(candidate)
    except ImportError:
        logger.debug(
            "provider_diversity module not available, cannot detect provider for %s", candidate
        )
        detected = "unknown"
    return "" if detected == "unknown" else detected


def _format_llm_label(model: str | None, provider: str | None) -> str:
    """Create the receipt label shown next to an agent response."""
    model_name = str(model or "").strip()
    provider_display = _provider_display_name(provider)
    if model_name and provider_display:
        return f"{model_name} via {provider_display}"
    if model_name:
        return model_name
    return provider_display


def _attach_agent_models_to_result(result: Any, agents: list[Any]) -> None:
    """Persist agent provider/model metadata onto the debate result."""
    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        setattr(result, "metadata", metadata)

    agent_models = metadata.get("agent_models")
    if not isinstance(agent_models, dict):
        agent_models = {}
        metadata["agent_models"] = agent_models

    for agent in agents:
        agent_name = str(getattr(agent, "name", "") or "").strip()
        if not agent_name:
            continue
        provider = str(getattr(agent, "provider", "") or "").strip()
        model = str(getattr(agent, "model", "") or "").strip()
        if not provider and model:
            provider = _detect_provider(model)
        agent_models[agent_name] = {
            "provider": provider,
            "provider_display": _provider_display_name(provider),
            "model": model,
            "llm_label": _format_llm_label(model, provider),
        }


def _attach_agent_roster_to_result(
    result: Any,
    *,
    requested: list[str],
    created: list[str],
    failed: list[str],
) -> None:
    """Persist the requested/created/failed agent roster onto the result.

    Issue #8101: receipts must surface requested vs created vs participated
    agents instead of silently dropping agents that authored no message.
    """
    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        setattr(result, "metadata", metadata)
    metadata["agent_roster"] = {
        "requested": [str(r) for r in requested if str(r).strip()],
        "created": [str(c) for c in created if str(c).strip()],
        "failed": [str(f) for f in failed],
    }


def _collect_agent_contributions(result: Any) -> dict[str, dict[str, int]]:
    """Count artifact-backed contributions (messages/proposals/critiques/votes)
    per agent from a debate result. Only agents with at least one recorded
    artifact appear in the returned mapping."""
    contributions: dict[str, dict[str, int]] = {}

    def _bump(raw_name: Any, kind: str) -> None:
        name = str(raw_name or "").strip()
        if not name:
            return
        entry = contributions.setdefault(
            name, {"messages": 0, "proposals": 0, "critiques": 0, "votes": 0}
        )
        entry[kind] += 1

    for msg in getattr(result, "messages", []) or []:
        if str(getattr(msg, "content", "") or "").strip():
            _bump(getattr(msg, "agent", ""), "messages")
    proposals = getattr(result, "proposals", None)
    if isinstance(proposals, dict):
        for name in proposals:
            _bump(name, "proposals")
    for critique in getattr(result, "critiques", []) or []:
        _bump(getattr(critique, "agent", ""), "critiques")
    for vote in getattr(result, "votes", []) or []:
        _bump(getattr(vote, "agent", ""), "votes")
    return contributions


def _create_revision_agent(
    provider: str,
    *,
    name: str,
    role: str = "synthesizer",
    model: str | None = None,
) -> Any:
    """Create a post-consensus repair/upgrade agent.

    Issue #8101: resolves credentials through the same CLI key-store surface
    (``_resolved_cli_provider_key``) as the main debate path. Without this,
    strict-secrets mode rejected env-provided keys here while the debate
    itself accepted them — an inconsistent posture within one command.
    """
    return create_agent(
        model_type=cast(AgentType, provider),
        name=name,
        role=role,
        model=model,
        api_key=_resolved_cli_provider_key(provider),
    )


def _persist_debate_receipt(result: Any, verbose: bool = False) -> str | None:
    """Generate and persist a debate receipt to ~/.aragora/receipts/.

    Returns the receipt file path, or None if receipt generation fails.
    """
    try:
        import hashlib
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        from aragora.gauntlet.receipt_models import (
            DecisionReceipt,
            crux_cards_from_metadata,
            receipt_schema_version,
        )

        receipts_dir = Path.home() / ".aragora" / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)

        debate_id = getattr(result, "debate_id", None) or "unknown"
        consensus_reached = getattr(result, "consensus_reached", False)
        confidence = getattr(result, "confidence", 0.0)
        final_answer = getattr(result, "final_answer", "") or ""
        task = str(getattr(result, "task", "") or "")
        metadata = getattr(result, "metadata", None)
        agent_models = metadata.get("agent_models", {}) if isinstance(metadata, dict) else {}
        messages = list(getattr(result, "messages", []) or [])
        agent_responses = []
        for msg in messages[:40]:
            agent_name = str(getattr(msg, "agent", "") or "").strip()
            content = str(getattr(msg, "content", "") or "").strip()
            if not agent_name or not content:
                continue
            model_meta = agent_models.get(agent_name, {}) if isinstance(agent_models, dict) else {}
            agent_responses.append(
                {
                    "agent": agent_name,
                    "role": str(getattr(msg, "role", "") or ""),
                    "round": int(getattr(msg, "round", 0) or 0),
                    "response": content,
                    "provider": str(model_meta.get("provider", "") or ""),
                    "provider_display": str(model_meta.get("provider_display", "") or ""),
                    "model": str(model_meta.get("model", "") or ""),
                    "llm_label": str(model_meta.get("llm_label", "") or ""),
                }
            )

        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if timestamp.endswith("+00:00"):
            timestamp = timestamp[: -len("+00:00")] + "Z"
        # Issue #8101: record ALL participating agents, not just message
        # authors. The roster comes from the engine's canonical participants
        # list (all agents in the debate), unioned with every artifact source
        # (messages, proposals, critiques, votes). Per-agent contribution
        # counts keep the accounting honest: a roster entry with zero
        # contributions is visible as such, never claimed as having spoken.
        contributions = _collect_agent_contributions(result)
        roster_meta = metadata.get("agent_roster", {}) if isinstance(metadata, dict) else {}
        if not isinstance(roster_meta, dict):
            roster_meta = {}
        participants = [
            str(p).strip() for p in (getattr(result, "participants", []) or []) if str(p).strip()
        ]
        created_roster = [str(c) for c in (roster_meta.get("created") or [])]
        requested_roster = [str(r) for r in (roster_meta.get("requested") or [])]
        failed_roster = [str(f) for f in (roster_meta.get("failed") or [])]
        roster = participants or created_roster or list(contributions)
        agents = list(dict.fromkeys([*roster, *contributions]))
        for name in agents:
            contributions.setdefault(
                name, {"messages": 0, "proposals": 0, "critiques": 0, "votes": 0}
            )
        contributing_agents = [name for name in agents if any(contributions[name].values())]
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "task": task,
                    "agents": agents,
                    "agent_responses": agent_responses,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        receipt = {
            "receipt_id": f"debate-{debate_id}",
            "gauntlet_id": str(debate_id),
            "debate_id": debate_id,
            "timestamp": timestamp,
            "task": task,
            "input_summary": task[:500],
            "input_hash": input_hash,
            "risk_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0},
            "attacks_attempted": 0,
            "attacks_successful": 0,
            "probes_run": 0,
            "vulnerabilities_found": 0,
            "verdict": "PASS" if consensus_reached else "CONDITIONAL",
            "verdict_reasoning": final_answer,
            "robustness_score": round(confidence, 4) if confidence else 0.0,
            "consensus_reached": consensus_reached,
            "confidence": round(confidence, 4) if confidence else 0.0,
            "final_answer": final_answer,
            "rounds_used": getattr(result, "rounds_used", 0),
            "agents": agents,
            "agents_requested": requested_roster or agents,
            "agents_failed": failed_roster,
            "agent_contributions": contributions,
            "agent_responses": agent_responses,
            "dissenting_views": [
                str(v)[:500] for v in (getattr(result, "dissenting_views", []) or [])
            ],
            "consensus_proof": {
                "reached": bool(consensus_reached),
                "confidence": round(confidence, 4) if confidence else 0.0,
                "supporting_agents": contributing_agents if consensus_reached else [],
                "dissenting_agents": [],
                "method": "majority",
                "evidence_hash": input_hash,
            },
            "provenance_chain": [
                {
                    "timestamp": timestamp,
                    "event_type": "verdict",
                    "agent": "aragora ask",
                    "description": "Debate receipt persisted from aragora ask.",
                    "evidence_hash": input_hash,
                }
            ],
        }
        model_comparison = metadata.get("model_comparison") if isinstance(metadata, dict) else None
        if isinstance(model_comparison, dict):
            receipt["model_comparison"] = model_comparison

        # Crux cards (#8227): attached by the consensus phase when the debate
        # ran with enable_crux_cards (--crux-cards). Shared helpers enforce
        # the "only carry non-empty blocks" invariant and the schema-version
        # bump (1.2 when cruxes bind into the hash) with from_debate_result.
        cruxes = crux_cards_from_metadata(metadata)
        if cruxes is not None:
            receipt["cruxes"] = cruxes
        receipt["schema_version"] = receipt_schema_version(cruxes)

        receipt["artifact_hash"] = DecisionReceipt.from_dict(receipt).artifact_hash
        receipt["checksum"] = receipt["artifact_hash"]
        content_hash = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        receipt["content_hash"] = content_hash

        filename = f"{debate_id}_{content_hash}.json"
        receipt_path = receipts_dir / filename
        receipt_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")

        if verbose:
            print(f"[receipt] persisted debate_id={debate_id} hash={content_hash}", file=sys.stderr)

        return str(receipt_path)

    except (OSError, TypeError, ValueError, AttributeError) as e:
        if verbose:
            print(f"[receipt] failed to persist: {e}", file=sys.stderr)
        return None


def _print_debate_result(debate: Any, verbose: bool = False) -> None:
    """Print a standard debate result summary."""
    final_answer = None
    dissenting_agents: list[str] = []
    if getattr(debate, "consensus", None):
        final_answer = debate.consensus.final_answer
        dissenting_agents = debate.consensus.dissenting_agents

    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    if final_answer:
        print(final_answer)
    else:
        print(f"Debate completed with status: {getattr(debate, 'status', 'unknown')}")

    if verbose and dissenting_agents:
        print("\n" + "-" * 60)
        print("DISSENTING AGENTS:")
        for agent in dissenting_agents:
            print(f"- {agent}")


def _print_graph_result(debate: Any, verbose: bool = False) -> None:
    """Print a graph debate result summary."""
    branches = getattr(debate, "branches", []) or []
    consensus = getattr(debate, "consensus", None)
    status = getattr(debate, "status", "unknown")
    if hasattr(status, "value"):
        status = status.value

    print("\n" + "=" * 60)
    print("GRAPH DEBATE RESULT:")
    print("=" * 60)
    print(f"Status: {status}")
    if getattr(debate, "branch_count", None) is not None:
        print(f"Branches: {getattr(debate, 'branch_count')}")
    else:
        print(f"Branches: {len(branches)}")
    if getattr(debate, "node_count", None) is not None:
        print(f"Nodes: {getattr(debate, 'node_count')}")

    if consensus and consensus.final_answer:
        print("\n" + "-" * 60)
        print("CONSENSUS:")
        print(consensus.final_answer)

    if verbose and branches:
        print("\n" + "-" * 60)
        print("BRANCHES:")
        for branch in branches:
            if isinstance(branch, dict):
                name = branch.get("name", "")
                nodes = branch.get("nodes", []) or []
                branch_id = branch.get("branch_id") or branch.get("id") or ""
            else:
                name = getattr(branch, "name", "")
                nodes = getattr(branch, "nodes", []) or []
                branch_id = getattr(branch, "branch_id", "")
            node_count = len(nodes)
            print(f"- {name or branch_id} ({node_count} nodes)")


def _print_matrix_result(debate: Any, verbose: bool = False) -> None:
    """Print a matrix debate result summary."""
    scenarios = getattr(debate, "scenarios", None) or getattr(debate, "results", None) or []
    conclusions = getattr(debate, "conclusions", None)
    status = getattr(debate, "status", "unknown")
    if hasattr(status, "value"):
        status = status.value

    print("\n" + "=" * 60)
    print("MATRIX DEBATE RESULT:")
    print("=" * 60)
    print(f"Status: {status}")
    print(f"Scenarios: {len(scenarios)}")

    if conclusions:
        if conclusions.universal:
            print("\n" + "-" * 60)
            print("UNIVERSAL CONCLUSIONS:")
            for item in conclusions.universal:
                print(f"- {item}")
        if conclusions.conditional:
            print("\n" + "-" * 60)
            print("CONDITIONAL CONCLUSIONS:")
            for scenario, items in conclusions.conditional.items():
                print(f"{scenario}:")
                for item in items:
                    print(f"- {item}")
        if conclusions.contradictions:
            print("\n" + "-" * 60)
            print("CONTRADICTIONS:")
            for item in conclusions.contradictions:
                print(f"- {item}")
    else:
        universal = getattr(debate, "universal_conclusions", []) or []
        conditional = getattr(debate, "conditional_conclusions", {}) or {}
        if universal:
            print("\n" + "-" * 60)
            print("UNIVERSAL CONCLUSIONS:")
            for item in universal:
                print(f"- {item}")
        if conditional:
            print("\n" + "-" * 60)
            print("CONDITIONAL CONCLUSIONS:")
            if isinstance(conditional, dict):
                for scenario, items in conditional.items():
                    print(f"{scenario}:")
                    for item in items:
                        print(f"- {item}")
            else:
                for item in conditional:
                    if isinstance(item, dict):
                        condition = item.get("condition") or item.get("scenario")
                        conclusion = item.get("conclusion")
                        confidence = item.get("confidence")
                        if condition:
                            print(f"{condition}:")
                        if conclusion:
                            suffix = (
                                f" (confidence {confidence:.2f})" if confidence is not None else ""
                            )
                            print(f"- {conclusion}{suffix}")
                    else:
                        print(f"- {item}")

    if verbose and scenarios:
        print("\n" + "-" * 60)
        print("SCENARIO RESULTS:")
        for scenario in scenarios:
            if isinstance(scenario, dict):
                name = scenario.get("scenario_name") or scenario.get("name", "")
                key_findings = scenario.get("key_findings") or scenario.get("key_claims") or []
                conclusion = scenario.get("conclusion")
            else:
                name = getattr(scenario, "scenario_name", "")
                key_findings = getattr(scenario, "key_findings", []) or []
                conclusion = getattr(scenario, "consensus", None)
                if conclusion is not None and hasattr(conclusion, "final_answer"):
                    conclusion = conclusion.final_answer

            print(f"- {name}")
            if conclusion:
                print(f"  Conclusion: {conclusion}")
            if key_findings:
                for finding in key_findings:
                    print(f"  {finding}")


def _print_decision_integrity_summary(package: dict[str, Any]) -> None:
    """Print a decision integrity package summary."""
    receipt = package.get("receipt") or {}
    plan = package.get("plan") or package.get("decision_plan") or {}
    receipt_id = package.get("receipt_id") or receipt.get("receipt_id") or receipt.get("id")
    plan_id = package.get("plan_id") or plan.get("id")
    approval = package.get("approval") or {}
    execution = package.get("execution") or package.get("workflow_execution") or {}

    print("\n" + "=" * 60)
    print("DECISION INTEGRITY PACKAGE")
    print("=" * 60)
    if receipt_id:
        print(f"Receipt ID: {receipt_id}")
    if plan_id:
        print(f"Plan ID: {plan_id}")
    if approval:
        status = approval.get("status") or approval.get("approval_status")
        if status:
            print(f"Approval: {status}")
    if execution:
        status = execution.get("status")
        if status:
            print(f"Execution: {status}")


def _print_model_comparison_summary(summaries: list[dict[str, Any]]) -> None:
    """Print a compact ranking for model-comparison runs."""
    if not summaries:
        return

    print("\n" + "=" * 60)
    print("MODEL COMPARISON")
    print("=" * 60)
    for idx, summary in enumerate(summaries, start=1):
        print(
            f"{idx}. agents={summary['agents']} "
            f"quality={summary['quality_score_10']:.2f} "
            f"practicality={summary['practicality_score_10']:.2f} "
            f"consensus={'yes' if summary['consensus_reached'] else 'no'} "
            f"confidence={summary['confidence']:.2f} "
            f"gate={'pass' if summary['passes_quality_gate'] else 'warn'}"
        )


def _run_debate_api(
    server_url: str,
    api_key: str | None,
    task: str,
    agents: list[Any],
    rounds: int,
    consensus: str,
    context: str | None,
    metadata: dict[str, Any],
    auto_select: bool | None,
    auto_select_config: dict[str, Any] | None,
    enable_verticals: bool,
    vertical_id: str | None,
    timeout_seconds: int,
) -> Any:
    """Run a standard debate via API and wait for completion."""
    client = _build_api_client(server_url, api_key)
    return client.debates.run(
        task=task,
        agents=agents,
        rounds=rounds,
        consensus=consensus,
        timeout=timeout_seconds,
        context=context,
        auto_select=auto_select,
        auto_select_config=auto_select_config,
        enable_verticals=enable_verticals,
        vertical_id=vertical_id,
        metadata=metadata,
    )


def _run_graph_debate_api(
    server_url: str,
    api_key: str | None,
    task: str,
    agents: list[str],
    max_rounds: int,
    branch_threshold: float,
    max_branches: int,
    timeout_seconds: int,
    verbose: bool = False,
) -> Any:
    """Run a graph debate via API and wait for completion."""
    from aragora.client.models import DebateStatus

    client = _build_api_client(server_url, api_key)
    response = client.graph_debates.create(
        task=task,
        agents=agents,
        max_rounds=max_rounds,
        branch_threshold=branch_threshold,
        max_branches=max_branches,
    )
    if getattr(response, "graph", None) or getattr(response, "branches", None):
        return response
    debate_id = response.debate_id

    start = time.time()
    while time.time() - start < timeout_seconds:
        debate = client.graph_debates.get(debate_id)
        if debate.status in (
            DebateStatus.COMPLETED,
            DebateStatus.FAILED,
            DebateStatus.CANCELLED,
        ):
            return debate
        if verbose:
            print(f"[graph] {debate_id} status={debate.status}")
        time.sleep(2)

    raise TimeoutError(f"Graph debate {debate_id} did not complete within timeout")


def _run_matrix_debate_api(
    server_url: str,
    api_key: str | None,
    task: str,
    agents: list[str],
    scenarios: list[dict[str, Any]],
    max_rounds: int,
    timeout_seconds: int,
    verbose: bool = False,
) -> Any:
    """Run a matrix debate via API and wait for completion."""
    from aragora.client.models import DebateStatus

    client = _build_api_client(server_url, api_key)
    response = client.matrix_debates.create(
        task=task,
        agents=agents,
        scenarios=scenarios,
        max_rounds=max_rounds,
    )
    if getattr(response, "results", None) or getattr(response, "universal_conclusions", None):
        return response
    matrix_id = response.matrix_id

    start = time.time()
    while time.time() - start < timeout_seconds:
        debate = client.matrix_debates.get(matrix_id)
        if debate.status in (
            DebateStatus.COMPLETED,
            DebateStatus.FAILED,
            DebateStatus.CANCELLED,
        ):
            return debate
        if verbose:
            print(f"[matrix] {matrix_id} status={debate.status}")
        time.sleep(2)

    raise TimeoutError(f"Matrix debate {matrix_id} did not complete within timeout")


def _build_decision_integrity_api(
    server_url: str,
    api_key: str | None,
    debate_id: str,
    *,
    include_context: bool = False,
    plan_strategy: str = "single_task",
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Build a decision integrity package via API."""
    client = _build_api_client(server_url, api_key)
    return client.debates.decision_integrity(
        debate_id=debate_id,
        include_context=include_context,
        plan_strategy=plan_strategy,
        execution_mode=execution_mode,
    )


def _build_decision_integrity_local(
    result: Any,
    *,
    include_context: bool = False,
    plan_strategy: str = "single_task",
) -> dict[str, Any]:
    """Build a decision integrity package locally from a DebateResult."""
    from aragora.pipeline.decision_integrity import build_decision_integrity_package

    if hasattr(result, "to_dict"):
        debate_payload = result.to_dict()
    else:
        debate_payload = {
            "debate_id": getattr(result, "debate_id", ""),
            "task": getattr(result, "task", ""),
            "final_answer": getattr(result, "final_answer", ""),
            "confidence": getattr(result, "confidence", 0.0),
            "consensus_reached": getattr(result, "consensus_reached", False),
            "rounds_used": getattr(result, "rounds_used", 0),
            "participants": getattr(result, "participants", []),
        }

    package = asyncio.run(
        build_decision_integrity_package(
            debate_payload,
            include_context=include_context,
            plan_strategy=plan_strategy,
        )
    )
    return package.to_dict()


async def run_debate(
    task: str,
    agents_str: str,
    rounds: int = DEFAULT_ROUNDS,  # 9-round format (0-8) default
    consensus: str = DEFAULT_CONSENSUS,  # Judge-based consensus default
    context: str = "",
    learn: bool = True,
    db_path: str = "agora_memory.db",
    enable_audience: bool = True,
    server_url: str = DEFAULT_API_URL,
    protocol_overrides: dict[str, Any] | None = None,
    mode: str | None = None,
    enable_verticals: bool = False,
    vertical_id: str | None = None,
    auto_select: bool = False,
    auto_select_config: dict[str, Any] | None = None,
    codebase_context: bool = False,
    codebase_context_path: str | None = None,
    offline: bool = False,
    **kwargs: Any,
):
    """Run a decision stress-test (debate engine)."""
    from aragora.utils.env import is_offline_mode

    if protocol_overrides is None:
        protocol_overrides = {}

    offline = offline or is_offline_mode()
    if offline:
        # Offline mode should be network-free and quiet.
        enable_audience = False
        learn = False
        protocol_overrides["enable_calibration"] = False

    # Get mode system prompt if specified
    mode_system_prompt = ""
    if mode:
        from aragora.modes import load_builtins

        load_builtins()
        mode_obj = ModeRegistry.get(mode)
        if mode_obj:
            mode_system_prompt = mode_obj.get_system_prompt()
            print(f"[mode] Using '{mode}' mode - {mode_obj.description}")
        else:
            available = ", ".join(ModeRegistry.list_all())
            raise KeyError(f"Mode '{mode}' not found. Available: {available}")

    # Auto-select agents if requested and no explicit list provided
    if auto_select:
        if agents_str and agents_str != DEFAULT_AGENTS:
            print("Warning: --auto-select ignores explicit --agents", file=sys.stderr)
        if not agents_str or agents_str == DEFAULT_AGENTS:
            selected = _auto_select_agents_local(task, auto_select_config)
            if selected:
                agents_str = selected
                print(f"[auto-select] Selected agents: {agents_str}")
            else:
                agents_str = DEFAULT_AGENTS

    if codebase_context and "## CODEBASE INVENTORY" not in context:
        from aragora.debate.codebase_context import build_static_inventory

        inventory = build_static_inventory(codebase_context_path or os.getcwd())
        if inventory:
            context = f"{context}\n\n{inventory}" if context else inventory

    # Parse and create agents
    agent_specs = parse_agents(agents_str)
    if (
        len(agent_specs) == 1
        and int(rounds) <= 1
        and consensus == "none"
        and not mode_system_prompt
    ):
        protocol_overrides.setdefault("single_agent_direct_answer", True)

    # Assign default roles based on position if not explicitly specified
    agents = []
    failed_agents: list[str] = []
    for i, spec in enumerate(agent_specs):
        role = spec.role
        # If role is None (not explicitly specified), assign based on position
        # This ensures diverse debate roles: proposer, critic(s), synthesizer
        if role is None:
            if i == 0:
                role = "proposer"
            elif i == len(agent_specs) - 1 and len(agent_specs) > 1:
                role = "synthesizer"
            else:
                role = "critic"

        try:
            api_key = _resolved_cli_provider_key(spec.provider)
            agent = create_agent(
                model_type=cast(AgentType, spec.provider),
                name=spec.name or f"{spec.provider}_{role}",
                role=role,
                model=spec.model,  # Pass model from spec
                api_key=api_key,
            )
        except (ValueError, ImportError, RuntimeError) as e:
            failed_agents.append(f"{spec.provider} ({e})")
            continue

        # Apply persona as system prompt if specified
        if spec.persona:
            try:
                from aragora.agents.personas import DEFAULT_PERSONAS

                if spec.persona in DEFAULT_PERSONAS:
                    p = DEFAULT_PERSONAS[spec.persona]
                    traits_str = ", ".join(p.traits) if p.traits else "analytical"
                    persona_prompt = f"You are a {traits_str} agent. {p.description}"
                    if p.top_expertise:
                        top_domains = [d for d, _ in p.top_expertise]
                        persona_prompt += f" Your key areas of expertise: {', '.join(top_domains)}."
                    existing = getattr(agent, "system_prompt", "") or ""
                    agent.system_prompt = f"{persona_prompt}\n\n{existing}".strip()

                    # Apply generation parameters from persona
                    if hasattr(agent, "set_generation_params"):
                        agent.set_generation_params(
                            temperature=p.temperature,
                            top_p=p.top_p,
                            frequency_penalty=p.frequency_penalty,
                        )
                else:
                    # Use persona name as a behavioral hint
                    existing = getattr(agent, "system_prompt", "") or ""
                    agent.system_prompt = (
                        f"You are a {spec.persona} in this debate. "
                        f"Approach arguments from that perspective.\n\n{existing}"
                    ).strip()
            except ImportError:
                logger.debug("Personas module not available for spec %s", spec.persona)

        # Apply mode system prompt if specified (takes precedence)
        if mode_system_prompt:
            agent.system_prompt = mode_system_prompt

        agents.append(agent)

    if failed_agents:
        print(
            f"Warning: {len(failed_agents)} agent(s) unavailable:",
            file=sys.stderr,
        )
        for fa in failed_agents:
            print(f"  - {fa}", file=sys.stderr)
    if not agents:
        print(
            "Error: No agents available. Set at least one API key.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if len(agents) < 2:
        print(
            f"Warning: Only {len(agents)} agent available. "
            "Multi-agent debate requires 2+ agents for meaningful consensus.",
            file=sys.stderr,
        )

    agents = _maybe_add_vertical_specialist_local(
        task=task,
        agents=agents,
        enable_verticals=enable_verticals,
        vertical_id=vertical_id,
    )

    # Create environment
    env = Environment(
        task=task,
        context=context,
        max_rounds=rounds,
    )

    # Create protocol
    consensus_type = cast(
        Literal[
            "majority",
            "unanimous",
            "judge",
            "none",
            "weighted",
            "supermajority",
            "any",
            "byzantine",
        ],
        consensus,
    )
    protocol = DebateProtocol(
        rounds=rounds,
        consensus=consensus_type,
        **protocol_overrides,
    )

    # Create memory store
    memory = CritiqueStore(db_path) if learn else None

    # Try to get event emitter for audience participation
    event_emitter = None
    if enable_audience:
        event_emitter = get_event_emitter_if_available(server_url)
        if event_emitter:
            print("[audience] Connected to streaming server - audience participation enabled")

    try:
        # Run debate
        auto_explain = kwargs.pop("auto_explain", False)
        # Pop kwargs that are set on Arena post-init, not accepted by __init__
        enable_cartographer = kwargs.pop("enable_cartographer", None)
        enable_introspection = kwargs.pop("enable_introspection", None)
        arena_kwargs: dict[str, Any] = dict(kwargs)
        if offline:
            arena_kwargs.update(
                {
                    # Disable subsystems that can initialize adapters / embeddings or
                    # attempt network calls in local demo/offline runs.
                    "knowledge_mound": None,
                    "auto_create_knowledge_mound": False,
                    "enable_knowledge_retrieval": False,
                    "enable_knowledge_ingestion": False,
                    "enable_cross_debate_memory": False,
                    # Avoid RLM-based compression and related model calls.
                    "use_rlm_limiter": False,
                    # Disable ML / quality-gate components that may rely on API agents.
                    "enable_ml_delegation": False,
                    "enable_quality_gates": False,
                    "enable_consensus_estimation": False,
                    # Post-debate coordinator can trigger canvas/LLM judge workflows.
                    "disable_post_debate_pipeline": True,
                }
            )
        _coalesce_grouped_arena_configs(arena_kwargs)
        # Strip kwargs that Arena doesn't accept (passed through from CLI/preset parsing)
        import inspect

        _arena_params = set(inspect.signature(Arena.__init__).parameters.keys()) - {"self"}
        arena_kwargs = {k: v for k, v in arena_kwargs.items() if k in _arena_params}

        arena = Arena(
            env,
            agents,
            protocol,
            memory=memory,
            event_emitter=event_emitter,
            **arena_kwargs,
        )

        # Apply post-init configuration flags
        if enable_cartographer is not None:
            setattr(arena, "enable_cartographer", enable_cartographer)  # type: ignore[attr-defined]
        if enable_introspection is not None:
            setattr(arena, "enable_introspection", enable_introspection)

        # Enable auto-explanation if requested
        if auto_explain and hasattr(arena, "extensions") and arena.extensions is not None:
            arena.extensions.auto_explain = True

        result = await arena.run()
        _attach_agent_models_to_result(result, agents)
        _attach_agent_roster_to_result(
            result,
            requested=[spec.name or spec.provider for spec in agent_specs],
            created=[str(getattr(a, "name", "") or "") for a in agents],
            failed=failed_agents,
        )

        # Store result
        if memory:
            memory.store_debate(result)

        return result
    finally:
        if memory is not None:
            memory.close()


def cmd_ask(args: argparse.Namespace) -> None:
    """Handle 'ask' command."""
    logger.debug("Initial task: '%s', context: '%s'", args.task, args.context)
    task = args.task
    raw_task = task
    context = args.context or ""

    # Ambiguity handling
    if len(task.split()) < 3:
        task_brief = handle_ambiguous_task(task)
        task = task_brief.goal  # type: ignore[attr-defined]  # The core goal is now the task
        context += f"\n\n--- Structured Task Brief (Confidence: {task_brief.confidence:.2f}) ---\n"
        objective = getattr(task_brief, "objective", None)
        if objective:
            context += f"Objective: {objective}\n"
        if task_brief.assumptions:  # type: ignore[attr-defined]
            context += "Assumptions:\n" + "\n".join(f"- {a}" for a in task_brief.assumptions)
        # Non-goals and evaluation_criteria are not in V1, but check defensively
        if getattr(task_brief, "non_goals", []):
            context += "\nNon-Goals:\n" + "\n".join(
                f"- {ng}" for ng in getattr(task_brief, "non_goals", [])
            )
        if getattr(task_brief, "success_criteria", []):
            context += "\nSuccess Criteria:\n" + "\n".join(
                f"- {sc}" for sc in task_brief.success_criteria
            )
        context += "\n--------------------------\n"
        if task_brief.requires_user_confirmation:
            logger.info(
                "This task was interpreted from an ambiguous input and requires confirmation."
            )

    # Crux cards (#8227): only the local run_debate path honors
    # enable_crux_cards, so the flag uniformly requires local execution.
    # Graph/matrix are rejected unconditionally (they conflict with local
    # execution below anyway). Explicit API configuration (--api, --api-url,
    # ARAGORA_API_URL) is rejected only when the run is not already local
    # (--local/--demo/ARAGORA_OFFLINE) — a merely-exported ARAGORA_API_URL
    # must not reject a run that could never dispatch to it. Checked up
    # front, before context engineering burns LLM work or ARAGORA_OFFLINE is
    # mutated. Otherwise local execution is forced below (mirroring --demo),
    # with a Note so the auto-discovery path is never silent.
    crux_cards_requested = bool(getattr(args, "crux_cards", False))
    if crux_cards_requested:
        from aragora.utils.env import is_offline_mode as _crux_is_offline

        if getattr(args, "graph", False) or getattr(args, "matrix", False):
            print(
                "--crux-cards currently requires local execution; graph/matrix "
                "debates do not honor it. Remove --graph/--matrix or drop "
                "--crux-cards.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        already_local = (
            getattr(args, "local", False) or getattr(args, "demo", False) or _crux_is_offline()
        )
        crux_api_url = getattr(args, "api_url", None)
        if not already_local and (
            getattr(args, "api", False)
            or _is_explicitly_configured_api_url(
                crux_api_url or DEFAULT_API_URL, flag_passed=crux_api_url is not None
            )
        ):
            print(
                "--crux-cards currently requires local execution; API debates do "
                "not honor it. Add --local, remove --api/--api-url and unset "
                "ARAGORA_API_URL, or drop --crux-cards.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if not getattr(args, "local", False):
            print(
                "Note: --crux-cards is only honored by local execution; "
                "running the debate locally.",
                file=sys.stderr,
            )

    explicit_codebase_context = bool(getattr(args, "codebase_context", False))
    mode_name = str(getattr(args, "mode", "") or "").strip().lower()
    inferred_codebase_context = mode_name == "orchestrator" or _looks_like_self_improvement_task(
        raw_task
    )
    codebase_context_requested = explicit_codebase_context or inferred_codebase_context
    codebase_context_repo: Path | None = None
    if codebase_context_requested:
        from aragora.debate.codebase_context import build_static_inventory
        from aragora.debate.context_engineering import (
            ContextEngineeringConfig,
            build_debate_context_engineering,
        )

        repo_raw = getattr(args, "codebase_context_path", None) or os.getcwd()
        codebase_context_repo = Path(str(repo_raw)).expanduser().resolve()
        if args.verbose and not explicit_codebase_context:
            print(
                "[context-engineering] auto-enabled codebase context"
                f" reason={'mode=orchestrator' if mode_name == 'orchestrator' else 'self-improvement task heuristic'}",
                file=sys.stderr,
            )

        static_inventory = build_static_inventory(
            repo_root=str(codebase_context_repo),
            max_chars=max(
                8_000, int(getattr(args, "codebase_context_inventory_max_chars", 20_000))
            ),
        )
        if static_inventory:
            context = f"{context}\n\n{static_inventory}" if context else static_inventory
            if args.verbose:
                print(
                    f"[context-engineering] static inventory injected chars={len(static_inventory)}",
                    file=sys.stderr,
                )

        cfg = ContextEngineeringConfig(
            task=task,
            repo_path=codebase_context_repo,
            include_tests=not bool(getattr(args, "codebase_context_exclude_tests", False)),
            include_rlm_full_corpus=bool(getattr(args, "codebase_context_rlm", False)),
            include_harness_exploration=bool(getattr(args, "codebase_context_harnesses", False)),
            include_kilocode=bool(getattr(args, "codebase_context_kilocode", False)),
            max_output_chars=max(8_000, int(getattr(args, "codebase_context_max_chars", 80_000))),
            build_timeout_seconds=max(30, int(getattr(args, "codebase_context_timeout", 240))),
            per_explorer_timeout_seconds=max(
                15, min(240, int(getattr(args, "codebase_context_timeout", 240)))
            ),
        )

        if args.verbose:
            print(
                "[context-engineering] building"
                f" repo={codebase_context_repo}"
                f" harnesses={'on' if cfg.include_harness_exploration else 'off'}"
                f" kilocode={'on' if cfg.include_kilocode else 'off'}"
                f" rlm={'on' if cfg.include_rlm_full_corpus else 'off'}"
                f" timeout={cfg.build_timeout_seconds}s",
                file=sys.stderr,
            )

        try:
            engineered = asyncio.run(build_debate_context_engineering(cfg))
        except Exception as e:  # noqa: BLE001 - best-effort pre-debate enrichment
            print(f"[context-engineering] failed: {e}", file=sys.stderr)
        else:
            engineered_context = (engineered.context or "").strip()
            harness_meta = (
                engineered.metadata.get("harnesses", {})
                if isinstance(engineered.metadata, dict)
                else {}
            )
            harness_errors = (
                harness_meta.get("errors", []) if isinstance(harness_meta, dict) else []
            )
            timeout_errors = [
                str(err) for err in harness_errors if "timeout after" in str(err).lower()
            ]
            if timeout_errors:
                print(
                    f"[context-engineering] explorer timeouts={len(timeout_errors)} "
                    f"(per_explorer_timeout={cfg.per_explorer_timeout_seconds}s)",
                    file=sys.stderr,
                )

            if engineered_context:
                if context:
                    context = f"{context}\n\n{engineered_context}"
                else:
                    context = engineered_context
                if args.verbose:
                    duration = engineered.metadata.get("duration_seconds", "n/a")
                    print(
                        f"[context-engineering] injected chars={len(engineered_context)}"
                        f" duration={duration}s",
                        file=sys.stderr,
                    )
                output_path_raw = getattr(args, "codebase_context_out", None)
                if output_path_raw:
                    output_path = Path(str(output_path_raw)).expanduser().resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(engineered_context, encoding="utf-8")
                    if args.verbose:
                        print(
                            f"[context-engineering] wrote={output_path}",
                            file=sys.stderr,
                        )
            elif args.verbose:
                reason = engineered.metadata.get("error", "empty_context")
                print(
                    f"[context-engineering] no context injected ({reason})",
                    file=sys.stderr,
                )

    agents = args.agents
    rounds = args.rounds
    learn = args.learn
    enable_audience = True
    protocol_overrides: dict[str, Any] = {}

    # Apply cross-pollination feature flags
    if not getattr(args, "calibration", True):
        protocol_overrides["enable_calibration"] = False
    if not getattr(args, "evidence_weighting", True):
        protocol_overrides["enable_evidence_weighting"] = False
    if not getattr(args, "trending", True):
        protocol_overrides["enable_trending_injection"] = False
    if crux_cards_requested:
        # Crux cards (#8227): attach load-bearing disagreements to the debate
        # result metadata so the decision receipt carries a cruxes block.
        protocol_overrides["enable_crux_cards"] = True
    # Note: ELO weighting is controlled via WeightCalculatorConfig, passed via protocol

    # Demo mode forces local execution
    force_local = False
    if getattr(args, "demo", False):
        print("Demo mode enabled - using built-in demo agents.")
        # Demo mode is meant to be network-free; align with the global offline flag
        # so subsystems can short-circuit consistently.
        os.environ.setdefault("ARAGORA_OFFLINE", "1")
        agents = "demo,demo,demo"
        rounds = min(args.rounds, 2)
        learn = False
        enable_audience = False
        force_local = True
        protocol_overrides.update(
            {
                "convergence_detection": False,
                "vote_grouping": False,
                "enable_trickster": False,
                "enable_research": False,
                "enable_rhetorical_observer": False,
                "role_rotation": False,
                "role_matching": False,
                # Keep demo/local mode network-free and deterministic.
                "enable_trending_injection": False,
                "enable_llm_question_classification": False,
                "enable_llm_synthesis": False,
            }
        )

    from aragora.utils.env import is_offline_mode

    offline = is_offline_mode()
    if offline:
        enable_audience = False
        learn = False
        protocol_overrides.update(
            {
                "enable_trending_injection": False,
                "enable_llm_question_classification": False,
                "enable_llm_synthesis": False,
                "enable_research": False,
            }
        )

    api_url_arg = getattr(args, "api_url", None)
    api_url_flag_passed = api_url_arg is not None
    server_url = api_url_arg or DEFAULT_API_URL
    api_key = (
        getattr(args, "api_key", None)
        or os.environ.get("ARAGORA_API_TOKEN")
        or os.environ.get("ARAGORA_API_KEY")
    )

    requested_api = getattr(args, "api", False)
    requested_local = getattr(args, "local", False)
    if crux_cards_requested:
        # Explicit API configuration was rejected above; force the local path
        # (like --demo does) so enable_crux_cards is honored even when a
        # trusted API server would otherwise be auto-selected.
        requested_local = True
    graph_mode = getattr(args, "graph", False)
    matrix_mode = getattr(args, "matrix", False)
    decision_integrity = bool(getattr(args, "decision_integrity", False))
    auto_select = bool(getattr(args, "auto_select", False))
    try:
        auto_select_config = _parse_auto_select_config(getattr(args, "auto_select_config", None))
    except ValueError as e:
        print(f"Invalid --auto-select-config: {e}", file=sys.stderr)
        raise SystemExit(2)
    if auto_select_config and not auto_select:
        auto_select = True

    enable_verticals = bool(
        getattr(args, "enable_verticals", False) or getattr(args, "vertical", None)
    )
    vertical_id = getattr(args, "vertical", None)
    default_timeout = int(os.environ.get("ARAGORA_ASK_TIMEOUT_SECONDS", "3600"))
    debate_timeout = int(getattr(args, "timeout", default_timeout) or default_timeout)
    comparison_agent_sets = _collect_comparison_agent_sets(
        agents,
        getattr(args, "compare_against", None),
    )
    comparison_mode = len(comparison_agent_sets) > 1
    protocol_overrides.setdefault("timeout_seconds", debate_timeout)
    protocol_overrides.setdefault(
        "debate_rounds_timeout_seconds",
        max(300, min(debate_timeout - 60, debate_timeout)),
    )

    if force_local or offline:
        requested_local = True
        requested_api = False

    if graph_mode or matrix_mode:
        if requested_local:
            print("Graph/matrix debates require API mode. Remove --local.", file=sys.stderr)
            raise SystemExit(2)
        requested_api = True
        if auto_select:
            # Use local auto-select to choose a team, then pass to graph/matrix APIs
            selected = _auto_select_agents_local(args.task, auto_select_config)
            if selected:
                agents = selected
            else:
                print(
                    "Auto-select failed; provide --agents for graph/matrix debates.",
                    file=sys.stderr,
                )
                raise SystemExit(2)
    if decision_integrity and (graph_mode or matrix_mode):
        print("Decision integrity is only supported for standard debates.", file=sys.stderr)
        raise SystemExit(2)
    if comparison_mode and (graph_mode or matrix_mode):
        print(
            "Model comparison mode only supports standard debates. Remove --graph/--matrix.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if comparison_mode and auto_select:
        print(
            "Model comparison mode requires explicit agent combinations. Remove --auto-select.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if comparison_mode and requested_api:
        print(
            "Model comparison mode currently supports local standard debates only. Remove --api.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if comparison_mode:
        requested_local = True

    di_include_context = bool(getattr(args, "di_include_context", False))
    di_plan_strategy = getattr(args, "di_plan_strategy", "single_task")
    di_execution_mode = getattr(args, "di_execution_mode", None)
    post_consensus_quality = bool(getattr(args, "post_consensus_quality", True))
    upgrade_to_good = bool(getattr(args, "upgrade_to_good", True))
    quality_upgrade_max_loops = max(0, int(getattr(args, "quality_upgrade_max_loops", 2)))
    quality_min_score = float(getattr(args, "quality_min_score", 9.0))
    quality_practical_min_score = float(getattr(args, "quality_practical_min_score", 5.0))
    quality_concretize_max_rounds = max(0, int(getattr(args, "quality_concretize_max_rounds", 3)))
    quality_extra_assessment_rounds = max(
        0, int(getattr(args, "quality_extra_assessment_rounds", 2))
    )
    quality_fail_closed = bool(getattr(args, "quality_fail_closed", False))
    grounding_fail_closed = bool(getattr(args, "grounding_fail_closed", False))
    grounding_min_verified_paths = float(getattr(args, "grounding_min_verified_paths", 0.8))

    if offline or force_local:
        # Keep contract validation/deterministic repairs, but avoid provider-backed
        # quality upgrade loops in demo/offline runs.
        upgrade_to_good = False
        quality_upgrade_max_loops = 0
        quality_concretize_max_rounds = 0
        quality_extra_assessment_rounds = 0

    if not 0.0 <= grounding_min_verified_paths <= 1.0:
        print(
            "Invalid --grounding-min-verified-paths: expected value in [0.0, 1.0].",
            file=sys.stderr,
        )
        raise SystemExit(2)

    def _assess_and_enforce_grounding(final_answer_text: str) -> None:
        from aragora.debate.repo_grounding import (
            assess_repo_grounding,
            format_path_verification_summary,
        )

        report = assess_repo_grounding(
            str(final_answer_text or ""),
            repo_root=str(codebase_context_repo or Path.cwd()),
        )
        print(format_path_verification_summary(report))

        if not grounding_fail_closed:
            return

        total = len(report.mentioned_paths)
        verified_existing = len(report.existing_paths)
        verified_ratio = (verified_existing / total) if total else 0.0
        if total == 0 or verified_ratio < grounding_min_verified_paths:
            print(
                (
                    "Debate failed grounding gate: verified existing path ratio "
                    f"{verified_ratio:.2f} is below required "
                    f"{grounding_min_verified_paths:.2f} (existing={verified_existing}, total={total})."
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)

    def _resolve_output_contract() -> tuple[Any | None, str]:
        from aragora.debate.output_quality import (
            derive_output_contract_from_task,
            load_output_contract_from_file,
        )

        output_contract_file = getattr(args, "output_contract_file", None)
        required_sections = getattr(args, "required_sections", None)
        task_lower = str(args.task or "").lower()
        has_explicit_task_contract = (
            "output sections" in task_lower
            or "required sections" in task_lower
            or "section headings" in task_lower
        )

        if isinstance(output_contract_file, str) and output_contract_file.strip():
            return load_output_contract_from_file(output_contract_file.strip()), "file"

        if isinstance(required_sections, str) and required_sections.strip():
            normalized = ", ".join(
                p.strip() for p in required_sections.strip().split(",") if p.strip()
            )
            return (
                derive_output_contract_from_task(f"output sections {normalized}"),
                "required_sections",
            )

        contract = derive_output_contract_from_task(
            args.task,
            has_context=bool(getattr(args, "context", None)),
        )
        if contract is None:
            return None, "none"
        if contract.required_sections or has_explicit_task_contract:
            return contract, "task"
        return contract, "fallback"

    quality_contract = None
    quality_contract_source = "none"
    output_contract_file = getattr(args, "output_contract_file", None)
    required_sections = getattr(args, "required_sections", None)
    task_lower = str(args.task or "").lower()
    has_explicit_task_contract = (
        "output sections" in task_lower
        or "required sections" in task_lower
        or "section headings" in task_lower
    )
    # Fail-closed cannot be honored when the post-consensus quality pipeline is
    # disabled (and we are not in comparison mode, which has its own enforcement
    # path). Both the config-validation guard below and the runtime gate inside
    # _post_consensus_quality_pipeline are skipped when post_consensus_quality is
    # False, so silently accepting --quality-fail-closed here would emit a false
    # green in CI. Reject the contradictory combination explicitly instead.
    if quality_fail_closed and not post_consensus_quality and not comparison_mode:
        print(
            "Debate configuration invalid: --quality-fail-closed cannot be "
            "enforced together with --no-post-consensus-quality. The fail-closed "
            "quality gate runs inside the post-consensus quality pipeline, which "
            "is disabled. Remove --no-post-consensus-quality to enforce the gate.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if post_consensus_quality or comparison_mode:
        from aragora.debate.output_quality import build_contract_context_block

        if (
            quality_fail_closed
            and not (isinstance(output_contract_file, str) and output_contract_file.strip())
            and not (isinstance(required_sections, str) and required_sections.strip())
            and not has_explicit_task_contract
        ):
            print(
                "Debate configuration invalid: --quality-fail-closed requires an explicit "
                "output contract. Add explicit output sections to the task or pass "
                "--required-sections/--output-contract-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)

        try:
            quality_contract, quality_contract_source = _resolve_output_contract()
        except ValueError as e:
            print(f"Debate configuration invalid: {e}", file=sys.stderr)
            raise SystemExit(2)

        if quality_fail_closed and quality_contract_source in {"none", "fallback"}:
            print(
                "Debate configuration invalid: --quality-fail-closed requires an explicit "
                "output contract. Add output sections to the task or pass --required-sections "
                "or --output-contract-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)

        if post_consensus_quality and quality_contract is not None:
            contract_block = build_contract_context_block(quality_contract)
            if context:
                context = f"{context}\n\n--- Deterministic Output Contract ---\n{contract_block}\n"
            else:
                context = contract_block
        elif post_consensus_quality and args.verbose:
            print(
                "[quality] contract=none (no explicit output sections detected in task)",
                file=sys.stderr,
            )

    use_api = requested_api
    if not requested_api and not requested_local:
        use_api = _trusted_server_available(server_url, flag_passed=api_url_flag_passed)

    if use_api:
        try:
            if graph_mode:
                graph_agents = _agent_names_for_graph_matrix(agents)
                result = _run_graph_debate_api(
                    server_url=server_url,
                    api_key=api_key,
                    task=args.task,
                    agents=graph_agents,
                    max_rounds=args.graph_rounds,
                    branch_threshold=args.branch_threshold,
                    max_branches=args.max_branches,
                    timeout_seconds=debate_timeout,
                    verbose=args.verbose,
                )
                _print_graph_result(result, verbose=args.verbose)
                return

            if matrix_mode:
                matrix_agents = _agent_names_for_graph_matrix(agents)
                scenarios = _parse_matrix_scenarios(args.scenario)
                result = _run_matrix_debate_api(
                    server_url=server_url,
                    api_key=api_key,
                    task=args.task,
                    agents=matrix_agents,
                    scenarios=scenarios,
                    max_rounds=args.matrix_rounds,
                    timeout_seconds=debate_timeout,
                    verbose=args.verbose,
                )
                _print_matrix_result(result, verbose=args.verbose)
                return

            if auto_select:
                if agents and agents != DEFAULT_AGENTS:
                    print("Warning: --auto-select ignores explicit --agents", file=sys.stderr)
                agents_payload = []
            else:
                agents_payload = _agents_payload_for_api(agents)

            result = _run_debate_api(
                server_url=server_url,
                api_key=api_key,
                task=task,
                agents=agents_payload,
                rounds=rounds,
                consensus=args.consensus,
                context=context or None,
                metadata={},
                auto_select=auto_select,
                auto_select_config=auto_select_config,
                enable_verticals=enable_verticals,
                vertical_id=vertical_id,
                timeout_seconds=debate_timeout,
            )
            _print_debate_result(result, verbose=args.verbose)
            if codebase_context_requested or grounding_fail_closed:
                final_answer = getattr(result, "final_answer", None)
                if not final_answer:
                    consensus = getattr(result, "consensus", None)
                    final_answer = getattr(consensus, "final_answer", "") if consensus else ""
                _assess_and_enforce_grounding(str(final_answer or ""))
            if decision_integrity:
                package = _build_decision_integrity_api(
                    server_url=server_url,
                    api_key=api_key,
                    debate_id=result.debate_id,
                    include_context=di_include_context,
                    plan_strategy=di_plan_strategy,
                    execution_mode=di_execution_mode,
                )
                _print_decision_integrity_summary(package)
            return
        except ValidationError as e:
            # The server answered but returned a payload the SDK models could
            # not parse (version skew, or a non-Aragora service on the port).
            # Surface a friendly error instead of a raw pydantic traceback.
            print(
                f"API run failed: server at {server_url} returned an unexpected "
                "response. If this is not an Aragora API server, rerun with "
                "--local (or set ARAGORA_API_URL). Use --verbose for details.",
                file=sys.stderr,
            )
            logger.debug("SDK response validation failed: %s", e)
            if args.verbose:
                print(f"Validation details: {e}", file=sys.stderr)
            raise SystemExit(1)
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            if requested_api or graph_mode or matrix_mode:
                print(f"API run failed: {e}", file=sys.stderr)
                raise SystemExit(1)
            if _is_server_available(server_url):
                print(f"API run failed: {e}", file=sys.stderr)
                raise SystemExit(1)
            print(
                "Warning: API server unavailable, falling back to local execution.",
                file=sys.stderr,
            )

    if not (force_local or offline):
        from aragora.config.provider_readiness import (
            agent_type_has_configured_provider,
            agent_provider_options,
            discover_provider_credentials,
            format_provider_bootstrap_error,
        )

        credential_report = discover_provider_credentials()
        requested_specs = parse_agents(agents)
        provider_backed_specs = [
            spec
            for spec in requested_specs
            if not agent_type_has_configured_provider(spec.provider, credential_report)
        ]
        if provider_backed_specs:
            if not credential_report.any_configured:
                print(format_provider_bootstrap_error(credential_report), file=sys.stderr)
            else:
                configured = ", ".join(credential_report.configured_providers)
                print(
                    "One or more selected agent providers are not configured.",
                    file=sys.stderr,
                )
                print(f"Configured providers: {configured}", file=sys.stderr)
                for spec in provider_backed_specs:
                    options = agent_provider_options(spec.provider)
                    required = ", ".join(options) if options else spec.provider
                    print(
                        f"  - {spec.provider}: requires one of {required}",
                        file=sys.stderr,
                    )
                print(
                    "Run "
                    f"'aragora validate-env --smoke --agents {agents} --verbose' "
                    "and select only configured agents.",
                    file=sys.stderr,
                )
            raise SystemExit(1)

    explain = getattr(args, "explain", False)

    # Apply preset configuration if specified
    preset_kwargs: dict[str, Any] = {}
    preset_name = getattr(args, "preset", None)
    if preset_name:
        from aragora.debate.presets import get_preset

        preset_kwargs = get_preset(preset_name)
        print(f"[preset] Applied '{preset_name}' configuration preset")

    # Create spectator stream if --spectate is specified
    spectate_kwargs: dict[str, Any] = {}
    if getattr(args, "spectate", False):
        from aragora.spectate.stream import SpectatorStream

        spectate_fmt = getattr(args, "spectate_format", "auto")
        spectate_kwargs["spectator"] = SpectatorStream(enabled=True, format=spectate_fmt)

    # CLI flag overrides for ArenaConfig (explicit flags take precedence over presets)
    cli_config_kwargs: dict[str, Any] = {}
    if hasattr(args, "enable_cartographer"):
        cli_config_kwargs["enable_cartographer"] = args.enable_cartographer
    if hasattr(args, "enable_introspection"):
        cli_config_kwargs["enable_introspection"] = args.enable_introspection
    if codebase_context_requested:
        cli_config_kwargs["enable_codebase_grounding"] = True
        if codebase_context_repo is not None:
            cli_config_kwargs["codebase_path"] = str(codebase_context_repo)
    if bool(getattr(args, "no_context_init_rlm", False)):
        cli_config_kwargs["use_rlm_limiter"] = False
        if args.verbose:
            print(
                "[context-init] disabled RLM limiter via --no-context-init-rlm",
                file=sys.stderr,
            )
    if getattr(args, "auto_execute", False):
        cli_config_kwargs["enable_auto_execution"] = True

    overall_timeout_seconds = (
        debate_timeout * max(1, len(comparison_agent_sets)) if comparison_mode else debate_timeout
    )
    start_time = time.monotonic()
    current_agents_for_revision = agents

    def _remaining_global_seconds() -> float:
        return max(0.0, float(overall_timeout_seconds) - (time.monotonic() - start_time))

    def _quality_upgrade_attempt_timeout(
        *,
        remaining_global_seconds: float,
        providers_remaining: int,
    ) -> int | None:
        """Compute per-provider upgrade timeout within remaining wall-clock budget."""
        if remaining_global_seconds <= 0:
            return None
        # Reserve tail budget for deterministic repairs/finalization + CLI reporting.
        reserved_tail_seconds = 60.0
        usable_seconds = max(0.0, remaining_global_seconds - reserved_tail_seconds)
        if usable_seconds <= 0:
            return None

        slots = max(1, providers_remaining)
        # Keep individual retries bounded; avoid multi-minute single-provider stalls.
        return max(60, min(360, int(usable_seconds / slots)))

    def _quality_gate_passes(report: Any) -> bool:
        return bool(
            report.verdict == "good"
            and report.quality_score_10 >= quality_min_score
            and float(getattr(report, "practicality_score_10", 0.0)) >= quality_practical_min_score
        )

    def _report_rank(report: Any) -> tuple[float, float, float]:
        quality_score = float(getattr(report, "quality_score_10", 0.0))
        practicality_score = float(getattr(report, "practicality_score_10", 0.0))
        defect_penalty = float(len(getattr(report, "defects", []) or []))
        # Fewer defects > higher practicality — prevents rejecting a
        # defect-free repair just because practicality dipped slightly.
        return (quality_score, -defect_penalty, practicality_score)

    def _is_better_report(candidate: Any, incumbent: Any) -> bool:
        return _report_rank(candidate) > _report_rank(incumbent)

    revision_penalties: dict[tuple[str, str | None], int] = {}

    def _revision_spec_key(spec: AgentSpec) -> tuple[str, str | None]:
        return (spec.provider, spec.model or None)

    def _mark_revision_penalty(spec: AgentSpec | None) -> None:
        if spec is None:
            return
        key = _revision_spec_key(spec)
        revision_penalties[key] = revision_penalties.get(key, 0) + 1

    def _build_revision_specs(
        *,
        preferred_providers: list[str] | None = None,
    ) -> list[AgentSpec]:
        ordered_specs: list[AgentSpec] = []
        specs = parse_agents(current_agents_for_revision)
        if specs:
            if preferred_providers:
                chosen: set[int] = set()
                for provider_name in preferred_providers:
                    for idx, spec in enumerate(specs):
                        if idx in chosen:
                            continue
                        if spec.provider == provider_name:
                            ordered_specs.append(spec)
                            chosen.add(idx)
                            break
                for idx, spec in enumerate(specs):
                    if idx not in chosen:
                        ordered_specs.append(spec)
            else:
                preferred_order = [len(specs) - 1] + [idx for idx in range(len(specs) - 1)]
                ordered_specs = [specs[idx] for idx in preferred_order if 0 <= idx < len(specs)]

        if preferred_providers:
            seen = {spec.provider for spec in ordered_specs}
            for provider_name in preferred_providers:
                if provider_name in seen:
                    continue
                try:
                    ordered_specs.append(AgentSpec(provider=provider_name, role="synthesizer"))
                    seen.add(provider_name)
                except ValueError as e:
                    logger.debug("Skipping preferred provider %s: %s", provider_name, e)
                    continue

        # Optional OpenRouter fallback for quota/billing/provider outages.
        if is_secret_presence_available(get_secret_presence("OPENROUTER_API_KEY")) and not any(
            spec.provider == "openrouter" for spec in ordered_specs
        ):
            try:
                ordered_specs.append(AgentSpec(provider="openrouter", role="synthesizer"))
            except ValueError as e:
                logger.debug("Could not add openrouter fallback agent: %s", e)

        ranked_specs = list(enumerate(ordered_specs))
        ranked_specs.sort(
            key=lambda item: (
                revision_penalties.get(_revision_spec_key(item[1]), 0),
                item[0],
            )
        )
        return [spec for _, spec in ranked_specs]

    async def _attempt_targeted_revision(
        *,
        prompt: str,
        attempt_num: int,
        stage: str,
        role_hint: str,
        preferred_providers: list[str] | None = None,
    ) -> tuple[str | None, AgentSpec | None]:
        ordered_specs = _build_revision_specs(preferred_providers=preferred_providers)
        if not ordered_specs:
            return (None, None)

        for idx, spec in enumerate(ordered_specs):
            provider = spec.provider
            per_attempt_timeout = _quality_upgrade_attempt_timeout(
                remaining_global_seconds=_remaining_global_seconds(),
                providers_remaining=len(ordered_specs) - idx,
            )
            if per_attempt_timeout is None:
                logger.warning(
                    "%s_budget_exhausted attempt=%s provider=%s",
                    stage,
                    attempt_num,
                    provider,
                )
                break
            try:
                repair_agent = _create_revision_agent(
                    provider,
                    name=f"{stage}_{provider}_{attempt_num}",
                    model=spec.model,
                )
                existing = getattr(repair_agent, "system_prompt", "") or ""
                repair_agent.system_prompt = f"{existing}\n\n{role_hint}".strip()
                repaired = await asyncio.wait_for(
                    repair_agent.generate(prompt),
                    timeout=per_attempt_timeout,
                )
                if repaired and repaired.strip():
                    return (repaired.strip(), spec)
                _mark_revision_penalty(spec)
            except Exception as e:  # noqa: BLE001 - best-effort repair fallback
                _mark_revision_penalty(spec)
                logger.warning("%s_attempt_failed provider=%s error=%s", stage, provider, e)
                continue
        return (None, None)

    async def _attempt_quality_upgrade(
        *,
        current_answer: str,
        defects: list[str],
        attempt_num: int,
    ) -> tuple[str | None, AgentSpec | None]:
        if quality_contract is None:
            return (None, None)

        from aragora.debate.output_quality import build_upgrade_prompt

        prompt = build_upgrade_prompt(
            task=task,
            contract=quality_contract,
            current_answer=current_answer,
            defects=defects,
        )
        role_hint = (
            "You are a post-consensus quality upgrader. Keep core ideas, "
            "fix defects, and preserve required section order."
        )
        return await _attempt_targeted_revision(
            prompt=prompt,
            attempt_num=attempt_num,
            stage="quality_upgrade",
            role_hint=role_hint,
        )

    async def _post_consensus_quality_pipeline(
        result: Any,
        *,
        enforce_fail_closed: bool = True,
    ) -> Any:
        if not post_consensus_quality or quality_contract is None:
            return result

        from aragora.debate.output_quality import (
            apply_deterministic_quality_repairs,
            build_concretization_prompt,
            finalize_json_payload,
            validate_output_against_contract,
        )

        repo_root = os.getcwd()
        metadata = getattr(result, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            setattr(result, "metadata", metadata)

        initial_report = validate_output_against_contract(
            result.final_answer,
            quality_contract,
            repo_root=repo_root,
        )
        best_report = initial_report
        best_answer = result.final_answer
        attempts: list[dict[str, Any]] = []
        loops_used = 0
        loops_by_stage = {"quality_upgrade": 0, "concretization": 0, "assessment_upgrade": 0}
        upgraded = False

        if upgrade_to_good and not _quality_gate_passes(initial_report):
            current_answer = result.final_answer
            current_report = initial_report
            for loop_idx in range(1, quality_upgrade_max_loops + 1):
                loops_by_stage["quality_upgrade"] += 1
                loops_used = loop_idx
                repaired, repair_spec = await _attempt_quality_upgrade(
                    current_answer=current_answer,
                    defects=current_report.defects,
                    attempt_num=loop_idx,
                )
                provider = repair_spec.provider if repair_spec else None
                model = repair_spec.model if repair_spec else None
                if not repaired:
                    attempts.append(
                        {
                            "stage": "quality_upgrade",
                            "loop": loop_idx,
                            "provider": provider or "none",
                            "model": model,
                            "status": "no_revision",
                        }
                    )
                    continue

                revised_report = validate_output_against_contract(
                    repaired,
                    quality_contract,
                    repo_root=repo_root,
                )
                accepted = _is_better_report(revised_report, best_report)

                attempts.append(
                    {
                        "stage": "quality_upgrade",
                        "loop": loop_idx,
                        "provider": provider or "unknown",
                        "model": model,
                        "status": "accepted" if accepted else "rejected",
                        "quality_score_10": revised_report.quality_score_10,
                        "practicality_score_10": revised_report.practicality_score_10,
                        "verdict": revised_report.verdict,
                        "defect_count": len(revised_report.defects),
                    }
                )

                if repair_spec is not None and (
                    not accepted or not _quality_gate_passes(revised_report)
                ):
                    _mark_revision_penalty(repair_spec)

                if accepted:
                    best_answer = repaired
                    best_report = revised_report
                    current_answer = repaired
                    current_report = revised_report
                    if _quality_gate_passes(revised_report):
                        upgraded = True
                        break

        if not _quality_gate_passes(best_report):
            deterministic_answer = apply_deterministic_quality_repairs(
                best_answer,
                quality_contract,
                best_report,
                repo_root=repo_root,
            )
            deterministic_report = validate_output_against_contract(
                deterministic_answer,
                quality_contract,
                repo_root=repo_root,
            )
            deterministic_accepted = _is_better_report(deterministic_report, best_report)
            attempts.append(
                {
                    "stage": "deterministic_repair",
                    "loop": loops_used + 1,
                    "provider": "deterministic_repair",
                    "status": "accepted" if deterministic_accepted else "rejected",
                    "quality_score_10": deterministic_report.quality_score_10,
                    "practicality_score_10": deterministic_report.practicality_score_10,
                    "verdict": deterministic_report.verdict,
                    "defect_count": len(deterministic_report.defects),
                }
            )
            if deterministic_accepted:
                best_answer = deterministic_answer
                best_report = deterministic_report
                upgraded = _quality_gate_passes(deterministic_report) or upgraded

        if quality_contract.require_json_payload:
            json_finalized_answer = finalize_json_payload(best_answer, quality_contract)
            json_finalized_report = validate_output_against_contract(
                json_finalized_answer,
                quality_contract,
                repo_root=repo_root,
            )
            json_finalized_accepted = _is_better_report(json_finalized_report, best_report)
            attempts.append(
                {
                    "stage": "deterministic_json_finalizer",
                    "loop": loops_used + 2,
                    "provider": "deterministic_json_finalizer",
                    "status": "accepted" if json_finalized_accepted else "rejected",
                    "quality_score_10": json_finalized_report.quality_score_10,
                    "practicality_score_10": json_finalized_report.practicality_score_10,
                    "verdict": json_finalized_report.verdict,
                    "defect_count": len(json_finalized_report.defects),
                }
            )
            if json_finalized_accepted:
                best_answer = json_finalized_answer
                best_report = json_finalized_report
                upgraded = _quality_gate_passes(json_finalized_report) or upgraded

        if quality_concretize_max_rounds > 0 and not _quality_gate_passes(best_report):
            for round_idx in range(1, quality_concretize_max_rounds + 1):
                loops_by_stage["concretization"] += 1
                loops_used += 1
                concretize_prompt = build_concretization_prompt(
                    task=task,
                    contract=quality_contract,
                    current_answer=best_answer,
                    practicality_score_10=best_report.practicality_score_10,
                    target_practicality_10=quality_practical_min_score,
                    defects=best_report.defects,
                )
                revised, revision_spec = await _attempt_targeted_revision(
                    prompt=concretize_prompt,
                    attempt_num=round_idx,
                    stage="concretization",
                    role_hint=(
                        "You are a concretization specialist. Raise execution practicality by "
                        "turning first-batch tasks into path-grounded, testable actions."
                    ),
                )
                provider = revision_spec.provider if revision_spec else None
                model = revision_spec.model if revision_spec else None
                if not revised:
                    attempts.append(
                        {
                            "stage": "concretization",
                            "loop": round_idx,
                            "provider": provider or "none",
                            "model": model,
                            "status": "no_revision",
                        }
                    )
                    continue
                revised_report = validate_output_against_contract(
                    revised,
                    quality_contract,
                    repo_root=repo_root,
                )
                accepted = _is_better_report(revised_report, best_report)
                attempts.append(
                    {
                        "stage": "concretization",
                        "loop": round_idx,
                        "provider": provider or "unknown",
                        "model": model,
                        "status": "accepted" if accepted else "rejected",
                        "quality_score_10": revised_report.quality_score_10,
                        "practicality_score_10": revised_report.practicality_score_10,
                        "verdict": revised_report.verdict,
                        "defect_count": len(revised_report.defects),
                    }
                )
                if revision_spec is not None and (
                    not accepted or not _quality_gate_passes(revised_report)
                ):
                    _mark_revision_penalty(revision_spec)
                if accepted:
                    best_answer = revised
                    best_report = revised_report
                    if _quality_gate_passes(revised_report):
                        upgraded = True
                        break

        practicality_shortfall = (
            float(getattr(best_report, "practicality_score_10", 0.0)) < quality_practical_min_score
        )
        if quality_extra_assessment_rounds > 0 and practicality_shortfall:
            for round_idx in range(1, quality_extra_assessment_rounds + 1):
                loops_by_stage["assessment_upgrade"] += 1
                loops_used += 1
                preferred_providers = (
                    ["claude", "codex"] if (round_idx % 2 == 1) else ["codex", "claude"]
                )
                assessment_prompt = build_concretization_prompt(
                    task=task,
                    contract=quality_contract,
                    current_answer=best_answer,
                    practicality_score_10=best_report.practicality_score_10,
                    target_practicality_10=quality_practical_min_score,
                    defects=best_report.defects
                    + [
                        f"Raise practicality score to >= {quality_practical_min_score:.2f}.",
                        "Ground owner paths to existing repository files.",
                    ],
                )
                revised, revision_spec = await _attempt_targeted_revision(
                    prompt=assessment_prompt,
                    attempt_num=round_idx,
                    stage="assessment_upgrade",
                    role_hint=(
                        "You are an independent post-consensus assessor. Improve practical value "
                        "without discarding valid consensus details."
                    ),
                    preferred_providers=preferred_providers,
                )
                provider = revision_spec.provider if revision_spec else None
                model = revision_spec.model if revision_spec else None
                if not revised:
                    attempts.append(
                        {
                            "stage": "assessment_upgrade",
                            "loop": round_idx,
                            "provider": provider or "none",
                            "model": model,
                            "status": "no_revision",
                        }
                    )
                    continue

                revised_report = validate_output_against_contract(
                    revised,
                    quality_contract,
                    repo_root=repo_root,
                )
                accepted = _is_better_report(revised_report, best_report)
                attempts.append(
                    {
                        "stage": "assessment_upgrade",
                        "loop": round_idx,
                        "provider": provider or "unknown",
                        "model": model,
                        "status": "accepted" if accepted else "rejected",
                        "quality_score_10": revised_report.quality_score_10,
                        "practicality_score_10": revised_report.practicality_score_10,
                        "verdict": revised_report.verdict,
                        "defect_count": len(revised_report.defects),
                    }
                )
                if revision_spec is not None and (
                    not accepted or not _quality_gate_passes(revised_report)
                ):
                    _mark_revision_penalty(revision_spec)
                if accepted:
                    best_answer = revised
                    best_report = revised_report
                    if _quality_gate_passes(revised_report):
                        upgraded = True
                        break

        result.final_answer = best_answer
        metadata["post_consensus_quality"] = {
            "enabled": True,
            "contract": quality_contract.to_dict(),
            "target_quality_score_10": quality_min_score,
            "target_practicality_score_10": quality_practical_min_score,
            "initial_report": initial_report.to_dict(),
            "final_report": best_report.to_dict(),
            "loops_used": loops_used,
            "loops_by_stage": loops_by_stage,
            "upgraded": upgraded,
            "attempts": attempts,
        }

        if enforce_fail_closed and quality_fail_closed and not _quality_gate_passes(best_report):
            raise RuntimeError(
                "Post-consensus quality gate failed after upgrade loops: "
                + "; ".join(best_report.defects[:3])
                + f" (quality={best_report.quality_score_10}, "
                + f"practicality={best_report.practicality_score_10})"
            )

        return result

    def _build_comparison_summary(result: Any, agents_value: str) -> dict[str, Any]:
        final_report: dict[str, Any] = {}
        quality_meta = None
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            quality_meta = metadata.get("post_consensus_quality")
        if isinstance(quality_meta, dict):
            final_report = quality_meta.get("final_report", {}) or {}
        elif quality_contract is not None:
            from aragora.debate.output_quality import validate_output_against_contract

            fallback_report = validate_output_against_contract(
                str(getattr(result, "final_answer", "") or ""),
                quality_contract,
                repo_root=os.getcwd(),
            )
            final_report = fallback_report.to_dict()

        summary = {
            "agents": _normalize_agents_combo(agents_value),
            "quality_score_10": float(final_report.get("quality_score_10", 0.0) or 0.0),
            "practicality_score_10": float(final_report.get("practicality_score_10", 0.0) or 0.0),
            "consensus_reached": bool(getattr(result, "consensus_reached", False)),
            "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
            "passes_quality_gate": bool(
                final_report.get("verdict") == "good"
                and float(final_report.get("quality_score_10", 0.0) or 0.0) >= quality_min_score
                and float(final_report.get("practicality_score_10", 0.0) or 0.0)
                >= quality_practical_min_score
            ),
            "verdict": str(final_report.get("verdict", "unknown") or "unknown"),
            "defect_count": len(final_report.get("defects") or []),
            "rounds_used": int(getattr(result, "rounds_used", 0) or 0),
            "duration_seconds": float(getattr(result, "duration_seconds", 0.0) or 0.0),
            "debate_id": str(getattr(result, "debate_id", "") or ""),
        }
        return summary

    def _comparison_rank(
        summary: dict[str, Any],
    ) -> tuple[int, float, float, int, float, float, int]:
        return (
            1 if summary["passes_quality_gate"] else 0,
            float(summary["quality_score_10"]),
            float(summary["practicality_score_10"]),
            1 if summary["consensus_reached"] else 0,
            float(summary["confidence"]),
            -float(summary["duration_seconds"]),
            -int(summary["defect_count"]),
        )

    async def _run_with_timeout(
        *,
        agents_override: str | None = None,
        enforce_quality_fail_closed: bool = True,
    ) -> Any:
        nonlocal current_agents_for_revision
        agents_value = agents_override or agents
        current_agents_for_revision = agents_value
        debate_result = await asyncio.wait_for(
            run_debate(
                task=task,
                agents_str=agents_value,
                rounds=rounds,
                consensus=args.consensus,
                context=context,
                learn=learn,
                db_path=args.db,
                enable_audience=enable_audience,
                server_url=server_url,
                protocol_overrides=protocol_overrides,
                mode=getattr(args, "mode", None),
                enable_verticals=enable_verticals,
                vertical_id=vertical_id,
                auto_select=auto_select,
                auto_select_config=auto_select_config,
                codebase_context=codebase_context_requested,
                codebase_context_path=str(codebase_context_repo) if codebase_context_repo else None,
                offline=offline or force_local,
                auto_explain=explain,
                **preset_kwargs,
                **spectate_kwargs,
                **cli_config_kwargs,
            ),
            timeout=debate_timeout,
        )
        return await _post_consensus_quality_pipeline(
            debate_result,
            enforce_fail_closed=enforce_quality_fail_closed,
        )

    async def _run_model_comparison() -> tuple[Any, list[dict[str, Any]], list[dict[str, str]]]:
        ranked_candidates: list[tuple[dict[str, Any], Any]] = []
        comparison_failures_local: list[dict[str, str]] = []
        total_candidates = len(comparison_agent_sets)

        for idx, combo_agents in enumerate(comparison_agent_sets, start=1):
            print(f"[compare] running {idx}/{total_candidates} agents={combo_agents}")
            try:
                combo_result = await _run_with_timeout(
                    agents_override=combo_agents,
                    enforce_quality_fail_closed=False,
                )
            except asyncio.TimeoutError:
                comparison_failures_local.append(
                    {
                        "agents": combo_agents,
                        "error": f"timed out after {debate_timeout}s",
                    }
                )
                print(
                    f"[compare] failed agents={combo_agents} error=timed out after {debate_timeout}s",
                    file=sys.stderr,
                )
                continue
            except Exception as e:  # noqa: BLE001 - comparison should continue when a combo fails
                comparison_failures_local.append({"agents": combo_agents, "error": str(e)})
                print(
                    f"[compare] failed agents={combo_agents} error={e}",
                    file=sys.stderr,
                )
                continue

            summary = _build_comparison_summary(combo_result, combo_agents)
            ranked_candidates.append((summary, combo_result))

        if not ranked_candidates:
            raise RuntimeError("All compared agent combinations failed.")

        ranked_candidates.sort(key=lambda item: _comparison_rank(item[0]), reverse=True)
        comparison_summaries_local = [summary for summary, _ in ranked_candidates]
        selected_result = ranked_candidates[0][1]
        return selected_result, comparison_summaries_local, comparison_failures_local

    result = None
    comparison_summaries: list[dict[str, Any]] = []
    comparison_failures: list[dict[str, str]] = []
    try:
        with _strict_wall_clock_timeout(overall_timeout_seconds):
            if comparison_mode:
                result, comparison_summaries, comparison_failures = asyncio.run(
                    _run_coro_with_cmd_ask_cleanup(_run_model_comparison())
                )
                metadata = getattr(result, "metadata", None)
                if not isinstance(metadata, dict):
                    metadata = {}
                    setattr(result, "metadata", metadata)
                metadata["model_comparison"] = {
                    "selected_agents": comparison_summaries[0]["agents"],
                    "selection_metric": [
                        "passes_quality_gate",
                        "quality_score_10",
                        "practicality_score_10",
                        "consensus_reached",
                        "confidence",
                        "duration_seconds",
                        "defect_count",
                    ],
                    "candidates": comparison_summaries,
                    "failures": comparison_failures,
                }
                _print_model_comparison_summary(comparison_summaries)
                print(f"[compare] selected agents={comparison_summaries[0]['agents']}")

                if quality_fail_closed and not comparison_summaries[0]["passes_quality_gate"]:
                    raise RuntimeError(
                        "Best model comparison result still failed the quality gate: "
                        f"quality={comparison_summaries[0]['quality_score_10']}, "
                        f"practicality={comparison_summaries[0]['practicality_score_10']}"
                    )
            else:
                result = asyncio.run(_run_coro_with_cmd_ask_cleanup(_run_with_timeout()))
    except _StrictWallClockTimeout:
        elapsed = time.monotonic() - start_time
        cleanup = _cleanup_cli_subprocesses_for_timeout()
        _emit_timeout_failure_payload(
            error_type="strict_wall_clock_timeout",
            timeout_seconds=overall_timeout_seconds,
            elapsed_seconds=elapsed,
            task=raw_task,
            agents_str=agents,
            comparison_agents=comparison_agent_sets if comparison_mode else None,
            mode=getattr(args, "mode", None),
            cleanup=cleanup,
        )
        print(
            f"Debate timed out after {overall_timeout_seconds}s (strict wall-clock; elapsed={elapsed:.2f}s)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start_time
        cleanup = _cleanup_cli_subprocesses_for_timeout()
        _emit_timeout_failure_payload(
            error_type="async_wait_for_timeout",
            timeout_seconds=overall_timeout_seconds,
            elapsed_seconds=elapsed,
            task=raw_task,
            agents_str=agents,
            comparison_agents=comparison_agent_sets if comparison_mode else None,
            mode=getattr(args, "mode", None),
            cleanup=cleanup,
        )
        print(
            f"Debate timed out after {overall_timeout_seconds}s (async wait_for; elapsed={elapsed:.2f}s)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except RuntimeError as e:
        print(f"Debate failed quality gate: {e}", file=sys.stderr)
        raise SystemExit(1)

    if _result_has_only_agent_failure_outputs(result):
        # Surface a substantive final answer if one exists (issue #9304): the
        # engine can synthesize a real answer even when round messages were
        # placeholders — hiding it behind a bare exit-1 buries user value.
        final = str(getattr(result, "final_answer", "") or "")
        if final and not _looks_like_agent_failure_response(final):
            print("\n" + "=" * 60)
            print("FINAL ANSWER (degraded run — agent rounds reported errors):")
            print("=" * 60)
            print(final)
        print(
            "Debate failed: all selected agents returned provider/error placeholders. "
            f"Run 'aragora validate-env --smoke --agents {agents} --verbose' and retry.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    print(result.final_answer)
    if codebase_context_requested or grounding_fail_closed:
        _assess_and_enforce_grounding(str(getattr(result, "final_answer", "") or ""))

    quality_meta = None
    if isinstance(getattr(result, "metadata", None), dict):
        quality_meta = result.metadata.get("post_consensus_quality")
    if isinstance(quality_meta, dict):
        final_report = quality_meta.get("final_report", {})
        print(
            f"\n[quality] verdict={final_report.get('verdict', 'unknown')} "
            f"score={final_report.get('quality_score_10', 'n/a')} "
            f"practicality={final_report.get('practicality_score_10', 'n/a')} "
            f"loops={quality_meta.get('loops_used', 0)} "
            f"upgraded={quality_meta.get('upgraded', False)}"
        )
        defects = final_report.get("defects") or []
        if defects and args.verbose:
            for defect in defects[:5]:
                print(f"[quality] defect: {defect}")
    elif post_consensus_quality:
        print("[quality] skipped=no_contract reason=no_explicit_output_contract_detected")

    # Display explanation if --explain was requested
    if explain:
        explanation = getattr(result, "explanation", None)
        if explanation:
            try:
                from aragora.explainability.builder import ExplanationBuilder

                summary = ExplanationBuilder().generate_summary(explanation)
                print("\nWHY THIS ANSWER:")
                print("-" * 40)
                print(summary)
            except (ImportError, AttributeError, TypeError) as e:
                logger.debug("Could not generate explanation summary: %s", e)

    if result.dissenting_views and args.verbose:
        print("\n" + "-" * 60)
        print("DISSENTING VIEWS:")
        for view in result.dissenting_views:
            print(f"\n{view}")

    # Auto-persist receipt for audit trail
    receipt_path = _persist_debate_receipt(result, verbose=args.verbose)
    if receipt_path:
        print(f"\nReceipt saved: {receipt_path}")
        print(f"  View:   aragora receipt view {receipt_path}")
        print(f"  Verify: aragora receipt verify {receipt_path}")

    if decision_integrity:
        if di_execution_mode and di_execution_mode != "plan_only":
            print(
                "Decision integrity execution is only supported in API mode. "
                "Generating plan-only package.",
                file=sys.stderr,
            )
        package = _build_decision_integrity_local(
            result,
            include_context=di_include_context,
            plan_strategy=di_plan_strategy,
        )
        _print_decision_integrity_summary(package)
