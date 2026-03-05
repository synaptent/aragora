"""
Admin and enterprise handler imports and registry entries.

This module contains imports and registry entries for:
- Admin handlers (AdminHandler, ControlPlaneHandler, etc.)
- Auth and security handlers
- Billing and budget handlers
- Organization and workspace handlers
- Compliance, backup, and DR handlers
- Gateway and integration handlers
- Workflow handlers
- Various feature and platform handlers
"""

from __future__ import annotations

from .core import _safe_import

# =============================================================================
# Core System Handler Imports
# =============================================================================

SystemHandler = _safe_import("aragora.server.handlers", "SystemHandler")
HealthHandler = _safe_import("aragora.server.handlers", "HealthHandler")
BuildInfoHandler = _safe_import("aragora.server.handlers.admin.health.build", "BuildInfoHandler")
DeployStatusHandler = _safe_import(
    "aragora.server.handlers.admin.health.deploy_status", "DeployStatusHandler"
)
NomicHandler = _safe_import("aragora.server.handlers", "NomicHandler")
DocsHandler = _safe_import("aragora.server.handlers", "DocsHandler")
ApiDocsHandler = _safe_import("aragora.server.handlers.api_docs", "ApiDocsHandler")
MCPToolsHandler = _safe_import("aragora.server.handlers.mcp_tools_handler", "MCPToolsHandler")

# =============================================================================
# Admin Handler Imports
# =============================================================================

AdminHandler = _safe_import("aragora.server.handlers", "AdminHandler")
ControlPlaneHandler = _safe_import("aragora.server.handlers", "ControlPlaneHandler")
PolicyHandler = _safe_import("aragora.server.handlers", "PolicyHandler")
SecurityHandler = _safe_import("aragora.server.handlers.admin", "SecurityHandler")
RotationStatusHandler = _safe_import(
    "aragora.server.handlers.admin.rotation_status", "RotationStatusHandler"
)
ModerationHandler = _safe_import("aragora.server.handlers.moderation", "ModerationHandler")
AudienceSuggestionsHandler = _safe_import(
    "aragora.server.handlers.audience_suggestions", "AudienceSuggestionsHandler"
)
CoordinationHandler = _safe_import("aragora.server.handlers.coordination", "CoordinationHandler")

# =============================================================================
# Auth Handler Imports
# =============================================================================

AuthHandler = _safe_import("aragora.server.handlers", "AuthHandler")
OAuthHandler = _safe_import("aragora.server.handlers", "OAuthHandler")
OAuthWizardHandler = _safe_import("aragora.server.handlers.oauth_wizard", "OAuthWizardHandler")
SCIMHandler = _safe_import("aragora.server.handlers.scim_handler", "SCIMHandler")
SSOHandler = _safe_import("aragora.server.handlers.sso", "SSOHandler")

# =============================================================================
# Billing and Budget Handler Imports
# =============================================================================

BillingHandler = _safe_import("aragora.server.handlers", "BillingHandler")
BudgetHandler = _safe_import("aragora.server.handlers", "BudgetHandler")
BudgetControlsHandler = _safe_import(
    "aragora.server.handlers.sme.budget_controls", "BudgetControlsHandler"
)
CreditsAdminHandler = _safe_import("aragora.server.handlers.admin.credits", "CreditsAdminHandler")
SpendAnalyticsHandler = _safe_import(
    "aragora.server.handlers.spend_analytics", "SpendAnalyticsHandler"
)

# =============================================================================
# Organization and Workspace Handler Imports
# =============================================================================

OrganizationsHandler = _safe_import("aragora.server.handlers", "OrganizationsHandler")
WorkspaceHandler = _safe_import("aragora.server.handlers", "WorkspaceHandler")

# =============================================================================
# Compliance, Backup, and DR Handler Imports
# =============================================================================

ComplianceHandler = _safe_import("aragora.server.handlers.compliance_handler", "ComplianceHandler")
BackupHandler = _safe_import("aragora.server.handlers.backup_handler", "BackupHandler")
DRHandler = _safe_import("aragora.server.handlers.dr_handler", "DRHandler")

# Privacy and audit handlers
PrivacyHandler = _safe_import("aragora.server.handlers.privacy", "PrivacyHandler")
AuditTrailHandler = _safe_import("aragora.server.handlers.audit_trail", "AuditTrailHandler")
AuditSessionsHandler = _safe_import(
    "aragora.server.handlers.features.audit_sessions", "AuditSessionsHandler"
)

# Data classification handler
DataClassificationHandler = _safe_import(
    "aragora.server.handlers.data_classification_handler", "DataClassificationHandler"
)

