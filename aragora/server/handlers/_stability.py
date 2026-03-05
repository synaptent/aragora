"""
Handler stability classifications.

Maps handler class names to their Stability level:
- STABLE: Production-ready, extensively tested, API stable
- EXPERIMENTAL: Works but may change, use with awareness
- PREVIEW: Early access, expect changes and potential issues
- DEPRECATED: Being phased out, use alternative

Extracted from __init__.py to reduce file complexity.
"""

from __future__ import annotations

from aragora.config.stability import Stability

HANDLER_STABILITY: dict[str, Stability] = {
    # Core - Stable
    "DebatesHandler": Stability.STABLE,
    "AgentConfigHandler": Stability.STABLE,
    "AgentsHandler": Stability.STABLE,
    "SystemHandler": Stability.STABLE,
    "HealthHandler": Stability.STABLE,
    "StatusPageHandler": Stability.STABLE,
    "NomicHandler": Stability.STABLE,
    "DocsHandler": Stability.STABLE,
    "AnalyticsHandler": Stability.STABLE,
    "AnalyticsDashboardHandler": Stability.STABLE,
    "AnalyticsMetricsHandler": Stability.STABLE,
    "EndpointAnalyticsHandler": Stability.STABLE,
    "CrossPlatformAnalyticsHandler": Stability.STABLE,
    "ConsensusHandler": Stability.STABLE,
    "MetricsHandler": Stability.STABLE,
    "SLOHandler": Stability.STABLE,
    "MemoryHandler": Stability.STABLE,
    "CoordinatorHandler": Stability.STABLE,
    "LeaderboardViewHandler": Stability.STABLE,
    "ReplaysHandler": Stability.STABLE,
    "FeaturesHandler": Stability.STABLE,
    "ConnectorsHandler": Stability.STABLE,
    "IntegrationsHandler": Stability.STABLE,
    "ExternalIntegrationsHandler": Stability.STABLE,
    "IntegrationManagementHandler": Stability.STABLE,
    "OAuthWizardHandler": Stability.STABLE,
    "TeamsIntegrationHandler": Stability.STABLE,
    "AuthHandler": Stability.STABLE,
    "TournamentHandler": Stability.STABLE,
    "DecisionHandler": Stability.STABLE,
    "ControlPlaneHandler": Stability.STABLE,
    "CostDashboardHandler": Stability.STABLE,
    "CostHandler": Stability.STABLE,
    "CritiqueHandler": Stability.STABLE,
    "RelationshipHandler": Stability.STABLE,
    "DashboardHandler": Stability.STABLE,
    "RoutingHandler": Stability.STABLE,
    "RoutingRulesHandler": Stability.STABLE,
    "CompositeHandler": Stability.STABLE,
    "MLHandler": Stability.STABLE,
    "RLMContextHandler": Stability.STABLE,
    "RLMHandler": Stability.STABLE,
    "SelectionHandler": Stability.STABLE,
    "BillingHandler": Stability.STABLE,
    "BudgetHandler": Stability.STABLE,
    "OAuthHandler": Stability.STABLE,
    "AudioHandler": Stability.STABLE,
    "DeviceHandler": Stability.STABLE,
    "TranscriptionHandler": Stability.STABLE,
    "TrainingHandler": Stability.STABLE,
    "VerificationHandler": Stability.STABLE,
    "PulseHandler": Stability.STABLE,
    "GalleryHandler": Stability.STABLE,
    "GauntletHandler": Stability.STABLE,
    "GauntletSchemaHandler": Stability.STABLE,
    "GauntletAllSchemasHandler": Stability.STABLE,
    "GauntletTemplatesListHandler": Stability.STABLE,
    "GauntletTemplateHandler": Stability.STABLE,
    "GauntletReceiptExportHandler": Stability.STABLE,
    "GauntletHeatmapExportHandler": Stability.STABLE,
    "GauntletValidateReceiptHandler": Stability.STABLE,
    "BeliefHandler": Stability.STABLE,
    "SkillsHandler": Stability.STABLE,
    "BindingsHandler": Stability.STABLE,
    "CalibrationHandler": Stability.STABLE,
    "PersonaHandler": Stability.STABLE,
    "GraphDebatesHandler": Stability.STABLE,
    "MatrixDebatesHandler": Stability.STABLE,
    "EvaluationHandler": Stability.STABLE,
    "EvolutionHandler": Stability.STABLE,
    "EvolutionABTestingHandler": Stability.STABLE,
    "LaboratoryHandler": Stability.STABLE,
    "IntrospectionHandler": Stability.STABLE,
    "LearningHandler": Stability.STABLE,
    "MemoryAnalyticsHandler": Stability.STABLE,
    "ProbesHandler": Stability.STABLE,
    "InsightsHandler": Stability.STABLE,
    "KnowledgeHandler": Stability.STABLE,
    "KnowledgeMoundHandler": Stability.STABLE,
    "KnowledgeChatHandler": Stability.STABLE,
    "ReviewsHandler": Stability.STABLE,
    "FormalVerificationHandler": Stability.STABLE,
    "OrganizationsHandler": Stability.STABLE,
    "SocialMediaHandler": Stability.STABLE,
    "MomentsHandler": Stability.STABLE,
    "AuditingHandler": Stability.STABLE,
    "SecurityDebateHandler": Stability.STABLE,
    "PluginsHandler": Stability.STABLE,
    "BroadcastHandler": Stability.STABLE,
    "GenesisHandler": Stability.STABLE,
    "DocumentHandler": Stability.STABLE,
    "DocumentBatchHandler": Stability.STABLE,
    "DocumentQueryHandler": Stability.STABLE,
    "FolderUploadHandler": Stability.STABLE,
    "SmartUploadHandler": Stability.STABLE,
    "CloudStorageHandler": Stability.EXPERIMENTAL,
    "FindingWorkflowHandler": Stability.EXPERIMENTAL,
    "EvidenceEnrichmentHandler": Stability.EXPERIMENTAL,
    "SchedulerHandler": Stability.EXPERIMENTAL,
    "AuditSessionsHandler": Stability.EXPERIMENTAL,
    "BreakpointsHandler": Stability.STABLE,
    "DebateInterventionHandler": Stability.EXPERIMENTAL,
    "SlackHandler": Stability.STABLE,
    "EvidenceHandler": Stability.STABLE,
    "WebhookHandler": Stability.STABLE,
    "AdminHandler": Stability.STABLE,
    "SecurityHandler": Stability.STABLE,
    "PolicyHandler": Stability.STABLE,
    "PrivacyHandler": Stability.STABLE,
    "WorkspaceHandler": Stability.STABLE,
    "WorkflowHandler": Stability.STABLE,
    "WorkflowTemplatesHandler": Stability.STABLE,
    "WorkflowCategoriesHandler": Stability.STABLE,
    "WorkflowPatternsHandler": Stability.STABLE,
    "WorkflowPatternTemplatesHandler": Stability.STABLE,
    "TemplateRecommendationsHandler": Stability.STABLE,
    "TemplateMarketplaceHandler": Stability.STABLE,
    "MarketplaceHandler": Stability.STABLE,
    "QueueHandler": Stability.STABLE,
    "RepositoryHandler": Stability.STABLE,
    "UncertaintyHandler": Stability.STABLE,
    "VerticalsHandler": Stability.STABLE,
    "DiscordHandler": Stability.STABLE,
    "GoogleChatHandler": Stability.STABLE,
    "TeamsHandler": Stability.STABLE,
    "TelegramHandler": Stability.STABLE,
    "WhatsAppHandler": Stability.STABLE,
    "ZoomHandler": Stability.STABLE,
    "ExplainabilityHandler": Stability.STABLE,
    "SCIMHandler": Stability.STABLE,
    "A2AHandler": Stability.EXPERIMENTAL,
    "ApprovalHandler": Stability.STABLE,
    "AlertHandler": Stability.EXPERIMENTAL,
    "TriggerHandler": Stability.STABLE,
    "MonitoringHandler": Stability.STABLE,
    "AutonomousLearningHandler": Stability.EXPERIMENTAL,
    "EmailHandler": Stability.STABLE,
    "EmailServicesHandler": Stability.STABLE,
    "GmailIngestHandler": Stability.STABLE,
    "GmailQueryHandler": Stability.STABLE,
    "UnifiedInboxHandler": Stability.STABLE,
    "EmailWebhooksHandler": Stability.STABLE,
    "DependencyAnalysisHandler": Stability.EXPERIMENTAL,
    "CodebaseAuditHandler": Stability.EXPERIMENTAL,
    "ExpenseHandler": Stability.STABLE,
    "InvoiceHandler": Stability.STABLE,
    "ARAutomationHandler": Stability.EXPERIMENTAL,
    "APAutomationHandler": Stability.EXPERIMENTAL,
    "ReconciliationHandler": Stability.EXPERIMENTAL,
    "CodeReviewHandler": Stability.STABLE,
    "LegalHandler": Stability.STABLE,
    "DevOpsHandler": Stability.STABLE,
    "AdvertisingHandler": Stability.EXPERIMENTAL,
    "AnalyticsPlatformsHandler": Stability.EXPERIMENTAL,
    "CRMHandler": Stability.STABLE,
    "SupportHandler": Stability.STABLE,
    "EcommerceHandler": Stability.STABLE,
    "ExternalAgentsHandler": Stability.STABLE,
    "OpenClawGatewayHandler": Stability.STABLE,
    "GatewayHealthHandler": Stability.STABLE,
    "GatewayAgentsHandler": Stability.STABLE,
    "GatewayCredentialsHandler": Stability.STABLE,
    "HybridDebateHandler": Stability.STABLE,
    "ERC8004Handler": Stability.STABLE,
    "AudienceSuggestionsHandler": Stability.EXPERIMENTAL,
    # Governance
    "OutcomeHandler": Stability.STABLE,
    # --- Newly registered handlers ---
    # admin/ sub-handlers
    "CreditsAdminHandler": Stability.EXPERIMENTAL,
    "EmergencyAccessHandler": Stability.EXPERIMENTAL,
    "FeatureFlagAdminHandler": Stability.EXPERIMENTAL,
    "LivenessHandler": Stability.STABLE,
    "ReadinessHandler": Stability.STABLE,
    "StorageHealthHandler": Stability.EXPERIMENTAL,
    # agents/ sub-handlers
    "AgentRecommendationHandler": Stability.EXPERIMENTAL,
    "FeedbackHandler": Stability.EXPERIMENTAL,
    # canvas pipeline stages
    "ActionCanvasHandler": Stability.EXPERIMENTAL,
    "GoalCanvasHandler": Stability.EXPERIMENTAL,
    "IdeaCanvasHandler": Stability.EXPERIMENTAL,
    "OrchestrationCanvasHandler": Stability.EXPERIMENTAL,
    # connectors
    "ConnectorManagementHandler": Stability.EXPERIMENTAL,
    # debates/ sub-handlers
    "DebateShareHandler": Stability.EXPERIMENTAL,
    "PublicDebateViewerHandler": Stability.STABLE,
    "DebateStatsHandler": Stability.STABLE,
    "DecisionPackageHandler": Stability.EXPERIMENTAL,
    # email-related
    "EmailDebateHandler": Stability.EXPERIMENTAL,
    "EmailTriageHandler": Stability.EXPERIMENTAL,
    # features/ sub-handlers
    "AgentDashboardHandler": Stability.EXPERIMENTAL,
    "OutlookHandler": Stability.EXPERIMENTAL,
    # gateway
    "GatewayConfigHandler": Stability.EXPERIMENTAL,
    # github
    "AuditGitHubBridgeHandler": Stability.EXPERIMENTAL,
    "PRReviewHandler": Stability.EXPERIMENTAL,
    # integrations
    "AutomationHandler": Stability.EXPERIMENTAL,
    "IntegrationHealthHandler": Stability.EXPERIMENTAL,
    # knowledge/ sub-handlers
    "KMAdapterStatusHandler": Stability.EXPERIMENTAL,
    "SharingNotificationsHandler": Stability.EXPERIMENTAL,
    # memory/ sub-handlers
    "UnifiedMemoryHandler": Stability.EXPERIMENTAL,
    # notifications
    "NotificationHistoryHandler": Stability.EXPERIMENTAL,
    "NotificationPreferencesHandler": Stability.EXPERIMENTAL,
    # payments
    "PaymentRoutesHandler": Stability.EXPERIMENTAL,
    # pipeline
    "PipelineGraphHandler": Stability.EXPERIMENTAL,
    "PipelineTransitionsHandler": Stability.EXPERIMENTAL,
    "PlanManagementHandler": Stability.EXPERIMENTAL,
    "ProvenanceExplorerHandler": Stability.EXPERIMENTAL,
    "UniversalGraphHandler": Stability.EXPERIMENTAL,
    # sme/ sub-handlers
    "BudgetControlsHandler": Stability.EXPERIMENTAL,
    "ReceiptDeliveryHandler": Stability.EXPERIMENTAL,
    "SlackWorkspaceHandler": Stability.EXPERIMENTAL,
    "TeamsWorkspaceHandler": Stability.EXPERIMENTAL,
    # social/ sub-handlers
    "ChannelHealthHandler": Stability.EXPERIMENTAL,
    "DiscordOAuthHandler": Stability.EXPERIMENTAL,
    "NotificationsHandler": Stability.EXPERIMENTAL,
    "SharingHandler": Stability.EXPERIMENTAL,
    "SlackOAuthHandler": Stability.EXPERIMENTAL,
    "TeamsOAuthHandler": Stability.EXPERIMENTAL,
    # streaming
    "StreamingConnectorHandler": Stability.EXPERIMENTAL,
    # tasks
    "TaskExecutionHandler": Stability.EXPERIMENTAL,
    # top-level handlers
    "AuditTrailHandler": Stability.STABLE,
    "BenchmarkingHandler": Stability.EXPERIMENTAL,
    "ComplianceReportHandler": Stability.EXPERIMENTAL,
    "ContextBudgetHandler": Stability.EXPERIMENTAL,
    "DRHandler": Stability.EXPERIMENTAL,
    "FeatureFlagsHandler": Stability.EXPERIMENTAL,
    "FeedbackRoutesHandler": Stability.EXPERIMENTAL,
    "GasTownDashboardHandler": Stability.EXPERIMENTAL,
    "GDPRDeletionHandler": Stability.STABLE,
    "MarketplaceBrowseHandler": Stability.EXPERIMENTAL,
    "ModerationHandler": Stability.EXPERIMENTAL,
    "ModerationAnalyticsHandler": Stability.EXPERIMENTAL,
    "PartnerHandler": Stability.EXPERIMENTAL,
    "PlansHandler": Stability.EXPERIMENTAL,
    "PlaybookHandler": Stability.EXPERIMENTAL,
    "PlaygroundHandler": Stability.EXPERIMENTAL,
    "ReceiptExportHandler": Stability.STABLE,
    "ReceiptsHandler": Stability.STABLE,
    "SkillMarketplaceHandler": Stability.EXPERIMENTAL,
    "SMESuccessDashboardHandler": Stability.EXPERIMENTAL,
    "SMEWorkflowsHandler": Stability.EXPERIMENTAL,
    "SSOHandler": Stability.STABLE,
    "TemplateDiscoveryHandler": Stability.EXPERIMENTAL,
    "TemplateRegistryHandler": Stability.EXPERIMENTAL,
    "ThreatIntelHandler": Stability.EXPERIMENTAL,
    "UnifiedMetricsHandler": Stability.EXPERIMENTAL,
    # workflows/ sub-handlers
    "WorkflowBuilderHandler": Stability.EXPERIMENTAL,
    # Readiness check (SME onboarding)
    "ReadinessCheckHandler": Stability.STABLE,
}


def get_handler_stability(handler_name: str) -> Stability:
    """Get the stability level for a handler.

    Args:
        handler_name: Handler class name (e.g., 'DebatesHandler')

    Returns:
        Stability level, defaults to EXPERIMENTAL if not classified
    """
    return HANDLER_STABILITY.get(handler_name, Stability.EXPERIMENTAL)


def get_all_handler_stability() -> dict[str, str]:
    """Get all handler stability levels as strings for API response."""
    return {name: stability.value for name, stability in HANDLER_STABILITY.items()}


__all__ = [
    "HANDLER_STABILITY",
    "get_all_handler_stability",
    "get_handler_stability",
]
