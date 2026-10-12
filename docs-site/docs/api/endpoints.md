---
title: Aragora API Documentation
description: Aragora API Documentation
---

# Aragora API Documentation

This document describes the HTTP API endpoints provided by the Aragora server.

## Table of Contents

- [Admin (admin/admin.py)](#admin-adminadminpy)
- [ApiDocs (admin/api_docs.py)](#apidocs-adminapi_docspy)
- [Backup Handler (admin/backup_handler.py)](#backup-handler-adminbackup_handlerpy)
- [Backup Offsite Handler (admin/backup_offsite_handler.py)](#backup-offsite-handler-adminbackup_offsite_handlerpy)
- [Billing (admin/billing.py)](#billing-adminbillingpy)
- [Credits (admin/credits.py)](#credits-admincreditspy)
- [Dashboard (admin/dashboard.py)](#dashboard-admindashboardpy)
- [Docs (admin/docs.py)](#docs-admindocspy)
- [Dr Handler (admin/dr_handler.py)](#dr-handler-admindr_handlerpy)
- [Feature Flags (admin/feature_flags.py)](#feature-flags-adminfeature_flagspy)
- [Feature Flags Read (admin/feature_flags_read.py)](#feature-flags-read-adminfeature_flags_readpy)
- [Admin (admin/handler.py)](#admin-adminhandlerpy)
- [BuildInfo (admin/health/build.py)](#buildinfo-adminhealthbuildpy)
- [DeployStatus (admin/health/deploy_status.py)](#deploystatus-adminhealthdeploy_statuspy)
- [Liveness (admin/health/liveness.py)](#liveness-adminhealthlivenesspy)
- [Readiness (admin/health/readiness.py)](#readiness-adminhealthreadinesspy)
- [StorageHealth (admin/health/storage_health.py)](#storagehealth-adminhealthstorage_healthpy)
- [Metrics Dashboard (admin/metrics_dashboard.py)](#metrics-dashboard-adminmetrics_dashboardpy)
- [Mfa Compliance (admin/mfa_compliance.py)](#mfa-compliance-adminmfa_compliancepy)
- [Nomic Admin (admin/nomic_admin.py)](#nomic-admin-adminnomic_adminpy)
- [Rotation Status (admin/rotation_status.py)](#rotation-status-adminrotation_statuspy)
- [Security (admin/security.py)](#security-adminsecuritypy)
- [System (admin/system.py)](#system-adminsystempy)
- [System Health (admin/system_health.py)](#system-health-adminsystem_healthpy)
- [System Intelligence (admin/system_intelligence.py)](#system-intelligence-adminsystem_intelligencepy)
- [Users (admin/users.py)](#users-adminuserspy)
- [AgentBridge (agents/agent_bridge.py)](#agentbridge-agentsagent_bridgepy)
- [Agents (agents/agents.py)](#agents-agentsagentspy)
- [Calibration (agents/calibration.py)](#calibration-agentscalibrationpy)
- [Config (agents/config.py)](#config-agentsconfigpy)
- [External Agents (agents/external_agents.py)](#external-agents-agentsexternal_agentspy)
- [Feedback (agents/feedback.py)](#feedback-agentsfeedbackpy)
- [Feedback Hub (agents/feedback_hub.py)](#feedback-hub-agentsfeedback_hubpy)
- [Harnesses (agents/harnesses.py)](#harnesses-agentsharnessespy)
- [Introspection (agents/introspection.py)](#introspection-agentsintrospectionpy)
- [Laboratory (agents/laboratory.py)](#laboratory-agentslaboratorypy)
- [LeaderboardView (agents/leaderboard.py)](#leaderboardview-agentsleaderboardpy)
- [MatchesStats (agents/matches_stats.py)](#matchesstats-agentsmatches_statspy)
- [Persona (agents/persona.py)](#persona-agentspersonapy)
- [Probes (agents/probes.py)](#probes-agentsprobespy)
- [AgentRecommendation (agents/recommendations.py)](#agentrecommendation-agentsrecommendationspy)
- [Routing (agents/routing.py)](#routing-agentsroutingpy)
- [Selection (agents/selection.py)](#selection-agentsselectionpy)
- [Verticals (agents/verticals.py)](#verticals-agentsverticalspy)
- [AnalyticsPerformance (analytics/analytics_performance.py)](#analyticsperformance-analyticsanalytics_performancepy)
- [DecisionAnalytics (analytics/decision_analytics.py)](#decisionanalytics-analyticsdecision_analyticspy)
- [ModerationAnalytics (analytics/moderation_analytics.py)](#moderationanalytics-analyticsmoderation_analyticspy)
- [OutcomeAnalytics (analytics/outcome_analytics.py)](#outcomeanalytics-analyticsoutcome_analyticspy)
- [SpendAnalytics (analytics/spend_analytics.py)](#spendanalytics-analyticsspend_analyticspy)
- [Agent Evolution Dashboard (analytics_dashboard/agent_evolution_dashboard.py)](#agent-evolution-dashboard-analytics_dashboardagent_evolution_dashboardpy)
- [Dashboard (analytics_dashboard/dashboard.py)](#dashboard-analytics_dashboarddashboardpy)
- [Differentiation (analytics_dashboard/differentiation.py)](#differentiation-analytics_dashboarddifferentiationpy)
- [AnalyticsDashboard (analytics_dashboard/handler.py)](#analyticsdashboard-analytics_dashboardhandlerpy)
- [Outcome Dashboard (analytics_dashboard/outcome_dashboard.py)](#outcome-dashboard-analytics_dashboardoutcome_dashboardpy)
- [Handler (auth/handler.py)](#handler-authhandlerpy)
- [RBAC (auth/rbac.py)](#rbac-authrbacpy)
- [SCIM (auth/scim_handler.py)](#scim-authscim_handlerpy)
- [Signup Handlers (auth/signup_handlers.py)](#signup-handlers-authsignup_handlerspy)
- [SSO (auth/sso.py)](#sso-authssopy)
- [Autonomous Learning (autonomous/autonomous_learning.py)](#autonomous-learning-autonomousautonomous_learningpy)
- [Gastown Dashboard (autonomous/gastown_dashboard.py)](#gastown-dashboard-autonomousgastown_dashboardpy)
- [Monitoring (autonomous/monitoring.py)](#monitoring-autonomousmonitoringpy)
- [Nomic (autonomous/nomic.py)](#nomic-autonomousnomicpy)
- [RalphDashboard (autonomous/ralph_dashboard.py)](#ralphdashboard-autonomousralph_dashboardpy)
- [Self Improve (autonomous/self_improve.py)](#self-improve-autonomousself_improvepy)
- [Self Improve Details (autonomous/self_improve_details.py)](#self-improve-details-autonomousself_improve_detailspy)
- [Budgets (billing/budgets.py)](#budgets-billingbudgetspy)
- [Core (billing/core.py)](#core-billingcorepy)
- [CostDashboard (billing/cost_dashboard.py)](#costdashboard-billingcost_dashboardpy)
- [UsageMetering (billing/subscriptions.py)](#usagemetering-billingsubscriptionspy)
- [UsageMetering (billing/usage_metering.py)](#usagemetering-billingusage_meteringpy)
- [Discord (bots/discord.py)](#discord-botsdiscordpy)
- [Email Webhook (bots/email_webhook.py)](#email-webhook-botsemail_webhookpy)
- [Google Chat (bots/google_chat.py)](#google-chat-botsgoogle_chatpy)
- [Slack (bots/slack/handler.py)](#slack-botsslackhandlerpy)
- [Handler (bots/teams/handler.py)](#handler-botsteamshandlerpy)
- [Telegram (bots/telegram.py)](#telegram-botstelegrampy)
- [Whatsapp (bots/whatsapp.py)](#whatsapp-botswhatsapppy)
- [Zoom (bots/zoom.py)](#zoom-botszoompy)
- [IdeaCanvas (canvas/idea_canvas.py)](#ideacanvas-canvasidea_canvaspy)
- [Marketplace (catalog/marketplace.py)](#marketplace-catalogmarketplacepy)
- [MarketplaceBrowse (catalog/marketplace_browse.py)](#marketplacebrowse-catalogmarketplace_browsepy)
- [Marketplace Pilot (catalog/marketplace_pilot.py)](#marketplace-pilot-catalogmarketplace_pilotpy)
- [Playbook (catalog/playbooks.py)](#playbook-catalogplaybookspy)
- [Skill Marketplace (catalog/skill_marketplace.py)](#skill-marketplace-catalogskill_marketplacepy)
- [Skills (catalog/skills.py)](#skills-catalogskillspy)
- [TemplateDiscovery (catalog/template_discovery.py)](#templatediscovery-catalogtemplate_discoverypy)
- [Template Marketplace (catalog/template_marketplace.py)](#template-marketplace-catalogtemplate_marketplacepy)
- [Workflow Templates (catalog/workflow_templates.py)](#workflow-templates-catalogworkflow_templatespy)
- [Code Review (codebase/code_review.py)](#code-review-codebasecode_reviewpy)
- [Dependency Analysis (codebase/dependency_analysis.py)](#dependency-analysis-codebasedependency_analysispy)
- [Intelligence (codebase/intelligence.py)](#intelligence-codebaseintelligencepy)
- [Metrics (codebase/metrics.py)](#metrics-codebasemetricspy)
- [Quick Scan (codebase/quick_scan.py)](#quick-scan-codebasequick_scanpy)
- [Repository (codebase/repository.py)](#repository-codebaserepositorypy)
- [Reviews (codebase/reviews.py)](#reviews-codebasereviewspy)
- [Audit Trail (compliance/audit_trail.py)](#audit-trail-complianceaudit_trailpy)
- [Data Classification Handler (compliance/data_classification_handler.py)](#data-classification-handler-compliancedata_classification_handlerpy)
- [Gdpr Deletion (compliance/gdpr_deletion.py)](#gdpr-deletion-compliancegdpr_deletionpy)
- [Compliance (compliance/handler.py)](#compliance-compliancehandlerpy)
- [Privacy (compliance/privacy.py)](#privacy-complianceprivacypy)
- [Queue (control_plane/queue.py)](#queue-control_planequeuepy)
- [Cost (costs/handler.py)](#cost-costshandlerpy)
- [Audience Suggestions (debates/audience_suggestions.py)](#audience-suggestions-debatesaudience_suggestionspy)
- [Auditing (debates/auditing.py)](#auditing-debatesauditingpy)
- [Belief (debates/belief.py)](#belief-debatesbeliefpy)
- [Breakpoints (debates/breakpoints.py)](#breakpoints-debatesbreakpointspy)
- [DebateDecisionBridge (debates/bridge.py)](#debatedecisionbridge-debatesbridgepy)
- [Composite (debates/composite.py)](#composite-debatescompositepy)
- [Context Budget (debates/context_budget.py)](#context-budget-debatescontext_budgetpy)
- [Critique (debates/critique.py)](#critique-debatescritiquepy)
- [Debate Intervention (debates/debate_intervention.py)](#debate-intervention-debatesdebate_interventionpy)
- [Debate Stats (debates/debate_stats.py)](#debate-stats-debatesdebate_statspy)
- [DecisionPackage (debates/decision_package.py)](#decisionpackage-debatesdecision_packagepy)
- [Deliberations (debates/deliberations.py)](#deliberations-debatesdeliberationspy)
- [Graph Debates (debates/graph_debates.py)](#graph-debates-debatesgraph_debatespy)
- [Handler (debates/handler.py)](#handler-debateshandlerpy)
- [HybridDebate (debates/hybrid_debate_handler.py)](#hybriddebate-debateshybrid_debate_handlerpy)
- [DebateInterventions (debates/interventions.py)](#debateinterventions-debatesinterventionspy)
- [Matrix Debates (debates/matrix_debates.py)](#matrix-debates-debatesmatrix_debatespy)
- [Moments (debates/moments.py)](#moments-debatesmomentspy)
- [PublicDebateViewer (debates/public_viewer.py)](#publicdebateviewer-debatespublic_viewerpy)
- [DebateShare (debates/share.py)](#debateshare-debatessharepy)
- [Tournaments (debates/tournaments.py)](#tournaments-debatestournamentspy)
- [Uncertainty (debates/uncertainty.py)](#uncertainty-debatesuncertaintypy)
- [Visualization (debates/visualization.py)](#visualization-debatesvisualizationpy)
- [Decision (decisions/decision.py)](#decision-decisionsdecisionpy)
- [DecisionExplain (decisions/explain.py)](#decisionexplain-decisionsexplainpy)
- [Explainability (decisions/explainability.py)](#explainability-decisionsexplainabilitypy)
- [Pipeline (decisions/pipeline.py)](#pipeline-decisionspipelinepy)
- [Receipts (decisions/receipts.py)](#receipts-decisionsreceiptspy)
- [Playground (demo/playground.py)](#playground-demoplaygroundpy)
- [EmailDebate (email/email_debate.py)](#emaildebate-emailemail_debatepy)
- [Email Services (email/email_services.py)](#email-services-emailemail_servicespy)
- [EmailTriage (email/email_triage.py)](#emailtriage-emailemail_triagepy)
- [Email (email/handler.py)](#email-emailhandlerpy)
- [Ab Testing (evolution/ab_testing.py)](#ab-testing-evolutionab_testingpy)
- [Cross Pollination (evolution/cross_pollination.py)](#cross-pollination-evolutioncross_pollinationpy)
- [Genesis (evolution/genesis.py)](#genesis-evolutiongenesispy)
- [Handler (evolution/handler.py)](#handler-evolutionhandlerpy)
- [Replays (evolution/replays.py)](#replays-evolutionreplayspy)
- [Training (evolution/training.py)](#training-evolutiontrainingpy)
- [ExamplePermission (examples/permission_example.py)](#examplepermission-examplespermission_examplepy)
- [Advertising (features/advertising.py)](#advertising-featuresadvertisingpy)
- [AnalyticsPlatforms (features/analytics_platforms.py)](#analyticsplatforms-featuresanalytics_platformspy)
- [Audio (features/audio.py)](#audio-featuresaudiopy)
- [AuditSessions (features/audit_sessions.py)](#auditsessions-featuresaudit_sessionspy)
- [Broadcast (features/broadcast.py)](#broadcast-featuresbroadcastpy)
- [Handler (features/codebase_audit/handler.py)](#handler-featurescodebase_audithandlerpy)
- [Connectors (features/connectors.py)](#connectors-featuresconnectorspy)
- [CRM (features/crm/handler.py)](#crm-featurescrmhandlerpy)
- [Cross Platform Analytics (features/cross_platform_analytics.py)](#cross-platform-analytics-featurescross_platform_analyticspy)
- [Handler (features/devops/handler.py)](#handler-featuresdevopshandlerpy)
- [Document Query (features/document_query.py)](#document-query-featuresdocument_querypy)
- [Documents (features/documents.py)](#documents-featuresdocumentspy)
- [DocumentBatch (features/documents_batch.py)](#documentbatch-featuresdocuments_batchpy)
- [Ecommerce (features/ecommerce/handler.py)](#ecommerce-featuresecommercehandlerpy)
- [Email Webhooks (features/email_webhooks.py)](#email-webhooks-featuresemail_webhookspy)
- [Evidence (features/evidence.py)](#evidence-featuresevidencepy)
- [Evidence Enrichment (features/evidence_enrichment.py)](#evidence-enrichment-featuresevidence_enrichmentpy)
- [Features (features/features.py)](#features-featuresfeaturespy)
- [Finding Workflow (features/finding_workflow.py)](#finding-workflow-featuresfinding_workflowpy)
- [Folder Upload (features/folder_upload.py)](#folder-upload-featuresfolder_uploadpy)
- [Gmail Ingest (features/gmail_ingest.py)](#gmail-ingest-featuresgmail_ingestpy)
- [GmailLabels (features/gmail_labels.py)](#gmaillabels-featuresgmail_labelspy)
- [Gmail Query (features/gmail_query.py)](#gmail-query-featuresgmail_querypy)
- [GmailThreads (features/gmail_threads.py)](#gmailthreads-featuresgmail_threadspy)
- [Integrations (features/integrations.py)](#integrations-featuresintegrationspy)
- [Legal (features/legal.py)](#legal-featureslegalpy)
- [Handler (features/marketplace/handler.py)](#handler-featuresmarketplacehandlerpy)
- [Outlook (features/outlook.py)](#outlook-featuresoutlookpy)
- [Plugins (features/plugins.py)](#plugins-featurespluginspy)
- [Pulse (features/pulse.py)](#pulse-featurespulsepy)
- [Reconciliation (features/reconciliation.py)](#reconciliation-featuresreconciliationpy)
- [Rlm (features/rlm.py)](#rlm-featuresrlmpy)
- [RoutingRules (features/routing_rules.py)](#routingrules-featuresrouting_rulespy)
- [Support (features/support.py)](#support-featuressupportpy)
- [Transcription (features/transcription.py)](#transcription-featurestranscriptionpy)
- [Handler (features/unified_inbox/handler.py)](#handler-featuresunified_inboxhandlerpy)
- [Status (federation/status.py)](#status-federationstatuspy)
- [Accounting (finance/accounting.py)](#accounting-financeaccountingpy)
- [Ap Automation (finance/ap_automation.py)](#ap-automation-financeap_automationpy)
- [Ar Automation (finance/ar_automation.py)](#ar-automation-financear_automationpy)
- [Expenses (finance/expenses.py)](#expenses-financeexpensespy)
- [Invoices (finance/invoices.py)](#invoices-financeinvoicespy)
- [A2A (gateway/a2a.py)](#a2a-gatewaya2apy)
- [GatewayAgents (gateway/gateway_agents_handler.py)](#gatewayagents-gatewaygateway_agents_handlerpy)
- [GatewayConfig (gateway/gateway_config_handler.py)](#gatewayconfig-gatewaygateway_config_handlerpy)
- [GatewayCredentials (gateway/gateway_credentials_handler.py)](#gatewaycredentials-gatewaygateway_credentials_handlerpy)
- [Gateway (gateway/gateway_handler.py)](#gateway-gatewaygateway_handlerpy)
- [GatewayHealth (gateway/gateway_health_handler.py)](#gatewayhealth-gatewaygateway_health_handlerpy)
- [Gauntlet (gauntlet/handler.py)](#gauntlet-gauntlethandlerpy)
- [Audit Bridge (github/audit_bridge.py)](#audit-bridge-githubaudit_bridgepy)
- [Pr Review (github/pr_review.py)](#pr-review-githubpr_reviewpy)
- [UnifiedApprovals (governance/approvals_inbox.py)](#unifiedapprovals-governanceapprovals_inboxpy)
- [Moderation (governance/moderation.py)](#moderation-governancemoderationpy)
- [Outcome (governance/outcomes.py)](#outcome-governanceoutcomespy)
- [Policy (governance/policy.py)](#policy-governancepolicypy)
- [ReviewQueue (governance/review_queue.py)](#reviewqueue-governancereview_queuepy)
- [Settlement (governance/settlements.py)](#settlement-governancesettlementspy)
- [Inbox Command (inbox/inbox_command.py)](#inbox-command-inboxinbox_commandpy)
- [Team Inbox (inbox/team_inbox.py)](#team-inbox-inboxteam_inboxpy)
- [InboxTrustWedge (inbox/trust_wedge_handler.py)](#inboxtrustwedge-inboxtrust_wedge_handlerpy)
- [Automation (integrations/automation.py)](#automation-integrationsautomationpy)
- [Bindings (integrations/bindings.py)](#bindings-integrationsbindingspy)
- [ComputerUse (integrations/computer_use_handler.py)](#computeruse-integrationscomputer_use_handlerpy)
- [ERC8004 (integrations/erc8004.py)](#erc8004-integrationserc8004py)
- [External Integrations (integrations/external_integrations.py)](#external-integrations-integrationsexternal_integrationspy)
- [Health (integrations/health.py)](#health-integrationshealthpy)
- [Integration Management (integrations/integration_management.py)](#integration-management-integrationsintegration_managementpy)
- [Partner (integrations/partner.py)](#partner-integrationspartnerpy)
- [Adapters (knowledge/adapters.py)](#adapters-knowledgeadapterspy)
- [KMCheckpoint (knowledge/checkpoints.py)](#kmcheckpoint-knowledgecheckpointspy)
- [KnowledgeChat (knowledge/knowledge_chat.py)](#knowledgechat-knowledgeknowledge_chatpy)
- [Ml (knowledge/ml.py)](#ml-knowledgemlpy)
- [RLMContext (knowledge/rlm.py)](#rlmcontext-knowledgerlmpy)
- [Knowledge (knowledge_base/handler.py)](#knowledge-knowledge_basehandlerpy)
- [KnowledgeMound (knowledge_base/mound/handler.py)](#knowledgemound-knowledge_basemoundhandlerpy)
- [Checkpoints (memory/checkpoints.py)](#checkpoints-memorycheckpointspy)
- [Consensus (memory/consensus.py)](#consensus-memoryconsensuspy)
- [Coordinator (memory/coordinator.py)](#coordinator-memorycoordinatorpy)
- [Insights (memory/insights.py)](#insights-memoryinsightspy)
- [Learning (memory/learning.py)](#learning-memorylearningpy)
- [Memory (memory/memory.py)](#memory-memorymemorypy)
- [Memory Analytics (memory/memory_analytics.py)](#memory-analytics-memorymemory_analyticspy)
- [Handler (metrics/handler.py)](#handler-metricshandlerpy)
- [Metrics Endpoint (metrics/metrics_endpoint.py)](#metrics-endpoint-metricsmetrics_endpointpy)
- [Devices (notifications/devices.py)](#devices-notificationsdevicespy)
- [NotificationHistory (notifications/history.py)](#notificationhistory-notificationshistorypy)
- [NotificationPreferences (notifications/preferences.py)](#notificationpreferences-notificationspreferencespy)
- [NotificationTemplates (notifications/templates.py)](#notificationtemplates-notificationstemplatespy)
- [Oauth Wizard (oauth/oauth_wizard.py)](#oauth-wizard-oauthoauth_wizardpy)
- [Crashes (observability/crashes.py)](#crashes-observabilitycrashespy)
- [Dashboard (observability/dashboard.py)](#dashboard-observabilitydashboardpy)
- [EndpointAnalytics (observability/endpoint_analytics.py)](#endpointanalytics-observabilityendpoint_analyticspy)
- [Slo (observability/slo.py)](#slo-observabilityslopy)
- [Gateway (openclaw/gateway.py)](#gateway-openclawgatewaypy)
- [Coordination (orchestration/coordination.py)](#coordination-orchestrationcoordinationpy)
- [Handler (orchestration/handler.py)](#handler-orchestrationhandlerpy)
- [PaymentRoutes (payments/handler.py)](#paymentroutes-paymentshandlerpy)
- [Decomposition (pipeline/decomposition.py)](#decomposition-pipelinedecompositionpy)
- [PipelineExecute (pipeline/execute.py)](#pipelineexecute-pipelineexecutepy)
- [Pipeline Graph (pipeline/pipeline_graph.py)](#pipeline-graph-pipelinepipeline_graphpy)
- [PlanManagement (pipeline/plans.py)](#planmanagement-pipelineplanspy)
- [ProvenanceExplorer (pipeline/provenance_explorer.py)](#provenanceexplorer-pipelineprovenance_explorerpy)
- [Receipts (pipeline/receipts.py)](#receipts-pipelinereceiptspy)
- [PipelineTransitions (pipeline/transitions.py)](#pipelinetransitions-pipelinetransitionspy)
- [UniversalGraph (pipeline/universal_graph.py)](#universalgraph-pipelineuniversal_graphpy)
- [Platform Config (platform_config.py)](#platform-config-platform_configpy)
- [Handler (prompt_engine/handler.py)](#handler-prompt_enginehandlerpy)
- [Gallery (public/gallery.py)](#gallery-publicgallerypy)
- [StatusPage (public/status_page.py)](#statuspage-publicstatus_pagepy)
- [Security Debate (security/security_debate.py)](#security-debate-securitysecurity_debatepy)
- [Threat Intel (security/threat_intel.py)](#threat-intel-securitythreat_intelpy)
- [SharedInbox (shared_inbox/handler.py)](#sharedinbox-shared_inboxhandlerpy)
- [Feedback (sme/feedback.py)](#feedback-smefeedbackpy)
- [Onboarding (sme/onboarding.py)](#onboarding-smeonboardingpy)
- [ReadinessCheck (sme/readiness_check.py)](#readinesscheck-smereadiness_checkpy)
- [SMEUsageDashboard (sme/sme_usage_dashboard.py)](#smeusagedashboard-smesme_usage_dashboardpy)
- [ChannelHealth (social/channel_health.py)](#channelhealth-socialchannel_healthpy)
- [Collaboration (social/collaboration.py)](#collaboration-socialcollaborationpy)
- [Discord Oauth (social/discord_oauth.py)](#discord-oauth-socialdiscord_oauthpy)
- [Notifications (social/notifications.py)](#notifications-socialnotificationspy)
- [Relationship (social/relationship.py)](#relationship-socialrelationshippy)
- [Sharing (social/sharing.py)](#sharing-socialsharingpy)
- [Slack Oauth (social/slack_oauth.py)](#slack-oauth-socialslack_oauthpy)
- [Social Media (social/social_media.py)](#social-media-socialsocial_mediapy)
- [Teams (social/teams.py)](#teams-socialteamspy)
- [Teams Oauth (social/teams_oauth.py)](#teams-oauth-socialteams_oauthpy)
- [Spectate Ws (streaming/spectate_ws.py)](#spectate-ws-streamingspectate_wspy)
- [TaskExecution (tasks/execution.py)](#taskexecution-tasksexecutionpy)
- [TaskQueue (tasks/queue.py)](#taskqueue-tasksqueuepy)
- [Benchmarking (verification/benchmarking.py)](#benchmarking-verificationbenchmarkingpy)
- [Evaluation (verification/evaluation.py)](#evaluation-verificationevaluationpy)
- [Formal Verification (verification/formal_verification.py)](#formal-verification-verificationformal_verificationpy)
- [Verification (verification/verification.py)](#verification-verificationverificationpy)
- [Voice (voice/handler.py)](#voice-voicehandlerpy)
- [Transcription (voice/transcription.py)](#transcription-voicetranscriptionpy)
- [Webhook (webhook_management.py)](#webhook-webhook_managementpy)
- [WorkflowBuilder (workflows/builder.py)](#workflowbuilder-workflowsbuilderpy)
- [Workflow (workflows/handler.py)](#workflow-workflowshandlerpy)
- [TemplateRegistry (workflows/registry.py)](#templateregistry-workflowsregistrypy)
- [Organizations (workspace/organizations.py)](#organizations-workspaceorganizationspy)
- [Workspace Module (workspace/workspace_module.py)](#workspace-module-workspaceworkspace_modulepy)

---

## Admin (admin/admin.py)

Admin API Handlers - Backward Compatibility Shim.

### `GET` `/api/v1/admin/organizations` 🔒

List all organizations

### `GET` `/api/v1/admin/users` 🔒

List all users

### `GET` `/api/v1/admin/stats` 🔒

Get system-wide statistics

### `GET` `/api/v1/admin/system/metrics` 🔒

Get aggregated system metrics

### `POST` `/api/v1/admin/impersonate/:user_id` 🔒

Create impersonation token

### `POST` `/api/v1/admin/users/:user_id/deactivate` 🔒

Deactivate a user

### `POST` `/api/v1/admin/users/:user_id/activate` 🔒

Activate a user

### `POST` `/api/v1/admin/users/:user_id/unlock` 🔒

Unlock a locked user account

### `GET` `/api/v1/admin/nomic/status` 🔒

Get detailed nomic status

### `GET` `/api/v1/admin/nomic/circuit-breakers` 🔒

Get circuit breaker status

### `POST` `/api/v1/admin/nomic/reset` 🔒

Reset nomic to a specific phase

### `POST` `/api/v1/admin/nomic/pause` 🔒

Pause the nomic loop

### `POST` `/api/v1/admin/nomic/resume` 🔒

Resume the nomic loop

### `POST` `/api/v1/admin/nomic/circuit-breakers/reset` 🔒

Reset all circuit breakers

---

## ApiDocs (admin/api_docs.py)

Handler for API documentation and introspection endpoints.

### `GET` `/api/v1/docs/openapi.json` ❔

GET /api/v1/docs/openapi.json

### `GET` `/api/v1/docs/routes` ❔

Return a lightweight summary of all registered routes

### `GET` `/api/v1/docs/stats` ❔

Return API statistics: endpoint counts by tag and method

---

## Backup Handler (admin/backup_handler.py)

Backup HTTP Handlers for Aragora.

### `GET` `/api/v2/backups` 🔒

List backups with filters

### `POST` `/api/v2/backups` 🔒

Create new backup

### `GET` `/api/v2/backups/:backup_id` 🔒

Get specific backup metadata

### `DELETE` `/api/v2/backups/:backup_id` 🔒

Delete a backup

### `GET` `/api/v1/backups/cleanup` ❔

Run retention policy cleanup

### `GET` `/api/v1/backups/stats` ❔

Get backup statistics

---

## Backup Offsite Handler (admin/backup_offsite_handler.py)

Backup Offsite and Restore Drill HTTP Handlers.

### `GET` `/api/v1/backup/status` 🔒

Current backup status and last successful backup

### `GET` `/api/v1/backup/drills` 🔒

List restore drill results

### `POST` `/api/v1/backup/drill` 🔒

Trigger a manual restore drill

---

## Billing (admin/billing.py)

Billing API Handlers.

### `GET` `/api/v1/billing/plans` ❔

Get available subscription plans

### `GET` `/api/v1/billing/usage` ❔

Export usage data as CSV

### `GET` `/api/v1/billing/subscription` ❔

Cancel subscription at end of billing period

### `GET` `/api/v1/billing/checkout` ❔

Create Stripe checkout session

### `GET` `/api/v1/billing/portal` ❔

Create Stripe billing portal session

### `GET` `/api/v1/billing/cancel` ❔

Cancel subscription at end of billing period

### `GET` `/api/v1/billing/resume` ❔

Resume a canceled subscription

### `GET` `/api/v1/billing/audit-log` ❔

GET /api/v1/billing/audit-log

### `GET` `/api/v1/billing/usage/export` ❔

Export usage data as CSV

### `GET` `/api/v1/billing/usage/forecast` ❔

Get usage forecast and cost projection

### `GET` `/api/v1/billing/invoices` ❔

Get invoice history from Stripe

### `GET` `/api/v1/webhooks/stripe` ❔

Handle Stripe webhook events

---

## Credits (admin/credits.py)

Credits Admin API Handler.

### `POST` `/api/v1/admin/credits/\{org_id\}/issue` 🔒

Issue credits to organization

### `GET` `/api/v1/admin/credits/\{org_id\}` 🔒

Get credit account details

### `GET` `/api/v1/admin/credits/\{org_id\}/transactions` 🔒

List credit transactions

### `POST` `/api/v1/admin/credits/\{org_id\}/adjust` 🔒

Make balance adjustment

---

## Dashboard (admin/dashboard.py)

Handler for dashboard endpoint.

### `GET` `/api/dashboard/debates` ❔

Get consolidated debate metrics for dashboard

### `POST` `/api/v1/dashboard` ❔

Get consolidated debate metrics for dashboard

### `GET` `/api/v1/dashboard/overview` 🔒

GET /api/v1/dashboard/overview

### `GET` `/api/v1/dashboard/debates` ❔

Get consolidated debate metrics for dashboard

### `GET` `/api/v1/dashboard/stats` 🔒

GET /api/v1/dashboard/stats

### `GET` `/api/v1/dashboard/stat-cards` 🔒

GET /api/v1/dashboard/stat-cards

### `GET` `/api/v1/dashboard/team-performance` 🔒

GET /api/v1/dashboard/team-performance

### `GET` `/api/v1/dashboard/top-senders` 🔒

GET /api/v1/dashboard/top-senders

### `GET` `/api/v1/dashboard/labels` 🔒

GET /api/v1/dashboard/labels

### `GET` `/api/v1/dashboard/activity` 🔒

Get recent debate activity metrics

### `GET` `/api/v1/dashboard/inbox-summary` 🔒

GET /api/v1/dashboard/inbox-summary

### `GET` `/api/v1/dashboard/quick-actions` 🔒

GET /api/v1/dashboard/quick-actions

### `GET` `/api/v1/dashboard/urgent` 🔒

GET /api/v1/dashboard/urgent

### `GET` `/api/v1/dashboard/pending-actions` 🔒

GET /api/v1/dashboard/pending-actions

### `GET` `/api/v1/dashboard/search` 🔒

GET /api/v1/dashboard/search

### `POST` `/api/v1/dashboard/export` ❔

POST /api/v1/dashboard/export

### `GET` `/api/v1/dashboard/quality-metrics` 🔒

GET /api/v1/dashboard/quality-metrics

---

## Docs (admin/docs.py)

API documentation endpoint handlers.

### `GET` `/api/openapi` ❔

OpenAPI 3.0 JSON specification

### `GET` `/api/openapi.json` ❔

OpenAPI 3.0 JSON specification

### `GET` `/api/openapi.yaml` ❔

OpenAPI 3.0 YAML specification

### `GET` `/api/postman.json` ❔

Postman collection export

### `GET` `/api/docs` ❔

Swagger UI interactive documentation

### `GET` `/api/redoc` ❔

ReDoc API documentation viewer

### `GET` `/api/v1/openapi` ❔

Get OpenAPI specification

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `format` | string | Output format - 'json' or 'yaml' |

### `GET` `/api/v1/openapi.json` ❔

GET /api/v1/openapi.json

### `GET` `/api/v1/openapi.yaml` ❔

GET /api/v1/openapi.yaml

### `GET` `/api/v1/postman.json` ❔

GET /api/v1/postman.json

### `GET` `/api/v1/docs` ❔

GET /api/v1/docs

### `GET` `/api/v1/redoc` ❔

Serve ReDoc API documentation viewer

---

## Dr Handler (admin/dr_handler.py)

Disaster Recovery HTTP Handlers for Aragora.

### `GET` `/api/v2/dr` 🔒

Run a DR drill (simulated recovery)

### `GET` `/api/v2/dr/*` 🔒

GET /api/v2/dr/*

### `POST` `/api/v2/dr/*` 🔒

POST /api/v2/dr/*

---

## Feature Flags (admin/feature_flags.py)

Feature flag administration endpoint handlers.

### `GET` `/api/v1/admin/feature-flags` 🔒

List all flags with values, categories, statuses

### `PUT` `/api/v1/admin/feature-flags` 🔒

Update multiple flags in one request

### `GET` `/api/v1/admin/feature-flags/:name` 🔒

Get flag value + usage stats

### `PUT` `/api/v1/admin/feature-flags/:name` 🔒

Toggle/set flag value (admin RBAC)

---

## Feature Flags Read (admin/feature_flags_read.py)

Feature flags handler for reading flag values.

### `GET` `/api/v1/feature-flags` ❔

List all feature flags with current values

### `GET` `/api/v1/feature-flags/:name` 🔒

Get a specific flag value

---

## Admin (admin/handler.py)

Handler for admin endpoints.

### `GET` `/api/v1/admin/organizations` 🔒

GET /api/v1/admin/organizations

### `GET` `/api/v1/admin/users` 🔒

GET /api/v1/admin/users

### `GET` `/api/v1/admin/stats` 🔒

GET /api/v1/admin/stats

### `GET` `/api/v1/admin/system/metrics` 🔒

GET /api/v1/admin/system/metrics

### `GET` `/api/v1/admin/impersonate` ❔

GET /api/v1/admin/impersonate

### `GET` `/api/v1/admin/revenue` 🔒

GET /api/v1/admin/revenue

### `GET` `/api/v1/admin/nomic/status` 🔒

GET /api/v1/admin/nomic/status

### `GET` `/api/v1/admin/nomic/circuit-breakers` 🔒

GET /api/v1/admin/nomic/circuit-breakers

### `POST` `/api/v1/admin/nomic/reset` 🔒

POST /api/v1/admin/nomic/reset

### `POST` `/api/v1/admin/nomic/pause` 🔒

POST /api/v1/admin/nomic/pause

### `POST` `/api/v1/admin/nomic/resume` 🔒

POST /api/v1/admin/nomic/resume

### `POST` `/api/v1/admin/nomic/circuit-breakers/reset` 🔒

POST /api/v1/admin/nomic/circuit-breakers/reset

### `GET` `/api/v1/admin/circuit-breakers` ❔

GET /api/v1/admin/circuit-breakers

### `GET` `/api/v1/admin/circuit-breakers/reset` ❔

GET /api/v1/admin/circuit-breakers/reset

---

## BuildInfo (admin/health/build.py)

Handler for the /health/build endpoint.

### `GET` `/health/build` ❔

Return build SHA, time, and version

### `GET` `/api/health/build` ❔

Return build SHA, time, and version

### `GET` `/api/v1/health/build` ❔

Return build SHA, time, and version

---

## DeployStatus (admin/health/deploy_status.py)

Handler for the deploy status endpoint.

### `GET` `/api/v1/deploy/status` 🔒

Return comprehensive deploy status

---

## Liveness (admin/health/liveness.py)

Handler for the /healthz liveness probe endpoint.

### `GET` `/healthz` ❔

GET /healthz

---

## Readiness (admin/health/readiness.py)

Handler for /readyz readiness probe endpoints.

### `GET` `/readyz` ❔

GET /readyz

### `GET` `/readyz/dependencies` ❔

Full dependency validation probe

---

## StorageHealth (admin/health/storage_health.py)

Handler for storage and database health check endpoints.

### `GET` `/api/v1/health/stores` ❔

Check health of all database stores

### `GET` `/api/v1/health/database` ❔

Check health of consolidated database schema

### `GET` `/api/health/stores` ❔

Check health of all database stores

---

## Metrics Dashboard (admin/metrics_dashboard.py)

Admin Metrics Dashboard Endpoints.

### `GET` `/api/v1/admin/stats` 🔒

Get system-wide statistics

### `GET` `/api/v1/admin/system/metrics` 🔒

Get aggregated system metrics

### `GET` `/api/v1/admin/revenue` 🔒

Get revenue and billing statistics

---

## Mfa Compliance (admin/mfa_compliance.py)

MFA Compliance Dashboard endpoint handler.

### `GET` `/api/v1/admin/mfa-compliance` 🔒

Aggregate MFA status for all admin users

---

## Nomic Admin (admin/nomic_admin.py)

Admin Nomic Loop Control Endpoints.

### `GET` `/api/v1/admin/nomic/status` 🔒

Get detailed nomic status

### `GET` `/api/v1/admin/nomic/circuit-breakers` 🔒

Get circuit breaker status

### `POST` `/api/v1/admin/nomic/reset` 🔒

Reset nomic to a specific phase

### `POST` `/api/v1/admin/nomic/pause` 🔒

Pause the nomic loop

### `POST` `/api/v1/admin/nomic/resume` 🔒

Resume the nomic loop

### `POST` `/api/v1/admin/nomic/circuit-breakers/reset` 🔒

Reset all circuit breakers

---

## Rotation Status (admin/rotation_status.py)

Key Rotation Status Admin Handler.

### `GET` `/api/v1/admin/security/rotation-status` 🔒

Get rotation status for all managed secrets

### `GET` `/api/admin/security/rotation-status` 🔒

(non-versioned backward compat)

---

## Security (admin/security.py)

Security endpoint handlers.

### `GET` `/api/admin/security/status` 🔒

Get encryption and key status

### `POST` `/api/admin/security/rotate-key` ❔

Rotate encryption key

### `GET` `/api/admin/security/health` 🔒

Check encryption health

### `GET` `/api/v1/admin/security/status` 🔒

Get encryption and key status

### `POST` `/api/v1/admin/security/rotate-key` 🔒

POST /api/v1/admin/security/rotate-key

### `GET` `/api/v1/admin/security/health` 🔒

Check encryption health

### `GET` `/api/v1/admin/security/keys` 🔒

List all encryption keys

### `POST` `/api/v1/admin/security/keys` 🔒

List all encryption keys

### `GET` `/api/admin/security/keys` 🔒

List all encryption keys

### `POST` `/api/admin/security/keys` ❔

List all encryption keys

---

## System (admin/system.py)

System and utility endpoint handlers.

### `GET` `/api/history/cycles` ❔

Get cycle history

### `GET` `/api/history/events` ❔

Get event history

### `GET` `/api/history/debates` ❔

Get debate history

### `GET` `/api/history/summary` ❔

Get history summary

### `POST` `/api/debug/test` ❔

Handle debug test endpoint

### `GET` `/api/system/maintenance` 🔒

Handle system maintenance endpoint

### `POST` `/api/auth/stats` ❔

Get authentication and rate limiting statistics

### `POST` `/api/circuit-breakers` ❔

POST /api/circuit-breakers

### `POST` `/api/v1/diagnostics/handlers` ❔

POST /api/v1/diagnostics/handlers

---

## System Health (admin/system_health.py)

System Health Dashboard handler.

### `GET` `/api/admin/system-health` 🔒

Aggregated health overview

### `GET` `/api/admin/system-health/circuit-breakers` 🔒

Circuit breaker states

### `GET` `/api/admin/system-health/slos` 🔒

SLO compliance status

### `GET` `/api/admin/system-health/adapters` 🔒

KM adapter health

### `GET` `/api/admin/system-health/agents` 🔒

Agent pool health

### `GET` `/api/admin/system-health/budget` 🔒

Budget utilization

---

## System Intelligence (admin/system_intelligence.py)

System Intelligence Dashboard Handler.

### `GET` `/api/v1/system-intelligence/overview` ❔

High-level system stats

### `GET` `/api/v1/system-intelligence/agent-performance` ❔

ELO, calibration, win rates

### `GET` `/api/v1/system-intelligence/institutional-memory` ❔

Cross-debate injection stats

### `GET` `/api/v1/system-intelligence/improvement-queue` ❔

Queue contents + breakdown

### `GET` `/api/v1/system-intelligence/anomalies` ❔

Recent anomaly alerts

### `GET` `/api/v1/system-intelligence/events` ❔

Recent system events

### `GET` `/api/v1/system-intelligence/km-sync` ❔

Knowledge sync status

### `GET` `/api/v1/system-intelligence/nomic-status` ❔

Nomic loop status

### `GET` `/api/v1/system-intelligence/debate-queue` ❔

Debate activity summary

### `GET` `/api/system-intelligence/overview` ❔

High-level system intelligence overview

### `GET` `/api/system-intelligence/agent-performance` ❔

GET /api/system-intelligence/agent-performance

### `GET` `/api/system-intelligence/institutional-memory` ❔

GET /api/system-intelligence/institutional-memory

### `GET` `/api/system-intelligence/improvement-queue` ❔

GET /api/system-intelligence/improvement-queue

### `GET` `/api/system-intelligence/anomalies` ❔

Recent anomaly alerts formatted for the dashboard

### `GET` `/api/system-intelligence/events` ❔

Recent system events normalized for the dashboard timeline

### `GET` `/api/system-intelligence/km-sync` ❔

GET /api/system-intelligence/km-sync

### `GET` `/api/system-intelligence/nomic-status` ❔

GET /api/system-intelligence/nomic-status

### `GET` `/api/system-intelligence/debate-queue` ❔

GET /api/system-intelligence/debate-queue

---

## Users (admin/users.py)

Admin User and Organization Management Endpoints.

### `GET` `/api/v1/admin/organizations` 🔒

List all organizations

### `GET` `/api/v1/admin/users` 🔒

List all users

### `POST` `/api/v1/admin/impersonate/:user_id` 🔒

Create impersonation token

### `POST` `/api/v1/admin/users/:user_id/deactivate` 🔒

Deactivate a user

### `POST` `/api/v1/admin/users/:user_id/activate` 🔒

Activate a user

### `POST` `/api/v1/admin/users/:user_id/unlock` 🔒

Unlock a locked user account

---

## AgentBridge (agents/agent_bridge.py)

Expose persisted agent-bridge state and feature-gated operator writes.

### `GET` `/api/v1/agent-bridge/runs` 🔒

GET /api/v1/agent-bridge/runs

### `POST` `/api/v1/agent-bridge/runs` 🔒

POST /api/v1/agent-bridge/runs

---

## Agents (agents/agents.py)

Agent-related endpoint handlers.

### `GET` `/api/leaderboard` ❔

Get agent rankings

### `GET` `/api/rankings` ❔

Get agent rankings (alias)

### `GET` `/api/agents/local` ❔

List detected local LLM servers

### `GET` `/api/agents/local/status` ❔

Get local LLM availability status

### `GET` `/api/agent/\{name\}/profile` ❔

Get agent profile

### `GET` `/api/agent/\{name\}/history` ❔

Get agent match history

### `GET` `/api/agent/\{name\}/calibration` ❔

Get calibration scores

### `GET` `/api/agent/\{name\}/consistency` ❔

Get consistency score

### `GET` `/api/agent/\{name\}/flips` ❔

Get agent flip history

### `GET` `/api/agent/\{name\}/network` ❔

Get relationship network

### `GET` `/api/agent/\{name\}/rivals` ❔

Get top rivals

### `GET` `/api/agent/\{name\}/allies` ❔

Get top allies

### `GET` `/api/agent/\{name\}/moments` ❔

Get significant moments

### `GET` `/api/agent/\{name\}/positions` ❔

Get position history

### `GET` `/api/agent/\{name\}/metadata` ❔

Get agent metadata (model, capabilities)

### `GET` `/api/agent/compare` 🔒

Compare multiple agents

### `GET` `/api/flips/recent` ❔

Get recent flips across all agents

### `GET` `/api/flips/summary` ❔

Get flip summary for dashboard

### `GET` `/api/flips/\{flip_id\}` ❔

Get one detected flip

### `GET` `/api/matches/recent` ❔

Get recent ELO matches

### `GET` `/api/matches/\{match_id\}` ❔

Get one ELO match by its debate ID

### `GET` `/api/agents` 🔒

List all known agents

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `include_stats` | string | If True, include basic stats (ELO, match count) |

### `GET` `/api/agents/health` ❔

Get runtime health status for all agents

### `GET` `/api/agents/availability` ❔

Report agent availability based on configured secrets

### `GET` `/api/agent/*/domains` ❔

GET /api/agent/*/domains

### `GET` `/api/agent/*/performance` ❔

GET /api/agent/*/performance

### `GET` `/api/agent/*/introspect` ❔

GET /api/agent/*/introspect

### `GET` `/api/v1/leaderboard/compare` ❔

GET /api/v1/leaderboard/compare

### `GET` `/api/v1/leaderboard/domains` ❔

GET /api/v1/leaderboard/domains

### `GET` `/api/v1/leaderboard/movers` ❔

GET /api/v1/leaderboard/movers

---

## Calibration (agents/calibration.py)

Calibration endpoint handlers.

### `GET` `/api/agent/\{name\}/calibration-curve` ❔

Get calibration curve (confidence vs accuracy)

### `GET` `/api/agent/\{name\}/calibration-summary` ❔

Get calibration summary metrics

### `GET` `/api/calibration/leaderboard` ❔

Get top agents by calibration score

### `GET` `/api/agents/*/calibration-report` ❔

GET /api/agents/*/calibration-report

### `GET` `/api/calibration/visualization` ❔

Get comprehensive calibration visualization data

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `limit` | string | Maximum number of agents to include |

---

## Config (agents/config.py)

Agent configuration endpoint handlers.

### `GET` `/api/v1/agents/configs` ❔

List all available YAML agent configurations

### `GET` `/api/v1/agents/configs/reload` ❔

Reload all configurations from disk

### `GET` `/api/v1/agents/configs/search` ❔

Search configurations by expertise, capability, or tag

### `GET` `/api/v1/agents/configs/*` 🔒

GET /api/v1/agents/configs/*

### `GET` `/api/v1/agents/configs/*/create` ❔

Create an agent from a YAML configuration

---

## External Agents (agents/external_agents.py)

External Agent Gateway endpoint handlers.

### `POST` `/api/external-agents/tasks` ❔

Submit task to external agent

### `GET` `/api/external-agents/adapters` ❔

List registered adapters

### `GET` `/api/external-agents/health` ❔

Health check all adapters

---

## Feedback (agents/feedback.py)

Agent SelectionFeedbackLoop state API handler.

### `GET` `/api/v1/agents/feedback/metrics` ❔

Loop metrics summary

### `GET` `/api/v1/agents/feedback/states` ❔

Per-agent win rate, timeout rate, calibration

### `GET` `/api/v1/agents/\{name\}/feedback/domains` ❔

Domain-specific weights

---

## Feedback Hub (agents/feedback_hub.py)

Feedback Hub endpoint handlers.

### `GET` `/api/v1/feedback-hub/stats` 🔒

Routing statistics

### `GET` `/api/v1/feedback-hub/history` 🔒

Recent routing history

### `GET` `/api/feedback-hub/stats` 🔒

GET /api/v1/feedback-hub/stats -- Return routing statistics

### `GET` `/api/feedback-hub/history` 🔒

GET /api/v1/feedback-hub/history -- Return recent routing history

---

## Harnesses (agents/harnesses.py)

External harness endpoint handlers.

### `GET` `/api/v1/harnesses` 🔒

List available harnesses

### `POST` `/api/v1/harnesses` 🔒

List all available harnesses

---

## Introspection (agents/introspection.py)

Introspection endpoint handlers.

### `GET` `/api/introspection/all` ❔

Get introspection for all agents

### `GET` `/api/introspection/leaderboard` ❔

Get agents ranked by reputation

### `GET` `/api/introspection/agents` ❔

List available agents

### `GET` `/api/introspection/agents/\{name\}` ❔

Get introspection for specific agent

### `GET` `/api/introspection/agents/availability` ❔

Return credential availability for known agent types

---

## Laboratory (agents/laboratory.py)

Persona laboratory endpoint handlers.

### `GET` `/api/laboratory/emergent-traits` ❔

Get emergent traits from agent performance

### `GET` `/api/v1/laboratory/emergent-traits` ❔

GET /api/v1/laboratory/emergent-traits

### `POST` `/api/v1/laboratory/cross-pollinations` ❔

POST /api/v1/laboratory/cross-pollinations

### `GET` `/api/v1/laboratory/cross-pollinations/suggest` ❔

Suggest beneficial trait transfers for a target agent

### `POST` `/api/v1/laboratory/experiments` ❔

POST /api/v1/laboratory/experiments

---

## LeaderboardView (agents/leaderboard.py)

Handler for consolidated leaderboard view endpoint.

### `GET` `/api/leaderboard-view` ❔

GET /api/leaderboard-view

---

## MatchesStats (agents/matches_stats.py)

Handler for aggregate match statistics.

### `GET` `/api/matches/stats` ❔

GET /api/matches/stats

---

## Persona (agents/persona.py)

Persona-related endpoint handlers.

### `GET` `/api/personas` ❔

Get all agent personas

### `GET` `/api/agent/\{name\}/persona` ❔

Get agent persona

### `GET` `/api/agent/\{name\}/grounded-persona` ❔

Get truth-grounded persona

### `GET` `/api/agent/\{name\}/identity-prompt` 🔒

Get identity prompt

### `GET` `/api/agent/\{name\}/performance` ❔

Get agent performance summary

### `GET` `/api/agent/\{name\}/domains` ❔

Get agent expertise domains

### `GET` `/api/agent/\{name\}/accuracy` ❔

Get position accuracy stats

### `GET` `/api/personas/options` ❔

Get available traits and expertise domains for persona creation

### `PUT` `/api/agent/*/persona` ❔

Create a new agent persona

### `DELETE` `/api/agent/*/persona` ❔

Create a new agent persona

---

## Probes (agents/probes.py)

Capability probing endpoint handlers.

### `POST` `/api/probes/capability` 🔒

Run capability probes on an agent to find vulnerabilities

### `POST` `/api/v1/probes/capability` 🔒

Run capability probes on an agent to find vulnerabilities

### `POST` `/api/v1/probes/run` ❔

Run capability probes on an agent to find vulnerabilities

### `POST` `/api/v1/probes/reports` ❔

GET /api/probes/reports - List all stored probe reports

---

## AgentRecommendation (agents/recommendations.py)

Handler for agent recommendation and leaderboard endpoints.

### `GET` `/api/v1/agents/recommend` ❔

Get top agent recommendations for a domain

### `GET` `/api/v1/agents/leaderboard` ❔

Get agent leaderboard with optional domain filter

---

## Routing (agents/routing.py)

Agent routing and team selection endpoint handlers.

### `GET` `/api/routing/best-teams` ❔

Get best-performing team combinations

### `POST` `/api/routing/recommendations` ❔

Get agent recommendations for a task

### `POST` `/api/routing/auto-route` ❔

Auto-route task with domain detection

### `POST` `/api/routing/detect-domain` ❔

Detect domain from task text

### `POST` `/api/routing/domain-leaderboard` ❔

POST /api/routing/domain-leaderboard

---

## Selection (agents/selection.py)

Handler for selection plugin endpoints.

### `POST` `/api/v1/selection/plugins` ❔

List all available selection plugins

### `POST` `/api/v1/selection/defaults` ❔

Get default plugin configuration

### `POST` `/api/v1/selection/scorers` ❔

List available scorer plugins

### `POST` `/api/v1/selection/team-selectors` ❔

POST /api/v1/selection/team-selectors

### `POST` `/api/v1/selection/role-assigners` ❔

POST /api/v1/selection/role-assigners

### `POST` `/api/v1/selection/score` ❔

Get information about a specific scorer

### `POST` `/api/v1/selection/team` ❔

Get information about a specific team selector

### `POST` `/api/v1/team-selection` ❔

POST /api/v1/team-selection

### `POST` `/api/v1/agent-selection/plugins` ❔

List all available selection plugins

### `POST` `/api/v1/agent-selection/defaults` ❔

Get default plugin configuration

### `POST` `/api/v1/agent-selection/score` ❔

Get information about a specific scorer

### `POST` `/api/v1/agent-selection/best` ❔

POST /api/v1/agent-selection/best

### `POST` `/api/v1/agent-selection/select-team` ❔

POST /api/v1/agent-selection/select-team

### `POST` `/api/v1/agent-selection/assign-roles` ❔

POST /api/v1/agent-selection/assign-roles

### `POST` `/api/v1/agent-selection/history` ❔

Get agent selection history

---

## Verticals (agents/verticals.py)

Vertical specialist endpoint handlers.

### `GET` `/api/verticals` ❔

List available verticals

### `GET` `/api/verticals/:id` ❔

Get vertical config

### `GET` `/api/verticals/:id/tools` ❔

Get vertical tools

### `GET` `/api/verticals/:id/compliance` ❔

Get compliance frameworks

### `GET` `/api/verticals/suggest` ❔

Suggest vertical for a task

### `PUT` `/api/verticals/*` 🔒

PUT /api/verticals/*

### `GET` `/api/verticals/*/config` ❔

Update configuration for a vertical

### `GET` `/api/verticals/*/debate` ❔

Create a debate using a vertical specialist

### `GET` `/api/verticals/*/agent` ❔

Create a specialist agent instance

### `GET` `/api/v1/verticals` ❔

List all available verticals

### `GET` `/api/v1/verticals/suggest` ❔

Suggest the best vertical for a task description

---

## AnalyticsPerformance (analytics/analytics_performance.py)

Handler for analytics performance endpoints.

### `GET` `/api/analytics/agents/performance` ❔

Get aggregate agent performance metrics

### `GET` `/api/analytics/debates/summary` ❔

Get debate summary statistics

### `GET` `/api/analytics/trends` ❔

Calculate trend analysis from data points

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `data_points` | string | List of period data points |

---

## DecisionAnalytics (analytics/decision_analytics.py)

Handler for decision outcome analytics API endpoints.

### `GET` `/api/v1/decision-analytics/overview` 🔒

GET /api/v1/decision-analytics/overview

### `GET` `/api/v1/decision-analytics/trends` 🔒

GET /api/v1/decision-analytics/trends

### `GET` `/api/v1/decision-analytics/outcomes` 🔒

GET /api/v1/decision-analytics/outcomes

### `GET` `/api/v1/decision-analytics/agents` 🔒

GET /api/v1/decision-analytics/agents

### `GET` `/api/v1/decision-analytics/domains` 🔒

GET /api/v1/decision-analytics/domains

---

## ModerationAnalytics (analytics/moderation_analytics.py)

Handler for moderation analytics dashboard endpoints.

### `GET` `/api/v1/moderation/stats` ❔

Return moderation statistics

### `GET` `/api/v1/moderation/queue` ❔

Return pending review items

---

## OutcomeAnalytics (analytics/outcome_analytics.py)

Handler for decision outcome analytics endpoints.

### `GET` `/api/analytics/outcomes` ❔

GET /api/analytics/outcomes/average-rounds

### `GET` `/api/analytics/outcomes/consensus-rate` ❔

GET /api/analytics/outcomes/consensus-rate

### `GET` `/api/analytics/outcomes/average-rounds` ❔

GET /api/analytics/outcomes/average-rounds

### `GET` `/api/analytics/outcomes/contributions` ❔

GET /api/analytics/outcomes/contributions

### `GET` `/api/analytics/outcomes/quality-trend` ❔

GET /api/analytics/outcomes/quality-trend

### `GET` `/api/analytics/outcomes/topics` ❔

GET /api/analytics/outcomes/topics

---

## SpendAnalytics (analytics/spend_analytics.py)

Handler for spend analytics endpoints.

### `GET` `/api/v1/spend/analytics` ❔

GET /api/v1/spend/analytics/anomalies

### `GET` `/api/v1/spend/analytics/trend` ❔

GET /api/v1/spend/analytics/trend

### `GET` `/api/v1/spend/analytics/provider` ❔

GET /api/v1/spend/analytics/provider

### `GET` `/api/v1/spend/analytics/agent` ❔

GET /api/v1/spend/analytics/agent

### `GET` `/api/v1/spend/analytics/forecast` ❔

GET /api/v1/spend/analytics/forecast

### `GET` `/api/v1/spend/analytics/anomalies` ❔

GET /api/v1/spend/analytics/anomalies

---

## Agent Evolution Dashboard (analytics_dashboard/agent_evolution_dashboard.py)

Agent Evolution Dashboard API Handler.

### `GET` `/api/v1/agent-evolution/timeline` ❔

Evolution events timeline

### `GET` `/api/v1/agent-evolution/elo-trends` ❔

ELO score history per agent

### `GET` `/api/v1/agent-evolution/pending` ❔

Pending Nomic Loop changes

### `POST` `/api/v1/agent-evolution/pending/\{id\}/approve` ❔

Approve a pending change

### `POST` `/api/v1/agent-evolution/pending/\{id\}/reject` ❔

Reject a pending change

---

## Dashboard (analytics_dashboard/dashboard.py)

HTTP API Handlers for Dashboard.

### `GET` `/api/v1/dashboard/stats` 🔒

Get detailed stats

### `GET` `/api/v1/dashboard/activity` 🔒

Get recent activity

### `GET` `/api/v1/dashboard/inbox-summary` 🔒

Get inbox summary

### `GET` `/api/v1/dashboard/quick-actions` 🔒

Get available quick actions

### `POST` `/api/v1/dashboard/quick-actions/\{action\}` 🔒

Execute quick action

---

## Differentiation (analytics_dashboard/differentiation.py)

Differentiation Dashboard Handler.

### `GET` `/api/v1/differentiation/summary` ❔

Top-level differentiation metrics

### `GET` `/api/v1/differentiation/vetting` ❔

Adversarial vetting evidence

### `GET` `/api/v1/differentiation/calibration` ❔

Multi-agent calibration advantage

### `GET` `/api/v1/differentiation/memory` ❔

Institutional memory growth

### `GET` `/api/v1/differentiation/benchmarks` ❔

Industry benchmark comparison

### `GET` `/api/differentiation/summary` ❔

Top-level metrics showing Aragora's differentiation

### `GET` `/api/differentiation/vetting` ❔

Adversarial vetting evidence from decision receipts

### `GET` `/api/differentiation/calibration` ❔

Multi-agent calibration advantage data

### `GET` `/api/differentiation/memory` ❔

Institutional memory growth metrics

### `GET` `/api/differentiation/benchmarks` ❔

Industry benchmark comparison

---

## AnalyticsDashboard (analytics_dashboard/handler.py)

Handler for analytics dashboard endpoints.

### `GET` `/api/analytics/summary` ❔

GET /api/analytics/summary

### `GET` `/api/analytics/trends/findings` ❔

GET /api/analytics/trends/findings

### `GET` `/api/analytics/remediation` ❔

GET /api/analytics/remediation

### `GET` `/api/analytics/agents` ❔

GET /api/analytics/agents

### `GET` `/api/analytics/cost` ❔

GET /api/analytics/cost

### `GET` `/api/analytics/compliance` ❔

GET /api/analytics/compliance

### `GET` `/api/analytics/heatmap` ❔

GET /api/analytics/heatmap

### `GET` `/api/analytics/tokens` ❔

GET /api/analytics/tokens

### `GET` `/api/analytics/tokens/trends` ❔

GET /api/analytics/tokens/trends

### `GET` `/api/analytics/tokens/providers` ❔

GET /api/analytics/tokens/providers

### `GET` `/api/analytics/cost/breakdown` ❔

GET /api/analytics/cost/breakdown

### `GET` `/api/analytics/flips/summary` ❔

GET /api/analytics/flips/summary

### `GET` `/api/analytics/flips/recent` ❔

GET /api/analytics/flips/recent

### `GET` `/api/analytics/flips/consistency` ❔

GET /api/analytics/flips/consistency

### `GET` `/api/analytics/flips/trends` ❔

GET /api/analytics/flips/trends

### `GET` `/api/analytics/deliberations` ❔

GET /api/analytics/deliberations

### `GET` `/api/analytics/deliberations/channels` ❔

GET /api/analytics/deliberations/channels

### `GET` `/api/analytics/deliberations/consensus` ❔

GET /api/analytics/deliberations/consensus

### `GET` `/api/analytics/deliberations/performance` ❔

GET /api/analytics/deliberations/performance

---

## Outcome Dashboard (analytics_dashboard/outcome_dashboard.py)

Decision Outcome Dashboard API Handler.

### `GET` `/api/v1/outcome-dashboard` ❔

Full dashboard data

### `GET` `/api/v1/outcome-dashboard/quality` ❔

Decision quality score + trend

### `GET` `/api/v1/outcome-dashboard/agents` ❔

Agent leaderboard (ELO + Brier)

### `GET` `/api/v1/outcome-dashboard/history` ❔

Decision history with scores

### `GET` `/api/v1/outcome-dashboard/calibration` ❔

Calibration curve data

---

## Handler (auth/handler.py)

User Authentication Handler.

### `POST` `/api/auth/register` ❔

Create a new user account

### `POST` `/api/auth/login` ❔

Authenticate and get tokens

### `POST` `/api/auth/logout` 🔒

Invalidate current token (adds to blacklist)

### `POST` `/api/auth/logout-all` 🔒

Invalidate all tokens for user (logout all devices)

### `POST` `/api/auth/refresh` ❔

Refresh access token (revokes old refresh token)

### `POST` `/api/auth/revoke` 🔒

Explicitly revoke a specific token

### `GET` `/api/auth/me` 🔒

Get current user information

### `PUT` `/api/auth/me` 🔒

Update current user information

### `POST` `/api/auth/password` 🔒

Change password

### `POST` `/api/auth/api-key` 🔒

Generate API key

### `DELETE` `/api/auth/api-key` 🔒

Revoke API key

### `GET` `/api/v1/api-keys` 🔒

List API keys (alias)

### `POST` `/api/v1/api-keys` 🔒

Generate API key (alias)

### `DELETE` `/api/v1/api-keys/:prefix` 🔒

Revoke API key by prefix (alias)

### `POST` `/api/auth/mfa`

Compatibility MFA action endpoint

### `GET` `/api/auth/sessions` 🔒

List active sessions for current user

### `DELETE` `/api/auth/sessions/:id` 🔒

Revoke a specific session

### `GET` `/api/auth/password/change` ❔

Change user password

### `POST` `/api/auth/password/change` 🔒

Change user password

### `GET` `/api/auth/password/forgot` ❔

Handle forgot password request

### `POST` `/api/auth/password/forgot` 🔒

Handle forgot password request

### `GET` `/api/auth/password/reset` ❔

Handle password reset with token

### `POST` `/api/auth/password/reset` 🔒

Handle password reset with token

### `POST` `/api/auth/forgot-password` ❔

POST /api/auth/forgot-password

### `POST` `/api/auth/reset-password`

POST /api/auth/reset-password

### `GET` `/api/auth/profile` ❔

GET /api/auth/profile

### `GET` `/api/auth/api-keys` 🔒

GET /api/auth/api-keys

### `POST` `/api/auth/api-keys` 🔒

POST /api/auth/api-keys

### `DELETE` `/api/auth/api-keys` 🔒

DELETE /api/auth/api-keys

### `DELETE` `/api/auth/api-keys/*` 🔒

DELETE /api/auth/api-keys/*

### `POST` `/api/auth/mfa/setup` 🔒

Generate MFA secret and provisioning URI for setup

### `POST` `/api/auth/mfa/enable` 🔒

Enable MFA after verifying setup code

### `POST` `/api/auth/mfa/disable` 🔒

Disable MFA for the user

### `POST` `/api/auth/mfa/verify` ❔

Verify MFA code during login

### `POST` `/api/auth/mfa/backup-codes` 🔒

POST /api/auth/mfa/backup-codes

### `GET` `/api/admin/mfa/compliance` 🔒

Return admin MFA compliance report

### `GET` `/api/auth/sessions/health` ❔

Lightweight diagnostic endpoint - no auth or DB required

### `GET` `/api/auth/sessions/sweep` ❔

GET /api/auth/sessions/sweep

### `GET` `/api/auth/sessions/active` ❔

GET /api/auth/sessions/active

### `POST` `/api/auth/verify-email`

POST /api/auth/verify-email

### `POST` `/api/auth/verify-email/resend`

POST /api/auth/verify-email/resend

### `POST` `/api/auth/resend-verification`

POST /api/auth/resend-verification

### `POST` `/api/auth/setup-organization`

POST /api/auth/setup-organization

### `POST` `/api/auth/invite` 🔒

POST /api/auth/invite

### `GET` `/api/auth/check-invite` ❔

GET /api/auth/check-invite

### `POST` `/api/auth/accept-invite`

POST /api/auth/accept-invite

### `GET` `/api/onboarding/status` ❔

GET /api/onboarding/status

### `GET` `/api/onboarding/complete` ❔

GET /api/onboarding/complete

### `GET` `/api/auth/health` ❔

Lightweight diagnostic endpoint - no auth or DB required

### `GET` `/api/keys` ❔

List API keys for the current user

### `GET` `/api/api-keys` 🔒

GET /api/api-keys

### `POST` `/api/api-keys` 🔒

POST /api/api-keys

### `DELETE` `/api/api-keys` 🔒

DELETE /api/api-keys

### `DELETE` `/api/api-keys/*` 🔒

DELETE /api/api-keys/*

---

## RBAC (auth/rbac.py)

HTTP handler for RBAC management endpoints.

### `GET` `/api/v1/rbac/permissions` ❔

List all system permissions with optional filtering

### `GET` `/api/v1/rbac/permissions/*` 🔒

GET /api/v1/rbac/permissions/*

### `GET` `/api/v1/rbac/roles` ❔

List all roles (system and custom)

### `GET` `/api/v1/rbac/roles/*` 🔒

GET /api/v1/rbac/roles/*

### `GET` `/api/v1/rbac/assignments` ❔

List role assignments with optional filtering

### `GET` `/api/v1/rbac/assignments/*` 🔒

GET /api/v1/rbac/assignments/*

### `GET` `/api/v1/rbac/check` ❔

Check if a user has a specific permission

---

## SCIM (auth/scim_handler.py)

HTTP request handler for SCIM 2.0 provisioning endpoints.

### `GET` `/scim/v2/Users` ❔

Extract resource ID from path like /scim/v2/Users/\{id\}

### `POST` `/scim/v2/Users` ❔

Extract resource ID from path like /scim/v2/Users/\{id\}

### `GET` `/scim/v2/Users/*` 🔒

GET /scim/v2/Users/*

### `PUT` `/scim/v2/Users/*` 🔒

PUT /scim/v2/Users/*

### `PATCH` `/scim/v2/Users/*` 🔒

PATCH /scim/v2/Users/*

### `DELETE` `/scim/v2/Users/*` 🔒

DELETE /scim/v2/Users/*

### `GET` `/scim/v2/Groups` ❔

GET /scim/v2/Groups

### `POST` `/scim/v2/Groups` ❔

POST /scim/v2/Groups

### `GET` `/scim/v2/Groups/*` 🔒

GET /scim/v2/Groups/*

### `PUT` `/scim/v2/Groups/*` 🔒

PUT /scim/v2/Groups/*

### `PATCH` `/scim/v2/Groups/*` 🔒

PATCH /scim/v2/Groups/*

### `DELETE` `/scim/v2/Groups/*` 🔒

DELETE /scim/v2/Groups/*

---

## Signup Handlers (auth/signup_handlers.py)

HTTP API Handlers for Self-Service Signup.

### `POST` `/api/v1/auth/verify-email`

Verify email address

### `POST` `/api/v1/auth/resend-verification`

Resend verification email

### `POST` `/api/v1/auth/setup-organization`

Create organization after signup

### `POST` `/api/v1/auth/invite` 🔒

Invite team member

### `POST` `/api/v1/auth/accept-invite`

Accept team invitation

### `GET` `/api/v1/auth/check-invite` ❔

Check invitation validity

---

## SSO (auth/sso.py)

Handler for SSO (Single Sign-On) endpoints.

### `GET` `/auth/sso/login` ❔

GET /auth/sso/login

### `POST` `/auth/sso/login` 🔒

POST /auth/sso/login

### `GET` `/auth/sso/callback` ❔

GET /auth/sso/callback

### `POST` `/auth/sso/callback` 🔒

POST /auth/sso/callback

### `GET` `/auth/sso/logout` ❔

GET /auth/sso/logout

### `POST` `/auth/sso/logout` 🔒

POST /auth/sso/logout

### `GET` `/auth/sso/metadata` ❔

GET /auth/sso/metadata

### `GET` `/auth/sso/status` ❔

GET /auth/sso/status

### `GET` `/api/v2/sso/login` ❔

GET /api/v2/sso/login

### `POST` `/api/v2/sso/login` 🔒

POST /api/v2/sso/login

### `GET` `/api/v2/sso/callback` ❔

GET /api/v2/sso/callback

### `POST` `/api/v2/sso/callback` 🔒

POST /api/v2/sso/callback

### `GET` `/api/v2/sso/logout` ❔

GET /api/v2/sso/logout

### `POST` `/api/v2/sso/logout` 🔒

POST /api/v2/sso/logout

### `GET` `/api/v2/sso/status` ❔

GET /api/v2/sso/status

### `GET` `/api/v2/sso/metadata` ❔

GET /api/v2/sso/metadata

---

## Autonomous Learning (autonomous/autonomous_learning.py)

Autonomous Learning Handler for Aragora.

### `POST` `/api/v2/learning/sessions` ❔

Start new training session

### `GET` `/api/v2/learning/sessions/:session_id` 🔒

Get session details

### `GET` `/api/v2/learning/metrics/:metric_type` 🔒

Get specific metric

### `POST` `/api/v2/learning/feedback` ❔

Submit learning feedback

### `POST` `/api/v2/learning/calibrate` ❔

Trigger calibration

### `POST` `/api/v2/learning/metrics` ❔

Get learning metrics with filtering

### `POST` `/api/v2/learning/patterns` ❔

List detected patterns with filtering

### `GET` `/api/v2/learning/patterns/*` 🔒

GET /api/v2/learning/patterns/*

### `POST` `/api/v2/learning/knowledge` ❔

Trigger knowledge extraction from debates

### `GET` `/api/v2/learning/knowledge/*` 🔒

GET /api/v2/learning/knowledge/*

### `POST` `/api/v2/learning/recommendations` ❔

Get learning recommendations

### `POST` `/api/v2/learning/performance` ❔

Get model performance statistics

### `POST` `/api/v1/learning/knowledge/extract` ❔

Trigger knowledge extraction from debates

---

## Gastown Dashboard (autonomous/gastown_dashboard.py)

Gas Town Dashboard API Handlers.

### `GET` `/api/v1/dashboard/gastown/overview` ❔

Get Gas Town overview

### `GET` `/api/v1/dashboard/gastown/convoys` ❔

Get convoy list with progress

### `GET` `/api/v1/dashboard/gastown/agents` ❔

Get agent workload distribution

### `GET` `/api/v1/dashboard/gastown/beads` ❔

Get bead queue stats

### `GET` `/api/v1/dashboard/gastown/metrics` ❔

Get throughput metrics

---

## Monitoring (autonomous/monitoring.py)

HTTP handlers for monitoring operations.

### `GET` `/api/v1/autonomous/monitoring/record` ❔

GET /api/v1/autonomous/monitoring/record

### `GET` `/api/v1/autonomous/monitoring/trends` ❔

GET /api/v1/autonomous/monitoring/trends

### `GET` `/api/v1/autonomous/monitoring/trends/*` 🔒

GET /api/v1/autonomous/monitoring/trends/*

### `GET` `/api/v1/autonomous/monitoring/anomalies` ❔

GET /api/v1/autonomous/monitoring/anomalies

### `GET` `/api/v1/autonomous/monitoring/baseline` ❔

GET /api/v1/autonomous/monitoring/baseline

### `GET` `/api/v1/autonomous/monitoring/baseline/*` 🔒

GET /api/v1/autonomous/monitoring/baseline/*

### `GET` `/api/v1/autonomous/monitoring/circuit-breaker` ❔

GET /api/v1/autonomous/monitoring/circuit-breaker

---

## Nomic (autonomous/nomic.py)

Nomic loop state and monitoring endpoint handlers.

### `GET` `/api/nomic/state` ❔

Get nomic loop state

### `GET` `/api/nomic/health` ❔

Get nomic loop health with stall detection

### `GET` `/api/nomic/metrics` 🔒

Get nomic loop Prometheus metrics summary

### `GET` `/api/nomic/log` 🔒

Get nomic loop logs

### `GET` `/api/nomic/risk-register` 🔒

Get risk register entries

### `GET` `/api/nomic/witness/status` 🔒

Get Gas Town witness patrol status

### `GET` `/api/nomic/mayor/current` 🔒

Get current Gas Town mayor information

### `GET` `/api/modes` ❔

Get available operational modes

### `POST` `/api/nomic/control/start` 🔒

Start the nomic loop with optional configuration

### `POST` `/api/nomic/control/stop` 🔒

Stop the running nomic loop

### `POST` `/api/nomic/control/pause` 🔒

Pause the nomic loop at current phase

### `POST` `/api/nomic/control/resume` 🔒

Resume a paused nomic loop

### `POST` `/api/nomic/control/skip-phase` 🔒

POST /api/nomic/control/skip-phase

### `GET` `/api/nomic/proposals` 🔒

Get pending improvement proposals

### `POST` `/api/nomic/proposals/approve` ❔

Approve a pending proposal

### `POST` `/api/nomic/proposals/reject` ❔

Reject a pending proposal

---

## RalphDashboard (autonomous/ralph_dashboard.py)

Handler for Ralph campaign dashboard endpoints.

### `GET` `/api/ralph/campaigns` 🔒

GET /api/ralph/campaigns

### `GET` `/api/ralph/campaigns/\{campaign_id\}` 🔒

GET /api/ralph/campaigns/\{campaign_id\}

### `GET` `/api/ralph/campaigns/\{campaign_id\}/timeline` 🔒

GET /api/ralph/campaigns/\{campaign_id\}/timeline

### `GET` `/api/ralph/campaigns/\{campaign_id\}/blockers` 🔒

GET /api/ralph/campaigns/\{campaign_id\}/blockers

### `GET` `/api/ralph/campaigns/\{campaign_id\}/repairs` 🔒

GET /api/ralph/campaigns/\{campaign_id\}/repairs

### `GET` `/api/ralph/campaigns/\{campaign_id\}/budget` 🔒

GET /api/ralph/campaigns/\{campaign_id\}/budget

### `GET` `/api/ralph/campaigns/\{campaign_id\}/pr-gate` 🔒

GET /api/ralph/campaigns/\{campaign_id\}/pr-gate

### `GET` `/api/ralph/overview` 🔒

GET /api/ralph/overview

### `GET` `/api/ralph/blockers` 🔒

GET /api/ralph/blockers

---

## Self Improve (autonomous/self_improve.py)

Self-improvement run management endpoints.

### `POST` `/api/self-improve/run` ❔

Start a new self-improvement cycle

### `POST` `/api/self-improve/start` ❔

Start a new run (legacy alias)

### `POST` `/api/self-improve/runs/:id/cancel` ❔

Cancel a running run

### `POST` `/api/self-improve/coordinate` ❔

Start a hierarchical coordination cycle

### `POST` `/api/self-improve/worktrees/cleanup` ❔

Clean up all worktrees

### `POST` `/api/self-improve/worktrees/autopilot/ensure` ❔

Ensure managed autopilot worktree

### `POST` `/api/self-improve/worktrees/autopilot/reconcile` ❔

Reconcile managed autopilot sessions

### `POST` `/api/self-improve/worktrees/autopilot/cleanup` ❔

Cleanup managed autopilot sessions

### `POST` `/api/self-improve/worktrees/autopilot/maintain` ❔

Run autopilot maintain lifecycle

### `POST` `/api/self-improve/status` ❔

Get current self-improvement cycle status

### `POST` `/api/self-improve/runs` ❔

List self-improvement runs with pagination

### `POST` `/api/self-improve/history` ❔

Get regression history from NomicOutcomeTracker

### `POST` `/api/self-improve/worktrees` ❔

Clean up all managed worktrees

### `POST` `/api/self-improve/worktrees/autopilot/status` ❔

Get current self-improvement cycle status

### `POST` `/api/self-improve/feedback` ❔

Get feedback loop state: regressions, adjustments, metrics

### `POST` `/api/self-improve/feedback-summary` ❔

POST /api/self-improve/feedback-summary

### `POST` `/api/self-improve/regression-history` ❔

POST /api/self-improve/regression-history

### `POST` `/api/self-improve/goals` ❔

POST /api/self-improve/goals

### `POST` `/api/self-improve/metrics/summary` ❔

Collect autopilot worktree status summary for metrics consumers

---

## Self Improve Details (autonomous/self_improve_details.py)

Self-improvement transparency dashboard endpoints.

### `GET` `/api/self-improve/meta-planner/goals` 🔒

MetaPlanner prioritized goals

### `GET` `/api/self-improve/execution/timeline` 🔒

Branch execution timeline

### `GET` `/api/self-improve/learning/insights` 🔒

Cross-cycle learning data

### `GET` `/api/self-improve/metrics/comparison` 🔒

Before/after codebase metrics

### `POST` `/api/self-improve/improvement-queue` 🔒

User-submitted improvement goals

### `PUT` `/api/self-improve/improvement-queue/\{id\}/priority` 🔒

Reorder queue items

### `DELETE` `/api/self-improve/improvement-queue/\{id\}` 🔒

Remove queue items

### `GET` `/api/self-improve/trends/cycles` 🔒

GET /api/self-improve/trends/cycles

---

## Budgets (billing/budgets.py)

Budget Management API Handler.

### `GET` `/api/v1/budgets` 🔒

List budgets for org

### `POST` `/api/v1/budgets` 🔒

Create a budget

### `GET` `/api/v1/budgets/:id` 🔒

Get budget details

### `PATCH` `/api/v1/budgets/:id` 🔒

Update a budget

### `DELETE` `/api/v1/budgets/:id` 🔒

Delete (close) a budget

### `GET` `/api/v1/budgets/:id/alerts` 🔒

Get alerts for a budget

### `POST` `/api/v1/budgets/:id/alerts/:alert_id/acknowledge` 🔒

Acknowledge alert

### `POST` `/api/v1/budgets/:id/override` 🔒

Add override for user

### `DELETE` `/api/v1/budgets/:id/override/:user_id` 🔒

Remove override

### `POST` `/api/v1/budgets/:id/reset` 🔒

Reset budget period

### `GET` `/api/v1/budgets/summary` 🔒

Get org budget summary

### `GET` `/api/v1/budgets/trends` ❔

Get org-wide spending trends

### `POST` `/api/v1/budgets/check` 🔒

Pre-flight cost check

### `GET` `/api/v1/costs/agents` ❔

GET /api/v1/costs/agents

### `GET` `/api/v1/costs/anomalies` ❔

Get recent cost anomalies with advisory

---

## Core (billing/core.py)

Billing API Handlers - Core Module.

### `GET` `/api/v1/billing/plans` ❔

Get available subscription plans

### `GET` `/api/v1/billing/usage` ❔

Get usage for authenticated user

### `GET` `/api/v1/billing/subscription` ❔

Cancel subscription at end of billing period

### `GET` `/api/v1/billing/trial` ❔

Get trial status for the organization

### `GET` `/api/v1/billing/trial/start` ❔

Start a free trial for a new organization

### `GET` `/api/v1/billing/checkout` ❔

Create Stripe checkout session

### `GET` `/api/v1/billing/portal` ❔

Create Stripe billing portal session

### `GET` `/api/v1/billing/cancel` ❔

Cancel subscription at end of billing period

### `GET` `/api/v1/billing/resume` ❔

Resume a canceled subscription

### `GET` `/api/v1/billing/audit-log` ❔

GET /api/v1/billing/audit-log

### `GET` `/api/v1/billing/usage/export` ❔

GET /api/v1/billing/usage/export

### `GET` `/api/v1/billing/usage/forecast` ❔

GET /api/v1/billing/usage/forecast

### `GET` `/api/v1/billing/invoices` ❔

GET /api/v1/billing/invoices

### `GET` `/api/v1/webhooks/stripe` ❔

GET /api/v1/webhooks/stripe

---

## CostDashboard (billing/cost_dashboard.py)

Handler for the consolidated cost dashboard endpoint.

### `GET` `/api/v1/billing/dashboard` ❔

Get the consolidated cost dashboard summary

---

## UsageMetering (billing/subscriptions.py)

Handler for usage metering endpoints.

### `GET` `/api/v1/billing/usage` ❔

Export usage data as CSV

### `GET` `/api/v1/billing/usage/breakdown` ❔

Get detailed usage breakdown for billing

### `GET` `/api/v1/billing/limits` ❔

Get current usage limits and utilization percentages

### `GET` `/api/v1/billing/usage/summary` ❔

GET /api/v1/billing/usage/summary

### `GET` `/api/v1/billing/usage/export` ❔

Export usage data as CSV

### `GET` `/api/v1/quotas` ❔

GET /api/v1/quotas

---

## UsageMetering (billing/usage_metering.py)

Handler for usage metering endpoints.

### `GET` `/api/v1/billing/usage` ❔

Export usage data as CSV

### `GET` `/api/v1/billing/usage/breakdown` ❔

Get detailed usage breakdown for billing

### `GET` `/api/v1/billing/usage/summary` ❔

GET /api/v1/billing/usage/summary

### `GET` `/api/v1/billing/usage/export` ❔

Export usage data as CSV

### `GET` `/api/v1/billing/limits` ❔

Get current usage limits and utilization percentages

### `GET` `/api/v1/quotas` ❔

GET /api/v1/quotas

### `GET` `/api/v1/quotas/usage` ❔

Export usage data as CSV

---

## Discord (bots/discord.py)

Discord Interactions endpoint handler.

### `POST` `/api/v1/bots/discord/interactions` ❔

Handle Discord interaction webhooks

### `GET` `/api/v1/bots/discord/status` 🔒

Return Discord-specific config fields for status response

---

## Email Webhook (bots/email_webhook.py)

Email Webhook Handler for Inbound Email Processing.

### `POST` `/api/v1/bots/email/webhook/sendgrid` ❔

SendGrid Inbound Parse

### `POST` `/api/v1/bots/email/webhook/mailgun` 🔒

Mailgun Inbound Webhook

### `POST` `/api/v1/bots/email/webhook/ses` ❔

AWS SES SNS notifications

### `GET` `/api/v1/bots/email/status` 🔒

Integration status

---

## Google Chat (bots/google_chat.py)

Google Chat Bot webhook handler.

### `POST` `/api/v1/bots/google-chat/webhook` ❔

Handle Google Chat webhook events

### `GET` `/api/v1/bots/google-chat/status` 🔒

Build Google Chat-specific status response

---

## Slack (bots/slack/handler.py)

Handler for Slack bot integration endpoints.

### `GET` `/api/v1/bots/slack/status` 🔒

Return system status for Slack

### `POST` `/api/v1/bots/slack/events` ❔

POST /api/v1/bots/slack/events

### `POST` `/api/v1/bots/slack/interactions` ❔

POST /api/v1/bots/slack/interactions

### `POST` `/api/v1/bots/slack/commands` ❔

POST /api/v1/bots/slack/commands

---

## Handler (bots/teams/handler.py)

Microsoft Teams Bot main handler.

### `POST` `/api/v1/bots/teams/messages` ❔

Handle incoming Bot Framework activities

### `GET` `/api/v1/bots/teams/status` ❔

Bot status

### `POST` `/api/v1/teams` ❔

POST /api/v1/teams

### `POST` `/api/v1/teams/debates/send` ❔

POST /api/v1/teams/debates/send

---

## Telegram (bots/telegram.py)

Telegram Bot webhook handler.

### `POST` `/api/v1/bots/telegram/webhook` ❔

Handle Telegram webhook updates

### `GET` `/api/v1/bots/telegram/status` 🔒

Handle /status command

---

## Whatsapp (bots/whatsapp.py)

WhatsApp Business webhook handler.

### `GET` `/api/v1/bots/whatsapp/webhook` ❔

Handle WhatsApp webhook messages

### `POST` `/api/v1/bots/whatsapp/webhook` ❔

Handle WhatsApp webhook messages

### `GET` `/api/v1/bots/whatsapp/status` 🔒

Return WhatsApp-specific config fields for status response

---

## Zoom (bots/zoom.py)

Zoom Bot endpoint handler.

### `POST` `/api/v1/bots/zoom/events` ❔

Handle incoming Zoom webhook events

### `GET` `/api/v1/bots/zoom/status` 🔒

Return Zoom-specific config fields for status response

---

## IdeaCanvas (canvas/idea_canvas.py)

Handler for Idea Canvas REST API endpoints.

### `GET` `/api/v1/ideas` ❔

GET /api/v1/ideas

### `GET` `/api/v1/ideas/*` 🔒

GET /api/v1/ideas/*

### `GET` `/api/v1/ideas/*/nodes` ❔

GET /api/v1/ideas/*/nodes

### `GET` `/api/v1/ideas/*/nodes/*` 🔒

GET /api/v1/ideas/*/nodes/*

### `GET` `/api/v1/ideas/*/edges` ❔

GET /api/v1/ideas/*/edges

### `GET` `/api/v1/ideas/*/edges/*` 🔒

GET /api/v1/ideas/*/edges/*

### `GET` `/api/v1/ideas/*/export` ❔

GET /api/v1/ideas/*/export

### `GET` `/api/v1/ideas/*/promote` ❔

GET /api/v1/ideas/*/promote

---

## Marketplace (catalog/marketplace.py)

Marketplace API Handlers.

### `GET` `/api/v1/marketplace/templates` ❔

List all templates

### `GET` `/api/v1/marketplace/templates/\{id\}` ❔

Get template details

### `GET` `/api/v1/marketplace/categories` ❔

List categories

### `GET` `/api/v1/marketplace/status` ❔

Health and circuit breaker status

---

## MarketplaceBrowse (catalog/marketplace_browse.py)

Handler for marketplace template browsing endpoints.

### `GET` `/api/v1/marketplace/templates` ❔

GET /api/v1/marketplace/templates

### `GET` `/api/v1/marketplace/templates/*` ❔

GET /api/v1/marketplace/templates/*

### `GET` `/api/v1/marketplace/featured` ❔

Return featured templates

### `GET` `/api/v1/marketplace/popular` ❔

Return popular templates sorted by downloads

---

## Marketplace Pilot (catalog/marketplace_pilot.py)

Marketplace Pilot API Handler.

### `GET` `/api/v1/marketplace/listings` 🔒

Browse listings with filters

### `GET` `/api/v1/marketplace/listings/featured` 🔒

Featured listings

### `GET` `/api/v1/marketplace/listings/stats` 🔒

Marketplace statistics

### `GET` `/api/v1/marketplace/listings/\{id\}` 🔒

Get listing details

### `POST` `/api/v1/marketplace/listings/\{id\}/install` 🔒

Install a listing

### `POST` `/api/v1/marketplace/listings/\{id\}/rate` 🔒

Rate a listing

### `POST` `/api/v1/marketplace/listings/\{id\}/launch-debate` 🔒

Launch debate from listing

---

## Playbook (catalog/playbooks.py)

Handler for playbook API endpoints.

### `GET` `/api/playbooks` ❔

Extract playbook ID from a path like /api/playbooks/\{id\}[/run]

---

## Skill Marketplace (catalog/skill_marketplace.py)

Skill Marketplace API Handlers.

### `GET` `/api/v1/skills/marketplace/search` ❔

Search skills

### `GET` `/api/v1/skills/marketplace/installed` ❔

List installed skills

### `GET` `/api/v1/skills/marketplace/stats` ❔

Get marketplace statistics

### `GET` `/api/skills/marketplace/search` ❔

Search for skills in the marketplace

### `GET` `/api/skills/marketplace/publish` ❔

Publish a skill to the marketplace

### `GET` `/api/skills/marketplace/installed` ❔

List installed skills for the tenant

### `GET` `/api/skills/marketplace/stats` ❔

Get marketplace statistics

---

## Skills (catalog/skills.py)

Skills endpoint handlers.

### `GET` `/api/skills` ❔

List all registered skills

### `POST` `/api/skills/invoke` ❔

Invoke a skill by name

### `GET` `/api/skills/:name/metrics` ❔

Get skill execution metrics

### `POST` `/api/skills/*/invoke` ❔

Invoke a skill by name

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `request` | string | The HTTP request object. |
| `skill_name_override` | string | If provided, use this as the skill name instead of reading from the request body. Supports the POST /api/skills/:name/invoke URL pattern. |

---

## TemplateDiscovery (catalog/template_discovery.py)

Handler for template discovery endpoints.

### `GET` `/api/v1/templates` ❔

GET /api/v1/templates

### `GET` `/api/v1/templates/categories` ❔

Return categories with counts

### `GET` `/api/v1/templates/recommend` ❔

Recommend templates for a given question

### `GET` `/api/v1/templates/*` 🔒

GET /api/v1/templates/*

---

## Template Marketplace (catalog/template_marketplace.py)

Template Marketplace API Handler.

### `GET` `/api/v1/marketplace/templates` ❔

List marketplace templates with search and filters

### `GET` `/api/v1/marketplace/templates/*` ❔

GET /api/v1/marketplace/templates/*

### `GET` `/api/v1/marketplace/featured` ❔

Get featured marketplace templates

### `GET` `/api/v1/marketplace/trending` ❔

Get trending marketplace templates

### `GET` `/api/v1/marketplace/categories` ❔

Get marketplace categories with counts

### `GET` `/api/v1/marketplace/circuit-breaker` ❔

GET /api/v1/marketplace/circuit-breaker

### `GET` `/api/v1/marketplace/recommendations` 🔒

GET /api/v1/marketplace/recommendations

---

## Workflow Templates (catalog/workflow_templates.py)

Workflow Templates API Handler.

### `GET` `/api/workflow/templates` ❔

List available templates

### `GET` `/api/workflow/templates/:id` ❔

Get template details

### `GET` `/api/workflow/templates/:id/package` ❔

Get full package

### `GET` `/api/v1/templates/recommended` ❔

GET /api/v1/templates/recommended

### `GET` `/api/v1/workflow/categories` ❔

GET /api/v1/workflow/categories

### `GET` `/api/v1/workflow/pattern-templates` ❔

GET /api/v1/workflow/pattern-templates

### `GET` `/api/v1/workflow/pattern-templates/*` ❔

GET /api/v1/workflow/pattern-templates/*

### `GET` `/api/v1/workflow/patterns` ❔

GET /api/v1/workflow/patterns

### `GET` `/api/v1/workflow/templates` ❔

List available workflow templates

### `GET` `/api/v1/workflow/templates/*` ❔

GET /api/v1/workflow/templates/*

### `GET` `/api/v1/workflow/templates/*/package` ❔

Get the full package for a template

---

## Code Review (codebase/code_review.py)

HTTP API Handlers for Code Review.

### `POST` `/api/v1/code-review/review` ❔

Review code snippet

### `POST` `/api/v1/code-review/diff` ❔

Review diff/patch

### `POST` `/api/v1/code-review/pr` ❔

Review GitHub PR

### `GET` `/api/v1/code-review/results/\{id\}` ❔

Get review results

### `GET` `/api/v1/code-review/history` ❔

Get review history

### `POST` `/api/v1/code-review/security-scan` ❔

POST /api/v1/code-review/security-scan

---

## Dependency Analysis (codebase/dependency_analysis.py)

HTTP API Handlers for Dependency Analysis.

### `POST` `/api/v1/codebase/analyze-dependencies`

Analyze project dependencies

### `POST` `/api/v1/codebase/scan-vulnerabilities`

Scan for CVEs

### `POST` `/api/v1/codebase/check-licenses`

Check license compatibility

### `POST` `/api/v1/codebase/sbom`

POST /api/v1/codebase/sbom

### `POST` `/api/v1/codebase/clear-cache`

POST /api/v1/codebase/clear-cache

---

## Intelligence (codebase/intelligence.py)

HTTP API Handlers for Code Intelligence Analysis.

### `POST` `/api/v1/codebase/\{repo\}/analyze`

Analyze codebase structure

### `GET` `/api/v1/codebase/\{repo\}/symbols`

List symbols (classes, functions)

### `GET` `/api/v1/codebase/\{repo\}/callgraph`

Get call graph

### `GET` `/api/v1/codebase/\{repo\}/deadcode`

Find dead/unreachable code

### `POST` `/api/v1/codebase/\{repo\}/impact`

Analyze impact of changes

### `POST` `/api/v1/codebase/\{repo\}/understand`

Answer questions about code

### `POST` `/api/v1/codebase/\{repo\}/audit`

Run comprehensive audit

### `GET` `/api/codebase/analyze` ❔

GET /api/codebase/analyze

### `GET` `/api/codebase/symbols` ❔

GET /api/codebase/symbols

### `GET` `/api/codebase/callgraph` ❔

GET /api/codebase/callgraph

### `GET` `/api/codebase/deadcode` ❔

GET /api/codebase/deadcode

### `GET` `/api/codebase/impact` ❔

GET /api/codebase/impact

### `GET` `/api/codebase/understand` ❔

GET /api/codebase/understand

### `GET` `/api/codebase/audit` ❔

GET /api/codebase/audit

### `GET` `/api/v1/codebase/analyze` ❔

GET /api/v1/codebase/analyze

### `GET` `/api/v1/codebase/symbols` ❔

GET /api/v1/codebase/symbols

### `GET` `/api/v1/codebase/callgraph` ❔

GET /api/v1/codebase/callgraph

### `GET` `/api/v1/codebase/deadcode` ❔

GET /api/v1/codebase/deadcode

### `GET` `/api/v1/codebase/impact` ❔

GET /api/v1/codebase/impact

### `GET` `/api/v1/codebase/understand` ❔

GET /api/v1/codebase/understand

### `GET` `/api/v1/codebase/audit` ❔

GET /api/v1/codebase/audit

---

## Metrics (codebase/metrics.py)

HTTP API Handlers for Codebase Metrics Analysis.

### `POST` `/api/v1/codebase/\{repo\}/metrics/analyze`

Run metrics analysis

### `GET` `/api/v1/codebase/\{repo\}/metrics`

Get latest metrics

### `GET` `/api/v1/codebase/\{repo\}/metrics/\{analysis_id\}`

Get specific analysis

### `GET` `/api/v1/codebase/\{repo\}/hotspots`

Get complexity hotspots

### `GET` `/api/v1/codebase/\{repo\}/duplicates`

Get code duplicates

---

## Quick Scan (codebase/quick_scan.py)

Quick Security Scan API Handler.

### `POST` `/api/codebase/quick-scan`

Run quick security scan

### `GET` `/api/codebase/quick-scan/\{scan_id\}`

Get scan result

---

## Repository (codebase/repository.py)

Repository indexing endpoint handlers.

### `POST` `/api/v1/repository` ❔

Get repository information

### `POST` `/api/v1/repository/index` ❔

Index multiple repositories in batch

### `POST` `/api/v1/repository/incremental` ❔

Perform incremental repository update

### `POST` `/api/v1/repository/batch` ❔

Index multiple repositories in batch

### `GET` `/api/v1/repository/*/status` ❔

Get indexing status for a repository

### `POST` `/api/v1/repository/*/entities` ❔

Get entities from an indexed repository

### `POST` `/api/v1/repository/*/graph` ❔

Get relationship graph for a repository

### `GET` `/api/v1/repository/*` 🔒

GET /api/v1/repository/*

---

## Reviews (codebase/reviews.py)

Reviews Handler - Serve shareable code reviews.

### `GET` `/api/reviews` ❔

List recent reviews

### `GET` `/api/v1/reviews` ❔

List recent reviews

### `GET` `/api/v1/reviews/*` ❔

GET /api/v1/reviews/*

### `PUT` `/api/v1/reviews/*` 🔒

PUT /api/v1/reviews/*

### `DELETE` `/api/v1/reviews/*` 🔒

DELETE /api/v1/reviews/*

---

## Audit Trail (compliance/audit_trail.py)

Audit Trail HTTP Handlers for Aragora.

### `GET` `/api/v1/audit-trails` ❔

List recent audit trails

### `GET` `/api/v1/receipts` ❔

List recent decision receipts

---

## Data Classification Handler (compliance/data_classification_handler.py)

Data Classification Policy HTTP Handler.

### `GET` `/api/v1/data-classification/policy` 🔒

Get the active classification policy

### `POST` `/api/v1/data-classification/classify` 🔒

Classify data and return metadata

### `POST` `/api/v1/data-classification/validate` 🔒

Validate a handling operation

### `POST` `/api/v1/data-classification/enforce` 🔒

Enforce cross-context access rules

---

## Gdpr Deletion (compliance/gdpr_deletion.py)

GDPR Self-Service Deletion Handler.

### `POST` `/api/v1/users/self/deletion-request` ❔

POST /api/v1/users/self/deletion-request

### `DELETE` `/api/v1/users/self/deletion-request` ❔

DELETE /api/v1/users/self/deletion-request

---

## Compliance (compliance/handler.py)

HTTP handler for compliance and audit operations.

### `GET` `/api/v1/compliance/rbac-coverage` ❔

GET /api/v1/compliance/rbac-coverage  Returns RBAC endpoint coverage metrics

### `GET` `/api/v2/compliance` 🔒

GET /api/v2/compliance

### `GET` `/api/v2/compliance/*` 🔒

GET /api/v2/compliance/*

---

## Privacy (compliance/privacy.py)

Privacy Handler - GDPR/CCPA Compliant Data Export and Account Deletion.

### `GET` `/api/v1/privacy/export` 🔒

Format export data as CSV

### `GET` `/api/v1/privacy/data-inventory` 🔒

GET /api/v1/privacy/data-inventory

### `DELETE` `/api/v1/privacy/account` 🔒

Delete user account and associated data

### `GET` `/api/v1/privacy/preferences` 🔒

Get user's privacy preferences

### `POST` `/api/v1/privacy/preferences` 🔒

Get user's privacy preferences

### `GET` `/api/v1/users` ❔

GET /api/v1/users

### `GET` `/api/v2/users/me/export` ❔

Format export data as CSV

### `GET` `/api/v2/users/me/data-inventory` ❔

GET /api/v2/users/me/data-inventory

### `GET` `/api/v2/users/me` ❔

GET /api/v2/users/me

---

## Queue (control_plane/queue.py)

Queue management endpoint handlers.

### `POST` `/api/queue/jobs` 🔒

Submit new job

### `GET` `/api/queue/jobs` 🔒

List jobs with filters

### `GET` `/api/queue/jobs/:id` 🔒

Get job status

### `POST` `/api/queue/jobs/:id/retry` 🔒

Retry failed job

### `DELETE` `/api/queue/jobs/:id` 🔒

Cancel job

### `GET` `/api/queue/stats` 🔒

Queue statistics

### `GET` `/api/queue/workers` 🔒

Worker status

### `GET` `/api/queue/dlq` 🔒

List jobs in the dead-letter queue (failed with max retries exceeded)

### `POST` `/api/queue/dlq/requeue` 🔒

Requeue all jobs from the DLQ

### `GET` `/api/queue/dlq/*/requeue` ❔

Requeue all jobs from the DLQ

### `POST` `/api/queue/cleanup` 🔒

Cleanup old completed/failed jobs

### `GET` `/api/queue/stale` 🔒

List stale/stuck jobs (processing for too long)

### `GET` `/api/v1/queue/jobs` 🔒

Cleanup old completed/failed jobs

### `POST` `/api/v1/queue/jobs` 🔒

Cleanup old completed/failed jobs

### `GET` `/api/v1/queue/jobs/*` 🔒

GET /api/v1/queue/jobs/*

### `DELETE` `/api/v1/queue/jobs/*` 🔒

DELETE /api/v1/queue/jobs/*

### `POST` `/api/v1/queue/jobs/*/retry` 🔒

Retry a failed job

### `GET` `/api/v1/queue/stats` 🔒

Get queue statistics

### `GET` `/api/v1/queue/workers` 🔒

Get worker status

### `GET` `/api/v1/queue/dlq` 🔒

List jobs in the dead-letter queue (failed with max retries exceeded)

### `POST` `/api/v1/queue/dlq/requeue` 🔒

Requeue all jobs from the DLQ

### `GET` `/api/v1/queue/dlq/*/requeue` ❔

Requeue all jobs from the DLQ

### `POST` `/api/v1/queue/cleanup` 🔒

Cleanup old completed/failed jobs

### `GET` `/api/v1/queue/stale` 🔒

List stale/stuck jobs (processing for too long)

---

## Cost (costs/handler.py)

Handler for cost visibility API endpoints.

### `GET` `/api/v1/costs`

GET /api/v1/costs

### `GET` `/api/v1/costs/alerts`

GET /api/v1/costs/alerts

### `POST` `/api/v1/costs/alerts`

POST /api/v1/costs/alerts

### `POST` `/api/v1/costs/alerts/*/dismiss`

POST /api/v1/costs/alerts/*/dismiss

### `GET` `/api/v1/costs/analytics/budget-utilization` 🔒

GET /api/v1/costs/analytics/budget-utilization

### `POST` `/api/v1/costs/analytics/budget-utilization` ❔

POST /api/v1/costs/analytics/budget-utilization

### `GET` `/api/v1/costs/analytics/by-agent` 🔒

GET /api/v1/costs/analytics/by-agent

### `POST` `/api/v1/costs/analytics/by-agent` ❔

POST /api/v1/costs/analytics/by-agent

### `GET` `/api/v1/costs/analytics/by-debate` 🔒

GET /api/v1/costs/analytics/by-debate

### `POST` `/api/v1/costs/analytics/by-debate` ❔

POST /api/v1/costs/analytics/by-debate

### `GET` `/api/v1/costs/analytics/by-model` 🔒

GET /api/v1/costs/analytics/by-model

### `POST` `/api/v1/costs/analytics/by-model` ❔

POST /api/v1/costs/analytics/by-model

### `GET` `/api/v1/costs/analytics/trend` 🔒

GET /api/v1/costs/analytics/trend

### `POST` `/api/v1/costs/analytics/trend` ❔

POST /api/v1/costs/analytics/trend

### `GET` `/api/v1/costs/breakdown`

GET /api/v1/costs/breakdown

### `POST` `/api/v1/costs/budget`

POST /api/v1/costs/budget

### `GET` `/api/v1/costs/budgets`

GET /api/v1/costs/budgets

### `POST` `/api/v1/costs/budgets`

POST /api/v1/costs/budgets

### `POST` `/api/v1/costs/constraints/check`

POST /api/v1/costs/constraints/check

### `GET` `/api/v1/costs/efficiency`

GET /api/v1/costs/efficiency

### `POST` `/api/v1/costs/estimate`

POST /api/v1/costs/estimate

### `GET` `/api/v1/costs/export`

GET /api/v1/costs/export

### `GET` `/api/v1/costs/forecast`

GET /api/v1/costs/forecast

### `GET` `/api/v1/costs/forecast/detailed`

GET /api/v1/costs/forecast/detailed

### `POST` `/api/v1/costs/forecast/simulate` ❔

POST /api/v1/costs/forecast/simulate

### `GET` `/api/v1/costs/recommendations`

GET /api/v1/costs/recommendations

### `GET` `/api/v1/costs/recommendations/detailed`

GET /api/v1/costs/recommendations/detailed

### `GET` `/api/v1/costs/recommendations/*` 🔒

GET /api/v1/costs/recommendations/*

### `POST` `/api/v1/costs/recommendations/*/apply` 🔒

POST /api/v1/costs/recommendations/*/apply

### `POST` `/api/v1/costs/recommendations/*/dismiss` 🔒

POST /api/v1/costs/recommendations/*/dismiss

### `GET` `/api/v1/costs/timeline`

GET /api/v1/costs/timeline

### `GET` `/api/v1/costs/usage`

GET /api/v1/costs/usage

### `GET` `/api/v1/costs/debates/\{debate_id\}`

GET /api/v1/costs/debates/\{debate_id\}

### `GET` `/api/v1/costs/debates/\{debate_id\}/line-items`

GET /api/v1/costs/debates/\{debate_id\}/line-items

### `GET` `/api/v1/costs/debates/\{debate_id\}/performance`

GET /api/v1/costs/debates/\{debate_id\}/performance

### `GET` `/api/costs`

GET /api/costs

### `GET` `/api/costs/alerts`

GET /api/costs/alerts

### `POST` `/api/costs/alerts`

POST /api/costs/alerts

### `POST` `/api/costs/alerts/*/dismiss`

POST /api/costs/alerts/*/dismiss

### `POST` `/api/costs/analytics/budget-utilization` ❔

POST /api/costs/analytics/budget-utilization

### `POST` `/api/costs/analytics/by-agent` ❔

POST /api/costs/analytics/by-agent

### `POST` `/api/costs/analytics/by-debate` ❔

POST /api/costs/analytics/by-debate

### `POST` `/api/costs/analytics/by-model` ❔

POST /api/costs/analytics/by-model

### `POST` `/api/costs/analytics/trend` ❔

POST /api/costs/analytics/trend

### `GET` `/api/costs/breakdown`

GET /api/costs/breakdown

### `POST` `/api/costs/budget`

POST /api/costs/budget

### `GET` `/api/costs/budgets`

GET /api/costs/budgets

### `POST` `/api/costs/budgets` ❔

POST /api/costs/budgets

### `POST` `/api/costs/constraints/check` ❔

POST /api/costs/constraints/check

### `GET` `/api/costs/efficiency`

GET /api/costs/efficiency

### `POST` `/api/costs/estimate` ❔

POST /api/costs/estimate

### `GET` `/api/costs/export`

GET /api/costs/export

### `GET` `/api/costs/forecast`

GET /api/costs/forecast

### `GET` `/api/costs/forecast/detailed`

GET /api/costs/forecast/detailed

### `POST` `/api/costs/forecast/simulate` ❔

POST /api/costs/forecast/simulate

### `GET` `/api/costs/recommendations`

GET /api/costs/recommendations

### `GET` `/api/costs/recommendations/detailed`

GET /api/costs/recommendations/detailed

### `GET` `/api/costs/recommendations/*` 🔒

GET /api/costs/recommendations/*

### `POST` `/api/costs/recommendations/*/apply` 🔒

POST /api/costs/recommendations/*/apply

### `POST` `/api/costs/recommendations/*/dismiss` 🔒

POST /api/costs/recommendations/*/dismiss

### `GET` `/api/costs/timeline`

GET /api/costs/timeline

### `GET` `/api/costs/usage`

GET /api/costs/usage

### `GET` `/api/costs/debates/\{debate_id\}`

GET /api/costs/debates/\{debate_id\}

### `GET` `/api/costs/debates/\{debate_id\}/line-items`

GET /api/costs/debates/\{debate_id\}/line-items

### `GET` `/api/costs/debates/\{debate_id\}/performance`

GET /api/costs/debates/\{debate_id\}/performance

---

## Audience Suggestions (debates/audience_suggestions.py)

Audience suggestion handler for debate audience input.

### `GET` `/api/v1/audience/suggestions` ❔

List clustered suggestions for a debate

---

## Auditing (debates/auditing.py)

Auditing and security analysis endpoint handlers.

### `POST` `/api/debates/capability-probe` 🔒

Run capability probes on an agent

### `POST` `/api/debates/deep-audit` 🔒

Run deep audit on a task

### `POST` `/api/v1/debates/capability-probe` 🔒

POST /api/v1/debates/capability-probe

### `POST` `/api/v1/debates/deep-audit` 🔒

POST /api/v1/debates/deep-audit

### `GET` `/api/v1/redteam/attack-types` ❔

GET /api/v1/redteam/attack-types

---

## Belief (debates/belief.py)

Belief Network and Reasoning endpoint handlers.

### `GET` `/api/belief-network/:debate_id/cruxes` 🔒

Get key claims that impact debate outcome

### `GET` `/api/belief-network/:debate_id/load-bearing-claims` 🔒

Get high-centrality claims

### `GET` `/api/provenance/:debate_id/claims/:claim_id/support` ❔

Get claim verification status

### `GET` `/api/laboratory/emergent-traits` ❔

Get emergent traits from agent performance

### `GET` `/api/debate/:debate_id/graph-stats` 🔒

Get argument graph statistics

### `GET` `/api/belief-network/*/graph` ❔

Get belief network as a graph structure for visualization

### `GET` `/api/belief-network/*/export` ❔

Export belief network in various formats

### `GET` `/api/v1/belief-network/*/graph` ❔

Get belief network as a graph structure for visualization

### `GET` `/api/v1/belief-network/*/export` ❔

Export belief network in various formats

### `GET` `/api/v1/debates/*/cruxes` ❔

Get key claims that would most impact the debate outcome

---

## Breakpoints (debates/breakpoints.py)

Breakpoints endpoint handlers for human-in-the-loop intervention.

### `POST` `/api/v1/breakpoints` ❔

Get all pending breakpoints awaiting human resolution

### `POST` `/api/v1/breakpoints/pending` ❔

Get all pending breakpoints awaiting human resolution

---

## DebateDecisionBridge (debates/bridge.py)

POST handler for bridging a debate's latest DecisionPlan to external tools.

### `POST` `/api/v1/debates/\{id\}/bridge` 🔒

POST /api/v1/debates/\{id\}/bridge

---

## Composite (debates/composite.py)

Composite API handlers that aggregate data from multiple subsystems.

### `GET` `/api/v1/debates/\{id\}/full-context` ❔

Memory + Knowledge + Belief context

### `GET` `/api/v1/agents/\{id\}/reliability` ❔

Circuit breaker + Airlock metrics

### `GET` `/api/v1/debates/\{id\}/compression-analysis` ❔

RLM compression metrics

---

## Context Budget (debates/context_budget.py)

Context budget handler for managing debate prompt token budgets.

### `GET` `/api/v1/context/budget` ❔

Get current context budget configuration

### `GET` `/api/v1/context/budget/estimate` ❔

GET /api/v1/context/budget/estimate

---

## Critique (debates/critique.py)

Critique pattern and reputation endpoint handlers.

### `GET` `/api/critiques/patterns` ❔

Get high-impact critique patterns

### `GET` `/api/critiques/archive` ❔

Get archive statistics

### `GET` `/api/reputation/all` ❔

Get all agent reputations

### `GET` `/api/reputation/:name` ❔

Get specific agent reputation

### `GET` `/api/agent/:name/reputation` ❔

Get specific agent reputation

### `GET` `/api/reputation/history` 🔒

Return reputation timeline snapshots derived from stored reputation rows

### `GET` `/api/reputation/domain` 🔒

Heuristic domain matcher for agent names

---

## Debate Intervention (debates/debate_intervention.py)

Debate intervention and reasoning endpoint handlers.

### `POST` `/api/v1/debates/\{debate_id\}/intervene` ❔

Submit a mid-debate intervention

---

## Debate Stats (debates/debate_stats.py)

Debate statistics handler for aggregate debate metrics.

### `GET` `/api/v1/debates/stats` ❔

Get aggregate debate statistics

### `GET` `/api/v1/debates/stats/agents` ❔

Get per-agent statistics

---

## DecisionPackage (debates/decision_package.py)

Handler for decision package assembly endpoints.

### `GET` `/api/v1/debates/*/package` ❔

Assemble a decision package for the given debate

### `GET` `/api/v1/debates/*/package/markdown` ❔

Return the decision package as markdown

---

## Deliberations (debates/deliberations.py)

Handler for vetted decisionmaking dashboard endpoints.

### `GET` `/api/v1/deliberations/active` 🔒

Fetch active vetted decisionmaking sessions from the debate store

### `GET` `/api/v1/deliberations/stats` 🔒

Get deliberation statistics

### `GET` `/api/v1/deliberations/stream` 🔒

Handle WebSocket stream for real-time updates

### `GET` `/api/v1/deliberations/\{deliberation_id\}` 🔒

GET /api/v1/deliberations/\{deliberation_id\}

---

## Graph Debates (debates/graph_debates.py)

Graph debates endpoint handlers.

### `GET` `/api/v1/debates/graph` ❔

Get a graph debate by ID

### `POST` `/api/v1/debates/graph` ❔

Get a graph debate by ID

### `GET` `/api/v1/graph-debates` ❔

GET /api/v1/graph-debates

### `POST` `/api/v1/graph-debates` ❔

POST /api/v1/graph-debates

### `GET` `/api/v1/graph-debates/*` ❔

GET /api/v1/graph-debates/*

---

## Handler (debates/handler.py)

Debate-related endpoint handlers.

### `GET` `/api/debates` 🔒

List all debates

### `GET` `/api/debates/\{slug\}` 🔒

Get debate by slug

### `GET` `/api/debates/slug/\{slug\}` ❔

Get debate by slug (alternative)

### `GET` `/api/debates/\{id\}/export/\{format\}` ❔

Export debate

### `GET` `/api/debates/\{id\}/impasse` ❔

Detect debate impasse

### `GET` `/api/debates/\{id\}/convergence` ❔

Get convergence status

### `GET` `/api/debates/\{id\}/citations` ❔

Get evidence citations for debate

### `GET` `/api/debates/\{id\}/evidence` ❔

Get comprehensive evidence trail

### `POST` `/api/debates/\{id\}/fork` ❔

Fork debate at a branch point

### `PATCH` `/api/debates/\{id\}` 🔒

Update debate metadata (title, tags, status)

### `DELETE` `/api/debates/\{id\}` 🔒

Permanently delete a debate (cascades to critiques)

### `GET` `/api/search` ❔

Cross-debate search by query

### `POST` `/api/v1/debate` 🔒

POST /api/v1/debate

### `GET` `/api/v1/debates` 🔒

GET /api/v1/debates

### `POST` `/api/v1/debates` 🔒

POST /api/v1/debates

### `GET` `/api/v1/debates/active` ❔

GET /api/v1/debates/active

### `GET` `/api/v1/debates/estimate-cost` ❔

GET /api/v1/debates/estimate-cost

### `GET` `/api/v1/debates/batch` ❔

Route batch export requests to appropriate methods

### `POST` `/api/v1/debates/batch` ❔

Route batch export requests to appropriate methods

### `GET` `/api/v1/debates/batch/*/status` ❔

GET /api/v1/debates/batch/*/status

### `GET` `/api/v1/debates/queue/status` ❔

GET /api/v1/debates/queue/status

### `GET` `/api/v1/debates/export/batch` ❔

Route batch export requests to appropriate methods

### `POST` `/api/v1/debates/export/batch` ❔

Route batch export requests to appropriate methods

### `GET` `/api/v1/debates/export/batch/*/status` 🔒

GET /api/v1/debates/export/batch/*/status

### `GET` `/api/v1/debates/export/batch/*/results` 🔒

GET /api/v1/debates/export/batch/*/results

### `GET` `/api/v1/debates/export/batch/*/stream` ❔

GET /api/v1/debates/export/batch/*/stream

### `POST` `/api/v1/debates/slug/` ❔

Route batch export requests to appropriate methods

### `POST` `/api/v1/debates/*/export/` ❔

Route batch export requests to appropriate methods

### `GET` `/api/v1/debates/*/impasse` ❔

GET /api/v1/debates/*/impasse

### `GET` `/api/v1/debates/*/convergence` ❔

GET /api/v1/debates/*/convergence

### `GET` `/api/v1/debates/*/citations` ❔

GET /api/v1/debates/*/citations

### `GET` `/api/v1/debates/*/messages` ❔

GET /api/v1/debates/*/messages

### `POST` `/api/v1/debates/*/messages` ❔

POST /api/v1/debates/*/messages

### `POST` `/api/v1/debates/*/fork` ❔

POST /api/v1/debates/*/fork

### `POST` `/api/v1/debates/*/followup` ❔

POST /api/v1/debates/*/followup

### `GET` `/api/v1/debates/*/followups` 🔒

GET /api/v1/debates/*/followups

### `GET` `/api/v1/debates/*/forks` 🔒

GET /api/v1/debates/*/forks

### `GET` `/api/v1/debates/*/verification-report` ❔

GET /api/v1/debates/*/verification-report

### `GET` `/api/v1/debates/*/summary` ❔

GET /api/v1/debates/*/summary

### `POST` `/api/v1/debates/*/cancel` ❔

POST /api/v1/debates/*/cancel

### `POST` `/api/v1/debates/*/decision-integrity` 🔒

POST /api/v1/debates/*/decision-integrity

### `GET` `/api/v1/debates/*/positions` 🔒

GET /api/v1/debates/*/positions

### `GET` `/api/v1/debates/*/diagnostics` ❔

GET /api/v1/debates/*/diagnostics

### `GET` `/api/v1/debates/*/costs` 🔒

GET /api/v1/debates/*/costs

### `POST` `/api/v1/debate-this` ❔

POST /api/v1/debate-this

### `GET` `/api/v1/search` ❔

GET /api/v1/search

### `POST` `/api/v1/debates/analytics/consensus` ❔

POST /api/v1/debates/analytics/consensus

### `POST` `/api/v1/debates/analytics/trends` ❔

POST /api/v1/debates/analytics/trends

### `POST` `/api/v1/debates/archive/batch` ❔

Route batch export requests to appropriate methods

### `POST` `/api/v1/debates/archived` ❔

POST /api/v1/debates/archived

### `POST` `/api/v1/debates/compare` ❔

POST /api/v1/debates/compare

### `GET` `/api/v1/debates/health` ❔

GET /api/v1/debates/health

### `POST` `/api/v1/debates/import` ❔

POST /api/v1/debates/import

### `GET` `/api/v1/debates/statistics` ❔

GET /api/v1/debates/statistics

### `GET` `/api/v1/debates/stream` ❔

GET /api/v1/debates/stream

### `GET` `/api/v1/debates/*/events` 🔒

GET /api/v1/debates/*/events

---

## HybridDebate (debates/hybrid_debate_handler.py)

HTTP request handler for hybrid debate API endpoints.

### `GET` `/api/v1/debates/hybrid` 🔒

Handle POST /api/v1/debates/hybrid

### `POST` `/api/v1/debates/hybrid` 🔒

Handle POST /api/v1/debates/hybrid

### `GET` `/api/v1/debates/hybrid/*` 🔒

GET /api/v1/debates/hybrid/*

---

## DebateInterventions (debates/interventions.py)

Handler for debate intervention endpoints.

### `POST` `/api/v1/debates/*/pause` ❔

POST /api/v1/debates/*/pause

### `POST` `/api/v1/debates/*/resume` ❔

POST /api/v1/debates/*/resume

### `POST` `/api/v1/debates/*/nudge` 🔒

POST /api/v1/debates/*/nudge

### `POST` `/api/v1/debates/*/challenge` 🔒

POST /api/v1/debates/*/challenge

### `POST` `/api/v1/debates/*/inject-evidence` 🔒

POST /api/v1/debates/*/inject-evidence

### `GET` `/api/v1/debates/*/intervention-log` 🔒

GET /api/v1/debates/*/intervention-log

---

## Matrix Debates (debates/matrix_debates.py)

Matrix debates endpoint handlers.

### `GET` `/api/v1/debates/matrix` ❔

Build a comparison matrix of scenarios

### `POST` `/api/v1/debates/matrix` ❔

Build a comparison matrix of scenarios

### `GET` `/api/v1/matrix-debates` ❔

GET /api/v1/matrix-debates

### `POST` `/api/v1/matrix-debates` ❔

POST /api/v1/matrix-debates

### `GET` `/api/v1/matrix-debates/*` ❔

GET /api/v1/matrix-debates/*

---

## Moments (debates/moments.py)

Moments endpoint handlers.

### `GET` `/api/moments/summary` ❔

Global moments overview

### `GET` `/api/moments/timeline` ❔

Chronological moments (limit, offset)

### `GET` `/api/moments/by-type/\{type\}` ❔

Filter moments by type

### `GET` `/api/moments/trending` ❔

Most significant recent moments

### `GET` `/api/moments` ❔

Get all moments from all agents

### `GET` `/api/moments/recent` ❔

GET /api/moments/recent

### `GET` `/api/v1/moments/by-type` ❔

GET /api/v1/moments/by-type

### `GET` `/api/v1/moments/recent` ❔

GET /api/v1/moments/recent

---

## PublicDebateViewer (debates/public_viewer.py)

Handler for public debate viewing and OG metadata.

### `GET` `/api/v1/debates/public/*` 🔒

GET /api/v1/debates/public/*

### `GET` `/api/v1/debates/public/*/og` ❔

Return HTML with Open Graph meta tags for social previews

---

## DebateShare (debates/share.py)

Handler for public debate sharing and spectating.

### `POST` `/api/v1/debates/*/share` ❔

POST /api/v1/debates/*/share

### `POST` `/api/v1/debates/*/spectate/public` ❔

Handle public spectate request (non-streaming fallback)

---

## Tournaments (debates/tournaments.py)

Tournament-related endpoint handlers.

### `GET` `/api/tournaments` ❔

List all tournaments

### `GET` `/api/tournaments/\{id\}/standings` ❔

Get tournament standings

### `POST` `/api/tournaments/\{id\}/advance` ❔

Advance to next round

### `POST` `/api/tournaments/\{id\}/matches/\{match_id\}/result` ❔

Record match result

### `POST` `/api/tournaments/*/bracket` ❔

Get tournament bracket structure

### `POST` `/api/tournaments/*/matches` ❔

Get tournament match history

---

## Uncertainty (debates/uncertainty.py)

Uncertainty estimation endpoint handlers.

### `POST` `/api/v1/uncertainty/estimate` ❔

Estimate uncertainty for provided debate data

### `POST` `/api/v1/uncertainty/followups` ❔

Generate follow-up debate suggestions from cruxes

### `POST` `/api/v1/uncertainty/debate` ❔

Get uncertainty metrics for a specific debate

### `GET` `/api/v1/uncertainty/debate/*` 🔒

GET /api/v1/uncertainty/debate/*

### `GET` `/api/v1/uncertainty/agent/*` 🔒

GET /api/v1/uncertainty/agent/*

---

## Visualization (debates/visualization.py)

Visualization endpoint handlers — argument cartography and replay.

### `GET` `/api/v1/visualization/debates` 🔒

GET /api/v1/visualization/debates

### `POST` `/api/v1/visualization/debates` 🔒

POST /api/v1/visualization/debates

---

## Decision (decisions/decision.py)

Handler for unified decision-making API endpoints.

### `GET` `/api/v1/decisions`

List recent decisions

### `POST` `/api/v1/decisions`

List recent decisions

### `GET` `/api/v1/decisions/*`

GET /api/v1/decisions/*

---

## DecisionExplain (decisions/explain.py)

Handler for decision explainability endpoints.

### `GET` `/api/v1/decisions/*/explain`

Generate comprehensive decision explanation

---

## Explainability (decisions/explainability.py)

Handler for debate explainability endpoints.

### `GET` `/api/v1/debates/*/explanation` ❔

Build explanation dictionary based on options

### `GET` `/api/v1/debates/*/evidence` ❔

Handle evidence chain request

### `GET` `/api/v1/debates/*/votes/pivots` ❔

Handle vote pivot analysis request

### `GET` `/api/v1/debates/*/counterfactuals` ❔

Handle counterfactual analysis request

### `GET` `/api/v1/explain` ❔

GET /api/v1/explain

### `GET` `/api/v1/explain/*` ❔

GET /api/v1/explain/*

### `POST` `/api/v1/explainability/batch` ❔

Create a new batch explainability job

### `GET` `/api/v1/explainability/batch/*/status` ❔

Get status of a batch job

### `GET` `/api/v1/explainability/batch/*/results` ❔

Get results of a completed batch job

### `GET` `/api/v1/explainability/compare` ❔

Compare explanations between multiple debates

---

## Pipeline (decisions/pipeline.py)

Decision Pipeline HTTP handlers.

### `POST` `/api/v1/decisions/plans` ❔

Create plan from debate result

### `GET` `/api/v1/decisions/plans/\{plan_id\}` 🔒

Get plan details

### `POST` `/api/v1/decisions/plans/\{plan_id\}/approve` ❔

Approve plan

### `POST` `/api/v1/decisions/plans/\{plan_id\}/reject` ❔

Reject plan

### `POST` `/api/v1/decisions/plans/\{plan_id\}/execute` ❔

Execute approved plan

### `POST` `/api/v1/decisions/plans/*/outcome` ❔

Get the execution outcome for a completed plan

---

## Receipts (decisions/receipts.py)

Decision Receipt HTTP Handlers for Aragora.

### `GET` `/api/v2/receipts` 🔒

List receipts with filters

### `GET` `/api/v2/receipts/search` 🔒

Full-text search receipts

### `GET` `/api/v2/receipts/:receipt_id` 🔒

Get specific receipt

### `GET` `/api/v2/receipts/:receipt_id/export`

Export (format=json|html|md|pdf)

### `GET` `/api/v2/receipts/:receipt_id/verify` 🔒

Verify integrity + signature

### `POST` `/api/v2/receipts/:receipt_id/verify` 🔒

Verify integrity checksum

### `POST` `/api/v2/receipts/:receipt_id/verify-signature` 🔒

Verify cryptographic signature

### `GET` `/api/v2/receipts/stats` 🔒

Receipt statistics

### `POST` `/api/v2/receipts/:receipt_id/share` 🔒

Create shareable link

### `GET` `/api/v2/receipts/share/:token` ❔

Access receipt via share token

### `GET` `/api/v2/receipts/signing-key`

ODR signing public key (JSON envelope)

### `GET` `/.well-known/aragora-odr-signing-key`

ODR signing public key (raw PEM)

### `GET` `/api/v1/receipts/deliveries` 🔒

Legacy/frontend delivery history bridge

### `POST` `/api/v1/receipts/*/deliver` ❔

Return receipt delivery history in the legacy/frontend response shape

---

## Playground (demo/playground.py)

HTTP handler for the public playground demo.

### `POST` `/api/v1/playground/assess` ❔

Assess question ambiguity using a frontier model

### `POST` `/api/v1/playground/debate` ❔

Retrieve a saved debate by ID for shareable links

### `POST` `/api/v1/playground/debate/live` ❔

Run a live debate with real API-backed agents

### `POST` `/api/v1/playground/debate/live/cost-estimate` ❔

POST /api/v1/playground/debate/live/cost-estimate

### `POST` `/api/v1/playground/landing/events` ❔

POST /api/v1/playground/landing/events

### `GET` `/api/v1/playground/landing/events/summary` ❔

Summarize recent landing telemetry without exposing raw events

### `GET` `/api/v1/playground/landing/feedback` 🔒

Accept a bounded wrong-answer report from the landing page

### `POST` `/api/v1/playground/landing/feedback` ❔

Accept a bounded wrong-answer report from the landing page

### `POST` `/api/v1/playground/landing/feedback/review` 🔒

Update admin review state for a wrong-answer report

### `POST` `/api/v1/playground/status` ❔

POST /api/v1/playground/status

### `POST` `/api/v1/playground/tts` ❔

Proxy text-to-speech through ElevenLabs, returning audio/mpeg

---

## EmailDebate (email/email_debate.py)

Handler for email vetted decisionmaking API endpoints.

### `GET` `/api/v1/email/prioritize` ❔

Prioritize multiple emails

### `POST` `/api/v1/email/prioritize` 🔒

Prioritize multiple emails

### `POST` `/api/v1/email/prioritize/batch` ❔

Prioritize multiple emails

### `POST` `/api/v1/email/triage` ❔

Full inbox triage with categorization and sorting

---

## Email Services (email/email_services.py)

HTTP API Handlers for Email Services.

### `POST` `/api/v1/email/followups/mark` ❔

Mark email as awaiting reply

### `GET` `/api/v1/email/followups/pending` ❔

List pending follow-ups

### `POST` `/api/v1/email/followups/check-replies` ❔

Check for replies

### `GET` `/api/v1/email/snoozed` ❔

List snoozed emails

### `GET` `/api/v1/email/categories` ❔

List available categories

### `POST` `/api/v1/email/categories/learn` ❔

Category feedback (501: learning is not implemented)

### `POST` `/api/v1/email/followups/auto-detect` ❔

POST /api/v1/email/followups/auto-detect

### `POST` `/api/v1/email/snooze/process-due` ❔

POST /api/v1/email/snooze/process-due

---

## EmailTriage (email/email_triage.py)

Handler for email triage rules management.

### `GET` `/api/v1/email/triage/rules` ❔

Return current triage rules

### `PUT` `/api/v1/email/triage/rules` ❔

Return current triage rules

### `POST` `/api/v1/email/triage/test` ❔

Test a message against current triage rules

---

## Email (email/handler.py)

HTTP handler for email prioritization endpoints.

### `GET` `/api/v1/email/prioritize` ❔

GET /api/v1/email/prioritize

### `POST` `/api/v1/email/prioritize` 🔒

POST /api/v1/email/prioritize

### `GET` `/api/v1/email/rank-inbox` ❔

GET /api/v1/email/rank-inbox

### `POST` `/api/v1/email/rank-inbox` 🔒

POST /api/v1/email/rank-inbox

### `GET` `/api/v1/email/feedback` ❔

GET /api/v1/email/feedback

### `POST` `/api/v1/email/feedback` 🔒

POST /api/v1/email/feedback

### `GET` `/api/v1/email/feedback/batch` ❔

GET /api/v1/email/feedback/batch

### `POST` `/api/v1/email/feedback/batch` 🔒

POST /api/v1/email/feedback/batch

### `GET` `/api/v1/email/inbox` ❔

GET /api/v1/email/inbox

### `GET` `/api/v1/email/config` ❔

GET /api/v1/email/config

### `PUT` `/api/v1/email/config` 🔒

PUT /api/v1/email/config

### `GET` `/api/v1/email/vip` ❔

GET /api/v1/email/vip

### `POST` `/api/v1/email/vip` 🔒

POST /api/v1/email/vip

### `DELETE` `/api/v1/email/vip` 🔒

DELETE /api/v1/email/vip

### `GET` `/api/v1/email/categorize` ❔

GET /api/v1/email/categorize

### `POST` `/api/v1/email/categorize` 🔒

POST /api/v1/email/categorize

### `GET` `/api/v1/email/categorize/batch` ❔

GET /api/v1/email/categorize/batch

### `POST` `/api/v1/email/categorize/batch` 🔒

POST /api/v1/email/categorize/batch

### `GET` `/api/v1/email/categorize/apply-label` ❔

GET /api/v1/email/categorize/apply-label

### `POST` `/api/v1/email/categorize/apply-label` 🔒

POST /api/v1/email/categorize/apply-label

### `GET` `/api/v1/email/gmail/oauth/url` ❔

GET /api/v1/email/gmail/oauth/url

### `POST` `/api/v1/email/gmail/oauth/url` 🔒

POST /api/v1/email/gmail/oauth/url

### `GET` `/api/v1/email/gmail/oauth/callback` ❔

GET /api/v1/email/gmail/oauth/callback

### `POST` `/api/v1/email/gmail/oauth/callback` 🔒

POST /api/v1/email/gmail/oauth/callback

### `GET` `/api/v1/email/gmail/status` ❔

GET /api/v1/email/gmail/status

### `GET` `/api/v1/email/context/boost` ❔

GET /api/v1/email/context/boost

### `POST` `/api/v1/email/context/boost` 🔒

POST /api/v1/email/context/boost

---

## Ab Testing (evolution/ab_testing.py)

Evolution A/B testing endpoint handlers.

### `GET` `/api/evolution/ab-tests` ❔

List all A/B tests

### `POST` `/api/evolution/ab-tests` ❔

Start new A/B test

### `GET` `/api/v1/evolution/ab-tests` ❔

GET /api/v1/evolution/ab-tests

### `POST` `/api/v1/evolution/ab-tests` ❔

POST /api/v1/evolution/ab-tests

---

## Cross Pollination (evolution/cross_pollination.py)

Cross-Pollination observability endpoint handlers.

### `GET` `/api/cross-pollination/stats` ❔

Get cross-subscriber statistics

### `GET` `/api/cross-pollination/subscribers` ❔

List all subscribers

### `GET` `/api/cross-pollination/bridge` ❔

Arena event bridge status

### `POST` `/api/cross-pollination/reset` ❔

Reset subscriber statistics

### `GET` `/api/v1/cross-pollination/bridge` ❔

GET /api/v1/cross-pollination/bridge

### `GET` `/api/v1/cross-pollination/km/culture` ❔

GET /api/v1/cross-pollination/km/culture

### `GET` `/api/v1/cross-pollination/km` ❔

GET /api/v1/cross-pollination/km

### `GET` `/api/v1/cross-pollination/km/staleness-check` ❔

GET /api/v1/cross-pollination/km/staleness-check

### `POST` `/api/v1/cross-pollination/km/sync` ❔

POST /api/v1/cross-pollination/km/sync

### `GET` `/api/v1/cross-pollination/metrics` ❔

GET /api/v1/cross-pollination/metrics

### `POST` `/api/v1/cross-pollination/reset` ❔

POST /api/v1/cross-pollination/reset

### `GET` `/api/v1/cross-pollination/stats` ❔

GET /api/v1/cross-pollination/stats

### `GET` `/api/v1/cross-pollination/conflicts` ❔

GET /api/v1/cross-pollination/conflicts

### `GET` `/api/v1/cross-pollination/federation` ❔

GET /api/v1/cross-pollination/federation

### `GET` `/api/v1/cross-pollination/federation/sync` ❔

GET /api/v1/cross-pollination/federation/sync

### `GET` `/api/v1/cross-pollination/subscribe` ❔

GET /api/v1/cross-pollination/subscribe

### `GET` `/api/v1/cross-pollination/sync/status` ❔

GET /api/v1/cross-pollination/sync/status

### `GET` `/api/v1/cross-pollination/sync/trigger` ❔

GET /api/v1/cross-pollination/sync/trigger

### `GET` `/api/v1/cross-pollination/subscribers` ❔

GET /api/v1/cross-pollination/subscribers

---

## Genesis (evolution/genesis.py)

Genesis (evolution visibility) endpoint handlers.

### `GET` `/api/genesis/stats` ❔

Get overall genesis statistics

### `GET` `/api/genesis/events` ❔

Get recent genesis events

### `GET` `/api/genesis/lineage/:genome_id` ❔

Get genome ancestry

### `GET` `/api/genesis/tree/:debate_id` ❔

Get debate tree structure

### `GET` `/api/genesis/genomes` ❔

List all genomes

### `GET` `/api/genesis/genomes/top` ❔

Get top genomes by fitness

### `GET` `/api/genesis/population` ❔

Get the active population and its status

### `GET` `/api/v1/genesis/stats` ❔

Get overall genesis statistics for evolution visibility

### `GET` `/api/v1/genesis/events` ❔

Get recent genesis events

### `GET` `/api/v1/genesis/genomes` ❔

Get all genomes with pagination

### `GET` `/api/v1/genesis/genomes/top` ❔

Get top genomes by fitness score

### `GET` `/api/v1/genesis/genomes/*` ❔

GET /api/v1/genesis/genomes/*

### `GET` `/api/v1/genesis/population` ❔

Get the active population and its status

### `GET` `/api/v1/genesis/lineage` ❔

Get the lineage (ancestry) of a genome

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `genome_id` | string | The genome to trace |
| `max_depth` | string | Maximum depth to trace (default 10) |
| `Response` | string |  \{ "genome_id": "genome_abc", "lineage": [ { "genome_id": "...", "name": "...", "generation": 5, "fitness_score": 0.85, "parent_ids": [...], "event_type": "mutation", "created_at": "2026-01-13T..." \} ], "generations": 5 } |

### `GET` `/api/v1/genesis/lineage/*` ❔

GET /api/v1/genesis/lineage/*

### `GET` `/api/v1/genesis/tree` ❔

Get the fractal tree structure for a debate

### `GET` `/api/v1/genesis/tree/*` ❔

GET /api/v1/genesis/tree/*

### `GET` `/api/v1/genesis/descendants` ❔

Get all descendants of a genome (genomes that have this as ancestor)

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `genome_id` | string | The genome to find descendants of |
| `max_depth` | string | Maximum depth to search (default 5) |
| `Response` | string |  \{ "genome_id": "genome_abc", "descendants": [ { "genome_id": "...", "name": "...", "generation": 6, "fitness_score": 0.87, "parent_ids": [...], "depth": 1 \} ], "total_descendants": 15, "max_generation": 8 } |

### `GET` `/api/v1/genesis/descendants/*` ❔

GET /api/v1/genesis/descendants/*

---

## Handler (evolution/handler.py)

Prompt evolution endpoint handlers.

### `GET` `/api/evolution/patterns` ❔

Get top patterns across all agents

### `GET` `/api/evolution/summary` ❔

Get evolution summary statistics

### `GET` `/api/evolution/\{agent\}/history` ❔

Get prompt evolution history for an agent

### `GET` `/api/evolution/\{agent\}/prompt` ❔

Get current/specific prompt version for an agent

### `GET` `/api/evolution` ❔

Get prompt evolution history for an agent

### `GET` `/api/v1/evolution` ❔

Get prompt evolution history for an agent

### `GET` `/api/v1/evolution/patterns` ❔

Get top evolution patterns across all agents

### `GET` `/api/v1/evolution/summary` ❔

Get evolution summary statistics

### `GET` `/api/v1/evolution/*/history` ❔

Get prompt evolution history for an agent

### `GET` `/api/v1/evolution/*/prompt` ❔

Get a specific prompt version for an agent

---

## Replays (evolution/replays.py)

Replays and learning evolution endpoint handlers.

### `GET` `/api/replays` ❔

List available replays

### `GET` `/api/replays/:replay_id` ❔

Get specific replay with events

### `GET` `/api/learning/evolution` ❔

Get meta-learning patterns

### `GET` `/api/meta-learning/stats` ❔

Get meta-learning hyperparameters and efficiency stats

### `GET` `/api/v1/replays` ❔

List available replay directories with bounded iteration

### `GET` `/api/v1/replays/compare` ❔

GET /api/v1/replays/compare

### `GET` `/api/v1/replays/search` ❔

GET /api/v1/replays/search

### `GET` `/api/v1/replays/stats` ❔

Get meta-learning hyperparameters and efficiency stats

### `GET` `/api/v1/learning/evolution` ❔

Get learning/evolution data from meta_learning

### `GET` `/api/v1/meta-learning/stats` ❔

Get meta-learning hyperparameters and efficiency stats

---

## Training (evolution/training.py)

Handler for training data export endpoints.

### `GET` `/api/training/export/sft` ❔

Get or create SFT exporter

### `GET` `/api/training/export/dpo` ❔

Get or create DPO exporter

### `GET` `/api/training/export/gauntlet` ❔

Get or create Gauntlet exporter

### `GET` `/api/training/stats` ❔

GET /api/training/stats

### `GET` `/api/training/formats` ❔

GET /api/training/formats

### `GET` `/api/training/jobs` ❔

GET /api/training/jobs

### `GET` `/api/v1/training/export/sft` ❔

Get or create SFT exporter

### `GET` `/api/v1/training/export/dpo` ❔

Get or create DPO exporter

### `GET` `/api/v1/training/export/gauntlet` ❔

Get or create Gauntlet exporter

### `GET` `/api/v1/training/stats` ❔

GET /api/v1/training/stats

### `GET` `/api/v1/training/formats` ❔

GET /api/v1/training/formats

### `GET` `/api/v1/training/jobs` ❔

GET /api/v1/training/jobs

---

## ExamplePermission (examples/permission_example.py)

Example handler with RBAC permission checking.

### `GET` `/api/v1/documents` ❔

Get sensitive documents - requires additional permission

---

## Advertising (features/advertising.py)

Handler for advertising platform API endpoints.

### `GET` `/api/v1/advertising/platforms` 🔒

List all supported advertising platforms and connection status

### `POST` `/api/v1/advertising/connect` 🔒

Connect an advertising platform with credentials

### `DELETE` `/api/v1/advertising/\{platform\}` 🔒

DELETE /api/v1/advertising/\{platform\}

### `GET` `/api/v1/advertising/campaigns` 🔒

Fetch campaigns from a specific platform

### `GET` `/api/v1/advertising/\{platform\}/campaigns` 🔒

Fetch campaigns from a specific platform

### `POST` `/api/v1/advertising/\{platform\}/campaigns` 🔒

Fetch campaigns from a specific platform

### `GET` `/api/v1/advertising/\{platform\}/campaigns/\{campaign_id\}` 🔒

GET /api/v1/advertising/\{platform\}/campaigns/\{campaign_id\}

### `PUT` `/api/v1/advertising/\{platform\}/campaigns/\{campaign_id\}` 🔒

PUT /api/v1/advertising/\{platform\}/campaigns/\{campaign_id\}

### `GET` `/api/v1/advertising/performance` 🔒

Run multi-agent analysis on advertising performance

### `GET` `/api/v1/advertising/\{platform\}/performance` 🔒

Run multi-agent analysis on advertising performance

### `POST` `/api/v1/advertising/analyze` 🔒

Run multi-agent analysis on advertising performance

### `GET` `/api/v1/advertising/budget-recommendations` 🔒

GET /api/v1/advertising/budget-recommendations

---

## AnalyticsPlatforms (features/analytics_platforms.py)

Handler for analytics platform API endpoints.

### `GET` `/api/v1/analytics/platforms` ❔

List all supported analytics platforms and connection status

### `GET` `/api/v1/analytics/connect` ❔

Connect an analytics platform with credentials

### `GET` `/api/v1/analytics/\{platform\}` ❔

GET /api/v1/analytics/\{platform\}

### `GET` `/api/v1/analytics/dashboards` ❔

Fetch dashboards from a specific platform

### `GET` `/api/v1/analytics/\{platform\}/dashboards` ❔

Fetch dashboards from a specific platform

### `GET` `/api/v1/analytics/\{platform\}/dashboards/\{dashboard_id\}` ❔

GET /api/v1/analytics/\{platform\}/dashboards/\{dashboard_id\}

### `GET` `/api/v1/analytics/query` ❔

Execute a query on a specific platform

### `GET` `/api/v1/analytics/reports` ❔

List available pre-built reports

### `GET` `/api/v1/analytics/reports/generate` ❔

Generate a custom analytics report

### `GET` `/api/v1/analytics/metrics` ❔

Get a unified metrics overview across all platforms

### `GET` `/api/v1/analytics/realtime` ❔

Get real-time metrics (primarily from GA4)

### `GET` `/api/v1/analytics/\{platform\}/events` ❔

Get event data from a platform

### `GET` `/api/v1/analytics/\{platform\}/funnels` ❔

Get funnel analysis from a platform

### `GET` `/api/v1/analytics/\{platform\}/retention` ❔

Get retention analysis from a platform

---

## Audio (features/audio.py)

Audio and Podcast endpoint handlers.

### `GET` `/api/podcast/feed.xml` ❔

iTunes-compatible RSS feed

### `GET` `/api/podcast/episodes` ❔

JSON episode listing

### `GET` `/audio` ❔

Serve audio file for a debate with security checks

### `GET` `/audio/*` ❔

GET /audio/*

### `GET` `/api/v1/media/audio` ❔

Serve audio file for a debate with security checks

### `GET` `/api/v1/podcast/feed` ❔

Generate iTunes-compatible podcast RSS feed

### `GET` `/api/v1/podcast/feed.xml` ❔

GET /api/v1/podcast/feed.xml

### `GET` `/api/v1/podcast/episodes` ❔

Get podcast episodes as JSON

---

## AuditSessions (features/audit_sessions.py)

Handler for audit session management endpoints.

### `GET` `/api/v1/audit/sessions`

List all audit sessions with optional filtering

### `POST` `/api/v1/audit/sessions`

List all audit sessions with optional filtering

### `GET` `/api/v1/audit/sessions/\{session_id\}`

GET /api/v1/audit/sessions/\{session_id\}

### `DELETE` `/api/v1/audit/sessions/\{session_id\}`

DELETE /api/v1/audit/sessions/\{session_id\}

### `POST` `/api/v1/audit/sessions/\{session_id\}/start`

Start an audit session

### `POST` `/api/v1/audit/sessions/\{session_id\}/pause`

Pause a running audit session

### `POST` `/api/v1/audit/sessions/\{session_id\}/resume`

Resume a paused audit session

### `POST` `/api/v1/audit/sessions/\{session_id\}/cancel`

Cancel an audit session using CancellationToken for cooperative abort

### `GET` `/api/v1/audit/sessions/\{session_id\}/findings`

Get findings for a session with optional filtering

### `GET` `/api/v1/audit/sessions/\{session_id\}/events`

Stream audit events via Server-Sent Events (SSE)

### `POST` `/api/v1/audit/sessions/\{session_id\}/intervene`

POST /api/v1/audit/sessions/\{session_id\}/intervene

### `GET` `/api/v1/audit/sessions/\{session_id\}/report`

Export audit report in various formats

---

## Broadcast (features/broadcast.py)

Broadcast generation handler.

### `POST` `/api/debates/\{id\}/broadcast` 🔒

Generate podcast audio from debate trace

### `GET` `/api/podcast/feed.xml` ❔

Get RSS podcast feed

### `POST` `/api/v1/debates/*/broadcast` 🔒

Generate podcast audio from a debate trace

### `POST` `/api/v1/debates/*/broadcast/full` ❔

Run the full broadcast pipeline with all options

---

## Handler (features/codebase_audit/handler.py)

Codebase Audit API Handler.

### `GET` `/api/v1/codebase/scan/\{id\}` ❔

Get scan status/results

### `GET` `/api/v1/codebase/scans` ❔

List past scans

### `GET` `/api/v1/codebase/findings` ❔

Get aggregated findings

### `GET` `/api/v1/codebase/dashboard` ❔

Get dashboard data

### `GET` `/api/v1/codebase/scan` ❔

Run bug detection scan

### `GET` `/api/v1/codebase/sast` ❔

Run SAST-only scan

### `GET` `/api/v1/codebase/bugs` ❔

GET /api/v1/codebase/bugs

### `GET` `/api/v1/codebase/secrets` ❔

Run secrets scan

### `GET` `/api/v1/codebase/dependencies` ❔

GET /api/v1/codebase/dependencies

### `GET` `/api/v1/codebase/metrics` ❔

Run code metrics analysis

### `GET` `/api/v1/codebase/findings/\{finding_id\}/dismiss` ❔

Dismiss a finding

### `GET` `/api/v1/codebase/findings/\{finding_id\}/create-issue` ❔

GET /api/v1/codebase/findings/\{finding_id\}/create-issue

### `GET` `/api/v1/codebase/demo` ❔

Get demo dashboard data

---

## Connectors (features/connectors.py)

Handler for enterprise connector endpoints.

### `GET` `/api/v1/connectors` ❔

List all configured connectors

### `GET` `/api/v1/connectors/\{connector_id\}` ❔

GET /api/v1/connectors/\{connector_id\}

### `GET` `/api/v1/connectors/\{connector_id\}/sync` ❔

Cancel a running sync operation

### `GET` `/api/v1/connectors/sync/\{sync_id\}/cancel` ❔

Cancel a running sync operation

### `GET` `/api/v1/connectors/test` ❔

Test a connector configuration without saving

### `GET` `/api/v1/connectors/sync-history` ❔

GET /api/v1/connectors/sync-history

### `GET` `/api/v1/connectors/stats` ❔

Get aggregate statistics for all connectors

### `GET` `/api/v1/connectors/health` ❔

Get health scores for all connectors

### `GET` `/api/v1/connectors/types` ❔

List all available connector types

---

## CRM (features/crm/handler.py)

Handler for CRM platform API endpoints.

### `GET` `/api/v1/crm/platforms` ❔

List all supported CRM platforms and connection status

### `POST` `/api/v1/crm/connect` ❔

Connect a CRM platform with credentials

### `GET` `/api/v1/crm/status` ❔

Get CRM handler status including circuit breaker state

### `DELETE` `/api/v1/crm/\{platform\}` ❔

DELETE /api/v1/crm/\{platform\}

### `GET` `/api/v1/crm/contacts` ❔

GET /api/v1/crm/contacts

### `GET` `/api/v1/crm/\{platform\}/contacts` ❔

GET /api/v1/crm/\{platform\}/contacts

### `GET` `/api/v1/crm/\{platform\}/contacts/\{contact_id\}` ❔

GET /api/v1/crm/\{platform\}/contacts/\{contact_id\}

### `GET` `/api/v1/crm/companies` ❔

GET /api/v1/crm/companies

### `GET` `/api/v1/crm/\{platform\}/companies` ❔

GET /api/v1/crm/\{platform\}/companies

### `GET` `/api/v1/crm/\{platform\}/companies/\{company_id\}` ❔

GET /api/v1/crm/\{platform\}/companies/\{company_id\}

### `GET` `/api/v1/crm/deals` ❔

GET /api/v1/crm/deals

### `GET` `/api/v1/crm/\{platform\}/deals` ❔

GET /api/v1/crm/\{platform\}/deals

### `GET` `/api/v1/crm/\{platform\}/deals/\{deal_id\}` ❔

GET /api/v1/crm/\{platform\}/deals/\{deal_id\}

### `GET` `/api/v1/crm/pipeline` ❔

GET /api/v1/crm/pipeline

### `POST` `/api/v1/crm/sync-lead` ❔

POST /api/v1/crm/sync-lead

### `POST` `/api/v1/crm/enrich` ❔

POST /api/v1/crm/enrich

### `GET` `/api/v1/crm/search` ❔

GET /api/v1/crm/search

---

## Cross Platform Analytics (features/cross_platform_analytics.py)

Cross-Platform Analytics Dashboard Handler.

### `GET` `/api/v1/analytics/cross-platform/summary` ❔

Unified dashboard summary

### `GET` `/api/v1/analytics/cross-platform/metrics` ❔

Aggregated metrics

### `GET` `/api/v1/analytics/cross-platform/trends` ❔

Cross-platform trends

### `GET` `/api/v1/analytics/cross-platform/comparison` ❔

Platform comparison

### `GET` `/api/v1/analytics/cross-platform/correlation` ❔

Metric correlation

### `GET` `/api/v1/analytics/cross-platform/anomalies` ❔

Anomaly detection

### `GET` `/api/v1/analytics/cross-platform/alerts` ❔

Active alerts

### `GET` `/api/v1/analytics/cross-platform/export` ❔

Export data

### `GET` `/api/v1/analytics/cross-platform/demo` ❔

Demo data

### `GET` `/api/v1/analytics/cross-platform/query` ❔

Extract query parameters from request

### `GET` `/api/v1/analytics/cross-platform/alerts/\{alert_id\}/acknowledge` ❔

Acknowledge an alert

---

## Handler (features/devops/handler.py)

DevOps Incident Management API Handler.

### `GET` `/api/v1/incidents` ❔

List incidents

### `GET` `/api/v1/incidents/\{id\}` 🔒

Get incident details

### `GET` `/api/v1/oncall` ❔

Get current on-call

### `GET` `/api/v1/services` ❔

List services

### `GET` `/api/v1/services/\{id\}` ❔

Get service details

### `GET` `/api/v1/devops/status` ❔

Connection status

### `GET` `/api/v1/webhooks/pagerduty` ❔

Handle PagerDuty webhook notifications

---

## Document Query (features/document_query.py)

Document NL Query endpoint handlers.

### `POST` `/api/v1/documents/query` ❔

Answer a natural language question about documents

### `POST` `/api/v1/documents/search` ❔

POST /api/v1/documents/search

### `POST` `/api/v1/documents/summarize` ❔

Run document summarization asynchronously

### `POST` `/api/v1/documents/compare` ❔

Compare multiple documents

### `POST` `/api/v1/documents/extract` ❔

Extract structured information from documents

---

## Documents (features/documents.py)

Document management endpoint handlers.

### `GET` `/api/documents` ❔

List all uploaded documents

### `GET` `/api/documents/formats` ❔

Get supported file formats

### `POST` `/api/documents/upload` 🔒

Upload a document

### `GET` `/api/v1/documents` ❔

List all uploaded documents

### `GET` `/api/v1/documents/formats` ❔

Get list of supported document formats

### `POST` `/api/v1/documents/upload` 🔒

Check IP-based upload rate limit

### `GET` `/api/v1/documents/*` 🔒

GET /api/v1/documents/*

---

## DocumentBatch (features/documents_batch.py)

Handler for batch document upload and processing endpoints.

### `POST` `/api/v1/batch` ❔

Generate unique batch ID

### `GET` `/api/v1/batch/queue/status` ❔

Get status of a batch processing job

### `POST` `/api/v1/documents/batch` ❔

Generate unique batch ID

### `GET` `/api/v1/documents/processing/stats` ❔

Get batch processing statistics

### `GET` `/api/v1/knowledge/jobs` ❔

List all knowledge processing jobs with optional filtering

---

## Ecommerce (features/ecommerce/handler.py)

Handler for e-commerce platform API endpoints with RBAC protection.

### `GET` `/api/v1/ecommerce/platforms` ❔

List all supported e-commerce platforms and connection status

### `POST` `/api/v1/ecommerce/connect` ❔

Connect an e-commerce platform with credentials

### `DELETE` `/api/v1/ecommerce/\{platform\}` ❔

DELETE /api/v1/ecommerce/\{platform\}

### `GET` `/api/v1/ecommerce/orders` ❔

Fetch orders from a specific platform

### `GET` `/api/v1/ecommerce/\{platform\}/orders` ❔

Fetch orders from a specific platform

### `GET` `/api/v1/ecommerce/\{platform\}/orders/\{order_id\}` ❔

GET /api/v1/ecommerce/\{platform\}/orders/\{order_id\}

### `GET` `/api/v1/ecommerce/products` ❔

Fetch products from a specific platform

### `GET` `/api/v1/ecommerce/\{platform\}/products` ❔

Fetch products from a specific platform

### `GET` `/api/v1/ecommerce/\{platform\}/products/\{product_id\}` ❔

GET /api/v1/ecommerce/\{platform\}/products/\{product_id\}

### `GET` `/api/v1/ecommerce/inventory` ❔

Get inventory levels across platforms

### `POST` `/api/v1/ecommerce/sync-inventory` ❔

POST /api/v1/ecommerce/sync-inventory

### `GET` `/api/v1/ecommerce/fulfillment` ❔

Get fulfillment status for orders

### `POST` `/api/v1/ecommerce/ship` ❔

Create a shipment for an order

### `GET` `/api/v1/ecommerce/metrics` ❔

Fetch metrics from a specific platform

### `GET` `/api/v1/ecommerce/circuit-breaker` ❔

GET /api/v1/ecommerce/circuit-breaker

---

## Email Webhooks (features/email_webhooks.py)

Email Webhook Handlers.

### `GET` `/api/v1/webhooks/status` ❔

Get webhook subscription status

### `GET` `/api/v1/webhooks/gmail` ❔

Create Gmail Pub/Sub watch

### `GET` `/api/v1/webhooks/outlook` ❔

Create Outlook Graph subscription

### `GET` `/api/v1/webhooks/outlook/validate` ❔

GET /api/v1/webhooks/outlook/validate

### `GET` `/api/v1/webhooks/subscribe` ❔

Create new webhook subscription

### `GET` `/api/v1/webhooks/unsubscribe` ❔

Remove webhook subscription

### `GET` `/api/v1/webhooks/history` ❔

Get notification history

---

## Evidence (features/evidence.py)

Evidence API Handler.

### `GET` `/api/v1/evidence` ❔

Get or create evidence collector instance with KM adapter

### `GET` `/api/v1/evidence/statistics` ❔

Handle GET /api/evidence/statistics - get store stats

### `POST` `/api/v1/evidence/search` ❔

Handle POST /api/evidence/search - full-text search

### `POST` `/api/v1/evidence/collect` ❔

Get or create evidence collector instance with KM adapter

---

## Evidence Enrichment (features/evidence_enrichment.py)

Evidence Enrichment endpoint handlers.

### `POST` `/api/v1/findings/batch-evidence` ❔

POST /api/v1/findings/batch-evidence

---

## Features (features/features.py)

Handler for feature availability endpoints.

### `GET` `/api/v1/features` ❔

Get full feature matrix

### `GET` `/api/v1/features/all` ❔

Get flat list of all API endpoints

### `GET` `/api/v1/features/available` ❔

Get list of available features

### `GET` `/api/v1/features/config` ❔

Get user's feature configuration

### `GET` `/api/v1/features/discover` ❔

Get comprehensive API discovery catalog

### `GET` `/api/v1/features/endpoints` ❔

Get flat list of all API endpoints

### `GET` `/api/v1/features/handlers` ❔

GET /api/v1/features/handlers

### `GET` `/api/v1/features/*` 🔒

GET /api/v1/features/*

### `GET` `/api/features` ❔

Get flat list of all API endpoints

### `GET` `/api/features/all` ❔

Get flat list of all API endpoints

### `GET` `/api/features/available` ❔

Get list of available features

### `GET` `/api/features/config` ❔

Get user's feature configuration

### `GET` `/api/features/discover` ❔

Get flat list of all API endpoints

### `GET` `/api/features/endpoints` ❔

Get flat list of all API endpoints

### `GET` `/api/features/handlers` ❔

GET /api/features/handlers

---

## Finding Workflow (features/finding_workflow.py)

Finding Workflow API Handler.

### `GET` `/api/v1/audit/findings/\{finding_id\}/status` ❔

Update finding workflow state

### `GET` `/api/v1/audit/findings/\{finding_id\}/assign` ❔

Assign finding to a user

### `GET` `/api/v1/audit/findings/\{finding_id\}/unassign` ❔

Remove assignment from finding

### `GET` `/api/v1/audit/findings/\{finding_id\}/comments` ❔

Get all comments for a finding

### `GET` `/api/v1/audit/findings/\{finding_id\}/history` ❔

Get full workflow history for a finding

### `GET` `/api/v1/audit/findings/\{finding_id\}/priority` ❔

Set finding priority

### `GET` `/api/v1/audit/findings/\{finding_id\}/due-date` ❔

GET /api/v1/audit/findings/\{finding_id\}/due-date

### `GET` `/api/v1/audit/findings/\{finding_id\}/link` ❔

Link this finding to another

### `GET` `/api/v1/audit/findings/\{finding_id\}/duplicate` ❔

Mark finding as duplicate of another

### `GET` `/api/v1/audit/findings/bulk-action` ❔

GET /api/v1/audit/findings/bulk-action

### `GET` `/api/v1/audit/findings/my-assignments` ❔

GET /api/v1/audit/findings/my-assignments

### `GET` `/api/v1/audit/findings/overdue` ❔

Get all overdue findings

### `GET` `/api/v1/audit/workflow/states` ❔

Get valid workflow states and transitions

### `GET` `/api/v1/audit/presets` ❔

Get available audit presets

### `GET` `/api/v1/audit/types` ❔

Get registered audit types

---

## Folder Upload (features/folder_upload.py)

Folder upload endpoint handlers.

### `POST` `/api/v1/documents/folder/scan` ❔

Scan a folder and return what would be uploaded

### `POST` `/api/v1/documents/folder/upload` ❔

Get status of a folder upload job

### `GET` `/api/v1/documents/folders` ❔

List all folder upload jobs

---

## Gmail Ingest (features/gmail_ingest.py)

Gmail inbox ingestion handler.

### `POST` `/api/v1/gmail/connect` ❔

Disconnect Gmail account

### `POST` `/api/v1/gmail/auth/url` ❔

Generate OAuth authorization URL

### `POST` `/api/v1/gmail/auth/callback` ❔

Handle OAuth callback (GET)

### `POST` `/api/v1/gmail/callback` ❔

Handle OAuth callback (GET)

### `POST` `/api/v1/gmail/connection` ❔

POST /api/v1/gmail/connection

### `POST` `/api/v1/gmail/sync` ❔

Get sync status for user

### `POST` `/api/v1/gmail/sync/status` ❔

Get connection status for user

### `POST` `/api/v1/gmail/messages` ❔

List indexed messages for user

### `POST` `/api/v1/gmail/search` ❔

Search emails

### `POST` `/api/v1/gmail/disconnect` ❔

Disconnect Gmail account

### `POST` `/api/v1/gmail/status` ❔

Get connection status for user

### `POST` `/api/v1/gmail/stats` ❔

POST /api/v1/gmail/stats

### `POST` `/api/v1/gmail/processed` ❔

POST /api/v1/gmail/processed

### `POST` `/api/v1/gmail/triage-rules` ❔

POST /api/v1/gmail/triage-rules

### `POST` `/api/v1/gmail/debate-configs` ❔

POST /api/v1/gmail/debate-configs

---

## GmailLabels (features/gmail_labels.py)

Handler for Gmail labels and message modification endpoints.

### `GET` `/api/v1/gmail/labels`

Modify message labels via Gmail API

### `POST` `/api/v1/gmail/labels`

Modify message labels via Gmail API

### `GET` `/api/v1/gmail/filters`

List filters via Gmail API

### `POST` `/api/v1/gmail/filters`

List filters via Gmail API

---

## Gmail Query (features/gmail_query.py)

Gmail Q&A query handler.

### `POST` `/api/v1/gmail/query` ❔

Handle natural language query over email content

### `POST` `/api/v1/gmail/query/voice` ❔

Handle voice input query

### `POST` `/api/v1/gmail/query/stream` ❔

POST /api/v1/gmail/query/stream

### `POST` `/api/v1/gmail/inbox/priority` ❔

Get prioritized inbox list

### `POST` `/api/v1/gmail/inbox/feedback` ❔

Record user feedback on email interaction

---

## GmailThreads (features/gmail_threads.py)

Handler for Gmail threads and drafts endpoints.

### `GET` `/api/v1/gmail/threads`

List threads via Gmail API

### `GET` `/api/v1/gmail/drafts`

List drafts via Gmail API

### `POST` `/api/v1/gmail/drafts`

List drafts via Gmail API

---

## Integrations (features/integrations.py)

Handler for integration management endpoints.

### `GET` `/api/v1/integrations` ❔

GET /api/v1/integrations

### `POST` `/api/v1/integrations` ❔

POST /api/v1/integrations

### `GET` `/api/v1/integrations/status` ❔

GET /api/v1/integrations/status

### `GET` `/api/v1/integrations/available` ❔

GET /api/v1/integrations/available

### `POST` `/api/v1/integrations/config` ❔

POST /api/v1/integrations/config

### `GET` `/api/v1/integrations/config/*` ❔

GET /api/v1/integrations/config/*

### `PUT` `/api/v1/integrations/config/*` ❔

PUT /api/v1/integrations/config/*

### `DELETE` `/api/v1/integrations/config/*` ❔

DELETE /api/v1/integrations/config/*

### `GET` `/api/v1/integrations/*` ❔

GET /api/v1/integrations/*

### `PUT` `/api/v1/integrations/*` ❔

PUT /api/v1/integrations/*

### `PATCH` `/api/v1/integrations/*` ❔

PATCH /api/v1/integrations/*

### `DELETE` `/api/v1/integrations/*` ❔

DELETE /api/v1/integrations/*

### `POST` `/api/v1/integrations/*/sync` ❔

Perform provider-specific sync operations

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `integration_type` | string | Type of integration |
| `config` | string | Current integration configuration |

### `POST` `/api/v1/integrations/*/test` ❔

Test connection to integration provider

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `integration_type` | string | Type of integration |
| `settings` | string | Provider settings |

---

## Legal (features/legal.py)

Legal E-Signature API Handler.

### `GET` `/api/v1/legal/envelopes` ❔

List envelopes

### `GET` `/api/v1/legal/envelopes/\{id\}` ❔

Get envelope details

### `GET` `/api/v1/legal/envelopes/\{id\}/documents/\{doc_id\}` ❔

Download document

### `GET` `/api/v1/legal/envelopes/\{id\}/certificate` ❔

Download certificate

### `GET` `/api/v1/legal/status` ❔

Connection status

### `GET` `/api/v1/legal/envelopes/\{envelope_id\}/void` ❔

Void an envelope

### `GET` `/api/v1/legal/envelopes/\{envelope_id\}/resend` ❔

Resend envelope notifications to recipients

### `GET` `/api/v1/legal/webhooks/docusign` ❔

Handle DocuSign Connect webhook notifications

### `GET` `/api/v1/legal/templates` ❔

List available DocuSign templates

---

## Handler (features/marketplace/handler.py)

Marketplace Handler - Template discovery and deployment.

### `GET` `/api/v1/marketplace/templates` ❔

List all available templates

### `GET` `/api/v1/marketplace/templates/\{id\}` ❔

Get template details

### `GET` `/api/v1/marketplace/categories` ❔

List template categories

### `GET` `/api/v1/marketplace/search` ❔

Search templates

### `GET` `/api/v1/marketplace/deployments` ❔

List deployed templates

### `GET` `/api/v1/marketplace/popular` ❔

Get popular templates

### `GET` `/api/v1/marketplace/demo` ❔

Get demo marketplace data

### `GET` `/api/v1/marketplace/status` ❔

Circuit breaker and health status

### `GET` `/api/v1/marketplace/templates/search` ❔

Search templates by query

### `GET` `/api/v1/marketplace/templates/\{template_id\}/deploy` ❔

Archive a deployment

### `GET` `/api/v1/marketplace/templates/\{template_id\}/rate` ❔

Rate a template

### `GET` `/api/v1/marketplace/deployments/\{deployment_id\}` ❔

GET /api/v1/marketplace/deployments/\{deployment_id\}

### `GET` `/api/v1/marketplace/my-deployments` ❔

GET /api/v1/marketplace/my-deployments

---

## Outlook (features/outlook.py)

Outlook/Microsoft 365 Email Handler.

### `GET` `/api/v1/outlook/oauth/url`

Get OAuth authorization URL

### `POST` `/api/v1/outlook/oauth/callback`

Handle OAuth callback

### `GET` `/api/v1/outlook/folders`

List mail folders

### `GET` `/api/v1/outlook/messages`

List messages

### `GET` `/api/v1/outlook/messages/\{id\}`

Get message details

### `GET` `/api/v1/outlook/conversations/\{id\}`

Get conversation thread

### `POST` `/api/v1/outlook/send`

Send new message

### `POST` `/api/v1/outlook/reply`

Reply to message

### `GET` `/api/v1/outlook/search`

Search messages

### `POST` `/api/v1/outlook/messages/\{id\}/read`

Mark as read/unread

### `POST` `/api/v1/outlook/messages/\{id\}/move`

Move message

### `DELETE` `/api/v1/outlook/messages/\{id\}`

Delete message

### `GET` `/api/v1/outlook/messages/reply` ❔

GET /api/v1/outlook/messages/reply

### `GET` `/api/v1/outlook/messages/search` ❔

GET /api/v1/outlook/messages/search

### `GET` `/api/v1/outlook/messages/send` ❔

GET /api/v1/outlook/messages/send

### `GET` `/api/v1/outlook/status`

GET /api/v1/outlook/status

---

## Plugins (features/plugins.py)

Plugins endpoint handlers.

### `GET` `/api/plugins` 🔒

List all available plugins

### `GET` `/api/plugins/\{name\}` ❔

Get details for a specific plugin

### `POST` `/api/plugins/\{name\}/run` 🔒

Run a plugin with provided input

### `GET` `/api/plugins/installed` 🔒

List installed plugins for user/org

### `POST` `/api/plugins/\{name\}/install` 🔒

Install a plugin

### `DELETE` `/api/plugins/\{name\}/install` 🔒

Uninstall a plugin

### `POST` `/api/plugins/submit` 🔒

Submit a new plugin for review

### `GET` `/api/plugins/submissions` 🔒

List user's plugin submissions

### `GET` `/api/v1/plugins` ❔

Check if path uses legacy (non-versioned) format

### `GET` `/api/v1/plugins/installed` 🔒

List installed plugins for the authenticated user

### `GET` `/api/v1/plugins/marketplace` ❔

Get marketplace listings with categorized plugins

### `POST` `/api/v1/plugins/submit` 🔒

Submit a new plugin for marketplace review

### `GET` `/api/v1/plugins/submissions` 🔒

List plugin submissions for the authenticated user

### `GET` `/api/v1/plugins/*` ❔

GET /api/v1/plugins/*

### `POST` `/api/v1/plugins/*/install` 🔒

Install a plugin for the authenticated user

### `DELETE` `/api/v1/plugins/*/install` 🔒

Install a plugin for the authenticated user

### `POST` `/api/v1/plugins/*/run` 🔒

Run a plugin with provided input

### `POST` `/api/v1/plugins/query` ❔

POST /api/v1/plugins/query

### `POST` `/api/v1/plugins/validate` ❔

POST /api/v1/plugins/validate

### `GET` `/api/plugins/marketplace` ❔

Get marketplace listings with categorized plugins

---

## Pulse (features/pulse.py)

Pulse and trending topics endpoint handlers.

### `GET` `/api/pulse/trending` ❔

Get trending topics from multiple sources

### `GET` `/api/pulse/suggest` ❔

Suggest a trending topic for debate

### `GET` `/api/v1/pulse/trending` ❔

Get trending topics from multiple pulse ingestors

### `GET` `/api/v1/pulse/suggest` ❔

Suggest a trending topic for debate

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `category` | string | Optional category filter (tech, ai, science, etc.) Returns topic suitable for debate with prompt formatting. Results are cached for 5 minutes per category. |

### `GET` `/api/v1/pulse/analytics` ❔

Get analytics on trending topic debate outcomes

### `POST` `/api/v1/pulse/debate-topic` ❔

POST /api/v1/pulse/debate-topic

### `GET` `/api/v1/pulse/scheduler/status` ❔

Get current scheduler status

### `POST` `/api/v1/pulse/scheduler/start` ❔

Start a debate on a trending topic

### `POST` `/api/v1/pulse/scheduler/stop` ❔

Stop the pulse debate scheduler

### `POST` `/api/v1/pulse/scheduler/pause` ❔

Pause the pulse debate scheduler

### `POST` `/api/v1/pulse/scheduler/resume` ❔

Resume the pulse debate scheduler

### `PATCH` `/api/v1/pulse/scheduler/config` ❔

Update scheduler configuration

### `GET` `/api/v1/pulse/scheduler/history` ❔

Get scheduled debate history

### `GET` `/api/v1/pulse/scheduler/analytics` ❔

Get analytics on trending topic debate outcomes

---

## Reconciliation (features/reconciliation.py)

Bank Reconciliation API Handler.

### `POST` `/api/v1/reconciliation/run`

Run new reconciliation

### `GET` `/api/v1/reconciliation/list` ❔

List past reconciliations

### `GET` `/api/v1/reconciliation/\{id\}` ❔

Get reconciliation details

### `GET` `/api/v1/reconciliation/\{id\}/report` ❔

Generate PDF report

### `POST` `/api/v1/reconciliation/\{id\}/resolve`

Resolve a discrepancy

### `POST` `/api/v1/reconciliation/\{id\}/approve`

Approve reconciliation

### `GET` `/api/v1/reconciliation/discrepancies` ❔

Get all pending discrepancies

### `POST` `/api/v1/reconciliation/discrepancies/bulk-resolve`

Bulk resolve

### `GET` `/api/v1/reconciliation/demo` ❔

Get demo reconciliation data

### `GET` `/api/v1/reconciliation/status` ❔

Get circuit breaker and service status

---

## Rlm (features/rlm.py)

RLM (Recursive Language Model) endpoint handlers.

### `POST` `/api/v1/debates/\{debate_id\}/query-rlm` ❔

POST /api/v1/debates/\{debate_id\}/query-rlm

### `POST` `/api/v1/debates/\{debate_id\}/compress` ❔

Compress a debate into hierarchical context

### `POST` `/api/v1/debates/\{debate_id\}/context/\{level\}` ❔

POST /api/v1/debates/\{debate_id\}/context/\{level\}

### `POST` `/api/v1/debates/\{debate_id\}/refinement-status` ❔

POST /api/v1/debates/\{debate_id\}/refinement-status

### `POST` `/api/v1/knowledge/query-rlm` ❔

POST /api/v1/knowledge/query-rlm

### `POST` `/api/v1/rlm/status` ❔

Get status of an ongoing refinement process

### `GET` `/api/v1/rlm/codebase/health` ❔

GET /api/v1/rlm/codebase/health

### `POST` `/api/v1/rlm/compress` ❔

Compress a debate into hierarchical context

### `GET` `/api/v1/rlm/contexts` ❔

GET /api/v1/rlm/contexts

### `POST` `/api/v1/rlm/query` ❔

Execute RLM query against knowledge mound

### `GET` `/api/v1/rlm/stats` ❔

GET /api/v1/rlm/stats

### `GET` `/api/v1/rlm/strategies` ❔

GET /api/v1/rlm/strategies

### `POST` `/api/v1/rlm/stream` ❔

POST /api/v1/rlm/stream

### `GET` `/api/v1/rlm/stream/modes` ❔

GET /api/v1/rlm/stream/modes

### `POST` `/api/v1/metrics/rlm` ❔

Execute RLM query with refinement loop

---

## RoutingRules (features/routing_rules.py)

Handler for routing rules CRUD and evaluation endpoints.

### `GET` `/api/v1/routing-rules` ❔

GET /api/v1/routing-rules

### `GET` `/api/v1/routing-rules/\{rule_id\}` ❔

GET /api/v1/routing-rules/\{rule_id\}

### `GET` `/api/v1/routing-rules/\{rule_id\}/toggle` ❔

Toggle a rule's enabled state

### `GET` `/api/v1/routing-rules/evaluate` ❔

Evaluate rules against a context for testing

### `GET` `/api/v1/routing-rules/templates` ❔

Get predefined rule templates

---

## Support (features/support.py)

Handler for support platform API endpoints.

### `GET` `/api/v1/support/platforms` ❔

List all supported support platforms and connection status

### `POST` `/api/v1/support/connect` ❔

Connect a support platform with credentials

### `DELETE` `/api/v1/support/\{platform\}` ❔

DELETE /api/v1/support/\{platform\}

### `GET` `/api/v1/support/tickets` ❔

Fetch tickets from a specific platform

### `POST` `/api/v1/support/\{platform\}/tickets` ❔

Fetch tickets from a specific platform

### `PUT` `/api/v1/support/\{platform\}/tickets/\{ticket_id\}` ❔

PUT /api/v1/support/\{platform\}/tickets/\{ticket_id\}

### `POST` `/api/v1/support/\{platform\}/tickets/\{ticket_id\}/reply` ❔

Reply to a ticket

### `GET` `/api/v1/support/metrics` ❔

Fetch metrics from a specific platform

### `POST` `/api/v1/support/triage` ❔

AI-powered ticket triage using multi-agent analysis

### `POST` `/api/v1/support/auto-respond` ❔

POST /api/v1/support/auto-respond

### `GET` `/api/v1/support/search` ❔

Coerce search platform inputs to a normalized list of platform ids

---

## Transcription (features/transcription.py)

Audio/Video transcription endpoint handlers.

### `POST` `/api/v1/transcription/upload` ❔

Parse raw file upload with X-Filename header

### `POST` `/api/v1/transcription/formats` ❔

Get list of supported audio/video formats

### `POST` `/api/v1/transcription/status` ❔

Get transcription job status and result

---

## Handler (features/unified_inbox/handler.py)

Unified Inbox API Handler.

### `GET` `/api/v1/inbox/oauth/gmail` 🔒

Get Gmail OAuth URL (redirect_uri required)

### `GET` `/api/v1/inbox/oauth/outlook` 🔒

Get Outlook OAuth URL (redirect_uri required)

### `POST` `/api/v1/inbox/connect` 🔒

Connect Gmail or Outlook account

### `GET` `/api/v1/inbox/accounts` 🔒

List connected accounts

### `DELETE` `/api/v1/inbox/accounts/\{id\}` 🔒

Disconnect an account

### `GET` `/api/v1/inbox/messages` 🔒

Get prioritized messages across accounts

### `GET` `/api/v1/inbox/messages/\{id\}` 🔒

Get single message details

### `POST` `/api/v1/inbox/messages/\{id\}/debate` 🔒

Stage receipt-backed review for a message

### `POST` `/api/v1/inbox/triage` 🔒

Multi-agent triage for messages

### `POST` `/api/v1/inbox/bulk-action` 🔒

Bulk actions (archive, read, etc.)

### `GET` `/api/v1/inbox/stats` 🔒

Inbox health metrics

### `GET` `/api/v1/inbox/trends` 🔒

Priority trends over time

---

## Status (federation/status.py)

Federation status and management endpoints.

### `GET` `/api/v1/federation/status` 🔒

Get federation overview status

### `GET` `/api/v1/federation/workspaces` 🔒

List connected workspaces with health

### `GET` `/api/v1/federation/activity` 🔒

Get recent sync activity feed

### `GET` `/api/v1/federation/config` 🔒

Get federation configuration

---

## Accounting (finance/accounting.py)

Accounting handlers for QuickBooks Online and Gusto payroll integration.

### `GET` `/api/accounting/status`

QuickBooks status + dashboard data

### `GET` `/api/accounting/connect`

Start QuickBooks OAuth

### `GET` `/api/accounting/callback`

QuickBooks OAuth callback

### `POST` `/api/accounting/disconnect`

Disconnect QuickBooks

### `GET` `/api/accounting/customers`

List QuickBooks customers

### `GET` `/api/accounting/transactions`

List QuickBooks transactions

### `POST` `/api/accounting/report`

Generate accounting report

### `GET` `/api/accounting/gusto/status`

Gusto connection status

### `GET` `/api/accounting/gusto/connect`

Start Gusto OAuth

### `GET` `/api/accounting/gusto/callback`

Gusto OAuth callback

### `POST` `/api/accounting/gusto/disconnect`

Disconnect Gusto

### `GET` `/api/accounting/gusto/employees`

List employees

### `GET` `/api/accounting/gusto/payrolls`

List payroll runs

### `GET` `/api/accounting/gusto/payrolls/\{payroll_id\}`

Payroll run details

### `POST` `/api/accounting/gusto/payrolls/\{payroll_id\}/journal-entry`

Generate journal entry

### `GET` `/api/v1/accounting/status`

GET /api/v1/accounting/status

### `GET` `/api/v1/accounting/connect`

GET /api/v1/accounting/connect

### `GET` `/api/v1/accounting/callback`

GET /api/v1/accounting/callback

### `GET` `/api/v1/accounting/customers`

GET /api/v1/accounting/customers

### `GET` `/api/v1/accounting/transactions`

GET /api/v1/accounting/transactions

### `GET` `/api/v1/accounting/reports` 🔒

GET /api/v1/accounting/reports

### `POST` `/api/v1/accounting/disconnect`

POST /api/v1/accounting/disconnect

### `POST` `/api/v1/accounting/report`

POST /api/v1/accounting/report

### `GET` `/api/v1/accounting/gusto/status`

GET /api/v1/accounting/gusto/status

### `GET` `/api/v1/accounting/gusto/employees`

GET /api/v1/accounting/gusto/employees

### `GET` `/api/v1/accounting/gusto/payrolls`

GET /api/v1/accounting/gusto/payrolls

### `GET` `/api/v1/accounting/gusto/connect`

GET /api/v1/accounting/gusto/connect

### `GET` `/api/v1/accounting/gusto/callback`

GET /api/v1/accounting/gusto/callback

### `POST` `/api/v1/accounting/gusto/disconnect`

POST /api/v1/accounting/gusto/disconnect

### `POST` `/api/v1/gusto/connect` 🔒

POST /api/v1/gusto/connect

### `POST` `/api/v1/gusto/disconnect` 🔒

POST /api/v1/gusto/disconnect

### `GET` `/api/v1/gusto/employees` 🔒

GET /api/v1/gusto/employees

### `GET` `/api/v1/gusto/payrolls` 🔒

GET /api/v1/gusto/payrolls

### `GET` `/api/v1/gusto/status` 🔒

GET /api/v1/gusto/status

### `GET` `/api/v1/ap/batch-payments` 🔒

GET /api/v1/ap/batch-payments

### `GET` `/api/v1/ap/cash-flow` 🔒

GET /api/v1/ap/cash-flow

### `GET` `/api/v1/ap/discount-opportunities` 🔒

GET /api/v1/ap/discount-opportunities

### `GET` `/api/v1/ap/invoices` 🔒

GET /api/v1/ap/invoices

### `GET` `/api/v1/ap/optimize` 🔒

GET /api/v1/ap/optimize

---

## Ap Automation (finance/ap_automation.py)

HTTP API Handlers for Accounts Payable Automation.

### `POST` `/api/v1/accounting/ap/invoices` ❔

Add payable invoice

### `GET` `/api/v1/accounting/ap/invoices` ❔

List payable invoices

### `GET` `/api/v1/accounting/ap/invoices/\{id\}` ❔

Get invoice by ID

### `POST` `/api/v1/accounting/ap/invoices/\{id\}/payment` ❔

Record payment

### `POST` `/api/v1/accounting/ap/optimize` ❔

Optimize payment timing

### `POST` `/api/v1/accounting/ap/batch` ❔

Create batch payment

### `GET` `/api/v1/accounting/ap/forecast` ❔

Get cash flow forecast

### `GET` `/api/v1/accounting/ap/discounts` ❔

Get discount opportunities

---

## Ar Automation (finance/ar_automation.py)

HTTP API Handlers for Accounts Receivable Automation.

### `POST` `/api/v1/accounting/ar/invoices` ❔

Create invoice

### `GET` `/api/v1/accounting/ar/invoices` ❔

List invoices

### `GET` `/api/v1/accounting/ar/invoices/\{id\}` ❔

Get invoice by ID

### `POST` `/api/v1/accounting/ar/invoices/\{id\}/send` ❔

Send invoice to customer

### `POST` `/api/v1/accounting/ar/invoices/\{id\}/reminder` ❔

Send payment reminder

### `POST` `/api/v1/accounting/ar/invoices/\{id\}/payment` ❔

Record payment

### `GET` `/api/v1/accounting/ar/aging` ❔

Get AR aging report

### `GET` `/api/v1/accounting/ar/collections` ❔

Get collection suggestions

### `POST` `/api/v1/accounting/ar/customers` ❔

Add customer

### `GET` `/api/v1/accounting/ar/customers/\{id\}/balance` ❔

Get customer balance

---

## Expenses (finance/expenses.py)

HTTP API Handlers for Expense Tracking.

### `POST` `/api/v1/accounting/expenses/upload` ❔

Upload and process receipt

### `POST` `/api/v1/accounting/expenses` ❔

Create expense manually

### `GET` `/api/v1/accounting/expenses` ❔

List expenses with filters

### `GET` `/api/v1/accounting/expenses/\{id\}` ❔

Get expense by ID

### `PUT` `/api/v1/accounting/expenses/\{id\}` ❔

Update expense

### `DELETE` `/api/v1/accounting/expenses/\{id\}` ❔

Delete expense

### `POST` `/api/v1/accounting/expenses/\{id\}/approve` ❔

Approve expense

### `POST` `/api/v1/accounting/expenses/\{id\}/reject` ❔

Reject expense

### `POST` `/api/v1/accounting/expenses/categorize` ❔

Auto-categorize expenses

### `POST` `/api/v1/accounting/expenses/sync` ❔

Sync expenses to QBO

### `GET` `/api/v1/accounting/expenses/stats` ❔

Get expense statistics

### `GET` `/api/v1/accounting/expenses/pending` ❔

Get pending approvals

### `GET` `/api/v1/accounting/expenses/export` ❔

Export expenses

---

## Invoices (finance/invoices.py)

HTTP API Handlers for Invoice Processing.

### `POST` `/api/v1/accounting/invoices/upload` ❔

Upload and extract invoice

### `POST` `/api/v1/accounting/invoices` ❔

Create invoice manually

### `GET` `/api/v1/accounting/invoices` ❔

List invoices with filters

### `GET` `/api/v1/accounting/invoices/\{id\}` ❔

Get invoice by ID

### `POST` `/api/v1/accounting/invoices/\{id\}/approve` ❔

Approve invoice

### `POST` `/api/v1/accounting/invoices/\{id\}/reject` ❔

Reject invoice

### `POST` `/api/v1/accounting/invoices/\{id\}/match` ❔

Match to PO

### `POST` `/api/v1/accounting/invoices/\{id\}/schedule` ❔

Schedule payment

### `GET` `/api/v1/accounting/invoices/\{id\}/anomalies` ❔

Get anomalies

### `GET` `/api/v1/accounting/invoices/pending` ❔

Get pending approvals

### `GET` `/api/v1/accounting/invoices/overdue` ❔

Get overdue invoices

### `GET` `/api/v1/accounting/invoices/stats` ❔

Get statistics

### `POST` `/api/v1/accounting/purchase-orders` ❔

Add purchase order

### `GET` `/api/v1/accounting/payments/scheduled` ❔

Get scheduled payments

### `GET` `/api/v1/accounting/invoices/status` ❔

GET /api/v1/accounting/invoices/status

---

## A2A (gateway/a2a.py)

A2A Protocol HTTP Handler.

### `GET` `/api/v1/a2a/.well-known/agent.json` 🔒

GET /api/v1/a2a/.well-known/agent.json

### `GET` `/.well-known/agent.json` ❔

GET /.well-known/agent.json

### `GET` `/api/v1/a2a/agents` 🔒

List all available agents

### `GET` `/api/v1/a2a/agents/*` 🔒

GET /api/v1/a2a/agents/*

### `POST` `/api/v1/a2a/tasks` 🔒

POST /api/v1/a2a/tasks

### `GET` `/api/v1/a2a/tasks/*` 🔒

GET /api/v1/a2a/tasks/*

### `DELETE` `/api/v1/a2a/tasks/*` 🔒

DELETE /api/v1/a2a/tasks/*

### `GET` `/api/v1/a2a/openapi.json` 🔒

GET /api/v1/a2a/openapi.json

---

## GatewayAgents (gateway/gateway_agents_handler.py)

HTTP request handler for external agent registration endpoints.

### `POST` `/api/v1/gateway/agents` ❔

Extract agent name from path like /api/v1/gateway/agents/\{name\}

### `DELETE` `/api/v1/gateway/agents` ❔

Extract agent name from path like /api/v1/gateway/agents/\{name\}

### `GET` `/api/v1/gateway/agents/*` 🔒

GET /api/v1/gateway/agents/*

---

## GatewayConfig (gateway/gateway_config_handler.py)

HTTP handler for gateway configuration endpoints.

### `POST` `/api/v1/gateway/config` ❔

Handle GET /api/v1/gateway/config

### `POST` `/api/v1/gateway/config/defaults` ❔

Handle GET /api/v1/gateway/config/defaults

---

## GatewayCredentials (gateway/gateway_credentials_handler.py)

HTTP request handler for gateway credential management endpoints.

### `POST` `/api/v1/gateway/credentials` ❔

Extract credential ID from path like /api/v1/gateway/credentials/\{id\}

### `DELETE` `/api/v1/gateway/credentials` ❔

Extract credential ID from path like /api/v1/gateway/credentials/\{id\}

### `GET` `/api/v1/gateway/credentials/*` 🔒

GET /api/v1/gateway/credentials/*

---

## Gateway (gateway/gateway_handler.py)

HTTP request handler for gateway API endpoints.

### `GET` `/api/v1/gateway/devices` ❔

Handle GET /api/v1/gateway/devices/\{id\}

### `POST` `/api/v1/gateway/devices` ❔

Handle GET /api/v1/gateway/devices/\{id\}

### `GET` `/api/v1/gateway/devices/*` ❔

GET /api/v1/gateway/devices/*

### `PUT` `/api/v1/gateway/devices/*` ❔

PUT /api/v1/gateway/devices/*

### `DELETE` `/api/v1/gateway/devices/*` ❔

DELETE /api/v1/gateway/devices/*

### `GET` `/api/v1/gateway/channels` ❔

Handle GET /api/v1/gateway/channels

### `POST` `/api/v1/gateway/channels` ❔

Handle GET /api/v1/gateway/channels

### `GET` `/api/v1/gateway/routing` ❔

Handle GET /api/v1/gateway/routing/rules

### `POST` `/api/v1/gateway/routing` ❔

Handle GET /api/v1/gateway/routing/rules

### `GET` `/api/v1/gateway/routing/*` ❔

GET /api/v1/gateway/routing/*

### `PUT` `/api/v1/gateway/routing/*` ❔

PUT /api/v1/gateway/routing/*

### `DELETE` `/api/v1/gateway/routing/*` ❔

DELETE /api/v1/gateway/routing/*

### `GET` `/api/v1/gateway/routing/rules` ❔

Handle GET /api/v1/gateway/routing/rules

### `GET` `/api/v1/gateway/routing/stats` ❔

Handle GET /api/v1/gateway/routing/stats

### `GET` `/api/v1/gateway/messages` ❔

Handle POST /api/v1/gateway/messages/route

### `POST` `/api/v1/gateway/messages` ❔

Handle POST /api/v1/gateway/messages/route

### `GET` `/api/v1/gateway/messages/*` ❔

GET /api/v1/gateway/messages/*

### `DELETE` `/api/v1/gateway/messages/*` ❔

DELETE /api/v1/gateway/messages/*

### `POST` `/api/v1/gateway/messages/route` ❔

Get or create agent router

---

## GatewayHealth (gateway/gateway_health_handler.py)

HTTP handler for gateway health endpoints.

### `GET` `/api/v1/gateway/health` ❔

Handle GET /api/v1/gateway/agents/\{name\}/health

### `GET` `/api/v1/gateway/agents/*/health` ❔

Handle GET /api/v1/gateway/agents/\{name\}/health

---

## Gauntlet (gauntlet/handler.py)

Handler for gauntlet stress-testing endpoints.

### `GET` `/api/gauntlet/run` ❔

GET /api/gauntlet/run

### `GET` `/api/gauntlet/personas` ❔

GET /api/gauntlet/personas

### `GET` `/api/gauntlet/results` ❔

GET /api/gauntlet/results

### `GET` `/api/gauntlet/receipts` ❔

GET /api/gauntlet/receipts

### `GET` `/api/gauntlet/*/receipt/verify` ❔

GET /api/gauntlet/*/receipt/verify

### `GET` `/api/gauntlet/*/receipt` ❔

GET /api/gauntlet/*/receipt

### `GET` `/api/gauntlet/*/heatmap` ❔

GET /api/gauntlet/*/heatmap

### `GET` `/api/gauntlet/*/export` ❔

GET /api/gauntlet/*/export

### `GET` `/api/v1/gauntlet/run` ❔

GET /api/v1/gauntlet/run

### `POST` `/api/v1/gauntlet/run` 🔒

POST /api/v1/gauntlet/run

### `GET` `/api/v1/gauntlet/personas` ❔

GET /api/v1/gauntlet/personas

### `GET` `/api/v1/gauntlet/results` ❔

GET /api/v1/gauntlet/results

### `POST` `/api/v1/gauntlet/*/receipt/verify` 🔒

POST /api/v1/gauntlet/*/receipt/verify

### `GET` `/api/v1/gauntlet/*/receipt` 🔒

GET /api/v1/gauntlet/*/receipt

### `GET` `/api/v1/gauntlet/*/heatmap` 🔒

GET /api/v1/gauntlet/*/heatmap

### `GET` `/api/v1/gauntlet/*/export` 🔒

GET /api/v1/gauntlet/*/export

### `GET` `/api/v1/gauntlet/*/compare/*` ❔

GET /api/v1/gauntlet/*/compare/*

### `GET` `/api/v1/gauntlet/*` ❔

Normalize path by removing version prefix for routing logic

### `DELETE` `/api/v1/gauntlet/*` 🔒

Normalize path by removing version prefix for routing logic

### `GET` `/api/v1/gauntlet` ❔

Normalize path by removing version prefix for routing logic

### `GET` `/api/v1/gauntlet/heatmaps` ❔

GET /api/v1/gauntlet/heatmaps

### `GET` `/api/v1/gauntlet/receipts` ❔

GET /api/v1/gauntlet/receipts

### `POST` `/api/v1/gauntlet/receipts/export/bundle` ❔

POST /api/v1/gauntlet/receipts/export/bundle

### `GET` `/api/v1/receipts/recent-anchors` 🔒

GET /api/v1/receipts/recent-anchors

### `GET` `/api/v1/receipts/*/anchor-status` 🔒

GET /api/v1/receipts/*/anchor-status

---

## Audit Bridge (github/audit_bridge.py)

Audit-to-GitHub Bridge Handler.

### `POST` `/api/v1/github/audit/issues`

Create issues from findings

### `POST` `/api/v1/github/audit/issues/bulk`

Bulk create issues

### `POST` `/api/v1/github/audit/pr`

Create PR with fixes

### `GET` `/api/v1/github/audit/sync/\{session_id\}`

Get sync status

### `POST` `/api/v1/github/audit/sync/\{session_id\}`

Sync session to GitHub

---

## Pr Review (github/pr_review.py)

HTTP API Handlers for GitHub Pull Request Review.

### `POST` `/api/v1/github/pr/review`

Trigger PR review

### `GET` `/api/v1/github/pr/\{pr_number\}`

Get PR details

### `POST` `/api/v1/github/pr/\{pr_number\}/review`

Submit review

### `GET` `/api/v1/github/pr/\{pr_number\}/reviews`

List reviews

---

## UnifiedApprovals (governance/approvals_inbox.py)

Aggregate approval requests across subsystems.

### `GET` `/api/v1/approvals` ❔

GET /api/v1/approvals

### `GET` `/api/v1/approvals/pending` ❔

GET /api/v1/approvals/pending

---

## Moderation (governance/moderation.py)

Handler for moderation configuration and review queue.

### `GET` `/api/moderation/config` ❔

GET /api/moderation/config

### `PUT` `/api/moderation/config` ❔

PUT /api/moderation/config

### `GET` `/api/moderation/stats` ❔

GET /api/moderation/stats

### `GET` `/api/moderation/queue` ❔

GET /api/moderation/queue

### `POST` `/api/moderation/items/*/approve` ❔

POST /api/moderation/items/*/approve

### `POST` `/api/moderation/items/*/reject` ❔

POST /api/moderation/items/*/reject

---

## Outcome (governance/outcomes.py)

Handler for decision outcome tracking API endpoints.

### `POST` `/api/outcomes/search` ❔

GET /api/v1/outcomes/search?q=

### `POST` `/api/outcomes/impact` ❔

GET /api/v1/outcomes/impact  Impact analytics across all outcomes

---

## Policy (governance/policy.py)

Policy and Compliance endpoint handlers.

### `GET` `/api/v1/policies` ❔

List policies with optional filters

### `GET` `/api/v1/policies/*` 🔒

GET /api/v1/policies/*

### `PUT` `/api/v1/policies/*` 🔒

PUT /api/v1/policies/*

### `DELETE` `/api/v1/policies/*` 🔒

DELETE /api/v1/policies/*

### `GET` `/api/v1/policies/*/toggle` ❔

Toggle a policy's enabled status

### `GET` `/api/v1/policies/*/violations` ❔

Get violations for a specific policy

### `GET` `/api/v1/policies/validate` ❔

GET /api/v1/policies/validate

### `GET` `/api/v1/policies/violations` ❔

Get violations for a specific policy

### `GET` `/api/v1/compliance/violations` ❔

Get violations for a specific policy

### `GET` `/api/v1/compliance/violations/*` 🔒

GET /api/v1/compliance/violations/*

### `PUT` `/api/v1/compliance/violations/*` 🔒

PUT /api/v1/compliance/violations/*

### `GET` `/api/v1/compliance/check` ❔

Run compliance check on content

### `GET` `/api/v1/compliance/stats` ❔

Get compliance statistics

### `GET` `/api/v1/compliance/status` ❔

GET /api/v1/compliance/status

### `GET` `/api/v1/compliance/summary` ❔

GET /api/v1/compliance/summary

### `GET` `/api/v1/compliance/audit-events` ❔

GET /api/v1/compliance/audit-events

### `GET` `/api/v1/compliance/audit-verify` ❔

GET /api/v1/compliance/audit-verify

### `GET` `/api/v1/compliance/soc2-report` ❔

GET /api/v1/compliance/soc2-report

### `GET` `/api/v1/compliance/gdpr-export` ❔

GET /api/v1/compliance/gdpr-export

### `GET` `/api/v1/compliance/gdpr/right-to-be-forgotten` ❔

GET /api/v1/compliance/gdpr/right-to-be-forgotten

### `GET` `/api/v1/compliance/eu-ai-act/audit` ❔

GET /api/v1/compliance/eu-ai-act/audit

### `GET` `/api/v1/compliance/eu-ai-act/classify` ❔

GET /api/v1/compliance/eu-ai-act/classify

### `GET` `/api/v1/compliance/eu-ai-act/generate-bundle` ❔

GET /api/v1/compliance/eu-ai-act/generate-bundle

### `GET` `/api/v1/compliance/hipaa/status` ❔

GET /api/v1/compliance/hipaa/status

### `GET` `/api/v1/compliance/hipaa/baa` ❔

GET /api/v1/compliance/hipaa/baa

### `GET` `/api/v1/compliance/hipaa/detect-phi` ❔

GET /api/v1/compliance/hipaa/detect-phi

### `GET` `/api/v1/compliance/hipaa/deidentify` ❔

GET /api/v1/compliance/hipaa/deidentify

### `GET` `/api/v1/compliance/hipaa/phi-access` ❔

GET /api/v1/compliance/hipaa/phi-access

### `GET` `/api/v1/compliance/hipaa/breach-assessment` ❔

GET /api/v1/compliance/hipaa/breach-assessment

### `GET` `/api/v1/compliance/hipaa/security-report` ❔

GET /api/v1/compliance/hipaa/security-report

### `GET` `/api/v1/compliance/hipaa/safe-harbor/verify` ❔

GET /api/v1/compliance/hipaa/safe-harbor/verify

---

## ReviewQueue (governance/review_queue.py)

HTTP handler for PDB UI v0 review-queue endpoints.

### `POST` `/api/review-queue/*` ❔

POST /api/review-queue/*

### `POST` `/api/v1/review-queue/*` ❔

POST /api/v1/review-queue/*

### `GET` `/api/review-queue/triage-metrics` 🔒

GET /api/review-queue/triage-metrics

### `GET` `/api/v1/review-queue/triage-metrics` 🔒

GET /api/v1/review-queue/triage-metrics

---

## Settlement (governance/settlements.py)

Handler for settlement API endpoints.

### `GET` `/api/settlements` 🔒

GET /api/settlements

### `GET` `/api/settlements/history` 🔒

Get settled (resolved) settlements

### `GET` `/api/settlements/summary` 🔒

Get overall settlement summary statistics

### `GET` `/api/settlements/\{id\}` 🔒

GET /api/settlements/\{id\}

### `POST` `/api/settlements/\{id\}/settle` 🔒

Get a specific settlement by ID

### `POST` `/api/settlements/batch` 🔒

Settle multiple claims at once

### `GET` `/api/settlements/agent/\{agent\}/accuracy` 🔒

Get accuracy statistics for a specific agent

### `GET` `/api/v1/settlements` 🔒

GET /api/v1/settlements

### `GET` `/api/v1/settlements/history` 🔒

Get settled (resolved) settlements

### `GET` `/api/v1/settlements/summary` 🔒

Get overall settlement summary statistics

### `GET` `/api/v1/settlements/\{id\}` 🔒

GET /api/v1/settlements/\{id\}

### `POST` `/api/v1/settlements/\{id\}/settle` 🔒

Get a specific settlement by ID

### `POST` `/api/v1/settlements/batch` 🔒

Settle multiple claims at once

### `GET` `/api/v1/settlements/agent/\{agent\}/accuracy` 🔒

Get accuracy statistics for a specific agent

---

## Inbox Command (inbox/inbox_command.py)

Inbox Command Center API Handler.

### `GET` `/api/inbox/command` 🔒

Fetch prioritized inbox

### `POST` `/api/inbox/actions` 🔒

Execute quick action

### `POST` `/api/inbox/bulk-actions` 🔒

Execute bulk action

### `GET` `/api/inbox/sender-profile` 🔒

Get sender profile

### `GET` `/api/inbox/daily-digest` 🔒

Get daily digest

### `POST` `/api/inbox/reprioritize` 🔒

Trigger AI re-prioritization

### `GET` `/api/v1/inbox/command` 🔒

GET /api/v1/inbox/command

### `POST` `/api/v1/inbox/actions` 🔒

POST /api/v1/inbox/actions

### `POST` `/api/v1/inbox/bulk-actions` 🔒

POST /api/v1/inbox/bulk-actions

### `GET` `/api/v1/inbox/sender-profile` 🔒

GET /api/v1/inbox/sender-profile

### `GET` `/api/v1/inbox/daily-digest` 🔒

GET /api/v1/inbox/daily-digest

### `POST` `/api/v1/inbox/reprioritize` 🔒

POST /api/v1/inbox/reprioritize

---

## Team Inbox (inbox/team_inbox.py)

HTTP API Handlers for Team Inbox Collaboration.

### `GET` `/api/v1/inbox/shared/\{id\}/team` 🔒

Get team members

### `POST` `/api/v1/inbox/shared/\{id\}/team` 🔒

Add team member

### `GET` `/api/v1/inbox/mentions`

Get mentions for current user

### `POST` `/api/v1/inbox/mentions/\{id\}/acknowledge` 🔒

Acknowledge mention

### `GET` `/api/v1/inbox/shared/\{id\}/activity` 🔒

Get activity feed

---

## InboxTrustWedge (inbox/trust_wedge_handler.py)

Expose receipt-gated inbox wedge actions over HTTP.

### `GET` `/api/v1/inbox/wedge/receipts`

GET /api/v1/inbox/wedge/receipts

### `POST` `/api/v1/inbox/wedge/receipts`

POST /api/v1/inbox/wedge/receipts

---

## Automation (integrations/automation.py)

HTTP Handler for Automation Platform Webhooks.

### `DELETE` `/api/v1/webhooks/\{id\}` 🔒

Remove subscription

### `GET` `/api/v1/webhooks` 🔒

List subscriptions

### `GET` `/api/v1/webhooks/\{id\}` 🔒

Get subscription details

### `POST` `/api/v1/webhooks/\{id\}/test` 🔒

Test subscription

### `GET` `/api/v1/webhooks/events` ❔

List available event types

### `POST` `/api/v1/webhooks/dispatch` ❔

Dispatch event (internal)

### `POST` `/api/v1/webhooks` 🔒

List all webhook subscriptions

### `GET` `/api/v1/webhooks/subscribe` ❔

Create a new webhook subscription

### `GET` `/api/v1/webhooks/platforms` ❔

List supported automation platforms

### `GET` `/api/v1/n8n/node` ❔

Get n8n community node definition

### `GET` `/api/v1/n8n/credentials` ❔

Get n8n credentials definition

### `GET` `/api/v1/n8n/trigger` ❔

Get n8n trigger node definition

---

## Bindings (integrations/bindings.py)

Bindings endpoint handlers.

### `GET` `/api/bindings` ❔

List all message bindings

### `POST` `/api/bindings` ❔

Create a new binding

### `POST` `/api/bindings/resolve` ❔

Resolve binding for a message

### `GET` `/api/bindings/stats` ❔

Get router statistics

---

## ComputerUse (integrations/computer_use_handler.py)

HTTP request handler for computer use API endpoints.

### `GET` `/api/v1/computer-use/tasks` 🔒

Handle POST /api/v1/computer-use/tasks/\{id\}/cancel

### `POST` `/api/v1/computer-use/tasks` 🔒

Handle POST /api/v1/computer-use/tasks/\{id\}/cancel

### `GET` `/api/v1/computer-use/tasks/*` 🔒

GET /api/v1/computer-use/tasks/*

### `DELETE` `/api/v1/computer-use/tasks/*` 🔒

DELETE /api/v1/computer-use/tasks/*

### `GET` `/api/v1/computer-use/actions` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `POST` `/api/v1/computer-use/actions` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `GET` `/api/v1/computer-use/actions/*` 🔒

GET /api/v1/computer-use/actions/*

### `DELETE` `/api/v1/computer-use/actions/*` 🔒

DELETE /api/v1/computer-use/actions/*

### `GET` `/api/v1/computer-use/actions/stats` 🔒

Handle GET /api/v1/computer-use/actions/stats

### `GET` `/api/v1/computer-use/policies` 🔒

Handle POST /api/v1/computer-use/policies

### `POST` `/api/v1/computer-use/policies` 🔒

Handle POST /api/v1/computer-use/policies

### `GET` `/api/v1/computer-use/policies/*` 🔒

GET /api/v1/computer-use/policies/*

### `PUT` `/api/v1/computer-use/policies/*` 🔒

PUT /api/v1/computer-use/policies/*

### `DELETE` `/api/v1/computer-use/policies/*` 🔒

DELETE /api/v1/computer-use/policies/*

### `GET` `/api/v1/computer-use/approvals` 🔒

Handle POST /api/v1/computer-use/approvals/\{id\}/approve

### `GET` `/api/v1/computer-use/approvals/*` 🔒

GET /api/v1/computer-use/approvals/*

---

## ERC8004 (integrations/erc8004.py)

Handler for ERC-8004 blockchain API endpoints.

### `GET` `/api/v1/blockchain/config` ❔

GET /api/v1/blockchain/config

### `GET` `/api/v1/blockchain/health` ❔

GET /api/v1/blockchain/health

### `GET` `/api/v1/blockchain/sync` ❔

GET /api/v1/blockchain/sync

### `POST` `/api/v1/blockchain/sync` 🔒

POST /api/v1/blockchain/sync

### `GET` `/api/v1/blockchain/agents` ❔

GET /api/v1/blockchain/agents

### `POST` `/api/v1/blockchain/agents` 🔒

POST /api/v1/blockchain/agents

### `GET` `/api/v1/blockchain/agents/*` 🔒

GET /api/v1/blockchain/agents/*

---

## External Integrations (integrations/external_integrations.py)

External Integrations API Handler.

### `GET` `/api/v1/integrations/zapier/apps` ❔

Handle GET /api/integrations/zapier/apps - list Zapier apps

### `POST` `/api/v1/integrations/zapier/apps` ❔

Handle GET /api/integrations/zapier/apps - list Zapier apps

### `GET` `/api/v1/integrations/zapier/triggers` ❔

GET /api/v1/integrations/zapier/triggers

### `POST` `/api/v1/integrations/zapier/triggers` ❔

POST /api/v1/integrations/zapier/triggers

### `GET` `/api/v1/integrations/make/connections` ❔

Handle GET /api/integrations/make/connections - list connections

### `POST` `/api/v1/integrations/make/connections` ❔

Handle GET /api/integrations/make/connections - list connections

### `POST` `/api/v1/integrations/make/webhooks` ❔

POST /api/v1/integrations/make/webhooks

### `GET` `/api/v1/integrations/make/modules` ❔

GET /api/v1/integrations/make/modules

### `GET` `/api/v1/integrations/n8n/credentials` ❔

Handle GET /api/integrations/n8n/credentials - list credentials

### `POST` `/api/v1/integrations/n8n/credentials` ❔

Handle GET /api/integrations/n8n/credentials - list credentials

### `POST` `/api/v1/integrations/n8n/webhooks` ❔

POST /api/v1/integrations/n8n/webhooks

### `GET` `/api/v1/integrations/n8n/nodes` ❔

Handle GET /api/integrations/n8n/nodes - get node definitions

### `POST` `/api/v1/integrations/wizard/preflight` ❔

POST /api/v1/integrations/wizard/preflight

### `POST` `/api/v1/integrations/wizard/recommendations` ❔

POST /api/v1/integrations/wizard/recommendations

### `GET` `/api/v2/integrations/stats` ❔

GET /api/v2/integrations/stats

### `GET` `/api/v2/integrations/wizard/providers` ❔

GET /api/v2/integrations/wizard/providers

### `GET` `/api/v2/integrations/wizard/status` ❔

GET /api/v2/integrations/wizard/status

### `POST` `/api/v2/integrations/wizard/validate` ❔

POST /api/v2/integrations/wizard/validate

---

## Health (integrations/health.py)

Integration health check endpoint handler.

### `GET` `/api/v1/integrations/health` ❔

Returns health status for each configured

---

## Integration Management (integrations/integration_management.py)

Integration Management HTTP Handlers for Aragora.

### `GET` `/api/v2/integrations` ❔

List all integrations

### `GET` `/api/v2/integrations/:type` ❔

Get specific integration status

### `DELETE` `/api/v2/integrations/:type` ❔

Disconnect integration

### `POST` `/api/v2/integrations/:type/test` ❔

Test integration connectivity

### `GET` `/api/v2/integrations/stats` ❔

Integration statistics

---

## Partner (integrations/partner.py)

Partner API HTTP handlers.

### `GET` `/api/v1/partners/register` ❔

Register a new partner

### `GET` `/api/v1/partners/me` ❔

GET /api/v1/partners/me

### `GET` `/api/v1/partners/keys` ❔

List all API keys for the partner

### `GET` `/api/v1/partners/usage` ❔

Get usage statistics

### `GET` `/api/v1/partners/webhooks` ❔

GET /api/v1/partners/webhooks

### `GET` `/api/v1/partners/limits` ❔

Get rate limits for the partner tier

---

## Adapters (knowledge/adapters.py)

Knowledge Mound adapter status endpoint handler.

### `GET` `/api/v1/knowledge/adapters` ❔

List all KM adapters with status, priority,

---

## KMCheckpoint (knowledge/checkpoints.py)

Handler for Knowledge Mound checkpoint management endpoints.

### `POST` `/api/v1/km/checkpoints/compare` 🔒

Compare checkpoint with current KM state

---

## KnowledgeChat (knowledge/knowledge_chat.py)

HTTP handler for Knowledge + Chat bridge endpoints.

### `POST` `/api/v1/chat/knowledge/search`

POST /api/v1/chat/knowledge/search

### `POST` `/api/v1/chat/knowledge/inject`

POST /api/v1/chat/knowledge/inject

### `POST` `/api/v1/chat/knowledge/store`

POST /api/v1/chat/knowledge/store

### `POST` `/api/v1/chat/knowledge/channel/*` ❔

POST /api/v1/chat/knowledge/channel/*

### `GET` `/api/v1/chat/knowledge/channel/*/summary`

GET /api/v1/chat/knowledge/channel/*/summary

---

## Ml (knowledge/ml.py)

ML (Machine Learning) endpoint handlers.

### `POST` `/api/v1/ml/route` ❔

Handle ML-based agent routing

### `POST` `/api/v1/ml/score` ❔

Handle single response quality scoring

### `POST` `/api/v1/ml/score-batch` ❔

POST /api/v1/ml/score-batch

### `POST` `/api/v1/ml/consensus` ❔

Handle consensus prediction

### `POST` `/api/v1/ml/export-training` ❔

POST /api/v1/ml/export-training

### `POST` `/api/v1/ml/models` ❔

List available ML models and capabilities

### `POST` `/api/v1/ml/stats` ❔

Get ML module statistics including circuit breaker status

### `POST` `/api/v1/ml/embed` ❔

Handle text embedding

### `POST` `/api/v1/ml/search` ❔

Handle semantic search

---

## RLMContext (knowledge/rlm.py)

Handler for RLM context compression and query endpoints.

### `GET` `/api/v1/rlm/stats` ❔

GET /api/v1/rlm/stats

### `GET` `/api/v1/rlm/strategies` ❔

GET /api/v1/rlm/strategies

### `POST` `/api/v1/rlm/compress` ❔

Get or create the hierarchical compressor using factory

### `POST` `/api/v1/rlm/query` ❔

Simple fallback query when full RLM is not available

### `GET` `/api/v1/rlm/contexts` ❔

GET /api/v1/rlm/contexts

### `POST` `/api/v1/rlm/stream` ❔

POST /api/v1/rlm/stream

### `GET` `/api/v1/rlm/stream/modes` ❔

GET /api/v1/rlm/stream/modes

### `GET` `/api/v1/rlm/codebase/health` ❔

GET /api/v1/rlm/codebase/health

---

## Knowledge (knowledge_base/handler.py)

Handler for knowledge base API endpoints.

### `POST` `/api/v1/knowledge/query` 🔒

Get or create query engine

### `GET` `/api/v1/knowledge/facts` 🔒

Handle /api/v1/knowledge/facts/:id/* routes

### `POST` `/api/v1/knowledge/facts` 🔒

Handle /api/v1/knowledge/facts/:id/* routes

### `POST` `/api/v1/knowledge/facts/relations` 🔒

POST /api/v1/knowledge/facts/relations

### `GET` `/api/v1/knowledge/facts/*` 🔒

Normalize /api/v1/facts/* to /api/v1/knowledge/facts/* for routing

### `PUT` `/api/v1/knowledge/facts/*` 🔒

Normalize /api/v1/facts/* to /api/v1/knowledge/facts/* for routing

### `DELETE` `/api/v1/knowledge/facts/*` 🔒

Normalize /api/v1/facts/* to /api/v1/knowledge/facts/* for routing

### `POST` `/api/v1/knowledge/facts/*/verify` 🔒

POST /api/v1/knowledge/facts/*/verify

### `GET` `/api/v1/knowledge/facts/*/contradictions` 🔒

GET /api/v1/knowledge/facts/*/contradictions

### `GET` `/api/v1/knowledge/facts/*/relations` 🔒

GET /api/v1/knowledge/facts/*/relations

### `POST` `/api/v1/knowledge/facts/*/relations` 🔒

POST /api/v1/knowledge/facts/*/relations

### `GET` `/api/v1/knowledge/search` 🔒

GET /api/v1/knowledge/search

### `GET` `/api/v1/knowledge/stats` 🔒

GET /api/v1/knowledge/stats

### `GET` `/api/v1/knowledge/embeddings` ❔

GET /api/v1/knowledge/embeddings

### `GET` `/api/v1/knowledge/entries/*/embeddings` ❔

GET /api/v1/knowledge/entries/*/embeddings

### `GET` `/api/v1/knowledge/entries/*/sources` ❔

GET /api/v1/knowledge/entries/*/sources

### `GET` `/api/v1/knowledge/export` ❔

GET /api/v1/knowledge/export

### `GET` `/api/v1/knowledge/refresh` ❔

GET /api/v1/knowledge/refresh

### `GET` `/api/v1/knowledge/validate` ❔

GET /api/v1/knowledge/validate

### `GET` `/api/v1/facts` ❔

Normalize /api/v1/facts/* to /api/v1/knowledge/facts/* for routing

### `GET` `/api/v1/facts/batch` ❔

Handle POST /api/v1/index/embed-batch with the local model /api/v1/ml/embed uses

### `GET` `/api/v1/facts/batch/delete` ❔

GET /api/v1/facts/batch/delete

### `GET` `/api/v1/facts/merge` ❔

GET /api/v1/facts/merge

### `GET` `/api/v1/facts/relationships` ❔

GET /api/v1/facts/relationships

### `GET` `/api/v1/facts/stats` ❔

GET /api/v1/facts/stats

### `GET` `/api/v1/facts/validate` ❔

GET /api/v1/facts/validate

### `GET` `/api/v1/index` ❔

Handle POST /api/v1/index/embed-batch with the local model /api/v1/ml/embed uses

### `GET` `/api/v1/index/embed-batch` ❔

Handle POST /api/v1/index/embed-batch with the local model /api/v1/ml/embed uses

### `GET` `/api/v1/index/search` ❔

GET /api/v1/index/search

---

## KnowledgeMound (knowledge_base/mound/handler.py)

Handler for Knowledge Mound API endpoints (unified knowledge storage).

### `GET` `/api/v1/knowledge/mound/query` ❔

GET /api/v1/knowledge/mound/query

### `POST` `/api/v1/knowledge/mound/query` 🔒

POST /api/v1/knowledge/mound/query

### `GET` `/api/v1/knowledge/mound/nodes` ❔

GET /api/v1/knowledge/mound/nodes

### `POST` `/api/v1/knowledge/mound/nodes` 🔒

POST /api/v1/knowledge/mound/nodes

### `GET` `/api/v1/knowledge/mound/nodes/*` 🔒

GET /api/v1/knowledge/mound/nodes/*

### `GET` `/api/v1/knowledge/mound/nodes/*/relationships` ❔

GET /api/v1/knowledge/mound/nodes/*/relationships

### `GET` `/api/v1/knowledge/mound/nodes/*/visibility` ❔

GET /api/v1/knowledge/mound/nodes/*/visibility

### `PUT` `/api/v1/knowledge/mound/nodes/*/visibility` 🔒

PUT /api/v1/knowledge/mound/nodes/*/visibility

### `GET` `/api/v1/knowledge/mound/nodes/*/access` ❔

GET /api/v1/knowledge/mound/nodes/*/access

### `POST` `/api/v1/knowledge/mound/nodes/*/access` 🔒

POST /api/v1/knowledge/mound/nodes/*/access

### `DELETE` `/api/v1/knowledge/mound/nodes/*/access` 🔒

DELETE /api/v1/knowledge/mound/nodes/*/access

### `GET` `/api/v1/knowledge/mound/relationships` ❔

GET /api/v1/knowledge/mound/relationships

### `POST` `/api/v1/knowledge/mound/relationships` 🔒

POST /api/v1/knowledge/mound/relationships

### `GET` `/api/v1/knowledge/mound/stats` ❔

GET /api/v1/knowledge/mound/stats

### `GET` `/api/v1/knowledge/mound/culture` ❔

GET /api/v1/knowledge/mound/culture

### `GET` `/api/v1/knowledge/mound/culture/*`

GET /api/v1/knowledge/mound/culture/*

### `GET` `/api/v1/knowledge/mound/stale` ❔

GET /api/v1/knowledge/mound/stale

### `GET` `/api/v1/knowledge/mound/revalidate` ❔

GET /api/v1/knowledge/mound/revalidate

### `POST` `/api/v1/knowledge/mound/revalidate/*`

POST /api/v1/knowledge/mound/revalidate/*

### `GET` `/api/v1/knowledge/mound/schedule-revalidation` ❔

GET /api/v1/knowledge/mound/schedule-revalidation

### `POST` `/api/v1/knowledge/mound/schedule-revalidation` 🔒

POST /api/v1/knowledge/mound/schedule-revalidation

### `GET` `/api/v1/knowledge/mound/sync` ❔

GET /api/v1/knowledge/mound/sync

### `POST` `/api/v1/knowledge/mound/sync/*`

POST /api/v1/knowledge/mound/sync/*

### `GET` `/api/v1/knowledge/mound/graph/*` 🔒

GET /api/v1/knowledge/mound/graph/*

### `GET` `/api/v1/knowledge/mound/graph/*/lineage` ❔

GET /api/v1/knowledge/mound/graph/*/lineage

### `GET` `/api/v1/knowledge/mound/graph/*/related` ❔

GET /api/v1/knowledge/mound/graph/*/related

### `GET` `/api/v1/knowledge/mound/export/d3` ❔

GET /api/v1/knowledge/mound/export/d3

### `GET` `/api/v1/knowledge/mound/export/graphml` ❔

GET /api/v1/knowledge/mound/export/graphml

### `GET` `/api/v1/knowledge/mound/share` ❔

GET /api/v1/knowledge/mound/share

### `POST` `/api/v1/knowledge/mound/share` 🔒

POST /api/v1/knowledge/mound/share

### `PATCH` `/api/v1/knowledge/mound/share` 🔒

PATCH /api/v1/knowledge/mound/share

### `DELETE` `/api/v1/knowledge/mound/share` 🔒

DELETE /api/v1/knowledge/mound/share

### `GET` `/api/v1/knowledge/mound/shared-with-me` ❔

GET /api/v1/knowledge/mound/shared-with-me

### `GET` `/api/v1/knowledge/mound/my-shares` ❔

GET /api/v1/knowledge/mound/my-shares

### `GET` `/api/v1/knowledge/mound/global` ❔

GET /api/v1/knowledge/mound/global

### `POST` `/api/v1/knowledge/mound/global` 🔒

POST /api/v1/knowledge/mound/global

### `GET` `/api/v1/knowledge/mound/global/facts` ❔

GET /api/v1/knowledge/mound/global/facts

### `GET` `/api/v1/knowledge/mound/global/promote` ❔

GET /api/v1/knowledge/mound/global/promote

### `POST` `/api/v1/knowledge/mound/global/promote` 🔒

POST /api/v1/knowledge/mound/global/promote

### `GET` `/api/v1/knowledge/mound/federation/regions` ❔

GET /api/v1/knowledge/mound/federation/regions

### `POST` `/api/v1/knowledge/mound/federation/regions` 🔒

POST /api/v1/knowledge/mound/federation/regions

### `DELETE` `/api/v1/knowledge/mound/federation/regions/*` 🔒

DELETE /api/v1/knowledge/mound/federation/regions/*

### `GET` `/api/v1/knowledge/mound/federation/status` ❔

GET /api/v1/knowledge/mound/federation/status

### `GET` `/api/v1/knowledge/mound/federation/sync/push` ❔

GET /api/v1/knowledge/mound/federation/sync/push

### `POST` `/api/v1/knowledge/mound/federation/sync/push` 🔒

POST /api/v1/knowledge/mound/federation/sync/push

### `GET` `/api/v1/knowledge/mound/federation/sync/pull` ❔

GET /api/v1/knowledge/mound/federation/sync/pull

### `POST` `/api/v1/knowledge/mound/federation/sync/pull` 🔒

POST /api/v1/knowledge/mound/federation/sync/pull

### `GET` `/api/v1/knowledge/mound/federation/sync/all` ❔

GET /api/v1/knowledge/mound/federation/sync/all

### `POST` `/api/v1/knowledge/mound/federation/sync/all` 🔒

POST /api/v1/knowledge/mound/federation/sync/all

### `GET` `/api/v1/knowledge/mound/index/repository` ❔

GET /api/v1/knowledge/mound/index/repository

### `POST` `/api/v1/knowledge/mound/index/repository` 🔒

POST /api/v1/knowledge/mound/index/repository

### `GET` `/api/v1/knowledge/mound/dedup/clusters` ❔

GET /api/v1/knowledge/mound/dedup/clusters

### `GET` `/api/v1/knowledge/mound/dedup/report` ❔

GET /api/v1/knowledge/mound/dedup/report

### `GET` `/api/v1/knowledge/mound/dedup/merge` ❔

GET /api/v1/knowledge/mound/dedup/merge

### `POST` `/api/v1/knowledge/mound/dedup/merge` 🔒

POST /api/v1/knowledge/mound/dedup/merge

### `GET` `/api/v1/knowledge/mound/dedup/auto-merge` ❔

GET /api/v1/knowledge/mound/dedup/auto-merge

### `POST` `/api/v1/knowledge/mound/dedup/auto-merge` 🔒

POST /api/v1/knowledge/mound/dedup/auto-merge

### `GET` `/api/v1/knowledge/mound/pruning/items` ❔

GET /api/v1/knowledge/mound/pruning/items

### `GET` `/api/v1/knowledge/mound/pruning/execute` ❔

GET /api/v1/knowledge/mound/pruning/execute

### `POST` `/api/v1/knowledge/mound/pruning/execute` 🔒

POST /api/v1/knowledge/mound/pruning/execute

### `GET` `/api/v1/knowledge/mound/pruning/auto` ❔

GET /api/v1/knowledge/mound/pruning/auto

### `POST` `/api/v1/knowledge/mound/pruning/auto` 🔒

POST /api/v1/knowledge/mound/pruning/auto

### `GET` `/api/v1/knowledge/mound/pruning/history` ❔

GET /api/v1/knowledge/mound/pruning/history

### `GET` `/api/v1/knowledge/mound/pruning/restore` ❔

GET /api/v1/knowledge/mound/pruning/restore

### `POST` `/api/v1/knowledge/mound/pruning/restore` 🔒

POST /api/v1/knowledge/mound/pruning/restore

### `GET` `/api/v1/knowledge/mound/pruning/decay` ❔

GET /api/v1/knowledge/mound/pruning/decay

### `POST` `/api/v1/knowledge/mound/pruning/decay` 🔒

POST /api/v1/knowledge/mound/pruning/decay

### `GET` `/api/v1/knowledge/mound/dashboard/health` ❔

GET /api/v1/knowledge/mound/dashboard/health

### `GET` `/api/v1/knowledge/mound/dashboard/metrics` ❔

GET /api/v1/knowledge/mound/dashboard/metrics

### `GET` `/api/v1/knowledge/mound/dashboard/metrics/reset` ❔

GET /api/v1/knowledge/mound/dashboard/metrics/reset

### `POST` `/api/v1/knowledge/mound/dashboard/metrics/reset` 🔒

POST /api/v1/knowledge/mound/dashboard/metrics/reset

### `GET` `/api/v1/knowledge/mound/dashboard/adapters` ❔

GET /api/v1/knowledge/mound/dashboard/adapters

### `GET` `/api/v1/knowledge/mound/dashboard/queries` ❔

GET /api/v1/knowledge/mound/dashboard/queries

### `GET` `/api/v1/knowledge/mound/dashboard/batcher` ❔

GET /api/v1/knowledge/mound/dashboard/batcher

### `GET` `/api/v1/knowledge/mound/curation/policy` ❔

GET /api/v1/knowledge/mound/curation/policy

### `POST` `/api/v1/knowledge/mound/curation/policy` 🔒

POST /api/v1/knowledge/mound/curation/policy

### `PUT` `/api/v1/knowledge/mound/curation/policy` 🔒

PUT /api/v1/knowledge/mound/curation/policy

### `GET` `/api/v1/knowledge/mound/curation/status` ❔

GET /api/v1/knowledge/mound/curation/status

### `GET` `/api/v1/knowledge/mound/curation/run` ❔

GET /api/v1/knowledge/mound/curation/run

### `POST` `/api/v1/knowledge/mound/curation/run` 🔒

POST /api/v1/knowledge/mound/curation/run

### `GET` `/api/v1/knowledge/mound/curation/history` ❔

GET /api/v1/knowledge/mound/curation/history

### `GET` `/api/v1/knowledge/mound/curation/scores` ❔

GET /api/v1/knowledge/mound/curation/scores

### `GET` `/api/v1/knowledge/mound/curation/tiers` ❔

GET /api/v1/knowledge/mound/curation/tiers

### `GET` `/api/v1/knowledge/mound/contradictions/detect` ❔

GET /api/v1/knowledge/mound/contradictions/detect

### `POST` `/api/v1/knowledge/mound/contradictions/detect` 🔒

POST /api/v1/knowledge/mound/contradictions/detect

### `GET` `/api/v1/knowledge/mound/contradictions` ❔

GET /api/v1/knowledge/mound/contradictions

### `GET` `/api/v1/knowledge/mound/contradictions/*/resolve` ❔

GET /api/v1/knowledge/mound/contradictions/*/resolve

### `POST` `/api/v1/knowledge/mound/contradictions/*/resolve` 🔒

POST /api/v1/knowledge/mound/contradictions/*/resolve

### `GET` `/api/v1/knowledge/mound/contradictions/stats` ❔

GET /api/v1/knowledge/mound/contradictions/stats

### `GET` `/api/v1/knowledge/mound/governance/roles` 🔒

GET /api/v1/knowledge/mound/governance/roles

### `POST` `/api/v1/knowledge/mound/governance/roles`

POST /api/v1/knowledge/mound/governance/roles

### `POST` `/api/v1/knowledge/mound/governance/roles/assign`

POST /api/v1/knowledge/mound/governance/roles/assign

### `POST` `/api/v1/knowledge/mound/governance/roles/revoke`

POST /api/v1/knowledge/mound/governance/roles/revoke

### `GET` `/api/v1/knowledge/mound/governance/permissions` ❔

GET /api/v1/knowledge/mound/governance/permissions

### `GET` `/api/v1/knowledge/mound/governance/permissions/*`

GET /api/v1/knowledge/mound/governance/permissions/*

### `POST` `/api/v1/knowledge/mound/governance/permissions/check`

Check authentication and return error response if failed

### `GET` `/api/v1/knowledge/mound/governance/audit`

GET /api/v1/knowledge/mound/governance/audit

### `GET` `/api/v1/knowledge/mound/governance/audit/user` ❔

GET /api/v1/knowledge/mound/governance/audit/user

### `GET` `/api/v1/knowledge/mound/governance/audit/user/*`

GET /api/v1/knowledge/mound/governance/audit/user/*

### `GET` `/api/v1/knowledge/mound/governance/stats`

GET /api/v1/knowledge/mound/governance/stats

### `GET` `/api/v1/knowledge/mound/analytics/coverage` ❔

GET /api/v1/knowledge/mound/analytics/coverage

### `GET` `/api/v1/knowledge/mound/analytics/usage` ❔

GET /api/v1/knowledge/mound/analytics/usage

### `GET` `/api/v1/knowledge/mound/analytics/usage/record` ❔

GET /api/v1/knowledge/mound/analytics/usage/record

### `POST` `/api/v1/knowledge/mound/analytics/usage/record` 🔒

POST /api/v1/knowledge/mound/analytics/usage/record

### `GET` `/api/v1/knowledge/mound/analytics/quality/snapshot` ❔

GET /api/v1/knowledge/mound/analytics/quality/snapshot

### `POST` `/api/v1/knowledge/mound/analytics/quality/snapshot` 🔒

POST /api/v1/knowledge/mound/analytics/quality/snapshot

### `GET` `/api/v1/knowledge/mound/analytics/quality/trend` ❔

GET /api/v1/knowledge/mound/analytics/quality/trend

### `GET` `/api/v1/knowledge/mound/analytics/stats` ❔

GET /api/v1/knowledge/mound/analytics/stats

### `GET` `/api/v1/knowledge/mound/extraction/debate` ❔

GET /api/v1/knowledge/mound/extraction/debate

### `POST` `/api/v1/knowledge/mound/extraction/debate` 🔒

POST /api/v1/knowledge/mound/extraction/debate

### `GET` `/api/v1/knowledge/mound/extraction/promote` ❔

GET /api/v1/knowledge/mound/extraction/promote

### `POST` `/api/v1/knowledge/mound/extraction/promote` 🔒

POST /api/v1/knowledge/mound/extraction/promote

### `GET` `/api/v1/knowledge/mound/extraction/stats` ❔

GET /api/v1/knowledge/mound/extraction/stats

### `GET` `/api/v1/knowledge/mound/confidence/decay` ❔

GET /api/v1/knowledge/mound/confidence/decay

### `POST` `/api/v1/knowledge/mound/confidence/decay` 🔒

POST /api/v1/knowledge/mound/confidence/decay

### `GET` `/api/v1/knowledge/mound/confidence/event` ❔

GET /api/v1/knowledge/mound/confidence/event

### `POST` `/api/v1/knowledge/mound/confidence/event` 🔒

POST /api/v1/knowledge/mound/confidence/event

### `GET` `/api/v1/knowledge/mound/confidence/history` ❔

GET /api/v1/knowledge/mound/confidence/history

### `GET` `/api/v1/knowledge/mound/confidence/stats` ❔

GET /api/v1/knowledge/mound/confidence/stats

### `GET` `/api/v1/knowledge/mound/culture/documents` ❔

GET /api/v1/knowledge/mound/culture/documents

### `POST` `/api/v1/knowledge/mound/culture/documents` 🔒

POST /api/v1/knowledge/mound/culture/documents

### `GET` `/api/v1/knowledge/mound/culture/promote` ❔

GET /api/v1/knowledge/mound/culture/promote

### `POST` `/api/v1/knowledge/mound/culture/promote` 🔒

POST /api/v1/knowledge/mound/culture/promote

### `GET` `/api/v1/km/checkpoints` 🔒

GET /api/v1/km/checkpoints

### `POST` `/api/v1/km/checkpoints` 🔒

POST /api/v1/km/checkpoints

---

## Checkpoints (memory/checkpoints.py)

Checkpoint management endpoint handlers.

### `GET` `/api/v1/checkpoints` ❔

GET /api/v1/checkpoints

### `GET` `/api/v1/checkpoints/resumable` ❔

GET /api/v1/checkpoints/resumable

### `GET` `/api/v1/checkpoints/*` 🔒

GET /api/v1/checkpoints/*

### `GET` `/api/v1/checkpoints/*/resume` ❔

GET /api/v1/checkpoints/*/resume

### `GET` `/api/v1/checkpoints/*/intervention` ❔

GET /api/v1/checkpoints/*/intervention

---

## Consensus (memory/consensus.py)

Consensus Memory endpoint handlers.

### `GET` `/api/consensus/similar` ❔

Find debates similar to a topic

### `GET` `/api/consensus/settled` ❔

Get high-confidence settled topics

### `GET` `/api/consensus/stats` ❔

Get consensus memory statistics

### `GET` `/api/consensus/dissents` ❔

Get recent dissenting views

### `GET` `/api/consensus/contrarian-views` ❔

Get contrarian perspectives

### `GET` `/api/consensus/risk-warnings` ❔

Get risk warnings and edge cases

### `GET` `/api/consensus/domain/:domain` 🔒

Get domain-specific history

### `POST` `/api/consensus` ❔

Detect consensus from provided proposals/text

### `POST` `/api/consensus/seed-demo` ❔

POST /api/consensus/seed-demo

### `POST` `/api/consensus/detect` 🔒

Detect consensus from provided proposals/text

### `POST` `/api/v1/consensus/domain` ❔

Get consensus history for a domain

---

## Coordinator (memory/coordinator.py)

Memory Coordinator endpoint handlers.

### `GET` `/api/v1/memory/coordinator/metrics` ❔

Get coordinator metrics including success rate and rollback stats

### `GET` `/api/v1/memory/coordinator/config` ❔

Get current coordinator configuration

---

## Insights (memory/insights.py)

Insights-related endpoint handlers.

### `GET` `/api/insights/recent` ❔

Get recent insights from InsightStore

### `POST` `/api/insights/extract-detailed` 🔒

Extract detailed insights from content

### `GET` `/api/flips/recent` ❔

Get recent position flips/reversals

### `GET` `/api/flips/summary` ❔

Get summary statistics for position flips

---

## Learning (memory/learning.py)

Cross-cycle learning analytics endpoint handlers.

### `GET` `/api/learning/cycles` ❔

Get all cycle summaries

### `GET` `/api/learning/patterns` ❔

Get learned patterns across cycles

### `GET` `/api/learning/agent-evolution` ❔

Get agent performance evolution

### `GET` `/api/learning/insights` ❔

Get aggregated insights from cycles

### `GET` `/api/v1/learning/cycles` ❔

GET /api/v1/learning/cycles

### `GET` `/api/v1/learning/patterns` ❔

Get patterns learned across cycles from consensus memory

### `GET` `/api/v1/learning/agent-evolution` ❔

GET /api/v1/learning/agent-evolution

### `GET` `/api/v1/learning/insights` ❔

Get insights aggregated from all cycles

---

## Memory (memory/memory.py)

Memory-related endpoint handlers.

### `GET` `/api/v1/memory/continuum/retrieve` 🔒

Retrieve memories from continuum

### `POST` `/api/v1/memory/continuum/consolidate` 🔒

Trigger memory consolidation

### `POST` `/api/v1/memory/continuum/cleanup` 🔒

Cleanup expired memories

### `GET` `/api/v1/memory/tier-stats` 🔒

Get tier statistics

### `GET` `/api/v1/memory/archive-stats` 🔒

Get archive statistics

### `GET` `/api/v1/memory/pressure` 🔒

Get memory pressure and utilization

### `DELETE` `/api/v1/memory/continuum/\{id\}` ❔

Delete a memory by ID

### `GET` `/api/v1/memory/tiers` 🔒

List all memory tiers with detailed stats

### `GET` `/api/v1/memory/search` 🔒

Search memories across tiers

### `GET` `/api/v1/memory/critiques` 🔒

Browse critique store entries

### `POST` `/api/v1/memory/store` ❔

Get user store from context

### `GET` `/api/v1/memory/search-index` 🔒

GET /api/v1/memory/search-index

### `GET` `/api/v1/memory/search-timeline` 🔒

GET /api/v1/memory/search-timeline

### `GET` `/api/v1/memory/entries` 🔒

GET /api/v1/memory/entries

### `GET` `/api/v1/memory/viewer` 🔒

GET /api/v1/memory/viewer

### `POST` `/api/v1/memory/compact` ❔

POST /api/v1/memory/compact

### `POST` `/api/v1/memory/context` ❔

POST /api/v1/memory/context

### `POST` `/api/v1/memory/cross-debate` ❔

POST /api/v1/memory/cross-debate

### `POST` `/api/v1/memory/cross-debate/inject` ❔

POST /api/v1/memory/cross-debate/inject

### `POST` `/api/v1/memory/export` ❔

POST /api/v1/memory/export

### `POST` `/api/v1/memory/import` ❔

POST /api/v1/memory/import

### `POST` `/api/v1/memory/prune` ❔

POST /api/v1/memory/prune

### `POST` `/api/v1/memory/query` ❔

POST /api/v1/memory/query

### `POST` `/api/v1/memory/rebuild-index` ❔

POST /api/v1/memory/rebuild-index

### `POST` `/api/v1/memory/semantic-search` ❔

POST /api/v1/memory/semantic-search

### `POST` `/api/v1/memory/snapshots` ❔

POST /api/v1/memory/snapshots

### `GET` `/api/v1/memory/snapshots/*` 🔒

GET /api/v1/memory/snapshots/*

### `POST` `/api/v1/memory/snapshots/*/restore` ❔

POST /api/v1/memory/snapshots/*/restore

### `POST` `/api/v1/memory/sync` ❔

POST /api/v1/memory/sync

### `GET` `/api/v1/memory/tier/*` 🔒

GET /api/v1/memory/tier/*

### `POST` `/api/v1/memory/vacuum` ❔

POST /api/v1/memory/vacuum

### `GET` `/api/v1/memory/*` 🔒

GET /api/v1/memory/*

### `POST` `/api/v1/memory/*/demote` ❔

POST /api/v1/memory/*/demote

### `POST` `/api/v1/memory/*/move` ❔

POST /api/v1/memory/*/move

### `POST` `/api/v1/memory/*/promote` ❔

Promote a memory entry to a new tier: POST /api/v1/memory/\{id\}/promote

---

## Memory Analytics (memory/memory_analytics.py)

Memory analytics endpoint handlers.

### `POST` `/api/v1/memory/analytics/snapshot` ❔

Take a manual snapshot

### `POST` `/api/v1/memory/analytics` ❔

Get comprehensive memory analytics

---

## Handler (metrics/handler.py)

Operational metrics endpoint handlers.

### `GET` `/api/metrics` ❔

Get operational metrics for monitoring

### `GET` `/api/metrics/health` ❔

Detailed health check

### `GET` `/api/metrics/cache` ❔

Cache statistics

### `GET` `/api/metrics/system` ❔

System information

### `GET` `/metrics` ❔

Prometheus-format metrics (OpenMetrics)

### `POST` `/api/metrics/verification` ❔

Get formal verification statistics

### `POST` `/api/metrics/background` ❔

Get background task statistics

### `POST` `/api/metrics/debate` ❔

Get debate performance statistics

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `debate_id` | string | Optional specific debate to get insights for |

### `POST` `/api/v1/monitoring/alerts` ❔

POST /api/v1/monitoring/alerts

### `POST` `/api/v1/monitoring/dashboards` ❔

POST /api/v1/monitoring/dashboards

### `POST` `/api/v1/monitoring/health` ❔

Get detailed health check status

### `POST` `/api/v1/monitoring/logs` ❔

POST /api/v1/monitoring/logs

### `POST` `/api/v1/monitoring/metrics` ❔

Get comprehensive operational metrics

### `POST` `/api/v1/monitoring/slos` ❔

POST /api/v1/monitoring/slos

### `POST` `/api/v1/monitoring/traces` ❔

POST /api/v1/monitoring/traces

---

## Metrics Endpoint (metrics/metrics_endpoint.py)

Unified Prometheus metrics endpoint.

### `GET` `/metrics` ❔

Full Prometheus-format metrics export

### `GET` `/api/v1/metrics/prometheus` ❔

Same as /metrics with API versioning

### `GET` `/api/v1/metrics/prometheus/summary` ❔

Aggregated metrics summary

### `GET` `/api/metrics/prometheus` ❔

Get full Prometheus metrics output

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `query_params` | string | Query parameters (supports aggregate=true) |

### `GET` `/api/metrics/prometheus/summary` ❔

Get aggregated metrics summary

---

## Devices (notifications/devices.py)

Device Registration and Notification API Handlers.

### `POST` `/api/devices/register` 🔒

Register a device for push notifications

### `DELETE` `/api/devices/\{device_id\}` 🔒

Unregister a device

### `GET` `/api/devices/health` 🔒

Get device connector health

### `POST` `/api/devices/alexa/webhook` ❔

Alexa skill webhook

### `POST` `/api/devices/google/webhook` ❔

Google Actions webhook

### `GET` `/api/v1/devices` 🔒

List all devices for a user

---

## NotificationHistory (notifications/history.py)

Handler for notification history and delivery stats.

### `GET` `/api/v1/notifications/history` ❔

Get paginated notification history

### `GET` `/api/v1/notifications/delivery-stats` ❔

GET /api/v1/notifications/delivery-stats

---

## NotificationPreferences (notifications/preferences.py)

Handler for notification preferences.

### `PUT` `/api/v1/notifications/preferences` ❔

Get notification preferences for current user

---

## NotificationTemplates (notifications/templates.py)

CRUD handler for per-user notification templates.

### `GET` `/api/v1/notifications/templates` ❔

GET /api/v1/notifications/templates

### `GET` `/api/v1/notifications/templates/\{id\}` ❔

GET /api/v1/notifications/templates/\{id\}

### `PUT` `/api/v1/notifications/templates/\{id\}` ❔

PUT /api/v1/notifications/templates/\{id\}

### `POST` `/api/v1/notifications/templates/\{id\}/reset` ❔

POST /api/v1/notifications/templates/\{id\}/reset

### `POST` `/api/v1/notifications/templates/\{id\}/preview` ❔

POST /api/v1/notifications/templates/\{id\}/preview

---

## Oauth Wizard (oauth/oauth_wizard.py)

Unified OAuth Wizard Handler for SME Onboarding.

### `GET` `/api/v2/integrations/wizard` ❔

Get wizard configuration

### `GET` `/api/v2/integrations/wizard/providers` ❔

List all available providers

### `GET` `/api/v2/integrations/wizard/status` ❔

Get status of all integrations

### `POST` `/api/v2/integrations/wizard/validate` ❔

Validate configuration before connecting

### `GET` `/api/v2/integrations/wizard/*` 🔒

GET /api/v2/integrations/wizard/*

---

## Crashes (observability/crashes.py)

Frontend crash telemetry collector.

### `POST` `/api/observability/crashes`

Ingest crash reports

### `GET` `/api/observability/crashes` 🔒

List recent crashes (admin)

### `GET` `/api/observability/crashes/stats` 🔒

Crash frequency stats (admin)

---

## Dashboard (observability/dashboard.py)

Observability dashboard endpoint.

### `GET` `/api/observability/dashboard` 🔒

Aggregated system observability metrics

### `GET` `/api/observability/metrics` 🔒

Collect debate count, avg duration, consensus rate

---

## EndpointAnalytics (observability/endpoint_analytics.py)

Handler for API endpoint performance analytics.

### `GET` `/api/analytics/endpoints` ❔

GET /api/analytics/endpoints - List all endpoints with metrics

### `GET` `/api/analytics/endpoints/slowest` ❔

GET /api/analytics/endpoints/slowest - Top N slowest endpoints

### `GET` `/api/analytics/endpoints/errors` ❔

GET /api/analytics/endpoints/errors - Top N endpoints by error rate

### `GET` `/api/analytics/endpoints/health` ❔

GET /api/analytics/endpoints/health - Overall API health summary

---

## Slo (observability/slo.py)

SLO (Service Level Objective) endpoint handlers.

### `GET` `/api/slos/status` ❔

Overall SLO compliance status

### `GET` `/api/slos/error-budget` ❔

Error budget timeline

### `GET` `/api/slos/violations` ❔

Recent SLO violations

### `GET` `/api/slos/targets` ❔

Configured SLO targets

### `GET` `/api/v1/slos/status` ❔

Versioned endpoint

### `GET` `/api/v1/slo/status` ❔

SLO enforcer real-time compliance status

### `GET` `/api/v1/slo/budget` ❔

SLO enforcer error budget remaining

### `GET` `/api/health/slos` ❔

Debate SLO health (green/yellow/red per SLO, multi-window)

### `GET` `/api/slos/availability` ❔

GET /api/slos/availability

### `GET` `/api/slos/latency` ❔

GET /api/slos/latency

### `GET` `/api/slos/debate-success` ❔

GET /api/slos/debate-success

### `GET` `/api/slo/status` ❔

GET /api/slos/status - Overall SLO compliance status

### `GET` `/api/slo/budget` ❔

GET /api/v1/slo/budget - Remaining error budget from enforcer

### `GET` `/api/v2/slo/status` ❔

GET /api/slos/status - Overall SLO compliance status

---

## Gateway (openclaw/gateway.py)

HTTP Handlers for OpenClaw Gateway.

### `GET` `/api/gateway/openclaw/health` ❔

Gateway health

### `GET` `/api/gateway/openclaw/metrics` ❔

Gateway metrics

### `GET` `/api/gateway/openclaw/audit` ❔

Audit log

### `GET` `/api/v1/openclaw/sessions` ❔

GET /api/v1/openclaw/sessions

### `POST` `/api/v1/openclaw/sessions` ❔

POST /api/v1/openclaw/sessions

### `GET` `/api/v1/openclaw/sessions/\{session_id\}` ❔

GET /api/v1/openclaw/sessions/\{session_id\}

### `DELETE` `/api/v1/openclaw/sessions/\{session_id\}` ❔

DELETE /api/v1/openclaw/sessions/\{session_id\}

### `POST` `/api/v1/openclaw/sessions/\{session_id\}/end` ❔

POST /api/v1/openclaw/sessions/\{session_id\}/end

### `POST` `/api/v1/openclaw/actions` ❔

POST /api/v1/openclaw/actions

### `GET` `/api/v1/openclaw/actions/\{action_id\}` ❔

GET /api/v1/openclaw/actions/\{action_id\}

### `POST` `/api/v1/openclaw/actions/\{action_id\}/cancel` ❔

POST /api/v1/openclaw/actions/\{action_id\}/cancel

### `GET` `/api/v1/openclaw/credentials` ❔

GET /api/v1/openclaw/credentials

### `POST` `/api/v1/openclaw/credentials` ❔

POST /api/v1/openclaw/credentials

### `DELETE` `/api/v1/openclaw/credentials/\{credential_id\}` ❔

DELETE /api/v1/openclaw/credentials/\{credential_id\}

### `POST` `/api/v1/openclaw/credentials/\{credential_id\}/rotate` ❔

POST /api/v1/openclaw/credentials/\{credential_id\}/rotate

### `GET` `/api/v1/openclaw/policy/rules` ❔

GET /api/v1/openclaw/policy/rules

### `POST` `/api/v1/openclaw/policy/rules` ❔

POST /api/v1/openclaw/policy/rules

### `DELETE` `/api/v1/openclaw/policy/rules/\{rule_name\}` ❔

DELETE /api/v1/openclaw/policy/rules/\{rule_name\}

### `GET` `/api/v1/openclaw/approvals` ❔

GET /api/v1/openclaw/approvals

### `POST` `/api/v1/openclaw/approvals/\{approval_id\}/approve` ❔

POST /api/v1/openclaw/approvals/\{approval_id\}/approve

### `POST` `/api/v1/openclaw/approvals/\{approval_id\}/deny` ❔

POST /api/v1/openclaw/approvals/\{approval_id\}/deny

### `GET` `/api/v1/openclaw/health` ❔

GET /api/v1/openclaw/health

### `GET` `/api/v1/openclaw/metrics` ❔

GET /api/v1/openclaw/metrics

### `GET` `/api/v1/openclaw/audit` ❔

GET /api/v1/openclaw/audit

### `GET` `/api/v1/openclaw/stats` ❔

GET /api/v1/openclaw/stats

### `GET` `/api/gateway/openclaw/sessions` ❔

GET /api/gateway/openclaw/sessions

### `POST` `/api/gateway/openclaw/sessions` ❔

POST /api/gateway/openclaw/sessions

### `POST` `/api/gateway/openclaw/actions` ❔

POST /api/gateway/openclaw/actions

### `GET` `/api/gateway/openclaw/credentials` ❔

GET /api/gateway/openclaw/credentials

### `POST` `/api/gateway/openclaw/credentials` ❔

POST /api/gateway/openclaw/credentials

---

## Coordination (orchestration/coordination.py)

Handler for cross-workspace coordination API endpoints.

### `GET` `/api/v1/coordination/workspaces` 🔒

GET /api/v1/coordination/workspaces -- list workspaces

### `POST` `/api/v1/coordination/workspaces` 🔒

GET /api/v1/coordination/workspaces -- list workspaces

### `GET` `/api/v1/coordination/federation` 🔒

POST /api/v1/coordination/federation -- create federation policy

### `POST` `/api/v1/coordination/federation` 🔒

POST /api/v1/coordination/federation -- create federation policy

### `POST` `/api/v1/coordination/execute` 🔒

POST /api/v1/coordination/execute -- cross-workspace execution

### `GET` `/api/v1/coordination/executions` 🔒

GET /api/v1/coordination/executions -- list pending executions

### `GET` `/api/v1/coordination/consent` 🔒

POST /api/v1/coordination/consent -- grant consent

### `POST` `/api/v1/coordination/consent` 🔒

POST /api/v1/coordination/consent -- grant consent

### `GET` `/api/v1/coordination/stats` 🔒

GET /api/v1/coordination/stats -- coordination statistics

### `GET` `/api/v1/coordination/health` ❔

GET /api/v1/coordination/health -- health check

---

## Handler (orchestration/handler.py)

Unified Orchestration Handler for Aragora Control Plane.

### `POST` `/api/v1/orchestration/deliberate` ❔

Unified vetted decisionmaking endpoint

### `GET` `/api/v1/orchestration/status/:id` 🔒

Get vetted decisionmaking status

### `GET` `/api/v1/orchestration/templates` 🔒

List available templates

### `POST` `/api/v1/orchestration/deliberate/sync` ❔

Synchronous vetted decisionmaking

---

## PaymentRoutes (payments/handler.py)

Facade handler for payment route discovery.

### `POST` `/api/v1/payments/authorize` 🔒

POST /api/v1/payments/authorize

### `POST` `/api/v1/payments/capture` 🔒

POST /api/v1/payments/capture

### `POST` `/api/v1/payments/charge` 🔒

POST /api/v1/payments/charge

### `POST` `/api/v1/payments/customer` 🔒

POST /api/v1/payments/customer

### `POST` `/api/v1/payments/refund` 🔒

POST /api/v1/payments/refund

### `POST` `/api/v1/payments/subscription` 🔒

POST /api/v1/payments/subscription

### `POST` `/api/v1/payments/void` 🔒

POST /api/v1/payments/void

---

## Decomposition (pipeline/decomposition.py)

Handler for task decomposition visualization endpoints.

### `GET` `/api/v1/pipeline` 🔒

GET /api/v1/pipeline

### `POST` `/api/v1/pipeline` 🔒

POST /api/v1/pipeline

---

## PipelineExecute (pipeline/execute.py)

Handler for pipeline execution via self-improvement pipeline.

### `GET` `/api/v1/pipeline` 🔒

Execute pipeline goals via the canonical DecisionPlan runtime

### `POST` `/api/v1/pipeline` 🔒

Execute pipeline goals via the canonical DecisionPlan runtime

---

## Pipeline Graph (pipeline/pipeline_graph.py)

Universal Pipeline Graph REST Handler.

### `POST` `/api/v1/pipeline/graph` ❔

Create graph

### `GET` `/api/v1/pipeline/graph` ❔

List graphs

### `GET` `/api/v1/pipeline/graph/\{id\}` ❔

Get graph

### `DELETE` `/api/v1/pipeline/graph/\{id\}` ❔

Delete graph

### `POST` `/api/v1/pipeline/graph/\{id\}/node` ❔

Add node

### `DELETE` `/api/v1/pipeline/graph/\{id\}/node/\{nid\}` ❔

Remove node

### `GET` `/api/v1/pipeline/graph/\{id\}/nodes` ❔

Query nodes (stage/subtype filters)

### `POST` `/api/v1/pipeline/graph/\{id\}/promote` ❔

Promote nodes to next stage

### `GET` `/api/v1/pipeline/graph/\{id\}/provenance/\{nid\}` ❔

Provenance chain

### `GET` `/api/v1/pipeline/graph/\{id\}/suggestions` ❔

Transition suggestions

### `GET` `/api/v1/pipeline/graph/\{id\}/react-flow` ❔

React Flow JSON export

### `GET` `/api/v1/pipeline/graph/\{id\}/integrity` ❔

Integrity hash

### `POST` `/api/v1/pipeline/graph/\{id\}/node/\{nid\}/reassign` ❔

Reassign agent on node

---

## PlanManagement (pipeline/plans.py)

Handler for decision plan management endpoints.

### `PUT` `/api/v1/plans` ❔

Get plans from context or in-memory store

---

## ProvenanceExplorer (pipeline/provenance_explorer.py)

Handler for provenance explorer endpoints (singular /graph/ prefix).

### `GET` `/api/v1/pipeline/graph` ❔

GET /api/v1/pipeline/graph

### `POST` `/api/v1/pipeline/graph` ❔

POST /api/v1/pipeline/graph

---

## Receipts (pipeline/receipts.py)

Receipt Explorer API Handler for Pipeline Execution Receipts.

### `GET` `/api/v1/receipts` ❔

List receipts with filtering

---

## PipelineTransitions (pipeline/transitions.py)

Handler for AI stage transition endpoints.

### `POST` `/api/v1/pipeline/transitions` ❔

POST /api/v1/pipeline/transitions

---

## UniversalGraph (pipeline/universal_graph.py)

Handler for universal pipeline graph endpoints.

### `POST` `/api/v1/pipeline/graphs` ❔

POST /api/v1/pipeline/graphs

### `PUT` `/api/v1/pipeline/graphs` ❔

PUT /api/v1/pipeline/graphs

### `PATCH` `/api/v1/pipeline/graphs` ❔

PATCH /api/v1/pipeline/graphs

### `DELETE` `/api/v1/pipeline/graphs` ❔

DELETE /api/v1/pipeline/graphs

---

## Platform Config (platform_config.py)

Platform Configuration handler.

### `GET` `/api/v1/platform/config` 🔒

Full platform configuration

---

## Handler (prompt_engine/handler.py)

Prompt Engine API Handler.

### `GET` `/api/prompt-engine/runs` 🔒

List persisted backbone runs

### `GET` `/api/prompt-engine/runs/\{id\}` 🔒

Fetch one persisted backbone run

### `POST` `/api/prompt-engine/run` 🔒

Full pipeline (decompose → interrogate → research → specify)

### `POST` `/api/prompt-engine/decompose` 🔒

Decompose a vague prompt into structured intent

### `POST` `/api/prompt-engine/interrogate` 🔒

Generate clarifying questions for an intent

### `POST` `/api/prompt-engine/research` 🔒

Research context for an intent

### `POST` `/api/prompt-engine/specify` 🔒

Build a specification from intent + questions + research

### `POST` `/api/prompt-engine/validate` 🔒

Validate a specification via SpecValidator

---

## Gallery (public/gallery.py)

Public Gallery endpoint handlers.

### `GET` `/api/gallery` ❔

List public debates

---

## StatusPage (public/status_page.py)

Handler for public status page endpoints.

### `GET` `/status` ❔

Return detailed component status

### `GET` `/api/status` ❔

Return detailed component status

### `GET` `/api/status/summary` ❔

Return JSON status summary

### `GET` `/api/status/history` ❔

Return historical uptime data

### `GET` `/api/status/components` ❔

Check health of all components

### `GET` `/api/status/incidents` ❔

Return current and recent incidents

### `GET` `/api/v1/status` ❔

Return detailed component status

### `GET` `/api/v1/status/components` ❔

Check health of all components

### `GET` `/api/v1/status/incidents` ❔

Return current and recent incidents

### `GET` `/api/v1/status/uptime` ❔

Format uptime in human-readable form

### `GET` `/api/v1/public/surfaces` ❔

Summarize the exposed surface inventory by readiness

---

## Security Debate (security/security_debate.py)

Security Debate API endpoint handlers.

### `POST` `/api/v1/audit/security/debate` ❔

Trigger a security debate on findings

### `POST` `/api/v1/audit/security/debate/:id` ❔

POST /api/v1/audit/security/debate/:id

---

## Threat Intel (security/threat_intel.py)

Threat Intelligence API Handlers.

### `POST` `/api/v1/threat/url` 🔒

Check URL for threats

### `POST` `/api/v1/threat/urls` 🔒

Batch check URLs

### `GET` `/api/v1/threat/ip/\{ip_address\}` 🔒

Check IP reputation

### `POST` `/api/v1/threat/ips` 🔒

Batch check IPs

### `GET` `/api/v1/threat/hash/\{hash_value\}` 🔒

Check file hash reputation

### `POST` `/api/v1/threat/hashes` 🔒

Batch check hashes

### `POST` `/api/v1/threat/email` 🔒

Scan email content

### `GET` `/api/v1/threat/status` 🔒

Get service status

---

## SharedInbox (shared_inbox/handler.py)

HTTP handler for shared inbox endpoints.

### `GET` `/api/v1/inbox/shared`

GET /api/v1/inbox/shared

### `POST` `/api/v1/inbox/shared`

POST /api/v1/inbox/shared

### `GET` `/api/v1/inbox/routing/rules`

GET /api/v1/inbox/routing/rules

### `POST` `/api/v1/inbox/routing/rules`

POST /api/v1/inbox/routing/rules

---

## Feedback (sme/feedback.py)

User Feedback Collection Handler.

### `GET` `/api/v1/feedback/nps/summary` ❔

Get NPS summary (requires feedback.update - admin)

### `GET` `/api/v1/feedback/prompts` ❔

Get active feedback prompts (requires feedback.read)

### `GET` `/api/v1/feedback/general` ❔

GET /api/v1/feedback/general

### `GET` `/api/v1/feedback/nps` ❔

GET /api/v1/feedback/nps

---

## Onboarding (sme/onboarding.py)

Onboarding Orchestration Handler.

### `GET` `/api/v1/onboarding/flow` ❔

Get current onboarding state

### `POST` `/api/v1/onboarding/flow` ❔

Initialize onboarding

### `PUT` `/api/v1/onboarding/flow/step` ❔

Update current step

### `GET` `/api/v1/onboarding/templates` ❔

Get recommended starter templates

### `POST` `/api/v1/onboarding/first-debate` ❔

Start guided first debate

### `POST` `/api/v1/onboarding/quick-start` ❔

Apply quick-start configuration

### `GET` `/api/v1/onboarding/analytics` ❔

Get onboarding funnel analytics

### `GET` `/api/onboarding/flow` ❔

GET /api/onboarding/flow

### `POST` `/api/onboarding/flow` ❔

POST /api/onboarding/flow

### `GET` `/api/onboarding/templates` ❔

GET /api/onboarding/templates

### `POST` `/api/onboarding/first-debate` ❔

POST /api/onboarding/first-debate

### `POST` `/api/onboarding/quick-start` ❔

POST /api/onboarding/quick-start

### `POST` `/api/onboarding/quick-debate` ❔

POST /api/onboarding/quick-debate

### `GET` `/api/onboarding/analytics` ❔

GET /api/onboarding/analytics

### `GET` `/api/v1/templates/recommended` ❔

GET /api/v1/templates/recommended

---

## ReadinessCheck (sme/readiness_check.py)

Public endpoint reporting what a user needs to configure before

### `GET` `/api/v1/readiness` ❔

GET /api/v1/readiness

### `GET` `/api/readiness` ❔

GET /api/readiness

---

## SMEUsageDashboard (sme/sme_usage_dashboard.py)

Handler for SME usage dashboard endpoints.

### `GET` `/api/v1/usage/summary` ❔

Get unified usage summary for the SME dashboard

### `GET` `/api/v1/usage/breakdown` ❔

Get detailed usage breakdown by dimension

### `GET` `/api/v1/usage/roi` ❔

Get ROI analysis for the organization

### `GET` `/api/v1/usage/export` ❔

Export usage data in various formats

### `GET` `/api/v1/usage/budget-status` ❔

GET /api/v1/usage/budget-status

### `GET` `/api/v1/usage/forecast` ❔

Get usage forecast based on current patterns

### `GET` `/api/v1/usage/benchmarks` ❔

Get industry benchmark comparison data

---

## ChannelHealth (social/channel_health.py)

Handler for chat channel health monitoring.

### `GET` `/api/v1/channels/health` ❔

Get basic health info for connectors without get_health method

### `GET` `/api/v1/channels/\{channel\}/health` ❔

Get basic health info for connectors without get_health method

---

## Collaboration (social/collaboration.py)

Handler for social collaboration endpoints.

### `GET` `/api/v1/social/collaboration/sessions` 🔒

GET /api/v1/social/collaboration/sessions

---

## Discord Oauth (social/discord_oauth.py)

Discord OAuth Handler for bot installation flow.

### `GET` `/api/integrations/discord/install` ❔

Redirect to Discord OAuth

### `GET` `/api/integrations/discord/callback` ❔

Handle OAuth callback

### `POST` `/api/integrations/discord/uninstall` ❔

Handle guild removal

---

## Notifications (social/notifications.py)

Handler for notification-related endpoints.

### `GET` `/api/v1/notifications/status` ❔

Get status of notification integrations scoped to organization

### `GET` `/api/v1/notifications/email/recipients` ❔

Get list of email recipients scoped to organization

### `POST` `/api/v1/notifications/email/config` ❔

Configure email integration settings for an organization

### `POST` `/api/v1/notifications/telegram/config` ❔

Configure email integration settings for an organization

### `POST` `/api/v1/notifications/email/recipient` ❔

Add an email recipient for an organization

### `DELETE` `/api/v1/notifications/email/recipient` ❔

Add an email recipient for an organization

### `POST` `/api/v1/notifications/test` ❔

Send a test notification

### `POST` `/api/v1/notifications/send` ❔

Send a notification with custom content

---

## Relationship (social/relationship.py)

Relationship endpoint handlers.

### `GET` `/api/relationships/summary` ❔

Global relationship overview

### `GET` `/api/relationships/graph` ❔

Full relationship graph for visualizations

### `GET` `/api/relationships/stats` ❔

Relationship system statistics

### `GET` `/api/relationship/\{agent_a\}/\{agent_b\}` ❔

Detailed relationship between two agents

### `GET` `/api/v1/relationships/summary` ❔

Get global relationship overview

### `GET` `/api/v1/relationships/graph` ❔

Get full relationship graph for visualizations

### `GET` `/api/v1/relationships/stats` ❔

Return empty stats response when no data available

### `GET` `/api/v1/relationship/\{agent_a\}/\{agent_b\}` ❔

GET /api/v1/relationship/\{agent_a\}/\{agent_b\}

---

## Sharing (social/sharing.py)

Debate Sharing Handler.

### `POST` `/api/v1/debates/*/share` ❔

Create a social share

### `POST` `/api/v1/debates/*/share/revoke` ❔

Revoke all share links for a debate

### `GET` `/api/v1/shared/*` 🔒

GET /api/v1/shared/*

---

## Slack Oauth (social/slack_oauth.py)

Slack OAuth Handler for app installation flow.

### `GET` `/api/integrations/slack/install` ❔

Redirect to Slack OAuth

### `GET` `/api/integrations/slack/callback` ❔

Handle OAuth callback

### `POST` `/api/integrations/slack/uninstall` ❔

Handle app removal

### `GET` `/api/integrations/slack/preview` ❔

Display consent preview page before Slack OAuth

### `GET` `/api/integrations/slack/workspaces` ❔

Return True when the caller has global Slack admin scope

---

## Social Media (social/social_media.py)

Social Media endpoint handlers for Twitter and YouTube.

### `GET` `/api/youtube/auth` ❔

Get YouTube OAuth authorization URL

### `GET` `/api/youtube/callback` ❔

Handle YouTube OAuth callback

### `GET` `/api/youtube/status` ❔

Get YouTube connector status

### `POST` `/api/debates/\{id\}/publish/twitter` 🔒

Publish debate to Twitter/X

### `POST` `/api/debates/\{id\}/publish/youtube` 🔒

Publish debate to YouTube

### `GET` `/api/v1/youtube/auth` ❔

Get YouTube OAuth authorization URL

### `GET` `/api/v1/youtube/callback` ❔

Handle YouTube OAuth callback

### `GET` `/api/v1/youtube/status` ❔

Get YouTube connector status

### `POST` `/api/v1/debates/*/publish/twitter` 🔒

Get the Twitter connector with proper typing

### `POST` `/api/v1/debates/*/publish/youtube` 🔒

Get YouTube OAuth authorization URL

---

## Teams (social/teams.py)

Microsoft Teams integration endpoint handlers.

### `POST` `/api/v1/integrations/teams/commands` ❔

POST /api/v1/integrations/teams/commands

### `POST` `/api/v1/integrations/teams/interactive` ❔

Handle Adaptive Card action submissions

### `GET` `/api/v1/integrations/teams/status` ❔

Get status of active debate in conversation

### `POST` `/api/v1/integrations/teams/notify` 🔒

Send notification to a Teams channel/conversation

---

## Teams Oauth (social/teams_oauth.py)

Microsoft Teams OAuth Handler for app installation flow.

### `GET` `/api/integrations/teams/install` ❔

Redirect to Microsoft OAuth

### `GET` `/api/integrations/teams/callback` ❔

Handle OAuth callback

### `POST` `/api/integrations/teams/refresh` ❔

Refresh expired tokens

### `GET` `/api/integrations/teams/disconnect` ❔

Disconnect a Teams tenant

### `GET` `/api/integrations/teams/tenants` ❔

List all Teams tenants with their status

---

## Spectate Ws (streaming/spectate_ws.py)

WebSocket/SSE handler for real-time spectate events.

### `GET` `/api/v1/spectate/recent` ❔

Get recent buffered spectate events

### `GET` `/api/v1/spectate/status` ❔

Get bridge status (active, subscribers, buffer size)

### `GET` `/api/v1/spectate/stream` ❔

Live SSE on the unified server, JSON/snapshot fallback here

### `POST` `/api/v1/spectate/emit` ❔

POST /api/v1/spectate/emit

---

## TaskExecution (tasks/execution.py)

HTTP handler for task execution endpoints.

### `POST` `/api/v2/tasks` ❔

List tasks, optionally filtered by status

### `GET` `/api/v2/tasks/*` 🔒

GET /api/v2/tasks/*

---

## TaskQueue (tasks/queue.py)

Expose queue inspection plus lease-scoped lifecycle endpoints.

### `GET` `/api/v1/tasks/queue` 🔒

GET /api/v1/tasks/queue

### `GET` `/api/v1/tasks/queue/stats` 🔒

GET /api/v1/tasks/queue/stats

### `POST` `/api/v1/tasks/queue/sync` 🔒

POST /api/v1/tasks/queue/sync

### `GET` `/api/v1/tasks/queue/\{task_id\}` 🔒

GET /api/v1/tasks/queue/\{task_id\}

### `POST` `/api/v1/tasks/queue/\{task_id\}/claim` 🔒

POST /api/v1/tasks/queue/\{task_id\}/claim

### `GET` `/api/v1/tasks/leases` 🔒

GET /api/v1/tasks/leases

### `POST` `/api/v1/tasks/leases/\{lease_id\}/heartbeat` 🔒

POST /api/v1/tasks/leases/\{lease_id\}/heartbeat

### `POST` `/api/v1/tasks/leases/\{lease_id\}/release` 🔒

POST /api/v1/tasks/leases/\{lease_id\}/release

### `POST` `/api/v1/tasks/leases/\{lease_id\}/complete` 🔒

POST /api/v1/tasks/leases/\{lease_id\}/complete

### `GET` `/api/v1/tasks/salvage` 🔒

GET /api/v1/tasks/salvage

---

## Benchmarking (verification/benchmarking.py)

Handler for decision benchmarking endpoints.

### `GET` `/api/benchmarks` ❔

GET /api/v1/benchmarks -- list aggregated benchmarks for a category

### `GET` `/api/benchmarks/categories` ❔

GET /api/v1/benchmarks/categories -- list available benchmark categories

### `GET` `/api/benchmarks/compare` ❔

GET /api/v1/benchmarks/compare -- compare tenant metrics to benchmarks

---

## Evaluation (verification/evaluation.py)

Handler for LLM-as-Judge evaluation endpoints.

### `POST` `/api/v1/evaluate` ❔

Evaluate a response using LLM-as-Judge

### `POST` `/api/v1/evaluate/compare` ❔

Compare two responses using pairwise evaluation

### `POST` `/api/v1/evaluate/dimensions` ❔

List available evaluation dimensions

### `POST` `/api/v1/evaluate/profiles` ❔

List available evaluation weight profiles

---

## Formal Verification (verification/formal_verification.py)

Formal Verification API Endpoints.

### `GET` `/api/v1/verify/claim` ❔

POST /api/verify/claim - Verify a single claim

### `GET` `/api/v1/verify/batch` ❔

POST /api/verify/batch - Batch verification of multiple claims

### `GET` `/api/v1/verify/status` ❔

GET /api/verify/status - Get backend availability status

### `GET` `/api/v1/verify/translate` ❔

POST /api/verify/translate - Translate claim to formal language only

### `GET` `/api/v1/verify/history` ❔

GET /api/verify/history - Get verification history

### `POST` `/api/verification/formal-verify` 🔒

POST /api/verification/formal-verify

### `GET` `/api/verification/status` ❔

GET /api/verify/status - Get backend availability status

---

## Verification (verification/verification.py)

Formal verification endpoint handlers.

### `GET` `/api/verification/status` ❔

Get status of formal verification backends

### `POST` `/api/verification/formal-verify` 🔒

Verify a claim using Z3 SMT solver

### `GET` `/api/v1/verification/status` ❔

Get status of formal verification backends

### `POST` `/api/v1/verification/formal-verify` 🔒

POST /api/v1/verification/formal-verify

### `GET` `/api/v1/verification/proofs` 🔒

Get generated verification proofs

### `POST` `/api/v1/verification/validate` ❔

Validate a specific claim or assertion

---

## Voice (voice/handler.py)

Handler for Twilio Voice webhooks.

### `GET` `/api/v1/voice/inbound` ❔

GET /api/v1/voice/inbound

### `GET` `/api/v1/voice/status` ❔

GET /api/v1/voice/status

### `GET` `/api/v1/voice/gather` ❔

GET /api/v1/voice/gather

### `GET` `/api/v1/voice/gather/confirm` ❔

GET /api/v1/voice/gather/confirm

### `GET` `/api/v1/voice/device` ❔

GET /api/v1/voice/device

### `GET` `/api/v1/voice/synthesize` ❔

GET /api/v1/voice/synthesize

### `GET` `/api/v1/voice/voices` ❔

GET /api/v1/voice/voices

### `GET` `/api/v1/voice/sessions` ❔

GET /api/v1/voice/sessions

### `GET` `/api/v1/voice/sessions/\{session_id\}` ❔

GET /api/v1/voice/sessions/\{session_id\}

### `GET` `/api/v1/voice/config` ❔

GET /api/v1/voice/config

### `GET` `/api/voice/inbound` ❔

GET /api/voice/inbound

### `GET` `/api/voice/status` ❔

GET /api/voice/status

### `GET` `/api/voice/gather` ❔

GET /api/voice/gather

### `GET` `/api/voice/gather/confirm` ❔

GET /api/voice/gather/confirm

---

## Transcription (voice/transcription.py)

Transcription endpoint handlers for speech-to-text and media processing.

### `POST` `/api/v1/transcription/audio` ❔

Handle audio file transcription

### `POST` `/api/v1/transcription/video` ❔

Handle video file transcription (extract audio and transcribe)

### `POST` `/api/v1/transcription/youtube` ❔

Get YouTube video info without transcribing

### `POST` `/api/v1/transcription/youtube/info` ❔

Get YouTube video info without transcribing

### `POST` `/api/v1/transcription/upload` ❔

POST /api/v1/transcription/upload

### `POST` `/api/v1/transcription/formats` ❔

POST /api/v1/transcription/formats

### `POST` `/api/v1/transcription/status` ❔

Get transcription job status

### `GET` `/api/v1/transcription/status/*` 🔒

GET /api/v1/transcription/status/*

### `POST` `/api/v1/transcription/config` ❔

Return transcription configuration and supported formats

### `POST` `/api/v1/transcribe/audio` ❔

Handle audio file transcription

### `POST` `/api/v1/transcribe/video` ❔

Handle video file transcription (extract audio and transcribe)

---

## Webhook (webhook_management.py)

Handler for webhook management API endpoints.

### `GET` `/api/v1/webhooks` 🔒

Handle GET /api/webhooks - list all webhooks

### `POST` `/api/v1/webhooks` 🔒

Handle GET /api/webhooks - list all webhooks

### `GET` `/api/v1/webhooks/events` ❔

Handle GET /api/webhooks/events - list available event types

### `POST` `/api/v1/webhooks/events/categories` ❔

POST /api/v1/webhooks/events/categories

### `GET` `/api/v1/webhooks/slo/status` 🔒

Handle GET /api/webhooks/slo/status - get SLO webhook status

### `POST` `/api/v1/webhooks/slo/test` 🔒

Handle POST /api/webhooks/slo/test - send test SLO violation notification

### `GET` `/api/v1/webhooks/dead-letter` 🔒

GET /api/v1/webhooks/dead-letter

### `GET` `/api/v1/webhooks/queue/stats` 🔒

Handle GET /api/webhooks/queue/stats - get queue statistics

### `POST` `/api/v1/webhooks/bulk` ❔

POST /api/v1/webhooks/bulk

### `POST` `/api/v1/webhooks/pause-all` ❔

POST /api/v1/webhooks/pause-all

### `POST` `/api/v1/webhooks/resume-all` ❔

POST /api/v1/webhooks/resume-all

---

## WorkflowBuilder (workflows/builder.py)

HTTP handlers for visual workflow builder API.

### `POST` `/api/v1/workflows/generate` ❔

Generate a workflow from a natural language description

### `POST` `/api/v1/workflows/auto-layout` ❔

POST /api/v1/workflows/auto-layout

### `POST` `/api/v1/workflows/step-types` ❔

POST /api/v1/workflows/step-types

### `POST` `/api/v1/workflows/from-pattern` ❔

POST /api/v1/workflows/from-pattern

### `POST` `/api/v1/workflows/validate` ❔

Validate a workflow definition

### `POST` `/api/v1/workflows/*/replay` ❔

Replay a workflow execution with same or new inputs

---

## Workflow (workflows/handler.py)

HTTP request handler for workflow API endpoints.

### `GET` `/api/v1/workflows` ❔

Handle GET /api/workflows

### `POST` `/api/v1/workflows` ❔

Handle GET /api/workflows

### `GET` `/api/v1/workflows/*` ❔

GET /api/v1/workflows/*

### `PUT` `/api/v1/workflows/*` ❔

PUT /api/v1/workflows/*

### `PATCH` `/api/v1/workflows/*` 🔒

PATCH /api/v1/workflows/*

### `DELETE` `/api/v1/workflows/*` ❔

DELETE /api/v1/workflows/*

### `GET` `/api/v1/workflow-templates` ❔

GET /api/v1/workflow-templates

### `GET` `/api/v1/workflows/templates` ❔

Handle GET /api/workflow-templates

### `POST` `/api/v1/workflows/templates` ❔

Handle GET /api/workflow-templates

### `DELETE` `/api/v1/workflows/templates` ❔

Handle GET /api/workflow-templates

### `GET` `/api/v1/workflows/templates/*` ❔

GET /api/v1/workflows/templates/*

### `PUT` `/api/v1/workflows/templates/*` 🔒

PUT /api/v1/workflows/templates/*

### `DELETE` `/api/v1/workflows/templates/*` 🔒

DELETE /api/v1/workflows/templates/*

### `GET` `/api/v1/workflow-approvals` 🔒

GET /api/v1/workflow-approvals

### `POST` `/api/v1/workflow-approvals/*` 🔒

POST /api/v1/workflow-approvals/*

### `GET` `/api/v1/workflow-executions` ❔

GET /api/v1/workflow-executions

### `GET` `/api/v1/workflow-executions/*` ❔

GET /api/v1/workflow-executions/*

### `DELETE` `/api/v1/workflow-executions/*` ❔

DELETE /api/v1/workflow-executions/*

### `GET` `/api/v1/workflows/executions` ❔

Handle GET /api/workflow-executions

### `POST` `/api/v1/workflows/executions` ❔

Handle GET /api/workflow-executions

### `DELETE` `/api/v1/workflows/executions` ❔

Handle GET /api/workflow-executions

### `GET` `/api/v1/workflows/executions/*` 🔒

GET /api/v1/workflows/executions/*

### `DELETE` `/api/v1/workflows/executions/*` 🔒

DELETE /api/v1/workflows/executions/*

---

## TemplateRegistry (workflows/registry.py)

HTTP handler for the public template registry API.

### `POST` `/api/v1/templates/registry` ❔

Extract listing ID from path like /api/v1/templates/registry/\{id\}

### `GET` `/api/v1/templates/registry/*` ❔

GET /api/v1/templates/registry/*

---

## Organizations (workspace/organizations.py)

Organization Management Handlers.

### `GET` `/api/v1/org` ❔

Check if user has access to organization with minimum role

### `GET` `/api/v1/org/*` 🔒

GET /api/v1/org/*

### `GET` `/api/v1/org/*/members` ❔

List organization members

### `GET` `/api/v1/org/*/members/*` 🔒

GET /api/v1/org/*/members/*

### `GET` `/api/v1/org/*/invite` ❔

Invite a user to the organization

### `GET` `/api/v1/org/*/invitations` ❔

Get all pending invitations for an email address

### `GET` `/api/v1/org/*/invitations/*` 🔒

GET /api/v1/org/*/invitations/*

### `GET` `/api/v1/org/*/members/*/role` ❔

Update a member's role in the organization

### `GET` `/api/v1/user/organizations` ❔

List organizations for the current user (single-org fallback)

### `GET` `/api/v1/user/organizations/switch` ❔

Switch the active organization for the current user

### `GET` `/api/v1/user/organizations/default` ❔

Set the default organization for the current user

### `GET` `/api/v1/invitations/pending` ❔

Get pending invitations for the authenticated user

### `GET` `/api/v1/invitations/*/accept` ❔

Accept an organization invitation

### `GET` `/api/v1/tenants` ❔

GET /api/v1/tenants

---

## Workspace Module (workspace/workspace_module.py)

Workspace Handler - Enterprise Privacy and Data Isolation APIs.

### `POST` `/api/workspaces` 🔒

Create a new workspace

### `GET` `/api/workspaces` 🔒

List workspaces

### `GET` `/api/workspaces/\{id\}` 🔒

Get workspace details

### `DELETE` `/api/workspaces/\{id\}` 🔒

Delete workspace

### `POST` `/api/workspaces/\{id\}/members` 🔒

Add member to workspace

### `GET` `/api/retention/policies` 🔒

List retention policies

### `POST` `/api/retention/policies` 🔒

Create retention policy

### `POST` `/api/retention/policies/\{id\}/execute` 🔒

Execute retention policy

### `GET` `/api/retention/expiring` 🔒

Get items expiring soon

### `POST` `/api/classify` 🔒

Classify content sensitivity

### `GET` `/api/classify/policy/\{level\}` 🔒

Get policy for sensitivity level

### `GET` `/api/audit/entries` 🔒

Query audit entries

### `GET` `/api/audit/report` 🔒

Generate compliance report

### `GET` `/api/audit/verify` 🔒

Verify audit log integrity

### `GET` `/api/v1/workspaces` 🔒

GET /api/v1/workspaces

### `POST` `/api/v1/workspaces` 🔒

POST /api/v1/workspaces

### `GET` `/api/v1/workspaces/profiles` 🔒

GET /api/v1/workspaces/profiles

### `GET` `/api/v1/invites` ❔

Route invite acceptance requests

### `GET` `/api/v1/retention/policies` 🔒

GET /api/v1/retention/policies

### `POST` `/api/v1/retention/policies` 🔒

POST /api/v1/retention/policies

### `GET` `/api/v1/retention/expiring` 🔒

GET /api/v1/retention/expiring

### `POST` `/api/v1/classify` 🔒

Route classification requests

### `GET` `/api/v1/audit/entries` 🔒

GET /api/v1/audit/entries

### `GET` `/api/v1/audit/report` 🔒

GET /api/v1/audit/report

### `GET` `/api/v1/audit/verify` 🔒

GET /api/v1/audit/verify

### `POST` `/api/v1/audit/actor` ❔

POST /api/v1/audit/actor

### `POST` `/api/v1/audit/resource` ❔

POST /api/v1/audit/resource

### `GET` `/api/v1/audit/denied` ❔

GET /api/v1/audit/denied

---

## Authentication

Endpoints marked with 🔒 require authentication. Endpoints marked with ❔ have no
security declared in the OpenAPI spec and may still require it.

Include an `Authorization` header with your API token:

```
Authorization: Bearer <your-api-token>
```

Set `ARAGORA_API_TOKEN` environment variable to configure the token.

---

*Generated automatically by `scripts/generate_api_docs.py`*