# CSP report handler
CSPReportHandler = _safe_import("aragora.server.handlers.security", "CSPReportHandler")

# =============================================================================
# Gateway Handler Imports
# =============================================================================

GatewayHandler = _safe_import("aragora.server.handlers.gateway_handler", "GatewayHandler")
OpenClawGatewayHandler = _safe_import(
    "aragora.server.handlers.openclaw_gateway", "OpenClawGatewayHandler"
)
GatewayCredentialsHandler = _safe_import(
    "aragora.server.handlers.gateway_credentials_handler", "GatewayCredentialsHandler"
)
GatewayHealthHandler = _safe_import(
    "aragora.server.handlers.gateway_health_handler", "GatewayHealthHandler"
)
GatewayConfigHandler = _safe_import(
    "aragora.server.handlers.gateway_config_handler", "GatewayConfigHandler"
)
ERC8004Handler = _safe_import("aragora.server.handlers.erc8004", "ERC8004Handler")

# =============================================================================
# Integration Handler Imports
# =============================================================================

ExternalIntegrationsHandler = _safe_import(
    "aragora.server.handlers.external_integrations", "ExternalIntegrationsHandler"
)
IntegrationHealthHandler = _safe_import(
    "aragora.server.handlers.integrations.health", "IntegrationHealthHandler"
)
IntegrationManagementHandler = _safe_import(
    "aragora.server.handlers.integration_management", "IntegrationsHandler"
)
FeatureIntegrationsHandler = _safe_import(
    "aragora.server.handlers.features.integrations", "IntegrationsHandler"
)
ConnectorsHandler = _safe_import("aragora.server.handlers", "ConnectorsHandler")
StreamingConnectorHandler = _safe_import(
    "aragora.server.handlers.streaming", "StreamingConnectorHandler"
)
MarketplaceHandler = _safe_import("aragora.server.handlers", "MarketplaceHandler")
MarketplaceBrowseHandler = _safe_import(
    "aragora.server.handlers.marketplace_browse", "MarketplaceBrowseHandler"
)
AutomationHandler = _safe_import(
    "aragora.server.handlers.integrations.automation", "AutomationHandler"
)

# =============================================================================
# Workflow Handler Imports
# =============================================================================

WorkflowHandler = _safe_import("aragora.server.handlers", "WorkflowHandler")
WebhookHandler = _safe_import("aragora.server.handlers", "WebhookHandler")
QueueHandler = _safe_import("aragora.server.handlers", "QueueHandler")

# Workflow templates and patterns
WorkflowTemplatesHandler = _safe_import(
    "aragora.server.handlers.workflow_templates", "WorkflowTemplatesHandler"
)
WorkflowPatternsHandler = _safe_import(
    "aragora.server.handlers.workflow_templates", "WorkflowPatternsHandler"
)
WorkflowCategoriesHandler = _safe_import(
    "aragora.server.handlers.workflow_templates", "WorkflowCategoriesHandler"
)
WorkflowPatternTemplatesHandler = _safe_import(
    "aragora.server.handlers.workflow_templates", "WorkflowPatternTemplatesHandler"
)
SMEWorkflowsHandler = _safe_import(
    "aragora.server.handlers.workflow_templates", "SMEWorkflowsHandler"
)

# =============================================================================
# UI and Dashboard Handler Imports
# =============================================================================

DashboardHandler = _safe_import("aragora.server.handlers", "DashboardHandler")
LeaderboardViewHandler = _safe_import("aragora.server.handlers", "LeaderboardViewHandler")
GalleryHandler = _safe_import("aragora.server.handlers", "GalleryHandler")
CanvasHandler = _safe_import("aragora.server.handlers.canvas", "CanvasHandler")
SMEUsageDashboardHandler = _safe_import(
    "aragora.server.handlers.sme_usage_dashboard", "SMEUsageDashboardHandler"
)
SMESuccessDashboardHandler = _safe_import(
    "aragora.server.handlers.sme_success_dashboard", "SMESuccessDashboardHandler"
)
AgentDashboardHandler = _safe_import(
    "aragora.server.handlers.features.control_plane", "AgentDashboardHandler"
)
StatusPageHandler = _safe_import("aragora.server.handlers.public.status_page", "StatusPageHandler")

# =============================================================================
# Lab and Introspection Handler Imports
# =============================================================================

LaboratoryHandler = _safe_import("aragora.server.handlers", "LaboratoryHandler")
ProbesHandler = _safe_import("aragora.server.handlers", "ProbesHandler")
BreakpointsHandler = _safe_import("aragora.server.handlers", "BreakpointsHandler")
DebateInterventionHandler = _safe_import("aragora.server.handlers", "DebateInterventionHandler")
IntrospectionHandler = _safe_import("aragora.server.handlers", "IntrospectionHandler")

