"""
Server Extensions Manager - Unified extension initialization and lifecycle.

Manages the initialization and lifecycle of optional extension layers:
- Agent Fabric: High-scale agent orchestration substrate
- Gastown: Developer orchestration (workspace, rigs, convoys)
- Moltbot: Consumer/device interface (inbox, gateway, voice, onboarding)

Extensions are loaded based on feature flags and can be disabled
for reduced memory footprint or feature isolation.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aragora.utils.optional_imports import try_import

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Flags
# =============================================================================


def _env_bool(key: str, default: bool = False) -> bool:
    """Parse boolean from environment variable."""
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


# Extension feature flags
ENABLE_AGENT_FABRIC = _env_bool("ARAGORA_ENABLE_AGENT_FABRIC", True)
ENABLE_GASTOWN = _env_bool("ARAGORA_ENABLE_GASTOWN", True)
ENABLE_MOLTBOT = _env_bool("ARAGORA_ENABLE_MOLTBOT", True)
ENABLE_COMPUTER_USE = _env_bool("ARAGORA_ENABLE_COMPUTER_USE", False)  # Disabled by default


# =============================================================================
# Optional Imports - Extensions
# =============================================================================

# Agent Fabric
_imp, FABRIC_AVAILABLE = try_import(
    "aragora.fabric",
    "AgentFabric",
    "FabricConfig",
    "HookManager",
    "HookManagerConfig",
)
AgentFabric = _imp.get("AgentFabric")
FabricConfig = _imp.get("FabricConfig")
HookManager = _imp.get("HookManager")
HookManagerConfig = _imp.get("HookManagerConfig")

# Gastown Extension
_imp, GASTOWN_AVAILABLE = try_import(
    "aragora.extensions.gastown",
    "WorkspaceManager",
    "ConvoyTracker",
    "HookRunner",
    "Coordinator",
    "GastownConvoyAdapter",
)
WorkspaceManager = _imp.get("WorkspaceManager")
ConvoyTracker = _imp.get("ConvoyTracker")
GastownHookRunner = _imp.get("HookRunner")
Coordinator = _imp.get("Coordinator")
GastownConvoyAdapter = _imp.get("GastownConvoyAdapter")

# Moltbot Extension
_imp, MOLTBOT_AVAILABLE = try_import(
    "aragora.extensions.moltbot",
    "InboxManager",
    "LocalGateway",
    "VoiceProcessor",
    "OnboardingOrchestrator",
    "MoltbotGatewayAdapter",
)
InboxManager = _imp.get("InboxManager")
LocalGateway = _imp.get("LocalGateway")
VoiceProcessor = _imp.get("VoiceProcessor")
OnboardingOrchestrator = _imp.get("OnboardingOrchestrator")
MoltbotGatewayAdapter = _imp.get("MoltbotGatewayAdapter")

# Computer Use
_imp, COMPUTER_USE_AVAILABLE = try_import(
    "aragora.computer_use",
    "ComputerUseOrchestrator",
    "ComputerPolicyChecker",
    "ComputerUseConfig",
    "create_default_computer_policy",
    "PlaywrightActionExecutor",
    "ExecutorConfig",
)
ComputerUseOrchestrator = _imp.get("ComputerUseOrchestrator")
ComputerPolicyChecker = _imp.get("ComputerPolicyChecker")
ComputerUseConfig = _imp.get("ComputerUseConfig")
create_default_computer_policy = _imp.get("create_default_computer_policy")
PlaywrightActionExecutor = _imp.get("PlaywrightActionExecutor")
ExecutorConfig = _imp.get("ExecutorConfig")


# =============================================================================
# Extension State Container
# =============================================================================


@dataclass
class ExtensionState:
    """Container for initialized extension instances."""

    # Agent Fabric
    fabric: Any | None = None
    hook_manager: Any | None = None

    # Gastown
    workspace_manager: Any | None = None
    convoy_tracker: Any | None = None
    gastown_hooks: Any | None = None
    coordinator: Any | None = None
    gastown_adapter: Any | None = None

    # Moltbot
    inbox_manager: Any | None = None
    local_gateway: Any | None = None
    voice_processor: Any | None = None
    onboarding: Any | None = None
    moltbot_adapter: Any | None = None

    # Computer Use
    computer_orchestrator: Any | None = None
    computer_policy: Any | None = None
    computer_approval_workflow: Any | None = None
    computer_approval_enforcer: Any | None = None

    # Status tracking
    fabric_enabled: bool = False
    gastown_enabled: bool = False
    moltbot_enabled: bool = False
    computer_use_enabled: bool = False

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)


# Global extension state (singleton pattern matching other server subsystems)
_extension_state: ExtensionState | None = None


def get_extension_state() -> ExtensionState | None:
    """Get the current extension state singleton."""
    return _extension_state


# =============================================================================
# Initialization Functions
# =============================================================================


def init_agent_fabric(
    storage_path: Path | None = None,
    enable_hooks: bool = True,
) -> tuple[Any | None, Any | None]:
    """
    Initialize the Agent Fabric orchestration substrate.

    Args:
        storage_path: Path for fabric state storage
        enable_hooks: Enable GUPP hook persistence

    Returns:
        Tuple of (AgentFabric instance, HookManager instance)
    """
    if not ENABLE_AGENT_FABRIC or not FABRIC_AVAILABLE:
        logger.debug("[extensions] Agent Fabric disabled or unavailable")
        return None, None

    try:
        # Initialize fabric with default config
        config = FabricConfig() if FabricConfig else None
        fabric = AgentFabric(config) if AgentFabric else None

        # Initialize hook manager for GUPP persistence
        hook_manager = None
        if enable_hooks and HookManager and HookManagerConfig:
            hook_config = HookManagerConfig(
                workspace_root=str(storage_path) if storage_path else ".",
                use_git_worktrees=False,  # Disable worktrees by default in server mode
            )
            hook_manager = HookManager(hook_config)

        if fabric:
            logger.info("[extensions] Agent Fabric initialized")

        return fabric, hook_manager

    except (ImportError, TypeError, ValueError, OSError) as e:
        logger.warning("[extensions] Failed to initialize Agent Fabric: %s", e)
        return None, None


def init_gastown(storage_path: Path | None = None) -> tuple[Any | None, ...]:
    """
    Initialize the Gastown developer orchestration extension.

    Args:
        storage_path: Path for Gastown state storage

    Returns:
        Tuple of (Coordinator, WorkspaceManager, ConvoyTracker, HookRunner, GastownConvoyAdapter)
    """
    if not ENABLE_GASTOWN or not GASTOWN_AVAILABLE:
        logger.debug("[extensions] Gastown disabled or unavailable")
        return None, None, None, None

    try:
        gastown_path = storage_path / "gastown" if storage_path else None

        # Initialize components
        workspace_mgr = (
            WorkspaceManager(storage_path=gastown_path / "workspaces" if gastown_path else None)
            if WorkspaceManager
            else None
        )

        convoy_tracker = (
            ConvoyTracker(storage_path=gastown_path / "convoys" if gastown_path else None)
            if ConvoyTracker
            else None
        )

        hook_runner = (
            GastownHookRunner(
                storage_path=gastown_path / "hooks" if gastown_path else None,
                auto_commit=False,  # Manual commits in server mode
            )
            if GastownHookRunner
            else None
        )

        # Initialize coordinator with all components
        coordinator = (
            Coordinator(
                storage_path=gastown_path if gastown_path else None,
                auto_persist=True,
                workspace_manager=workspace_mgr,
                convoy_tracker=convoy_tracker,
                hook_runner=hook_runner,
            )
            if Coordinator
            else None
        )

        if GastownConvoyAdapter:
            gastown_adapter = (
                GastownConvoyAdapter(tracker=convoy_tracker)
                if convoy_tracker is not None
                else GastownConvoyAdapter()
            )
        else:
            gastown_adapter = None

        if coordinator:
            logger.info("[extensions] Gastown extension initialized")

        return coordinator, workspace_mgr, convoy_tracker, hook_runner, gastown_adapter

    except (ImportError, TypeError, ValueError, OSError) as e:
        logger.warning("[extensions] Failed to initialize Gastown: %s", e)
        return None, None, None, None, None


def init_moltbot(storage_path: Path | None = None) -> tuple[Any | None, ...]:
    """
    Initialize the Moltbot consumer/device interface extension.

    Args:
        storage_path: Path for Moltbot state storage

    Returns:
        Tuple of (InboxManager, LocalGateway, VoiceProcessor, OnboardingOrchestrator, MoltbotGatewayAdapter)
    """
    if not ENABLE_MOLTBOT or not MOLTBOT_AVAILABLE:
        logger.debug("[extensions] Moltbot disabled or unavailable")
        return None, None, None, None, None

    try:
        moltbot_path = storage_path / "moltbot" if storage_path else None

        canonical_gateway = None
        if os.getenv("MOLTBOT_CANONICAL_GATEWAY", "1") == "1":
            from aragora.gateway.canonical_api import GatewayRuntime

            canonical_gateway = GatewayRuntime()

        # Initialize components
        inbox = (
            InboxManager(
                storage_path=moltbot_path / "inbox" if moltbot_path else None,
                gateway_inbox=canonical_gateway.inbox if canonical_gateway else None,
            )
            if InboxManager
            else None
        )

        gateway = (
            LocalGateway(
                gateway_id=os.getenv("ARAGORA_GATEWAY_ID", "default"),
                storage_path=moltbot_path / "gateway" if moltbot_path else None,
                registry=canonical_gateway.registry if canonical_gateway else None,
                mirror_registry=bool(canonical_gateway),
            )
            if LocalGateway
            else None
        )

        voice = (
            VoiceProcessor(
                storage_path=moltbot_path / "voice" if moltbot_path else None,
            )
            if VoiceProcessor
            else None
        )

        onboarding = (
            OnboardingOrchestrator(
                storage_path=moltbot_path / "onboarding" if moltbot_path else None
            )
            if OnboardingOrchestrator
            else None
        )

        moltbot_adapter = (
            MoltbotGatewayAdapter(gateway=canonical_gateway) if MoltbotGatewayAdapter else None
        )

        if inbox or gateway:
            logger.info("[extensions] Moltbot extension initialized")

        return inbox, gateway, voice, onboarding, moltbot_adapter

    except (ImportError, TypeError, ValueError, OSError) as e:
        logger.warning("[extensions] Failed to initialize Moltbot: %s", e)
        return None, None, None, None, None


def init_computer_use() -> tuple[Any | None, Any | None, Any | None, Any | None]:
    """
    Initialize the Computer Use orchestration (disabled by default).

    Returns:
        Tuple of (ComputerUseOrchestrator, ComputerPolicyChecker, ApprovalWorkflow, UnifiedApprovalEnforcer)
    """
    if not ENABLE_COMPUTER_USE or not COMPUTER_USE_AVAILABLE:
        logger.debug("[extensions] Computer Use disabled or unavailable")
        return None, None, None, None

    try:
        # Create default policy
        default_policy = None
        policy_checker = None
        if create_default_computer_policy:
            default_policy = create_default_computer_policy()
        if ComputerPolicyChecker and default_policy:
            policy_checker = ComputerPolicyChecker(default_policy)

        # Create approval workflow and enforcer (optional)
        approval_workflow = None
        approval_enforcer = None
        approval_timeout = float(os.getenv("ARAGORA_COMPUTER_USE_APPROVAL_TIMEOUT", "300"))
        try:
            from aragora.computer_use.approval import create_approval_workflow

            approval_workflow = create_approval_workflow(
                webhook_url=os.getenv("ARAGORA_COMPUTER_USE_APPROVAL_WEBHOOK"),
                require_reason=_env_bool("ARAGORA_COMPUTER_USE_APPROVAL_REQUIRE_REASON", False),
                timeout_seconds=approval_timeout,
            )
        except (ImportError, TypeError, ValueError):
            approval_workflow = None

        try:
            from aragora.security.approval_enforcer import (
                UnifiedApprovalEnforcer,
                set_approval_enforcer,
            )

            approval_enforcer = UnifiedApprovalEnforcer(
                policy=None,
                approval_workflow=approval_workflow,
            )
            set_approval_enforcer(approval_enforcer)
        except (ImportError, TypeError, ValueError):
            approval_enforcer = None

        # Create executor for browser automation
        executor = None
        if PlaywrightActionExecutor:
            executor = PlaywrightActionExecutor()

        # Create orchestrator with executor and policy
        orchestrator = (
            ComputerUseOrchestrator(
                executor=executor,
                policy=default_policy,
                config=ComputerUseConfig(
                    max_steps=20,
                    total_timeout_seconds=300,
                    enforce_sensitive_approvals=approval_workflow is not None,
                    approval_timeout_seconds=approval_timeout,
                ),
                approval_workflow=approval_workflow,
                approval_enforcer=approval_enforcer,
            )
            if ComputerUseOrchestrator and ComputerUseConfig
            else None
        )

        if orchestrator:
            logger.info("[extensions] Computer Use initialized (with policy enforcement)")

        return orchestrator, policy_checker, approval_workflow, approval_enforcer

    except (ImportError, TypeError, ValueError, OSError) as e:
        logger.warning("[extensions] Failed to initialize Computer Use: %s", e)
        return None, None, None, None


# =============================================================================
# Unified Extension Manager
# =============================================================================


def init_extensions(storage_path: Path | None = None) -> ExtensionState:
    """
    Initialize all enabled extensions.

    This is the main entry point for server startup to initialize
    all extension layers based on feature flags.

    Args:
        storage_path: Base path for extension state storage

    Returns:
        ExtensionState with all initialized extensions
    """
    global _extension_state

    state = ExtensionState()

    # Create storage directory if specified
    if storage_path:
        storage_path.mkdir(parents=True, exist_ok=True)

    # Initialize Agent Fabric
    fabric, hook_mgr = init_agent_fabric(storage_path)
    state.fabric = fabric
    state.hook_manager = hook_mgr
    state.fabric_enabled = fabric is not None

    # Initialize Gastown
    coordinator, workspace_mgr, convoy_tracker, gastown_hooks, gastown_adapter = init_gastown(
        storage_path
    )
    state.coordinator = coordinator
    state.workspace_manager = workspace_mgr
    state.convoy_tracker = convoy_tracker
    state.gastown_hooks = gastown_hooks
    state.gastown_adapter = gastown_adapter
    state.gastown_enabled = coordinator is not None

    # Initialize Moltbot
    inbox, gateway, voice, onboarding, moltbot_adapter = init_moltbot(storage_path)
    state.inbox_manager = inbox
    state.local_gateway = gateway
    state.voice_processor = voice
    state.onboarding = onboarding
    state.moltbot_adapter = moltbot_adapter
    state.moltbot_enabled = inbox is not None or gateway is not None

    # Initialize Computer Use
    computer_orch, computer_policy, approval_workflow, approval_enforcer = init_computer_use()
    state.computer_orchestrator = computer_orch
    state.computer_policy = computer_policy
    state.computer_approval_workflow = approval_workflow
    state.computer_approval_enforcer = approval_enforcer
    state.computer_use_enabled = computer_orch is not None

    # Store metadata
    state.metadata = {
        "fabric_available": FABRIC_AVAILABLE,
        "gastown_available": GASTOWN_AVAILABLE,
        "moltbot_available": MOLTBOT_AVAILABLE,
        "computer_use_available": COMPUTER_USE_AVAILABLE,
    }

    # Set global state
    _extension_state = state

    # Log summary
    enabled = []
    if state.fabric_enabled:
        enabled.append("AgentFabric")
    if state.gastown_enabled:
        enabled.append("Gastown")
    if state.moltbot_enabled:
        enabled.append("Moltbot")
    if state.computer_use_enabled:
        enabled.append("ComputerUse")

    if enabled:
        logger.info("[extensions] Enabled extensions: %s", ", ".join(enabled))
    else:
        logger.info("[extensions] No extensions enabled")

    return state


async def shutdown_extensions() -> None:
    """
    Gracefully shutdown all extensions.

    Called during server shutdown to clean up extension resources.
    """
    global _extension_state

    if not _extension_state:
        return

    # Shutdown Moltbot gateway (if running)
    if _extension_state.local_gateway:
        try:
            await _extension_state.local_gateway.stop()
            logger.debug("[extensions] Moltbot gateway stopped")
        except (OSError, RuntimeError, asyncio.CancelledError) as e:
            logger.warning("[extensions] Error stopping gateway: %s", e)

    # Persist extension state
    if _extension_state.coordinator:
        try:
            await _extension_state.coordinator.persist_all()
            logger.debug("[extensions] Gastown state persisted")
        except (OSError, RuntimeError, asyncio.CancelledError) as e:
            logger.warning("[extensions] Error persisting Gastown: %s", e)

    logger.info("[extensions] Extensions shutdown complete")
    _extension_state = None


def get_extension_stats() -> dict[str, Any]:
    """
    Get statistics from all enabled extensions.

    Returns:
        Dictionary with stats from each extension
    """
    if not _extension_state:
        return {"error": "Extensions not initialized"}

    stats = {
        "fabric_enabled": _extension_state.fabric_enabled,
        "gastown_enabled": _extension_state.gastown_enabled,
        "moltbot_enabled": _extension_state.moltbot_enabled,
        "computer_use_enabled": _extension_state.computer_use_enabled,
    }

    # Note: Full stats would require async calls, this is sync summary only
    return stats
