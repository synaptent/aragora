"""
Stream package for real-time debate streaming via WebSocket.

This package provides the infrastructure for broadcasting debate events
to connected clients in real-time.

Main components:
- events: Event types and data classes (StreamEventType, StreamEvent)
- emitter: Event emitter and audience participation (SyncEventEmitter, AudienceInbox)
- state_manager: Debate and loop state management (DebateStateManager)
- arena_hooks: Arena integration hooks (create_arena_hooks)
- broadcaster: Client management and broadcasting utilities (WebSocketBroadcaster)
- server_base: Common server functionality (ServerBase, ServerConfig)
- servers: WebSocket and HTTP server classes (DebateStreamServer, AiohttpUnifiedServer)
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    # Events
    "StreamEventType": ("aragora.server.stream.events", "StreamEventType"),
    "StreamEvent": ("aragora.server.stream.events", "StreamEvent"),
    "AudienceMessage": ("aragora.server.stream.events", "AudienceMessage"),
    # Emitter
    "TokenBucket": ("aragora.server.stream.emitter", "TokenBucket"),
    "AudienceInbox": ("aragora.server.stream.emitter", "AudienceInbox"),
    "SyncEventEmitter": ("aragora.server.stream.emitter", "SyncEventEmitter"),
    "normalize_intensity": ("aragora.server.stream.emitter", "normalize_intensity"),
    # State management
    "BoundedDebateDict": ("aragora.server.stream.state_manager", "BoundedDebateDict"),
    "LoopInstance": ("aragora.server.stream.state_manager", "LoopInstance"),
    "DebateStateManager": ("aragora.server.stream.state_manager", "DebateStateManager"),
    "get_active_debates": ("aragora.server.stream.state_manager", "get_active_debates"),
    "get_active_debates_lock": ("aragora.server.stream.state_manager", "get_active_debates_lock"),
    "get_debate_executor": ("aragora.server.stream.state_manager", "get_debate_executor"),
    "set_debate_executor": ("aragora.server.stream.state_manager", "set_debate_executor"),
    "get_debate_executor_lock": ("aragora.server.stream.state_manager", "get_debate_executor_lock"),
    "cleanup_stale_debates": ("aragora.server.stream.state_manager", "cleanup_stale_debates"),
    "increment_cleanup_counter": (
        "aragora.server.stream.state_manager",
        "increment_cleanup_counter",
    ),
    "get_stream_state_manager": (
        "aragora.server.stream.state_manager",
        "get_stream_state_manager",
    ),
    # Arena hooks
    "create_arena_hooks": ("aragora.server.stream.arena_hooks", "create_arena_hooks"),
    "wrap_agent_for_streaming": ("aragora.server.stream.arena_hooks", "wrap_agent_for_streaming"),
    # Gauntlet streaming
    "GauntletStreamEmitter": ("aragora.server.stream.gauntlet_emitter", "GauntletStreamEmitter"),
    "GauntletPhase": ("aragora.server.stream.gauntlet_emitter", "GauntletPhase"),
    "create_gauntlet_emitter": (
        "aragora.server.stream.gauntlet_emitter",
        "create_gauntlet_emitter",
    ),
    # Broadcaster
    "BroadcasterConfig": ("aragora.server.stream.broadcaster", "BroadcasterConfig"),
    "ClientManager": ("aragora.server.stream.broadcaster", "ClientManager"),
    "DebateStateCache": ("aragora.server.stream.broadcaster", "DebateStateCache"),
    "LoopRegistry": ("aragora.server.stream.broadcaster", "LoopRegistry"),
    "WebSocketBroadcaster": ("aragora.server.stream.broadcaster", "WebSocketBroadcaster"),
    # Server base
    "ServerBase": ("aragora.server.stream.server_base", "ServerBase"),
    "ServerConfig": ("aragora.server.stream.server_base", "ServerConfig"),
    # Servers
    "DebateStreamServer": ("aragora.server.stream.debate_stream_server", "DebateStreamServer"),
    "AiohttpUnifiedServer": ("aragora.server.stream.servers", "AiohttpUnifiedServer"),
    "DEBATE_AVAILABLE": ("aragora.server.stream.debate_stream_server", "DEBATE_AVAILABLE"),
    # Control plane stream
    "ControlPlaneStreamServer": (
        "aragora.server.stream.control_plane_stream",
        "ControlPlaneStreamServer",
    ),
    "ControlPlaneEventType": (
        "aragora.server.stream.control_plane_stream",
        "ControlPlaneEventType",
    ),
    "ControlPlaneEvent": (
        "aragora.server.stream.control_plane_stream",
        "ControlPlaneEvent",
    ),
    # Nomic loop stream
    "NomicLoopStreamServer": (
        "aragora.server.stream.nomic_loop_stream",
        "NomicLoopStreamServer",
    ),
    "NomicLoopEventType": (
        "aragora.server.stream.nomic_loop_stream",
        "NomicLoopEventType",
    ),
    "NomicLoopEvent": (
        "aragora.server.stream.nomic_loop_stream",
        "NomicLoopEvent",
    ),
    # Voice stream
    "VoiceStreamHandler": (
        "aragora.server.stream.voice_stream",
        "VoiceStreamHandler",
    ),
    "VoiceSession": (
        "aragora.server.stream.voice_stream",
        "VoiceSession",
    ),
    # TTS event bridge
    "TTSEventBridge": (
        "aragora.server.stream.tts_event_bridge",
        "TTSEventBridge",
    ),
    "AudioPlaybackState": (
        "aragora.server.stream.tts_event_bridge",
        "AudioPlaybackState",
    ),
    # Autonomous operations stream (Phase 5)
    "AutonomousStreamEmitter": (
        "aragora.server.stream.autonomous_stream",
        "AutonomousStreamEmitter",
    ),
    "AutonomousStreamClient": (
        "aragora.server.stream.autonomous_stream",
        "AutonomousStreamClient",
    ),
    "get_autonomous_emitter": (
        "aragora.server.stream.autonomous_stream",
        "get_autonomous_emitter",
    ),
    "set_autonomous_emitter": (
        "aragora.server.stream.autonomous_stream",
        "set_autonomous_emitter",
    ),
    "emit_approval_event": (
        "aragora.server.stream.autonomous_stream",
        "emit_approval_event",
    ),
    "emit_alert_event": (
        "aragora.server.stream.autonomous_stream",
        "emit_alert_event",
    ),
    "emit_trigger_event": (
        "aragora.server.stream.autonomous_stream",
        "emit_trigger_event",
    ),
    "emit_monitoring_event": (
        "aragora.server.stream.autonomous_stream",
        "emit_monitoring_event",
    ),
    "emit_learning_event": (
        "aragora.server.stream.autonomous_stream",
        "emit_learning_event",
    ),
    "autonomous_websocket_handler": (
        "aragora.server.stream.autonomous_stream",
        "autonomous_websocket_handler",
    ),
    "register_autonomous_stream_routes": (
        "aragora.server.stream.autonomous_stream",
        "register_autonomous_stream_routes",
    ),
    # Team inbox stream
    "TeamInboxEmitter": (
        "aragora.server.stream.team_inbox",
        "TeamInboxEmitter",
    ),
    "TeamInboxEvent": (
        "aragora.server.stream.team_inbox",
        "TeamInboxEvent",
    ),
    "TeamInboxEventType": (
        "aragora.server.stream.team_inbox",
        "TeamInboxEventType",
    ),
    "get_team_inbox_emitter": (
        "aragora.server.stream.team_inbox",
        "get_team_inbox_emitter",
    ),
    "TeamMember": (
        "aragora.server.stream.team_inbox",
        "TeamMember",
    ),
    "Mention": (
        "aragora.server.stream.team_inbox",
        "Mention",
    ),
    "InternalNote": (
        "aragora.server.stream.team_inbox",
        "InternalNote",
    ),
    # Inbox sync stream
    "InboxSyncEmitter": (
        "aragora.server.stream.inbox_sync",
        "InboxSyncEmitter",
    ),
    "InboxSyncEvent": (
        "aragora.server.stream.inbox_sync",
        "InboxSyncEvent",
    ),
    "InboxSyncEventType": (
        "aragora.server.stream.inbox_sync",
        "InboxSyncEventType",
    ),
    "get_inbox_sync_emitter": (
        "aragora.server.stream.inbox_sync",
        "get_inbox_sync_emitter",
    ),
    # Pipeline stream (Idea-to-Execution)
    "PipelineStreamEmitter": (
        "aragora.server.stream.pipeline_stream",
        "PipelineStreamEmitter",
    ),
    "PipelineStreamClient": (
        "aragora.server.stream.pipeline_stream",
        "PipelineStreamClient",
    ),
    "get_pipeline_emitter": (
        "aragora.server.stream.pipeline_stream",
        "get_pipeline_emitter",
    ),
    "set_pipeline_emitter": (
        "aragora.server.stream.pipeline_stream",
        "set_pipeline_emitter",
    ),
    "pipeline_websocket_handler": (
        "aragora.server.stream.pipeline_stream",
        "pipeline_websocket_handler",
    ),
    "register_pipeline_stream_routes": (
        "aragora.server.stream.pipeline_stream",
        "register_pipeline_stream_routes",
    ),
    # Prompt engine stream (prompt-to-spec pipeline)
    "PromptEngineStreamEmitter": (
        "aragora.server.stream.prompt_engine_stream",
        "PromptEngineStreamEmitter",
    ),
    "PromptEngineStreamClient": (
        "aragora.server.stream.prompt_engine_stream",
        "PromptEngineStreamClient",
    ),
    "get_prompt_engine_emitter": (
        "aragora.server.stream.prompt_engine_stream",
        "get_prompt_engine_emitter",
    ),
    "set_prompt_engine_emitter": (
        "aragora.server.stream.prompt_engine_stream",
        "set_prompt_engine_emitter",
    ),
    "prompt_engine_websocket_handler": (
        "aragora.server.stream.prompt_engine_stream",
        "prompt_engine_websocket_handler",
    ),
    "register_prompt_engine_stream_routes": (
        "aragora.server.stream.prompt_engine_stream",
        "register_prompt_engine_stream_routes",
    ),
    # Workflow stream (WorkflowEngine execution)
    "WorkflowStreamEmitter": (
        "aragora.server.stream.workflow_stream",
        "WorkflowStreamEmitter",
    ),
    "WorkflowStreamClient": (
        "aragora.server.stream.workflow_stream",
        "WorkflowStreamClient",
    ),
    "get_workflow_emitter": (
        "aragora.server.stream.workflow_stream",
        "get_workflow_emitter",
    ),
    "set_workflow_emitter": (
        "aragora.server.stream.workflow_stream",
        "set_workflow_emitter",
    ),
    "workflow_websocket_handler": (
        "aragora.server.stream.workflow_stream",
        "workflow_websocket_handler",
    ),
    "register_workflow_stream_routes": (
        "aragora.server.stream.workflow_stream",
        "register_workflow_stream_routes",
    ),
    # Oracle real-time stream
    "oracle_websocket_handler": (
        "aragora.server.stream.oracle_stream",
        "oracle_websocket_handler",
    ),
    "register_oracle_stream_routes": (
        "aragora.server.stream.oracle_stream",
        "register_oracle_stream_routes",
    ),
    "OracleSession": (
        "aragora.server.stream.oracle_stream",
        "OracleSession",
    ),
    "SentenceAccumulator": (
        "aragora.server.stream.oracle_stream",
        "SentenceAccumulator",
    ),
    # Backward compatibility
    "_cleanup_stale_debates_stream": (
        "aragora.server.stream.servers",
        "_cleanup_stale_debates_stream",
    ),
    "_wrap_agent_for_streaming": ("aragora.server.stream.servers", "_wrap_agent_for_streaming"),
    "_active_debates": ("aragora.server.stream.state_manager", "_active_debates"),
    "_active_debates_lock": ("aragora.server.stream.state_manager", "_active_debates_lock"),
    "_debate_executor_lock": ("aragora.server.stream.state_manager", "_debate_executor_lock"),
    "_DEBATE_TTL_SECONDS": ("aragora.server.stream.servers", "_DEBATE_TTL_SECONDS"),
    "TRUSTED_PROXIES": ("aragora.server.stream.servers", "TRUSTED_PROXIES"),
    "_safe_error_message": ("aragora.server.errors", "safe_error_message"),
    "_debate_executor": ("aragora.server.stream.state_manager", "_debate_executor"),
    "_get_active_debates": ("aragora.server.stream.state_manager", "get_active_debates"),
}

_DYNAMIC_EXPORTS = {"_debate_executor"}

__all__ = [
    # Events
    "StreamEventType",
    "StreamEvent",
    "AudienceMessage",
    # Emitter
    "TokenBucket",
    "AudienceInbox",
    "SyncEventEmitter",
    "normalize_intensity",
    # State management
    "BoundedDebateDict",
    "LoopInstance",
    "DebateStateManager",
    "get_active_debates",
    "get_active_debates_lock",
    "get_debate_executor",
    "set_debate_executor",
    "get_debate_executor_lock",
    "cleanup_stale_debates",
    "increment_cleanup_counter",
    "get_stream_state_manager",
    # Arena hooks
    "create_arena_hooks",
    "wrap_agent_for_streaming",
    # Broadcaster
    "BroadcasterConfig",
    "ClientManager",
    "DebateStateCache",
    "LoopRegistry",
    "WebSocketBroadcaster",
    # Server base
    "ServerBase",
    "ServerConfig",
    # Servers
    "DebateStreamServer",
    "AiohttpUnifiedServer",
    "DEBATE_AVAILABLE",
    # Control plane stream
    "ControlPlaneStreamServer",
    "ControlPlaneEventType",
    "ControlPlaneEvent",
    # Nomic loop stream
    "NomicLoopStreamServer",
    "NomicLoopEventType",
    "NomicLoopEvent",
    # Voice stream
    "VoiceStreamHandler",
    "VoiceSession",
    # TTS event bridge
    "TTSEventBridge",
    "AudioPlaybackState",
    # Autonomous operations stream (Phase 5)
    "AutonomousStreamEmitter",
    "AutonomousStreamClient",
    "get_autonomous_emitter",
    "set_autonomous_emitter",
    "emit_approval_event",
    "emit_alert_event",
    "emit_trigger_event",
    "emit_monitoring_event",
    "emit_learning_event",
    "autonomous_websocket_handler",
    "register_autonomous_stream_routes",
    # Team inbox stream
    "TeamInboxEmitter",
    "TeamInboxEvent",
    "TeamInboxEventType",
    "get_team_inbox_emitter",
    "TeamMember",
    "Mention",
    "InternalNote",
    # Inbox sync stream
    "InboxSyncEmitter",
    "InboxSyncEvent",
    "InboxSyncEventType",
    "get_inbox_sync_emitter",
    # Pipeline stream (Idea-to-Execution)
    "PipelineStreamEmitter",
    "PipelineStreamClient",
    "get_pipeline_emitter",
    "set_pipeline_emitter",
    "pipeline_websocket_handler",
    "register_pipeline_stream_routes",
    # Workflow stream (WorkflowEngine execution)
    "WorkflowStreamEmitter",
    "WorkflowStreamClient",
    "get_workflow_emitter",
    "set_workflow_emitter",
    "workflow_websocket_handler",
    "register_workflow_stream_routes",
    # Oracle real-time stream
    "oracle_websocket_handler",
    "register_oracle_stream_routes",
    "OracleSession",
    "SentenceAccumulator",
    # Backward compatibility
    "_cleanup_stale_debates_stream",
    "_wrap_agent_for_streaming",
    "_active_debates",
    "_active_debates_lock",
    "_debate_executor_lock",
    "_DEBATE_TTL_SECONDS",
    "TRUSTED_PROXIES",
    "_safe_error_message",
    "_debate_executor",
]


def __getattr__(name: str) -> Any:
    """Lazily import stream components to avoid side effects on package import."""
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr_name)
        if name not in _DYNAMIC_EXPORTS:
            globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_EXPORTS.keys()))