# =============================================================================
# Harnesses Handler Imports
# =============================================================================

HarnessesHandler = _safe_import("aragora.server.handlers.harnesses", "HarnessesHandler")

# =============================================================================
# Sandbox and Visualization Handler Imports
# =============================================================================

SandboxHandler = _safe_import("aragora.server.handlers", "SandboxHandler")
VisualizationHandler = _safe_import("aragora.server.handlers", "VisualizationHandler")

# =============================================================================
# Evolution Handler Imports
# =============================================================================

EvolutionHandler = _safe_import("aragora.server.handlers", "EvolutionHandler")
EvolutionABTestingHandler = _safe_import("aragora.server.handlers", "EvolutionABTestingHandler")

# =============================================================================
# Plugin and Feature Handler Imports
# =============================================================================

PluginsHandler = _safe_import("aragora.server.handlers", "PluginsHandler")
FeaturesHandler = _safe_import("aragora.server.handlers", "FeaturesHandler")
OnboardingHandler = _safe_import("aragora.server.handlers.onboarding", "OnboardingHandler")

# Device handler
DeviceHandler = _safe_import("aragora.server.handlers", "DeviceHandler")

# Relationship and routing handlers
RelationshipHandler = _safe_import("aragora.server.handlers", "RelationshipHandler")
RoutingHandler = _safe_import("aragora.server.handlers", "RoutingHandler")
RoutingRulesHandler = _safe_import(
    "aragora.server.handlers.features.routing_rules", "RoutingRulesHandler"
)

# =============================================================================
# Specialized Feature Handler Imports
# =============================================================================

CodeIntelligenceHandler = _safe_import("aragora.server.handlers.codebase", "IntelligenceHandler")
ComputerUseHandler = _safe_import(
    "aragora.server.handlers.computer_use_handler", "ComputerUseHandler"
)
RLMContextHandler = _safe_import("aragora.server.handlers", "RLMContextHandler")
RLMHandler = _safe_import("aragora.server.handlers.features.rlm", "RLMHandler")
MLHandler = _safe_import("aragora.server.handlers.ml", "MLHandler")
VerticalsHandler = _safe_import("aragora.server.handlers", "VerticalsHandler")

# =============================================================================
# Feature Platform Handler Imports
# =============================================================================

AdvertisingHandler = _safe_import("aragora.server.handlers.features", "AdvertisingHandler")
CRMHandler = _safe_import("aragora.server.handlers.features", "CRMHandler")
SupportHandler = _safe_import("aragora.server.handlers.features", "SupportHandler")
EcommerceHandler = _safe_import("aragora.server.handlers.features", "EcommerceHandler")
ReconciliationHandler = _safe_import("aragora.server.handlers.features", "ReconciliationHandler")
CodebaseAuditHandler = _safe_import("aragora.server.handlers.features", "CodebaseAuditHandler")
LegalHandler = _safe_import("aragora.server.handlers.features", "LegalHandler")
DevOpsHandler = _safe_import("aragora.server.handlers.features", "DevOpsHandler")

# =============================================================================
# Accounting Handler Imports
# =============================================================================

APAutomationHandler = _safe_import("aragora.server.handlers.ap_automation", "APAutomationHandler")
ARAutomationHandler = _safe_import("aragora.server.handlers.ar_automation", "ARAutomationHandler")
InvoiceHandler = _safe_import("aragora.server.handlers.invoices", "InvoiceHandler")
ExpenseHandler = _safe_import("aragora.server.handlers.expenses", "ExpenseHandler")

# =============================================================================
# Skills and Marketplace Handler Imports
# =============================================================================

SkillsHandler = _safe_import("aragora.server.handlers.skills", "SkillsHandler")
SkillMarketplaceHandler = _safe_import(
    "aragora.server.handlers.skill_marketplace", "SkillMarketplaceHandler"
)
TemplateMarketplaceHandler = _safe_import(
    "aragora.server.handlers.template_marketplace", "TemplateMarketplaceHandler"
)
TemplateRecommendationsHandler = _safe_import(
    "aragora.server.handlers.template_marketplace", "TemplateRecommendationsHandler"
)

# =============================================================================
# GitHub Handler Imports
# =============================================================================

PRReviewHandler = _safe_import("aragora.server.handlers.github.pr_review", "PRReviewHandler")
AuditGitHubBridgeHandler = _safe_import(
    "aragora.server.handlers.github.audit_bridge", "AuditGitHubBridgeHandler"
)

