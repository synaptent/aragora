"""
Modular HTTP request handlers for the unified server.

Each module handles a specific domain of endpoints:
- debates: Debate history and management
- agents: Agent profiles, rankings, and metrics
- system: Health checks, nomic state, modes
- pulse: Trending topics from multiple sources
- analytics: Aggregated metrics and statistics
- consensus: Consensus memory and dissent tracking

Usage:
    from aragora.server.handlers import DebatesHandler, AgentsHandler, SystemHandler

    # Create handlers with server context
    ctx = {"storage": storage, "elo_system": elo, "nomic_dir": nomic_dir}
    debates = DebatesHandler(ctx)
    agents = AgentsHandler(ctx)
    system = SystemHandler(ctx)

    # Handle requests
    if debates.can_handle(path):
        result = debates.handle(path, query_params, handler)
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Handler stability classifications (extracted to reduce file complexity)
from ._stability import (
    HANDLER_STABILITY,
    get_all_handler_stability,
    get_handler_stability,
)

# Lazy loading infrastructure - load early, contains only string mappings
from ._lazy_imports import ALL_HANDLER_NAMES, HANDLER_MODULES

# IMPORTANT: Import order matters to avoid circular imports.
# The admin.cache module must be loaded before base.py because:
# 1. base.py imports from admin.cache
# 2. admin/__init__.py imports from handler.py, which imports from base.py
# By pre-loading admin.cache, we break the circular dependency.
from .admin import cache as cache  # noqa: F401, PLC0414  -- public for patch paths

# Expose utils submodule for tests
from . import utils as utils  # noqa: PLC0414

# Base utilities - always loaded (small and frequently needed)
from .base import BaseHandler, HandlerResult, error_response, json_response

# Handler mixins (extracted to separate module)
from .mixins import (
    AuthenticatedHandlerMixin,
    CachedHandlerMixin,
    PaginatedHandlerMixin,
)

# API decorators (extracted to separate module)
from .api_decorators import (
    api_endpoint,
    rate_limit,
    require_quota,
    validate_body,
)

# Typed handler base classes (extracted to separate module)
from .typed_handlers import (
    AdminHandler as TypedAdminHandler,
    AsyncTypedHandler,
    AuthenticatedHandler as TypedAuthenticatedHandler,
    MaybeAsyncHandlerResult,
    PermissionHandler,
    ResourceHandler,
    TypedHandler,
)

# Handler interfaces for type checking and contract definition
from .interface import (
    AuthenticatedHandlerInterface,
    CachedHandlerInterface,
    HandlerInterface,
    HandlerRegistration,
    MinimalServerContext,
    PaginatedHandlerInterface,
    RouteConfig,
    StorageAccessInterface,
    is_authenticated_handler,
    is_handler,
)

# Shared types for handlers (protocols, type aliases, common parameters)
from .types import (
    AsyncHandlerFunction,
    AsyncMiddlewareFunction,
    FilterParams,
    HandlerFunction,
    HandlerProtocol,
    MaybeAsyncHandlerFunction,
    MaybeAsyncMiddlewareFunction,
    MiddlewareFactory,
    MiddlewareFunction,
    PaginationParams,
    QueryParams,
    RequestContext,
    ResponseType,
    SortParams,
)

# Standalone utilities that don't require full server infrastructure
from .utilities import (
    agent_to_dict,
    build_api_url,
    extract_path_segment,
    get_agent_name,
    get_content_length,
    get_host_header,
    get_media_type,
    get_request_id,
    is_json_content_type,
    normalize_agent_names,
)

# Type checking imports - these are not executed at runtime
if TYPE_CHECKING:
    from .a2a import A2AHandler
    from .action_canvas import ActionCanvasHandler
    from .admin import (
        AdminHandler,
        BillingHandler,
        DashboardHandler,
        HealthHandler,
        SecurityHandler,
        SystemHandler,
    )
    from .admin.credits import CreditsAdminHandler
    from .admin.emergency_access import EmergencyAccessHandler
    from .admin.feature_flags import FeatureFlagAdminHandler
    from .admin.health.liveness import LivenessHandler
    from .admin.health.readiness import ReadinessHandler
    from .admin.health.storage_health import StorageHealthHandler
    from .agents import (
        AgentConfigHandler,
        AgentsHandler,
        CalibrationHandler,
        LeaderboardViewHandler,
        ProbesHandler,
    )
    from .agents.feedback import FeedbackHandler
    from .agents.recommendations import AgentRecommendationHandler
    from ._analytics_impl import AnalyticsHandler
    from .analytics_dashboard import AnalyticsDashboardHandler
    from ._analytics_metrics_impl import AnalyticsMetricsHandler
    from .outcome_analytics import OutcomeAnalyticsHandler
    from .ap_automation import APAutomationHandler
    from .ar_automation import ARAutomationHandler
    from .audit_trail import AuditTrailHandler
    from .audience_suggestions import AudienceSuggestionsHandler
    from .auditing import AuditingHandler
    from .security_debate import SecurityDebateHandler
    from .auth import AuthHandler
    from .autonomous import (
        AlertHandler,
        ApprovalHandler,
        # Unified approvals inbox
        # (separate handler module)
        LearningHandler as AutonomousLearningHandler,
        MonitoringHandler,
        TriggerHandler,
    )
    from .approvals_inbox import UnifiedApprovalsHandler
    from .backup_handler import BackupHandler
    from .belief import BeliefHandler
    from .benchmarking import BenchmarkingHandler
    from .bindings import BindingsHandler
    from .differentiation import DifferentiationHandler
    from .bots import (
        DiscordHandler,
        GoogleChatHandler,
        TeamsHandler,
        TelegramHandler,
        WhatsAppHandler,
        ZoomHandler,
    )
    from .breakpoints import BreakpointsHandler
    from .debate_intervention import DebateInterventionHandler
    from .budgets import BudgetHandler
    from .canvas import CanvasHandler
    from .checkpoints import CheckpointHandler
    from .code_review import CodeReviewHandler
    from .codebase import IntelligenceHandler
    from .compliance_reports import ComplianceReportHandler
    from .composite import CompositeHandler
    from .connectors.management import ConnectorManagementHandler
    from .context_budget import ContextBudgetHandler
    from .computer_use_handler import ComputerUseHandler
    from .consensus import ConsensusHandler
    from .control_plane import ControlPlaneHandler
    from .billing.cost_dashboard import CostDashboardHandler
    from .costs import CostHandler
    from .critique import CritiqueHandler
    from .debate_stats import DebateStatsHandler
    from .cross_pollination import (
        CrossPollinationBridgeHandler,
        CrossPollinationKMCultureHandler,
        CrossPollinationKMHandler,
        CrossPollinationKMStalenessHandler,
        CrossPollinationKMSyncHandler,
        CrossPollinationMetricsHandler,
        CrossPollinationResetHandler,
        CrossPollinationStatsHandler,
        CrossPollinationSubscribersHandler,
    )
    from .debates import DebatesHandler, GraphDebatesHandler, MatrixDebatesHandler
    from .debates.decision_package import DecisionPackageHandler
    from .debates.public_viewer import PublicDebateViewerHandler
    from .debates.share import DebateShareHandler
    from .decision import DecisionHandler
    from .decisions import DecisionExplainHandler
    from .deliberations import DeliberationsHandler
    from .dependency_analysis import DependencyAnalysisHandler
    from .devices import DeviceHandler
    from .docs import DocsHandler
    from .dr_handler import DRHandler
    from .email import EmailHandler
    from .email_debate import EmailDebateHandler
    from .email_services import EmailServicesHandler
    from .email_triage import EmailTriageHandler
    from .endpoint_analytics import EndpointAnalyticsHandler
    from .erc8004 import ERC8004Handler
    from .evaluation import EvaluationHandler
    from .evolution import EvolutionABTestingHandler, EvolutionHandler
    from .expenses import ExpenseHandler
    from .explainability import ExplainabilityHandler
    from .external_agents import ExternalAgentsHandler
    from .external_integrations import ExternalIntegrationsHandler
    from .feature_flags import FeatureFlagsHandler
    from .features import (
        AdvertisingHandler,
        AnalyticsPlatformsHandler,
        AuditSessionsHandler,
        AudioHandler,
        BroadcastHandler,
        CloudStorageHandler,
        CodebaseAuditHandler,
        ConnectorsHandler,
        CRMHandler,
        CrossPlatformAnalyticsHandler,
        DevOpsHandler,
        DocumentBatchHandler,
        DocumentHandler,
        DocumentQueryHandler,
        EcommerceHandler,
        EmailWebhooksHandler,
        EvidenceEnrichmentHandler,
        EvidenceHandler,
        FeaturesHandler,
        FindingWorkflowHandler,
        FolderUploadHandler,
        GmailIngestHandler,
        GmailQueryHandler,
        IntegrationsHandler,
        LegalHandler,
        MarketplaceHandler,
        PluginsHandler,
        PulseHandler,
        ReconciliationHandler,
        RLMHandler,
        RoutingRulesHandler,
        SchedulerHandler,
        SmartUploadHandler,
        SupportHandler,
        UnifiedInboxHandler,
    )
    from .features.control_plane import AgentDashboardHandler
    from .features.gmail_labels import GmailLabelsHandler
    from .features.gmail_threads import GmailThreadsHandler
    from .features.outlook import OutlookHandler
    from .feedback import FeedbackRoutesHandler
    from .gallery import GalleryHandler
    from .gastown_dashboard import GasTownDashboardHandler
    from .gateway_agents_handler import GatewayAgentsHandler
    from .gateway_config_handler import GatewayConfigHandler
    from .gateway_credentials_handler import GatewayCredentialsHandler
    from .gateway_handler import GatewayHandler
    from .gateway_health_handler import GatewayHealthHandler
    from .gauntlet import GauntletHandler
    from .gdpr_deletion import GDPRDeletionHandler
    from .gauntlet_v1 import (
        GAUNTLET_V1_HANDLERS,
        GauntletAllSchemasHandler,
        GauntletHeatmapExportHandler,
        GauntletReceiptExportHandler,
        GauntletSchemaHandler,
        GauntletTemplateHandler,
        GauntletTemplatesListHandler,
        GauntletValidateReceiptHandler,
    )
    from .genesis import GenesisHandler
    from .harnesses import HarnessesHandler
    from .github.audit_bridge import AuditGitHubBridgeHandler
    from .github.pr_review import PRReviewHandler
    from .goal_canvas import GoalCanvasHandler
    from .hybrid_debate_handler import HybridDebateHandler
    from .idea_canvas import IdeaCanvasHandler
    from .integrations.automation import AutomationHandler
    from .integrations.health import IntegrationHealthHandler
    from .integration_management import (
        IntegrationsHandler as IntegrationManagementHandler,
    )
    from .introspection import IntrospectionHandler
    from .invoices import InvoiceHandler
    from .knowledge.adapters import KMAdapterStatusHandler
    from .knowledge.checkpoints import KMCheckpointHandler
    from .knowledge.sharing_notifications import SharingNotificationsHandler
    from .knowledge_base import KnowledgeHandler, KnowledgeMoundHandler
    from .knowledge_chat import KnowledgeChatHandler
    from .laboratory import LaboratoryHandler
    from .marketplace_browse import MarketplaceBrowseHandler
    from .memory import (
        CoordinatorHandler,
        InsightsHandler,
        LearningHandler,
        MemoryAnalyticsHandler,
        MemoryHandler,
    )
    from .memory.unified_handler import UnifiedMemoryHandler
    from .metrics import MetricsHandler
    from .metrics_endpoint import UnifiedMetricsHandler
    from .ml import MLHandler
    from .moderation import ModerationHandler
    from .moderation_analytics import ModerationAnalyticsHandler
    from .moments import MomentsHandler
    from .nomic import NomicHandler
    from .notifications.history import NotificationHistoryHandler
    from .notifications.preferences import NotificationPreferencesHandler
    from .oauth import OAuthHandler
    from .oauth_wizard import OAuthWizardHandler
    from .onboarding import (
        OnboardingHandler,
        get_onboarding_handlers,
        handle_analytics,
        handle_first_debate,
        handle_get_flow,
        handle_get_templates,
        handle_init_flow,
        handle_quick_start,
        handle_update_step,
    )
    from .openclaw_gateway import OpenClawGatewayHandler
    from .readiness_check import ReadinessCheckHandler
    from .orchestration import OrchestrationHandler
    from .orchestration_canvas import OrchestrationCanvasHandler
    from .organizations import OrganizationsHandler
    from .partner import PartnerHandler
    from .payments.handler import PaymentRoutesHandler
    from .persona import PersonaHandler
    from .pipeline_graph import PipelineGraphHandler
    from .pipeline.plans import PlanManagementHandler
    from .pipeline.provenance_explorer import ProvenanceExplorerHandler
    from .pipeline.transitions import PipelineTransitionsHandler
    from .pipeline.universal_graph import UniversalGraphHandler
    from .plans import PlansHandler
    from .playbooks import PlaybookHandler
    from .playground import PlaygroundHandler
    from .policy import PolicyHandler
    from .privacy import PrivacyHandler
    from .public import StatusPageHandler
    from .queue import QueueHandler
    from .receipt_export import ReceiptExportHandler
    from .receipts import ReceiptsHandler
    from .replays import ReplaysHandler
    from .repository import RepositoryHandler
    from .reviews import ReviewsHandler
    from .rlm import RLMContextHandler
    from .routing import RoutingHandler
    from .sandbox import SandboxHandler
    from .scim_handler import SCIMHandler
    from .selection import SelectionHandler
    from .skill_marketplace import SkillMarketplaceHandler
    from .skills import SkillsHandler
    from .slo import SLOHandler
    from .sme.budget_controls import BudgetControlsHandler
    from .sme.receipt_delivery import ReceiptDeliveryHandler
    from .sme.slack_workspace import SlackWorkspaceHandler
    from .sme.teams_workspace import TeamsWorkspaceHandler
    from .sme_success_dashboard import SMESuccessDashboardHandler
    from .sme_usage_dashboard import SMEUsageDashboardHandler
    from .social import (
        CollaborationHandlers,
        RelationshipHandler,
        SlackHandler,
        SocialMediaHandler,
        get_collaboration_handlers,
    )
    from .social.channel_health import ChannelHealthHandler
    from .social.discord_oauth import DiscordOAuthHandler
    from .social.notifications import NotificationsHandler
    from .social.sharing import SharingHandler
    from .social.slack_oauth import SlackOAuthHandler
    from .social.teams import TeamsIntegrationHandler
    from .social.teams_oauth import TeamsOAuthHandler
    from .sso import SSOHandler
    from .streaming.handler import StreamingConnectorHandler
    from .tasks.execution import TaskExecutionHandler
    from .template_discovery import TemplateDiscoveryHandler
    from .template_marketplace import TemplateMarketplaceHandler
    from .threat_intel import ThreatIntelHandler
    from .tournaments import TournamentHandler
    from .training import TrainingHandler
    from .transcription import TranscriptionHandler
    from .uncertainty import UncertaintyHandler
    from .usage_metering import UsageMeteringHandler
    from .verification import FormalVerificationHandler, VerificationHandler
    from .verticals import VerticalsHandler
    from .visualization import VisualizationHandler
    from .webhooks import WebhookHandler
    from .workflow_templates import (
        SMEWorkflowsHandler,
        TemplateRecommendationsHandler,
        WorkflowCategoriesHandler,
        WorkflowPatternTemplatesHandler,
        WorkflowPatternsHandler,
        WorkflowTemplatesHandler,
    )
    from .workflows import WorkflowHandler
    from .workflows.builder import WorkflowBuilderHandler
    from .workflows.registry import TemplateRegistryHandler
    from .workspace import WorkspaceHandler


# Cache for lazily loaded handlers
_handler_cache: dict[str, Any] = {}

# Cached ALL_HANDLERS list
_all_handlers_cache: list[type] | None = None


def _get_all_handlers() -> list[type]:
    """Lazily load and return all handler classes."""
    global _all_handlers_cache
    if _all_handlers_cache is not None:
        return _all_handlers_cache

    handlers = []
    for name in ALL_HANDLER_NAMES:
        try:
            handler = _lazy_import(name)
            if handler is not None:
                handlers.append(handler)
        except (ImportError, AttributeError):
            # Skip handlers that fail to import
            pass
    _all_handlers_cache = handlers
    return handlers


def _lazy_import(name: str) -> Any:
    """Lazily import a handler by name."""
    if name in _handler_cache:
        return _handler_cache[name]

    if name not in HANDLER_MODULES:
        return None

    module_path = HANDLER_MODULES[name]
    module = importlib.import_module(module_path)
    attr = getattr(module, name)
    _handler_cache[name] = attr
    return attr


def __getattr__(name: str) -> Any:
    """Lazy loading via module __getattr__."""
    # Handle ALL_HANDLERS specially
    if name == "ALL_HANDLERS":
        return _get_all_handlers()

    # Handle GAUNTLET_V1_HANDLERS specially
    if name == "GAUNTLET_V1_HANDLERS":
        return _lazy_import("GAUNTLET_V1_HANDLERS")

    # Check if this is a lazily-loaded handler
    if name in HANDLER_MODULES:
        return _lazy_import(name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Populate the registry for modules that need to avoid circular imports
# (e.g., features.py needs to enumerate handlers)
# This is deferred to avoid importing all handlers
def _populate_registry() -> None:
    """Populate the handler registry with lazily loaded handlers."""
    from aragora.server.handlers import _registry

    _registry.ALL_HANDLERS[:] = _get_all_handlers()
    _registry.HANDLER_STABILITY.update(HANDLER_STABILITY)


__all__ = [
    # Base utilities
    "HandlerResult",
    "BaseHandler",
    "json_response",
    "error_response",
    # Handler mixins (from mixins.py)
    "PaginatedHandlerMixin",
    "CachedHandlerMixin",
    "AuthenticatedHandlerMixin",
    # API decorators (from api_decorators.py)
    "api_endpoint",
    "rate_limit",
    "validate_body",
    "require_quota",
    # Typed handler base classes (from typed_handlers.py)
    "TypedHandler",
    "TypedAuthenticatedHandler",
    "PermissionHandler",
    "TypedAdminHandler",
    "AsyncTypedHandler",
    "ResourceHandler",
    "MaybeAsyncHandlerResult",
    # Handler interfaces (from interface.py)
    "HandlerInterface",
    "AuthenticatedHandlerInterface",
    "PaginatedHandlerInterface",
    "CachedHandlerInterface",
    "StorageAccessInterface",
    "MinimalServerContext",
    "RouteConfig",
    "HandlerRegistration",
    "is_handler",
    "is_authenticated_handler",
    # Shared types (from types.py)
    "HandlerProtocol",
    "RequestContext",
    "ResponseType",
    "HandlerFunction",
    "AsyncHandlerFunction",
    "MaybeAsyncHandlerFunction",
    "MiddlewareFunction",
    "AsyncMiddlewareFunction",
    "MaybeAsyncMiddlewareFunction",
    "MiddlewareFactory",
    "PaginationParams",
    "FilterParams",
    "SortParams",
    "QueryParams",
    # Standalone utilities (from utilities.py)
    "get_host_header",
    "get_agent_name",
    "agent_to_dict",
    "normalize_agent_names",
    "extract_path_segment",
    "build_api_url",
    "is_json_content_type",
    "get_media_type",
    "get_request_id",
    "get_content_length",
    # Handler registry
    "ALL_HANDLERS",
    # Individual handlers (lazily loaded)
    "DebatesHandler",
    "AgentConfigHandler",
    "AgentsHandler",
    "SystemHandler",
    "HealthHandler",
    "StatusPageHandler",
    "NomicHandler",
    "DocsHandler",
    "PulseHandler",
    "AnalyticsHandler",
    "AnalyticsDashboardHandler",
    "AnalyticsMetricsHandler",
    "OutcomeAnalyticsHandler",
    "EndpointAnalyticsHandler",
    "CrossPlatformAnalyticsHandler",
    "MetricsHandler",
    "SLOHandler",
    "ConsensusHandler",
    "BeliefHandler",
    "SkillsHandler",
    "BindingsHandler",
    "ControlPlaneHandler",
    "OrchestrationHandler",
    "DecisionExplainHandler",
    "DecisionPipelineHandler",
    "DecisionHandler",
    "CostDashboardHandler",
    "CostHandler",
    "CritiqueHandler",
    "GenesisHandler",
    "ReplaysHandler",
    "TournamentHandler",
    "MemoryHandler",
    "CoordinatorHandler",
    "LeaderboardViewHandler",
    "RelationshipHandler",
    "MomentsHandler",
    "DocumentHandler",
    "DocumentBatchHandler",
    "DocumentQueryHandler",
    "FolderUploadHandler",
    "SmartUploadHandler",
    "CloudStorageHandler",
    "FindingWorkflowHandler",
    "EvidenceEnrichmentHandler",
    "SchedulerHandler",
    "AuditSessionsHandler",
    "VerificationHandler",
    "AuditingHandler",
    "SecurityDebateHandler",
    "DashboardHandler",
    "PersonaHandler",
    "IntrospectionHandler",
    "CalibrationHandler",
    "CanvasHandler",
    "CompositeHandler",
    "RoutingHandler",
    "RoutingRulesHandler",
    "MLHandler",
    "RLMContextHandler",
    "RLMHandler",
    "EvolutionHandler",
    "EvolutionABTestingHandler",
    "PluginsHandler",
    "AudioHandler",
    "DeviceHandler",
    "TranscriptionHandler",
    "SocialMediaHandler",
    "BroadcastHandler",
    "LaboratoryHandler",
    "ProbesHandler",
    "InsightsHandler",
    "KnowledgeHandler",
    "KnowledgeMoundHandler",
    "KnowledgeChatHandler",
    "GalleryHandler",
    "BreakpointsHandler",
    "DebateInterventionHandler",
    "LearningHandler",
    "AuthHandler",
    "BillingHandler",
    "BudgetHandler",
    "UsageMeteringHandler",
    "SMEUsageDashboardHandler",
    "OrganizationsHandler",
    # Onboarding handlers
    "handle_get_flow",
    "handle_init_flow",
    "handle_update_step",
    "handle_get_templates",
    "handle_first_debate",
    "handle_quick_start",
    "handle_analytics",
    "get_onboarding_handlers",
    "OAuthHandler",
    "GraphDebatesHandler",
    "MatrixDebatesHandler",
    "FeaturesHandler",
    "ConnectorsHandler",
    "IntegrationsHandler",
    "ExternalIntegrationsHandler",
    "IntegrationManagementHandler",
    "OAuthWizardHandler",
    "TeamsIntegrationHandler",
    "MemoryAnalyticsHandler",
    "GauntletHandler",
    # Gauntlet v1 API
    "GauntletSchemaHandler",
    "GauntletAllSchemasHandler",
    "GauntletTemplatesListHandler",
    "GauntletTemplateHandler",
    "GauntletReceiptExportHandler",
    "GauntletHeatmapExportHandler",
    "GauntletValidateReceiptHandler",
    "GAUNTLET_V1_HANDLERS",
    "ReviewsHandler",
    "FormalVerificationHandler",
    "SlackHandler",
    "EvidenceHandler",
    "WebhookHandler",
    "AdminHandler",
    "SecurityHandler",
    "PolicyHandler",
    "PrivacyHandler",
    "QueueHandler",
    "RepositoryHandler",
    "UncertaintyHandler",
    "VerticalsHandler",
    "WorkspaceHandler",
    "WorkflowHandler",
    "WorkflowTemplatesHandler",
    "WorkflowCategoriesHandler",
    "WorkflowPatternsHandler",
    "WorkflowPatternTemplatesHandler",
    "TemplateRecommendationsHandler",
    "TemplateMarketplaceHandler",
    "MarketplaceHandler",
    "TrainingHandler",
    "EmailHandler",
    "EmailServicesHandler",
    "GmailIngestHandler",
    "GmailQueryHandler",
    "UnifiedInboxHandler",
    "EmailWebhooksHandler",
    "DependencyAnalysisHandler",
    "CodebaseAuditHandler",
    "IntelligenceHandler",
    # Collaboration handlers
    "CollaborationHandlers",
    "get_collaboration_handlers",
    # Bot platform handlers
    "DiscordHandler",
    "GoogleChatHandler",
    "TeamsHandler",
    "TelegramHandler",
    "WhatsAppHandler",
    "ZoomHandler",
    # Explainability
    "ExplainabilityHandler",
    # Enterprise provisioning
    "SCIMHandler",
    # Protocols
    "A2AHandler",
    # Autonomous operations handlers (Phase 5)
    "ApprovalHandler",
    "UnifiedApprovalsHandler",
    "AlertHandler",
    "TriggerHandler",
    "MonitoringHandler",
    "AutonomousLearningHandler",
    # Accounting handlers (Phase 4 - SME Vertical)
    "ExpenseHandler",
    "InvoiceHandler",
    "ARAutomationHandler",
    "APAutomationHandler",
    "ReconciliationHandler",
    # Code review handler (Phase 5 - SME Vertical)
    "CodeReviewHandler",
    "LegalHandler",
    "DevOpsHandler",
    # Connector platform handlers
    "AdvertisingHandler",
    "AnalyticsPlatformsHandler",
    "CRMHandler",
    "SupportHandler",
    "EcommerceHandler",
    # OpenClaw enterprise gateway
    "OpenClawGatewayHandler",
    # Secure Gateway handlers (Batch 5)
    "GatewayHealthHandler",
    "GatewayAgentsHandler",
    "GatewayCredentialsHandler",
    "HybridDebateHandler",
    # Blockchain handlers (ERC-8004)
    "ERC8004Handler",
    # Cross-pollination handlers
    "CrossPollinationStatsHandler",
    "CrossPollinationSubscribersHandler",
    "CrossPollinationBridgeHandler",
    "CrossPollinationMetricsHandler",
    "CrossPollinationResetHandler",
    "CrossPollinationKMHandler",
    "CrossPollinationKMSyncHandler",
    "CrossPollinationKMStalenessHandler",
    "CrossPollinationKMCultureHandler",
    # Onboarding
    "OnboardingHandler",
    "BackupHandler",
    "GmailLabelsHandler",
    "GmailThreadsHandler",
    # Additional handlers (TYPE_CHECKING exports)
    "CheckpointHandler",
    "ComputerUseHandler",
    "DeliberationsHandler",
    "EvaluationHandler",
    "ExternalAgentsHandler",
    "GatewayHandler",
    "KMCheckpointHandler",
    "SelectionHandler",
    # Audience suggestions
    "AudienceSuggestionsHandler",
    # Spectate (real-time debate observation bridge)
    "SpectateStreamHandler",
    # --- Newly registered handlers ---
    # admin/ sub-handlers
    "CreditsAdminHandler",
    "EmergencyAccessHandler",
    "FeatureFlagAdminHandler",
    "LivenessHandler",
    "ReadinessHandler",
    "StorageHealthHandler",
    # agents/ sub-handlers
    "AgentRecommendationHandler",
    "FeedbackHandler",
    # canvas pipeline stages
    "ActionCanvasHandler",
    "GoalCanvasHandler",
    "IdeaCanvasHandler",
    "OrchestrationCanvasHandler",
    # connectors
    "ConnectorManagementHandler",
    # debates/ sub-handlers
    "PublicDebateViewerHandler",
    "DebateShareHandler",
    "DebateStatsHandler",
    "DecisionPackageHandler",
    # email-related
    "EmailDebateHandler",
    "EmailTriageHandler",
    # features/ sub-handlers
    "AgentDashboardHandler",
    "OutlookHandler",
    # gateway
    "GatewayConfigHandler",
    # github
    "AuditGitHubBridgeHandler",
    "PRReviewHandler",
    # integrations
    "AutomationHandler",
    "IntegrationHealthHandler",
    # knowledge/ sub-handlers
    "KMAdapterStatusHandler",
    "SharingNotificationsHandler",
    # memory/ sub-handlers
    "UnifiedMemoryHandler",
    # notifications
    "NotificationHistoryHandler",
    "NotificationPreferencesHandler",
    # payments
    "PaymentRoutesHandler",
    # pipeline
    "PipelineGraphHandler",
    "PipelineTransitionsHandler",
    "PlanManagementHandler",
    "ProvenanceExplorerHandler",
    "UniversalGraphHandler",
    # sme/ sub-handlers
    "BudgetControlsHandler",
    "ReceiptDeliveryHandler",
    "SlackWorkspaceHandler",
    "TeamsWorkspaceHandler",
    # social/ sub-handlers
    "ChannelHealthHandler",
    "DiscordOAuthHandler",
    "NotificationsHandler",
    "SharingHandler",
    "SlackOAuthHandler",
    "TeamsOAuthHandler",
    # streaming
    "StreamingConnectorHandler",
    # tasks
    "TaskExecutionHandler",
    # top-level handlers
    "AuditTrailHandler",
    "BenchmarkingHandler",
    "DifferentiationHandler",
    "ComplianceReportHandler",
    "ContextBudgetHandler",
    "DRHandler",
    "FeatureFlagsHandler",
    "FeedbackRoutesHandler",
    "GasTownDashboardHandler",
    "GDPRDeletionHandler",
    "MarketplaceBrowseHandler",
    "ModerationHandler",
    "ModerationAnalyticsHandler",
    "PartnerHandler",
    "PlansHandler",
    "PlaybookHandler",
    "PlaygroundHandler",
    "ReceiptExportHandler",
    "ReceiptsHandler",
    "SkillMarketplaceHandler",
    "SMESuccessDashboardHandler",
    "SMEWorkflowsHandler",
    "SSOHandler",
    "TemplateDiscoveryHandler",
    "TemplateRegistryHandler",
    "ThreatIntelHandler",
    "UnifiedMetricsHandler",
    # workflows/ sub-handlers
    "WorkflowBuilderHandler",
    # Readiness check (SME onboarding)
    "ReadinessCheckHandler",
    # Harnesses (external tool integration)
    "HarnessesHandler",
    # Sandbox (code execution)
    "SandboxHandler",
    # Visualization (argument cartography)
    "VisualizationHandler",
    # Stability utilities
    "HANDLER_STABILITY",
    "get_handler_stability",
    "get_all_handler_stability",
]
