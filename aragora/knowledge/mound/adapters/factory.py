"""
AdapterFactory - Auto-create and register KM adapters from Arena subsystems.

This factory enables automatic adapter injection in Arena by creating
appropriate adapters based on available subsystems.

Usage:
    from aragora.knowledge.mound.adapters.factory import AdapterFactory

    # Create adapters from Arena subsystems
    factory = AdapterFactory()
    adapters = factory.create_from_config(
        elo_system=arena.elo_system,
        continuum_memory=arena.continuum_memory,
        evidence_store=arena.evidence_collector,
        insight_store=arena.insight_store,
    )

    # Register with coordinator
    factory.register_with_coordinator(coordinator, adapters)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.knowledge.mound.bidirectional_coordinator import BidirectionalCoordinator

logger = logging.getLogger(__name__)


@dataclass
class AdapterSpec:
    """Specification for an adapter."""

    name: str
    adapter_class: type
    required_deps: list[str]
    forward_method: str = "sync_to_km"
    reverse_method: str | None = "sync_from_km"
    priority: int = 0
    enabled_by_default: bool = True
    config_key: str | None = None  # Key in ArenaConfig to check for explicit adapter


# Registry of available adapter specifications
ADAPTER_SPECS: dict[str, AdapterSpec] = {}


def register_adapter_spec(spec: AdapterSpec) -> None:
    """Register an adapter specification."""
    ADAPTER_SPECS[spec.name] = spec


# ---------------------------------------------------------------------------
# Data-driven adapter registry
# ---------------------------------------------------------------------------
# Each entry: (module_path, class_name, AdapterSpec kwargs)
# module_path is relative to this package (e.g. ".continuum_adapter")
_ADAPTER_DEFS: list[tuple[str, str, dict[str, Any]]] = [
    # --- Core memory adapters ---
    (
        ".continuum_adapter",
        "ContinuumAdapter",
        {
            "name": "continuum",
            "required_deps": ["continuum_memory"],
            "forward_method": "store",
            "reverse_method": "sync_validations_to_continuum",
            "priority": 100,
            "config_key": "km_continuum_adapter",
        },
    ),
    (
        ".consensus_adapter",
        "ConsensusAdapter",
        {
            "name": "consensus",
            "required_deps": ["consensus_memory"],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_validations_from_km",
            "priority": 90,
            "config_key": "km_consensus_adapter",
        },
    ),
    (
        ".critique_adapter",
        "CritiqueAdapter",
        {
            "name": "critique",
            "required_deps": ["memory"],
            "forward_method": "store",
            "reverse_method": "sync_validations_from_km",
            "priority": 80,
            "config_key": "km_critique_adapter",
        },
    ),
    # --- Bidirectional integration adapters ---
    (
        ".evidence_adapter",
        "EvidenceAdapter",
        {
            "name": "evidence",
            "required_deps": ["evidence_store"],
            "forward_method": "store",
            "reverse_method": "update_reliability_from_km",
            "priority": 70,
            "config_key": "km_evidence_adapter",
        },
    ),
    (
        ".belief_adapter",
        "BeliefAdapter",
        {
            "name": "belief",
            "required_deps": [],
            "forward_method": "store_converged_belief",
            "reverse_method": "sync_validations_from_km",
            "priority": 60,
            "config_key": "km_belief_adapter",
        },
    ),
    (
        ".insights_adapter",
        "InsightsAdapter",
        {
            "name": "insights",
            "required_deps": ["insight_store"],
            "forward_method": "store_insight",
            "reverse_method": "sync_validations_from_km",
            "priority": 50,
            "config_key": "km_insights_adapter",
        },
    ),
    (
        ".performance_adapter",
        "EloAdapter",
        {
            "name": "elo",
            "required_deps": ["elo_system"],
            "forward_method": "store_match",
            "reverse_method": "sync_km_to_elo",
            "priority": 40,
            "config_key": "km_elo_bridge",
        },
    ),
    (
        ".performance_adapter",
        "PerformanceAdapter",
        {
            "name": "performance",
            "required_deps": ["elo_system"],
            "forward_method": "store_match",
            "reverse_method": "sync_km_to_elo",
            "priority": 45,
            "enabled_by_default": False,
            "config_key": "km_performance_adapter",
        },
    ),
    # --- Operational adapters ---
    (
        ".pulse_adapter",
        "PulseAdapter",
        {
            "name": "pulse",
            "required_deps": ["pulse_manager"],
            "forward_method": "store_trending_topic",
            "reverse_method": "sync_validations_from_km",
            "priority": 30,
            "config_key": "km_pulse_adapter",
        },
    ),
    (
        ".cost_adapter",
        "CostAdapter",
        {
            "name": "cost",
            "required_deps": ["cost_tracker"],
            "forward_method": "store_anomaly",
            "reverse_method": "sync_validations_from_km",
            "priority": 10,
            "enabled_by_default": False,
            "config_key": "km_cost_adapter",
        },
    ),
    (
        ".provenance_adapter",
        "ProvenanceAdapter",
        {
            "name": "provenance",
            "required_deps": ["provenance_store"],
            "forward_method": "ingest_provenance",
            "reverse_method": None,
            "priority": 75,
            "config_key": "km_provenance_adapter",
        },
    ),
    # --- Extension module adapters ---
    (
        ".fabric_adapter",
        "FabricAdapter",
        {
            "name": "fabric",
            "required_deps": ["fabric"],
            "forward_method": "sync_from_fabric",
            "reverse_method": "get_pool_recommendations",
            "priority": 35,
            "config_key": "km_fabric_adapter",
        },
    ),
    (
        ".workspace_adapter",
        "WorkspaceAdapter",
        {
            "name": "workspace",
            "required_deps": ["workspace_manager"],
            "forward_method": "sync_from_workspace",
            "reverse_method": "get_rig_recommendations",
            "priority": 34,
            "config_key": "km_workspace_adapter",
        },
    ),
    (
        ".computer_use_adapter",
        "ComputerUseAdapter",
        {
            "name": "computer_use",
            "required_deps": ["computer_use_orchestrator"],
            "forward_method": "sync_from_orchestrator",
            "reverse_method": "get_similar_tasks",
            "priority": 33,
            "config_key": "km_computer_use_adapter",
        },
    ),
    (
        ".gateway_adapter",
        "GatewayAdapter",
        {
            "name": "gateway",
            "required_deps": ["gateway"],
            "forward_method": "sync_from_gateway",
            "reverse_method": "get_routing_recommendations",
            "priority": 32,
            "config_key": "km_gateway_adapter",
        },
    ),
    # --- Advanced integration adapters ---
    (
        ".calibration_fusion_adapter",
        "CalibrationFusionAdapter",
        {
            "name": "calibration_fusion",
            "required_deps": [],
            # CalibrationFusionAdapter exposes sync_to_km/search_by_topic.
            # Registering missing method names causes noisy runtime warnings
            # and skips adapter wiring during debate context collection.
            "forward_method": "sync_to_km",
            "reverse_method": "search_by_topic",
            "priority": 55,
            "config_key": "km_calibration_fusion_adapter",
        },
    ),
    (
        ".control_plane_adapter",
        "ControlPlaneAdapter",
        {
            "name": "control_plane",
            "required_deps": ["control_plane"],
            "forward_method": "sync_from_control_plane",
            "reverse_method": "get_policy_recommendations",
            "priority": 85,
            "config_key": "km_control_plane_adapter",
        },
    ),
    (
        ".culture_adapter",
        "CultureAdapter",
        {
            "name": "culture",
            "required_deps": [],
            "forward_method": "sync_to_mound",
            "reverse_method": "load_from_mound",
            "priority": 25,
            "config_key": "km_culture_adapter",
        },
    ),
    (
        ".receipt_adapter",
        "ReceiptAdapter",
        {
            "name": "receipt",
            "required_deps": [],
            "forward_method": "ingest_receipt",
            "reverse_method": "find_related_decisions",
            "priority": 65,
            "config_key": "km_receipt_adapter",
        },
    ),
    (
        ".decision_plan_adapter",
        "DecisionPlanAdapter",
        {
            "name": "decision_plan",
            "required_deps": [],
            "forward_method": "ingest_plan_outcome",
            "reverse_method": "query_similar_plans",
            "priority": 64,
            "config_key": "km_decision_plan_adapter",
        },
    ),
    (
        ".outcome_adapter",
        "OutcomeAdapter",
        {
            "name": "outcome",
            "required_deps": [],
            "forward_method": "ingest",
            "reverse_method": "find_similar_outcomes",
            "priority": 62,
            "config_key": "km_outcome_adapter",
        },
    ),
    (
        ".supermemory_adapter",
        "SupermemoryAdapter",
        {
            "name": "supermemory",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 15,
            "enabled_by_default": False,
        },
    ),
    (
        ".rlm_adapter",
        "RlmAdapter",
        {
            "name": "rlm",
            "required_deps": ["compressor"],
            "forward_method": "sync_to_mound",
            "reverse_method": "load_from_mound",
            "priority": 20,
            "config_key": "km_rlm_adapter",
        },
    ),
    (
        ".trickster_adapter",
        "TricksterAdapter",
        {
            "name": "trickster",
            "required_deps": ["trickster"],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 55,
            "config_key": "km_trickster_adapter",
        },
    ),
    (
        ".erc8004_adapter",
        "ERC8004Adapter",
        {
            "name": "erc8004",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 80,
            "enabled_by_default": False,
            "config_key": "km_erc8004_adapter",
        },
    ),
    (
        ".obsidian_adapter",
        "ObsidianAdapter",
        {
            "name": "obsidian",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 50,
            "config_key": "km_obsidian_adapter",
        },
    ),
    # --- High-level domain adapters ---
    (
        ".debate_adapter",
        "DebateAdapter",
        {
            "name": "debate",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 88,
            "config_key": "km_debate_adapter",
        },
    ),
    (
        ".workflow_adapter",
        "WorkflowAdapter",
        {
            "name": "workflow",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 50,
            "config_key": "km_workflow_adapter",
        },
    ),
    (
        ".compliance_adapter",
        "ComplianceAdapter",
        {
            "name": "compliance",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 75,
            "config_key": "km_compliance_adapter",
        },
    ),
    (
        ".langextract_adapter",
        "LangExtractAdapter",
        {
            "name": "langextract",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_validations_from_km",
            "priority": 72,
            "enabled_by_default": False,
            "config_key": "km_langextract_adapter",
        },
    ),
    (
        ".codebase_adapter",
        "CodebaseAdapter",
        {
            "name": "codebase",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 63,
            "enabled_by_default": False,
            "config_key": "km_codebase_adapter",
        },
    ),
    # --- Canvas adapters ---
    (
        ".idea_canvas_adapter",
        "IdeaCanvasAdapter",
        {
            "name": "idea_canvas",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 12,
            "enabled_by_default": False,
            "config_key": "km_idea_canvas_adapter",
        },
    ),
    (
        ".goal_canvas_adapter",
        "GoalCanvasAdapter",
        {
            "name": "goal_canvas",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 13,
            "enabled_by_default": False,
            "config_key": "km_goal_canvas_adapter",
        },
    ),
    # --- Unified memory adapters ---
    (
        ".claude_mem_adapter",
        "ClaudeMemAdapter",
        {
            "name": "claude_mem",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 14,
            "enabled_by_default": False,
            "config_key": "km_claude_mem_adapter",
        },
    ),
    (
        ".rlm_context_adapter",
        "RLMContextAdapter",
        {
            "name": "rlm_context",
            "required_deps": [],
            "forward_method": "store_codebase_summary",
            "reverse_method": "get_codebase_context",
            "priority": 55,
            "enabled_by_default": False,
            "config_key": "km_rlm_context_adapter",
        },
    ),
    # --- Genesis evolution adapters ---
    (
        ".genesis_adapter",
        "GenesisAdapter",
        {
            "name": "genesis",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": None,
            "priority": 60,
            "enabled_by_default": False,
            "config_key": "km_genesis_adapter",
        },
    ),
    # --- Pipeline adapters ---
    (
        ".pipeline_adapter",
        "PipelineAdapter",
        {
            "name": "pipeline",
            "required_deps": [],
            "forward_method": "ingest_pipeline_result",
            "reverse_method": "find_similar_pipelines",
            "priority": 20,
            "config_key": "km_pipeline_adapter",
        },
    ),
    # --- Explainability adapter ---
    (
        ".explainability_adapter",
        "ExplainabilityAdapter",
        {
            "name": "explainability",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "search_by_topic",
            "priority": 66,
            "config_key": "km_explainability_adapter",
        },
    ),
    # --- Enterprise data adapters (Tier 5) ---
    (
        ".email_adapter",
        "EmailAdapter",
        {
            "name": "email",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 18,
            "enabled_by_default": False,
            "config_key": "km_email_adapter",
        },
    ),
    (
        ".jira_adapter",
        "JiraAdapter",
        {
            "name": "jira",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 17,
            "enabled_by_default": False,
            "config_key": "km_jira_adapter",
        },
    ),
    (
        ".confluence_adapter",
        "ConfluenceAdapter",
        {
            "name": "confluence",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 16,
            "enabled_by_default": False,
            "config_key": "km_confluence_adapter",
        },
    ),
    # Idea Cloud - personal knowledge graph for debate pipeline input
    (
        "aragora.ideacloud.adapters.km_adapter",
        "IdeaCloudAdapter",
        {
            "name": "ideacloud",
            "required_deps": [],
            "forward_method": "sync_to_km",
            "reverse_method": "sync_from_km",
            "priority": 17,
            "enabled_by_default": False,
            "config_key": "km_ideacloud_adapter",
        },
    ),
]


def _init_specs() -> None:
    """Initialize adapter specifications from the data-driven registry."""
    import importlib

    for module_path, class_name, spec_kwargs in _ADAPTER_DEFS:
        mod = importlib.import_module(module_path, package=__package__)
        adapter_class = getattr(mod, class_name)
        register_adapter_spec(AdapterSpec(adapter_class=adapter_class, **spec_kwargs))


# Initialize specs on import
_init_specs()


@dataclass
class CreatedAdapter:
    """A created adapter with metadata."""

    name: str
    adapter: Any
    spec: AdapterSpec
    deps_used: dict[str, Any] = field(default_factory=dict)


class AdapterFactory:
    """
    Factory for creating and registering KM adapters.

    This factory automatically creates adapters based on available
    subsystem dependencies and can register them with a coordinator.

    Example:
        factory = AdapterFactory()

        # Create adapters from subsystems
        adapters = factory.create_from_subsystems(
            continuum_memory=my_continuum,
            elo_system=my_elo,
        )

        # Or from ArenaConfig
        adapters = factory.create_from_arena_config(config)

        # Register with coordinator
        factory.register_with_coordinator(coordinator, adapters)
    """

    def __init__(
        self,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        """
        Initialize the factory.

        Args:
            event_callback: Optional callback for WebSocket events
        """
        self._event_callback = event_callback

    def set_event_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Set the event callback for all created adapters."""
        self._event_callback = callback

    def create_from_subsystems(
        self,
        continuum_memory: Any | None = None,
        consensus_memory: Any | None = None,
        memory: Any | None = None,  # CritiqueStore
        evidence_store: Any | None = None,
        insight_store: Any | None = None,
        elo_system: Any | None = None,
        pulse_manager: Any | None = None,
        cost_tracker: Any | None = None,
        flip_detector: Any | None = None,
        provenance_store: Any | None = None,
        obsidian_connector: Any | None = None,
        **kwargs,
    ) -> dict[str, CreatedAdapter]:
        """
        Create adapters from provided subsystems.

        Args:
            continuum_memory: ContinuumMemory instance
            consensus_memory: ConsensusMemory instance
            memory: CritiqueStore instance
            evidence_store: EvidenceStore/Collector instance
            insight_store: InsightStore instance
            elo_system: EloSystem instance
            pulse_manager: PulseManager instance
            cost_tracker: CostTracker instance
            flip_detector: FlipDetector instance (for insights)
            provenance_store: ProvenanceStore instance
            **kwargs: Additional dependencies

        Returns:
            Dict of adapter name -> CreatedAdapter
        """
        # Collect all available dependencies
        deps = {
            "continuum_memory": continuum_memory,
            "consensus_memory": consensus_memory,
            "memory": memory,
            "evidence_store": evidence_store,
            "insight_store": insight_store,
            "elo_system": elo_system,
            "pulse_manager": pulse_manager,
            "cost_tracker": cost_tracker,
            "flip_detector": flip_detector,
            "provenance_store": provenance_store,
            "obsidian_connector": obsidian_connector,
        }
        deps.update(kwargs)

        # Filter to non-None deps
        available_deps = {k: v for k, v in deps.items() if v is not None}

        return self._create_adapters(available_deps)

    def create_from_arena_config(
        self,
        config: Any,  # ArenaConfig
        subsystems: dict[str, Any] | None = None,
    ) -> dict[str, CreatedAdapter]:
        """
        Create adapters from ArenaConfig.

        Checks for explicitly configured adapters first, then
        falls back to auto-creation from subsystems.

        Args:
            config: ArenaConfig instance
            subsystems: Optional dict of subsystem instances (e.g., from Arena)

        Returns:
            Dict of adapter name -> CreatedAdapter
        """
        adapters = {}
        subsystems = subsystems or {}

        # Collect dependencies from config and subsystems
        deps = {
            "continuum_memory": getattr(config, "continuum_memory", None)
            or subsystems.get("continuum_memory"),
            "consensus_memory": getattr(config, "consensus_memory", None)
            or subsystems.get("consensus_memory"),
            "memory": getattr(config, "memory", None) or subsystems.get("memory"),
            "evidence_store": subsystems.get("evidence_store")
            or subsystems.get("evidence_collector"),
            "insight_store": getattr(config, "insight_store", None)
            or subsystems.get("insight_store"),
            "elo_system": getattr(config, "elo_system", None) or subsystems.get("elo_system"),
            "pulse_manager": getattr(config, "pulse_manager", None)
            or subsystems.get("pulse_manager"),
            "cost_tracker": getattr(config, "usage_tracker", None)
            or subsystems.get("cost_tracker"),
            "flip_detector": getattr(config, "flip_detector", None)
            or subsystems.get("flip_detector"),
            "obsidian_connector": subsystems.get("obsidian_connector"),
        }

        # Check for explicitly configured adapters
        for spec_name, spec in ADAPTER_SPECS.items():
            if spec.config_key:
                explicit_adapter = getattr(config, spec.config_key, None)
                if explicit_adapter is not None:
                    # Use the explicitly configured adapter
                    adapters[spec_name] = CreatedAdapter(
                        name=spec_name,
                        adapter=explicit_adapter,
                        spec=spec,
                        deps_used={},
                    )
                    logger.debug("Using explicit adapter: %s", spec_name)

        # Auto-create remaining adapters
        available_deps = {k: v for k, v in deps.items() if v is not None}
        auto_adapters = self._create_adapters(available_deps, exclude=set(adapters.keys()))

        adapters.update(auto_adapters)
        return adapters

    def _create_adapters(
        self,
        deps: dict[str, Any],
        exclude: set | None = None,
    ) -> dict[str, CreatedAdapter]:
        """
        Create adapters based on available dependencies.

        Args:
            deps: Available dependencies
            exclude: Adapter names to skip

        Returns:
            Dict of adapter name -> CreatedAdapter
        """
        exclude = exclude or set()
        adapters = {}

        for spec_name, spec in ADAPTER_SPECS.items():
            if spec_name in exclude:
                continue

            # Check if all required deps are available
            # (Empty required_deps means the adapter can work standalone)
            missing_deps = [d for d in spec.required_deps if d not in deps]
            if missing_deps:
                logger.debug("Skipping adapter '%s': missing deps %s", spec_name, missing_deps)
                continue

            try:
                # Create the adapter
                adapter_deps = {d: deps[d] for d in spec.required_deps if d in deps}
                adapter = self._create_single_adapter(spec, adapter_deps)

                if adapter:
                    adapters[spec_name] = CreatedAdapter(
                        name=spec_name,
                        adapter=adapter,
                        spec=spec,
                        deps_used=adapter_deps,
                    )
                    logger.info("Created adapter: %s", spec_name)

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Failed to create adapter '%s': %s", spec_name, e)

        return adapters

    def _create_single_adapter(
        self,
        spec: AdapterSpec,
        deps: dict[str, Any],
    ) -> Any | None:
        """Create a single adapter from spec."""
        adapter_class = spec.adapter_class

        try:
            # Different adapters have different constructor signatures
            # We try to be smart about what to pass

            if spec.name == "continuum":
                adapter = adapter_class(
                    continuum=deps.get("continuum_memory"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "consensus":
                adapter = adapter_class(
                    consensus=deps.get("consensus_memory"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "critique":
                adapter = adapter_class(
                    store=deps.get("memory"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "evidence":
                adapter = adapter_class(
                    store=deps.get("evidence_store"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "belief":
                adapter = adapter_class(
                    event_callback=self._event_callback,
                )
            elif spec.name == "insights":
                adapter = adapter_class(
                    insight_store=deps.get("insight_store"),
                    flip_detector=deps.get("flip_detector"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "elo":
                adapter = adapter_class(
                    elo_system=deps.get("elo_system"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "pulse":
                adapter = adapter_class(
                    manager=deps.get("pulse_manager"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "cost":
                adapter = adapter_class(
                    cost_tracker=deps.get("cost_tracker"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "obsidian":
                connector = deps.get("obsidian_connector")
                if connector is None:
                    try:
                        from aragora.connectors.knowledge.obsidian import (
                            ObsidianConfig,
                            ObsidianConnector,
                        )

                        config = ObsidianConfig.from_env()
                        if config is None:
                            return None
                        connector = ObsidianConnector(config)
                    except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
                        logger.debug("Obsidian connector init failed: %s", e)
                        return None

                adapter = adapter_class(
                    connector=connector,
                    event_callback=self._event_callback,
                )
            elif spec.name == "fabric":
                adapter = adapter_class(
                    fabric=deps.get("fabric"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "workspace":
                adapter = adapter_class(
                    workspace_manager=deps.get("workspace_manager"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "computer_use":
                adapter = adapter_class(
                    orchestrator=deps.get("computer_use_orchestrator"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "gateway":
                adapter = adapter_class(
                    gateway=deps.get("gateway"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "calibration_fusion":
                adapter = adapter_class(
                    event_callback=self._event_callback,
                )
            elif spec.name == "control_plane":
                adapter = adapter_class(
                    control_plane=deps.get("control_plane"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "culture":
                adapter = adapter_class(
                    mound=deps.get("mound"),
                )
            elif spec.name == "receipt":
                adapter = adapter_class(
                    mound=deps.get("mound"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "outcome":
                adapter = adapter_class(
                    mound=deps.get("mound"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "supermemory":
                from aragora.connectors.supermemory import SupermemoryConfig, SupermemoryClient

                supermemory_config = SupermemoryConfig.from_env()
                if supermemory_config is None:
                    return None

                client = SupermemoryClient(supermemory_config)
                adapter = adapter_class(
                    client=client,
                    config=supermemory_config,
                    min_importance_threshold=supermemory_config.sync_threshold,
                    enable_privacy_filter=supermemory_config.privacy_filter_enabled,
                    event_callback=self._event_callback,
                )
            elif spec.name == "rlm":
                adapter = adapter_class(
                    compressor=deps.get("compressor"),
                )
            elif spec.name == "trickster":
                adapter = adapter_class(
                    trickster=deps.get("trickster"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "erc8004":
                adapter = adapter_class(
                    event_callback=self._event_callback,
                )
            elif spec.name == "codebase":
                adapter = adapter_class(
                    mound=deps.get("mound"),
                    event_callback=self._event_callback,
                )
            elif spec.name == "claude_mem":
                try:
                    from aragora.connectors.memory.claude_mem import (
                        ClaudeMemConnector,
                        ClaudeMemConfig,
                    )

                    cm_config = ClaudeMemConfig.from_env()
                    connector = ClaudeMemConnector(cm_config)
                    adapter = adapter_class(
                        connector=connector,
                        project=cm_config.project,
                        event_callback=self._event_callback,
                    )
                except (ImportError, OSError, ValueError) as e:
                    logger.debug("claude-mem connector init failed: %s", e)
                    return None
            elif spec.name == "rlm_context":
                adapter = adapter_class(
                    store_fn=deps.get("rlm_context_store_fn"),
                    search_fn=deps.get("rlm_context_search_fn"),
                    event_callback=self._event_callback,
                )
            elif spec.name in ("idea_canvas", "goal_canvas", "genesis"):
                adapter = adapter_class(
                    event_callback=self._event_callback,
                )
            elif spec.name in ("email", "jira", "confluence"):
                adapter = adapter_class(
                    event_callback=self._event_callback,
                )
            elif spec.name == "pipeline":
                adapter = adapter_class(
                    mound=deps.get("mound"),
                    on_event=self._event_callback,
                )
            elif spec.name == "explainability":
                adapter = adapter_class(
                    event_callback=self._event_callback,
                )
            else:
                # Generic construction attempt
                adapter = adapter_class(
                    event_callback=self._event_callback,
                    **deps,
                )

            return adapter

        except TypeError as e:
            logger.warning("Constructor mismatch for %s: %s", spec.name, e)
            # Try without event_callback
            try:
                if spec.name == "continuum":
                    return adapter_class(continuum=deps.get("continuum_memory"))
                elif spec.name == "consensus":
                    return adapter_class(consensus=deps.get("consensus_memory"))
                elif spec.name == "critique":
                    return adapter_class(store=deps.get("memory"))
                elif spec.name == "evidence":
                    return adapter_class(store=deps.get("evidence_store"))
                elif spec.name == "belief":
                    return adapter_class()
                elif spec.name == "insights":
                    return adapter_class(
                        insight_store=deps.get("insight_store"),
                        flip_detector=deps.get("flip_detector"),
                    )
                elif spec.name == "elo":
                    return adapter_class(elo_system=deps.get("elo_system"))
                elif spec.name == "pulse":
                    return adapter_class(manager=deps.get("pulse_manager"))
                elif spec.name == "cost":
                    return adapter_class(cost_tracker=deps.get("cost_tracker"))
                elif spec.name == "fabric":
                    return adapter_class(fabric=deps.get("fabric"))
                elif spec.name == "workspace":
                    return adapter_class(workspace_manager=deps.get("workspace_manager"))
                elif spec.name == "computer_use":
                    return adapter_class(orchestrator=deps.get("computer_use_orchestrator"))
                elif spec.name == "gateway":
                    return adapter_class(gateway=deps.get("gateway"))
                elif spec.name == "calibration_fusion":
                    return adapter_class()
                elif spec.name == "control_plane":
                    return adapter_class(control_plane=deps.get("control_plane"))
                elif spec.name == "culture":
                    return adapter_class(mound=deps.get("mound"))
                elif spec.name == "receipt":
                    return adapter_class(mound=deps.get("mound"))
                elif spec.name == "outcome":
                    return adapter_class(mound=deps.get("mound"))
                elif spec.name == "supermemory":
                    from aragora.connectors.supermemory import SupermemoryConfig, SupermemoryClient

                    supermemory_config = SupermemoryConfig.from_env()
                    if supermemory_config is None:
                        return None

                    client = SupermemoryClient(supermemory_config)
                    return adapter_class(
                        client=client,
                        config=supermemory_config,
                        min_importance_threshold=supermemory_config.sync_threshold,
                        enable_privacy_filter=supermemory_config.privacy_filter_enabled,
                    )
                elif spec.name == "rlm":
                    return adapter_class(compressor=deps.get("compressor"))
                elif spec.name == "trickster":
                    return adapter_class(trickster=deps.get("trickster"))
                elif spec.name == "erc8004":
                    return adapter_class()
                elif spec.name == "codebase":
                    return adapter_class(mound=deps.get("mound"))
                elif spec.name == "claude_mem":
                    try:
                        from aragora.connectors.memory.claude_mem import (
                            ClaudeMemConnector,
                            ClaudeMemConfig,
                        )

                        cm_config = ClaudeMemConfig.from_env()
                        connector = ClaudeMemConnector(cm_config)
                        return adapter_class(
                            connector=connector,
                            project=cm_config.project,
                        )
                    except (ImportError, OSError, ValueError) as e:
                        logger.debug("claude-mem connector init failed: %s", e)
                        return None
                elif spec.name == "rlm_context":
                    return adapter_class(
                        store_fn=deps.get("rlm_context_store_fn"),
                        search_fn=deps.get("rlm_context_search_fn"),
                    )
                elif spec.name in ("idea_canvas", "goal_canvas", "genesis"):
                    return adapter_class()
                elif spec.name in ("email", "jira", "confluence"):
                    return adapter_class()
                elif spec.name == "pipeline":
                    return adapter_class(mound=deps.get("mound"))
                elif spec.name == "explainability":
                    return adapter_class()
                else:
                    return adapter_class(**deps)
            except (RuntimeError, ValueError, OSError, AttributeError) as e2:
                logger.error("Failed to create %s adapter: %s", spec.name, e2)
                return None

    def register_with_coordinator(
        self,
        coordinator: BidirectionalCoordinator,
        adapters: dict[str, CreatedAdapter],
        enable_overrides: set[str] | None = None,
    ) -> int:
        """
        Register created adapters with a BidirectionalCoordinator.

        Args:
            coordinator: The coordinator to register with
            adapters: Dict of adapters from create_from_* methods
            enable_overrides: Optional set of adapter names to force-enable

        Returns:
            Number of successfully registered adapters
        """
        registered = 0
        enable_overrides = enable_overrides or set()

        for name, created in adapters.items():
            spec = created.spec

            success = coordinator.register_adapter(
                name=name,
                adapter=created.adapter,
                forward_method=spec.forward_method,
                reverse_method=spec.reverse_method,
                priority=spec.priority,
                metadata={"deps": list(created.deps_used.keys())},
            )

            if success:
                # Enable/disable based on spec
                if name in enable_overrides:
                    coordinator.enable_adapter(name)
                elif not spec.enabled_by_default:
                    coordinator.disable_adapter(name)
                registered += 1

        logger.info("Registered %s/%s adapters with coordinator", registered, len(adapters))
        return registered

    def get_available_adapter_specs(self) -> dict[str, AdapterSpec]:
        """Get all available adapter specifications."""
        return ADAPTER_SPECS.copy()


_ADAPTER_NAME_ALIASES: dict[str, str] = {
    "insight": "insights",
}

_MOUND_AWARE_ADAPTERS = frozenset({"culture", "receipt", "outcome", "pipeline", "codebase"})


def _extract_mound_dependencies(mound: Any) -> dict[str, Any]:
    """Extract known adapter dependencies from a KnowledgeMound-like object."""
    if mound is None:
        return {}

    deps: dict[str, Any] = {
        "mound": mound,
        "continuum_memory": getattr(mound, "_continuum", None),
        "consensus_memory": getattr(mound, "_consensus", None),
        "memory": getattr(mound, "_critique", None),
        "evidence_store": getattr(mound, "_evidence", None),
        "insight_store": getattr(mound, "_insight_store", None),
        "flip_detector": getattr(mound, "_flip_detector", None),
        "elo_system": getattr(mound, "_elo_system", None),
        "pulse_manager": getattr(mound, "_pulse_manager", None),
        "cost_tracker": getattr(mound, "_cost_tracker", None),
        "provenance_store": getattr(mound, "_provenance_store", None),
    }

    # Backward-compatible attribute fallbacks for alternate mound implementations.
    if deps["evidence_store"] is None:
        deps["evidence_store"] = getattr(mound, "evidence_store", None)
    if deps["insight_store"] is None:
        deps["insight_store"] = getattr(mound, "insight_store", None)
    if deps["memory"] is None:
        deps["memory"] = getattr(mound, "critique_store", None)

    return {key: value for key, value in deps.items() if value is not None}


def get_adapter(name: str, mound: Any = None) -> Any | None:
    """Look up an adapter by name and return an instance.

    Args:
        name: Adapter name registered in ADAPTER_SPECS (e.g. "nomic_cycle", "insight").
        mound: Optional KnowledgeMound instance to pass to the adapter constructor.

    Returns:
        An adapter instance, or ``None`` if the name is not registered.
    """
    canonical_name = _ADAPTER_NAME_ALIASES.get(name, name)
    spec = ADAPTER_SPECS.get(canonical_name)
    if spec is None:
        return None

    deps = _extract_mound_dependencies(mound)

    # If required dependencies are absent, skip creation instead of constructing
    # a broken adapter (for example EvidenceAdapter(store=<KnowledgeMound>)).
    missing_required = [dep for dep in spec.required_deps if dep not in deps]
    if missing_required:
        return None

    adapter_deps = {dep: deps[dep] for dep in spec.required_deps if dep in deps}
    if canonical_name in _MOUND_AWARE_ADAPTERS and mound is not None:
        adapter_deps["mound"] = mound
    # Optional dependency for InsightsAdapter.
    if canonical_name == "insights" and "flip_detector" in deps:
        adapter_deps["flip_detector"] = deps["flip_detector"]

    try:
        factory = AdapterFactory()
        return factory._create_single_adapter(spec, adapter_deps)
    except (RuntimeError, ValueError, OSError, AttributeError):
        return None


__all__ = [
    "AdapterFactory",
    "AdapterSpec",
    "CreatedAdapter",
    "ADAPTER_SPECS",
    "get_adapter",
    "register_adapter_spec",
]