# =============================================================================
# Miscellaneous Handler Imports
# =============================================================================

BindingsHandler = _safe_import("aragora.server.handlers.bindings", "BindingsHandler")
DependencyAnalysisHandler = _safe_import(
    "aragora.server.handlers.dependency_analysis", "DependencyAnalysisHandler"
)
RepositoryHandler = _safe_import("aragora.server.handlers.repository", "RepositoryHandler")
SchedulerHandler = _safe_import("aragora.server.handlers.features.scheduler", "SchedulerHandler")
ThreatIntelHandler = _safe_import("aragora.server.handlers.threat_intel", "ThreatIntelHandler")
FeedbackRoutesHandler = _safe_import("aragora.server.handlers.feedback", "FeedbackRoutesHandler")
PaymentRoutesHandler = _safe_import(
    "aragora.server.handlers.payments.handler", "PaymentRoutesHandler"
)
FindingWorkflowHandler = _safe_import(
    "aragora.server.handlers.features.finding_workflow", "FindingWorkflowHandler"
)
ReceiptDeliveryHandler = _safe_import(
    "aragora.server.handlers.sme.receipt_delivery", "ReceiptDeliveryHandler"
)
CodeReviewHandler = _safe_import("aragora.server.handlers.code_review", "CodeReviewHandler")
QuickScanHandler = _safe_import("aragora.server.handlers.codebase.quick_scan", "QuickScanHandler")
CloudStorageHandler = _safe_import(
    "aragora.server.handlers.features.cloud_storage", "CloudStorageHandler"
)
SmartUploadHandler = _safe_import(
    "aragora.server.handlers.features.smart_upload", "SmartUploadHandler"
)
PartnerHandler = _safe_import("aragora.server.handlers.partner", "PartnerHandler")

# Playground (public demo)
PlaygroundHandler = _safe_import("aragora.server.handlers.playground", "PlaygroundHandler")

# Autonomous handlers
AlertHandler = _safe_import("aragora.server.handlers.autonomous.alerts", "AlertHandler")
ApprovalHandler = _safe_import("aragora.server.handlers.autonomous.approvals", "ApprovalHandler")
TriggerHandler = _safe_import("aragora.server.handlers.autonomous.triggers", "TriggerHandler")
MonitoringHandler = _safe_import(
    "aragora.server.handlers.autonomous.monitoring", "MonitoringHandler"
)

# Approvals and RBAC handlers
UnifiedApprovalsHandler = _safe_import(
    "aragora.server.handlers.approvals_inbox", "UnifiedApprovalsHandler"
)
RBACHandler = _safe_import("aragora.server.handlers.rbac", "RBACHandler")

# Federation status
FederationStatusHandler = _safe_import(
    "aragora.server.handlers.federation.status", "FederationStatusHandler"
)

# Self-improvement
SelfImproveHandler = _safe_import("aragora.server.handlers.self_improve", "SelfImproveHandler")
SelfImproveDetailsHandler = _safe_import(
    "aragora.server.handlers.self_improve_details", "SelfImproveDetailsHandler"
)
AutonomousImproveHandler = _safe_import(
    "aragora.server.handlers.autonomous.improve", "AutonomousImproveHandler"
)

# System intelligence dashboard
SystemIntelligenceHandler = _safe_import(
    "aragora.server.handlers.system_intelligence", "SystemIntelligenceHandler"
)

# Observability dashboard
ObservabilityDashboardHandler = _safe_import(
    "aragora.server.handlers.observability.dashboard", "ObservabilityDashboardHandler"
)

# Crash telemetry collector
CrashTelemetryHandler = _safe_import(
    "aragora.server.handlers.observability.crashes", "CrashTelemetryHandler"
)

# System health dashboard
SystemHealthDashboardHandler = _safe_import(
    "aragora.server.handlers.system_health", "SystemHealthDashboardHandler"
)

# System health dashboard
SystemHealthDashboardHandler = _safe_import(
    "aragora.server.handlers.system_health", "SystemHealthDashboardHandler"
)

# Platform config (runtime config for frontend)
PlatformConfigHandler = _safe_import(
    "aragora.server.handlers.platform_config", "PlatformConfigHandler"
)

# Feature flag admin
FeatureFlagAdminHandler = _safe_import(
    "aragora.server.handlers.admin.feature_flags", "FeatureFlagAdminHandler"
)

# Emergency break-glass access
EmergencyAccessHandler = _safe_import(
    "aragora.server.handlers.admin.emergency_access", "EmergencyAccessHandler"
)

# Cost dashboard
CostDashboardHandler = _safe_import(
    "aragora.server.handlers.billing.cost_dashboard", "CostDashboardHandler"
)

# Gas Town dashboard
GasTownDashboardHandler = _safe_import(
    "aragora.server.handlers.gastown_dashboard", "GasTownDashboardHandler"
)

# Connector management
ConnectorManagementHandler = _safe_import(
    "aragora.server.handlers.connectors.management", "ConnectorManagementHandler"
)

# Task execution
TaskExecutionHandler = _safe_import(
    "aragora.server.handlers.tasks.execution", "TaskExecutionHandler"
)

# Decision plans
PlansHandler = _safe_import("aragora.server.handlers.plans", "PlansHandler")

# Base handler result (for backward compatibility)
HandlerResult = _safe_import("aragora.server.handlers", "HandlerResult")

# Health and readiness handlers
LivenessHandler = _safe_import("aragora.server.handlers.admin.health.liveness", "LivenessHandler")
ReadinessHandler = _safe_import(
    "aragora.server.handlers.admin.health.readiness", "ReadinessHandler"
)
StorageHealthHandler = _safe_import(
    "aragora.server.handlers.admin.health.storage_health", "StorageHealthHandler"
)
ReadinessCheckHandler = _safe_import(
    "aragora.server.handlers.readiness_check", "ReadinessCheckHandler"
)

# Compliance handlers
ComplianceReportHandler = _safe_import(
    "aragora.server.handlers.compliance_reports", "ComplianceReportHandler"
)
EUAIActComplianceHandler = _safe_import(
    "aragora.server.handlers.compliance_eu_ai_act", "EUAIActComplianceHandler"
)
GDPRDeletionHandler = _safe_import("aragora.server.handlers.gdpr_deletion", "GDPRDeletionHandler")
MFAComplianceHandler = _safe_import(
    "aragora.server.handlers.admin.mfa_compliance", "MFAComplianceHandler"
)

# Backup offsite, feature flags, marketplace pilot
BackupOffsiteHandler = _safe_import(
    "aragora.server.handlers.backup_offsite_handler", "BackupOffsiteHandler"
)
FeatureFlagsHandler = _safe_import("aragora.server.handlers.feature_flags", "FeatureFlagsHandler")
MarketplacePilotHandler = _safe_import(
    "aragora.server.handlers.marketplace_pilot", "MarketplacePilotHandler"
)

# Workflow builder and template registry
WorkflowBuilderHandler = _safe_import(
    "aragora.server.handlers.workflows.builder", "WorkflowBuilderHandler"
)
TemplateRegistryHandler = _safe_import(
    "aragora.server.handlers.workflows.registry", "TemplateRegistryHandler"
)

# =============================================================================
# Admin Handler Registry Entries
# =============================================================================

ADMIN_HANDLER_REGISTRY: list[tuple[str, object]] = [
    # Core system
    ("_health_handler", HealthHandler),
    ("_build_info_handler", BuildInfoHandler),
    ("_deploy_status_handler", DeployStatusHandler),
    ("_nomic_handler", NomicHandler),
    ("_docs_handler", DocsHandler),
    ("_api_docs_handler", ApiDocsHandler),
    ("_mcp_tools_handler", MCPToolsHandler),
    ("_system_handler", SystemHandler),
    # Admin
    ("_admin_handler", AdminHandler),
    ("_control_plane_handler", ControlPlaneHandler),
    ("_policy_handler", PolicyHandler),
    ("_security_handler", SecurityHandler),
    ("_rotation_status_handler", RotationStatusHandler),
    ("_moderation_handler", ModerationHandler),
    ("_audience_suggestions_handler", AudienceSuggestionsHandler),
    ("_coordination_handler", CoordinationHandler),
    # Auth
    ("_auth_handler", AuthHandler),
    ("_oauth_handler", OAuthHandler),
    ("_oauth_wizard_handler", OAuthWizardHandler),
    ("_scim_handler", SCIMHandler),
    ("_sso_handler", SSOHandler),
    # Billing and budget
    ("_billing_handler", BillingHandler),
    ("_budget_handler", BudgetHandler),
    ("_budget_controls_handler", BudgetControlsHandler),
    ("_credits_admin_handler", CreditsAdminHandler),
    # Organization and workspace
    ("_organizations_handler", OrganizationsHandler),
    ("_workspace_handler", WorkspaceHandler),
    # Compliance, backup, DR
    ("_compliance_handler", ComplianceHandler),
    ("_backup_handler", BackupHandler),
    ("_dr_handler", DRHandler),
    ("_privacy_handler", PrivacyHandler),
    ("_audit_trail_handler", AuditTrailHandler),
    ("_audit_sessions_handler", AuditSessionsHandler),
    ("_csp_report_handler", CSPReportHandler),
    ("_data_classification_handler", DataClassificationHandler),
    # Gateway
    ("_gateway_handler", GatewayHandler),
    ("_openclaw_gateway_handler", OpenClawGatewayHandler),
    ("_gateway_credentials_handler", GatewayCredentialsHandler),
    ("_gateway_health_handler", GatewayHealthHandler),
    ("_gateway_config_handler", GatewayConfigHandler),
    ("_erc8004_handler", ERC8004Handler),
    # Integrations
    ("_external_integrations_handler", ExternalIntegrationsHandler),
    ("_integration_management_handler", IntegrationManagementHandler),
    ("_feature_integrations_handler", FeatureIntegrationsHandler),
    ("_connectors_handler", ConnectorsHandler),
    ("_streaming_connector_handler", StreamingConnectorHandler),
    ("_marketplace_handler", MarketplaceHandler),
    ("_integration_health_handler", IntegrationHealthHandler),
    ("_automation_handler", AutomationHandler),
    # Workflow
    ("_workflow_handler", WorkflowHandler),
    ("_webhook_handler", WebhookHandler),
    ("_queue_handler", QueueHandler),
    ("_workflow_templates_handler", WorkflowTemplatesHandler),
    ("_workflow_patterns_handler", WorkflowPatternsHandler),
    ("_workflow_categories_handler", WorkflowCategoriesHandler),
    ("_workflow_pattern_templates_handler", WorkflowPatternTemplatesHandler),
    ("_sme_workflows_handler", SMEWorkflowsHandler),
    # UI and dashboards
    ("_dashboard_handler", DashboardHandler),
    ("_leaderboard_handler", LeaderboardViewHandler),
    ("_gallery_handler", GalleryHandler),
    ("_canvas_handler", CanvasHandler),
    ("_sme_usage_dashboard_handler", SMEUsageDashboardHandler),
    ("_sme_success_dashboard_handler", SMESuccessDashboardHandler),
    ("_agent_dashboard_handler", AgentDashboardHandler),
    ("_status_page_handler", StatusPageHandler),
    # Lab and introspection
    ("_laboratory_handler", LaboratoryHandler),
    ("_probes_handler", ProbesHandler),
    ("_breakpoints_handler", BreakpointsHandler),
    ("_debate_intervention_handler", DebateInterventionHandler),
    ("_introspection_handler", IntrospectionHandler),
    # Harnesses (external tool integration)
    ("_harnesses_handler", HarnessesHandler),
    # Sandbox and visualization
    ("_sandbox_handler", SandboxHandler),
    ("_visualization_handler", VisualizationHandler),
    # Evolution
    ("_evolution_handler", EvolutionHandler),
    ("_evolution_ab_testing_handler", EvolutionABTestingHandler),
    # Plugins and features
    ("_plugins_handler", PluginsHandler),
    ("_features_handler", FeaturesHandler),
    ("_onboarding_handler", OnboardingHandler),
    ("_devices_handler", DeviceHandler),
    ("_relationship_handler", RelationshipHandler),
    ("_routing_handler", RoutingHandler),
    ("_routing_rules_handler", RoutingRulesHandler),
    # Specialized features
    ("_code_intelligence_handler", CodeIntelligenceHandler),
    ("_computer_use_handler", ComputerUseHandler),
    ("_rlm_context_handler", RLMContextHandler),
    ("_rlm_handler", RLMHandler),
    ("_ml_handler", MLHandler),
    ("_verticals_handler", VerticalsHandler),
    # Feature platforms
    ("_advertising_handler", AdvertisingHandler),
    ("_crm_handler", CRMHandler),
    ("_support_handler", SupportHandler),
    ("_ecommerce_handler", EcommerceHandler),
    ("_reconciliation_handler", ReconciliationHandler),
    ("_codebase_audit_handler", CodebaseAuditHandler),
    ("_legal_handler", LegalHandler),
    ("_devops_handler", DevOpsHandler),
    # Accounting
    ("_ap_automation_handler", APAutomationHandler),
    ("_ar_automation_handler", ARAutomationHandler),
    ("_invoice_handler", InvoiceHandler),
    ("_expense_handler", ExpenseHandler),
    # Skills and marketplace
    ("_skills_handler", SkillsHandler),
    ("_skill_marketplace_handler", SkillMarketplaceHandler),
    ("_template_marketplace_handler", TemplateMarketplaceHandler),
    ("_template_recommendations_handler", TemplateRecommendationsHandler),
    # GitHub
    ("_pr_review_handler", PRReviewHandler),
    ("_audit_github_bridge_handler", AuditGitHubBridgeHandler),
    # Miscellaneous
    ("_bindings_handler", BindingsHandler),
    ("_dependency_analysis_handler", DependencyAnalysisHandler),
    ("_repository_handler", RepositoryHandler),
    ("_scheduler_handler", SchedulerHandler),
    ("_threat_intel_handler", ThreatIntelHandler),
    ("_feedback_routes_handler", FeedbackRoutesHandler),
    ("_payment_routes_handler", PaymentRoutesHandler),
    ("_finding_workflow_handler", FindingWorkflowHandler),
    ("_receipt_delivery_handler", ReceiptDeliveryHandler),
    ("_code_review_handler", CodeReviewHandler),
    ("_quick_scan_handler", QuickScanHandler),
    ("_cloud_storage_handler", CloudStorageHandler),
    ("_smart_upload_handler", SmartUploadHandler),
    ("_partner_handler", PartnerHandler),
    # Autonomous
    ("_alert_handler", AlertHandler),
    ("_approval_handler", ApprovalHandler),
    ("_trigger_handler", TriggerHandler),
    ("_monitoring_handler", MonitoringHandler),
    # Approvals, RBAC, and management
    ("_unified_approvals_handler", UnifiedApprovalsHandler),
    ("_rbac_handler", RBACHandler),
    ("_feature_flag_admin_handler", FeatureFlagAdminHandler),
    ("_emergency_access_handler", EmergencyAccessHandler),
    ("_cost_dashboard_handler", CostDashboardHandler),
    ("_gastown_dashboard_handler", GasTownDashboardHandler),
    ("_connector_management_handler", ConnectorManagementHandler),
    ("_task_execution_handler", TaskExecutionHandler),
    # Decision plans
    ("_plans_handler", PlansHandler),
    # Playground (public demo)
    ("_playground_handler", PlaygroundHandler),
    # Marketplace browsing
    ("_marketplace_browse_handler", MarketplaceBrowseHandler),
    # Federation
    ("_federation_status_handler", FederationStatusHandler),
    # Self-improvement
    ("_self_improve_handler", SelfImproveHandler),
    ("_self_improve_details_handler", SelfImproveDetailsHandler),
    ("_autonomous_improve_handler", AutonomousImproveHandler),
    # System intelligence
    ("_system_intelligence_handler", SystemIntelligenceHandler),
    # Observability
    ("_observability_dashboard_handler", ObservabilityDashboardHandler),
    # Crash telemetry
    ("_crash_telemetry_handler", CrashTelemetryHandler),
    # System health dashboard
    ("_system_health_dashboard_handler", SystemHealthDashboardHandler),
    # Platform config (runtime config for frontend)
    ("_platform_config_handler", PlatformConfigHandler),
    # Spend analytics (imported but was missing from registry)
    ("_spend_analytics_handler", SpendAnalyticsHandler),
    # Health and readiness
    ("_liveness_handler", LivenessHandler),
    ("_readiness_handler", ReadinessHandler),
    ("_storage_health_handler", StorageHealthHandler),
    ("_readiness_check_handler", ReadinessCheckHandler),
    # Compliance
    ("_compliance_report_handler", ComplianceReportHandler),
    ("_eu_ai_act_compliance_handler", EUAIActComplianceHandler),
    ("_gdpr_deletion_handler", GDPRDeletionHandler),
    ("_mfa_compliance_handler", MFAComplianceHandler),
    # Backup offsite, feature flags, marketplace pilot
    ("_backup_offsite_handler", BackupOffsiteHandler),
    ("_feature_flags_handler", FeatureFlagsHandler),
    ("_marketplace_pilot_handler", MarketplacePilotHandler),
    # Workflow builder and template registry
    ("_workflow_builder_handler", WorkflowBuilderHandler),
    ("_template_registry_handler", TemplateRegistryHandler),
]

__all__ = [
    # Core system
    "SystemHandler",
    "HealthHandler",
    "NomicHandler",
    "DocsHandler",
    # Admin
    "AdminHandler",
    "ControlPlaneHandler",
    "PolicyHandler",
    "SecurityHandler",
    "RotationStatusHandler",
    "AudienceSuggestionsHandler",
    "CoordinationHandler",
    # Auth
    "AuthHandler",
    "OAuthHandler",
    "OAuthWizardHandler",
    "SCIMHandler",
    "SSOHandler",
    # Billing
    "BillingHandler",
    "BudgetHandler",
    "BudgetControlsHandler",
    "CreditsAdminHandler",
    # Organization
    "OrganizationsHandler",
    "WorkspaceHandler",
    # Compliance
    "ComplianceHandler",
    "BackupHandler",
    "DRHandler",
    "PrivacyHandler",
    "AuditTrailHandler",
    "AuditSessionsHandler",
    "CSPReportHandler",
    "DataClassificationHandler",
    # Gateway
    "GatewayHandler",
    "OpenClawGatewayHandler",
    "GatewayCredentialsHandler",
    "GatewayHealthHandler",
    "GatewayConfigHandler",
    "ERC8004Handler",
    # Integrations
    "ExternalIntegrationsHandler",
    "IntegrationManagementHandler",
    "FeatureIntegrationsHandler",
    "ConnectorsHandler",
    "IntegrationHealthHandler",
    "StreamingConnectorHandler",
    "MarketplaceHandler",
    "AutomationHandler",
    # Workflow
    "WorkflowHandler",
    "WebhookHandler",
    "QueueHandler",
    "WorkflowTemplatesHandler",
    "WorkflowPatternsHandler",
    "WorkflowCategoriesHandler",
    "WorkflowPatternTemplatesHandler",
    "SMEWorkflowsHandler",
    # UI
    "DashboardHandler",
    "LeaderboardViewHandler",
    "GalleryHandler",
    "CanvasHandler",
    "SMEUsageDashboardHandler",
    "SMESuccessDashboardHandler",
    "AgentDashboardHandler",
    "StatusPageHandler",
    # Lab
    "LaboratoryHandler",
    "ProbesHandler",
    "BreakpointsHandler",
    "DebateInterventionHandler",
    "IntrospectionHandler",
    # Harnesses
    "HarnessesHandler",
    # Sandbox and visualization
    "SandboxHandler",
    "VisualizationHandler",
    # Evolution
    "EvolutionHandler",
    "EvolutionABTestingHandler",
    # Plugins
    "PluginsHandler",
    "FeaturesHandler",
    "OnboardingHandler",
    "DeviceHandler",
    "RelationshipHandler",
    "RoutingHandler",
    "RoutingRulesHandler",
    # Specialized
    "CodeIntelligenceHandler",
    "ComputerUseHandler",
    "RLMContextHandler",
    "RLMHandler",
    "MLHandler",
    "VerticalsHandler",
    # Platforms
    "AdvertisingHandler",
    "CRMHandler",
    "SupportHandler",
    "EcommerceHandler",
    "ReconciliationHandler",
    "CodebaseAuditHandler",
    "LegalHandler",
    "DevOpsHandler",
    # Accounting
    "APAutomationHandler",
    "ARAutomationHandler",
    "InvoiceHandler",
    "ExpenseHandler",
    # Skills
    "SkillsHandler",
    "SkillMarketplaceHandler",
    "TemplateMarketplaceHandler",
    "TemplateRecommendationsHandler",
    # GitHub
    "PRReviewHandler",
    "AuditGitHubBridgeHandler",
    # Misc
    "BindingsHandler",
    "DependencyAnalysisHandler",
    "RepositoryHandler",
    "SchedulerHandler",
    "ThreatIntelHandler",
    "FeedbackRoutesHandler",
    "PaymentRoutesHandler",
    "FindingWorkflowHandler",
    "ReceiptDeliveryHandler",
    "CodeReviewHandler",
    "QuickScanHandler",
    "CloudStorageHandler",
    "SmartUploadHandler",
    "PartnerHandler",
    # Autonomous
    "AlertHandler",
    "ApprovalHandler",
    "TriggerHandler",
    "MonitoringHandler",
    # Approvals, RBAC, and management
    "UnifiedApprovalsHandler",
    "RBACHandler",
    "FeatureFlagAdminHandler",
    "EmergencyAccessHandler",
    "CostDashboardHandler",
    "GasTownDashboardHandler",
    "ConnectorManagementHandler",
    "TaskExecutionHandler",
    # Decision plans
    "PlansHandler",
    # Playground
    "PlaygroundHandler",
    # Marketplace browsing
    "MarketplaceBrowseHandler",
    # Federation
    "FederationStatusHandler",
    # Self-improvement
    "SelfImproveHandler",
    "SelfImproveDetailsHandler",
    "AutonomousImproveHandler",
    # System intelligence
    "SystemIntelligenceHandler",
    # Observability
    "ObservabilityDashboardHandler",
    # Crash telemetry
    "CrashTelemetryHandler",
    # System health dashboard
    "SystemHealthDashboardHandler",
    # Platform config
    "PlatformConfigHandler",
    # Handler result
    "HandlerResult",
    # Registry
    "ADMIN_HANDLER_REGISTRY",
]
